// Discord interactions endpoint. Set this as the app's "Interactions Endpoint URL":
//   https://<your site>/api/discord

import { after, NextResponse } from "next/server";
import { DISCORD_APP_ID, EPHEMERAL, InteractionType, ResponseType, verifyDiscordRequest } from "@/lib/discord";
import { getLobby, LOBBY_FRESH_MS, ratePlayers } from "@/lib/lobby";
import { makeTeams, parseGroups, parseNames, type TeamPlayer, type TeamResult } from "@/lib/teams";
import { getDataset, kda, searchPlayers } from "@/lib/stats";
import { siteUrl } from "@/lib/ingest-key";
import { store } from "@/lib/store";
import { champName, getStatic } from "@/lib/ddragon";
import { getRanks } from "@/lib/rank-store";
import { rankLabel, rankScore, rankShort, scoreLabel } from "@/lib/ranks";
import { newCaptains, newDraft, pick, remaining, roster, turn, type Draft } from "@/lib/draft";
import { castVote, createPrediction, leaderboard, renderPrediction } from "@/lib/predictions";
import { discordByPuuid, linkDiscord, mentionedUser, puuidForDiscord } from "@/lib/discord-links";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

const BLUE = 0x4f9dff;
const GOLD = 0xe3b866;
const UNRANKED_DEFAULT = 4 * 400; // Platinum 4, used only when nobody in the list has a rank on file

type Opts = Record<string, string>;
type Balance = "custy" | "solo" | "random";

// A reply: the message to show, and whether only the person who ran the command should see it.
type Reply = { data: object; private?: boolean };
const message = (data: object): Reply => ({ data });
const privateNote = (content: string): Reply => ({ data: { content }, private: true });

const DEFERRED_MESSAGE = 5; // "custy.gg is thinking..."
const DEFERRED_UPDATE = 6; // keep the message as is while we work

export async function POST(req: Request) {
  const body = await req.text();
  if (!verifyDiscordRequest(body, req.headers.get("x-signature-ed25519"), req.headers.get("x-signature-timestamp"))) {
    return new NextResponse("Bad signature", { status: 401 });
  }
  const i = JSON.parse(body);
  if (i.type === InteractionType.PING) return NextResponse.json({ type: ResponseType.PONG });

  // Discord gives us 3 seconds to answer. Loading every game can take longer (especially when the
  // site has been idle), so answer straight away and fill in the real reply once it's ready.
  const isComponent = i.type === InteractionType.COMPONENT;
  after(async () => {
    const started = Date.now();
    const reply = await handle(req, i);
    await deliver(i, reply, isComponent);
    console.log(`[discord] answered in ${Date.now() - started}ms`);
  });
  return NextResponse.json({ type: isComponent ? DEFERRED_UPDATE : DEFERRED_MESSAGE });
}

async function handle(req: Request, i: any): Promise<Reply> {
  try {
    if (i.type === InteractionType.COMMAND) {
      const opts: Opts = Object.fromEntries((i.data.options ?? []).map((o: any) => [o.name, String(o.value)]));
      console.log(`[discord] /${i.data.name} ${JSON.stringify(opts)}`);
      switch (i.data.name) {
        case "custy_teams":
        case "teams":
          return await teams(req, opts);
        case "custy_lobby":
        case "lobby":
          return await lobby();
        case "custy_player":
        case "custy":
          return await lookup(req, opts.player ?? "");
      }
    }
    const cid = i.type === InteractionType.COMPONENT ? String(i.data.custom_id) : "";
    const user: string | null = i.member?.user?.id ?? i.user?.id ?? null;
    if (cid.startsWith("draftstart:")) {
      const saved = await store().getSetting(`teams:${cid.slice(11)}`);
      if (!saved) return privateNote("That team request has expired. Run /custy_teams again.");
      return await startDraft(req, JSON.parse(saved), user);
    }
    if (cid.startsWith("draft:")) return await draftClick(req, cid, user);
    if (cid.startsWith("vote:")) {
      const [, id, side] = cid.split(":");
      if (!user) return privateNote("I couldn't tell who you are.");
      const who = i.member?.nick ?? i.member?.user?.global_name ?? i.member?.user?.username ?? i.user?.global_name ?? i.user?.username ?? "someone";
      const r = await castVote(id, user, String(who).slice(0, 32), side === "1" ? 1 : 0);
      if (typeof r === "string") return privateNote(r);
      return { data: renderPrediction(r) };
    }
    if (cid === "predboard") return await predictionBoard();
    if (cid.startsWith("linkme:")) return await linkMenu(cid.slice(7), user);
    if (cid === "linkpick") {
      if (!user) return privateNote("I couldn't tell who you are.");
      const v = String(i.data.values?.[0] ?? "");
      await linkDiscord(user, v === "none" ? null : v);
      if (v === "none") return { data: { content: "Unlinked. The bot will use your League name again.", components: [] } };
      const d = await getDataset();
      const pl = d.players.find((x) => x.puuid === v);
      return { data: { content: `Linked: you're **${pl ? `${pl.name}#${pl.tag}` : "that player"}**. Team splits will tag you from now on.`, components: [] } };
    }
    if (i.type === InteractionType.COMPONENT && String(i.data.custom_id).startsWith("reroll:")) {
      const saved = await store().getSetting(`teams:${String(i.data.custom_id).slice(7)}`);
      if (!saved) return privateNote("That team request has expired. Run /custy_teams again.");
      return await teams(req, JSON.parse(saved));
    }
    return privateNote("I don't know that command yet.");
  } catch (e) {
    console.log(`[discord] error: ${(e as Error).stack ?? e}`);
    return privateNote(`Something went wrong: ${(e as Error).message}`);
  }
}

/** Sends the finished reply in place of the "thinking" placeholder. */
async function deliver(i: any, reply: Reply, isComponent: boolean) {
  const appId = i.application_id ?? DISCORD_APP_ID;
  const hook = `https://discord.com/api/v10/webhooks/${appId}/${i.token}`;
  const send = async (method: string, url: string, data?: object) => {
    if (process.env.DISCORD_DRY_RUN) return void console.log(`[dry] ${method} ${JSON.stringify(data ?? null)}`);
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: data ? JSON.stringify(data) : undefined,
    });
    if (!res.ok) console.log(`[discord] ${method} reply failed ${res.status}: ${await res.text().catch(() => "")}`);
  };
  if (reply.private) {
    // Notes like "no lobby found" go only to the person who asked.
    if (!isComponent) await send("DELETE", `${hook}/messages/@original`);
    await send("POST", hook, { ...reply.data, flags: EPHEMERAL });
  } else {
    await send("PATCH", `${hook}/messages/@original`, reply.data);
  }
}

// ---------------------------------------------------------------------------

function balanceOf(opts: Opts): Balance {
  const v = opts.balance ?? opts.mode;
  if (v === "solo" || v === "random") return v;
  return "custy";
}

/** The players a team request is about (lobby or list, with add/remove), rated for its balance mode. */
async function gatherPlayers(opts: Opts): Promise<{ players: TeamPlayer[]; source: string } | Reply> {
  let entries: { name: string; puuid?: string }[] = parseNames(opts.players).map((name) => ({ name }));
  let source = "your list";
  if (!entries.length) {
    const lob = await getLobby();
    if (!lob || !lob.members.length || Date.now() - lob.updatedAt > LOBBY_FRESH_MS) {
      return privateNote(
        "I can't see a custom lobby right now. Someone in the lobby needs the custy.gg app running (and updated), " +
          "or list the players: `/custy_teams players: Ringo, Sevi, Vender, ...`",
      );
    }
    entries = lob.members.map((m) => ({ name: m.name, puuid: m.puuid }));
    source = "the custom lobby";
  }
  const lower = (s: string) => s.toLowerCase().replace(/\s+/g, "");
  const removed = new Set(parseNames(opts.remove).map(lower));
  entries = entries.filter((e) => !removed.has(lower(e.name)));
  for (const name of parseNames(opts.add)) if (!entries.some((e) => lower(e.name) === lower(name))) entries.push({ name });

  const balance = balanceOf(opts);
  let players = await ratePlayers(entries);
  if (balance === "solo") {
    // Balance on solo queue rank. Anyone without a rank on file counts as the group's average.
    const scores = players.map((p) => rankScore(p.rank)).filter((x): x is number => x !== null);
    const fill = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : UNRANKED_DEFAULT;
    players = players.map((p) => {
      const sc = rankScore(p.rank);
      return { ...p, rating: sc ?? fill, guessed: sc === null };
    });
  }
  return { players, source };
}

async function teams(req: Request, opts: Opts): Promise<Reply> {
  const got = await gatherPlayers(opts);
  if ("data" in got) return got;
  const { players, source } = got;
  const balance = balanceOf(opts);
  const result = makeTeams(players, {
    mode: balance === "random" ? "random" : "balanced",
    together: parseGroups(opts.together),
    apart: parseGroups(opts.apart),
  });
  if ("error" in result) return privateNote(result.error);

  // Remember the request so the Reroll button can repeat it.
  const id = crypto.randomUUID().slice(0, 12);
  await store().setSetting(`teams:${id}`, JSON.stringify(opts));

  const site = siteUrl(req);
  const tags = await discordByPuuid();
  const tagged = (ps: TeamPlayer[]) => ps.map((p) => (p.puuid ? tags.get(p.puuid) : undefined)).filter(Boolean) as string[];
  const blueTags = tagged(result.blue);
  const redTags = tagged(result.red);
  const data = {
    // The content line is what actually pings people (mentions inside embeds don't).
    content: blueTags.length || redTags.length
      ? `🔵 ${blueTags.map((u) => `<@${u}>`).join(" ") || "—"}\n🔴 ${redTags.map((u) => `<@${u}>`).join(" ") || "—"}`
      : undefined,
    allowed_mentions: { parse: [], users: [...blueTags, ...redTags] },
    embeds: [teamsEmbed(result, balance, source, site, tags)],
    components: [{
      type: 1,
      components: [
        { type: 2, style: 1, label: "Reroll", custom_id: `reroll:${id}`, emoji: { name: "🎲" } },
        { type: 2, style: 2, label: "Captain draft", custom_id: `draftstart:${id}`, emoji: { name: "👑" } },
        { type: 2, style: 2, label: "Link my account", custom_id: `linkme:${id}`, emoji: { name: "🔗" } },
        { type: 2, style: 5, label: "Standings", url: `${site}/` },
      ],
    }],
  };
  const pred = await createPrediction(id, result.blue.map((p) => p.puuid), result.red.map((p) => p.puuid), data);
  return { data: renderPrediction(pred) };
}

function teamsEmbed(r: TeamResult, balance: Balance, source: string, site: string, tags: Map<string, string>) {
  const tagFor = (p: TeamPlayer) => {
    if (balance === "solo") return p.rank?.tier ? rankShort(p.rank) : "unranked";
    return p.known ? String(p.custy ?? p.rating) : "new";
  };
  const line = (p: TeamPlayer) => {
    const user = p.puuid ? tags.get(p.puuid) : undefined;
    const name = user ? `<@${user}> · ${p.name}` : p.known && p.puuid ? `[${p.name}](${site}/players/${encodeURIComponent(p.puuid)})` : p.name;
    return `${name}  \`${tagFor(p)}\``;
  };
  const avgLabel = (avg: number) => (balance === "solo" ? scoreLabel(avg) : String(Math.round(avg)));
  const gap = Math.abs(r.blueAvg - r.redAvg);
  const summary =
    balance === "random"
      ? "Random teams, ratings ignored."
      : balance === "solo"
        ? `Balanced by solo queue rank: ${gap < 100 ? "within one division" : `about ${(gap / 100).toFixed(1)} divisions apart`} on average.`
        : `Balanced by custy rating: ${Math.round(gap)} point${Math.round(gap) === 1 ? "" : "s"} apart on average.`;
  const all = [...r.blue, ...r.red];
  const missing =
    balance === "solo"
      ? all.filter((p) => p.guessed).map((p) => p.name)
      : balance === "custy"
        ? all.filter((p) => !p.known).map((p) => p.name)
        : [];
  const missingNote = missing.length
    ? balance === "solo"
      ? `No rank on file, counted as the group average: ${missing.join(", ")}.`
      : `No custom games yet, counted as 1500: ${missing.join(", ")}.`
    : "";
  const title = { custy: "Teams by custy rating", solo: "Teams by solo queue rank", random: "Random teams" }[balance];
  return {
    title,
    color: balance === "solo" ? BLUE : GOLD,
    fields: [
      { name: `🔵 Blue side${balance === "random" ? "" : `  (avg ${avgLabel(r.blueAvg)})`}`, value: r.blue.map(line).join("\n") || "—", inline: true },
      { name: `🔴 Red side${balance === "random" ? "" : `  (avg ${avgLabel(r.redAvg)})`}`, value: r.red.map(line).join("\n") || "—", inline: true },
    ],
    footer: { text: [summary, `From ${source}.`, missingNote].filter(Boolean).join(" ") },
  };
}

async function lobby(): Promise<Reply> {
  const lob = await getLobby();
  if (!lob || !lob.members.length) return privateNote("No lobby yet. It shows up once someone with the custy.gg app joins a custom lobby.");
  const mins = Math.round((Date.now() - lob.updatedAt) / 60000);
  const stale = Date.now() - lob.updatedAt > LOBBY_FRESH_MS;
  const [players, tags] = await Promise.all([ratePlayers(lob.members.map((m) => ({ name: m.name, puuid: m.puuid }))), discordByPuuid()]);
  return message({
    embeds: [{
      title: `Custom lobby (${players.length})`,
      color: BLUE,
      description: players
        .map((p) => `${p.puuid && tags.get(p.puuid) ? `<@${tags.get(p.puuid)}> · ` : ""}${p.name}  \`${p.known ? p.custy ?? p.rating : "new"}\`  ${p.rank?.tier ? rankLabel(p.rank) : "unranked"}`)
        .join("\n"),
      footer: { text: `${stale ? "Old: " : ""}seen ${mins <= 0 ? "just now" : `${mins} min ago`}${lob.uploader ? ` by ${lob.uploader}'s app` : ""}. Run /custy_teams to split them.` },
    }],
  });
}

async function lookup(req: Request, query: string): Promise<Reply> {
  const [d, st] = await Promise.all([getDataset(), getStatic()]);
  const mentioned = mentionedUser(query);
  const linked = mentioned ? await puuidForDiscord(mentioned) : null;
  if (mentioned && !linked) return privateNote(`<@${mentioned}> hasn't linked a League account yet. They can tap **Link my account** under a team split.`);
  const p = linked ? d.players.find((x) => x.puuid === linked) : searchPlayers(d.players, query)[0];
  if (!p) return privateNote(`Nobody called "${query}" has played a tracked custom game.`);
  const rank = d.players.indexOf(p) + 1;
  const solo = (await getRanks([p.puuid])).get(p.puuid);
  const wr = Math.round((p.wins / p.games) * 100);
  const ratio = p.deaths === 0 ? "Perfect" : `${kda(p.kills, p.deaths, p.assists).toFixed(2)}:1`;
  const top = p.champs.slice(0, 3).map((c) => `${champName(st, c.championId)} (${c.games})`).join(", ");
  const url = `${siteUrl(req)}/players/${encodeURIComponent(p.puuid)}`;
  return message({
    embeds: [{
      title: `${p.name}#${p.tag}`,
      url,
      color: GOLD,
      fields: [
        { name: "Custy rating", value: `${p.rating} (#${rank} of ${d.players.length})`, inline: true },
        { name: "Solo queue", value: solo?.tier ? rankLabel(solo) : "Not on file yet", inline: true },
        { name: "Record", value: `${p.wins}W ${p.games - p.wins}L (${wr}%)`, inline: true },
        { name: "KDA", value: `${ratio}  ${(p.kills / p.games).toFixed(1)} / ${(p.deaths / p.games).toFixed(1)} / ${(p.assists / p.games).toFixed(1)}`, inline: true },
        { name: "MVPs", value: String(p.mvps), inline: true },
        { name: "Most played", value: top || "None", inline: true },
      ],
    }],
  });
}

// --- Captain draft ---------------------------------------------------------

async function startDraft(req: Request, opts: Opts, user: string | null): Promise<Reply> {
  const got = await gatherPlayers({ ...opts, balance: "custy" });
  if ("data" in got) return got;
  if (got.players.length < 4) return privateNote("A captain draft needs at least 4 players.");
  if (got.players.length > 20) return privateNote("That's too many players for a draft (20 at most).");
  const id = crypto.randomUUID().slice(0, 12);
  const d = newDraft(got.players, user);
  await store().setSetting(`draft:${id}`, JSON.stringify(d));
  return { data: draftMessage(id, d, siteUrl(req), await discordByPuuid()) };
}

async function draftClick(req: Request, cid: string, user: string | null): Promise<Reply> {
  const [, id, what] = cid.split(":");
  const raw = await store().getSetting(`draft:${id}`);
  if (!raw) return privateNote("That draft has expired. Run /custy_teams again.");
  let d = JSON.parse(raw) as Draft;
  if (what === "captains") {
    if (d.teams[0].length + d.teams[1].length > 0) return privateNote("Picks have started, so the captains are locked in.");
    d = newCaptains(d);
  } else {
    const r = pick(d, Number(what), user);
    if (!r.ok) return privateNote(r.reason);
  }
  await store().setSetting(`draft:${id}`, JSON.stringify(d));
  const data = draftMessage(id, d, siteUrl(req), await discordByPuuid());
  if (d.done) {
    const pred = await createPrediction(`d${id}`, roster(d, 0).map((p) => p.puuid), roster(d, 1).map((p) => p.puuid), data);
    return { data: renderPrediction(pred) };
  }
  return { data };
}

function draftMessage(id: string, d: Draft, site: string, tags: Map<string, string> = new Map()) {
  const tag = (p: TeamPlayer) => {
    const bits = [p.known ? String(p.custy ?? p.rating) : "new"];
    if (p.rank?.tier) bits.push(rankShort(p.rank));
    return bits.join(" · ");
  };
  const name = (p: TeamPlayer) =>
    p.puuid && tags.get(p.puuid) ? `<@${tags.get(p.puuid)}> · ${p.name}` : p.known && p.puuid ? `[${p.name}](${site}/players/${encodeURIComponent(p.puuid)})` : p.name;
  const side = (s: 0 | 1) => {
    const ps = roster(d, s);
    const avg = Math.round(ps.reduce((a, p) => a + p.rating, 0) / ps.length);
    return {
      name: `${s === 0 ? "🔵 Blue" : "🔴 Red"} (avg ${avg})`,
      value: ps.map((p, k) => `${k === 0 ? "👑 " : ""}${name(p)}  \`${tag(p)}\``).join("\n"),
      inline: true,
    };
  };
  const t = turn(d);
  const left = remaining(d);
  const captain = d.players[d.captains[t]].name;
  const embed = {
    title: d.done ? "Draft done" : "Captain draft",
    color: d.done ? GOLD : t === 0 ? BLUE : 0xe84057,
    description: d.done
      ? "Teams are set. Good luck!"
      : `**${captain}'s pick** ${t === 0 ? "🔵" : "🔴"}  (${d.teams[0].length + d.teams[1].length + 1} of ${d.players.length - 2})\n` +
        "The first person to pick for a captain becomes that captain's picker.",
    fields: [side(0), side(1)],
  };
  const components: object[] = [];
  if (!d.done) {
    const buttons = left.map((i) => ({
      type: 2,
      style: 2,
      label: `${d.players[i].name} · ${tag(d.players[i])}`.slice(0, 80),
      custom_id: `draft:${id}:${i}`,
    }));
    for (let r = 0; r < buttons.length && components.length < 4; r += 5) components.push({ type: 1, components: buttons.slice(r, r + 5) });
    if (d.teams[0].length + d.teams[1].length === 0) {
      components.push({ type: 1, components: [{ type: 2, style: 1, label: "New captains", custom_id: `draft:${id}:captains`, emoji: { name: "🎲" } }] });
    }
  } else {
    components.push({ type: 1, components: [{ type: 2, style: 5, label: "Standings", url: `${site}/` }] });
  }
  return { embeds: [embed], components };
}

async function predictionBoard(): Promise<Reply> {
  const rows = await leaderboard();
  if (!rows.length) return privateNote("No predictions settled yet. Vote under a team split, then play the game.");
  const medal = ["🥇", "🥈", "🥉"];
  return {
    private: true,
    data: {
      embeds: [{
        title: "🏆 Prediction leaderboard",
        color: GOLD,
        description: rows
          .slice(0, 20)
          .map((r, k) => `${medal[k] ?? `${k + 1}.`} **${r.name}** · ${r.points.toLocaleString("en-US")} pts  (${r.right}-${r.wrong})`)
          .join("\n"),
        footer: { text: "Right: 100 × (all votes ÷ votes for the winner). Wrong: 0." },
      }],
    },
  };
}

// --- Linking Discord users to League players ---------------------------------

/** A private dropdown of the players in that split, so you can say which one you are. */
async function linkMenu(teamsId: string, user: string | null): Promise<Reply> {
  if (!user) return privateNote("I couldn't tell who you are.");
  const saved = await store().getSetting(`teams:${teamsId}`);
  if (!saved) return privateNote("That team split has expired. Run /custy_teams again, then tap Link my account.");
  const got = await gatherPlayers(JSON.parse(saved));
  if ("data" in got) return got;
  const [tags, mine] = await Promise.all([discordByPuuid(), puuidForDiscord(user)]);
  const options = got.players
    .filter((p) => p.known && p.puuid)
    .slice(0, 24)
    .map((p) => ({
      label: p.name.slice(0, 100),
      value: p.puuid!,
      description: p.puuid === mine ? "Linked to you" : tags.has(p.puuid!) ? "Linked to someone else (picking it moves it to you)" : undefined,
      default: p.puuid === mine,
    }));
  if (!options.length) return privateNote("Nobody in this split has played a tracked game yet, so there's nothing to link.");
  if (mine) options.push({ label: "Unlink me", value: "none", description: "Go back to showing your League name", default: false });
  return {
    private: true,
    data: {
      content: "Which League account is yours? The bot will tag you in team splits and show you as @you.",
      components: [{ type: 1, components: [{ type: 3, custom_id: "linkpick", placeholder: "Pick your League name", options }] }],
    },
  };
}

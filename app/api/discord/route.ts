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

async function teams(req: Request, opts: Opts): Promise<Reply> {
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
  const data = {
    embeds: [teamsEmbed(result, balance, source, site)],
    components: [{
      type: 1,
      components: [
        { type: 2, style: 1, label: "Reroll", custom_id: `reroll:${id}`, emoji: { name: "🎲" } },
        { type: 2, style: 5, label: "Standings", url: `${site}/` },
      ],
    }],
  };
  return { data };
}

function teamsEmbed(r: TeamResult, balance: Balance, source: string, site: string) {
  const tagFor = (p: TeamPlayer) => {
    if (balance === "solo") return p.rank?.tier ? rankShort(p.rank) : "unranked";
    return p.known ? String(p.custy ?? p.rating) : "new";
  };
  const line = (p: TeamPlayer) => {
    const name = p.known && p.puuid ? `[${p.name}](${site}/players/${encodeURIComponent(p.puuid)})` : p.name;
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
  const players = await ratePlayers(lob.members.map((m) => ({ name: m.name, puuid: m.puuid })));
  return message({
    embeds: [{
      title: `Custom lobby (${players.length})`,
      color: BLUE,
      description: players
        .map((p) => `${p.name}  \`${p.known ? p.custy ?? p.rating : "new"}\`  ${p.rank?.tier ? rankLabel(p.rank) : "unranked"}`)
        .join("\n"),
      footer: { text: `${stale ? "Old: " : ""}seen ${mins <= 0 ? "just now" : `${mins} min ago`}${lob.uploader ? ` by ${lob.uploader}'s app` : ""}. Run /custy_teams to split them.` },
    }],
  });
}

async function lookup(req: Request, query: string): Promise<Reply> {
  const [d, st] = await Promise.all([getDataset(), getStatic()]);
  const p = searchPlayers(d.players, query)[0];
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

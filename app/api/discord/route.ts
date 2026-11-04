// Discord interactions endpoint. Set this as the app's "Interactions Endpoint URL":
//   https://<your site>/api/discord

import { NextResponse } from "next/server";
import { EPHEMERAL, InteractionType, ResponseType, verifyDiscordRequest } from "@/lib/discord";
import { getLobby, LOBBY_FRESH_MS, ratePlayers } from "@/lib/lobby";
import { makeTeams, parseGroups, parseNames, type TeamOptions, type TeamPlayer, type TeamResult } from "@/lib/teams";
import { getDataset, kda, searchPlayers } from "@/lib/stats";
import { siteUrl } from "@/lib/ingest-key";
import { store } from "@/lib/store";
import { champName, getStatic } from "@/lib/ddragon";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BLUE = 0x4f9dff;
const GOLD = 0xe3b866;

type Opts = Record<string, string>;

const message = (data: object) => NextResponse.json({ type: ResponseType.MESSAGE, data });
const privateNote = (content: string) => message({ content, flags: EPHEMERAL });

export async function POST(req: Request) {
  const body = await req.text();
  if (!verifyDiscordRequest(body, req.headers.get("x-signature-ed25519"), req.headers.get("x-signature-timestamp"))) {
    return new NextResponse("Bad signature", { status: 401 });
  }
  const i = JSON.parse(body);
  if (i.type === InteractionType.PING) return NextResponse.json({ type: ResponseType.PONG });

  try {
    if (i.type === InteractionType.COMMAND) {
      const opts: Opts = Object.fromEntries((i.data.options ?? []).map((o: any) => [o.name, String(o.value)]));
      if (i.data.name === "custy_teams") return await teams(req, opts, false);
      if (i.data.name === "lobby") return await lobby();
      if (i.data.name === "custy") return await lookup(req, opts.player ?? "");
    }
    if (i.type === InteractionType.COMPONENT && String(i.data.custom_id).startsWith("reroll:")) {
      const saved = await store().getSetting(`teams:${String(i.data.custom_id).slice(7)}`);
      if (!saved) return privateNote("That team request has expired. Run /custy_teams again.");
      return await teams(req, JSON.parse(saved), true);
    }
    return privateNote("I don't know that command yet.");
  } catch (e) {
    return privateNote(`Something went wrong: ${(e as Error).message}`);
  }
}

// ---------------------------------------------------------------------------

async function teams(req: Request, opts: Opts, reroll: boolean) {
  let entries: { name: string; puuid?: string }[] = parseNames(opts.players).map((name) => ({ name }));
  let source = "your list";
  if (!entries.length) {
    const lob = await getLobby();
    if (!lob || !lob.members.length || Date.now() - lob.updatedAt > LOBBY_FRESH_MS) {
      return privateNote(
        "I can't see a custom lobby right now. Either someone in the lobby needs the custy.gg app running, " +
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

  const players = await ratePlayers(entries);
  const mode: TeamOptions["mode"] = opts.mode === "random" ? "random" : "balanced";
  const result = makeTeams(players, { mode, together: parseGroups(opts.together), apart: parseGroups(opts.apart) });
  if ("error" in result) return privateNote(result.error);

  // Remember the request so the Reroll button can repeat it.
  const id = crypto.randomUUID().slice(0, 12);
  await store().setSetting(`teams:${id}`, JSON.stringify(opts));

  const data = {
    embeds: [teamsEmbed(result, mode, source, siteUrl(req))],
    components: [{
      type: 1,
      components: [
        { type: 2, style: 1, label: "Reroll", custom_id: `reroll:${id}`, emoji: { name: "🎲" } },
        { type: 2, style: 5, label: "Standings", url: `${siteUrl(req)}/` },
      ],
    }],
  };
  return NextResponse.json({ type: reroll ? ResponseType.UPDATE_MESSAGE : ResponseType.MESSAGE, data });
}

function teamsEmbed(r: TeamResult, mode: string, source: string, site: string) {
  const line = (p: TeamPlayer) => {
    const name = p.known && p.puuid ? `[${p.name}](${site}/players/${encodeURIComponent(p.puuid)})` : p.name;
    return `${name}  \`${p.known ? p.rating : "new"}\``;
  };
  const gap = Math.round(Math.abs(r.blueAvg - r.redAvg));
  const newcomers = [...r.blue, ...r.red].filter((p) => !p.known).map((p) => p.name);
  const footer = [
    mode === "balanced" ? `Balanced by custy rating: ${gap} point${gap === 1 ? "" : "s"} apart on average.` : "Random teams.",
    `From ${source}.`,
    newcomers.length ? `No games yet, counted as 1500: ${newcomers.join(", ")}.` : "",
  ].filter(Boolean).join(" ");
  return {
    title: "Teams",
    color: mode === "balanced" ? GOLD : BLUE,
    fields: [
      { name: `🔵 Blue side  (avg ${Math.round(r.blueAvg)})`, value: r.blue.map(line).join("\n") || "—", inline: true },
      { name: `🔴 Red side  (avg ${Math.round(r.redAvg)})`, value: r.red.map(line).join("\n") || "—", inline: true },
    ],
    footer: { text: footer },
  };
}

async function lobby() {
  const lob = await getLobby();
  if (!lob || !lob.members.length) return privateNote("No lobby yet. It shows up once someone with the custy.gg app joins a custom lobby.");
  const mins = Math.round((Date.now() - lob.updatedAt) / 60000);
  const stale = Date.now() - lob.updatedAt > LOBBY_FRESH_MS;
  const players = await ratePlayers(lob.members.map((m) => ({ name: m.name, puuid: m.puuid })));
  return message({
    embeds: [{
      title: `Custom lobby (${players.length})`,
      color: BLUE,
      description: players.map((p) => `${p.name}  \`${p.known ? p.rating : "new"}\``).join("\n"),
      footer: { text: `${stale ? "Old: " : ""}seen ${mins <= 0 ? "just now" : `${mins} min ago`}${lob.uploader ? ` by ${lob.uploader}'s app` : ""}. Run /custy_teams to split them.` },
    }],
  });
}

async function lookup(req: Request, query: string) {
  const [d, st] = await Promise.all([getDataset(), getStatic()]);
  const p = searchPlayers(d.players, query)[0];
  if (!p) return privateNote(`Nobody called "${query}" has played a tracked custom game.`);
  const rank = d.players.indexOf(p) + 1;
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
        { name: "Rating", value: `${p.rating} (#${rank} of ${d.players.length})`, inline: true },
        { name: "Record", value: `${p.wins}W ${p.games - p.wins}L (${wr}%)`, inline: true },
        { name: "KDA", value: `${ratio}  ${(p.kills / p.games).toFixed(1)} / ${(p.deaths / p.games).toFixed(1)} / ${(p.assists / p.games).toFixed(1)}`, inline: true },
        { name: "MVPs", value: String(p.mvps), inline: true },
        { name: "Most played", value: top || "None", inline: true },
      ],
    }],
  });
}

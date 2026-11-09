// Read-only JSON API for AI agents (e.g. a Discord bot) to analyze custom games.
// GET /api/agent lists every endpoint. If AGENT_API_KEY is set in Vercel, requests need
// "Authorization: Bearer <key>" (or ?key=<key>).

import { NextResponse } from "next/server";
import { adjustedWinRate, getDataset, kda, searchPlayers, type Dataset } from "@/lib/stats";
import { champName, getStatic, type Static } from "@/lib/ddragon";
import { store } from "@/lib/store";
import { getRanks } from "@/lib/rank-store";
import { rankLabel } from "@/lib/ranks";
import { leaderboard } from "@/lib/predictions";
import { analyzePlayer, matchDetail } from "@/lib/analysis";
import { siteUrl } from "@/lib/ingest-key";
import { puuidForDiscord } from "@/lib/discord-links";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const r2 = (n: number) => Math.round(n * 100) / 100;
const pct = (n: number) => Math.round(n * 1000) / 10;

const ENDPOINTS = {
  "/api/agent/standings": "Everyone ranked by custy rating (Elo, starts at 1500) with record, KDA, MVPs, streak and solo queue rank.",
  "/api/agent/player?discord=<discord user id>": "Same as below, for whoever has linked that Discord account (people link with /custy_link_account).",
  "/api/agent/player?name=<riot id or name>": "Deep analysis of one player: every stat compared to what the group does in the same roles, strengths and weaknesses, recent form vs before, splits by role/side/game length, champion pool, best and worst teammates, opponents, lane opponents, early game (CS at 10, gold diff at 15, deaths before 15, where and when they die), rating history and their last 15 games.",
  "/api/agent/compare?a=<name>&b=<name>": "Two players side by side, plus their record together and against each other.",
  "/api/agent/matches?limit=10&player=<optional name>": "Recent games (newest first), short form.",
  "/api/agent/match?id=<match id>": "One game in full: every player's stats, MVP, rating changes, and the timeline (gold lead each minute, objectives, every kill) when available.",
  "/api/agent/champions": "Every champion the group has picked or banned: picks, win rate, bans, KDA, damage per minute, best players on it.",
  "/api/agent/champion?name=<champion>": "One champion: stats and everyone who has played it.",
  "/api/agent/duos?limit=20": "Pairs of teammates: games together, win rate, combined KDA, favorite champion combos.",
  "/api/agent/records": "Single-game records (most kills, damage, longest game...) and pentakills.",
  "/api/agent/predictions": "Discord prediction leaderboard (fake points).",
};

export async function GET(req: Request, { params }: { params: Promise<{ path?: string[] }> }) {
  const key = process.env.AGENT_API_KEY;
  if (key) {
    const url = new URL(req.url);
    const given = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? url.searchParams.get("key");
    if (given !== key) return NextResponse.json({ error: "Missing or wrong API key" }, { status: 401 });
  }
  const { path = [] } = await params;
  const q = new URL(req.url).searchParams;
  const site = siteUrl(req);
  try {
    const [d, st] = await Promise.all([getDataset(), getStatic()]);
    const body = await route(path[0] ?? "", q, d, st, site);
    return NextResponse.json(body, { status: "error" in (body as object) ? 404 : 200, headers: { "Cache-Control": "no-store" } });
  } catch (e) {
    console.log(`[agent] /${path.join("/")} failed: ${(e as Error).stack ?? e}`);
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

function findPlayer(d: Dataset, name: string | null) {
  if (!name) return null;
  return searchPlayers(d.players, name)[0] ?? null;
}

const notFound = (what: string, d: Dataset) => ({
  error: `No player matching "${what}".`,
  knownPlayers: d.players.map((p) => `${p.name}#${p.tag}`),
});

async function route(ep: string, q: URLSearchParams, d: Dataset, st: Static, site: string): Promise<object> {
  const champ = (id: number) => champName(st, id);
  switch (ep) {
    case "":
      return {
        about: "custy.gg tracks League of Legends custom games played by a friend group. Stats only cover custom games uploaded by the group's collector app, not ranked or normal games (except the solo queue rank shown).",
        site,
        games: d.counted,
        players: d.players.length,
        notes: [
          "Custy rating is an Elo rating (start 1500, K=32), replayed from the oldest game, so it can shift a little when older games are uploaded late.",
          "Roles are guessed (custom games don't record positions).",
          "Remakes (under 5 minutes) are excluded from stats.",
          "Percent fields are 0-100.",
        ],
        endpoints: ENDPOINTS,
      };

    case "standings": {
      const ranks = await getRanks(d.players.map((p) => p.puuid));
      return {
        players: d.players.map((p, i) => ({
          rank: i + 1, name: `${p.name}#${p.tag}`, rating: p.rating, peak: p.peakRating,
          games: p.games, wins: p.wins, losses: p.games - p.wins, winRate: pct(p.wins / p.games),
          kda: r2(kda(p.kills, p.deaths, p.assists)), mvps: p.mvps,
          streak: p.streak, last10: p.form.map((w) => (w ? "W" : "L")).join(""),
          mainChampions: p.champs.slice(0, 3).map((c) => `${champ(c.championId)} (${c.games})`),
          soloQueue: ranks.get(p.puuid)?.tier ? rankLabel(ranks.get(p.puuid)!) : null,
          lastPlayed: new Date(p.lastPlayed).toISOString().slice(0, 10),
        })),
      };
    }

    case "player": {
      const discordId = q.get("discord");
      const linked = discordId ? await puuidForDiscord(discordId) : null;
      if (discordId && !linked) return { error: `Discord user ${discordId} hasn't linked a League account. Ask them for their League name, or to run /custy_link_account.` };
      const pl = linked ? d.players.find((x) => x.puuid === linked) ?? null : findPlayer(d, q.get("name"));
      if (!pl) return notFound(q.get("name") ?? "", d);
      const [timelines, ranks] = await Promise.all([store().timelines().catch(() => new Map()), getRanks([pl.puuid])]);
      const a = analyzePlayer(d, st, pl, timelines);
      const solo = ranks.get(pl.puuid);
      return { ...a, soloQueue: solo?.tier ? rankLabel(solo) : null, profileUrl: `${site}/players/${encodeURIComponent(pl.puuid)}` };
    }

    case "compare": {
      const a = findPlayer(d, q.get("a"));
      const b = findPlayer(d, q.get("b"));
      if (!a) return notFound(q.get("a") ?? "", d);
      if (!b) return notFound(q.get("b") ?? "", d);
      const mate = a.mates.find((x) => x.puuid === b.puuid);
      const card = (p: typeof a) => ({
        name: `${p.name}#${p.tag}`, rating: p.rating, standing: d.players.indexOf(p) + 1, games: p.games,
        winRate: pct(p.wins / p.games), kda: r2(kda(p.kills, p.deaths, p.assists)),
        csPerMin: r2(p.cs / Math.max(1, p.minutes)), damagePerMin: Math.round(p.damage / Math.max(1, p.minutes)),
        killParticipation: pct(p.kpSum / p.games), damageShare: pct(p.damageShareSum / p.games),
        visionPerMin: r2(p.vision / Math.max(1, p.minutes)), mvps: p.mvps,
        mainChampions: p.champs.slice(0, 5).map((c) => ({ champion: champ(c.championId), games: c.games, winRate: pct(c.wins / c.games) })),
      });
      return {
        a: card(a), b: card(b),
        together: mate ? { games: mate.with.games, wins: mate.with.wins, winRate: mate.with.games ? pct(mate.with.wins / mate.with.games) : null } : { games: 0 },
        against: mate ? { games: mate.against.games, [`${a.name}Wins`]: mate.against.wins, [`${b.name}Wins`]: mate.against.games - mate.against.wins } : { games: 0 },
      };
    }

    case "matches": {
      const limit = Math.min(50, Math.max(1, Number(q.get("limit")) || 10));
      const who = q.get("player") ? findPlayer(d, q.get("player")) : null;
      if (q.get("player") && !who) return notFound(q.get("player")!, d);
      const ms = d.matches.filter((m) => !m.remake && (!who || m.players.some((p) => p.puuid === who.puuid))).slice(0, limit);
      return {
        matches: ms.map((m) => ({
          matchId: m.id, date: new Date(m.playedAt).toISOString().slice(0, 16), length: `${Math.floor(m.duration / 60)}m`,
          winner: m.teams.find((t) => t.win)?.teamId === 100 ? "blue" : "red",
          mvp: m.players.find((p) => p.puuid === d.mvpOf.get(m.id))?.name ?? null,
          blue: m.players.filter((p) => p.teamId === 100).map((p) => `${p.name} (${champ(p.championId)} ${p.kills}/${p.deaths}/${p.assists})`),
          red: m.players.filter((p) => p.teamId === 200).map((p) => `${p.name} (${champ(p.championId)} ${p.kills}/${p.deaths}/${p.assists})`),
        })),
      };
    }

    case "match": {
      const id = q.get("id") ?? "";
      const m = d.matches.find((x) => x.id === id) ?? (id === "latest" ? d.matches.find((x) => !x.remake) : undefined);
      if (!m) return { error: `No game with id "${id}". Use /api/agent/matches to find ids, or id=latest.` };
      return matchDetail(d, st, m, await store().getTimeline(m.id).catch(() => null));
    }

    case "champions":
      return {
        champions: d.champions
          .filter((c) => c.games > 0 || c.bans > 0)
          .map((c) => ({
            champion: champ(c.championId), picks: c.games, wins: c.wins,
            winRate: c.games ? pct(c.wins / c.games) : null, bans: c.bans,
            kda: c.games ? r2(kda(c.kills, c.deaths, c.assists)) : null,
            damagePerMin: c.games ? Math.round(c.damage / Math.max(1, c.minutes)) : null,
            bestPlayers: c.players.slice(0, 3).map((p) => `${p.name} ${p.wins}-${p.games - p.wins}`),
          })),
      };

    case "champion": {
      const name = (q.get("name") ?? "").toLowerCase().replace(/[^a-z]/g, "");
      const c = d.champions.find((x) => champ(x.championId).toLowerCase().replace(/[^a-z]/g, "") === name);
      if (!c) return { error: `Nobody has played or banned "${q.get("name")}".` };
      return {
        champion: champ(c.championId), picks: c.games, wins: c.wins, winRate: c.games ? pct(c.wins / c.games) : null, bans: c.bans,
        kda: c.games ? r2(kda(c.kills, c.deaths, c.assists)) : null,
        csPerMin: c.games ? r2(c.cs / Math.max(1, c.minutes)) : null,
        damagePerMin: c.games ? Math.round(c.damage / Math.max(1, c.minutes)) : null,
        multikills: { doubles: c.doubles, triples: c.triples, quadras: c.quadras, pentas: c.pentas },
        players: c.players.map((p) => ({ name: p.name, games: p.games, wins: p.wins, winRate: pct(p.wins / p.games) })),
      };
    }

    case "duos": {
      const limit = Math.min(100, Math.max(1, Number(q.get("limit")) || 20));
      return {
        duos: [...d.duos]
          .filter((x) => x.games >= 2)
          .sort((x, y) => adjustedWinRate(y.wins, y.games) - adjustedWinRate(x.wins, x.games))
          .slice(0, limit)
          .map((x) => ({
            players: `${x.a.name} + ${x.b.name}`, games: x.games, wins: x.wins, winRate: pct(x.wins / x.games),
            combinedKda: r2(kda(x.kills, x.deaths, x.assists)), mvps: x.mvps, ratingChangeEach: x.ratingSum,
            favoriteCombos: x.combos.slice(0, 3).map((c) => `${champ(c.champs[0])} + ${champ(c.champs[1])} (${c.wins}-${c.games - c.wins})`),
          })),
        note: "Sorted by win rate adjusted for sample size; pairs with 2+ games together.",
      };
    }

    case "records":
      return {
        records: d.records.map((r) => ({ record: r.label, value: r.display, player: r.name, champion: champ(r.championId), date: new Date(r.playedAt).toISOString().slice(0, 10), matchId: r.matchId })),
        pentakills: d.matches.flatMap((m) => (m.remake ? [] : m.players.filter((p) => p.pentaKills > 0).map((p) => ({ player: p.name, champion: champ(p.championId), date: new Date(m.playedAt).toISOString().slice(0, 10), matchId: m.id })))),
      };

    case "predictions":
      return { leaderboard: (await leaderboard()).map((r) => ({ name: r.name, points: r.points, right: r.right, wrong: r.wrong })), note: "Discord users' predictions on custom games; fake points." };

    default:
      return { error: `Unknown endpoint "${ep}".`, endpoints: ENDPOINTS };
  }
}

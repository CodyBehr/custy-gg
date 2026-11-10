// Every number on the site is computed here from the stored matches.
// A friend group plays at most a few thousand games, so it's fine to
// crunch everything on each request.

import "server-only";
import { cache } from "react";
import type { Match, MatchPlayer, Role } from "./types";
import { NORMALIZER_VERSION, renormalizeAll, store } from "./store";
import { linkAccounts } from "./player-links";

export const START_RATING = 1500;
const K = 32;

export interface ChampLine {
  championId: number;
  games: number;
  wins: number;
  kills: number;
  deaths: number;
  assists: number;
  cs: number;
  minutes: number;
  damage: number;
  gold: number;
  vision: number;
  doubles: number;
  triples: number;
  quadras: number;
  pentas: number;
}

export interface Mate {
  puuid: string;
  name: string;
  with: { games: number; wins: number };
  against: { games: number; wins: number };
}

export interface PlayerSummary {
  puuid: string;
  name: string;
  tag: string;
  profileIcon: number;
  games: number;
  wins: number;
  kills: number;
  deaths: number;
  assists: number;
  cs: number;
  minutes: number;
  damage: number;
  gold: number;
  vision: number;
  kpSum: number;            // sum of kill participation, divide by games
  damageShareSum: number;
  otherAccounts: string[];  // Riot IDs of linked accounts (lib/player-links.ts)
  pentas: number;
  quadras: number;
  triples: number;
  doubles: number;
  largestSpree: number;
  mvps: number;
  rating: number;
  peakRating: number;
  ratingHistory: { matchId: string; rating: number; at: number }[];
  form: boolean[];          // most recent first, up to 10
  streak: number;           // +3 = three wins in a row, -2 = two losses
  lastPlayed: number;
  platform: string;         // server of their latest game, e.g. NA1
  champs: ChampLine[];      // most played first
  roles: Partial<Record<Role, { games: number; wins: number }>>;
  mates: Mate[];
}

export interface ChampSummary extends ChampLine {
  bans: number;
  players: { puuid: string; name: string; games: number; wins: number }[];
}

export interface RecordLine {
  label: string;
  value: number;
  display: string;
  puuid: string;
  name: string;
  championId: number;
  matchId: string;
  playedAt: number;
}

export interface Dataset {
  matches: Match[];                   // newest first, remakes included
  counted: number;                    // matches that count toward stats
  players: PlayerSummary[];           // by rating, highest first
  byPuuid: Map<string, PlayerSummary>;
  champions: ChampSummary[];          // most picked first
  records: RecordLine[];
  mvpOf: Map<string, string>;         // matchId -> puuid of the MVP
  ratingDelta: Map<string, number>;   // `${matchId}:${puuid}` -> rating change
  scores: Map<string, number>;        // `${matchId}:${puuid}` -> performance score (0-10)
  duos: DuoSummary[];                 // every pair of teammates, most games first
}

/** Two players on the same team, any roles. `a` and `b` are ordered by puuid. */
export interface DuoSummary {
  key: string;                        // `${a}+${b}`
  a: { puuid: string; name: string; tag: string; profileIcon: number };
  b: { puuid: string; name: string; tag: string; profileIcon: number };
  games: number;
  wins: number;
  kills: number;                      // the two players combined
  deaths: number;
  assists: number;
  damage: number;
  minutes: number;
  scoreSum: number;                   // sum of both players' performance scores
  ratingSum: number;                  // rating gained or lost together (per player)
  mvps: number;                       // games where one of them was MVP
  streak: number;                     // +3 = won their last three together
  lastPlayed: number;
  combos: { champs: [number, number]; games: number; wins: number }[];  // a's champ, b's champ
  matchIds: string[];                 // newest first
}

/** Win rate pulled toward 50% for small samples, so 1-0 doesn't top the chart. */
export const adjustedWinRate = (wins: number, games: number) => (wins + 2) / (games + 4);

export const kda = (k: number, d: number, a: number) => (d === 0 ? k + a : (k + a) / d);

/** A 0-10 performance score, loosely in the spirit of op.gg's OP Score. */
function performance(p: MatchPlayer, m: Match): number {
  const team = m.players.filter((x) => x.teamId === p.teamId);
  const teamKills = Math.max(1, team.reduce((a, x) => a + x.kills, 0));
  const teamDmg = Math.max(1, team.reduce((a, x) => a + x.damageToChampions, 0));
  const minutes = Math.max(1, m.duration / 60);
  const kp = (p.kills + p.assists) / teamKills;
  const dmgShare = p.damageToChampions / teamDmg;
  const ratio = Math.min(kda(p.kills, p.deaths, p.assists), 12) / 12;
  const vision = Math.min(p.visionScore / minutes / 2.5, 1);
  const raw = 3.2 * ratio + 2.6 * kp + 2.6 * dmgShare * 2.5 + 0.8 * vision + (p.win ? 0.8 : 0);
  return Math.max(0, Math.min(10, raw));
}

function blankPlayer(p: MatchPlayer): PlayerSummary {
  return {
    puuid: p.puuid, name: p.name, tag: p.tag, profileIcon: p.profileIcon,
    games: 0, wins: 0, kills: 0, deaths: 0, assists: 0, cs: 0, minutes: 0, damage: 0, gold: 0, vision: 0,
    kpSum: 0, damageShareSum: 0, otherAccounts: [], pentas: 0, quadras: 0, triples: 0, doubles: 0, largestSpree: 0, mvps: 0,
    rating: START_RATING, peakRating: START_RATING, ratingHistory: [],
    form: [], streak: 0, lastPlayed: 0, platform: "NA1", champs: [], roles: {}, mates: [],
  };
}

function blankChamp(championId: number): ChampLine {
  return { championId, games: 0, wins: 0, kills: 0, deaths: 0, assists: 0, cs: 0, minutes: 0, damage: 0, gold: 0, vision: 0, doubles: 0, triples: 0, quadras: 0, pentas: 0 };
}

function addLine(line: ChampLine, p: MatchPlayer, minutes: number) {
  line.games++;
  if (p.win) line.wins++;
  line.kills += p.kills;
  line.deaths += p.deaths;
  line.assists += p.assists;
  line.cs += p.cs;
  line.minutes += minutes;
  line.damage += p.damageToChampions;
  line.gold += p.gold;
  line.vision += p.visionScore;
  line.doubles += p.doubleKills;
  line.triples += p.tripleKills;
  line.quadras += p.quadraKills;
  line.pentas += p.pentaKills;
}

export function buildDataset(raw: Match[]): Dataset {
  const linked = linkAccounts(raw);
  const matches = [...linked.matches].sort((a, b) => b.playedAt - a.playedAt);
  const oldestFirst = [...matches].reverse().filter((m) => !m.remake);

  const byPuuid = new Map<string, PlayerSummary>();
  const champLines = new Map<string, ChampLine>();          // `${puuid}:${champ}`
  const champs = new Map<number, ChampSummary>();
  const mates = new Map<string, Mate>();                    // `${puuid}>${other}`
  const mvpOf = new Map<string, string>();
  const ratingDelta = new Map<string, number>();
  const scores = new Map<string, number>();
  const records: Record<string, RecordLine> = {};
  const duoMap = new Map<string, DuoSummary>();

  const record = (key: string, label: string, value: number, display: string, p: MatchPlayer, m: Match, lowerIsBetter = false) => {
    const cur = records[key];
    if (!cur || (lowerIsBetter ? value < cur.value : value > cur.value)) {
      records[key] = { label, value, display, puuid: p.puuid, name: p.name, championId: p.championId, matchId: m.id, playedAt: m.playedAt };
    }
  };

  for (const m of oldestFirst) {
    const humans = m.players.filter((p) => !p.isBot);
    const minutes = Math.max(1, m.duration / 60);

    // Ratings: compare team averages, everyone on a team moves by the same amount.
    const avg = (team: number) => {
      const t = m.players.filter((p) => p.teamId === team);
      return t.reduce((a, p) => a + (p.isBot ? START_RATING : byPuuid.get(p.puuid)?.rating ?? START_RATING), 0) / Math.max(1, t.length);
    };
    const blue = avg(100);
    const red = avg(200);
    const expectedBlue = 1 / (1 + Math.pow(10, (red - blue) / 400));

    let best: { puuid: string; score: number } | null = null;
    for (const p of m.players) {
      const score = performance(p, m);
      scores.set(`${m.id}:${p.puuid}`, score);
      if (!p.isBot && (!best || score > best.score)) best = { puuid: p.puuid, score };
    }
    if (best && humans.length >= 2) mvpOf.set(m.id, best.puuid);

    for (const p of humans) {
      let s = byPuuid.get(p.puuid);
      if (!s) {
        s = blankPlayer(p);
        byPuuid.set(p.puuid, s);
      }
      // Keep the newest name and icon (people rename).
      s.name = p.name;
      s.tag = p.tag;
      if (p.profileIcon) s.profileIcon = p.profileIcon;

      const team = m.players.filter((x) => x.teamId === p.teamId);
      const teamKills = Math.max(1, team.reduce((a, x) => a + x.kills, 0));
      const teamDmg = Math.max(1, team.reduce((a, x) => a + x.damageToChampions, 0));

      s.games++;
      if (p.win) s.wins++;
      s.kills += p.kills;
      s.deaths += p.deaths;
      s.assists += p.assists;
      s.cs += p.cs;
      s.minutes += minutes;
      s.damage += p.damageToChampions;
      s.gold += p.gold;
      s.vision += p.visionScore;
      s.kpSum += (p.kills + p.assists) / teamKills;
      s.damageShareSum += p.damageToChampions / teamDmg;
      s.pentas += p.pentaKills;
      s.quadras += p.quadraKills;
      s.triples += p.tripleKills;
      s.doubles += p.doubleKills;
      s.largestSpree = Math.max(s.largestSpree, p.largestKillingSpree);
      if (mvpOf.get(m.id) === p.puuid) s.mvps++;
      s.lastPlayed = m.playedAt;
      s.platform = m.platformId || s.platform;
      s.streak = p.win ? (s.streak > 0 ? s.streak + 1 : 1) : s.streak < 0 ? s.streak - 1 : -1;
      s.form.unshift(p.win);
      if (s.form.length > 10) s.form.pop();
      if (p.role) {
        const r = (s.roles[p.role] ??= { games: 0, wins: 0 });
        r.games++;
        if (p.win) r.wins++;
      }

      const expected = p.teamId === 100 ? expectedBlue : 1 - expectedBlue;
      const delta = Math.round(K * ((p.win ? 1 : 0) - expected));
      s.rating += delta;
      s.peakRating = Math.max(s.peakRating, s.rating);
      s.ratingHistory.push({ matchId: m.id, rating: s.rating, at: m.playedAt });
      ratingDelta.set(`${m.id}:${p.puuid}`, delta);

      const lineKey = `${p.puuid}:${p.championId}`;
      const line = champLines.get(lineKey) ?? blankChamp(p.championId);
      addLine(line, p, minutes);
      champLines.set(lineKey, line);

      for (const o of humans) {
        if (o.puuid === p.puuid) continue;
        const key = `${p.puuid}>${o.puuid}`;
        const mate = mates.get(key) ?? { puuid: o.puuid, name: o.name, with: { games: 0, wins: 0 }, against: { games: 0, wins: 0 } };
        mate.name = o.name;
        const bucket = o.teamId === p.teamId ? mate.with : mate.against;
        bucket.games++;
        if (p.win) bucket.wins++;
        mates.set(key, mate);
      }

      // Single-game records
      record("kills", "Most kills", p.kills, `${p.kills}`, p, m);
      record("deaths", "Most deaths", p.deaths, `${p.deaths}`, p, m);
      record("assists", "Most assists", p.assists, `${p.assists}`, p, m);
      record("damage", "Most damage to champions", p.damageToChampions, p.damageToChampions.toLocaleString("en-US"), p, m);
      record("taken", "Most damage taken", p.damageTaken, p.damageTaken.toLocaleString("en-US"), p, m);
      record("gold", "Most gold", p.gold, p.gold.toLocaleString("en-US"), p, m);
      if (p.role !== "SUPPORT" && p.role !== "JUNGLE") record("cspm", "Best CS per minute", p.cs / minutes, (p.cs / minutes).toFixed(1), p, m);
      record("vision", "Highest vision score", p.visionScore, `${p.visionScore}`, p, m);
      record("spree", "Longest killing spree", p.largestKillingSpree, `${p.largestKillingSpree}`, p, m);
      record("cc", "Most crowd control", p.ccTime, `${p.ccTime}s`, p, m);
      if (p.deaths === 0) record("deathless", "Most kills without dying", p.kills + p.assists, `${p.kills}/0/${p.assists}`, p, m);
    }

    // Every pair of teammates
    for (const team of [100, 200]) {
      const side = humans.filter((x) => x.teamId === team).sort((x, y) => (x.puuid < y.puuid ? -1 : 1));
      const won = side[0]?.win ?? false;
      const delta = side[0] ? ratingDelta.get(`${m.id}:${side[0].puuid}`) ?? 0 : 0;
      const mvp = mvpOf.get(m.id);
      for (let i = 0; i < side.length; i++) {
        for (let j = i + 1; j < side.length; j++) {
          const x = side[i], y = side[j];
          const key = `${x.puuid}+${y.puuid}`;
          let duo = duoMap.get(key);
          if (!duo) {
            duo = {
              key, games: 0, wins: 0, kills: 0, deaths: 0, assists: 0, damage: 0, minutes: 0,
              scoreSum: 0, ratingSum: 0, mvps: 0, streak: 0, lastPlayed: 0, matchIds: [], combos: [],
              a: { puuid: x.puuid, name: x.name, tag: x.tag, profileIcon: x.profileIcon },
              b: { puuid: y.puuid, name: y.name, tag: y.tag, profileIcon: y.profileIcon },
            };
            duoMap.set(key, duo);
          }
          duo.a = { puuid: x.puuid, name: x.name, tag: x.tag, profileIcon: x.profileIcon || duo.a.profileIcon };
          duo.b = { puuid: y.puuid, name: y.name, tag: y.tag, profileIcon: y.profileIcon || duo.b.profileIcon };
          duo.games++;
          if (won) duo.wins++;
          duo.kills += x.kills + y.kills;
          duo.deaths += x.deaths + y.deaths;
          duo.assists += x.assists + y.assists;
          duo.damage += x.damageToChampions + y.damageToChampions;
          duo.minutes += minutes;
          duo.scoreSum += (scores.get(`${m.id}:${x.puuid}`) ?? 0) + (scores.get(`${m.id}:${y.puuid}`) ?? 0);
          duo.ratingSum += delta;
          if (mvp === x.puuid || mvp === y.puuid) duo.mvps++;
          duo.streak = won ? (duo.streak > 0 ? duo.streak + 1 : 1) : duo.streak < 0 ? duo.streak - 1 : -1;
          duo.lastPlayed = m.playedAt;
          duo.matchIds.unshift(m.id);
          const combo = duo.combos.find((c) => c.champs[0] === x.championId && c.champs[1] === y.championId);
          if (combo) {
            combo.games++;
            if (won) combo.wins++;
          } else duo.combos.push({ champs: [x.championId, y.championId], games: 1, wins: won ? 1 : 0 });
        }
      }
    }

    // Champion picks (humans only) and bans
    for (const p of humans) {
      const c = champs.get(p.championId) ?? { ...blankChamp(p.championId), bans: 0, players: [] };
      addLine(c, p, minutes);
      const who = c.players.find((x) => x.puuid === p.puuid);
      if (who) {
        who.games++;
        if (p.win) who.wins++;
        who.name = p.name;
      } else c.players.push({ puuid: p.puuid, name: p.name, games: 1, wins: p.win ? 1 : 0 });
      champs.set(p.championId, c);
    }
    for (const t of m.teams) for (const ban of t.bans) {
      const c = champs.get(ban) ?? { ...blankChamp(ban), bans: 0, players: [] };
      c.bans++;
      champs.set(ban, c);
    }

    // Game-level records
    const winner = humans.find((p) => p.win);
    if (winner) {
      record("long", "Longest game", m.duration, clock(m.duration), winner, m);
      record("short", "Fastest win", m.duration, clock(m.duration), winner, m, true);
    }
  }

  for (const [key, line] of champLines) {
    const puuid = key.slice(0, key.lastIndexOf(":"));
    byPuuid.get(puuid)?.champs.push(line);
  }
  for (const [key, mate] of mates) {
    const puuid = key.slice(0, key.indexOf(">"));
    byPuuid.get(puuid)?.mates.push(mate);
  }
  for (const p of byPuuid.values()) {
    p.otherAccounts = [...(linked.otherNames.get(p.puuid) ?? [])].filter((n) => n !== `${p.name}#${p.tag}`);
    p.champs.sort((a, b) => b.games - a.games || b.wins - a.wins);
    p.mates.sort((a, b) => b.with.games + b.against.games - (a.with.games + a.against.games));
  }

  const players = [...byPuuid.values()].sort((a, b) => b.rating - a.rating || b.games - a.games);
  const champions = [...champs.values()].sort((a, b) => b.games - a.games || b.bans - a.bans);
  for (const c of champions) c.players.sort((a, b) => b.games - a.games);

  const order = ["kills", "deathless", "assists", "damage", "gold", "cspm", "vision", "spree", "cc", "taken", "deaths", "long", "short"];
  return {
    matches,
    counted: oldestFirst.length,
    players,
    byPuuid,
    champions,
    records: order.map((k) => records[k]).filter(Boolean),
    mvpOf,
    ratingDelta,
    scores,
    duos: [...duoMap.values()]
      .map((d) => ({ ...d, combos: d.combos.sort((x, y) => y.games - x.games || y.wins - x.wins) }))
      .sort((x, y) => y.games - x.games || y.wins - x.wins),
  };
}

let renormalized = false;
export const getDataset = cache(async () => {
  let matches = await store().all();
  // After the site's game reader improves (e.g. better role detection), rebuild stored games once.
  if (!renormalized && matches.some((m) => (m.v ?? 0) < NORMALIZER_VERSION)) {
    renormalized = true; // once per server instance, even if a game can't be re-read
    const r = await renormalizeAll();
    console.log(`[renormalize] updated ${r.updated}, failed ${r.failed}`);
    matches = await store().all();
  }
  return buildDataset(matches);
});

export function clock(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Players whose Riot ID matches a search, best matches first. */
export function searchPlayers(players: PlayerSummary[], query: string): PlayerSummary[] {
  const norm = (t: string) => t.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, "");
  const q = norm(query.replace(/^#/, ""));
  if (!q) return [];
  const [qName, qTag] = q.includes("#") ? q.split("#", 2) : [q, ""];
  const scoreId = (rawName: string, rawTag: string) => {
    const name = norm(rawName);
    const tag = norm(rawTag);
    if (qTag) return name === qName && tag.startsWith(qTag) ? 100 : 0;
    if (name === q) return 90;
    if (name.startsWith(q)) return 70;
    if (name.includes(q)) return 50;
    if (tag === q) return 30;
    return 0;
  };
  const scored = players.map((p) => {
    let score = scoreId(p.name, p.tag);
    for (const other of p.otherAccounts) {
      const [n, t = ""] = other.split("#");
      score = Math.max(score, scoreId(n, t) - 5);
    }
    return { p, score };
  });
  return scored.filter((x) => x.score > 0).sort((a, b) => b.score - a.score || b.p.games - a.p.games).map((x) => x.p);
}

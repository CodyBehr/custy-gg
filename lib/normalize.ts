// Turns a game as the League client returns it (/lol-match-history/v1/games/{id})
// into the smaller Match shape the website uses. Also accepts Riot API
// Match-v5 JSON, in case you later pull tournament-code games too.

import type { Match, MatchPlayer, MatchTeam, Role } from "./types";

export const NORMALIZER_VERSION = 1;
const REMAKE_SECONDS = 300;
const SMITE = 11;

type Json = Record<string, any>;

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : Number(v) || 0);

function isBotPuuid(puuid: unknown): boolean {
  if (typeof puuid !== "string" || !puuid) return true;
  return /^[0-]+$/.test(puuid) || puuid.toUpperCase() === "BOT";
}

export function isCustomGame(raw: Json): boolean {
  if (raw?.info) return num(raw.info.queueId) === 0 || raw.info.gameType === "CUSTOM_GAME";
  return raw?.gameType === "CUSTOM_GAME" || (raw?.queueId === 0 && raw?.gameType !== "MATCHED_GAME");
}

export function normalize(raw: Json): Match {
  if (!raw || typeof raw !== "object") throw new Error("Game data is empty");
  return raw.info ? fromMatchV5(raw) : fromLcu(raw);
}

// ---------------------------------------------------------------------------
// League client format
// ---------------------------------------------------------------------------

function fromLcu(g: Json): Match {
  const participants: Json[] = g.participants ?? [];
  const identities = new Map<number, Json>();
  for (const ident of g.participantIdentities ?? []) identities.set(num(ident.participantId), ident.player ?? {});
  if (!participants.length) throw new Error("Game has no players");

  const teamWin = new Map<number, boolean>();
  for (const t of g.teams ?? []) teamWin.set(num(t.teamId), t.win === "Win" || t.win === true);

  const players: MatchPlayer[] = participants.map((p) => {
    const s: Json = p.stats ?? {};
    const who = identities.get(num(p.participantId)) ?? {};
    const teamId = (num(p.teamId) === 200 ? 200 : 100) as 100 | 200;
    const bot = isBotPuuid(who.puuid);
    const championId = num(p.championId);
    return {
      puuid: bot ? `bot:${championId}:${teamId}` : String(who.puuid),
      name: bot ? "Bot" : String(who.gameName || who.summonerName || "Unknown"),
      tag: bot ? "" : String(who.tagLine || ""),
      isBot: bot,
      profileIcon: num(who.profileIcon),
      teamId,
      win: typeof s.win === "boolean" ? s.win : teamWin.get(teamId) ?? false,
      championId,
      champLevel: num(s.champLevel),
      role: "",
      spells: [num(p.spell1Id), num(p.spell2Id)],
      items: [0, 1, 2, 3, 4, 5, 6].map((i) => num(s[`item${i}`])),
      keystone: num(s.perk0),
      primaryStyle: num(s.perkPrimaryStyle),
      subStyle: num(s.perkSubStyle),
      kills: num(s.kills),
      deaths: num(s.deaths),
      assists: num(s.assists),
      cs: num(s.totalMinionsKilled) + num(s.neutralMinionsKilled),
      gold: num(s.goldEarned),
      damageToChampions: num(s.totalDamageDealtToChampions),
      damageTaken: num(s.totalDamageTaken),
      damageMitigated: num(s.damageSelfMitigated),
      damageToObjectives: num(s.damageDealtToObjectives),
      damageToTurrets: num(s.damageDealtToTurrets),
      healing: num(s.totalHeal),
      visionScore: num(s.visionScore),
      wardsPlaced: num(s.wardsPlaced),
      wardsKilled: num(s.wardsKilled),
      controlWards: num(s.visionWardsBoughtInGame),
      ccTime: num(s.timeCCingOthers),
      turretKills: num(s.turretKills),
      doubleKills: num(s.doubleKills),
      tripleKills: num(s.tripleKills),
      quadraKills: num(s.quadraKills),
      pentaKills: num(s.pentaKills),
      largestMultiKill: num(s.largestMultiKill),
      largestKillingSpree: num(s.largestKillingSpree),
      firstBlood: Boolean(s.firstBloodKill),
      _lane: String(p.timeline?.lane ?? ""),
      _laneRole: String(p.timeline?.role ?? ""),
      _jungleCs: num(s.neutralMinionsKilled),
    } as MatchPlayer & Json;
  });

  const teams: MatchTeam[] = [100, 200].map((teamId) => {
    const t: Json = (g.teams ?? []).find((x: Json) => num(x.teamId) === teamId) ?? {};
    const mine = players.filter((p) => p.teamId === teamId);
    return {
      teamId: teamId as 100 | 200,
      win: teamWin.get(teamId) ?? mine.some((p) => p.win),
      kills: mine.reduce((a, p) => a + p.kills, 0),
      gold: mine.reduce((a, p) => a + p.gold, 0),
      bans: (t.bans ?? []).map((b: Json) => num(b.championId)).filter((id: number) => id > 0),
      towers: num(t.towerKills),
      inhibitors: num(t.inhibitorKills),
      dragons: num(t.dragonKills),
      barons: num(t.baronKills),
      heralds: num(t.riftHeraldKills),
      firstBlood: Boolean(t.firstBlood),
      firstTower: Boolean(t.firstTower),
    };
  });

  const platformId = String(g.platformId || "NA1");
  const match: Match = {
    v: NORMALIZER_VERSION,
    id: `${platformId}-${g.gameId}`,
    gameId: num(g.gameId),
    platformId,
    playedAt: num(g.gameCreation) || Date.parse(g.gameCreationDate) || Date.now(),
    duration: seconds(g.gameDuration),
    mode: String(g.gameMode || "CLASSIC"),
    mapId: num(g.mapId),
    version: String(g.gameVersion || ""),
    remake: false,
    teams,
    players,
  };
  finish(match);
  return match;
}

// ---------------------------------------------------------------------------
// Riot API Match-v5 format (tournament-code games)
// ---------------------------------------------------------------------------

const V5_ROLE: Record<string, Role> = { TOP: "TOP", JUNGLE: "JUNGLE", MIDDLE: "MID", BOTTOM: "BOT", UTILITY: "SUPPORT" };

function fromMatchV5(m: Json): Match {
  const info = m.info;
  const players: MatchPlayer[] = (info.participants ?? []).map((p: Json) => {
    const bot = isBotPuuid(p.puuid);
    const teamId = (num(p.teamId) === 200 ? 200 : 100) as 100 | 200;
    const perks = p.perks?.styles ?? [];
    return {
      puuid: bot ? `bot:${p.championId}:${teamId}` : p.puuid,
      name: bot ? "Bot" : p.riotIdGameName || p.summonerName || "Unknown",
      tag: bot ? "" : p.riotIdTagline || "",
      isBot: bot,
      profileIcon: num(p.profileIcon),
      teamId,
      win: Boolean(p.win),
      championId: num(p.championId),
      champLevel: num(p.champLevel),
      role: V5_ROLE[p.teamPosition] ?? "",
      spells: [num(p.summoner1Id), num(p.summoner2Id)],
      items: [0, 1, 2, 3, 4, 5, 6].map((i) => num(p[`item${i}`])),
      keystone: num(perks[0]?.selections?.[0]?.perk),
      primaryStyle: num(perks[0]?.style),
      subStyle: num(perks[1]?.style),
      kills: num(p.kills),
      deaths: num(p.deaths),
      assists: num(p.assists),
      cs: num(p.totalMinionsKilled) + num(p.neutralMinionsKilled),
      gold: num(p.goldEarned),
      damageToChampions: num(p.totalDamageDealtToChampions),
      damageTaken: num(p.totalDamageTaken),
      damageMitigated: num(p.damageSelfMitigated),
      damageToObjectives: num(p.damageDealtToObjectives),
      damageToTurrets: num(p.damageDealtToBuildings),
      healing: num(p.totalHeal),
      visionScore: num(p.visionScore),
      wardsPlaced: num(p.wardsPlaced),
      wardsKilled: num(p.wardsKilled),
      controlWards: num(p.visionWardsBoughtInGame),
      ccTime: num(p.timeCCingOthers),
      turretKills: num(p.turretKills),
      doubleKills: num(p.doubleKills),
      tripleKills: num(p.tripleKills),
      quadraKills: num(p.quadraKills),
      pentaKills: num(p.pentaKills),
      largestMultiKill: num(p.largestMultiKill),
      largestKillingSpree: num(p.largestKillingSpree),
      firstBlood: Boolean(p.firstBloodKill),
    };
  });
  const teams: MatchTeam[] = [100, 200].map((teamId) => {
    const t: Json = (info.teams ?? []).find((x: Json) => num(x.teamId) === teamId) ?? {};
    const o = t.objectives ?? {};
    const mine = players.filter((p) => p.teamId === teamId);
    return {
      teamId: teamId as 100 | 200,
      win: Boolean(t.win),
      kills: mine.reduce((a, p) => a + p.kills, 0),
      gold: mine.reduce((a, p) => a + p.gold, 0),
      bans: (t.bans ?? []).map((b: Json) => num(b.championId)).filter((id: number) => id > 0),
      towers: num(o.tower?.kills),
      inhibitors: num(o.inhibitor?.kills),
      dragons: num(o.dragon?.kills),
      barons: num(o.baron?.kills),
      heralds: num(o.riftHerald?.kills),
      firstBlood: Boolean(o.champion?.first),
      firstTower: Boolean(o.tower?.first),
    };
  });
  const platformId = String(info.platformId || "NA1");
  const match: Match = {
    v: NORMALIZER_VERSION,
    id: `${platformId}-${info.gameId}`,
    gameId: num(info.gameId),
    platformId,
    playedAt: num(info.gameStartTimestamp || info.gameCreation),
    duration: seconds(info.gameDuration),
    mode: String(info.gameMode || "CLASSIC"),
    mapId: num(info.mapId),
    version: String(info.gameVersion || ""),
    remake: false,
    teams,
    players,
  };
  finish(match, true);
  return match;
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function seconds(d: unknown): number {
  const n = num(d);
  return n > 20000 ? Math.round(n / 1000) : n; // very old payloads used milliseconds
}

function finish(match: Match, rolesKnown = false) {
  match.remake = match.duration > 0 && match.duration < REMAKE_SECONDS;
  if (!rolesKnown && match.mapId === 11 && match.mode === "CLASSIC") {
    for (const teamId of [100, 200]) guessRoles(match.players.filter((p) => p.teamId === teamId) as (MatchPlayer & Json)[]);
  }
  for (const p of match.players as Json[]) {
    delete p._lane;
    delete p._laneRole;
    delete p._jungleCs;
  }
}

/** Custom games don't store positions, so infer them from smite, lane and CS. */
function guessRoles(team: (MatchPlayer & Json)[]) {
  const smiters = team.filter((p) => p.spells.includes(SMITE)).sort((a, b) => b._jungleCs - a._jungleCs);
  if (smiters[0]) smiters[0].role = "JUNGLE";

  const open = () => team.filter((p) => !p.role);
  for (const p of open()) {
    const lane = p._lane.toUpperCase();
    if (lane === "TOP") p.role = "TOP";
    else if (lane === "MIDDLE" || lane === "MID") p.role = "MID";
    else if (lane === "JUNGLE" && !smiters.length) p.role = "JUNGLE";
  }
  const bottom = open().filter((p) => ["BOTTOM", "BOT"].includes(p._lane.toUpperCase()));
  for (const p of bottom) {
    if (p._laneRole === "DUO_SUPPORT") p.role = "SUPPORT";
    else if (p._laneRole === "DUO_CARRY") p.role = "BOT";
  }
  const bottomLeft = bottom.filter((p) => !p.role).sort((a, b) => b.cs - a.cs);
  if (bottomLeft.length === 2) {
    bottomLeft[0].role = "BOT";
    bottomLeft[1].role = "SUPPORT";
  }

  // Drop duplicate guesses, then if exactly one player and one role remain, pair them.
  const seen = new Set<Role>();
  for (const p of team) {
    if (p.role && seen.has(p.role)) p.role = "";
    else if (p.role) seen.add(p.role);
  }
  const missing = (["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"] as Role[]).filter((r) => !seen.has(r));
  const left = open();
  if (left.length === 1 && missing.length === 1) left[0].role = missing[0];
  else if (left.length && left.length === missing.length && missing.includes("SUPPORT")) {
    // Lowest CS of the rest is almost always the support.
    const sorted = [...left].sort((a, b) => a.cs - b.cs);
    sorted[0].role = "SUPPORT";
    const rest = missing.filter((r) => r !== "SUPPORT");
    const rem = open();
    if (rem.length === 1 && rest.length === 1) rem[0].role = rest[0];
  }
}

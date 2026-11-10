// Deep, per-player analysis of custom games for the agent API (/api/agent).
// Everything is compared against what the group usually does in the same roles,
// so a support isn't judged on damage like a mid laner.

import "server-only";
import { adjustedWinRate, kda, type Dataset, type PlayerSummary } from "./stats";
import { champName, type Static } from "./ddragon";
import { PLAYER_LINKS } from "./player-links";
import type { TimelineSummary } from "./timeline";
import type { Match, MatchPlayer, Role } from "./types";

const main = (p: string) => PLAYER_LINKS[p] ?? p;
const r1 = (n: number) => Math.round(n * 10) / 10;
const r2 = (n: number) => Math.round(n * 100) / 100;
const pct = (n: number) => Math.round(n * 1000) / 10; // 0.523 -> 52.3
const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

/** One player's numbers from one game, normalized per minute where it makes sense. */
interface GameLine {
  m: Match;
  p: MatchPlayer;
  minutes: number;
  metrics: Record<Metric, number>;
}

type Metric =
  | "kills" | "deaths" | "assists" | "kda" | "killParticipation" | "damageShare" | "goldShare"
  | "csPerMin" | "damagePerMin" | "goldPerMin" | "visionPerMin" | "damageTakenPerMin"
  | "objectiveDamagePerMin" | "ccSecondsPerMin" | "controlWards";

const METRICS: { key: Metric; label: string; higherIsBetter: boolean }[] = [
  { key: "kda", label: "KDA", higherIsBetter: true },
  { key: "kills", label: "kills per game", higherIsBetter: true },
  { key: "deaths", label: "deaths per game", higherIsBetter: false },
  { key: "assists", label: "assists per game", higherIsBetter: true },
  { key: "killParticipation", label: "kill participation", higherIsBetter: true },
  { key: "damageShare", label: "share of team damage", higherIsBetter: true },
  { key: "goldShare", label: "share of team gold", higherIsBetter: true },
  { key: "csPerMin", label: "CS per minute", higherIsBetter: true },
  { key: "damagePerMin", label: "damage to champions per minute", higherIsBetter: true },
  { key: "goldPerMin", label: "gold per minute", higherIsBetter: true },
  { key: "visionPerMin", label: "vision score per minute", higherIsBetter: true },
  { key: "damageTakenPerMin", label: "damage taken per minute", higherIsBetter: true },
  { key: "objectiveDamagePerMin", label: "objective damage per minute", higherIsBetter: true },
  { key: "ccSecondsPerMin", label: "crowd control per minute", higherIsBetter: true },
  { key: "controlWards", label: "control wards per game", higherIsBetter: true },
];

function lineFor(m: Match, p: MatchPlayer): GameLine {
  const minutes = Math.max(1, m.duration / 60);
  const team = m.players.filter((x) => x.teamId === p.teamId);
  const teamKills = Math.max(1, team.reduce((a, x) => a + x.kills, 0));
  const teamDmg = Math.max(1, team.reduce((a, x) => a + x.damageToChampions, 0));
  const teamGold = Math.max(1, team.reduce((a, x) => a + x.gold, 0));
  return {
    m, p, minutes,
    metrics: {
      kills: p.kills, deaths: p.deaths, assists: p.assists,
      kda: kda(p.kills, p.deaths, p.assists),
      killParticipation: (p.kills + p.assists) / teamKills,
      damageShare: p.damageToChampions / teamDmg,
      goldShare: p.gold / teamGold,
      csPerMin: p.cs / minutes,
      damagePerMin: p.damageToChampions / minutes,
      goldPerMin: p.gold / minutes,
      visionPerMin: p.visionScore / minutes,
      damageTakenPerMin: p.damageTaken / minutes,
      objectiveDamagePerMin: p.damageToObjectives / minutes,
      ccSecondsPerMin: p.ccTime / minutes,
      controlWards: p.controlWards,
    },
  };
}

/** Every human player-game that counts toward stats. */
function allLines(d: Dataset): GameLine[] {
  return d.matches.filter((m) => !m.remake).flatMap((m) => m.players.filter((p) => !p.isBot).map((p) => lineFor(m, p)));
}

/** Average of each metric; KDA is total (kills + assists) / total deaths, like everywhere else on the site. */
function averages(ls: GameLine[]): Record<Metric, number> {
  const out = Object.fromEntries(METRICS.map(({ key }) => [key, avg(ls.map((l) => l.metrics[key]))])) as Record<Metric, number>;
  out.kda = kda(ls.reduce((a, l) => a + l.p.kills, 0), ls.reduce((a, l) => a + l.p.deaths, 0), ls.reduce((a, l) => a + l.p.assists, 0));
  return out;
}

/** What the group averages in each role (and overall, under ""). */
function baselines(lines: GameLine[]) {
  const by = new Map<Role, GameLine[]>();
  for (const l of lines) {
    by.set(l.p.role, [...(by.get(l.p.role) ?? []), l]);
    if (l.p.role) by.set("", [...(by.get("") ?? []), l]);
  }
  const out = new Map<Role, Record<Metric, number>>();
  for (const [role, ls] of by) out.set(role, averages(ls));
  return out;
}

// --- Map regions (approximate) for "where do you die" ----------------------

type Region = "own base" | "enemy base" | "top lane" | "mid lane" | "bot lane" | "river" | "own jungle" | "enemy jungle";

function region(x: number, y: number, teamId: 100 | 200): Region {
  const s = x + y;
  const blueSide = s < 14900;
  const own = (teamId === 100) === blueSide;
  if (s < 5200) return teamId === 100 ? "own base" : "enemy base";
  if (s > 24600) return teamId === 200 ? "own base" : "enemy base";
  if ((x < 2300 && y > 2300) || (y > 12600 && x < 12600)) return "top lane";
  if ((y < 2300 && x > 2300) || (x > 12600 && y < 12600)) return "bot lane";
  if (Math.abs(x - y) < 1700) return "mid lane";
  if (Math.abs(s - 14900) < 1700) return "river";
  return own ? "own jungle" : "enemy jungle";
}

// --- The analysis -----------------------------------------------------------

export function analyzePlayer(d: Dataset, st: Static, pl: PlayerSummary, timelines: Map<string, TimelineSummary>) {
  const lines = allLines(d);
  const base = baselines(lines);
  const mine = lines.filter((l) => l.p.puuid === pl.puuid).sort((a, b) => b.m.playedAt - a.m.playedAt);
  if (!mine.length) return null;
  const champ = (id: number) => champName(st, id);
  const delta = (l: GameLine) => d.ratingDelta.get(`${l.m.id}:${l.p.puuid}`) ?? 0;
  const score = (l: GameLine) => d.scores.get(`${l.m.id}:${l.p.puuid}`) ?? 0;

  // Averages vs. what the group does in the same roles.
  const roleMix = new Map<Role, number>();
  for (const l of mine) roleMix.set(l.p.role, (roleMix.get(l.p.role) ?? 0) + 1);
  const expected = (k: Metric) => {
    let sum = 0;
    for (const [role, n] of roleMix) sum += (base.get(role)?.[k] ?? base.get("")?.[k] ?? 0) * n;
    return sum / mine.length;
  };
  // Rank among regulars (5+ games) on each metric.
  const regulars = d.players.filter((p) => p.games >= 5);
  const perPlayer = new Map(regulars.map((p) => [p.puuid, lines.filter((l) => l.p.puuid === p.puuid)]));
  const myAvg = averages(mine);
  const theirAvg = [...perPlayer.values()].map(averages);
  const metrics = METRICS.map(({ key, label, higherIsBetter }) => {
    const value = myAvg[key];
    const exp = expected(key);
    const vs = exp ? value / exp - 1 : 0;
    const values = theirAvg.map((a) => a[key]);
    const better = values.filter((v) => (higherIsBetter ? v > value : v < value)).length;
    return {
      metric: key, label,
      value: key.endsWith("Share") || key === "killParticipation" ? pct(value) : r2(value),
      unit: key.endsWith("Share") || key === "killParticipation" ? "%" : "",
      groupExpectedForTheirRoles: key.endsWith("Share") || key === "killParticipation" ? pct(exp) : r2(exp),
      vsExpectedPercent: Math.round(vs * 100),
      verdict: Math.abs(vs) < 0.08 ? "about average" : (vs > 0) === higherIsBetter ? "better than average" : "worse than average",
      rankAmongRegulars: pl.games >= 5 && values.length ? `${better + 1} of ${values.length}` : null,
    };
  });

  // Recent form vs. the rest.
  const recent = mine.slice(0, 10);
  const earlier = mine.slice(10);
  const summarize = (ls: GameLine[]) =>
    ls.length
      ? {
          games: ls.length,
          winRate: pct(ls.filter((l) => l.p.win).length / ls.length),
          kda: r2(kda(ls.reduce((a, l) => a + l.p.kills, 0), ls.reduce((a, l) => a + l.p.deaths, 0), ls.reduce((a, l) => a + l.p.assists, 0))),
          damagePerMin: Math.round(avg(ls.map((l) => l.metrics.damagePerMin))),
          csPerMin: r1(avg(ls.map((l) => l.metrics.csPerMin))),
          deathsPerGame: r1(avg(ls.map((l) => l.p.deaths))),
          ratingChange: ls.reduce((a, l) => a + delta(l), 0),
          avgPerformanceScore: r1(avg(ls.map(score))),
        }
      : null;

  // Splits.
  const split = <K extends string>(key: (l: GameLine) => K | null) => {
    const m = new Map<K, GameLine[]>();
    for (const l of mine) {
      const k = key(l);
      if (k !== null) m.set(k, [...(m.get(k) ?? []), l]);
    }
    return Object.fromEntries([...m].map(([k, ls]) => [k, summarize(ls)]));
  };
  const byRole = split((l) => l.p.role || "unknown");
  const bySide = split((l) => (l.p.teamId === 100 ? "blue" : "red"));
  const byLength = split((l) => (l.minutes < 25 ? "under 25 min" : l.minutes <= 35 ? "25 to 35 min" : "over 35 min"));

  // Champions.
  const champs = [...new Set(mine.map((l) => l.p.championId))]
    .map((id) => {
      const ls = mine.filter((l) => l.p.championId === id);
      return { champion: champ(id), ...summarize(ls)! };
    })
    .sort((a, b) => b.games - a.games);

  // Teammates and opponents.
  const mates = pl.mates
    .filter((x) => x.with.games >= 2)
    .map((x) => ({ name: x.name, games: x.with.games, wins: x.with.wins, winRate: pct(x.with.wins / x.with.games), adjusted: adjustedWinRate(x.with.wins, x.with.games) }))
    .sort((a, b) => b.adjusted - a.adjusted);
  const opps = pl.mates
    .filter((x) => x.against.games >= 2)
    .map((x) => ({ name: x.name, games: x.against.games, winsAgainst: x.against.wins, winRateAgainst: pct(x.against.wins / x.against.games), adjusted: adjustedWinRate(x.against.wins, x.against.games) }))
    .sort((a, b) => b.adjusted - a.adjusted);
  const clean = <T extends { adjusted: number }>(xs: T[]) => xs.map(({ adjusted: _a, ...rest }) => rest);

  // Lane opponents (same role on the other team).
  const laneOpp = new Map<string, { name: string; games: number; wins: number }>();
  for (const l of mine) {
    if (!l.p.role) continue;
    const o = l.m.players.find((x) => x.teamId !== l.p.teamId && x.role === l.p.role && !x.isBot);
    if (!o) continue;
    const e = laneOpp.get(o.puuid) ?? { name: o.name, games: 0, wins: 0 };
    e.games++;
    if (l.p.win) e.wins++;
    laneOpp.set(o.puuid, e);
  }

  // Early game and deaths, from timelines.
  const tlGames = mine.map((l) => ({ l, tl: timelines.get(l.m.id) })).filter((x): x is { l: GameLine; tl: TimelineSummary } => Boolean(x.tl));
  let early: object | null = null;
  if (tlGames.length) {
    const at = (arr: number[], min: number) => arr[Math.min(min, arr.length - 1)] ?? 0;
    const rows = tlGames.map(({ l, tl }) => {
      const me = tl.players.find((x) => main(x.puuid) === l.p.puuid);
      const opp = l.p.role ? l.m.players.find((x) => x.teamId !== l.p.teamId && x.role === l.p.role) : undefined;
      const oppT = opp ? tl.players.find((x) => main(x.puuid) === opp.puuid) : undefined;
      const teamDiff15 = (at(tl.blueGold, 15) - at(tl.redGold, 15)) * (l.p.teamId === 100 ? 1 : -1);
      const deaths = tl.kills.filter((k) => main(k.victim) === l.p.puuid);
      const involved = tl.kills.filter((k) => (k.killer && main(k.killer) === l.p.puuid) || k.assists.some((a) => main(a) === l.p.puuid));
      return {
        l, long: tl.minutes >= 15,
        cs10: me ? at(me.cs, 10) : null,
        gold15: me ? at(me.gold, 15) : null,
        laneDiff15: me && oppT ? at(me.gold, 15) - at(oppT.gold, 15) : null,
        teamDiff15,
        deathsBefore15: deaths.filter((k) => k.t < 900).length,
        takedownsBefore15: involved.filter((k) => k.t < 900).length,
        firstDeath: deaths.length ? Math.min(...deaths.map((k) => k.t)) : null,
        deaths: deaths.map((k) => ({ ...k, teamId: l.p.teamId })),
      };
    });
    const ok = rows.filter((r) => r.long);
    const nums = (xs: (number | null)[]) => xs.filter((x): x is number => x !== null);
    const ahead = ok.filter((r) => r.teamDiff15 > 1000);
    const behind = ok.filter((r) => r.teamDiff15 < -1000);
    const laneAhead = ok.filter((r) => r.laneDiff15 !== null && r.laneDiff15 > 300);
    const zones = new Map<Region, number>();
    const deathTimes = { "0-10 min": 0, "10-20 min": 0, "20-30 min": 0, "30+ min": 0 };
    for (const r of rows)
      for (const k of r.deaths) {
        if (k.x || k.y) zones.set(region(k.x, k.y, k.teamId), (zones.get(region(k.x, k.y, k.teamId)) ?? 0) + 1);
        const bucket = k.t < 600 ? "0-10 min" : k.t < 1200 ? "10-20 min" : k.t < 1800 ? "20-30 min" : "30+ min";
        deathTimes[bucket]++;
      }
    const totalDeaths = [...zones.values()].reduce((a, b) => a + b, 0) || 1;
    // Group average CS at 10 and lane diff for context.
    const groupCs10 = avg(
      [...timelines.values()].flatMap((tl) => tl.players.filter((x) => !x.puuid.startsWith("bot:")).map((x) => at(x.cs, 10))),
    );
    early = {
      gamesWithTimeline: tlGames.length,
      avgCsAt10: r1(avg(nums(rows.map((r) => r.cs10)))),
      groupAvgCsAt10: r1(groupCs10),
      avgGoldAt15: Math.round(avg(nums(ok.map((r) => r.gold15)))),
      avgLaneGoldDiffAt15: Math.round(avg(nums(ok.map((r) => r.laneDiff15)))),
      laneAheadAt15Percent: ok.length ? pct(laneAhead.length / ok.length) : null,
      avgDeathsBefore15: r1(avg(rows.map((r) => r.deathsBefore15))),
      avgTakedownsBefore15: r1(avg(rows.map((r) => r.takedownsBefore15))),
      avgFirstDeathMinute: r1(avg(nums(rows.map((r) => r.firstDeath))) / 60),
      teamAheadAt15: { games: ahead.length, winRate: ahead.length ? pct(ahead.filter((r) => r.l.p.win).length / ahead.length) : null },
      teamBehindAt15: { games: behind.length, comebackRate: behind.length ? pct(behind.filter((r) => r.l.p.win).length / behind.length) : null },
      whereTheyDie: Object.fromEntries([...zones].sort((a, b) => b[1] - a[1]).map(([z, n]) => [z, `${n} (${Math.round((n / totalDeaths) * 100)}%)`])),
      whenTheyDie: deathTimes,
      note: "Map regions are approximate. Lane opponent = same role on the other team.",
    };
  }

  // Plain-language highlights the agent can lead with.
  const strengths = metrics.filter((m) => m.verdict === "better than average" && Math.abs(m.vsExpectedPercent) >= 12).sort((a, b) => Math.abs(b.vsExpectedPercent) - Math.abs(a.vsExpectedPercent)).slice(0, 4).map((m) => `${m.label}: ${m.value}${m.unit} vs ${m.groupExpectedForTheirRoles}${m.unit} expected for their roles (${m.vsExpectedPercent > 0 ? "+" : ""}${m.vsExpectedPercent}%)`);
  const weaknesses = metrics.filter((m) => m.verdict === "worse than average" && Math.abs(m.vsExpectedPercent) >= 12).sort((a, b) => Math.abs(b.vsExpectedPercent) - Math.abs(a.vsExpectedPercent)).slice(0, 4).map((m) => `${m.label}: ${m.value}${m.unit} vs ${m.groupExpectedForTheirRoles}${m.unit} expected for their roles (${m.vsExpectedPercent > 0 ? "+" : ""}${m.vsExpectedPercent}%)`);
  const champNotes = champs.filter((c) => c.games >= 3).flatMap((c) =>
    c.winRate >= 65 ? [`Strong on ${c.champion}: ${c.winRate}% over ${c.games} games`] : c.winRate <= 35 ? [`Struggles on ${c.champion}: ${c.winRate}% over ${c.games} games`] : [],
  );

  const rank = d.players.indexOf(pl) + 1;
  return {
    player: { name: `${pl.name}#${pl.tag}`, otherAccounts: pl.otherAccounts, profile: `/players/${encodeURIComponent(pl.puuid)}` },
    summary: {
      rating: pl.rating, standing: `${rank} of ${d.players.length}`, peakRating: pl.peakRating,
      games: pl.games, wins: pl.wins, losses: pl.games - pl.wins, winRate: pct(pl.wins / pl.games),
      kda: r2(kda(pl.kills, pl.deaths, pl.assists)),
      avgKills: r1(pl.kills / pl.games), avgDeaths: r1(pl.deaths / pl.games), avgAssists: r1(pl.assists / pl.games),
      mvps: pl.mvps, mvpRate: pct(pl.mvps / pl.games),
      avgPerformanceScore: r1(avg(mine.map(score))), performanceScoreNote: "0-10 per game; blends KDA, kill participation, damage share and vision",
      streak: pl.streak > 0 ? `${pl.streak} wins in a row` : pl.streak < 0 ? `${-pl.streak} losses in a row` : "none",
      multikills: { doubles: pl.doubles, triples: pl.triples, quadras: pl.quadras, pentas: pl.pentas },
      lastPlayed: new Date(pl.lastPlayed).toISOString(),
    },
    highlights: { strengths, weaknesses, champions: champNotes },
    metricsVsGroup: metrics,
    form: { last10: summarize(recent), before: summarize(earlier) },
    ratingHistory: pl.ratingHistory.slice(-30).map((h) => ({ rating: h.rating, at: new Date(h.at).toISOString().slice(0, 10) })),
    byRole, bySide, byGameLength: byLength,
    champions: champs,
    teammates: { best: clean(mates.slice(0, 5)), worst: clean(mates.slice(-5).reverse()), note: "Win rate when on the same team, 2+ games" },
    opponents: { beatsMost: clean(opps.slice(0, 5)), losesToMost: clean(opps.slice(-5).reverse()), note: "Their win rate in games against this person, 2+ games" },
    laneOpponents: [...laneOpp.values()].filter((x) => x.games >= 2).map((x) => ({ ...x, winRate: pct(x.wins / x.games) })).sort((a, b) => b.games - a.games).slice(0, 8),
    earlyGame: early,
    recentGames: mine.slice(0, 15).map((l) => ({
      matchId: l.m.id,
      date: new Date(l.m.playedAt).toISOString().slice(0, 16),
      result: l.p.win ? "win" : "loss",
      champion: champ(l.p.championId),
      role: l.p.role || "unknown",
      kda: `${l.p.kills}/${l.p.deaths}/${l.p.assists}`,
      killParticipation: pct(l.metrics.killParticipation),
      damage: l.p.damageToChampions, damageShare: pct(l.metrics.damageShare),
      cs: l.p.cs, csPerMin: r1(l.metrics.csPerMin), vision: l.p.visionScore,
      gameLength: `${Math.floor(l.m.duration / 60)}m`,
      ratingChange: delta(l), performanceScore: r1(score(l)), mvp: d.mvpOf.get(l.m.id) === l.p.puuid,
    })),
  };
}

/** One game in full, with the timeline when there is one. */
export function matchDetail(d: Dataset, st: Static, m: Match, tl: TimelineSummary | null) {
  const champ = (id: number) => champName(st, id);
  const nameOf = new Map(m.players.map((p) => [p.puuid, p.isBot ? `${champ(p.championId)} bot` : p.name]));
  const who = (puuid: string | null) => (puuid ? nameOf.get(main(puuid)) ?? "unknown" : "minions/tower");
  const mvp = d.mvpOf.get(m.id);
  return {
    matchId: m.id, date: new Date(m.playedAt).toISOString(), length: `${Math.floor(m.duration / 60)}m ${m.duration % 60}s`,
    remake: m.remake, winner: m.teams.find((t) => t.win)?.teamId === 100 ? "blue" : "red",
    teams: m.teams.map((t) => ({
      side: t.teamId === 100 ? "blue" : "red", win: t.win, kills: t.kills, gold: t.gold, towers: t.towers,
      dragons: t.dragons, barons: t.barons, heralds: t.heralds, bans: t.bans.map(champ),
      players: m.players.filter((p) => p.teamId === t.teamId).map((p) => ({
        name: nameOf.get(p.puuid), champion: champ(p.championId), role: p.role || "unknown", level: p.champLevel,
        kda: `${p.kills}/${p.deaths}/${p.assists}`, cs: p.cs, gold: p.gold, damage: p.damageToChampions,
        damageTaken: p.damageTaken, vision: p.visionScore, controlWards: p.controlWards, ccSeconds: p.ccTime,
        ratingChange: d.ratingDelta.get(`${m.id}:${p.puuid}`) ?? null,
        performanceScore: d.scores.has(`${m.id}:${p.puuid}`) ? r1(d.scores.get(`${m.id}:${p.puuid}`)!) : null,
        mvp: mvp === p.puuid,
      })),
    })),
    timeline: tl
      ? {
          blueGoldLeadByMinute: tl.blueGold.map((b, i) => b - tl.redGold[i]),
          objectives: tl.objectives.map((o) => ({ minute: r1(o.t / 60), side: o.teamId === 100 ? "blue" : "red", objective: o.kind.toLowerCase(), detail: o.sub ?? null })),
          kills: tl.kills.map((k) => ({ minute: r1(k.t / 60), killer: who(k.killer), victim: who(k.victim), assists: k.assists.map((a) => who(a)) })),
          csAndGoldAt10And15: tl.players.filter((x) => !x.puuid.startsWith("bot:")).map((x) => ({
            name: who(x.puuid), csAt10: x.cs[Math.min(10, x.cs.length - 1)], goldAt10: x.gold[Math.min(10, x.gold.length - 1)], goldAt15: x.gold[Math.min(15, x.gold.length - 1)],
          })),
        }
      : null,
  };
}

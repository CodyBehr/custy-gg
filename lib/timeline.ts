// Game timelines from the League client (/lol-match-history/v1/game-timelines/{gameId}):
// a snapshot of every player each minute plus every kill, objective and item purchase.
// We keep the raw timeline and a compact summary the site reads.

export interface TimelinePlayer {
  puuid: string;          // as uploaded (before account merges)
  teamId: 100 | 200;
  gold: number[];         // total gold earned at each minute
  cs: number[];           // lane + jungle minions at each minute
  xp: number[];
  level: number[];
}

export interface TimelineKill {
  t: number;              // seconds
  killer: string | null;  // puuid, null for executions (tower, minions)
  victim: string;
  assists: string[];
  x: number;
  y: number;
}

export interface TimelineObjective {
  t: number;
  teamId: 100 | 200;      // team that took it
  kind: "DRAGON" | "BARON" | "HERALD" | "GRUBS" | "ATAKHAN" | "TOWER" | "INHIBITOR";
  sub?: string;           // dragon type, tower lane
}

export interface TimelineSummary {
  version: 1;
  minutes: number;                    // number of frames after the start
  blueGold: number[];                 // team total gold at each minute
  redGold: number[];
  players: TimelinePlayer[];
  kills: TimelineKill[];
  objectives: TimelineObjective[];
  items: Record<string, [number, number][]>; // puuid -> [seconds, itemId] purchases (undone ones removed)
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : Number(v) || 0);

/**
 * Builds the summary. `game` is the raw match from the client, used to map
 * timeline participant numbers to players and teams.
 */
export function summarizeTimeline(raw: any, game: any): TimelineSummary | null {
  const frames: any[] = Array.isArray(raw?.frames) ? raw.frames : [];
  if (frames.length < 2) return null;

  const who = new Map<number, { puuid: string; teamId: 100 | 200 }>();
  const idents = new Map<number, any>();
  for (const i of game?.participantIdentities ?? []) idents.set(num(i.participantId), i.player ?? {});
  for (const p of game?.participants ?? []) {
    const pid = num(p.participantId);
    const teamId: 100 | 200 = num(p.teamId) === 200 ? 200 : 100;
    let puuid = String(idents.get(pid)?.puuid ?? p.puuid ?? "");
    // Bots have an empty or all-zero puuid; name them the way normalize() does.
    if (!puuid || /^[0-]+$/.test(puuid) || puuid.toUpperCase() === "BOT") puuid = `bot:${num(p.championId)}:${teamId}`;
    who.set(pid, { puuid, teamId });
  }
  if (!who.size) return null;

  const pf = (frame: any, pid: number) => {
    const set = frame?.participantFrames;
    if (!set) return null;
    if (Array.isArray(set)) return set.find((x: any) => num(x?.participantId) === pid) ?? null;
    return set[String(pid)] ?? null;
  };

  const players: TimelinePlayer[] = [...who.entries()].map(([pid, w]) => ({
    puuid: w.puuid,
    teamId: w.teamId,
    gold: frames.map((f) => num(pf(f, pid)?.totalGold)),
    cs: frames.map((f) => num(pf(f, pid)?.minionsKilled) + num(pf(f, pid)?.jungleMinionsKilled)),
    xp: frames.map((f) => num(pf(f, pid)?.xp)),
    level: frames.map((f) => num(pf(f, pid)?.level)),
  }));
  const teamGold = (team: 100 | 200) =>
    frames.map((_, i) => players.filter((p) => p.teamId === team).reduce((a, p) => a + p.gold[i], 0));

  const kills: TimelineKill[] = [];
  const objectives: TimelineObjective[] = [];
  const items: Record<string, [number, number][]> = {};
  const puuidOf = (pid: unknown) => who.get(num(pid))?.puuid ?? null;
  const teamOf = (pid: unknown) => who.get(num(pid))?.teamId;

  for (const f of frames) {
    for (const e of Array.isArray(f?.events) ? f.events : []) {
      const t = Math.round(num(e.timestamp) / 1000);
      const type = String(e.type ?? "");
      if (type === "CHAMPION_KILL") {
        const victim = puuidOf(e.victimId);
        if (!victim) continue;
        kills.push({
          t, victim, killer: puuidOf(e.killerId),
          assists: (Array.isArray(e.assistingParticipantIds) ? e.assistingParticipantIds : []).map(puuidOf).filter(Boolean) as string[],
          x: num(e.position?.x), y: num(e.position?.y),
        });
      } else if (type === "ELITE_MONSTER_KILL") {
        const team = teamOf(e.killerId) ?? (num(e.killerTeamId) === 200 ? 200 : num(e.killerTeamId) === 100 ? 100 : undefined);
        if (!team) continue;
        const m = String(e.monsterType ?? "").toUpperCase();
        const kind = m.includes("DRAGON") ? "DRAGON" : m.includes("BARON") ? "BARON" : m.includes("RIFTHERALD") ? "HERALD"
          : m.includes("HORDE") || m.includes("GRUB") ? "GRUBS" : m.includes("ATAKHAN") ? "ATAKHAN" : null;
        if (kind) objectives.push({ t, teamId: team, kind, sub: e.monsterSubType ? String(e.monsterSubType) : undefined });
      } else if (type === "BUILDING_KILL") {
        // teamId on a building kill is the team that LOST the building.
        const lost = num(e.teamId);
        const team: 100 | 200 = lost === 100 ? 200 : lost === 200 ? 100 : (teamOf(e.killerId) ?? 100);
        const b = String(e.buildingType ?? "");
        objectives.push({ t, teamId: team, kind: b.includes("INHIB") ? "INHIBITOR" : "TOWER", sub: e.laneType ? String(e.laneType) : undefined });
      } else if (type === "ITEM_PURCHASED" || type === "ITEM_UNDO") {
        const p = puuidOf(e.participantId);
        if (!p) continue;
        const list = (items[p] ??= []);
        if (type === "ITEM_PURCHASED") list.push([t, num(e.itemId)]);
        else {
          const undo = num(e.beforeId) || num(e.itemId);
          for (let i = list.length - 1; i >= 0; i--) if (list[i][1] === undo) { list.splice(i, 1); break; }
        }
      }
    }
  }

  return {
    version: 1,
    minutes: frames.length - 1,
    blueGold: teamGold(100),
    redGold: teamGold(200),
    players, kills, objectives, items,
  };
}

/** Gold lead for blue (negative = red ahead) each minute. */
export const goldDiff = (s: TimelineSummary) => s.blueGold.map((b, i) => b - s.redGold[i]);

/** The biggest deficit the winning team came back from (0 if they were never behind). */
export function comeback(s: TimelineSummary, blueWon: boolean) {
  const diff = goldDiff(s).map((d) => (blueWon ? d : -d));
  let worst = 0, at = 0;
  diff.forEach((d, i) => { if (d < worst) { worst = d; at = i; } });
  return { deficit: -worst, minute: at };
}

/** The biggest lead either team had. */
export function biggestLead(s: TimelineSummary) {
  let best = 0, at = 0, team: 100 | 200 = 100;
  goldDiff(s).forEach((d, i) => { if (Math.abs(d) > best) { best = Math.abs(d); at = i; team = d >= 0 ? 100 : 200; } });
  return { lead: best, minute: at, team };
}

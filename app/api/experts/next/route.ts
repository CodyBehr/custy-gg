// The next high-elo games for custy coach to download replays of (League lets each account download 10 an hour).
//   GET /api/experts/next?patch=16.22&count=1   (Authorization: Bearer <ingest key>)
//   -> { games: [{ gameId, platform, gameVersion, kind: "matchup" | "general", matchup? }], queued, crawled }
//
// It keeps a small queue in the settings table and refills it a little on each call, so nothing has to be kicked off:
// it walks the NA Master+ ladder, reads each player's recent solo-queue games on the current patch, and puts games
// with a target matchup (Garen vs Darius top for now) first. When someone plays one of those champions in that role,
// their history is read next, since mains play the matchup far more often. Every other game still counts as
// "general" data for learning how lanes go. Only NA, since League only downloads replays from your own region.

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const TARGETS = [{ a: "Garen", b: "Darius", role: "TOP" }];
const STATE_KEY = "expert_crawl_v1";
const BUDGET_MS = 25_000;
const BUDGET_CALLS = 40;

interface QItem {
  gameId: number; platform: string; gameVersion: string; gameType: string; queueId: number; gameEnd: number;
  kind: "matchup" | "general"; matchup?: string;
}
interface State {
  patch: string;
  ladder: string[];           // puuids, Master+ (refreshed daily)
  ladderAt: number;
  next: number;               // where we are in the ladder
  front: string[];            // players to read next (they play a target champion)
  scanned: Record<string, number>;   // puuid -> when their history was last read
  queue: QItem[];
  served: number[];           // game ids already handed out (newest last)
  seen: number[];             // match ids already looked at (newest last)
}

async function riot(host: string, path: string, key: string) {
  const r = await fetch(`https://${host}.api.riotgames.com${path}`, { headers: { "X-Riot-Token": key, "User-Agent": "custy.gg" }, cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw Object.assign(new Error(`Riot API answered ${r.status}`), { status: r.status });
  return r.json();
}

/** "16.21.700.1" is older than patch "16.22"? */
function older(version: string, patch: string): boolean {
  const [a, b] = version.split(".").map(Number), [c, d] = patch.split(".").map(Number);
  return a < c || (a === c && b < d);
}

function fresh(patch: string): State {
  return { patch, ladder: [], ladderAt: 0, next: 0, front: [], scanned: {}, queue: [], served: [], seen: [] };
}

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  const key = process.env.RIOT_API_KEY;
  if (!key) return NextResponse.json({ error: "RIOT_API_KEY isn't set on the site" }, { status: 503 });
  const url = new URL(req.url);
  const patch = /^\d+\.\d+$/.test(url.searchParams.get("patch") ?? "") ? url.searchParams.get("patch")! : null;
  if (!patch) return NextResponse.json({ error: "patch is required, like 16.22" }, { status: 400 });
  const count = Math.max(1, Math.min(10, Number(url.searchParams.get("count")) || 1));
  const skip = new Set((url.searchParams.get("skip") ?? "").split(",").map(Number).filter(Boolean));

  const s = store();
  let st: State;
  try { st = JSON.parse((await s.getSetting(STATE_KEY)) ?? "null") ?? fresh(patch); } catch { st = fresh(patch); }
  if (st.patch !== patch) st = { ...fresh(patch), ladder: st.ladder, ladderAt: st.ladderAt };   // new patch: old replays can't be downloaded

  const t0 = Date.now();
  let calls = 0, crawled = 0, note: string | undefined;
  const served = new Set(st.served), seen = new Set(st.seen);
  const ready = () => st.queue.filter(q => !served.has(q.gameId) && !skip.has(q.gameId)).length;
  try {
    // Refill until there's enough waiting, within a time and request budget (development keys allow 100 per 2 minutes).
    while (ready() < count + 3 && Date.now() - t0 < BUDGET_MS && calls < BUDGET_CALLS) {
      if (!st.ladder.length || Date.now() - st.ladderAt > 86_400_000) {
        const all: string[] = [];
        for (const tier of ["challengerleagues", "grandmasterleagues", "masterleagues"]) {
          const l = await riot("na1", `/lol/league/v4/${tier}/by-queue/RANKED_SOLO_5x5`, key); calls++;
          for (const e of l?.entries ?? []) if (e.puuid) all.push(e.puuid);
        }
        st.ladder = all; st.ladderAt = Date.now(); st.next = 0;
        if (!all.length) { note = "The ladder came back empty."; break; }
      }
      const puuid = st.front.shift() ?? st.ladder[st.next++ % st.ladder.length];
      if (Date.now() - (st.scanned[puuid] ?? 0) < 6 * 3_600_000) continue;   // read at most every 6 hours
      st.scanned[puuid] = Date.now();
      const since = Math.floor(Date.now() / 1000) - 14 * 86400;
      const ids: string[] = (await riot("americas", `/lol/match/v5/matches/by-puuid/${puuid}/ids?queue=420&startTime=${since}&count=20`, key)) ?? []; calls++;
      for (const mid of ids) {
        const gid = Number(mid.split("_")[1]);
        if (!gid || seen.has(gid)) continue;
        if (Date.now() - t0 > BUDGET_MS || calls >= BUDGET_CALLS) break;
        seen.add(gid); st.seen.push(gid);
        const m = await riot("americas", `/lol/match/v5/matches/${mid}`, key); calls++; crawled++;
        const info = m?.info;
        if (!info || !String(info.gameVersion).startsWith(patch + ".")) {
          if (info && older(String(info.gameVersion), patch)) break;   // older patch: the rest of this history is older too
          continue;
        }
        if ((info.gameDuration ?? 0) < 900) continue;   // remakes and early surrenders say little
        let hit: string | undefined;
        for (const t of TARGETS) {
          const inRole = (c: string) => info.participants.find((p: any) => p.championName === c && p.teamPosition === t.role);
          const pa = inRole(t.a), pb = inRole(t.b);
          if (pa && pb && pa.teamId !== pb.teamId) hit = `${t.a}-${t.b}-${t.role}`;
          for (const p of [pa, pb]) if (p?.puuid && !st.front.includes(p.puuid) && p.puuid !== puuid) st.front.push(p.puuid);
        }
        st.queue.push({ gameId: gid, platform: info.platformId ?? "NA1", gameVersion: info.gameVersion, gameType: info.gameType ?? "MATCHED_GAME",
          queueId: info.queueId ?? 420, gameEnd: info.gameEndTimestamp ?? (info.gameCreation + info.gameDuration * 1000),
          kind: hit ? "matchup" : "general", matchup: hit });
      }
    }
  } catch (e: any) {
    note = e?.status === 429 ? "Riot's rate limit: more next time." : (e?.status === 401 || e?.status === 403) ? "Riot rejected the site's key." : String(e?.message ?? e);
  }

  // Hand out matchup games first, then the newest general games.
  const pick = st.queue.filter(q => !served.has(q.gameId) && !skip.has(q.gameId))
    .sort((x, y) => (x.kind === y.kind ? y.gameId - x.gameId : x.kind === "matchup" ? -1 : 1)).slice(0, count);
  for (const q of pick) st.served.push(q.gameId);
  st.served = st.served.slice(-5000);
  st.seen = st.seen.slice(-20000);
  const done = new Set(st.served);
  st.queue = st.queue.filter(q => !done.has(q.gameId)).slice(-400);
  st.front = st.front.slice(0, 200);
  if (Object.keys(st.scanned).length > 3000) {
    st.scanned = Object.fromEntries(Object.entries(st.scanned).sort((a, b) => b[1] - a[1]).slice(0, 2000));
  }
  await s.setSetting(STATE_KEY, JSON.stringify(st));
  return NextResponse.json({ games: pick, queued: st.queue.length, crawled, calls, note });
}

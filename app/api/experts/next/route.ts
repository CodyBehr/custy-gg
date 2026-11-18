// The next high-elo games for custy coach to download replays of. Every PC running the app asks here, so each
// game goes to only one of them.
//   GET /api/experts/next?patch=16.22&count=1&skip=1,2,3   (Authorization: Bearer <ingest key>)
//   -> { games: [{ gameId, platform, gameVersion, gameType, queueId, gameEnd, tier, matchup? }], queued, crawled, note? }
//
// It keeps a queue in the settings table and refills it a little on each call, so nothing has to be kicked off.
// It reads the NA ladder from the top (Challenger, then Grandmaster, then Master), takes each player's recent solo
// queue games on the current patch, and hands out games found through higher-ranked players first, newest first.
// NA only, since League only downloads replays from your own region and patch.

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const MATCHUPS = [{ a: "Garen", b: "Darius", role: "TOP" }];   // only labelled, not preferred
const STATE_KEY = "expert_crawl_v2";
const LOCK_KEY = "expert_crawl_lock";
// Each PC can only download replays from its own region, so each region has its own crawl (and its own Riot rate
// limit). NA keeps the original keys.
const ROUTES: Record<string, string> = {
  na1: "americas", br1: "americas", la1: "americas", la2: "americas",
  euw1: "europe", eun1: "europe", tr1: "europe", ru: "europe", me1: "europe",
  kr: "asia", jp1: "asia", oc1: "sea", sg2: "sea", tw2: "sea", vn2: "sea",
};
const BUDGET_MS = 22_000;
const BUDGET_CALLS = 40;
const TIERS = ["challengerleagues", "grandmasterleagues", "masterleagues"] as const;

interface QItem {
  gameId: number; platform: string; gameVersion: string; gameType: string; queueId: number; gameEnd: number;
  tier: number; matchup?: string;   // tier: 0 Challenger, 1 Grandmaster, 2 Master (of the player it was found through)
}
interface State {
  patch: string;
  ladder: { p: string; t: number }[];   // puuid, tier; Challenger first (refreshed every 12 hours)
  ladderAt: number;
  next: number;
  scanned: Record<string, number>;      // puuid -> when their history was last read
  queue: QItem[];
  served: number[];
  seen: number[];
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

const fresh = (patch: string): State => ({ patch, ladder: [], ladderAt: 0, next: 0, scanned: {}, queue: [], served: [], seen: [] });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

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
  const platform = (url.searchParams.get("platform") ?? "na1").toLowerCase();
  const route = ROUTES[platform];
  if (!route) return NextResponse.json({ games: [], note: `Region ${platform} isn't supported yet.` });
  const sfx = platform === "na1" ? "" : `_${platform}`;

  // One request at a time works on the queue, so two PCs never get the same game.
  const s = store();
  let locked = false;
  for (let i = 0; i < 30 && !(locked = await s.tryLock(LOCK_KEY + sfx, 55_000)); i++) await sleep(500);
  if (!locked) return NextResponse.json({ games: [], note: "busy" });

  try {
    let st: State;
    try { st = JSON.parse((await s.getSetting(STATE_KEY + sfx)) ?? "null") ?? fresh(patch); } catch { st = fresh(patch); }
    if (st.patch !== patch) {
      if (older(patch, st.patch)) return NextResponse.json({ games: [], note: "Your League is on an older patch." });
      st = { ...fresh(patch), ladder: st.ladder, ladderAt: st.ladderAt };   // new patch: older replays can't be downloaded
    }
    const t0 = Date.now();
    let calls = 0, crawled = 0, note: string | undefined;
    const served = new Set(st.served), seen = new Set(st.seen);
    const ready = () => st.queue.filter((q) => !served.has(q.gameId) && !skip.has(q.gameId)).length;
    try {
      while (ready() < count + 5 && Date.now() - t0 < BUDGET_MS && calls < BUDGET_CALLS) {
        if (!st.ladder.length || Date.now() - st.ladderAt > 12 * 3_600_000) {
          const all: { p: string; t: number }[] = [];
          for (let t = 0; t < TIERS.length; t++) {
            const l = await riot(platform, `/lol/league/v4/${TIERS[t]}/by-queue/RANKED_SOLO_5x5`, key); calls++;
            const es = [...(l?.entries ?? [])].sort((x: any, y: any) => y.leaguePoints - x.leaguePoints);
            for (const e of es) if (e.puuid) all.push({ p: e.puuid, t });
          }
          if (!all.length) { note = "The ladder came back empty."; break; }
          st.ladder = all; st.ladderAt = Date.now(); st.next = 0;
        }
        // Next player from the top of the ladder who hasn't been read in the last 6 hours.
        let pl: { p: string; t: number } | undefined;
        for (let n = 0; n < st.ladder.length && !pl; n++) {
          const c = st.ladder[(st.next + n) % st.ladder.length];
          if (Date.now() - (st.scanned[c.p] ?? 0) > 6 * 3_600_000) { pl = c; st.next = (st.next + n + 1) % st.ladder.length; }
        }
        if (!pl) { st.next = 0; note = "Everyone on the ladder was read in the last 6 hours."; break; }
        st.scanned[pl.p] = Date.now();
        const since = Math.floor(Date.now() / 1000) - 14 * 86400;
        const ids: string[] = (await riot(route, `/lol/match/v5/matches/by-puuid/${pl.p}/ids?queue=420&startTime=${since}&count=20`, key)) ?? []; calls++;
        for (const mid of ids) {
          const gid = Number(mid.split("_")[1]);
          if (!gid || seen.has(gid)) continue;
          if (Date.now() - t0 > BUDGET_MS || calls >= BUDGET_CALLS) break;
          const m = await riot(route, `/lol/match/v5/matches/${mid}`, key); calls++; crawled++;
          seen.add(gid); st.seen.push(gid);
          const info = m?.info;
          if (!info) continue;
          if (!String(info.gameVersion).startsWith(patch + ".")) {
            if (older(String(info.gameVersion), patch)) break;   // the rest of this history is older too
            continue;
          }
          if ((info.gameDuration ?? 0) < 900) continue;   // remakes and early surrenders say little
          let matchup: string | undefined;
          for (const t of MATCHUPS) {
            const inRole = (c: string) => info.participants.find((p: any) => p.championName === c && p.teamPosition === t.role);
            const pa = inRole(t.a), pb = inRole(t.b);
            if (pa && pb && pa.teamId !== pb.teamId) matchup = `${t.a}-${t.b}-${t.role}`;
          }
          st.queue.push({
            gameId: gid, platform: info.platformId ?? platform.toUpperCase(), gameVersion: info.gameVersion, gameType: info.gameType ?? "MATCHED_GAME",
            queueId: info.queueId ?? 420, gameEnd: info.gameEndTimestamp ?? info.gameCreation + info.gameDuration * 1000,
            tier: pl.t, matchup,
          });
        }
      }
    } catch (e: any) {
      note = e?.status === 429 ? "Riot's rate limit: more next time." : e?.status === 401 || e?.status === 403 ? "Riot rejected the site's key." : String(e?.message ?? e);
    }

    // Games found through Challenger players first, then Grandmaster, then Master; newest first within each.
    const pick = st.queue.filter((q) => !served.has(q.gameId) && !skip.has(q.gameId))
      .sort((x, y) => x.tier - y.tier || y.gameId - x.gameId).slice(0, count);
    for (const q of pick) st.served.push(q.gameId);
    st.served = st.served.slice(-20000);
    st.seen = st.seen.slice(-40000);
    const done = new Set(st.served);
    st.queue = st.queue.filter((q) => !done.has(q.gameId)).sort((x, y) => x.tier - y.tier || y.gameId - x.gameId).slice(0, 600);
    if (Object.keys(st.scanned).length > 6000) {
      st.scanned = Object.fromEntries(Object.entries(st.scanned).sort((a, b) => b[1] - a[1]).slice(0, 4000));
    }
    await s.setSetting(STATE_KEY + sfx, JSON.stringify(st));
    console.log(`experts/next ${platform}: served ${pick.length}, queued ${st.queue.length}, crawled ${crawled}, calls ${calls}, ladder ${st.ladder.length}${note ? ", note: " + note : ""}`);
    return NextResponse.json({ games: pick, queued: st.queue.length, served: st.served.length, crawled, calls, note });
  } finally {
    await s.setSetting(LOCK_KEY + sfx, "0");
  }
}

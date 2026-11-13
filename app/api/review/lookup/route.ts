// Look up any player's recent games for the Windows app's review page ("view another player").
// The Riot key stays on the server.
//   GET /api/review/lookup?riotId=Name%23TAG&platform=NA1   -> { puuid, gameName, tagLine, ids }
//   GET /api/review/lookup?match=NA1_5676694528             -> { match, timeline } (raw match-v5)
// (Authorization: Bearer <ingest key>)

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const ROUTES: Record<string, string> = {
  NA1: "americas", BR1: "americas", LA1: "americas", LA2: "americas",
  EUW1: "europe", EUN1: "europe", TR1: "europe", RU: "europe", ME1: "europe",
  KR: "asia", JP1: "asia",
  OC1: "sea", SG2: "sea", TW2: "sea", VN2: "sea", PH2: "sea", TH2: "sea",
};
// Riot ID lookups use americas/europe/asia only.
const ACCOUNT: Record<string, string> = { americas: "americas", europe: "europe", asia: "asia", sea: "asia" };

async function riot(host: string, path: string, key: string) {
  const r = await fetch(`https://${host}.api.riotgames.com${path}`, { headers: { "X-Riot-Token": key, "User-Agent": "custy.gg" }, cache: "no-store" });
  if (!r.ok) throw Object.assign(new Error(`Riot API answered ${r.status}`), { status: r.status });
  return r.json();
}

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  const key = process.env.RIOT_API_KEY;
  if (!key) return NextResponse.json({ error: "RIOT_API_KEY isn't set on the site" }, { status: 503 });
  const url = new URL(req.url);
  try {
    const match = url.searchParams.get("match");
    if (match) {
      const m = /^([A-Z0-9]+)_(\d+)$/.exec(match.toUpperCase());
      const route = m && ROUTES[m[1]];
      if (!route) return NextResponse.json({ error: "Bad match id" }, { status: 400 });
      const [mt, tl] = await Promise.all([
        riot(route, `/lol/match/v5/matches/${match.toUpperCase()}`, key),
        riot(route, `/lol/match/v5/matches/${match.toUpperCase()}/timeline`, key),
      ]);
      return NextResponse.json({ match: mt, timeline: tl }, { headers: { "Cache-Control": "private, max-age=86400" } });
    }
    const riotId = (url.searchParams.get("riotId") || "").trim();
    const platform = (url.searchParams.get("platform") || "NA1").toUpperCase();
    const route = ROUTES[platform];
    const [name, tag] = riotId.split("#");
    if (!route || !name || !tag) return NextResponse.json({ error: "Give a Riot ID like Name#TAG" }, { status: 400 });
    const acc = await riot(ACCOUNT[route], `/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`, key);
    const ids: string[] = await riot(route, `/lol/match/v5/matches/by-puuid/${acc.puuid}/ids?start=0&count=20`, key);
    return NextResponse.json({ puuid: acc.puuid, gameName: acc.gameName, tagLine: acc.tagLine, ids });
  } catch (e: any) {
    const s = e?.status === 404 ? 404 : e?.status === 429 ? 429 : 502;
    const msg = s === 404 ? "Player or game not found"
      : s === 429 ? "Riot's request limit for the site is used up for the moment (100 requests per 2 minutes). Try again in a minute or two."
      : e?.message || "Riot API error";
    return NextResponse.json({ error: msg, rateLimited: s === 429 }, { status: s });
  }
}

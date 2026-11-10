// The game review in the Windows app asks for the parts of a timeline the League client leaves out
// (item purchases, skill and level ups) for ranked and normal games. The site fetches them from
// Riot's match API with RIOT_API_KEY, so the key never leaves the server.
//   GET /api/review/timeline?platform=NA1&gameId=5676694528   (Authorization: Bearer <ingest key>)

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
const KEEP = new Set(["ITEM_PURCHASED", "ITEM_UNDO", "ITEM_SOLD", "ITEM_DESTROYED", "SKILL_LEVEL_UP", "LEVEL_UP", "TURRET_PLATE_DESTROYED"]);

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  const key = process.env.RIOT_API_KEY;
  if (!key) return NextResponse.json({ error: "RIOT_API_KEY isn't set on the site" }, { status: 503 });
  const url = new URL(req.url);
  const platform = (url.searchParams.get("platform") || "NA1").toUpperCase();
  const gameId = url.searchParams.get("gameId") || "";
  const route = ROUTES[platform];
  if (!route || !/^\d+$/.test(gameId)) return NextResponse.json({ error: "Needs platform and gameId" }, { status: 400 });

  const res = await fetch(`https://${route}.api.riotgames.com/lol/match/v5/matches/${platform}_${gameId}/timeline`, {
    headers: { "X-Riot-Token": key, "User-Agent": "custy.gg" },
    cache: "no-store",
  });
  if (!res.ok) {
    const status = res.status === 404 ? 404 : res.status === 429 ? 429 : 502;
    return NextResponse.json({ error: `Riot API answered ${res.status}` }, { status });
  }
  const tl = await res.json();
  const info = tl?.info ?? {};
  const participants = (info.participants ?? []).map((p: any) => ({ participantId: p.participantId, puuid: p.puuid }));
  const frames = (info.frames ?? []).map((f: any) => ({
    timestamp: f.timestamp,
    events: (f.events ?? []).filter((e: any) => KEEP.has(e.type)),
    // Armor per participant: the client's timeline doesn't have champion stats.
    armor: Object.fromEntries(Object.values(f.participantFrames ?? {}).map((pf: any) => [pf.participantId, pf.championStats?.armor ?? null])),
  }));
  return NextResponse.json({ participants, frames }, { headers: { "Cache-Control": "private, max-age=86400" } });
}

// TEMPORARY (removed right after use): Leaden#0417's recent ranked solo games for a one-off comparison.
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;
const H = () => ({ "X-Riot-Token": process.env.RIOT_API_KEY ?? "", "User-Agent": "custy.gg" });
const get = async (u: string) => {
  const r = await fetch(u, { headers: H(), cache: "no-store" });
  if (!r.ok) throw new Error(`Riot ${r.status}`);
  return r.json();
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  try {
    const acct = await get("https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/Leaden/0417");
    const ids: string[] = await get(`https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/${acct.puuid}/ids?queue=420&count=40`);
    const m = url.searchParams.get("match");
    if (!m) return NextResponse.json({ puuid: acct.puuid, ids });
    if (!ids.includes(m)) return NextResponse.json({ error: "not one of Leaden's recent games" }, { status: 400 });
    const [match, timeline] = await Promise.all([
      get(`https://americas.api.riotgames.com/lol/match/v5/matches/${m}`),
      get(`https://americas.api.riotgames.com/lol/match/v5/matches/${m}/timeline`),
    ]);
    return NextResponse.json({ match, timeline });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}

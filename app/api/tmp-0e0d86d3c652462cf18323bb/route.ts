// TEMPORARY (removed right after use): ranks, champion mastery and recent roles of players in Buckley#NA0's ranked games.
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;
const A = "https://americas.api.riotgames.com";
const N = "https://na1.api.riotgames.com";
const H = () => ({ "X-Riot-Token": process.env.RIOT_API_KEY ?? "", "User-Agent": "custy.gg" });
class RiotErr extends Error { constructor(public status: number, public retry: string | null) { super(`Riot ${status}`); } }
const get = async (u: string) => {
  const r = await fetch(u, { headers: H(), cache: "no-store" });
  if (!r.ok) throw new RiotErr(r.status, r.headers.get("retry-after"));
  return r.json();
};

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const game = q.get("game") ?? "";
  const puuid = q.get("puuid") ?? "";
  if (!/^\d+$/.test(game)) return NextResponse.json({ error: "game" }, { status: 400 });
  try {
    const acct = await get(`${A}/riot/account/v1/accounts/by-riot-id/Buckley/NA0`);
    const ME: string = acct.puuid;
    const match = await get(`${A}/lol/match/v5/matches/NA1_${game}`);
    const ps: { puuid: string; participantId: number; championId: number; teamPosition: string; teamId: number }[] = match.info.participants;
    if (!ps.some((p) => p.puuid === ME)) return NextResponse.json({ error: "not Buckley's game" }, { status: 400 });
    if (!puuid) return NextResponse.json({ participants: ps.map((p) => ({ puuid: p.puuid, participantId: p.participantId, championId: p.championId, teamPosition: p.teamPosition, teamId: p.teamId })) });
    const me = ps.find((p) => p.puuid === puuid);
    if (!me) return NextResponse.json({ error: "not in that game" }, { status: 400 });
    const league = await get(`${N}/lol/league/v4/entries/by-puuid/${puuid}`);
    if (q.get("deep") !== "1") return NextResponse.json({ league });
    let mastery = null;
    try { mastery = await get(`${N}/lol/champion-mastery/v4/champion-masteries/by-puuid/${puuid}/by-champion/${me.championId}`); }
    catch (e) { if (!(e instanceof RiotErr && e.status === 404)) throw e; }
    const end = Math.floor(match.info.gameStartTimestamp / 1000) - 60;
    const ids: string[] = await get(`${A}/lol/match/v5/matches/by-puuid/${puuid}/ids?queue=420&count=8&endTime=${end}`);
    const history = [];
    for (const id of ids) {
      const m = await get(`${A}/lol/match/v5/matches/${id}`);
      const p = m.info.participants.find((x: { puuid: string }) => x.puuid === puuid);
      history.push({ id, role: p?.teamPosition, championId: p?.championId, win: p?.win, start: m.info.gameStartTimestamp });
    }
    return NextResponse.json({ league, mastery, history });
  } catch (e) {
    if (e instanceof RiotErr) return NextResponse.json({ error: e.message, retry: e.retry }, { status: e.status === 429 ? 429 : 502 });
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}

// The collector posts who's in the custom lobby here while you're in one.
//   POST /api/lobby  { members: [{ puuid, name, tag, team }], uploader }
//   GET  /api/lobby  the latest lobby (needs the same key)

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { getLobby, saveLobby, type LobbyMember } from "@/lib/lobby";
import { saveRanks } from "@/lib/rank-store";

export const dynamic = "force-dynamic";

async function authorized(req: Request) {
  try {
    return await checkIngestKey(req.headers.get("authorization"));
  } catch {
    return false;
  }
}

export async function GET(req: Request) {
  if (!(await authorized(req))) return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  return NextResponse.json((await getLobby()) ?? { members: [] });
}

export async function POST(req: Request) {
  if (!(await authorized(req))) return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body must be JSON" }, { status: 400 });
  }
  const members: LobbyMember[] = (Array.isArray(body?.members) ? body.members : [])
    .slice(0, 20)
    .map((m: any) => ({
      puuid: typeof m?.puuid === "string" ? m.puuid : undefined,
      name: String(m?.name ?? "").slice(0, 40),
      tag: m?.tag ? String(m.tag).slice(0, 10) : undefined,
      team: m?.team === 100 || m?.team === 200 ? m.team : 0,
    }))
    .filter((m: LobbyMember) => m.name);
  // Ranks read alongside the lobby (from the League client) refresh the rank cache.
  const ranks: Record<string, unknown> = {};
  for (const m of Array.isArray(body?.members) ? body.members : []) {
    if (typeof m?.puuid === "string" && m.rank) ranks[m.puuid] = m.rank;
  }
  if (Object.keys(ranks).length) await saveRanks(ranks);
  const u = body?.uploader;
  await saveLobby({ members, updatedAt: Date.now(), uploader: u?.gameName ? `${u.gameName}#${u.tagLine ?? ""}` : undefined });
  console.log(`[lobby] ${members.length} players from ${u?.gameName ?? "unknown"}: ${members.map((m) => m.name).join(", ")}`);
  return NextResponse.json({ ok: true, members: members.length });
}

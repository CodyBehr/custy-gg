// The collector sends solo queue ranks it read from the League client.
//   POST /api/ranks  { ranks: { <puuid>: { tier, division, lp, wins, losses, source } } }

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { saveRanks } from "@/lib/rank-store";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let ok = false;
  try {
    ok = await checkIngestKey(req.headers.get("authorization"));
  } catch {
    ok = false;
  }
  if (!ok) return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body must be JSON" }, { status: 400 });
  }
  const saved = await saveRanks(body?.ranks && typeof body.ranks === "object" ? body.ranks : {});
  return NextResponse.json({ ok: true, saved });
}

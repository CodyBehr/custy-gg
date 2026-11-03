// Rebuilds every stored game's summary from its raw data. Run it after an
// update to lib/normalize.ts:
//   curl -X POST https://your-site/api/admin/renormalize -H "Authorization: Bearer $INGEST_KEY"

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { renormalizeAll } from "@/lib/store";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  return NextResponse.json(await renormalizeAll());
}

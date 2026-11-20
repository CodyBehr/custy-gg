// Where custy coach sends a batch of your grades on the coach's reads (Right / Wrong / Meh + your note, with the
// read and the moment's numbers), so they can be reviewed together.
//   GET /api/coach/grades?by=<Riot ID>   (Authorization: Bearer <ingest key>)
//   -> { url } : a link that accepts one PUT of the batch (JSON) for 15 minutes, into R2 grades/<by>/<time>.json

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { presignPut } from "@/lib/r2";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  const { R2_ACCOUNT_ID: acc, R2_ACCESS_KEY_ID: akid, R2_SECRET_ACCESS_KEY: secret, R2_BUCKET: bucket } = process.env;
  if (!acc || !akid || !secret || !bucket) {
    return NextResponse.json({ error: "Storage isn't set up on the site yet" }, { status: 503 });
  }
  const url = new URL(req.url);
  const by = (url.searchParams.get("by") ?? "someone").replace(/[^A-Za-z0-9 _#-]/g, "").slice(0, 40) || "someone";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return NextResponse.json({ url: presignPut(acc, akid, secret, bucket, `grades/${by}/${stamp}.json`) });
}

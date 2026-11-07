// Vercel cron (see vercel.json) calls this every Monday morning to post last week's recap.
// Safe to call more than once: each week is only posted one time.

import { NextResponse } from "next/server";
import { postLastWeek } from "@/lib/weekly";
import { siteUrl } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (secret && req.headers.get("authorization") !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "Not allowed" }, { status: 401 });
  }
  return NextResponse.json(await postLastWeek(siteUrl(req)));
}

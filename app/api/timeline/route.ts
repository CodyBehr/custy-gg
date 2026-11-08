// The collector sends each game's timeline here after uploading the game.
//   POST /api/timeline  { id: "<platformId>-<gameId>", timeline: {...} }

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { store } from "@/lib/store";
import { summarizeTimeline } from "@/lib/timeline";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function POST(req: Request) {
  try {
    if (!(await checkIngestKey(req.headers.get("authorization")))) {
      return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
    }
  } catch (e) {
    return NextResponse.json({ error: `Database error: ${(e as Error).message}` }, { status: 500 });
  }
  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body must be JSON" }, { status: 400 });
  }
  const id = String(body?.id ?? "");
  if (!id || !body?.timeline) return NextResponse.json({ error: "Needs id and timeline" }, { status: 400 });
  if (await store().hasTimeline(id)) return NextResponse.json({ status: "exists" });

  const game = await store().getRaw(id);
  if (!game) return NextResponse.json({ error: "Unknown game; upload it first" }, { status: 404 });
  const summary = summarizeTimeline(body.timeline, game);
  if (!summary) {
    console.log(`[timeline] ${id}: couldn't read it (keys: ${Object.keys(body.timeline ?? {}).join(",")})`);
    return NextResponse.json({ error: "Couldn't read that timeline" }, { status: 422 });
  }
  const status = await store().saveTimeline(id, summary, body.timeline);
  console.log(`[timeline] ${id}: ${status}, ${summary.minutes} min, ${summary.kills.length} kills, ${summary.objectives.length} objectives`);
  return NextResponse.json({ status }, { status: status === "created" ? 201 : 200 });
}

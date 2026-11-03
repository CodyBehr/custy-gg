// The collector posts each finished custom game here.
//   POST /api/ingest   body: { game, uploader }   -> { status: "created" | "exists", id }
//   GET  /api/ingest   health check for `custy_collector.py --test`

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { isCustomGame, normalize } from "@/lib/normalize";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

const denied = () => NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });

async function authorized(req: Request): Promise<NextResponse | null> {
  try {
    return (await checkIngestKey(req.headers.get("authorization"))) ? null : denied();
  } catch (e) {
    return NextResponse.json({ error: `Database error: ${(e as Error).message}` }, { status: 500 });
  }
}

export async function GET(req: Request) {
  const fail = await authorized(req);
  if (fail) return fail;
  try {
    return NextResponse.json({ ok: true, matches: await store().count() });
  } catch (e) {
    return NextResponse.json({ error: `Database error: ${(e as Error).message}` }, { status: 500 });
  }
}

export async function POST(req: Request) {
  const fail = await authorized(req);
  if (fail) return fail;

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body must be JSON" }, { status: 400 });
  }
  const raw = body?.game ?? body;
  if (!isCustomGame(raw)) {
    return NextResponse.json({ error: "Only custom games are stored" }, { status: 422 });
  }

  let match;
  try {
    match = normalize(raw);
  } catch (e) {
    return NextResponse.json({ error: `Could not read game: ${(e as Error).message}` }, { status: 422 });
  }

  const u = body?.uploader;
  const uploadedBy = u?.gameName ? `${u.gameName}#${u.tagLine ?? ""}` : null;
  try {
    const status = await store().save(match, raw, uploadedBy);
    return NextResponse.json({ status, id: match.id }, { status: status === "created" ? 201 : 200 });
  } catch (e) {
    return NextResponse.json({ error: `Database error: ${(e as Error).message}` }, { status: 500 });
  }
}

// Where custy coach uploads the data it pulls out of an expert replay (about 1 MB, gzipped JSON).
//   GET /api/experts/upload?gameId=5679011844&patch=16.22   (Authorization: Bearer <ingest key>)
//   -> { url } : a link that accepts one PUT of the file for 15 minutes, straight into Cloudflare R2
//   -> 503 { error } until R2 is set up (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET)
// The files go to games/<patch>/<gameId>.json.gz. The app deletes its own copy once the upload succeeds.

import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { store } from "@/lib/store";
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
  const gameId = url.searchParams.get("gameId") ?? "";
  const patch = url.searchParams.get("patch") ?? "";
  if (!/^\d{6,15}$/.test(gameId) || !/^\d+\.\d+$/.test(patch)) {
    return NextResponse.json({ error: "gameId and patch are required" }, { status: 400 });
  }
  // ?done=1 after the upload went through: count it for the sender (their Riot ID), once per game.
  if (url.searchParams.get("done") === "1") {
    const by = (url.searchParams.get("by") ?? "").slice(0, 40) || "someone";
    const s = store();
    for (let i = 0; i < 20; i++) {
      if (await s.tryLock("expert_contrib_lock", 10_000)) {
        try {
          const c = JSON.parse((await s.getSetting("expert_contrib_v2")) ?? "{}") as { counts?: Record<string, number>; games?: number[] };
          c.counts ??= {}; c.games ??= [];
          if (!c.games.includes(Number(gameId))) {
            c.counts[by] = (c.counts[by] ?? 0) + 1;
            c.games = [...c.games, Number(gameId)].slice(-30000);
            await s.setSetting("expert_contrib_v2", JSON.stringify(c));
          }
        } finally {
          await s.setSetting("expert_contrib_lock", "0");
        }
        break;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    return NextResponse.json({ ok: true });
  }
  return NextResponse.json({ url: presignPut(acc, akid, secret, bucket, `games/${patch}/${gameId}.json.gz`) });
}

// Writes a tiny test file to the R2 bucket and reports what Cloudflare answered, so the app can show it.
//   GET /api/experts/storage-check   (Authorization: Bearer <ingest key>) -> { ok, status?, why? }
// Never returns the keys themselves, only which ones are missing or look wrong.
import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { presignPut } from "@/lib/r2";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  const env = { R2_ACCOUNT_ID: process.env.R2_ACCOUNT_ID, R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY, R2_BUCKET: process.env.R2_BUCKET };
  const missing = Object.entries(env).filter(([, v]) => !v?.trim()).map(([k]) => k);
  if (missing.length) return NextResponse.json({ ok: false, why: `Not set on the site: ${missing.join(", ")}` });
  const acc = env.R2_ACCOUNT_ID!.trim(), bucket = env.R2_BUCKET!.trim();
  const hints: string[] = [];
  if (!/^[0-9a-f]{32}$/.test(acc)) hints.push("R2_ACCOUNT_ID should be just the 32-character account ID, not a URL");
  if (env.R2_ACCESS_KEY_ID!.trim().length !== 32) hints.push("R2_ACCESS_KEY_ID is usually 32 characters (the S3 Access Key ID, not the token value)");
  if (env.R2_SECRET_ACCESS_KEY!.trim().length !== 64) hints.push("R2_SECRET_ACCESS_KEY is usually 64 characters");
  if (env.R2_ACCOUNT_ID !== acc || env.R2_BUCKET !== bucket || env.R2_ACCESS_KEY_ID !== env.R2_ACCESS_KEY_ID!.trim()
      || env.R2_SECRET_ACCESS_KEY !== env.R2_SECRET_ACCESS_KEY!.trim()) hints.push("one of the values has a space or line break around it");
  try {
    const url = presignPut(acc, env.R2_ACCESS_KEY_ID!.trim(), env.R2_SECRET_ACCESS_KEY!.trim(), bucket, "check/ping.txt", 300);
    const r = await fetch(url, { method: "PUT", body: "ok " + new Date().toISOString(), headers: { "Content-Type": "text/plain" } });
    const text = (await r.text()).slice(0, 400);
    const code = text.match(/<Code>([^<]+)<\/Code>/)?.[1];
    return NextResponse.json({ ok: r.ok, status: r.status, why: r.ok ? undefined : [code ?? `Cloudflare answered ${r.status}`, ...hints].join(" · ") });
  } catch (e: any) {
    return NextResponse.json({ ok: false, why: [String(e?.message ?? e), ...hints].join(" · ") });
  }
}

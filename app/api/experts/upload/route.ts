// Where custy coach uploads the data it pulls out of an expert replay (about 1 MB, gzipped JSON).
//   GET /api/experts/upload?gameId=5679011844&patch=16.22   (Authorization: Bearer <ingest key>)
//   -> { url } : a link that accepts one PUT of the file for 15 minutes, straight into Cloudflare R2
//   -> 503 { error } until R2 is set up (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET)
// The files go to games/<patch>/<gameId>.json.gz. The app deletes its own copy once the upload succeeds.

import crypto from "node:crypto";
import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";

const hmac = (k: crypto.BinaryLike, s: string) => crypto.createHmac("sha256", k).update(s).digest();
const enc = (s: string) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());

/** An S3-style presigned PUT link (AWS Signature Version 4), which is what R2 accepts. */
function presignPut(account: string, akid: string, secret: string, bucket: string, key: string, seconds = 900) {
  const host = `${account}.r2.cloudflarestorage.com`;
  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const day = amzDate.slice(0, 8);
  const scope = `${day}/auto/s3/aws4_request`;
  const path = `/${bucket}/${key.split("/").map(enc).join("/")}`;
  const q: Record<string, string> = {
    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
    "X-Amz-Credential": `${akid}/${scope}`,
    "X-Amz-Date": amzDate,
    "X-Amz-Expires": String(seconds),
    "X-Amz-SignedHeaders": "host",
  };
  const query = Object.keys(q).sort().map((k) => `${enc(k)}=${enc(q[k])}`).join("&");
  const canonical = ["PUT", path, query, `host:${host}\n`, "host", "UNSIGNED-PAYLOAD"].join("\n");
  const toSign = ["AWS4-HMAC-SHA256", amzDate, scope, crypto.createHash("sha256").update(canonical).digest("hex")].join("\n");
  const kSign = hmac(hmac(hmac(hmac("AWS4" + secret, day), "auto"), "s3"), "aws4_request");
  const sig = crypto.createHmac("sha256", kSign).update(toSign).digest("hex");
  return `https://${host}${path}?${query}&X-Amz-Signature=${sig}`;
}

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
  return NextResponse.json({ url: presignPut(acc, akid, secret, bucket, `games/${patch}/${gameId}.json.gz`) });
}

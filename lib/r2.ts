// Presigned upload links for Cloudflare R2 (S3 Signature Version 4), checked against AWS's own library.
import crypto from "node:crypto";

const hmac = (k: crypto.BinaryLike, s: string) => crypto.createHmac("sha256", k).update(s).digest();
const enc = (s: string) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());

/** An S3-style presigned PUT link (AWS Signature Version 4), which is what R2 accepts. */
export function presignPut(account: string, akid: string, secret: string, bucket: string, key: string, seconds = 900) {
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


/** Every object under a prefix (key, size, last modified), via signed ListObjectsV2 requests. */
export async function listObjects(account: string, akid: string, secret: string, bucket: string, prefix: string) {
  const host = `${account}.r2.cloudflarestorage.com`;
  const out: { key: string; size: number; at: number }[] = [];
  let token: string | undefined;
  for (let page = 0; page < 200; page++) {
    const now = new Date();
    const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    const day = amzDate.slice(0, 8);
    const scope = `${day}/auto/s3/aws4_request`;
    const path = `/${bucket}`;
    const q: Record<string, string> = {
      "list-type": "2", prefix, "max-keys": "1000",
      "X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": `${akid}/${scope}`, "X-Amz-Date": amzDate,
      "X-Amz-Expires": "300", "X-Amz-SignedHeaders": "host",
    };
    if (token) q["continuation-token"] = token;
    const query = Object.keys(q).sort().map((k) => `${enc(k)}=${enc(q[k])}`).join("&");
    const canonical = ["GET", path, query, `host:${host}\n`, "host", "UNSIGNED-PAYLOAD"].join("\n");
    const toSign = ["AWS4-HMAC-SHA256", amzDate, scope, crypto.createHash("sha256").update(canonical).digest("hex")].join("\n");
    const kSign = hmac(hmac(hmac(hmac("AWS4" + secret, day), "auto"), "s3"), "aws4_request");
    const sig = crypto.createHmac("sha256", kSign).update(toSign).digest("hex");
    const r = await fetch(`https://${host}${path}?${query}&X-Amz-Signature=${sig}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`R2 answered ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const xml = await r.text();
    for (const m of xml.matchAll(/<Contents>([\s\S]*?)<\/Contents>/g)) {
      const key = /<Key>([^<]*)<\/Key>/.exec(m[1])?.[1] ?? "";
      out.push({ key, size: Number(/<Size>(\d+)<\/Size>/.exec(m[1])?.[1] ?? 0), at: Date.parse(/<LastModified>([^<]*)<\/LastModified>/.exec(m[1])?.[1] ?? "") });
    }
    if (!/<IsTruncated>true<\/IsTruncated>/.test(xml)) break;
    token = /<NextContinuationToken>([^<]*)<\/NextContinuationToken>/.exec(xml)?.[1]?.replace(/&amp;/g, "&");
    if (!token) break;
  }
  return out;
}

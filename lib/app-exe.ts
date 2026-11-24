// The two Windows apps the site hands out, built by .github/workflows/build-collector.yml into collector-dist/:
//   custy-collector.exe  uploads custom games (the custom game tracker)
//   custy-coach.exe      reviews ranked and normal games (custy coach)
// Downloads get this site's address and upload key attached to the end, where the app reads them.

import fs from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { ingestKey, siteUrl } from "@/lib/ingest-key";

export type AppName = "custy-collector" | "custy-coach";
const exePath = (app: AppName) => path.join(process.cwd(), "collector-dist", `${app}.exe`);
const cache = new Map<AppName, { mtime: number; version: string }>();

function productVersion(buf: Buffer): string {
  const key = Buffer.from("ProductVersion\0", "utf16le");
  const at = buf.lastIndexOf(key);
  if (at < 0) return "";
  // Value follows the key, after padding to a 4-byte boundary.
  let i = at + key.length;
  while (i < buf.length && buf.readUInt16LE(i) === 0) i += 2;
  let out = "";
  for (; i + 1 < buf.length && out.length < 20; i += 2) {
    const c = buf.readUInt16LE(i);
    if (c === 0) break;
    out += String.fromCharCode(c);
  }
  return /^\d+(\.\d+)*$/.test(out) ? out : "";
}

/**
 * Where installed apps fetch updates: the same .exe on GitHub, pinned to the commit this site was deployed
 * from, so it always matches the version above. Serving updates from here used up Vercel's free
 * Fast Origin Transfer (10 GB a month) and paused the site; GitHub serves them for free.
 * The app attaches its own settings to the download. null when not deployed from Git (local dev).
 */
function githubDownload(app: AppName): string | null {
  const { VERCEL_GIT_REPO_OWNER: owner, VERCEL_GIT_REPO_SLUG: repo, VERCEL_GIT_COMMIT_SHA: sha } = process.env;
  if (!owner || !repo || !sha) return null;
  return `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/collector-dist/${app}.exe`;
}

/** GET handler body: { version } read from the built .exe, so apps only update once the new build is live. */
export async function versionResponse(app: AppName) {
  try {
    const stat = await fs.stat(exePath(app));
    const hit = cache.get(app);
    if (!hit || hit.mtime !== stat.mtimeMs) cache.set(app, { mtime: stat.mtimeMs, version: productVersion(await fs.readFile(exePath(app))) });
    return NextResponse.json(
      { version: cache.get(app)!.version, download: githubDownload(app) },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json({ version: "" }, { headers: { "Cache-Control": "no-store" } });
  }
}

/** GET handler body: the .exe with this site's settings attached. */
export async function downloadResponse(app: AppName, req: Request) {
  let exe: Buffer;
  try {
    exe = await fs.readFile(exePath(app));
  } catch {
    return new Response("This app hasn't been built yet. Try again in a few minutes.", { status: 503 });
  }
  let key: string;
  try {
    key = await ingestKey();
  } catch (e) {
    return new Response(`The site's database isn't connected yet: ${(e as Error).message}`, { status: 500 });
  }
  const config = { site_url: siteUrl(req), ingest_key: key, min_players: 2 };
  const trailer = Buffer.from(`\n#CUSTY-CONFIG#${JSON.stringify(config)}#END-CUSTY-CONFIG#`, "utf8");
  const body = Buffer.concat([exe, trailer]);
  return new Response(new Uint8Array(body), {
    headers: {
      "Content-Type": "application/vnd.microsoft.portable-executable",
      "Content-Disposition": `attachment; filename="${app}.exe"`,
      "Content-Length": String(body.length),
      "Cache-Control": "no-store",
    },
  });
}

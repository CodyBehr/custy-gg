// GET /api/collector/windows -> custy-collector.exe, linked to this site.
// The .exe is built by .github/workflows/build-collector.yml. This site's
// address and upload key are attached to the end of the file, where the app
// reads them on first launch.

import fs from "node:fs/promises";
import path from "node:path";
import { ingestKey, siteUrl } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const EXE = path.join(process.cwd(), "collector-dist", "custy-collector.exe");

export async function GET(req: Request) {
  let exe: Buffer;
  try {
    exe = await fs.readFile(EXE);
  } catch {
    return new Response("The Windows app hasn't been built yet. Use the zip download for now.", { status: 503 });
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
      "Content-Disposition": 'attachment; filename="custy-collector.exe"',
      "Content-Length": String(body.length),
      "Cache-Control": "no-store",
    },
  });
}

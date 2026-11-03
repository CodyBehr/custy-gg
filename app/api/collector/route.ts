// GET /api/collector -> custy-collector.zip, already set up for this site.

import { strToU8, zipSync, type Zippable } from "fflate";
import { COLLECTOR_FILES } from "@/lib/collector-files";
import { ingestKey, siteUrl } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";

const README = (site: string) => `custy.gg collector
==================

This uploads your League custom games to ${site}

Windows
  1. Install Python from https://www.python.org/downloads/
     On the first installer screen, tick "Add python.exe to PATH".
  2. Move this folder somewhere permanent, like Documents.
  3. Open League, then double-click windows-test.bat. You should see three [ok] lines.
  4. Double-click windows-autostart-on.bat. Done: it now runs hidden whenever
     you log in to Windows and uploads custom games after they end.

  To turn it off, run windows-autostart-off.bat.
  Everything it does is written to collector.log in this folder.

Mac
  Install Python 3, then in Terminal run:  bash mac-autostart-on.sh
`;

export async function GET(req: Request) {
  const site = siteUrl(req);
  let key: string;
  try {
    key = await ingestKey();
  } catch (e) {
    return new Response(`The site's database isn't connected yet: ${(e as Error).message}`, { status: 500 });
  }

  const config = { site_url: site, ingest_key: key, league_path: "", min_players: 2 };
  const files: Zippable = {};
  for (const [name, text] of Object.entries(COLLECTOR_FILES)) {
    if (name === "config.example.json") continue;
    // Windows batch files misbehave with Unix line endings.
    const body = name.endsWith(".bat") ? text.replace(/\r?\n/g, "\r\n") : text;
    files[`custy-collector/${name}`] = strToU8(body);
  }
  files["custy-collector/config.json"] = strToU8(JSON.stringify(config, null, 2) + "\n");
  files["custy-collector/README.txt"] = strToU8(README(site).replace(/\n/g, "\r\n"));

  const zip = zipSync(files, { level: 6 });
  return new Response(new Uint8Array(zip), {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": 'attachment; filename="custy-collector.zip"',
      "Cache-Control": "no-store",
    },
  });
}

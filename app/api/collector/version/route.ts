// GET /api/collector/version -> { version } of the Windows app this site serves.
// Read from the .exe itself, so the app only updates once the new build is live.

import fs from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const EXE = path.join(process.cwd(), "collector-dist", "custy-collector.exe");
let cached: { mtime: number; version: string } | null = null;

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

export async function GET() {
  try {
    const stat = await fs.stat(EXE);
    if (!cached || cached.mtime !== stat.mtimeMs) {
      cached = { mtime: stat.mtimeMs, version: productVersion(await fs.readFile(EXE)) };
    }
    return NextResponse.json({ version: cached.version }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ version: "" }, { headers: { "Cache-Control": "no-store" } });
  }
}

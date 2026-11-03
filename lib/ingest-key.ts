// The secret the collector sends with each upload. If INGEST_KEY is set in the
// environment that's used; otherwise the site makes one up the first time it's
// needed and keeps it in the database, so there's nothing to configure.

import "server-only";
import { safeEqual } from "./auth";
import { store } from "./store";

export async function ingestKey(): Promise<string> {
  const fromEnv = process.env.INGEST_KEY?.trim();
  if (fromEnv) return fromEnv;
  const s = store();
  const existing = await s.getSetting("ingest_key");
  if (existing) return existing;
  const fresh = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
  return s.initSetting("ingest_key", fresh);
}

/** Checks the collector's "Authorization: Bearer <key>" header. */
export async function checkIngestKey(header: string | null): Promise<boolean> {
  const given = (header ?? "").replace(/^Bearer\s+/i, "").trim();
  if (!given) return false;
  return safeEqual(given, await ingestKey());
}

/** The site's public address, used in the collector's config. */
export function siteUrl(req: Request): string {
  if (process.env.NEXT_PUBLIC_SITE_URL) return process.env.NEXT_PUBLIC_SITE_URL.replace(/\/$/, "");
  // On Vercel, prefer the production domain: preview URLs sit behind Vercel's login.
  if (process.env.VERCEL_PROJECT_PRODUCTION_URL) return `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`;
  const h = req.headers;
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  return `${proto}://${host}`;
}

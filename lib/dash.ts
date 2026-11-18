// The private data dashboard (/data): only for whoever knows DASHBOARD_KEY (set in Vercel). Without it set, /data
// doesn't exist.
import { cookies } from "next/headers";
import { safeEqual, sha256 } from "@/lib/auth";

export const DASH_COOKIE = "custy_dash";

export async function dashToken(): Promise<string | null> {
  const k = process.env.DASHBOARD_KEY;
  return k ? sha256(`custy.gg-dash:${k}`) : null;
}

export async function dashAllowed(): Promise<boolean> {
  const t = await dashToken();
  if (!t) return false;
  const c = (await cookies()).get(DASH_COOKIE)?.value ?? "";
  return !!c && safeEqual(c, t);
}

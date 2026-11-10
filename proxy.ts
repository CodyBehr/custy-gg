// If SITE_PASSWORD is set, everyone has to enter it once before seeing the site.
// Endpoints that programs call (the collector app, Discord, Vercel cron) are left open:
// they can't type a password, and each checks its own key or signature.

import { NextResponse, type NextRequest } from "next/server";
import { AUTH_COOKIE, passwordToken, safeEqual } from "@/lib/auth";

// /api/discord itself is Discord's signed requests; /api/discord/register and /webhook are the setup forms and stay behind the password.
const OPEN = /^\/api\/(timeline|lobby|ranks|collector\/version|cron\/weekly|discord)\/?$/;

export async function proxy(req: NextRequest) {
  const expected = await passwordToken();
  if (!expected) return NextResponse.next();
  const path = req.nextUrl.pathname;
  if (OPEN.test(path)) return NextResponse.next();
  // The agent API has its own key; without one it stays behind the password.
  if (path.startsWith("/api/agent") && process.env.AGENT_API_KEY) return NextResponse.next();
  const cookie = req.cookies.get(AUTH_COOKIE)?.value ?? "";
  if (cookie && safeEqual(cookie, expected)) return NextResponse.next();

  const login = new URL("/login", req.url);
  login.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api/ingest|api/admin|api/login|api/review|login|benchmarks/|_next/|favicon|icon).*)"],
};

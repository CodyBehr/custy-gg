// If SITE_PASSWORD is set, everyone has to enter it once before seeing the site.
// The collector's upload endpoint is left open; it checks INGEST_KEY itself.

import { NextResponse, type NextRequest } from "next/server";
import { AUTH_COOKIE, passwordToken, safeEqual } from "@/lib/auth";

export async function proxy(req: NextRequest) {
  const expected = await passwordToken();
  if (!expected) return NextResponse.next();
  const cookie = req.cookies.get(AUTH_COOKIE)?.value ?? "";
  if (cookie && safeEqual(cookie, expected)) return NextResponse.next();

  const login = new URL("/login", req.url);
  login.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api/ingest|api/admin|api/login|login|benchmarks/|_next/|favicon|icon).*)"],
};

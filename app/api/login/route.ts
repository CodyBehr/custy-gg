import { NextResponse } from "next/server";
import { AUTH_COOKIE, passwordToken, safeEqual, sha256 } from "@/lib/auth";

export async function POST(req: Request) {
  const form = await req.formData();
  const password = String(form.get("password") ?? "");
  const next = String(form.get("next") ?? "/");
  const dest = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const expected = await passwordToken();
  const base = new URL(req.url);

  if (!expected) return NextResponse.redirect(new URL(dest, base), 303);
  const given = await sha256(`custy.gg:${password}`);
  if (!safeEqual(given, expected)) {
    const back = new URL("/login", base);
    back.searchParams.set("next", dest);
    back.searchParams.set("wrong", "1");
    return NextResponse.redirect(back, 303);
  }
  const res = NextResponse.redirect(new URL(dest, base), 303);
  res.cookies.set(AUTH_COOKIE, expected, {
    httpOnly: true,
    sameSite: "lax",
    secure: base.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  return res;
}

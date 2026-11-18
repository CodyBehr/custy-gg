import { NextResponse } from "next/server";
import { sha256, safeEqual } from "@/lib/auth";
import { DASH_COOKIE, dashToken } from "@/lib/dash";

export async function POST(req: Request) {
  const form = await req.formData();
  const t = await dashToken();
  const base = new URL(req.url);
  const given = await sha256(`custy.gg-dash:${String(form.get("password") ?? "")}`);
  if (!t || !safeEqual(given, t)) return NextResponse.redirect(new URL("/data/enter?wrong=1", base), 303);
  const res = NextResponse.redirect(new URL("/data", base), 303);
  res.cookies.set(DASH_COOKIE, t, { httpOnly: true, sameSite: "lax", secure: base.protocol === "https:", path: "/", maxAge: 60 * 60 * 24 * 365 });
  return res;
}

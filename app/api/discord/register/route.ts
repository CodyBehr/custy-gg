// Registers the slash commands with Discord. The client secret is used once
// and never stored.

import { NextResponse } from "next/server";
import { DISCORD_APP_ID, registerCommands } from "@/lib/discord";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const form = await req.formData();
  const secret = String(form.get("secret") ?? "").trim();
  const back = new URL("/discord", req.url);
  if (!DISCORD_APP_ID) back.searchParams.set("error", "DISCORD_APP_ID isn't set on the site yet.");
  else if (!secret) back.searchParams.set("error", "Paste the client secret first.");
  else {
    try {
      const names = await registerCommands(DISCORD_APP_ID, secret);
      back.searchParams.set("ok", names.map((n) => `/${n}`).join(", "));
    } catch (e) {
      back.searchParams.set("error", (e as Error).message);
    }
  }
  return NextResponse.redirect(back, 303);
}

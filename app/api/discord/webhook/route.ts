// Saves (or removes) the Discord channel webhook that new games are posted to.

import { NextResponse } from "next/server";
import { getWebhook, isWebhookUrl, postGame, setWebhook } from "@/lib/game-post";
import { siteUrl } from "@/lib/ingest-key";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const form = await req.formData();
  const back = new URL("/discord", req.url);
  const done = () => NextResponse.redirect(back, 303);

  if (form.get("remove")) {
    await setWebhook(null);
    back.searchParams.set("ok_post", "Stopped posting games to Discord.");
    return done();
  }
  if (form.get("test")) {
    const hook = await getWebhook();
    if (!hook) back.searchParams.set("error", "Add a channel link first.");
    else {
      // Re-post the most recent game so you can see exactly what a game post looks like.
      const r = await postGame("latest", siteUrl(req), null, { test: true });
      if (r.ok) back.searchParams.set("ok_post", "Posted your most recent game to the channel as a test.");
      else back.searchParams.set("error", `Discord didn't accept the test message (${r.status}).`);
    }
    return done();
  }

  const url = String(form.get("webhook") ?? "").trim();
  if (!isWebhookUrl(url)) {
    back.searchParams.set("error", "That doesn't look like a Discord webhook link. It starts with https://discord.com/api/webhooks/");
    return done();
  }
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "custy.gg", content: "custy.gg is connected. Finished custom games will be posted here." }) });
  if (!r.ok) {
    back.searchParams.set("error", `Discord didn't accept that link (${r.status}). Copy it again from the channel's Webhooks settings.`);
    return done();
  }
  await setWebhook(url);
  console.log("[post] webhook saved");
  back.searchParams.set("ok_post", "Connected. Finished games will be posted to that channel.");
  return done();
}

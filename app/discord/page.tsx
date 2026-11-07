import type { Metadata } from "next";
import { headers } from "next/headers";
import { DISCORD_APP_ID, DISCORD_PUBLIC_KEY, inviteUrl } from "@/lib/discord";
import { getWebhook } from "@/lib/game-post";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Discord bot" };

type Props = { searchParams: Promise<{ ok?: string; ok_post?: string; error?: string }> };

export default async function DiscordSetup({ searchParams }: Props) {
  const { ok, ok_post, error } = await searchParams;
  const posting = Boolean(await getWebhook().catch(() => null));
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "custy-gg.vercel.app";
  const endpoint = `https://${host}/api/discord`;
  const ready = Boolean(DISCORD_APP_ID && DISCORD_PUBLIC_KEY);

  return (
    <>
      <div className="head">
        <div>
          <h1>Discord bot</h1>
          <p>
            Type <code>/custy_teams</code> in your server to split the current custom lobby into two balanced teams, or{" "}
            <code>/custy_player</code> to look someone up. The bot runs on this site, so there&apos;s nothing else to host.
          </p>
        </div>
      </div>

      {ok ? <p className="panel" style={{ padding: "14px 18px", marginBottom: 18 }}>Commands registered: <b>{ok}</b>. They can take a minute to show up in Discord.</p> : null}
      {ok_post ? <p className="panel" style={{ padding: "14px 18px", marginBottom: 18 }}>{ok_post}</p> : null}
      {error ? <p className="panel err" style={{ padding: "14px 18px", marginBottom: 18 }}>{error}</p> : null}

      <div className="cols">
        <section className="panel" style={{ padding: "24px 26px" }}>
          <ol className="steps">
            <li>
              <b>Connect the app.</b>{" "}
              {ready ? (
                <span className="win-t">Done: this site knows your Discord app ({DISCORD_APP_ID}).</span>
              ) : (
                <>Not yet. The site needs <code>DISCORD_APP_ID</code> and <code>DISCORD_PUBLIC_KEY</code> from the Discord Developer Portal.</>
              )}
            </li>
            <li>
              <b>Point Discord at this site.</b> In the Developer Portal, on the app&apos;s General Information page, set{" "}
              <i>Interactions Endpoint URL</i> to <code>{endpoint}</code> and save.
            </li>
            <li>
              <b>Register the commands.</b> Paste the app&apos;s <b>bot token</b> (Developer Portal, <i>Bot</i>, <i>Reset Token</i>)
              or its client secret (<i>OAuth2</i> page). It&apos;s used once and not saved.
              <form method="post" action="/api/discord/register" className="secret-form">
                <input type="password" name="secret" placeholder="Bot token or client secret" aria-label="Discord bot token or client secret" autoComplete="off" required />
                <button className="btn" type="submit" disabled={!ready}>Register commands</button>
              </form>
            </li>
            <li>
              <b>Add it to your server.</b>{" "}
              {ready ? <a className="btn ghost" href={inviteUrl(DISCORD_APP_ID)} target="_blank" rel="noopener noreferrer">Add to Discord</a> : "The button appears once step 1 is done."}
            </li>
          </ol>
          <h2 id="post-games" style={{ fontSize: 22, margin: "34px 0 6px" }}>Post finished games to a channel</h2>
          {posting ? (
            <>
              <p className="win-t" style={{ margin: "0 0 12px" }}>On: every new game is posted with the result, MVP and rating changes.</p>
              <form method="post" action="/api/discord/webhook" className="row" style={{ gap: 8 }}>
                <button className="btn ghost" type="submit" name="test" value="1">Send a test message</button>
                <button className="btn ghost" type="submit" name="remove" value="1">Stop posting</button>
              </form>
              <p className="sub" style={{ marginTop: 12 }}>To switch channels, paste a new link below.</p>
            </>
          ) : (
            <p className="sub" style={{ margin: "0 0 12px" }}>
              In Discord, open the channel&apos;s settings (the gear next to its name), then <i>Integrations</i>,{" "}
              <i>Webhooks</i>, <i>New Webhook</i>, and <i>Copy Webhook URL</i>. Paste it here.
            </p>
          )}
          <form method="post" action="/api/discord/webhook" className="secret-form">
            <input type="password" name="webhook" placeholder="https://discord.com/api/webhooks/..." aria-label="Discord channel webhook link" autoComplete="off" required />
            <button className="btn" type="submit">{posting ? "Switch channel" : "Start posting"}</button>
          </form>
        </section>
        <aside>
          <section className="panel" style={{ padding: "18px 20px" }}>
            <b>Commands</b>
            <ul className="notes">
              <li><code>/custy_teams</code> splits whoever is in the custom lobby. Someone in the lobby needs the custy.gg app running.</li>
              <li><code>balance</code>: custy rating (default), solo queue rank, or random.</li>
              <li><code>players: Ringo, Sevi, ...</code> uses your list instead of the lobby.</li>
              <li><code>together: Ringo, Sevi</code> keeps them on one team; <code>apart: Vender, Leaden</code> splits them. Separate groups with <code>;</code>.</li>
              <li><code>add</code> and <code>remove</code> tweak the lobby list.</li>
              <li>Hit <b>Reroll</b> for a different split with the same rules.</li>
              <li><code>/custy_lobby</code> shows who&apos;s in the lobby with ratings and ranks.</li>
              <li><code>/custy_player</code> shows someone&apos;s stats.</li>
              <li>Hit <b>Captain draft</b> under a team split to have two captains pick teams instead.</li>
            </ul>
          </section>
        </aside>
      </div>
    </>
  );
}

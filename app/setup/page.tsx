import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Add your games" };

const hasWindowsApp = () => fs.existsSync(path.join(process.cwd(), "collector-dist", "custy-collector.exe"));

export default async function Setup() {
  let games: number | null = null;
  try {
    games = await store().count();
  } catch {
    games = null;
  }
  const windows = hasWindowsApp();

  return (
    <>
      <div className="head">
        <div>
          <h1>Add your games</h1>
          <p>
            Custom games reach this site through a small app that runs in the background on your computer. It reads
            finished custom games from the League client and uploads them. Only one person per game needs it, but the
            more of you run it, the fewer games get missed.
          </p>
          <p className="muted">
            Looking for game reviews of your ranked games? That&apos;s a separate app now: <a href="/coach">custy coach</a>.
          </p>
        </div>
      </div>

      {games === null ? (
        <div className="panel empty">
          <h2>Database not connected</h2>
          <p>Connect a Postgres database to this project in Vercel (Storage tab), then redeploy.</p>
        </div>
      ) : (
        <div className="cols">
          <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            {windows ? (
              <section className="panel" style={{ padding: "24px 26px" }}>
                <h2 className="section-title">Windows</h2>
                <ol className="steps">
                  <li>
                    <b>Download the app.</b> It&apos;s already linked to this site.
                    <div style={{ marginTop: 12 }}>
                      <a className="btn" href="/api/collector/windows" download>Download custy-collector.exe</a>
                    </div>
                  </li>
                  <li>
                    <b>Double-click it.</b> If Windows shows &ldquo;Windows protected your PC&rdquo;, click{" "}
                    <i>More info</i>, then <i>Run anyway</i>. That warning appears for any app that isn&apos;t from a big
                    publisher.
                  </li>
                  <li>
                    <b>That&apos;s it.</b> A message confirms it&apos;s installed. It runs quietly in the background and starts
                    with Windows, so there&apos;s nothing to keep open.
                  </li>
                </ol>
              </section>
            ) : null}

            <section className="panel" style={{ padding: "24px 26px" }}>
              <h2 className="section-title">{windows ? "Mac, or run it with Python" : "Set it up"}</h2>
              <ol className="steps">
                <li>
                  <b>Install Python</b> from <a className="win-t" href="https://www.python.org/downloads/">python.org/downloads</a>.
                  On Windows, tick <i>Add python.exe to PATH</i> on the first installer screen.
                </li>
                <li>
                  <b>Download the collector</b> and unzip it somewhere permanent, like your Documents folder. It&apos;s
                  already set up for this site.
                  <div style={{ marginTop: 12 }}>
                    <a className={windows ? "btn ghost" : "btn"} href="/api/collector" download>Download custy-collector.zip</a>
                  </div>
                </li>
                <li>
                  <b>Turn it on.</b> On a Mac, run <code>bash mac-autostart-on.sh</code> in Terminal from that folder. On
                  Windows, open League, then double-click <code>windows-autostart-on.bat</code>.
                </li>
              </ol>
            </section>
          </div>
          <aside>
            <section className="panel" style={{ padding: "18px 20px" }}>
              <b>Good to know</b>
              <ul className="notes">
                <li>On the first run it also uploads the custom games still in your recent match history.</li>
                <li>It only reads match history. It doesn&apos;t touch the game, and never sends your password.</li>
                <li>
                  {windows
                    ? "To update or remove the Windows app, run the download again and pick Yes (update) or No (remove)."
                    : <>To stop it, run <code>windows-autostart-off.bat</code>.</>}
                </li>
                <li>Keep the download to your group: anyone with it can add games here.</li>
              </ul>
            </section>
          </aside>
        </div>
      )}
    </>
  );
}

import type { Metadata } from "next";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Add your games" };

export default async function Setup() {
  let games: number | null = null;
  try {
    games = await store().count();
  } catch {
    games = null;
  }

  return (
    <>
      <div className="head">
        <div>
          <h1>Add your games</h1>
          <p>
            Custom games reach this site through a small program that runs in the background on your computer. It reads
            finished custom games from the League client and uploads them. Only one person per game needs it, but the
            more of you run it, the fewer games get missed.
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
          <section className="panel" style={{ padding: "24px 26px" }}>
            <ol className="steps">
              <li>
                <b>Install Python</b> from <a className="win-t" href="https://www.python.org/downloads/">python.org/downloads</a>.
                On the first installer screen, tick <i>Add python.exe to PATH</i>.
              </li>
              <li>
                <b>Download the collector</b> and unzip it somewhere permanent, like your Documents folder. It&apos;s already
                set up for this site.
                <div style={{ marginTop: 12 }}>
                  <a className="btn" href="/api/collector" download>Download custy-collector.zip</a>
                </div>
              </li>
              <li>
                <b>Open League</b>, then double-click <code>windows-test.bat</code> in the folder. You should see three
                lines starting with <code>[ok]</code>.
              </li>
              <li>
                <b>Double-click <code>windows-autostart-on.bat</code>.</b> That&apos;s it. It now runs hidden whenever you log
                in to Windows, and games show up here about 20 seconds after they end.
              </li>
            </ol>
          </section>
          <aside>
            <section className="panel" style={{ padding: "18px 20px" }}>
              <b>Good to know</b>
              <ul className="notes">
                <li>On the first run it also uploads the custom games still in your recent match history.</li>
                <li>It only reads match history. It doesn&apos;t touch the game, and never sends your password.</li>
                <li>To stop it, run <code>windows-autostart-off.bat</code>.</li>
                <li>On a Mac, run <code>bash mac-autostart-on.sh</code> in Terminal instead.</li>
                <li>Keep the download to your group: anyone with it can add games here.</li>
              </ul>
            </section>
          </aside>
        </div>
      )}
    </>
  );
}

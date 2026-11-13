import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "custy coach" };

const hasApp = () => fs.existsSync(path.join(process.cwd(), "collector-dist", "custy-coach.exe"));

const FEATURES: [string, string][] = [
  ["Moments to watch", "Your lane gold against your opponent minute by minute, the swings, early deaths and timings that cost you, each with a button that opens your replay at that moment."],
  ["Breakdown against experts", "The same game next to high-elo players on your champion and role: CS, gold, levels, build order, backs and first clear."],
  ["Lane trades", "Every trade with your lane opponent from 1:30 to 14:00, read from your replay file: damage each way, who started it, HP going in, ability order, and a playback on the map."],
  ["Champ select helper", "Pops up during champ select with what high-elo players run in your matchup: runes, summoner spells and items, one click to apply."],
  ["Matchup guide", "Pick a champion and an opponent before you queue to see how experts play it."],
];

export default function Coach() {
  const app = hasApp();
  return (
    <>
      <div className="head">
        <div>
          <h1>custy coach</h1>
          <p>
            A separate app from the custom-game tracker. It reviews your ranked and normal games on Summoner&apos;s Rift
            after you play them, and shows where to improve. Everything runs on your computer; nothing about your
            games is posted to this site.
          </p>
        </div>
      </div>

      <div className="cols">
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <section className="panel" style={{ padding: "24px 26px" }}>
            <h2 className="section-title">Get it (Windows)</h2>
            {app ? (
              <ol className="steps">
                <li>
                  <b>Download custy coach.</b>
                  <div style={{ marginTop: 12 }}>
                    <a className="btn" href="/api/coach/windows" download>Download custy-coach.exe</a>
                  </div>
                </li>
                <li>
                  <b>Double-click it.</b> If Windows shows &ldquo;Windows protected your PC&rdquo;, click <i>More info</i>,
                  then <i>Run anyway</i>.
                </li>
                <li>
                  <b>Open it</b> from the icon next to the clock or from the Start menu (&ldquo;custy coach&rdquo;). It starts
                  with Windows and updates itself.
                </li>
              </ol>
            ) : (
              <p className="muted">The app is being built. Check back in a few minutes.</p>
            )}
            <p className="muted" style={{ marginTop: 14 }}>
              Already use the custy.gg collector for custom games? Keep it: the two apps run side by side. Your saved
              reviews move over to custy coach the first time you install it.
            </p>
          </section>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <section className="panel" style={{ padding: "24px 26px" }}>
            <h2 className="section-title">What it does</h2>
            <ul className="steps" style={{ listStyle: "none", paddingLeft: 0 }}>
              {FEATURES.map(([t, d]) => (
                <li key={t} style={{ marginBottom: 12 }}>
                  <b>{t}.</b> {d}
                </li>
              ))}
            </ul>
            <p className="muted">
              Lane trades need the game&apos;s replay; the app downloads it through the League client when you ask.
              League only keeps replays for the current patch. custy coach reads replay files after the game and never
              touches the game while you play.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}

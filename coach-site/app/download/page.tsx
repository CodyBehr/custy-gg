import type { Metadata } from "next";
import { BRAND, DOWNLOAD_URL } from "@/lib/brand";

export const metadata: Metadata = { title: "Download the app" };

const FEATURES: [string, string][] = [
  ["Moments to watch", "Your lane gold against your opponent minute by minute, the swings and early deaths that cost you, each with a button that opens your replay at that moment."],
  ["Lane trades", "Every trade with your lane opponent from 1:30 to 14:00, read from your replay: damage each way, who started it, and a playback on the map."],
  ["Gank and caught-out checks", "Every death that wasn't a fair fight: where the enemies were last seen, what your team could see, and a playback of the lead-up."],
  ["Breakdown against experts", "The same game next to Master+ players on your champion and role: CS, gold, levels, build order, backs and first clear."],
  ["Matchup guide", "Before and during champ select: what high-elo players run in your matchup, one click to apply."],
];

export default async function Download({ searchParams }: { searchParams: Promise<{ game?: string }> }) {
  const { game } = await searchParams;
  return (
    <>
      <section className="dl-hero">
        <div>
          <h1>Review every game you play.</h1>
          <p>
            {BRAND} runs next to League on your PC. After each game it reads your replay and match data and shows the
            moments that decided it. Free during the beta.
          </p>
          {game && (
            <p className="note">
              To review game <b>{game}</b>, install the app and open it while signed in to the League client: your
              recent games show up on their own.
            </p>
          )}
          <div style={{ marginTop: 22, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <a className="btn" href={DOWNLOAD_URL}>Download for Windows</a>
          </div>
          <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>Windows 10 or 11 with League of Legends installed.</p>
        </div>
        <div className="panel">
          <h2>Install</h2>
          <ol className="steps">
            <li><b>Download</b> the app and double-click it.</li>
            <li>
              Beta builds aren&apos;t code-signed yet, so Windows may show &ldquo;Windows protected your PC&rdquo;. Click{" "}
              <i>More info</i>, then <i>Run anyway</i>.
            </li>
            <li><b>Open it</b> from the icon next to the clock or the Start menu. It starts with Windows and updates itself.</li>
          </ol>
          <p className="note">
            It reads your games from the League client on your own PC. It never reads game memory and shows nothing
            during your games.
          </p>
        </div>
      </section>

      <div className="cards">
        {FEATURES.map(([t, d]) => (
          <div className="card" key={t}>
            <h3>{t}</h3>
            <p>{d}</p>
          </div>
        ))}
      </div>
    </>
  );
}

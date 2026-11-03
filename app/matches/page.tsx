import type { Metadata } from "next";
import { getStatic } from "@/lib/ddragon";
import { getDataset } from "@/lib/stats";
import { Empty, GameRow, when } from "@/components/ui";
import type { Match } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Matches" };

export default async function Matches() {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  if (!d.matches.length) {
    return (<><div className="head"><h1>Matches</h1></div><Empty /></>);
  }

  // Group games into nights. A game after 4am counts toward that day,
  // so a session running past midnight stays together.
  const nights = new Map<string, Match[]>();
  for (const m of d.matches) {
    const key = when(m.playedAt - 4 * 3600_000).long;
    nights.set(key, [...(nights.get(key) ?? []), m]);
  }

  return (
    <>
      <div className="head">
        <div>
          <h1>Matches</h1>
          <p>{d.matches.length} custom games over {nights.size} game nights.</p>
        </div>
      </div>
      {[...nights].map(([night, games]) => (
        <section key={night}>
          <div className="night">
            <h2>{night}</h2>
            <span className="sub">{games.length} game{games.length > 1 ? "s" : ""}</span>
          </div>
          <div className="games">
            {games.map((m) => <GameRow key={m.id} s={s} m={m} mvp={d.mvpOf.get(m.id)} />)}
          </div>
        </section>
      ))}
    </>
  );
}

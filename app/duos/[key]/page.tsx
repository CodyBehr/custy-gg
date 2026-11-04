import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { champName, getStatic, img } from "@/lib/ddragon";
import { getDataset } from "@/lib/stats";
import { Champ, GameRow, Img, WinRate, ratio, Pct, kdaTone } from "@/components/ui";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ key: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { key } = await params;
  const d = (await getDataset()).duos.find((x) => x.key === decodeURIComponent(key));
  return { title: d ? `${d.a.name} & ${d.b.name}` : "Duo" };
}

export default async function DuoPage({ params }: Props) {
  const { key } = await params;
  const [data, s] = await Promise.all([getDataset(), getStatic()]);
  const d = data.duos.find((x) => x.key === decodeURIComponent(key));
  if (!d) notFound();

  const ids = new Set(d.matchIds);
  const games = data.matches.filter((m) => ids.has(m.id));
  const minutes = Math.max(1, d.minutes);
  // How each of them does apart, for comparison.
  const pa = data.byPuuid.get(d.a.puuid);
  const pb = data.byPuuid.get(d.b.puuid);
  const apart = (p: typeof pa) => {
    if (!p) return null;
    const games = p.games - d.games;
    const wins = p.wins - d.wins;
    return games > 0 ? { games, wins } : null;
  };

  return (
    <>
      <section className="duo-head">
        <div className="pair big" style={{ width: 150 }}>
          <Img src={img.icon(s, d.a.profileIcon)} size={92} alt="" round />
          <Img src={img.icon(s, d.b.profileIcon)} size={92} alt="" round />
        </div>
        <div style={{ minWidth: 0 }}>
          <h1 className="duo-title">
            <Link href={`/players/${encodeURIComponent(d.a.puuid)}`}>{d.a.name}</Link>{" "}
            <span className="amp">&amp;</span>{" "}
            <Link href={`/players/${encodeURIComponent(d.b.puuid)}`}>{d.b.name}</Link>
          </h1>
          <p className="muted" style={{ marginTop: 8 }}><Link href="/duos" className="win-t">All duos</Link></p>
        </div>
      </section>

      <div className="facts">
        <div className="fact"><div className="v">{d.wins}–{d.games - d.wins}</div><div className="k">{Math.round((d.wins / d.games) * 100)}% win rate together</div></div>
        <div className="fact"><div className={`v ${kdaTone(d.kills, d.deaths, d.assists)}`}>{ratio(d.kills, d.deaths, d.assists)}</div><div className="k">Combined KDA</div></div>
        <div className="fact"><div className="v">{(d.kills / d.games).toFixed(1)}</div><div className="k">Kills per game between them</div></div>
        <div className="fact"><div className="v">{Math.round(d.damage / minutes)}</div><div className="k">Damage per minute between them</div></div>
        <div className="fact"><div className="v">{d.ratingSum >= 0 ? "+" : "−"}{Math.abs(d.ratingSum)}</div><div className="k">Rating gained together</div></div>
        <div className="fact"><div className="v">{d.mvps}</div><div className="k">Games one of them was MVP</div></div>
      </div>

      <div className="cols">
        <section>
          <h2 className="section-title">Games together</h2>
          <div className="games">
            {games.map((m) => <GameRow key={m.id} s={s} m={m} mvp={data.mvpOf.get(m.id)} />)}
          </div>
        </section>
        <aside>
          <section>
            <h2 className="section-title">Champion combos</h2>
            <div className="panel list">
              {d.combos.slice(0, 8).map((c) => (
                <div key={c.champs.join("-")} className="li">
                  <Champ s={s} id={c.champs[0]} size={30} />
                  <Champ s={s} id={c.champs[1]} size={30} />
                  <div className="grow ellip sub">{champName(s, c.champs[0])} and {champName(s, c.champs[1])}</div>
                  <span style={{ textAlign: "right" }}><Pct wins={c.wins} games={c.games} /> <span className="sub">{c.wins}W {c.games - c.wins}L</span></span>
                </div>
              ))}
            </div>
          </section>
          <section>
            <h2 className="section-title">Together vs. apart</h2>
            <div className="panel list">
              <div className="li">
                <div className="grow stack"><b>Together</b><span className="sub">{d.games} games</span></div>
                <div style={{ width: 150 }}><WinRate wins={d.wins} games={d.games} /></div>
              </div>
              {[{ p: d.a, r: apart(pa) }, { p: d.b, r: apart(pb) }].map(({ p, r }) => (
                <div key={p.puuid} className="li">
                  <div className="grow stack" style={{ minWidth: 0 }}><b className="ellip">{p.name} alone</b><span className="sub">{r ? r.games : 0} games without the other</span></div>
                  <div style={{ width: 150 }}>{r ? <WinRate wins={r.wins} games={r.games} /> : <span className="sub">No games apart</span>}</div>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

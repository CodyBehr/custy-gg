import Link from "next/link";
import type { Metadata } from "next";
import { champName, getStatic, img, type Static } from "@/lib/ddragon";
import { adjustedWinRate, getDataset, kda, type DuoSummary } from "@/lib/stats";
import { Champ, Empty, Img, WinRate, ago, ratio } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Duos" };

type Props = { searchParams: Promise<{ sort?: string; min?: string; player?: string }> };

const SORTS: Record<string, { label: string; value: (d: DuoSummary) => number }> = {
  best: { label: "Best win rate", value: (d) => adjustedWinRate(d.wins, d.games) },
  games: { label: "Most games", value: (d) => d.games },
  kda: { label: "Highest KDA", value: (d) => kda(d.kills, d.deaths, d.assists) },
  rating: { label: "Most rating gained", value: (d) => d.ratingSum },
  score: { label: "Best performance", value: (d) => d.scoreSum / d.games },
};

export default async function Duos({ searchParams }: Props) {
  const { sort = "best", min, player } = await searchParams;
  const [data, s] = await Promise.all([getDataset(), getStatic()]);
  if (!data.duos.length) return (<><div className="head"><h1>Duos</h1></div><Empty /></>);

  const most = data.duos[0].games;
  const defaultMin = most >= 5 ? 3 : most >= 2 ? 2 : 1;
  const minGames = Math.max(1, Number(min) || defaultMin);
  const sorter = SORTS[sort] ?? SORTS.best;
  const focus = player ? data.byPuuid.get(player) : undefined;

  const pool = data.duos.filter((d) => d.games >= minGames && (!focus || d.a.puuid === focus.puuid || d.b.puuid === focus.puuid));
  const ranked = [...pool].sort((x, y) => sorter.value(y) - sorter.value(x) || y.games - x.games);
  const worst = [...pool].sort((x, y) => adjustedWinRate(x.wins, x.games) - adjustedWinRate(y.wins, y.games) || y.games - x.games).slice(0, 5);
  const best = [...pool].sort((x, y) => adjustedWinRate(y.wins, y.games) - adjustedWinRate(x.wins, x.games) || y.games - x.games)[0];

  const href = (next: { sort?: string; min?: number; player?: string | null }) => {
    const q = new URLSearchParams();
    const sv = next.sort ?? sort;
    const mv = next.min ?? minGames;
    const pv = next.player === null ? undefined : next.player ?? player;
    if (sv !== "best") q.set("sort", sv);
    if (mv !== defaultMin) q.set("min", String(mv));
    if (pv) q.set("player", pv);
    const qs = q.toString();
    return qs ? `/duos?${qs}` : "/duos";
  };

  return (
    <>
      <div className="head">
        <div>
          <h1>Duos</h1>
          <p>
            Every pair of players who were on the same team, in any roles. Ranked by win rate together, adjusted so a pair
            that went 1–0 doesn&apos;t outrank one that went 8–2.
          </p>
        </div>
      </div>

      {focus ? (
        <p className="muted" style={{ marginBottom: 16 }}>
          Showing duos with <Link href={`/players/${encodeURIComponent(focus.puuid)}`} className="win-t">{focus.name}</Link>.{" "}
          <Link href={href({ player: null })} className="win-t">Show everyone</Link>
        </p>
      ) : null}

      {best && sort === "best" ? <Spotlight s={s} d={best} /> : null}

      <div className="filters" role="group" aria-label="Sort duos">
        {Object.entries(SORTS).map(([key, def]) => (
          <Link key={key} href={href({ sort: key })} className={sorter === def ? "chip on" : "chip"}>{def.label}</Link>
        ))}
      </div>
      <div className="filters" role="group" aria-label="Minimum games together" style={{ marginBottom: 18 }}>
        {[1, 2, 3, 5, 10].filter((n) => n === 1 || n <= most).map((n) => (
          <Link key={n} href={href({ min: n })} className={minGames === n ? "chip on" : "chip"}>
            {n === 1 ? "Any number of games" : `${n}+ games together`}
          </Link>
        ))}
      </div>

      {ranked.length ? (
        <div className="table-wrap">
          <table className="t duos-t">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Duo</th>
                <th className="num">Games</th>
                <th>Win rate</th>
                <th className="num">KDA together</th>
                <th className="num">Kills/game</th>
                <th className="num">Rating</th>
                <th className="num">MVPs</th>
                <th>Favorite combo</th>
                <th>Last played</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((d, i) => (
                <tr key={d.key}>
                  <td className="num faint">{i + 1}</td>
                  <td>
                    <Link href={`/duos/${encodeURIComponent(d.key)}`} className="row" style={{ gap: 10 }}>
                      <Pair s={s} d={d} size={30} />
                      <span className="stack">
                        <b>{d.a.name} <span className="faint">&amp;</span> {d.b.name}</b>
                        {d.streak >= 2 ? <span className="sub win-t">Won last {d.streak} together</span> : d.streak <= -3 ? <span className="sub loss-t">Lost last {-d.streak} together</span> : null}
                      </span>
                    </Link>
                  </td>
                  <td className="num">{d.games}</td>
                  <td>
                    <WinRate wins={d.wins} games={d.games} />
                    <div className="sub">{d.wins}W {d.games - d.wins}L</div>
                  </td>
                  <td className="num">{ratio(d.kills, d.deaths, d.assists)}</td>
                  <td className="num">{(d.kills / d.games).toFixed(1)}</td>
                  <td className="num"><span className={d.ratingSum >= 0 ? "win-t" : "loss-t"}>{d.ratingSum >= 0 ? "+" : "−"}{Math.abs(d.ratingSum)}</span></td>
                  <td className="num">{d.mvps || <span className="faint">0</span>}</td>
                  <td><Combo s={s} d={d} /></td>
                  <td className="sub">{ago(d.lastPlayed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No duos have played {minGames}+ games together yet. <Link href={href({ min: 1 })} className="win-t">Show all duos</Link></p>
      )}

      {worst.length >= 3 && sort === "best" && pool.length >= 8 ? (
        <section style={{ marginTop: 40 }}>
          <h2 className="section-title">Maybe don&apos;t queue together</h2>
          <div className="panel list">
            {worst.map((d) => (
              <Link key={d.key} href={`/duos/${encodeURIComponent(d.key)}`} className="li">
                <Pair s={s} d={d} size={28} />
                <div className="grow ellip"><b>{d.a.name}</b> <span className="faint">&amp;</span> <b>{d.b.name}</b></div>
                <span className="loss-t" style={{ fontWeight: 700 }}>{d.wins}W {d.games - d.wins}L</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

/** The single best duo, shown big at the top. */
function Spotlight({ s, d }: { s: Static; d: DuoSummary }) {
  const top = d.combos[0];
  return (
    <Link href={`/duos/${encodeURIComponent(d.key)}`} className="panel spotlight">
      <div className="spot-pair">
        <Img src={img.icon(s, d.a.profileIcon)} size={72} alt="" round />
        <Img src={img.icon(s, d.b.profileIcon)} size={72} alt="" round />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="sub gold-t" style={{ fontWeight: 700 }}>Best duo</div>
        <div className="spot-names">{d.a.name} <span className="amp">&amp;</span> {d.b.name}</div>
        <div className="muted" style={{ marginTop: 6 }}>
          {d.wins} wins, {d.games - d.wins} losses together. {ratio(d.kills, d.deaths, d.assists)} KDA,{" "}
          {d.ratingSum >= 0 ? `+${d.ratingSum}` : d.ratingSum} rating.
          {top && top.games > 1 ? ` Favorite combo: ${champName(s, top.champs[0])} and ${champName(s, top.champs[1])}.` : ""}
        </div>
      </div>
      <div className="spot-wr">
        <div className="n win-t">{Math.round((d.wins / d.games) * 100)}%</div>
        <div className="sub">win rate together</div>
      </div>
    </Link>
  );
}

function Pair({ s, d, size }: { s: Static; d: DuoSummary; size: number }) {
  return (
    <span className="pair" style={{ width: size * 1.6 }}>
      <Img src={img.icon(s, d.a.profileIcon)} size={size} alt="" round />
      <Img src={img.icon(s, d.b.profileIcon)} size={size} alt="" round />
    </span>
  );
}

function Combo({ s, d }: { s: Static; d: DuoSummary }) {
  const c = d.combos[0];
  if (!c) return null;
  return (
    <span className="row" style={{ gap: 4 }} title={`${d.a.name} on ${champName(s, c.champs[0])}, ${d.b.name} on ${champName(s, c.champs[1])}`}>
      <Champ s={s} id={c.champs[0]} size={24} />
      <Champ s={s} id={c.champs[1]} size={24} />
      <span className="sub" style={{ marginLeft: 4 }}>{c.wins}W {c.games - c.wins}L</span>
    </span>
  );
}

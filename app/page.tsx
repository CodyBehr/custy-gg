import Link from "next/link";
import { getStatic, img } from "@/lib/ddragon";
import { adjustedWinRate, getDataset, kda, START_RATING } from "@/lib/stats";
import { Champ, Empty, Form, GameRow, Img, WinRate, ago, ratio, kdaTone } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Standings() {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  if (!d.matches.length) {
    return (
      <>
        <div className="head"><h1>Standings</h1></div>
        <Empty />
      </>
    );
  }

  const last = d.matches[0];
  const recent = d.matches.slice(0, 8);

  return (
    <>
      <div className="head">
        <div>
          <h1>Standings</h1>
          <p>
            {d.counted} games played. Last game {ago(last.playedAt)}. Ratings start at {START_RATING} and move after every win and loss,
            more when you beat a stronger team.
          </p>
        </div>
      </div>

      <div className="panel ladder" role="table" aria-label="Standings">
        <div className="rung ladder-head" role="row">
          <span role="columnheader" style={{ textAlign: "right" }}>Rank</span>
          <span role="columnheader">Player</span>
          <span role="columnheader">Rating</span>
          <span role="columnheader">Win rate</span>
          <span role="columnheader">KDA</span>
          <span role="columnheader">Last 10</span>
          <span role="columnheader">Most played</span>
        </div>
        {d.players.map((p, i) => {
          const change = p.ratingHistory.at(-1)?.rating! - (p.ratingHistory.at(-2)?.rating ?? START_RATING);
          return (
            <Link key={p.puuid} href={`/players/${encodeURIComponent(p.puuid)}`} className={`rung${i === 0 ? " first" : ""}`} role="row">
              <span className="place" role="cell">{i + 1}</span>
              <span className="who" role="cell">
                <Img src={img.icon(s, p.profileIcon)} size={44} alt="" round />
                <span style={{ minWidth: 0 }}>
                  <div className="name">{p.name}</div>
                  <div className="tag">#{p.tag}<span style={{ marginLeft: 10 }}>{p.games} games</span></div>
                </span>
              </span>
              <span className="rating" role="cell">
                {p.rating}
                <small className={change >= 0 ? "win-t" : "loss-t"}>{change >= 0 ? "+" : "−"}{Math.abs(change)}<span className="hide-sm"> last game</span></small>
              </span>
              <span role="cell">
                <WinRate wins={p.wins} games={p.games} />
                <div className="sub" style={{ marginTop: 4 }}>{p.wins}W {p.games - p.wins}L</div>
              </span>
              <span className="mini" role="cell">
                <b className={kdaTone(p.kills, p.deaths, p.assists)}>{ratio(p.kills, p.deaths, p.assists)}</b>
                {(p.kills / p.games).toFixed(1)}/{(p.deaths / p.games).toFixed(1)}/{(p.assists / p.games).toFixed(1)}
              </span>
              <span role="cell"><Form results={[...p.form].reverse()} /></span>
              <span className="pool" role="cell">
                {p.champs.slice(0, 3).map((c) => <Champ key={c.championId} s={s} id={c.championId} size={28} />)}
              </span>
            </Link>
          );
        })}
      </div>

      <div className="split">
        <section>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 className="section-title">Recent games</h2>
            <Link href="/matches" className="sub">All {d.matches.length} games</Link>
          </div>
          <div className="games">
            {recent.map((m) => <GameRow key={m.id} s={s} m={m} mvp={d.mvpOf.get(m.id)} />)}
          </div>
        </section>

        <aside>
          <h2 className="section-title">Who&apos;s carrying</h2>
          <div className="panel list">
            {highlights(d).map((h) => (
              <Link key={h.label} href={h.href ?? `/players/${encodeURIComponent(h.puuid)}`} className="li">
                <div className="grow">
                  <div className="label">{h.label}</div>
                  <div className="ellip" style={{ fontWeight: 600 }}>{h.name}</div>
                </div>
                <div className="val">{h.value}</div>
              </Link>
            ))}
          </div>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginTop: 28 }}>
            <h2 className="section-title">Records</h2>
            <Link href="/records" className="sub">All records</Link>
          </div>
          <div className="panel list">
            {d.records.slice(0, 4).map((r) => (
              <Link key={r.label} href={`/matches/${encodeURIComponent(r.matchId)}`} className="li">
                <Champ s={s} id={r.championId} size={36} />
                <div className="grow">
                  <div className="label">{r.label}</div>
                  <div className="ellip" style={{ fontWeight: 600 }}>{r.name}</div>
                </div>
                <div className="val gold-t">{r.display}</div>
              </Link>
            ))}
          </div>
        </aside>
      </div>
    </>
  );
}

/** A few "best at" lines for players with enough games to count. */
function highlights(d: Awaited<ReturnType<typeof getDataset>>) {
  const regulars = d.players.filter((p) => p.games >= Math.min(5, Math.max(1, Math.floor(d.counted / 4))));
  if (!regulars.length) return [];
  const best = <T,>(f: (p: (typeof regulars)[number]) => number) => regulars.reduce((a, b) => (f(b) > f(a) ? b : a));
  const out: { label: string; name: string; puuid: string; value: string; href?: string }[] = [];
  const streak = best((p) => p.streak);
  if (streak.streak >= 2) out.push({ label: "Hottest streak", name: streak.name, puuid: streak.puuid, value: `${streak.streak}W` });
  const mvp = best((p) => p.mvps / p.games);
  out.push({ label: "Most MVPs", name: mvp.name, puuid: mvp.puuid, value: `${mvp.mvps}` });
  const k = best((p) => kda(p.kills, p.deaths, p.assists));
  out.push({ label: "Best KDA", name: k.name, puuid: k.puuid, value: ratio(k.kills, k.deaths, k.assists) });
  const dmg = best((p) => p.damage / p.minutes);
  out.push({ label: "Most damage per minute", name: dmg.name, puuid: dmg.puuid, value: `${Math.round(dmg.damage / dmg.minutes)}` });
  const vis = best((p) => p.vision / p.minutes);
  out.push({ label: "Best vision per minute", name: vis.name, puuid: vis.puuid, value: (vis.vision / vis.minutes).toFixed(2) });
  const duoMin = Math.min(3, Math.max(1, ...d.duos.map((x) => x.games)));
  const duo = d.duos.filter((x) => x.games >= duoMin).sort((x, y) => adjustedWinRate(y.wins, y.games) - adjustedWinRate(x.wins, x.games) || y.games - x.games)[0];
  if (duo) out.push({ label: "Best duo", name: `${duo.a.name} & ${duo.b.name}`, puuid: "", href: `/duos/${encodeURIComponent(duo.key)}`, value: `${duo.wins}-${duo.games - duo.wins}` });
  const cold = d.players.reduce((a, b) => (b.streak < a.streak ? b : a));
  if (cold.streak <= -3) out.push({ label: "Needs a hug", name: cold.name, puuid: cold.puuid, value: `${-cold.streak}L` });
  return out;
}

import Link from "next/link";
import type { Metadata } from "next";
import { champName, getStatic } from "@/lib/ddragon";
import { getDataset, type Dataset } from "@/lib/stats";
import { Champ, Empty, WinRate, ratio, KdaRatio } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Champions" };

type ChampRow = Dataset["champions"][number];
type Props = { searchParams: Promise<{ sort?: string; dir?: string }> };

// Each column's sort value. null = no data (never picked), always listed last.
const SORTS: Record<string, { label: string; num: boolean; value: (c: ChampRow, name: string) => number | string | null }> = {
  champion: { label: "Champion", num: false, value: (_c, name) => name },
  picked: { label: "Picked", num: true, value: (c) => c.games },
  winrate: { label: "Win rate", num: false, value: (c) => (c.games ? c.wins / c.games : null) },
  banned: { label: "Banned", num: true, value: (c) => c.bans },
  kda: { label: "KDA", num: true, value: (c) => (c.games ? (c.kills + c.assists) / Math.max(1, c.deaths) : null) },
  dpm: { label: "Damage/min", num: true, value: (c) => (c.games ? c.damage / Math.max(1, c.minutes) : null) },
};

export default async function Champions({ searchParams }: Props) {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const { sort: sortParam = "picked", dir: dirParam } = await searchParams;
  const sortKey = sortParam in SORTS ? sortParam : "picked";
  // Names start A to Z; numbers start high to low. Clicking the sorted column flips it.
  const dir: "asc" | "desc" = dirParam === "asc" || dirParam === "desc" ? dirParam : sortKey === "champion" ? "asc" : "desc";
  if (!d.matches.length) return (<><div className="head"><h1>Champions</h1></div><Empty /></>);

  const picked = d.champions.filter((c) => c.games > 0);
  // Every champion that was picked or banned, in the chosen order.
  const def = SORTS[sortKey];
  const rows = d.champions
    .filter((c) => c.games > 0 || c.bans > 0)
    .map((c) => ({ c, v: def.value(c, champName(s, c.championId)) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === null ? (b.v === null ? b.c.games - a.c.games : 1) : -1;
      const cmp = typeof a.v === "string" ? a.v.localeCompare(String(b.v)) : (a.v as number) - (b.v as number);
      return (dir === "asc" ? cmp : -cmp) || b.c.games - a.c.games || b.c.bans - a.c.bans;
    })
    .map((r) => r.c);
  const sortHref = (key: string) => {
    const next = key === sortKey ? (dir === "asc" ? "desc" : "asc") : key === "champion" ? "asc" : "desc";
    return `/champions?sort=${key}&dir=${next}`;
  };
  // Ban rate is out of games that had bans at all (blind pick customs have none).
  const draftGames = d.matches.filter((m) => !m.remake && m.teams.some((t) => t.bans.length > 0)).length;
  const mostBanned = [...d.champions].filter((c) => c.bans > 0).sort((a, b) => b.bans - a.bans || b.games - a.games).slice(0, 10);

  return (
    <>
      <div className="head">
        <div>
          <h1>Champions</h1>
          <p>{picked.length} different champions picked across {d.counted} games. Best player is whoever has won the most on it.</p>
        </div>
      </div>
      {mostBanned.length ? (
        <section style={{ marginBottom: 36 }}>
          <h2 className="section-title">Most banned</h2>
          <p className="sub" style={{ margin: "-6px 0 14px" }}>
            Banned in {draftGames} game{draftGames === 1 ? "" : "s"} with bans. Win rate is from the games it got through.
          </p>
          <ol className="bans">
            {mostBanned.map((c, i) => (
              <li key={c.championId} className="ban panel">
                <span className="ban-rank">{i + 1}</span>
                <Champ s={s} id={c.championId} size={44} />
                <div className="stack" style={{ minWidth: 0 }}>
                  <b className="ellip">{champName(s, c.championId)}</b>
                  <span className="sub">
                    {c.bans} ban{c.bans === 1 ? "" : "s"}
                    {draftGames ? ` · ${Math.round((c.bans / draftGames) * 100)}%` : ""}
                  </span>
                  <span className="sub">
                    {c.games ? <>{Math.round((c.wins / c.games) * 100)}% win in {c.games}</> : "Never picked"}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <h2 className="section-title">All picks</h2>
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              {Object.entries(SORTS).map(([key, col]) => (
                <th key={key} className={col.num ? "num" : undefined} aria-sort={key === sortKey ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                  <Link href={sortHref(key)} scroll={false} className={`sort-h${key === sortKey ? ` sorted ${dir}` : ""}`}>{col.label}</Link>
                </th>
              ))}
              <th>Best player</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const best = [...c.players].sort((a, b) => b.wins - a.wins || a.games - b.games)[0];
              return (
                <tr key={c.championId}>
                  <td>
                    <div className="row">
                      <Champ s={s} id={c.championId} size={34} />
                      <b>{champName(s, c.championId)}</b>
                    </div>
                  </td>
                  <td className="num">{c.games || <span className="faint">0</span>}</td>
                  <td>{c.games ? <WinRate wins={c.wins} games={c.games} /> : <span className="faint">—</span>}</td>
                  <td className="num">{c.bans || <span className="faint">0</span>}</td>
                  <td className="num">{c.games ? <KdaRatio k={c.kills} d={c.deaths} a={c.assists} suffix={false} /> : <span className="faint">—</span>}</td>
                  <td className="num">{c.games ? Math.round(c.damage / Math.max(1, c.minutes)) : <span className="faint">—</span>}</td>
                  <td>
                    {best && best.wins > 0 ? (
                      <Link href={`/players/${encodeURIComponent(best.puuid)}`}>
                        {best.name} <span className="sub">{best.wins}W {best.games - best.wins}L</span>
                      </Link>
                    ) : <span className="faint">{c.games ? "No wins yet" : "Never picked"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

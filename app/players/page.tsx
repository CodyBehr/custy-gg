import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { champName, getStatic, img } from "@/lib/ddragon";
import { getDataset, searchPlayers, type PlayerSummary } from "@/lib/stats";
import type { Role } from "@/lib/types";
import { Champ, Empty, Form, Img, WinRate, ago, ratio, roleLabel, KdaRatio } from "@/components/ui";
import { PlayerSearch } from "@/components/player-search";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Players" };

type Props = { searchParams: Promise<{ q?: string; sort?: string }> };

const kdaOf = (p: PlayerSummary) => (p.deaths === 0 ? p.kills + p.assists : (p.kills + p.assists) / p.deaths);
const SORTS: Record<string, { label: string; value: (p: PlayerSummary) => number }> = {
  rating: { label: "Rating", value: (p) => p.rating },
  games: { label: "Games", value: (p) => p.games },
  winrate: { label: "Win rate", value: (p) => p.wins / p.games },
  kda: { label: "KDA", value: kdaOf },
  kp: { label: "Kill part.", value: (p) => p.kpSum / p.games },
  dpm: { label: "Damage/min", value: (p) => p.damage / Math.max(1, p.minutes) },
  cs: { label: "CS/min", value: (p) => p.cs / Math.max(1, p.minutes) },
  vision: { label: "Vision/min", value: (p) => p.vision / Math.max(1, p.minutes) },
  mvps: { label: "MVPs", value: (p) => p.mvps },
};

function mainRole(p: PlayerSummary): Role {
  const best = (Object.entries(p.roles) as [Role, { games: number }][]).sort((a, b) => b[1].games - a[1].games)[0];
  return best ? best[0] : "";
}

export default async function Players({ searchParams }: Props) {
  const { q = "", sort = "rating" } = await searchParams;
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const options = d.players.map((p) => ({ puuid: p.puuid, label: `${p.name}#${p.tag}` }));
  const query = q.trim();

  if (!d.players.length) {
    return (<><div className="head"><h1>Players</h1></div><Empty /></>);
  }

  let list = d.players;
  if (query) {
    list = searchPlayers(d.players, query);
    // One clear hit: go straight to the profile, like op.gg does.
    if (list.length === 1) redirect(`/players/${encodeURIComponent(list[0].puuid)}`);
  }
  const sorter = SORTS[sort] ?? SORTS.rating;
  if (!query) list = [...list].sort((a, b) => sorter.value(b) - sorter.value(a));
  const rankOf = new Map(d.players.map((p, i) => [p.puuid, i + 1]));
  const sortLink = (key: string) => `/players?sort=${key}`;

  return (
    <>
      <div className="head">
        <div style={{ width: "100%" }}>
          <h1>Players</h1>
          <p>Look anyone up by Riot ID to see their match history, champions, duos and every stat the site tracks.</p>
          <div style={{ marginTop: 18, maxWidth: 560 }}>
            <PlayerSearch options={options} defaultValue={query} autoFocus={!query} big />
          </div>
        </div>
      </div>

      {query ? (
        <p className="muted" style={{ marginBottom: 14 }}>
          {list.length ? `${list.length} players match “${query}”.` : `Nobody matches “${query}”. Check the spelling, or they may not have played a tracked game yet.`}
          {" "}<Link href="/players" className="win-t">Show everyone</Link>
        </p>
      ) : null}

      {list.length ? (
        <div className="table-wrap">
          <table className="t players-t">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Player</th>
                {Object.entries(SORTS).map(([key, def]) => (
                  <th key={key} className={key === "winrate" ? undefined : "num"} aria-sort={!query && sorter === def ? "descending" : undefined}>
                    {query ? def.label : <Link href={sortLink(key)} className={sorter === def ? "sorted" : undefined}>{def.label}</Link>}
                  </th>
                ))}
                <th>Mains</th>
                <th>Last 10</th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => {
                const minutes = Math.max(1, p.minutes);
                const role = mainRole(p);
                return (
                  <tr key={p.puuid}>
                    <td className="num faint">{rankOf.get(p.puuid)}</td>
                    <td>
                      <Link href={`/players/${encodeURIComponent(p.puuid)}`} className="row" style={{ gap: 10 }}>
                        <Img src={img.icon(s, p.profileIcon)} size={32} alt="" round />
                        <span className="stack">
                          <b>{p.name}</b>
                          <span className="sub">#{p.tag}{role ? `, ${roleLabel(role)}` : ""}, {ago(p.lastPlayed)}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="num"><b>{p.rating}</b></td>
                    <td className="num">{p.games}</td>
                    <td><WinRate wins={p.wins} games={p.games} /></td>
                    <td className="num"><KdaRatio k={p.kills} d={p.deaths} a={p.assists} suffix={false} /></td>
                    <td className="num">{Math.round((p.kpSum / p.games) * 100)}%</td>
                    <td className="num">{Math.round(p.damage / minutes)}</td>
                    <td className="num">{(p.cs / minutes).toFixed(1)}</td>
                    <td className="num">{(p.vision / minutes).toFixed(2)}</td>
                    <td className="num">{p.mvps}</td>
                    <td>
                      <span className="row" style={{ gap: 3 }}>
                        {p.champs.slice(0, 3).map((c) => (
                          <span key={c.championId} title={`${champName(s, c.championId)}: ${c.games} games`}>
                            <Champ s={s} id={c.championId} size={24} />
                          </span>
                        ))}
                      </span>
                    </td>
                    <td><Form results={[...p.form].reverse()} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

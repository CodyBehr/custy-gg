import Link from "next/link";
import type { Metadata } from "next";
import { champName, getStatic } from "@/lib/ddragon";
import { getDataset } from "@/lib/stats";
import { Champ, Empty, WinRate, ratio } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Champions" };

export default async function Champions() {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  if (!d.matches.length) return (<><div className="head"><h1>Champions</h1></div><Empty /></>);

  const picked = d.champions.filter((c) => c.games > 0);
  const bannedOnly = d.champions.filter((c) => c.games === 0 && c.bans > 0);

  return (
    <>
      <div className="head">
        <div>
          <h1>Champions</h1>
          <p>{picked.length} different champions picked across {d.counted} games. Best player is whoever has won the most on it.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              <th>Champion</th>
              <th className="num">Picked</th>
              <th>Win rate</th>
              <th className="num">Banned</th>
              <th className="num">KDA</th>
              <th className="num">Damage/min</th>
              <th>Best player</th>
            </tr>
          </thead>
          <tbody>
            {picked.map((c) => {
              const best = [...c.players].sort((a, b) => b.wins - a.wins || a.games - b.games)[0];
              return (
                <tr key={c.championId}>
                  <td>
                    <div className="row">
                      <Champ s={s} id={c.championId} size={34} />
                      <b>{champName(s, c.championId)}</b>
                    </div>
                  </td>
                  <td className="num">{c.games}</td>
                  <td><WinRate wins={c.wins} games={c.games} /></td>
                  <td className="num">{c.bans || <span className="faint">0</span>}</td>
                  <td className="num">{ratio(c.kills, c.deaths, c.assists)}</td>
                  <td className="num">{Math.round(c.damage / Math.max(1, c.minutes))}</td>
                  <td>
                    {best && best.wins > 0 ? (
                      <Link href={`/players/${encodeURIComponent(best.puuid)}`}>
                        {best.name} <span className="sub">{best.wins}W {best.games - best.wins}L</span>
                      </Link>
                    ) : <span className="faint">No wins yet</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {bannedOnly.length ? (
        <section style={{ marginTop: 32 }}>
          <h2 className="section-title">Banned but never picked</h2>
          <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
            {bannedOnly.map((c) => (
              <span key={c.championId} className="row" style={{ gap: 6 }}>
                <Champ s={s} id={c.championId} size={30} />
                <span className="sub">{c.bans}×</span>
              </span>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

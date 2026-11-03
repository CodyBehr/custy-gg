import Link from "next/link";
import type { Metadata } from "next";
import { champName, getStatic } from "@/lib/ddragon";
import { getDataset } from "@/lib/stats";
import { Champ, Empty, when } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Records" };

export default async function Records() {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  if (!d.matches.length) return (<><div className="head"><h1>Records</h1></div><Empty /></>);

  const pentas = d.matches.flatMap((m) =>
    m.remake ? [] : m.players.filter((p) => p.pentaKills > 0).map((p) => ({ m, p })),
  );

  return (
    <>
      <div className="head">
        <div>
          <h1>Records</h1>
          <p>The best (and worst) single games anyone has had. Click one to see the full scoreboard.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr><th>Record</th><th className="num">Value</th><th>Player</th><th>Date</th></tr>
          </thead>
          <tbody>
            {d.records.map((r) => (
              <tr key={r.label}>
                <td><Link href={`/matches/${encodeURIComponent(r.matchId)}`}><b>{r.label}</b></Link></td>
                <td className="num"><span className="gold-t" style={{ fontFamily: "var(--display)", fontWeight: 800, fontSize: 24 }}>{r.display}</span></td>
                <td>
                  <div className="row">
                    <Champ s={s} id={r.championId} size={30} />
                    <Link href={`/players/${encodeURIComponent(r.puuid)}`}>{r.name}</Link>
                    <span className="sub">on {champName(s, r.championId)}</span>
                  </div>
                </td>
                <td className="sub">{when(r.playedAt).day}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section style={{ marginTop: 36 }}>
        <h2 className="section-title">Pentakills</h2>
        {pentas.length ? (
          <div className="panel list">
            {pentas.map(({ m, p }) => (
              <Link key={m.id + p.puuid} href={`/matches/${encodeURIComponent(m.id)}`} className="li">
                <Champ s={s} id={p.championId} size={36} />
                <div className="grow">
                  <b>{p.name}</b> <span className="sub">on {champName(s, p.championId)}</span>
                </div>
                <span className="sub">{when(m.playedAt).day}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="muted">Nobody has a pentakill yet.</p>
        )}
      </section>
    </>
  );
}

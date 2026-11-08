import Link from "next/link";
import type { Metadata } from "next";
import { champName, getStatic } from "@/lib/ddragon";
import { getDataset } from "@/lib/stats";
import { store } from "@/lib/store";
import { PLAYER_LINKS } from "@/lib/player-links";
import { biggestLead, comeback } from "@/lib/timeline";
import { Champ, Empty, when } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Records" };

export default async function Records() {
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  if (!d.matches.length) return (<><div className="head"><h1>Records</h1></div><Empty /></>);

  // Records that need game timelines (games uploaded with app 1.5 or later).
  const tls = await store().timelines().catch(() => new Map());
  const main = (p: string) => PLAYER_LINKS[p] ?? p;
  type TRow = { label: string; display: string; who: string; matchId: string; playedAt: number; value: number };
  const best = new Map<string, TRow>();
  const consider = (r: TRow) => {
    const cur = best.get(r.label);
    if (!cur || r.value > cur.value) best.set(r.label, r);
  };
  for (const m of d.matches) {
    const tl = tls.get(m.id);
    if (!tl || m.remake) continue;
    const blueWon = m.teams.find((t) => t.teamId === 100)?.win ?? false;
    const names = (team: number) => m.players.filter((p) => p.teamId === team && !p.isBot).map((p) => p.name).join(", ");
    const cb = comeback(tl, blueWon);
    if (cb.deficit > 0) consider({ label: "Biggest comeback", value: cb.deficit, display: `${(cb.deficit / 1000).toFixed(1)}k`, who: `${blueWon ? "Blue" : "Red"}: ${names(blueWon ? 100 : 200)}`, matchId: m.id, playedAt: m.playedAt });
    const lead = biggestLead(tl);
    consider({ label: "Biggest gold lead", value: lead.lead, display: `${(lead.lead / 1000).toFixed(1)}k`, who: `${lead.team === 100 ? "Blue" : "Red"} at ${lead.minute} min: ${names(lead.team)}`, matchId: m.id, playedAt: m.playedAt });
    const fb = [...tl.kills].sort((a, b) => a.t - b.t)[0];
    const fbKiller = fb?.killer ? m.players.find((p) => p.puuid === main(fb.killer!)) : undefined;
    if (fb && fbKiller) consider({ label: "Fastest first blood", value: -fb.t, display: `${Math.floor(fb.t / 60)}:${String(fb.t % 60).padStart(2, "0")}`, who: fbKiller.name, matchId: m.id, playedAt: m.playedAt });
    for (const tp of tl.players) {
      const p = m.players.find((x) => x.puuid === main(tp.puuid));
      if (!p || p.isBot) continue;
      const cs10 = tp.cs[Math.min(10, tp.cs.length - 1)] ?? 0;
      if (tl.minutes >= 10) consider({ label: "Most CS at 10 minutes", value: cs10, display: String(cs10), who: p.name, matchId: m.id, playedAt: m.playedAt });
    }
  }
  const tlRecords = ["Biggest comeback", "Biggest gold lead", "Fastest first blood", "Most CS at 10 minutes"].map((l) => best.get(l)).filter(Boolean) as TRow[];

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

      {tlRecords.length ? (
        <section style={{ marginTop: 36 }}>
          <h2 className="section-title">From the game timelines</h2>
          <div className="table-wrap">
            <table className="t">
              <tbody>
                {tlRecords.map((r) => (
                  <tr key={r.label}>
                    <td><Link href={`/matches/${encodeURIComponent(r.matchId)}`}><b>{r.label}</b></Link></td>
                    <td className="num"><span className="gold-t" style={{ fontFamily: "var(--display)", fontWeight: 800, fontSize: 24 }}>{r.display}</span></td>
                    <td>{r.who}</td>
                    <td className="sub">{when(r.playedAt).day}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

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

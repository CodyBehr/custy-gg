import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { champName, getStatic } from "@/lib/ddragon";
import { clock, getDataset } from "@/lib/stats";
import type { Match, MatchTeam } from "@/lib/types";
import { Champ, Delta, Items, Kda, Loadout, ratio, roleLabel, when } from "@/components/ui";
import type { Static } from "@/lib/ddragon";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const d = await getDataset();
  const m = d.matches.find((x) => x.id === decodeURIComponent(id));
  return { title: m ? `Game on ${when(m.playedAt).day}` : "Game" };
}

const ROLE_ORDER = { TOP: 0, JUNGLE: 1, MID: 2, BOT: 3, SUPPORT: 4, "": 5 } as const;

export default async function MatchPage({ params }: Props) {
  const { id } = await params;
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const m = d.matches.find((x) => x.id === decodeURIComponent(id));
  if (!m) notFound();

  const w = when(m.playedAt);
  const blue = m.teams.find((t) => t.teamId === 100)!;
  const red = m.teams.find((t) => t.teamId === 200)!;
  const maxDmg = Math.max(1, ...m.players.map((p) => p.damageToChampions));
  const winnerFirst = [...m.teams].sort((a, b) => Number(b.win) - Number(a.win));

  return (
    <>
      <p className="sub" style={{ marginBottom: 14 }}>
        {w.long} at {w.time}, {clock(m.duration)} long{m.remake ? ". Remake, not counted in stats." : "."}
      </p>
      <section className="verdict">
        <TeamHead t={blue} label="Blue side" />
        <div className="mid">
          <div className="kills">{blue.kills} : {red.kills}</div>
          kills
        </div>
        <TeamHead t={red} label="Red side" right />
      </section>

      {winnerFirst.map((t) => (
        <Board key={t.teamId} s={s} m={m} t={t} maxDmg={maxDmg} mvp={d.mvpOf.get(m.id)} deltas={d.ratingDelta} scores={d.scores} />
      ))}
    </>
  );
}

function TeamHead({ t, label, right }: { t: MatchTeam; label: string; right?: boolean }) {
  return (
    <div className={right ? "right" : ""}>
      <div className={`team-name ${t.win ? "won" : "lost"}`}>{t.win ? "Victory" : "Defeat"}</div>
      <div className="objs">
        {label}: {t.towers} towers, {t.dragons} dragons, {t.barons} barons, {(t.gold / 1000).toFixed(1)}k gold
      </div>
    </div>
  );
}

function Board({ s, m, t, maxDmg, mvp, deltas, scores }: {
  s: Static; m: Match; t: MatchTeam; maxDmg: number; mvp?: string;
  deltas: Map<string, number>; scores: Map<string, number>;
}) {
  const players = m.players.filter((p) => p.teamId === t.teamId).sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role]);
  const minutes = Math.max(1, m.duration / 60);
  return (
    <section className={`panel board ${t.win ? "won" : "lost"}`}>
      <div className="board-head">
        <h2>{t.teamId === 100 ? "Blue side" : "Red side"}</h2>
        <span className="sub">{t.win ? "Won" : "Lost"}</span>
        {t.bans.length ? (
          <div className="bans">
            <span className="sub" style={{ marginRight: 4 }}>Bans</span>
            {t.bans.map((b) => <Champ key={b} s={s} id={b} size={22} />)}
          </div>
        ) : null}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="t">
          <thead>
            <tr>
              <th>Player</th>
              <th>KDA</th>
              <th>Damage</th>
              <th className="num">Gold</th>
              <th className="num">CS</th>
              <th className="num">Vision</th>
              <th>Items</th>
              <th className="num">Score</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => {
              const score = scores.get(`${m.id}:${p.puuid}`) ?? 0;
              const delta = deltas.get(`${m.id}:${p.puuid}`);
              return (
                <tr key={p.puuid}>
                  <td>
                    <div className="row" style={{ gap: 8 }}>
                      <Champ s={s} id={p.championId} size={36} level={p.champLevel} />
                      <Loadout s={s} p={p} size={17} />
                      <div className="stack" style={{ marginLeft: 4 }}>
                        {p.isBot ? (
                          <span className="pname faint">Bot</span>
                        ) : (
                          <Link href={`/players/${encodeURIComponent(p.puuid)}`} className="pname">{p.name}</Link>
                        )}
                        <span className="sub">{champName(s, p.championId)}{p.role ? `, ${roleLabel(p.role)}` : ""}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <Kda k={p.kills} d={p.deaths} a={p.assists} />
                    <div className="sub">{ratio(p.kills, p.deaths, p.assists)}{p.pentaKills ? ", pentakill" : p.quadraKills ? ", quadra" : ""}</div>
                  </td>
                  <td>
                    <div className="dmg">
                      <span>{p.damageToChampions.toLocaleString("en-US")}</span>
                      <span className="bar"><i style={{ width: `${(p.damageToChampions / maxDmg) * 100}%` }} /></span>
                    </div>
                  </td>
                  <td className="num">{p.gold.toLocaleString("en-US")}</td>
                  <td className="num">{p.cs}<div className="sub">{(p.cs / minutes).toFixed(1)}/min</div></td>
                  <td className="num">{p.visionScore}<div className="sub">{p.controlWards} control</div></td>
                  <td><Items s={s} items={p.items} size={24} /></td>
                  <td className="num">
                    {mvp === p.puuid && !m.remake ? <span className="badge mvp">MVP</span> : <b>{score.toFixed(1)}</b>}
                    <div><Delta n={delta} /></div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

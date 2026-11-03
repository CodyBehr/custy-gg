import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { champName, getStatic, img } from "@/lib/ddragon";
import { clock, getDataset, START_RATING } from "@/lib/stats";
import type { Role } from "@/lib/types";
import { Champ, Delta, Img, Items, Kda, Loadout, WinRate, ratio, roleLabel, when } from "@/components/ui";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const d = await getDataset();
  const p = d.byPuuid.get(decodeURIComponent(id));
  return { title: p ? `${p.name}#${p.tag}` : "Player" };
}

export default async function PlayerPage({ params }: Props) {
  const { id } = await params;
  const puuid = decodeURIComponent(id);
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const p = d.byPuuid.get(puuid);
  if (!p) notFound();

  const rank = d.players.indexOf(p) + 1;
  const games = d.matches.filter((m) => m.players.some((x) => x.puuid === puuid));
  const minutes = p.minutes || 1;
  const duoFloor = Math.min(3, Math.max(1, Math.floor(p.games / 5)));
  const duos = p.mates.filter((m) => m.with.games >= duoFloor).sort((a, b) => b.with.wins / b.with.games - a.with.wins / a.with.games || b.with.games - a.with.games);
  const rivals = p.mates.filter((m) => m.against.games >= duoFloor).sort((a, b) => a.against.wins / a.against.games - b.against.wins / b.against.games || b.against.games - a.against.games);
  const roles = (Object.entries(p.roles) as [Role, { games: number; wins: number }][]).sort((a, b) => b[1].games - a[1].games);

  return (
    <>
      <section className="profile">
        <div className="pic"><Img src={img.icon(s, p.profileIcon)} size={96} alt="" /></div>
        <div style={{ minWidth: 0 }}>
          <h1 className="ellip">{p.name}</h1>
          <div className="tag">#{p.tag}</div>
        </div>
        <div className="big-rating">
          <div className={`n${rank === 1 ? " gold-t" : ""}`}>{p.rating}</div>
          <div className="l">Rank {rank} of {d.players.length}. Peak {p.peakRating}.</div>
        </div>
      </section>

      <div className="facts">
        <Fact v={`${p.wins}–${p.games - p.wins}`} k={`${Math.round((p.wins / p.games) * 100)}% win rate`} />
        <Fact v={ratio(p.kills, p.deaths, p.assists)} k={`KDA, ${(p.kills / p.games).toFixed(1)} / ${(p.deaths / p.games).toFixed(1)} / ${(p.assists / p.games).toFixed(1)}`} />
        <Fact v={`${Math.round((p.kpSum / p.games) * 100)}%`} k="Kill participation" />
        <Fact v={`${Math.round((p.damageShareSum / p.games) * 100)}%`} k={`Team damage, ${Math.round(p.damage / minutes)} per min`} />
        <Fact v={(p.cs / minutes).toFixed(1)} k="CS per minute" />
        <Fact v={`${p.mvps}`} k={p.pentas ? `MVPs, ${p.pentas} pentakill${p.pentas > 1 ? "s" : ""}` : "MVPs"} />
      </div>

      <div className="cols">
        <section>
          <h2 className="section-title">Match history</h2>
          <div className="games">
            {games.map((m) => {
              const me = m.players.find((x) => x.puuid === puuid)!;
              const w = when(m.playedAt);
              const mates = m.players.filter((x) => x.teamId === me.teamId);
              const teamKills = Math.max(1, mates.reduce((a, x) => a + x.kills, 0));
              const delta = d.ratingDelta.get(`${m.id}:${puuid}`);
              const mvp = d.mvpOf.get(m.id) === puuid;
              return (
                <Link key={m.id} href={`/matches/${encodeURIComponent(m.id)}`} className={`pgame ${m.remake ? "" : me.win ? "won" : "lost"}`}>
                  <span className="edge" />
                  <div className="meta">
                    <div className="res">{m.remake ? "Remake" : me.win ? "Victory" : "Defeat"}</div>
                    {w.day}<br />{clock(m.duration)} {delta !== undefined ? <Delta n={delta} /> : null}
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <Champ s={s} id={me.championId} size={46} level={me.champLevel} />
                    <Loadout s={s} p={me} size={21} />
                  </div>
                  <div>
                    <div className="big-kda"><Kda k={me.kills} d={me.deaths} a={me.assists} /></div>
                    <div className="kda-sub">
                      {ratio(me.kills, me.deaths, me.assists)} KDA {mvp && !m.remake ? <span className="badge mvp">MVP</span> : null}
                    </div>
                  </div>
                  <div className="meta">
                    {champName(s, me.championId)}{me.role ? `, ${roleLabel(me.role)}` : ""}<br />
                    {me.cs} CS ({(me.cs / Math.max(1, m.duration / 60)).toFixed(1)}), {Math.round(((me.kills + me.assists) / teamKills) * 100)}% KP
                  </div>
                  <Items s={s} items={me.items} size={26} />
                </Link>
              );
            })}
          </div>
        </section>

        <aside>
          {p.ratingHistory.length > 1 ? (
            <section className="panel spark-box">
              <div className="row"><b>Rating</b><span className="sub">{p.ratingHistory.length} games</span></div>
              <Spark points={[START_RATING, ...p.ratingHistory.map((r) => r.rating)]} />
            </section>
          ) : null}

          <section>
            <h2 className="section-title">Champions</h2>
            <div className="panel list">
              {p.champs.slice(0, 8).map((c) => (
                <div key={c.championId} className="li">
                  <Champ s={s} id={c.championId} size={36} />
                  <div className="grow">
                    <div style={{ fontWeight: 600 }} className="ellip">{champName(s, c.championId)}</div>
                    <div className="sub">{ratio(c.kills, c.deaths, c.assists)} KDA, {(c.cs / Math.max(1, c.minutes)).toFixed(1)} CS/min</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className={c.wins / c.games >= 0.5 ? "win-t" : "loss-t"} style={{ fontWeight: 700 }}>{Math.round((c.wins / c.games) * 100)}%</div>
                    <div className="sub">{c.games} played</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {roles.length ? (
            <section>
              <h2 className="section-title">Roles</h2>
              <div className="panel list">
                {roles.map(([r, v]) => (
                  <div key={r} className="li">
                    <div className="grow"><b>{roleLabel(r)}</b> <span className="sub">{v.games} games</span></div>
                    <div style={{ width: 150 }}><WinRate wins={v.wins} games={v.games} /></div>
                  </div>
                ))}
              </div>
              <p className="sub" style={{ marginTop: 8 }}>Roles are guessed from summoner spells, lane and CS, since custom games don&apos;t record them.</p>
            </section>
          ) : null}

          <MateList title="Best duos" empty="Play a few more games together to see duos." rows={duos.slice(0, 5).map((m) => ({ ...m, rec: m.with }))} />
          <MateList title="Toughest opponents" empty="Not enough games against anyone yet." rows={rivals.slice(0, 5).map((m) => ({ ...m, rec: m.against }))} />
        </aside>
      </div>
    </>
  );
}

function Fact({ v, k }: { v: string; k: string }) {
  return (
    <div className="fact">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

function MateList({ title, empty, rows }: { title: string; empty: string; rows: { puuid: string; name: string; rec: { games: number; wins: number } }[] }) {
  return (
    <section>
      <h2 className="section-title">{title}</h2>
      <div className="panel list">
        {rows.length ? rows.map((r) => (
          <Link key={r.puuid} href={`/players/${encodeURIComponent(r.puuid)}`} className="li">
            <div className="grow ellip" style={{ fontWeight: 600 }}>{r.name}</div>
            <div style={{ textAlign: "right" }}>
              <div className={r.rec.wins / r.rec.games >= 0.5 ? "win-t" : "loss-t"} style={{ fontWeight: 700 }}>
                {r.rec.wins}W {r.rec.games - r.rec.wins}L
              </div>
            </div>
          </Link>
        )) : <div className="li sub">{empty}</div>}
      </div>
    </section>
  );
}

function Spark({ points }: { points: number[] }) {
  const w = 300, h = 90, pad = 6;
  const min = Math.min(...points), max = Math.max(...points);
  const span = Math.max(1, max - min);
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - pad * 2);
  const y = (v: number) => pad + (1 - (v - min) / span) * (h - pad * 2);
  const line = points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const baseY = y(START_RATING);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={`Rating went from ${points[0]} to ${points.at(-1)}`}>
      {START_RATING >= min && START_RATING <= max ? (
        <line x1={pad} x2={w - pad} y1={baseY} y2={baseY} stroke="var(--line)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
      ) : null}
      <path d={`${line}L${x(points.length - 1)},${h}L${x(0)},${h}Z`} fill="var(--blue-wash)" />
      <path d={line} fill="none" stroke="var(--blue)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

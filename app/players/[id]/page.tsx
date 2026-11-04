import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { PLAYER_LINKS } from "@/lib/player-links";
import type { Metadata } from "next";
import { champName, getStatic, img, type Static } from "@/lib/ddragon";
import { clock, getDataset, kda, START_RATING, type ChampLine, type Dataset, type PlayerSummary } from "@/lib/stats";
import type { Match, MatchPlayer, Role } from "@/lib/types";
import { Champ, Delta, Img, Items, Kda, Loadout, WinRate, ratio, roleLabel, when, ago } from "@/components/ui";
import { Board } from "@/components/scoreboard";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; champ?: string; role?: string; all?: string }>;
};

const HISTORY_PAGE = 20;
const ROLES: Role[] = ["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"];

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const d = await getDataset();
  const p = d.byPuuid.get(decodeURIComponent(id));
  return { title: p ? `${p.name}#${p.tag}` : "Player" };
}

export default async function PlayerPage({ params, searchParams }: Props) {
  const { id } = await params;
  const { tab = "overview", champ, role, all } = await searchParams;
  const puuid = decodeURIComponent(id);
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const p = d.byPuuid.get(puuid);
  if (!p) {
    const main = PLAYER_LINKS[puuid];
    if (main && d.byPuuid.has(main)) redirect(`/players/${encodeURIComponent(main)}`);
    notFound();
  }

  const base = `/players/${encodeURIComponent(puuid)}`;
  const rank = d.players.indexOf(p) + 1;

  return (
    <>
      <section className="profile">
        <div className="pic"><Img src={img.icon(s, p.profileIcon)} size={96} alt="" /></div>
        <div style={{ minWidth: 0 }}>
          <h1 className="ellip">{p.name}</h1>
          <div className="tag">#{p.tag}<span style={{ marginLeft: 12 }}>Last played {ago(p.lastPlayed)}</span></div>
          {p.otherAccounts.length ? <div className="sub" style={{ marginTop: 4 }}>Also plays as {p.otherAccounts.join(", ")}</div> : null}
        </div>
        <div className="big-rating">
          <div className={`n${rank === 1 ? " gold-t" : ""}`}>{p.rating}</div>
          <div className="l">Rank {rank} of {d.players.length}. Peak {p.peakRating}.</div>
        </div>
      </section>

      <nav className="tabs" aria-label="Profile sections">
        <Link href={base} aria-current={tab !== "champions" ? "page" : undefined}>Overview</Link>
        <Link href={`${base}?tab=champions`} aria-current={tab === "champions" ? "page" : undefined}>Champions</Link>
        <Link href={`/players`}>All players</Link>
      </nav>

      {tab === "champions" ? (
        <ChampionsTab s={s} p={p} base={base} />
      ) : (
        <Overview d={d} s={s} p={p} base={base} champ={champ ? Number(champ) : undefined} role={role as Role | undefined} showAll={all === "1"} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function Overview({ d, s, p, base, champ, role, showAll }: {
  d: Dataset; s: Static; p: PlayerSummary; base: string; champ?: number; role?: Role; showAll: boolean;
}) {
  const minutes = p.minutes || 1;
  const mine = d.matches
    .map((m) => ({ m, me: m.players.find((x) => x.puuid === p.puuid)! }))
    .filter((x) => x.me);
  const filtered = mine.filter(({ me }) => (!champ || me.championId === champ) && (!role || me.role === role));
  const shown = showAll ? filtered : filtered.slice(0, HISTORY_PAGE);
  const counted = filtered.filter(({ m }) => !m.remake).slice(0, HISTORY_PAGE);

  const duoFloor = Math.min(3, Math.max(1, Math.floor(p.games / 5)));
  const duos = p.mates.filter((m) => m.with.games >= duoFloor).sort((a, b) => b.with.wins / b.with.games - a.with.wins / a.with.games || b.with.games - a.with.games);
  const rivals = p.mates.filter((m) => m.against.games >= duoFloor).sort((a, b) => a.against.wins / a.against.games - b.against.wins / b.against.games || b.against.games - a.against.games);
  const roles = (Object.entries(p.roles) as [Role, { games: number; wins: number }][]).sort((a, b) => b[1].games - a[1].games);

  const filterHref = (next: { champ?: number; role?: Role }) => {
    const q = new URLSearchParams();
    if (next.champ) q.set("champ", String(next.champ));
    if (next.role) q.set("role", next.role);
    const qs = q.toString();
    return qs ? `${base}?${qs}` : base;
  };

  return (
    <>
      <div className="facts">
        <Fact v={`${p.wins}–${p.games - p.wins}`} k={`${Math.round((p.wins / p.games) * 100)}% win rate`} />
        <Fact v={ratio(p.kills, p.deaths, p.assists)} k={`KDA, ${(p.kills / p.games).toFixed(1)} / ${(p.deaths / p.games).toFixed(1)} / ${(p.assists / p.games).toFixed(1)}`} />
        <Fact v={`${Math.round((p.kpSum / p.games) * 100)}%`} k="Kill participation" />
        <Fact v={`${Math.round((p.damageShareSum / p.games) * 100)}%`} k={`Team damage, ${Math.round(p.damage / minutes)} per min`} />
        <Fact v={(p.cs / minutes).toFixed(1)} k={`CS per minute, ${Math.round(p.gold / minutes)} gold/min`} />
        <Fact v={`${p.mvps}`} k={`MVPs, ${(p.vision / minutes).toFixed(2)} vision/min`} />
      </div>

      <div className="cols">
        <section>
          <RecentSummary s={s} games={counted} label={champ ? `Last ${counted.length} on ${champName(s, champ)}` : role ? `Last ${counted.length} as ${roleLabel(role)}` : `Last ${counted.length} games`} />

          <div className="filters" role="group" aria-label="Filter match history">
            <Link href={filterHref({ role })} className={!champ ? "chip on" : "chip"}>All champions</Link>
            {p.champs.slice(0, 10).map((c) => (
              <Link key={c.championId} href={filterHref({ champ: c.championId, role })} className={champ === c.championId ? "chip on" : "chip"}>
                <Champ s={s} id={c.championId} size={20} /> {champName(s, c.championId)} <span className="faint">{c.games}</span>
              </Link>
            ))}
          </div>
          {roles.length > 1 ? (
            <div className="filters" role="group" aria-label="Filter by role">
              <Link href={filterHref({ champ })} className={!role ? "chip on" : "chip"}>All roles</Link>
              {ROLES.filter((r) => p.roles[r]).map((r) => (
                <Link key={r} href={filterHref({ champ, role: r })} className={role === r ? "chip on" : "chip"}>
                  {roleLabel(r)} <span className="faint">{p.roles[r]!.games}</span>
                </Link>
              ))}
            </div>
          ) : null}

          <h2 className="section-title" style={{ marginTop: 22 }}>Match history</h2>
          {shown.length ? (
            <div className="games">
              {shown.map(({ m, me }) => <HistoryRow key={m.id} d={d} s={s} m={m} me={me} />)}
            </div>
          ) : (
            <p className="muted">No games match this filter. <Link href={base} className="win-t">Clear filters</Link></p>
          )}
          {!showAll && filtered.length > HISTORY_PAGE ? (
            <p style={{ marginTop: 14 }}>
              <Link className="btn ghost" href={`${filterHref({ champ, role })}${champ || role ? "&" : "?"}all=1`}>
                Show all {filtered.length} games
              </Link>
            </p>
          ) : null}
        </section>

        <aside>
          {p.ratingHistory.length > 1 ? (
            <section className="panel spark-box">
              <div className="row"><b>Rating</b><span className="sub">{p.ratingHistory.length} games, peak {p.peakRating}</span></div>
              <Spark points={[START_RATING, ...p.ratingHistory.map((r) => r.rating)]} />
            </section>
          ) : null}

          <section>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="section-title">Champions</h2>
              <Link href={`${base}?tab=champions`} className="sub">All {p.champs.length}</Link>
            </div>
            <div className="panel list">
              {p.champs.slice(0, 7).map((c) => <ChampRow key={c.championId} s={s} c={c} href={filterHref({ champ: c.championId })} />)}
            </div>
          </section>

          {roles.length ? (
            <section>
              <h2 className="section-title">Roles</h2>
              <div className="panel list">
                {roles.map(([r, v]) => (
                  <Link key={r} href={filterHref({ role: r })} className="li">
                    <div className="grow"><b>{roleLabel(r)}</b> <span className="sub">{v.games} games</span></div>
                    <div style={{ width: 150 }}><WinRate wins={v.wins} games={v.games} /></div>
                  </Link>
                ))}
              </div>
              <p className="sub" style={{ marginTop: 8 }}>Roles are guessed from summoner spells, lane and CS, since custom games don&apos;t record them.</p>
            </section>
          ) : null}

          <section>
            <h2 className="section-title">Multikills</h2>
            <div className="panel multis">
              <Multi n={p.doubles} l="Double" />
              <Multi n={p.triples} l="Triple" />
              <Multi n={p.quadras} l="Quadra" />
              <Multi n={p.pentas} l="Penta" gold />
            </div>
            <p className="sub" style={{ marginTop: 8 }}>Longest killing spree: {p.largestSpree}.</p>
          </section>

          <MateList title="Best duos" empty="Play a few more games together to see duos." rows={duos.slice(0, 5).map((m) => ({ ...m, rec: m.with }))} more={{ href: `/duos?player=${encodeURIComponent(p.puuid)}&min=1`, label: "All duos" }} />
          <MateList title="Toughest opponents" empty="Not enough games against anyone yet." rows={rivals.slice(0, 5).map((m) => ({ ...m, rec: m.against }))} />
        </aside>
      </div>
    </>
  );
}

/** op.gg's "last 20 games" box: record ring, average KDA and top champions. */
function RecentSummary({ s, games, label }: { s: Static; games: { m: Match; me: MatchPlayer }[]; label: string }) {
  if (!games.length) return null;
  const wins = games.filter((g) => g.me.win).length;
  const n = games.length;
  const sum = (f: (x: { m: Match; me: MatchPlayer }) => number) => games.reduce((a, g) => a + f(g), 0);
  const k = sum((g) => g.me.kills), dd = sum((g) => g.me.deaths), a = sum((g) => g.me.assists);
  const kp = sum(({ m, me }) => {
    const teamKills = Math.max(1, m.players.filter((x) => x.teamId === me.teamId).reduce((t, x) => t + x.kills, 0));
    return (me.kills + me.assists) / teamKills;
  }) / n;
  const champs = new Map<number, { games: number; wins: number; k: number; d: number; a: number }>();
  for (const { me } of games) {
    const c = champs.get(me.championId) ?? { games: 0, wins: 0, k: 0, d: 0, a: 0 };
    c.games++;
    if (me.win) c.wins++;
    c.k += me.kills; c.d += me.deaths; c.a += me.assists;
    champs.set(me.championId, c);
  }
  const top = [...champs].sort((x, y) => y[1].games - x[1].games).slice(0, 3);
  const roleCount = new Map<Role, number>();
  for (const { me } of games) if (me.role) roleCount.set(me.role, (roleCount.get(me.role) ?? 0) + 1);
  const pct = Math.round((wins / n) * 100);
  const ratioValue = kda(k, dd, a);

  return (
    <section className="panel recent">
      <div className="recent-head">
        <b>{label}</b>
        <span className="sub">{wins}W {n - wins}L</span>
      </div>
      <div className="recent-body">
        <div className="ring-wrap">
          <Ring pct={pct} />
          <div className="ring-label"><b className={pct >= 50 ? "win-t" : "loss-t"}>{pct}%</b></div>
        </div>
        <div className="recent-kda">
          <div className="avg">{(k / n).toFixed(1)} <span className="faint">/</span> <span className="loss-t">{(dd / n).toFixed(1)}</span> <span className="faint">/</span> {(a / n).toFixed(1)}</div>
          <div className="ratio">{dd === 0 ? "Perfect" : `${ratioValue.toFixed(2)}:1`} KDA</div>
          <div className="sub">{Math.round(kp * 100)}% kill participation</div>
        </div>
        <div className="recent-champs">
          {top.map(([id, c]) => (
            <div key={id} className="row" style={{ gap: 8 }}>
              <Champ s={s} id={id} size={28} />
              <div className="stack" style={{ gap: 0 }}>
                <span style={{ fontSize: 13 }}>
                  <b className={c.wins / c.games >= 0.5 ? "win-t" : "loss-t"}>{Math.round((c.wins / c.games) * 100)}%</b>{" "}
                  <span className="sub">({c.wins}W {c.games - c.wins}L)</span>
                </span>
                <span className="sub">{ratio(c.k, c.d, c.a)} KDA</span>
              </div>
            </div>
          ))}
        </div>
        {roleCount.size ? (
          <div className="recent-roles" aria-label="Roles played">
            {ROLES.map((r) => {
              const v = roleCount.get(r) ?? 0;
              return (
                <div key={r} className="rbar" title={`${roleLabel(r)}: ${v} games`}>
                  <span className="track"><i style={{ height: `${(v / n) * 100}%` }} /></span>
                  <span className="sub">{roleLabel(r).slice(0, 3)}</span>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Ring({ pct }: { pct: number }) {
  const r = 34, c = 2 * Math.PI * r;
  return (
    <svg width="84" height="84" viewBox="0 0 84 84" aria-hidden>
      <circle cx="42" cy="42" r={r} fill="none" stroke="var(--red)" strokeWidth="9" />
      <circle cx="42" cy="42" r={r} fill="none" stroke="var(--blue)" strokeWidth="9"
        strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 42 42)" />
    </svg>
  );
}

/** One game in match history: op.gg-style summary, expands into the full scoreboard. */
function HistoryRow({ d, s, m, me }: { d: Dataset; s: Static; m: Match; me: MatchPlayer }) {
  const w = when(m.playedAt);
  const mates = m.players.filter((x) => x.teamId === me.teamId);
  const teamKills = Math.max(1, mates.reduce((a, x) => a + x.kills, 0));
  const delta = d.ratingDelta.get(`${m.id}:${me.puuid}`);
  const mvp = d.mvpOf.get(m.id) === me.puuid;
  const minutes = Math.max(1, m.duration / 60);
  const state = m.remake ? "" : me.win ? "won" : "lost";
  const teams = [me.teamId, me.teamId === 100 ? 200 : 100].map((t) => m.players.filter((x) => x.teamId === t));
  const winnerFirst = [...m.teams].sort((a, b) => Number(b.win) - Number(a.win));

  return (
    <details className={`mgame ${state}`}>
      <summary className={`pgame ${state}`}>
        <span className="edge" />
        <div className="meta">
          <div className="res">{m.remake ? "Remake" : me.win ? "Victory" : "Defeat"}</div>
          {w.day}<br />{clock(m.duration)} {delta !== undefined ? <Delta n={delta} /> : null}
        </div>
        <div className="row" style={{ gap: 6 }}>
          <Champ s={s} id={me.championId} size={46} level={me.champLevel} />
          <Loadout s={s} p={me} size={21} />
        </div>
        <div className="kda-col">
          <div className="big-kda"><Kda k={me.kills} d={me.deaths} a={me.assists} /></div>
          <div className="kda-sub">
            {ratio(me.kills, me.deaths, me.assists)} KDA {mvp && !m.remake ? <span className="badge mvp">MVP</span> : null}
            {me.pentaKills ? <span className="badge multi">Penta</span> : me.quadraKills ? <span className="badge multi">Quadra</span> : me.tripleKills ? <span className="badge multi">Triple</span> : null}
          </div>
          <Items s={s} items={me.items} size={22} />
        </div>
        <div className="meta pstats">
          {champName(s, me.championId)}{me.role ? `, ${roleLabel(me.role)}` : ""}<br />
          {Math.round(((me.kills + me.assists) / teamKills) * 100)}% KP<br />
          {me.cs} CS ({(me.cs / minutes).toFixed(1)})<br />
          {me.damageToChampions.toLocaleString("en-US")} dmg
        </div>
        <div className="lineup" aria-label="Players in this game">
          {teams.map((team, i) => (
            <div key={i} className="lineup-col">
              {team.map((x) => (
                <span key={x.puuid} className={`lp${x.puuid === me.puuid ? " me" : ""}`}>
                  <Img src={img.champ(s, x.championId)} size={16} alt={champName(s, x.championId)} />
                  <span className="ellip">{x.isBot ? "Bot" : x.name}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
        <span className="chev" aria-hidden>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
        </span>
      </summary>
      <div className="mgame-detail">
        {winnerFirst.map((t) => (
          <Board key={t.teamId} s={s} m={m} t={t} mvp={d.mvpOf.get(m.id)} deltas={d.ratingDelta} scores={d.scores} highlight={me.puuid} compact />
        ))}
        <p style={{ margin: "4px 0 6px" }}>
          <Link href={`/matches/${encodeURIComponent(m.id)}`} className="sub win-t">Open the full game page</Link>
        </p>
      </div>
    </details>
  );
}

function ChampRow({ s, c, href }: { s: Static; c: ChampLine; href: string }) {
  return (
    <Link href={href} className="li">
      <Champ s={s} id={c.championId} size={36} />
      <div className="grow">
        <div style={{ fontWeight: 600 }} className="ellip">{champName(s, c.championId)}</div>
        <div className="sub">{ratio(c.kills, c.deaths, c.assists)} KDA, {(c.cs / Math.max(1, c.minutes)).toFixed(1)} CS/min</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div className={c.wins / c.games >= 0.5 ? "win-t" : "loss-t"} style={{ fontWeight: 700 }}>{Math.round((c.wins / c.games) * 100)}%</div>
        <div className="sub">{c.games} played</div>
      </div>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Champions tab
// ---------------------------------------------------------------------------

function ChampionsTab({ s, p, base }: { s: Static; p: PlayerSummary; base: string }) {
  if (!p.champs.length) return <p className="muted">No games yet.</p>;
  return (
    <div className="table-wrap">
      <table className="t">
        <thead>
          <tr>
            <th>Champion</th>
            <th className="num">Played</th>
            <th>Win rate</th>
            <th className="num">KDA</th>
            <th className="num">Kills / Deaths / Assists</th>
            <th className="num">CS/min</th>
            <th className="num">Damage/min</th>
            <th className="num">Gold/min</th>
            <th className="num">Vision/min</th>
            <th className="num">Double</th>
            <th className="num">Triple</th>
            <th className="num">Quadra</th>
            <th className="num">Penta</th>
          </tr>
        </thead>
        <tbody>
          {p.champs.map((c) => {
            const min = Math.max(1, c.minutes);
            return (
              <tr key={c.championId}>
                <td>
                  <Link href={`${base}?champ=${c.championId}`} className="row">
                    <Champ s={s} id={c.championId} size={32} />
                    <b>{champName(s, c.championId)}</b>
                  </Link>
                </td>
                <td className="num">{c.games}</td>
                <td><WinRate wins={c.wins} games={c.games} /></td>
                <td className="num"><b>{ratio(c.kills, c.deaths, c.assists)}</b></td>
                <td className="num">{(c.kills / c.games).toFixed(1)} / <span className="loss-t">{(c.deaths / c.games).toFixed(1)}</span> / {(c.assists / c.games).toFixed(1)}</td>
                <td className="num">{(c.cs / min).toFixed(1)}</td>
                <td className="num">{Math.round(c.damage / min)}</td>
                <td className="num">{Math.round(c.gold / min)}</td>
                <td className="num">{(c.vision / min).toFixed(2)}</td>
                <td className="num">{c.doubles || <span className="faint">0</span>}</td>
                <td className="num">{c.triples || <span className="faint">0</span>}</td>
                <td className="num">{c.quadras || <span className="faint">0</span>}</td>
                <td className="num">{c.pentas ? <span className="gold-t">{c.pentas}</span> : <span className="faint">0</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Fact({ v, k }: { v: string; k: string }) {
  return (
    <div className="fact">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

function Multi({ n, l, gold }: { n: number; l: string; gold?: boolean }) {
  return (
    <div className="multi">
      <div className={`v${gold && n ? " gold-t" : ""}${n ? "" : " faint"}`}>{n}</div>
      <div className="sub">{l}</div>
    </div>
  );
}

function MateList({ title, empty, rows, more }: {
  title: string; empty: string; rows: { puuid: string; name: string; rec: { games: number; wins: number } }[];
  more?: { href: string; label: string };
}) {
  return (
    <section>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h2 className="section-title">{title}</h2>
        {more ? <Link href={more.href} className="sub">{more.label}</Link> : null}
      </div>
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

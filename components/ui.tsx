// Small presentational pieces shared by every page.

import Link from "next/link";
import type { Match, MatchPlayer, Role } from "@/lib/types";
import { champName, img, type Static } from "@/lib/ddragon";
import { clock, kda } from "@/lib/stats";

export function Img({ src, size, alt, round, className }: { src: string; size: number; alt: string; round?: boolean; className?: string }) {
  const cls = `icon${round ? " round" : ""}${className ? " " + className : ""}`;
  if (!src) return <span className={`${cls} icon-ph`} style={{ width: size, height: size }} aria-label={alt} />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={cls} src={src} width={size} height={size} alt={alt} loading="lazy" decoding="async" />;
}

export function Champ({ s, id, size = 32, level }: { s: Static; id: number; size?: number; level?: number }) {
  return (
    <span className="champ" title={champName(s, id)}>
      <Img src={img.champ(s, id)} size={size} alt={champName(s, id)} />
      {level ? <span className="lvl">{level}</span> : null}
    </span>
  );
}

export function Items({ s, items, size = 24 }: { s: Static; items: number[]; size?: number }) {
  return (
    <div className="items">
      {items.map((id, i) => (
        <span key={i} title={s.items[id] ?? ""}>
          <Img src={img.item(s, id)} size={size} alt={s.items[id] ?? "Empty slot"} />
        </span>
      ))}
    </div>
  );
}

export function Loadout({ s, p, size = 18 }: { s: Static; p: MatchPlayer; size?: number }) {
  return (
    <div className="spells two">
      <Img src={img.spell(s, p.spells[0])} size={size} alt="Summoner spell" />
      <Img src={img.rune(s, p.keystone)} size={size} alt={s.runeNames[p.keystone] ?? "Keystone"} round />
      <Img src={img.spell(s, p.spells[1])} size={size} alt="Summoner spell" />
      <Img src={img.rune(s, p.subStyle)} size={size} alt={s.runeNames[p.subStyle] ?? "Secondary runes"} round />
    </div>
  );
}

export function Kda({ k, d, a }: { k: number; d: number; a: number }) {
  return (
    <span className="kda">
      <b>{k}</b><span className="slash">/</span><b className="loss-t">{d}</b><span className="slash">/</span><b>{a}</b>
    </span>
  );
}

export function ratio(k: number, d: number, a: number) {
  return d === 0 ? "Perfect" : kda(k, d, a).toFixed(2);
}

/** op.gg's KDA tiers: gray under 3, teal 3+, blue 4+, orange 5+ (and Perfect). */
export function kdaTone(k: number, d: number, a: number) {
  if (d === 0 && k + a > 0) return "kda-5";
  const v = kda(k, d, a);
  return v >= 5 ? "kda-5" : v >= 4 ? "kda-4" : v >= 3 ? "kda-3" : "kda-0";
}

/** op.gg's win-rate tier: red from 60% up, plain otherwise. */
export function wrTone(wins: number, games: number) {
  return games && wins / games >= 0.6 ? "wr-hot" : "wr-plain";
}

/** "5.36:1 KDA" in its tier color. */
export function KdaRatio({ k, d, a, suffix = true }: { k: number; d: number; a: number; suffix?: boolean }) {
  const text = d === 0 ? "Perfect" : `${kda(k, d, a).toFixed(2)}:1`;
  return <b className={`kdar ${kdaTone(k, d, a)}`}>{text}{suffix ? " KDA" : ""}</b>;
}

/** Win rate as a colored percentage. */
export function Pct({ wins, games }: { wins: number; games: number }) {
  const pct = games ? Math.round((wins / games) * 100) : 0;
  return <b className={`pct ${wrTone(wins, games)}`}>{pct}%</b>;
}

export function WinRate({ wins, games }: { wins: number; games: number }) {
  const pct = games ? Math.round((wins / games) * 100) : 0;
  return (
    <div className="wr" title={`${wins} wins, ${games - wins} losses`}>
      <div className="wr-bar" aria-hidden><i style={{ width: `${pct}%` }} /></div>
      <Pct wins={wins} games={games} />
    </div>
  );
}

/** One champion line in op.gg's layout: icon, name and CS; KDA; win rate and games. */
export function ChampLineRow({ s, c, href, label }: {
  s: Static;
  c: { championId: number; games: number; wins: number; kills: number; deaths: number; assists: number; cs: number; minutes: number };
  href?: string;
  label?: string;  // overrides the champion name, e.g. "All"
}) {
  const g = Math.max(1, c.games);
  const body = (
    <>
      {label ? <span className="all-ico" aria-hidden>{label.slice(0, 1)}</span> : <Champ s={s} id={c.championId} size={34} />}
      <div className="cl-name">
        <b className="ellip">{label ?? champName(s, c.championId)}</b>
        <span className="sub">CS {Math.round(c.cs / g)} ({(c.cs / Math.max(1, c.minutes)).toFixed(1)})</span>
      </div>
      <div className="cl-kda">
        <KdaRatio k={c.kills} d={c.deaths} a={c.assists} />
        <span className="sub">{(c.kills / g).toFixed(1)} / {(c.deaths / g).toFixed(1)} / {(c.assists / g).toFixed(1)}</span>
      </div>
      <div className="cl-wr">
        <Pct wins={c.wins} games={c.games} />
        <span className="sub">{c.games} {c.games === 1 ? "Game" : "Games"}</span>
      </div>
    </>
  );
  return href ? <Link href={href} className="cl">{body}</Link> : <div className="cl">{body}</div>;
}

export function Form({ results }: { results: boolean[] }) {
  return (
    <div className="form" aria-label={`Last ${results.length}: ${results.map((w) => (w ? "W" : "L")).join(" ")}`}>
      {results.map((w, i) => <i key={i} className={w ? "w" : ""} />)}
    </div>
  );
}

export function Delta({ n }: { n?: number }) {
  if (n === undefined) return null;
  return <span className={`delta ${n >= 0 ? "up" : "down"}`}>{n >= 0 ? "+" : "−"}{Math.abs(n)}</span>;
}

const ROLE_LABEL: Record<Role, string> = { TOP: "Top", JUNGLE: "Jungle", MID: "Mid", BOT: "Bot", SUPPORT: "Support", "": "" };
export const roleLabel = (r: Role) => ROLE_LABEL[r];

export function when(ms: number) {
  const d = new Date(ms);
  return {
    day: d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: TZ }),
    time: d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: TZ }),
    long: d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: TZ }),
  };
}
// Dates are shown in this time zone. Set NEXT_PUBLIC_TIMEZONE to change it.
export const TZ = process.env.NEXT_PUBLIC_TIMEZONE || "America/New_York";

export function ago(ms: number) {
  const days = Math.floor((Date.now() - ms) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "last week";
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  return `${Math.floor(days / 30)} months ago`;
}

/** One game in a list, shown neutrally: both teams side by side. */
export function GameRow({ s, m, mvp }: { s: Static; m: Match; mvp?: string }) {
  const w = when(m.playedAt);
  const mvpPlayer = m.players.find((p) => p.puuid === mvp);
  const teams = [...m.teams].sort((a, b) => Number(b.win) - Number(a.win));
  return (
    <Link href={`/matches/${encodeURIComponent(m.id)}`} className={`game${m.remake ? " remake" : ""}`}>
      <div className="when">
        <b>{w.time}</b>
        {clock(m.duration)}
        {m.remake ? <div><span className="badge remake">Remake</span></div> : null}
      </div>
      <div className="sides">
        {teams.map((t) => {
          const players = m.players.filter((p) => p.teamId === t.teamId);
          return (
            <div key={t.teamId} className={`side ${t.win ? "won" : "lost"}`}>
              <span className="res">{t.win ? "Won" : "Lost"}</span>
              {players.map((p) => (
                <span key={p.puuid} className="sp">
                  <Champ s={s} id={p.championId} size={28} />
                  <span className="pn">{p.isBot ? "Bot" : p.name}</span>
                </span>
              ))}
              <span className="score">{t.kills} kills</span>
            </div>
          );
        })}
        {mvpPlayer && !m.remake ? (
          <div className="mvp-line"><span className="badge mvp">MVP</span> {mvpPlayer.name} on {champName(s, mvpPlayer.championId)}</div>
        ) : null}
      </div>
    </Link>
  );
}

export function Empty({ title = "No games yet" }: { title?: string }) {
  return (
    <div className="panel empty">
      <h2>{title}</h2>
      <p>
        Games show up here after someone who played installs the collector. It takes a couple of minutes:{" "}
        <Link href="/setup" className="win-t">get the collector</Link>, and the custom games in your recent match history
        get uploaded right away.
      </p>
    </div>
  );
}

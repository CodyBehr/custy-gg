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

export function WinRate({ wins, games }: { wins: number; games: number }) {
  const pct = games ? Math.round((wins / games) * 100) : 0;
  return (
    <div className="wr" title={`${wins} wins, ${games - wins} losses`}>
      <div className="wr-bar" aria-hidden><i style={{ width: `${pct}%` }} /></div>
      <b className={pct >= 50 ? "win-t" : "loss-t"}>{pct}%</b>
    </div>
  );
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

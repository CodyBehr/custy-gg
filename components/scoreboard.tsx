// One team's full scoreboard. Used on the match page and inside expanded
// match-history rows on player profiles.

import Link from "next/link";
import { champName, type Static } from "@/lib/ddragon";
import type { Match, MatchTeam } from "@/lib/types";
import { Champ, Delta, Items, Kda, Loadout, ratio, roleLabel } from "@/components/ui";

const ROLE_ORDER = { TOP: 0, JUNGLE: 1, MID: 2, BOT: 3, SUPPORT: 4, "": 5 } as const;

export function Board({ s, m, t, mvp, deltas, scores, highlight, compact }: {
  s: Static;
  m: Match;
  t: MatchTeam;
  mvp?: string;
  deltas: Map<string, number>;
  scores: Map<string, number>;
  highlight?: string;   // puuid to emphasize
  compact?: boolean;
}) {
  const players = m.players.filter((p) => p.teamId === t.teamId).sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role]);
  const minutes = Math.max(1, m.duration / 60);
  const maxDmg = Math.max(1, ...m.players.map((p) => p.damageToChampions));
  const size = compact ? 30 : 36;
  return (
    <section className={`panel board ${t.win ? "won" : "lost"}${compact ? " compact" : ""}`}>
      <div className="board-head">
        <h2>{t.teamId === 100 ? "Blue side" : "Red side"}</h2>
        <span className="sub">
          {t.win ? "Won" : "Lost"}, {t.kills} kills, {t.towers} towers, {t.dragons} dragons, {t.barons} barons
        </span>
        {t.bans.length ? (
          <div className="bans">
            <span className="sub" style={{ marginRight: 4 }}>Bans</span>
            {t.bans.map((b) => <Champ key={b} s={s} id={b} size={20} />)}
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
              {compact ? null : <th className="num">Gold</th>}
              <th className="num">CS</th>
              {compact ? null : <th className="num">Vision</th>}
              <th>Items</th>
              <th className="num">Score</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => {
              const score = scores.get(`${m.id}:${p.puuid}`) ?? 0;
              const delta = deltas.get(`${m.id}:${p.puuid}`);
              return (
                <tr key={p.puuid} className={p.puuid === highlight ? "me" : undefined}>
                  <td>
                    <div className="row" style={{ gap: 8 }}>
                      <Champ s={s} id={p.championId} size={size} level={p.champLevel} />
                      {compact ? null : <Loadout s={s} p={p} size={17} />}
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
                  {compact ? null : <td className="num">{p.gold.toLocaleString("en-US")}</td>}
                  <td className="num">{p.cs}<div className="sub">{(p.cs / minutes).toFixed(1)}/min</div></td>
                  {compact ? null : <td className="num">{p.visionScore}<div className="sub">{p.controlWards} control</div></td>}
                  <td><Items s={s} items={p.items} size={compact ? 22 : 24} /></td>
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

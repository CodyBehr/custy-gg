// Match page sections built from the game timeline: gold lead graph with
// objectives, a kill map, and how each player was doing at 10 and 15 minutes.

import { champName, img, type Static } from "@/lib/ddragon";
import { PLAYER_LINKS } from "@/lib/player-links";
import { comeback, goldDiff, type TimelineObjective, type TimelineSummary } from "@/lib/timeline";
import type { Match, MatchPlayer } from "@/lib/types";

const main = (p: string) => PLAYER_LINKS[p] ?? p;
const k = (n: number) => `${n < 0 ? "−" : n > 0 ? "+" : ""}${(Math.abs(n) / 1000).toFixed(1)}k`;
const mmss = (t: number) => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;

const OBJ_LABEL: Record<TimelineObjective["kind"], string> = {
  DRAGON: "Dragon", BARON: "Baron", HERALD: "Herald", GRUBS: "Grubs", ATAKHAN: "Atakhan", TOWER: "Tower", INHIBITOR: "Inhibitor",
};
const OBJ_GLYPH: Record<TimelineObjective["kind"], string> = {
  DRAGON: "D", BARON: "B", HERALD: "H", GRUBS: "G", ATAKHAN: "A", TOWER: "T", INHIBITOR: "I",
};
const dragonName = (sub?: string) =>
  sub ? sub.replace(/_DRAGON$/, "").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()).replace("Hextech", "Hextech").replace("Air", "Cloud").replace("Fire", "Infernal").replace("Water", "Ocean").replace("Earth", "Mountain") : "";

export function TimelineView({ tl, m, s }: { tl: TimelineSummary; m: Match; s: Static }) {
  const blueWon = m.teams.find((t) => t.teamId === 100)?.win ?? false;
  const back = comeback(tl, blueWon);
  return (
    <section className="tl">
      <div className="tl-grid">
        <div className="panel tl-card">
          <h2 className="section-title">Gold lead</h2>
          <GoldGraph tl={tl} />
          <p className="sub tl-note">
            {back.deficit >= 1500
              ? `${blueWon ? "Blue" : "Red"} came back from ${(back.deficit / 1000).toFixed(1)}k gold down at ${back.minute}:00.`
              : back.deficit < 300
                ? `${blueWon ? "Blue" : "Red"} led the whole game.`
                : `${blueWon ? "Blue" : "Red"} was never more than ${(back.deficit / 1000).toFixed(1)}k gold behind.`}{" "}
            Hover the graph for each minute; letters mark dragons, heralds, barons, towers and inhibitors.
          </p>
        </div>
        <div className="panel tl-card">
          <h2 className="section-title">Kill map</h2>
          <KillMap tl={tl} s={s} />
          <p className="sub tl-note"><span className="dot blue" /> Blue got the kill <span className="dot red" /> Red got the kill</p>
        </div>
      </div>
      <div className="panel tl-card">
        <h2 className="section-title">Early game</h2>
        <EarlyTable tl={tl} m={m} s={s} />
      </div>
    </section>
  );
}

function GoldGraph({ tl }: { tl: TimelineSummary }) {
  const diff = goldDiff(tl);
  const W = 640, H = 220, padL = 44, padR = 10, padT = 12, padB = 34;
  const max = Math.max(2000, ...diff.map(Math.abs));
  const top = Math.ceil(max / 2000) * 2000;
  const x = (i: number) => padL + (i / Math.max(1, diff.length - 1)) * (W - padL - padR);
  const y = (v: number) => padT + ((top - v) / (2 * top)) * (H - padT - padB);
  const line = diff.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${line}L${x(diff.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  const ticks = [top, top / 2, 0, -top / 2, -top];
  const minuteTicks = diff.map((_, i) => i).filter((i) => i % 5 === 0);
  const objs = tl.objectives.filter((o) => o.kind !== "TOWER" || true);
  return (
    <svg className="gold-graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Blue minus red team gold, by minute">
      <defs>
        <clipPath id="above"><rect x="0" y="0" width={W} height={y(0)} /></clipPath>
        <clipPath id="below"><rect x="0" y={y(0)} width={W} height={H} /></clipPath>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className={t === 0 ? "gg-zero" : "gg-grid"} />
          <text x={padL - 6} y={y(t) + 4} className="gg-label" textAnchor="end">{t === 0 ? "0" : k(t)}</text>
        </g>
      ))}
      {minuteTicks.map((i) => (
        <text key={i} x={x(i)} y={H - padB + 16} className="gg-label" textAnchor="middle">{i}m</text>
      ))}
      <path d={area} className="gg-blue" clipPath="url(#above)" />
      <path d={area} className="gg-red" clipPath="url(#below)" />
      <path d={line} className="gg-line" />
      {objs.map((o, i) => {
        const pos = Math.min(diff.length - 1, o.t / 60);
        return (
          <g key={i} transform={`translate(${x(pos)},${H - 8})`}>
            <title>{`${mmss(o.t)} ${o.teamId === 100 ? "Blue" : "Red"} took ${o.kind === "DRAGON" && o.sub ? `${dragonName(o.sub)} dragon` : OBJ_LABEL[o.kind].toLowerCase()}`}</title>
            <circle r="6.5" className={o.teamId === 100 ? "gg-obj blue" : "gg-obj red"} />
            <text y="3" textAnchor="middle" className="gg-obj-t">{OBJ_GLYPH[o.kind]}</text>
          </g>
        );
      })}
      {diff.map((v, i) => (
        <rect key={i} x={x(i) - (W - padL - padR) / diff.length / 2} y={padT} width={(W - padL - padR) / diff.length} height={H - padT - padB} fill="transparent">
          <title>{`${i}:00  ${v === 0 ? "even" : `${v > 0 ? "Blue" : "Red"} ahead by ${Math.abs(v).toLocaleString("en-US")} gold`}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function KillMap({ tl, s }: { tl: TimelineSummary; s: Static }) {
  const team = new Map(tl.players.map((p) => [p.puuid, p.teamId]));
  const size = 300;
  // Summoner's Rift coordinates run about 0 to 14,870 (x) and 0 to 14,980 (y), with y pointing up.
  const px = (v: number) => (v / 14870) * size;
  const py = (v: number) => size - (v / 14980) * size;
  return (
    <svg className="kill-map" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${tl.kills.length} kills on the map`}>
      <image href={img.map(s)} width={size} height={size} opacity="0.55" />
      {tl.kills.filter((kl) => kl.x || kl.y).map((kl, i) => {
        const t = kl.killer ? team.get(kl.killer) : team.get(kl.victim) === 100 ? 200 : 100;
        return (
          <circle key={i} cx={px(kl.x)} cy={py(kl.y)} r="4.5" className={t === 100 ? "km blue" : "km red"}>
            <title>{mmss(kl.t)}</title>
          </circle>
        );
      })}
    </svg>
  );
}

function EarlyTable({ tl, m, s }: { tl: TimelineSummary; m: Match; s: Static }) {
  const at = (arr: number[], min: number) => arr[Math.min(min, arr.length - 1)] ?? 0;
  const byPuuid = new Map(tl.players.map((p) => [main(p.puuid), p]));
  const opp = (p: MatchPlayer) => (p.role ? m.players.find((x) => x.teamId !== p.teamId && x.role === p.role) : undefined);
  const roleOrder = ["TOP", "JUNGLE", "MID", "BOT", "SUPPORT", ""];
  const rows = [...m.players].sort((a, b) => a.teamId - b.teamId || roleOrder.indexOf(a.role) - roleOrder.indexOf(b.role));
  const has15 = tl.minutes >= 15;
  return (
    <div className="table-wrap">
      <table className="t early">
        <thead>
          <tr>
            <th>Player</th>
            <th className="num">CS at 10</th>
            <th className="num">Gold at 10</th>
            {has15 ? <th className="num">Gold at 15</th> : null}
            <th className="num">vs lane at {has15 ? 15 : 10}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const t = byPuuid.get(p.puuid);
            if (!t) return null;
            const o = opp(p);
            const ot = o ? byPuuid.get(o.puuid) : undefined;
            const mark = has15 ? 15 : 10;
            const lane = ot ? at(t.gold, mark) - at(ot.gold, mark) : null;
            return (
              <tr key={p.puuid} className={p.teamId === 100 ? "side-blue" : "side-red"}>
                <td>
                  <span className="row" style={{ gap: 8 }}>
                    <img src={img.champ(s, p.championId)} alt="" width={22} height={22} className="ic" />
                    <b>{p.isBot ? `${champName(s, p.championId)} bot` : p.name}</b>
                    {p.role ? <span className="faint">{p.role.toLowerCase()}</span> : null}
                  </span>
                </td>
                <td className="num">{at(t.cs, 10)}</td>
                <td className="num">{at(t.gold, 10).toLocaleString("en-US")}</td>
                {has15 ? <td className="num">{at(t.gold, 15).toLocaleString("en-US")}</td> : null}
                <td className={`num ${lane === null ? "faint" : lane > 0 ? "win-t" : lane < 0 ? "loss-t" : ""}`}>
                  {lane === null ? "—" : `${lane > 0 ? "+" : lane < 0 ? "−" : ""}${Math.abs(lane).toLocaleString("en-US")}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

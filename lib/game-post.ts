// Posts each newly uploaded game to a Discord channel through a channel webhook
// (set on the site's /discord page). No bot permissions needed.

import "server-only";
import { store } from "./store";
import { buildDataset, clock, type Dataset } from "./stats";
import { champName, getStatic, type Static } from "./ddragon";
import type { Match, MatchPlayer } from "./types";
import { settledLine, type Prediction } from "./predictions";
import { discordByPuuid } from "./discord-links";

const WEBHOOK_KEY = "discord:webhook";
const BLUE = 0x4f9dff;
const RED = 0xe84057;
/** Games that ended longer ago than this are a backfill (a new collector catching up), not news. */
const FRESH_MS = 3 * 60 * 60 * 1000;

export const isWebhookUrl = (u: string) =>
  /^https:\/\/(?:canary\.|ptb\.)?(?:discord|discordapp)\.com\/api\/webhooks\/\d+\/[\w-]+$/.test(u);

export async function getWebhook() {
  return store().getSetting(WEBHOOK_KEY);
}

export async function setWebhook(url: string | null) {
  await store().setSetting(WEBHOOK_KEY, url ?? "");
}

export function shouldPost(m: Match) {
  return !m.remake && Date.now() - (m.playedAt + m.duration * 1000) < FRESH_MS;
}

/** Sends the result card for a game. Never throws: a Discord hiccup shouldn't fail an upload. */
export async function postGame(matchId: string | "latest", site: string, pred?: Prediction | null, opts: { test?: boolean } = {}) {
  try {
    const hook = await getWebhook();
    if (!hook) return { ok: false, status: 0 };
    const [d, s, tags] = await Promise.all([store().all().then(buildDataset), getStatic(), discordByPuuid()]);
    const m = matchId === "latest" ? d.matches.find((x) => !x.remake) : d.matches.find((x) => x.id === matchId);
    if (!m) return { ok: false, status: 0 };
    const embed = gameEmbed(m, d, s, site, pred, tags);
    if (opts.test) embed.footer = { text: `Test post · ${embed.footer.text}` };
    const link = (label: string, url: string, emoji: string) => ({ type: 2, style: 5, label, url, emoji: { name: emoji } });
    // Channel webhooks can carry link buttons (with_components=true).
    const res = await fetch(`${hook}?wait=true&with_components=true`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "custy.gg",
        embeds: [embed],
        allowed_mentions: { parse: [] }, // show @names without pinging after every game
        components: [{
          type: 1,
          components: [
            link("Match details", `${site}/matches/${encodeURIComponent(m.id)}`, "📊"),
            link("Standings", `${site}/`, "🏆"),
            link("Champions", `${site}/champions`, "🛡️"),
            link("Records", `${site}/records`, "📈"),
          ],
        }],
      }),
    });
    console.log(`[post] ${m.id} -> Discord ${res.status}${res.ok ? "" : ` ${await res.text().catch(() => "")}`}`);
    return { ok: res.ok, status: res.status };
  } catch (e) {
    console.log(`[post] ${matchId} failed: ${(e as Error).message}`);
    return { ok: false, status: 0 };
  }
}

/**
 * Each player's rating and standings position just before and just after this game.
 * Ratings replay oldest-first, so "after" is the rating history entry for this game.
 */
export function movement(m: Match, d: Dataset) {
  // d.matches is newest first; ratings were replayed oldest first.
  const order = new Map(d.matches.map((x, i) => [x.id, d.matches.length - 1 - i]));
  const k = order.get(m.id) ?? 0;
  const ratingAt = (hist: { matchId: string; rating: number }[], includeThis: boolean) => {
    let r: number | null = null;
    for (const h of hist) {
      const j = order.get(h.matchId) ?? -1;
      if (j < k || (includeThis && j === k)) r = h.rating;
    }
    return r;
  };
  const standings = (includeThis: boolean) => {
    const rated = d.players
      .map((p) => ({ puuid: p.puuid, rating: ratingAt(p.ratingHistory, includeThis) }))
      .filter((x): x is { puuid: string; rating: number } => x.rating !== null)
      .sort((a, b) => b.rating - a.rating);
    return new Map(rated.map((x, i) => [x.puuid, { rating: x.rating, rank: i + 1 }]));
  };
  const before = standings(false);
  const after = standings(true);
  return (puuid: string) => {
    const a = after.get(puuid);
    if (!a) return null;
    const delta = d.ratingDelta.get(`${m.id}:${puuid}`) ?? 0;
    return { before: before.get(puuid) ?? { rating: a.rating - delta, rank: null as number | null }, after: a, delta };
  };
}

export function gameEmbed(m: Match, d: Dataset, s: Static, site: string, pred?: Prediction | null, tags: Map<string, string> = new Map()) {
  const blueWon = m.teams.find((t) => t.teamId === 100)?.win ?? m.players.find((p) => p.teamId === 100)?.win ?? false;
  const mvp = d.mvpOf.get(m.id);
  const move = movement(m, d);
  const player = (p: MatchPlayer, links = true) => {
    const name = p.isBot ? `${champName(s, p.championId)} bot` : p.name;
    const user = p.isBot ? undefined : tags.get(p.puuid);
    const linked = user ? `<@${user}>` : p.isBot || !links ? name : `[${name}](${site}/players/${encodeURIComponent(p.puuid)})`;
    const head = `${mvp === p.puuid ? "⭐ " : ""}**${linked}** · ${champName(s, p.championId)} \`${p.kills}/${p.deaths}/${p.assists}\``;
    const mv = p.isBot ? null : move(p.puuid);
    if (!mv) return head;
    const sign = mv.delta >= 0 ? "+" : "";
    const b = mv.before.rank;
    const a = mv.after.rank;
    const place =
      b === null ? `new at #${a}` : b === a ? `#${a}` : `#${b} → #${a} ${a < b ? "▲" : "▼"}${Math.abs(b - a)}`;
    return `${head}\n${mv.before.rating} → **${mv.after.rating}** (${sign}${mv.delta}) · ${place}`;
  };
  const side = (team: 100 | 200) => {
    const ps = m.players.filter((p) => p.teamId === team);
    const t = m.teams.find((x) => x.teamId === team);
    const kills = t?.kills ?? ps.reduce((a, p) => a + p.kills, 0);
    const won = (team === 100) === blueWon;
    return {
      name: `${team === 100 ? "🔵 Blue" : "🔴 Red"} ${won ? "won" : "lost"} · ${kills} kills`,
      // Discord caps a field at 1024 characters; drop the profile links if they'd push it over.
      value: (() => {
        const full = ps.map((p) => player(p)).join("\n");
        return (full.length <= 1024 ? full : ps.map((p) => player(p, false)).join("\n").slice(0, 1024)) || "—";
      })(),
      inline: true,
    };
  };

  return {
    title: `${blueWon ? "Blue" : "Red"} side wins in ${clock(m.duration)}`,
    url: `${site}/matches/${encodeURIComponent(m.id)}`,
    color: blueWon ? BLUE : RED,
    description: highlights(m, s, mvp).join("\n") || undefined,
    fields: [side(100), side(200), ...(pred?.settled ? [{ name: "🔮 Predictions", value: settledLine(pred).slice(0, 1024), inline: false }] : [])],
    footer: { text: `Custom game · ${m.mode === "CLASSIC" ? "Summoner's Rift" : m.mode}` },
    timestamp: new Date(m.playedAt + m.duration * 1000).toISOString(),
  };
}

/** A few lines worth bragging (or laughing) about. */
function highlights(m: Match, s: Static, mvp: string | undefined): string[] {
  const humans = m.players.filter((p) => !p.isBot);
  const out: string[] = [];
  const champ = (p: MatchPlayer) => champName(s, p.championId);
  const line = (p: MatchPlayer) => `${p.kills}/${p.deaths}/${p.assists}`;

  const best = humans.find((p) => p.puuid === mvp);
  if (best) out.push(`⭐ **MVP: ${best.name}** on ${champ(best)}, ${line(best)}`);
  for (const p of humans) {
    if (p.pentaKills) out.push(`🔥 **${p.name} got a PENTAKILL** on ${champ(p)}${p.pentaKills > 1 ? ` (×${p.pentaKills})` : ""}`);
    else if (p.quadraKills) out.push(`💥 ${p.name} got a quadra kill on ${champ(p)}`);
  }
  const perfect = humans.filter((p) => p.deaths === 0 && p.kills + p.assists >= 8 && p.puuid !== mvp);
  for (const p of perfect) out.push(`🛡️ ${p.name} didn't die once (${line(p)})`);
  const fed = [...humans].sort((a, b) => b.deaths - a.deaths)[0];
  if (fed && fed.deaths >= 10) out.push(`💀 ${fed.name} died ${fed.deaths} times on ${champ(fed)}`);
  const dmg = [...humans].sort((a, b) => b.damageToChampions - a.damageToChampions)[0];
  if (dmg && dmg.puuid !== mvp) out.push(`⚔️ Most damage: ${dmg.name}, ${Math.round(dmg.damageToChampions / 1000)}k`);
  return out.slice(0, 6);
}

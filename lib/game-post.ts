// Posts each newly uploaded game to a Discord channel through a channel webhook
// (set on the site's /discord page). No bot permissions needed.

import "server-only";
import { store } from "./store";
import { buildDataset, clock, type Dataset } from "./stats";
import { champName, getStatic, type Static } from "./ddragon";
import type { Match, MatchPlayer } from "./types";
import { settledLine, type Prediction } from "./predictions";

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
export async function postGame(matchId: string, site: string, pred?: Prediction | null) {
  try {
    const hook = await getWebhook();
    if (!hook) return;
    const [d, s] = await Promise.all([store().all().then(buildDataset), getStatic()]);
    const m = d.matches.find((x) => x.id === matchId);
    if (!m) return;
    const res = await fetch(`${hook}?wait=true`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "custy.gg", embeds: [gameEmbed(m, d, s, site, pred)] }),
    });
    console.log(`[post] ${matchId} -> Discord ${res.status}${res.ok ? "" : ` ${await res.text().catch(() => "")}`}`);
  } catch (e) {
    console.log(`[post] ${matchId} failed: ${(e as Error).message}`);
  }
}

export function gameEmbed(m: Match, d: Dataset, s: Static, site: string, pred?: Prediction | null) {
  const blueWon = m.teams.find((t) => t.teamId === 100)?.win ?? m.players.find((p) => p.teamId === 100)?.win ?? false;
  const mvp = d.mvpOf.get(m.id);
  const delta = (p: MatchPlayer) => d.ratingDelta.get(`${m.id}:${p.puuid}`);
  const player = (p: MatchPlayer) => {
    const name = p.isBot ? `${champName(s, p.championId)} bot` : p.name;
    const linked = p.isBot ? name : `[${name}](${site}/players/${encodeURIComponent(p.puuid)})`;
    return `${mvp === p.puuid ? "⭐ " : ""}**${linked}** · ${champName(s, p.championId)}\n\`${p.kills}/${p.deaths}/${p.assists}\``;
  };
  const side = (team: 100 | 200) => {
    const ps = m.players.filter((p) => p.teamId === team);
    const t = m.teams.find((x) => x.teamId === team);
    const kills = t?.kills ?? ps.reduce((a, p) => a + p.kills, 0);
    const change = ps.find((p) => !p.isBot && delta(p) !== undefined);
    const ch = change ? delta(change)! : null;
    const won = (team === 100) === blueWon;
    return {
      name: `${team === 100 ? "🔵 Blue" : "🔴 Red"} ${won ? "won" : "lost"} · ${kills} kills${ch !== null ? ` · ${ch >= 0 ? "+" : ""}${ch} rating` : ""}`,
      value: ps.map(player).join("\n").slice(0, 1024) || "—",
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

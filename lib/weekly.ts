// Weekly recap posted to the Discord channel every Monday morning (Vercel cron),
// covering Monday to Sunday of the week before.

import "server-only";
import { store } from "./store";
import { buildDataset, kda, START_RATING, type Dataset } from "./stats";
import { champName, getStatic, type Static } from "./ddragon";
import { getWebhook } from "./game-post";
import { discordByPuuid } from "./discord-links";
import type { Match, MatchPlayer } from "./types";

const TZ = process.env.NEXT_PUBLIC_TIMEZONE || "America/New_York";
const GOLD = 0xe3b866;
const DAY = 24 * 60 * 60 * 1000;

/** Midnight at the start of Monday of the week containing `t`, in the group's time zone. */
export function weekStart(t: number): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { timeZone: TZ, year: "numeric", month: "numeric", day: "numeric", weekday: "short", hour: "numeric", minute: "numeric", second: "numeric", hourCycle: "h23" })
      .formatToParts(new Date(t))
      .map((p) => [p.type, p.value]),
  );
  const dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday);
  const sinceMidnight = (Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second)) * 1000;
  const guess = t - sinceMidnight - dow * DAY;
  // Snap to local midnight (handles daylight saving changes during the week).
  const h = Number(new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" }).format(new Date(guess)));
  return guess - (h > 12 ? h - 24 : h) * 3600 * 1000;
}

const day = (t: number) => new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric" }).format(new Date(t));
const hours = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m` : `${Math.round(s / 60)}m`);
const signed = (n: number) => `${n >= 0 ? "+" : ""}${n}`;
const pct = (w: number, g: number) => `${Math.round((w / g) * 100)}%`;

function ratingAt(hist: { rating: number; at: number }[], t: number) {
  let r = START_RATING;
  for (const h of hist) if (h.at < t) r = h.rating;
  return r;
}

interface Line { name: string; puuid: string; games: number; wins: number; k: number; d: number; a: number; mvps: number }

export function recapEmbed(d: Dataset, s: Static, from: number, to: number, site: string, tags: Map<string, string> = new Map()) {
  const games = d.matches.filter((m) => !m.remake && m.playedAt >= from && m.playedAt < to).sort((a, b) => a.playedAt - b.playedAt);
  const range = `${day(from)} – ${day(to - 1)}`;
  if (!games.length) {
    return { title: `Weekly recap · ${range}`, color: GOLD, description: "No custom games this week. Get the lobby going! 🎮" };
  }

  // Per-player totals for the week.
  const by = new Map<string, Line>();
  for (const m of games) {
    const mvp = d.mvpOf.get(m.id);
    for (const p of m.players) {
      if (p.isBot) continue;
      const l = by.get(p.puuid) ?? { name: p.name, puuid: p.puuid, games: 0, wins: 0, k: 0, d: 0, a: 0, mvps: 0 };
      l.name = p.name;
      l.games++;
      if (p.win) l.wins++;
      l.k += p.kills; l.d += p.deaths; l.a += p.assists;
      if (mvp === p.puuid) l.mvps++;
      by.set(p.puuid, l);
    }
  }
  const lines = [...by.values()];
  const player = (puuid: string) => d.players.find((p) => p.puuid === puuid);
  const link = (l: { name: string; puuid: string }) =>
    `[${l.name}](${site}/players/${encodeURIComponent(l.puuid)})${tags.get(l.puuid) ? ` (<@${tags.get(l.puuid)}>)` : ""}`;

  // Rating movement over the week.
  const moves = lines
    .map((l) => {
      const hist = player(l.puuid)?.ratingHistory ?? [];
      return { ...l, change: ratingAt(hist, to) - ratingAt(hist, from), now: ratingAt(hist, to) };
    })
    .sort((a, b) => b.change - a.change);
  const climbers = moves.filter((x) => x.change > 0).slice(0, 3);
  const fallers = moves.filter((x) => x.change < 0).reverse().slice(0, 3);

  const fields: { name: string; value: string; inline?: boolean }[] = [];
  const medal = ["🥇", "🥈", "🥉"];
  if (climbers.length) fields.push({ name: "📈 Biggest climbers", value: climbers.map((x, i) => `${medal[i]} ${link(x)} **${signed(x.change)}** → ${x.now}`).join("\n"), inline: true });
  if (fallers.length) fields.push({ name: "📉 Rough week", value: fallers.map((x) => `${link(x)} **${x.change}** → ${x.now}`).join("\n"), inline: true });

  const minGames = Math.min(3, Math.max(1, Math.floor(games.length / 3)));
  const records = lines.filter((l) => l.games >= minGames).sort((a, b) => b.wins / b.games - a.wins / a.games || b.wins - a.wins);
  const mostGames = [...lines].sort((a, b) => b.games - a.games)[0];
  const mostMvps = [...lines].sort((a, b) => b.mvps - a.mvps || b.wins - a.wins)[0];
  const bestKda = lines.filter((l) => l.games >= minGames).sort((a, b) => kda(b.k, b.d, b.a) - kda(a.k, a.d, a.a))[0];
  const awards = [
    records[0] && `🏆 **Best record:** ${link(records[0])} ${records[0].wins}-${records[0].games - records[0].wins} (${pct(records[0].wins, records[0].games)})`,
    mostMvps?.mvps && `⭐ **Most MVPs:** ${link(mostMvps)} ×${mostMvps.mvps}`,
    bestKda && `🎯 **Best KDA:** ${link(bestKda)} ${kda(bestKda.k, bestKda.d, bestKda.a).toFixed(2)}`,
    mostGames && `🎮 **Most games:** ${link(mostGames)} (${mostGames.games})`,
  ].filter(Boolean);
  if (awards.length) fields.push({ name: "Awards", value: awards.join("\n") });

  // Best single games and multikills.
  const all: { m: Match; p: MatchPlayer }[] = games.flatMap((m) => m.players.filter((p) => !p.isBot).map((p) => ({ m, p })));
  const top = <T,>(f: (x: { m: Match; p: MatchPlayer }) => number) => [...all].sort((a, b) => f(b) - f(a))[0] as T & { m: Match; p: MatchPlayer };
  const kills = top((x) => x.p.kills);
  const dmg = top((x) => x.p.damageToChampions);
  const deaths = top((x) => x.p.deaths);
  const ch = (p: MatchPlayer) => champName(s, p.championId);
  const big = [
    ...all.filter((x) => x.p.pentaKills).map((x) => `🔥 **PENTAKILL:** ${x.p.name} on ${ch(x.p)}`),
    ...all.filter((x) => !x.p.pentaKills && x.p.quadraKills).map((x) => `💥 Quadra: ${x.p.name} on ${ch(x.p)}`),
    `⚔️ Most kills: ${kills.p.name}, ${kills.p.kills} on ${ch(kills.p)}`,
    `💣 Most damage: ${dmg.p.name}, ${Math.round(dmg.p.damageToChampions / 1000)}k on ${ch(dmg.p)}`,
    deaths.p.deaths >= 8 ? `💀 Most deaths: ${deaths.p.name}, ${deaths.p.deaths} on ${ch(deaths.p)}` : "",
  ].filter(Boolean);
  fields.push({ name: "Big moments", value: big.slice(0, 7).join("\n") });

  // Duo of the week: most wins together on the same team.
  const duos = new Map<string, { a: MatchPlayer; b: MatchPlayer; games: number; wins: number }>();
  for (const m of games) {
    const hs = m.players.filter((p) => !p.isBot);
    for (let i = 0; i < hs.length; i++)
      for (let j = i + 1; j < hs.length; j++) {
        if (hs[i].teamId !== hs[j].teamId) continue;
        const [a, b] = hs[i].puuid < hs[j].puuid ? [hs[i], hs[j]] : [hs[j], hs[i]];
        const k = `${a.puuid}|${b.puuid}`;
        const e = duos.get(k) ?? { a, b, games: 0, wins: 0 };
        e.games++;
        if (a.win) e.wins++;
        duos.set(k, e);
      }
  }
  const duo = [...duos.values()].filter((x) => x.games >= 2).sort((x, y) => y.wins - x.wins || y.wins / y.games - x.wins / x.games)[0];

  // Champions this week.
  const picks = new Map<number, number>();
  const bans = new Map<number, number>();
  for (const m of games) {
    for (const p of m.players) picks.set(p.championId, (picks.get(p.championId) ?? 0) + 1);
    for (const t of m.teams) for (const b of t.bans) if (b > 0) bans.set(b, (bans.get(b) ?? 0) + 1);
  }
  const topPick = [...picks.entries()].sort((a, b) => b[1] - a[1])[0];
  const topBan = [...bans.entries()].sort((a, b) => b[1] - a[1])[0];
  const misc = [
    duo && `🤝 **Duo of the week:** ${duo.a.name} + ${duo.b.name}, ${duo.wins}-${duo.games - duo.wins} together`,
    topPick && `🛡️ **Most picked:** ${champName(s, topPick[0])} (${topPick[1]})`,
    topBan && `🚫 **Most banned:** ${champName(s, topBan[0])} (${topBan[1]})`,
  ].filter(Boolean);
  if (misc.length) fields.push({ name: "This week's meta", value: misc.join("\n") });

  // Standings now.
  const standings = d.players.slice(0, 5).map((p, i) => `${medal[i] ?? `${i + 1}.`} ${link(p)} ${ratingAt(p.ratingHistory, to)}`);
  fields.push({ name: "Top of the standings", value: standings.join("\n") });

  const blueWins = games.filter((m) => (m.teams.find((t) => t.teamId === 100)?.win ?? false)).length;
  const played = games.reduce((a, m) => a + m.duration, 0);
  return {
    title: `📅 Weekly recap · ${range}`,
    url: `${site}/`,
    color: GOLD,
    description:
      `**${games.length} game${games.length === 1 ? "" : "s"}** with **${lines.length} players**, ${hours(played)} on the Rift. ` +
      `Blue won ${blueWins}, Red won ${games.length - blueWins}.`,
    fields: fields.map((f) => ({ ...f, value: f.value.slice(0, 1024) })),
  };
}

/** Posts the recap for [from, to). `label` goes in the footer. */
export async function postRecap(from: number, to: number, site: string, label: string, ping = true) {
  const hook = await getWebhook();
  if (!hook) return { ok: false, status: 0, reason: "No Discord channel connected." };
  const [d, s, tags] = await Promise.all([store().all().then(buildDataset), getStatic(), discordByPuuid()]);
  const embed = { ...recapEmbed(d, s, from, to, site, tags), footer: { text: label } };
  // Ping everyone linked who played that week (mentions inside the embed alone don't notify).
  const played = new Set(d.matches.filter((m) => !m.remake && m.playedAt >= from && m.playedAt < to).flatMap((m) => m.players.map((p) => p.puuid)));
  const users = ping ? ([...played].map((p) => tags.get(p)).filter(Boolean) as string[]) : [];
  const link = (lbl: string, url: string, emoji: string) => ({ type: 2, style: 5, label: lbl, url, emoji: { name: emoji } });
  const res = await fetch(`${hook}?wait=true&with_components=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: "custy.gg",
      content: users.length ? `This week's players: ${users.map((u) => `<@${u}>`).join(" ")}` : undefined,
      embeds: [embed],
      allowed_mentions: { parse: [], users },
      components: [{ type: 1, components: [link("Standings", `${site}/`, "🏆"), link("Records", `${site}/records`, "📈"), link("Duos", `${site}/duos`, "🤝")] }],
    }),
  });
  const detail = res.ok ? "" : await res.text().catch(() => "");
  console.log(`[recap] ${new Date(from).toISOString()} -> Discord ${res.status} ${detail}`);
  return { ok: res.ok, status: res.status, reason: detail };
}

/** Monday's job: last week's recap, once. */
export async function postLastWeek(site: string) {
  const to = weekStart(Date.now());
  const from = weekStart(to - DAY);
  const key = "recap:last";
  if ((await store().getSetting(key)) === String(from)) return { ok: true, status: 0, reason: "Already posted." };
  const r = await postRecap(from, to, site, "Weekly recap · posts every Monday morning");
  if (r.ok) await store().setSetting(key, String(from));
  return r;
}

/** This week so far (for testing). */
export const postThisWeek = (site: string) => postRecap(weekStart(Date.now()), Date.now() + 1, site, "Test post · this week so far", false);

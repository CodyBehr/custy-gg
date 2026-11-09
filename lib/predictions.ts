// Predictions with fake points. People vote Blue or Red under a team split; when
// the game with those teams uploads, correct votes earn points. Calling the side
// fewer people picked pays more: points = 100 × (all votes ÷ votes for the winner).

import "server-only";
import { store } from "./store";
import { PLAYER_LINKS } from "./player-links";
import type { Match } from "./types";

export const VOTE_WINDOW_MS = 15 * 60 * 1000;
const MATCH_WINDOW_MS = 4 * 60 * 60 * 1000; // a prediction can settle against a game ending within 4 hours
const INDEX = "pred:index";
const BOARD = "pred:board";

export interface Vote { side: 0 | 1; name: string }

export interface Prediction {
  id: string;
  createdAt: number;
  closesAt: number;
  blue: string[];          // puuids (main accounts) on each side; players we can't identify are left out
  red: string[];
  votes: Record<string, Vote>; // Discord user id -> vote
  message: { embeds: any[]; components: any[]; content?: string; allowed_mentions?: object }; // the teams message, without the predictions bits
  settled?: { matchId: string; winner: 0 | 1; results: { name: string; side: 0 | 1; points: number }[] };
}

export interface BoardEntry { name: string; points: number; right: number; wrong: number }

const main = (puuid: string) => PLAYER_LINKS[puuid] ?? puuid;

async function load(id: string): Promise<Prediction | null> {
  const raw = await store().getSetting(`pred:${id}`);
  return raw ? (JSON.parse(raw) as Prediction) : null;
}
const save = (p: Prediction) => store().setSetting(`pred:${p.id}`, JSON.stringify(p));

export async function createPrediction(id: string, blue: (string | undefined)[], red: (string | undefined)[], message: Prediction["message"]) {
  const now = Date.now();
  const p: Prediction = {
    id, createdAt: now, closesAt: now + VOTE_WINDOW_MS,
    blue: blue.filter(Boolean).map((x) => main(x!)), red: red.filter(Boolean).map((x) => main(x!)),
    votes: {}, message,
  };
  await save(p);
  const index = JSON.parse((await store().getSetting(INDEX)) ?? "[]") as string[];
  await store().setSetting(INDEX, JSON.stringify([id, ...index.filter((x) => x !== id)].slice(0, 30)));
  return p;
}

export async function castVote(id: string, user: string, name: string, side: 0 | 1): Promise<Prediction | string> {
  const p = await load(id);
  if (!p) return "That prediction has expired.";
  if (p.settled) return "That game's already been played.";
  if (Date.now() > p.closesAt) return "Voting's closed for this one.";
  p.votes[user] = { side, name };
  await save(p);
  return p;
}

/** Settles whichever open prediction had the teams this game was played with. */
export async function settleForMatch(m: Match): Promise<Prediction | null> {
  if (m.remake) return null;
  const ended = m.playedAt + m.duration * 1000;
  const gameBlue = new Set(m.players.filter((x) => x.teamId === 100 && !x.isBot).map((x) => main(x.puuid)));
  const gameRed = new Set(m.players.filter((x) => x.teamId === 200 && !x.isBot).map((x) => main(x.puuid)));
  const blueWon = m.teams.find((t) => t.teamId === 100)?.win ?? m.players.find((x) => x.teamId === 100)?.win ?? false;

  const index = JSON.parse((await store().getSetting(INDEX)) ?? "[]") as string[];
  let best: { p: Prediction; swapped: boolean; votes: number } | null = null;
  for (const id of index) {
    const p = await load(id);
    if (!p || p.settled || !Object.keys(p.votes).length) continue;
    if (p.createdAt > ended || ended - p.createdAt > MATCH_WINDOW_MS) continue;
    const known = p.blue.length + p.red.length;
    if (known < 2) continue;
    const same = p.blue.filter((x) => gameBlue.has(x)).length + p.red.filter((x) => gameRed.has(x)).length;
    const swap = p.blue.filter((x) => gameRed.has(x)).length + p.red.filter((x) => gameBlue.has(x)).length;
    const fit = Math.max(same, swap);
    if (fit < Math.ceil(known * 0.8)) continue; // allow a sub or two
    const votes = Object.keys(p.votes).length;
    if (!best || votes > best.votes || (votes === best.votes && p.createdAt > best.p.createdAt)) best = { p, swapped: swap > same, votes };
  }
  if (!best) return null;

  // Which of the prediction's sides won (the teams may have swapped sides in the lobby).
  const predBlueWon = best.swapped ? !blueWon : blueWon;
  const winner: 0 | 1 = predBlueWon ? 0 : 1;
  const votes = Object.entries(best.p.votes);
  const right = votes.filter(([, v]) => v.side === winner).length;
  const payout = right ? Math.round((100 * votes.length) / right) : 0;

  const board = JSON.parse((await store().getSetting(BOARD)) ?? "{}") as Record<string, BoardEntry>;
  const results = votes.map(([user, v]) => {
    const ok = v.side === winner;
    const e = board[user] ?? { name: v.name, points: 0, right: 0, wrong: 0 };
    e.name = v.name;
    e.points += ok ? payout : 0;
    if (ok) e.right++;
    else e.wrong++;
    board[user] = e;
    return { name: v.name, side: v.side, points: ok ? payout : 0 };
  });
  best.p.settled = { matchId: m.id, winner, results };
  await save(best.p);
  await store().setSetting(BOARD, JSON.stringify(board));
  console.log(`[pred] ${best.p.id} settled by ${m.id}: ${right}/${votes.length} right, +${payout} each`);
  return best.p;
}

export async function leaderboard(): Promise<BoardEntry[]> {
  const board = JSON.parse((await store().getSetting(BOARD)) ?? "{}") as Record<string, BoardEntry>;
  return Object.values(board).sort((a, b) => b.points - a.points || b.right - a.right);
}

/** The teams message with the current votes and the vote buttons added. */
export function renderPrediction(p: Prediction) {
  const blue = Object.values(p.votes).filter((v) => v.side === 0).map((v) => v.name);
  const red = Object.values(p.votes).filter((v) => v.side === 1).map((v) => v.name);
  const open = Date.now() <= p.closesAt && !p.settled;
  const closes = Math.floor(p.closesAt / 1000);
  const value =
    (blue.length || red.length
      ? `🔵 ${blue.length ? blue.join(", ") : "—"}\n🔴 ${red.length ? red.join(", ") : "—"}\n`
      : "No votes yet. ") +
    (open ? `Voting closes <t:${closes}:R>. Calling the upset pays more.` : "Voting's closed.");
  const [first, ...rest] = p.message.embeds;
  const embeds = [{ ...first, fields: [...(first.fields ?? []), { name: "🔮 Who wins?", value: value.slice(0, 1024), inline: false }] }, ...rest];
  const components = [
    ...p.message.components,
    {
      type: 1,
      components: [
        { type: 2, style: 1, label: "Blue wins", custom_id: `vote:${p.id}:0`, emoji: { name: "🔵" }, disabled: !open },
        { type: 2, style: 4, label: "Red wins", custom_id: `vote:${p.id}:1`, emoji: { name: "🔴" }, disabled: !open },
        { type: 2, style: 2, label: "Leaderboard", custom_id: "predboard", emoji: { name: "🏆" } },
      ],
    },
  ];
  return { content: p.message.content, allowed_mentions: p.message.allowed_mentions, embeds, components };
}

/** One line for the game post: who called it. */
export function settledLine(p: Prediction): string {
  const s = p.settled!;
  const right = s.results.filter((r) => r.points > 0);
  const wrong = s.results.filter((r) => r.points === 0);
  const parts = [];
  if (right.length) parts.push(`✅ ${right.map((r) => `${r.name} +${r.points}`).join(", ")}`);
  if (wrong.length) parts.push(`❌ ${wrong.map((r) => r.name).join(", ")}`);
  return parts.join("\n") || "No votes.";
}

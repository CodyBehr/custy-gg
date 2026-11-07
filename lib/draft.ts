// Captain draft: two captains take turns picking players, snake order
// (A, B, B, A, A, B, B, A...). Pure logic; the Discord side is in app/api/discord.

import type { TeamPlayer } from "./teams";

export interface Draft {
  players: TeamPlayer[];
  captains: [number, number];       // indexes into players; captains[0] is blue
  teams: [number[], number[]];      // picked players (captains not included)
  firstPick: 0 | 1;                 // which captain picks first
  owners: [string | null, string | null]; // Discord user picking for each captain (claimed on first pick)
  host: string | null;              // who started the draft; can pick for either side
  done: boolean;
}

export function newDraft(players: TeamPlayer[], host: string | null, rand: () => number = Math.random): Draft {
  const idx = players.map((_, i) => i);
  const a = idx.splice(Math.floor(rand() * idx.length), 1)[0];
  const b = idx.splice(Math.floor(rand() * idx.length), 1)[0];
  return { players, captains: [a, b], teams: [[], []], firstPick: rand() < 0.5 ? 0 : 1, owners: [null, null], host, done: false };
}

export const picksMade = (d: Draft) => d.teams[0].length + d.teams[1].length;

/** Players not on a team yet. */
export const remaining = (d: Draft) =>
  d.players.map((_, i) => i).filter((i) => !d.captains.includes(i) && !d.teams[0].includes(i) && !d.teams[1].includes(i));

/** Whose pick it is (0 or 1), snake order: A B B A A B B A... */
export function turn(d: Draft): 0 | 1 {
  const n = picksMade(d);
  const first = Math.floor((n + 1) / 2) % 2 === 0;
  return (first ? d.firstPick : 1 - d.firstPick) as 0 | 1;
}

/** The roster of one side, captain first. */
export const roster = (d: Draft, side: 0 | 1) => [d.captains[side], ...d.teams[side]].map((i) => d.players[i]);

export type PickResult = { ok: true } | { ok: false; reason: string };

/** Picks a player for whoever's turn it is, checking that the clicker may pick for that captain. */
export function pick(d: Draft, playerIdx: number, user: string | null): PickResult {
  if (d.done) return { ok: false, reason: "This draft is finished." };
  if (!remaining(d).includes(playerIdx)) return { ok: false, reason: "That player's already been picked." };
  const t = turn(d);
  const captain = d.players[d.captains[t]].name;
  if (user && d.owners[t] !== user) {
    if (d.owners[t] === null && d.owners[1 - t] !== user) d.owners[t] = user; // first click claims this captain
    else if (user !== d.host) return { ok: false, reason: `It's ${captain}'s pick.` };
  }
  d.teams[t].push(playerIdx);
  // The last player goes to whoever's turn is next.
  const left = remaining(d);
  if (left.length === 1) d.teams[turn(d)].push(left[0]);
  if (remaining(d).length === 0) d.done = true;
  return { ok: true };
}

/** Swaps in two new random captains (only before anyone's been picked). */
export function newCaptains(d: Draft, rand: () => number = Math.random): Draft {
  return { ...newDraft(d.players, d.host, rand) };
}

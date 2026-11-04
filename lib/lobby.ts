// The custom-game lobby someone's collector last saw, and turning a list of
// names into rated players for the team maker.

import "server-only";
import { store } from "./store";
import { getDataset, searchPlayers, START_RATING } from "./stats";
import { PLAYER_LINKS } from "./player-links";
import type { TeamPlayer } from "./teams";
import { getRanks } from "./rank-store";

export interface LobbyMember {
  puuid?: string;
  name: string;
  tag?: string;
  team?: 100 | 200 | 0;   // 0 = spectator or unknown
}

export interface Lobby {
  members: LobbyMember[];
  updatedAt: number;      // ms
  uploader?: string;      // Riot ID of whoever's app sent it
}

export const LOBBY_FRESH_MS = 30 * 60 * 1000;

export async function getLobby(): Promise<Lobby | null> {
  const raw = await store().getSetting("lobby");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Lobby;
  } catch {
    return null;
  }
}

export async function saveLobby(lobby: Lobby) {
  await store().setSetting("lobby", JSON.stringify(lobby));
}

/** Looks each name or lobby member up on the site to get their rating. */
export async function ratePlayers(entries: { name: string; puuid?: string }[]): Promise<TeamPlayer[]> {
  const d = await getDataset();
  const rated = entries.map((e) => {
    const main = e.puuid ? PLAYER_LINKS[e.puuid] ?? e.puuid : undefined;
    let p = main ? d.byPuuid.get(main) : undefined;
    if (!p) {
      const hits = searchPlayers(d.players, e.name);
      const exact = hits.find((h) => h.name.toLowerCase() === e.name.toLowerCase().split("#")[0]);
      p = exact ?? (hits.length === 1 ? hits[0] : undefined);
    }
    return p
      ? { name: p.name, rating: p.rating, custy: p.rating, known: true, puuid: p.puuid }
      : { name: e.name.split("#")[0], rating: START_RATING, known: false, puuid: e.puuid };
  });
  const ranks = await getRanks(rated.map((p) => p.puuid));
  return rated.map((p) => ({ ...p, rank: p.puuid ? ranks.get(p.puuid) ?? null : null }));
}

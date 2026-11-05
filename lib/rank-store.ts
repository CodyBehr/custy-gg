// Where solo queue ranks are kept: one settings row per player ("rank:<puuid>").

import "server-only";
import { store } from "./store";
import { cleanRank, type Rank } from "./ranks";
import { PLAYER_LINKS } from "./player-links";

const key = (puuid: string) => `rank:${PLAYER_LINKS[puuid] ?? puuid}`;

export async function getRanks(puuids: (string | undefined)[]): Promise<Map<string, Rank>> {
  const out = new Map<string, Rank>();
  const ids = [...new Set(puuids.filter(Boolean) as string[])];
  // One query for everyone: lots of small queries at once can stall the database pooler.
  const rows = await store().getSettings([...new Set(ids.map(key))]);
  for (const p of ids) {
    const raw = rows[key(p)];
    if (!raw) continue;
    try {
      out.set(p, JSON.parse(raw));
    } catch {
      /* ignore a bad row */
    }
  }
  return out;
}

/** Saves ranks the collector sent: { puuid: rank }. Linked accounts share their main's row; the higher rank wins. */
export async function saveRanks(input: Record<string, unknown>) {
  const entries = Object.entries(input).slice(0, 50);
  let saved = 0;
  for (const [puuid, raw] of entries) {
    if (typeof puuid !== "string" || puuid.length < 20) continue;
    const r = cleanRank(raw);
    if (!r) continue;
    if (PLAYER_LINKS[puuid] && !r.tier) continue; // an unranked alt shouldn't overwrite the main's rank
    await store().setSetting(key(puuid), JSON.stringify(r));
    saved++;
  }
  return saved;
}

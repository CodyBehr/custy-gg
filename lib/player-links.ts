import type { Match } from "./types";

// Accounts that belong to the same person. Each entry maps an extra account's
// PUUID to the PUUID of the account their stats should be counted under.
// Every page then treats them as one player: one rating, one profile, one
// match history. The profile lists the other account names.
//
// To find a PUUID, open the player's page on the site: it's the long id at the
// end of the address, e.g. /players/407f5693-6ae2-546d-bbf6-cae18e99474c.

export const PLAYER_LINKS: Record<string, string> = {
  // big booler#NA1 -> yung stunny#NA1
  "9159cb71-175f-5a5a-b2aa-10717b7aaaa2": "407f5693-6ae2-546d-bbf6-cae18e99474c",
  // Django#Fox -> can u feel my#heart (shown as buckley)
  "bc1fa0d6-5057-59c6-aaec-e592564340b6": "68906810-e02e-5129-9bb4-9a03e9ab9f7c",
};

// Names to show instead of the one in the game data, for players who renamed
// their Riot ID before playing a tracked game under the new name. Keyed by the
// main account's PUUID. Remove an entry once games under the new name come in.
export const PLAYER_NAMES: Record<string, { name: string; tag?: string }> = {
  "68906810-e02e-5129-9bb4-9a03e9ab9f7c": { name: "buckley" },
};

/**
 * Rewrites linked accounts (lib/player-links.ts) to their main account, so one
 * person's games all count under one profile and one name. Returns the Riot
 * IDs each main account has also played as.
 */
export function linkAccounts(
  all: Match[],
  links: Record<string, string> = PLAYER_LINKS,
  names: Record<string, { name: string; tag?: string }> = PLAYER_NAMES,
) {
  const otherNames = new Map<string, Set<string>>();
  if (!Object.keys(links).length && !Object.keys(names).length) return { matches: all, otherNames };
  const resolve = (puuid: string) => {
    let id = puuid;
    for (let i = 0; i < 5 && links[id]; i++) id = links[id];
    return id;
  };
  // The name and icon to show for each main account: its newest appearance on
  // the main account itself, or on any linked account if the main never played.
  const display = new Map<string, { name: string; tag: string; profileIcon: number; at: number; own: boolean }>();
  for (const m of all) {
    for (const p of m.players) {
      if (p.isBot) continue;
      const main = resolve(p.puuid);
      if (main === p.puuid && !Object.values(links).includes(p.puuid) && !names[main]) continue;
      const own = main === p.puuid;
      const cur = display.get(main);
      if (!cur || (own && !cur.own) || (own === cur.own && m.playedAt > cur.at)) {
        display.set(main, { name: p.name, tag: p.tag, profileIcon: p.profileIcon, at: m.playedAt, own });
      }
    }
  }
  for (const [main, shown] of display) {
    const override = names[main];
    if (override) display.set(main, { ...shown, name: override.name, tag: override.tag ?? shown.tag });
  }
  const remember = (main: string, riotId: string) => {
    const set = otherNames.get(main) ?? new Set<string>();
    set.add(riotId);
    otherNames.set(main, set);
  };
  const matches = all.map((m) => {
    if (!m.players.some((p) => resolve(p.puuid) !== p.puuid || names[p.puuid])) return m;
    const present = new Set(m.players.map((p) => p.puuid));
    return {
      ...m,
      players: m.players.map((p) => {
        const main = resolve(p.puuid);
        const shown = display.get(main);
        if (main === p.puuid) {
          // The main account itself: only its display name may change.
          if (!names[main] || !shown) return p;
          remember(main, `${p.name}#${p.tag}`);
          return { ...p, name: shown.name, tag: shown.tag };
        }
        // If both accounts were somehow in the same game, leave them separate.
        if (present.has(main) || !shown) return p;
        remember(main, `${p.name}#${p.tag}`);
        return { ...p, puuid: main, name: shown.name, tag: shown.tag, profileIcon: shown.profileIcon || p.profileIcon };
      }),
    };
  });
  return { matches, otherNames };
}


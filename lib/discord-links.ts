// Which Discord user is which League player, so the bot can @mention people.
// People link themselves from the "Link my account" button under a team split.

import "server-only";
import { store } from "./store";
import { PLAYER_LINKS } from "./player-links";

const KEY = "discord:links"; // { discordUserId: puuid (main account) }
const main = (p: string) => PLAYER_LINKS[p] ?? p;

export type Links = Record<string, string>;

export async function getLinks(): Promise<Links> {
  try {
    return JSON.parse((await store().getSetting(KEY)) ?? "{}") as Links;
  } catch {
    return {};
  }
}

/** puuid (main account) -> Discord user id */
export async function discordByPuuid(): Promise<Map<string, string>> {
  const links = await getLinks();
  return new Map(Object.entries(links).map(([user, puuid]) => [main(puuid), user]));
}

export async function puuidForDiscord(user: string): Promise<string | null> {
  const p = (await getLinks())[user];
  return p ? main(p) : null;
}

/** Links a Discord user to a League player; a player has one Discord user, so an older link to them is replaced. */
export async function linkDiscord(user: string, puuid: string | null) {
  const links = await getLinks();
  if (puuid) {
    const target = main(puuid);
    for (const [u, p] of Object.entries(links)) if (main(p) === target) delete links[u];
    links[user] = target;
  } else {
    delete links[user];
  }
  await store().setSetting(KEY, JSON.stringify(links));
}

/** "<@123>" (or the raw id) typed into a command -> the Discord user id. */
export const mentionedUser = (s: string) => s.trim().match(/^<@!?(\d{5,25})>$/)?.[1] ?? null;

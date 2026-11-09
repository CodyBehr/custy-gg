// Discord slash commands, answered over HTTP by this site (no bot process to run).
// Discord signs every request; we check the signature with the app's public key.

import "server-only";
import crypto from "node:crypto";

export const DISCORD_APP_ID = process.env.DISCORD_APP_ID ?? "";
export const DISCORD_PUBLIC_KEY = process.env.DISCORD_PUBLIC_KEY ?? "";

export const InteractionType = { PING: 1, COMMAND: 2, COMPONENT: 3, AUTOCOMPLETE: 4 } as const;
export const ResponseType = { PONG: 1, MESSAGE: 4, UPDATE_MESSAGE: 7 } as const;
export const EPHEMERAL = 1 << 6;

let publicKey: crypto.KeyObject | null = null;

export function verifyDiscordRequest(body: string, signature: string | null, timestamp: string | null): boolean {
  if (!DISCORD_PUBLIC_KEY || !signature || !timestamp) return false;
  try {
    publicKey ??= crypto.createPublicKey({
      key: { kty: "OKP", crv: "Ed25519", x: Buffer.from(DISCORD_PUBLIC_KEY, "hex").toString("base64url") },
      format: "jwk",
    });
    return crypto.verify(null, Buffer.from(timestamp + body), publicKey, Buffer.from(signature, "hex"));
  } catch {
    return false;
  }
}

// Option types: 3 = string, 5 = boolean, 6 = user
export const COMMANDS = [
  {
    name: "custy_teams",
    description: "Make two teams from the current lobby or a list of players",
    options: [
      {
        type: 3, name: "balance", description: "What to balance on (default: custy rating)", required: false,
        choices: [
          { name: "Custy rating", value: "custy" },
          { name: "Solo queue rank", value: "solo" },
          { name: "Random (no balancing)", value: "random" },
        ],
      },
      { type: 3, name: "players", description: "Names separated by commas. Leave empty to use the custom lobby.", required: false },
      { type: 3, name: "together", description: "Must be on the same team, e.g. Ringo, Sevi (separate groups with ;)", required: false },
      { type: 3, name: "apart", description: "Must be on opposite teams, e.g. Vender, Leaden (separate groups with ;)", required: false },
      { type: 3, name: "add", description: "Add players to the lobby list, e.g. someone not in the lobby yet", required: false },
      { type: 3, name: "remove", description: "Leave players out of the lobby list", required: false },
    ],
  },
  { name: "custy_lobby", description: "Show who's in the custom lobby right now, with ratings and ranks" },
  {
    name: "custy_link_account",
    description: "Link your Discord to your League account so the bot can tag you",
    options: [
      { type: 3, name: "player", description: "Your League name (start typing to search)", required: false, autocomplete: true },
      { type: 6, name: "user", description: "Link someone else instead of yourself", required: false },
      { type: 5, name: "unlink", description: "Remove the link", required: false },
    ],
  },
  {
    name: "custy_player",
    description: "Look up a player's custom game stats",
    options: [{ type: 3, name: "player", description: "Riot ID or name", required: true }],
  },
] as const;

/**
 * Registers the slash commands. Accepts either the app's client secret (OAuth2 page)
 * or its bot token (Bot page); bot tokens contain dots, client secrets don't.
 */
export async function registerCommands(appId: string, credential: string) {
  let auth: string;
  if (credential.split(".").length === 3) {
    auth = `Bot ${credential}`;
  } else {
    const tokenRes = await fetch("https://discord.com/api/v10/oauth2/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Authorization: "Basic " + Buffer.from(`${appId}:${credential}`).toString("base64"),
      },
      body: "grant_type=client_credentials&scope=applications.commands.update",
    });
    if (!tokenRes.ok) {
      const detail = await tokenRes.text().catch(() => "");
      console.log(`[discord] client credentials failed ${tokenRes.status}: ${detail}`);
      throw new Error(
        `Discord didn't accept the client secret (${tokenRes.status}${detail ? `: ${detail.slice(0, 200)}` : ""}). ` +
          "Try the bot token instead: Developer Portal, Bot, Reset Token, then paste it here.",
      );
    }
    const { access_token } = (await tokenRes.json()) as { access_token: string };
    auth = `Bearer ${access_token}`;
  }
  const res = await fetch(`https://discord.com/api/v10/applications/${appId}/commands`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: auth },
    body: JSON.stringify(COMMANDS),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    console.log(`[discord] command update failed ${res.status}: ${detail}`);
    throw new Error(`Discord rejected the commands (${res.status}): ${detail.slice(0, 300)}`);
  }
  return ((await res.json()) as { name: string }[]).map((c) => c.name);
}

export const inviteUrl = (appId: string) =>
  `https://discord.com/oauth2/authorize?client_id=${appId}&scope=applications.commands`;

// Discord slash commands, answered over HTTP by this site (no bot process to run).
// Discord signs every request; we check the signature with the app's public key.

import "server-only";
import crypto from "node:crypto";

export const DISCORD_APP_ID = process.env.DISCORD_APP_ID ?? "";
export const DISCORD_PUBLIC_KEY = process.env.DISCORD_PUBLIC_KEY ?? "";

export const InteractionType = { PING: 1, COMMAND: 2, COMPONENT: 3 } as const;
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

// Option types: 3 = string, 5 = boolean
export const COMMANDS = [
  {
    name: "custy_teams",
    description: "Make two teams from the current lobby or a list of players",
    options: [
      { type: 3, name: "players", description: "Names separated by commas. Leave empty to use the custom lobby.", required: false },
      {
        type: 3, name: "mode", description: "Balanced uses custy ratings; random ignores them", required: false,
        choices: [{ name: "Balanced (by rating)", value: "balanced" }, { name: "Random", value: "random" }],
      },
      { type: 3, name: "together", description: "Keep on the same team, e.g. Ringo, Sevi (separate groups with ;)", required: false },
      { type: 3, name: "apart", description: "Put on opposite teams, e.g. Vender, Leaden (separate groups with ;)", required: false },
      { type: 3, name: "add", description: "Add names to the lobby list, e.g. a friend not in the lobby yet", required: false },
      { type: 3, name: "remove", description: "Leave these names out of the lobby list", required: false },
    ],
  },
  { name: "lobby", description: "Show who's in the custom lobby right now" },
  {
    name: "custy",
    description: "Look up a player's custom game stats",
    options: [{ type: 3, name: "player", description: "Riot ID or name", required: true }],
  },
] as const;

export async function registerCommands(appId: string, clientSecret: string) {
  // Client credentials grant: lets the app update its own commands without a bot token.
  const tokenRes = await fetch("https://discord.com/api/v10/oauth2/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: "Basic " + Buffer.from(`${appId}:${clientSecret}`).toString("base64"),
    },
    body: "grant_type=client_credentials&scope=applications.commands.update",
  });
  if (!tokenRes.ok) throw new Error(`Discord didn't accept the client secret (${tokenRes.status}).`);
  const { access_token } = (await tokenRes.json()) as { access_token: string };
  const res = await fetch(`https://discord.com/api/v10/applications/${appId}/commands`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
    body: JSON.stringify(COMMANDS),
  });
  if (!res.ok) throw new Error(`Discord rejected the commands (${res.status}): ${await res.text()}`);
  return ((await res.json()) as { name: string }[]).map((c) => c.name);
}

export const inviteUrl = (appId: string) =>
  `https://discord.com/oauth2/authorize?client_id=${appId}&scope=applications.commands`;

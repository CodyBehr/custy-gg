// Small helpers shared by the ingest API, login and the password gate.
// Uses Web Crypto so it also runs in proxy.ts.

export const AUTH_COOKIE = "custy_auth";

export async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** The value stored in the login cookie for the current SITE_PASSWORD. */
export async function passwordToken(): Promise<string | null> {
  const pw = process.env.SITE_PASSWORD;
  return pw ? sha256(`custy.gg:${pw}`) : null;
}

export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

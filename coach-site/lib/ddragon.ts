// Champion, item, spell and rune icons from Riot's Data Dragon CDN, fetched once a day.

import "server-only";
import { cache } from "react";

const CDN = "https://ddragon.leagueoflegends.com";
const DAY = 86400;

export interface Static {
  version: string;
  champs: Record<number, { id: string; name: string }>;
  spells: Record<number, string>;
  runes: Record<number, string>; // perk or style id -> icon path
}

async function getJson(url: string) {
  const res = await fetch(url, { next: { revalidate: DAY } });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json();
}

export const getStatic = cache(async (): Promise<Static> => {
  const s: Static = { version: "16.23.1", champs: {}, spells: {}, runes: {} };
  try {
    const versions: string[] = await getJson(`${CDN}/api/versions.json`);
    s.version = versions[0];
    const base = `${CDN}/cdn/${s.version}/data/en_US`;
    const [champion, summoner, runes] = await Promise.all([
      getJson(`${base}/champion.json`),
      getJson(`${base}/summoner.json`),
      getJson(`${base}/runesReforged.json`),
    ]);
    for (const c of Object.values<any>(champion.data)) s.champs[Number(c.key)] = { id: c.id, name: c.name };
    for (const sp of Object.values<any>(summoner.data)) s.spells[Number(sp.key)] = sp.id;
    for (const style of runes) {
      s.runes[style.id] = style.icon;
      for (const slot of style.slots) for (const p of slot.runes) s.runes[p.id] = p.icon;
    }
  } catch {
    // Icons just won't show; the page still works.
  }
  return s;
});

export const champIcon = (s: Static, id: number) =>
  s.champs[id] ? `${CDN}/cdn/${s.version}/img/champion/${s.champs[id].id}.png` : "";
export const champName = (s: Static, id: number) => s.champs[id]?.name ?? "Unknown";
export const itemIcon = (s: Static, id: number) => (id ? `${CDN}/cdn/${s.version}/img/item/${id}.png` : "");
export const spellIcon = (s: Static, id: number) =>
  s.spells[id] ? `${CDN}/cdn/${s.version}/img/spell/${s.spells[id]}.png` : "";
export const runeIcon = (s: Static, id: number) => (s.runes[id] ? `${CDN}/cdn/img/${s.runes[id]}` : "");
export const profileIcon = (s: Static, id: number) => `${CDN}/cdn/${s.version}/img/profileicon/${id}.png`;

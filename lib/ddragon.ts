// Champion names, icons and other static data from Riot's Data Dragon CDN.
// Fetched once and cached for a day.

import "server-only";
import { cache } from "react";

const CDN = "https://ddragon.leagueoflegends.com";
const DAY = 60 * 60 * 24;

export interface Static {
  version: string;
  champs: Record<number, { key: string; name: string }>;
  spells: Record<number, string>;   // 4 -> "SummonerFlash"
  runes: Record<number, string>;    // perk or style id -> icon path
  runeNames: Record<number, string>;
  items: Record<number, string>;    // id -> name
}

async function getJson(url: string) {
  const res = await fetch(url, { next: { revalidate: DAY } });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json();
}

export const getStatic = cache(async (): Promise<Static> => {
  const empty: Static = { version: "16.21.1", champs: {}, spells: {}, runes: {}, runeNames: {}, items: {} };
  try {
    const versions: string[] = await getJson(`${CDN}/api/versions.json`);
    const v = versions[0];
    const base = `${CDN}/cdn/${v}/data/en_US`;
    const [champion, summoner, runes, item] = await Promise.all([
      getJson(`${base}/champion.json`),
      getJson(`${base}/summoner.json`),
      getJson(`${base}/runesReforged.json`),
      getJson(`${base}/item.json`),
    ]);
    const s: Static = { ...empty, version: v };
    for (const c of Object.values<any>(champion.data)) s.champs[Number(c.key)] = { key: c.id, name: c.name };
    for (const sp of Object.values<any>(summoner.data)) s.spells[Number(sp.key)] = sp.id;
    for (const style of runes) {
      s.runes[style.id] = style.icon;
      s.runeNames[style.id] = style.name;
      for (const slot of style.slots) for (const r of slot.runes) {
        s.runes[r.id] = r.icon;
        s.runeNames[r.id] = r.name;
      }
    }
    for (const [id, it] of Object.entries<any>(item.data)) s.items[Number(id)] = it.name;
    return s;
  } catch (e) {
    console.error("Could not load Data Dragon, showing ids instead of names", e);
    return empty;
  }
});

export const img = {
  champ: (s: Static, id: number) => (s.champs[id] ? `${CDN}/cdn/${s.version}/img/champion/${s.champs[id].key}.png` : ""),
  item: (s: Static, id: number) => (id ? `${CDN}/cdn/${s.version}/img/item/${id}.png` : ""),
  spell: (s: Static, id: number) => (s.spells[id] ? `${CDN}/cdn/${s.version}/img/spell/${s.spells[id]}.png` : ""),
  rune: (s: Static, id: number) => (s.runes[id] ? `${CDN}/cdn/img/${s.runes[id]}` : ""),
  icon: (s: Static, id: number) => `${CDN}/cdn/${s.version}/img/profileicon/${id || 29}.png`,
  splash: (s: Static, id: number) => (s.champs[id] ? `${CDN}/cdn/img/champion/centered/${s.champs[id].key}_0.jpg` : ""),
};

export const champName = (s: Static, id: number) => s.champs[id]?.name ?? `Champion ${id}`;

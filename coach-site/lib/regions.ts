// Short region names in URLs (like op.gg) -> Riot platform and routing values.

export interface Region { slug: string; label: string; platform: string; route: string; account: string; tag: string }

const R = (slug: string, label: string, platform: string, route: string, tag: string): Region => ({
  slug, label, platform, route, tag,
  // Riot ID lookups (account-v1) only exist on americas / europe / asia.
  account: route === "sea" ? "asia" : route,
});

export const REGIONS: Region[] = [
  R("na", "North America", "na1", "americas", "NA1"),
  R("euw", "EU West", "euw1", "europe", "EUW"),
  R("eune", "EU Nordic & East", "eun1", "europe", "EUNE"),
  R("kr", "Korea", "kr", "asia", "KR1"),
  R("br", "Brazil", "br1", "americas", "BR1"),
  R("lan", "Latin America North", "la1", "americas", "LAN"),
  R("las", "Latin America South", "la2", "americas", "LAS"),
  R("oce", "Oceania", "oc1", "sea", "OCE"),
  R("jp", "Japan", "jp1", "asia", "JP1"),
  R("tr", "Turkey", "tr1", "europe", "TR1"),
  R("me", "Middle East", "me1", "europe", "ME1"),
  R("sg", "Singapore", "sg2", "sea", "SG2"),
  R("tw", "Taiwan", "tw2", "sea", "TW2"),
  R("vn", "Vietnam", "vn2", "sea", "VN2"),
];

export const regionBySlug = (slug: string) => REGIONS.find((r) => r.slug === slug.toLowerCase());

/** "Name#TAG" or "Name-TAG" -> { name, tag }. Tag defaults to the region's usual tag. */
export function parseRiotId(raw: string, region: Region): { name: string; tag: string } | null {
  const s = raw.trim();
  if (!s) return null;
  const i = s.includes("#") ? s.lastIndexOf("#") : s.lastIndexOf("-");
  if (i <= 0) return { name: s, tag: region.tag };
  const name = s.slice(0, i).trim();
  const tag = s.slice(i + 1).trim();
  return name ? { name, tag: tag || region.tag } : null;
}

export const profilePath = (region: Region, name: string, tag: string) =>
  `/${region.slug}/${encodeURIComponent(`${name}-${tag}`)}`;

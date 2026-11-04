// Links to outside stat sites for a player's ranked and solo queue history.
// Custom games never show up there, which is why this site exists.

const OPGG_REGION: Record<string, string> = {
  NA1: "na", EUW1: "euw", EUN1: "eune", KR: "kr", BR1: "br", LA1: "lan", LA2: "las",
  OC1: "oce", JP1: "jp", TR1: "tr", RU: "ru", PH2: "ph", SG2: "sg", TH2: "th",
  TW2: "tw", VN2: "vn", ME1: "me",
};

const riotId = (name: string, tag: string) => `${encodeURIComponent(name)}-${encodeURIComponent(tag)}`;

export function opggUrl(name: string, tag: string, platform = "NA1") {
  const region = OPGG_REGION[platform.toUpperCase()] ?? "na";
  return `https://op.gg/lol/summoners/${region}/${riotId(name, tag)}`;
}

export function uggUrl(name: string, tag: string, platform = "NA1") {
  return `https://u.gg/lol/profile/${platform.toLowerCase()}/${riotId(name, tag).toLowerCase()}/overview`;
}

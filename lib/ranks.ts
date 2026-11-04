// Solo queue ranks, read by the collector from the League client (no Riot API
// key needed) and cached here per player.

export interface Rank {
  tier: string;           // IRON ... CHALLENGER, or "" when unranked
  division: string;       // I-IV ("" for Master and up)
  lp: number;
  wins?: number;
  losses?: number;
  source: "solo" | "flex" | "last season" | "";
  updatedAt: number;
}

export const TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"];
const DIVS = ["IV", "III", "II", "I"];

/** One number per rank: 100 per division, 400 per tier, plus LP. Master+ continues on LP. */
export function rankScore(r: Rank | undefined | null): number | null {
  if (!r || !r.tier) return null;
  const t = TIERS.indexOf(r.tier.toUpperCase());
  if (t < 0) return null;
  if (t >= 7) return 7 * 400 + Math.max(0, r.lp);
  const d = Math.max(0, DIVS.indexOf(r.division));
  return t * 400 + d * 100 + Math.min(100, Math.max(0, r.lp));
}

const SHORT: Record<string, string> = {
  IRON: "I", BRONZE: "B", SILVER: "S", GOLD: "G", PLATINUM: "P", EMERALD: "E", DIAMOND: "D",
  MASTER: "M", GRANDMASTER: "GM", CHALLENGER: "C",
};
const DIV_NUM: Record<string, string> = { I: "1", II: "2", III: "3", IV: "4" };

/** "Diamond 2" */
export function rankLabel(r: Rank | undefined | null): string {
  if (!r || !r.tier) return "Unranked";
  const tier = r.tier.charAt(0) + r.tier.slice(1).toLowerCase();
  return TIERS.indexOf(r.tier) >= 7 ? `${tier} ${r.lp} LP` : `${tier} ${DIV_NUM[r.division] ?? ""}`.trim();
}

/** "D2 45LP" for tight spaces like Discord lists */
export function rankShort(r: Rank | undefined | null): string {
  if (!r || !r.tier) return "unranked";
  const s = SHORT[r.tier] ?? r.tier;
  return TIERS.indexOf(r.tier) >= 7 ? `${s} ${r.lp}LP` : `${s}${DIV_NUM[r.division] ?? ""} ${r.lp}LP`;
}

/** Reads what the collector sends, keeping only sane values. */
export function cleanRank(x: any): Rank | null {
  if (!x || typeof x !== "object") return null;
  const tier = String(x.tier ?? "").toUpperCase();
  if (tier && !TIERS.includes(tier)) return null;
  const division = String(x.division ?? "").toUpperCase();
  const source = ["solo", "flex", "last season"].includes(x.source) ? x.source : tier ? "solo" : "";
  return {
    tier,
    division: DIVS.includes(division) ? division : "",
    lp: Math.max(0, Math.min(5000, Number(x.lp) || 0)),
    wins: Number.isFinite(x.wins) ? Number(x.wins) : undefined,
    losses: Number.isFinite(x.losses) ? Number(x.losses) : undefined,
    source,
    updatedAt: Date.now(),
  };
}

/** The rank an average score corresponds to, e.g. 2650 -> "Diamond 3". */
export function scoreLabel(score: number): string {
  if (score >= 7 * 400) return `Master+ ${Math.round(score - 2800)} LP`;
  const t = Math.max(0, Math.min(6, Math.floor(score / 400)));
  const d = Math.max(0, Math.min(3, Math.floor((score - t * 400) / 100)));
  const tier = TIERS[t].charAt(0) + TIERS[t].slice(1).toLowerCase();
  return `${tier} ${["4", "3", "2", "1"][d]}`;
}

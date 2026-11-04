// Splits a list of players into two teams.
//   balanced: as close as possible in average custy rating, picking at random
//             among the fairest few splits so a reroll gives something new
//   random:   any split that meets the rules
// Rules: groups that must be on the same team, and groups that must be split up.

export interface TeamPlayer {
  name: string;           // as shown, e.g. "Buckley"
  rating: number;         // custy rating; 1500 if they have no games yet
  known: boolean;         // false when nobody by that name is on the site
  puuid?: string;
}

export interface TeamOptions {
  mode: "balanced" | "random";
  together: string[][];   // each inner list: names that must share a team
  apart: string[][];      // each inner list: names that must not share a team
}

export interface TeamResult {
  blue: TeamPlayer[];
  red: TeamPlayer[];
  blueAvg: number;
  redAvg: number;
  options: number;        // how many splits met the rules
}

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, "");
const avg = (team: TeamPlayer[]) => (team.length ? team.reduce((a, p) => a + p.rating, 0) / team.length : 0);

function* splits(n: number): Generator<number> {
  // Bitmasks of who's on blue. Blue gets floor(n/2); the first player is pinned
  // to blue when teams are even, so each split appears once.
  const size = Math.floor(n / 2);
  const total = 1 << n;
  for (let mask = 0; mask < total; mask++) {
    if (popcount(mask) !== size) continue;
    if (n % 2 === 0 && !(mask & 1)) continue;
    yield mask;
  }
}

function popcount(x: number) {
  let c = 0;
  while (x) {
    x &= x - 1;
    c++;
  }
  return c;
}

export function makeTeams(players: TeamPlayer[], opts: TeamOptions, rand: () => number = Math.random): TeamResult | { error: string } {
  const n = players.length;
  if (n < 2) return { error: "Give me at least 2 players." };
  if (n > 16) return { error: "That's more than 16 players. Split them into separate lobbies first." };

  const index = new Map(players.map((p, i) => [norm(p.name), i]));
  const resolve = (groups: string[][], label: string): number[][] | string => {
    const out: number[][] = [];
    for (const g of groups) {
      const ids: number[] = [];
      for (const name of g) {
        const i = index.get(norm(name));
        if (i === undefined) return `${label}: "${name}" isn't in the player list.`;
        ids.push(i);
      }
      if (ids.length > 1) out.push(ids);
    }
    return out;
  };
  const together = resolve(opts.together, "Together");
  if (typeof together === "string") return { error: together };
  const apart = resolve(opts.apart, "Apart");
  if (typeof apart === "string") return { error: apart };

  const ok = (mask: number) => {
    const side = (i: number) => (mask >> i) & 1;
    for (const g of together) if (!g.every((i) => side(i) === side(g[0]))) return false;
    for (const g of apart) {
      // Spread as evenly as possible: a pair must split; bigger groups can't all share a side.
      const blue = g.filter((i) => side(i)).length;
      if (Math.abs(blue - (g.length - blue)) > 1) return false;
    }
    return true;
  };

  const scored: { mask: number; gap: number }[] = [];
  for (const mask of splits(n)) {
    if (!ok(mask)) continue;
    let b = 0, r = 0, nb = 0, nr = 0;
    for (let i = 0; i < n; i++) {
      if ((mask >> i) & 1) { b += players[i].rating; nb++; } else { r += players[i].rating; nr++; }
    }
    scored.push({ mask, gap: Math.abs(b / nb - r / nr) });
  }
  if (!scored.length) return { error: "No split fits those rules. Try loosening the together/apart groups." };

  let pool = scored;
  if (opts.mode === "balanced") {
    scored.sort((a, b) => a.gap - b.gap);
    const best = scored[0].gap;
    // The fairest splits: within 15 rating points of the best. If that leaves too few
    // to vary rerolls, allow up to 40 points, but never a lopsided split.
    pool = scored.filter((s) => s.gap <= best + 15);
    if (pool.length < 4) pool = scored.filter((s) => s.gap <= best + 40);
  }
  const pick = pool[Math.floor(rand() * pool.length)];

  let blue = players.filter((_, i) => (pick.mask >> i) & 1);
  let red = players.filter((_, i) => !((pick.mask >> i) & 1));
  if (rand() < 0.5) [blue, red] = [red, blue]; // don't always put the first player on blue
  const byRating = (a: TeamPlayer, b: TeamPlayer) => b.rating - a.rating;
  blue.sort(byRating);
  red.sort(byRating);
  return { blue, red, blueAvg: avg(blue), redAvg: avg(red), options: scored.length };
}

/** "a, b; c d" -> [["a","b"],["c d"]]: groups separated by ; and names by , */
export function parseGroups(text: string | undefined): string[][] {
  if (!text) return [];
  return text
    .split(/[;|]/)
    .map((g) => g.split(",").map((s) => s.trim()).filter(Boolean))
    .filter((g) => g.length);
}

/** Player names from a comma or newline separated list. */
export function parseNames(text: string | undefined): string[] {
  if (!text) return [];
  return text.split(/[,\n]/).map((s) => s.trim().replace(/^@/, "")).filter(Boolean);
}

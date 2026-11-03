export type Role = "TOP" | "JUNGLE" | "MID" | "BOT" | "SUPPORT" | "";

export interface MatchPlayer {
  puuid: string;          // stable player id; bots get "bot:<champion>:<team>"
  name: string;           // Riot ID game name
  tag: string;            // Riot ID tag line
  isBot: boolean;
  profileIcon: number;
  teamId: 100 | 200;
  win: boolean;
  championId: number;
  champLevel: number;
  role: Role;             // best guess; custom games don't record roles reliably
  spells: [number, number];
  items: number[];        // item0..item6 (6 = trinket); 0 = empty slot
  keystone: number;
  primaryStyle: number;
  subStyle: number;
  kills: number;
  deaths: number;
  assists: number;
  cs: number;
  gold: number;
  damageToChampions: number;
  damageTaken: number;
  damageMitigated: number;
  damageToObjectives: number;
  damageToTurrets: number;
  healing: number;
  visionScore: number;
  wardsPlaced: number;
  wardsKilled: number;
  controlWards: number;
  ccTime: number;
  turretKills: number;
  doubleKills: number;
  tripleKills: number;
  quadraKills: number;
  pentaKills: number;
  largestMultiKill: number;
  largestKillingSpree: number;
  firstBlood: boolean;
}

export interface MatchTeam {
  teamId: 100 | 200;
  win: boolean;
  kills: number;
  gold: number;
  bans: number[];
  towers: number;
  inhibitors: number;
  dragons: number;
  barons: number;
  heralds: number;
  firstBlood: boolean;
  firstTower: boolean;
}

export interface Match {
  v: number;              // normalizer version
  id: string;             // "<platformId>-<gameId>"
  gameId: number;
  platformId: string;
  playedAt: number;       // ms since epoch
  duration: number;       // seconds
  mode: string;           // CLASSIC, ARAM, ...
  mapId: number;
  version: string;        // game version, e.g. 16.21.712.1234
  remake: boolean;        // under 5 minutes: shown but left out of stats
  teams: MatchTeam[];
  players: MatchPlayer[];
}

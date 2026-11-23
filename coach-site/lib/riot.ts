// Riot web API calls. The key stays on the server. Responses are cached by Next.js so page views
// don't each cost API calls (the personal key allows 100 requests per 2 minutes).

import "server-only";
import type { Region } from "./regions";

export class RiotError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function riot<T>(host: string, path: string, revalidate: number): Promise<T> {
  const key = process.env.RIOT_API_KEY;
  if (!key) throw new RiotError(503, "The site's Riot API key isn't set up yet.");
  const res = await fetch(`https://${host}.api.riotgames.com${path}`, {
    headers: { "X-Riot-Token": key },
    next: { revalidate },
  });
  if (res.status === 404) throw new RiotError(404, "Not found");
  if (res.status === 429) throw new RiotError(429, "Too many lookups right now. Try again in a minute.");
  if (res.status === 401 || res.status === 403) throw new RiotError(res.status, "The site's Riot API key was rejected.");
  if (!res.ok) throw new RiotError(res.status, `Riot's servers answered ${res.status}.`);
  return res.json() as Promise<T>;
}

export interface Account { puuid: string; gameName: string; tagLine: string }
export interface Summoner { profileIconId: number; summonerLevel: number }
export interface LeagueEntry {
  queueType: string; tier: string; rank: string; leaguePoints: number; wins: number; losses: number;
}
export interface Participant {
  puuid: string; riotIdGameName?: string; riotIdTagline?: string; championId: number; champLevel: number;
  teamId: number; win: boolean; kills: number; deaths: number; assists: number;
  totalMinionsKilled: number; neutralMinionsKilled: number; goldEarned: number; visionScore: number;
  totalDamageDealtToChampions: number; teamPosition: string;
  item0: number; item1: number; item2: number; item3: number; item4: number; item5: number; item6: number;
  summoner1Id: number; summoner2Id: number;
  perks?: { styles: { style: number; selections: { perk: number }[] }[] };
  gameEndedInEarlySurrender?: boolean;
}
export interface Match {
  metadata: { matchId: string };
  info: { gameCreation: number; gameEndTimestamp?: number; gameDuration: number; queueId: number; participants: Participant[] };
}

const MIN = 60, HOUR = 3600, DAY = 86400;

export const getAccount = (r: Region, name: string, tag: string) =>
  riot<Account>(r.account, `/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`, HOUR);

export const getSummoner = (r: Region, puuid: string) =>
  riot<Summoner>(r.platform, `/lol/summoner/v4/summoners/by-puuid/${puuid}`, 10 * MIN);

export const getRanks = (r: Region, puuid: string) =>
  riot<LeagueEntry[]>(r.platform, `/lol/league/v4/entries/by-puuid/${puuid}`, 5 * MIN);

export const getMatchIds = (r: Region, puuid: string, count = 10) =>
  riot<string[]>(r.route, `/lol/match/v5/matches/by-puuid/${puuid}/ids?start=0&count=${count}`, 2 * MIN);

// A finished match never changes, so cache it for a long time.
export const getMatch = (r: Region, id: string) =>
  riot<Match>(r.route, `/lol/match/v5/matches/${id}`, 7 * DAY);

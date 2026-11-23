import type { Metadata } from "next";
import { notFound } from "next/navigation";
import SearchBox from "@/components/SearchBox";
import {
  champIcon, champName, getStatic, itemIcon, profileIcon, runeIcon, spellIcon, type Static,
} from "@/lib/ddragon";
import { parseRiotId, regionBySlug } from "@/lib/regions";
import {
  getAccount, getMatch, getMatchIds, getRanks, getSummoner, RiotError, type LeagueEntry, type Match, type Participant,
} from "@/lib/riot";

type Params = { region: string; riotId: string };

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { region, riotId } = await params;
  const r = regionBySlug(region);
  const id = r && parseRiotId(decodeURIComponent(riotId), r);
  return { title: id ? `${id.name}#${id.tag} (${r!.slug.toUpperCase()})` : "Player" };
}

const QUEUES: Record<number, string> = {
  420: "Ranked Solo", 440: "Ranked Flex", 400: "Normal Draft", 430: "Normal Blind", 480: "Swiftplay", 490: "Quickplay",
  450: "ARAM", 1700: "Arena", 1710: "Arena", 900: "URF", 1900: "URF", 0: "Custom", 3100: "Custom",
};
const TIER_COLOR: Record<string, string> = {
  IRON: "#8a7f7a", BRONZE: "#b0794f", SILVER: "#9fb1bd", GOLD: "#e5b85c", PLATINUM: "#4fc1b0", EMERALD: "#2fbf71",
  DIAMOND: "#7aa2ff", MASTER: "#c06bff", GRANDMASTER: "#ff5a5a", CHALLENGER: "#f4d35e",
};
const APEX = new Set(["MASTER", "GRANDMASTER", "CHALLENGER"]);

const cap = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

function ago(ms: number) {
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}
const dur = (s: number) => `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
const kdaRatio = (k: number, d: number, a: number) => (d === 0 ? "Perfect" : `${((k + a) / d).toFixed(2)}:1`);

function RankCard({ title, entry }: { title: string; entry?: LeagueEntry }) {
  if (!entry) {
    return (
      <section className="panel">
        <h2>{title}</h2>
        <div className="muted">Unranked</div>
      </section>
    );
  }
  const games = entry.wins + entry.losses;
  const color = TIER_COLOR[entry.tier] ?? "var(--muted)";
  return (
    <section className="panel">
      <h2>{title}</h2>
      <div className="rank">
        <div className="rank-badge" style={{ color }}>{entry.tier.slice(0, 2)}</div>
        <div>
          <b style={{ color }}>{cap(entry.tier)}{APEX.has(entry.tier) ? "" : ` ${entry.rank}`}</b>
          <span>{entry.leaguePoints} LP</span>
          <div className="muted" style={{ fontSize: 13 }}>
            {entry.wins}W {entry.losses}L · {games ? Math.round((entry.wins / games) * 100) : 0}% win rate
          </div>
        </div>
      </div>
    </section>
  );
}

function MatchRow({ m, me, s, region }: { m: Match; me: Participant; s: Static; region: string }) {
  const remake = m.info.gameDuration < 300 || me.gameEndedInEarlySurrender;
  const cls = remake ? "remake" : me.win ? "win" : "loss";
  const cs = me.totalMinionsKilled + me.neutralMinionsKilled;
  const mins = m.info.gameDuration / 60;
  const items = [me.item0, me.item1, me.item2, me.item3, me.item4, me.item5, me.item6];
  const keystone = me.perks?.styles?.[0]?.selections?.[0]?.perk ?? 0;
  const secondary = me.perks?.styles?.[1]?.style ?? 0;
  const ended = m.info.gameEndTimestamp ?? m.info.gameCreation + m.info.gameDuration * 1000;
  return (
    <div className={`match ${cls}`}>
      <div className="meta">
        <b>{QUEUES[m.info.queueId] ?? "Game"}</b>
        {ago(ended)}
        <div style={{ marginTop: 6 }}>{remake ? "Remake" : me.win ? "Victory" : "Defeat"}</div>
        {dur(m.info.gameDuration)}
      </div>
      <div className="champ">
        <div className="portrait">
          {champIcon(s, me.championId) && <img src={champIcon(s, me.championId)} alt={champName(s, me.championId)} title={champName(s, me.championId)} />}
          <span>{me.champLevel}</span>
        </div>
        <div className="stack">
          {spellIcon(s, me.summoner1Id) && <img src={spellIcon(s, me.summoner1Id)} alt="" />}
          {spellIcon(s, me.summoner2Id) && <img src={spellIcon(s, me.summoner2Id)} alt="" />}
        </div>
        <div className="stack">
          {runeIcon(s, keystone) && <img className="rune" src={runeIcon(s, keystone)} alt="" />}
          {runeIcon(s, secondary) && <img className="rune" src={runeIcon(s, secondary)} alt="" style={{ padding: 3 }} />}
        </div>
      </div>
      <div className="middle">
        <div className="kda">
          <b>{me.kills} / <span style={{ color: "var(--loss)" }}>{me.deaths}</span> / {me.assists}</b>{" "}
          <span className="ratio">{kdaRatio(me.kills, me.deaths, me.assists)} KDA</span>
        </div>
        <div className="muted" style={{ fontSize: 13 }}>
          {cs} CS ({(cs / mins).toFixed(1)}) · {me.visionScore} vision · {Math.round(me.totalDamageDealtToChampions / 1000)}k dmg
        </div>
        <div className="items">
          {items.map((id, i) => (id ? <img key={i} src={itemIcon(s, id)} alt="" /> : <div key={i} className="empty" />))}
        </div>
      </div>
      {!remake && (
        <a className="review-btn" href={`/download?game=${encodeURIComponent(m.metadata.matchId)}&region=${region}`}>
          Review this game →
        </a>
      )}
    </div>
  );
}

export default async function Profile({ params }: { params: Promise<Params> }) {
  const { region: slug, riotId } = await params;
  const region = regionBySlug(slug);
  if (!region) notFound();
  const id = parseRiotId(decodeURIComponent(riotId), region);
  if (!id) notFound();

  let account, summoner, ranks: LeagueEntry[], matches: Match[];
  try {
    account = await getAccount(region, id.name, id.tag);
    const [sum, rk, ids] = await Promise.all([
      getSummoner(region, account.puuid),
      getRanks(region, account.puuid),
      getMatchIds(region, account.puuid, 10),
    ]);
    summoner = sum;
    ranks = rk;
    matches = (await Promise.all(ids.map((mid) => getMatch(region, mid).catch(() => null)))).filter((x): x is Match => !!x);
  } catch (e) {
    const err = e instanceof RiotError ? e : new RiotError(500, "Something went wrong.");
    return (
      <div className="error-box">
        <h1>{err.status === 404 ? `No player called ${id.name}#${id.tag} on ${region.label}` : "Couldn't load this player"}</h1>
        <p className="muted">{err.status === 404 ? "Check the name, the #tag and the region." : err.message}</p>
        <SearchBox big region={region.slug} value={`${id.name}#${id.tag}`} />
      </div>
    );
  }

  const s = await getStatic();
  const solo = ranks.find((r) => r.queueType === "RANKED_SOLO_5x5");
  const flex = ranks.find((r) => r.queueType === "RANKED_FLEX_SR");
  const rows = matches
    .map((m) => ({ m, me: m.info.participants.find((p) => p.puuid === account.puuid) }))
    .filter((x): x is { m: Match; me: Participant } => !!x.me);

  const counted = rows.filter(({ m, me }) => m.info.gameDuration >= 300 && !me.gameEndedInEarlySurrender);
  const wins = counted.filter(({ me }) => me.win).length;
  const tot = counted.reduce((a, { me }) => ({ k: a.k + me.kills, d: a.d + me.deaths, a: a.a + me.assists }), { k: 0, d: 0, a: 0 });
  const n = counted.length || 1;
  const champs = new Map<number, { games: number; wins: number }>();
  for (const { me } of counted) {
    const c = champs.get(me.championId) ?? { games: 0, wins: 0 };
    c.games++; if (me.win) c.wins++;
    champs.set(me.championId, c);
  }
  const topChamps = [...champs.entries()].sort((a, b) => b[1].games - a[1].games).slice(0, 5);

  return (
    <>
      <div className="profile-head">
        <div className="icon">
          <img src={profileIcon(s, summoner.profileIconId)} alt="" />
          <span className="level">{summoner.summonerLevel}</span>
        </div>
        <div>
          <h1>{account.gameName} <span>#{account.tagLine}</span></h1>
          <div className="muted">{region.label}</div>
        </div>
      </div>

      <div className="layout">
        <aside>
          <RankCard title="Ranked Solo/Duo" entry={solo} />
          <RankCard title="Ranked Flex" entry={flex} />
          {counted.length > 0 && (
            <section className="panel">
              <h2>Last {counted.length} games</h2>
              <div className="summary-row"><span>Record</span><b>{wins}W {counted.length - wins}L ({Math.round((wins / counted.length) * 100)}%)</b></div>
              <div className="summary-row">
                <span>Average KDA</span>
                <b>{(tot.k / n).toFixed(1)} / {(tot.d / n).toFixed(1)} / {(tot.a / n).toFixed(1)}</b>
              </div>
              <div style={{ marginTop: 10 }}>
                {topChamps.map(([cid, c]) => (
                  <div key={cid} className="summary-row" style={{ alignItems: "center" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {champIcon(s, cid) && <img src={champIcon(s, cid)} alt="" width={24} height={24} style={{ borderRadius: "50%" }} />}
                      {champName(s, cid)}
                    </span>
                    <span className="muted">{c.games} games · {Math.round((c.wins / c.games) * 100)}%</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </aside>

        <section>
          {rows.length === 0 ? (
            <div className="panel muted">No recent games.</div>
          ) : (
            rows.map(({ m, me }) => <MatchRow key={m.metadata.matchId} m={m} me={me} s={s} region={region.slug} />)
          )}
        </section>
      </div>
    </>
  );
}

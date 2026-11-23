"""
Find current-patch ranked games of one lane matchup played by Silver–Platinum players, to compare with expert games
(for testing the coach on the players it's most for).

  python3 low_elo_games.py --a Garen --b Camille --role TOP --patch 16.23 --tiers SILVER,GOLD,PLATINUM --want 6

Finds players of champion A in those tiers (league-v4 entries, then champion mastery to keep people who play A a lot),
reads their recent ranked games, keeps A vs B in that role, and adds the lane state at 14:00 from Riot's timeline
(gold, CS and level gaps for A's player). Writes public/experts/<A>-<B>-<ROLE>-low.json with the games sorted from
A's worst lane to best, each with the player's rank.
"""
import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True)
ap.add_argument("--b", required=True)   # one champion or several, comma-separated
ap.add_argument("--role", default="TOP")
ap.add_argument("--patch", required=True)
ap.add_argument("--tiers", default="SILVER,GOLD,PLATINUM")
ap.add_argument("--want", type=int, default=6)
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--days", type=int, default=10)
ap.add_argument("--mastery", type=int, default=60000)
ap.add_argument("--out", default="public/experts")
a = ap.parse_args()
KEY = os.environ["RIOT_API_KEY"].strip()
T0 = time.time()
calls = 0


def get(host, path):
    global calls
    for _ in range(6):
        calls += 1
        req = urllib.request.Request("https://%s.api.riotgames.com%s" % (host, path), headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(1.25)   # stay under 100 requests per 2 minutes
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code in (500, 502, 503, 504):
                time.sleep(5); continue
            if e.code in (401, 403):
                raise SystemExit("Riot rejected the key (HTTP %s)." % e.code)
            if e.code == 404:
                return None
            raise
        except Exception:
            time.sleep(5)
    return None


dd = json.loads(urllib.request.urlopen("https://ddragon.leagueoflegends.com/cdn/%s.1/data/en_US/champion.json" % a.patch).read())["data"]
cid = {v["id"]: int(v["key"]) for v in dd.values()}
A = cid[a.a]
B = [x.strip() for x in a.b.split(",")]
watch = [cid[a.a]] + [cid[x] for x in B]   # players of A, or of any B, may have played the matchup
since = int(time.time()) - a.days * 86400
found, seen_games, seen_players = [], set(), set()
tiers = a.tiers.split(",")
random.seed(int(time.time()))
while time.time() - T0 < a.minutes * 60 and len(found) < a.want:
    tier, div, page = random.choice(tiers), random.choice(["I", "II", "III", "IV"]), random.randint(1, 30)
    entries = get("na1", "/lol/league/v4/entries/RANKED_SOLO_5x5/%s/%s?page=%d" % (tier, div, page)) or []
    random.shuffle(entries)
    for e in entries[:40]:
        if time.time() - T0 > a.minutes * 60 or len(found) >= a.want:
            break
        pu = e.get("puuid")
        if not pu or pu in seen_players:
            continue
        seen_players.add(pu)
        top = get("na1", "/lol/champion-mastery/v4/champion-masteries/by-puuid/%s/top?count=5" % pu) or []
        if not any(m.get("championId") in watch and m.get("championPoints", 0) >= a.mastery for m in top):
            continue
        ids = get("americas", "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&startTime=%d&count=20" % (pu, since)) or []
        for mid in ids:
            if mid in seen_games:
                continue
            seen_games.add(mid)
            g = get("americas", "/lol/match/v5/matches/%s" % mid)
            info = (g or {}).get("info") or {}
            if not str(info.get("gameVersion", "")).startswith(a.patch + "."):
                if info.get("gameVersion", "") < a.patch:
                    break
                continue
            if info.get("gameDuration", 0) < 900:
                continue
            P = info["participants"]
            pa = next((p for p in P if p["championName"] == a.a and p["teamPosition"] == a.role), None)
            pb = next((p for p in P if pa and p["championName"] in B and p["teamPosition"] == a.role and p["teamId"] != pa["teamId"]), None)
            if not pa or not pb:
                continue
            if pa["puuid"] != pu:   # found through the B player: look up A's player's rank
                ra = get("na1", "/lol/league/v4/entries/by-puuid/%s" % pa["puuid"]) or []
                ra = next((x for x in ra if x.get("queueType") == "RANKED_SOLO_5x5"), None)
                if not ra or ra["tier"] not in tiers:
                    continue
                e = dict(e, tier=ra["tier"], rank=ra["rank"], leaguePoints=ra["leaguePoints"])
            tl = get("americas", "/lol/match/v5/matches/%s/timeline" % mid)
            fr = (tl or {}).get("info", {}).get("frames") or []
            f14 = fr[min(14, len(fr) - 1)]["participantFrames"] if fr else {}
            x, y = f14.get(str(pa["participantId"]), {}), f14.get(str(pb["participantId"]), {})
            row = {"gameId": int(mid.split("_")[1]), "opp": pb["championName"], "platform": "NA1", "gameVersion": info["gameVersion"], "queueId": 420,
                   "gameEnd": info.get("gameEndTimestamp"), "rank": "%s %s" % (e["tier"].title(), e["rank"]), "lp": e.get("leaguePoints"),
                   "win": pa["win"], "kda": "%d/%d/%d" % (pa["kills"], pa["deaths"], pa["assists"]),
                   "oppKda": "%d/%d/%d" % (pb["kills"], pb["deaths"], pb["assists"]),
                   "gold14": (x.get("totalGold") or 0) - (y.get("totalGold") or 0),
                   "cs14": (x.get("minionsKilled") or 0) - (y.get("minionsKilled") or 0),
                   "lv14": (x.get("level") or 0) - (y.get("level") or 0)}
            found.append(row)
            print("found %s vs %s: %s %s %s vs %s, gold@14 %+d, cs@14 %+d (%d calls, %.0f min)" % (mid, pb["championName"], row["rank"], "W" if row["win"] else "L", row["kda"], row["oppKda"], row["gold14"], row["cs14"], calls, (time.time() - T0) / 60), flush=True)
found.sort(key=lambda r: r["gold14"])
os.makedirs(a.out, exist_ok=True)
out = os.path.join(a.out, "%s-%s-%s-low.json" % (a.a, B[0] if len(B) == 1 else "any", a.role))
json.dump({"champions": [a.a] + B, "role": a.role, "patch": a.patch, "tiers": tiers, "built": int(time.time()), "games": found}, open(out, "w"), indent=1)
print("%d games written to %s (%d calls, %d players checked)" % (len(found), out, calls, len(seen_players)))

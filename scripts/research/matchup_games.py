"""Finds recent NA high-elo ranked solo games where two champions met in the same lane, on the current patch, so
custy coach can download their replays (League only downloads replays from the client's own region and patch).

    RIOT_API_KEY=... python3 matchup_games.py --a Garen --b Darius --role TOP --patch 16.22 --minutes 100 --want 25

Starts from the Master+ ladder; whenever a game shows someone on champion A or B in that role, that player's history is
scanned next (mains play the matchup far more often than a random ladder player). Writes
public/experts/<A>-<B>-<ROLE>.json with the games and both laners' Riot IDs and ranks.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True)
ap.add_argument("--b", required=True)
ap.add_argument("--role", default="TOP")
ap.add_argument("--patch", required=True)            # gameVersion prefix, e.g. 16.22
ap.add_argument("--minutes", type=float, default=100)
ap.add_argument("--want", type=int, default=25)
ap.add_argument("--days", type=int, default=16)
ap.add_argument("--out", default="public/experts")
a = ap.parse_args()
KEY = os.environ["RIOT_API_KEY"]
DEADLINE = time.time() + a.minutes * 60
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]

stamps = {}
def get(host, path):
    """Stays under 100 requests / 2 min per host (development key)."""
    for _ in range(8):
        st = [t for t in stamps.get(host, []) if time.time() - t < 121]
        if len(st) >= 98:
            time.sleep(max(0.1, 121 - (time.time() - st[0]))); continue
        if st and time.time() - st[-1] < 0.06:
            time.sleep(0.06)
        stamps[host] = st + [time.time()]
        req = urllib.request.Request("https://%s.api.riotgames.com%s" % (host, path),
                                     headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code in (500, 502, 503, 504):
                time.sleep(5); continue
            if e.code in (401, 403):
                raise SystemExit("Riot rejected the key (HTTP %s). It may have expired." % e.code)
            if e.code == 404:
                return None
            raise
        except Exception:
            time.sleep(5)
    return None


def rank_of(puuid):
    for e in get("na1", "/lol/league/v4/entries/by-puuid/%s" % puuid) or []:
        if e.get("queueType") == "RANKED_SOLO_5x5":
            return {"tier": e["tier"], "division": e.get("rank"), "lp": e.get("leaguePoints")}
    return None


ladder = []
for q in ("challengerleagues", "grandmasterleagues", "masterleagues"):
    L = get("na1", "/lol/league/v4/%s/by-queue/RANKED_SOLO_5x5" % q) or {}
    ladder += sorted(L.get("entries", []), key=lambda e: -e["leaguePoints"])
ladder = [e["puuid"] for e in ladder if e.get("puuid")]
print("Ladder: %d players" % len(ladder), flush=True)

since = int(time.time() - a.days * 86400)
mains, queue, scanned, seen, found = [], list(ladder), set(), set(), {}
fetched = 0
while time.time() < DEADLINE and len(found) < a.want and (mains or queue):
    puuid = (mains or queue).pop(0)
    if puuid in scanned:
        continue
    scanned.add(puuid)
    ids = get("americas", "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&count=30&startTime=%d" % (puuid, since)) or []
    for mid in ids:
        if mid in seen or time.time() > DEADLINE:
            continue
        seen.add(mid)
        m = (get("americas", "/lol/match/v5/matches/%s" % mid) or {}).get("info")
        fetched += 1
        if not m:
            continue
        if not m.get("gameVersion", "").startswith(a.patch + "."):
            break                      # newest first: older patch from here on
        lane = {p["championName"]: p for p in m["participants"] if p.get("teamPosition") == a.role}
        for c in (a.a, a.b):
            p = lane.get(c)
            if p and p["puuid"] not in scanned and p["puuid"] not in mains:
                mains.append(p["puuid"])
        pa, pb = lane.get(a.a), lane.get(a.b)
        if pa and pb and pa["teamId"] != pb["teamId"] and m.get("gameDuration", 0) > 900:
            side = lambda p: {"name": p.get("riotIdGameName"), "tag": p.get("riotIdTagline"), "puuid": p["puuid"],
                              "team": p["teamId"], "win": p["win"], "kda": [p["kills"], p["deaths"], p["assists"]]}
            found[mid] = {"matchId": mid, "gameId": m["gameId"], "gameVersion": m["gameVersion"], "queueId": m["queueId"],
                          "gameType": m.get("gameType") or "MATCHED_GAME", "gameCreation": m["gameCreation"],
                          "gameDuration": m["gameDuration"],
                          "gameEnd": m.get("gameEndTimestamp") or m["gameCreation"] + m["gameDuration"] * 1000,
                          a.a: side(pa), a.b: side(pb)}
            print("Found %s (%d so far, %d games read, %d players scanned)" % (mid, len(found), fetched, len(scanned)), flush=True)

games = sorted(found.values(), key=lambda g: -g["gameCreation"])
for g in games:                       # ranks now (Riot has no rank-at-the-time)
    for c in (a.a, a.b):
        g[c]["rank"] = rank_of(g[c]["puuid"])
        del g[c]["puuid"]
top = lambda r: TIERS.index(r["tier"]) if r else -1
games.sort(key=lambda g: -max(top(g[a.a]["rank"]), top(g[a.b]["rank"])))
os.makedirs(a.out, exist_ok=True)
path = os.path.join(a.out, "%s-%s-%s.json" % (a.a, a.b, a.role))
json.dump({"champions": [a.a, a.b], "role": a.role, "region": "NA", "patch": a.patch,
           "built": time.strftime("%Y-%m-%d"), "games": games}, open(path, "w"), indent=1)
print("Wrote %s: %d games (%d games read, %d players scanned)" % (path, len(games), fetched, len(scanned)))

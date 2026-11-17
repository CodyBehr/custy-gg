"""Which skill does each champion take first in a lane matchup, with which setup, and how do the first minutes go?
No replays needed: Riot's match + timeline give the level 1 skill, runes, starting items and early kills/gold.

    RIOT_API_KEY=... python3 skill_starts.py --a Garen --b Darius --role TOP --days 30 --minutes 90 --regions na1,euw1,kr

Starts from each region's Master+ ladder, then follows players seen on either champion (mains play the matchup most).
Writes research/skill-starts-<A>-<B>-<ROLE>.json.
"""
import argparse, json, os, time, urllib.error, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--role", default="TOP")
ap.add_argument("--days", type=int, default=30); ap.add_argument("--minutes", type=float, default=90)
ap.add_argument("--want", type=int, default=400); ap.add_argument("--regions", default="na1,euw1,kr")
ap.add_argument("--out", default="research")
a = ap.parse_args()
KEY = os.environ["RIOT_API_KEY"]
DEADLINE = time.time() + a.minutes * 60
ROUTE = {"na1": "americas", "euw1": "europe", "kr": "asia", "eun1": "europe", "br1": "americas"}
SLOT = {1: "Q", 2: "W", 3: "E", 4: "R"}
stamps = []


def get(host, path):
    for _ in range(8):
        global stamps
        stamps = [t for t in stamps if time.time() - t < 121]
        if len(stamps) >= 98:
            time.sleep(max(0.1, 121 - (time.time() - stamps[0]))); continue
        stamps.append(time.time())
        req = urllib.request.Request("https://%s.api.riotgames.com%s" % (host, path), headers={"X-Riot-Token": KEY})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code in (500, 502, 503, 504):
                time.sleep(5); continue
            if e.code in (401, 403):
                raise SystemExit("Riot rejected the key (HTTP %s)." % e.code)
            return None
        except Exception:
            time.sleep(5)
    return None


def summarize(m, tl, pa, pb):
    pid = {pa["participantId"]: "a", pb["participantId"]: "b"}
    first, start, kills, frames = {}, {"a": [], "b": []}, [], {}
    for f in tl["info"]["frames"]:
        t = f["timestamp"] / 1000
        if t <= 360:
            frames[round(t / 60)] = {s: {"gold": f["participantFrames"][str(p)]["totalGold"], "xp": f["participantFrames"][str(p)]["xp"],
                                         "hp": f["participantFrames"][str(p)]["championStats"]["health"],
                                         "hpMax": f["participantFrames"][str(p)]["championStats"]["healthMax"]}
                                     for p, s in pid.items()}
        for e in f["events"]:
            s = pid.get(e.get("participantId"))
            te = e["timestamp"] / 1000
            if e["type"] == "SKILL_LEVEL_UP" and s and s not in first:
                first[s] = SLOT.get(e["skillSlot"])
            if e["type"] == "ITEM_PURCHASED" and s and te < 60:
                start[s].append(e["itemId"])
            if e["type"] == "CHAMPION_KILL" and te < 360 and (e["victimId"] in pid):
                kills.append({"t": round(te, 1), "victim": pid[e["victimId"]], "byLaner": e.get("killerId") in pid,
                              "assists": len(e.get("assistingParticipantIds") or [])})
    perks = lambda p: [sel["perk"] for st in p["perks"]["styles"] for sel in st["selections"]]
    sums = lambda p: [p["summoner1Id"], p["summoner2Id"]]
    return {"matchId": m["metadata"]["matchId"], "version": m["info"]["gameVersion"],
            "a": {"first": first.get("a"), "perks": perks(pa), "sums": sums(pa), "start": start["a"], "win": pa["win"]},
            "b": {"first": first.get("b"), "perks": perks(pb), "sums": sums(pb), "start": start["b"], "win": pb["win"]},
            "kills": kills, "frames": frames}


found, seen = {}, set()
since = int(time.time() - a.days * 86400)
regions = a.regions.split(",")
per_region = DEADLINE
for i, plat in enumerate(regions):
    reg_deadline = time.time() + (DEADLINE - time.time()) / (len(regions) - i)
    route = ROUTE[plat]
    ladder = []
    for q in ("challengerleagues", "grandmasterleagues", "masterleagues"):
        L = get(plat, "/lol/league/v4/%s/by-queue/RANKED_SOLO_5x5" % q) or {}
        ladder += [e["puuid"] for e in sorted(L.get("entries", []), key=lambda e: -e["leaguePoints"]) if e.get("puuid")]
    mains, queue, scanned = [], ladder, set()
    print("%s: ladder %d" % (plat, len(ladder)), flush=True)
    while time.time() < reg_deadline and len(found) < a.want and (mains or queue):
        puuid = (mains or queue).pop(0)
        if puuid in scanned:
            continue
        scanned.add(puuid)
        for mid in get(route, "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&count=40&startTime=%d" % (puuid, since)) or []:
            if mid in seen or time.time() > reg_deadline:
                continue
            seen.add(mid)
            m = get(route, "/lol/match/v5/matches/%s" % mid)
            if not m:
                continue
            lane = {p["championName"]: p for p in m["info"]["participants"] if p.get("teamPosition") == a.role}
            for c in (a.a, a.b):
                p = lane.get(c)
                if p and p["puuid"] not in scanned and p["puuid"] not in mains:
                    mains.append(p["puuid"])
            pa, pb = lane.get(a.a), lane.get(a.b)
            if pa and pb and pa["teamId"] != pb["teamId"] and m["info"].get("gameDuration", 0) > 600:
                tl = get(route, "/lol/match/v5/matches/%s/timeline" % mid)
                if tl:
                    found[mid] = summarize(m, tl, pa, pb)
                    print("%s %d found" % (mid, len(found)), flush=True)
os.makedirs(a.out, exist_ok=True)
path = os.path.join(a.out, "skill-starts-%s-%s-%s.json" % (a.a, a.b, a.role))
json.dump({"a": a.a, "b": a.b, "role": a.role, "days": a.days, "games": list(found.values())}, open(path, "w"))
print("Wrote %s: %d games" % (path, len(found)))

import json, os, sys, urllib.request, urllib.parse, urllib.error
K = os.environ["RIOT_API_KEY"]
import time
def get(u):
    while True:
        r = urllib.request.Request("https://americas.api.riotgames.com" + u, headers={"X-Riot-Token": K, "User-Agent": "custy-review-test/0.1"})
        try:
            return json.loads(urllib.request.urlopen(r, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(int(e.headers.get("Retry-After") or 10))
acc = get("/riot/account/v1/accounts/by-riot-id/" + sys.argv[1] + "/" + sys.argv[2] + ""); print(acc["gameName"], acc["tagLine"]); puuid = acc["puuid"]
open("data/benchmark/%s.puuid" % sys.argv[1], "w").write(puuid)
ids = get("/lol/match/v5/matches/by-puuid/%s/ids?count=10" % puuid)
os.makedirs("data/benchmark/mine", exist_ok=True)
for mid in ids:
    m = get("/lol/match/v5/matches/%s" % mid)
    me = next(p for p in m["info"]["participants"] if p["puuid"] == puuid)
    opp = next((p for p in m["info"]["participants"] if p["teamId"] != me["teamId"] and p.get("teamPosition") == me.get("teamPosition")), {})
    print(mid, m["info"]["queueId"], me["championName"], me.get("teamPosition"), "vs", opp.get("championName"), me["kills"], me["deaths"], me["assists"], "W" if me["win"] else "L", m["info"]["gameDuration"] // 60, "min")
    if me["championName"] == sys.argv[3]:
        tl = get("/lol/match/v5/matches/%s/timeline" % mid)
        json.dump({"expert": {"name": "you", "puuid": puuid}, "match": m, "timeline": tl}, open("data/benchmark/mine/%s.json" % mid, "w"))
        break

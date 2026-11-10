"""Pull high-elo games for one champion+position through the Riot API (key in RIOT_API_KEY)."""
import json, os, sys, time, threading, urllib.request, urllib.parse, urllib.error
KEY = os.environ["RIOT_API_KEY"]
ROUTE = {"NA": "americas", "EUW": "europe", "KR": "asia"}
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/benchmark/games"
CHAMP, POS = os.environ.get("CHAMP", "Lucian"), os.environ.get("POS", "BOTTOM")
PER_PLAYER, SCAN = int(os.environ.get("PER", "6")), int(os.environ.get("SCAN", "40"))
os.makedirs(OUT, exist_ok=True)
locks = {r: threading.Lock() for r in ROUTE.values()}
stamps = {r: [] for r in ROUTE.values()}

def get(route, path):
    url = "https://%s.api.riotgames.com%s" % (route, path)
    while True:
        with locks[route]:       # stay under 100 requests / 2 min and 20 / s per routing region
            now = time.time()
            st = [t for t in stamps[route] if now - t < 121]
            if len(st) >= 98:
                time.sleep(121 - (now - st[0]))
            stamps[route] = st + [time.time()]
            time.sleep(0.06)
        req = urllib.request.Request(url, headers={"X-Riot-Token": KEY, "User-Agent": "custy-review-test/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code in (500, 502, 503, 504):
                time.sleep(3); continue
            if e.code == 404:
                return None
            raise

def player(name, region):
    route = ROUTE[region]
    g, t = name.split("#")
    acc = get(route, "/riot/account/v1/accounts/by-riot-id/%s/%s" % (urllib.parse.quote(g.strip()), urllib.parse.quote(t.strip())))
    if not acc:
        print("  not found:", name, flush=True); return 0
    ids = get(route, "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&count=%d" % (acc["puuid"], SCAN)) or []
    kept = 0
    for mid in ids:
        if kept >= PER_PLAYER:
            break
        path = os.path.join(OUT, "%s.json" % mid)
        if os.path.exists(path):
            kept += 1; continue
        m = get(route, "/lol/match/v5/matches/%s" % mid)
        if not m:
            continue
        me = next((p for p in m["info"]["participants"] if p["puuid"] == acc["puuid"]), None)
        if not me or me["championName"] != CHAMP or me.get("teamPosition") != POS or m["info"]["gameDuration"] < 900:
            continue
        tl = get(route, "/lol/match/v5/matches/%s/timeline" % mid)
        if not tl:
            continue
        json.dump({"expert": {"name": name, "region": region, "puuid": acc["puuid"]}, "match": m, "timeline": tl}, open(path, "w"))
        kept += 1
    print("  %-28s %s  %d games" % (name, region, kept), flush=True)
    return kept

players = [l.split("|") for l in open(os.environ.get("PLAYERS", "data/benchmark/players.txt")) if "|" in l]
by_region = {}
for name, region in players:
    by_region.setdefault(region.strip(), []).append(name.strip())
def run(region):
    for n in by_region[region]:
        try:
            player(n, region)
        except Exception as e:
            print("  error", n, e, flush=True)
ts = [threading.Thread(target=run, args=(r,)) for r in by_region]
[t.start() for t in ts]; [t.join() for t in ts]
print("total games:", len([f for f in os.listdir(OUT) if f.endswith(".json")]))

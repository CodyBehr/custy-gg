"""Research sampler: ranked solo games from rank groups (NA), one game per randomly drawn player.
Saves match+timeline gz per game into OUT/games. Used by .github/workflows/research-pull.yml.
  RIOT_API_KEY=... python pull_ranks.py --out DIR --groups EMERALD,DIAMOND,MASTER+ --per-group 350 --minutes 300"""
import argparse, gzip, http.client, json, os, random, sys, time, urllib.error, urllib.request
KEY = os.environ["RIOT_API_KEY"]
OUT = None
GROUPS = {"BRONZE": [("BRONZE", d) for d in ("I", "II", "III")], "SILVER": [("SILVER", d) for d in ("I", "II", "III")],
          "GOLD": [("GOLD", d) for d in ("I", "II", "III")], "EMERALD": [("EMERALD", d) for d in ("I", "II", "III")],
          "DIAMOND": [("DIAMOND", d) for d in ("I", "II", "III", "IV")],
          "MASTER+": [("MASTER", None), ("GRANDMASTER", None), ("CHALLENGER", None)]}
stamps = []
def get(host, path):
    while True:
        now = time.time()
        while stamps and now - stamps[0] > 121: stamps.pop(0)
        if len(stamps) >= RATE:            # leave room for the nightly pull and the site on the same key
            time.sleep(121 - (now - stamps[0]) + 0.1); continue
        if stamps and now - stamps[-1] < 0.07: time.sleep(0.07)
        stamps.append(time.time())
        req = urllib.request.Request("https://%s.api.riotgames.com%s" % (host, path), headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code >= 500: time.sleep(5); continue
            if e.code == 404: return None
            raise
        except (ValueError, ConnectionError, TimeoutError, http.client.IncompleteRead, urllib.error.URLError):
            time.sleep(3); continue
ap = argparse.ArgumentParser(); ap.add_argument("--minutes", type=float, default=9)
ap.add_argument("--out", required=True); ap.add_argument("--groups", default="EMERALD,DIAMOND,MASTER+")
ap.add_argument("--per-group", type=int, default=350); ap.add_argument("--rate", type=int, default=55)
ap.add_argument("--skip", default="", help="file of match ids already sampled")
a = ap.parse_args()
OUT, PER_GROUP, RATE = a.out, a.per_group, a.rate
GROUPS = {g: GROUPS[g] for g in a.groups.split(",")}
os.makedirs(OUT + "/games", exist_ok=True)
end = time.time() + a.minutes * 60
st = json.load(open(OUT + "/state.json")) if os.path.exists(OUT + "/state.json") else {"seen": [], "count": {}, "players": {}}
seen = set(st["seen"]) | (set(open(a.skip).read().split()) if a.skip and os.path.exists(a.skip) else set())
def save():
    st["seen"] = sorted(seen); json.dump(st, open(OUT + "/state.json.tmp", "w")); os.replace(OUT + "/state.json.tmp", OUT + "/state.json")
def players(group):
    if st["players"].get(group): return
    ps = []
    for tier, div in GROUPS[group]:
        if div is None:
            r = get("na1", "/lol/league/v4/%sleagues/by-queue/RANKED_SOLO_5x5" % tier.lower()) or {}
            ps += [e.get("puuid") for e in r.get("entries", []) if e.get("puuid")]
        else:
            for page in random.sample(range(1, 30), 2):
                r = get("na1", "/lol/league/v4/entries/RANKED_SOLO_5x5/%s/%s?page=%d" % (tier, div, page)) or []
                ps += [e.get("puuid") for e in r if e.get("puuid")]
    random.shuffle(ps); st["players"][group] = ps; save()
while time.time() < end:
    todo = [g for g in GROUPS if st["count"].get(g, 0) < PER_GROUP]
    if not todo: print("all done"); break
    g = min(todo, key=lambda g: st["count"].get(g, 0))
    players(g)
    if not st["players"][g]: print("no players for", g); st["count"][g] = PER_GROUP; continue
    pu = st["players"][g].pop()
    ids = get("americas", "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&count=5" % pu) or []
    mid = next((m for m in ids if m not in seen), None)
    if not mid: continue
    seen.add(mid)
    m = get("americas", "/lol/match/v5/matches/" + mid)
    if not m or m["info"].get("gameDuration", 0) < 15 * 60 or m["info"].get("queueId") != 420: save(); continue
    tl = get("americas", "/lol/match/v5/matches/%s/timeline" % mid)
    if not tl: save(); continue
    with gzip.open("%s/games/%s.json.gz" % (OUT, mid), "wt") as f:
        json.dump({"group": g, "seed": pu, "match": m, "timeline": tl}, f)
    st["count"][g] = st["count"].get(g, 0) + 1; save()
print({g: st["count"].get(g, 0) for g in GROUPS}, "requests in window", len(stamps))

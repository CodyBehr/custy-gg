"""Pull Master+ ranked games for one region and save every player's numbers, grouped by champion and role.

    RIOT_API_KEY=... python3 master_pull.py --platform na1 --route americas --out rows --minutes 300

Each game gives 10 player samples (every champion and role in it). A champion+role stops collecting once it has
--cap samples, and games whose 10 players are all full are skipped before their timeline is fetched.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_core as C

ap = argparse.ArgumentParser()
ap.add_argument("--platform", required=True)          # na1, euw1, kr
ap.add_argument("--route", required=True)             # americas, europe, asia
ap.add_argument("--out", default="rows")
ap.add_argument("--minutes", type=float, default=300)  # time budget
ap.add_argument("--cap", type=int, default=300)        # samples per champion+role from this region
ap.add_argument("--players", type=int, default=1500)
ap.add_argument("--days", type=int, default=21)
a = ap.parse_args()
KEY = os.environ["RIOT_API_KEY"]
REGION = {"na1": "NA", "euw1": "EUW", "kr": "KR", "eun1": "EUNE", "br1": "BR"}.get(a.platform, a.platform.upper())
DEADLINE = time.time() + a.minutes * 60
os.makedirs(a.out, exist_ok=True)

stamps = {}
def get(host, path):
    """GET with a per-host limiter: under 100 requests / 2 min and 20 / s (development and personal keys)."""
    while True:
        st = [t for t in stamps.get(host, []) if time.time() - t < 121]
        if len(st) >= 99:
            time.sleep(max(0.1, 121 - (time.time() - st[0])))
            continue
        if st and time.time() - st[-1] < 0.06:
            time.sleep(0.06)
        stamps[host] = st + [time.time()]
        req = urllib.request.Request("https://%s.api.riotgames.com%s" % (host, path),
                                     headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg-benchmarks"})
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
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(5)

# Players: Challenger, Grandmaster, Master, highest LP first
players = []
for tier in ("challengerleagues", "grandmasterleagues", "masterleagues"):
    lg = get(a.platform, "/lol/league/v4/%s/by-queue/RANKED_SOLO_5x5" % tier) or {}
    players += [(e.get("leaguePoints", 0), e["puuid"]) for e in lg.get("entries") or [] if e.get("puuid")]
players = [p for _, p in sorted(players, reverse=True)][:a.players]
print("%s: %d Master+ players" % (REGION, len(players)), flush=True)

counts = {}
for f in os.listdir(a.out):
    if f.endswith(".jsonl"):
        counts[f[:-6]] = sum(1 for _ in open(os.path.join(a.out, f)))
seen, games, skipped = set(), 0, 0
since = int(time.time()) - a.days * 86400
full = lambda key: counts.get(key, 0) >= a.cap

for n, puuid in enumerate(players):
    if time.time() > DEADLINE:
        break
    ids = get(a.route, "/lol/match/v5/matches/by-puuid/%s/ids?queue=420&type=ranked&count=20&startTime=%d" % (puuid, since)) or []
    for mid in ids:
        if mid in seen or time.time() > DEADLINE:
            continue
        seen.add(mid)
        m = get(a.route, "/lol/match/v5/matches/%s" % mid)
        if not m or m["info"].get("gameDuration", 0) < 900:
            continue
        info = m["info"]
        keys = {p["participantId"]: "%s-%s" % (p["championName"], C.ROLE.get(p.get("teamPosition"), "")) for p in info["participants"]}
        wanted = [p for p in info["participants"] if C.ROLE.get(p.get("teamPosition")) and not full(keys[p["participantId"]])]
        if not wanted:
            skipped += 1
            continue
        tl = get(a.route, "/lol/match/v5/matches/%s/timeline" % mid)
        if not tl:
            continue
        for p in wanted:
            try:
                r = C.row(info, tl["info"], p)
            except Exception as e:
                print("  row error %s: %s" % (mid, e), flush=True)
                continue
            r["region"], r["match"] = REGION, mid
            k = keys[p["participantId"]]
            with open(os.path.join(a.out, k + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
            counts[k] = counts.get(k, 0) + 1
        games += 1
    if n % 25 == 0:
        filled = sum(1 for v in counts.values() if v >= a.cap)
        print("%s: %d players, %d games used, %d skipped (all full), %d champion+roles, %d full, %.0f min left" % (
            REGION, n + 1, games, skipped, len(counts), filled, (DEADLINE - time.time()) / 60), flush=True)

print("%s done: %d games, %d champion+roles, %d samples" % (REGION, games, len(counts), sum(counts.values())), flush=True)

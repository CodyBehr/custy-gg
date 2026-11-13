"""Fetch match + timeline for given match ids (e.g. games the user has replays of, to check replay decoding
against Riot's own per-minute positions/HP). Used by .github/workflows/match-pull.yml.
  RIOT_API_KEY=... python pull_matches.py --out DIR NA1_123 NA1_456 ..."""
import argparse, gzip, json, os, time, urllib.error, urllib.request
KEY = os.environ["RIOT_API_KEY"]
ROUTE = {"NA1": "americas", "BR1": "americas", "LA1": "americas", "LA2": "americas", "EUW1": "europe", "EUN1": "europe",
         "TR1": "europe", "KR": "asia", "JP1": "asia", "OC1": "sea"}
def get(host, path):
    for _ in range(8):
        req = urllib.request.Request(f"https://{host}.api.riotgames.com{path}", headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(int(e.headers.get("Retry-After") or 5) if e.code == 429 else 3)
    return None
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("ids", nargs="+")
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
for mid in a.ids:
    mid = mid.strip().upper().replace("-", "_")
    host = ROUTE.get(mid.split("_")[0], "americas")
    m, tl = get(host, f"/lol/match/v5/matches/{mid}"), get(host, f"/lol/match/v5/matches/{mid}/timeline")
    if m and tl:
        json.dump({"match": m, "timeline": tl}, gzip.open(f"{a.out}/{mid}.json.gz", "wt"))
    print(mid, "ok" if m and tl else "missing")

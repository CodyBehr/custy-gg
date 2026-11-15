"""Health per minute and death times of both laners in each expert game (public/experts/<set>.json), from Riot's
match timelines, so replay trades can be read the same way as your own games.

    RIOT_API_KEY=... python3 expert_timelines.py Garen-Darius-TOP
Writes public/experts/<set>.timelines.json: {gameId: {champion: {"frames": [[t, hp, max], ...], "deaths": [t, ...]}}}
"""
import json, os, sys, time, urllib.error, urllib.request

KEY = os.environ["RIOT_API_KEY"]
name = sys.argv[1]
src = "public/experts/%s.json" % name
out_path = "public/experts/%s.timelines.json" % name
data = json.load(open(src))
champs = data["champions"]
try:
    out = json.load(open(out_path))
except (OSError, ValueError):
    out = {}


def get(path):
    for _ in range(6):
        req = urllib.request.Request("https://americas.api.riotgames.com" + path,
                                     headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 10)); continue
            if e.code == 404:
                return None
            if e.code in (401, 403):
                raise SystemExit("Riot rejected the key (HTTP %s)" % e.code)
            time.sleep(3)
    return None


for g in data["games"]:
    gid = str(g["gameId"])
    if gid in out:
        continue
    m = get("/lol/match/v5/matches/%s" % g["matchId"])
    tl = get("/lol/match/v5/matches/%s/timeline" % g["matchId"])
    if not m or not tl:
        print("No data for", gid); continue
    pid = {p["championName"]: p["participantId"] for p in m["info"]["participants"] if p.get("teamPosition") == data["role"]}
    rec = {}
    for c in champs:
        k = pid.get(c)
        if not k:
            continue
        frames, deaths = [], []
        for f in tl["info"]["frames"]:
            st = ((f.get("participantFrames") or {}).get(str(k)) or {}).get("championStats") or {}
            if st.get("healthMax"):
                frames.append([round(f["timestamp"] / 1000.0, 1), st.get("health"), st.get("healthMax")])
            deaths += [round(e["timestamp"] / 1000.0, 2) for e in f.get("events") or []
                       if e.get("type") == "CHAMPION_KILL" and e.get("victimId") == k]
        rec[c] = {"frames": frames, "deaths": deaths}
    out[gid] = rec
    print("Timeline", gid)
    time.sleep(1.3)
json.dump(out, open(out_path, "w"), separators=(",", ":"))
print("Wrote", out_path, len(out), "games")

"""Lists a few recent NA Challenger solo queue games on the current patch (to test downloading expert replays
through the League client). Needs RIOT_API_KEY. Prints JSON: [{matchId, gameId, version, player, champion, role}]."""
import json, os, sys, time, urllib.request

KEY = os.environ["RIOT_API_KEY"]


def get(url):
    for _ in range(4):
        req = urllib.request.Request(url, headers={"X-Riot-Token": KEY, "User-Agent": "custy.gg research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 5)); continue
            raise
    raise RuntimeError("rate limited")


patch = sys.argv[1] if len(sys.argv) > 1 else "16.22"
league = get("https://na1.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5")
top = sorted(league["entries"], key=lambda e: -e["leaguePoints"])[:6]
out = []
for e in top:
    ids = get(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{e['puuid']}/ids?queue=420&count=5")
    for mid in ids:
        m = get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{mid}")["info"]
        if not m["gameVersion"].startswith(patch):
            continue
        p = next(p for p in m["participants"] if p["puuid"] == e["puuid"])
        out.append({"matchId": mid, "gameId": m["gameId"], "version": m["gameVersion"], "ended": m.get("gameEndTimestamp"),
                    "player": f"{p.get('riotIdGameName')}#{p.get('riotIdTagline')}", "champion": p["championName"],
                    "role": p.get("teamPosition"), "lp": e["leaguePoints"]})
        break
print(json.dumps(out, indent=1))

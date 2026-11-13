"""Lists a player's recent games (id, champion, role, date, patch). Needs RIOT_API_KEY. Usage: recent_games.py "Name#TAG" [count]"""
import json, os, sys, time, urllib.parse, urllib.request
KEY = os.environ["RIOT_API_KEY"]
def get(url):
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"X-Riot-Token": KEY}), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(int(e.headers.get("Retry-After") or 5)); continue
            raise
name, tag = sys.argv[1].split("#")
acc = get(f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}")
for mid in get(f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{acc['puuid']}/ids?count={sys.argv[2] if len(sys.argv) > 2 else 10}"):
    m = get(f"https://americas.api.riotgames.com/lol/match/v5/matches/{mid}")["info"]
    p = next(p for p in m["participants"] if p["puuid"] == acc["puuid"])
    print(mid, p["championName"], p.get("teamPosition"), m["queueId"], m["gameVersion"][:5], time.strftime("%Y-%m-%d %H:%M", time.gmtime(m["gameCreation"] / 1000)),
          f'{p["kills"]}/{p["deaths"]}/{p["assists"]}', "win" if p["win"] else "loss")

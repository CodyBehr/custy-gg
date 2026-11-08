#!/usr/bin/env python3
"""
A pretend League client, for testing the collector without League installed.

    python scripts/mock_lcu.py <folder>

Serves scripts/sample/games.json over HTTPS the way the real client does and
writes a lockfile into <folder>. Point the collector at it by setting
"league_path": "<folder>" in collector/config.json.
Needs `openssl` on the PATH to make a throwaway certificate.
"""

import base64
import http.server
import json
import os
import secrets
import ssl
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def fake_timeline(g):
    """A made-up timeline shaped like the client's: a frame per minute plus kill and objective events."""
    import random
    rnd = random.Random(g["gameId"])
    parts = g["participants"]
    minutes = max(2, g.get("gameDuration", 1500) // 60)
    final = {p["participantId"]: p["stats"] for p in parts}
    frames = []
    for m in range(minutes + 1):
        f = m / minutes
        pf = {}
        for p in parts:
            st = final[p["participantId"]]
            wobble = 1 + (rnd.random() - 0.5) * 0.2 * (1 - f)
            pf[str(p["participantId"])] = {
                "participantId": p["participantId"],
                "totalGold": int(500 + (st.get("goldEarned", 10000) - 500) * f * wobble),
                "currentGold": 300, "level": max(1, int(1 + 17 * f)), "xp": int(15000 * f),
                "minionsKilled": int(st.get("totalMinionsKilled", 150) * f),
                "jungleMinionsKilled": int(st.get("neutralMinionsKilled", 0) * f),
                "position": {"x": rnd.randint(500, 14000), "y": rnd.randint(500, 14000)},
            }
        frames.append({"timestamp": m * 60000, "participantFrames": pf, "events": []})
    blue = [p["participantId"] for p in parts if p["teamId"] == 100]
    red = [p["participantId"] for p in parts if p["teamId"] == 200]
    for p in parts:
        for _ in range(final[p["participantId"]].get("kills", 0)):
            m = rnd.randint(2, minutes)
            victims = red if p["teamId"] == 100 else blue
            frames[m]["events"].append({"type": "CHAMPION_KILL", "timestamp": m * 60000 - rnd.randint(0, 59000),
                "killerId": p["participantId"], "victimId": rnd.choice(victims), "assistingParticipantIds": [],
                "position": {"x": rnd.randint(500, 14300), "y": rnd.randint(500, 14300)}})
        frames[1]["events"].append({"type": "ITEM_PURCHASED", "timestamp": 15000, "participantId": p["participantId"], "itemId": 1055})
    for m, kind in ((8, "DRAGON"), (14, "RIFTHERALD"), (20, "DRAGON"), (24, "BARON_NASHOR")):
        if m <= minutes:
            frames[m]["events"].append({"type": "ELITE_MONSTER_KILL", "timestamp": m * 60000, "monsterType": kind,
                "monsterSubType": "FIRE_DRAGON" if kind == "DRAGON" else None, "killerId": rnd.choice(blue + red)})
    for m in (11, 16, 22):
        if m <= minutes:
            frames[m]["events"].append({"type": "BUILDING_KILL", "timestamp": m * 60000, "buildingType": "TOWER_BUILDING",
                "laneType": "MID_LANE", "teamId": rnd.choice([100, 200]), "killerId": rnd.choice(blue + red)})
    return {"frameInterval": 60000, "frames": frames}


def main():
    folder = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "mock-league"))
    os.makedirs(folder, exist_ok=True)
    games = json.load(open(os.path.join(HERE, "sample", "games.json")))
    games.sort(key=lambda g: g["gameCreation"], reverse=True)
    password = secrets.token_urlsafe(16)
    auth = "Basic " + base64.b64encode(("riot:" + password).encode()).decode()

    me = games[0]["participantIdentities"][0]["player"]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Authorization") != auth:
                return self.send(401, {"message": "unauthorized"})
            path = self.path.split("?")[0]
            if path == "/lol-summoner/v1/current-summoner":
                return self.send(200, {"puuid": me["puuid"], "gameName": me["gameName"], "tagLine": me["tagLine"]})
            if path == "/lol-gameflow/v1/gameflow-phase":
                return self.send(200, "Lobby" if os.environ.get("MOCK_LOBBY") else "None")
            if path == "/lol-lobby/v2/lobby":
                if not os.environ.get("MOCK_LOBBY"):
                    return self.send(404, {"message": "not in a lobby"})
                ids = games[0]["participantIdentities"]
                entry = lambda x: {"puuid": x["player"]["puuid"], "summonerName": "", "isBot": False}
                return self.send(200, {"gameConfig": {"isCustom": True,
                    "customTeam100": [entry(x) for x in ids[:5]],
                    "customTeam200": [entry(x) for x in ids[5:9]] + [{"botId": "Annie", "isBot": True}],
                    "customSpectators": []}, "members": [entry(x) for x in ids[:9]]})
            if path.startswith("/lol-ranked/v1/ranked-stats/"):
                puuid = path.rsplit("/", 1)[1]
                tiers = ["GOLD", "PLATINUM", "EMERALD", "DIAMOND", "SILVER", ""]
                t = tiers[sum(map(ord, puuid)) % len(tiers)]
                q = {"queueType": "RANKED_SOLO_5x5", "tier": t, "division": "II" if t else "NA", "leaguePoints": 45 if t else 0, "wins": 30, "losses": 25,
                     "previousSeasonEndTier": "GOLD", "previousSeasonEndDivision": "I"}
                return self.send(200, {"queueMap": {"RANKED_SOLO_5x5": q}, "queues": [q]})
            if path.startswith("/lol-summoner/v2/summoners/puuid/"):
                puuid = path.rsplit("/", 1)[1]
                for x in games[0]["participantIdentities"]:
                    if x["player"]["puuid"] == puuid:
                        return self.send(200, {"gameName": x["player"]["gameName"], "tagLine": x["player"]["tagLine"], "puuid": puuid})
                return self.send(404, {})
            if path == "/lol-match-history/v1/products/lol/current-summoner/matches":
                summaries = [{k: g[k] for k in ("gameId", "platformId", "gameCreation", "gameType", "queueId", "gameMode")} for g in games[:50]]
                # Mix in a ranked game so the collector's custom-only filter is exercised.
                summaries.insert(1, {"gameId": 1, "platformId": "NA1", "gameCreation": 0, "gameType": "MATCHED_GAME", "queueId": 420, "gameMode": "CLASSIC"})
                return self.send(200, {"accountId": 0, "games": {"gameCount": len(summaries), "games": summaries}})
            if path.startswith("/lol-match-history/v1/game-timelines/"):
                gid = int(path.rsplit("/", 1)[1])
                for g in games:
                    if g["gameId"] == gid:
                        return self.send(200, fake_timeline(g))
                return self.send(404, {"message": "not found"})
            if path.startswith("/lol-match-history/v1/games/"):
                gid = int(path.rsplit("/", 1)[1])
                for g in games:
                    if g["gameId"] == gid:
                        return self.send(200, g)
                return self.send(404, {"message": "not found"})
            return self.send(404, {"message": "unknown endpoint"})

    cert, key = os.path.join(folder, "mock.crt"), os.path.join(folder, "mock.key")
    if not os.path.exists(cert):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                        "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]
    with open(os.path.join(folder, "lockfile"), "w") as f:
        f.write("LeagueClient:%d:%d:%s:https" % (os.getpid(), port, password))
    print("Mock League client on https://127.0.0.1:%d, lockfile in %s" % (port, folder), flush=True)
    try:
        server.serve_forever()
    finally:
        os.remove(os.path.join(folder, "lockfile"))


if __name__ == "__main__":
    main()

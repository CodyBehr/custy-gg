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
        st = final[p["participantId"]]
        build = [st.get("item%d" % i) for i in range(6) if st.get("item%d" % i)]
        for n, it in enumerate(build[:4]):
            m = min(minutes, rnd.randint(6, 9) + n * rnd.randint(5, 7))
            frames[m]["events"].append({"type": "ITEM_PURCHASED", "timestamp": m * 60000 - rnd.randint(1000, 50000),
                                        "participantId": p["participantId"], "itemId": it})
        six = min(minutes, rnd.randint(6, 9))
        frames[six]["events"].append({"type": "SKILL_LEVEL_UP", "timestamp": six * 60000 - rnd.randint(0, 59000),
                                      "participantId": p["participantId"], "skillSlot": 4, "levelUpType": "NORMAL"})
    for m, kind in ((8, "DRAGON"), (14, "RIFTHERALD"), (20, "DRAGON"), (24, "BARON_NASHOR")):
        if m <= minutes:
            frames[m]["events"].append({"type": "ELITE_MONSTER_KILL", "timestamp": m * 60000, "monsterType": kind,
                "monsterSubType": "FIRE_DRAGON" if kind == "DRAGON" else None, "killerId": rnd.choice(blue + red)})
    for m in (11, 16, 22):
        if m <= minutes:
            frames[m]["events"].append({"type": "BUILDING_KILL", "timestamp": m * 60000, "buildingType": "TOWER_BUILDING",
                "laneType": "MID_LANE", "teamId": rnd.choice([100, 200]), "killerId": rnd.choice(blue + red)})
    return {"frameInterval": 60000, "frames": frames}


RANKED = os.environ.get("MOCK_RANKED")


def as_ranked(g, me_puuid):
    """With MOCK_RANKED=1, games you're in are served as ranked solo queue games."""
    if RANKED and any(i["player"]["puuid"] == me_puuid for i in g["participantIdentities"]):
        return dict(g, gameType="MATCHED_GAME", queueId=420)
    return g


def main():
    folder = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "mock-league"))
    os.makedirs(folder, exist_ok=True)
    games = json.load(open(os.path.join(HERE, "sample", "games.json")))
    games.sort(key=lambda g: g["gameCreation"], reverse=True)
    password = secrets.token_urlsafe(16)
    auth = "Basic " + base64.b64encode(("riot:" + password).encode()).decode()

    me = games[0]["participantIdentities"][0]["player"]
    games = [as_ranked(g, me["puuid"]) for g in games]
    replay = {"watching": None}

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
            if path.startswith("/lol-replays/v1/metadata/"):
                return self.send(200, {"gameId": int(path.rsplit("/", 1)[1]), "state": "watch", "downloadProgress": 0})
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

        def do_POST(self):
            if self.headers.get("Authorization") != auth:
                return self.send(401, {"message": "unauthorized"})
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path.startswith("/lol-replays/v1/rofls/") and self.path.endswith("/watch"):
                replay["watching"], replay["started"] = self.path.split("/")[4], None
                return self.send(204, {})
            if self.path.startswith("/lol-replays/v1/rofls/"):
                return self.send(204, {})
            return self.send(404, {"message": "unknown endpoint"})

    class ReplayApi(http.server.BaseHTTPRequestHandler):
        """Pretend in-game Replay API (port 2999) once a replay is 'watched'."""
        state = {"time": 0.0}

        def log_message(self, *a):
            pass

        def do_GET(self):
            # Real replays: a loading screen first (no game clock), and seeks take a few seconds.
            import time as _t
            st, now = self.state, _t.time()
            if replay["watching"] and replay.get("started") is None:
                replay["started"] = now
            loaded = replay["watching"] and now - replay["started"] > 6
            if self.path.startswith("/liveclientdata/gamestats"):
                return Handler.send(self, 200, {"gameTime": st["time"]} if loaded else {}) if replay["watching"] else Handler.send(self, 404, {})
            if self.path.startswith("/liveclientdata/playerlist"):
                g = next((g for g in games if str(g["gameId"]) == str(replay["watching"])), None)
                ids = [i["player"] for i in g["participantIdentities"]] if g else []
                return Handler.send(self, 200, [{"riotId": "%s#%s" % (p.get("gameName"), p.get("tagLine"))} for p in ids])
            seeking = st.get("seek_until", 0) > now
            if loaded and not seeking:
                if st.get("pending") is not None:
                    st["time"], st["pending"] = st["pending"], None
                st["time"] += 1.0 if not st.get("last") else now - st["last"]
            st["last"] = now
            g = next((g for g in games if str(g["gameId"]) == str(replay["watching"])), None)
            Handler.send(self, 200, {"length": float(g["gameDuration"]) if g else 0, "time": st["time"], "paused": False, "seeking": seeking})

        def do_POST(self):
            import time as _t
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            loaded = replay["watching"] and replay.get("started") and _t.time() - replay["started"] > 6
            if "time" in req and loaded:   # ignored during the loading screen, like the real thing
                self.state["pending"], self.state["seek_until"] = float(req["time"]), _t.time() + 3
                print("Replay API: seek to %.0fs" % float(req["time"]), flush=True)
            Handler.send(self, 200, {"length": 1800.0, "time": self.state["time"], "paused": False})

    cert, key = os.path.join(folder, "mock.crt"), os.path.join(folder, "mock.key")
    if not os.path.exists(cert):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                        "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]
    if os.environ.get("MOCK_REPLAY_API"):
        import threading
        rserver = http.server.ThreadingHTTPServer(("127.0.0.1", 2999), ReplayApi)
        rctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        rctx.load_cert_chain(cert, key)
        rserver.socket = rctx.wrap_socket(rserver.socket, server_side=True)
        threading.Thread(target=rserver.serve_forever, daemon=True).start()
    with open(os.path.join(folder, "lockfile"), "w") as f:
        f.write("LeagueClient:%d:%d:%s:https" % (os.getpid(), port, password))
    print("Mock League client on https://127.0.0.1:%d, lockfile in %s" % (port, folder), flush=True)
    try:
        server.serve_forever()
    finally:
        os.remove(os.path.join(folder, "lockfile"))


if __name__ == "__main__":
    main()

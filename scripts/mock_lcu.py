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

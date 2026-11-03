#!/usr/bin/env python3
"""
custy.gg collector

Watches the League of Legends client on this computer and uploads every
custom game you play to your custy.gg site. Uses only the Python standard
library, so there is nothing to pip install.

Usage:
    python custy_collector.py            run forever (checks every minute)
    python custy_collector.py --once     upload any new custom games, then exit
    python custy_collector.py --test     check config, League client and site
    python custy_collector.py --all      re-send every custom game in history

Settings live in config.json next to this file.
"""

import base64
import json
import logging
import os
import platform
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "uploaded.json")
LOG_PATH = os.path.join(HERE, "collector.log")

POLL_SECONDS = 60          # how often to look for new games while idle
AFTER_GAME_DELAY = 20      # wait this long after a game ends before checking
HISTORY_PAGE = 50          # how many recent games to look through each check

DEFAULT_LEAGUE_DIRS = [
    r"C:\Riot Games\League of Legends",
    r"D:\Riot Games\League of Legends",
    r"C:\Program Files\Riot Games\League of Legends",
    r"C:\Program Files (x86)\Riot Games\League of Legends",
    "/Applications/League of Legends.app/Contents/LoL",
]

log = logging.getLogger("custy")


# --------------------------------------------------------------------------
# Config and local state
# --------------------------------------------------------------------------

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit(
            "config.json is missing. Copy config.example.json to config.json "
            "and fill in site_url and ingest_key."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    site = (cfg.get("site_url") or "").strip().rstrip("/")
    key = (cfg.get("ingest_key") or "").strip()
    if not site or "your-site" in site:
        raise SystemExit("Set site_url in config.json to your custy.gg site address.")
    if not key or key == "paste-the-INGEST_KEY-here":
        raise SystemExit("Set ingest_key in config.json (same value as INGEST_KEY on the site).")
    cfg["site_url"] = site
    cfg["ingest_key"] = key
    cfg.setdefault("league_path", "")
    cfg.setdefault("min_players", 2)
    return cfg


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_state(seen):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)
    os.replace(tmp, STATE_PATH)


# --------------------------------------------------------------------------
# Finding the League client
# --------------------------------------------------------------------------

def _client_command_line():
    """Return the command line of the running LeagueClientUx process, or ''."""
    system = platform.system()
    try:
        if system == "Windows":
            cmd = [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ]
            flags = 0x08000000  # CREATE_NO_WINDOW, so no console flashes when running hidden
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                 creationflags=flags)
            return out.stdout or ""
        out = subprocess.run(["ps", "-A", "-o", "command"], capture_output=True,
                             text=True, timeout=10)
        for line in out.stdout.splitlines():
            if "LeagueClientUx" in line and "--app-port" in line:
                return line
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _read_lockfile(folder):
    try:
        with open(os.path.join(folder, "lockfile"), "r", encoding="utf-8") as f:
            parts = f.read().strip().split(":")
        if len(parts) >= 5:
            return int(parts[2]), parts[3]
    except (OSError, ValueError):
        pass
    return None


def find_client(cfg):
    """Return (port, password) for the running League client, or None."""
    # The client writes a lockfile while it's open and deletes it on exit.
    # Checking the usual install folders first is cheap.
    dirs = ([cfg["league_path"]] if cfg.get("league_path") else []) + DEFAULT_LEAGUE_DIRS
    for d in dirs:
        creds = _read_lockfile(d)
        if creds:
            return creds

    # League installed somewhere else: ask the operating system.
    cmdline = _client_command_line()
    port = re.search(r"--app-port=(\d+)", cmdline)
    token = re.search(r"--remoting-auth-token=([\w-]+)", cmdline)
    if port and token:
        return int(port.group(1)), token.group(1)
    install = re.search(r'--install-directory=([^"]+?)(?:"|\s--|$)', cmdline)
    if install:
        return _read_lockfile(install.group(1).strip())
    return None


class LeagueClient:
    """Tiny wrapper around the client's local API on 127.0.0.1."""

    def __init__(self, port, password):
        self.base = "https://127.0.0.1:%d" % port
        auth = base64.b64encode(("riot:%s" % password).encode()).decode()
        self.headers = {"Authorization": "Basic " + auth, "Accept": "application/json"}
        # The client uses a self-signed certificate. This context is only ever
        # used for requests to 127.0.0.1, never for the internet.
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers=self.headers)
        with urllib.request.urlopen(req, context=self.ctx, timeout=20) as resp:
            body = resp.read()
        return json.loads(body) if body else None


# --------------------------------------------------------------------------
# Talking to the custy.gg site
# --------------------------------------------------------------------------

def post_json(url, key, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
            "User-Agent": "custy-collector/" + VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        return e.code, body


def check_site(cfg):
    req = urllib.request.Request(
        cfg["site_url"] + "/api/ingest",
        headers={"Authorization": "Bearer " + cfg["ingest_key"],
                 "User-Agent": "custy-collector/" + VERSION},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}


# --------------------------------------------------------------------------
# Finding and uploading custom games
# --------------------------------------------------------------------------

def game_key(game):
    return "%s-%s" % (game.get("platformId") or "NA", game.get("gameId"))


def is_custom(game):
    return game.get("gameType") == "CUSTOM_GAME"


def human_count(game):
    count = 0
    for ident in game.get("participantIdentities") or []:
        player = ident.get("player") or {}
        puuid = player.get("puuid") or ""
        if puuid and set(puuid.replace("-", "")) != {"0"}:
            count += 1
    return count


def recent_games(lcu):
    data = lcu.get(
        "/lol-match-history/v1/products/lol/current-summoner/matches"
        "?begIndex=0&endIndex=%d" % HISTORY_PAGE
    )
    games = (data or {}).get("games") or {}
    if isinstance(games, dict):
        games = games.get("games") or []
    return games


def sync(cfg, lcu, seen, me, force=False):
    """Upload any custom games not uploaded before. Returns number uploaded."""
    uploaded = 0
    for summary in recent_games(lcu):
        if not is_custom(summary):
            continue
        key = game_key(summary)
        if key in seen and not force:
            continue
        try:
            game = lcu.get("/lol-match-history/v1/games/%s" % summary["gameId"])
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.warning("Could not read game %s from the client: %s", key, e)
            continue
        if not game or not game.get("participants"):
            continue
        if human_count(game) < int(cfg.get("min_players", 2)):
            log.info("Skipping %s: fewer than %s players", key, cfg.get("min_players", 2))
            seen.add(key)
            continue

        status, body = post_json(
            cfg["site_url"] + "/api/ingest", cfg["ingest_key"],
            {"game": game, "uploader": me, "collectorVersion": VERSION},
        )
        if status in (200, 201):
            seen.add(key)
            uploaded += 1
            if body.get("status") == "exists":
                log.info("Custom game %s is already on the site", key)
            else:
                log.info("Uploaded custom game %s", key)
        elif status == 401:
            raise SystemExit("The site rejected the ingest_key in config.json. Check it matches INGEST_KEY.")
        else:
            log.warning("Upload of %s failed (HTTP %s): %s", key, status, body.get("error", ""))
    if uploaded:
        save_state(seen)
    return uploaded


def current_player(lcu):
    try:
        me = lcu.get("/lol-summoner/v1/current-summoner") or {}
        return {"puuid": me.get("puuid"), "gameName": me.get("gameName"),
                "tagLine": me.get("tagLine")}
    except (urllib.error.URLError, OSError, ValueError):
        return {}


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def run_test(cfg):
    ok = True
    print("custy.gg collector %s\n" % VERSION)
    status, body = check_site(cfg)
    if status == 200:
        print("[ok]   Site reachable: %s (%s games stored)" % (cfg["site_url"], body.get("matches", "?")))
    elif status == 401:
        print("[fail] Site is up, but ingest_key does not match INGEST_KEY")
        ok = False
    else:
        print("[fail] Could not reach %s/api/ingest (%s)" % (cfg["site_url"], body.get("error") or "HTTP %s" % status))
        ok = False

    creds = find_client(cfg)
    if not creds:
        print("[fail] League client not found. Open League and log in, then run --test again.")
        return False
    lcu = LeagueClient(*creds)
    try:
        me = current_player(lcu)
        games = recent_games(lcu)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print("[fail] Found the League client but could not read it: %s" % e)
        return False
    name = "%s#%s" % (me.get("gameName"), me.get("tagLine"))
    customs = [g for g in games if is_custom(g)]
    print("[ok]   League client found, logged in as %s" % name)
    print("[ok]   %d recent games in history, %d of them custom games" % (len(games), len(customs)))
    return ok


def main():
    args = set(sys.argv[1:])
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:  # None when launched hidden with pythonw/pyw
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    cfg = load_config()
    if "--test" in args:
        sys.exit(0 if run_test(cfg) else 1)

    seen = set() if "--all" in args else load_state()
    force = "--all" in args
    log.info("custy.gg collector %s started, uploading to %s", VERSION, cfg["site_url"])

    last_phase = None
    waiting_logged = False
    while True:
        try:
            creds = find_client(cfg)
            if not creds:
                if "--once" in args:
                    log.info("League client is not running. Open League, then try again.")
                    return
                if not waiting_logged:
                    log.info("Waiting for the League client to open...")
                    waiting_logged = True
                time.sleep(POLL_SECONDS)
                continue
            waiting_logged = False
            lcu = LeagueClient(*creds)

            try:
                phase = lcu.get("/lol-gameflow/v1/gameflow-phase")
            except (urllib.error.URLError, OSError, ValueError):
                phase = None

            if phase in ("InProgress", "Reconnect", "GameStart") and "--once" not in args:
                # Mid-game: nothing new to upload until it ends.
                last_phase = phase
                time.sleep(30)
                continue

            if phase in ("PreEndOfGame", "EndOfGame", "WaitingForStats") and last_phase != phase:
                time.sleep(AFTER_GAME_DELAY)  # give match history a moment to update
            last_phase = phase

            me = current_player(lcu)
            sync(cfg, lcu, seen, me, force=force)
            force = False
            if "--once" in args:
                return
        except SystemExit:
            raise
        except Exception as e:  # keep running through client restarts and network blips
            log.warning("Check failed: %s", e)
            if "--once" in args:
                return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

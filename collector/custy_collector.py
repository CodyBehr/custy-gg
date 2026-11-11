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
    python custy_collector.py --review   open the game review page (test)

Settings live in config.json next to this file.

Packaged as custy-collector.exe (see collector/windows_app.py), the same code
runs as a one-click Windows app: the site's address and upload key are
attached to the end of the .exe when it is downloaded, double-clicking it
installs it to %LOCALAPPDATA%/custy-collector and starts it with Windows.
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

VERSION = "1.9.9"
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # Packaged app: keep config, state and log in the user's app-data folder.
    HERE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "custy-collector")
    os.makedirs(HERE, exist_ok=True)
else:
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

TRAILER_START = b"\n#CUSTY-CONFIG#"
TRAILER_END = b"#END-CUSTY-CONFIG#"


def embedded_config(path=None):
    """Settings the website attached to the end of this .exe, or None."""
    path = path or (sys.executable if FROZEN else None)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read()
    except OSError:
        return None
    start = tail.rfind(TRAILER_START)
    end = tail.rfind(TRAILER_END)
    if start < 0 or end < start:
        return None
    try:
        return json.loads(tail[start + len(TRAILER_START):end].decode("utf-8"))
    except ValueError:
        return None


def load_config():
    cfg = embedded_config()
    if cfg is None:
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


TIMELINE_STATE = STATE_PATH.replace(".json", "") + "-timelines.json"


def load_timeline_state():
    try:
        with open(TIMELINE_STATE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_timeline_state(done):
    tmp = TIMELINE_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f)
    os.replace(tmp, TIMELINE_STATE)


TIMELINE_EVENTS = {"CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL", "ITEM_PURCHASED", "ITEM_UNDO",
                   "ITEM_SOLD", "SKILL_LEVEL_UP", "WARD_PLACED", "WARD_KILL", "CHAMPION_SPECIAL_KILL"}


def slim_timeline(tl):
    """Drops event types the site doesn't use, to keep the upload small."""
    out = dict(tl)
    out["frames"] = [dict(f, events=[e for e in (f.get("events") or []) if e.get("type") in TIMELINE_EVENTS])
                     for f in tl.get("frames") or []]
    return out


def send_timeline(cfg, lcu, key, game_id):
    """Uploads one game's timeline. Returns True when the site has it (or can't use it), so we stop trying."""
    try:
        tl = lcu.get("/lol-match-history/v1/game-timelines/%s" % game_id)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.info("No timeline for %s from the client: %s", key, e)
        return True
    if not tl or not tl.get("frames"):
        log.info("No timeline for %s from the client", key)
        return True
    tl = slim_timeline(tl)
    status, body = post_json(cfg["site_url"] + "/api/timeline", cfg["ingest_key"], {"id": key, "timeline": tl})
    if status in (200, 201):
        log.info("Uploaded timeline for %s", key)
        return True
    if status in (404, 413, 422):
        log.warning("Site couldn't take the timeline for %s (HTTP %s): %s", key, status, body.get("error", ""))
        return True
    log.warning("Timeline upload for %s failed (HTTP %s), will retry", key, status)
    return False


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
    """Upload any custom games not uploaded before. Returns how many were new to the site."""
    uploaded = 0
    created = 0
    new_players = set()
    timelines = load_timeline_state()
    timelines_before = len(timelines)
    for summary in recent_games(lcu):
        if not is_custom(summary):
            continue
        key = game_key(summary)
        if key in seen and not force:
            # Games uploaded before timelines existed: send their timeline once.
            if key not in timelines and send_timeline(cfg, lcu, key, summary["gameId"]):
                timelines.add(key)
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
            if body.get("needTimeline") and key not in timelines:
                if send_timeline(cfg, lcu, key, summary["gameId"]):
                    timelines.add(key)
            elif not body.get("needTimeline"):
                timelines.add(key)
            if body.get("status") == "exists":
                log.info("Custom game %s is already on the site", key)
            else:
                created += 1
                log.info("Uploaded custom game %s", key)
                for ident in game.get("participantIdentities") or []:
                    puuid = (ident.get("player") or {}).get("puuid") or ""
                    if puuid and set(puuid.replace("-", "")) != {"0"}:
                        new_players.add(puuid)
        elif status == 401:
            raise SystemExit("The site rejected the ingest_key in config.json. Check it matches INGEST_KEY.")
        else:
            log.warning("Upload of %s failed (HTTP %s): %s", key, status, body.get("error", ""))
    if uploaded:
        save_state(seen)
    if len(timelines) != timelines_before:
        save_timeline_state(timelines)
    if new_players:
        try:
            send_ranks(cfg, lcu, new_players)
        except Exception as e:
            log.warning("Couldn't send ranks: %s", e)
    return created


# --------------------------------------------------------------------------
# Who's in the custom lobby (for the Discord team maker)
# --------------------------------------------------------------------------

_last_lobby = {"key": None, "sent": 0.0}


def _name_of(entry):
    for k in ("gameName", "riotIdGameName", "summonerName", "displayName"):
        if entry.get(k):
            return str(entry[k]).split("#")[0]
    return ""


def lobby_members(lcu):
    """Players in the current custom lobby, or None when not in one."""
    try:
        lobby = lcu.get("/lol-lobby/v2/lobby")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    cfg = (lobby or {}).get("gameConfig") or {}
    if not lobby or not cfg.get("isCustom"):
        return None
    seen, out = set(), []
    groups = [(100, cfg.get("customTeam100") or []), (200, cfg.get("customTeam200") or []),
              (0, cfg.get("customSpectators") or []), (0, lobby.get("members") or [])]
    for team, entries in groups:
        for e in entries:
            if not isinstance(e, dict) or e.get("isBot") or e.get("botId"):
                continue
            puuid = e.get("puuid") or ""
            key = puuid or _name_of(e)
            if not key or key in seen:
                continue
            seen.add(key)
            name, tag = _name_of(e), e.get("tagLine") or e.get("riotIdTagLine") or ""
            if puuid and (not name or not tag):
                try:
                    who = lcu.get("/lol-summoner/v2/summoners/puuid/%s" % puuid) or {}
                    name, tag = who.get("gameName") or name, who.get("tagLine") or tag
                except (urllib.error.URLError, OSError, ValueError):
                    pass
            if name:
                out.append({"puuid": puuid or None, "name": name, "tag": tag or None, "team": team})
    return out


def read_rank(lcu, puuid):
    """Solo queue rank for any player, read from the League client (no Riot API key needed)."""
    if not puuid:
        return None
    try:
        data = lcu.get("/lol-ranked/v1/ranked-stats/%s" % puuid) or {}
    except (urllib.error.URLError, OSError, ValueError):
        return None
    queues = data.get("queueMap") or {q.get("queueType"): q for q in (data.get("queues") or []) if isinstance(q, dict)}

    def pick(q):
        tier = (q or {}).get("tier") or ""
        if tier and tier.upper() not in ("NONE", "NA", "UNRANKED"):
            return tier.upper(), (q.get("division") or "").upper(), int(q.get("leaguePoints") or 0), q
        return None

    for key, source in (("RANKED_SOLO_5x5", "solo"), ("RANKED_FLEX_SR", "flex")):
        hit = pick(queues.get(key))
        if hit:
            tier, div, lp, q = hit
            return {"tier": tier, "division": div if div not in ("NA", "") else "", "lp": lp,
                    "wins": q.get("wins"), "losses": q.get("losses"), "source": source}
    solo = queues.get("RANKED_SOLO_5x5") or {}
    prev = (solo.get("previousSeasonEndTier") or data.get("highestPreviousSeasonEndTier") or "").upper()
    if prev and prev not in ("NONE", "NA", "UNRANKED"):
        div = (solo.get("previousSeasonEndDivision") or "").upper()
        return {"tier": prev, "division": div if div != "NA" else "", "lp": 0, "source": "last season"}
    return {"tier": "", "division": "", "lp": 0, "source": ""}


def send_ranks(cfg, lcu, puuids):
    """Reads and uploads ranks for a set of players (e.g. everyone in a game just uploaded)."""
    ranks = {}
    for p in list(puuids)[:30]:
        r = read_rank(lcu, p)
        if r is not None:
            ranks[p] = r
    if ranks:
        post_json(cfg["site_url"] + "/api/ranks", cfg["ingest_key"], {"ranks": ranks})


def send_lobby(cfg, lcu, me):
    """Posts the lobby when it changes (and every few minutes while it lasts)."""
    members = lobby_members(lcu)
    if not members:
        return
    key = ",".join(sorted("%s:%s" % (m["name"], m["team"]) for m in members))
    if key == _last_lobby["key"] and time.time() - _last_lobby["sent"] < 300:
        return
    for m in members:
        m["rank"] = read_rank(lcu, m.get("puuid"))
    status, _ = post_json(cfg["site_url"] + "/api/lobby", cfg["ingest_key"], {"members": members, "uploader": me})
    if status == 200:
        _last_lobby.update(key=key, sent=time.time())
        log.info("Sent lobby to the site: %s", ", ".join(m["name"] for m in members))


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
    if "--selftest" in args:
        # Used by the build: proves the packaged app starts and can read attached settings.
        out = sys.argv[sys.argv.index("--selftest") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "frozen": FROZEN, "config": embedded_config()}, f)
        return
    if FROZEN and platform.system() == "Windows" and "--test" not in args:
        import windows_app  # installs, updates or removes the app; returns True to keep running here
        if not windows_app.handle_launch(args):
            return
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:  # None when launched hidden with pythonw/pyw
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    cfg = load_config()
    if "--test" in args:
        sys.exit(0 if run_test(cfg) else 1)
    if "--review" in args:
        import review
        review.serve_forever(cfg)
        return

    log.info("custy.gg collector %s started, uploading to %s", VERSION, cfg["site_url"])
    if FROZEN and platform.system() == "Windows":
        import windows_app
        windows_app.run_with_tray(cfg, lambda stop: run_collector(cfg, args, stop))
    else:
        run_collector(cfg, args)


# What the tray icon shows. Updated by the collector loop.
STATUS = {"state": "Starting", "uploaded": 0, "last_upload": None, "paused": False, "on_upload": None}


def run_collector(cfg, args, stop=None):
    """Checks for new custom games until `stop` (a threading.Event) is set."""
    def wait(seconds):
        if stop is None:
            time.sleep(seconds)
            return False
        return stop.wait(seconds)

    seen = set() if "--all" in args else load_state()
    force = "--all" in args
    last_phase = None
    waiting_logged = False
    while not (stop and stop.is_set()):
        try:
            if STATUS["paused"]:
                STATUS["state"] = "Paused"
                if wait(5):
                    return
                continue
            creds = find_client(cfg)
            if not creds:
                STATUS["state"] = "Waiting for League to open"
                if "--once" in args:
                    log.info("League client is not running. Open League, then try again.")
                    return
                if not waiting_logged:
                    log.info("Waiting for the League client to open...")
                    waiting_logged = True
                if wait(POLL_SECONDS):
                    return
                continue
            waiting_logged = False
            lcu = LeagueClient(*creds)

            try:
                phase = lcu.get("/lol-gameflow/v1/gameflow-phase")
            except (urllib.error.URLError, OSError, ValueError):
                phase = None

            if phase in ("InProgress", "Reconnect", "GameStart") and "--once" not in args:
                # Mid-game: nothing new to upload until it ends.
                STATUS["state"] = "In a game"
                last_phase = phase
                if wait(30):
                    return
                continue

            if phase in ("PreEndOfGame", "EndOfGame", "WaitingForStats") and last_phase != phase:
                STATUS["state"] = "Game ended, checking for it"
                if wait(AFTER_GAME_DELAY):  # give match history a moment to update
                    return
            last_phase = phase

            STATUS["state"] = "Watching for custom games"
            me = current_player(lcu)
            in_lobby = phase in ("Lobby", "ChampSelect")
            if in_lobby:
                STATUS["state"] = "In a lobby"
                try:
                    send_lobby(cfg, lcu, me)
                except Exception as e:
                    log.warning("Couldn't send the lobby: %s", e)
            n = sync(cfg, lcu, seen, me, force=force)
            if n:
                STATUS["uploaded"] += n
                STATUS["last_upload"] = time.time()
                if STATUS["on_upload"]:
                    try:
                        STATUS["on_upload"](n)
                    except Exception:
                        pass
            force = False
            if "--once" in args:
                return
            if in_lobby:
                if wait(15):  # check the lobby more often so the roster stays current
                    return
                continue
        except SystemExit as e:
            if stop is None:
                raise
            STATUS["state"] = "Stopped: %s" % e
            log.error("%s", e)
            return
        except Exception as e:  # keep running through client restarts and network blips
            STATUS["state"] = "Couldn't reach League, retrying"
            log.warning("Check failed: %s", e)
            if "--once" in args:
                return
        if wait(POLL_SECONDS):
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

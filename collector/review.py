"""
Game review (test version).

A small page, served only to this computer, that reviews your recent
Summoner's Rift games (ranked, normals, quickplay; not customs): your lane gold
difference by minute, the moments it slipped, your back, item and level 6
timings, and a button that opens your replay at that moment.

Nothing here is uploaded anywhere. Games and timelines read from the League
client are kept in review-cache/ next to the app's log, so the comparison with
"your usual" grows as you play with the app running.

    python custy_collector.py --review     open it without the Windows app
"""

import json
import os
import re
import secrets
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

core = sys.modules.get("custy_collector") or sys.modules["__main__"]

CACHE_DIR = os.path.join(core.HERE, "review-cache")
INFO_PATH = os.path.join(core.HERE, "review.json")   # where the running app's page is
CACHE_LIMIT = 400          # games kept on disk (oldest dropped first)
HISTORY_DEPTH = 100        # how far back to look in the client's match history
REPLAY_API = "https://127.0.0.1:2999"
SR_MAP = 11

QUEUES = {420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal Draft", 430: "Normal Blind",
          490: "Quickplay", 480: "Swiftplay", 700: "Clash"}

# The role quest slot (stats.roleBoundItem) names each player's role. Same table as lib/normalize.ts.
QUEST_ROLE = {
    1090: "TOP", 1200: "TOP", 1220: "TOP", 1221: "TOP", 1222: "TOP",
    1094: "JUNGLE", 1204: "JUNGLE", 1205: "JUNGLE", 1209: "JUNGLE", 1210: "JUNGLE", 1211: "JUNGLE",
    1091: "MID", 1201: "MID", 1206: "MID",
    1092: "BOT", 1202: "BOT", 1207: "BOT",
    1093: "SUPPORT", 1203: "SUPPORT", 1208: "SUPPORT", 2055: "SUPPORT", 2056: "SUPPORT",
}
BOOTS = {1001, 2422, 3005, 3006, 3008, 3009, 3010, 3013, 3020, 3047, 3111, 3117, 3158, 3168, 3170,
         3171, 3172, 3173, 3174, 3175, 3176}
KEEP_EVENTS = {"CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL", "ITEM_PURCHASED", "ITEM_UNDO",
               "ITEM_SOLD", "SKILL_LEVEL_UP", "TURRET_PLATE_DESTROYED"}
FRAME_FIELDS = ("totalGold", "currentGold", "minionsKilled", "jungleMinionsKilled", "level", "xp", "position")

_lock = threading.Lock()
_bench = {}   # name -> (fetched_at, data or None)
_replay = {"state": "idle", "message": "", "game": None, "at": 0}


# --------------------------------------------------------------------------
# Reading games from the client, with a local cache
# --------------------------------------------------------------------------

def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def roles(game):
    """participantId -> TOP/JUNGLE/MID/BOT/SUPPORT, from the role quest slot, else a guess."""
    out = {}
    for team in (100, 200):
        players = [p for p in game.get("participants") or [] if _num(p.get("teamId")) == team]
        taken = set()
        for p in players:
            st = p.get("stats") or {}
            r = QUEST_ROLE.get(_num(st.get("roleBoundItem"))) or ("BOT" if _num(st.get("roleBoundItem")) in BOOTS else "")
            if r and r not in taken:
                out[p["participantId"]] = r
                taken.add(r)
        rest = [p for p in players if p["participantId"] not in out]
        for p in rest:  # fall back to Smite, then the lane the game saw
            tl = p.get("timeline") or {}
            lane, sub = str(tl.get("lane") or "").upper(), str(tl.get("role") or "").upper()
            guess = ("JUNGLE" if 11 in (_num(p.get("spell1Id")), _num(p.get("spell2Id"))) else
                     "TOP" if lane == "TOP" else "MID" if lane in ("MIDDLE", "MID") else
                     "SUPPORT" if sub == "DUO_SUPPORT" else "BOT" if sub == "DUO_CARRY" else "")
            if guess and guess not in taken:
                out[p["participantId"]] = guess
                taken.add(guess)
        rest = sorted([p for p in players if p["participantId"] not in out],
                      key=lambda p: -_num((p.get("stats") or {}).get("totalMinionsKilled")))
        left = [r for r in ("TOP", "MID", "BOT", "JUNGLE", "SUPPORT") if r not in taken]
        for p, r in zip(rest, left):
            out[p["participantId"]] = r
    return out


def _is_reviewable(summary):
    if summary.get("gameType") == "CUSTOM_GAME":
        return False
    m = summary.get("mapId")
    return m in (None, SR_MAP) and str(summary.get("gameMode") or "CLASSIC") == "CLASSIC"


def _slim_timeline(tl):
    frames = []
    for f in tl.get("frames") or []:
        pfs = f.get("participantFrames") or {}
        items = pfs.values() if isinstance(pfs, dict) else pfs
        slim = {}
        for pf in items:
            pid = str(pf.get("participantId"))
            slim[pid] = {k: pf.get(k) for k in FRAME_FIELDS if k in pf}
        frames.append({"timestamp": f.get("timestamp"), "participantFrames": slim,
                       "events": [e for e in f.get("events") or [] if e.get("type") in KEEP_EVENTS]})
    return {"frames": frames}


def _cache_path(game_id):
    return os.path.join(CACHE_DIR, "%s.json" % int(game_id))


def _read_cache(game_id):
    try:
        with open(_cache_path(game_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_cache(game_id, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _cache_path(game_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, _cache_path(game_id))


def _prune_cache():
    try:
        files = sorted((os.path.getmtime(os.path.join(CACHE_DIR, n)), n) for n in os.listdir(CACHE_DIR) if n.endswith(".json"))
    except OSError:
        return
    for _, name in files[:-CACHE_LIMIT] if len(files) > CACHE_LIMIT else []:
        try:
            os.remove(os.path.join(CACHE_DIR, name))
        except OSError:
            pass


def _summarize(game, me_puuid):
    """The few fields the game list needs."""
    idents = {i.get("participantId"): (i.get("player") or {}) for i in game.get("participantIdentities") or []}
    rl = roles(game)
    me = None
    for p in game.get("participants") or []:
        if idents.get(p["participantId"], {}).get("puuid") == me_puuid:
            me = p
    if me is None:
        return None
    opp = next((p for p in game["participants"] if _num(p.get("teamId")) != _num(me.get("teamId"))
                and rl.get(p["participantId"]) == rl.get(me["participantId"])), None)
    st = me.get("stats") or {}
    return {
        "id": game.get("gameId"), "created": game.get("gameCreation"), "duration": game.get("gameDuration"),
        "queue": QUEUES.get(_num(game.get("queueId")), "Queue %s" % game.get("queueId")),
        "version": game.get("gameVersion"),
        "champion": me.get("championId"), "role": rl.get(me["participantId"], ""),
        "opponent": opp.get("championId") if opp else None,
        "win": bool(st.get("win")), "kills": st.get("kills"), "deaths": st.get("deaths"), "assists": st.get("assists"),
        "cs": _num(st.get("totalMinionsKilled")) + _num(st.get("neutralMinionsKilled")),
    }


_cfg = {}


def _has_purchases(tl):
    return any(e.get("type") == "ITEM_PURCHASED" for f in (tl or {}).get("frames") or [] for e in f.get("events") or [])


def fill_from_riot(data):
    """The client's timeline for ranked/normal games has no item purchases or skill-ups.
    Asks the site, which gets them from Riot's match API, and merges them in. Returns True if it changed anything."""
    tl, game = data.get("timeline"), data.get("game") or {}
    if not tl or _has_purchases(tl) or not _cfg.get("site_url"):
        return False
    # "fillTried2": attempts made before the site had its Riot key don't count.
    if time.time() - float(data.get("fillTried2") or 0) < 600:
        return False
    data["fillTried2"] = time.time()
    url = "%s/api/review/timeline?platform=%s&gameId=%s" % (_cfg["site_url"].rstrip("/"), game.get("platformId") or "NA1", game.get("gameId"))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + _cfg.get("ingest_key", ""),
                                               "User-Agent": "custy-collector/" + core.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            extra = json.loads(r.read())
    except Exception as e:
        core.log.info("Review: couldn't get item data for %s from the site: %s", game.get("gameId"), e)
        return True   # remember when we tried
    # Riot's participant numbers -> the client's, matched by player
    by_puuid = {(i.get("player") or {}).get("puuid"): i.get("participantId") for i in game.get("participantIdentities") or []}
    pid_map = {p["participantId"]: by_puuid.get(p["puuid"], p["participantId"]) for p in extra.get("participants") or []}
    frames = tl.get("frames") or []
    added = 0
    for f in extra.get("frames") or []:
        for e in f.get("events") or []:
            e = dict(e)
            if "participantId" in e:
                e["participantId"] = pid_map.get(e["participantId"], e["participantId"])
            if not frames:
                break
            idx = min(len(frames) - 1, int((e.get("timestamp") or 0) // 60000) + 1)
            frames[idx].setdefault("events", []).append(e)
            added += 1
    for f in frames:
        f["events"] = sorted(f.get("events") or [], key=lambda e: e.get("timestamp") or 0)
    data["filled"] = added
    core.log.info("Review: added %d item and skill events to game %s from Riot", added, game.get("gameId"))
    return True


def _lcu(cfg):
    creds = core.find_client(cfg)
    return core.LeagueClient(*creds) if creds else None


def fetch_game(lcu, game_id, me_puuid):
    """Game + timeline from the cache, or from the client (then cached)."""
    data = _read_cache(game_id)
    if data and data.get("timeline") is not None:
        return data
    if lcu is None:
        return data
    game = lcu.get("/lol-match-history/v1/games/%s" % game_id)
    if not game or not game.get("participants"):
        return None
    try:
        tl = _slim_timeline(lcu.get("/lol-match-history/v1/game-timelines/%s" % game_id) or {})
    except (urllib.error.URLError, OSError, ValueError):
        tl = None
    data = {"game": game, "timeline": tl if tl and tl["frames"] else None,
            "summary": _summarize(game, me_puuid), "me": me_puuid}
    fill_from_riot(data)
    _write_cache(game_id, data)
    return data


def refresh(cfg):
    """Reads any reviewable games in the client's history that aren't cached yet. Returns (me, error)."""
    lcu = _lcu(cfg)
    if lcu is None:
        return None, "League isn't open. Showing games saved earlier."
    me = core.current_player(lcu)
    if not me.get("puuid"):
        return None, "League is open but not logged in yet."
    try:
        data = lcu.get("/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=%d" % HISTORY_DEPTH)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return me, "Couldn't read match history: %s" % e
    games = (data or {}).get("games") or {}
    if isinstance(games, dict):
        games = games.get("games") or []
    for s in games:
        if not _is_reviewable(s) or not s.get("gameId"):
            continue
        cached = _read_cache(s["gameId"])
        if cached and cached.get("timeline") is not None:
            continue
        try:
            fetch_game(lcu, s["gameId"], me["puuid"])
        except (urllib.error.URLError, OSError, ValueError) as e:
            core.log.info("Review: couldn't read game %s: %s", s.get("gameId"), e)
    _prune_cache()
    return me, None


def list_games(me_puuid=None):
    out = []
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        data = _read_cache(n[:-5])
        s = (data or {}).get("summary")
        if not s or (me_puuid and data.get("me") != me_puuid):
            continue
        g = data.get("game") or {}
        if not _is_reviewable(g):
            continue
        s = dict(s, hasTimeline=data.get("timeline") is not None)
        out.append(s)
    out.sort(key=lambda s: s.get("created") or 0, reverse=True)
    return out


# --------------------------------------------------------------------------
# Replays: download, start, and jump to a time
# --------------------------------------------------------------------------

def league_dir(cfg):
    dirs = ([cfg["league_path"]] if cfg.get("league_path") else []) + list(core.DEFAULT_LEAGUE_DIRS)
    for d in dirs:
        if os.path.exists(os.path.join(d, "lockfile")) or os.path.isdir(os.path.join(d, "Config")):
            return d
    m = re.search(r'--install-directory=([^"]+?)(?:"|\s--|$)', core._client_command_line())
    return m.group(1).strip() if m else None


def _game_cfg(cfg):
    d = league_dir(cfg)
    return os.path.join(d, "Config", "game.cfg") if d else None


def replay_api_enabled(cfg):
    path = _game_cfg(cfg)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    return bool(re.search(r"(?im)^\s*EnableReplayApi\s*=\s*1\s*$", text))


def enable_replay_api(cfg):
    """Adds EnableReplayApi=1 under [General] in League's game.cfg (keeps a backup of the original)."""
    path = _game_cfg(cfg)
    if not path or not os.path.exists(path):
        raise ValueError("Couldn't find League's Config/game.cfg")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    backup = path + ".custy-backup"
    if not os.path.exists(backup):
        with open(backup, "w", encoding="utf-8") as f:
            f.write(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    if re.search(r"(?im)^\s*EnableReplayApi\s*=", text):
        text = re.sub(r"(?im)^(\s*EnableReplayApi\s*=).*$", r"\g<1>1", text)
    elif re.search(r"(?im)^\[General\]\s*$", text):
        text = re.sub(r"(?im)^(\[General\]\s*?)$", lambda m: m.group(1) + nl + "EnableReplayApi=1", text, count=1)
    else:
        text = text.rstrip() + nl + nl + "[General]" + nl + "EnableReplayApi=1" + nl
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _local_ctx():
    # League's local servers use self-signed certificates; only ever used for 127.0.0.1.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _lcu_post(lcu, path, body):
    req = urllib.request.Request(lcu.base + path, data=json.dumps(body).encode(), method="POST",
                                 headers=dict(lcu.headers, **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, context=lcu.ctx, timeout=20) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def _playback(body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(REPLAY_API + "/replay/playback", data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=_local_ctx(), timeout=5) as r:
        return json.loads(r.read() or b"{}")


def _status(state, message, **extra):
    with _lock:
        _replay.update(state=state, message=message, at=time.time(), **extra)
    core.log.info("Replay: %s", message)


def _clock(t):
    t = max(0, int(t))
    return "%d:%02d" % (t // 60, t % 60)


def _live(path):
    req = urllib.request.Request(REPLAY_API + path)
    with urllib.request.urlopen(req, context=_local_ctx(), timeout=5) as r:
        return json.loads(r.read() or b"null")


def _replay_is_game(game_id):
    """True/False if the open replay is (not) this game, None if we can't tell."""
    data = _read_cache(game_id)
    if not data:
        return None
    try:   # the replay's length is the game's length
        length, dur = float(_playback().get("length") or 0), float((data.get("game") or {}).get("gameDuration") or 0)
        if length and dur and abs(length - dur) > 20:
            return False
    except Exception:
        pass
    want = set()
    for i in (data.get("game") or {}).get("participantIdentities") or []:
        pl = i.get("player") or {}
        if pl.get("gameName"):
            want.add(("%s#%s" % (pl.get("gameName"), pl.get("tagLine") or "")).lower())
    try:
        players = _live("/liveclientdata/playerlist") or []
    except Exception:
        return None
    seen = {str(p.get("riotId") or "").lower() for p in players if p.get("riotId")}
    if not want or not seen:
        return None
    return len(want & seen) >= len(want) - 1   # same ten players (allowing one renamed)


def _replay_playing():
    """The replay has finished loading and its clock is running (seeking any earlier gets ignored)."""
    try:
        if not _playback().get("length"):
            return False
        if (_live("/liveclientdata/gamestats") or {}).get("gameTime") is None:
            return False
        a = float(_playback().get("time") or 0)
        time.sleep(1.5)
        pb = _playback()
        return float(pb.get("time") or 0) > a or bool(pb.get("paused"))
    except Exception:
        return False


def _seek(seconds):
    """Jumps and waits for the jump to finish before checking it (re-sending mid-seek restarts it)."""
    target = float(seconds)
    for attempt in range(4):
        _status("working", "Jumping to %s..." % _clock(target))
        try:
            _playback({"time": target, "paused": False})
        except Exception as e:
            core.log.info("Replay seek %d failed: %s", attempt + 1, e)
        # Long jumps take a few seconds while the replay catches up; wait until it's done.
        settled_at = time.time() + 20
        now = None
        while time.time() < settled_at:
            time.sleep(1)
            try:
                pb = _playback()
            except Exception:
                continue
            if pb.get("seeking"):
                continue
            now = float(pb.get("time") or 0)
            if target - 3 <= now <= target + 20:
                return _status("done", "Jumped to %s." % _clock(target))
            if time.time() > settled_at - 14:   # gave it 6s without seeking: it didn't take
                break
        core.log.info("Replay seek %d landed at %s, wanted %s", attempt + 1, now, target)
        time.sleep(1.5)
    return _status("done", "Replay is open, but the jump didn't stick. Drag the timeline to %s." % _clock(target))


def _open_replay(cfg, game_id, seconds):
    try:
        lcu = _lcu(cfg)
        if lcu is None:
            return _status("error", "Open League first: replays are played through the client.")
        # A replay already open? Jump in it if it's this game; otherwise it has to be closed first.
        try:
            open_now = bool(_playback().get("length"))
        except Exception:
            open_now = False
        if open_now:
            if _replay_is_game(game_id) is False:
                return _status("error", "A different replay is open. Close it, then click Watch again.")
            return _seek(seconds)

        meta = lcu.get("/lol-replays/v1/metadata/%s" % game_id) or {}
        state = meta.get("state")
        if state in ("incompatible", "unsupported"):
            return _status("error", "This replay is from an older patch, so League can't play it. "
                                    "Moments still show their times.")
        if state in ("lost", "missingOrExpired", "error"):
            return _status("error", "League no longer has this replay (state: %s)." % state)
        if state != "watch":
            _status("working", "Downloading the replay...")
            try:
                _lcu_post(lcu, "/lol-replays/v1/rofls/%s/download" % game_id, {"componentType": "replay-button_match-history"})
            except urllib.error.HTTPError as e:
                core.log.info("Replay download request: HTTP %s", e.code)
            for _ in range(120):
                time.sleep(1)
                meta = lcu.get("/lol-replays/v1/metadata/%s" % game_id) or {}
                if meta.get("state") == "watch":
                    break
                if meta.get("state") in ("incompatible", "unsupported", "lost", "missingOrExpired", "error"):
                    return _status("error", "League couldn't get this replay (state: %s)." % meta.get("state"))
                pct = meta.get("downloadProgress")
                if pct:
                    _status("working", "Downloading the replay... %s%%" % pct)
            else:
                return _status("error", "The replay didn't finish downloading. Try again in a minute.")

        _status("working", "Starting the replay...")
        _lcu_post(lcu, "/lol-replays/v1/rofls/%s/watch" % game_id, {"componentType": "replay-button_match-history"})

        if replay_api_enabled(cfg) is False:
            return _status("done", "Replay is starting. Jumping isn't turned on, so drag the timeline to %s." % _clock(seconds))

        _status("working", "Waiting for the replay to load...")
        deadline = time.time() + 240
        while time.time() < deadline:
            time.sleep(2)
            if _replay_playing():
                return _seek(seconds)
        return _status("error", "The replay didn't open within 4 minutes. If it opened, drag the timeline to %s." % _clock(seconds))
    except Exception as e:
        _status("error", "Couldn't open the replay: %s" % e)


# --------------------------------------------------------------------------
# The local web server
# --------------------------------------------------------------------------

def _page():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, "review.html"), "rb") as f:
        return f.read()


def benchmark(cfg, name):
    """High-elo numbers for one champion and role, from the site (refreshed every few hours)."""
    hit = _bench.get(name)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    data = {"missing": True}
    try:
        url = cfg["site_url"].rstrip("/") + "/benchmarks/%s.json" % name
        req = urllib.request.Request(url, headers={"User-Agent": "custy-collector/" + core.VERSION})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code != 404 and hit:
            return hit[1]
    except Exception:
        if hit:
            return hit[1]
        return {"missing": True, "offline": True}
    _bench[name] = (time.time(), data)
    return data


def make_handler(cfg, token):
    me_cache = {"me": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self):
            # Only this computer, only our own page (stops other sites from poking it).
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            return secrets.compare_digest(self.headers.get("X-Custy-Key") or "", token)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost") or parse_qs(url.query).get("k", [""])[0] != token:
                    return self._send(403, b"Open this from the custy.gg app.", "text/plain")
                return self._send(200, _page(), "text/html; charset=utf-8")
            if url.path == "/api/ping":
                return self._send(200, {"ok": True})
            if not self._allowed():
                return self._send(403, {"error": "forbidden"})
            if url.path == "/api/games":
                me, err = refresh(cfg)
                if me:
                    me_cache["me"] = me
                me = me_cache["me"]
                games = list_games(me.get("puuid") if me else None)
                return self._send(200, {"me": me, "note": err, "games": games,
                                        "replayApi": replay_api_enabled(cfg)})
            m = re.match(r"^/api/game/(\d+)$", url.path)
            if m:
                me = me_cache["me"] or {}
                data = fetch_game(_lcu(cfg) if not _read_cache(m.group(1)) else None, m.group(1), me.get("puuid"))
                if not data:
                    return self._send(404, {"error": "game not found"})
                if fill_from_riot(data):
                    _write_cache(m.group(1), data)
                return self._send(200, dict(data, roles=roles(data["game"])))
            m = re.match(r"^/api/benchmark/([A-Za-z]+-(?:TOP|JUNGLE|MID|BOT|SUPPORT))$", url.path)
            if m:
                return self._send(200, benchmark(cfg, m.group(1)))
            if url.path == "/api/replay":
                with _lock:
                    return self._send(200, dict(_replay))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._allowed():
                return self._send(403, {"error": "forbidden"})
            m = re.match(r"^/api/replay/(\d+)$", url.path)
            if m:
                t = float(parse_qs(url.query).get("t", ["0"])[0])
                with _lock:
                    busy = _replay["state"] == "working" and time.time() - _replay["at"] < 200
                if busy:
                    return self._send(409, {"error": "A replay is already being opened."})
                _status("working", "Opening the replay...", game=m.group(1))
                threading.Thread(target=_open_replay, args=(cfg, m.group(1), t), daemon=True).start()
                return self._send(202, {"ok": True})
            if url.path == "/api/replay-setup":
                try:
                    enable_replay_api(cfg)
                    return self._send(200, {"ok": True, "replayApi": replay_api_enabled(cfg)})
                except Exception as e:
                    return self._send(500, {"error": str(e)})
            return self._send(404, {"error": "not found"})

    return Handler


def start(cfg, port=0):
    """Starts the page in a background thread. Returns its address (with the access key)."""
    _cfg.update(cfg)
    token = secrets.token_urlsafe(18)
    # A fixed port when it's free, so the page keeps its saved choices (like the queue filter) between restarts.
    server = None
    for p in ([port] if port else [47821, 0]):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), make_handler(cfg, token))
            break
        except OSError:
            continue
    url = "http://127.0.0.1:%d/?k=%s" % (server.server_address[1], token)
    threading.Thread(target=server.serve_forever, name="review", daemon=True).start()
    try:
        with open(INFO_PATH, "w", encoding="utf-8") as f:
            json.dump({"url": url, "pid": os.getpid()}, f)
    except OSError:
        pass
    core.log.info("Game review page ready")
    return url


def running_url():
    """The page address of an app that's already running, or None."""
    try:
        with open(INFO_PATH, "r", encoding="utf-8") as f:
            url = json.load(f).get("url")
        base = url.split("/?")[0]
        with urllib.request.urlopen(base + "/api/ping", timeout=2) as r:
            if r.status == 200:
                return url
    except Exception:
        pass
    return None


def open_window(url):
    """Opens the page in its own app-style window (Edge or Chrome), else the normal browser."""
    import subprocess
    import webbrowser
    if sys.platform == "win32":
        candidates = []
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                candidates += [os.path.join(root, r"Microsoft\Edge\Application\msedge.exe"),
                               os.path.join(root, r"Google\Chrome\Application\chrome.exe")]
        for exe in candidates:
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, "--app=" + url, "--window-size=1280,900"], close_fds=True)
                    return
                except OSError:
                    pass
    webbrowser.open(url)


def keep_cache_fresh(cfg, stop):
    """Saves new games to the review cache after each game, so 'your usual' keeps growing."""
    stop.wait(90)
    last = None
    while not stop.is_set():
        try:
            lcu = _lcu(cfg)
            phase = lcu.get("/lol-gameflow/v1/gameflow-phase") if lcu else None
            if lcu and phase not in ("InProgress", "Reconnect", "GameStart") and phase != last:
                refresh(cfg)
            last = phase
        except Exception as e:
            core.log.info("Review cache: %s", e)
        stop.wait(120)


def serve_forever(cfg):
    """For --review outside the Windows app: serve the page until Ctrl+C."""
    url = start(cfg)
    print("Game review: " + url)
    open_window(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass

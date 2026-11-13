"""
Game review (test version).

A small page, served only to this computer, that reviews your recent
Summoner's Rift games (ranked, normals, quickplay; not customs): your lane gold
difference by minute, the moments it slipped, your back, item and level 6
timings, and a button that opens your replay at that moment.

Games and timelines read from the League client stay on this computer, in
review-cache/ next to the app's log, so the comparison with "your usual" grows
as you play with the app running. Two things come from the site: the item
purchases and skill-ups the client leaves out of ranked games (the app sends
the game's id; the site looks them up with its Riot key), and the expert
numbers for the "vs Experts" tab.

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
KEY_PATH = os.path.join(core.HERE, "review-key.txt")  # the page's access key, kept across restarts
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
               "ITEM_SOLD", "SKILL_LEVEL_UP", "LEVEL_UP", "TURRET_PLATE_DESTROYED"}
FRAME_FIELDS = ("totalGold", "currentGold", "minionsKilled", "jungleMinionsKilled", "level", "xp", "position", "armor", "st")

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


_index = {}   # file name -> (mtime, the small facts list_games and refresh need)


def _info(name):
    """Summary facts about one cached game, without re-reading its (large) file unless it changed."""
    path = os.path.join(CACHE_DIR, name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _index.pop(name, None)
        return None
    hit = _index.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    data = _read_cache(name[:-5])
    info = None
    if data:
        info = {"summary": data.get("summary"), "me": data.get("me"), "hasTimeline": data.get("timeline") is not None,
                "reviewable": _is_reviewable(data.get("game") or {}), "tlTried": float(data.get("tlTried") or 0),
                "created": (data.get("game") or {}).get("gameCreation") or 0}
    _index[name] = (mtime, info)
    return info


def _prune_cache():
    """Keeps the newest CACHE_LIMIT games (by when they were played)."""
    try:
        names = [n for n in os.listdir(CACHE_DIR) if n.endswith(".json")]
    except OSError:
        return
    if len(names) <= CACHE_LIMIT:
        return
    names.sort(key=lambda n: (_info(n) or {}).get("created") or 0)
    for name in names[:-CACHE_LIMIT]:
        try:
            os.remove(os.path.join(CACHE_DIR, name))
        except OSError:
            pass
        _index.pop(name, None)


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


def _has_armor(tl):
    return any("armor" in pf for f in (tl or {}).get("frames") or [] for pf in (f.get("participantFrames") or {}).values())


def fill_from_riot(data):
    """The client's timeline for ranked/normal games has no item purchases, skill-ups or champion stats.
    Asks the site, which gets them from Riot's match API, and merges them in. Returns True if it changed anything."""
    tl, game = data.get("timeline"), data.get("game") or {}
    if not tl or not _cfg.get("site_url"):
        return False
    need_events, need_armor = not _has_purchases(tl), not _has_armor(tl)
    need_levels = not any(e.get("type") == "LEVEL_UP" for f in tl.get("frames") or [] for e in f.get("events") or [])
    need_pings = "pings" not in data
    # trading data: health, resource and damage totals per minute ("st") + cast counts; not in the client's timeline
    need_stats = not any("st" in pf for f in (tl.get("frames") or [])[1:3] for pf in (f.get("participantFrames") or {}).values())
    if not need_events and not need_armor and not need_levels and not need_pings and not need_stats:
        return False
    # "fillTried3": attempts made before the site sent trading data don't count.
    if time.time() - float(data.get("fillTried3") or 0) < 600:
        return False
    data["fillTried3"] = time.time()
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
    if extra.get("pings"):   # ping counts per player, keyed by the client's participant numbers
        data["pings"] = {str(pid): extra["pings"][pu] for pu, pid in by_puuid.items() if pu in extra["pings"]}
    if extra.get("casts"):   # [Q, W, E, R, summoner 1, summoner 2] casts over the whole game, by client participant number
        data["casts"] = {str(pid): extra["casts"][pu] for pu, pid in by_puuid.items() if pu in extra["casts"]}
    for i, f in enumerate(extra.get("frames") or []):
        if i < len(frames):
            for pid, st in (f.get("stats") or {}).items():
                pf = (frames[i].get("participantFrames") or {}).get(str(pid_map.get(int(pid), int(pid))))
                if pf is not None and st and st[0] is not None:
                    pf["st"] = st
            for pid, armor in (f.get("armor") or {}).items():
                pf = (frames[i].get("participantFrames") or {}).get(str(pid_map.get(int(pid), int(pid))))
                if pf is not None and armor is not None:
                    pf["armor"] = armor
        for e in f.get("events") or []:
            if not (need_levels if e.get("type") == "LEVEL_UP" else need_events):
                continue   # only the kinds this game is missing
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


def _client_patch(cfg):
    """The patch League is on now ("16.22"), to tell which replays can still be played. None if unknown."""
    try:
        lcu = _lcu(cfg)
        v = str(lcu.get("/lol-patch/v1/game-version") or "") if lcu else ""
        m = re.match(r"^(\d+\.\d+)\.", v)
        return m.group(1) if m else None
    except Exception:
        return None


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
            "summary": _summarize(game, me_puuid), "me": me_puuid, "tlTried": time.time()}
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
        cached = _info("%s.json" % int(s["gameId"]))
        # Already saved; a game the client had no timeline for is retried at most every 10 minutes.
        if cached and (cached["hasTimeline"] or time.time() - cached["tlTried"] < 600):
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
        info = _info(n)
        if not info or not info["summary"] or not info["reviewable"]:
            continue
        if me_puuid and info["me"] != me_puuid:
            continue
        out.append(dict(info["summary"], hasTimeline=info["hasTimeline"]))
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


def _replay_meta(lcu, game_id):
    """What League knows about this game's replay. For a game the client hasn't shown in match history yet
    it knows nothing (404) until it's asked to look, so ask, the way the match history page does."""
    path = "/lol-replays/v1/metadata/%s" % game_id
    try:
        return lcu.get(path) or {}
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    game = (_read_cache(game_id) or {}).get("game") or {}
    body = {"gameVersion": game.get("gameVersion") or "", "gameType": game.get("gameType") or "MATCHED_GAME",
            "queueId": _num(game.get("queueId")),
            "gameEnd": _num(game.get("gameCreation")) + _num(game.get("gameDuration")) * 1000}
    try:
        _lcu_post(lcu, path + "/create", body)
    except Exception as e:
        core.log.info("Replay metadata create for %s failed: %s", game_id, e)
    for _ in range(5):
        time.sleep(1)
        try:
            return lcu.get(path) or {}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    return {}


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

        meta = _replay_meta(lcu, game_id)
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
                meta = _replay_meta(lcu, game_id)
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
        try:
            _lcu_post(lcu, "/lol-replays/v1/rofls/%s/watch" % game_id, {"componentType": "replay-button_match-history"})
        except urllib.error.HTTPError as e:
            core.log.info("Replay watch request for %s: HTTP %s", game_id, e.code)
            return _status("error", "League isn't ready to play this replay yet. Open the game once in League's match history "
                                    "(Profile > Match History), then click Watch again.")

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


def benchmark(cfg, name, folder="benchmarks"):
    """High-elo numbers (or expert matchup notes) from the site, cached for 30 minutes."""
    name = folder + "/" + name
    hit = _bench.get(name)
    if hit and time.time() - hit[0] < (600 if hit[1].get("missing") else 1800):
        return hit[1]
    data = {"missing": True}
    try:
        url = cfg["site_url"].rstrip("/") + "/%s.json" % name
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
            if url.path == "/api/app-version":      # lets an open page notice that the app updated
                return self._send(200, {"version": core.VERSION})
            if url.path == "/api/games":
                me, err = refresh(cfg)
                if me:
                    me_cache["me"] = me
                me = me_cache["me"]
                games = list_games(me.get("puuid") if me else None)
                return self._send(200, {"me": me, "note": err, "games": games, "patch": _client_patch(cfg),
                                        "replayApi": replay_api_enabled(cfg)})
            m = re.match(r"^/api/game/(\d+)$", url.path)
            if m:
                me = me_cache["me"] or {}
                data = _read_cache(m.group(1)) or fetch_game(_lcu(cfg), m.group(1), me.get("puuid"))
                if not data:
                    return self._send(404, {"error": "game not found"})
                if fill_from_riot(data):
                    _write_cache(m.group(1), data)
                return self._send(200, dict(data, roles=roles(data["game"])))
            m = re.match(r"^/api/benchmark/([A-Za-z]+-(?:TOP|JUNGLE|MID|BOT|SUPPORT))$", url.path)
            if m:
                return self._send(200, benchmark(cfg, m.group(1)))
            m = re.match(r"^/api/notes/([A-Za-z]+|index)$", url.path)   # expert matchup sheets
            if m:
                return self._send(200, benchmark(cfg, m.group(1), "matchups"))
            if url.path == "/api/replay":
                with _lock:
                    return self._send(200, dict(_replay))
            if url.path == "/api/benchmark-index":   # champion -> role -> expert games, for the matchup guide
                import champselect
                return self._send(200, champselect.role_index(cfg))
            if url.path == "/api/champselect":
                import champselect
                return self._send(200, champselect.state(cfg))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._allowed():
                return self._send(403, {"error": "forbidden"})
            m = re.match(r"^/api/champselect/(runes|spells|itemset)$", url.path)
            if m:
                import champselect
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    {"runes": champselect.set_runes, "spells": champselect.set_spells, "itemset": champselect.set_item_set}[m.group(1)](cfg, body)
                    return self._send(200, {"ok": True})
                except Exception as e:
                    core.log.info("Champ select %s failed: %s", m.group(1), e)
                    return self._send(409, {"error": str(e)})
            m = re.match(r"^/api/replay/(\d+)$", url.path)
            if m:
                try:
                    t = max(0.0, float(parse_qs(url.query).get("t", ["0"])[0]))
                except ValueError:
                    return self._send(400, {"error": "bad time"})
                with _lock:
                    busy = _replay["state"] == "working" and time.time() - _replay["at"] < 200
                if busy:
                    return self._send(409, {"error": "A replay is already being opened."})
                _status("working", "Opening the replay...", game=m.group(1))
                threading.Thread(target=_open_replay, args=(cfg, m.group(1), t), daemon=True).start()
                return self._send(202, {"ok": True})
            m = re.match(r"^/api/overlay/(\d+)$", url.path)
            if m:
                # The caption bar over the replay. The page sends the moments it found for this game.
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    moments = [{"start": float(x["start"]), "end": float(x["end"]), "title": str(x.get("title") or "")[:160],
                                "text": str(x.get("text") or "")[:400], "turning": bool(x.get("turning")), "good": bool(x.get("good"))}
                               for x in (body.get("moments") or [])[:20]]
                    import overlay
                    overlay.show(m.group(1), body.get("duration"), moments, _playback, os.path.join(core.HERE, "overlay-pos.json"))
                    return self._send(200, {"ok": True})
                except Exception as e:
                    core.log.info("Overlay failed: %s", e)
                    return self._send(500, {"error": str(e)})
            if url.path == "/api/open":
                # Links (YouTube) open in the user's default browser, not in this Edge app window.
                link = parse_qs(url.query).get("url", [""])[0]
                guides = {m.get("url") for m in benchmark(cfg, "index", "matchups").values() if isinstance(m, dict)}
                if not (re.match(r"^https://(www\.)?youtube\.com/", link) or link in guides):
                    return self._send(400, {"error": "not allowed"})   # only YouTube and the expert guides we list
                import webbrowser
                webbrowser.open(link)
                return self._send(200, {"ok": True})
            if url.path == "/api/replay-setup":
                try:
                    enable_replay_api(cfg)
                    return self._send(200, {"ok": True, "replayApi": replay_api_enabled(cfg)})
                except Exception as e:
                    return self._send(500, {"error": str(e)})
            return self._send(404, {"error": "not found"})

    return Handler


def _page_key():
    """Same key across restarts and updates, so a review window left open keeps working."""
    try:
        with open(KEY_PATH, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if len(key) >= 20:
            return key
    except OSError:
        pass
    key = secrets.token_urlsafe(18)
    try:
        with open(KEY_PATH, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass
    return key


def start(cfg, port=0):
    """Starts the page in a background thread. Returns its address (with the access key)."""
    _cfg.update(cfg)
    token = _page_key()
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


def open_small(url, w=470, h=860):
    """A narrow app window on the right of the screen, for the champ select helper."""
    import subprocess
    if sys.platform == "win32":
        try:
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
        except Exception:
            sw = 1920
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env)
            for exe in ([os.path.join(root, r"Microsoft\Edge\Application\msedge.exe"), os.path.join(root, r"Google\Chrome\Application\chrome.exe")] if root else []):
                if os.path.exists(exe):
                    try:
                        subprocess.Popen([exe, "--app=" + url, "--window-size=%d,%d" % (w, h), "--window-position=%d,%d" % (max(0, sw - w - 20), 60)], close_fds=True)
                        return
                    except OSError:
                        pass
    open_window(url)


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

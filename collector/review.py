"""
Game review (test version).

A small page, served only to this computer, that reviews your recent
Summoner's Rift games (ranked, normals, quickplay and full 5v5 customs): your lane gold
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

import bisect
import json
import math
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
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

QUEUES = {0: "Custom", 420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal Draft", 430: "Normal Blind",
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
        # Customs count when they're a full 5v5. The history list only names you, so the count is checked
        # once the whole game has been read.
        n = len(summary.get("participants") or [])
        if n > 1 and n != 10:
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
        if data.get("summary") and data["summary"].get("v") != SUMMARY_V and data.get("game"):
            try:
                data["summary"] = _summarize(data["game"], data.get("me")) or data["summary"]
            except Exception as e:
                core.log.info("Review: couldn't re-summarise %s: %s", name, e)
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
    players, tags = _scoreboard(game, idents, me.get("participantId"))
    return {
        "id": game.get("gameId"), "created": game.get("gameCreation"), "duration": game.get("gameDuration"),
        "queue": QUEUES.get(_num(game.get("queueId")), "Queue %s" % game.get("queueId")),
        "version": game.get("gameVersion"),
        "champion": me.get("championId"), "role": rl.get(me["participantId"], ""),
        "opponent": opp.get("championId") if opp else None,
        "win": bool(st.get("win")), "kills": st.get("kills"), "deaths": st.get("deaths"), "assists": st.get("assists"),
        "cs": _num(st.get("totalMinionsKilled")) + _num(st.get("neutralMinionsKilled")),
        "players": players, "tags": tags, "pid": me.get("participantId"), "v": SUMMARY_V,
    }


SUMMARY_V = 3   # bump when the summary gains fields, so cached games are summarised again


def _scoreboard(game, idents, me_pid):
    """All ten players with a 0-10 score (the custy site's MVP formula), placed 1st to 10th. MVP = best on the
    winning team, ACE = best on the losing team. Also your tags for the match list."""
    parts = game.get("participants") or []
    minutes = max(1.0, _num(game.get("gameDuration")) / 60.0)
    rows = []
    for p in parts:
        st = p.get("stats") or {}
        rows.append({"pid": p.get("participantId"), "champ": p.get("championId"), "team": _num(p.get("teamId")),
                     "name": (idents.get(p.get("participantId")) or {}).get("gameName") or (idents.get(p.get("participantId")) or {}).get("summonerName") or "",
                     "tag": (idents.get(p.get("participantId")) or {}).get("tagLine") or "",
                     "k": _num(st.get("kills")), "d": _num(st.get("deaths")), "a": _num(st.get("assists")),
                     "dmg": _num(st.get("totalDamageDealtToChampions")), "gold": _num(st.get("goldEarned")),
                     "cs": _num(st.get("totalMinionsKilled")) + _num(st.get("neutralMinionsKilled")),
                     "vision": _num(st.get("visionScore")), "win": bool(st.get("win")),
                     "multi": _num(st.get("largestMultiKill")), "fb": bool(st.get("firstBloodKill"))})
    for r in rows:
        team = [x for x in rows if x["team"] == r["team"]]
        kills = max(1, sum(x["k"] for x in team)); dmg = max(1, sum(x["dmg"] for x in team))
        ratio = min((r["k"] + r["a"]) / max(1, r["d"]), 12) / 12.0
        raw = 3.2 * ratio + 2.6 * (r["k"] + r["a"]) / kills + 2.6 * (r["dmg"] / dmg) * 2.5 \
            + 0.8 * min(r["vision"] / minutes / 2.5, 1) + (0.8 if r["win"] else 0)
        r["score"] = round(max(0.0, min(10.0, raw)), 1)
    order = sorted(rows, key=lambda r: -r["score"])
    for n, r in enumerate(order):
        r["rank"] = n + 1
    mvp = next((r for r in order if r["win"]), None)
    ace = next((r for r in order if not r["win"]), None)
    for r in rows:
        r["badge"] = "MVP" if r is mvp else "ACE" if r is ace else ""
    tags = []
    me = next((r for r in rows if r["pid"] == me_pid), None)
    if me:
        if me["badge"]:
            tags.append(me["badge"])
        if me["multi"] >= 2:
            tags.append({2: "Double kill", 3: "Triple kill", 4: "Quadra kill"}.get(me["multi"], "Penta kill"))
        if me["win"] and me["d"] == 0:
            tags.append("Unstoppable")
        if me["fb"]:
            tags.append("First blood")
    for r in rows:
        for k in ("vision", "multi", "fb"):
            r.pop(k, None)
    return rows, tags


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
    if game.get("gameType") == "CUSTOM_GAME":   # Riot's match API doesn't have custom games
        return False
    need_events, need_armor = not _has_purchases(tl), not _has_armor(tl)
    need_levels = not any(e.get("type") == "LEVEL_UP" for f in tl.get("frames") or [] for e in f.get("events") or [])
    need_pings = not data.get("pings") or not data.get("casts")   # empty when puuids failed to match (before 1.10.22)
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
    # Riot's participant numbers -> the client's. Riot's API encrypts puuids for the site's key, so they never
    # match the client's; match by champion and team (unique in a Summoner's Rift game), then by number.
    by_champ = {(_num(p.get("championId")), _num(p.get("teamId"))): p.get("participantId") for p in game.get("participants") or []}
    client_pids = {p.get("participantId") for p in game.get("participants") or []}
    who = extra.get("who") or {}
    by_puuid = {(i.get("player") or {}).get("puuid"): i.get("participantId") for i in game.get("participantIdentities") or []}
    for pu, w in who.items():
        pid = by_champ.get((_num(w[0]), _num(w[1])))
        if pid is None and w[2] in client_pids:
            pid = w[2]
        if pid is not None:
            by_puuid[pu] = pid
    for p in extra.get("participants") or []:   # older site without "who": Riot and the client number players the same way
        if p["puuid"] not in by_puuid and p["participantId"] in client_pids:
            by_puuid[p["puuid"]] = p["participantId"]
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


# --------------------------------------------------------------------------
# Lane trades, decoded from the game's replay file (replay_trades.py)
# --------------------------------------------------------------------------

TRADES_DIR = os.path.join(CACHE_DIR, "trades")
TRADES_VERSION = 14          # bump when the trade data changes shape, so old results are rebuilt
_replay_dir_cache = {}
_trades_dl = {}             # game id -> {"state", "message", "at"}


def replay_dir(cfg):
    """Where League saves replays: the client's setting, else the usual Documents folders."""
    hit = _replay_dir_cache.get("dir")
    if hit and os.path.isdir(hit):
        return hit
    try:
        lcu = _lcu(cfg)
        p = lcu.get("/lol-replays/v1/rofls/path") if lcu else None
        if isinstance(p, str) and os.path.isdir(p):
            _replay_dir_cache["dir"] = p
            return p
    except Exception:
        pass
    home = os.path.expanduser("~")
    for d in (os.path.join(home, "Documents", "League of Legends", "Replays"),
              os.path.join(home, "OneDrive", "Documents", "League of Legends", "Replays")):
        if os.path.isdir(d):
            _replay_dir_cache["dir"] = d
            return d
    return None


def _rofl_path(cfg, game):
    d = replay_dir(cfg)
    if not d:
        return None
    name = "%s-%s.rofl" % (game.get("platformId") or "NA1", game.get("gameId"))
    p = os.path.join(d, name)
    return p if os.path.exists(p) else None


def _lane_pair(data):
    """(my participant, my lane opponent) in the client's numbering."""
    game = data.get("game") or {}
    idents = {i.get("participantId"): (i.get("player") or {}) for i in game.get("participantIdentities") or []}
    me = next((p for p in game.get("participants") or [] if idents.get(p["participantId"], {}).get("puuid") == data.get("me")), None)
    if not me:
        return None, None, idents
    rl = roles(game)
    opp = next((p for p in game["participants"] if _num(p.get("teamId")) != _num(me.get("teamId"))
                and rl.get(p["participantId"]) == rl.get(me["participantId"])), None)
    return me, opp, idents


def _hp_anchors(data, slot_of_pid):
    """Everyone's health at each minute mark from the saved timeline, keyed by replay slot."""
    out = {}
    for f in data["timeline"].get("frames") or []:
        t = (f.get("timestamp") or 0) / 1000.0
        for pid, pf in (f.get("participantFrames") or {}).items():
            k = slot_of_pid(int(pid))
            st = (pf or {}).get("st")
            if k is not None and st and st[0] is not None and st[1]:
                out.setdefault(k, []).append((t, st[0], st[1]))
    return out


def _kf_anchors(path, have):
    """Health anchors read from the replay's own keyframes, for anyone the saved timeline has no health for
    (custom games: Riot serves no timeline for them)."""
    import replay_trades as RT
    if len([v for v in have.values() if v]) >= 10:
        return have
    try:
        kf = RT.keyframe_health(path)
    except Exception as e:
        core.log.info("Keyframe health: couldn't read %s: %s", path, e)
        return have
    out = dict(have)
    for k, ser in kf.items():
        if not out.get(k):
            out[k] = [(t, hp, mx) for t, hp, mx in ser if mx > 0]
    return out


def _deaths_by_slot(data, slot_of_pid):
    out = {}
    for f in data["timeline"].get("frames") or []:
        for e in f.get("events") or []:
            if e.get("type") == "CHAMPION_KILL":
                k = slot_of_pid(int(e.get("victimId") or 0))
                if k is not None:
                    out.setdefault(k, []).append(e["timestamp"] / 1000.0)
    return out


def trades_for(cfg, game_id):
    """The lane trades for one of your games, decoded from its replay (cached). Returns a dict for the page."""
    import replay_trades as RT
    data = _read_cache(game_id)
    if not data or not data.get("timeline"):
        return {"error": "This game isn't saved yet."}
    game = data["game"]
    os.makedirs(TRADES_DIR, exist_ok=True)
    cpath = os.path.join(TRADES_DIR, "%s.json" % int(game_id))
    try:
        with open(cpath, "r", encoding="utf-8") as f:
            hit = json.load(f)
        if hit.get("v") == TRADES_VERSION:
            return hit
    except (OSError, ValueError):
        pass
    if RT.zstandard is None:
        return {"error": "Reading replays needs the zstandard package: pip install zstandard"}
    path = _rofl_path(cfg, game)
    if not path:
        st = _trades_dl.get(str(game_id)) or {}
        return {"missing": True, "download": st.get("state"), "message": st.get("message", ""),
                "patch": ".".join(str(game.get("gameVersion") or "").split(".")[:2])}
    me, opp, idents = _lane_pair(data)
    if not me or not opp:
        return {"error": "Couldn't tell who your lane opponent was in this game."}
    try:
        _v, stats, _c = RT.read_rofl(path)
    except Exception as e:
        core.log.info("Trades: couldn't read %s: %s", path, e)
        return {"error": "Couldn't read this game's replay file."}
    def slot(p):
        pl = idents.get(p["participantId"], {})
        return RT.slot_of(stats, puuid=pl.get("puuid"), name=pl.get("gameName"))
    i, j = slot(me), slot(opp)
    if i is None or j is None:
        return {"error": "The replay's players don't match this game."}
    frames = []
    for f in data["timeline"].get("frames") or []:
        pf = f.get("participantFrames") or {}
        a, b = (pf.get(str(me["participantId"])) or {}).get("st"), (pf.get(str(opp["participantId"])) or {}).get("st")
        frames.append({"t": (f.get("timestamp") or 0) / 1000.0,
                       "me": [a[0], a[1]] if a and a[0] is not None and a[1] else None,
                       "opp": [b[0], b[1]] if b and b[0] is not None and b[1] else None})
    kills = {"me": [], "opp": []}
    for f in data["timeline"].get("frames") or []:
        for e in f.get("events") or []:
            if e.get("type") == "CHAMPION_KILL":
                if e.get("victimId") == me["participantId"]:
                    kills["me"].append(e["timestamp"] / 1000.0)
                elif e.get("victimId") == opp["participantId"]:
                    kills["opp"].append(e["timestamp"] / 1000.0)
    pslot = {p["participantId"]: slot(p) for p in game.get("participants") or []}
    hpa = _hp_anchors(data, pslot.get)
    if not any(fr["me"] for fr in frames) or not any(fr["opp"] for fr in frames):
        # No health in the timeline (custom games): use the health snapshots inside the replay itself
        hpa = _kf_anchors(path, hpa)
        mine, theirs = hpa.get(i) or [], hpa.get(j) or []
        frames = [{"t": t, "me": [hp, mx], "opp": next(([h2, m2] for t2, h2, m2 in theirs if abs(t2 - t) < 2), None)}
                  for t, hp, mx in mine]
    if not any(fr["me"] for fr in frames):
        return {"error": "Still waiting for this game's health data from the site. Try again in a minute."}
    try:
        rl = roles(game)
        # Bot lane is two against two: both supports are part of the lane, not a gank
        lane_roles = {"BOT", "SUPPORT"} if rl.get(me["participantId"]) in ("BOT", "SUPPORT") else {rl.get(me["participantId"])}
        mates = {pslot[pid] for pid, r in rl.items() if r in lane_roles and pslot.get(pid) is not None} - {i, j}
        # 16.23+: abilities the replay names by an id we haven't mapped get their slot from Riot's cast counts
        rc = {pslot[int(pid)]: c[:4] for pid, c in (data.get("casts") or {}).items() if pslot.get(int(pid)) is not None}
        fs = {}
        for f in data["timeline"].get("frames") or []:
            for e in f.get("events") or []:
                if e.get("type") == "SKILL_LEVEL_UP" and pslot.get(e.get("participantId")) is not None:
                    fs.setdefault(pslot[e["participantId"]], {}).setdefault(e.get("skillSlot"), e["timestamp"] / 1000.0)
        out = RT.lane_trades(path, i, j, frames, kills, hpa=_kf_anchors(path, hpa), deaths_all=_deaths_by_slot(data, pslot.get),
                             lane_mates=mates, riot_casts=rc, first_skill=fs)
    except Exception as e:
        core.log.exception("Trades: decoding %s failed", path)
        return {"error": "Couldn't decode this replay: %s" % e}
    if out.get("unsupported"):
        return {"error": "Trades can't be read from patch %s replays yet." % out["unsupported"]}
    try:   # the coach's read of each trade, level race and risky death (general rules; see coach_reads.py)
        import coach_reads
        out["coach"] = coach_reads.analyze(path, i, j, me, opp, pslot.get, data["timeline"], out)
    except Exception:
        core.log.exception("Trades: coach reads failed for %s", path)
    out["v"] = TRADES_VERSION
    out["role"] = roles(game).get(me["participantId"], "")
    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


DEATHS_VERSION = 10   # 6: map pings in playbacks; 7: everyone's health


def deaths_for(cfg, game_id):
    """Gank and caught-out checks for your deaths in one of your games, from its replay (cached)."""
    import replay_trades as RT
    import replay_deaths as RD
    data = _read_cache(game_id)
    if not data or not data.get("timeline"):
        return {"error": "This game isn't saved yet."}
    game = data["game"]
    d = os.path.join(CACHE_DIR, "deaths")
    os.makedirs(d, exist_ok=True)
    cpath = os.path.join(d, "%s.json" % int(game_id))
    try:
        with open(cpath, "r", encoding="utf-8") as f:
            hit = json.load(f)
        if hit.get("v") == DEATHS_VERSION:
            return hit
    except (OSError, ValueError):
        pass
    if RT.zstandard is None:
        return {"error": "Reading replays needs the zstandard package: pip install zstandard"}
    path = _rofl_path(cfg, game)
    if not path:
        st = _trades_dl.get(str(game_id)) or {}
        return {"missing": True, "download": st.get("state"), "message": st.get("message", ""),
                "patch": ".".join(str(game.get("gameVersion") or "").split(".")[:2])}
    me, _opp, idents = _lane_pair(data)
    if not me:
        return {"error": "Couldn't find you in this game."}
    try:
        _v, stats, _c = RT.read_rofl(path)
    except Exception as e:
        core.log.info("Deaths: couldn't read %s: %s", path, e)
        return {"error": "Couldn't read this game's replay file."}
    slots = {}
    for p in game.get("participants") or []:
        pl = idents.get(p["participantId"], {})
        k = RT.slot_of(stats, puuid=pl.get("puuid"), name=pl.get("gameName"))
        if k is not None:
            slots[p["participantId"]] = k
    if me["participantId"] not in slots or len(slots) < 10:
        return {"error": "The replay's players don't match this game."}
    rl = roles(game)
    conv = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MID": "MIDDLE", "BOT": "BOTTOM", "SUPPORT": "UTILITY"}
    rmap = {slots[pid]: conv.get(r, "") for pid, r in rl.items() if pid in slots}
    kills, towers = [], []
    for f in data["timeline"].get("frames") or []:
        for e in f.get("events") or []:
            if e.get("type") == "CHAMPION_KILL" and e.get("victimId") in slots:
                pos = e.get("position") or {}
                kills.append({"t": e["timestamp"] / 1000.0, "victim": slots[e["victimId"]], "killer": slots.get(e.get("killerId"), -1),
                              "assists": [slots[a] for a in e.get("assistingParticipantIds") or [] if a in slots],
                              "x": pos.get("x", 0), "z": pos.get("y", 0)})
            elif e.get("type") == "BUILDING_KILL" and e.get("buildingType") == "TOWER_BUILDING":
                pos = e.get("position") or {}
                towers.append((e["timestamp"] / 1000.0, pos.get("x", 0), pos.get("y", 0)))
    try:
        prev = []
        out = {"deaths": RD.death_reviews(path, slots[me["participantId"]], rmap, kills, towers, previews=prev,
                                           hpa=_kf_anchors(path, _hp_anchors(data, slots.get))), "previews": prev}
    except Exception as e:
        core.log.exception("Deaths: decoding %s failed", path)
        return {"error": "Couldn't decode this replay: %s" % e}
    out["champs"] = [[p.get("SKIN"), int(p.get("TEAM") or 0)] for p in stats]
    out["v"] = DEATHS_VERSION
    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


def _download_for_trades(cfg, game_id):
    """Asks League to download this game's replay (no playback), so its trades can be read."""
    st = _trades_dl[str(game_id)] = {"state": "working", "message": "Downloading the replay...", "at": time.time()}
    try:
        lcu = _lcu(cfg)
        if lcu is None:
            st.update(state="error", message="Open League first: it downloads the replay.")
            return
        meta = _replay_meta(lcu, game_id)
        if meta.get("state") in ("incompatible", "unsupported"):
            st.update(state="error", message="This replay is from an older patch, so League can't download it.")
            return
        if meta.get("state") != "watch":
            try:
                _lcu_post(lcu, "/lol-replays/v1/rofls/%s/download" % game_id, {"componentType": "replay-button_match-history"})
            except urllib.error.HTTPError as e:
                core.log.info("Trades: replay download request HTTP %s", e.code)
            for _ in range(120):
                time.sleep(1)
                meta = _replay_meta(lcu, game_id)
                if meta.get("state") == "watch":
                    break
                if meta.get("state") in ("incompatible", "unsupported", "lost", "missingOrExpired", "error"):
                    st.update(state="error", message="League couldn't get this replay (%s)." % meta.get("state"))
                    return
                if meta.get("downloadProgress"):
                    st["message"] = "Downloading the replay... %s%%" % meta["downloadProgress"]
            else:
                st.update(state="error", message="The download didn't finish. Try again in a minute.")
                return
        st.update(state="done", message="Downloaded.")
    except Exception as e:
        core.log.info("Trades: download failed: %s", e)
        st.update(state="error", message="The download failed: %s" % e)


# Expert replays: League downloads other players' replays too (its own region and patch only), at most 10 an
# hour per account. We use 8, leaving 2 for the player's own replays, and never download while a game is on.
XP_PER_HOUR = 8          # default; each player can pick 1-10 (League's cap is 10 an hour per account)
_xp_lock = threading.Lock()


def xp_limit():
    try:
        return max(1, min(10, int(xpa_settings().get("per_hour", XP_PER_HOUR))))
    except Exception:
        return XP_PER_HOUR
XP_FILE = os.path.join(core.HERE, "expert-downloads.json")
_xp = {"state": "idle"}


def _xp_times():
    try:
        return [t for t in json.load(open(XP_FILE)) if time.time() - t < 3600]
    except Exception:
        return []


def _xp_have(cfg, game_id):
    d = replay_dir(cfg)
    try:
        return d and any(f.endswith(".rofl") and ("-%s." % game_id) in f for f in os.listdir(d))
    except OSError:
        return False


def expert_status(cfg, name):
    data = benchmark(cfg, name, folder="experts")
    games = [] if data.get("missing") else data.get("games", [])
    out = dict(_xp) if _xp.get("set") == name else {"state": "idle"}
    out.update(set=name, total=len(games), have=sum(1 for g in games if _xp_have(cfg, g["gameId"])),
               patch=data.get("patch"), hourLeft=max(0, xp_limit() - len(_xp_times())), perHour=xp_limit())
    return out


def _xp_download(lcu, gid, g):
    """Asks League to download someone else's replay (counts against the hourly limit either way). Returns League's
    final state for it: "watch" means it's on disk."""
    with _xp_lock:
        json.dump(_xp_times() + [time.time()], open(XP_FILE, "w"))
    meta = _replay_meta(lcu, gid, g)
    core.log.info("Expert replay %s (%s): metadata %s", gid, g.get("gameVersion"), meta)
    if meta.get("state") != "watch":
        try:
            r = _lcu_post(lcu, "/lol-replays/v1/rofls/%s/download" % gid, {"componentType": "replay-button_match-history"})
            core.log.info("Expert replay %s: download request -> %s", gid, r)
        except urllib.error.HTTPError as e:
            core.log.info("Expert replay %s: download request HTTP %s %s", gid, e.code, e.read()[:300])
        for _ in range(180):
            time.sleep(1)
            meta = _replay_meta(lcu, gid, g)
            if meta.get("state") in ("watch", "incompatible", "unsupported", "lost", "missingOrExpired", "error"):
                break
        core.log.info("Expert replay %s: final metadata %s", gid, meta)
    return meta.get("state")


def expert_fetch(cfg, name):
    """Downloads every replay in public/experts/<name>.json that isn't in the Replays folder yet, paced."""
    if _xp.get("state") == "working":
        return
    _xp.clear(); _xp.update(state="working", set=name, failed=[], message="Starting...")
    try:
        data = benchmark(cfg, name, folder="experts")
        games = [] if data.get("missing") else data.get("games", [])
        for g in games:
            gid = g["gameId"]
            if _xp.get("stop"):
                break
            if _xp_have(cfg, gid):
                continue
            while not _xp.get("stop"):
                lcu = _lcu(cfg)
                phase = lcu.get("/lol-gameflow/v1/gameflow-phase") if lcu else None
                times = _xp_times()
                if lcu is None:
                    _xp["message"] = "Waiting for League to open."
                elif phase in ("ChampSelect", "InProgress", "Reconnect", "GameStart", "WaitingForStats"):
                    _xp["message"] = "Paused while you play."
                elif len(times) >= xp_limit():
                    _xp["message"] = "Hourly limit reached (%d an hour). Next one in about %d min." % (
                        xp_limit(), max(1, (min(times) + 3600 - time.time()) // 60))
                    _xp["next_at"] = min(times) + 3600
                else:
                    break
                time.sleep(20)
            if _xp.get("stop"):
                break
            _xp["message"] = "Downloading game %s..." % gid
            state = _xp_download(lcu, gid, g)
            if state != "watch" and not _xp_have(cfg, gid):
                _xp["failed"].append({"gameId": gid, "why": state or "no answer"})
        _xp.update(state="done", message="Stopped." if _xp.get("stop") else "All downloaded.")
    except Exception as e:
        core.log.info("Expert replays: %s", e)
        _xp.update(state="error", message=str(e))


# Always-on expert downloads: 8 high-elo replays an hour by default (the player can pick 1-10), every hour, on every PC running the app, with nothing to
# start. The site picks the games (Challenger first, then Grandmaster, then Master; each game goes to one PC). Each
# replay is boiled down to a small data file (positions, hits, casts, levels; about 1 MB) and the replay is deleted
# straight away; the file is uploaded to the site's storage and then deleted too (if storage isn't reachable, only
# the small file waits). Never runs while you're in champ select or a game.
XPA_SETTINGS = os.path.join(core.HERE, "expert-auto.json")
XPA_LOG = os.path.join(core.HERE, "expert-auto-log.json")
XPA_DATA = os.path.join(core.HERE, "expert-data")
_xpa = {"state": "starting", "message": "Starting..."}


def xpa_settings():
    try:
        s = json.load(open(XPA_SETTINGS))
    except Exception:
        s = {}
    s.setdefault("on", True)
    s.setdefault("open_league", True)   # open League (when you're away) if it's closed, so downloads keep going
    s.setdefault("noticed", False)      # the one-time "this is running" notice was seen
    s.setdefault("per_hour", XP_PER_HOUR)
    return s


def xpa_save(**kw):
    s = xpa_settings()
    s.update(kw)
    with open(XPA_SETTINGS, "w") as f:
        json.dump(s, f)
    return s


def _xpa_log():
    try:
        return json.load(open(XPA_LOG))
    except Exception:
        return []


def _xpa_log_add(entry):
    with _xp_lock:
        log = _xpa_log() + [entry]
        with open(XPA_LOG, "w") as f:
            json.dump(log[-20000:], f)


def _idle_seconds():
    """How long since you last touched the mouse or keyboard."""
    if sys.platform != "win32":
        return 0
    import ctypes

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LII()
    li.cbSize = ctypes.sizeof(LII)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def _open_league():
    """Starts League through the Riot Client (signs in by itself if you ticked "Stay signed in")."""
    paths = []
    try:
        inst = json.load(open(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Riot Games", "RiotClientInstalls.json")))
        paths += [inst.get(k) for k in ("rc_default", "rc_live") if inst.get(k)]
    except Exception:
        pass
    paths.append(r"C:\Riot Games\Riot Client\RiotClientServices.exe")
    for p in paths:
        if p and os.path.exists(p):
            subprocess.Popen([p, "--launch-product=league_of_legends", "--launch-patchline=live"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
    return False


REGION_PLATFORM = {"NA": "na1", "EUW": "euw1", "EUNE": "eun1", "KR": "kr", "BR": "br1", "LAN": "la1", "LAS": "la2",
                   "OCE": "oc1", "TR": "tr1", "RU": "ru", "JP": "jp1", "ME": "me1", "SG": "sg2", "TW": "tw2", "VN": "vn2"}


def _client_platform(lcu):
    """The Riot platform the League client is signed into (na1, euw1...). Replays can only come from there."""
    try:
        r = (lcu.get("/riotclient/region-locale") or {}).get("region", "NA")
        return REGION_PLATFORM.get(str(r).upper(), str(r).lower())
    except Exception:
        return "na1"


def _xpa_next(cfg, patch, platform="na1"):
    skip = ",".join(str(e["gameId"]) for e in _xpa_log()[-300:])
    url = "%s/api/experts/next?patch=%s&count=1&skip=%s&platform=%s" % (cfg["site_url"].rstrip("/"), patch, skip, platform)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""),
                                               "User-Agent": "custy-collector/" + core.VERSION})
    with urllib.request.urlopen(req, timeout=70) as r:
        data = json.loads(r.read())
    if data.get("note"):
        core.log.info("Expert downloads: site says %s", data["note"])
    return (data.get("games") or [None])[0], data


def _xpa_extract(cfg, gid, g):
    """Keeps the useful part of a replay (about 1 MB) so the replay itself can go later."""
    d = replay_dir(cfg)
    f = next((os.path.join(d, n) for n in os.listdir(d) if n.endswith(".rofl") and ("-%s." % gid) in n), None) if d else None
    if not f:
        return False
    import gzip
    import replay_trades as RT
    os.makedirs(XPA_DATA, exist_ok=True)
    data = RT.decode(f, until=99999)
    try:
        data["hp"] = RT.keyframe_health(f, units=True)   # every unit's health about once a minute
    except Exception:
        pass
    data["game"] = g
    with gzip.open(os.path.join(XPA_DATA, "%s.json.gz" % gid), "wt") as out:
        json.dump(data, out, default=str)
    return True


def _xpa_upload(cfg, gid, patch, platform="na1"):
    """Sends a data file to the site's storage. True once it's there (the local copy is then deleted)."""
    f = os.path.join(XPA_DATA, "%s.json.gz" % gid)
    if not os.path.exists(f):
        return False
    base = cfg["site_url"].rstrip("/")
    me = urllib.parse.quote(xpa_settings().get("me") or "")
    req = urllib.request.Request("%s/api/experts/upload?gameId=%s&patch=%s&by=%s&platform=%s" % (base, gid, patch, me, platform),
                                 headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""), "User-Agent": "custy-collector/" + core.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            url = json.loads(r.read())["url"]
    except urllib.error.HTTPError as e:
        if e.code == 503:
            _xpa["storage"] = "not set up yet"
        return False
    with open(f, "rb") as fh:
        body = fh.read()
    put = urllib.request.Request(url, data=body, method="PUT", headers={"Content-Type": "application/gzip", "Content-Length": str(len(body))})
    try:
        with urllib.request.urlopen(put, timeout=120) as r:
            ok = 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        _xpa["storage"] = "Cloudflare answered %s: %s" % (e.code, e.read()[:200].decode(errors="replace"))
        raise
    if ok:
        _xpa["storage"] = "ok"
        os.remove(f)
        try:   # tell custy.gg it arrived, so it counts for you
            done = urllib.request.Request("%s/api/experts/upload?gameId=%s&patch=%s&by=%s&done=1&platform=%s" % (base, gid, patch, me, platform),
                                          headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""), "User-Agent": "custy-collector/" + core.VERSION})
            urllib.request.urlopen(done, timeout=20).read()
        except Exception:
            pass
    return ok


def _xpa_delete_replay(cfg, gid):
    d = replay_dir(cfg)
    for n in (os.listdir(d) if d else []):
        if n.endswith(".rofl") and ("-%s." % gid) in n:
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass


def _xpa_backlog(cfg, limit=5):
    """Uploads data files that couldn't be sent earlier."""
    if _xpa.get("storage") not in (None, "ok") and time.time() - _xpa.get("storage_checked", 0) < 600:
        return
    _xpa["storage_checked"] = time.time()
    log = _xpa_log()
    by_id = {str(e["gameId"]): e for e in log}
    try:
        names = sorted(os.listdir(XPA_DATA))[:limit]
    except OSError:
        return
    sent = False
    for n in names:
        gid = n.split(".")[0]
        e = by_id.get(gid) or {}
        try:
            if _xpa_upload(cfg, gid, e.get("patch") or "0.0", e.get("platform") or "na1"):
                _xpa_delete_replay(cfg, gid)
                e["uploaded"] = sent = True
        except Exception as ex:
            core.log.info("Expert downloads: upload of %s failed: %s", gid, ex)
            break
    if sent:
        with open(XPA_LOG, "w") as f:
            json.dump(log[-20000:], f)


def _xpa_cleanup(cfg):
    """Deletes any expert replay still on disk once its data file exists (older versions kept them for a while).
    Only games from this downloader's own list; your own replays are never touched."""
    for e in _xpa_log():
        if e.get("state") == "watch" and e.get("extracted"):
            _xpa_delete_replay(cfg, e["gameId"])


def _xpa_one(cfg, lcu, g, patch, platform="na1"):
    """Download one expert replay, boil it down, delete it, upload the data. Safe to run a few at once."""
    gid = g["gameId"]
    if time.time() < _xpa.get("limited_until", 0):
        return gid, "skipped"
    state = "watch" if _xp_have(cfg, gid) else _xp_download(lcu, gid, g)
    if state == "maxLimitReached":
        # League's own limit (it isn't just 10 an hour): back off instead of spending attempts, and note how many
        # downloads worked recently so we can learn the real number
        if time.time() >= _xpa.get("limited_until", 0):
            ok = _xpa_ok_times()
            core.log.info("Expert downloads: League says its replay limit is reached. Worked in the last 1 h: %d, 6 h: %d, 24 h: %d, 48 h: %d. Pausing 1 hour.",
                          *[sum(1 for t in ok if time.time() - t < h * 3600) for h in (1, 6, 24, 48)])
        _xpa["limited_until"] = time.time() + 3600
    elif state == "watch":
        with _xp_lock:
            json.dump(_xpa_ok_times() + [time.time()], open(XPA_OK, "w"))
    entry = {"gameId": gid, "at": time.time(), "state": state, "kind": g.get("kind"), "matchup": g.get("matchup"),
             "patch": patch, "platform": platform}
    if state == "watch":
        try:
            entry["extracted"] = _xpa_extract(cfg, gid, g)
        except Exception as e:
            core.log.info("Expert downloads: couldn't read %s: %s", gid, e)
        _xpa_delete_replay(cfg, gid)   # the data file has what we need; the replay goes now
        try:
            if entry.get("extracted") and _xpa_upload(cfg, gid, patch, platform):
                entry["uploaded"] = True
        except Exception as e:
            core.log.info("Expert downloads: upload of %s failed: %s", gid, e)
    _xpa_log_add(entry)
    return gid, state


XPA_PARALLEL = 3   # replays fetched at once; League's hourly cap still applies
XPA_OK = os.path.join(core.HERE, "expert-ok.json")   # when each download worked (to learn League's real limit)


def _xpa_ok_times():
    try:
        return [t for t in json.load(open(XPA_OK)) if time.time() - t < 3 * 86400]
    except Exception:
        return []


def expert_auto(cfg, stop):
    from concurrent.futures import ThreadPoolExecutor
    opened_at = 0
    cleaned = False
    while not stop.is_set():
        wait = 10
        try:
            st = xpa_settings()
            limit = xp_limit()
            if not st["on"]:
                _xpa.update(state="off", message="Turned off.")
                wait = 60
            elif _xp.get("state") == "working":
                _xpa.update(state="waiting", message="A matchup download set is running.")
                wait = 60
            else:
                lcu = _lcu(cfg)
                phase = lcu.get("/lol-gameflow/v1/gameflow-phase") if lcu else None
                times = _xp_times()
                if not cleaned and replay_dir(cfg):
                    cleaned = True
                    _xpa_cleanup(cfg)
                if lcu and not st.get("me"):
                    try:   # your Riot ID, so custy.gg can show who sent how many
                        me = lcu.get("/lol-summoner/v1/current-summoner") or {}
                        if me.get("gameName"):
                            xpa_save(me="%s#%s" % (me["gameName"], me.get("tagLine", "")))
                    except Exception:
                        pass
                if lcu is None:
                    if st["open_league"] and time.time() - opened_at > 3 * 3600 and _idle_seconds() > 600:
                        opened_at = time.time()
                        ok = _open_league()
                        _xpa.update(state="waiting", message="Opening League so downloads can continue." if ok else "League is closed (couldn't find it to open).")
                    else:
                        _xpa.update(state="waiting", message="Waiting for League to open.")
                    wait = 8      # a cheap local check: start within seconds of League signing in
                elif phase in ("ChampSelect", "InProgress", "Reconnect", "GameStart", "WaitingForStats", "PreEndOfGame"):
                    _xpa.update(state="waiting", message="Paused while you play.")
                    wait = 15
                elif time.time() < _xpa.get("limited_until", 0):
                    nxt = _xpa["limited_until"]
                    _xpa.update(state="waiting", message="League's replay limit is reached. Trying again at %s." % time.strftime("%H:%M", time.localtime(nxt)), next_at=nxt)
                    wait = max(30, min(600, nxt - time.time() + 2))
                elif len(times) >= limit:
                    nxt = min(times) + 3600
                    _xpa_backlog(cfg)
                    _xpa.update(state="waiting", message="Hourly limit reached. Next one in about %d min." % max(1, (nxt - time.time()) // 60), next_at=nxt)
                    wait = max(5, min(120, nxt - time.time() + 2))
                else:
                    patch = _client_patch(cfg)
                    platform = _client_platform(lcu)
                    games, info = [], {}
                    probing = _xpa.get("limited_until", 0) > 0   # just came off a pause: try one first
                    for _ in range(1 if probing else min(XPA_PARALLEL, limit - len(times))):
                        g, info = _xpa_next(cfg, patch, platform) if patch else (None, {})
                        if not g:
                            break
                        games.append(g)
                    if not games:
                        busy = (info or {}).get("note") == "busy"
                        _xpa.update(state="waiting", message="Waiting for the site." if busy else (info or {}).get("note") or "No games ready yet. Trying again in 10 min.")
                        wait = 8 if busy else 600
                    else:
                        _xpa.update(state="working", message="Downloading %d high-elo game%s..." % (len(games), "s" if len(games) > 1 else ""))
                        with ThreadPoolExecutor(max_workers=len(games)) as pool:
                            done = list(pool.map(lambda g: _xpa_one(cfg, lcu, g, patch, platform), games))
                        if probing and any(s_ == "watch" for _, s_ in done):
                            _xpa["limited_until"] = 0
                            core.log.info("Expert downloads: League's limit has lifted.")
                        _xpa.update(state="ok", message="Last: %s." % ", ".join("game %s (%s)" % (gid, "saved" if s_ == "watch" else s_) for gid, s_ in done))
                        wait = 1
        except Exception as e:
            core.log.info("Expert downloads: %s", e)
            _xpa.update(state="error", message=str(e)[:200])
            wait = 120
        stop.wait(wait)


def _xpa_contributors(cfg):
    if time.time() - _xpa.get("contrib_at", 0) < 300:
        return _xpa.get("contrib")
    _xpa["contrib_at"] = time.time()
    try:
        req = urllib.request.Request(cfg["site_url"].rstrip("/") + "/api/experts/contributors",
                                     headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""), "User-Agent": "custy-collector/" + core.VERSION})
        with urllib.request.urlopen(req, timeout=15) as r:
            _xpa["contrib"] = json.loads(r.read())
    except Exception:
        pass
    return _xpa.get("contrib")


def _xpa_storage_check(cfg):
    """custy.gg tries writing a tiny file to its storage and says what happened (checked every 10 minutes)."""
    if time.time() - _xpa.get("check_at", 0) < (600 if (_xpa.get("check") or {}).get("ok") else 120):
        return _xpa.get("check")
    _xpa["check_at"] = time.time()
    try:
        req = urllib.request.Request(cfg["site_url"].rstrip("/") + "/api/experts/storage-check",
                                     headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""), "User-Agent": "custy-collector/" + core.VERSION})
        with urllib.request.urlopen(req, timeout=20) as r:
            _xpa["check"] = json.loads(r.read())
    except Exception as e:
        _xpa["check"] = {"ok": False, "why": "Couldn't reach custy.gg: %s" % e}
    if _xpa["check"].get("ok") and _xpa.get("storage") == "not set up yet":
        _xpa["storage"] = None
    return _xpa["check"]


def xpa_status(cfg):
    log = _xpa_log()
    ok = [e for e in log if e.get("state") == "watch"]
    day = time.time() - 86400
    try:
        data_mb = sum(os.path.getsize(os.path.join(XPA_DATA, n)) for n in os.listdir(XPA_DATA)) / 1e6
    except OSError:
        data_mb = 0
    return dict(_xpa, settings=xpa_settings(), total=len(ok), today=sum(1 for e in ok if e["at"] > day),
                uploaded=sum(1 for e in ok if e.get("uploaded")), contributors=_xpa_contributors(cfg), storageCheck=_xpa_storage_check(cfg),
                failedToday=sum(1 for e in log if e["at"] > day and e.get("state") != "watch"),
                matchup={k: sum(1 for e in ok if e.get("matchup") == k) for k in {e.get("matchup") for e in ok if e.get("matchup")}},
                hourLeft=max(0, xp_limit() - len(_xp_times())), dataMB=round(data_mb))


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


# --------------------------------------------------------------------------
# Rank and LP per game. Riot doesn't publish LP per game, so the app notes your rank each time it looks
# and credits the change to the ranked game played in between.
# --------------------------------------------------------------------------

LP_FILE = os.path.join(core.HERE, "review-lp.json")   # outside the game cache, which is pruned
RANKED = {"RANKED_SOLO_5x5": "Ranked Solo/Duo", "RANKED_FLEX_SR": "Ranked Flex", "RANKED_PREMADE_5x5": "Ranked 5s"}
_lp_logged = {}
_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
_DIVS = {"IV": 0, "III": 1, "II": 2, "I": 3}


def _ladder(r):
    """Rank as one number, so a promotion or demotion still gives a point change. None when unranked."""
    tier = str(r.get("tier") or "").upper()
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return 2800 + _num(r.get("lp"))
    if tier not in _TIERS:
        return None
    return _TIERS.index(tier) * 400 + _DIVS.get(str(r.get("division") or "").upper(), 0) * 100 + _num(r.get("lp"))


def _lp_load():
    try:
        with open(LP_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def lp_credit(store, puuid, now_ranks, games, now=None):
    """Compares your rank now with the last one noted and credits the change to the ranked game(s) in between.
    `games`: your cached game summaries. Changes `store` in place; returns True when it changed."""
    now = now or time.time()
    me = store.setdefault(str(puuid), {"last": {}, "games": {}})
    changed = me.get("now") != now_ranks
    me["now"] = {q: dict(c) for q, c in now_ranks.items()}   # what the rank strip shows
    for queue, cur in now_ranks.items():
        prev = me["last"].get(queue)
        cur = dict(cur, t=now)
        if prev is None:
            me["last"][queue] = cur
            changed = True
            continue
        same = all(prev.get(k) == cur.get(k) for k in ("tier", "division", "lp", "wins", "losses"))
        if same:
            continue
        a, b = _ladder(prev), _ladder(cur)
        played = (_num(cur.get("wins")) + _num(cur.get("losses"))) - (_num(prev.get("wins")) + _num(prev.get("losses")))
        # ranked games of this queue that ended after the last note and have no LP yet
        new = sorted((g for g in games if g.get("queue") == queue and str(g.get("id")) not in me["games"]
                      and (_num(g.get("created")) / 1000 + _num(g.get("duration"))) > prev["t"] - 60),
                     key=lambda g: _num(g.get("created")))
        if new and played > 0 and played != len(new):
            new = new[-played:] if played < len(new) else new
        if not new and played > 0:
            # The rank moved but the game isn't in League's match history yet (it can take a minute or two).
            # Keep the old rank as the starting point so the change is credited once the game shows up.
            wait = me.setdefault("wait", {})
            if now - wait.setdefault(queue, now) < 3 * 3600:
                changed = True
                continue
        me.get("wait", {}).pop(queue, None)
        if new:
            rec = {"from": {k: prev.get(k) for k in ("tier", "division", "lp")}, "to": {k: cur.get(k) for k in ("tier", "division", "lp")}}
            if a is not None and b is not None:
                rec["delta"] = b - a
            else:
                rec["placed"] = a is None and b is not None
            if len(new) == 1:
                me["games"][str(new[0]["id"])] = rec
            else:   # several games since the last look: only the total is known
                for g in new:
                    me["games"][str(g["id"])] = dict(rec, over=len(new), last=g is new[-1])
        me["last"][queue] = cur
        changed = True
    return changed


def _lp_update(lcu, puuid):
    """Notes your rank from the client and credits any change. Returns your per-player LP record."""
    store = _lp_load()
    try:
        qm = (lcu.get("/lol-ranked/v1/current-ranked-stats") or {}).get("queueMap") or {}
        ranks = {}
        keys = list(RANKED) + [k for k in qm if k not in RANKED and "TFT" not in k and "CHERRY" not in k and str((qm[k] or {}).get("tier") or "").upper() not in ("", "NONE", "UNRANKED")]
        if set(qm) - set(RANKED) and not _lp_logged.get("q"):
            _lp_logged["q"] = True
            core.log.info("Review: ranked queues the client reports: %s", sorted(qm))
        for key in keys:
            label = RANKED.get(key) or key.replace("RANKED_", "Ranked ").replace("_", " ").title().replace("Sr", "").strip()
            q = qm.get(key) or {}
            tier = str(q.get("tier") or "").upper()
            ranks[label] = {"tier": tier if tier not in ("", "NONE", "UNRANKED") else None, "division": q.get("division"),
                            "lp": _num(q.get("leaguePoints")), "wins": _num(q.get("wins")), "losses": _num(q.get("losses"))}
        if lp_credit(store, puuid, ranks, list_games(puuid)):
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(LP_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(store, f)
            os.replace(LP_FILE + ".tmp", LP_FILE)
    except Exception as e:
        core.log.info("Review: couldn't read rank: %s", e)
    return store.get(str(puuid)) or {"last": {}, "games": {}}


def lp_for(puuid):
    return _lp_load().get(str(puuid)) or {"last": {}, "games": {}}


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
    _lp_update(lcu, me["puuid"])
    if time.time() - _bf.get("started", 0) > 1800:
        plat = next((g.get("platformId") for g in games if g.get("platformId")), None) or "NA1"
        threading.Thread(target=backfill_history, args=(cfg, me["puuid"], plat), daemon=True).start()
    return me, None


# Your full history, like op.gg: the client only keeps recent games, so older ranked and normal games come from
# Riot's match API through the site. Paced well under the site key's limit (100 requests / 2 min, shared with
# lookups), two requests per game (match + timeline). Games are kept for good, so this only fetches new ones.
BACKFILL_GAMES = 200
BACKFILL_RATE = 50         # requests per 2 minutes, at most
_bf = {"state": "idle"}


def backfill_history(cfg, puuid, platform):
    if _bf.get("state") == "working" or not cfg.get("site_url") or not cfg.get("ingest_key"):
        return
    _bf.clear(); _bf.update(state="working", loaded=0, started=time.time())
    skip_path = os.path.join(core.HERE, "review-riot-skip.json")
    try:
        skip = set(json.load(open(skip_path)))
    except (OSError, ValueError):
        skip = set()
    stamps = []

    def pace(n):
        while True:
            now = time.time()
            stamps[:] = [t for t in stamps if now - t < 120]
            if len(stamps) + n <= BACKFILL_RATE:
                stamps.extend([now] * n)
                return
            time.sleep(max(1, 120 - (now - stamps[0])))
    try:
        ids = []
        for typ in ("ranked", "normal"):
            for start in range(0, BACKFILL_GAMES, 100):
                pace(1)
                page = _site_get("/api/review/lookup?" + urllib.parse.urlencode(
                    {"puuid": puuid, "platform": platform, "type": typ, "start": start, "count": 100})).get("ids") or []
                ids += page
                if len(page) < 100:
                    break
        ids = sorted(set(ids), key=lambda m: -int(m.split("_")[-1]))[:BACKFILL_GAMES]
        _bf["total"] = len(ids)
        for mid in ids:
            gid = int(mid.split("_")[-1])
            if os.path.exists(_cache_path(gid)) or mid in skip:
                continue
            for attempt in range(4):
                pace(2)
                try:
                    raw = _site_get("/api/review/lookup?match=" + mid)
                    break
                except Exception as e:
                    raw = None
                    if "request limit" in str(e):
                        time.sleep(120)          # someone else used the shared limit: wait it out
                        continue
                    core.log.info("History: couldn't load %s: %s", mid, e)
                    break
            if not raw:
                continue
            info = raw["match"]["info"]
            if info.get("queueId") not in _VIEW_QUEUES or info.get("gameDuration", 0) < 600:
                skip.add(mid)
                json.dump(sorted(skip), open(skip_path, "w"))
                continue
            if os.path.exists(_cache_path(gid)):     # the client saved it meanwhile
                continue
            data = riot_to_client(raw["match"], raw["timeline"], puuid)
            data.pop("viewing", None)
            data["source"] = "riot"
            with open(_cache_path(gid), "w", encoding="utf-8") as f:
                json.dump(data, f)
            _bf["loaded"] += 1
        _bf.update(state="done", finished=time.time())
        core.log.info("History: %d older games loaded from Riot", _bf["loaded"])
    except Exception as e:
        core.log.info("History backfill stopped: %s", e)
        _bf.update(state="error", message=str(e))


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
# Viewing another player: their recent games from Riot (through the site), kept apart from your own
# --------------------------------------------------------------------------

OTHERS_DIR = os.path.join(CACHE_DIR, "others")
_LANE = {"TOP": ("TOP", "SOLO"), "JUNGLE": ("JUNGLE", "NONE"), "MIDDLE": ("MIDDLE", "SOLO"),
         "BOTTOM": ("BOTTOM", "DUO_CARRY"), "UTILITY": ("BOTTOM", "DUO_SUPPORT")}
_VIEW_QUEUES = (400, 420, 430, 440, 490)   # Summoner's Rift normals and ranked


def riot_to_client(match, timeline, puuid):
    """A Riot API match + timeline in the League client's shape (what the review page reads), with the extras
    the site normally fills in (items, skills, armor, trading stats, casts, pings) already in place."""
    m, tl = match["info"], timeline["info"]
    parts, idents = [], []
    for p in m["participants"]:
        lane, role = _LANE.get(p.get("teamPosition"), ("NONE", "NONE"))
        st = {k: p.get(k) for k in ("win", "kills", "deaths", "assists", "totalMinionsKilled", "neutralMinionsKilled", "goldEarned",
                                    "totalDamageDealtToChampions", "visionScore", "largestMultiKill", "firstBloodKill")}
        st.update({"item%d" % i: p.get("item%d" % i) for i in range(7)})
        sty = (p.get("perks") or {}).get("styles") or []
        if len(sty) >= 2:
            sel = [x["perk"] for x in sty[0]["selections"]] + [x["perk"] for x in sty[1]["selections"]]
            st.update({"perk%d" % i: v for i, v in enumerate(sel)}, perkPrimaryStyle=sty[0]["style"], perkSubStyle=sty[1]["style"])
            sp = p["perks"].get("statPerks") or {}
            st.update(statPerk0=sp.get("offense"), statPerk1=sp.get("flex"), statPerk2=sp.get("defense"))
        parts.append({"participantId": p["participantId"], "teamId": p["teamId"], "championId": p["championId"],
                      "spell1Id": p.get("summoner1Id"), "spell2Id": p.get("summoner2Id"), "stats": st,
                      "timeline": {"lane": lane, "role": role}})
        idents.append({"participantId": p["participantId"], "player": {"puuid": p["puuid"], "gameName": p.get("riotIdGameName"),
                                                                       "tagLine": p.get("riotIdTagline")}})
    game = {"gameId": m["gameId"], "platformId": m.get("platformId"), "gameCreation": m["gameCreation"],
            "gameDuration": m["gameDuration"], "queueId": m["queueId"], "mapId": m.get("mapId", 11), "gameMode": m.get("gameMode", "CLASSIC"),
            "gameType": "MATCHED_GAME", "gameVersion": m["gameVersion"], "participants": parts, "participantIdentities": idents}
    frames = []
    for f in tl["frames"]:
        pfs = {}
        for k, v in f["participantFrames"].items():
            c, d = v.get("championStats") or {}, v.get("damageStats") or {}
            x = {f2: v.get(f2) for f2 in FRAME_FIELDS if f2 in v}
            x["armor"] = c.get("armor")
            x["st"] = [c.get("health"), c.get("healthMax"), c.get("power"), c.get("powerMax"),
                       d.get("totalDamageDoneToChampions"), d.get("totalDamageTaken")]
            pfs[k] = x
        frames.append({"timestamp": f["timestamp"], "participantFrames": pfs, "events": f.get("events") or []})
    by_pid = {p["participantId"]: p for p in m["participants"]}
    casts = {str(i): [p.get(k, 0) for k in ("spell1Casts", "spell2Casts", "spell3Casts", "spell4Casts", "summoner1Casts", "summoner2Casts")]
             for i, p in by_pid.items()}
    pings = {str(i): {k: v for k, v in p.items() if k.endswith("Pings") and isinstance(v, int)} for i, p in by_pid.items()}
    data = {"game": game, "timeline": {"frames": frames}, "me": puuid, "casts": casts, "pings": pings,
            "viewing": True, "fillTried3": time.time()}
    data["summary"] = _summarize(game, puuid)
    return data


def _site_get(path, timeout=30):
    url = _cfg["site_url"].rstrip("/") + path
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + _cfg.get("ingest_key", ""),
                                               "User-Agent": "custy-collector/" + core.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        raise RuntimeError(msg or "The site answered %s" % e.code)


def _others_dir(puuid):
    d = os.path.join(OTHERS_DIR, re.sub(r"[^A-Za-z0-9_-]", "", puuid)[:24])
    os.makedirs(d, exist_ok=True)
    return d


def lookup_player(riot_id, platform="NA1", limit=12):
    """Finds a player by Riot ID and loads their recent Summoner's Rift games. Returns (who, games)."""
    q = urllib.parse.urlencode({"riotId": riot_id, "platform": platform})
    who = _site_get("/api/review/lookup?" + q)
    d = _others_dir(who["puuid"])
    json.dump({k: who.get(k) for k in ("puuid", "gameName", "tagLine", "ranks")}, open(os.path.join(d, "_who.json"), "w"))
    # Games that aren't reviewable (ARAM, remakes...) are remembered so a second lookup doesn't spend
    # Riot requests on them again: the site's key allows 100 requests per 2 minutes, 2 per game.
    skip_path = os.path.join(d, "_skip.json")
    try:
        skip = set(json.load(open(skip_path)))
    except (OSError, ValueError):
        skip = set()
    got = 0
    for mid in who.get("ids") or []:
        if got >= limit:
            break
        path = os.path.join(d, "%s.json" % mid.split("_")[-1])
        if os.path.exists(path):
            got += 1
            continue
        if mid in skip:
            continue
        try:
            raw = _site_get("/api/review/lookup?match=" + mid)
        except Exception as e:
            core.log.info("Lookup: couldn't load %s: %s", mid, e)
            if "request limit" in str(e):
                break   # rate limited: show what loaded so far; the rest load on the next lookup
            continue
        if raw["match"]["info"].get("queueId") not in _VIEW_QUEUES or raw["match"]["info"].get("gameDuration", 0) < 600:
            skip.add(mid)
            json.dump(sorted(skip), open(skip_path, "w"))
            continue
        data = riot_to_client(raw["match"], raw["timeline"], who["puuid"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        got += 1
    return {k: who.get(k) for k in ("puuid", "gameName", "tagLine")}, list_others(who["puuid"])


def list_others(puuid):
    d = _others_dir(puuid)
    out = []
    for n in os.listdir(d):
        if n.endswith(".json") and not n.startswith("_"):
            try:
                data = json.load(open(os.path.join(d, n), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("summary"):
                if data["summary"].get("v") != SUMMARY_V and data.get("game"):
                    try:
                        data["summary"] = _summarize(data["game"], puuid) or data["summary"]
                    except Exception:
                        pass
                out.append(dict(data["summary"], hasTimeline=True))
    out.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return out


def _who_ranks(puuid):
    try:
        return json.load(open(os.path.join(_others_dir(puuid), "_who.json"), encoding="utf-8")).get("ranks") or None
    except (OSError, ValueError):
        return None


def read_other(puuid, game_id):
    try:
        return json.load(open(os.path.join(_others_dir(puuid), "%d.json" % int(game_id)), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def who_other(puuid):
    try:
        return json.load(open(os.path.join(_others_dir(puuid), "_who.json")))
    except (OSError, ValueError):
        return {"puuid": puuid}


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


def _replay_meta(lcu, game_id, game=None):
    """What League knows about this game's replay. For a game the client hasn't shown in match history yet
    it knows nothing (404) until it's asked to look, so ask, the way the match history page does. Someone else's
    game isn't in our cache, so its version, queue and end time come in `game` (from the Riot match API): without
    them League can't tell which replay file to fetch."""
    path = "/lol-replays/v1/metadata/%s" % game_id
    try:
        return lcu.get(path) or {}
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    game = game or (_read_cache(game_id) or {}).get("game") or {}
    body = {"gameVersion": game.get("gameVersion") or "", "gameType": game.get("gameType") or "MATCHED_GAME",
            "queueId": _num(game.get("queueId")),
            "gameEnd": _num(game.get("gameEnd")) or _num(game.get("gameCreation")) + _num(game.get("gameDuration")) * 1000}
    if not body["gameVersion"]:
        core.log.info("Replay metadata for %s: no game version known, League may not find this replay", game_id)
    try:
        core.log.info("Replay metadata create %s %s -> %s", game_id, body, _lcu_post(lcu, path + "/create", body))
    except urllib.error.HTTPError as e:
        try:
            why = e.read()[:300]
        except Exception:
            why = b""
        core.log.info("Replay metadata create for %s: HTTP %s %s", game_id, e.code, why)
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
# Clips: record a stretch of a replay to a video file through League's own Replay API
# (/replay/render for the camera, /replay/recording for the file). League has to play the replay;
# the app drives it and, if asked, keeps its window out of the way while it records.
# --------------------------------------------------------------------------

_clip = {"state": "idle", "message": "", "at": 0, "file": None}


CLIP_SETTINGS = os.path.join(core.HERE, "clip-settings.json")


def _highlights_dir():
    """Where the League client saves its highlights (its own setting), else its default folder."""
    try:
        lcu = _lcu(_cfg)
        p = lcu.get("/lol-highlights/v1/highlights-folder-path") if lcu else None
        if isinstance(p, str) and p.strip():
            return p
    except Exception:
        pass
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "League of Legends", "Highlights")


def clips_dir():
    """The folder clips are saved to: the one picked in custy coach, else League's highlights folder."""
    d = None
    try:
        d = json.load(open(CLIP_SETTINGS)).get("folder")
    except Exception:
        pass
    d = d or _highlights_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.join(os.path.expanduser("~"), "Videos", "custy clips")
        os.makedirs(d, exist_ok=True)
    return d


def set_clips_dir(path):
    path = (path or "").strip()
    if path:
        os.makedirs(path, exist_ok=True)
    json.dump({"folder": path or None}, open(CLIP_SETTINGS, "w"))
    return clips_dir()


def pick_folder(start):
    """Windows' own folder picker (through PowerShell, so nothing extra has to be bundled)."""
    import subprocess
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='Where custy coach saves clips';"
          "$d.SelectedPath=$env:CUSTY_START;$d.ShowNewFolderButton=$true;"
          "$f=New-Object System.Windows.Forms.Form;$f.TopMost=$true;"
          "if($d.ShowDialog($f) -eq 'OK'){[Console]::Out.Write($d.SelectedPath)}")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True, timeout=600,
                       env=dict(os.environ, CUSTY_START=start), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.strip() or None


def list_clips():
    d = clips_dir()
    out = []
    for n in os.listdir(d):
        if n.lower().endswith((".webm", ".mp4")):
            p = os.path.join(d, n)
            out.append({"name": n, "size": os.path.getsize(p), "at": os.path.getmtime(p)})
    out.sort(key=lambda x: -x["at"])
    custom = False
    try:
        custom = bool(json.load(open(CLIP_SETTINGS)).get("folder"))
    except Exception:
        pass
    return {"dir": d, "clips": out[:50], "custom": custom, "league": _highlights_dir()}


def _clip_status(state, message, **extra):
    with _lock:
        _clip.update(state=state, message=message, at=time.time(), **extra)
    core.log.info("Clip: %s", message)


def _replay_post(path, body):
    req = urllib.request.Request(REPLAY_API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=_local_ctx(), timeout=10) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


_win_prev = {}


def _clip_setting(key, default=None):
    try:
        return json.load(open(CLIP_SETTINGS)).get(key, default)
    except Exception:
        return default


def _save_clip_setting(key, value):
    try:
        d = json.load(open(CLIP_SETTINGS))
    except Exception:
        d = {}
    d[key] = value
    json.dump(d, open(CLIP_SETTINGS, "w"))


def _hide_how():
    """'vanish' (no window, no taskbar button) until we've seen League stop drawing that way, then 'hide' (off screen)."""
    how = "hide" if _clip_setting("vanish_stalls") else "vanish"
    _win_prev["how"] = how
    return how


def _league_mute(on):
    """Mutes League's replay sound in Windows' volume mixer (only League's, nothing else), or unmutes it."""
    if os.name != "nt":
        return False
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize()
        done = False
        for ses in AudioUtilities.GetAllSessions():
            if ses.Process and ses.Process.name().lower() == "league of legends.exe":
                ses.SimpleAudioVolume.SetMute(1 if on else 0, None)
                done = True
        return done
    except Exception as e:
        core.log.info("Clip: %s failed: %s", "mute" if on else "unmute", e)
        return False


def _mute_when_ready(stop):
    """League's sound session appears a little after its window: keep trying until it's muted."""
    for _ in range(200):
        if _league_mute(True):
            core.log.info("Clip: replay sound muted")
            return
        if stop.wait(0.3):
            return


def _window_mode(cfg, mode=None):
    """Reads (or sets) WindowMode in League's game.cfg: 0 full screen, 1 windowed, 2 borderless."""
    path = _game_cfg(cfg)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = re.search(r"(?im)^\s*WindowMode\s*=\s*(\d+)", text)
    if mode is None:
        return int(m.group(1)) if m else None
    if m:
        text = re.sub(r"(?im)^(\s*WindowMode\s*=\s*)\d+", lambda x: x.group(1) + str(mode), text, count=1)
    else:
        nl = "\r\n" if "\r\n" in text else "\n"
        text = re.sub(r"(?im)^(\[General\]\s*?)$", lambda x: x.group(1) + nl + "WindowMode=%d" % mode, text, count=1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return mode




def _hide_as_it_opens(stop):
    """Moves the replay window off the screen the moment it appears, instead of after it has loaded."""
    if os.name != "nt":
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        _win_prev["hwnd"] = u.GetForegroundWindow()
        end = time.time() + 120
        how = _hide_how()
        while time.time() < end and not stop.is_set():
            if u.FindWindowW("RiotWindowClass", None):
                _league_window(how)
                # League re-centres its window as it finishes loading: keep it away for a while longer
                for _ in range(100):
                    if stop.wait(0.1):
                        return
                    _league_window(_win_prev.get("how", how))
                return
            stop.wait(0.03)
    except Exception as e:
        core.log.info("Clip: early hide failed: %s", e)


def _league_window(action):
    """Moves League's game window off the screen ('hide') or back ('show'), or closes it ('close').
    Only standard window calls on the window; nothing inside the game is touched."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW("RiotWindowClass", None)
        if not hwnd:
            return False
        if action == "close":
            u.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE, same as clicking the X
        elif action == "vanish":                          # hidden entirely, no taskbar button (if League keeps drawing)
            u.ShowWindow(hwnd, 0)
            prev = _win_prev.get("hwnd")
            if prev and prev != hwnd:
                u.SetForegroundWindow(prev)
        elif action == "hide":
            u.ShowWindow(hwnd, 4)                             # SW_SHOWNOACTIVATE, in case it was hidden entirely
            u.SetWindowPos(hwnd, 0, -4000, -4000, 0, 0, 0x0001 | 0x0004 | 0x0010)   # move off screen, keep size
            prev = _win_prev.get("hwnd")
            if prev and prev != hwnd:
                u.SetForegroundWindow(prev)                  # give the screen back to whatever you were using
        elif action == "show":
            u.ShowWindow(hwnd, 5)
            u.SetWindowPos(hwnd, 0, 40, 40, 0, 0, 0x0001 | 0x0004)
        return True
    except Exception as e:
        core.log.info("Clip: window %s failed: %s", action, e)
        return False


def _who_in_replay(champion_name):
    """The replay's name for the player on this champion, which /replay/render follows."""
    try:
        players = _live("/liveclientdata/playerlist") or []
    except Exception:
        return None
    want = re.sub(r"[^a-z]", "", str(champion_name).lower())
    for p in players:
        if re.sub(r"[^a-z]", "", str(p.get("championName") or "").lower()) == want:
            return p.get("riotIdGameName") or p.get("summonerName") or p.get("riotId")
    return None


def _render_now():
    try:
        return _live("/replay/render") or {}
    except Exception:
        return {}


def _follow(cfg, game_id, champion, t0, t1):
    """Locks the camera on a champion. League follows the object named in selectionName with the camera attached,
    but only once the replay is running, and the name it wants varies (Riot ID, summoner name, champion). We check
    what League actually took; if nothing sticks, we fly the camera ourselves along the champion's path from the
    replay file, at the normal game camera's angle."""
    names = []
    try:
        for p in _live("/liveclientdata/playerlist") or []:
            if re.sub(r"[^a-z]", "", str(p.get("championName") or "").lower()) == re.sub(r"[^a-z]", "", champion.lower()):
                names = [p.get("riotIdGameName"), p.get("summonerName"), p.get("riotId"), p.get("championName"),
                         (p.get("riotId") or "").split("#")[0]]
                break
    except Exception as e:
        core.log.info("Clip: player list failed: %s", e)
    names = [n for i, n in enumerate(names) if n and n not in names[:i]] + [champion]
    time.sleep(1.0)
    picked = None
    for n in names:
        try:
            _replay_post("/replay/render", {"selectionName": n})
        except Exception as e:
            core.log.info("Clip: select %s failed: %s", n, e); continue
        time.sleep(0.5)
        r = _render_now()
        core.log.info("Clip: select %r -> selectionName=%r", n, r.get("selectionName"))
        if str(r.get("selectionName") or "").lower() == n.lower():
            picked = n
            break
    # The replay API can't pick a champion in the camera dropdown (the real lock), but it can attach the FPS camera
    # to the selected champion: League then carries the camera along with it every frame (Flash, dashes and all).
    # Put the camera where the game camera would be over the champion, attach, and check it really moves.
    if picked:
        try:
            import replay_trades as RT
            game = (_read_cache(game_id) or {}).get("game") or {"gameId": game_id}
            path = _rofl_path(cfg, game)
            d = RT.decode(path, until=t0 + 3) if path else None
            slot = next((k for k, st in enumerate((d or {}).get("stats", [])) if
                         re.sub(r"[^a-z]", "", str(st.get("SKIN") or "").lower()) == re.sub(r"[^a-z]", "", champion.lower())), None)
            L = [p for p in (d["tracks"].get(slot) or [])] if d and slot is not None else []
            here = None
            for p in L:
                if p[0] <= t0 + 1.5:
                    here = p
            # the champion may have moved since its last click; fine, the camera is re-centred below if needed
            x, z = (here[1], here[2]) if here else (None, None)
            body = {"cameraMode": "fps", "cameraAttached": False, "selectionName": picked,
                    "cameraRotation": {"x": 0.0, "y": 56.0, "z": 0.0}}
            if x is not None:
                body["cameraPosition"] = {"x": float(x), "y": 1900.0, "z": float(z) - 1250.0}
            _replay_post("/replay/render", body)
            time.sleep(0.3)
            _replay_post("/replay/render", {"cameraAttached": True})
            time.sleep(0.4)
            a = _render_now(); time.sleep(1.6); b = _render_now()
            pa, pb = a.get("cameraPosition") or {}, b.get("cameraPosition") or {}
            moved = math.hypot(float(pb.get("x", 0)) - float(pa.get("x", 0)), float(pb.get("z", 0)) - float(pa.get("z", 0)))
            core.log.info("Clip: attached camera to %s at %s -> mode=%r attached=%r, moved %.0f units in 1.6s (%s -> %s)",
                          picked, body.get("cameraPosition"), b.get("cameraMode"), b.get("cameraAttached"), moved, pa, pb)
            if b.get("cameraAttached") and moved > 60:
                return True
            _replay_post("/replay/render", {"cameraAttached": False})
        except Exception as e:
            core.log.info("Clip: attaching the camera failed: %s", e)
    core.log.info("Clip: following %s along its path from the replay file", champion)
    try:
        import replay_trades as RT
        game = (_read_cache(game_id) or {}).get("game") or {"gameId": game_id}
        path = _rofl_path(cfg, game)
        d = RT.decode(path, until=t1 + 5) if path else None
        slot = next((k for k, st in enumerate((d or {}).get("stats", [])) if
                     re.sub(r"[^a-z]", "", str(st.get("SKIN") or "").lower()) == re.sub(r"[^a-z]", "", champion.lower())), None)
        L = d["tracks"].get(slot) if d and slot is not None else None
        if not L:
            core.log.info("Clip: no positions for %s in the replay file", champion)
            return False
        T = [p[0] for p in L]

        def at(t):
            i = bisect.bisect_right(T, t)
            if i <= 0:
                return L[0][1:]
            if i >= len(L):
                return L[-1][1:]
            (ta, xa, za), (tb, xb, zb) = L[i - 1], L[i]
            f = (t - ta) / max(1e-6, tb - ta)
            return xa + (xb - xa) * f, za + (zb - za) * f
        keys, t = [], max(0.0, t0 - 1)
        while t <= t1 + 1:
            # average a second either side, so the camera glides instead of jerking with each click
            pts = [at(t + o) for o in (-1, -0.5, 0, 0.5, 1)]
            x = sum(p[0] for p in pts) / 5; z = sum(p[1] for p in pts) / 5
            keys.append({"time": round(t, 2), "value": {"x": x, "y": 1900.0, "z": z - 1250.0}, "blend": "smoothStep"})
            t += 0.5
        rot = [{"time": keys[0]["time"], "value": {"x": 0.0, "y": 56.0, "z": 0.0}, "blend": "snap"}]
        _replay_post("/replay/render", {"cameraMode": "fps", "cameraAttached": False})
        core.log.info("Clip: camera path %d points -> %s", len(keys),
                      _replay_post("/replay/sequence", {"cameraPosition": keys, "cameraRotation": rot}))
        return True
    except Exception as e:
        core.log.info("Clip: camera path failed: %s", e)
        return False


def _clear_sequence():
    try:
        _replay_post("/replay/sequence", {})
    except Exception:
        pass


def _replay_open():
    try:
        _live("/replay/playback")
        return True
    except Exception:
        return False


def _record_clip(cfg, game_id, spec):
    """Same order as Riot's League Director: set the camera, press play, then turn recording on with a folder
    as the path. League names the file and reports it (and its progress) on GET /replay/recording."""
    hidden = False
    restore_mode = None
    try:
        t0 = max(0.0, float(spec.get("start", 0)))
        t1 = max(t0 + 1, float(spec.get("end", t0 + 15)))
        if replay_api_enabled(cfg) is False:
            return _clip_status("error", "Clips need replay jumping turned on (Replay API). Turn it on from any game's banner, restart League, then try again.")
        hide_stop = threading.Event()
        if spec.get("hide") and _window_mode(cfg) == 0 and not _replay_open():
            # Full screen can't be moved off the screen: open this replay borderless, then put the setting back
            restore_mode = 0 if _window_mode(cfg, 2) is not None else None
            core.log.info("Clip: League is set to full screen; opening this replay borderless")
        _clip_status("working", "Opening the replay...")
        if spec.get("hide"):
            threading.Thread(target=_hide_as_it_opens, args=(hide_stop,), daemon=True).start()
        if spec.get("mute", True):
            threading.Thread(target=_mute_when_ready, args=(hide_stop,), daemon=True).start()
        _open_replay(cfg, game_id, t0)
        with _lock:
            st = dict(_replay)
        if st.get("state") == "error":
            return _clip_status("error", st.get("message") or "Couldn't open the replay.")
        render = {"interfaceAll": bool(spec.get("hud", True)), "fogOfWar": bool(spec.get("fog", False))}
        if spec.get("camera") == "fps":
            c = spec.get("fps") or {}
            render.update(cameraMode="fps", cameraAttached=False, fieldOfView=float(c.get("fov", 50)),
                          cameraPosition={"x": float(c.get("x", 7400)), "y": float(c.get("h", 2200)), "z": float(c.get("z", 7400))},
                          cameraRotation={"x": float(c.get("yaw", 0)), "y": float(c.get("pitch", 55)), "z": 0.0})
        try:
            core.log.info("Clip: render -> %s", _replay_post("/replay/render", render))
        except Exception as e:
            core.log.info("Clip: render failed: %s", e)
        hidden = bool(spec.get("hide")) and _league_window(_win_prev.get("how") or _hide_how())
        folder = clips_dir()
        watch = [folder] + [d for d in {_highlights_dir()} if d != folder and os.path.isdir(d)]
        before = {d: set(os.listdir(d)) for d in watch if os.path.isdir(d)}
        _playback({"paused": False})                       # League records while the replay plays
        if spec.get("camera") != "fps":
            _follow(cfg, game_id, spec.get("champion") or "", t0, t1)
        req = {"recording": True, "codec": "webm", "path": folder, "startTime": t0, "endTime": t1,
               "framesPerSecond": int(spec.get("fps_rate", 60)), "enforceFrameRate": True, "replaySpeed": 1.0}
        _clip_status("working", "Recording %s to %s..." % (_clock(t0), _clock(t1)))
        core.log.info("Clip: recording request %s -> %s", req, _replay_post("/replay/recording", req))
        started, rec, out = False, {}, None
        start_by = time.time() + 20
        deadline = time.time() + max(120, (t1 - t0) * 10)
        while time.time() < deadline:
            time.sleep(1)
            try:
                rec = _live("/replay/recording") or {}
            except Exception as e:
                core.log.info("Clip: recording status failed: %s", e)
                continue
            out = rec.get("path") or out
            if rec.get("recording"):
                if not started:
                    core.log.info("Clip: League is recording: %s", rec)
                    last_t, last_at = None, time.time()
                started = True
                cur = float(rec.get("currentTime") or t0)
                if cur != last_t:
                    last_t, last_at = cur, time.time()
                elif hidden and _win_prev.get("how") == "vanish" and time.time() - last_at > 4:
                    # Hidden entirely, League stopped drawing: remember that, and move it off screen instead
                    core.log.info("Clip: recording stalled with the window hidden entirely; moving it off screen instead")
                    _save_clip_setting("vanish_stalls", True)
                    _win_prev["how"] = "hide"
                    _league_window("hide")
                    last_at = time.time()
                _clip_status("working", "Recording... %d%%" % max(0, min(99, int(100 * (cur - t0) / (t1 - t0)))))
            elif started or time.time() > start_by:
                break
        core.log.info("Clip: last recording status %s", rec)
        _clear_sequence()
        try:
            _playback({"paused": True})
        except Exception:
            pass
        hide_stop.set()
        if started and hidden and _win_prev.get("how") == "vanish" and not _clip_setting("vanish_stalls"):
            _save_clip_setting("vanish_ok", True)
        if spec.get("mute", True) and not spec.get("close", True):
            _league_mute(False)
        if hidden and not spec.get("close", True):   # closing it anyway: no need to bring it back first
            _league_window("show")
        hidden = False
        if not started:
            return _clip_status("error", "League didn't start recording. If \"Keep the replay off my screen\" was on, try once with it off. The log has League's answer.")
        found = None
        for _ in range(30):   # League can take a while to finish writing; it may also use its own highlights folder
            time.sleep(1)
            found = out if out and os.path.isfile(out) else None
            if not found:
                new = [os.path.join(d, n) for d in before for n in set(os.listdir(d)) - before[d] if n.lower().endswith(".webm")]
                found = max(new, key=os.path.getmtime) if new else None
            if found:
                size = os.path.getsize(found); time.sleep(1.5)
                if size and os.path.getsize(found) == size:
                    break
        core.log.info("Clip: League's file %s", found)
        if found:   # into the chosen folder, named after the moment
            nice = re.sub(r"[^\w\-. ()]", "", str(spec.get("name") or "")).strip()[:90] or "custy clip"
            target = os.path.join(folder, "%s (%s).webm" % (nice, time.strftime("%Y-%m-%d %H.%M")))
            n = 2
            while os.path.exists(target):
                target = os.path.join(folder, "%s (%s) %d.webm" % (nice, time.strftime("%Y-%m-%d %H.%M"), n)); n += 1
            for _ in range(5):
                try:
                    shutil.move(found, target)
                    found = target
                    break
                except OSError as e:
                    core.log.info("Clip: couldn't move %s yet: %s", found, e); time.sleep(2)
        if spec.get("close", True):
            _league_window("close")
        if not found:
            return _clip_status("error", "League recorded, but the file isn't in %s. League reported: %s" % (folder, out or "no path"))
        _clip_status("done", "Saved %s" % os.path.basename(found), file=os.path.basename(found))
    except Exception as e:
        core.log.exception("Clip failed")
        if hidden:
            _league_window("show")
        _league_mute(False)
        _clip_status("error", "Couldn't record the clip: %s" % e)
    finally:
        if restore_mode is not None:   # League reads it at the next launch; your normal setting goes back now
            try:
                _window_mode(cfg, restore_mode)
            except Exception as e:
                core.log.info("Clip: couldn't put full screen back: %s", e)

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

        def _send_file(self, path, ctype):
            """A file, with Range support so the video player can jump around without loading it all."""
            size = os.path.getsize(path)
            rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            a, b = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    a = int(rng.group(1))
                    b = min(size - 1, int(rng.group(2))) if rng.group(2) else size - 1
                else:
                    a = max(0, size - int(rng.group(2)))
                if a >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers()
                    return
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(b - a + 1))
            if rng:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with open(path, "rb") as f:
                    f.seek(a)
                    left = b - a + 1
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass   # the player stopped reading (it jumped elsewhere)

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
            m = re.match(r"^/assets/(sr-map\.jpg|sr-mini\.jpg|minion-blue\.png|minion-red\.png|rank-[a-z]+\.png)$", url.path)
            if m:   # map art for the trades playback (public images; no key needed)
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    return self._send(403, b"forbidden", "text/plain")
                base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
                try:
                    with open(os.path.join(base, "assets", m.group(1)), "rb") as f:
                        body = f.read()
                except OSError:
                    return self._send(404, b"missing", "text/plain")
                return self._send(200, body, "image/jpeg" if m.group(1).endswith(".jpg") else "image/png")
            if url.path == "/api/ping":
                return self._send(200, {"ok": True})
            m = re.match(r"^/rec/(\d+)\.mp4$", url.path)
            if m:   # your recording of a game, for the page's player (key in the address: <video> can't send headers)
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost") or not secrets.compare_digest(parse_qs(url.query).get("k", [""])[0], token):
                    return self._send(403, b"forbidden", "text/plain")
                import recorder
                f = recorder.find(m.group(1))
                if not f:
                    return self._send(404, b"no recording", "text/plain")
                return self._send_file(f[0], "video/mp4" if f[0].endswith(".mp4") else "video/x-matroska")
            if not self._allowed():
                return self._send(403, {"error": "forbidden"})
            if url.path == "/api/app-version":      # lets an open page notice that the app updated
                return self._send(200, {"version": core.VERSION})
            if url.path == "/api/lookup":           # view another player's recent games
                q = parse_qs(url.query)
                try:
                    who, games = lookup_player((q.get("riotId") or [""])[0], (q.get("platform") or ["NA1"])[0])
                except Exception as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"me": who, "games": games, "viewing": True, "patch": _client_patch(cfg), "replayApi": False,
                                        "rank": _who_ranks(who.get("puuid"))})
            if url.path == "/api/games" and parse_qs(url.query).get("as"):
                pu = parse_qs(url.query)["as"][0]
                return self._send(200, {"me": who_other(pu), "games": list_others(pu), "viewing": True,
                                        "patch": _client_patch(cfg), "replayApi": False, "rank": _who_ranks(pu)})
            if url.path == "/api/games":
                me, err = refresh(cfg)
                if me:
                    me_cache["me"] = me
                me = me_cache["me"]
                games = list_games(me.get("puuid") if me else None)
                lp = lp_for(me.get("puuid")) if me else {"last": {}, "games": {}}
                for g in games:
                    if str(g.get("id")) in lp["games"]:
                        g["lp"] = lp["games"][str(g["id"])]
                return self._send(200, {"me": me, "note": err, "games": games, "patch": _client_patch(cfg),
                                        "replayApi": replay_api_enabled(cfg), "rank": lp.get("now") or lp["last"]})
            m = re.match(r"^/api/game/(\d+)$", url.path)
            if m and parse_qs(url.query).get("as"):
                data = read_other(parse_qs(url.query)["as"][0], m.group(1))
                if not data:
                    return self._send(404, {"error": "game not found"})
                return self._send(200, dict(data, roles=roles(data["game"])))
            if m:
                me = me_cache["me"] or {}
                data = _read_cache(m.group(1)) or fetch_game(_lcu(cfg), m.group(1), me.get("puuid"))
                if not data:
                    return self._send(404, {"error": "game not found"})
                if fill_from_riot(data):
                    _write_cache(m.group(1), data)
                return self._send(200, dict(data, roles=roles(data["game"])))
            m = re.match(r"^/api/deaths/(\d+)$", url.path)
            if m:
                try:
                    return self._send(200, deaths_for(cfg, m.group(1)))
                except Exception as e:
                    core.log.exception("Deaths for %s failed", m.group(1))
                    return self._send(200, {"error": "Couldn't check deaths: %s" % e})
            m = re.match(r"^/api/trades/(\d+)$", url.path)
            if m:
                try:
                    return self._send(200, trades_for(cfg, m.group(1)))
                except Exception as e:
                    core.log.exception("Trades for %s failed", m.group(1))
                    return self._send(200, {"error": "Couldn't build trades: %s" % e})
            m = re.match(r"^/api/benchmark/([A-Za-z]+-(?:TOP|JUNGLE|MID|BOT|SUPPORT))$", url.path)
            if m:
                return self._send(200, benchmark(cfg, m.group(1)))
            m = re.match(r"^/api/notes/([A-Za-z]+|index)$", url.path)   # expert matchup sheets
            if m:
                return self._send(200, benchmark(cfg, m.group(1), "matchups"))
            if url.path == "/api/replay":
                with _lock:
                    return self._send(200, dict(_replay))
            if url.path == "/api/clip":
                with _lock:
                    return self._send(200, dict(_clip))
            if url.path == "/api/clips":
                return self._send(200, list_clips())
            if url.path == "/api/experts-auto":        # the always-on expert downloads
                return self._send(200, xpa_status(cfg))
            if url.path == "/api/rec":                 # recording settings, state and the list
                import recorder
                return self._send(200, recorder.status())
            m = re.match(r"^/api/rec/(\d+)$", url.path)
            if m:                                      # is there a recording of this game, and where 0:00 is in it
                import recorder
                q = parse_qs(url.query)
                if q.get("len"):
                    try:
                        recorder.fill_length(m.group(1), float(q["len"][0]))
                    except (ValueError, OSError):
                        pass
                return self._send(200, recorder.info_for(m.group(1)))
            m = re.match(r"^/api/experts/([A-Za-z]+-[A-Za-z]+-[A-Z]+)$", url.path)   # expert replay downloads
            if m:
                return self._send(200, expert_status(cfg, m.group(1)))
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
            m = re.match(r"^/api/trades/(\d+)/download$", url.path)
            if m:
                st = _trades_dl.get(m.group(1)) or {}
                if st.get("state") != "working" or time.time() - st.get("at", 0) > 200:
                    threading.Thread(target=_download_for_trades, args=(cfg, m.group(1)), daemon=True).start()
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
            m = re.match(r"^/api/clip/(\d+)$", url.path)
            if m:
                with _lock:
                    busy = _clip["state"] == "working" and time.time() - _clip["at"] < 300
                if busy:
                    return self._send(409, {"error": "A clip is already recording."})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    spec = json.loads(self.rfile.read(n) or b"{}") if n else {}
                except ValueError:
                    return self._send(400, {"error": "bad clip settings"})
                _clip_status("working", "Starting...", file=None)
                threading.Thread(target=_record_clip, args=(cfg, int(m.group(1)), spec), daemon=True).start()
                return self._send(200, {"ok": True})
            if url.path == "/api/clips/folder":   # {"path": "..."} to set, {"pick": true} for Windows' picker, {} = League's
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    path = pick_folder(clips_dir()) if body.get("pick") else body.get("path")
                    if body.get("pick") and not path:
                        return self._send(200, {"dir": clips_dir(), "cancelled": True})
                    return self._send(200, {"dir": set_clips_dir(path), "league": _highlights_dir()})
                except Exception as e:
                    return self._send(400, {"error": str(e)})
            if url.path == "/api/clips/open":
                try:
                    os.startfile(clips_dir())   # Windows: opens the folder in Explorer
                except Exception:
                    pass
                return self._send(200, {"ok": True})
            if url.path == "/api/rec":   # {"on": bool, "days": n, "pick": true (folder picker), "folder": path or ""}
                import recorder
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    if "on" in body:
                        recorder.save_settings(on=bool(body["on"]))
                        if body["on"]:
                            recorder.get_ffmpeg()
                    if body.get("days"):
                        recorder.save_settings(days=max(1, min(60, int(body["days"]))))
                    if body.get("capture") in ("window", "screen"):
                        recorder.save_settings(capture=body["capture"])
                    if body.get("sound") in ("game", "all", "off"):
                        recorder.save_settings(sound=body["sound"])
                    if body.get("pick"):
                        path = pick_folder(recorder.root_dir())
                        if path:
                            recorder.save_settings(folder=path)
                    elif "folder" in body:
                        recorder.save_settings(folder=(body["folder"] or "").strip() or None)
                    if body.get("retry"):
                        recorder.get_ffmpeg()
                    return self._send(200, recorder.status())
                except Exception as e:
                    return self._send(400, {"error": str(e)})
            if url.path == "/api/experts-auto":   # {"on": bool, "open_league": bool, "noticed": bool}
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    kw = {k: body[k] for k in ("on", "open_league", "noticed", "per_hour") if k in body}
                    if "per_hour" in kw:
                        kw["per_hour"] = max(1, min(10, int(kw["per_hour"])))
                    xpa_save(**kw)
                    return self._send(200, xpa_status(cfg))
                except Exception as e:
                    return self._send(400, {"error": str(e)})
            if url.path == "/api/rec/open":
                import recorder
                try:
                    os.startfile(recorder.root_dir())
                except Exception:
                    pass
                return self._send(200, {"ok": True})
            m = re.match(r"^/api/rec/(\d+)/(keep|unkeep|nudge|delete|clip)$", url.path)
            if m:
                import recorder
                gid, act = m.groups()
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    if act == "keep" or act == "unkeep":
                        return self._send(200, recorder.keep(gid, act == "keep"))
                    if act == "nudge":
                        return self._send(200, recorder.nudge(gid, float(body.get("delta") or 0)) or {"exists": False})
                    if act == "delete":
                        recorder.delete(gid)
                        return self._send(200, {"exists": False})
                    out = recorder.clip(gid, float(body["start"]), float(body["end"]), body.get("name"), clips_dir())
                    return self._send(200, {"file": os.path.basename(out), "dir": clips_dir()})
                except Exception as e:
                    return self._send(400, {"error": str(e)})
            m = re.match(r"^/api/experts/([A-Za-z]+-[A-Za-z]+-[A-Z]+)/(start|stop)$", url.path)
            if m:
                if m.group(2) == "stop":
                    _xp["stop"] = True
                else:
                    threading.Thread(target=expert_fetch, args=(cfg, m.group(1)), daemon=True).start()
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

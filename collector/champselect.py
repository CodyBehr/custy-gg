"""Champ select helper: reads your pick and the enemy picks from the League client, guesses your lane
opponent, and (through the review server) shows the experts' runes, spells, skill order and build.
Can put the rune page, summoner spells and an item set into the client.

Only uses what champ select shows you: your own pick and position, and enemy champions once revealed."""
import itertools
import json
import threading
import time
import urllib.error
import urllib.request

import custy_collector as core

ROLE = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID", "bottom": "BOT", "utility": "SUPPORT"}
ROLES = ["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"]
FLASH = 4

_names = {}        # champion id -> alias ("MonkeyKing")
_index = {"t": 0, "roles": {}}   # alias -> {role: expert games}
_state = {"phase": None, "session": None, "opened_for": None}


def _lcu(cfg):
    creds = core.find_client(cfg)
    return core.LeagueClient(*creds) if creds else None


def _call(lcu, method, path, body=None):
    req = urllib.request.Request(lcu.base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers=dict(lcu.headers, **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, context=lcu.ctx, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def champ_names(lcu):
    if not _names:
        for c in lcu.get("/lol-game-data/assets/v1/champion-summary.json") or []:
            if c.get("id", -1) > 0:
                _names[c["id"]] = c.get("alias") or c.get("name")
    return _names


def role_index(cfg):
    """How many expert games each champion has in each role, to guess where enemy champions are playing."""
    if time.time() - _index["t"] < 6 * 3600 and _index["roles"]:
        return _index["roles"]
    try:
        req = urllib.request.Request(cfg["site_url"].rstrip("/") + "/benchmarks/index.json", headers={"User-Agent": "custy-collector/" + core.VERSION})
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
        roles = {}
        for name, games, _src in rows:
            champ, role = name.rsplit("-", 1)
            roles.setdefault(champ, {})[role] = games
        _index.update(t=time.time(), roles=roles)
    except Exception as e:
        core.log.info("Champ select: couldn't load the role index: %s", e)
    return _index["roles"]


def guess_roles(enemies, index, taken=None):
    """Best guess of each enemy champion's role: the assignment that fits how often each one plays each role."""
    enemies = [e for e in enemies if e]
    if not enemies:
        return {}
    def p(champ, role):
        r = index.get(champ) or {}
        total = sum(r.values())
        return (r.get(role, 0) + 0.5) / (total + 2.5) if total else 0.2
    best, best_score = {}, -1
    for perm in itertools.permutations(ROLES, len(enemies)):
        score = 1.0
        for c, r in zip(enemies, perm):
            score *= p(c, r)
        if score > best_score:
            best, best_score = dict(zip(enemies, perm)), score
    return best


def state(cfg):
    """What the champ select page needs: phase, your champion and role, enemy champions, lane opponent guess."""
    _state["polled"] = time.time()   # a helper window is open and asking
    lcu = _lcu(cfg)
    if not lcu:
        return {"phase": None, "error": "League isn't open."}
    try:
        phase = lcu.get("/lol-gameflow/v1/gameflow-phase")
    except Exception:
        return {"phase": None, "error": "League isn't answering."}
    out = {"phase": phase}
    if phase != "ChampSelect":
        return out
    try:
        s = lcu.get("/lol-champ-select/v1/session") or {}
    except Exception as e:
        return dict(out, error="Couldn't read champ select (%s)." % e)
    names = champ_names(lcu)
    me = next((p for p in s.get("myTeam") or [] if p.get("cellId") == s.get("localPlayerCellId")), {}) or {}
    cid = me.get("championId") or me.get("championPickIntent") or 0
    role = ROLE.get((me.get("assignedPosition") or "").lower())
    index = role_index(cfg)
    champ = names.get(cid)
    if champ and not role:   # blind pick or no position: the role this champion is played in most
        r = index.get(champ) or {}
        role = max(r, key=r.get) if r else None
    enemies = [names.get(p.get("championId")) for p in s.get("theirTeam") or [] if p.get("championId")]
    guess = guess_roles(enemies, index)
    opp = next((c for c, r in guess.items() if r == role), None)
    lane = {"BOT": ("BOT", "SUPPORT"), "SUPPORT": ("BOT", "SUPPORT")}.get(role, (role,))
    out.update({
        "champion": champ, "championId": cid, "locked": bool(me.get("championId")), "role": role,
        "assigned": bool(me.get("assignedPosition")), "enemies": [{"champion": c, "role": guess.get(c)} for c in enemies],
        "opponent": opp, "laneEnemies": [c for c, r in guess.items() if r in lane],
        "spells": [me.get("spell1Id"), me.get("spell2Id")], "gameId": (s.get("gameId") or s.get("timer", {}).get("internalNowInEpochMs")),
    })
    return out


def set_runes(cfg, body):
    """Adds (or replaces) a 'custy.gg' rune page and makes it current. Never deletes the player's own pages."""
    lcu = _lcu(cfg)
    if not lcu:
        raise RuntimeError("League isn't open.")
    page = {"name": str(body.get("name") or "custy.gg")[:25], "primaryStyleId": int(body["primary"]), "subStyleId": int(body["sub"]),
            "selectedPerkIds": [int(x) for x in body["perks"]] + [int(x) for x in body["shards"]], "current": True}
    pages = _call(lcu, "GET", "/lol-perks/v1/pages") or []
    mine = next((p for p in pages if str(p.get("name", "")).startswith("custy.gg") and p.get("isDeletable", True)), None)
    if mine:
        _call(lcu, "DELETE", "/lol-perks/v1/pages/%s" % mine["id"])
    try:
        _call(lcu, "POST", "/lol-perks/v1/pages", page)
    except urllib.error.HTTPError as e:
        raise RuntimeError("Your rune pages are full. Delete one, or rename one to start with \"custy.gg\" so it can be reused, then click again.") from e
    return True


def set_spells(cfg, body):
    """Sets your summoner spells, keeping Flash on the key it's already on."""
    lcu = _lcu(cfg)
    if not lcu:
        raise RuntimeError("League isn't open.")
    a, b = int(body["spells"][0]), int(body["spells"][1])
    cur = body.get("current") or []
    if FLASH in (a, b) and cur and cur[1] == FLASH and a == FLASH:
        a, b = b, a
    elif FLASH in (a, b) and cur and cur[0] == FLASH and b == FLASH:
        a, b = b, a
    _call(lcu, "PATCH", "/lol-champ-select/v1/session/my-selection", {"spell1Id": a, "spell2Id": b})
    return True


def set_item_set(cfg, body):
    """Adds a 'custy.gg' item set for this champion (replacing an earlier custy.gg one for it). Shows in the shop."""
    lcu = _lcu(cfg)
    if not lcu:
        raise RuntimeError("League isn't open.")
    me = lcu.get("/lol-summoner/v1/current-summoner") or {}
    sid = me.get("summonerId")
    path = "/lol-item-sets/v1/item-sets/%s/sets" % sid
    cur = lcu.get(path) or {}
    champ = int(body["championId"])
    keep = [s for s in cur.get("itemSets") or [] if not (str(s.get("title", "")).startswith("custy.gg") and champ in (s.get("associatedChampions") or []))]
    new = {"title": str(body.get("title") or "custy.gg")[:40], "type": "custom", "map": "any", "mode": "any", "sortrank": 0,
           "startedFrom": "blank", "associatedChampions": [champ], "associatedMaps": [11], "preferredItemSlots": [],
           "uid": "custy-%d-%d" % (champ, int(time.time())),
           "blocks": [{"type": str(b["name"])[:40], "items": [{"id": str(int(i)), "count": 1} for i in b["items"]]} for b in body["blocks"] if b.get("items")]}
    _call(lcu, "PUT", path, {"accountId": cur.get("accountId") or me.get("accountId"), "itemSets": keep + [new], "timestamp": int(time.time() * 1000)})
    return True


def watch(cfg, stop, open_page):
    """Opens the review window (it switches to the matchup guide by itself) once per champ select, unless one is
    already open: an open page polls /api/champselect and follows the client on its own."""
    while not stop.is_set():
        stop.wait(3)
        if not cfg.get("champ_select_helper", True):
            continue
        try:
            lcu = _lcu(cfg)
            phase = lcu.get("/lol-gameflow/v1/gameflow-phase") if lcu else None
            if phase != "ChampSelect":
                _state["opened_for"] = None if phase not in ("ChampSelect", "InProgress", "GameStart") else _state["opened_for"]
                continue
            s = lcu.get("/lol-champ-select/v1/session") or {}
            key = s.get("gameId") or "cs-%d" % (int(time.time()) // 600)
            if _state["opened_for"] != key:
                _state["opened_for"] = key
                if time.time() - _state.get("polled", 0) > 8:   # one is already open from last game: it updates itself
                    open_page()
        except Exception as e:
            core.log.info("Champ select watch: %s", e)

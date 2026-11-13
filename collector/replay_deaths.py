"""
Gank warnings and caught-out checks for your deaths, from the game's replay file (after the game, offline).

For each of your deaths it works out:
  - who killed you and whether it was a gank (an enemy other than your lane opponent joined) or a catch
    (outnumbered with no teammate near, usually mid/late game);
  - when and where your team last saw each enemy that joined before they appeared (the replay marks every
    time a champion steps into the other team's vision; teammates standing near them count as seeing them);
  - for an early jungle gank, the jungler's first clear (camp order) and whether a start your team saw pointed
    at your lane;
  - where the wave was (crashed into their tower, stuck outside it, in the middle, at your tower);
  - how far you were from your nearest tower, and how many enemies were missing.
Then it writes the verdict in plain words. Rules, not AI; thresholds are meant to be tuned.
"""

import bisect
import math

import replay_trades as RT

LANE_OPP = {"TOP": ("TOP",), "JUNGLE": ("JUNGLE",), "MIDDLE": ("MIDDLE",), "MID": ("MIDDLE",),
            "BOTTOM": ("BOTTOM", "UTILITY"), "UTILITY": ("BOTTOM", "UTILITY")}
TOWERS = {   # (x, z, lane) per team
    100: [(981, 10441, "top"), (1512, 6699, "top"), (1169, 4287, "top"), (5846, 6396, "mid"), (5048, 4812, "mid"),
          (3651, 3696, "mid"), (10504, 1029, "bot"), (6919, 1483, "bot"), (4281, 1253, "bot"), (1748, 2270, "base"), (2177, 1807, "base")],
    200: [(4318, 13875, "top"), (7943, 13411, "top"), (10481, 13650, "top"), (8955, 8510, "mid"), (9767, 10113, "mid"),
          (11134, 11207, "mid"), (13866, 4505, "bot"), (13327, 8226, "bot"), (13624, 10572, "bot"), (12611, 13084, "base"), (13052, 12612, "base")],
}
FOUNTAIN = {100: (400, 400), 200: (14400, 14400)}
CAMPS = {   # camp -> (x, z) for the jungle of each team
    100: {"blue buff": (3821, 8101), "gromp": (2288, 8448), "wolves": (3783, 6495), "chickens": (6823, 5508), "red buff": (7765, 4072), "krugs": (8482, 2766)},
    200: {"blue buff": (10984, 6960), "gromp": (12703, 6444), "wolves": (11008, 8387), "chickens": (7986, 9471), "red buff": (7101, 10900), "krugs": (6317, 12146)},
}
SIDE = {   # which lane each camp sits next to, per team's jungle
    100: {"blue buff": "top", "gromp": "top", "wolves": "top", "chickens": "bot", "red buff": "bot", "krugs": "bot"},
    200: {"blue buff": "bot", "gromp": "bot", "wolves": "bot", "chickens": "top", "red buff": "top", "krugs": "top"},
}
OBJ = {"dragon pit": (9866, 4414), "baron pit": (5007, 10471), "bot river": (10500, 5170), "top river": (4400, 9600)}
SIGHT = 1350
NAMES = {"MissFortune": "Miss Fortune", "MonkeyKing": "Wukong", "DrMundo": "Dr. Mundo", "JarvanIV": "Jarvan IV", "LeeSin": "Lee Sin",
         "XinZhao": "Xin Zhao", "MasterYi": "Master Yi", "TahmKench": "Tahm Kench", "TwistedFate": "Twisted Fate", "KSante": "K'Sante",
         "Khazix": "Kha'Zix", "Chogath": "Cho'Gath", "Velkoz": "Vel'Koz", "KogMaw": "Kog'Maw", "AurelionSol": "Aurelion Sol",
         "RenataGlasc": "Renata Glasc", "Belveth": "Bel'Veth", "Kaisa": "Kai'Sa", "Leblanc": "LeBlanc", "Nunu": "Nunu & Willump", "RekSai": "Rek'Sai"}


def nice(name):
    return NAMES.get(name, name)


def clock(t):
    t = max(0, int(t))
    return "%d:%02d" % (t // 60, t % 60)


def _pos(L, t):
    if not L:
        return None
    T = [p[0] for p in L]
    j = bisect.bisect_left(T, t)
    if j == 0:
        return (L[0][1], L[0][2]) if T[0] - t < 3 else None
    if j >= len(L):
        return (L[-1][1], L[-1][2]) if t - T[-1] < 3 else None
    a, b = L[j - 1], L[j]
    g = b[0] - a[0]
    if g > 8 or math.hypot(b[1] - a[1], b[2] - a[2]) / max(g, 1e-6) > 900:   # long gap or recall/death: hold
        return (a[1], a[2])
    f = (t - a[0]) / g
    return (a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def region(x, z, team):
    """A short place name from the point of view of `team` (100/200)."""
    for t2, base in FOUNTAIN.items():
        if math.hypot(x - base[0], z - base[1]) < 3400:
            return "your base" if t2 == team else "their base"
    for name, (cx, cz) in OBJ.items():
        if math.hypot(x - cx, z - cz) < 1100:
            return name
    for t2, camps in CAMPS.items():
        for name, (cx, cz) in camps.items():
            if math.hypot(x - cx, z - cz) < 1000:
                return ("your " if t2 == team else "their ") + name
    if x < 2300 or z > 12600:
        return "top lane"
    if z < 2300 or x > 12600:
        return "bot lane"
    if abs(x - z) < 1300:
        return "mid lane"
    if abs(x + z - 14900) < 1500:
        return "top river" if x < 7450 else "bot river"
    own = 100 if x + z < 14900 else 200
    side = "top side" if x - z < 0 else "bot side"
    return ("your jungle, " if own == team else "their jungle, ") + side


def lane_of(x, z):
    if x < 2300 or z > 12600:
        return "top"
    if z < 2300 or x > 12600:
        return "bot"
    if abs(x - z) < 1300:
        return "mid"
    return None


def _alive_towers(team, t, dead):
    out = []
    for (x, z, lane) in TOWERS[team]:
        if not any(dt <= t and math.hypot(x - dx, z - dz) < 600 for dt, dx, dz in dead):
            out.append((x, z, lane))
    return out


def _first_clear(track, team, until):
    """Camps the jungler stood at for 3s+ between 1:00 and `until`, in order: [(camp, side, start, end)]."""
    out = []
    t = 60.0
    cur, since = None, None
    while t <= until:
        p = _pos(track, t)
        here = None
        if p:
            for name, (cx, cz) in CAMPS[team].items():
                if math.hypot(p[0] - cx, p[1] - cz) < 1100:
                    here = name
        if here != cur:
            if cur and t - since >= 3 and cur not in [c[0] for c in out]:
                out.append((cur, SIDE[team][cur], since, t))
            cur, since = here, t
        t += 1.0
    return out


def death_reviews(path, me, roles, kills, towers_dead, d=None):
    """me: your replay slot. roles: slot -> TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY. kills: [{t, victim, killer, assists, x, z}] in
    replay slots (killer -1 for towers/minions). towers_dead: [(t, x, z)]. Returns a list of reviewed deaths."""
    if d is None:
        last = max([k["t"] for k in kills] + [0]) + 5
        d = RT.decode(path, until=last)
    tracks, vision = d["tracks"], d["vision"]
    team = lambda k: 100 if k < 5 else 200
    my = team(me)
    allies = [k for k in range(10) if team(k) == my]
    enemies = [k for k in range(10) if team(k) != my]
    names = [p.get("SKIN") for p in d["stats"]]
    deaths_at = {k: [x["t"] for x in kills if x["victim"] == k] for k in range(10)}

    def alive(k, t):   # not inside a death timer (approximate: dead for 8s + 2s per minute)
        return not any(dt <= t < dt + 8 + 2 * dt / 60 for dt in deaths_at[k])

    def seen(k, t):
        """Was enemy k visible to your team at t: a vision event in the last 3s, or a living teammate within sight range."""
        v = vision.get(k) or []
        j = bisect.bisect_right(v, t)
        if j and t - v[j - 1] <= 3:
            return True
        p = _pos(tracks.get(k), t)
        if not p:
            return False
        for a in allies:
            if alive(a, t):
                q = _pos(tracks.get(a), t)
                if q and math.hypot(p[0] - q[0], p[1] - q[1]) <= SIGHT:
                    return True
        return False

    out = []
    opp_roles = LANE_OPP.get(roles.get(me, ""), ())
    for kill in kills:
        if kill["victim"] != me:
            continue
        T = kill["t"]
        involved = [k for k in [kill["killer"]] + list(kill.get("assists") or []) if k is not None and k >= 0 and team(k) != my]
        if not involved:
            continue
        lane_opps = [k for k in involved if roles.get(k) in opp_roles and roles.get(me) != "JUNGLE"]
        others = [k for k in involved if k not in lane_opps]
        mpos = _pos(tracks.get(me), T - 0.5) or (kill["x"], kill["z"])
        near_allies = [a for a in allies if a != me and alive(a, T) and (lambda q: q and math.hypot(q[0] - mpos[0], q[1] - mpos[1]) < 1500)(_pos(tracks.get(a), T - 1))]
        early = T < 14 * 60
        if region(mpos[0], mpos[1], my) == "your base":
            continue   # defending your base: a fight, not a pick
        if early and roles.get(me) != "JUNGLE" and others:
            kind = "gank"
        elif not early and len(involved) >= 2 and (not near_allies or (len(near_allies) == 1 and len(involved) >= 3)):
            kind = "caught"
        else:
            continue
        # When each enemy that joined (or the ganker) was last seen before they appeared
        who = []
        for k in (others if kind == "gank" else involved):
            # Visible stretch leading into the death (gaps under GAP seconds don't count as losing sight), then the
            # last moment they were seen before that stretch.
            GAP = 5.0
            t, last_vis = T, T
            while t > max(0, T - 300):
                if seen(k, t):
                    last_vis = t
                elif last_vis - t >= GAP:
                    break
                t -= 0.5
            appear = last_vis
            last_seen = None
            t = appear - GAP
            while t > max(0, T - 300):
                if seen(k, t):
                    last_seen = t
                    break
                t -= 0.5
            p_app = _pos(tracks.get(k), appear)
            p_last = _pos(tracks.get(k), last_seen) if last_seen is not None else None
            who.append({"slot": k, "name": names[k], "role": roles.get(k, ""), "appear": round(appear, 1),
                        "appearDist": round(math.hypot(p_app[0] - mpos[0], p_app[1] - mpos[1])) if p_app else None,
                        "lastSeen": round(last_seen, 1) if last_seen is not None else None,
                        "lastWhere": region(p_last[0], p_last[1], my) if p_last else None,
                        "lastXZ": [round(p_last[0]), round(p_last[1])] if p_last else None,
                        "unseenFor": round(appear - last_seen) if last_seen is not None else None})
        # Missing enemies: not seen in the 15s before the death
        missing = [k for k in enemies if alive(k, T) and not any(seen(k, T - s) for s in range(0, 16, 1))]
        # Distance to your nearest standing tower
        towers = _alive_towers(my, T, towers_dead)
        tdist = min((math.hypot(mpos[0] - x, mpos[1] - z) for x, z, _ in towers), default=None)
        # Wave in your lane
        lane = lane_of(*mpos) or {"TOP": "top", "MIDDLE": "mid", "BOTTOM": "bot", "UTILITY": "bot"}.get(roles.get(me, ""))
        wave = _wave(tracks, my, lane, T, towers, _alive_towers(300 - my, T, towers_dead)) if lane and early else None
        # Jungle route for an early jungle gank
        route = None
        jg = next((w for w in who if w["role"] == "JUNGLE"), None)
        if kind == "gank" and jg and T < 5 * 60:
            clear = _first_clear(tracks.get(jg["slot"]), team(jg["slot"]), T)
            first_seen = None
            for (camp, side, a, b) in clear:
                if any(seen(jg["slot"], x) for x in [a + i for i in range(int(b - a) + 1)]):
                    first_seen = {"camp": camp, "side": side, "t": a}
                    break
            route = {"camps": [c[0] for c in clear], "sides": [c[1] for c in clear], "seenAt": first_seen}
        r = {"t": T, "kind": kind, "killer": names[kill["killer"]] if kill["killer"] is not None and kill["killer"] >= 0 else None,
             "involved": [names[k] for k in involved], "laneOpps": [names[k] for k in lane_opps], "who": who,
             "pos": [round(mpos[0]), round(mpos[1])], "where": region(mpos[0], mpos[1], my),
             "towerDist": round(tdist) if tdist is not None else None, "allies": [names[a] for a in near_allies],
             "missing": [names[k] for k in missing], "wave": wave, "route": route, "lane": lane}
        r["text"] = _verdict(r, roles.get(me, ""))
        r["map"] = _snapshot(tracks, me, involved, who, T, my)
        r["pb"] = _playback(d, me, involved, who, T, seen, kills, enemies)
        out.append(r)
    return out


def _wave(tracks, my, lane, T, mine_t, theirs_t):
    """Where the fight front of the wave was, a few seconds before the death."""
    t = T - 3
    blue_up = my == 100   # lane progress s = x + z grows from the blue base toward the red base on every lane
    mine, theirs = [], []
    for key, L in tracks.items():
        if isinstance(key, int) and key < 10:
            continue
        p = _pos(L, t)
        if not p or lane_of(*p) != lane or not L or t - L[-1][0] > 4:
            continue
        x0, z0 = L[0][1], L[0][2]
        tm = 100 if math.hypot(x0 - 1500, z0 - 1500) < math.hypot(x0 - 13300, z0 - 13300) else 200
        (mine if tm == my else theirs).append(p[0] + p[1])
    their_tower = [x + z for x, z, ln in theirs_t if ln == lane]
    my_tower = [x + z for x, z, ln in mine_t if ln == lane]
    if not their_tower or not my_tower:
        return None
    et = min(their_tower) if blue_up else max(their_tower)   # their frontmost tower in this lane
    mt = max(my_tower) if blue_up else min(my_tower)
    front = (max(mine) if blue_up else min(mine)) if mine else None
    efront = (min(theirs) if blue_up else max(theirs)) if theirs else None
    # distances along the lane (s units are ~1.0-1.4x world units on the diagonal lanes; good enough for buckets)
    if front is not None and abs(et - front) < 1000:
        state = "crashed"      # your minions are hitting their tower
    elif efront is not None and abs(efront - mt) < 1100:
        state = "your tower"   # their wave is at your tower
    elif front is not None and abs(et - front) < 2400 and len(mine) >= len(theirs):
        state = "outside their tower"
    elif front is None and efront is None:
        state = "empty"
    else:
        state = "middle"
    return {"state": state, "mine": len(mine), "theirs": len(theirs),
            "toTheirTower": round(abs(et - front)) if front is not None else None}


def _verdict(r, my_role):
    T = clock(r["t"])
    lines = []
    if r["kind"] == "gank":
        g = r["who"]
        names = " and ".join(nice(w["name"]) for w in g)
        head = "Gank at %s: %s joined%s." % (T, names, (" " + " and ".join(nice(n) for n in r["laneOpps"])) if r["laneOpps"] else "")
    else:
        head = "Caught out at %s in %s: %d enemies against %s." % (T, r["where"], len(r["involved"]),
                                                                 "you alone" if not r["allies"] else "you and " + ", ".join(nice(a) for a in r["allies"]))
    lines.append(head)
    if r["kind"] == "caught":
        fog = [w for w in r["who"] if w["lastSeen"] is not None and w["unseenFor"] >= 8]
        if fog:
            lines.append("Out of sight before it: " + "; ".join("%s (last seen in %s at %s)" % (nice(w["name"]), w["lastWhere"], clock(w["lastSeen"])) for w in fog) + ".")
        never = [w for w in r["who"] if w["lastSeen"] is None]
        if never:
            lines.append("Not seen at all before it: " + ", ".join(nice(w["name"]) for w in never) + ".")
    for w in (r["who"] if r["kind"] == "gank" else []):
        if w["lastSeen"] is None:
            lines.append("Your team hadn't seen %s before they showed up %s units from you, %ds before you died."
                         % (nice(w["name"]), "{:,}".format(w["appearDist"] or 0), max(0, int(r["t"] - w["appear"]))))
        elif r["t"] - w["appear"] >= 10:
            lines.append("%s was in sight for %ds before you died (from %s units away): this gank could be seen coming."
                         % (nice(w["name"]), int(r["t"] - w["appear"]), "{:,}".format(w["appearDist"] or 0)))
        else:
            lines.append("Your team last saw %s in %s at %s, then not for %ds, until %s units from you, %ds before you died."
                         % (nice(w["name"]), w["lastWhere"], clock(w["lastSeen"]), w["unseenFor"],
                            "{:,}".format(w["appearDist"] or 0), max(0, int(r["t"] - w["appear"]))))
    rt = r.get("route")
    if rt and rt["camps"]:
        path = " → ".join(rt["camps"][:4])
        s = rt.get("seenAt")
        lane = r.get("lane")
        if s:
            toward = s["side"] == lane or lane == "mid"
            lines.append("He started %s; your team saw him at his %s at %s%s." % (path, s["camp"], clock(s["t"]),
                         ", on your lane's side, so a gank on your lane around 2:00–2:20 was the likely next step" if toward and r["t"] < 170 else ""))
        else:
            lines.append("His first clear: %s. Your team didn't see where he started." % path)
    wv = r.get("wave")
    if wv:
        st = wv["state"]
        if st == "outside their tower":
            lines.append("Your wave was stuck about %s units outside their tower, not crashed, so they had room to run you down."
                         % "{:,}".format(wv["toTheirTower"] or 0))
        elif st == "crashed":
            lines.append("Your wave was crashed into their tower.")
        elif st == "your tower":
            lines.append("The wave was at your tower.")
        elif st == "middle":
            lines.append("The wave was in the middle of the lane.")
    if r["towerDist"] is not None:
        lines.append("You were %s units from your nearest tower%s." % ("{:,}".format(r["towerDist"]),
                     " with " + ", ".join(nice(m) for m in r["missing"]) + " missing" if r["missing"] and r["kind"] == "caught" else ""))
    # advice
    adv = None
    if r["kind"] == "gank":
        if wv and wv["state"] == "outside their tower":
            adv = "Before the jungler can arrive, crash the wave into their tower (then ward your side's brush) or let it come back to you."
        elif rt and rt.get("seenAt") and r["t"] < 170:
            adv = "Play near your tower in the window that start points to, or ward the path from his last camp into your lane."
        elif wv and wv["state"] == "crashed":
            adv = "The wave was crashed, so this one comes down to vision: ward the brush the gank came through after you crash."
        elif any(r["t"] - w["appear"] >= 10 for w in r["who"]):
            adv = "He was visible on the way in: back off as soon as he shows up near your lane."
        elif r["towerDist"] and r["towerDist"] > 2500:
            adv = "With the jungler unseen for that long, stay closer to your tower or put a ward where he'd come from."
    else:
        miss = len(r["missing"])
        if miss >= 2:
            adv = "With %d enemies missing, walk with your team or check the area with a ward or sweeper before going in." % miss
        else:
            adv = "Outnumbered with no help near: stay within reach of your team, or only go where you have vision."
    if adv:
        lines.append(adv)
    return lines


def _playback(d, me, involved, who, T, seen, kills, enemies):
    """Everything the page needs to play the lead-up back: all 10 champions, minions near you, hits on you,
    casts, deaths, and when each enemy was visible to your team. Times are seconds from the window start."""
    seen_at = [w["lastSeen"] for w in who if w.get("lastSeen") is not None]
    w0 = min(T - 30, max(T - 90, min(seen_at) - 3)) if seen_at else T - 30
    w0 = max(0.0, w0); w1 = T + 3
    rel = lambda t: round(t - w0, 2)

    def seg(L, step=0.2):
        out, last = [], -9
        for t, x, z in L or []:
            if w0 - 4 <= t <= w1 + 2 and (t - last >= step or t > w1):
                out.append([rel(t), round(x), round(z)]); last = t
        return out
    pos = {str(k): seg(d["tracks"].get(k)) for k in range(10)}
    # enemy visibility to your team, as [start, end] stretches
    vis = {}
    for k in enemies:
        iv, cur, t = [], None, w0
        while t <= w1:
            if seen(k, t):
                if cur is None: cur = [rel(t), rel(t)]
                else: cur[1] = rel(t)
            elif cur is not None:
                iv.append(cur); cur = None
            t += 0.5
        if cur is not None: iv.append(cur)
        vis[str(k)] = iv
    ev = []
    for t, tg, a, v in d["hits"]:
        if w0 <= t <= w1 and v > 0.5 and (tg == me or (a == me and tg is not None and tg < 10)):
            ev.append([rel(t), "h", tg, -1 if a is None else a, round(v)])
    near = set([me] + list(involved))
    for t, k, L in d["casts"]:
        if w0 <= t <= w1 and k in near:
            ev.append([rel(t), "c", k, L])
    for x in kills:
        if w0 <= x["t"] <= w1:
            ev.append([rel(x["t"]), "d", x["victim"]])
    ev.sort(key=lambda e: e[0])
    # minions that came near your path
    mine = [(x, z) for t, x, z in pos[str(me)]]
    mins = []
    for key, L in d["tracks"].items():
        if isinstance(key, int) and key < 10:
            continue
        sg = seg(L, 0.4)
        if len(sg) >= 2 and any(math.hypot(x - a, z - b) < 1800 for t, x, z in sg[::3] for a, b in mine[::10]):
            x0, z0 = L[0][1], L[0][2]
            mins.append({"tm": 100 if math.hypot(x0 - 1500, z0 - 1500) < math.hypot(x0 - 13300, z0 - 13300) else 200, "p": sg})
    return {"w0": round(w0, 2), "len": round(w1 - w0, 2), "death": rel(T), "pos": pos, "vis": vis, "ev": ev,
            "mins": mins[:80], "involved": list(involved)}


def _snapshot(tracks, me, involved, who, T, my):
    """Small map data for the page: paths for the last 20s, last-seen pins."""
    def path(k, a, b):
        L = tracks.get(k) or []
        return [[round(t - T, 1), x, z] for t, x, z in L if a <= t <= b]
    start = {w["slot"]: max(T - 120, w["lastSeen"]) for w in who if w.get("lastSeen") is not None}
    keys = [me] + list(involved)
    return {"paths": {str(k): path(k, start.get(k, T - 25) if k != me else T - 25, T + 0.5) for k in keys},
            "pins": [{"slot": w["slot"], "t": w["lastSeen"], "xz": w["lastXZ"]} for w in who if w.get("lastXZ")],
            "me": me}

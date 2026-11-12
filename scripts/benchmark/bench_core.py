"""Shared pieces for building expert benchmarks from Riot match-v5 data.

row(match, timeline, participant)  -> one player's numbers for one game (small, JSON-safe)
aggregate(rows, meta)              -> the benchmark JSON the review page reads (public/benchmarks/<Champion>-<ROLE>.json)
"""
import json, os, statistics as S
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "BOT", "UTILITY": "SUPPORT"}
_ITEMS = None


def items():
    global _ITEMS
    if _ITEMS is None:
        with open(os.path.join(HERE, "item.json"), encoding="utf-8") as f:
            _ITEMS = json.load(f)["data"]
    return _ITEMS


def cost(i): return items().get(str(i), {}).get("gold", {}).get("total", 0)
def stat(i, k): return items().get(str(i), {}).get("stats", {}).get(k, 0)


def boots(i):
    it = items().get(str(i))
    return bool(it) and "Boots" in it.get("tags", []) and it["gold"]["total"] >= 700 and i != 1001


def legendary(i):
    it = items().get(str(i))
    return bool(it) and it["gold"]["total"] >= 2200 and not it.get("into") and "Consumable" not in it.get("tags", []) and not boots(i)


def row(m, tl, me):
    """Numbers for participant `me` (a match-v5 participant dict). m = match['info'], tl = timeline['info']."""
    parts = m["participants"]
    pos = me.get("teamPosition")
    opp = next((p for p in parts if p["teamId"] != me["teamId"] and p.get("teamPosition") == pos), None)
    jg = next((p for p in parts if p["teamId"] != me["teamId"] and p.get("teamPosition") == "JUNGLE"), None)
    pid, oid = me["participantId"], opp["participantId"] if opp else None
    fr = tl["frames"]
    pf = lambda f, i: f["participantFrames"][str(i)]
    ser = lambda i, fn: [fn(pf(f, i)) for f in fr]
    gold, cs = ser(pid, lambda x: x["totalGold"]), ser(pid, lambda x: x["minionsKilled"] + x["jungleMinionsKilled"])
    xp, lvl = ser(pid, lambda x: x["xp"]), ser(pid, lambda x: x["level"])
    r = {"win": me["win"], "dur": m["gameDuration"], "champ": me["championName"], "role": ROLE.get(pos, ""),
         "opp": opp["championName"] if opp else None, "puuid": me["puuid"][:12],
         "gold": gold, "cs": cs, "xp": xp, "level": lvl}
    if oid:
        r["gdiff"] = [a - b for a, b in zip(gold, ser(oid, lambda x: x["totalGold"]))]
        r["csdiff"] = [a - b for a, b in zip(cs, ser(oid, lambda x: x["minionsKilled"] + x["jungleMinionsKilled"]))]
        r["xpdiff"] = [a - b for a, b in zip(xp, ser(oid, lambda x: x["xp"]))]
    ev = [e for f in fr for e in f["events"]]
    buys = []
    for e in ev:
        if e["type"] == "ITEM_PURCHASED" and e.get("participantId") == pid:
            buys.append([e["timestamp"] / 1000, e["itemId"]])
        elif e["type"] == "ITEM_UNDO" and e.get("participantId") == pid:
            for b in reversed(buys):
                if b[1] == e.get("beforeId"):
                    buys.remove(b)
                    break
    backs = []
    for t, i in buys:
        if t < 120:
            continue
        if backs and t - backs[-1]["end"] < 40:
            backs[-1]["items"].append(i); backs[-1]["end"] = t
        else:
            backs.append({"t": t, "end": t, "items": [i]})
    r6 = lambda who: next((e["timestamp"] / 1000 for e in ev if e["type"] == "SKILL_LEVEL_UP" and e.get("participantId") == who and e.get("skillSlot") == 4), None)
    deaths = [e for e in ev if e["type"] == "CHAMPION_KILL" and e.get("victimId") == pid]
    jg_in = lambda e: jg and (e.get("killerId") == jg["participantId"] or jg["participantId"] in (e.get("assistingParticipantIds") or []))
    comp = [(round(t), i) for t, i in buys if legendary(i)]
    ch = me.get("challenges", {})
    arm = mr = 0
    for p in parts:
        if p["teamId"] == me["teamId"]:
            continue
        its = [p["item%d" % k] for k in range(6)]
        arm += sum(stat(i, "FlatArmorMod") for i in its) >= 80
        mr += sum(stat(i, "FlatSpellBlockMod") for i in its) >= 80
    a, b = r6(pid), (r6(oid) if oid else None)
    # When each side reached levels 2, 3 and 6 (seconds; negative gap = this player got there first).
    up = lambda who, n: next((e["timestamp"] / 1000 for e in ev if e["type"] == "LEVEL_UP" and e.get("participantId") == who and e.get("level") == n), None)
    for n_ in (2, 3, 6):
        x, y = up(pid, n_), (up(oid, n_) if oid else None)
        r["lvl%d_race" % n_] = round(x - y, 1) if x and y else None
    r.update({
        "first_back": round(backs[0]["t"]) if backs else None,
        "first_back_gold": sum(cost(i) for i in backs[0]["items"]) if backs else None,
        "backs_before_14": sum(1 for x in backs if x["t"] < 840),
        "boots": next((round(t) for t, i in buys if boots(i)), None),
        "legendary1": comp[0][0] if comp else None, "legendary2": comp[1][0] if len(comp) > 1 else None,
        "items": comp[:6],
        "lvl6_gap": round(a - b) if a and b else None,
        "death_t": [round(e["timestamp"] / 1000) for e in deaths],
        "deaths": len(deaths), "deaths_14": sum(1 for e in deaths if e["timestamp"] < 840000),
        "deaths_14_jg": sum(1 for e in deaths if e["timestamp"] < 840000 and jg_in(e)),
        "kills_14": sum(1 for e in ev if e["type"] == "CHAMPION_KILL" and e.get("killerId") == pid and e["timestamp"] < 840000),
        "time_dead": me.get("totalTimeSpentDead"), "kp": ch.get("killParticipation"), "dmg_share": ch.get("teamDamagePercentage"),
        "vision_pm": ch.get("visionScorePerMinute"), "control_wards": me.get("visionWardsBoughtInGame"),
        "armor_n": arm, "mr_n": mr,
    })
    # Setup: rune page, summoner spells, skill order, starting items and what was bought at each back.
    pk = me.get("perks") or {}
    st_ = pk.get("styles") or []
    if len(st_) >= 2:
        sp = pk.get("statPerks") or {}
        r["runes"] = [st_[0]["style"], st_[1]["style"], [x["perk"] for x in st_[0]["selections"]] + [x["perk"] for x in st_[1]["selections"]],
                      [sp.get("offense"), sp.get("flex"), sp.get("defense")]]
    r["spells"] = sorted([me.get("summoner1Id"), me.get("summoner2Id")])
    r["skills"] = [e["skillSlot"] for e in ev if e["type"] == "SKILL_LEVEL_UP" and e.get("participantId") == pid and e.get("levelUpType", "NORMAL") == "NORMAL"][:18]
    r["start"] = sorted(i for t, i in buys if t < 120)
    r["back_buys"] = [[round(x["t"]), x["items"]] for x in backs[:6]]
    if pos == "JUNGLE":
        r["jg"] = jungle(m, tl, me)
    if oid:
        r.update(by_level(tl, pid, oid))
    return r


def _q(v):
    v = [x for x in v if x is not None]
    if len(v) < 4:
        return None
    qs = S.quantiles(v, n=4)
    return [round(qs[0], 1), round(S.median(v), 1), round(qs[2], 1), len(v)]


TIMINGS = ("first_back", "first_back_gold", "backs_before_14", "boots", "legendary1", "legendary2", "lvl6_gap", "deaths",
           "deaths_14", "deaths_14_jg", "kills_14", "time_dead", "kp", "dmg_share", "vision_pm", "control_wards")


def aggregate(rows, source, built):
    n = len(rows)
    out = {"champion": rows[0]["champ"], "role": rows[0]["role"], "games": n, "winrate": round(sum(r["win"] for r in rows) / n, 3),
           "players": len({r["puuid"] for r in rows}), "regions": sorted({r.get("region") for r in rows if r.get("region")}),
           "built": built, "source": source, "minutes": {}, "timings": {}, "items": [], "orders": [],
           "opponents": Counter(r["opp"] for r in rows if r["opp"]).most_common(10)}
    for k in ("gold", "cs", "xp", "level", "gdiff", "csdiff", "xpdiff"):
        out["minutes"][k] = [_q([r[k][m] for r in rows if r.get(k) and len(r[k]) > m]) for m in range(31)]
    for k in TIMINGS:
        out["timings"][k] = _q([r.get(k) for r in rows])
    # Deaths per game in each 5-minute block (the last is 30+), among games that lasted into that block.
    timed = [r for r in rows if "death_t" in r]
    if len(timed) >= 20:
        out["deaths_by5"] = []
        for i in range(7):
            lo, hi = i * 300, (10 ** 9 if i == 6 else (i + 1) * 300)
            games = [r for r in timed if r["dur"] > lo]
            out["deaths_by5"].append(round(sum(sum(1 for t in r["death_t"] if lo <= t < hi) for r in games) / len(games), 3) if len(games) >= 10 else None)
    slot, when = defaultdict(list), defaultdict(list)
    for r in rows:
        for n_, (t, i) in enumerate(r["items"][:5]):
            slot[i].append(n_ + 1); when[i].append(t)
    for i in sorted(slot, key=lambda i: -len(slot[i])):
        if len(slot[i]) < 3:
            continue
        by = defaultdict(lambda: [0, 0])
        for r in rows:
            got = any(x == i for _, x in r["items"][:5])
            for key in ("armor%d" % min(r["armor_n"], 2), "mr%d" % min(r["mr_n"], 2)):
                by[key][1] += 1
                by[key][0] += got
        out["items"].append({"id": i, "name": items().get(str(i), {}).get("name"), "rate": round(len(slot[i]) / n, 3),
                             "slot": S.median(slot[i]), "time": round(S.median(when[i])),
                             "slots": dict(Counter(slot[i])), "by": {k: list(v) for k, v in by.items()}})
        if len(out["items"]) >= 30:
            break
    out["orders"] = [[list(k), c] for k, c in Counter(tuple(i for _, i in r["items"][:3]) for r in rows if len(r["items"]) >= 3).most_common(6)]
    out["paths"] = full_paths(rows)
    out["levels"] = level_races(rows)
    out["setup"] = setup(rows)
    out["matchups"] = matchups(rows)
    out["by_level"] = level_summary(rows)
    by = defaultdict(list)
    for r in rows:
        if r.get("opp") and r.get("lane_fights") is not None:
            by[r["opp"]].append(r)
    for o, rs in by.items():   # per opponent, only with plenty of lane fights
        if len(rs) >= 15 and o in out["matchups"]:
            out["matchups"][o]["by_level"] = level_summary(rs, min_fights=8)
    if rows and rows[0].get("role") == "JUNGLE":
        out["jungle"] = jungle_summary(rows)
    return out


def area(p):
    """Rough map area of a position: top/mid/bot lane, own or enemy jungle is decided by the caller."""
    x, y = p["x"], p["y"]
    if x < 3600 and y < 3600 or x > 11200 and y > 11200:
        return "base"
    if x < 2400 or y > 12400:
        return "top"
    if y < 2400 or x > 12400:
        return "bot"
    if abs(x - y) < 1600:
        return "mid"
    if abs(x + y - 14800) < 1300:
        return "river"
    return "jungle"


def jungle(m, tl, me):
    """How a jungler played the first 14 minutes: clear speed, start side, where they spent time,
    ganks (takedowns and deaths in each lane), invades, scuttles and objectives."""
    pid, team = me["participantId"], me["teamId"]
    fr, ev = tl["frames"], [e for f in tl["frames"] for e in f["events"]]
    pf = lambda k, i: fr[min(k, len(fr) - 1)]["participantFrames"][str(i)]
    pos = lambda k: pf(k, pid).get("position") or {"x": 7400, "y": 7400}
    own = lambda p: (p["x"] + p["y"] < 14800) == (team == 100)   # own half of the map (split along the river)
    j = {"jcs": [pf(k, pid)["jungleMinionsKilled"] for k in range(0, min(len(fr), 15))]}
    p2 = pos(2)
    j["start"] = "top" if p2["y"] - p2["x"] > 0 else "bot"   # which side of the map they were on at 2:00
    j["where"] = {}
    for k in range(2, min(len(fr), 15)):
        a = area(pos(k))
        if a == "jungle":
            a = "own jungle" if own(pos(k)) else "enemy jungle"
        j["where"][a] = j["where"].get(a, 0) + 1
    j["first_lane"] = next(([k, area(pos(k))] for k in range(2, min(len(fr), 15)) if area(pos(k)) in ("top", "mid", "bot")), None)
    gank = {}
    for e in ev:
        if e["type"] != "CHAMPION_KILL" or e["timestamp"] > 840000:
            continue
        a = area(e["position"])
        if a not in ("top", "mid", "bot"):
            continue
        g = gank.setdefault(a, [0, 0])
        if e.get("killerId") == pid or pid in (e.get("assistingParticipantIds") or []):
            g[0] += 1
        elif e.get("victimId") == pid:
            g[1] += 1
    j["ganks"] = gank   # lane -> [takedowns, deaths] before 14:00
    j["first_takedown"] = next((round(e["timestamp"] / 1000) for e in ev if e["type"] == "CHAMPION_KILL" and
                                (e.get("killerId") == pid or pid in (e.get("assistingParticipantIds") or []))), None)
    ch = me.get("challenges") or {}
    j["scuttles"] = ch.get("scuttleCrabKills")
    j["enemy_camps"] = ch.get("enemyJungleMonsterKills")
    j["jcs10"] = ch.get("jungleCsBefore10Minutes")
    objs = {}
    for e in ev:
        if e["type"] == "ELITE_MONSTER_KILL" and e["timestamp"] <= 840000 and (e.get("killerTeamId") == team or
                any(p["participantId"] == e.get("killerId") and p["teamId"] == team for p in m["participants"])):
            objs[e["monsterType"]] = objs.get(e["monsterType"], 0) + 1
    j["objs14"] = objs
    return j


def jungle_summary(rows):
    """Expert jungle habits for one champion: clear speed, start side, time in each area, ganks per lane."""
    js = [r["jg"] for r in rows if r.get("jg")]
    if len(js) < 10:
        return None
    med = lambda v: round(S.median(v), 1) if v else None
    n = len(js)
    areas = ("own jungle", "enemy jungle", "river", "top", "mid", "bot", "base")
    lanes = ("top", "mid", "bot")
    return {
        "n": n,
        "jcs": [med([j["jcs"][k] for j in js if len(j["jcs"]) > k]) for k in range(15)],
        "start_top": round(sum(1 for j in js if j["start"] == "top") / n, 2),
        "where": {a: round(S.mean(j["where"].get(a, 0) for j in js), 2) for a in areas},
        "first_lane": Counter(j["first_lane"][1] for j in js if j.get("first_lane")).most_common(),
        "first_lane_min": med([j["first_lane"][0] for j in js if j.get("first_lane")]),
        "first_takedown": med([j["first_takedown"] for j in js if j.get("first_takedown")]),
        "ganks": {l: [round(S.mean(j["ganks"].get(l, [0, 0])[0] for j in js), 2), round(S.mean(j["ganks"].get(l, [0, 0])[1] for j in js), 2)] for l in lanes},
        "scuttles": med([j["scuttles"] for j in js if j.get("scuttles") is not None]),
        "enemy_camps": med([j["enemy_camps"] for j in js if j.get("enemy_camps") is not None]),
        "objs14": {k: round(S.mean(j["objs14"].get(k, 0) for j in js), 2) for k in ("DRAGON", "HORDE", "RIFTHERALD")},
    }


def by_level(tl, pid, oid):
    """Lane fighting by level, before 14:00: damage each side did to champions in each minute (keyed by this
    player's level at the end of it), and every fight with the lane opponent: this player's level then, +1 a kill
    or assist on the opponent, -1 a death with the opponent in on it."""
    fr = tl["frames"]
    ev = [e for f in fr for e in f["events"]]
    dmg = {}
    for k in range(1, min(len(fr), 15)):
        a, b = fr[k - 1]["participantFrames"], fr[k]["participantFrames"]
        d = lambda i: (b[str(i)].get("damageStats") or {}).get("totalDamageDoneToChampions", 0) - (a[str(i)].get("damageStats") or {}).get("totalDamageDoneToChampions", 0)
        lv = b[str(pid)]["level"]
        x = dmg.setdefault(str(lv), [0, 0, 0])
        x[0] += d(pid); x[1] += d(oid); x[2] += 1
    ups = sorted((e["timestamp"], e["level"]) for e in ev if e["type"] == "LEVEL_UP" and e.get("participantId") == pid)
    level_at = lambda t: max([L for tt, L in ups if tt <= t] or [1])
    fights = []
    for e in ev:
        if e["type"] != "CHAMPION_KILL" or e["timestamp"] >= 840000:
            continue
        helpers = e.get("assistingParticipantIds") or []
        if e.get("victimId") == oid and (e.get("killerId") == pid or pid in helpers):
            fights.append([level_at(e["timestamp"]), 1])
        elif e.get("victimId") == pid and (e.get("killerId") == oid or oid in helpers):
            fights.append([level_at(e["timestamp"]), -1])
    return {"lv_dmg": dmg, "lane_fights": fights}


def level_summary(rows, min_fights=12):
    """Per level 1-11: lane kills and deaths against the lane opponent, and median damage per minute each way."""
    out = {}
    for lv in range(1, 12):
        k = d = 0
        mine, theirs = [], []
        for r in rows:
            for L, res in r.get("lane_fights") or []:
                if L == lv:
                    k += res > 0; d += res < 0
            x = (r.get("lv_dmg") or {}).get(str(lv))
            if x and x[2]:
                mine.append(x[0] / x[2]); theirs.append(x[1] / x[2])
        if k + d >= min_fights or len(mine) >= 20:
            out[str(lv)] = {"kills": k, "deaths": d, "dmg": round(S.median(mine)) if mine else None,
                            "opp_dmg": round(S.median(theirs)) if theirs else None, "n": len(mine)}
    return out


def matchups(rows, min_games=8):
    """How the lane usually goes against each opponent: win rate, gold/CS/XP lead at 10 and 15,
    kills and deaths before 14:00, first back, and who reaches level 2 and 3 first."""
    by = defaultdict(list)
    for r in rows:
        if r.get("opp") and r.get("gdiff"):
            by[r["opp"]].append(r)
    med = lambda v: round(S.median(v)) if v else None
    at = lambda rs, k, m: med([r[k][m] for r in rs if len(r.get(k) or []) > m])
    out = {}
    for o, rs in by.items():
        if len(rs) < min_games:
            continue
        races = lambda n: [r["lvl%d_race" % n] for r in rs if r.get("lvl%d_race" % n) is not None]
        out[o] = {"n": len(rs), "win": round(sum(1 for r in rs if r["win"]) / len(rs), 2),
                  "gd": [at(rs, "gdiff", m) for m in range(16)],
                  "gd10": at(rs, "gdiff", 10), "gd15": at(rs, "gdiff", 15), "csd10": at(rs, "csdiff", 10), "xpd10": at(rs, "xpdiff", 10),
                  "deaths14": round(S.mean(r.get("deaths_14", 0) for r in rs), 2), "kills14": round(S.mean(r.get("kills_14", 0) for r in rs), 2),
                  "first_back": med([r["first_back"] for r in rs if r.get("first_back")]),
                  "lvl2_first": round(sum(1 for x in races(2) if x < -3) / len(races(2)), 2) if races(2) else None,
                  "lvl3_first": round(sum(1 for x in races(3) if x < -3) / len(races(3)), 2) if races(3) else None}
    return out


def max_order(seq):
    """'QEW': the order Q, W and E reach rank 5 (ranks past what the game allows count as maxed)."""
    n, done = {1: 0, 2: 0, 3: 0}, []
    for s_ in seq:
        if s_ in n:
            n[s_] += 1
            if n[s_] == 5 and s_ not in done:
                done.append(s_)
    rest = sorted((k for k in n if k not in done), key=lambda k: -n[k])
    return "".join("QWE"[k - 1] for k in done + rest)


def setup(rows, top=3, min_vs=8):
    """Most common rune pages, spells, skill orders, starting items and per-back buys, overall and vs each
    opponent with enough games. Rates are shares of the games that had that data."""
    def pages(rs):
        c = Counter(json.dumps(r["runes"]) for r in rs if r.get("runes"))
        n = sum(c.values())
        return [{"page": json.loads(k), "rate": round(v / n, 3), "n": v} for k, v in c.most_common(top)] if n else []
    def recommended(rs):
        """A full page built slot by slot: most common styles and keystone, then the most common pick in each
        slot among games with those (full pages vary too much in small runes to take the single most common)."""
        rs = [r for r in rs if r.get("runes")]
        if len(rs) < 5:
            return None
        ks = Counter(r["runes"][2][0] for r in rs).most_common(1)[0][0]
        with_ks = [r for r in rs if r["runes"][2][0] == ks]
        styles = Counter((r["runes"][0], r["runes"][1]) for r in with_ks).most_common(1)[0][0]
        same = [r for r in with_ks if (r["runes"][0], r["runes"][1]) == styles]
        mode = lambda vals: Counter(vals).most_common(1)[0][0]
        prim = [mode(r["runes"][2][i] for r in same) for i in range(4)]
        sec = list(mode(tuple(sorted(r["runes"][2][4:6])) for r in same))
        shards = [mode(r["runes"][3][i] for r in same) for i in range(3)]
        return {"page": [styles[0], styles[1], prim + sec, shards], "keystone_rate": round(len(with_ks) / len(rs), 3), "n": len(same)}
    def keystones(rs):
        c = Counter(r["runes"][2][0] for r in rs if r.get("runes"))
        n = sum(c.values())
        return [[k, round(v / n, 3)] for k, v in c.most_common(4)] if n else []
    def spells(rs):
        c = Counter(tuple(r["spells"]) for r in rs if r.get("spells") and None not in r["spells"])
        n = sum(c.values())
        return [[list(k), round(v / n, 3)] for k, v in c.most_common(top)] if n else []
    def skills(rs):
        seqs = [r["skills"] for r in rs if len(r.get("skills") or []) >= 9]
        if not seqs:
            return None
        c = Counter(max_order(q) for q in seqs)
        best, k = c.most_common(1)[0]
        same = [q for q in seqs if max_order(q) == best]
        typical = []
        for lv in range(18):   # most common skill at each level among games with that max order
            at = Counter(q[lv] for q in same if len(q) > lv)
            if not at:
                break
            typical.append(at.most_common(1)[0][0])
        return {"order": best, "rate": round(k / len(seqs), 3), "others": [[o, round(v / len(seqs), 3)] for o, v in c.most_common(3)[1:]], "typical": typical}
    def starts(rs):
        c = Counter(tuple(r["start"]) for r in rs if r.get("start"))
        n = sum(c.values())
        return [[list(k), round(v / n, 3)] for k, v in c.most_common(2)] if n else []
    def backs(rs):
        out = []
        for b in range(5):
            have = [r["back_buys"][b] for r in rs if len(r.get("back_buys") or []) > b]
            if len(have) < 15:
                break
            c = Counter(i for t, items in have for i in set(items))
            out.append({"t": round(S.median(t for t, _ in have)), "n": len(have),
                        "items": [[i, round(v / len(have), 2)] for i, v in c.most_common(6) if v / len(have) >= 0.15]})
        return out
    out = {"rec": recommended(rows), "pages": pages(rows), "keystones": keystones(rows), "spells": spells(rows), "skills": skills(rows),
           "start": starts(rows), "backs": backs(rows)}
    by = defaultdict(list)
    for r in rows:
        if r.get("opp") and r.get("runes"):
            by[r["opp"]].append(r)
    out["vs"] = {o: {"n": len(rs), "rec": recommended(rs), "spells": spells(rs)[:1], "keystones": keystones(rs)[:2]}
                 for o, rs in by.items() if len(rs) >= min_vs}
    return out


def level_races(rows, even=3):
    """How often these players reach levels 2, 3 and 6 before their lane opponent ("first"), or within 3s of
    them ("even"). "by" has the same for the opponents with 8+ games: champion -> [first, even, games]."""
    out = {}
    for n_ in (2, 3, 6):
        k = "lvl%d_race" % n_
        have = [r for r in rows if r.get(k) is not None]
        if len(have) < 20:
            continue
        rate = lambda rs: [round(sum(1 for r in rs if r[k] < -even) / len(rs), 3), round(sum(1 for r in rs if abs(r[k]) <= even) / len(rs), 3), len(rs)]
        f, e, c = rate(have)
        by = defaultdict(list)
        for r in have:
            if r.get("opp"):
                by[r["opp"]].append(r)
        out[str(n_)] = {"first": f, "even": e, "n": c, "by": {o: rate(rs) for o, rs in by.items() if len(rs) >= 8}}
    return out


def full_paths(rows, top=3):
    """The most common first-3-item paths, carried on to a full build. Few games reach a 4th item, so items 4-6
    come from the games that shared at least 2 of the path's first 3 items and got that far: the items they most
    often bought 4th-6th (in 20%+ of them), in the order they usually came. "rates" is that share; "late" is how
    many games it's based on."""
    paths = []
    for first3, c in Counter(tuple(i for _, i in r["items"][:3]) for r in rows if len(r["items"]) >= 3).most_common(top):
        base = set(first3)
        late = [r for r in rows if len(r["items"]) >= 4 and len(base & {i for _, i in r["items"][:3]}) >= 2]
        count, slots = Counter(), defaultdict(list)
        for r in late:
            for n_, (_, i) in enumerate(r["items"][3:6]):
                if i not in base:
                    count[i] += 1; slots[i].append(n_ + 4)
        nxt = [(i, k) for i, k in count.most_common(3) if k >= max(3, 0.2 * len(late))]
        nxt.sort(key=lambda x: S.median(slots[x[0]]))
        paths.append({"items": list(first3) + [i for i, _ in nxt], "games": c, "late": len(late),
                      "rates": [round(k / len(late), 2) for _, k in nxt]})
    return paths

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
    r.update({
        "first_back": round(backs[0]["t"]) if backs else None,
        "first_back_gold": sum(cost(i) for i in backs[0]["items"]) if backs else None,
        "backs_before_14": sum(1 for x in backs if x["t"] < 840),
        "boots": next((round(t) for t, i in buys if boots(i)), None),
        "legendary1": comp[0][0] if comp else None, "legendary2": comp[1][0] if len(comp) > 1 else None,
        "items": comp[:6],
        "lvl6_gap": round(a - b) if a and b else None,
        "deaths": len(deaths), "deaths_14": sum(1 for e in deaths if e["timestamp"] < 840000),
        "deaths_14_jg": sum(1 for e in deaths if e["timestamp"] < 840000 and jg_in(e)),
        "kills_14": sum(1 for e in ev if e["type"] == "CHAMPION_KILL" and e.get("killerId") == pid and e["timestamp"] < 840000),
        "time_dead": me.get("totalTimeSpentDead"), "kp": ch.get("killParticipation"), "dmg_share": ch.get("teamDamagePercentage"),
        "vision_pm": ch.get("visionScorePerMinute"), "control_wards": me.get("visionWardsBoughtInGame"),
        "armor_n": arm, "mr_n": mr,
    })
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
    return out

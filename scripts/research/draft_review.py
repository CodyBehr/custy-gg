"""
Coach draft review of one lane, built from the building blocks the user's VOD reviews taught us. Facts only come
from data: the replay (hits, casts, summoner spells, positions, minion waves) and Riot's timeline (level-ups, skill
choices, items, per-minute health and kills). Each flagged moment says what happened and why it may matter; the user
grades it.

  python3 draft_review.py <gameId> <me champion> <opp champion> [until seconds] > draft.json

Needs the replay (/mnt/user-data/uploads/Replays/NA1-<id>.rofl) and the timeline (/home/claude/riot/matches).
"""

import gzip
import json
import math
import sys

sys.path.insert(0, "/home/claude/custy-gg/collector")
import replay_trades as RT  # noqa: E402
import replay_waves as W  # noqa: E402

SUMM = {"363fad": "Flash", "78ed5b": "Teleport", "22568a": "Ignite", "cbb9e2": "Heal", "96b4e4": "Barrier",
        "f62bbf": "Exhaust", "993dca": "Ghost"}
SUMM_ID = {4: "Flash", 14: "Ignite", 6: "Ghost", 12: "Teleport", 7: "Heal", 21: "Barrier", 3: "Exhaust", 11: "Smite", 1: "Cleanse"}
SUMM_CD = {"Flash": 300, "Ignite": 180, "Ghost": 210, "Teleport": 330, "Heal": 240, "Barrier": 180, "Exhaust": 210, "Cleanse": 210}
KEY = {"Darius": "E", "Garen": "Q"}            # the ability each side least wants to have down in a trade
SLOT = {1: "Q", 2: "W", 3: "E", 4: "R"}
TOWERS = {100: (981, 10441), 200: (4318, 13875)}   # outer top towers (blue, red)


def clock(t):
    return "%d:%02d" % (int(t) // 60, int(t) % 60)


def summoner_casts(path, until):
    _v, _s, chunks = RT.read_rofl(path)
    out = []
    for body in chunks:
        for t, nid, prm, pl in RT._blocks(body):
            if t > until:
                break
            if nid == 1131 and prm in RT.CHAMPS:
                b = bytes(pl)
                q = b.find(RT.CAST_MARK)
                name = SUMM.get(b[q + 4:q + 7].hex()) if q >= 0 else None
                if name:
                    out.append((t, RT.CHAMPS.index(prm), name))
    return out


def main(gid, me_c, opp_c, until=600.0):
    path = "/mnt/user-data/uploads/Replays/NA1-%s.rofl" % gid
    g = json.load(gzip.open("/home/claude/riot/matches/NA1_%s.json.gz" % gid))
    m, tl = g["match"]["info"], g["timeline"]["info"]
    parts = {p["participantId"]: p for p in m["participants"]}
    pid = {p["championName"]: p["participantId"] for p in m["participants"]}
    d = RT.decode(path, until=until + 30)
    skins = [s["SKIN"] for s in d["stats"]]
    me, opp = skins.index(me_c), skins.index(opp_c)
    pme, popp = pid[me_c], pid[opp_c]
    slot_of_pid = {pid[s]: k for k, s in enumerate(skins) if s in pid}

    # --- Riot timeline facts
    lvl = {pme: [0.0], popp: [0.0]}
    skills = {pme: [], popp: []}
    items = {pme: [], popp: []}
    kills = []
    for f in tl["frames"]:
        for e in f["events"]:
            t = e["timestamp"] / 1000
            if t > until + 30:
                continue
            p = e.get("participantId")
            if e["type"] == "LEVEL_UP" and p in lvl:
                lvl[p].append(t)
            elif e["type"] == "SKILL_LEVEL_UP" and p in skills:
                skills[p].append((t, SLOT.get(e["skillSlot"], "?")))
            elif e["type"] == "ITEM_PURCHASED" and p in items:
                items[p].append((t, e["itemId"]))
            elif e["type"] == "CHAMPION_KILL":
                kills.append({"t": t, "victim": slot_of_pid.get(e["victimId"]), "killer": slot_of_pid.get(e.get("killerId")),
                              "assists": [slot_of_pid.get(a) for a in e.get("assistingParticipantIds") or []],
                              "pos": (e["position"]["x"], e["position"]["y"])})
    level = lambda p, t: sum(1 for x in lvl[p] if x <= t)
    frames = []
    for f in tl["frames"]:
        a, b = f["participantFrames"][str(pme)], f["participantFrames"][str(popp)]
        frames.append({"t": f["timestamp"] / 1000, "me": [a["championStats"]["health"], a["championStats"]["healthMax"]],
                       "opp": [b["championStats"]["health"], b["championStats"]["healthMax"]]})
    hpa = {}
    for k, s in enumerate(skins):
        pp = str(pid[s])
        hpa[k] = [(f["timestamp"] / 1000, f["participantFrames"][pp]["championStats"]["health"],
                   f["participantFrames"][pp]["championStats"]["healthMax"]) for f in tl["frames"]]
    dl = {}
    for x in kills:
        dl.setdefault(x["victim"], []).append(x["t"])
    my_sums = [SUMM_ID.get(parts[pme]["summoner1Id"]), SUMM_ID.get(parts[pme]["summoner2Id"])]
    op_sums = [SUMM_ID.get(parts[popp]["summoner1Id"]), SUMM_ID.get(parts[popp]["summoner2Id"])]
    runes = {k: parts[p]["perks"]["styles"][0]["selections"][0]["perk"] for k, p in (("me", pme), ("opp", popp))}

    # --- replay facts
    sc = summoner_casts(path, until + 30)
    def sums_up(k, have, t):
        out = []
        for s in have:
            last = max([x for x, kk, n in sc if kk == k and n == s and x <= t], default=None)
            out.append((s, last is None or t - last >= SUMM_CD.get(s, 300), round(SUMM_CD.get(s, 300) - (t - last)) if last is not None and t - last < SUMM_CD.get(s, 300) else 0))
        return out
    de = W.unit_deaths(path, until + 30)
    mins = W.minions(d, de)
    tr = RT.lane_trades(path, me, opp, frames, {"me": dl.get(me, []), "opp": dl.get(opp, [])}, hpa=hpa, deaths_all=dl)
    casts = d["casts"]
    hits = d["hits"]

    def near_minions(x, z, t, r=1100):
        c = {100: 0, 200: 0}
        for mm in mins.values():
            if mm["spawn"] > t or (mm["died"] is not None and mm["died"] <= t):
                continue
            p = RT._at(mm["track"], t)
            if p and math.hypot(p[0] - x, p[1] - z) < r:
                c[mm["team"]] += 1
        return c

    my_team = 100 if me < 5 else 200
    out = {"game": gid, "me": me_c, "opp": opp_c, "mySums": my_sums, "oppSums": op_sums, "runes": runes,
           "levels": {"me": [round(x, 1) for x in lvl[pme][1:7]], "opp": [round(x, 1) for x in lvl[popp][1:7]]},
           "skills": {"me": [s for t, s in skills[pme][:6]], "opp": [s for t, s in skills[popp][:6]]},
           "items": {"me": [(round(t), i) for t, i in items[pme] if t < until], "opp": [(round(t), i) for t, i in items[popp] if t < until]},
           "moments": []}

    # level race (2 and 3)
    for L in (2, 3):
        a, b = lvl[pme][L - 1] if len(lvl[pme]) >= L else None, lvl[popp][L - 1] if len(lvl[popp]) >= L else None
        if a and b:
            out["moments"].append({"t": min(a, b), "kind": "level race", "L": L,
                                   "first": "me" if a < b else "opp", "gap": round(abs(a - b), 1),
                                   "meAt": round(a, 1), "oppAt": round(b, 1),
                                   "skill": {"me": next((s for t, s in skills[pme] if abs(t - a) < 60 and t >= a - 0.5), None),
                                             "opp": next((s for t, s in skills[popp] if abs(t - b) < 60 and t >= b - 0.5), None)}})

    # trades
    for x in tr["trades"]:
        if x["t0"] > until:
            continue
        t0, t1 = x["t0"], x["t1"]
        pm = RT._at(d["tracks"][me], t0) or (0, 0)
        po = RT._at(d["tracks"][opp], t0) or (0, 0)
        cx, cz = (pm[0] + po[0]) / 2, (pm[1] + po[1]) / 2
        nm = near_minions(cx, cz, t0)
        mt = TOWERS[my_team]; ot = TOWERS[300 - my_team]
        net_me = x["dealt"] - x["took"]
        mx = (x["hpMe"][1] or 1, x["hpOpp"][1] or 1)
        mo = {"t": t0, "end": t1, "kind": "trade", "solo": x["solo"], "first": x["first"], "seq": x["seq"],
              "dealt": x["dealt"], "took": x["took"], "netPct": round(100 * (x["dealt"] / mx[1] - x["took"] / mx[0])),
              "hpMe": x["hpMe"], "hpOpp": x["hpOpp"], "lv": [level(pme, t0), level(popp, t0)],
              "died": x["died"], "others": [o["champ"] for o in x["others"]],
              "minions": {"mine": nm[my_team], "theirs": nm[300 - my_team]},
              "toMyTower": round(math.hypot(cx - mt[0], cz - mt[1])), "toTheirTower": round(math.hypot(cx - ot[0], cz - ot[1])),
              "sumsMe": sums_up(me, my_sums, t0), "sumsOpp": sums_up(opp, op_sums, t0), "flags": []}
        # level-up during the trade
        for p, who in ((pme, "me"), (popp, "opp")):
            for lt in lvl[p][1:]:
                if t0 - 0.5 <= lt <= t1 + 0.5:
                    mo["flags"].append({"f": "levels mid-fight", "who": who, "to": level(p, lt), "at": round(lt, 1)})
        # free poke: one side hit, the other gave nothing back
        if x["took"] >= 40 and x["dealt"] < 10:
            mo["flags"].append({"f": "free poke taken", "dmg": x["took"]})
        if x["dealt"] >= 40 and x["took"] < 10:
            mo["flags"].append({"f": "free poke landed", "dmg": x["dealt"]})
        # key ability used on the wave shortly before they engaged
        if x["first"] == "them":
            for t, k, L in casts:
                if k == me and t0 - 8 <= t < t0 - 0.3 and L in ("Q", "E"):
                    hit = any(a == me and tg == opp and t <= ht <= t + 3 for ht, tg, a, v in hits)
                    if not hit:
                        mo["flags"].append({"f": "ability used on the wave, then they engaged", "ability": L, "at": round(t, 1)})
        # their key ability down when they started
        for t, k, L in casts:
            if k == opp and L == KEY.get(opp_c) and t0 - 24 <= t < t0 - 2:
                mo["flags"].append({"f": "their key ability was on cooldown", "ability": L, "since": round(t, 1)})
                break
        out["moments"].append(mo)

    # deaths in lane
    for x in kills:
        if x["t"] > until or x["victim"] not in (me, opp):
            continue
        k = x["victim"]
        p = RT._at(d["tracks"][k], x["t"] - 0.5) or x["pos"]
        nm = near_minions(p[0], p[1], x["t"] - 3)
        team = 100 if k < 5 else 200
        out["moments"].append({"t": x["t"], "kind": "death", "who": "me" if k == me else "opp",
                               "killer": skins[x["killer"]] if x["killer"] is not None else "minions/tower",
                               "assists": [skins[a] for a in x["assists"] if a is not None],
                               "lv": [level(pme, x["t"]), level(popp, x["t"])],
                               "sumsMe": sums_up(me, my_sums, x["t"] - 1), "sumsOpp": sums_up(opp, op_sums, x["t"] - 1),
                               "sumsUsed": [(round(t, 1), skins[kk], n) for t, kk, n in sc if kk in (me, opp) and x["t"] - 15 <= t <= x["t"]],
                               "minions": {"theirTeam": nm[300 - team], "ownTeam": nm[team]},
                               "toOwnTower": round(math.hypot(p[0] - TOWERS[team][0], p[1] - TOWERS[team][1]))})
    out["moments"].sort(key=lambda z: z["t"])
    out["sumCasts"] = [(round(t, 1), skins[k], n) for t, k, n in sc if k in (me, opp)]
    return out


if __name__ == "__main__":
    a = sys.argv
    print(json.dumps(main(a[1], a[2], a[3], float(a[4]) if len(a) > 4 else 600.0), indent=1, default=str))

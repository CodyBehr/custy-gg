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
KEY = {"Darius": "E", "Garen": "Q"}
RUNE = {8010: "Conqueror", 8230: "Stormraider's Surge", 8005: "Press the Attack", 8021: "Fleet Footwork", 8437: "Grasp",
        8439: "Aftershock", 8465: "Guardian", 8112: "Electrocute", 8214: "Aery", 8229: "Arcane Comet", 9923: "Hail of Blades",
        8128: "Dark Harvest", 8351: "Glacial", 8360: "Unsealed Spellbook", 8369: "First Strike", 8473: "Bone Plating",
        8275: "Nimbus Cloak", 8444: "Second Wind", 8299: "Last Stand", 9111: "Triumph"}            # the ability each side least wants to have down in a trade
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


def reads(out):
    """The coach's read of each moment, from general rules (the reviewer's lessons, games 1-2). No champion names."""
    R = []
    mom = out["moments"]
    trades = [m for m in mom if m["kind"] == "trade"]
    for m in mom:
        t = clock(m["t"])
        if m["kind"] == "level race":
            if m["first"] == "opp" and m["gap"] > 3:
                lost = [x for x in trades if x["t"] < m["oppAt"] and x["netPct"] <= -8 and x["solo"]]
                why = (" Likely caused by the lost trade at %s: you gave up the push and they controlled the wave." % clock(lost[-1]["t"])) if lost else ""
                R.append((t, "level race", "context" if lost else "check", "Level %d: they were %.0fs earlier.%s" % (m["L"], m["gap"], why)))
            continue
        if m["kind"] == "death":
            if m["who"] == "me" and m.get("laneLead", 0) >= 2 and len(m["assists"]) >= 1:
                R.append((t, "death", "meh", "Died to %d enemies with a %d-kill lead: unnecessary risk, and a shutdown." % (1 + len(m["assists"]), m["laneLead"])))
            continue
        if m["kind"] != "trade":
            continue
        st, f = m["state"], {x["f"] for x in m["flags"]}
        behind = st["deathsGap"] >= 2 or (st["levelGap"] <= -1 and st["itemGoldGap"] <= -700)
        ahead = st["deathsGap"] <= -2 or st["levelGap"] >= 1 and st["itemGoldGap"] >= 700
        dur = m["end"] - m["t"]
        win = m["biggerWave"] == "mine"
        notes, verdict = [], None
        if m.get("stillBefore") and m["first"] == "them" and "you" in m["died"]:
            verdict = "exclude"; notes.append("You were standing still in their range when they engaged. Looks idle or tilted; not a lesson.")
        elif behind and "you" not in m["died"]:
            verdict = "meh"; notes.append("You're behind (%+d deaths, %+d levels, %+d item gold): judge farming and staying alive here, not the trade." % (st["deathsGap"], st["levelGap"], st["itemGoldGap"]))
        elif m.get("theirBonePlatingUp") and dur < 6 and abs(m["netPct"]) <= 8 and not m["died"]:
            verdict = "good"; notes.append("Short trade that popped their Bone Plating; any fight in the next ~55 s is without it.")
        elif m["died"] and m.get("enemiesNear"):
            verdict = "good" if m["died"] == ["them"] else "check"
            notes.append("Their teammates were there too (%s), so this isn't judged as a 1v1 trade." % ", ".join(m["enemiesNear"]))
        elif "you" in m["died"] and "them" in m["died"]:
            verdict = "1-for-1"
            if m["minionDmg"]["me"] >= 300 and m["toTheirTower"] < 900:
                notes.append("You got the kill but died to their tower (%d tower/minion damage): was the dive worth more than the wave and plates?" % m["minionDmg"]["me"])
            else:
                notes.append("You got the kill, then died yourself: after a kill, back off toward your side instead of staying in their wave.")
        elif m["died"]:
            loser = "you" if "you" in m["died"] and "them" not in m["died"] else "them" if "them" in m["died"] and "you" not in m["died"] else None
            if loser == "you":
                gap = m["leftAtEnd"]["opp"]
                close = gap <= 0.15 * m["hpOpp"][1]
                verdict = "close" if close else "lost"
                if m.get("alliesNear"):
                    notes.append("(Your %s was nearby.)" % ", ".join(m["alliesNear"]))
                n = gap / m["avgHit"] if m["avgHit"] else None
                notes.append("They were left on ~%d HP%s." % (gap, " — about %d more of your hits would have flipped it" % max(1, math.ceil(n)) if n is not None and close else ""))
                if m["openedWithAuto"]:
                    notes.append("You opened with an auto before your first ability; that can let them space out of it.")
                unused = [n for n, up, _ in m["sumsMe"] if up and n not in m.get("sumsUsedMe", [])]
                if unused:
                    notes.append("Unused: %s." % ", ".join(unused))
            elif loser == "them":
                verdict = "good"
        their_win = st["levelGap"] <= -1 and m["biggerWave"] == "theirs"
        if st["levelGap"] >= 1 and win and m["first"] == "them":
            notes.append("They fought into your bigger wave a level down: their mistake to punish.")
            if verdict is None:
                verdict = "good" if m["netPct"] > 0 else "missed"
        if verdict is None:
            if their_win and not m["died"]:
                verdict = "meh"; notes.append("Their window (a level up, bigger wave): giving up a little here is fine.")
            elif False:
                pass
            elif st["levelGap"] >= 1 and win and m["netPct"] < 0:
                verdict = "missed"; notes.append("You were a level up with the bigger wave: your window to trade hard, not take damage.")
            elif "free poke taken" in f:
                soon = any(x for x in trades if 0 < x["t"] - m["t"] <= 60 and (x["died"] or abs(x["netPct"]) <= 10))
                verdict = "bad" if soon and not ahead else "meh"
                notes.append("Free poke taken." + (" It mattered: a close fight followed within a minute." if verdict == "bad" else " Little weight here." if ahead else ""))
            elif m["netPct"] >= 10:
                verdict = "good"
            elif m["netPct"] <= -10:
                verdict = "bad"
            else:
                verdict = "even"
        for sp in m["spike"]:
            starter = "me" if m["first"] == "you" else "opp"
            if sp["who"] == starter:
                notes.append("%s started it %.0fs before %s level %d: good timing%s." % ("You" if starter == "me" else "They", sp["secsIn"], "your" if starter == "me" else "their", sp["to"], "" if starter == "me" else " for them"))
            else:
                notes.append("%s started it %.0fs before %s level %d: %s." % ("You" if starter == "me" else "They", sp["secsIn"], "their" if sp["who"] == "opp" else "your", sp["to"], "risky" if starter == "me" else "their mistake"))
        if "ability used on the wave, then they engaged" in f:
            notes.append("Ability on the wave, then they engaged: commit to crashing and recalling, or to fighting; not in between.")
        if m["minionDmg"]["me"] + m["minionDmg"]["opp"] >= 60:
            notes.append("Minions/towers: %d to you, %d to them." % (m["minionDmg"]["me"], m["minionDmg"]["opp"]))
        R.append((t, "trade" if m["solo"] else "fight (others near)", verdict, " ".join(notes) or "Net %+d%% of max HP." % m["netPct"]))
    return R


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
    perks = {k: [sel["perk"] for st in parts[p]["perks"]["styles"] for sel in st["selections"]] for k, p in (("me", pme), ("opp", popp))}
    setup = {k: [RUNE.get(r) for r in v if r in RUNE] for k, v in perks.items()}
    def gold_at(p, t):   # item gold (spent) at the last minute mark
        f = tl["frames"][min(len(tl["frames"]) - 1, int(t // 60))]["participantFrames"][str(p)]
        return f["totalGold"] - f["currentGold"]

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
    deaths_by = {}
    for x in kills:
        deaths_by.setdefault(x["victim"], []).append(x["t"])
    rec = W.recalls(d, deaths_by, until + 30)
    out_recalls = {"me": [round(t) for k, t, x, z in rec if k == me], "opp": [round(t) for k, t, x, z in rec if k == opp]}
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
        bigger = "even" if abs(nm[my_team] - nm[300 - my_team]) <= 1 else ("mine" if nm[my_team] > nm[300 - my_team] else "theirs")
        back = {w: next((round(t0 - r) for r in out_recalls[w] if 0 < t0 - r <= 60), None) for w in ("me", "opp")}
        mo = {"t": t0, "end": t1, "kind": "trade", "biggerWave": bigger, "backFromBaseSecsAgo": back, "solo": x["solo"], "first": x["first"], "seq": x["seq"],
              "dealt": x["dealt"], "took": x["took"], "netPct": round(100 * (x["dealt"] / mx[1] - x["took"] / mx[0])),
              "hpMe": x["hpMe"], "hpOpp": x["hpOpp"], "lv": [level(pme, t0), level(popp, t0)],
              "died": x["died"], "others": [o["champ"] for o in x["others"]],
              "minions": {"mine": nm[my_team], "theirs": nm[300 - my_team]},
              "toMyTower": round(math.hypot(cx - mt[0], cz - mt[1])), "toTheirTower": round(math.hypot(cx - ot[0], cz - ot[1])),
              "sumsMe": sums_up(me, my_sums, t0), "sumsOpp": sums_up(opp, op_sums, t0), "flags": [],
              "sumsUsedMe": sorted({n for tt, kk, n in sc if kk == me and t0 - 1 <= tt <= t1})}
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
        # --- added from the reviewer's games 1-2 grades (general rules)
        dmg_from = lambda tg, a0, a1: round(sum(v for ht, t2, a, v in hits if t2 == tg and a is None and a0 <= ht <= a1))
        mo["enemiesNear"] = [o for o in mo["others"] if (skins.index(o) < 5) != (me < 5)] if all(o in skins for o in mo["others"]) else mo["others"]
        mo["alliesNear"] = [o for o in mo["others"] if o not in mo["enemiesNear"]]
        mo["minionDmg"] = {"me": dmg_from(me, t0, t1 + 1), "opp": dmg_from(opp, t0, t1 + 1)}
        # health left on each side when the fight ended (start - champion damage - minion/tower damage)
        left_me = x["hpMe"][0] - x["took"] - mo["minionDmg"]["me"]
        left_opp = x["hpOpp"][0] - x["dealt"] - mo["minionDmg"]["opp"]
        mo["leftAtEnd"] = {"me": round(max(0, left_me)), "opp": round(max(0, left_opp))}
        my_hits = [v for ht, tg, a, v in hits if a == me and tg == opp and t0 <= ht <= t1]
        mo["avgHit"] = round(sum(my_hits) / len(my_hits)) if my_hits else None
        # opened with an auto before the first ability?
        first_cast = min([t for t, k, L in casts if k == me and t0 - 1 <= t <= t1], default=None)
        first_hit = min([ht for ht, tg, a, v in hits if a == me and tg == opp and t0 - 1 <= ht <= t1], default=None)
        mo["openedWithAuto"] = bool(first_hit is not None and (first_cast is None or first_hit < first_cast - 0.1))
        # defensive rune up for them? (Bone Plating: on after 55 s without champion damage)
        if "Bone Plating" in setup["opp"]:
            prev = [ht for ht, tg, a, v in hits if tg == opp and a is not None and t0 - 55 <= ht < t0]
            mo["theirBonePlatingUp"] = not prev
        # context: who is ahead
        lv_gap = level(pme, t0) - level(popp, t0)
        gold_gap = gold_at(pme, t0) - gold_at(popp, t0)
        deaths_gap = (sum(1 for z in kills if z["victim"] == me and z["killer"] == opp and z["t"] < t0)
                      - sum(1 for z in kills if z["victim"] == opp and z["killer"] == me and z["t"] < t0))
        mo["state"] = {"levelGap": lv_gap, "itemGoldGap": gold_gap, "deathsGap": deaths_gap}
        # level spikes within the first 8 s
        a3, a0 = RT._at(d["tracks"][me], t0 - 3), RT._at(d["tracks"][me], t0)
        mo["stillBefore"] = bool(a3 and a0 and math.hypot(a3[0] - a0[0], a3[1] - a0[1]) < 120 and math.hypot(pm[0] - po[0], pm[1] - po[1]) < 750)
        mo["spike"] = [{"who": who, "to": level(pp, lt), "secsIn": round(lt - t0, 1)}
                       for pp, who in ((pme, "me"), (popp, "opp")) for lt in lvl[pp][1:] if 0 <= lt - t0 <= 8]
        out["moments"].append(mo)

    # deaths in lane
    for x in kills:
        if x["t"] > until or x["victim"] not in (me, opp):
            continue
        k = x["victim"]
        p = RT._at(d["tracks"][k], x["t"] - 0.5) or x["pos"]
        nm = near_minions(p[0], p[1], x["t"] - 3)
        team = 100 if k < 5 else 200
        # standing still just before dying, with the killer close (tilt / idle)
        still = None
        if k == me:
            a, b = RT._at(d["tracks"][k], x["t"] - 4), RT._at(d["tracks"][k], x["t"] - 1)
            o = RT._at(d["tracks"][opp], x["t"] - 1)
            if a and b and o:
                still = math.hypot(a[0] - b[0], a[1] - b[1]) < 150 and math.hypot(b[0] - o[0], b[1] - o[1]) < 700
        lead = (sum(1 for z in kills if z["victim"] == opp and z["killer"] == me and z["t"] < x["t"])
                - sum(1 for z in kills if z["victim"] == me and z["killer"] == opp and z["t"] < x["t"]))
        out["moments"].append({"t": x["t"], "kind": "death", "who": "me" if k == me else "opp", "standingStill": still, "laneLead": lead,
                               "killer": skins[x["killer"]] if x["killer"] is not None else "minions/tower",
                               "assists": [skins[a] for a in x["assists"] if a is not None],
                               "lv": [level(pme, x["t"]), level(popp, x["t"])],
                               "sumsMe": sums_up(me, my_sums, x["t"] - 1), "sumsOpp": sums_up(opp, op_sums, x["t"] - 1),
                               "sumsUsed": [(round(t, 1), skins[kk], n) for t, kk, n in sc if kk in (me, opp) and x["t"] - 15 <= t <= x["t"]],
                               "minions": {"theirTeam": nm[300 - team], "ownTeam": nm[team]},
                               "toOwnTower": round(math.hypot(p[0] - TOWERS[team][0], p[1] - TOWERS[team][1]))})
    for w, L in out_recalls.items():
        for r in L:
            if r <= until:
                out["moments"].append({"t": r, "kind": "recall", "who": w})
    out["moments"].sort(key=lambda z: z["t"])
    out["sumCasts"] = [(round(t, 1), skins[k], n) for t, k, n in sc if k in (me, opp)]
    out["setup"] = setup
    out["reads"] = reads(out)
    return out


if __name__ == "__main__":
    a = sys.argv
    print(json.dumps(main(a[1], a[2], a[3], float(a[4]) if len(a) > 4 else 600.0), indent=1, default=str))

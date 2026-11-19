"""The coach's read of your lane: level races, every trade and your deaths, judged by general rules (no champion
names in them) that came out of the first graded reviews (see the project's coach-draft-grades notes).

analyze() takes the replay, the saved timeline and the lane trades already decoded by replay_trades.lane_trades, and
returns [{"t", "kind", "verdict", "text"}] for the Lane trades tab. Ported from scripts/research/draft_review.py.
"""
import bisect
import math

import replay_trades as RT
import replay_waves as W

SUMM = {"363fad": "Flash", "78ed5b": "Teleport", "22568a": "Ignite", "cbb9e2": "Heal", "96b4e4": "Barrier",
        "f62bbf": "Exhaust", "993dca": "Ghost"}
SUMM_ID = {4: "Flash", 14: "Ignite", 6: "Ghost", 12: "Teleport", 7: "Heal", 21: "Barrier", 3: "Exhaust", 11: "Smite", 1: "Cleanse"}
SUMM_CD = {"Flash": 300, "Ignite": 180, "Ghost": 210, "Teleport": 330, "Heal": 240, "Barrier": 180, "Exhaust": 210, "Cleanse": 210}
BONE_PLATING = 8473
# outer and inner turrets of each team (Summoner's Rift map units)
TOWERS = {100: [(981, 10441), (5846, 6396), (10504, 1029), (1512, 6699), (5048, 4812), (6919, 1483)],
          200: [(4318, 13875), (8955, 8510), (13866, 4505), (7943, 13411), (9767, 10113), (13327, 8226)]}


def clock(t):
    return "%d:%02d" % (int(t) // 60, int(t) % 60)


def _summoner_casts(path, until):
    _v, _s, chunks = RT.read_rofl(path)
    if RT.is23(_v):
        return [(t, k, n) for t, k, n in RT.decode(path, until=until)["summs"]]
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


def _tower_dist(team, x, z):
    return min(math.hypot(x - a, z - b) for a, b in TOWERS[team])


def analyze(path, me, opp, p_me, p_opp, slot_of_pid, timeline, trades_out, until=840.0):
    """me/opp: replay slots; p_me/p_opp: the game's participant dicts (participantId, spell1Id, spell2Id, stats.perkN)."""
    d = RT.decode(path, until=until + 30)
    skins = [s.get("SKIN") for s in d["stats"]]
    pme, popp = p_me["participantId"], p_opp["participantId"]
    frames = timeline.get("frames") or []

    lvl = {pme: [0.0], popp: [0.0]}
    kills = []
    for f in frames:
        for e in f.get("events") or []:
            t = (e.get("timestamp") or 0) / 1000
            if t > until + 30:
                continue
            p = e.get("participantId")
            if e.get("type") == "LEVEL_UP" and p in lvl:
                lvl[p].append(t)
            elif e.get("type") == "CHAMPION_KILL":
                kills.append({"t": t, "victim": slot_of_pid(e.get("victimId")), "killer": slot_of_pid(e.get("killerId")),
                              "assists": [slot_of_pid(a) for a in e.get("assistingParticipantIds") or []]})
    for p in lvl:
        lvl[p].sort()
    level = lambda p, t: sum(1 for x in lvl[p] if x <= t)

    def gold_at(p, t):   # item gold (spent) at the last minute mark
        if not frames:
            return 0
        f = (frames[min(len(frames) - 1, int(t // 60))].get("participantFrames") or {}).get(str(p)) or {}
        return (f.get("totalGold") or 0) - (f.get("currentGold") or 0)

    perks = lambda pp: [(pp.get("stats") or {}).get("perk%d" % n) for n in range(6)]
    opp_bone = BONE_PLATING in perks(p_opp)
    my_sums = [SUMM_ID.get(p_me.get("spell1Id")), SUMM_ID.get(p_me.get("spell2Id"))]
    sc = _summoner_casts(path, until + 30)

    def sums_up(k, have, t):
        out = []
        for s in have:
            if not s:
                continue
            last = max([x for x, kk, n in sc if kk == k and n == s and x <= t], default=None)
            out.append((s, last is None or t - last >= SUMM_CD.get(s, 300)))
        return out

    de = W.unit_deaths(path, until + 30)
    mins = W.minions(d, de)
    casts, hits = d["casts"], d["hits"]
    my_team = 100 if me < 5 else 200

    def near_minions(x, z, t, r=1100):
        c = {100: 0, 200: 0}
        for mm in mins.values():
            if mm["spawn"] > t or (mm["died"] is not None and mm["died"] <= t):
                continue
            p = RT._at(mm["track"], t)
            if p and math.hypot(p[0] - x, p[1] - z) < r:
                c[mm["team"]] += 1
        return c

    def lane_kills(victim, killer, before):
        return sum(1 for z in kills if z["victim"] == victim and z["killer"] == killer and z["t"] < before)

    R = []
    trades = []
    # --- trades
    for x in trades_out.get("trades") or []:
        t0, t1 = x["t0"], x["t1"]
        if t0 > until:
            continue
        pm = RT._at(d["tracks"][me], t0) or (0, 0)
        po = RT._at(d["tracks"][opp], t0) or (0, 0)
        cx, cz = (pm[0] + po[0]) / 2, (pm[1] + po[1]) / 2
        nm = near_minions(cx, cz, t0)
        bigger = "even" if abs(nm[my_team] - nm[300 - my_team]) <= 1 else ("mine" if nm[my_team] > nm[300 - my_team] else "theirs")
        mx = (x["hpMe"][1] or 1, x["hpOpp"][1] or 1)
        net = round(100 * (x["dealt"] / mx[1] - x["took"] / mx[0]))
        others = [o.get("champ") for o in x.get("others") or []]
        enemies = [o for o in others if o in skins and (skins.index(o) < 5) != (me < 5)]
        allies = [o for o in others if o not in enemies]
        mdmg = {k: round(sum(v for ht, tg, a, v in hits if tg == s and a is None and t0 <= ht <= t1 + 1)) for k, s in (("me", me), ("opp", opp))}
        left_opp = max(0, round(x["hpOpp"][0] - x["dealt"] - mdmg["opp"]))
        my_hits = [v for ht, tg, a, v in hits if a == me and tg == opp and t0 <= ht <= t1]
        avg_hit = sum(my_hits) / len(my_hits) if my_hits else None
        first_cast = min([t for t, k, L in casts if k == me and t0 - 1 <= t <= t1], default=None)
        first_hit = min([ht for ht, tg, a, v in hits if a == me and tg == opp and t0 - 1 <= ht <= t1], default=None)
        opened_auto = first_hit is not None and (first_cast is None or first_hit < first_cast - 0.1)
        bone_up = opp_bone and not [ht for ht, tg, a, v in hits if tg == opp and a is not None and t0 - 55 <= ht < t0]
        lv_gap = level(pme, t0) - level(popp, t0)
        gold_gap = gold_at(pme, t0) - gold_at(popp, t0)
        deaths_gap = lane_kills(me, opp, t0) - lane_kills(opp, me, t0)
        a3 = RT._at(d["tracks"][me], t0 - 3)
        still = bool(a3 and math.hypot(a3[0] - pm[0], a3[1] - pm[1]) < 120 and math.hypot(pm[0] - po[0], pm[1] - po[1]) < 750)
        spikes = [("me" if pp == pme else "opp", level(pp, lt), lt - t0) for pp in (pme, popp) for lt in lvl[pp][1:] if 0 <= lt - t0 <= 8]
        free_poke = x["took"] >= 40 and x["dealt"] < 10
        wave_then_engaged = x["first"] == "them" and any(
            k == me and t0 - 8 <= t < t0 - 0.3 and L in ("Q", "W", "E") and not any(a == me and tg == opp and t <= ht <= t + 3 for ht, tg, a, v in hits)
            for t, k, L in casts)
        used = {n for tt, kk, n in sc if kk == me and t0 - 1 <= tt <= t1}
        died = x.get("died") or []
        trades.append({"t": t0, "netPct": net, "died": died, "solo": x.get("solo", True),
                       "both": min(x["dealt"], x["took"]) >= 40})   # both sides hit: a real fight, not another poke

        behind = deaths_gap >= 2 or (lv_gap <= -1 and gold_gap <= -700)
        ahead = deaths_gap <= -2 or (lv_gap >= 1 and gold_gap >= 700)
        dur = t1 - t0
        notes, verdict = [], None
        if still and x["first"] == "them" and "you" in died:
            verdict = "skip"; notes.append("You were standing still in their range when they engaged. Looks idle; not a lesson.")
        elif behind and "you" not in died:
            verdict = "meh"; notes.append("You're behind here (%+d lane deaths, %+d levels, %+d item gold): what matters now is farming and staying alive, not this trade." % (deaths_gap, lv_gap, gold_gap))
        elif bone_up and dur < 6 and abs(net) <= 8 and not died:
            verdict = "good"; notes.append("Short trade that popped their Bone Plating: the next fight in the following ~55 s is without it.")
        elif allies and not enemies and (died or any(o.get("dmg", 0) > 0 for o in x.get("others") or [])):
            # your teammates joined: a gank, not a lane trade (user grade, round 3)
            verdict = "good" if died == ["them"] else "check"
            notes.append("Gank with your %s: not judged as a 1v1." % ", ".join(allies))
            if died == ["them"] and bigger == "mine":
                notes.append("Good setup: your bigger wave was pushing to them, so they lose those minions too.")
        elif died and enemies:
            verdict = "good" if died == ["them"] else "check"
            notes.append("Their teammates were there too (%s), so this isn't judged as a 1v1." % ", ".join(enemies))
        elif "you" in died and "them" in died:
            verdict = "1-for-1"
            if mdmg["me"] >= 300 and _tower_dist(300 - my_team, cx, cz) < 900:
                notes.append("You got the kill but died to their tower: was the dive worth more than the wave and plates?")
            else:
                notes.append("You got the kill, then died: after a kill, back off toward your side instead of staying in their wave.")
        elif "you" in died:
            close = left_opp <= 0.15 * mx[1]
            verdict = "close" if close else "lost"
            if close and avg_hit:
                notes.append("They were left on ~%d HP: about %d more of your hits would have flipped it." % (left_opp, max(1, math.ceil(left_opp / avg_hit))))
            else:
                notes.append("They were left on ~%d HP." % left_opp)
            if allies:
                notes.append("(Your %s was nearby.)" % ", ".join(allies))
            if opened_auto:
                notes.append("You opened with an auto before your first ability, which can let them space out of it.")
            unused = [s for s, up in sums_up(me, my_sums, t0) if up and s not in used and s not in ("Teleport", "Smite")]
            if unused:
                notes.append("Unused: %s." % ", ".join(unused))
        elif "them" in died:
            verdict = "good"; notes.append("You got the kill.")
        if lv_gap >= 1 and bigger == "mine" and x["first"] == "them":
            notes.append("They fought into your bigger wave a level down: their mistake to punish.")
            if verdict is None:
                verdict = "good" if net > 0 else "missed"
        if verdict is None:
            if lv_gap <= -1 and bigger == "theirs":
                verdict = "meh"; notes.append("Their window (a level up, bigger wave): giving up a little here is fine.")
            elif lv_gap >= 1 and bigger == "mine" and net < 0:
                verdict = "missed"; notes.append("You were a level up with the bigger wave: your window to trade hard.")
            elif free_poke:
                verdict = "meh" if ahead else "bad"
                notes.append("Free poke taken." + (" Little weight with your lead." if ahead else ""))
            else:
                verdict = "good" if net >= 10 else "bad" if net <= -10 else "even"
                notes.insert(0, "%s %d%% of max HP more than %s." % ("You dealt" if net >= 0 else "They dealt", abs(net), "they did" if net >= 0 else "you did"))
        for who, to, secs in spikes:
            starter = "me" if x["first"] == "you" else "opp"
            if who == starter:
                notes.append("%s started it %.0fs before %s level %d: good timing%s." % ("You" if starter == "me" else "They", secs, "your" if who == "me" else "their", to, "" if starter == "me" else " for them"))
            else:
                notes.append("%s started it %.0fs before %s level %d: %s." % ("You" if starter == "me" else "They", secs, "their" if who == "opp" else "your", to, "risky" if starter == "me" else "their mistake"))
        if wave_then_engaged:
            notes.append("Ability on the wave, then they engaged: commit to crashing and recalling, or to fighting, not in between.")
        if mdmg["me"] + mdmg["opp"] >= 60:
            notes.append("Minions and towers: %d to you, %d to them." % (mdmg["me"], mdmg["opp"]))
        R.append({"t": round(t0, 1), "kind": "trade", "verdict": verdict, "text": " ".join(notes) or "Net %+d%% of max HP." % net,
                  "free_poke": free_poke and verdict == "bad", "poke_pct": round(100 * x["took"] / mx[0]),
                  "lv": level(pme, t0)})

    # A free poke matters when it's a real chunk of health for that stage of the game (early levels: a Q + auto is a big
    # share of your health; by level 9 the same poke regens away) AND something follows within a minute where that health
    # counts: a lane fight, a skirmish, an objective (user grades, round 3).
    objectives = []
    for f in frames:
        for e in f.get("events") or []:
            if e.get("type") == "ELITE_MONSTER_KILL":
                objectives.append(((e.get("timestamp") or 0) / 1000, (e.get("monsterType") or "objective").replace("_", " ").lower()))
            elif e.get("type") == "BUILDING_KILL":
                objectives.append(((e.get("timestamp") or 0) / 1000, "a tower"))
    my_fights = [z["t"] for z in kills if me in [z["victim"], z["killer"]] + z["assists"]]
    for r in R:
        if r.pop("free_poke", False):
            pct, lv_now = r.get("poke_pct", 0), r.get("lv", 1)
            big = pct >= (8 if lv_now <= 6 else 15)
            nxt = None
            for y in trades:
                if 0 < y["t"] - r["t"] <= 60 and (y["died"] or (y["both"] and abs(y["netPct"]) <= 10)):
                    nxt = "a close lane fight" if y["solo"] else "a skirmish"
                    break
            if not nxt and any(0 < t - r["t"] <= 60 for t in my_fights):
                nxt = "a skirmish"
            if not nxt:
                nxt = next((name for t, name in objectives if 0 < t - r["t"] <= 60), None)
            head = "Free poke taken (%d%% of your max HP)." % pct
            if big and nxt:
                r["text"] = r["text"].replace("Free poke taken.", head + " It mattered: %s followed within a minute and you went in down that health." % nxt)
            else:
                r["verdict"] = "meh"
                why = "too small to matter at level %d" % lv_now if not big else "nothing followed where it counted"
                r["text"] = r["text"].replace("Free poke taken.", head + " Little weight: %s." % why)
        r.pop("poke_pct", None); r.pop("lv", None)

    # --- level races (2 and 3)
    for L in (2, 3):
        a = lvl[pme][L - 1] if len(lvl[pme]) >= L else None
        b = lvl[popp][L - 1] if len(lvl[popp]) >= L else None
        if a and b and b < a and a - b >= 10:
            lost = [y for y in trades if y["t"] < b and y["netPct"] <= -8 and y["solo"]]   # before THEY levelled
            R.append({"t": round(b, 1), "kind": "level race", "verdict": "context" if lost else "check",
                      "text": "Level %d: they were %.0fs earlier.%s" % (L, a - b, (" Likely caused by the lost trade at %s: you gave up the push and they controlled the wave." % clock(lost[-1]["t"])) if lost else "")})

    # --- your deaths: risky plays with a lead
    for z in kills:
        if z["t"] > until or z["victim"] != me:
            continue
        lead = lane_kills(opp, me, z["t"]) - lane_kills(me, opp, z["t"])
        n = 1 + len([a for a in z["assists"] if a is not None])
        if lead >= 2 and n >= 2:
            R.append({"t": round(z["t"], 1), "kind": "death", "verdict": "meh",
                      "text": "Died to %d enemies with a %d-kill lead: unnecessary risk, and a shutdown." % (n, lead)})
    R.sort(key=lambda r: r["t"])
    return R

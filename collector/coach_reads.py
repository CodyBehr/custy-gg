"""The coach's read of your lane: level races, every trade and your deaths, judged by general rules (no champion
names in them) that came out of the first graded reviews (see the project's coach-draft-grades notes).

analyze() takes the replay, the saved timeline and the lane trades already decoded by replay_trades.lane_trades, and
returns [{"t", "kind", "verdict", "text"}] for the Lane trades tab. Ported from scripts/research/draft_review.py.
"""
import bisect
import math

import replay_trades as RT
try:
    import champ_cd
except Exception:   # older builds
    champ_cd = None
try:
    import fight_feats
    import fight_eval
except Exception:   # older builds
    fight_feats = fight_eval = None
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

    # Riot's minute health (championStats) is exact at each frame. Work back from the next frame to a moment: health
    # then = health at the frame + the damage the replay shows them taking in between. Unlike counting forward from the
    # start of a fight, this includes their healing during it (passives, lifesteal, potions). None when they recalled
    # or died in between (user grade: "about 3 more hits" when Aatrox, who heals, was really on ~300-400).
    deaths_of = {}
    for z in kills:
        deaths_of.setdefault(z["victim"], []).append(z["t"])
    backs_of = {}
    for k_, t_, _x, _z in W.recalls(d, deaths_of, until + 90):
        backs_of.setdefault(k_, []).append(t_)
    slot_pid = {me: pme, opp: popp}

    def frame_hp(slot, i):
        if i >= len(frames):
            return None
        pf = (frames[i].get("participantFrames") or {}).get(str(slot_pid[slot])) or {}
        st = pf.get("st")   # the site's slim timeline: [health, max health]
        if st and len(st) >= 2 and st[1]:
            return st[0], st[1]
        cs = pf.get("championStats") or {}
        return (cs.get("health"), cs.get("healthMax")) if cs.get("healthMax") else None

    def hp_back(slot, t):
        i = int(t // 60) + 1
        f = frame_hp(slot, i)
        if not f or f[0] is None:
            return None
        tf = (frames[i].get("timestamp") or i * 60000) / 1000
        if any(t < x <= tf for x in deaths_of.get(slot, []) + backs_of.get(slot, [])):
            return None
        return min(f[1], f[0] + sum(v for ht, tg, a, v in hits if tg == slot and t < ht <= tf)), f[1]

    def my_last_hits(t0, t1):
        return sum(1 for mm in mins.values() if mm.get("killer") == me and mm["died"] is not None and t0 - 0.5 <= mm["died"] <= t1 + 1)

    R = []
    trades = []
    # --- the fight model (Master+ 1v1 top/mid fights): experts' odds of coming out ahead in this spot, fighting or not
    lane = (d["stats"][me].get("TEAM_POSITION") or d["stats"][me].get("INDIVIDUAL_POSITION") or "").upper()
    FX = None
    if fight_eval and fight_eval.available() and lane in ("TOP", "MIDDLE") and not d.get("hp"):
        try:
            d["hp"] = RT.keyframe_health(path)   # the replay's own minute health (matches Riot's within 1 HP)
        except Exception:
            pass
    if fight_eval and fight_eval.available() and lane in ("TOP", "MIDDLE") and d.get("hp"):
        kd = {}
        for z in kills:
            if z["victim"] is not None:
                kd.setdefault(z["victim"], []).append(z["t"])
        rk = {}
        for f in frames:
            for e in f.get("events") or []:
                if e.get("type") == "SKILL_LEVEL_UP" and e.get("participantId") in (pme, popp) and e.get("levelUpType") != "EVOLVE" and e.get("skillSlot") in (1, 2, 3, 4):
                    rk.setdefault(me if e["participantId"] == pme else opp, []).append(((e.get("timestamp") or 0) / 1000, "QWER"[e["skillSlot"] - 1]))
        try:
            FX = fight_feats.Ctx(d, kd, rk, lambda k, t: gold_at(pme if k == me else popp, t) if k in (me, opp) else None, until)
        except Exception:
            FX = None

    def expert_odds(t0, first=None):
        if not FX:
            return None
        try:
            st = FX.state(me, opp, t0, lane, first)
            if not st:
                return None
            st.pop("_hp", None)
            o = fight_eval.odds(st, skins[me], skins[opp])
            if o:
                o["state"] = st
            return o
        except Exception:
            return None

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
        left_fwd = max(0, round(x["hpOpp"][0] - x["dealt"] - mdmg["opp"]))
        my_death = min([z["t"] for z in kills if z["victim"] == me and t0 - 1 <= z["t"] <= t1 + 20], default=None)
        hb = hp_back(opp, my_death) if my_death is not None else None
        # Two estimates of what they had left when you died: counting forward from the start of the fight misses their
        # healing during it (too low); counting back from Riot's next minute mark adds any healing after it (too high).
        # The truth is in between: only call it close when even the high one is low.
        left_opp = round(hb[0]) if hb else left_fwd
        left_lo = min(left_fwd, left_opp)
        left_known = hb is not None
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
        # Poke: one side's damage, the other side's next to nothing (user grades: "this should be labelled as poke").
        free_poke = x["took"] >= 40 and x["dealt"] <= max(10, 0.2 * x["took"])
        poke_landed = x["dealt"] >= 40 and x["took"] <= max(10, 0.2 * x["dealt"])
        lh = my_last_hits(t0, t1)
        # Did the damage you took heal back by the next minute without a recall (regen passives, potions)?
        after = hp_back(me, t1 + 1)
        healed_back = bool(after and x["took"] >= 40 and after[0] >= x["hpMe"][0] - x["took"] - mdmg["me"] + 0.7 * x["took"])
        potion = any(e.get("type") == "ITEM_DESTROYED" and e.get("participantId") == pme and e.get("itemId") in (2003, 2031, 2033)
                     and t0 - 2 <= (e.get("timestamp") or 0) / 1000 <= t1 + 60 for f in frames for e in f.get("events") or [])
        # Their poke spent a long-cooldown ability (12 s+ at rank 1): that's a window for you.
        opp_name = skins[opp] if 0 <= opp < len(skins) else None
        cdt = ((champ_cd.CD.get(opp_name) or {}).get("cd") or {}) if champ_cd else {}
        spent = [L for t, k, L in casts if k == opp and t0 - 1 <= t <= t1 and L in ("Q", "W", "E") and (cdt.get(L) or [0])[0] >= 12]
        wave_then_engaged = x["first"] == "them" and any(
            k == me and t0 - 8 <= t < t0 - 0.3 and L in ("Q", "W", "E") and not any(a == me and tg == opp and t <= ht <= t + 3 for ht, tg, a, v in hits)
            for t, k, L in casts)
        used = {n for tt, kk, n in sc if kk == me and t0 - 1 <= tt <= t1}
        died = x.get("died") or []
        trades.append({"t": t0, "netPct": net, "died": died, "solo": x.get("solo", True), "bigger": bigger,
                       "both": min(x["dealt"], x["took"]) >= 40})   # both sides hit: a real fight, not another poke

        behind = deaths_gap >= 2 or (lv_gap <= -1 and gold_gap <= -700)
        ahead = deaths_gap <= -2 or (lv_gap >= 1 and gold_gap >= 700)
        dur = t1 - t0
        notes, verdict = [], None
        if still and x["first"] == "them" and "you" in died:
            verdict = "skip"; notes.append("You were standing still in their range when they engaged. Looks idle; not a lesson.")
        elif behind and "you" not in died:
            verdict = "meh"; notes.append("You're behind here (%+d lane deaths, %+d levels, %+d item gold): what matters now is farming and staying alive, not this trade." % (deaths_gap, lv_gap, gold_gap))
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
            close = left_known and left_opp <= 0.15 * mx[1]
            verdict = "close" if close else "lost"
            if close and avg_hit:
                notes.append("They were left on ~%d HP: about %d more of your hits would have flipped it." % (left_opp, max(1, math.ceil(left_opp / avg_hit))))
            elif left_known and left_opp - left_lo > 0.12 * mx[1]:
                pass   # the two estimates disagree too much to name a number (healing in or after the fight)
            elif left_known:
                notes.append("They were left on ~%d HP (%d%%)." % (left_opp, round(100 * left_opp / mx[1])))
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
            elif free_poke and lh >= 1:
                verdict = "meh"; notes.append("Poke taken (%d%% of your max HP) while you last-hit %d minion%s: trading some health for CS is often fine." % (round(100 * x["took"] / mx[0]), lh, "" if lh == 1 else "s"))
            elif free_poke:
                verdict = "meh" if ahead else "bad"
                notes.append("Free poke taken." + (" Little weight with your lead." if ahead else ""))
            elif poke_landed:
                pp = round(100 * x["dealt"] / mx[1])
                verdict = "good" if pp >= 10 else "even"
                notes.append("Poke landed: %d%% of their max HP for nothing back." % pp)
            else:
                verdict = "good" if net >= 10 else "bad" if net <= -10 else "even"
                notes.insert(0, "%s %d%% of max HP more than %s." % ("You dealt" if net >= 0 else "They dealt", abs(net), "they did" if net >= 0 else "you did"))
                if verdict == "bad" and lh >= 2:
                    notes.append("You did last-hit %d minions during it, so you got some CS for that health." % lh)
        if verdict == "bad" and healed_back and not potion:
            # Healed back for free (regen passives, lifesteal) by the next minute: it cost little (user grades: Garen's
            # passive, Aatrox). A potion is a real cost, so those stay as they were.
            verdict = "meh"; notes.append("You had healed it back by the next minute without a potion or a recall, so it cost little.")
        hp_after = ((x["hpMe"][0] - x["took"] - mdmg["me"]) / mx[0], (x["hpOpp"][0] - x["dealt"] - mdmg["opp"]) / mx[1])
        if verdict == "bad" and not died and dur < 3 and hp_after[0] - hp_after[1] >= 0.1:
            # User grade (Garen v Fiora 3:28): their poke, but you still had the health lead: just a poke.
            verdict = "meh"; free_poke = True
            notes.append("You still had the health lead after it (%d%% vs %d%%), so it's just a poke." % (round(100 * hp_after[0]), round(100 * hp_after[1])))
        if (free_poke or verdict == "bad") and not behind and spent and not died:
            notes.append("They spent %s on it: that's down for a while, your window to go in." % " and ".join(sorted(set(spent))))
        if bone_up and dur < 6 and not died and verdict in ("even", "good", "meh"):
            notes.append("It also popped their Bone Plating for the next fight.")
        for who, to, secs in spikes:
            starter = "me" if x["first"] == "you" else "opp"
            if who == starter:
                notes.append("%s started it %.0fs before %s level %d: good timing%s." % ("You" if starter == "me" else "They", secs, "your" if who == "me" else "their", to, "" if starter == "me" else " for them"))
            else:
                notes.append("%s started it %.0fs before %s level %d: %s." % ("You" if starter == "me" else "They", secs, "their" if who == "opp" else "your", to, "risky" if starter == "me" else "their mistake"))
        if wave_then_engaged:
            notes.append("Ability on the wave, then they engaged: commit to crashing and recalling, or to fighting, not in between.")
        # (minion and tower damage is still counted in the reads above; the line itself was more noise than help)
        od = expert_odds(t0, x.get("first") == "you") if x.get("solo", True) else None
        if od:
            pf, pc = round(100 * od["fight"]), round(100 * od["calm"])
            i_died = "you" in died
            lost_it = (verdict in ("bad", "lost", "close") or i_died) and "them" not in died
            won_it = verdict == "good" or ("them" in died and not i_died)
            # Only say something when the odds add to what happened: a good call that didn't land, a bad spot, a win
            # against the odds, or a spot where fighting clearly costs or pays compared with not fighting.
            if lost_it and pf >= 60:
                notes.append("The call was fine: experts in this spot come out ahead %d%% of the time, so look at how it played out, not the decision." % pf)
            elif lost_it and (pf <= 35 or od["value"] <= -0.10):
                notes.append("A bad spot to take it: experts come out ahead only %d%% of the time fighting here (%d%% if they don't)." % (pf, pc))
            elif won_it and pf <= 30:
                notes.append("You won one experts usually lose here (%d%%)." % pf)
            elif od["value"] <= -0.15 and verdict not in ("missed", "check"):   # "their mistake to punish" stands on its own
                notes.append("Fighting here usually costs: experts come out ahead %d%% of the time fighting, %d%% not fighting." % (pf, pc))
        R.append({"t": round(t0, 1), "kind": "trade", "verdict": verdict, "text": " ".join(notes) or "Net %+d%% of max HP." % net,
                  "odds": {"fight": round(od["fight"], 3), "calm": round(od["calm"], 3)} if od else None,
                  "free_poke": free_poke and verdict == "bad" and not lh, "poke_pct": round(100 * x["took"] / mx[0]),
                  "lv": level(pme, t0)})

    # --- windows you didn't take: near each other, no fight, and experts in that spot come out clearly better fighting
    if FX:
        duel_t = sorted(t for t, tg, a, v in hits if {a, tg} == {me, opp})
        cand = []
        tt = 90.0
        while tt <= min(until, 840):
            a_, b_ = RT._at(d["tracks"].get(me), tt), RT._at(d["tracks"].get(opp), tt)
            busy = any(tt - 8 <= x <= tt + 20 for x in duel_t)
            dead = any(tt - 20 <= z["t"] <= tt + 2 and z["victim"] in (me, opp) for z in kills)
            others = any(k not in (me, opp) and RT._at(d["tracks"].get(k), tt) and a_ and
                         math.hypot(RT._at(d["tracks"][k], tt)[0] - a_[0], RT._at(d["tracks"][k], tt)[1] - a_[1]) < 1400 for k in range(10))
            # recalls are logged when they land in base: skip the 25 s before (walking off + the 8 s channel)
            backing = any(x - 25 <= tt <= x + 5 for x in FX.backs.get(opp, []) + FX.backs.get(me, []))
            their_tower = min(math.hypot(b_[0] - tx, b_[1] - tz) for tx, tz in TOWERS[300 - my_team]) < 1000 if b_ else True
            if a_ and b_ and not busy and not dead and not others and not backing and not their_tower and math.hypot(a_[0] - b_[0], a_[1] - b_[1]) < 1500:
                od = expert_odds(tt)
                if od and od["fight"] >= 0.62 and od["value"] >= 0.12:
                    cand.append((od["value"], tt, od))
            tt += 10
        picked = []
        for v, tt, od in sorted(cand, reverse=True):
            if len(picked) < 3 and all(abs(tt - p_[0]) >= 60 for p_ in picked):
                picked.append((tt, od))
        for tt, od in sorted(picked):
            st = od["state"]
            why = []
            if st["lvMe"] > st["lvOpp"]:
                why.append("you were a level up")
            if st["hpMe"] - st["hpOpp"] >= 15:
                why.append("you had %d%% health to their %d%%" % (st["hpMe"], st["hpOpp"]))
            key = ((champ_cd.CD.get(skins[opp]) or {}).get("key")) if champ_cd else None
            if key and st.get("keyOpp") not in ("", None) and st["keyOpp"] < 1:
                why.append("their %s was on cooldown" % key)
            if st["minMine"] - st["minTheirs"] >= 3:
                why.append("your wave was bigger")
            if st["flashOpp"] == 0 and st["flashMe"] == 1:
                why.append("their Flash was down")
            R.append({"t": round(tt, 1), "kind": "window", "verdict": "check",
                      "odds": {"fight": round(od["fight"], 3), "calm": round(od["calm"], 3)},
                      "text": "A window you didn't take: experts in this spot come out ahead %d%% of the time when they fight, %d%% when they don't%s." % (
                          round(100 * od["fight"]), round(100 * od["calm"]), (" (" + ", ".join(why) + ")") if why else "")})

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

    # --- reset windows (reviewer, round 3): your wave crashed into their tower, you had gold for a real purchase, the
    # opponent couldn't punish a back, and you stayed (or roamed) instead of backing. Crash, back while their tower
    # takes the wave, and you lose nothing; the wave bounces to you as you return. Ambiguous by nature: "check".
    for r in _reset_windows(d, mins, frames, kills, me, opp, pme, my_team, p_opp, until):
        # User grade (Garen v Fiora 7:14): with them on half health and you full, staying to keep pressure is right too.
        i = int(r["t"] // 60)
        a, b = frame_hp(me, i), frame_hp(opp, i)
        if a and b and a[0] and b[0] is not None and a[0] / a[1] - b[0] / b[1] >= 0.3:
            r["text"] += " You were well ahead on health (%d%% vs %d%%), so staying to keep the pressure on is also a good choice." % (round(100 * a[0] / a[1]), round(100 * b[0] / b[1]))
            r["verdict"] = "meh"
        R.append(r)

    # --- level races (2 and 3)
    for L in (2, 3):
        a = lvl[pme][L - 1] if len(lvl[pme]) >= L else None
        b = lvl[popp][L - 1] if len(lvl[popp]) >= L else None
        if a and b and b < a and a - b >= 10:
            lost = [y for y in trades if y["t"] < b and y["netPct"] <= -8 and y["solo"]]   # before THEY levelled
            # If they already had the bigger wave when that trade started, the wave got them the XP, not the trade
            # (user grade, Garen v Fiora 2:02: "wasn't the trade, she had the minion advantage / push").
            if lost and lost[-1].get("bigger") == "theirs":
                why = " They had the bigger wave (the push) from before the trade at %s, so they got the XP first: normal unless you could contest the wave." % clock(lost[-1]["t"])
                verdict = "context"
            elif lost:
                why = " Likely caused by the lost trade at %s: you gave up the push and they controlled the wave." % clock(lost[-1]["t"])
                verdict = "context"
            else:
                why, verdict = "", "check"
            R.append({"t": round(b, 1), "kind": "level race", "verdict": verdict, "text": "Level %d: they were %.0fs earlier.%s" % (L, a - b, why)})

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


LANE_TOWERS = {"top": (0, 3), "mid": (1, 4), "bot": (2, 5)}   # indexes into TOWERS[team]: (outer, inner)


def _gold_at(frames, pid, t):
    """Unspent gold at time t, interpolated between Riot's minute frames."""
    i = int(t // 60)
    if not frames or i + 1 >= len(frames):
        return None
    g = lambda f: ((f.get("participantFrames") or {}).get(str(pid)) or {}).get("currentGold")
    a, b = g(frames[i]), g(frames[i + 1])
    if a is None or b is None:
        return None
    if b < a:        # spent during the minute: use the value before the purchase
        return a
    return a + (b - a) * (t - 60 * i) / 60.0


def _reset_windows(d, mins, frames, kills, me, opp, pme, my_team, p_opp, until, min_gold=400):
    track = d["tracks"].get(me) or []
    if not track:
        return []
    their = 300 - my_team
    p3 = RT._at(track, 180)
    lane = W.lane_of(*p3) if p3 else None
    if lane not in LANE_TOWERS:
        return []
    dead = []
    for f in frames:
        for e in f.get("events") or []:
            if e.get("type") == "BUILDING_KILL" and e.get("position"):
                dead.append(((e.get("timestamp") or 0) / 1000, e["position"]["x"], e["position"]["y"]))

    def their_tower(t):
        for idx in LANE_TOWERS[lane]:
            x, z = TOWERS[their][idx]
            if not any(dt <= t and math.hypot(dx - x, dz - z) < 600 for dt, dx, dz in dead):
                return x, z
        return None

    my_deaths = [z["t"] for z in kills if z["victim"] == me]
    backs = [t for k, t, _x, _z in W.recalls(d, {me: my_deaths}, until + 60) if k == me]
    opp_tp = 12 in (p_opp.get("spell1Id"), p_opp.get("spell2Id"), p_opp.get("summoner1Id"), p_opp.get("summoner2Id"))
    out, last = [], -999
    t = 120.0
    while t <= until:
        tw = their_tower(t)
        here = RT._at(track, t)
        if not tw or not here:
            t += 2; continue
        mine = sum(1 for m in mins.values() if m["team"] == my_team and m["lane"] == lane and m["spawn"] <= t
                   and (m["died"] is None or m["died"] > t)
                   and (lambda p: p is not None and math.hypot(p[0] - tw[0], p[1] - tw[1]) < 900)(RT._at(m["track"], t)))
        if mine < 3 or t - last < 60:   # check every moment of the crash; one read per minute at most
            t += 2; continue
        alive = not any(x <= t < x + 60 for x in my_deaths)
        near = math.hypot(here[0] - tw[0], here[1] - tw[1]) < 3500
        gold = _gold_at(frames, pme, t)
        backed = any(t - 5 <= b <= t + 30 for b in backs)
        if not alive or not near or gold is None or gold < min_gold or backed:
            t += 2; continue
        later = RT._at(track, t + 20)
        roamed = later is not None and W.lane_of(*later) != lane and math.hypot(later[0] - here[0], later[1] - here[1]) > 2500
        txt = ("Potential reset window: your wave crashed into their tower and you had ~%d gold. A back here costs you nothing (their "
               "tower takes the wave, it bounces back to you as you return) and you come back with the item." % round(gold, -1))
        if not opp_tp:
            txt += " They have no Teleport, so they can't match your back cheaply."
        if roamed:
            txt += " You left the lane instead: worth it only if the roam got something."
        out.append({"t": round(t, 1), "kind": "reset", "verdict": "check", "text": txt})
        last = t
        t += 2
    return out

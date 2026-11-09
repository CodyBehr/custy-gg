"""Benchmark numbers for one champion/position from Riot API match+timeline files."""
import json, os, sys, statistics as S
ITEMS = json.load(open("" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "item.json") + ""))["data"]
def cost(i): return ITEMS.get(str(i), {}).get("gold", {}).get("total", 0)
def boots(i):
    it = ITEMS.get(str(i)); return bool(it) and "Boots" in it.get("tags", []) and it["gold"]["total"] >= 700 and i != 1001
def legendary(i):
    it = ITEMS.get(str(i)); return bool(it) and it["gold"]["total"] >= 2200 and not it.get("into") and "Consumable" not in it.get("tags", []) and not boots(i)

def one(path, puuid=None):
    d = json.load(open(path)); m, tl = d["match"]["info"], d["timeline"]["info"]
    puuid = puuid or d["expert"]["puuid"]
    me = next(p for p in m["participants"] if p["puuid"] == puuid)
    opp = next((p for p in m["participants"] if p["teamId"] != me["teamId"] and p.get("teamPosition") == me.get("teamPosition")), None)
    jg = next((p for p in m["participants"] if p["teamId"] != me["teamId"] and p.get("teamPosition") == "JUNGLE"), None)
    pid, oid = me["participantId"], opp["participantId"] if opp else None
    fr = tl["frames"]; pf = lambda f, i: f["participantFrames"][str(i)]
    gold = [pf(f, pid)["totalGold"] for f in fr]; ogold = [pf(f, oid)["totalGold"] for f in fr] if oid else None
    cs = [pf(f, pid)["minionsKilled"] + pf(f, pid)["jungleMinionsKilled"] for f in fr]
    ocs = [pf(f, oid)["minionsKilled"] + pf(f, oid)["jungleMinionsKilled"] for f in fr] if oid else None
    xp = [pf(f, pid)["xp"] - (pf(f, oid)["xp"] if oid else 0) for f in fr]
    unspent = [pf(f, pid)["currentGold"] for f in fr]
    ev = [e for f in fr for e in f["events"]]
    buys = []
    for e in ev:
        if e["type"] == "ITEM_PURCHASED" and e.get("participantId") == pid: buys.append([e["timestamp"] / 1000, e["itemId"]])
        if e["type"] == "ITEM_UNDO" and e.get("participantId") == pid:
            for b in reversed(buys):
                if b[1] == e.get("beforeId"): buys.remove(b); break
    backs = []
    for t, i in buys:
        if t < 120: continue
        if backs and t - backs[-1]["end"] < 40: backs[-1]["items"].append(i); backs[-1]["end"] = t
        else: backs.append({"t": t, "end": t, "items": [i]})
    for b in backs: b["spent"] = sum(cost(i) for i in b["items"])
    r6 = lambda who: next((e["timestamp"] / 1000 for e in ev if e["type"] == "SKILL_LEVEL_UP" and e.get("participantId") == who and e.get("skillSlot") == 4), None)
    deaths = [e for e in ev if e["type"] == "CHAMPION_KILL" and e["victimId"] == pid]
    kills = [e for e in ev if e["type"] == "CHAMPION_KILL" and e.get("killerId") == pid]
    jg_in = lambda e: jg and (e.get("killerId") == jg["participantId"] or jg["participantId"] in (e.get("assistingParticipantIds") or []))
    ch = me.get("challenges", {})
    return {
        "win": me["win"], "dur": m["gameDuration"], "opp": opp["championName"] if opp else None, "id": d["match"]["metadata"]["matchId"],
        "deaths_t": [round(e["timestamp"] / 1000) for e in deaths], "backs_t": [(round(b["t"]), b["spent"]) for b in backs[:6]], "gold": gold, "cs": cs,
        "gdiff": [a - b for a, b in zip(gold, ogold)] if ogold else None,
        "csdiff": [a - b for a, b in zip(cs, ocs)] if ocs else None, "xpdiff": xp, "unspent": unspent,
        "first_back": backs[0]["t"] if backs else None, "first_back_gold": backs[0]["spent"] if backs else None,
        "backs_before_14": sum(1 for b in backs if b["t"] < 840),
        "boots": next((t for t, i in buys if boots(i)), None), "legendary1": next((t for t, i in buys if legendary(i)), None),
        "legendary2": ([t for t, i in buys if legendary(i)][1:2] or [None])[0],
        "lvl6_gap": (r6(pid) - r6(oid)) if oid and r6(pid) and r6(oid) else None,
        "deaths": len(deaths), "deaths_14": sum(1 for e in deaths if e["timestamp"] < 840000),
        "deaths_14_jg": sum(1 for e in deaths if e["timestamp"] < 840000 and jg_in(e)),
        "kills_14": sum(1 for e in kills if e["timestamp"] < 840000),
        "lane_cs_10": ch.get("laneMinionsFirst10Minutes"), "lane_adv": ch.get("laningPhaseGoldExpAdvantage"),
        "max_cs_adv": ch.get("maxCsAdvantageOnLaneOpponent"), "kp": ch.get("killParticipation"),
        "dmg_share": ch.get("teamDamagePercentage"), "dpm": ch.get("damagePerMinute"),
        "unseen_recalls": ch.get("unseenRecalls"), "skillshots_hit": ch.get("skillshotsHit"),
        "vision_pm": ch.get("visionScorePerMinute"), "control_wards": me.get("visionWardsBoughtInGame"),
        "flash_casts": me["summoner1Casts"] if me["summoner1Id"] == 4 else me["summoner2Casts"] if me["summoner2Id"] == 4 else None,
        "time_dead": me.get("totalTimeSpentDead"),
    }

def summary(rows):
    def med(k, f=lambda x: x):
        v = [f(r[k]) for r in rows if r.get(k) is not None]
        return (S.median(v), len(v)) if v else (None, 0)
    def at(k, m):
        v = [r[k][m] for r in rows if r.get(k) and len(r[k]) > m]
        return (S.median(v), S.quantiles(v, n=4)[0], S.quantiles(v, n=4)[2]) if len(v) >= 4 else None
    out = {"games": len(rows), "winrate": sum(r["win"] for r in rows) / len(rows)}
    for m in (5, 10, 15, 20):
        out["gold@%d" % m] = at("gold", m); out["gdiff@%d" % m] = at("gdiff", m)
        out["cs@%d" % m] = at("cs", m); out["csdiff@%d" % m] = at("csdiff", m); out["xpdiff@%d" % m] = at("xpdiff", m)
    for k in ["first_back", "first_back_gold", "backs_before_14", "boots", "legendary1", "legendary2", "lvl6_gap", "deaths", "deaths_14",
              "deaths_14_jg", "kills_14", "lane_cs_10", "lane_adv", "max_cs_adv", "kp", "dmg_share", "dpm", "unseen_recalls",
              "skillshots_hit", "vision_pm", "control_wards", "flash_casts", "time_dead"]:
        out[k] = med(k)
    out["unspent>=1500 per game (minutes 3-20)"] = med("unspent", lambda u: sum(1 for x in u[3:21] if x >= 1500))
    return out

if __name__ == "__main__":
    folder = sys.argv[1]; puuid = sys.argv[2] if len(sys.argv) > 2 else None
    rows = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".json"):
            try: rows.append(one(os.path.join(folder, f), puuid))
            except Exception as e: print("skip", f, e, file=sys.stderr)
    json.dump(summary(rows), open(folder.rstrip("/") + ".summary.json", "w"), indent=1, default=str)
    print(json.dumps(summary(rows), indent=1, default=str))

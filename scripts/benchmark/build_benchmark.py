"""Turn a folder of expert match+timeline files into one small benchmark JSON the review page reads."""
import json, os, sys, statistics as S, datetime
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import analyse as A
ROLE = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "BOT", "UTILITY": "SUPPORT"}
STAT = lambda i, k: A.ITEMS.get(str(i), {}).get("stats", {}).get(k, 0)

def enemy_defense(m, me):
    """How many enemies built real armor / magic resist (from their final items, same on both sides)."""
    arm = mr = 0
    for p in m["participants"]:
        if p["teamId"] == me["teamId"]: continue
        items = [p["item%d" % k] for k in range(6)]
        if sum(STAT(i, "FlatArmorMod") for i in items) >= 80: arm += 1
        if sum(STAT(i, "FlatSpellBlockMod") for i in items) >= 80: mr += 1
    return arm, mr

def game(path):
    d = json.load(open(path)); m, tl = d["match"]["info"], d["timeline"]["info"]
    me = next(p for p in m["participants"] if p["puuid"] == d["expert"]["puuid"])
    opp = next((p for p in m["participants"] if p["teamId"] != me["teamId"] and p.get("teamPosition") == me.get("teamPosition")), None)
    r = A.one(path)
    fr = tl["frames"]; pf = lambda f, i: f["participantFrames"][str(i)]
    r["xp"] = [pf(f, me["participantId"])["xp"] for f in fr]
    r["level"] = [pf(f, me["participantId"])["level"] for f in fr]
    r["role"] = ROLE.get(me.get("teamPosition"), "")
    r["champ"] = me["championName"]
    # completed items in order (same rule as the review page)
    pid = me["participantId"]; buys = []
    for e in (e for f in fr for e in f["events"]):
        if e["type"] == "ITEM_PURCHASED" and e.get("participantId") == pid: buys.append([e["timestamp"] / 1000, e["itemId"]])
        if e["type"] == "ITEM_UNDO" and e.get("participantId") == pid:
            for b in reversed(buys):
                if b[1] == e.get("beforeId"): buys.remove(b); break
    r["items"] = [(t, i) for t, i in buys if A.legendary(i)]
    r["armor_n"], r["mr_n"] = enemy_defense(m, me)
    r["player"] = d["expert"]["name"]; r["region"] = d["expert"].get("region")
    return r

def q(v):
    v = [x for x in v if x is not None]
    if len(v) < 4: return None
    qs = S.quantiles(v, n=4)
    return [round(qs[0], 1), round(S.median(v), 1), round(qs[2], 1), len(v)]

def build(folder):
    rows = [game(os.path.join(folder, f)) for f in sorted(os.listdir(folder)) if f.endswith(".json")]
    n = len(rows)
    out = {"champion": rows[0]["champ"], "role": rows[0]["role"], "games": n, "winrate": round(sum(r["win"] for r in rows) / n, 3),
           "players": len({r["player"] for r in rows}), "regions": sorted({r["region"] for r in rows if r["region"]}),
           "built": datetime.date.today().isoformat(), "source": "onetricks.gg top players, Riot match-v5 ranked solo games",
           "minutes": {}, "timings": {}, "items": [], "orders": [], "opponents": Counter(r["opp"] for r in rows).most_common(10)}
    for k in ("gold", "cs", "xp", "level", "gdiff", "csdiff", "xpdiff"):
        out["minutes"][k] = [q([r[k][m] for r in rows if r.get(k) and len(r[k]) > m]) for m in range(31)]
    for k in ("first_back", "first_back_gold", "backs_before_14", "boots", "legendary1", "legendary2", "lvl6_gap",
              "deaths", "deaths_14", "deaths_14_jg", "kills_14", "time_dead", "kp", "dmg_share", "vision_pm", "control_wards"):
        out["timings"][k] = q([r.get(k) for r in rows])
    slot, when, by = defaultdict(list), defaultdict(list), defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        bought = {i: n_ for n_, (t, i) in enumerate(r["items"][:5])}
        for n_, (t, i) in enumerate(r["items"][:5]):
            slot[i].append(n_ + 1); when[i].append(t)
        for i in set(bought) | set():
            pass
    every = set(slot)
    for r in rows:
        bought = {i for _, i in r["items"][:5]}
        akey, mkey = "armor%d" % min(r["armor_n"], 2), "mr%d" % min(r["mr_n"], 2)
        for i in every:
            for key in (akey, mkey):
                by[i][key][1] += 1
                if i in bought: by[i][key][0] += 1
    for i in sorted(every, key=lambda i: -len(slot[i])):
        if len(slot[i]) < 3: continue
        out["items"].append({"id": i, "name": A.ITEMS.get(str(i), {}).get("name"), "rate": round(len(slot[i]) / n, 3),
                             "slot": S.median(slot[i]), "time": round(S.median(when[i])),
                             "slots": dict(Counter(slot[i])),
                             "by": {k: [v[0], v[1]] for k, v in by[i].items()}})
    out["orders"] = [[list(k), c] for k, c in Counter(tuple(i for _, i in r["items"][:3]) for r in rows if len(r["items"]) >= 3).most_common(6)]
    return out

if __name__ == "__main__":
    b = build(sys.argv[1]); name = "%s-%s.json" % (b["champion"], b["role"])
    os.makedirs(sys.argv[2], exist_ok=True)
    json.dump(b, open(os.path.join(sys.argv[2], name), "w"), separators=(",", ":"))
    print(name, b["games"], "games", os.path.getsize(os.path.join(sys.argv[2], name)), "bytes")

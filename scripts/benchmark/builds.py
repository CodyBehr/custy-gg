"""Build order: when and in which slot experts buy each completed item, and how armor on the enemy team changes it."""
import json, os, sys, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import analyse as A
NAME = lambda i: A.ITEMS.get(str(i), {}).get("name", str(i))
def build(path, puuid=None):
    d = json.load(open(path)); m, tl = d["match"]["info"], d["timeline"]["info"]
    puuid = puuid or d["expert"]["puuid"]
    me = next(p for p in m["participants"] if p["puuid"] == puuid); pid = me["participantId"]
    ev = [e for f in tl["frames"] for e in f["events"]]
    buys = []
    for e in ev:
        if e["type"] == "ITEM_PURCHASED" and e.get("participantId") == pid: buys.append([e["timestamp"] / 1000, e["itemId"]])
        if e["type"] == "ITEM_UNDO" and e.get("participantId") == pid:
            for b in reversed(buys):
                if b[1] == e.get("beforeId"): buys.remove(b); break
    items = [(t, i) for t, i in buys if A.legendary(i)]
    enemies = [p["participantId"] for p in m["participants"] if p["teamId"] != me["teamId"]]
    def armor_at(mm):
        f = tl["frames"][min(mm, len(tl["frames"]) - 1)]
        return sorted((f["participantFrames"][str(e)]["championStats"]["armor"] for e in enemies), reverse=True)
    opp = next((p for p in m["participants"] if p["teamId"] != me["teamId"] and p.get("teamPosition") == me.get("teamPosition")), {})
    return {"id": d["match"]["metadata"]["matchId"], "win": me["win"], "opp": opp.get("championName"),
            "items": items, "armor15": armor_at(15), "armor20": armor_at(20),
            "enemy": [p["championName"] for p in m["participants"] if p["teamId"] != me["teamId"]]}
folder = sys.argv[1]; focus = int(sys.argv[2]) if len(sys.argv) > 2 else None
rows = [build(os.path.join(folder, f)) for f in sorted(os.listdir(folder)) if f.endswith(".json")]
print("games", len(rows))
# Most common items and their usual slot/time
from collections import defaultdict
slot, when = defaultdict(list), defaultdict(list)
for r in rows:
    for n, (t, i) in enumerate(r["items"][:5]):
        slot[i].append(n + 1); when[i].append(t)
print("\nItem | games bought | usual slot | usual time")
for i in sorted(slot, key=lambda i: -len(slot[i]))[:14]:
    print("%-28s %3d (%2.0f%%)  slot %s  %s" % (NAME(i), len(slot[i]), 100 * len(slot[i]) / len(rows), S.median(slot[i]), "%d:%02d" % divmod(int(S.median(when[i])), 60)))
print("\nFirst three items, most common orders:")
from collections import Counter
for k, c in Counter(tuple(NAME(i) for _, i in r["items"][:3]) for r in rows if len(r["items"]) >= 3).most_common(8): print(" %2d  %s" % (c, " > ".join(k)))
if focus:
    print("\nFocus item:", NAME(focus))
    for lo, hi, label in ((0, 100, "enemy top armor at 15 < 100"), (100, 999, "enemy top armor at 15 >= 100")):
        grp = [r for r in rows if lo <= r["armor15"][0] < hi and len(r["items"]) >= 2]
        has = [r for r in grp if any(i == focus for _, i in r["items"][:4])]
        sl = [next(n + 1 for n, (_, i) in enumerate(r["items"]) if i == focus) for r in has]
        print("  %s: %d games, bought in first 4 items in %d%%, usual slot %s" % (label, len(grp), 100 * len(has) / max(1, len(grp)), S.median(sl) if sl else "-"))
    n_armor = lambda r: sum(1 for a in r["armor20"] if a >= 150)
    for k in (0, 1, 2, 3):
        grp = [r for r in rows if (n_armor(r) >= 3 if k == 3 else n_armor(r) == k) and len(r["items"]) >= 3]
        has = [next((n + 1 for n, (_, i) in enumerate(r["items"]) if i == focus), None) for r in grp]
        b = [h for h in has if h]
        print("  enemies with 150+ armor at 20 min = %s%s: %d games, LDR bought %d%%, usual slot %s" % (k, "+" if k == 3 else "", len(grp), 100 * len(b) / max(1, len(grp)), S.median(b) if b else "-"))

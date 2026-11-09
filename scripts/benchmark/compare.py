"""Put one game (yours) next to the expert set: python3 compare.py <expert folder> <your match file> <your puuid>"""
import json, os, sys, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import analyse as A, os
folder, mine, puuid = sys.argv[1], sys.argv[2], sys.argv[3]
rows = [A.one(os.path.join(folder, f)) for f in sorted(os.listdir(folder)) if f.endswith(".json")]
me = A.one(mine, puuid)
vs = [r for r in rows if r["opp"] == me["opp"]]
def band(rs, k, m):
    v = [r[k][m] for r in rs if r.get(k) and len(r[k]) > m]
    if len(v) < 3: return None
    q = S.quantiles(v, n=4) if len(v) >= 4 else [min(v), S.median(v), max(v)]
    return (round(S.median(v)), round(q[0]), round(q[2]), len(v))
def med(rs, k):
    v = [r[k] for r in rs if r.get(k) is not None]
    return (round(S.median(v), 2), len(v)) if v else None
out = {"you": {k: me[k] for k in me if k not in ("gold", "cs", "gdiff", "csdiff", "xpdiff", "unspent")}, "experts": len(rows), "experts_vs_same_opp": len(vs), "minutes": {}, "stats": {}}
for m in (5, 10, 15, 20):
    for k in ("gold", "cs", "gdiff", "csdiff", "xpdiff"):
        out["minutes"]["%s@%d" % (k, m)] = {"you": me[k][m] if me.get(k) and len(me[k]) > m else None, "all": band(rows, k, m), "same_opp": band(vs, k, m)}
for k in ("first_back", "first_back_gold", "backs_before_14", "boots", "legendary1", "legendary2", "lvl6_gap", "deaths", "deaths_14", "deaths_14_jg",
          "kills_14", "lane_cs_10", "lane_adv", "max_cs_adv", "kp", "dmg_share", "dpm", "vision_pm", "control_wards", "time_dead"):
    out["stats"][k] = {"you": me.get(k), "all": med(rows, k), "same_opp": med(vs, k)}
print(json.dumps(out, indent=1, ensure_ascii=False))

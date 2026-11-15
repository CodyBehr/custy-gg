"""How experts trade in one lane matchup, from their replays: every lane trade from both sides, then
openers, combos, levels and outcomes per champion.

    python3 expert_trades.py Garen-Darius-TOP <replay folder> [out.json]
Needs public/experts/<set>.json and <set>.timelines.json (scripts/research/expert_timelines.py).
"""
import collections, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "collector"))
import replay_trades as RT

name, folder = sys.argv[1], sys.argv[2]
out_path = sys.argv[3] if len(sys.argv) > 3 else None
games = json.load(open("public/experts/%s.json" % name))
tls = json.load(open("public/experts/%s.timelines.json" % name))
A, B = games["champions"]

rows = []      # one per trade, from the point of view of `champ`
for g in games["games"]:
    path = os.path.join(folder, "NA1-%d.rofl" % g["gameId"])
    tl = tls.get(str(g["gameId"]))
    if not os.path.exists(path) or not tl:
        continue
    _v, stats, _c = RT.read_rofl(path)
    slot = {c: RT.slot_of(stats, champion=c) for c in (A, B)}
    for me, opp in ((A, B), (B, A)):
        frames = []
        fm, fo = tl[me]["frames"], tl[opp]["frames"]
        for x, y in zip(fm, fo):
            frames.append({"t": x[0], "me": [x[1], x[2]], "opp": [y[1], y[2]]})
        kills = {"me": tl[me]["deaths"], "opp": tl[opp]["deaths"]}
        res = RT.lane_trades(path, slot[me], slot[opp], frames, kills)
        for tr in res.get("trades", []):
            mine = [s["k"] for s in tr["seq"] if s["w"] == "you"]
            theirs = [s["k"] for s in tr["seq"] if s["w"] == "them"]
            # who pressed the first button: our first cast vs theirs, by order in the sequence
            first_cast = tr["seq"][0]["w"] if tr["seq"] else None
            rows.append(dict(game=g["gameId"], champ=me, opp=opp, t=tr["t0"], lv=tr["lv"][0], olv=tr["lv"][1],
                             net=tr["dealt"] - tr["took"], dealt=tr["dealt"], took=tr["took"], gank=tr["gank"],
                             died=tr["died"], first_hit=tr["first"], first_cast=first_cast,
                             opener=mine[0] if mine else "auto", combo=mine[:3], theirs=theirs[:3],
                             hp=round(100 * tr["hpMe"][0] / max(1, tr["hpMe"][1])),
                             ohp=round(100 * tr["hpOpp"][0] / max(1, tr["hpOpp"][1])),
                             solo=tr.get("solo", True), others=[o["champ"] for o in tr.get("others", [])],
                             won=None if not tr.get("solo", True) else (tr["dealt"] - tr["took"] > 0 or "them" in tr["died"]) and "you" not in tr["died"]))


def pct(a, b):
    return round(100 * a / b) if b else None


summary = {"set": name, "games": len({r["game"] for r in rows}), "champions": {}}
for c in (A, B):
    R = [r for r in rows if r["champ"] == c and r["won"] is not None]
    S = {"trades": len(R), "won": pct(sum(r["won"] for r in R), len(R))}
    op = collections.defaultdict(list)
    for r in R:
        if r["first_cast"] == "you" or r["opener"] == "auto":
            op[r["opener"]].append(r)
    S["openers"] = sorted([{"opener": k, "n": len(v), "won": pct(sum(r["won"] for r in v), len(v)),
                            "net": round(sum(r["net"] for r in v) / len(v))} for k, v in op.items()], key=lambda x: -x["n"])
    cb = collections.defaultdict(list)
    for r in R:
        if r["combo"]:
            cb[" > ".join(r["combo"])].append(r)
    S["combos"] = sorted([{"combo": k, "n": len(v), "won": pct(sum(r["won"] for r in v), len(v)),
                           "net": round(sum(r["net"] for r in v) / len(v))} for k, v in cb.items()], key=lambda x: -x["n"])[:8]
    lv = collections.defaultdict(list)
    for r in R:
        lv["1-2" if r["lv"] <= 2 else "3-5" if r["lv"] <= 5 else "6+"].append(r)
    S["by_level"] = {k: {"n": len(v), "won": pct(sum(r["won"] for r in v), len(v))} for k, v in sorted(lv.items())}
    S["hp_going_in"] = {"won": round(sum(r["hp"] for r in R if r["won"]) / max(1, sum(1 for r in R if r["won"]))),
                        "lost": round(sum(r["hp"] for r in R if not r["won"]) / max(1, sum(1 for r in R if not r["won"])))}
    S["used_first"] = pct(sum(1 for r in R if r["first_cast"] == "you"), sum(1 for r in R if r["first_cast"]))
    S["deaths_in_trades"] = sum(1 for r in R if "you" in r["died"])
    S["kills_in_trades"] = sum(1 for r in R if "them" in r["died"])
    summary["champions"][c] = S
summary["rows"] = rows
txt = json.dumps(summary, indent=1)
if out_path:
    open(out_path, "w").write(txt)
for c, S in summary["champions"].items():
    print("\n==", c, "vs", B if c == A else A, "|", S["trades"], "trades, won", S["won"], "% | first to press a button",
          S["used_first"], "% | HP going in won/lost", S["hp_going_in"], "| kills/deaths in trades", S["kills_in_trades"], S["deaths_in_trades"])
    print("  openers:", [(o["opener"], o["n"], o["won"], o["net"]) for o in S["openers"]])
    print("  combos:", [(o["combo"], o["n"], o["won"], o["net"]) for o in S["combos"][:6]])
    print("  by level:", S["by_level"])

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

import urllib.request
CD = {}
for c in (A, B):
    data = json.loads(urllib.request.urlopen("https://ddragon.leagueoflegends.com/cdn/16.22.1/data/en_US/champion/%s.json" % c).read())
    CD[c] = {k: sp["cooldown"][0] for k, sp in zip("QWER", list(data["data"].values())[0]["spells"])}
LONG = 12    # only abilities this slow: "used it a moment ago" reliably means "it's still down"


def down(casts, k, t, champ):
    """Long-cooldown abilities of champion slot k that were used within ~90% of their (rank 1) cooldown before t."""
    out = []
    for key, cd in CD[champ].items():
        if cd < LONG:
            continue
        last = max([tc for tc, kk, L in casts if kk == k and L == key and tc < t - 0.5] or [-1e9])
        if t - last < 0.9 * cd:
            out.append(key)
    return out


def down_share(casts, k, champ, a=90, b=840):
    """Share of the laning phase (1:30–14:00) each long-cooldown ability of slot k spends on cooldown."""
    out = {}
    for key, cd in CD[champ].items():
        if cd < LONG:
            continue
        spans, total = [], 0.0
        for tc, kk, L in casts:
            if kk == k and L == key and a <= tc <= b:
                spans.append((tc, min(b, tc + 0.9 * cd)))
        end = a
        for x, y in sorted(spans):
            x = max(x, end)
            if y > x:
                total += y - x; end = y
        out[key] = total / (b - a)
    return out


DOWNTIME = collections.defaultdict(list)   # (champ, key) -> per-game share of laning spent on cooldown
rows = []      # one per trade, from the point of view of `champ`
for g in games["games"]:
    path = os.path.join(folder, "NA1-%d.rofl" % g["gameId"])
    tl = tls.get(str(g["gameId"]))
    if not os.path.exists(path) or not tl:
        continue
    _v, stats, _c = RT.read_rofl(path)
    slot = {c: RT.slot_of(stats, champion=c) for c in (A, B)}
    casts = RT.decode(path, until=900)["casts"]
    for c in (A, B):
        for key, v in down_share(casts, slot[c], c).items():
            DOWNTIME[(c, key)].append(v)
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
            rows.append(dict(game=g["gameId"], champ=me, opp=opp, t=tr["t0"], t1=tr["t1"], lv=tr["lv"][0], olv=tr["lv"][1],
                             opp_down=down(casts, slot[opp], tr["t0"] - 2, opp), my_down=down(casts, slot[me], tr["t0"] - 2, me),
                             netp=round(100 * (tr["dealt"] / max(1, tr["hpOpp"][1]) - tr["took"] / max(1, tr["hpMe"][1]))),
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
import math


def z2(a, n, b, m):
    """Two-proportion z: how sure we are that a/n really differs from b/m."""
    if n < 6 or m < 6:
        return 0.0
    p = (a + b) / (n + m)
    se = math.sqrt(max(1e-9, p * (1 - p) * (1 / n + 1 / m)))
    return (a / n - b / m) / se


def fmt(t, **kw):
    for k, v in kw.items():
        t = t.replace("{%s}" % k, str(v))
    return t


def takeaways(c):
    """Every pattern we can test, scored by how big and how reliable the difference is; the best few become
    plain advice. Works for any matchup: nothing here is about Garen or Darius."""
    o = B if c == A else A
    R = [r for r in rows if r["champ"] == c and r["won"] is not None]
    W = lambda rr: sum(1 for r in rr if r["won"])
    cands = []

    def split(family, yes, no, good, bad):
        a, n, b, m = W(yes), len(yes), W(no), len(no)
        z = z2(a, n, b, m)
        if z >= 0:
            cands.append(dict(family=family, z=z, text=fmt(good, a=a, n=n, b=b, m=m), nums=[a, n, b, m]))
        else:
            cands.append(dict(family=family, z=-z, text=fmt(bad, a=a, n=n, b=b, m=m), nums=[b, m, a, n]))

    short = [r for r in R if r["t1"] - r["t"] < 3]; long_ = [r for r in R if r["t1"] - r["t"] >= 3]
    split("length", short, long_,
          "Keep trades short: under 3 seconds you won {a} of {n}, longer ones {b} of {m}.",
          "Commit to longer trades: 3 seconds or more you won {b} of {m}, short ones {a} of {n}.")
    pre = [r for r in R if r["lv"] < 6]; post = [r for r in R if r["lv"] >= 6]
    split("six", post, pre,
          "Wait for level 6 to trade: from 6 on you won {a} of {n}, before it {b} of {m}.",
          "Trade early, before level 6: you won {b} of {m} before 6 and {a} of {n} after.")
    up = [r for r in R if r["lv"] > r["olv"]]; notup = [r for r in R if r["lv"] <= r["olv"]]
    split("level", up, notup,
          "Trade when you're a level up: you won {a} of {n}, otherwise {b} of {m}.",
          "Level leads don't help here: a level up you won {a} of {n}, otherwise {b} of {m}.")
    me_first = [r for r in R if r["first_cast"] == "you"]; them_first = [r for r in R if r["first_cast"] == "them"]
    split("starter", me_first, them_first,
          "Start the trades yourself: you won {a} of {n} you started, {b} of {m} " + o + " started.",
          "Let " + o + " commit first, then answer: you won {b} of {m} they started, {a} of {n} you started.")
    for key, cd in CD[o].items():
        if cd >= LONG:
            dn = [r for r in R if key in r["opp_down"]]; upk = [r for r in R if key not in r["opp_down"]]
            split("opp_cd_" + key, dn, upk,
                  "Trade when " + o + "'s {opp:" + key + "} is on cooldown: you won {a} of {n}, otherwise {b} of {m}.",
                  o + "'s {opp:" + key + "} being down didn't help: {a} of {n} vs {b} of {m}.")
    # what experts avoid: trades started with their own long-cooldown ability down, vs how often it's down at all
    for key, cd in CD[c].items():
        if cd < LONG or not DOWNTIME[(c, key)]:
            continue
        q = sum(DOWNTIME[(c, key)]) / len(DOWNTIME[(c, key)])
        k = sum(1 for r in R if key in r["my_down"]); N = len(R)
        if N >= 20 and 0.05 < q < 0.95:
            z = (q - k / N) / math.sqrt(q * (1 - q) / N)
            if z > 0:
                cands.append(dict(family="own_cd_" + key, z=z, nums=[k, N, round(100 * q)],
                                  text="Don't start a trade with your {me:%s} on cooldown: it's down about %d%% of the laning phase, "
                                       "but only %d of %d expert trades started that way." % (key, round(100 * q), k, N)))
    opens = collections.defaultdict(list)
    for r in R:
        if r["first_cast"] == "you" and r["opener"] != "auto":
            opens[r["opener"]].append(r)
    for key, rr in opens.items():
        rest = [r for k2, v in opens.items() if k2 != key for r in v]
        a, n, b, m = W(rr), len(rr), W(rest), len(rest)
        z = z2(a, n, b, m)
        if z > 0:
            cands.append(dict(family="opener", z=z, nums=[a, n, b, m],
                              text="Open with {me:%s}: you won %d of %d trades started with it, %d of %d with your other abilities." % (key, a, n, b, m)))
    best = {}
    for x in cands:       # one per family, strongest first
        if x["z"] >= 1.96 and (x["family"] not in best or x["z"] > best[x["family"]]["z"]):
            best[x["family"]] = x
    return sorted(best.values(), key=lambda x: -x["z"]), sorted(cands, key=lambda x: -x["z"])


for c in (A, B):
    top, allc = takeaways(c)
    summary["champions"][c]["takeaways"] = [{k: x[k] for k in ("family", "text", "nums")} | {"z": round(x["z"], 2)} for x in top]
    print("\n== Takeaways for", c)
    for x in top[:5]:
        print("  z=%.1f  %s" % (x["z"], x["text"]))
    print("  (not shown, weaker:)", [(x["family"], round(x["z"], 1)) for x in allc if x not in top][:6])
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


def line(label, rr):
    if not rr:
        return
    w = sum(r["won"] for r in rr)
    print("   %-44s won %2d of %2d (%3d%%)  avg net %+d%% of max HP" % (label, w, len(rr), round(100 * w / len(rr)), round(sum(r["netp"] for r in rr) / len(rr))))


for c in (A, B):
    o = B if c == A else A
    R = [r for r in rows if r["champ"] == c and r["won"] is not None]
    print("\n== General patterns, %s vs %s (%d 1v1 trades)" % (c, o, len(R)))
    line("%s pressed the first button" % c, [r for r in R if r["first_cast"] == "you"])
    line("%s pressed first" % o, [r for r in R if r["first_cast"] == "them"])
    for key in [k for k, cd in CD[o].items() if cd >= LONG]:
        line("%s's %s was down when it started" % (o, key), [r for r in R if key in r["opp_down"]])
        line("%s's %s was up" % (o, key), [r for r in R if key not in r["opp_down"]])
    for key in [k for k, cd in CD[c].items() if cd >= LONG]:
        line("own %s was down when it started" % key, [r for r in R if key in r["my_down"]])
    line("level ahead", [r for r in R if r["lv"] > r["olv"]])
    line("same level", [r for r in R if r["lv"] == r["olv"]])
    line("level behind", [r for r in R if r["lv"] < r["olv"]])
    line("15%+ more HP going in", [r for r in R if r["hp"] - r["ohp"] >= 15])
    line("HP within 15%", [r for r in R if abs(r["hp"] - r["ohp"]) < 15])
    line("15%+ less HP going in", [r for r in R if r["ohp"] - r["hp"] >= 15])
    line("short trade (under 3 s)", [r for r in R if r["t1"] - r["t"] < 3])
    line("long trade (3 s+)", [r for r in R if r["t1"] - r["t"] >= 3])

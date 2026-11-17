"""
Model-ready rows from the expert games custy coach uploads to R2 (games/<patch>/<gameId>.json.gz, each the output
of replay_trades.decode()). One row per 1v1 lane fight in top or mid, from both laners' side, with the state when
it started and how it turned out. Riot's timeline (optional, from match-pull.yml) adds exact health anchors and deaths.

  python3 lane_rows.py <data dir with *.json.gz> [timeline dir] > rows.csv

State: champions, levels (skill points so far), health % (needs the timeline), seconds since each side last used
Q/W/E/R, minions of each side within 1,100 units, distance to each side's outer tower, game time.
Outcome: damage dealt and taken (each as % of max health when the timeline is there), net, and whether either
laner died within 20 s of the fight's start (timeline kills).
Only 1v1: no other champion within 1,400 units of either laner from 3 s before to 4 s after, and no damage from one.
"""

import csv
import glob
import gzip
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "collector"))
import replay_trades as RT  # noqa: E402

TOWERS = {("TOP", 100): (981, 10441), ("TOP", 200): (4318, 13875), ("MIDDLE", 100): (5846, 6396), ("MIDDLE", 200): (8955, 8510)}
FIELDS = ["game", "patch", "t", "lane", "me", "opp", "lvMe", "lvOpp", "hpMe", "hpOpp", "first",
          "sinceQme", "sinceWme", "sinceEme", "sinceRme", "sinceQopp", "sinceWopp", "sinceEopp", "sinceRopp",
          "minMine", "minTheirs", "toMyTower", "toTheirTower", "dur", "dealt", "took", "dealtPct", "tookPct", "netPct",
          "iDied", "theyDied"]


def load_timeline(tdir, gid):
    p = os.path.join(tdir or "", "NA1_%s.json.gz" % gid)
    if not tdir or not os.path.exists(p):
        return None
    return json.load(gzip.open(p))


def rows_for(d, tl):
    stats = d["stats"]
    skins = [s.get("SKIN") for s in stats]
    tracks = {}
    for k, L in d["tracks"].items():
        tracks[int(k)] = L
    hits = d["hits"]
    casts = d["casts"]
    levels = d["levels"]
    team = [int(s.get("TEAM") or (100 if i < 5 else 200)) for i, s in enumerate(stats)]
    pos = [s.get("TEAM_POSITION") or s.get("INDIVIDUAL_POSITION") for s in stats]
    hpa, kills, mx = {}, {}, {}
    if tl:
        pid = {p["championName"]: p["participantId"] for p in tl["match"]["info"]["participants"]}
        fr = tl["timeline"]["info"]["frames"]
        for k, s in enumerate(skins):
            if s in pid:
                hpa[k] = [(f["timestamp"] / 1000, f["participantFrames"][str(pid[s])]["championStats"]["health"],
                           f["participantFrames"][str(pid[s])]["championStats"]["healthMax"]) for f in fr]
        inv = {v: skins.index(n) for n, v in pid.items() if n in skins}
        for f in fr:
            for e in f["events"]:
                if e["type"] == "CHAMPION_KILL" and e["victimId"] in inv:
                    kills.setdefault(inv[e["victimId"]], []).append(e["timestamp"] / 1000)

    def hp_at(k, t):
        if k not in hpa:
            return None, None
        S = RT.hp_series({"hits": hits}, {k: hpa[k]}, kills, t, t, 0.5)
        v = S.get(str(k)) or []
        if not v:
            return None, None
        A = hpa[k]
        m = max(0, min(len(A) - 1, int(t // 60)))
        return v[0][1], A[m][2]

    out = []
    for lane in ("TOP", "MIDDLE"):
        ks = [k for k in range(10) if pos[k] == lane]
        if len(ks) != 2 or team[ks[0]] == team[ks[1]]:
            continue
        for i, j in ((ks[0], ks[1]), (ks[1], ks[0])):
            duel = sorted((t, a, v) for t, tg, a, v in hits if 30 <= t <= 840 and {a, tg} == {i, j})
            groups, cur = [], []
            for e in duel:
                if cur and e[0] - cur[-1][0] > 3:
                    groups.append(cur)
                    cur = []
                cur.append(e)
            if cur:
                groups.append(cur)
            for w in groups:
                t0, t1 = w[0][0], w[-1][0]
                dealt = sum(v for _, a, v in w if a == i)
                took = sum(v for _, a, v in w if a == j)
                if dealt + took < 60:
                    continue
                # 1v1 only
                solo = not any(a not in (i, j) and a is not None and tg in (i, j) and t0 - 2 <= t <= t1 + 4 for t, tg, a, v in hits)
                if solo:
                    for k in range(10):
                        if k in (i, j) or k not in tracks:
                            continue
                        tt = t0 - 3
                        while tt <= t1 + 4 and solo:
                            a = RT._at(tracks[k], tt)
                            for m in (i, j):
                                b = RT._at(tracks.get(m), tt) if m in tracks else None
                                if a and b and math.hypot(a[0] - b[0], a[1] - b[1]) < 1400:
                                    solo = False
                            tt += 0.5
                if not solo:
                    continue
                pm = RT._at(tracks.get(i), t0) if i in tracks else None
                po = RT._at(tracks.get(j), t0) if j in tracks else None
                if not pm or not po:
                    continue
                cx, cz = (pm[0] + po[0]) / 2, (pm[1] + po[1]) / 2
                mine = theirs = 0
                for key, L in tracks.items():
                    if key < 10 or len(L) < 2:
                        continue
                    q = RT._at(L, t0)
                    if not q or math.hypot(q[0] - cx, q[1] - cz) > 1100 or t0 - L[-1][0] > 4:
                        continue
                    tm = 100 if math.hypot(L[0][1] - 1500, L[0][2] - 1500) < math.hypot(L[0][1] - 13300, L[0][2] - 13300) else 200
                    if tm == team[i]:
                        mine += 1
                    else:
                        theirs += 1
                since = {}
                for who, k in (("me", i), ("opp", j)):
                    for sl in "QWER":
                        last = max([t for t, kk, s in casts if kk == k and s == sl and t < t0 - 0.3], default=None)
                        since[sl + who] = round(t0 - last, 1) if last is not None else ""
                hm, mm = hp_at(i, t0)
                ho, mo = hp_at(j, t0)
                mt, ot = TOWERS[(lane, team[i])], TOWERS[(lane, team[j])]
                died = lambda k: int(any(t0 <= x <= t0 + 20 for x in kills.get(k, [])))
                out.append({
                    "game": (d.get("game") or {}).get("gameId"), "patch": d["version"][:5], "t": round(t0, 1), "lane": lane,
                    "me": skins[i], "opp": skins[j],
                    "lvMe": sum(1 for t, k in levels if k == i and t <= t0), "lvOpp": sum(1 for t, k in levels if k == j and t <= t0),
                    "hpMe": round(100 * hm / mm) if hm is not None and mm else "", "hpOpp": round(100 * ho / mo) if ho is not None and mo else "",
                    "first": "me" if w[0][1] == i else "opp",
                    "sinceQme": since["Qme"], "sinceWme": since["Wme"], "sinceEme": since["Eme"], "sinceRme": since["Rme"],
                    "sinceQopp": since["Qopp"], "sinceWopp": since["Wopp"], "sinceEopp": since["Eopp"], "sinceRopp": since["Ropp"],
                    "minMine": mine, "minTheirs": theirs,
                    "toMyTower": round(math.hypot(cx - mt[0], cz - mt[1])), "toTheirTower": round(math.hypot(cx - ot[0], cz - ot[1])),
                    "dur": round(t1 - t0, 1), "dealt": round(dealt), "took": round(took),
                    "dealtPct": round(100 * dealt / mo, 1) if mo else "", "tookPct": round(100 * took / mm, 1) if mm else "",
                    "netPct": round(100 * (dealt / mo - took / mm), 1) if mo and mm else "",
                    "iDied": died(i) if kills else "", "theyDied": died(j) if kills else ""})
    return out


if __name__ == "__main__":
    ddir = sys.argv[1]
    tdir = sys.argv[2] if len(sys.argv) > 2 else None
    w = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    w.writeheader()
    n = 0
    for p in sorted(glob.glob(os.path.join(ddir, "*.json.gz"))):
        d = json.load(gzip.open(p))
        gid = os.path.basename(p).split(".")[0]
        try:
            for r in rows_for(d, load_timeline(tdir, gid)):
                w.writerow(r)
                n += 1
        except Exception as e:
            print("skip %s: %s" % (gid, e), file=sys.stderr)
    print("rows: %d" % n, file=sys.stderr)

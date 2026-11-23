"""
Rows for the fight model: one row per 1v1 top/mid lane fight in the expert games (games/<patch>/<id>.json.gz, the
output of replay_trades.decode()), from both laners' side.

  python3 fight_rows.py <out.csv> <timeline dir> <data dir> [<data dir> ...]

State when the fight starts: game time, champions, levels, health % (the replay's own minute health, which matches
Riot's within 1 HP 99.7% of the time on 16.23, plus every hit since; healing between minute marks is spread evenly),
seconds since each side last used Q/W/E/R and that as a share of the ability's rank-1 cooldown, Flash up, who hit
first, minions of each side nearby, distance to each side's outer tower, item gold gap (from Riot's timeline).

Outcome, built on things healing can't fool: who died within 20 s (Riot's kills), else who was healthier at the next minute mark (exact numbers;
no recall or death in between; within 5 points is a draw). Plus the fight's
own damage each way as % of max health, for reference.
"""
import csv
import glob
import gzip
import json
import math
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "collector"))
import replay_trades as RT  # noqa: E402
import replay_waves as W  # noqa: E402
import champ_cd  # noqa: E402

TOWERS = {("TOP", 100): (981, 10441), ("TOP", 200): (4318, 13875), ("MIDDLE", 100): (5846, 6396), ("MIDDLE", 200): (8955, 8510)}
FOUNTAIN = {100: (400, 400), 200: (14400, 14400)}
FIELDS = ["game", "kind", "patch", "t", "lane", "me", "opp", "lvMe", "lvOpp", "hpMe", "hpOpp", "first",
          "sinceQme", "sinceWme", "sinceEme", "sinceRme", "sinceQopp", "sinceWopp", "sinceEopp", "sinceRopp",
          "readyQme", "readyWme", "readyEme", "readyRme", "readyQopp", "readyWopp", "readyEopp", "readyRopp",
          "keyMe", "keyOpp", "flashMe", "flashOpp", "minMine", "minTheirs", "toMyTower", "toTheirTower", "goldGap",
          "dur", "dealtPct", "tookPct", "netPct", "iDied", "theyDied", "leadNow", "leadNext", "swing", "nextIn", "won"]


def _hp_anchors(d):
    out = {}
    for k, L in (d.get("hp") or {}).items():
        out[int(k)] = sorted((t, h, m) for t, h, m in L)
    return out


def _timeline(tdir, gid):
    for name in ("NA1_%s.json.gz" % gid,):
        p = os.path.join(tdir, name)
        if os.path.exists(p):
            try:
                return json.load(gzip.open(p))
            except (OSError, ValueError):
                return None
    return None


def rows_for(args):
    path, tdir = args
    gid = os.path.basename(path).split(".")[0]
    try:
        d = json.load(gzip.open(path))
    except (OSError, ValueError):
        return []
    tl = _timeline(tdir, gid)
    if not tl or not d.get("hits") or not d.get("hp"):
        return []
    stats = d["stats"]
    skins = [s.get("SKIN") for s in stats]
    team = [int(s.get("TEAM") or (100 if i < 5 else 200)) for i, s in enumerate(stats)]
    pos = [s.get("TEAM_POSITION") or s.get("INDIVIDUAL_POSITION") for s in stats]
    tracks = {int(k): L for k, L in d["tracks"].items()}
    hits, casts, levels = d["hits"], d["casts"], d["levels"]
    summs = d.get("summs") or []
    hpa = _hp_anchors(d)

    # Riot: kills and item gold per minute, matched to replay slots by champion and team
    m, fr = tl["match"]["info"], tl["timeline"]["info"]["frames"]
    pid = {}
    for p in m["participants"]:
        for k, s in enumerate(skins):
            if s and s.lower() == p["championName"].lower() and (k < 5) == (p["teamId"] == 100):
                pid[k] = p["participantId"]
    inv = {v: k for k, v in pid.items()}
    kills = {}
    for f in fr:
        for e in f.get("events") or []:
            if e.get("type") == "CHAMPION_KILL" and e.get("victimId") in inv:
                kills.setdefault(inv[e["victimId"]], []).append(e["timestamp"] / 1000)
    # Ability ranks from Riot's skill-ups: the cooldown at the rank they actually had (champ_cd per-rank cooldowns)
    ranks = {}
    for f in fr:
        for e in f.get("events") or []:
            if e.get("type") == "SKILL_LEVEL_UP" and e.get("participantId") in inv and e.get("levelUpType") != "EVOLVE":
                ranks.setdefault(inv[e["participantId"]], []).append((e["timestamp"] / 1000, "QWER"[e["skillSlot"] - 1]))

    def rank(k, sl, t):
        return sum(1 for tt, x in ranks.get(k, []) if x == sl and tt <= t)

    backs = {}
    for k, t, _x, _z in W.recalls(d, kills, 900):
        backs.setdefault(k, []).append(t)

    def item_gold(k, t):
        if k not in pid:
            return None
        f = fr[min(len(fr) - 1, int(t // 60))]["participantFrames"].get(str(pid[k])) or {}
        return (f.get("totalGold") or 0) - (f.get("currentGold") or 0)

    def hp_at(k, t):
        A = hpa.get(k) or []
        if len(A) < 2:
            return None
        i = max(0, min(len(A) - 2, max(x for x in range(len(A)) if A[x][0] <= t) if A[0][0] <= t else 0))
        (t0, h0, m0), (t1, h1, m1) = A[i], A[i + 1]
        if any(t0 < x <= t1 for x in kills.get(k, []) + backs.get(k, [])):
            # a death or recall in this minute: count down from the earlier mark only
            dmg = sum(v for ht, tg, a, v in hits if tg == k and t0 < ht <= t)
            return max(0.0, min(m0, h0 - dmg)), m0
        dmg = lambda a, b: sum(v for ht, tg, aa, v in hits if tg == k and a < ht <= b)
        heal = max(0.0, h1 - h0 + dmg(t0, t1))
        f = (t - t0) / max(1e-6, t1 - t0)
        return max(0.0, min(m0 + (m1 - m0) * f, h0 - dmg(t0, t) + heal * f)), m0 + (m1 - m0) * f

    def next_mark(k, t):
        """The first minute mark after t with no death or recall of k in between: (time, hp, max) or None."""
        for (tt, h, mm) in hpa.get(k) or []:
            if tt > t + 2:
                if any(t < x <= tt for x in kills.get(k, []) + backs.get(k, [])):
                    return None
                return tt, h, mm
        return None

    def level(k, t):
        return sum(1 for tt, kk in levels if kk == k and tt <= t)

    out = []
    for lane in ("TOP", "MIDDLE"):
        ks = [k for k in range(10) if pos[k] == lane]
        if len(ks) != 2 or team[ks[0]] == team[ks[1]]:
            continue
        for i, j in ((ks[0], ks[1]), (ks[1], ks[0])):
            duel = sorted((t, a, v) for t, tg, a, v in hits if 60 <= t <= 840 and {a, tg} == {i, j})
            groups, cur = [], []
            for e in duel:
                if cur and e[0] - cur[-1][0] > 3:
                    groups.append(cur)
                    cur = []
                cur.append(e)
            if cur:
                groups.append(cur)
            fight_times = [x[0] for x in duel]
            # Calm moments: every 10 s when the two are within 1,500 units, both alive, and no hit between them for
            # 8 s before and 20 s after. The same state, but no fight: what "not taking it" usually leads to.
            calm = []
            tt = 90.0
            while tt <= 840:
                a_, b_ = RT._at(tracks.get(i), tt) if i in tracks else None, RT._at(tracks.get(j), tt) if j in tracks else None
                if a_ and b_ and math.hypot(a_[0] - b_[0], a_[1] - b_[1]) < 1500 and not any(tt - 8 <= x <= tt + 20 for x in fight_times) \
                        and not any(tt - 20 <= x <= tt for x in kills.get(i, []) + kills.get(j, [])):
                    calm.append([(tt, None, 0)])
                tt += 10
            for w in [("fight", g) for g in groups] + [("calm", c) for c in calm]:
                kind, w = w
                t0, t1 = w[0][0], w[-1][0]
                dealt = sum(v for _, a, v in w if a == i)
                took = sum(v for _, a, v in w if a == j)
                if kind == "fight" and dealt + took < 60:
                    continue
                solo = kind == "calm" or not any(a not in (i, j) and a is not None and tg in (i, j) and t0 - 2 <= t <= t1 + 4 for t, tg, a, v in hits)
                if solo:
                    for k in range(10):
                        if k in (i, j) or k not in tracks or not solo:
                            continue
                        tt = t0 - 3
                        while tt <= t1 + 4 and solo:
                            a = RT._at(tracks[k], tt)
                            for mm in (i, j):
                                b = RT._at(tracks.get(mm), tt) if mm in tracks else None
                                if a and b and math.hypot(a[0] - b[0], a[1] - b[1]) < 1400:
                                    solo = False
                            tt += 1.0
                if not solo:
                    continue
                pm = RT._at(tracks.get(i), t0) if i in tracks else None
                po = RT._at(tracks.get(j), t0) if j in tracks else None
                if not pm or not po:
                    continue
                hm, ho = hp_at(i, t0), hp_at(j, t0)
                if not hm or not ho or not hm[1] or not ho[1]:
                    continue
                cx, cz = (pm[0] + po[0]) / 2, (pm[1] + po[1]) / 2
                mine = theirs = 0
                for key, L in tracks.items():
                    if key < 10 or len(L) < 2 or t0 - L[-1][0] > 4:
                        continue
                    q = RT._at(L, t0)
                    if not q or math.hypot(q[0] - cx, q[1] - cz) > 1100:
                        continue
                    tm = 100 if math.hypot(L[0][1] - 1500, L[0][2] - 1500) < math.hypot(L[0][1] - 13300, L[0][2] - 13300) else 200
                    if tm == team[i]:
                        mine += 1
                    else:
                        theirs += 1
                row = {"game": gid, "patch": d["version"][:5], "t": round(t0, 1), "lane": lane, "me": skins[i], "opp": skins[j],
                       "lvMe": level(i, t0), "lvOpp": level(j, t0),
                       "hpMe": round(100 * hm[0] / hm[1]), "hpOpp": round(100 * ho[0] / ho[1]),
                       "first": (1 if w[0][1] == i else 0) if kind == "fight" else "", "kind": kind}
                for who, k in (("me", i), ("opp", j)):
                    cd = (champ_cd.CD.get(skins[k]) or {}).get("cd") or {}
                    for sl in "QWER":
                        last = max([t for t, kk, s in casts if kk == k and s == sl and t < t0 - 0.3], default=None)
                        since = t0 - last if last is not None else 999.0
                        row["since%s%s" % (sl, who)] = round(min(since, 999.0), 1)
                        rk = rank(k, sl, t0)
                        cds = cd.get(sl) or []
                        c1 = cds[min(len(cds), max(1, rk)) - 1] if cds else None
                        # 0 = not learned yet; otherwise time since the last cast as a share of the cooldown at their rank
                        row["ready%s%s" % (sl, who)] = (0.0 if rk == 0 else round(min(3.0, since / c1), 2)) if c1 else ""
                    key = (champ_cd.CD.get(skins[k]) or {}).get("key")
                    row["key" + who.capitalize()] = row.get("ready%s%s" % (key, who), "") if key else ""
                    fl = max([t for t, kk, n in summs if kk == k and n == "Flash" and t < t0], default=None)
                    row["flash" + who.capitalize()] = 1 if fl is None or t0 - fl >= 300 else 0
                mt, ot = TOWERS[(lane, team[i])], TOWERS[(lane, team[j])]
                gi, gj = item_gold(i, t0), item_gold(j, t0)
                died = lambda k: int(any(t0 <= x <= t0 + 20 for x in kills.get(k, [])))
                lead_now = hm[0] / hm[1] - ho[0] / ho[1]
                ni, nj = next_mark(i, t1), next_mark(j, t1)
                if ni and nj and abs(ni[0] - nj[0]) < 2:
                    lead_next = ni[1] / ni[2] - nj[1] / nj[2]
                    row.update(leadNext=round(100 * lead_next, 1), swing=round(100 * (lead_next - lead_now), 1), nextIn=round(ni[0] - t0))
                else:
                    row.update(leadNext="", swing="", nextIn="")
                a, b = died(i), died(j)
                # Who came out ahead: a death decides it; otherwise who was healthier at the next minute mark (exact
                # numbers, healing included). Within 5 points it's a draw and left out. The starting health is an input,
                # so the model learns how much of that is just the lead you walked in with.
                won = 1 if (b and not a) else 0 if (a and not b) else ""
                if won == "" and row["leadNext"] != "" and not (a and b):
                    won = 1 if row["leadNext"] > 5 else 0 if row["leadNext"] < -5 else ""
                row.update(minMine=mine, minTheirs=theirs,
                           toMyTower=round(math.hypot(cx - mt[0], cz - mt[1])), toTheirTower=round(math.hypot(cx - ot[0], cz - ot[1])),
                           goldGap=(gi - gj) if gi is not None and gj is not None else "",
                           dur=round(t1 - t0, 1), dealtPct=round(100 * dealt / ho[1], 1), tookPct=round(100 * took / hm[1], 1),
                           netPct=round(100 * (dealt / ho[1] - took / hm[1]), 1), iDied=a, theyDied=b,
                           leadNow=round(100 * lead_now, 1), won=won)
                out.append(row)
    return out


if __name__ == "__main__":
    out_path, tdir, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
    files = sorted(p for dd in dirs for p in glob.glob(os.path.join(dd, "*.json.gz")))
    n = games = 0
    with open(out_path, "w", newline="") as fh, Pool(max(1, os.cpu_count() - 1)) as pool:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for rows in pool.imap_unordered(rows_for, [(p, tdir) for p in files], chunksize=4):
            if rows:
                games += 1
            for r in rows:
                w.writerow(r)
                n += 1
    print("%d rows from %d games (of %d files)" % (n, games, len(files)), file=sys.stderr)

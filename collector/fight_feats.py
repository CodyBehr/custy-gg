"""
The state of a 1v1 lane fight when it starts, as the fight model sees it. Shared by the research rows
(scripts/research/fight_rows.py, Riot timelines) and the app's trade reads (coach_reads.py, the client's timeline plus
the site's), so the model gets the same inputs in both places.

Ctx(d, kills, ranks, item_gold): d = replay_trades.decode() output; kills = {slot: [death times]}; ranks =
{slot: [(time, "Q"/"W"/"E"/"R")]} from skill-ups; item_gold(slot, t) -> gold spent on items by then, or None.
"""
import math

import replay_trades as RT
import replay_waves as W

try:
    import champ_cd
except Exception:   # older builds
    champ_cd = None

TOWERS = {("TOP", 100): (981, 10441), ("TOP", 200): (4318, 13875), ("MIDDLE", 100): (5846, 6396), ("MIDDLE", 200): (8955, 8510)}


class Ctx:
    def __init__(self, d, kills, ranks, item_gold, until=900):
        self.d = d
        self.skins = [s.get("SKIN") for s in d["stats"]]
        self.team = [int(s.get("TEAM") or (100 if i < 5 else 200)) for i, s in enumerate(d["stats"])]
        self.tracks = {int(k): L for k, L in d["tracks"].items()}
        self.hits, self.casts, self.levels = d["hits"], d["casts"], d["levels"]
        self.summs = d.get("summs") or []
        self.hpa = {int(k): sorted((t, h, m) for t, h, m in L) for k, L in (d.get("hp") or {}).items()}
        self.kills, self.ranks, self.item_gold = kills, ranks, item_gold
        self.backs = {}
        for k, t, _x, _z in W.recalls(d, kills, until):
            self.backs.setdefault(k, []).append(t)

    def _gone(self, k, a, b):
        return any(a < x <= b for x in self.kills.get(k, []) + self.backs.get(k, []))

    def hp_at(self, k, t):
        """(health, max) at t: the replay's minute health (exact) plus every hit since; healing between marks spread evenly."""
        A = self.hpa.get(k) or []
        if len(A) < 2:
            return None
        i = max(0, min(len(A) - 2, max(x for x in range(len(A)) if A[x][0] <= t) if A[0][0] <= t else 0))
        (t0, h0, m0), (t1, h1, m1) = A[i], A[i + 1]
        dmg = lambda a, b: sum(v for ht, tg, aa, v in self.hits if tg == k and a < ht <= b)
        if self._gone(k, t0, t1):
            return max(0.0, min(m0, h0 - dmg(t0, t))), m0
        heal = max(0.0, h1 - h0 + dmg(t0, t1))
        f = (t - t0) / max(1e-6, t1 - t0)
        return max(0.0, min(m0 + (m1 - m0) * f, h0 - dmg(t0, t) + heal * f)), m0 + (m1 - m0) * f

    def next_mark(self, k, t):
        """The first minute mark after t with no death or recall of k in between: (time, hp, max) or None."""
        for (tt, h, mm) in self.hpa.get(k) or []:
            if tt > t + 2:
                return None if self._gone(k, t, tt) else (tt, h, mm)
        return None

    def level(self, k, t):
        return sum(1 for tt, kk in self.levels if kk == k and tt <= t)

    def rank(self, k, sl, t):
        return sum(1 for tt, x in self.ranks.get(k, []) if x == sl and tt <= t)

    def state(self, i, j, t0, lane, first=None):
        """Model inputs for slot i facing slot j at t0 (None when health or positions are missing)."""
        tracks = self.tracks
        pm = RT._at(tracks.get(i), t0) if i in tracks else None
        po = RT._at(tracks.get(j), t0) if j in tracks else None
        hm, ho = self.hp_at(i, t0), self.hp_at(j, t0)
        if not pm or not po or not hm or not ho or not hm[1] or not ho[1]:
            return None
        cx, cz = (pm[0] + po[0]) / 2, (pm[1] + po[1]) / 2
        mine = theirs = 0
        for key, L in tracks.items():
            if key < 10 or len(L) < 2 or t0 - L[-1][0] > 4:
                continue
            q = RT._at(L, t0)
            if not q or math.hypot(q[0] - cx, q[1] - cz) > 1100:
                continue
            tm = 100 if math.hypot(L[0][1] - 1500, L[0][2] - 1500) < math.hypot(L[0][1] - 13300, L[0][2] - 13300) else 200
            if tm == self.team[i]:
                mine += 1
            else:
                theirs += 1
        row = {"t": round(t0, 1), "lvMe": self.level(i, t0), "lvOpp": self.level(j, t0),
               "hpMe": round(100 * hm[0] / hm[1]), "hpOpp": round(100 * ho[0] / ho[1]), "first": "" if first is None else int(first)}
        for who, k in (("me", i), ("opp", j)):
            cd = ((champ_cd.CD.get(self.skins[k]) or {}).get("cd") or {}) if champ_cd else {}
            for sl in "QWER":
                last = max([t for t, kk, s in self.casts if kk == k and s == sl and t < t0 - 0.3], default=None)
                since = t0 - last if last is not None else 999.0
                row["since%s%s" % (sl, who)] = round(min(since, 999.0), 1)
                rk = self.rank(k, sl, t0)
                cds = cd.get(sl) or []
                c1 = cds[min(len(cds), max(1, rk)) - 1] if cds else None
                # 0 = not learned yet; otherwise time since the last cast as a share of the cooldown at their rank
                row["ready%s%s" % (sl, who)] = (0.0 if rk == 0 else round(min(3.0, since / c1), 2)) if c1 else ""
            key = ((champ_cd.CD.get(self.skins[k]) or {}).get("key")) if champ_cd else None
            row["key" + who.capitalize()] = row.get("ready%s%s" % (key, who), "") if key else ""
            fl = max([t for t, kk, n in self.summs if kk == k and n == "Flash" and t < t0], default=None)
            row["flash" + who.capitalize()] = 1 if fl is None or t0 - fl >= 300 else 0
        mt, ot = TOWERS[(lane, self.team[i])], TOWERS[(lane, self.team[j])]
        gi, gj = self.item_gold(i, t0), self.item_gold(j, t0)
        row.update(minMine=mine, minTheirs=theirs,
                   toMyTower=round(math.hypot(cx - mt[0], cz - mt[1])), toTheirTower=round(math.hypot(cx - ot[0], cz - ot[1])),
                   goldGap=(gi - gj) if gi is not None and gj is not None else "")
        row["_hp"] = (hm, ho)
        return row

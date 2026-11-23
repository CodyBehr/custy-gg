"""
Is a fight worth taking? Compare, in the same situation, how often experts come out ahead when they fight vs when they
don't (calm moments from fight_rows.py). value = P(ahead | fight) - P(ahead | no fight), both from models fit on
other games (by game, 5 folds).

  python3 fight_value.py rows.csv
"""
import sys

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

import fight_model as FM

S = [c for c in FM.FEATS if c != "first"]

r = pd.read_csv(sys.argv[1])
r = r[r.won.notna()].copy()
r["won"] = r.won.astype(int)
r["lvGap"] = r.lvMe - r.lvOpp
r["hpGap"] = r.hpMe - r.hpOpp
r["minGap"] = r.minMine - r.minTheirs
for c in FM.STATE:
    r[c] = pd.to_numeric(r[c], errors="coerce")
r = r.reset_index(drop=True)
r["pf"] = np.nan
r["pc"] = np.nan
for tr, te in GroupKFold(5).split(r, r.won, r.game):
    a, b = FM.with_rates(r.iloc[tr], r.iloc[te])
    f, c = a[a.kind == "fight"], a[a.kind == "calm"]
    mf = FM.model().fit(f[S], f.won)
    mc = FM.model().fit(c[S], c.won)
    r.loc[b.index, "pf"] = mf.predict_proba(b[S])[:, 1]
    r.loc[b.index, "pc"] = mc.predict_proba(b[S])[:, 1]
f = r[r.kind == "fight"].copy()
f["value"] = f.pf - f.pc
print("%d fights, %d calm moments" % (len(f), (r.kind == "calm").sum()))
print("Worth of fighting vs not, by situation (points of 'comes out ahead'; + means fight):")
rows = [("a level up", f.lvGap >= 1), ("a level down", f.lvGap <= -1), ("even levels", f.lvGap == 0),
        ("their key ability down", f.keyOpp < 1), ("their key ability up", f.keyOpp >= 1),
        ("your key ability down", f.keyMe < 1), ("your key ability up", f.keyMe >= 1),
        ("your wave 3+ bigger", f.minGap >= 3), ("their wave 3+ bigger", f.minGap <= -3),
        ("you 20+ healthier", f.hpGap >= 20), ("you 20+ behind on health", f.hpGap <= -20),
        ("near their tower", f.toTheirTower < 1200), ("near your tower", f.toMyTower < 1200),
        ("their Flash down", f.flashOpp == 0), ("your Flash down", f.flashMe == 0),
        ("before 3:00", f.t < 180), ("after 10:00", f.t > 600)]
for name, mask in rows:
    x = f[mask]
    if len(x) >= 100:
        print("  %-26s %+5.1f   (won %2.0f%% of %d)" % (name, 100 * x.value.mean(), 100 * x.won.mean(), len(x)))
print("\nShare of fights experts take with value below -10 points (clearly bad spots): %.1f%%" % (100 * (f.value < -0.10).mean()))
print("Share above +10 (clearly good): %.1f%%" % (100 * (f.value > 0.10).mean()))
f.to_csv(sys.argv[1].replace(".csv", "_value.csv"), index=False)

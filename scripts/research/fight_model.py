"""
First fight model: given the state when a 1v1 lane fight starts, how likely is this side to come out ahead
(fight_rows.py "won": a death, else healthier at the next minute mark)?

  python3 fight_model.py rows.csv [model.json]

Gradient-boosted trees (scikit-learn), checked by game (no game is in both training and test folds). Reports
accuracy against simple baselines, calibration, and what the model leans on.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

STATE = ["t", "lvMe", "lvOpp", "lvGap", "hpMe", "hpOpp", "hpGap", "first",
         "readyQme", "readyWme", "readyEme", "readyRme", "readyQopp", "readyWopp", "readyEopp", "readyRopp",
         "keyMe", "keyOpp", "flashMe", "flashOpp", "minMine", "minTheirs", "minGap", "toMyTower", "toTheirTower",
         "goldGap"]
# Champion names are left out for now: with ~100 champions they over-fit (worse than health + levels alone on
# 292 games). Matchup effects come back later as smoothed per-matchup rates once there are enough games.


def prepare(r):
    r = r[r.won.notna()].copy()
    if "kind" in r:
        r = r[r.kind == "fight"]
    r["won"] = r.won.astype(int)
    r["lvGap"] = r.lvMe - r.lvOpp
    r["hpGap"] = r.hpMe - r.hpOpp
    r["minGap"] = r.minMine - r.minTheirs
    champs = sorted(set(r.me) | set(r.opp))
    code = {c: i for i, c in enumerate(champs)}
    r["champMe"] = r.me.map(code)
    r["champOpp"] = r.opp.map(code)
    for c in STATE:
        r[c] = pd.to_numeric(r[c], errors="coerce")
    return r, champs


def rates(train, test, k_champ=100, k_mu=40):
    """Smoothed fight win rates from the training rows only: each champion's, its opponent's, and the matchup's
    (shrunk toward the overall rate, so a matchup with few fights says little)."""
    m = train.won.mean()
    out = pd.DataFrame(index=test.index)
    for col, key, k in (("wrMe", "me", k_champ), ("wrOpp", "opp", k_champ)):
        g = train.groupby(key).won.agg(["sum", "count"])
        out[col] = test[key].map((g["sum"] + k * m) / (g["count"] + k)).fillna(m)
    g = train.groupby(["me", "opp"]).won.agg(["sum", "count"])
    s = (g["sum"] + k_mu * m) / (g["count"] + k_mu)
    out["wrMu"] = [s.get((a, b), m) for a, b in zip(test.me, test.opp)]
    return out


def with_rates(train, test):
    """Training rows get rates from other folds of the training set (no row sees its own outcome)."""
    a, b = train.copy(), test.copy()
    a[["wrMe", "wrOpp", "wrMu"]] = np.nan
    for itr, ite in GroupKFold(5).split(a, a.won, a.game):
        a.iloc[ite, [a.columns.get_loc(c) for c in ("wrMe", "wrOpp", "wrMu")]] = rates(a.iloc[itr], a.iloc[ite]).values
    b[["wrMe", "wrOpp", "wrMu"]] = rates(a, b).values
    return a, b


FEATS = STATE + ["wrMe", "wrOpp", "wrMu"]


def model():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=80,
                                          l2_regularization=1.0, random_state=0)


def main():
    r, champs = prepare(pd.read_csv(sys.argv[1]))
    r = r.reset_index(drop=True)
    X, y, g = r[STATE], r.won.values, r.game.values
    print("%d fights with an outcome, %d games, %d champions" % (len(r), len(set(g)), len(champs)))
    p = np.zeros(len(r))
    base = {"health + levels only": ["hpGap", "lvGap", "hpMe", "hpOpp"]}
    pb = {k: np.zeros(len(r)) for k in base}
    for tr, te in GroupKFold(5).split(X, y, g):
        a, b = with_rates(r.iloc[tr], r.iloc[te])
        m = model().fit(a[FEATS], y[tr])
        p[te] = m.predict_proba(b[FEATS])[:, 1]
        for k, cols in base.items():
            mb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0).fit(X.iloc[tr][cols], y[tr])
            pb[k][te] = mb.predict_proba(X.iloc[te][cols])[:, 1]
    print("\nHeld-out (by game):")
    print("  coin flip          accuracy 50.0%%  log loss %.3f" % log_loss(y, np.full(len(y), 0.5)))
    for k in base:
        print("  %-18s accuracy %.1f%%  AUC %.3f  log loss %.3f" % (k, 100 * ((pb[k] > .5) == y).mean(), roc_auc_score(y, pb[k]), log_loss(y, pb[k])))
    print("  full model         accuracy %.1f%%  AUC %.3f  log loss %.3f  Brier %.3f" % (100 * ((p > .5) == y).mean(), roc_auc_score(y, p), log_loss(y, p), brier_score_loss(y, p)))
    print("\nCalibration (predicted -> actual):")
    bins = pd.cut(p, [0, .2, .35, .5, .65, .8, 1])
    for b, grp in pd.DataFrame({"p": p, "y": y, "b": bins}).groupby("b", observed=True):
        print("  %-12s %5.0f%% -> %5.0f%%  (%d)" % (b, 100 * grp.p.mean(), 100 * grp.y.mean(), len(grp)))
    a, _ = with_rates(r, r.iloc[:1])
    m = model().fit(a[FEATS], y)
    smp = a.sample(min(6000, len(a)), random_state=0)
    imp = permutation_importance(m, smp[FEATS], smp.won, n_repeats=3, random_state=0, scoring="roc_auc")
    print("\nWhat it leans on (AUC lost when shuffled):")
    for c, v in sorted(zip(FEATS, imp.importances_mean), key=lambda x: -x[1])[:15]:
        print("  %-12s %.4f" % (c, v))
    r["p"] = p
    r.to_csv(sys.argv[1].replace(".csv", "_pred.csv"), index=False)
    if len(sys.argv) > 2:
        json.dump({"features": STATE, "champs": champs}, open(sys.argv[2], "w"))


if __name__ == "__main__":
    main()

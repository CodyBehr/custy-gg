"""
Train the fight model (fights) and the no-fight model (calm moments) on every row and export both, plus the smoothed
champion/matchup fight rates, to collector/fight_model.json for the app (collector/fight_eval.py). Checks that the
plain-Python evaluator gives the same probabilities as scikit-learn.

  python3 fight_export.py rows.csv [out.json]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import fight_model as FM

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "collector"))
import fight_eval  # noqa: E402


def export(m, feats):
    trees = []
    for it in m._predictors:
        for pred in it:
            nodes = []
            for nd in pred.nodes:
                if nd["is_leaf"]:
                    nodes.append([-1, float("%.6g" % nd["value"])])
                else:
                    nodes.append([int(nd["feature_idx"]), float(nd["num_threshold"]), int(nd["missing_go_to_left"]), int(nd["left"]), int(nd["right"])])
            trees.append(nodes)
    return {"features": feats, "base": float(np.ravel(m._baseline_prediction)[0]), "trees": trees}


def main():
    src, out = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "..", "collector", "fight_model.json"))
    raw = pd.read_csv(src)
    r = raw[raw.won.notna()].copy()
    r["won"] = r.won.astype(int)
    r["lvGap"] = r.lvMe - r.lvOpp
    r["hpGap"] = r.hpMe - r.hpOpp
    r["minGap"] = r.minMine - r.minTheirs
    for c in FM.STATE:
        r[c] = pd.to_numeric(r[c], errors="coerce")
    r = r.reset_index(drop=True)
    fights = r[r.kind == "fight"]
    # rates from all fights (what the app looks up), and leak-free rates for training rows
    m_all = fights.won.mean()
    rates = {"all": float(m_all), "champ": {}, "opp": {}, "mu": {}}
    for key, name, k in (("me", "champ", 100), ("opp", "opp", 100)):
        g = fights.groupby(key).won.agg(["sum", "count"])
        rates[name] = {c: round(float(v), 4) for c, v in ((g["sum"] + k * m_all) / (g["count"] + k)).items()}
    g = fights.groupby(["me", "opp"]).won.agg(["sum", "count"])
    rates["mu"] = {"%s|%s" % ab: round(float(v), 4) for ab, v in ((g["sum"] + 40 * m_all) / (g["count"] + 40)).items()}
    a, _ = FM.with_rates(r[r.kind == "fight"], r.iloc[:1])
    # calm rows get the fight rates (the same lookup the app does)
    calm = r[r.kind == "calm"].copy()
    calm["wrMe"] = calm.me.map(rates["champ"]).fillna(m_all)
    calm["wrOpp"] = calm.opp.map(rates["opp"]).fillna(m_all)
    calm["wrMu"] = [rates["mu"].get("%s|%s" % (x, y), m_all) for x, y in zip(calm.me, calm.opp)]
    S_f = FM.FEATS
    S_c = [f for f in FM.FEATS if f != "first"]
    mf = FM.model().fit(a[S_f], a.won)
    mc = FM.model().fit(calm[S_c], calm.won)
    J = {"version": 1, "rows": int(len(r)), "games": int(r.game.nunique()), "rates": rates,
         "fight": export(mf, S_f), "calm": export(mc, S_c)}
    with open(out, "w") as fh:
        json.dump(J, fh, separators=(",", ":"))
    print("wrote %s (%.0f KB): %d fight trees, %d calm trees" % (out, os.path.getsize(out) / 1024, len(J["fight"]["trees"]), len(J["calm"]["trees"])))
    # check the plain-Python evaluator against scikit-learn
    fight_eval._M = J
    smp = a.sample(300, random_state=1)
    mine = [fight_eval._score(J["fight"], [fight_eval._num(v) for v in row]) for row in smp[S_f].astype(object).where(smp[S_f].notna(), None).values.tolist()]
    sk = mf.predict_proba(smp[S_f])[:, 1]
    print("max difference vs scikit-learn: %.2e" % np.max(np.abs(np.array(mine) - sk)))
    diffs = np.abs(np.array(mine) - sk); print("rows differing by more than 1 point:", int((diffs > 0.01).sum()))


if __name__ == "__main__":
    main()

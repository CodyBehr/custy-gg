"""
The fight model in the app, without scikit-learn: gradient-boosted trees exported to fight_model.json by
scripts/research/fight_export.py, evaluated in plain Python.

  odds(state, me, opp) -> {"fight": P(you come out ahead | you fight), "calm": P(... | you don't), "value": fight - calm}

"Come out ahead" = a death within 20 s decides it, otherwise who's healthier at the next minute mark. Trained on
1v1 top/mid fights from Master+ games (see the project's fight-model notes).
"""
import json
import math
import os

_M = None


def _load():
    global _M
    if _M is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, "fight_model.json"), os.path.join(getattr(__import__("sys"), "_MEIPASS", here), "fight_model.json")):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    _M = json.load(fh)
                break
        else:
            _M = {}
    return _M


def available():
    return bool(_load())


def _num(v):
    if v is None or v == "":
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _score(model, x):
    s = model["base"]
    for tree in model["trees"]:
        n = 0
        while True:
            node = tree[n]
            if node[0] == -1:            # leaf: [-1, value]
                s += node[1]
                break
            f, thr, miss_left, left, right = node
            v = x[f]
            n = (left if miss_left else right) if v is None else (left if v <= thr else right)
    return 1 / (1 + math.exp(-s))


def features(state, me, opp):
    """The model's inputs in its order, from a fight_feats state plus the champions' smoothed fight rates."""
    M = _load()
    r = M["rates"]
    x = dict(state)
    x["lvGap"] = x["lvMe"] - x["lvOpp"]
    x["hpGap"] = x["hpMe"] - x["hpOpp"]
    x["minGap"] = x["minMine"] - x["minTheirs"]
    x["wrMe"] = r["champ"].get(me, r["all"])
    x["wrOpp"] = r["opp"].get(opp, r["all"])
    x["wrMu"] = r["mu"].get("%s|%s" % (me, opp), r["all"])
    return x


def odds(state, me, opp):
    M = _load()
    if not M:
        return None
    x = features(state, me, opp)
    pf = _score(M["fight"], [_num(x.get(f)) for f in M["fight"]["features"]])
    pc = _score(M["calm"], [_num(x.get(f)) for f in M["calm"]["features"]])
    return {"fight": pf, "calm": pc, "value": pf - pc}

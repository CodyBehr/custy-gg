"""Merge the per-region rows and write one benchmark file per champion+role.

    python3 master_build.py rows-NA rows-EUW rows-KR --out public/benchmarks --min 40
Files built from onetricks.gg one-trick pulls (source mentions onetricks) are left alone.
"""
import argparse, datetime, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_core as C
ap = argparse.ArgumentParser()
ap.add_argument("folders", nargs="+")
ap.add_argument("--out", default="public/benchmarks")
ap.add_argument("--min", type=int, default=40)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
names = sorted({os.path.basename(p)[:-6] for d in a.folders for p in glob.glob(os.path.join(d, "*.jsonl"))})
built, thin, kept = 0, [], 0
index = []
for name in names:
    rows = []
    for d in a.folders:
        p = os.path.join(d, name + ".jsonl")
        if os.path.exists(p):
            rows += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    if len(rows) < a.min:
        thin.append("%s (%d)" % (name, len(rows))); continue
    path = os.path.join(a.out, name + ".json")
    if os.path.exists(path):
        try:
            if "onetricks" in json.load(open(path)).get("source", ""):
                kept += 1; index.append([name, json.load(open(path))["games"], "onetricks"]); continue
        except ValueError:
            pass
    b = C.aggregate(rows, "Master+ ranked solo games (NA, EUW, KR), Riot match-v5", datetime.date.today().isoformat())
    with open(path, "w") as f:
        json.dump(b, f, separators=(",", ":"))
    index.append([name, b["games"], "master"])
    built += 1
with open(os.path.join(a.out, "index.json"), "w") as f:
    json.dump(sorted(index), f, separators=(",", ":"))
print("built %d, kept %d onetricks files, %d too thin (< %d games)" % (built, kept, len(thin), a.min))
print("thin:", ", ".join(thin[:60]))

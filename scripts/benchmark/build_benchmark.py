"""Turn a folder of one-trick match+timeline files (from pull.py) into the benchmark JSON the review page reads.

    python3 scripts/benchmark/build_benchmark.py data/benchmark/jhin_bot public/benchmarks

Uses the same per-game numbers and summary as the Master+ pipeline (bench_core.py).
"""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_core as C


def rows(folder):
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(folder, f), encoding="utf-8") as fh:
            d = json.load(fh)
        me = next(p for p in d["match"]["info"]["participants"] if p["puuid"] == d["expert"]["puuid"])
        r = C.row(d["match"]["info"], d["timeline"]["info"], me)
        r["region"] = d["expert"].get("region")
        yield r


if __name__ == "__main__":
    folder, out = sys.argv[1], sys.argv[2]
    b = C.aggregate(list(rows(folder)), "onetricks.gg top players, Riot match-v5 ranked solo games", datetime.date.today().isoformat())
    name = "%s-%s.json" % (b["champion"], b["role"])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name), "w") as f:
        json.dump(b, f, separators=(",", ":"))
    print(name, b["games"], "games", os.path.getsize(os.path.join(out, name)), "bytes")

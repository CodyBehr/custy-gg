"""Pull expert matchup sheets into public/matchups/.

Reads scripts/matchups/sheets.json (best source per champion), downloads every
sheet whose export works, finds the opponent column and the author's own column
labels, and writes one JSON per champion plus public/matchups/index.json.

A sheet that stops downloading (deleted, made private, export turned off) has
its notes removed: we only show what the author still shares.

Run weekly (see .github/workflows/matchups.yml). Usage: python pull.py [--offline DIR]
"""
import csv, io, json, os, re, sys, time, urllib.request, urllib.error, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "scripts", "matchups", "sheets.json")
OUT = os.path.join(ROOT, "public", "matchups")
BENCH = os.path.join(ROOT, "public", "benchmarks", "index.json")

MAX_CELL = 700          # keep notes short; the full sheet is one click away
ALIASES = {
    "wukong": "MonkeyKing", "wu": "MonkeyKing", "mundo": "DrMundo", "j4": "JarvanIV", "jarvan": "JarvanIV",
    "cho": "Chogath", "kha": "Khazix", "kog": "KogMaw", "rek": "RekSai", "tahm": "TahmKench", "tk": "TahmKench",
    "yi": "MasterYi", "mf": "MissFortune", "tf": "TwistedFate", "asol": "AurelionSol", "lb": "Leblanc",
    "lee": "LeeSin", "xin": "XinZhao", "nunuwillump": "Nunu", "renataglasc": "Renata", "vel": "Velkoz",
    "gp": "Gangplank", "malph": "Malphite", "morde": "Mordekaiser", "panth": "Pantheon", "renek": "Renekton",
    "trynd": "Tryndamere", "voli": "Volibear", "vlad": "Vladimir", "ww": "Warwick", "heimer": "Heimerdinger",
    "cass": "Cassiopeia", "cassio": "Cassiopeia", "kass": "Kassadin", "kat": "Katarina", "ez": "Ezreal",
    "fiddle": "Fiddlesticks", "fid": "Fiddlesticks", "naut": "Nautilus", "liss": "Lissandra", "ori": "Orianna",
    "sej": "Sejuani", "kayn": "Kayn", "gnar": "Gnar", "ksante": "KSante", "belveth": "Belveth",
}
LABEL = re.compile(r"champ|opponent|matchup|vs\.?|enemy|name", re.I)
PLACEHOLDER = re.compile(r"\s*(in progress|tbd|todo|wip|coming soon|n/?a|-+|\?+|\.+)\s*\.?\s*", re.I)
HEAD = re.compile(r"\s*(vs\.?\s*)?(champions?( name)?|opponents?|matchups?|enem(y|ies)|against)\s*:?\s*", re.I)


def norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def champ_ids():
    ids = sorted({k.rsplit("-", 1)[0] for k, *_ in json.load(open(BENCH))})
    look = {norm(c): c for c in ids}
    look.update({k: v for k, v in ALIASES.items() if v in ids})
    return ids, look


def match_champ(cell, look):
    t = norm(cell)
    if not t or len(t) > 30:
        return None
    if t in look:
        return look[t]
    words = [norm(w) for w in re.split(r"[\s/(]+", cell) if norm(w)]
    for w in words:                 # "AP Chogath", "Tank Garen", "Renekton (top)"
        if w in look:
            return look[w]
    for w in words[:1]:
        if len(w) >= 4:
            hits = {v for k, v in look.items() if k.startswith(w)}
            if len(hits) == 1:
                return hits.pop()
    return None


def tabs(sid):
    """Tab ids from the public view page (sheets often keep matchups on a second tab)."""
    try:
        req = urllib.request.Request(f"https://docs.google.com/spreadsheets/d/{sid}/htmlview",
                                     headers={"User-Agent": "custy.gg matchup notes (weekly)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf8", "replace")
    except Exception:
        return []
    return list(dict.fromkeys(re.findall(r"gid=(\d+)", html)))


def fetch(sid, gid=None):
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv" + (f"&gid={gid}" if gid else "")
    req = urllib.request.Request(url, headers={"User-Agent": "custy.gg matchup notes (weekly)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:
        return None, type(e).__name__
    if body.lstrip().startswith("<"):
        return None, "not shared"
    return body, "ok"


def parse(text, me, look):
    rows = list(csv.reader(io.StringIO(text)))
    width = max((len(r) for r in rows), default=0)
    # opponent column = the column naming the most champions
    best = (0, -1)
    for c in range(width):
        n = sum(1 for r in rows if c < len(r) and match_champ(r[c], look))
        best = max(best, (n, c))
    n, oc = best
    if n < 8:
        return None
    hits = [i for i, r in enumerate(rows) if oc < len(r) and match_champ(r[oc], look)]
    # header: a row above the first champion whose opponent cell says "Champion"/"Matchup"/...,
    # with sub-header rows below it filling the gaps; else the closest label-looking row
    # the list starts where champion rows come close together (skips titles like "Pantheon Top matchups")
    first = next((a for a, b, c in zip(hits, hits[1:], hits[2:]) if b - a <= 2 and c - b <= 2), hits[0])
    hits = [h for h in hits if h >= first]
    labels = {}
    cells_of = lambda r: {c: " ".join(v.strip().splitlines()[0].split()) for c, v in enumerate(r) if v.strip()}
    top = next((i for i in range(first - 1, max(-1, first - 9), -1)
                if any(0 <= k < len(rows[i]) and HEAD.fullmatch(rows[i][k] or "") for k in (oc - 1, oc, oc + 1))), None)
    if top is not None:
        for i in range(top, first):
            for c, v in cells_of(rows[i]).items():
                if len(v) < 60 and c not in labels:
                    labels[c] = v
    else:
        for i in range(first - 1, max(-1, first - 6), -1):
            cells = cells_of(rows[i])
            if len(cells) >= 2 and all(len(v) < 60 for v in cells.values()):
                labels = cells
                break
    out = {}
    for i in hits:
        r = rows[i]
        opp = match_champ(r[oc], look)
        if not opp or opp == me and norm(r[oc]) != norm(me):
            continue
        fields = []
        for c, v in enumerate(r):
            v = " ".join(v.split()) if "\n" not in v else "\n".join(" ".join(x.split()) for x in v.splitlines() if x.strip())
            if c == oc or not v or v.startswith("http") or PLACEHOLDER.fullmatch(v):
                continue
            label = labels.get(c, "")
            if label and LABEL.fullmatch(label.strip(" :")):
                continue
            fields.append([label, v[:MAX_CELL] + ("…" if len(v) > MAX_CELL else "")])
        if not fields:
            continue
        note = r[oc].strip()
        entry = {"fields": fields}
        if norm(note) != norm(opp):
            entry["as"] = note[:40]             # "AP Chogath", "Tank Garen"
        out.setdefault(opp, []).append(entry)
    if top is not None:
        out["_head"] = True        # a real "Champion | ... " header: a proper matchup table
    return out


def advice(rows):
    """Opponents with at least one real sentence of advice."""
    n = sum(1 for k, es in (rows or {}).items() if not k.startswith("_") and any(len(v) >= 40 for e in es for _, v in e["fields"]))
    return n + (1000 if (rows or {}).get("_head") and n >= 5 else 0)


def best_tab(sid, text, me, look):
    """Matchups are often on another tab: keep the tab with the most real advice."""
    rows = parse(text, me, look)
    for gid in tabs(sid)[:12]:
        if gid == "0":
            continue
        t2, _ = fetch(sid, gid)
        r2 = parse(t2, me, look) if t2 else None
        if r2 and advice(r2) > advice(rows):
            rows = dict(r2, _gid=gid)
    if not rows or advice(rows) % 1000 < 5:
        return None
    rows.pop("_head", None)
    return rows


def main():
    src = json.load(open(SRC))["sources"]
    ids, look = champ_ids()
    os.makedirs(OUT, exist_ok=True)
    index = {}
    for s in src:
        c = s["champ"]
        meta = {k: s.get(k) for k in ("quality", "url", "author", "rank", "updated")}
        if meta["quality"] in ("none", "stats_only"):
            meta = {"quality": meta["quality"]}
        meta = {k: v for k, v in meta.items() if v not in (None, "", "?")}
        path = os.path.join(OUT, f"{c}.json")
        if s.get("quality") == "sheet" and s.get("id"):
            rows, why, text = None, "", None
            for cand in [s] + s.get("alt", []):          # best sheet first, then runners-up
                text, why = fetch(cand["id"])
                rows = best_tab(cand["id"], text, c, look) if text else None
                if rows:
                    meta["url"] = f"https://docs.google.com/spreadsheets/d/{cand['id']}/edit" + (f"#gid={rows['_gid']}" if rows.get("_gid") else "")
                    if cand is not s:
                        meta.update({k: cand[k] for k in ("author", "rank", "updated") if cand.get(k)})
                        meta.pop("note", None)
                    break
            if rows:
                rows.pop("_gid", None)
                body = {"champ": c, "source": meta, "fetched": time.strftime("%Y-%m-%d"), "rows": rows}
                old = json.load(open(path)) if os.path.exists(path) else {}
                if old.get("rows") == rows and old.get("source") == meta:
                    body["fetched"] = old.get("fetched", body["fetched"])   # no change, no churn
                json.dump(body, open(path, "w"), indent=0, ensure_ascii=False)
                meta["opponents"] = len(rows)
            else:
                meta["quality"] = "sheet_link" if text is None else "sheet_unparsed"
                meta["pull"] = why if text is None else "no opponent column"
                if os.path.exists(path):
                    os.remove(path)                  # author stopped sharing: drop our copy
            print(f"{c:14} {meta['quality']:14} {meta.get('opponents', '')} {meta.get('pull', '')}")
        elif os.path.exists(path):
            os.remove(path)
        index[c] = meta
    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=0, ensure_ascii=False)


if __name__ == "__main__":
    main()

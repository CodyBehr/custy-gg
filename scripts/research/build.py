"""Builds data/champions/<Alias>.json from Community Dragon (live patch): exact numbers from the game files,
Riot's official ability descriptions with the numbers filled in, and tags read from Riot's own markup.
Judgment fields (identity, strengths, power curve, key ability...) are filled in later under "profile"."""
import json, os, re, sys, glob

STAT = {0: "AP", 1: "armor", 2: "AD", 3: "attack speed", 5: "move speed", 6: "MR", 7: "move speed", 8: "crit",
        11: "max HP", 12: "max HP", 29: "lethality"}
SLOTS = ["Q", "W", "E", "R", "Passive"]


def fv(v):
    if isinstance(v, float):
        return int(v) if v == int(v) else round(v, 3)
    return v


def ranks(vals, n=5):
    v = [fv(x) for x in (vals or [])[1:n + 1]]
    if not v:
        return None
    return v[0] if all(x == v[0] for x in v) else v


def part_text(p):
    t = p.get("__type")
    bonus = "bonus " if p.get("mStatFormula") == 2 else ""
    if t == "NamedDataValueCalculationPart":
        return "{%s}" % p["mDataValue"]
    if t == "StatByNamedDataValueCalculationPart":
        return "{%s}×%s%s" % (p["mDataValue"], bonus, STAT.get(p.get("mStat", 0), "stat"))
    if t == "StatByCoefficientCalculationPart":
        return "%s×%s%s" % (fv(p.get("mCoefficient", 0)), bonus, STAT.get(p.get("mStat", 0), "stat"))
    if t == "NumberCalculationPart":
        return str(fv(p.get("mNumber", 0)))
    if t == "ByCharLevelInterpolationCalculationPart":
        return "%s–%s (by level)" % (fv(p.get("mStartValue")), fv(p.get("mEndValue")))
    if t == "ByCharLevelBreakpointsCalculationPart":
        return "%s+ (by level)" % fv(p.get("mLevel1Value"))
    if t == "ProductOfSubPartsCalculationPart":
        return "(%s × %s)" % (part_text(p["mPart1"]), part_text(p["mPart2"]))
    if t == "SumOfSubPartsCalculationPart":
        return "(%s)" % " + ".join(part_text(x) for x in p.get("mSubparts", []))
    if t == "StatBySubPartCalculationPart":
        return "%s×%s%s" % (part_text(p["mSubpart"]), bonus, STAT.get(p.get("mStat", 0), "stat"))
    if t == "GameCalculationReferencePart" or "mCalculation" in p:
        return "[%s]" % p.get("mCalculation", "?")
    return "?"


def calc_text(c):
    if c.get("__type") == "GameCalculationModified":
        return "[%s] × %s" % (c.get("mModifiedGameCalculation"), part_text(c["mMultiplier"]) if c.get("mMultiplier") else "?")
    s = " + ".join(part_text(p) for p in c.get("mFormulaParts", []))
    if c.get("mMultiplier"):
        s = "(%s) × %s" % (s, part_text(c["mMultiplier"]))
    return s


def show(v):
    if isinstance(v, list):
        return "/".join(str(x) for x in v)
    return str(v)


def resolve(expr, dv, calcs, depth=0):
    """Expands {Name} and [Calc] references inside a calculation text into numbers per rank."""
    if depth > 4:
        return expr
    def dvsub(m):
        v = dv.get(m.group(1))
        return show(v) if v is not None else m.group(1)
    expr = re.sub(r"\{(\w+)\}", dvsub, expr)
    expr = re.sub(r"\[(\w+)\]", lambda m: "(%s)" % resolve(calcs.get(m.group(1), m.group(1)), dv, calcs, depth + 1), expr)
    return expr


def render(text, dv, calcs):
    if not text:
        return ""
    def sub(m):
        name, op, k = m.group(1), m.group(2), m.group(3)
        if name in calcs and not op:
            return resolve(calcs[name], dv, calcs)
        v = dv.get(name)
        if v is None and name.lower() in {x.lower(): x for x in dv}:
            v = dv[{x.lower(): x for x in dv}[name.lower()]]
        if v is None:
            return "" if name.endswith("Append") or name.startswith("Spell") else "(varies)"
        if op:
            k = float(k)
            f = (lambda x: fv(x * k)) if op == "*" else (lambda x: fv(x / k))
            v = [f(x) for x in v] if isinstance(v, list) else f(v)
        return show(v)
    t = re.sub(r"@([\w.]+?)(?:([*/])(-?[\d.]+))?@", sub, text)
    return t


def tags_from(desc_html, plain):
    tags = set()
    for s in re.findall(r"<status>(.*?)</status>", desc_html or ""):
        s = s.strip().lower()
        for k, tag in (("stun", "stun"), ("root", "root"), ("silence", "silence"), ("slow", "slow"),
                       ("knock", "airborne"), ("airborne", "airborne"), ("pull", "airborne"), ("suppress", "suppression"),
                       ("charm", "charm"), ("fear", "fear"), ("flee", "fear"), ("taunt", "taunt"), ("sleep", "sleep"),
                       ("blind", "blind"), ("nearsight", "nearsight"), ("disarm", "disarm"), ("ground", "grounded"),
                       ("polymorph", "polymorph"), ("immobiliz", "immobilizing"), ("unstoppable", "unstoppable"),
                       ("untargetable", "untargetable"), ("stasis", "stasis"), ("invulnerab", "invulnerable"),
                       ("cleanse", "cleanse"), ("drowsy", "drowsy"), ("cripple", "cripple"), ("berserk", "berserk")):
            if k in s:
                tags.add(tag)
    low = (plain or "").lower()
    for pat, tag in ((r"\bdash", "dash"), (r"\bleap", "dash"), (r"\bjump", "dash"), (r"\blunge", "dash"),
                     (r"\bblink", "blink"), (r"\bteleport", "blink"), (r"\bspell shield", "spell shield"),
                     (r"\bparries\b|\bparry\b", "parry"), (r"\bdodg", "dodge"), (r"\bshield", "shield"),
                     (r"\bheal|restores health|\bdrain", "heal"), (r"\binvisib|camouflage", "stealth"),
                     (r"next (basic )?attack|empowers .*attack|next \d+ attacks", "empowered attack"),
                     (r"\bmissile|\bprojectile", "projectile"), (r"\btrue damage", "true damage"),
                     (r"\bexecute|missing health", "execute"), (r"\btenacity", "tenacity"),
                     (r"\bdamage reduction|reduces? (all )?(incoming )?damage|takes? \d+% (less|reduced) damage", "damage reduction"),
                     (r"\battack speed", "attack speed"), (r"\bmove speed|movement speed", "move speed"),
                     (r"\bunstoppable", "unstoppable"), (r"\buntargetable", "untargetable"),
                     (r"\bstealth", "stealth"), (r"\bstasis", "stasis")):
        if re.search(pat, low):
            tags.add(tag)
    return sorted(tags)


def strip(html):
    t = re.sub(r"<br\s*/?>", " ", html or "")
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def build(alias):
    desc = json.load(open(f"raw/{alias}.desc.json"))
    binj = json.load(open(f"raw/{alias}.bin.json"))
    rootkey = next((k for k in binj if k.endswith("/CharacterRecords/Root")), None)
    r = binj.get(rootkey, {})
    g = lambda k: (r.get(k) or {}).get("baseValue") if isinstance(r.get(k), dict) else r.get(k)
    stats = {"hp": g("baseHPModifiable"), "hpPerLevel": g("hpPerLevelModifiable"), "ad": g("baseDamageModifiable"),
             "adPerLevel": g("damagePerLevelModifiable"), "armor": g("baseArmorModifiable"),
             "armorPerLevel": g("armorPerLevelModifiable"), "mr": g("baseSpellBlockModifiable"),
             "mrPerLevel": g("spellBlockPerLevelModifiable"), "attackSpeed": g("attackSpeedModifiable"),
             "attackSpeedPerLevel": g("attackSpeedPerLevelModifiable"), "range": g("attackRangeModifiable"),
             "moveSpeed": g("baseMoveSpeedModifiable")}
    stats = {k: fv(v) for k, v in stats.items() if v is not None}
    abil = r.get("mAbilities") or []
    out = {"id": desc["id"], "alias": alias, "name": desc["name"], "title": desc.get("title"),
           "classes": desc.get("roles"), "attackType": (desc.get("tacticalInfo") or {}).get("attackType"),
           "damageType": (desc.get("tacticalInfo") or {}).get("damageType"), "riotRatings": desc.get("playstyleInfo"),
           "resource": None, "stats": stats, "abilities": {}, "source": "Community Dragon latest (live patch) game files + client data"}
    spells = {s["spellKey"].upper(): s for s in desc.get("spells", [])}
    spells["Passive"] = {"name": desc["passive"]["name"], "description": desc["passive"].get("description", ""),
                         "dynamicDescription": desc["passive"].get("description", "")}
    names = r.get("spellNames") or []
    base = rootkey.rsplit("/CharacterRecords/", 1)[0] + "/Spells/"
    used = set()
    paths = []
    for i in range(4):   # Q W E R come from spellNames (mAbilities isn't always in slot order)
        p = base + names[i].split("/")[0] if i < len(names) else None
        paths.append(p); used.add(p)
    pas = (r.get("mCharacterPassiveSpell") or "").rsplit("/", 1)[0] or next((a for a in abil if a not in used), None)
    paths.append(pas)
    for i, slot in enumerate(SLOTS):
        path = paths[i]
        objs = [(k, v) for k, v in binj.items() if path and k.startswith(path + "/") and isinstance(v, dict) and "mSpell" in v]
        if slot == "Passive" and not objs and r.get("mCharacterPassiveSpell"):
            objs = [(k, v) for k, v in binj.items() if k == r["mCharacterPassiveSpell"]]
        main = None
        if slot != "Passive" and i < len(names):
            main = next((v for k, v in objs if k.endswith("/" + names[i].split("/")[-1])), None)
        if main is None and objs:
            main = objs[-1][1]
        dv, calcs = {}, {}
        if main is not None:
            objs = [(k, v) for k, v in objs if v is main] + [(k, v) for k, v in objs if v is not main]
        for k, v in objs:
            s = v["mSpell"]
            for x in s.get("DataValues") or []:
                if "name" in x and x["name"] not in dv:
                    dv[x["name"]] = ranks(x.get("values"), 3 if slot == "R" else 5)
            for cn, c in (s.get("mSpellCalculations") or {}).items():
                if isinstance(c, dict) and cn not in calcs:
                    calcs[cn] = calc_text(c)
        ms = (main or {}).get("mSpell", {})
        n = 3 if slot == "R" else 5
        sp = spells.get(slot, {})
        dyn = sp.get("dynamicDescription") or sp.get("description") or ""
        text = strip(render(dyn, dv, calcs))
        out["abilities"][slot] = {
            "name": sp.get("name"),
            "cooldown": ranks(ms.get("cooldownTime"), n),
            "cost": ranks(ms.get("mana"), n),
            "costType": sp.get("costBurnModifier") and None,
            "range": sp.get("range", [None])[0] if isinstance(sp.get("range"), list) and sp.get("range") else None,
            "description": text,
            "summary": strip(sp.get("description", "")),
            "values": {k: v for k, v in dv.items() if v is not None},
            "formulas": {k: resolve(v, dv, calcs) for k, v in calcs.items()},
            "tags": tags_from(dyn, strip(dyn)),
        }
    return out


if __name__ == "__main__":
    os.makedirs("out", exist_ok=True)
    champs = json.load(open("raw/summary.json"))
    bad = []
    for c in champs:
        try:
            new = build(c["alias"])
            p = f"out/{c['alias']}.json"
            if os.path.exists(p):   # keep the hand-written profile
                old = json.load(open(p))
                if "profile" in old:
                    new["profile"] = old["profile"]
            json.dump(new, open(p, "w"), indent=1, ensure_ascii=False)
        except Exception as e:
            bad.append((c["alias"], repr(e)[:120]))
    print(len(champs) - len(bad), "built;", "failed:", bad)

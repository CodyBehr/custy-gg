"""Headbutt damage race: from a moment in a replay, both champions stand and fight with what they have.
Garen vs Darius, early levels. Numbers from the game's own data (patch 16.22), checked against real hits."""
import sys, json, copy
sys.path.insert(0, "/home/claude/custy-gg/collector"); import replay_trades as RT

def mit(armor): return 100.0 / (100.0 + armor)
def growth(lvl): return (lvl - 1) * (0.7025 + 0.0175 * (lvl - 1))

def run(s, verbose=False):
    """s: scenario dict. Returns result dict. Time steps of 0.01 s."""
    G, D = s["G"], s["D"]
    t, dt, log = s["t0"], 0.01, []
    ign_end = s["t0"] + 5 if s.get("ignite") else -1
    gw_end = ign_end
    shred_until = -1
    bleed = list(s["bleed"])   # expiry times of hemorrhage stacks on Garen
    might_until = -1
    dmg_by = {"G": 0, "D": 0}
    q_armed = False; silence_until = -1; w_dr_until = -1; shield = 0; shield_until = -1
    nxt_bleed_tick = t + 1.26
    def g_ad(): return G["ad"] + (G["conq"] * G["conq_ad"])
    def d_ad(): return D["ad"] + D["conq"] * D["conq_ad"] + (35 if t < might_until else 0)
    def d_bonus(): return d_ad() - 64
    def d_armor(): return D["armor"] * (0.75 if t < shred_until else 1.0)
    def hit_garen(raw, what):
        nonlocal shield
        v = raw * mit(G["armor"]) * (1 - (G["w_dr"] if t < w_dr_until else 0))
        if t < shield_until and shield > 0:
            a = min(shield, v); shield -= a; v -= a
        G["hp"] -= v; dmg_by["D"] += v
        D["hp"] = min(D["max"], D["hp"] + v * D["vamp"] * (0.6 if t < gw_end else 1))
        log.append((round(t, 2), "Darius " + what, round(v)))
    def add_stack():
        nonlocal might_until
        bleed[:] = [x for x in bleed if x > t]
        if t < might_until or len(bleed) >= 4:
            might_until = t + 5; bleed[:] = [t + 5] * 5
        else:
            bleed.append(t + 5); bleed[:] = [t + 5] * len(bleed)   # new stack refreshes all
        D["conq"] = min(12, D["conq"] + 2)
    def hit_darius(raw, what, plate=True):
        v = raw * mit(d_armor())
        if plate and D.get("plating", 0) > 0:
            v = max(0, v - D["plate_amt"]); D["plating"] -= 1
        D["hp"] -= v; dmg_by["G"] += v
        if G["conq"] >= 12 and G["conq_ad"]: G["hp"] = min(G["max"], G["hp"] + v * 0.08)
        G["conq"] = min(12, G["conq"] + (2 if G["conq_ad"] else 0))
        log.append((round(t, 2), "Garen " + what, round(v)))
    while t < s["t0"] + 20 and G["hp"] > 0 and D["hp"] > 0:
        # Garen level-up
        if G.get("lvl_at") and t >= G["lvl_at"]:
            G["lvl_at"] = None; G["max"] += 98 * 0.72; G["hp"] += 98 * 0.72; G["armor"] += 4.2 * 0.72
            log.append((round(t, 2), "Garen hits level 2 -> " + G["learn"], 0))
            if G["learn"] == "Q": G["q_ready"] = t
            if G["learn"] == "W": G["w_ready"] = t
        # Garen E ticks
        if G["e_ticks"] and t >= G["e_ticks"][0]:
            G["e_ticks"].pop(0); G["e_hits"] += 1
            hit_darius((4 + 0.4 * g_ad()) * 1.25, "E tick")
            if G["e_hits"] >= 6: shred_until = t + 6
        spinning = bool(G["e_ticks"])
        # Garen Q
        if G.get("q_ready") is not None and t >= G["q_ready"]:
            q_armed = True; G["q_ready"] = None; log.append((round(t, 2), "Garen Q (speed, next hit empowered)", 0))
        # Garen W: used when Darius's W or Q comes up
        if G.get("w_ready") is not None and t >= G["w_ready"] and (abs(t - D["w_cd"]) < 0.05 or abs(t - D["q_cd"]) < 0.05):
            w_dr_until = t + 4; shield = 65 + 0.18 * G["bonus_hp"]; shield_until = t + 0.75; G["w_ready"] = None
            log.append((round(t, 2), "Garen W (shield %d, -25%% damage 4s)" % shield, 0))
        # Garen autos
        if not spinning and t >= G["aa"]:
            if q_armed:
                hit_darius(30 + 1.5 * g_ad(), "Q hit"); q_armed = False; silence_until = t + 1.5
            else:
                hit_darius(g_ad(), "auto")
            G["aa"] = t + 1 / G["as"]
        # Ignite
        if t < ign_end and abs((t - s["t0"]) % 1.0) < dt / 2:
            D["hp"] -= 22; dmg_by["G"] += 22; log.append((round(t, 2), "Ignite tick", 22))
        # Darius W (empowered auto) / Q / autos
        if t >= D["q_cd"] and t >= silence_until and not s.get("q_dodged"):
            D["q_cd"] = t + 9; D["q_hit"] = t + 0.75
        if D.get("q_hit") and t >= D["q_hit"]:
            D["q_hit"] = None
            if s.get("q_handle"):   # Garen Flashes into the middle: handle damage, no bleed, no heal
                hit_garen((50 + d_ad()) * 0.35, "Q handle (Garen flashed in)"); heal = 0
            else:
                hit_garen(50 + d_ad(), "Q blade"); add_stack()
                heal = (D["max"] - D["hp"]) * 0.17 * (0.6 if t < gw_end else 1)
            D["hp"] += heal
            log.append((round(t, 2), "Darius Q heal", round(heal)))
        if t >= D["aa"]:
            if t >= D["w_cd"] and t >= silence_until:
                hit_garen(1.4 * d_ad(), "W"); D["w_cd"] = t + 5
            else:
                hit_garen(d_ad(), "auto")
            add_stack(); D["aa"] = t + 1 / D["as"]
        # bleed
        if t >= nxt_bleed_tick:
            n = len([x for x in bleed if x > t])
            if n:
                v = n * (14 + 0.3 * d_bonus()) / 4 * mit(G["armor"])
                G["hp"] -= v; dmg_by["D"] += v; log.append((round(t, 2), "bleed x%d" % n, round(v)))
            nxt_bleed_tick += 1.26
        G["hp"] -= s.get("minions", 0) * dt; D["hp"] -= s.get("minions_d", 0) * dt
        # Doran's Shield recovery (~5 HP/s after champion damage)
        G["hp"] = min(G["max"], G["hp"] + 5 * dt)
        t += dt
    win = "Garen" if D["hp"] <= 0 else "Darius" if G["hp"] <= 0 else "nobody (20s)"
    return {"winner": win, "time": round(t - s["t0"], 1), "garen_hp": round(max(0, G["hp"])), "darius_hp": round(max(0, D["hp"])), "log": log}

def base(t0, G_hp, D_hp):
    G = {"hp": G_hp, "max": 810, "bonus_hp": 120, "armor": 38, "ad": 69 + 10.8, "as": 0.641, "conq": 12, "conq_ad": 1.16,
         "e_ticks": [98.95, 99.42], "e_hits": 5, "aa": 99.62, "lvl_at": t0 + 0.45, "learn": "Q"}
    D = {"hp": D_hp, "max": 824, "armor": 40.7, "ad": 64 + 10 + 5.4, "as": 0.692, "conq": 4, "conq_ad": 1.16, "vamp": 0.035,
         "q_cd": 106.4, "w_cd": 101.9, "aa": 98.8}
    return {"t0": t0, "G": G, "D": D, "bleed": [102.35], "ignite": True}

if __name__ == "__main__":
    p = "/mnt/user-data/uploads/Replays/NA1-5679011844.rofl"
    d = RT.decode(p, until=110); sk = [x.get("SKIN") for x in d["stats"]]; g, dr = sk.index("Garen"), sk.index("Darius")
    t0 = 98.5
    took = lambda k, a, b: sum(v for t, tg, at, v in d["hits"] if tg == k and a <= t <= b)
    # health: full at 1:00 (both), minus every hit since, plus a little regen
    # health from the replay's health line (Riot's minute values minus every hit, healing spread between them)
    T = json.load(open("/home/claude/custy-gg/public/experts/Garen-Darius-TOP.timelines.json"))["5679011844"]
    anch = {g: [tuple(x) for x in T["Garen"]["frames"]], dr: [tuple(x) for x in T["Darius"]["frames"]]}
    hs = RT.hp_series(d, anch, {}, t0, t0, 0.5)
    G_hp, D_hp = hs[str(g)][0][1], hs[str(dr)][0][1]
    G_hp = min(G_hp, 810)
    print("start (1:38.5): Garen %.0f/810, Darius %.0f/824" % (G_hp, D_hp))
    S = {}
    a = base(t0, G_hp, D_hp); S["A. Stays, levels Q, Ignite"] = a
    b = copy.deepcopy(a); b["ignite"] = False; S["B. Stays, levels Q, no Ignite"] = b
    c = copy.deepcopy(a); c["G"]["learn"] = "W"; c["G"]["w_dr"] = 0.25; S["C. Stays, levels W (what he took), Ignite"] = c
    e = copy.deepcopy(a); e["ignite"] = False; e["G"]["conq"] = 0; e["G"]["conq_ad"] = 0; S["D. Phase Rush + Ghost/Flash instead (no Conqueror, no Ignite)"] = e
    f = copy.deepcopy(a); f["G"]["hp"] -= 58; f["D"]["hp"] += 15; f["bleed"] = [102.35, 103.22]; S["E. Same as A, but Darius's 1:37 Q hit the blade"] = f
    h = copy.deepcopy(a); h["D"]["plating"] = 3; h["D"]["plate_amt"] = 32; S["F. Same as A, but Darius's Bone Plating was up"] = h
    out = {}
    for k, sc in S.items():
        r = run(copy.deepcopy(sc)); out[k] = r
        print("%-62s -> %s wins in %.1fs | Garen %d HP left, Darius %d" % (k, r["winner"], r["time"], r["garen_hp"], r["darius_hp"]))
    json.dump({k: v for k, v in out.items()}, open("/home/claude/sim/out.json", "w"))
    print("\nFight log, scenario A:")
    for x in out["A. Stays, levels Q, Ignite"]["log"]: print("  ", x)

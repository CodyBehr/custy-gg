"""
Minion waves from a replay file (patch 16.22): every lane minion's team, lane, wave, type, path, when it died and
who last-hit it. Offline and post-game, from the .rofl file only.

How it's read:
  - Movement records (871) carry each unit's id in the same byte cipher as positions (T871), so a track's key
    decodes to the unit's network id (0x40xxxxxx).
  - Unit deaths (981) are keyed to the dead unit's id. Payload byte 1 is 0x9d; bytes 2-3 are the killer:
    a champion when byte 3 is 0x29 and byte 2 is one of KILLER (checked against every player's end-of-game
    minion + monster count in the replay: laners within a few, supports exact).
  - Lane minions are the units whose track starts at a base; lane from where they walk; wave from spawn time
    (a wave every 30 s); type from spawn order inside the wave (melee first, then the siege minion, then casters).
"""

import math
import replay_trades as RT

KILLER = {0x54: 0, 0x5C: 1, 0xE0: 2, 0xE8: 3, 0xE4: 4, 0xEC: 5, 0xC0: 6, 0xC8: 7, 0xC4: 8, 0xCC: 9}
BASES = {100: (1500, 1500), 200: (13300, 13300)}
# Byte cipher for unit ids in movement records. Same cipher as positions (replay_trades.T871), but exact: T871 was
# fitted from coordinates, where an entry off by 1-4 moves a point by a few units and went unnoticed; ids need it
# exact. Learned from track ends vs unit deaths in 14 games (a clean 1:1 table).
TID = bytes.fromhex("d8f76ec22c4fabd7daa45fb38652329fca5af2df01c14319155bbc04f1c4031b701a88050a78083a6369d09702aacc1c3f2095e2e739b42598817f1423b81700fae421a730a06b55a383de0bcf92e83673768e1f4b2ed2b7c864ad7e85a6a9e98a3166423bc7c32791a535ffbaebbe340c296a28d33d46e1752b967bf84816504c2ad5eaf90f715c4982b27db0263eb644e09e8dfd337a1d8f87acdba856aeec60bf5d723740e662e5c5f6efaf651311c96c470712f36f0d4a518c0661b54e77dcce6d53384dd980d174cde3fe93d4591e9d24d645fc9add3ca290bb997cb9228b9c18f0fb41b10e67549bedee94f58409c0c65e105768bd89f42fa12dcb5879")


def lane_of(x, z):
    if x < 2300 or z > 12600:
        return "top"
    if z < 2300 or x > 12600:
        return "bot"
    if abs(x - z) < 1300:
        return "mid"
    return None


def unit_id(key):
    """Track key (as decode() stores it) -> the unit's network id."""
    if isinstance(key, int) and key < 10:
        return RT.CHAMPS[key]
    return 0x40000000 | TID[(key >> 16) & 255] << 16 | TID[(key >> 8) & 255] << 8 | TID[key & 255]


def unit_deaths(path, until=99999.0):
    """[(t, unit id, killer slot or None)] from record 981."""
    _v, _stats, chunks = RT.read_rofl(path)
    out = []
    for body in chunks:
        for t, nid, prm, pl in RT._blocks(body):
            if t > until:
                break
            if nid == 981 and len(pl) >= 4:
                k = KILLER.get(pl[2]) if pl[3] == 0x29 else None
                out.append((t, prm, k))
    return out


def minions(d, deaths):
    """d: replay_trades.decode() output. Returns {unit id: minion} for lane minions:
    {team, lane, wave, kind: melee|caster|siege, spawn, died, killer, track}."""
    by_id = {unit_id(k): L for k, L in d["tracks"].items() if not (isinstance(k, int) and k < 10)}
    dead = {u: (t, k) for t, u, k in deaths}
    raw = []
    for u, L in by_id.items():
        if len(L) < 3:
            continue
        x0, z0 = L[0][1], L[0][2]
        team = next((tm for tm, (bx, bz) in BASES.items() if math.hypot(x0 - bx, z0 - bz) < 2600), None)
        if team is None or L[0][0] < 20:
            continue
        # lane: where it is most of the time once out of base
        votes = {}
        for t, x, z in L[2:]:
            ln = lane_of(x, z)
            if ln and math.hypot(x - BASES[team][0], z - BASES[team][1]) > 3500:
                votes[ln] = votes.get(ln, 0) + 1
        if not votes:
            continue
        lane = max(votes, key=votes.get)
        raw.append((L[0][0], u, team, lane, L))
    raw.sort()
    if not raw:
        return {}
    t_first = raw[0][0]
    out = {}
    groups = {}
    for t0, u, team, lane, L in raw:
        wave = int(round((t0 - t_first) / 30.0))
        groups.setdefault((team, lane, wave), []).append((t0, u, L))
    for (team, lane, wave), G in groups.items():
        G.sort()
        n = len(G)
        for i, (t0, u, L) in enumerate(G):
            kind = "melee" if i < 3 else ("siege" if n >= 7 and i == 3 else "caster")
            dt, dk = dead.get(u, (None, None))
            out[u] = {"team": team, "lane": lane, "wave": wave, "kind": kind, "spawn": round(t0, 2),
                      "died": round(dt, 2) if dt is not None else None, "killer": dk, "track": L}
    return out


def cs_events(mins):
    """[(t, slot, lane, kind, team)] for every lane minion a champion last-hit."""
    ev = [(m["died"], m["killer"], m["lane"], m["kind"], m["team"]) for m in mins.values()
          if m["died"] is not None and m["killer"] is not None]
    return sorted(ev)


def wave_state(mins, lane, t):
    """Alive minions of each team in a lane at time t, with the front of each wave (lane progress s = x + z,
    which grows from the blue base toward the red base)."""
    st = {100: [], 200: []}
    for m in mins.values():
        if m["lane"] != lane or m["spawn"] > t or (m["died"] is not None and m["died"] <= t):
            continue
        p = RT._at(m["track"], t)
        if p:
            st[m["team"]].append((p[0] + p[1], m["kind"], p))
    out = {}
    for tm, L in st.items():
        s = [a for a, _k, _p in L]
        out[tm] = {"n": len(L), "melee": sum(1 for _a, k, _p in L if k == "melee"),
                   "caster": sum(1 for _a, k, _p in L if k == "caster"), "siege": sum(1 for _a, k, _p in L if k == "siege"),
                   "front": (max(s) if tm == 100 else min(s)) if s else None}
    return out


FOUNTAIN = {100: (400, 420), 200: (14300, 14400)}


def recalls(d, deaths_by_slot, until=99999.0):
    """[(slot, done_t, from_x, from_z)]: a jump of 3,000+ units straight into the team's fountain that isn't a
    respawn (no death in the 60 s before). done_t is the first move from the fountain, just after the 8 s recall.
    Checked against Riot's item purchases, which follow each one within seconds."""
    out = []
    for k in range(10):
        L = d["tracks"].get(k) or []
        fx, fz = FOUNTAIN[100 if k < 5 else 200]
        for a, b in zip(L, L[1:]):
            if b[0] > until:
                break
            if math.hypot(b[1] - a[1], b[2] - a[2]) > 3000 and math.hypot(b[1] - fx, b[2] - fz) < 1500:
                if any(b[0] - 60 <= x <= b[0] for x in deaths_by_slot.get(k, [])):
                    continue
                out.append((k, round(b[0], 1), a[1], a[2]))
    return sorted(out, key=lambda r: r[1])


def minion_damage(path, mins, until=99999.0):
    """Every hit each lane minion took (record 393 keyed to the minion): {unit id: [(t, amount)]}.
    A minion's hits add up to its max health at death (plus the last hit's overkill), so health over time is
    1 - (damage so far / damage at death). Melee ~490 and casters ~340 early, growing over the game."""
    _v, _s, chunks = RT.read_rofl(path)
    out = {}
    for body in chunks:
        for t, nid, prm, pl in RT._blocks(body):
            if t > until:
                break
            if nid == 393 and prm in mins:
                out.setdefault(prm, []).append((t, RT._amount(bytes(pl))))
    return out


def minion_hp(mins, dmg, u, t):
    """Fraction of health left (0-1) for minion u at time t, or None if it isn't alive then."""
    m = mins[u]
    if m["spawn"] > t or (m["died"] is not None and m["died"] <= t):
        return None
    hits = dmg.get(u, [])
    total = sum(a for _t, a in hits) or 1.0
    done = sum(a for ht, a in hits if ht <= t)
    return max(0.0, 1.0 - done / total)


def auto_attacks(path, until=99999.0):
    """[(t, slot)]: a champion starting a basic attack (record 991, keyed to the attacker). Fires before 49 of
    Garen's 54 hits on Darius in one game and never during his E spin. The target isn't decoded yet; an auto not
    followed by a hit on a champion went into a minion or monster."""
    _v, _s, chunks = RT.read_rofl(path)
    out = []
    for body in chunks:
        for t, nid, prm, pl in RT._blocks(body):
            if t > until:
                break
            if nid == 991 and prm in RT.CHAMPS:
                out.append((t, RT.CHAMPS.index(prm)))
    return out

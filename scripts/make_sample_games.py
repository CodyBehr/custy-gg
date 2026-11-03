#!/usr/bin/env python3
"""
Generates realistic fake custom games in the same format the League client
returns, so you can try the site before anyone has played.

    python scripts/make_sample_games.py                     writes scripts/sample/games.json
    python scripts/make_sample_games.py --post URL KEY      also uploads them to your site

The sample players and games are invented.
"""

import json
import os
import random
import sys
import time
import urllib.request
import uuid

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sample", "games.json")

POOLS = {
    "TOP": [86, 122, 875, 54, 516, 266, 114, 17, 82, 164, 24, 58, 150, 92, 897, 83],
    "JUNGLE": [64, 32, 19, 254, 104, 141, 120, 245, 121, 234, 56, 113, 11, 131, 876, 233],
    "MIDDLE": [103, 157, 238, 99, 134, 112, 55, 45, 61, 84, 517, 777, 1, 105, 910, 3],
    "BOTTOM": [222, 51, 81, 145, 202, 21, 67, 22, 236, 360, 119, 498, 901, 15, 29],
    "UTILITY": [412, 89, 117, 267, 25, 53, 555, 235, 350, 43, 111, 16, 497, 902, 201, 143],
}
ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

FRIENDS = [
    # name, tag, skill, preferred roles
    ("Mayo", "mayo", 1.25, ["MIDDLE", "TOP"]),
    ("lowkeyjgl", "jgl", 1.15, ["JUNGLE"]),
    ("Pentakill Pam", "5555", 1.2, ["BOTTOM", "MIDDLE"]),
    ("noflashjustvibes", "TOP", 0.95, ["TOP", "UTILITY"]),
    ("Sona Arrival", "bard", 1.0, ["UTILITY"]),
    ("Kaiju Kevin", "NA1", 0.9, ["TOP", "JUNGLE"]),
    ("dewdrop", "mint", 1.05, ["UTILITY", "BOTTOM"]),
    ("Tilted Tuesday", "4417", 0.85, ["MIDDLE", "BOTTOM"]),
    ("minionwhisperer", "cs", 1.1, ["BOTTOM"]),
    ("Gromp Enjoyer", "frog", 0.95, ["JUNGLE", "TOP"]),
    ("Jayden", "NA1", 0.8, ["UTILITY", "MIDDLE"]),
    ("big rift energy", "666", 1.0, ["TOP", "MIDDLE"]),
]
PUUIDS = {f[0]: str(uuid.UUID(int=random.getrandbits(128))) for f in FRIENDS}
ICONS = {f[0]: random.choice([29, 588, 4568, 5367, 6631, 4834, 3505, 1301]) for f in FRIENDS}

ITEMS = {
    "TOP": [3078, 3053, 3071, 3074, 3065, 3068, 6333, 3742, 3161, 3181, 2501, 3143],
    "JUNGLE": [3071, 3142, 6692, 3074, 3053, 3156, 3068, 3065, 6631, 3179],
    "MIDDLE": [3089, 3157, 3135, 4645, 3165, 6655, 3100, 3118, 3137, 3102, 3115],
    "BOTTOM": [3031, 3036, 3046, 3072, 3094, 3085, 3087, 3032, 3153, 3033, 3124],
    "UTILITY": [3190, 3107, 3504, 6616, 2065, 3109, 3050, 3222, 4005, 3011],
}
BOOTS = {"TOP": 3047, "JUNGLE": 3111, "MIDDLE": 3020, "BOTTOM": 3006, "UTILITY": 3158}
TRINKET = {"TOP": 3340, "JUNGLE": 3364, "MIDDLE": 3340, "BOTTOM": 3363, "UTILITY": 3364}
SPELLS = {"TOP": [12, 14], "JUNGLE": [11], "MIDDLE": [14, 12], "BOTTOM": [7, 21], "UTILITY": [14, 3]}
KEYSTONES = {8000: [8005, 8008, 8010, 8021], 8100: [8112, 8128, 9923], 8200: [8214, 8229, 8230], 8300: [8351, 8360, 8369], 8400: [8437, 8439, 8465]}
ROLE_STYLE = {"TOP": [8000, 8400], "JUNGLE": [8000, 8100], "MIDDLE": [8100, 8200], "BOTTOM": [8000], "UTILITY": [8400, 8200]}
LANE = {"TOP": ("TOP", "SOLO"), "JUNGLE": ("JUNGLE", "NONE"), "MIDDLE": ("MIDDLE", "SOLO"), "BOTTOM": ("BOTTOM", "DUO_CARRY"), "UTILITY": ("BOTTOM", "DUO_SUPPORT")}


def split(total, weights):
    """Split an integer total randomly according to weights."""
    out = [0] * len(weights)
    for _ in range(total):
        out[random.choices(range(len(weights)), weights=weights)[0]] += 1
    return out


def assign_roles(names):
    roles = {}
    left = list(ROLES)
    for n in sorted(names, key=lambda _: random.random()):
        prefs = dict((f[0], f[3]) for f in FRIENDS)[n]
        pick = next((r for r in prefs if r in left), None) or random.choice(left)
        roles[n] = pick
        left.remove(pick)
    return roles


def make_game(game_id, start_ms, remake=False):
    skill = {f[0]: f[2] for f in FRIENDS}
    lobby = random.sample([f[0] for f in FRIENDS], 10)
    blue, red = lobby[:5], lobby[5:]
    roles = {**assign_roles(blue), **assign_roles(red)}
    strength = lambda team: sum(skill[n] for n in team) + random.gauss(0, 0.6)
    blue_wins = strength(blue) > strength(red)

    duration = random.randint(170, 230) if remake else int(random.gauss(31, 6) * 60)
    duration = max(duration, 160 if remake else 17 * 60)
    minutes = duration / 60
    drafted = set()
    with_bans = random.random() < 0.5
    bans = {100: [], 200: []}
    if with_bans:
        for t in (100, 200):
            for _ in range(random.choice([3, 5])):
                c = random.choice(random.choice(list(POOLS.values())))
                if c not in drafted:
                    drafted.add(c)
                    bans[t].append(c)
    lanes_known = random.random() < 0.7

    participants, identities = [], []
    team_kills = {}
    for team_id, team in ((100, blue), (200, red)):
        won = blue_wins == (team_id == 100)
        kills = 0 if remake else max(4, int(random.gauss(0.95 if won else 0.6, 0.15) * minutes))
        team_kills[team_id] = kills

    for idx, name in enumerate(blue + red):
        team_id = 100 if idx < 5 else 200
        won = blue_wins == (team_id == 100)
        role = roles[name]
        pool = [c for c in POOLS[role] if c not in drafted]
        champ = random.choice(pool[:8] if random.random() < 0.7 else pool)
        drafted.add(champ)
        participants.append({"participantId": idx + 1, "teamId": team_id, "championId": champ, "role": role, "name": name, "won": won})

    for team_id in (100, 200):
        team = [p for p in participants if p["teamId"] == team_id]
        enemy_kills = team_kills[300 - team_id]
        weights_k = [{"TOP": 2, "JUNGLE": 2.2, "MIDDLE": 2.6, "BOTTOM": 3, "UTILITY": 0.6}[p["role"]] * skill[p["name"]] for p in team]
        weights_d = [{"TOP": 2, "JUNGLE": 2, "MIDDLE": 2, "BOTTOM": 2, "UTILITY": 2.2}[p["role"]] / skill[p["name"]] for p in team]
        ks = split(team_kills[team_id], weights_k)
        ds = split(enemy_kills, weights_d)
        for p, k, d in zip(team, ks, ds):
            p["kills"], p["deaths"] = k, d
            kp = random.uniform(0.45, 0.8) if p["role"] != "UTILITY" else random.uniform(0.6, 0.9)
            p["assists"] = max(0, int(team_kills[team_id] * kp) - k)

    for p in participants:
        role, won = p["role"], p["won"]
        s = skill[p["name"]]
        cspm = {"TOP": 6.6, "JUNGLE": 5.6, "MIDDLE": 7.2, "BOTTOM": 7.8, "UTILITY": 1.1}[role] * (0.85 + 0.15 * s) * random.uniform(0.85, 1.12)
        cs = int(cspm * minutes)
        jungle_cs = int(cs * 0.85) if role == "JUNGLE" else random.randint(0, 12)
        gold = int((310 + (40 if won else 0)) * minutes + p["kills"] * 300 + p["assists"] * 110 + cs * 20 * 0.3)
        dpm = {"TOP": 720, "JUNGLE": 560, "MIDDLE": 860, "BOTTOM": 880, "UTILITY": 360}[role] * s * random.uniform(0.75, 1.3)
        n_items = min(6, max(1, int(gold / 3000)))
        items = random.sample(ITEMS[role], n_items - 1) + [BOOTS[role]]
        items += [0] * (6 - len(items))
        random.shuffle(items)
        style = random.choice(ROLE_STYLE[role])
        sub = random.choice([x for x in KEYSTONES if x != style])
        spells = [4, random.choice(SPELLS[role])]
        if random.random() < 0.5:
            spells.reverse()
        multi = 1
        if p["kills"] >= 2: multi = random.choices([1, 2, 3, 4, 5], weights=[30, 40, 14, 4, 1.2])[0]
        multi = min(multi, max(1, p["kills"]))
        lane, lane_role = LANE[role] if lanes_known else ("NONE", "NONE")
        stats = {
            "participantId": p["participantId"], "win": won,
            "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
            "champLevel": min(18, int(8 + minutes / 3 + random.randint(-2, 2) - (3 if role == "UTILITY" else 0))),
            "totalMinionsKilled": cs - jungle_cs, "neutralMinionsKilled": jungle_cs,
            "goldEarned": gold, "goldSpent": int(gold * 0.93),
            "totalDamageDealtToChampions": int(dpm * minutes),
            "totalDamageTaken": int({"TOP": 1050, "JUNGLE": 1000, "MIDDLE": 650, "BOTTOM": 580, "UTILITY": 620}[role] * minutes * random.uniform(0.8, 1.25)),
            "damageSelfMitigated": int({"TOP": 900, "JUNGLE": 700, "MIDDLE": 300, "BOTTOM": 250, "UTILITY": 500}[role] * minutes),
            "damageDealtToObjectives": int({"TOP": 250, "JUNGLE": 700, "MIDDLE": 180, "BOTTOM": 300, "UTILITY": 60}[role] * minutes * (1.4 if won else 0.6)),
            "damageDealtToTurrets": int({"TOP": 180, "JUNGLE": 60, "MIDDLE": 120, "BOTTOM": 220, "UTILITY": 30}[role] * minutes * (1.4 if won else 0.5)),
            "totalHeal": int(random.uniform(100, 400) * minutes),
            "visionScore": int({"TOP": 0.7, "JUNGLE": 1.2, "MIDDLE": 0.8, "BOTTOM": 0.75, "UTILITY": 2.4}[role] * minutes * random.uniform(0.7, 1.3)),
            "wardsPlaced": int({"TOP": 0.35, "JUNGLE": 0.5, "MIDDLE": 0.4, "BOTTOM": 0.4, "UTILITY": 1.3}[role] * minutes),
            "wardsKilled": random.randint(0, int(minutes / 4)),
            "visionWardsBoughtInGame": random.randint(0, 6 if role in ("UTILITY", "JUNGLE") else 2),
            "timeCCingOthers": random.randint(5, 60),
            "turretKills": random.randint(0, 3 if won else 1),
            "inhibitorKills": random.randint(0, 1) if won else 0,
            "doubleKills": 1 if multi >= 2 else 0, "tripleKills": 1 if multi >= 3 else 0,
            "quadraKills": 1 if multi >= 4 else 0, "pentaKills": 1 if multi >= 5 else 0,
            "largestMultiKill": multi, "largestKillingSpree": min(p["kills"], random.randint(0, 6)),
            "firstBloodKill": False, "firstBloodAssist": False,
            "perk0": random.choice(KEYSTONES[style]), "perkPrimaryStyle": style, "perkSubStyle": sub,
        }
        for i, it in enumerate(items):
            stats["item%d" % i] = it
        stats["item6"] = TRINKET[role]
        p["out"] = {
            "participantId": p["participantId"], "teamId": p["teamId"], "championId": p["championId"],
            "spell1Id": spells[0], "spell2Id": spells[1], "highestAchievedSeasonTier": "UNRANKED",
            "stats": stats, "timeline": {"lane": lane, "role": lane_role, "participantId": p["participantId"]},
        }
        identities.append({"participantId": p["participantId"], "player": {
            "accountId": 0, "currentAccountId": 0, "currentPlatformId": "NA1", "platformId": "NA1",
            "gameName": p["name"], "tagLine": dict((f[0], f[1]) for f in FRIENDS)[p["name"]],
            "summonerName": "", "summonerId": random.randint(10 ** 8, 10 ** 9),
            "puuid": PUUIDS[p["name"]], "profileIcon": ICONS[p["name"]], "matchHistoryUri": "",
        }})

    if not remake:
        fb = random.choice([p for p in participants if p["kills"] > 0] or participants)
        fb["out"]["stats"]["firstBloodKill"] = True

    teams = []
    for team_id in (100, 200):
        won = blue_wins == (team_id == 100)
        teams.append({
            "teamId": team_id, "win": "Win" if won else "Fail",
            "firstBlood": any(p["out"]["stats"]["firstBloodKill"] for p in participants if p["teamId"] == team_id),
            "firstTower": won and random.random() < 0.7, "firstInhibitor": won, "firstBaron": won and random.random() < 0.6,
            "firstDargon": random.random() < 0.5,
            "towerKills": 0 if remake else (random.randint(7, 11) if won else random.randint(1, 5)),
            "inhibitorKills": 0 if remake else (random.randint(1, 3) if won else random.randint(0, 1)),
            "baronKills": 0 if remake else (random.randint(0, 2) if won else random.randint(0, 1)),
            "dragonKills": 0 if remake else (random.randint(2, 4) if won else random.randint(0, 2)),
            "riftHeraldKills": random.randint(0, 1), "vilemawKills": 0, "dominionVictoryScore": 0,
            "bans": [{"championId": c, "pickTurn": i + 1} for i, c in enumerate(bans[team_id])],
        })

    return {
        "gameId": game_id, "platformId": "NA1", "gameCreation": start_ms,
        "gameCreationDate": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(start_ms / 1000)),
        "gameDuration": duration, "queueId": 0, "mapId": 11, "seasonId": 16,
        "gameVersion": "16.21.712.4402", "gameMode": "CLASSIC", "gameType": "CUSTOM_GAME",
        "teams": teams, "participants": [p["out"] for p in participants],
        "participantIdentities": identities,
    }


def build(n_nights=14):
    games = []
    now = int(time.time() * 1000)
    game_id = 5_400_000_000
    for night in range(n_nights, 0, -1):
        start = now - night * 5 * 24 * 3600 * 1000 + random.randint(-3, 3) * 3600 * 1000
        for g in range(random.randint(3, 6)):
            remake = random.random() < 0.04
            game = make_game(game_id, start, remake)
            games.append(game)
            game_id += random.randint(2_000, 90_000)
            start += (game["gameDuration"] + random.randint(240, 600)) * 1000
    return games


def main():
    games = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(games, f)
    print("Wrote %d sample games to %s" % (len(games), OUT))
    if len(sys.argv) >= 4 and sys.argv[1] == "--post":
        url, key = sys.argv[2].rstrip("/") + "/api/ingest", sys.argv[3]
        for g in games:
            req = urllib.request.Request(url, data=json.dumps({"game": g}).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req) as r:
                pass
        print("Uploaded %d games to %s" % (len(games), url))


if __name__ == "__main__":
    main()

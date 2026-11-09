"""Turn a Riot API match+timeline into the League client's format, so the review page can be tested with real games."""
import json, sys, os
src, puuid, out = sys.argv[1], open(sys.argv[2]).read().strip(), sys.argv[3]
d = json.load(open(src)); m, tl = d["match"]["info"], d["timeline"]["info"]
LANE = {"TOP": ("TOP", "SOLO"), "JUNGLE": ("JUNGLE", "NONE"), "MIDDLE": ("MIDDLE", "SOLO"), "BOTTOM": ("BOTTOM", "DUO_CARRY"), "UTILITY": ("BOTTOM", "DUO_SUPPORT")}
parts, ids = [], []
for p in m["participants"]:
    lane, role = LANE.get(p.get("teamPosition"), ("NONE", "NONE"))
    st = {k: p.get(k) for k in ("win", "kills", "deaths", "assists", "totalMinionsKilled", "neutralMinionsKilled", "roleBoundItem", "goldEarned")}
    st.update({"item%d" % i: p["item%d" % i] for i in range(7)})
    parts.append({"participantId": p["participantId"], "teamId": p["teamId"], "championId": p["championId"], "spell1Id": p["summoner1Id"],
                  "spell2Id": p["summoner2Id"], "stats": st, "timeline": {"lane": lane, "role": role}})
    ids.append({"participantId": p["participantId"], "player": {"puuid": p["puuid"], "gameName": p.get("riotIdGameName"), "tagLine": p.get("riotIdTagline")}})
game = {"gameId": m["gameId"], "gameCreation": m["gameCreation"], "gameDuration": m["gameDuration"], "queueId": m["queueId"], "mapId": 11,
        "gameMode": "CLASSIC", "gameType": "MATCHED_GAME", "gameVersion": m["gameVersion"], "participants": parts, "participantIdentities": ids}
frames = [{"timestamp": f["timestamp"], "participantFrames": {k: {x: v.get(x) for x in ("totalGold", "currentGold", "minionsKilled", "jungleMinionsKilled", "level", "xp", "position")} for k, v in f["participantFrames"].items()},
           "events": f["events"]} for f in tl["frames"]]
sys.path.insert(0, "collector")
import importlib.util
os.makedirs(out, exist_ok=True)
json.dump({"game": game, "timeline": {"frames": frames}, "me": puuid, "summary": None}, open(os.path.join(out, "%s.json" % m["gameId"]), "w"))
print("wrote", m["gameId"])

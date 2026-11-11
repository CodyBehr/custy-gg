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
    sty = (p.get("perks") or {}).get("styles") or []
    if len(sty) >= 2:   # the client's shape: perk0-5, perkPrimaryStyle, perkSubStyle, statPerk0-2
        sel = [x["perk"] for x in sty[0]["selections"]] + [x["perk"] for x in sty[1]["selections"]]
        st.update({"perk%d" % i: v for i, v in enumerate(sel)}, perkPrimaryStyle=sty[0]["style"], perkSubStyle=sty[1]["style"])
        sp = p["perks"].get("statPerks") or {}
        st.update(statPerk0=sp.get("offense"), statPerk1=sp.get("flex"), statPerk2=sp.get("defense"))
    parts.append({"participantId": p["participantId"], "teamId": p["teamId"], "championId": p["championId"], "spell1Id": p["summoner1Id"],
                  "spell2Id": p["summoner2Id"], "stats": st, "timeline": {"lane": lane, "role": role}})
    ids.append({"participantId": p["participantId"], "player": {"puuid": p["puuid"], "gameName": p.get("riotIdGameName"), "tagLine": p.get("riotIdTagline")}})
game = {"gameId": m["gameId"], "gameCreation": m["gameCreation"], "gameDuration": m["gameDuration"], "queueId": m["queueId"], "mapId": 11,
        "gameMode": "CLASSIC", "gameType": "MATCHED_GAME", "gameVersion": m["gameVersion"], "participants": parts, "participantIdentities": ids}
frames = [{"timestamp": f["timestamp"], "participantFrames": {k: {x: v.get(x) for x in ("totalGold", "currentGold", "minionsKilled", "jungleMinionsKilled", "level", "xp", "position")} | {"armor": v.get("championStats", {}).get("armor")} for k, v in f["participantFrames"].items()},
           "events": f["events"]} for f in tl["frames"]]
os.makedirs(out, exist_ok=True)
json.dump({"game": game, "timeline": {"frames": frames}, "me": puuid, "summary": None}, open(os.path.join(out, "%s.json" % m["gameId"]), "w"))
print("wrote", m["gameId"])

import json, urllib.request, os, sys
from concurrent.futures import ThreadPoolExecutor
B="https://raw.communitydragon.org/latest"
def get(url, path):
    if os.path.exists(path) and os.path.getsize(path)>100: return True
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"curl/8"}), timeout=60) as r: open(path,"wb").write(r.read()); return True
    except Exception as e: print("fail",url,e); return False
summ=json.load(urllib.request.urlopen(urllib.request.Request(B+"/plugins/rcp-be-lol-game-data/global/default/v1/champion-summary.json",headers={"User-Agent":"curl/8"})))
champs=[c for c in summ if 0<c["id"]<3000]
json.dump(champs,open("raw/summary.json","w"))
def one(c):
    a=c["alias"]
    get(f"{B}/plugins/rcp-be-lol-game-data/global/default/v1/champions/{c['id']}.json", f"raw/{a}.desc.json")
    get(f"{B}/game/data/characters/{a.lower()}/{a.lower()}.bin.json", f"raw/{a}.bin.json")
with ThreadPoolExecutor(12) as ex: list(ex.map(one,champs))
print(len(champs), len([f for f in os.listdir("raw") if f.endswith(".bin.json")]), len([f for f in os.listdir("raw") if f.endswith(".desc.json")]))

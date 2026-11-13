"""
Lane trades from a downloaded replay (.rofl), for the review page.

Reads the replay file only, after the game, on this computer. It never touches the game program or a
running game. From the file it takes every champion-on-champion hit (time, attacker, target, amount),
ability casts, level-ups and champion positions, and turns them into "trades" with your lane opponent:
who started, damage each way, HP going in, and a playback of the fight on the map.

The byte tables below were fitted for patch 16.22 from replays checked against Riot's match data
(damage totals match Riot's to r = 1.00; positions are within ~10-30 units). Other patches return
"unsupported" until the tables are re-fitted.

Needs the zstandard package (bundled in the Windows app; `pip install zstandard` otherwise).
"""

import bisect
import json
import math
import os
import struct

try:
    import zstandard
except ImportError:   # running from source without it
    zstandard = None

SUPPORTED = ("16.22",)
CHAMPS = list(range(0x400000AE, 0x400000B8))     # the 10 champions' unit ids, in the replay's player order
ATK = [0x0F, 0xCF, 0x56, 0x86, 0x83, 0xD8, 0x36, 0xD5, 0x8C, 0x7D]   # damage record: attacker slot codes
TGT = [0x13, 0x35, 0x63, 0x0D, 0xE3, 0x6C, 0x05, 0x2F, 0x95, 0xF5]   # damage record: target slot codes
BASE = {0xF9: 2.0, 0x76: 8.0, 0xB2: 32.0, 0x90: 128.0, 0x29: 512.0}
CAST_MARK = bytes.fromhex("b4a4b4b4")
POS_IDS = {0x9E: 0, 0xAC: 1, 0x8C: 2, 0xE6: 3, 0x8A: 4, 0x0B: 5, 0x36: 6, 0xBD: 7, 0x8F: 8, 0x57: 9}
# Patch 16.22 tables, fitted from replays against Riot's match data (see project notes).
T871 = bytes.fromhex('d8f76fc3304fabd7d9a460b38652329fca5af2df01c143181a5bbf04f1c4031b771988050a78083a6769d09702aacc1c3f2094e2e739b42498817f0f22b81600fae421a92fa06a54a383de0bcf92e93672758e1f4d2dd2b7c863ac7e85a6a7e88a31654238c7c22791a534ffbbebbe350c296b28d33d46e1742a967bf84815504b2bd4eaf911705d4982b27db0253eb644e09e8cfd337a1d9087addba856aeed5fbd5c713740e661e5c5f6efaf641310c96c470714f36e0d4a518f0662b54e76dcce6d553b4cda80d173cde3fe93d5591e9d23d645fc9add3ca289ba997cb9268b9c17f0fb41b10e66539becee95f58409c0c65e125768bc8df42ea12ccb5879')   # movement record byte substitution, cipher -> plain
V5 = {0: 0.99244, 1: 0.96423, 2: 2.6283, 3: 1.21461, 4: 2.69389, 5: 2.67777, 6: 2.75567, 7: 4.07101, 8: 2.84625, 9: 2.96833, 10: 3.76961, 11: 1.59941, 12: 1.72865, 13: 2.29203, 14: 2.14738, 15: 1.68718, 16: 1.49479, 17: 1.97127, 18: 1.91285, 19: 1.04486, 20: 2.68361, 21: 1.30626, 22: 1.95473, 23: 1.83899, 24: 1.38926, 25: 1.79608, 26: 1.64566, 27: 2.75377, 28: 1.24987, 29: 1.22691, 30: 2.45938, 31: 1.7913, 32: 1.24416, 33: 2.08861, 34: 3.60904, 35: 3.26637, 36: 3.88285, 37: 2.43834, 38: 1.17434, 39: 1.38713, 40: 1.12313, 41: 1.56858, 42: 1.34275, 43: 1.99112, 44: 3.77012, 45: 1.12482, 46: 1.45439, 47: 3.82127, 48: 1.49496, 49: 1.40935, 50: 3.47277, 51: 1.08489, 52: 2.49006, 53: 1.16334, 54: 3.27619, 55: 2.35399, 56: 3.23038, 57: 3.91898, 58: 1.16506, 59: 1.74664, 60: 1.55533, 61: 3.40343, 62: 2.74054, 63: 0.96628, 64: 1.52571, 65: 1.62642, 66: 2.58247, 67: 3.9746, 68: 1.50561, 69: 1.81279, 70: 3.78485, 71: 1.84722, 72: 3.45651, 73: 2.00195, 74: 1.22493, 75: 1.74159, 76: 2.25008, 77: 1.08095, 78: 2.61116, 79: 1.42175, 80: 2.0026, 81: 2.20776, 82: 2.66845, 83: 2.79832, 84: 3.31475, 85: 2.35998, 86: 3.15475, 87: 1.26173, 88: 1.11384, 89: 2.28378, 90: 2.05553, 91: 1.47219, 92: 3.56632, 93: 2.65862, 94: 4.08901, 95: 3.69639, 96: 2.15482, 97: 3.2715, 98: 3.8313, 99: 1.64475, 100: 1.59613, 101: 1.73961, 102: 1.42096, 103: 2.08205, 104: 2.09476, 105: 1.34145, 106: 1.66004, 107: 1.82177, 108: 3.29863, 109: 1.69952, 110: 2.78585, 111: 2.50042, 112: 2.67689, 113: 3.08521, 114: 2.20478, 115: 2.5878, 116: 1.36803, 117: 1.70019, 118: 1.41713, 119: 2.04416, 120: 3.44246, 121: 1.16475, 122: 1.48643, 123: 1.6615, 124: 2.75415, 125: 3.67954, 126: 2.26808, 127: 2.27816, 128: 1.71373, 129: 2.75782, 130: 2.60967, 131: 1.55453, 132: 1.66962, 133: 1.02813, 134: 1.83045, 135: 1.36829, 136: 3.27992, 137: 4.26791, 138: 1.06355, 139: 1.91134, 140: 0.95808, 141: 3.95976, 142: 3.67662, 143: 4.01625, 144: 1.57287, 145: 1.49156, 146: 3.33214, 147: 3.91247, 148: 2.60253, 149: 1.63617, 150: 3.70305, 151: 2.0401, 152: 1.40221, 153: 3.18593, 154: 2.60224, 155: 2.88662, 156: 3.11252, 157: 3.32368, 158: 1.16618, 159: 1.9525, 160: 2.04645, 161: 4.11021, 162: 3.52291, 163: 3.41221, 164: 3.31733, 165: 1.4644, 166: 2.3684, 167: 2.62049, 168: 1.73656, 169: 1.968, 170: 1.06706, 171: 2.18309, 172: 2.34341, 173: 3.37621, 174: 3.63669, 175: 1.37185, 176: 2.95017, 177: 2.86488, 178: 1.576, 179: 1.0837, 180: 1.87634, 181: 1.76471, 182: 2.15517, 183: 1.66403, 184: 1.77537, 185: 1.13597, 186: 1.38154, 187: 1.37792, 188: 1.39034, 189: 2.3661, 190: 1.39685, 191: 2.9618, 192: 1.98736, 193: 1.65302, 194: 1.74985, 195: 1.7763, 196: 3.53079, 197: 2.44821, 198: 1.53107, 199: 2.23073, 200: 1.33419, 201: 2.4181, 202: 3.03713, 203: 3.14022, 204: 2.0015, 205: 1.41485, 206: 1.04041, 207: 2.18042, 208: 1.91424, 209: 4.25205, 210: 2.05959, 211: 2.64407, 212: 3.3603, 213: 1.92737, 214: 2.76978, 215: 1.33297, 216: 1.70819, 217: 3.58633, 218: 2.03507, 219: 1.83374, 220: 2.77871, 221: 3.55708, 222: 1.20787, 223: 1.51829, 224: 2.92133, 225: 1.35923, 226: 3.70653, 227: 3.65212, 228: 1.33084, 229: 2.01042, 230: 2.53852, 231: 1.28954, 232: 1.30595, 233: 1.24856, 234: 1.91241, 235: 3.69928, 236: 3.18368, 237: 3.60274, 238: 2.58293, 239: 3.03854, 240: 3.25307, 241: 3.25357, 242: 1.08245, 243: 1.07306, 244: 3.32475, 245: 1.6351, 246: 1.31399, 247: 1.13424, 248: 3.09634, 249: 1.47496, 250: 2.21211, 251: 1.1232, 252: 3.41543, 253: 1.0229, 254: 3.73208, 255: 1.98863}   # damage amount: byte 5 -> multiplier
SPELLS = {"Jax":{"3b8e7b":"W","2d8e7b":"Q","8c8e7b":"E","3a8e7b":"R"},"JarvanIV":{"2b03d7":"Q","f1aa45":"E","e9382f":"W","3fd49e":"R"},"Vladimir":{"adaf1d":"Q","38af1d":"E","e1638f":"W","2b01f4":"R"},"Jhin":{"befdc6":"Q","fbfdc6":"W","7afdc6":"E","f10120":"R","31fdc6":"R"},"Alistar":{"7a8ee6":"Q","07336c":"E","f7e69e":"W","8b56d1":"R"},"Sion":{"be4357":"-","7a4357":"E","fb4357":"W","2b6cc8":"W","314357":"Q","f7c699":"R"},"Lillia":{"2d0143":"Q","07b943":"E","3b0143":"W","3a0143":"R"},"Garen":{"be9c00":"Q","7a9c00":"E","8b24c6":"E","fb9c00":"W","319c00":"R"},"Ezreal":{"beb300":"Q","7ab300":"E","fbb300":"W","31b300":"R"},"Karma":{"c239a2":"E","d4f000":"Q","38ad92":"R","bb3830":"W"},"Tryndamere":{"2bbe85":"E","9cbe57":"-","d4be85":"Q","7dbe85":"W","13e3bc":"R"},"Ekko":{"85bb54":"Q","13bb54":"E","bc2456":"-","20bb54":"W","00bb54":"R"},"Jinx":{"2d24bb":"Q","3b24bb":"W","7ad1aa":"-","8c24bb":"E","3a24bb":"R"},"Thresh":{"d461e9":"Q","0370f1":"-","7d61e9":"W","9961e9":"E","38e28c":"R","e723af":"Q"},"Khazix":{"fbe892":"Q","d47322":"Q","7d7322":"W","997322":"E","fbe805":"W","967322":"R","018ff4":"Q","01bb73":"Q"},"Teemo":{"002fec":"R","852fec":"Q","202fec":"W"},"MissFortune":{"22f7de":"Q","3e878a":"W","c2d72e":"E","994d93":"R","f11de6":"W"},"Leona":{"aa3b57":"Q","96157a":"W","7a0896":"E","8c78e3":"R"},"Aatrox":{"e64dd0":"Q","07a271":"E","8ea271":"-","70318c":"-","3e318c":"-","e3a271":"W","e2a271":"R"},"LeeSin":{"070139":"Q","92e7dd":"Q","07015e":"E","079243":"W","926224":"W","92e7fe":"E","bfe73a":"R"},"Akali":{"d48989":"Q","2b0789":"E","7d8989":"W","3101fd":"E","968989":"R","0085fd":"R","33a5c8":"-"},"Karthus":{"85615b":"Q","99c639":"E","e29900":"-","79b39c":"W","d3ad2e":"R","e228c2":"R","3afe5e":"W"},"MonkeyKing":{"ca39be":"Q","4d2e08":"E","30ce9c":"W","5e7c3a":"R","2b00d3":"R"},"Malzahar":{"8e7c56":"Q","e37c56":"W","077c56":"E","e27c56":"R"},"Caitlyn":{"1d2b48":"Q","2e2b48":"W","132b48":"E","ad6bca":"-","152b48":"R"},"Mordekaiser":{"be489c":"Q","7a489c":"E","fb489c":"W","31489c":"R"},"Zyra":{"7d8e2f":"W","d48e2f":"Q","2ba12f":"E","968e2f":"R"},"Lucian":{"73b320":"Q","d3b320":"E","f0b320":"W","bfb320":"R","993bce":"R"},"Milio":{"13fd62":"E","85fd62":"Q","20fd62":"W","00fd62":"R","8f40e9":"W"},"Belveth":{"2d9cb4":"Q","bb3126":"-","3b9cb4":"W","8c9cb4":"E","3a9cb4":"R"},"Morgana":{"2e7d7c":"W","1d7d7c":"Q","d3897c":"E","157d7c":"R"},"Zac":{"99fe90":"-","f0fe90":"W","73fe90":"Q","bffe90":"E"},"Yasuo":{"13f200":"E","02782d":"-","70caa1":"Q","3843ca":"-","bfcaa1":"Q","e2caa1":"Q","7043ca":"-","3e43ca":"-"},"Twitch":{"b84a36":"W","7af333":"E","f4963b":"Q","f4e362":"R"},"Yone":{"1d30d4":"Q","c69c3d":"W","2e30d4":"E","d330d4":"Q","1530d4":"R"},"Cassiopeia":{"13aa9a":"E","739e9a":"Q","f09e9a":"W","bf9e9a":"R"},"Blitzcrank":{"bbfef4":"E","074354":"W","31b8d3":"Q","8ffc3d":"R","48f058":"Q"},"Poppy":{"d4b38a":"Q","481bc2":"-","2b268a":"E","7db38a":"W","96b38a":"-","c2d0fc":"R","481be6":"R"},"Viego":{"208be4":"-","858be4":"Q","138be4":"E","008be4":"R","f171d7":"E","be4357":"W","7da1e2":"E","fbe892":"E"},"Xayah":{"2d26f4":"Q","8c26f4":"E","3b26f4":"W","3a26f4":"R"},"Bard":{"058ebf":"W","1b2ebc":"-","388ebf":"Q","ad8ebf":"E","8bde33":"-","708ebf":"R"},"Viktor":{"2b35dd":"E","8535dd":"Q","2035dd":"W","7afcd0":"R","0035dd":"R"},"Yunara":{"2b8ee2":"E","7da1e2":"W","d4a1e2":"Q","9692bf":"E","bfd4bf":"W","96a1e2":"R"},"Yuumi":{"2b7d3e":"E","d42f3e":"Q","992daf":"-","f636e4":"-","7d2f3e":"W","8f87d4":"-","f636a4":"-","70b57c":"W"},"Kayle":{"d307f6":"E","1d07f6":"Q","2e07f6":"W","8bf6ca":"-","1507f6":"R"},"Janna":{"99c2dd":"Q","4fa433":"E","222ba2":"W","e6e69e":"R"},"Pantheon":{"befcaf":"-","fd7805":"Q","fbfcaf":"W","992392":"-","7afcaf":"Q","4ff6dd":"E","24ceec":"Q","31fcaf":"R"},"Nocturne":{"312de1":"Q","bf3af1":"E","e940f2":"W","38f285":"R","3a891b":"R"},"Galio":{"85fdfd":"Q","20fdfd":"-","13fdfd":"E","15ed43":"W","00fdfd":"R"},"Aphelios":{"2e3fdd":"W","af24e8":"Q","1d1356":"Q","7a78e9":"Q","2d03c6":"-","d4ce3f":"-","d49c19":"Q","38b33d":"R"},"Velkoz":{"85a543":"Q","20a543":"W","2ba543":"E","991c66":"Q","00a543":"R"},"Fiora":{"d4be1d":"Q","2bc81d":"E","7dbe1d":"W","96be1d":"R"},"KogMaw":{"8addb5":"R","2b857f":"E","8cf4a4":"-","8e2ddb":"Q","13befc":"W"},"Samira":{"2d8ea1":"Q","634f4a":"-","8f5b10":"-","07a1a1":"E","3b8ea1":"W","ad6c45":"-","f6bc88":"-","addb8c":"R"},"Nautilus":{"996c22":"W","8cdb19":"E","2026ad":"Q","13bb3b":"-","2b8b43":"R"},"DrMundo":{"be1b38":"Q","8c1b38":"E","fb1b38":"W","c26c92":"W","311b38":"R"},"Ashe":{"1dd7bf":"Q","bb58f7":"W","1b71a4":"E","c658f7":"W","1558f7":"W","308cf2":"W","05106c":"R"},"Seraphine":{"1be473":"Q","1db3ad":"-","f7e94a":"-","d3b3ad":"E","f7e958":"-","9203bc":"-","2eb3ad":"W","f7e9e3":"-"},"Jayce":{"c25ee3":"Q","e3f61d":"R","9cde1d":"R","8ced56":"W","99704f":"E","e9b4ce":"Q","c2027a":"W","05891b":"E"},"Veigar":{"7a28ce":"Q","157001":"W","8fe93e":"-","63311d":"E","003845":"R"},"Zilean":{"78e4b4":"E","be2ddd":"W","fb2ddd":"Q","bbe73e":"Q","fe2862":"-","e6a262":"R","8b6ce3":"Q"},"TahmKench":{"d4333b":"Q","7d333b":"W","99333b":"E","e248f3":"R","96333b":"-","e2e7b8":"R"},"Kayn":{"be7866":"Q","7a7866":"E","051be2":"W","fb7866":"W","317866":"R","f7de2b":"R"},"Syndra":{"998ef1":"Q","f102f3":"W","3b2de2":"W","2d2de2":"Q","07b3e2":"E","d36271":"E","3a2de2":"R","adaf4f":"-"},"Tristana":{"8c4a36":"E","8ee436":"Q","e3e436":"W","e2e436":"R"},"Swain":{"fb627c":"W","be627c":"Q","7a627c":"E","3a39fd":"E","31627c":"R"},"Gnar":{"8e8e87":"Q","adec02":"-","d4e2bf":"Q","8c782f":"-","078e87":"E","7de2bf":"W","d3e2bf":"E","e28e87":"R"},"Qiyana":{"3b39e4":"W","ce1bf3":"Q","70cb2f":"Q","072fe4":"E","4d9cbb":"Q","2d39e4":"Q","3a39e4":"R"},"Yorick":{"732bf4":"Q","992bf4":"E","f02bf4":"W","15f7e4":"Q","bf2bf4":"R","31f7e4":"R"},"Graves":{"5b5bd7":"-","48071b":"Q","39aa24":"-","7a33c6":"E","1313bf":"W","f63158":"R"},"Xerath":{"788ead":"-","3a7062":"Q","00e400":"W","96dbec":"R","d32bd3":"-","7043d1":"E","bf38e2":"R"},"Kaisa":{"d461fd":"Q","7d61fd":"W","2be2fd":"E","9661fd":"R","c228f3":"Q","e630f3":"W","f140f3":"-"},"Sylas":{"99bee7":"E","f0bee7":"W","3a61dd":"Q","73bee7":"E","bfbee7":"R","2b8b43":"R","f63158":"R","bf2bf4":"R"},"Rell":{"ad89e9":"E","3889e9":"Q","f6c266":"W","b34fad":"W","7089e9":"R"},"Ambessa":{"f23fe8":"-","d4b970":"Q","2dfdca":"E","2b0170":"-","7db970":"W","3afdca":"-","96b970":"R"},"Malphite":{"19d43a":"W","ade81c":"E","e67afb":"Q","57be57":"R"},"Soraka":{"2dd1bf":"Q","3bd1bf":"W","0796bf":"E","3ad1bf":"R"},"Olaf":{"22fda1":"Q","d3e44a":"E","d1ec45":"W","ce351b":"R"},"Vex":{"2d3db2":"Q","8c3db2":"E","3b3db2":"W","3a3db2":"R","3156b4":"R"},"Lux":{"2b8a70":"E","331333":"E","f02f48":"Q","d358d3":"W","3a197b":"E","b436e4":"R"},"Taliyah":{"befdc6":"Q","7afdc6":"E","b4a21d":"W","e4664f":"R","31fdc6":"E","5efb79":"R","a1d75e":"R"},"Ahri":{"7d3a92":"W","d43a92":"Q","963a92":"R","2b2d92":"E"},"Draven":{"3d4039":"W","fb8823":"Q","f700e8":"E","f6785b":"R","f74f00":"R"},"Rakan":{"e67354":"-","fb5478":"W","e67357":"-","7a5478":"E","be5478":"Q","f6d45e":"E","315478":"R"},"Nidalee":{"31d126":"R","9939ce":"W","e9c2f7":"Q","630079":"Q","8ce7aa":"E","8c38d3":"E","cecb6b":"W"},"Lulu":{"d37d58":"E","2e7d58":"W","1d7d58":"Q","ad30f3":"-","268ab4":"-","157d58":"R"},"Locke":{"d32f15":"Q","1dc628":"Q","d3c628":"E","2ec628":"W","15c628":"R","f63adb":"W","45231d":"-"},"Talon":{"7a0378":"E","fb0378":"W","be0378":"Q","3a30ed":"-","bcf45e":"-","afa579":"-","310378":"R"},"Sett":{"38e320":"Q","ade320":"E","05e320":"W","70e320":"R"},"MasterYi":{"2b2b5e":"Q","990115":"W","8c07ca":"E","e210dd":"R"},"Varus":{"7387bf":"-","9987bf":"Q","7aeced":"E","f087bf":"W","bf87bf":"R"},"Diana":{"d439e4":"Q","f78bc8":"E","e98f78":"W","9639e4":"R"},"Trundle":{"02afe1":"Q","ade3e4":"W","2b898d":"E","e43b01":"R"},"Mel":{"38db7b":"Q","addb7b":"E","05db7b":"W","70db7b":"R"},"Sona":{"2b401c":"E","7d301c":"W","d4301c":"Q","96301c":"R"},"Gangplank":{"13d031":"E","bf1d5e":"Q","f71b19":"Q","bb791c":"-","20d031":"W","00d031":"R"},"Chogath":{"2b1956":"Q","c6791d":"E","b57d8a":"W","222d70":"R"},"Nami":{"7d2f31":"W","2b7d31":"E","d42f31":"Q","ad1d24":"-","962f31":"R"},"Annie":{"d39299":"E","31f0b3":"R","1d9299":"Q","2e9299":"W","159299":"R"},"Gwen":{"7a02af":"E","be02af":"Q","c23999":"W","fb02af":"R","3102af":"R"},"Shyvana":{"7389d8":"Q","f089d8":"W","15f678":"E","137dd8":"Q","8f05cb":"W","bf89d8":"Q","5e454d":"R","c6f678":"E"},"Zed":{"ade390":"E","38e390":"Q","05e390":"W","bf3b96":"W","70e390":"R","316b96":"R","9cfda2":"E"},"Corki":{"7062a1":"Q","ad8f5e":"R","e4d791":"E","8c8b10":"-","bf3f54":"W","bf4fec":"-","f11de6":"Q"},"XinZhao":{"e3c6d1":"W","dba1ec":"-","e2bf6c":"-","8ec6d1":"Q","d3d320":"-","e2c6d1":"R"},"Senna":{"d4fc2d":"Q","c23962":"-","7dfc2d":"W","2b362d":"E","96fc2d":"R"},"Brand":{"053900":"W","ad3900":"E","383900":"Q","703900":"R"},"Naafiri":{"1d78c2":"Q","f68ef3":"E","d392c2":"Q","1578c2":"W","2e78c2":"R"},"Aurora":{"bbfd24":"E","85bead":"Q","99c8ad":"Q","20bead":"W","00bead":"R"},"Hwei":{"2b623b":"Q","13d43b":"E","d3456b":"Q","d4d43b":"W","7dd43b":"W","20d43b":"W","85d43b":"R","96024a":"W"},"Camille":{"be5762":"Q","1524ed":"Q","fb5762":"W","ad5762":"E","3a99d0":"E","315762":"R"},"Ziggs":{"73d74a":"Q","5bec6c":"-","99d74a":"E","96313b":"-","f0d74a":"W","073957":"W","bfd74a":"R"},"Singed":{"33a53e":"Q","2efde6":"E","d3ec3f":"W","56b4af":"R"},"Zeri":{"d4e2d1":"Q","2b8ed1":"E","7de2d1":"W","96e2d1":"R"}}   # champion -> {3-byte spell id: slot}


# --------------------------------------------------------------------------
# Reading the file
# --------------------------------------------------------------------------

def read_rofl(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIOT":
        raise ValueError("not a replay file")
    md_len = struct.unpack_from("<I", data, len(data) - 4)[0]
    meta = json.loads(data[len(data) - 4 - md_len:len(data) - 4])
    sig_start = len(data) - 4 - md_len - 256
    vlen = data[0x0E]
    version = data[0x0F:0x0F + vlen].decode("ascii", "replace")
    pos = 0x0F + vlen
    hdr = 18 if data[pos + 18:pos + 22] == b"\x28\xb5\x2f\xfd" else 17
    dctx = zstandard.ZstdDecompressor()
    chunks = []
    while pos + hdr <= sig_start:
        cid, _ctype, cid2, ulen, clen = struct.unpack_from("<IBIII", data, pos)
        pos += hdr
        if clen:
            body = dctx.decompress(data[pos:pos + clen], max_output_size=ulen)
            pos += clen
        else:
            body = data[pos:pos + ulen]
            pos += ulen
        if (cid2 >> 24) & 0xFF == 1:    # the game stream
            chunks.append((cid, body))
    stats = meta.get("statsJson")
    stats = json.loads(stats) if isinstance(stats, str) else stats
    chunks.sort()
    return version, stats, [b for _, b in chunks]


def _blocks(body):
    p, t, pid, prm, n = 0, 0.0, 0, 0, len(body)
    while p < n:
        m = body[p]; p += 1
        if m & 0x80:
            t += body[p] * 0.001; p += 1
        else:
            t = struct.unpack_from("<f", body, p)[0]; p += 4
        if m & 0x10:
            ln = body[p]; p += 1
        else:
            ln = struct.unpack_from("<I", body, p)[0]; p += 4
        if not m & 0x40:
            pid = struct.unpack_from("<H", body, p)[0]; p += 2
        if m & 0x20:
            prm = (prm + struct.unpack_from("<b", body, p)[0]) & 0xFFFFFFFF; p += 1
        else:
            prm = struct.unpack_from("<I", body, p)[0]; p += 4
        yield t, pid, prm, body[p:p + ln]
        p += ln


def _amount(b):
    if len(b) < 6 or b[4] not in BASE:
        return 0.0
    return BASE[b[4]] * V5.get(b[5], 2.0)


def _v16(h, l):
    v = (T871[h] << 8) | T871[l]
    return v - 65536 if v >= 32768 else v


def decode(path, until=900.0):
    """One pass over the replay: hits on champions, casts, level-ups and positions up to `until` seconds."""
    version, stats, chunks = read_rofl(path)
    skins = [p.get("SKIN") for p in stats]
    hits, casts, levels = [], [], []
    tracks = {}
    for body in chunks:
        for t, netid, param, pl in _blocks(body):
            if t > until:
                break
            if netid == 393 and param in CHAMPS:          # damage landed on a champion
                b = bytes(pl)
                atk = None
                for o in range(4, len(b) - 3):
                    if b[o + 1] == 0x39 and b[o + 3] == 0x42 and b[o] in ATK and b[o + 2] in TGT:
                        atk = ATK.index(b[o])
                        break
                hits.append((t, CHAMPS.index(param), atk, _amount(b)))
            elif netid == 1131 and param in CHAMPS:       # ability cast
                b = bytes(pl)
                q = b.find(CAST_MARK)
                k = CHAMPS.index(param)
                slot = SPELLS.get(skins[k], {}).get(b[q + 4:q + 7].hex(), "") if q >= 0 else ""
                if slot in ("Q", "W", "E", "R"):
                    casts.append((t, k, slot))
            elif netid == 12 and param in CHAMPS:         # level up
                levels.append((t, CHAMPS.index(param)))
            elif netid == 871:                            # movement order (single-waypoint entries)
                b = bytes(pl)
                if len(b) < 18 or b[-1] != 0x2C or b[-6] != 0xA5:
                    continue
                x = _v16(b[-12], b[-11]) * 2 + 7358
                z = _v16(b[-14], b[-13]) * 2 + 7412
                if not (-500 < x < 15500 and -500 < z < 15500):
                    continue
                key = POS_IDS[b[-3]] if (b[-4] == 0x3F and b[-5] == 0x3F and b[-3] in POS_IDS) else (b[-5] << 16 | b[-4] << 8 | b[-3])
                tracks.setdefault(key, []).append((round(t + 0.19, 2), round(x), round(z)))
    return dict(version=version, stats=stats, hits=hits, casts=casts, levels=levels, tracks=tracks)


# --------------------------------------------------------------------------
# Trades
# --------------------------------------------------------------------------

def lane_trades(path, me_slot, opp_slot, frames, kills):
    """frames: per minute [{t, me:[hp, max], opp:[hp, max]}] from Riot's timeline (HP anchors).
    kills: {"me": [times], "opp": [times]} from Riot's kill events. Returns the page's data for this lane."""
    d = decode(path)
    if not any(d["version"].startswith(v) for v in SUPPORTED):
        return {"unsupported": d["version"]}
    i, j = me_slot, opp_slot
    H = d["hits"]
    taken = {i: [(t, v) for t, tg, a, v in H if tg == i], j: [(t, v) for t, tg, a, v in H if tg == j]}
    ts = {k: [x[0] for x in taken[k]] for k in (i, j)}
    deaths = {i: kills.get("me") or [], j: kills.get("opp") or []}
    anchor = {i: [(f["t"], f["me"]) for f in frames if f.get("me")], j: [(f["t"], f["opp"]) for f in frames if f.get("opp")]}

    def dmg(k, a, b):
        return sum(v for _, v in taken[k][bisect.bisect_left(ts[k], a):bisect.bisect_left(ts[k], b)])

    def hp_at(k, t):
        A = anchor[k]
        if len(A) < 2:
            return 0, 1
        m = max(0, min(bisect.bisect_right([x[0] for x in A], t) - 1, len(A) - 2))
        (t0, (h0, mx0)), (t1, (h1, mx1)) = A[m], A[m + 1]
        nxt = [x for x in deaths[k] if t <= x < t + 45]
        if nxt:   # a death is coming: HP now = damage still to be taken before it
            return max(1, min(mx0, dmg(k, t, nxt[0] + 0.05))), mx0
        if [x for x in deaths[k] if t0 <= x < t]:
            return min(h1, mx1), mx1
        heal = max(0.0, h1 - h0 + dmg(k, t0, t1))
        f = (t - t0) / max(1e-6, t1 - t0)
        mx = mx0 + (mx1 - mx0) * f
        return max(0, min(mx, h0 - dmg(k, t0, t) + heal * f)), mx

    lv = {i: sorted(t for t, k in d["levels"] if k == i), j: sorted(t for t, k in d["levels"] if k == j)}
    level = lambda k, t: sum(1 for x in lv[k] if x <= t)
    duel = sorted((t, a, v) for t, tg, a, v in H if 90 <= t <= 840 and {a, tg} == {i, j})
    others = [(t, tg, v) for t, tg, a, v in H if 90 <= t <= 840 and tg in (i, j) and a not in (i, j) and a is not None and (a < 5) != (tg < 5)]
    groups, cur = [], []
    for e in duel:
        if cur and e[0] - cur[-1][0] > 3:
            groups.append(cur); cur = []
        cur.append(e)
    if cur:
        groups.append(cur)

    def seg(L, w0, w1):
        T = [p[0] for p in L]
        a, b = bisect.bisect_left(T, w0 - 4), bisect.bisect_right(T, w1 + 2)
        return [[round(t - w0, 2), x, z] for t, x, z in L[max(0, a - 1):b + 1]]

    out = []
    for w in groups:
        t0, t1 = w[0][0], w[-1][0]
        dealt = sum(v for _, a, v in w if a == i); took = sum(v for _, a, v in w if a == j)
        if dealt + took < 60:
            continue
        hm, mm = hp_at(i, t0); ho, mo = hp_at(j, t0)
        w0, w1 = t0 - 2.5, t1 + 3.0
        ev = []
        for t, tg, a, v in H:
            if w0 <= t <= w1 and tg in (i, j) and v > 0.5:
                src = "lane" if a in (i, j) else ("champ" if a is not None else "other")
                ev.append([round(t - w0, 2), "h", "you" if tg == i else "them", src, round(v), -1 if a is None else a])
        for t, k, L in d["casts"]:
            if w0 <= t <= w1 and k in (i, j):
                ev.append([round(t - w0, 2), "c", "you" if k == i else "them", L])
        for k, who in ((i, "you"), (j, "them")):
            for t in deaths[k]:
                if w0 <= t <= w1:
                    ev.append([round(t - w0, 2), "d", who])
        ev.sort(key=lambda e: e[0])
        pos = {str(k): seg(d["tracks"][k], w0, w1) for k in range(10) if k in d["tracks"]}
        pts = [(x, z) for k in (i, j) for t, x, z in pos.get(str(k), []) if -1 <= t <= w1 - w0 + 1]
        cx = sum(p[0] for p in pts) / max(1, len(pts)); cz = sum(p[1] for p in pts) / max(1, len(pts))
        mins = []
        for key, L in d["tracks"].items():
            if isinstance(key, int) and key < 10:
                continue
            sg = seg(L, w0, w1)
            if len(sg) >= 2 and any(math.hypot(x - cx, z - cz) < 1700 for t, x, z in sg if 0 <= t <= w1 - w0):
                x0, z0 = L[0][1], L[0][2]
                mins.append({"tm": 100 if math.hypot(x0 - 1500, z0 - 1500) < math.hypot(x0 - 13300, z0 - 13300) else 200, "p": sg})
        died = [who for k, who in ((i, "you"), (j, "them")) if any(t0 - 0.5 <= x <= t1 + 8 for x in deaths[k])]
        out.append(dict(
            t0=round(t0, 1), t1=round(t1, 1), dealt=round(dealt), took=round(took), first="you" if w[0][1] == i else "them",
            lv=[level(i, t0), level(j, t0)],
            gank=round(sum(v for t, tg, v in others if t0 - 2 <= t <= t1 + 2)), died=died,
            seq=[{"w": "you" if k == i else "them", "k": L} for t, k, L in d["casts"] if k in (i, j) and t0 - 1.5 <= t <= t1 + 0.5],
            hpMe=[round(hm), round(mm)], hpOpp=[round(ho), round(mo)],
            pb=dict(w0=round(w0, 2), len=round(w1 - w0, 2), start=[round(hp_at(i, w0)[0]), round(hp_at(j, w0)[0])], ev=ev,
                    pos=pos, mins=mins[:60], c=[round(cx), round(cz)])))
    return {"version": d["version"], "champs": [[p.get("SKIN"), int(p.get("TEAM") or 0)] for p in d["stats"]],
            "mi": i, "oi": j, "trades": out}


def slot_of(stats, puuid=None, name=None, champion=None, team=None):
    """The replay's player slot for a player: by puuid, then Riot ID name, then champion + team."""
    for k, p in enumerate(stats):
        if puuid and p.get("PUUID") == puuid:
            return k
    for k, p in enumerate(stats):
        if name and str(p.get("RIOT_ID_GAME_NAME") or "").lower() == str(name).lower():
            return k
    for k, p in enumerate(stats):
        if champion and str(p.get("SKIN") or "").lower() == str(champion).lower() and (team is None or int(p.get("TEAM") or 0) == team):
            return k
    return None

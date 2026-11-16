"""
Records your League games to video, so a review can show you what you actually saw.

Off until you turn on "Record my games". It never reads the game: it watches the League
client's game state (champ select / in game / end of game, the same client connection the
app already uses) and records the screen the game is on with ffmpeg and your graphics
card's video encoder, like OBS or Outplayed do.

After the game, the recording is lined up with game time: Riot's match timeline says when
0:00 was (to about a second); for custom games, which Riot's API doesn't have, it's
estimated from when the game closed and how long it lasted, and gets better as you nudge it.

Recordings are kept for a week in Recordings/, unless you press Keep (moves them to Saved/).
ffmpeg (about 90 MB) is downloaded from its official Windows builds the first time you
turn recording on, and checked against a known checksum.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

core = sys.modules.get("custy_collector") or sys.modules["__main__"]

SETTINGS = os.path.join(core.HERE, "recording.json")
FF_DIR = os.path.join(core.HERE, "ffmpeg")
FF_EXE = os.path.join(FF_DIR, "ffmpeg.exe")
FF_URL = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
FF_SHA256 = "04861d3339c5ebe38b56c19a15cf2c0cc97f5de4fa8910e4d47e5e6404e4a2d4"
GAME_WINDOW = "League of Legends (TM) Client"
IN_GAME = ("GameStart", "InProgress", "Reconnect")
FPS = 30
END_DWELL = 5.0          # custom games: seconds on the victory screen before the game closes (a first guess)
START_LAG = 0.4          # ffmpeg's first frame comes about this long after it's started

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_lock = threading.Lock()
_state = {"recording": None, "ffmpeg": None, "proc": None}   # ffmpeg: None | {"pct": n} while downloading | {"error": ...}

# Encoders to try, best first. Each takes the frames ddagrab captures (on the graphics card).
ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "5M", "-maxrate", "8M", "-bufsize", "10M"],
    "amf": ["-c:v", "h264_amf", "-quality", "speed", "-rc", "vbr_peak", "-b:v", "5M", "-maxrate", "8M"],
    "qsv": ["-vf", "hwmap=derive_device=qsv,format=qsv", "-c:v", "h264_qsv", "-b:v", "5M", "-maxrate", "8M"],
    # No usable graphics encoder: the processor, at 720p so it stays light.
    "cpu": ["-vf", "hwdownload,format=bgra,scale=-2:720,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"],
}


# ---------------------------------------------------------------- settings and folders
def settings():
    try:
        s = json.load(open(SETTINGS))
    except Exception:
        s = {}
    s.setdefault("on", False)
    s.setdefault("days", 7)
    s.setdefault("folder", None)
    if not isinstance(s.get("bias"), dict):
        s["bias"] = {}     # custom games: game id -> how far the user nudged the estimated sync (seconds)
    return s


def save_settings(**kw):
    s = settings()
    s.update(kw)
    with open(SETTINGS, "w") as f:
        json.dump(s, f)
    return s


def root_dir():
    d = settings().get("folder") or os.path.join(os.path.expanduser("~"), "Videos", "custy coach")
    for sub in ("Recordings", "Saved"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def temp_dir():
    return os.path.join(root_dir(), "Recordings")


def saved_dir():
    return os.path.join(root_dir(), "Saved")


# ---------------------------------------------------------------- ffmpeg
def ffmpeg_ready():
    return os.path.exists(FF_EXE)


def get_ffmpeg():
    """Downloads ffmpeg once (in the background; the page shows progress)."""
    if ffmpeg_ready():
        if not settings().get("encoder"):
            threading.Thread(target=pick_encoder, daemon=True).start()
        return True
    with _lock:
        if _state["ffmpeg"] and "pct" in _state["ffmpeg"]:
            return False
        _state["ffmpeg"] = {"pct": 0}
    threading.Thread(target=_download_ffmpeg, name="ffmpeg-download", daemon=True).start()
    return False


def _download_ffmpeg():
    import hashlib
    tmp = os.path.join(core.HERE, "ffmpeg-download.zip")
    try:
        req = urllib.request.Request(FF_URL, headers={"User-Agent": "custy-coach/" + core.VERSION})
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 92_000_000)
            got = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                h.update(b)
                got += len(b)
                with _lock:
                    _state["ffmpeg"] = {"pct": min(99, round(got * 100 / total))}
        if h.hexdigest() != FF_SHA256:
            raise RuntimeError("the download didn't match ffmpeg's checksum")
        os.makedirs(FF_DIR, exist_ok=True)
        with zipfile.ZipFile(tmp) as z:
            for n in z.namelist():
                if n.endswith("/bin/ffmpeg.exe") or n.endswith("/LICENSE"):
                    with z.open(n) as src, open(os.path.join(FF_DIR, os.path.basename(n)), "wb") as dst:
                        shutil.copyfileobj(src, dst)
        with _lock:
            _state["ffmpeg"] = None
        core.log.info("Recording: ffmpeg is ready")
        pick_encoder(force=True)   # now, rather than while your first game loads
    except Exception as e:
        core.log.warning("Recording: couldn't get ffmpeg: %s", e)
        with _lock:
            _state["ffmpeg"] = {"error": str(e)}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _ff(args, **kw):
    return subprocess.run([FF_EXE, "-hide_banner", "-loglevel", "error", "-y"] + args, capture_output=True, text=True,
                          creationflags=_NO_WINDOW, **kw)


def _source(output_idx=0):
    return ["-f", "lavfi", "-i", "ddagrab=output_idx=%d:framerate=%d:draw_mouse=0" % (output_idx, FPS)]


def pick_encoder(force=False):
    """The first encoder that works on this computer, remembered (and checked again if a recording fails)."""
    s = settings()
    if s.get("encoder") in ENCODERS and not force:
        return s["encoder"]
    for name, args in ENCODERS.items():
        try:
            r = _ff(_source() + ["-frames:v", "5"] + args + ["-f", "null", "-"], timeout=30)
        except Exception:
            continue
        if r.returncode == 0:
            save_settings(encoder=name)
            core.log.info("Recording: using the %s encoder", name)
            return name
        core.log.info("Recording: %s encoder not available: %s", name, (r.stderr or "").strip()[-200:])
    return None


# ---------------------------------------------------------------- which screen the game is on
def _game_monitor():
    """Index of the monitor the game window is on (0 if unknown). None if the game window isn't open."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, GAME_WINDOW)
    if not hwnd:
        return None
    mon = u.MonitorFromWindow(hwnd, 2)   # nearest
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    u.EnumDisplayMonitors(None, None, proc(lambda m, dc, rc, lp: found.append(m) or 1), 0)
    return found.index(mon) if mon in found else 0


# ---------------------------------------------------------------- recording
def _start(game_id, info):
    enc = pick_encoder()
    if not enc:
        core.log.warning("Recording: no encoder works on this computer")
        return
    mon = _game_monitor() or 0
    stamp = time.strftime("%Y-%m-%d %H.%M")
    base = os.path.join(temp_dir(), "%s - %s" % (stamp, game_id))
    cmd = [FF_EXE, "-hide_banner", "-loglevel", "error", "-y"] + _source(mon) + ENCODERS[enc] + ["-g", str(FPS * 2), "-an", base + ".mkv"]
    t0 = time.time()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    rec = {"game": str(game_id), "base": base, "start": t0 + START_LAG, "encoder": enc, "monitor": mon,
           "championId": info.get("championId"), "queue": info.get("queue"), "platform": info.get("platform")}
    with _lock:
        _state["recording"], _state["proc"] = rec, p
    _write_meta(base, rec)
    core.log.info("Recording: started game %s (%s, screen %d)", game_id, enc, mon)


def _stop(game_length=None):
    with _lock:
        rec, p = _state["recording"], _state["proc"]
        _state["recording"], _state["proc"] = None, None
    if not rec:
        return
    rec["end"] = time.time()
    try:
        p.stdin.write(b"q")
        p.stdin.flush()
        p.wait(15)
    except Exception:
        p.kill()
    err = (p.stderr.read() or b"").decode(errors="replace").strip() if p.stderr else ""
    if err:
        core.log.info("Recording: ffmpeg said: %s", err[-300:])
    mkv, mp4 = rec["base"] + ".mkv", rec["base"] + ".mp4"
    if not os.path.exists(mkv) or os.path.getsize(mkv) < 100_000:
        core.log.warning("Recording: nothing was recorded for game %s", rec["game"])
        save_settings(encoder=None)   # try the encoders again next time
        for f in (mkv, rec["base"] + ".json"):
            try:
                os.remove(f)
            except OSError:
                pass
        return
    # mp4 with the index up front, so the page's player can jump around in it right away
    r = _ff(["-i", mkv, "-c", "copy", "-movflags", "+faststart", mp4], timeout=600)
    if r.returncode == 0 and os.path.exists(mp4):
        os.remove(mkv)
        rec["file"] = os.path.basename(mp4)
    else:
        rec["file"] = os.path.basename(mkv)
    if game_length:
        rec["length"] = game_length
    _estimate(rec)
    _write_meta(rec["base"], rec)
    core.log.info("Recording: saved game %s", rec["game"])
    threading.Thread(target=_sync_from_riot, args=(rec["base"],), daemon=True).start()


def _write_meta(base, rec):
    with open(base + ".json", "w") as f:
        json.dump(rec, f)


def _read_meta(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------- lining video time up with game time
def _estimate(rec):
    """Custom games (and until Riot's timeline is ready): 0:00 = when the game closed - its length - a few
    seconds on the victory screen, corrected by how the user nudged earlier estimates."""
    if rec.get("sync") == "riot" or not rec.get("length"):
        return
    bias = sorted(v for k, v in settings()["bias"].items() if k != rec.get("game"))
    extra = bias[len(bias) // 2] if bias else 0.0
    rec["zero"] = rec["end"] - rec["length"] - END_DWELL + extra
    rec["bias_used"] = extra
    rec["sync"] = "estimate"


def _sync_from_riot(base, tries=12):
    """Riot's match timeline says, to about a second, when 0:00 was. It's ready a few minutes after the game."""
    cfg = getattr(sys.modules.get("review"), "_cfg", {}) or {}
    for _ in range(tries):
        rec = _read_meta(base + ".json")
        if not rec or rec.get("sync") == "riot" or not cfg.get("site_url"):
            return
        if rec.get("queue") == 0:   # custom game: not in Riot's API
            return
        try:
            url = "%s/api/review/timeline?platform=%s&gameId=%s" % (cfg["site_url"].rstrip("/"), rec.get("platform") or "NA1", rec["game"])
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + cfg.get("ingest_key", ""),
                                                       "User-Agent": "custy-collector/" + core.VERSION})
            with urllib.request.urlopen(req, timeout=30) as r:
                zero = (json.loads(r.read()).get("clock") or {}).get("zero")
            if zero:
                rec.update(zero=zero / 1000.0, sync="riot")
                _write_meta(base, rec)
                core.log.info("Recording: game %s lined up with Riot's timeline", rec["game"])
                return
        except Exception as e:
            core.log.info("Recording: timeline for %s not ready (%s)", rec["game"], e)
        time.sleep(120)


def fill_length(game_id, seconds):
    """The review page knows the game's length (from match history) even if the app missed the end screen."""
    found = find(game_id)
    if found and not found[1].get("length") and seconds:
        rec = found[1]
        rec["length"] = float(seconds)
        _estimate(rec)
        _write_meta(rec["base"], rec)


# ---------------------------------------------------------------- the list, keep, delete, clip
def _all():
    out = []
    for kept, d in ((False, temp_dir()), (True, saved_dir())):
        for n in os.listdir(d):
            if n.endswith(".json"):
                rec = _read_meta(os.path.join(d, n))
                if rec:
                    rec["base"] = os.path.join(d, n[:-5])   # the folder may have moved since it was written
                    rec["kept"] = kept
                    out.append(rec)
    return out


def find(game_id):
    for rec in _all():
        if rec.get("game") == str(game_id) and rec.get("file") and os.path.exists(os.path.join(os.path.dirname(rec["base"]), rec["file"])):
            return os.path.join(os.path.dirname(rec["base"]), rec["file"]), rec
    return None


def video_offset(rec):
    """Seconds into the video where game time 0:00 is (None if not known yet)."""
    if rec.get("zero") is None:
        return None
    return rec["zero"] - rec["start"] + (rec.get("nudge") or 0.0)


def info_for(game_id):
    f = find(game_id)
    if not f:
        return {"exists": False}
    path, rec = f
    return {"exists": True, "offset": video_offset(rec), "sync": rec.get("sync"), "nudge": rec.get("nudge") or 0.0,
            "kept": rec.get("kept"), "name": os.path.basename(path), "size": os.path.getsize(path),
            "expires": None if rec.get("kept") else rec.get("end", rec["start"]) + settings()["days"] * 86400}


def nudge(game_id, delta):
    f = find(game_id)
    if not f:
        return None
    rec = f[1]
    rec["nudge"] = round((rec.get("nudge") or 0.0) + float(delta), 2)
    if rec.get("sync") == "estimate":   # learn from it for the next custom game
        if abs(rec["nudge"]) < 60:
            bias = dict(settings().get("bias") or {})   # game id -> how far it was nudged (latest 15 games)
            bias.pop(rec["game"], None)
            bias[rec["game"]] = (rec.get("bias_used") or 0.0) + rec["nudge"]   # the full correction this game needed
            save_settings(bias=dict(list(bias.items())[-15:]))
    _write_meta(rec["base"], rec)
    return info_for(game_id)


def _move(rec, dest_dir):
    src_dir = os.path.dirname(rec["base"])
    name = os.path.basename(rec["base"])
    for ext in (".mp4", ".mkv", ".json"):
        if os.path.exists(os.path.join(src_dir, name + ext)):
            shutil.move(os.path.join(src_dir, name + ext), os.path.join(dest_dir, name + ext))


def keep(game_id, on=True):
    f = find(game_id)
    if f and bool(f[1].get("kept")) != on:
        _move(f[1], saved_dir() if on else temp_dir())
        if not on:   # back in the temp folder: the week starts again from now
            meta = os.path.join(temp_dir(), os.path.basename(f[1]["base"]) + ".json")
            rec = _read_meta(meta)
            rec["end"] = time.time()
            _write_meta(meta[:-5], rec)
    return info_for(game_id)


def delete(game_id):
    f = find(game_id)
    if not f:
        return
    for ext in (".mp4", ".mkv", ".json"):
        try:
            os.remove(f[1]["base"] + ext)
        except OSError:
            pass


def clip(game_id, start, end, name, out_dir):
    """Cuts game time start..end out of the recording (no re-encoding, so it's instant; starts up to 2 s early)."""
    f = find(game_id)
    if not f:
        raise RuntimeError("There's no recording of this game.")
    path, rec = f
    off = video_offset(rec) or 0.0
    a, b = max(0.0, start + off), max(0.0, end + off)
    if b - a < 1:
        raise RuntimeError("The clip is too short.")
    name = re.sub(r"[^\w\-. ()]", "", name or "Clip").strip()[:90] or "Clip"
    out = os.path.join(out_dir, "%s (%s).mp4" % (name, time.strftime("%Y-%m-%d %H.%M.%S")))
    r = _ff(["-ss", "%.2f" % a, "-i", path, "-t", "%.2f" % (b - a), "-c", "copy", "-avoid_negative_ts", "make_zero",
             "-movflags", "+faststart", out], timeout=300)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg couldn't cut the clip: " + (r.stderr or "").strip()[-200:])
    return out


def cleanup():
    """Recordings older than the setting (7 days) go; Saved/ is never touched."""
    days = settings()["days"]
    with _lock:
        now_rec = (_state["recording"] or {}).get("base")
    for rec in _all():
        if rec.get("kept") or rec["base"] == now_rec:
            continue
        if time.time() - rec.get("end", rec.get("start", 0)) > days * 86400:
            for ext in (".mp4", ".mkv", ".json"):
                try:
                    os.remove(rec["base"] + ext)
                except OSError:
                    pass
            core.log.info("Recording: removed %s (older than %d days)", os.path.basename(rec["base"]), days)


def listing():
    out = []
    for rec in _all():
        p = os.path.join(os.path.dirname(rec["base"]), rec.get("file") or "")
        if rec.get("file") and os.path.exists(p):
            out.append({"game": rec["game"], "name": rec["file"], "size": os.path.getsize(p), "kept": rec["kept"],
                        "at": rec.get("start"), "sync": rec.get("sync"), "championId": rec.get("championId")})
    out.sort(key=lambda x: -(x["at"] or 0))
    return out


def status():
    s = settings()
    with _lock:
        rec, ff = _state["recording"], _state["ffmpeg"]
    return {"on": s["on"], "days": s["days"], "folder": root_dir(), "encoder": s.get("encoder"),
            "ffmpeg": "ready" if ffmpeg_ready() else ff or "missing",
            "recording": {"game": rec["game"], "since": rec["start"]} if rec else None, "list": listing()}


# ---------------------------------------------------------------- the watcher
def _session(lcu):
    """Game id, queue and your champion from the client, when a game starts."""
    try:
        s = lcu.get("/lol-gameflow/v1/session") or {}
        gd = s.get("gameData") or {}
        info = {"queue": (gd.get("queue") or {}).get("id"), "platform": (lcu.get("/lol-platform-config/v1/namespaces/LoginDataPacket/platformId") or None)}
        try:
            me = lcu.get("/lol-summoner/v1/current-summoner") or {}
            for p in (gd.get("teamOne") or []) + (gd.get("teamTwo") or []):
                if p.get("puuid") == me.get("puuid"):
                    info["championId"] = p.get("championId")
        except Exception:
            pass
        return gd.get("gameId"), info
    except Exception:
        return None, {}


def watch(cfg, stop, lcu_for):
    """Runs with the app: starts recording when a game starts (if turned on), stops when it ends."""
    last_clean = 0
    pending_len = None
    while not stop.is_set():
        try:
            if time.time() - last_clean > 3600:
                last_clean = time.time()
                cleanup()
            with _lock:
                rec = _state["recording"]
            lcu = lcu_for(cfg)
            phase = lcu.get("/lol-gameflow/v1/gameflow-phase") if lcu else None
            if rec is None and phase in IN_GAME and settings()["on"] and ffmpeg_ready():
                game_id, info = _session(lcu)
                if game_id and _game_monitor() is not None and not find(game_id):
                    _start(game_id, info)
            elif rec is not None and phase not in IN_GAME and (phase is not None or _game_monitor() is None):
                if phase in ("PreEndOfGame", "EndOfGame", "WaitingForStats"):
                    try:   # the game's length, from the end-of-game screen
                        eog = lcu.get("/lol-end-of-game/v1/eog-stats-block") or {}
                        if str(eog.get("gameId")) == rec["game"]:
                            pending_len = eog.get("gameLength")
                    except Exception:
                        pass
                _stop(pending_len)
                pending_len = None
        except Exception as e:
            core.log.info("Recording: %s", e)
        stop.wait(2)
    _stop()

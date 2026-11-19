"""Account rotation for expert downloads (for a spare PC with several League accounts).

League lets each account download about 10 replays an hour. With rotation on, the app signs into one account,
lets the expert downloader pull that account's quota, signs out and moves straight to the next account that has
quota left. No fixed timer: it switches as soon as the account is done (quota sent, League's limit hit, or no
games to fetch). When every account is used up, it waits only until the first one frees up.

Passwords are encrypted with Windows' own per-user protection (DPAPI) and stay in rotation.json on this PC; they
are never sent anywhere. Sign-in is done the way a person does it: the Riot Client's sign-in screen, typed. If a
captcha or any other problem stops the sign-in, that account is skipped and marked "needs you"; nothing tries to
get around a captcha.

Never runs while a game is on. Off by default.
"""
import base64
import ctypes
import urllib.error
import json
import os
import subprocess
import threading
import time

import sys

core = sys.modules.get("custy_collector") or sys.modules["__main__"]   # log, HERE

ROT_FILE = os.path.join(core.HERE, "rotation.json")
ROT_STATE = os.path.join(core.HERE, "rotation-state.json")
PER_ACCOUNT = 10
SIGNIN_TIMEOUT = 120        # seconds from typing the password to League being up
ACCOUNT_CAP = 25 * 60       # at most this long on one account, whatever happens
NO_GAMES_GIVE_UP = 5 * 60   # no games to fetch for this long: move on
_lock = threading.Lock()
_rot = {"state": "off", "message": "Off.", "account": None}
_cur = {"user": None, "since": 0, "sent": 0, "limited": False, "idle_since": None}


# --------------------------------------------------------------------------- settings and per-account state
def settings():
    try:
        s = json.load(open(ROT_FILE))
    except Exception:
        s = {}
    s.setdefault("on", False)
    s.setdefault("per_account", PER_ACCOUNT)
    s.setdefault("accounts", [])
    return s


def save(s):
    with _lock:
        with open(ROT_FILE, "w") as f:
            json.dump(s, f, indent=1)


def _state():
    try:
        return json.load(open(ROT_STATE))
    except Exception:
        return {}


def _state_save(st):
    with _lock:
        with open(ROT_STATE, "w") as f:
            json.dump(st, f, indent=1)


def _acct(st, user):
    a = st.setdefault(user, {})
    a.setdefault("ok", [])          # when each of its downloads worked
    a["ok"] = [t for t in a["ok"] if time.time() - t < 2 * 86400]
    return a


def public_status():
    """For the app's settings page: accounts without passwords, plus each one's state."""
    s, st = settings(), _state()
    rows = []
    for a in s["accounts"]:
        x = _acct(st, a["user"])
        hour = sum(1 for t in x["ok"] if time.time() - t < 3600)
        day = sum(1 for t in x["ok"] if time.time() - t < 86400)
        rows.append({"user": a["user"], "riotId": x.get("riotId"), "lastHour": hour, "lastDay": day,
                     "limitedUntil": x.get("limited_until", 0), "needsYou": x.get("needs_you"),
                     "lastError": x.get("last_error"), "current": _cur["user"] == a["user"]})
    return {"on": s["on"], "perAccount": s["per_account"], "accounts": rows, **_rot}


# --------------------------------------------------------------------------- passwords (Windows DPAPI)
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(text):
    raw = text.encode("utf-8")
    buf = ctypes.create_string_buffer(raw, len(raw))   # kept alive for the call
    src = _Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("couldn't encrypt the password")
    data = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return base64.b64encode(data).decode()


def _unprotect(b64):
    raw = base64.b64decode(b64)
    buf = ctypes.create_string_buffer(raw, len(raw))
    src = _Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("couldn't decrypt the password (was it saved by another Windows user?)")
    data = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return data.decode("utf-8")


def add_account(user, password):
    s = settings()
    s["accounts"] = [a for a in s["accounts"] if a["user"].lower() != user.lower()]
    s["accounts"].append({"user": user, "pw": _protect(password)})
    save(s)


def remove_account(user):
    s = settings()
    s["accounts"] = [a for a in s["accounts"] if a["user"].lower() != user.lower()]
    save(s)


# --------------------------------------------------------------------------- hooks used by the expert downloader
def active():
    return settings()["on"] and _cur["user"] is not None


def quota():
    """(downloads this account made in the last hour, its quota) while rotation is driving, else None."""
    if not active():
        return None
    a = _acct(_state(), _cur["user"])
    return [t for t in a["ok"] if time.time() - t < 3600], settings()["per_account"]


def note(result):
    """The downloader tells us how each download went: "watch" (worked), "maxLimitReached", or "nogames"."""
    user = _cur["user"]
    if not user:
        return
    st = _state()
    a = _acct(st, user)
    if result == "watch":
        a["ok"].append(time.time())
        _cur["sent"] += 1
        _cur["idle_since"] = None
    elif result == "maxLimitReached":
        a["limited_until"] = time.time() + 3600
        _cur["limited"] = True
    elif result == "nogames":
        _cur["idle_since"] = _cur["idle_since"] or time.time()
    _state_save(st)


# --------------------------------------------------------------------------- Riot Client control
def _riot_client_paths():
    paths = []
    try:
        inst = json.load(open(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Riot Games", "RiotClientInstalls.json")))
        paths += [inst.get(k) for k in ("rc_default", "rc_live") if inst.get(k)]
    except Exception:
        pass
    paths.append(r"C:\Riot Games\Riot Client\RiotClientServices.exe")
    return [p for p in paths if p and os.path.exists(p)]


def _rc_api(method, path, body=None):
    """Riot Client's local API (lockfile in %LOCALAPPDATA%). Returns (status, json or None)."""
    import ssl
    import urllib.request
    lf = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
    try:
        _name, _pid, port, pw, proto = open(lf).read().strip().split(":")
    except Exception:
        return None, None
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("%s://127.0.0.1:%s%s" % (proto, port, path), method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Basic " + base64.b64encode(("riot:" + pw).encode()).decode(),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def _kill_league_and_client():
    for exe in ("LeagueClient.exe", "LeagueClientUx.exe", "LeagueClientUxRender.exe", "RiotClientServices.exe",
                "Riot Client.exe", "RiotClientUx.exe", "RiotClientUxRender.exe"):
        subprocess.run(["taskkill", "/f", "/im", exe], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def sign_out():
    """Signs the Riot Client out (so the next start shows the sign-in screen) and closes League."""
    for path in ("/rso-auth/v1/session", "/riot-login/v1/session"):
        code, _ = _rc_api("DELETE", path)
        if code and code < 300:
            core.log.info("Rotation: signed out (%s).", path)
            break
    time.sleep(3)
    _kill_league_and_client()
    time.sleep(5)


def _riot_client_window():
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith("Riot Client"):
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def _focus(hwnd):
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)                    # restore
    user32.keybd_event(0x12, 0, 0, 0)             # a tap of Alt lets this app bring a window forward
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    return user32.GetForegroundWindow() == hwnd


class _KI(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _IN(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def _key(vk=0, scan=0, flags=0):
    i = _IN(type=1)
    i.ki = _KI(vk, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))


def _type(text):
    for ch in text:   # KEYEVENTF_UNICODE: any character, independent of keyboard layout
        _key(0, ord(ch), 0x0004); _key(0, ord(ch), 0x0004 | 0x0002)
        time.sleep(0.02)


def _press(vk):
    _key(vk); _key(vk, 0, 0x0002)
    time.sleep(0.05)


def sign_in(user, password, lcu_up):
    """Starts the Riot Client, types the account into its sign-in screen and waits for League.
    lcu_up() -> current summoner dict or None. Returns (ok, riot_id or reason)."""
    paths = _riot_client_paths()
    if not paths:
        return False, "Riot Client not found"
    subprocess.Popen([paths[0], "--launch-product=league_of_legends", "--launch-patchline=live"],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    hwnd = None
    for _ in range(60):
        time.sleep(1)
        me = lcu_up()
        if me:   # signed in by itself ("Stay signed in" was ticked for some account): not who we want
            return False, "signed in automatically as %s; untick 'Stay signed in'" % me.get("riotId")
        hwnd = _riot_client_window()
        if hwnd:
            break
    if not hwnd:
        return False, "Riot Client sign-in window didn't appear"
    time.sleep(6)   # let the sign-in page load
    if not _focus(hwnd):
        return False, "couldn't bring the Riot Client to the front (is the PC locked?)"
    _type(user); _press(0x09)          # username, Tab
    _type(password); _press(0x0D)      # password, Enter
    t0 = time.time()
    while time.time() - t0 < SIGNIN_TIMEOUT:
        time.sleep(3)
        me = lcu_up()
        if me:
            return True, me.get("riotId")
    return False, "didn't get into League within %d s (captcha, wrong password, or a Riot prompt)" % SIGNIN_TIMEOUT


# --------------------------------------------------------------------------- the rotation loop
def _pick(s, st, exclude=None):
    """Next account with quota left, in list order after the current one. (account, wait_seconds)."""
    accts = [a for a in s["accounts"] if not _acct(st, a["user"]).get("needs_you")]
    if not accts:
        return None, 600
    start = 0
    if exclude:
        idx = [i for i, a in enumerate(accts) if a["user"] == exclude]
        start = (idx[0] + 1) if idx else 0
    order = accts[start:] + accts[:start]
    soonest = None
    for a in order:
        x = _acct(st, a["user"])
        hour = sorted(t for t in x["ok"] if time.time() - t < 3600)
        free_at = max(x.get("limited_until", 0), (hour[0] + 3600) if len(hour) >= s["per_account"] else 0)
        if free_at <= time.time():
            return a, 0
        soonest = free_at if soonest is None else min(soonest, free_at)
    return None, max(30, soonest - time.time())


def run(stop, lcu_up, playing):
    """Background thread. lcu_up() -> {"riotId"} or None; playing() -> True while a game is on."""
    fails = 0
    while not stop.is_set():
        wait = 10
        try:
            s = settings()
            if not s["on"] or not s["accounts"]:
                _cur.update(user=None)
                _rot.update(state="off", message="Off." if not s["on"] else "No accounts added.", account=None)
                stop.wait(30)
                continue
            if playing():
                _rot.update(state="waiting", message="Paused while a game is on.")
                stop.wait(30)
                continue
            st = _state()
            user = _cur["user"]
            if user:
                done = (_cur["sent"] >= s["per_account"] or _cur["limited"]
                        or (_cur["idle_since"] and time.time() - _cur["idle_since"] > NO_GAMES_GIVE_UP)
                        or time.time() - _cur["since"] > ACCOUNT_CAP or not lcu_up())
                if not done:
                    _rot.update(state="working", message="On %s: %d of %d sent." % (_acct(st, user).get("riotId") or user, _cur["sent"], s["per_account"]),
                                account=user)
                    stop.wait(5)
                    continue
                why = ("quota sent" if _cur["sent"] >= s["per_account"] else "League's limit" if _cur["limited"]
                       else "no games to fetch" if _cur["idle_since"] else "signed out" if not lcu_up() else "time cap")
                core.log.info("Rotation: done with %s (%d sent, %s).", user, _cur["sent"], why)
            acct, wait_s = _pick(s, st, exclude=user)
            if not acct:
                _rot.update(state="waiting", message="Every account has used its hour. Next one frees up in about %d min." % max(1, wait_s // 60),
                            next_at=time.time() + wait_s, account=user)
                stop.wait(min(wait_s, 300))
                continue
            if acct["user"] == user and lcu_up():   # only one account has quota: stay on it
                _cur.update(since=time.time(), sent=0, limited=False, idle_since=None)
                continue
            _cur.update(user=None)
            _rot.update(state="switching", message="Signing out%s..." % (" of " + user if user else ""))
            sign_out()
            _rot.update(state="switching", message="Signing in to %s..." % acct["user"], account=acct["user"])
            ok, info = sign_in(acct["user"], _unprotect(acct["pw"]), lcu_up)
            st = _state(); x = _acct(st, acct["user"])
            if ok:
                fails = 0
                x.update(riotId=info, last_error=None, needs_you=None, last_signin=time.time())
                _state_save(st)
                _cur.update(user=acct["user"], since=time.time(), sent=0, limited=False, idle_since=None)
                core.log.info("Rotation: signed in to %s (%s).", acct["user"], info)
                _rot.update(state="working", message="On %s." % (info or acct["user"]), account=acct["user"])
            else:
                fails += 1
                x.update(last_error=info, needs_you=time.time())
                _state_save(st)
                core.log.info("Rotation: couldn't sign in to %s: %s", acct["user"], info)
                _rot.update(state="error", message="Couldn't sign in to %s: %s" % (acct["user"], info))
                if fails >= 3:
                    s["on"] = False; save(s)
                    _rot.update(state="off", message="Turned off after 3 failed sign-ins in a row. Last: %s" % info)
                    core.log.info("Rotation: turned off after 3 failed sign-ins in a row.")
                wait = 20
        except Exception as e:
            core.log.info("Rotation: %s", e)
            _rot.update(state="error", message=str(e)[:200])
            wait = 60
        stop.wait(wait)

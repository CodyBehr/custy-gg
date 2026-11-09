"""
One-click install for the packaged Windows app (custy-collector.exe).

Double-clicking the downloaded .exe:
  - copies it to %LOCALAPPDATA%\\custy-collector\\custy-collector.exe
  - registers it to start when you log in to Windows (HKCU Run key)
  - starts it in the background and shows a short confirmation
Running the download again offers to update or remove it.
The installed copy runs the collector with a tray icon (bottom-right of the
taskbar) for opening the site, pausing, and quitting. One copy at a time.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
import winreg

core = sys.modules["__main__"]  # custy_collector, which imported us

APP = "custy-collector"
INSTALL_EXE = os.path.join(core.HERE, APP + ".exe")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

MB_OK, MB_YESNOCANCEL = 0x0, 0x3
MB_ICONERROR, MB_ICONQUESTION, MB_ICONINFO = 0x10, 0x20, 0x40
MB_TOPMOST = 0x40000 | 0x10000
IDYES, IDNO = 6, 7

_mutex = None


def message(text, flags=MB_OK | MB_ICONINFO):
    return ctypes.windll.user32.MessageBoxW(None, text, "custy.gg collector", flags | MB_TOPMOST)


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def already_running():
    """Takes a per-user lock; returns True if another copy already holds it."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\" + APP)
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def powershell(command):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def stop_running_copies():
    """Stops the installed app and the older Python version of the collector."""
    target = INSTALL_EXE.replace("'", "''")
    powershell(
        "Get-CimInstance Win32_Process | Where-Object { "
        f"$_.ProcessId -ne {os.getpid()} -and ($_.ExecutablePath -eq '{target}' -or "
        "$_.CommandLine -like '*custy_collector.py*') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    time.sleep(1.5)


def remove_old_python_autostart():
    startup = powershell("[Environment]::GetFolderPath('Startup')") or os.path.join(
        os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
    try:
        os.remove(os.path.join(startup, APP + ".vbs"))
    except OSError:
        pass


def set_autostart(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, f'"{INSTALL_EXE}"')
        else:
            try:
                winreg.DeleteValue(key, APP)
            except FileNotFoundError:
                pass


def start_installed():
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # let the new copy unpack itself fresh
    subprocess.Popen([INSTALL_EXE], cwd=core.HERE, env=env, creationflags=DETACHED, close_fds=True)


def install(source):
    stop_running_copies()
    remove_old_python_autostart()
    os.makedirs(core.HERE, exist_ok=True)
    for attempt in range(10):
        try:
            shutil.copy2(source, INSTALL_EXE)
            break
        except OSError:
            if attempt == 9:
                raise
            time.sleep(1)
    set_autostart(True)
    start_installed()


def uninstall():
    stop_running_copies()
    set_autostart(False)
    remove_old_python_autostart()
    try:
        os.remove(REVIEW_SHORTCUT)
    except OSError:
        pass
    shutil.rmtree(core.HERE, ignore_errors=True)


def status_line(cfg):
    """One or two sentences about whether League and the site are reachable."""
    lines = []
    try:
        cfg = dict(cfg)
        cfg.setdefault("league_path", "")
        creds = core.find_client(cfg)
        if creds:
            me = core.current_player(core.LeagueClient(*creds))
            if me.get("gameName"):
                lines.append(f"League is open and you're logged in as {me['gameName']}#{me.get('tagLine', '')}. "
                             "Custom games still in your recent history are being uploaded now.")
        if not lines:
            lines.append("League isn't open right now. That's fine: it will notice whenever you play.")
    except Exception:
        lines.append("It will notice League whenever you play.")
    try:
        code, _ = core.check_site({"site_url": cfg["site_url"].rstrip("/"), "ingest_key": cfg["ingest_key"]})
        if code != 200:
            lines.append(f"Warning: couldn't reach {cfg['site_url']} just now (HTTP {code}). "
                         "It will keep trying in the background.")
    except Exception:
        pass
    return "\n\n".join(lines)


def open_review():
    """Opens the game review window, starting the installed app first if it isn't running."""
    import review
    url = review.running_url()
    if not url and os.path.exists(INSTALL_EXE):
        start_installed()
        for _ in range(40):
            time.sleep(0.5)
            url = review.running_url()
            if url:
                break
    if url:
        review.open_window(url)
    else:
        message("Couldn't start custy.gg game review. Try again in a few seconds.", MB_OK | MB_ICONERROR)


REVIEW_SHORTCUT = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs",
                               "custy.gg game review.lnk")


def make_review_shortcut():
    """Start menu entry that opens the game review window."""
    if os.path.exists(REVIEW_SHORTCUT) or not os.path.exists(INSTALL_EXE):
        return
    lnk, exe = REVIEW_SHORTCUT.replace("'", "''"), INSTALL_EXE.replace("'", "''")
    powershell(
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
        "$s.TargetPath = '%s'; $s.Arguments = '--review'; $s.IconLocation = '%s,0'; "
        "$s.Description = 'Review your recent League games'; $s.Save()" % (lnk, exe, exe))


def handle_launch(args):
    """Returns True when this process should go on to run the collector."""
    me = sys.executable

    if "--review" in args:
        open_review()
        return False

    if "--uninstall" in args:
        uninstall()
        message("custy.gg collector has been removed from this PC.")
        return False

    if same_path(me, INSTALL_EXE):
        if already_running():
            return False
        _after_update()
        return True

    cfg = core.embedded_config(me)
    if "--update" in args and cfg:
        # Launched by the running app after it downloaded a newer version: install quietly.
        try:
            install(me)
            _write_json(UPDATED_FLAG, {"version": core.VERSION})
        except Exception:
            pass
        return False
    if not cfg:
        message("This copy of the collector isn't linked to a site.\n\n"
                "Download it again from your custy.gg site's \"Add your games\" page.", MB_OK | MB_ICONERROR)
        return False

    if os.path.exists(INSTALL_EXE):
        choice = message(
            "custy.gg collector is already installed on this PC.\n\n"
            "Yes: update it with this download\n"
            "No: remove it from this PC\n"
            "Cancel: leave it as it is",
            MB_YESNOCANCEL | MB_ICONQUESTION)
        if choice == IDNO:
            uninstall()
            message("custy.gg collector has been removed from this PC.")
            return False
        if choice != IDYES:
            return False

    try:
        install(me)
    except Exception as e:
        message(f"Couldn't install the collector: {e}\n\nClose any copy that's running and try again.",
                MB_OK | MB_ICONERROR)
        return False

    site = cfg.get("site_url", "your custy.gg site").rstrip("/")
    message(
        "custy.gg collector is installed and running.\n\n"
        "It runs in the background and starts with Windows, so there's nothing to keep open. "
        "Look for its icon next to the clock (it may be under the ^ arrow): right-click it to open the site, "
        "pause uploads or quit. "
        f"Your custom games show up on {site} about a minute after each one ends.\n\n"
        + status_line(cfg)
        + "\n\nYou can delete this download now. To remove the app later, run the download again and choose No."
    )
    return False


# --------------------------------------------------------------------------
# Tray icon: shows it's running, and lets you open the site, pause or quit.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Settings and automatic updates
# --------------------------------------------------------------------------

SETTINGS = os.path.join(core.HERE, "settings.json")
UPDATE_EXE = os.path.join(core.HERE, APP + "-update.exe")
UPDATED_FLAG = os.path.join(core.HERE, "updated.json")
UPDATE_EVERY = 15 * 60  # check every 15 minutes; one tiny request


def _read_json(path, default):
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    import json
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def auto_update_on():
    return _read_json(SETTINGS, {}).get("auto_update", True)


def set_auto_update(on):
    data = _read_json(SETTINGS, {})
    data["auto_update"] = bool(on)
    _write_json(SETTINGS, data)


def _after_update():
    """Runs when the installed app starts: tidies up after an update."""
    try:
        os.remove(UPDATE_EXE)
    except OSError:
        pass


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def check_for_update(cfg):
    """Downloads and starts a newer version if the site has one. Returns True if an update was started."""
    import json
    import urllib.request
    site = cfg["site_url"].rstrip("/")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                site + "/api/collector/version", headers={"User-Agent": "custy-collector/" + core.VERSION}), timeout=20) as r:
            latest = json.loads(r.read() or b"{}").get("version", "")
    except Exception as e:
        core.log.info("Update check failed: %s", e)
        return False
    if not latest or _version_tuple(latest) <= _version_tuple(core.VERSION):
        return False
    core.log.info("Downloading version %s (this is %s)", latest, core.VERSION)
    tmp = UPDATE_EXE + ".part"
    try:
        with urllib.request.urlopen(urllib.request.Request(
                site + "/api/collector/windows", headers={"User-Agent": "custy-collector/" + core.VERSION}), timeout=180) as r, \
                open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("download isn't a Windows app")
        if not core.embedded_config(tmp):
            raise ValueError("download isn't linked to the site")
        os.replace(tmp, UPDATE_EXE)
    except Exception as e:
        core.log.warning("Update download failed: %s", e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen([UPDATE_EXE, "--update"], cwd=core.HERE, env=env, creationflags=DETACHED, close_fds=True)
    core.log.info("Installing version %s", latest)
    return True


def _resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def _ago(ts):
    if not ts:
        return "none yet"
    mins = int((time.time() - ts) // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP)
            return True
    except OSError:
        return False


def run_with_tray(cfg, start_collector):
    """Runs the collector in a background thread with a tray icon in front."""
    import threading
    import webbrowser

    import pystray
    from PIL import Image

    stop = threading.Event()
    worker = threading.Thread(target=start_collector, args=(stop,), name="collector", daemon=True)
    status = core.STATUS
    site = cfg["site_url"].rstrip("/")

    try:
        image = Image.open(_resource("icon.ico"))
    except OSError:
        image = Image.new("RGB", (64, 64), (227, 184, 102))

    def status_text(_item=None):
        return f"Status: {status['state']}"

    def uploads_text(_item=None):
        n = status["uploaded"]
        return f"Uploaded this session: {n} game{'s' if n != 1 else ''} (last {_ago(status['last_upload'])})"

    def open_site(icon, item):
        webbrowser.open(site)

    review_url = {"url": None}
    try:
        import review
        review_url["url"] = review.start(cfg)
        threading.Thread(target=review.keep_cache_fresh, args=(cfg, stop), name="review-cache", daemon=True).start()
    except Exception as e:
        core.log.warning("Game review page didn't start: %s", e)

    def open_review_window(icon, item):
        if review_url["url"]:
            import review
            review.open_window(review_url["url"])

    def open_log(icon, item):
        try:
            os.startfile(core.LOG_PATH)
        except OSError:
            os.startfile(core.HERE)

    def toggle_pause(icon, item):
        status["paused"] = not status["paused"]
        status["state"] = "Paused" if status["paused"] else "Resuming"
        icon.update_menu()

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())
        icon.update_menu()

    def toggle_updates(icon, item):
        set_auto_update(not auto_update_on())
        icon.update_menu()

    def quit_app(icon, item):
        stop.set()
        icon.visible = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open custy.gg", open_site, default=True),
        pystray.MenuItem("Review my games (test)", open_review_window),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.MenuItem(uploads_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause uploads", toggle_pause, checked=lambda item: status["paused"]),
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Update automatically", toggle_updates, checked=lambda item: auto_update_on()),
        pystray.MenuItem("Open log", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon(APP, image, "custy.gg collector", menu)

    def on_upload(n):
        icon.title = f"custy.gg collector: {n} new game{'s' if n != 1 else ''} uploaded {_ago(time.time())}"
        try:
            icon.notify(f"Uploaded {n} custom game{'s' if n != 1 else ''} to custy.gg", "custy.gg collector")
        except Exception:
            pass

    status["on_upload"] = on_upload

    def updater():
        stop.wait(60)  # let the app settle first
        while not stop.is_set():
            if auto_update_on() and status["state"] != "In a game":
                if check_for_update(cfg):
                    stop.set()  # the new version stops this one as it installs
                    try:
                        icon.stop()
                    except Exception:
                        pass
                    return
            stop.wait(UPDATE_EVERY)

    def setup(icon):
        icon.visible = True
        threading.Thread(target=make_review_shortcut, name="shortcut", daemon=True).start()
        worker.start()
        threading.Thread(target=updater, name="updater", daemon=True).start()
        done = _read_json(UPDATED_FLAG, None)
        if done:
            try:
                os.remove(UPDATED_FLAG)
                icon.notify(f"Updated to version {done.get('version', core.VERSION)}", "custy.gg collector")
            except Exception:
                pass
        # Refresh the hover text so it says what the app is doing.
        while not stop.is_set():
            icon.title = f"custy.gg collector: {status['state'].lower()}"
            try:
                icon.update_menu()
            except Exception:
                pass
            stop.wait(10)

    icon.run(setup=setup)
    stop.set()
    worker.join(timeout=5)

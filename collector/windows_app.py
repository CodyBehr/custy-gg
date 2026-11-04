"""
One-click install for the packaged Windows app (custy-collector.exe).

Double-clicking the downloaded .exe:
  - copies it to %LOCALAPPDATA%\\custy-collector\\custy-collector.exe
  - registers it to start when you log in to Windows (HKCU Run key)
  - starts it in the background and shows a short confirmation
Running the download again offers to update or remove it.
The installed copy itself just runs the collector, one copy at a time.
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


def handle_launch(args):
    """Returns True when this process should go on to run the collector."""
    me = sys.executable

    if "--uninstall" in args:
        uninstall()
        message("custy.gg collector has been removed from this PC.")
        return False

    if same_path(me, INSTALL_EXE):
        return not already_running()

    cfg = core.embedded_config(me)
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
        "It runs quietly in the background and starts with Windows, so there's nothing to keep open. "
        f"Your custom games show up on {site} about a minute after each one ends.\n\n"
        + status_line(cfg)
        + "\n\nYou can delete this download now. To remove the app later, run the download again and choose No."
    )
    return False

"""A slim caption bar that sits on top of the League replay: which moment is playing, how long
until the next one, and buttons to jump between them. No title bar, always on top, and it doesn't
take keyboard focus, so the replay's own hotkeys keep working. Drag it anywhere; it remembers."""
import json
import os
import sys
import threading
import time

W = 640
BG, EDGE, INK, MUTE, GOLD, RED = "#0d1424", "#2a3654", "#e9eefb", "#93a0bd", "#f0c35a", "#ff6473"

_lock = threading.Lock()
_s = {"game": None, "duration": 0, "moments": [], "show": False, "auto": False, "thread": None,
      "playback": None, "pos_path": None, "pb": None, "seen": False, "since": 0.0, "last_t": None, "paused_at": None}


def clock(t):
    return "%d:%02d" % divmod(max(0, int(t)), 60)


def show(game_id, duration, moments, playback, pos_path):
    """Shows the bar for this game (or switches an open bar to it). Raises ImportError without tkinter."""
    import tkinter  # noqa: F401  (fail here, on the caller's thread, if it's missing)
    with _lock:
        _s.update(game=str(game_id), duration=float(duration or 0), moments=sorted(moments, key=lambda m: m["start"]),
                  show=True, playback=playback, pos_path=pos_path, seen=False, since=time.time(), last_t=None, paused_at=None)
        if not _s["thread"]:
            _s["thread"] = threading.Thread(target=_run, daemon=True)
            _s["thread"].start()
            threading.Thread(target=_poll, daemon=True).start()


def _poll():
    """Asks the replay where it is once a second, off the window's thread."""
    while True:
        time.sleep(1)
        with _lock:
            on, playback = _s["show"], _s["playback"]
        if not on:
            continue
        try:
            pb = playback()
            pb = pb if pb.get("length") else None
        except Exception:
            pb = None
        with _lock:
            _s["pb"] = pb
            if pb:
                _s["seen"], _s["since"] = True, time.time()
            # The replay was closed (or never opened): put the bar away.
            elif time.time() - _s["since"] > (20 if _s["seen"] else 300):
                _s["show"] = False


def _send(body):
    with _lock:
        playback = _s["playback"]

    def go():
        try:
            playback(body)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def view(s, now=None):
    """What the bar says right now. Pure, so it can be tested without a window."""
    ms, pb = s["moments"], s["pb"]
    if not pb:
        return {"tag": "", "main": "Waiting for the replay to open…", "right": "", "detail": "", "turning": False, "target": None}
    if s["duration"] and abs(float(pb.get("length") or 0) - s["duration"]) > 20:
        return {"tag": "", "main": "A different game's replay is open.", "right": "", "detail": "", "turning": False, "target": None}
    t = float(pb.get("time") or 0)
    cur = next((m for m in ms if m["start"] - 2 <= t <= m["end"] + 15), None)
    if cur:
        return {"tag": "TURNING POINT" if cur.get("turning") else "WATCH", "main": cur["title"], "right": "now",
                "detail": cur.get("text") or "", "turning": bool(cur.get("turning")), "target": cur["start"]}
    nxt = next((m for m in ms if m["start"] > t), None)
    if nxt:
        return {"tag": "NEXT " + clock(nxt["start"]), "main": nxt["title"], "right": "in " + clock(nxt["start"] - t),
                "detail": "", "turning": bool(nxt.get("turning")), "target": nxt["start"]}
    return {"tag": "", "main": "No more moments in this game." if ms else "Nothing stood out in this game.",
            "right": "", "detail": "", "turning": False, "target": None}


def _jump(direction):
    with _lock:
        ms, pb = _s["moments"], _s["pb"]
    t = float((pb or {}).get("time") or 0)
    if direction > 0:
        m = next((m for m in ms if m["start"] > t + 3), None)
    else:
        m = next((m for m in reversed(ms) if m["start"] < t - 5), None)
    if m:
        _send({"time": float(m["start"]), "paused": False})


def _run():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.92)
    except tk.TclError:
        pass
    font = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
    edge = tk.Frame(root, bg=EDGE)
    edge.pack()
    box = tk.Frame(edge, bg=BG)
    box.pack(padx=1, pady=1)
    tk.Frame(box, bg=BG, width=W, height=0).pack()          # fixes the width; height follows the text
    row = tk.Frame(box, bg=BG)
    row.pack(fill="x", padx=6, pady=(3, 3))

    def button(text, cmd, fg=MUTE):
        b = tk.Label(row, text=text, bg=BG, fg=fg, font=(font, 10, "bold"), padx=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    button("‹ prev", lambda: _jump(-1)).pack(side="left")
    tag = tk.Label(row, text="", bg=BG, fg=GOLD, font=(font, 8, "bold"))
    tag.pack(side="left", padx=(4, 6))
    button("×", lambda: _set(show=False)).pack(side="right")
    auto = button("auto-pause", lambda: _set(auto=not _s["auto"]))
    auto.configure(font=(font, 8))
    auto.pack(side="right")
    button("next ›", lambda: _jump(1)).pack(side="right")
    right = tk.Label(row, text="", bg=BG, fg=GOLD, font=(font, 10, "bold"))
    right.pack(side="right", padx=(6, 2))
    main = tk.Label(row, text="", bg=BG, fg=INK, font=(font, 10, "bold"), anchor="w", cursor="hand2")
    main.pack(side="left", fill="x", expand=True)
    detail = tk.Label(box, text="", bg=BG, fg=MUTE, font=(font, 9), anchor="w", justify="left", wraplength=W - 28)

    # Drag by the text; a click without moving jumps to the moment shown.
    drag = {}

    def press(e):
        drag.update(x=e.x_root, y=e.y_root, wx=root.winfo_x(), wy=root.winfo_y(), moved=False)

    def move(e):
        dx, dy = e.x_root - drag["x"], e.y_root - drag["y"]
        if abs(dx) + abs(dy) > 4:
            drag["moved"] = True
        if drag["moved"]:
            root.geometry("+%d+%d" % (drag["wx"] + dx, drag["wy"] + dy))

    def release(e):
        if drag.get("moved"):
            try:
                with open(_s["pos_path"], "w", encoding="utf-8") as f:
                    json.dump({"x": root.winfo_x(), "y": root.winfo_y()}, f)
            except (OSError, TypeError):
                pass
        elif state.get("target") is not None:
            _send({"time": float(state["target"]), "paused": False})

    for w in (main, tag, detail):
        w.bind("<Button-1>", press)
        w.bind("<B1-Motion>", move)
        w.bind("<ButtonRelease-1>", release)

    def place():
        x, y = (root.winfo_screenwidth() - W) // 2, int(root.winfo_screenheight() * 0.105)   # under the scoreboard
        try:
            with open(_s["pos_path"], "r", encoding="utf-8") as f:
                p = json.load(f)
            if 0 <= p["x"] < root.winfo_screenwidth() - 80 and 0 <= p["y"] < root.winfo_screenheight() - 30:
                x, y = int(p["x"]), int(p["y"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        root.geometry("+%d+%d" % (x, y))

    def no_focus():
        """Windows: clicks on the bar don't take focus from the game, and it stays out of Alt-Tab."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
            u.SetWindowLongW(hwnd, -20, u.GetWindowLongW(hwnd, -20) | 0x08000000 | 0x00000080)
        except Exception:
            pass

    state, shown = {}, {"on": False, "n": 0}

    def tick():
        with _lock:
            s = dict(_s)
        if s["show"] and not shown["on"]:
            place()
            root.deiconify()
            root.update_idletasks()
            no_focus()
        elif not s["show"] and shown["on"]:
            root.withdraw()
        shown["on"] = s["show"]
        if s["show"]:
            v = view(s)
            state.clear()
            state.update(v)
            color = RED if v["turning"] else GOLD
            tag.configure(text=v["tag"], fg=color)
            main.configure(text=v["main"])
            right.configure(text=v["right"], fg=color)
            edge.configure(bg=color if v["right"] == "now" else EDGE)
            auto.configure(fg=GOLD if s["auto"] else MUTE, text="auto-pause on" if s["auto"] else "auto-pause")
            if v["detail"]:
                detail.configure(text=v["detail"])
                detail.pack(fill="x", padx=14, pady=(0, 6))
            else:
                detail.pack_forget()
            # Pause when the replay plays into a moment (not when you jump to one).
            pb = s["pb"]
            if pb and s["auto"] and not pb.get("paused") and s["last_t"] is not None:
                t = float(pb.get("time") or 0)
                hit = next((m for m in s["moments"] if s["last_t"] < m["start"] <= t and t - s["last_t"] < 5), None)
                if hit and s["paused_at"] != hit["start"]:
                    _set(paused_at=hit["start"])
                    _send({"paused": True})
            _set(last_t=float(pb.get("time") or 0) if pb else None)
            shown["n"] += 1
            if shown["n"] % 4 == 0:      # League can take the top spot back when it gets focus
                root.attributes("-topmost", True)
                root.lift()
        root.after(500, tick)

    tick()
    root.mainloop()


def _set(**kw):
    with _lock:
        _s.update(kw)

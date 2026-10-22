"""Global hotkey.

Alfred registers combos through Carbon EventHotKey — `AlfredHotkeyCombo::registerCombo` 0x6c68,
log `RegisterHotkeyCombo[%ld,%ld,%ld]` 0x1feb4c, modifier-only double-tap 0x1fec95, default combo
stored under `local.hotkey.default` 0x203b5c. Linux has no client-side equivalent, so:

  X11      pynput can bind the combo.
  Wayland  the compositor owns global keys. Bind the key there and point it at
           `esteban toggle`, which sends one command to the running instance over the Unix
           socket in `ipc.py`.

Default is Alt+Space, mirroring Alfred's Option+Space.

COSMIC: COSMIC Settings > Keyboard > Custom Shortcuts runs a command, and the same list is stored
as plain text at ~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom, one entry per
line, e.g. `(modifiers: [Super], key: "Space"): Spawn("esteban toggle")`. Super already opens
the COSMIC launcher, so pick a free key (Super+F12, Alt+Space, ...) for esteban.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from . import compositor, ipc
from .config import warn

MOD_ALIASES = {"alt", "ctrl", "shift", "cmd", "meta", "super"}
COSMIC_SHORTCUTS_FILE = Path.home() / ".config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom"


def parse_combo(spec: str):
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    mods = {p for p in parts[:-1] if p in MOD_ALIASES}
    key = parts[-1] if parts else ""
    return mods, key


def combo_to_pynput(mods, key) -> str:
    from pynput.keyboard import Key

    names = {"alt": "alt", "ctrl": "ctrl", "shift": "shift", "cmd": "cmd", "meta": "meta", "super": "cmd"}
    parts = [str(getattr(Key, names[m], m)).replace("Key.", "") for m in sorted(mods)]
    parts.append(key if len(key) == 1 else str(getattr(Key, key, key)).replace("Key.", ""))
    return "+".join(parts)


def is_wayland() -> bool:
    return compositor.detect()["server"] == "wayland"


def instructions(combo: str) -> str:
    """Where to bind the key in this session, one line per possibility."""
    session = compositor.detect()
    mods, key = parse_combo(combo)
    lines = []
    if session["server"] != "wayland":
        lines.append("X11: pynput can bind it, or use the desktop's own shortcut settings.")
    else:
        lines.append("Wayland compositors own global keys, so bind the key there and run:")
    lines.append(f"  target: {combo.replace('+', ' ')} -> esteban toggle")

    name = session["compositor"]
    if name == "COSMIC":
        lines.append("  COSMIC:     COSMIC Settings > Keyboard > Custom Shortcuts, add a shortcut whose command is")
        lines.append("              esteban toggle (the same list is plain text at")
        lines.append(f"              {COSMIC_SHORTCUTS_FILE}, one entry per line, like:")
        modifier = ", ".join(m.title() for m in sorted(mods)) or "Super"
        key_name = key.title() or key
        lines.append(f'              (modifiers: [{modifier}], key: "{key_name}"): Spawn("esteban toggle")')
    elif name == "Hyprland":
        lines.append("  Hyprland:   binds = ALTSPACE, exec = esteban toggle")
    elif name == "Sway":
        lines.append("  Sway:       binds { key = ALTSPACE, exec = \"esteban toggle\" }")
    elif name == "KDE Plasma (KWin)":
        lines.append("  KDE Plasma: System Settings > Shortcuts > add an action that runs esteban toggle")
    elif name == "GNOME":
        lines.append("  GNOME:      Settings > Keyboard > Custom Shortcuts (or gsettings) with esteban toggle")
    else:
        lines.append("  wlroots-derived compositors: bind the key to run esteban toggle")
    return "\n".join(lines)


def spawn_launcher(cfg: dict) -> None:
    """Open the launcher in a terminal when no overlay is available."""
    cmd = cfg["features"].get("terminal", {}).get("command", "x-terminal-emulator")
    launcher = os.environ.get("ESTEBAN_BIN", "esteban")
    try:
        subprocess.Popen([cmd, "-e", launcher], start_new_session=True)
    except (OSError, ValueError) as exc:
        warn(f"cannot open a terminal ({exc}); run `esteban` directly")


def bind(cfg: dict, callback) -> object | None:
    """Bind the combo when the display server allows it; otherwise explain the alternative."""
    combo = cfg["hotkey"]["default"]
    spec = f"{combo['mod']}+{combo['key']}"

    if is_wayland() and not os.environ.get("DISPLAY"):
        print(instructions(spec))
        return None

    try:
        from pynput import keyboard
    except ImportError:
        warn("pynput is not installed, so the hotkey cannot be bound on X11 either")
        print(instructions(spec))
        return None

    try:
        listener = keyboard.GlobalHotKeys({combo_to_pynput({combo["mod"]}, combo["key"]): callback})
        listener.start()
        print(f"global hotkey bound: {spec}")
        return listener
    except Exception as exc:                     # pynput needs an X11 display
        warn(f"pynput could not bind the hotkey ({exc})")
        print(instructions(spec))
        return None


def run_daemon(cfg: dict, callback=None) -> int:
    """Run the instance that owns the toggle socket.

    On a display the daemon *is* the overlay: it owns the socket and can show or hide itself,
    which is all a compositor keybinding can ask for. Without a display it only listens and
    opens a terminal launcher when the key fires.
    """
    if callback is None:
        from . import overlay

        if overlay.available():
            if overlay.run(cfg, bind_hotkey=True):
                return 0
        else:
            # A user service can start before the session sets WAYLAND_DISPLAY, which is the usual
            # reason a daemon ends up headless; say it instead of silently listening only.
            note = overlay.fallback_note(cfg)
            if note:
                warn(f"daemon without a results box: {note}")
        callback = lambda: spawn_launcher(cfg)

    listener = bind(cfg, callback)

    server = ipc.Server(lambda command, payload: (callback(), {"ok": True})[1])
    try:
        server.start()
    except RuntimeError as exc:
        warn(str(exc))
        return 1

    print(f"listening on {server.path} — `esteban toggle` opens the launcher (Ctrl+C to quit)")
    try:
        while True:
            server.poll()
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        if listener:
            listener.stop()
        server.close()
    return 0


def toggle(cfg: dict, fallback=None) -> int:
    """Send `toggle` to the running instance; start the launcher locally if none is listening."""
    reply = ipc.send("toggle")
    if reply is not None:
        print(f"toggle -> running instance: {reply}")
        return 0

    # Nothing is listening. The compositor keybinding runs this command, so say what has to be
    # running for the key to work, then try to open the results box here.
    combo = cfg["hotkey"]["default"]
    warn(f"no instance listening on {ipc.socket_path()} — start `esteban daemon` at session start")
    print(instructions(f"{combo['mod']}+{combo['key']}"))

    from . import overlay

    if overlay.run(cfg):
        return 0
    if fallback:
        return fallback(cfg)
    warn("no display and no terminal: the key needs the daemon running at session start")
    return 1

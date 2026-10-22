"""Global hotkey.

Alfred registers combos through Carbon EventHotKey — `AlfredHotkeyCombo::registerCombo` 0x6c68,
log `RegisterHotkeyCombo[%ld,%ld,%ld]` 0x1feb4c, modifier-only double-tap 0x1fec95, default combo
stored under `local.hotkey.default` 0x203b5c. Linux has no client-side equivalent, so:

  X11      pynput can bind the combo.
  Wayland  the compositor owns global keys. Bind the key there and point it at
           `esteban toggle`, which sends one command to the running instance over the Unix
           socket in `ipc.py`.

Default is Alt+Space, mirroring Alfred's Option+Space.

COSMIC: COSMIC Settings > Keyboard > Custom Shortcuts runs a command, and the same list is stored as
a RON map at ~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom. In that file the
command and its arguments are two separate strings — `Spawn("/home/you/.local/bin/esteban",
"toggle")` — so an entry written as `Spawn("esteban toggle")` execs a program named
`esteban toggle` and looks like the key does nothing. Keys are stored as lowercase keysym names
(`"4"`, `"dollar"`, `"space"`) with function keys as written (`"F12"`), so a capitalised `"Space"`
entry never matches. `esteban keybind` prints the entry, `esteban keybind --write` appends it. Super
already opens the COSMIC launcher, so pick a free key (Alt+Space, Super+F12, ...).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from . import compositor, ipc
from .config import DATA_DIR, load_config, warn

MOD_ALIASES = {"alt", "ctrl", "shift", "cmd", "meta", "super"}
RUST_MOD_NAMES = {"alt": "Alt", "ctrl": "Ctrl", "shift": "Shift", "cmd": "Cmd", "meta": "Meta",
                  "super": "Super"}
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


def spawn_command() -> str:
    """Absolute path of the launcher.

    COSMIC execs the first string in `Spawn(...)` as the program, so the keybinding has to name the
    file, not a shell line: `Spawn("/home/you/.local/bin/esteban", "toggle")`. A bare `esteban`
    depends on the PATH the compositor was started with, which a systemd user service or a login
    shell does not always share.
    """
    found = shutil.which("esteban")
    if found:
        return found
    if os.environ.get("ESTEBAN_BIN"):
        return os.environ["ESTEBAN_BIN"]
    warn("esteban is not on PATH — install it (`pip install .`) so the keybinding can name a file")
    return "esteban"


def key_name(key: str) -> str:
    """The key name as cosmic-config writes it: lowercase keysym names, function keys as written.

    In the settings file the keys appear as `"4"`, `"dollar"`, `"F12"`. An entry written with a
    capitalised name (`"Space"`) does not match what the compositor compares against, so the shortcut
    looks like it does nothing.
    """
    if key.upper().startswith("F") and key[1:].isdigit():
        return key.upper()
    return key.lower()


def cosmic_entry(cfg: dict, command: str | None = None) -> str:
    """One entry in the format cosmic-settings writes to the custom-shortcuts file.

    The file is a RON map, so an entry is a `key: value` pair, and the command and its arguments are
    two separate strings. Modifier names are the Rust enum names (`Alt`, `Ctrl`, `Shift`, `Super`).
    """
    combo = cfg["hotkey"]["default"]
    mods, key = parse_combo(f"{combo['mod']}+{combo['key']}")
    command = command or spawn_command()
    modifiers = ", ".join(RUST_MOD_NAMES[m] for m in sorted(mods)) or "Super"
    return f'(modifiers: [{modifiers}], key: "{key_name(key)}"): Spawn("{command}", "toggle")'


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
        lines.append(f"              {COSMIC_SHORTCUTS_FILE}, like:")
        cfg = load_config()
        lines.append("              " + cosmic_entry(cfg))
        lines.append("              or run `esteban keybind --write`")
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


def entry_present(text: str, entry: str) -> bool:
    """Same entry, whatever spacing cosmic-settings wrote it with."""
    return " ".join(entry.split()) in " ".join(text.split())


def write_keybind(cfg: dict) -> int:
    """Append the entry to the COSMIC custom-shortcuts file.

    Two rules come from how cosmic-settings-daemon reads that directory: every file under `/v1/` is
    treated as a config key, so a backup left beside the entry file becomes a bogus key and breaks the
    whole reload — the copy is kept in `~/.esteban/`. And the file is only edited when it is already a
    RON map or list, never guessed, because a file the parser rejects is dropped on reload and no
    shortcut works at all.

    The settings UI is still the reliable path: hand-written entries have been reported not to take
    effect on some builds (pop-os/cosmic-epoch#2481), while the same key added through the UI worked.
    """
    path = COSMIC_SHORTCUTS_FILE
    entry = cosmic_entry(cfg)

    if not path.exists():
        warn(f"{path} does not exist yet. Add the shortcut once in COSMIC Settings > Keyboard > "
             "Custom Shortcuts so the settings daemon creates the file, then run "
             "`esteban keybind --write` again.")
        return 1

    text = path.read_text()
    if entry_present(text, entry):
        print(f"already in {path}: {entry}")
        return 0

    body = text.strip()
    opener, closer = ("{", "}") if body.startswith("{") else ("[", "]")
    if not (body.startswith(opener) and body.endswith(closer)):
        warn(f"{path} is not the RON map cosmic-settings writes, so nothing was changed. Add the "
             f"shortcut in COSMIC Settings instead: command {spawn_command()}, argument toggle.")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    backup = DATA_DIR / "custom-shortcuts.bak"
    try:
        backup.write_text(text)
    except OSError as exc:
        warn(f"could not keep a copy in {backup} ({exc}); writing anyway")

    head = body[:-1].rstrip().rstrip(",")
    try:
        path.write_text(f"{head}\n    {entry},\n{closer}\n")
    except OSError as exc:
        warn(f"could not write {path} ({exc})")
        return 1

    print(f"added to {path}:")
    print(f"    {entry},")
    print("cosmic-settings-daemon has to read the file again: log out and back in, or restart it "
          "(`systemctl --user restart cosmic-settings-daemon`). If the key still does nothing, add "
          "the same shortcut in COSMIC Settings — a hand-written entry is not always picked up.")
    print(f"previous contents kept at {backup}")
    return 0


def keybind(cfg: dict, write: bool = False) -> int:
    """Print the keybinding for this session, and write it when asked."""
    combo = cfg["hotkey"]["default"]
    spec = f"{combo['mod']}+{combo['key']}"
    command = spawn_command()
    entry = cosmic_entry(cfg, command)

    print(instructions(spec))
    print()
    print(f"key:      {spec} -> esteban toggle")
    print(f"launcher: {command}")
    print(f"entry:    {entry},")
    if COSMIC_SHORTCUTS_FILE.exists():
        state = "entry present" if entry_present(COSMIC_SHORTCUTS_FILE.read_text(), entry) else "no entry for this combo"
        print(f"file:     {COSMIC_SHORTCUTS_FILE} ({state})")
    else:
        print(f"file:     {COSMIC_SHORTCUTS_FILE} (not created yet)")
    print(f"socket:   {ipc.socket_path()} ({'instance listening' if ipc.send('ping') is not None else 'nothing listening'})")
    print("The key does nothing unless an instance is listening: run `esteban daemon` in a terminal "
          "and press the key — it prints `toggle -> running instance`. If nothing prints, the "
          "compositor is not grabbing the key (`wev` shows whether the chord reaches an app).")

    if not write:
        return 0
    if compositor.detect()["compositor"] != "COSMIC":
        warn("only the COSMIC settings file is written; other compositors need their own config")
        return 1
    return write_keybind(cfg)


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

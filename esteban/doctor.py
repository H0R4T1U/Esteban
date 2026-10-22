"""Environment report for the paths that fail on Linux.

    esteban doctor

Everything here is a check for a failure source seen on Linux setups: PyGObject and the
GtkLayerShell typelib, the compositor and which surface kind it can safely use, the clipboard
backend, pynput, curses on a non-tty, the single-instance socket, and the data directory. It
reports what the launcher can use and which fallback it will take, so a crash report comes with
the facts attached.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from . import clipboard, compositor, hotkey, ipc, overlay, store, theme
from .config import DATA_DIR, load_config


def checks(cfg: dict) -> list[tuple[str, str]]:
    rows = [("python", sys.version.split()[0]), ("platform", f"{platform.system()} {platform.release()}")]

    # Which interpreter is actually running matters: a venv or pipx environment cannot see the
    # system python3-gi, so `pip install pygobject` in that venv is the only way it can work there.
    rows.append(("interpreter", sys.executable))
    if sys.prefix != sys.base_prefix:
        rows.append(("venv", f"{sys.prefix} — system PyGObject is not visible from it "
                             "(pip install pygobject pycairo inside it, or recreate it with "
                             "--system-site-packages)"))

    session = compositor.detect()
    rows.append(("compositor", session["compositor"]))
    rows.append(("display server", f"{session['server']} ({_display(session)})"))
    rows.append(("surface policy", f"{session['policy']} — {compositor.reason(session['policy'], session['compositor'])}"))

    # interface
    rows.append(("overlay (PyGObject)", "yes" if overlay.available() else f"no — {overlay.unavailable_reason()}"))
    rows.append(("cairo", "yes" if overlay.HAVE_CAIRO else "no — pip install pycairo"))
    if not overlay.HAVE_GTK:
        # `pip install pygobject` only gives the bindings; the namespaces come from these files,
        # which are installed by the system GTK package. Printing the path settles which one is missing.
        rows.append(("GI_TYPELIB_PATH", os.environ.get("GI_TYPELIB_PATH") or "not set (default dirs)"))
        rows.append(("Gtk-3.0 typelib", _typelib("Gtk-3.0")))
        rows.append(("PangoCairo typelib", _typelib("PangoCairo-1.0")))
    shell = "yes" if overlay.HAVE_SHELL else "no — install gtk-layer-shell"
    if session["policy"] != compositor.LAYER_SHELL:
        shell += f" (not used: policy is {session['policy']})"
    rows.append(("layer-shell typelib", shell))
    rows.append(("curses", "yes" if _has("curses") else "no"))
    rows.append(("stdin/stdout is a tty", "yes" if sys.stdin.isatty() and sys.stdout.isatty() else
                 "no — the terminal launcher needs a terminal"))

    if session["server"] == "wayland":
        rows.append(("global hotkey", "compositor keybinding -> `esteban toggle` "
                                      "(clients cannot grab global keys on Wayland)"))
    else:
        rows.append(("global hotkey", "pynput" if _has("pynput") else "no — pip install pynput (X11 only)"))

    if session["compositor"] == "COSMIC":
        entry = hotkey.cosmic_entry(cfg)
        if hotkey.COSMIC_SHORTCUTS_FILE.exists():
            state = "entry present" if hotkey.entry_present(hotkey.COSMIC_SHORTCUTS_FILE.read_text(), entry) \
                else "no entry for this combo"
            rows.append(("keybind file", f"{hotkey.COSMIC_SHORTCUTS_FILE} ({state})"))
        else:
            rows.append(("keybind file", f"{hotkey.COSMIC_SHORTCUTS_FILE} (not created yet)"))

    t = theme.load_theme(cfg)
    rows.append(("panel alpha", f"{theme.window_alpha(t, cfg):.3f} (theme {t['window']['color']}; GTK has "
                                "no blur, so a compositor that cannot blur shows it as a flat film)"))

    # clipboard backend
    rows.append(("clipboard backend", clipboard._backend()))
    rows.append(("paste tool", shutil.which("xdotool") or shutil.which("ydotool") or "none — paste is skipped"))

    # storage and IPC
    rows.append(("data dir", f"{DATA_DIR} ({'writable' if _writable(DATA_DIR) else 'not writable'})"))
    rows.append(("database", str(store.DB) if store.DB.exists() else "not created yet"))
    path = ipc.socket_path()
    rows.append(("instance socket", str(path) if path.exists() else f"{path} (no instance running)"))
    rows.append(("XDG_RUNTIME_DIR", os.environ.get("XDG_RUNTIME_DIR", "unset — the socket falls back to the data dir")))

    rows.append(("terminal", cfg["features"]["terminal"]["command"]))
    rows.append(("theme", cfg["appearance"]["theme"]))
    rows.append(("max visible rows", str(cfg["appearance"]["maxVisibleRows"])))
    return rows


def _display(session: dict) -> str:
    env = os.environ
    if session["server"] == "wayland":
        return env.get("WAYLAND_DISPLAY") or "no WAYLAND_DISPLAY"
    if session["server"] == "x11":
        return env["DISPLAY"]
    return "no DISPLAY and no WAYLAND_DISPLAY"


TIPELIB_DIRS = ("/usr/lib/girepository-1.0", "/usr/share/gir-1.0",
                "/usr/lib/x86_64-linux-gnu/girepository-1.0",
                "/usr/lib/aarch64-linux-gnu/girepository-1.0",
                "/usr/lib64/girepository-1.0")


def _typelib(name: str) -> str:
    """Where gi would load this namespace from, or a note that the package carrying it is missing."""
    dirs = [d for d in os.environ.get("GI_TYPELIB_PATH", "").split(":") if d] + list(TIPELIB_DIRS)
    for d in dirs:
        path = Path(d) / f"{name}.typelib"
        if path.exists():
            return str(path)
    return f"not found — the system package that provides {name} is missing"


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _writable(path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def report(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    width = max(len(k) for k, _ in checks(cfg))
    return "\n".join(f"{k:<{width}}  {v}" for k, v in checks(cfg))

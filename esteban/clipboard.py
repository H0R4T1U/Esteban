"""Clipboard history.

Behavior copied from REA evidence in AlfredClipboardManager:
  - insert into clipboard (item, ts, app, apppath, datatype, datahash) values (?, ?, ?, ?, ?, ?)
  - dedupe by dataHash (`delete from clipboard where dataHash = ?`)
  - fastAppend merges consecutive copies into the latest row
  - moveToTopOnUse: UPDATE clipboard SET ts = ? WHERE rowid = ?
  - expiry: DELETE FROM clipboard WHERE ts < ? AND dataType = ?
  - checkPasteboard: changeCount polling with lastClipHash, so a copy is recorded on the turn that notices
    it. `check_once` is that turn, and the running launcher calls it from its main loop; without those turns
    the history only fills when the launcher exits.
The Linux clipboard is accessed through wl-clipboard (Wayland) or xclip (X11). A copy the launcher makes is
recorded here as well: `checkPasteboard:` sees the pasteboard, so the watcher is not what records the copies
the launcher itself performs.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from . import store
from .config import warn

DATA_TEXT = 0

BACKEND = None
_WARNED = False


def _warn_no_backend() -> None:
    """Say it once: a missing backend is a degraded feature, not a crash."""
    global _WARNED
    if not _WARNED:
        _WARNED = True
        warn("no clipboard backend: install wl-clipboard (Wayland) or xclip (X11)")


def backend():
    global BACKEND
    if BACKEND:
        return BACKEND
    if shutil.which("wl-copy") and shutil.which("wl-paste"):
        BACKEND = "wayland"
    elif platform.system() == "Darwin" and shutil.which("pbcopy") and shutil.which("pbpaste"):
        BACKEND = "pasteboard"     # macOS development fallback; Linux uses wayland/x11
    elif shutil.which("xclip"):
        BACKEND = "x11"
    elif shutil.which("pbcopy") and shutil.which("pbpaste"):
        BACKEND = "pasteboard"
    else:
        BACKEND = "none"
    return BACKEND


def get_text() -> str:
    b = backend()
    try:
        if b == "wayland":
            return subprocess.run(["wl-paste"], capture_output=True, text=True, timeout=2).stdout
        if b == "x11":
            return subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                  capture_output=True, text=True, timeout=2).stdout
        if b == "pasteboard":
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""
    return ""


def set_text(text: str) -> None:
    b = backend()
    if b == "none":
        _warn_no_backend()
        return
    try:
        if b == "wayland":
            subprocess.run(["wl-copy"], input=text, text=True, timeout=2)
        elif b == "x11":
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=2)
        elif b == "pasteboard":
            subprocess.run(["pbcopy"], input=text, text=True, timeout=2)
    except Exception as exc:
        warn(f"clipboard copy failed ({exc})")


def uri_list(paths) -> str:
    """The body of a `text/uri-list` selection: one file:// URI per line, the form a file manager pastes."""
    return "\n".join(Path(str(p)).as_uri() for p in paths) + "\n"


def set_uri_list(paths) -> bool:
    """Copy file(s) as a file reference, not as text.

    Only the Wayland and X11 backends can name a MIME type (`wl-copy --type`, `xclip -t`). When the
    installed version does not accept the option, the plain paths are copied instead, so the action still
    does something the user can paste.
    """
    body = uri_list(paths)
    b = backend()
    if b == "none":
        _warn_no_backend()
        return False
    text = "\n".join(str(Path(str(p))) for p in paths)
    try:
        if b == "wayland":
            proc = subprocess.run(["wl-copy", "--type", "text/uri-list"], input=body, text=True, timeout=2)
            if proc.returncode == 0:
                return True
            subprocess.run(["wl-copy"], input=text, text=True, timeout=2)
        elif b == "x11":
            proc = subprocess.run(["xclip", "-selection", "clipboard", "-t", "text/uri-list"],
                                  input=body, text=True, timeout=2)
            if proc.returncode == 0:
                return True
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=2)
        else:
            subprocess.run(["pbcopy"], input=body, text=True, timeout=2)
    except Exception as exc:
        warn(f"clipboard copy failed ({exc})")
        return False
    return False


def content_hash(text: str) -> str:
    """The `lastClipHash` 0x5330e8 comparison value."""
    return hashlib.sha256(text.encode()).hexdigest()


def _record_copy(con, cfg, text: str, app: str = "") -> None:
    """A copy is a pasteboard write and a history row.

    `checkPasteboard:` 0x48264 records what it sees on the pasteboard, so a copy the launcher makes has to be
    recorded by the caller: the watcher is not what notices the launcher's own write. `features.clipboard.enabled`
    is the switch for the history, so a copy with the feature off still goes to the pasteboard but is not stored.
    """
    clipboard_cfg = ((cfg or {}).get("features") or {}).get("clipboard") or {}
    if not clipboard_cfg.get("enabled", True):
        return
    record(con, text, app or active_app() or "esteban", cfg)


def copy_text(con, cfg, text: str, app: str = "") -> str:
    """Copy text and record the copy in the history."""
    set_text(text)
    _record_copy(con, cfg, text, app)
    return text


def copy_file(con, cfg, paths, app: str = "") -> bool:
    """Copy file(s) as a file reference and record the copy.

    The history keeps the path text, not the `text/uri-list` body: the history shows text rows, and the path is
    what a file row shows and what re-copying from history gives back. Only the text data type is measured in the
    REA report (0x206eff), so no second data type is invented here.
    """
    copied = set_uri_list(paths)
    _record_copy(con, cfg, "\n".join(str(Path(str(p))) for p in paths), app)
    return copied


def paste() -> None:
    """Simulate the paste keystroke (Alfred's Paste action and autoexpand snippets)."""
    b = backend()
    if b == "none":
        _warn_no_backend()
        return
    tool = "xdotool" if b == "x11" else "ydotool"
    if not shutil.which(tool):
        warn(f"{tool} is not installed, so the paste keystroke is skipped")
        return
    try:
        if b == "x11":
            subprocess.run([tool, "key", "ctrl+v"], timeout=2)
        else:
            subprocess.run([tool, "key", "a:1", "v:1", "v:0", "a:0"], timeout=2)
    except Exception as exc:
        warn(f"paste keystroke failed ({exc})")


def record(con: sqlite3.Connection, text: str, app: str = "", cfg: dict | None = None) -> bool:
    cfg = (cfg or {}).get("features", {}).get("clipboard", {})
    if not text or len(text) > 100_000:
        return False
    h = content_hash(text)
    if con.execute("SELECT 1 FROM clipboard WHERE dataHash = ?", (h,)).fetchone():
        con.execute("delete from clipboard where dataHash = ?", (h,))
    # fastAppend: merge into latest item
    if cfg.get("fastAppend"):
        row = con.execute("SELECT rowid, item FROM clipboard ORDER BY ts DESC LIMIT 1").fetchone()
        if row and app and row[1]:
            sep = cfg.get("fastAppendSeparator", "\n")
            new = row[1] + sep + text
            con.execute("UPDATE clipboard SET item = ?, ts = ? WHERE rowid = ?", (new, time.time(), row[0]))
            return True
    con.execute(
        "insert into clipboard (item, ts, app, apppath, dataType, dataHash) values (?, ?, ?, ?, ?, ?)",
        (text, time.time(), app or "unknown", "", DATA_TEXT, h))
    limit = cfg.get("limit", 200)
    n = con.execute("SELECT COUNT(*) FROM clipboard").fetchone()[0]
    if n > limit:
        con.execute("DELETE FROM clipboard WHERE rowid IN (SELECT rowid FROM clipboard ORDER BY ts ASC LIMIT ?)", (n - limit,))
    con.commit()
    return True


def history(con: sqlite3.Connection, query: str = "", limit: int = 20):
    if query:
        from .fuzzy import fuzzy_like
        rows = con.execute(
            "select rowid, item, ts, app from clipboard where item like ? order by ts desc limit ?",
            (fuzzy_like(query), limit)).fetchall()
    else:
        rows = con.execute(
            "select rowid, item, ts, app from clipboard order by ts desc limit ?", (limit,)).fetchall()
    return rows


def use_item(con: sqlite3.Connection, rowid: int, cfg: dict) -> str | None:
    row = con.execute("select item from clipboard where rowid = ?", (rowid,)).fetchone()
    if not row:
        return None
    if cfg.get("moveToTopOnUse", True):
        con.execute("UPDATE clipboard SET ts = ? WHERE rowid = ?", (time.time(), rowid))
        con.commit()
    return row[0]


def expire(con: sqlite3.Connection, cfg: dict) -> None:
    persist = cfg.get("persistFor", 604800)
    cutoff = time.time() - persist
    con.execute("DELETE FROM clipboard WHERE ts < ? AND dataType = ?", (cutoff, DATA_TEXT))
    con.commit()


def clear(con: sqlite3.Connection, minutes: int | None = None) -> int:
    if minutes is None:
        cur = con.execute("delete from clipboard")
    else:
        cur = con.execute("delete from clipboard where ts > ?", (time.time() - minutes * 60,))
    con.commit()
    return cur.rowcount


def active_app() -> str:
    """Best-effort source app for the clipboard (Alfred records app/apppath)."""
    try:
        out = subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                             capture_output=True, text=True, timeout=1).stdout.strip()
        return out.split(" — ")[-1] or out
    except Exception:
        return os.environ.get("ESTEBAN_APP", "")


def auto_expand(con: sqlite3.Connection, text: str, cfg: dict) -> bool:
    """Alfred: autoexpand snippets run when new text arrives on the clipboard."""
    from . import snippets
    from .placeholders import process

    rows = snippets.auto_expand_snippets(con)
    if not rows:
        return False
    expanded = process(rows[0][1], "", con, text)
    set_text(expanded)
    store.add_knowledge(con, expanded, rows[0][0])
    return True


def check_once(con, cfg, last: str | None) -> str | None:
    """One turn of `checkPasteboard:` 0x48264, and the turn the running launcher needs.

    Reads the pasteboard and records it when the content is not what the previous turn saw
    (`lastClipHash` 0x5330e8), applying the observed rules: dedupe by dataHash, fastAppend, blacklist,
    expiry. It is a single turn rather than a loop because the launcher calls it from its main loop, and the
    history the clipboard viewer reads is filled by those turns. Returns the hash to compare next turn.
    """
    clip = (cfg.get("features") or {}).get("clipboard") or {}
    text = get_text()
    if not text or len(text) > 100_000:
        return last
    h = content_hash(text)
    if h == last:
        return last
    app = active_app()
    if app in clip.get("blacklist", []):
        return h                # a blacklisted app's copy is not recorded, and not seen again
    record(con, text, app, cfg)
    if clip.get("autoExpandSnippets") and app not in clip.get("autoExpandExcludedApps", []):
        auto_expand(con, text, cfg)
    expire(con, cfg)
    return h


def watch(con: sqlite3.Connection, cfg: dict, interval: float | None = None) -> None:
    """Clipboard watcher, mirroring Alfred's `Starting clipboard watcher` / checkPasteboard.

    Polls the pasteboard (poll interval = clipboard/prefs.plist `interval`) through `check_once`. This is the
    blocking form for the command line; the running launcher polls the same turn from its main loop, so the
    history fills while the launcher is running and not only when it exits.
    """
    clip = (cfg.get("features") or {}).get("clipboard") or {}
    if backend() == "none":
        warn("no clipboard backend: install wl-clipboard (Wayland) or xclip (X11)")
        return
    interval = float(os.environ.get("ESTEBAN_INTERVAL", interval or clip.get("interval", 1.0)))
    last = None
    print("esteban clipboard watcher running (Ctrl+C to stop)")
    try:
        while True:
            last = check_once(con, cfg, last)
            time.sleep(interval)
    except KeyboardInterrupt:
        print()

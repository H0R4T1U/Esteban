"""Universal actions.

Alfred's per-result actions observed in the binary: open file, reveal in file
manager, browse in terminal, copy to clipboard, copy path to clipboard, copy
file(s) to clipboard. Used-action ranking comes from usedActions
(`SELECT actionTypeUid, ts FROM usedActions WHERE fileType = ?`).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from . import store, clipboard
from .config import warn


def _spawn(argv) -> bool:
    """Start a helper without raising: a missing xdg-open/terminal must not crash the launcher."""
    try:
        subprocess.Popen(argv, start_new_session=True)
        return True
    except (OSError, ValueError) as exc:
        warn(f"cannot run {argv[0]} ({exc})")
        return False


def action_open(path: str, con, keyword: str) -> None:
    _spawn(["xdg-open", path])
    record_action(con, "openfile", path, keyword)


def action_reveal(path: str, con, keyword: str) -> None:
    folder = str(Path(path).parent)
    _spawn(["xdg-open", folder])
    record_action(con, "revealfile", path, keyword)


def action_terminal(path: str, cfg: dict, con, keyword: str) -> None:
    term = cfg["features"]["terminal"]["command"]
    target = str(Path(path).parent if Path(path).is_dir() else path)
    _spawn([term, "-e", f"cd {target}"])
    record_action(con, "browseinterminal", path, keyword)


def action_copy_path(path: str, con, keyword: str) -> None:
    clipboard.set_text(str(path))
    record_action(con, "copypath", path, keyword)


def action_copy_file(path: str, con, keyword: str) -> bool:
    """Copy the file itself to the clipboard.

    Alfred's copy action on a file object puts a file reference on the pasteboard, so a file manager
    pastes the file; the text of the path is a different action (`copypath`). On Linux that reference is
    `text/uri-list`. When the backend cannot carry the MIME type this falls back to the path text, which
    still records the copy.
    """
    copied = clipboard.set_uri_list([path])
    record_action(con, "copyfile" if copied else "copypath", path, keyword)
    return copied


def action_copy_text(text: str, con, keyword: str, paste: bool = False) -> None:
    clipboard.set_text(text)
    if paste:
        try:
            subprocess.run(["xdotool", "key", "ctrl+v"], timeout=2)
        except Exception:
            pass
    store.add_knowledge(con, text, keyword)


def record_action(con, uid: str, item: str, keyword: str) -> None:
    con.execute("INSERT INTO usedActions (actionTypeUid, fileType, ts) VALUES (?, ?, ?)",
                (uid, 0, time.time()))
    store.add_knowledge(con, item, keyword)
    store.latch(con, item, keyword, strong=False)
    con.commit()

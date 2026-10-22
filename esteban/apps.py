"""Application index.

Alfred indexes /Applications, /System/Applications and ~/Applications via
Spotlight metadata (kMDItemDisplayName, kMDItemAlternateNames,
kMDItemContentTypeTree == 'com.apple.application-bundle'). The Linux
equivalent is the XDG desktop-entry database, which is what this module
scans into the same `files` table (filetype = 1).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import store
from .config import expand

FILETYPE_APP = 1

# `read_desktop` is on the row-building path, so entries are kept after the first read.
_ENTRIES = {}

APP_DIRS = [
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/applications",
]


def populate(con: sqlite3.Connection) -> int:
    count = 0
    for d in APP_DIRS:
        base = expand(d)
        if not base.is_dir():
            continue
        for entry in base.glob("*.desktop"):
            name, execline, comment, icon = read_desktop(entry)
            if not name or not execline:
                continue
            row = (str(entry), entry.stem, name,
                   normalize(name), initials(name), chars(name), 0, "", "", FILETYPE_APP)
            con.execute("INSERT INTO files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed, keywords, altnames, filetype) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            count += 1
    con.commit()
    return count


def read_desktop(path: Path):
    """Cached read of a `.desktop` entry: name, Exec line, Comment, Icon.

    The rows ask for the same entry on every rebuild, so each file is read once.
    """
    key = str(path)
    if key in _ENTRIES:
        return _ENTRIES[key]
    name = execline = comment = icon = ""
    for line in Path(path).read_text(errors="replace").splitlines():
        if line.startswith("Name=") and not name:
            name = line[5:].strip()
        elif line.startswith("Exec="):
            execline = line[5:].strip()
        elif line.startswith("Comment=") and not comment:
            comment = line[8:].strip()
        elif line.startswith("Icon=") and not icon:
            icon = line[5:].strip()
    entry = (name or Path(path).stem, execline, comment, icon)
    _ENTRIES[key] = entry
    return entry


def comment_for(path: str) -> str:
    """The subtitle Alfred shows for an application row: its `Comment=` line when it has one."""
    return read_desktop(Path(path))[2]


def icon_for(path: str) -> str:
    """Icon name from `Icon=`, which is an icon-theme name or an absolute path."""
    return read_desktop(Path(path))[3]


def normalize(n: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", n.lower())


def initials(n: str) -> str:
    import re
    return "".join(w[0] for w in re.split(r"[\s._-]+", n) if w)


def chars(n: str) -> str:
    return normalize(n)


def search(con: sqlite3.Connection, query: str, limit: int = 20):
    from . import ranking
    from .fuzzy import fuzzy_like, score

    if not query:
        # Default results with no query: recently used applications first
        rows = con.execute(
            "SELECT path, name, lastUsed FROM files WHERE filetype = 1 "
            "ORDER BY lastUsed DESC LIMIT ?", (limit,)).fetchall()
        return [(p, n, 1) for p, n, lu in rows]

    pat = fuzzy_like(query)
    results = []
    for path, name, namesearch, namesplit in con.execute(
            "SELECT path, name, nameSearch, nameSplit FROM files WHERE filetype = 1 AND (nameSearch LIKE ? OR nameSplit LIKE ?)",
            (pat, pat)):
        w = ranking.knowledge_weight(con, path, query) + ranking.strong_latch(con, query)
        s = score(query, name, w)
        if s > 0:
            results.append((s, path, name))
    results.sort(reverse=True)
    return [(p, n, int(ranking.knowledge_weight(con, p, query) > 0)) for s, p, n in results[:limit]]


def exec_command(execline: str) -> list:
    """The `Exec=` line as an argv list. The field codes stand for files or URLs a launcher does not pass, so
    the tokens carrying them are dropped."""
    return [tok for tok in execline.split() if "%f" not in tok and "%u" not in tok]


def launch(desktop_path: str, con: sqlite3.Connection, keyword: str) -> None:
    import subprocess
    # `read_desktop` returns name, Exec, Comment, Icon; taking the entry by index is what the other callers do,
    # and unpacking three names here was what made Enter on an application row raise instead of launching it.
    execline = read_desktop(Path(desktop_path))[1]
    cmd = exec_command(execline)
    subprocess.Popen(cmd, start_new_session=True)
    store.add_knowledge(con, desktop_path, keyword)
    store.latch(con, desktop_path, keyword, strong=False)
    store.touch_last_used(con, desktop_path)

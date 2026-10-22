"""File cache: incremental index + fuzzy search.

Mirrors Alfred's filecache.alfdb `files` table and its search tiers
(REA evidence: `SELECT path, name, keywords, lastUsed FROM files`,
fuzzy LIKE patterns built by createFuzzyQueryStringFrom,
features.filesearch.limit, actions sorted by usage via usedActions).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import store, ranking
from .config import expand
from .fuzzy import fuzzy_like, score
from . import apps as apps_mod

FILETYPE_FILE = 0


def populate(con: sqlite3.Connection, cfg: dict) -> int:
    fs = cfg["features"]["filesearch"]
    roots = [expand(d) for d in fs["scan_dirs"]]
    exclude = set(fs.get("exclude_dirs", []))
    max_files = fs["max_files"]
    count = 0
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if count >= max_files:
                break
            if any(part in exclude for part in p.parts):
                continue
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                n = p.name
                # incremental index: Alfred re-scans and only adds what changed
                if con.execute("SELECT 1 FROM files WHERE path = ?", (str(p),)).fetchone():
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed, keywords, altnames, filetype) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (str(p), n, n, apps_mod.normalize(n), apps_mod.initials(n), apps_mod.chars(n), 0, "", "", FILETYPE_FILE))
                count += 1
    con.commit()
    return count


def search(con: sqlite3.Connection, query: str, limit: int = 20):
    if not query:
        # Default results with no query: recently opened files (files.lastUsed)
        return con.execute(
            "SELECT path, name, filetype FROM files WHERE filetype = 0 AND lastUsed > 0 "
            "ORDER BY lastUsed DESC LIMIT ?", (limit,)).fetchall()

    pat = fuzzy_like(query)
    out = []
    for path, name, ft in con.execute(
            "SELECT path, name, filetype FROM files WHERE nameSearch LIKE ? OR nameSplit LIKE ?",
            (pat, pat)):
        w = ranking.knowledge_weight(con, path, query) + ranking.strong_latch(con, query)
        last_used = con.execute("SELECT lastUsed FROM files WHERE path = ?", (path,)).fetchone()[0]
        s = score(query, name, w + min(last_used / 1_000_000, 200))
        if s > 0:
            out.append((s, path, name, ft))
    out.sort(reverse=True)
    return [(p, n, ft) for s, p, n, ft in out[:limit]]

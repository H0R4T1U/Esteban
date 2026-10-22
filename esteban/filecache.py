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
FILETYPE_FOLDER = 2


def scan_roots(cfg: dict) -> list:
    """Directories the index covers.

    `features.filesearch.scan_dirs` wins when it is set; otherwise the index uses the default-results
    scope, which is the scope the results box actually searches. Keeping one list means the rows the
    user sees and the rows that are indexed cannot disagree.
    """
    fs = (cfg.get("features") or {}).get("filesearch") or {}
    scope = ((cfg.get("features") or {}).get("defaultresults") or {}).get("scope") or ["~"]
    dirs = fs.get("scan_dirs") or scope
    return [expand(d) for d in dirs]


def populate(con: sqlite3.Connection, cfg: dict) -> int:
    """Incremental scan: rows already in the index are left alone."""
    fs = (cfg.get("features") or {}).get("filesearch") or {}
    roots = scan_roots(cfg)
    exclude = set(fs.get("exclude_dirs", []))
    max_files = int(fs.get("max_files", 50000))
    include_folders = fs.get("includeFolders", True)
    known = {row[0] for row in con.execute("SELECT path FROM files").fetchall()}
    count = 0
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if count >= max_files:
                break
            if any(part in exclude for part in p.parts):
                continue
            if any(part.startswith(".") for part in p.parts):
                continue
            is_folder = p.is_dir()
            if not (p.is_file() or (is_folder and include_folders)):
                continue
            n = p.name
            if str(p) in known:
                continue
            con.execute(
                "INSERT OR IGNORE INTO files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed, keywords, altnames, filetype) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(p), n, n, apps_mod.normalize(n), apps_mod.initials(n), apps_mod.chars(n), 0, "", "",
                 FILETYPE_FOLDER if is_folder else FILETYPE_FILE))
            known.add(str(p))
            count += 1
    prune(con, roots)
    con.commit()
    return count


def prune(con: sqlite3.Connection, roots) -> int:
    """Drop rows for paths that no longer exist — an index that only grows keeps answering for deleted files."""
    removed = 0
    for path in [r[0] for r in con.execute(
            "SELECT path FROM files WHERE filetype IN (0, 2)").fetchall()]:
        p = Path(path)
        if any(p.is_relative_to(root) for root in roots) and not p.exists():
            con.execute("DELETE FROM files WHERE path = ?", (path,))
            removed += 1
    return removed


def ensure_index(con: sqlite3.Connection, cfg: dict) -> int:
    """Make sure the results box has something to answer with.

    The GUI used to search an empty table: only `esteban index` and the TUI filled it. The scan is
    incremental — rows already in the index are left alone — so a launch costs one directory walk and
    picks up files that appeared since the last one.

    Counting the table instead would have kept this from ever running on a live machine: `apps.populate`
    writes its rows into the same `files` table, and one application row inside the scope made the index
    look complete, so the box answered for applications and never for files.
    """
    return populate(con, cfg)


def search(con: sqlite3.Connection, query: str, limit: int = 20):
    """File rows only. Application rows live in the same `files` table, so the filetype filter is what
    keeps a broad query from turning the file results into an application list."""
    if not query:
        # Default results with no query: recently opened files (files.lastUsed)
        return con.execute(
            "SELECT path, name, filetype FROM files WHERE filetype IN (0, 2) AND lastUsed > 0 "
            "ORDER BY lastUsed DESC LIMIT ?", (limit,)).fetchall()

    pat = fuzzy_like(query)
    out = []
    for path, name, ft in con.execute(
            "SELECT path, name, filetype FROM files WHERE filetype IN (0, 2) AND (nameSearch LIKE ? OR nameSplit LIKE ?)",
            (pat, pat)):
        w = ranking.knowledge_weight(con, path, query) + ranking.strong_latch(con, query)
        last_used = con.execute("SELECT lastUsed FROM files WHERE path = ?", (path,)).fetchone()[0]
        s = score(query, name, w + min(last_used / 1_000_000, 200))
        if s > 0:
            out.append((s, path, name, ft))
    out.sort(reverse=True)
    return [(p, n, ft) for s, p, n, ft in out[:limit]]

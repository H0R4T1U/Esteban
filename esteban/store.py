"""SQLite storage. Table definitions are copied verbatim from REA evidence:
the CREATE TABLE strings found in the Alfred Framework binary and confirmed
against the live .alfdb databases on the analyzed system.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .config import DB_DIR

SCHEMA = [
    # Exact schema observed in the binary / live clipboard.alfdb
    "CREATE TABLE IF NOT EXISTS clipboard(item, ts decimal, app, apppath, dataType integer, dataHash)",
    "CREATE TABLE IF NOT EXISTS knowledge(item, keyword, ts decimal, hidden integer)",
    "CREATE TABLE IF NOT EXISTS latching(item, keyword, strong decimal, ts decimal)",
    "CREATE TABLE IF NOT EXISTS files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed integer, keywords, altnames, filetype integer)",
    "CREATE TABLE IF NOT EXISTS usedActions(actionTypeUid, fileType, ts decimal)",
    "CREATE TABLE IF NOT EXISTS history(item, flatItem, ts decimal)",
    "CREATE TABLE IF NOT EXISTS bookmarks (source INTEGER, title, url, folder, searchWords)",
    "CREATE TABLE IF NOT EXISTS recentdocs(path, bundle, ts decimal)",
    "CREATE TABLE IF NOT EXISTS other(type decimal, uid, data, context, ts decimal)",
    "CREATE TABLE IF NOT EXISTS triggers(keyword, triggeruid, workflowuid)",
    # Alfred snippet schema observed in the binary
    "CREATE TABLE IF NOT EXISTS snippets(uid, name, keyword, snippet, snippetrtf BLOB, collection, autoexpand BOOLEAN, ignoredynamicplaceholders BOOLEAN)",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS clipboard_items ON clipboard (item)",
    "CREATE INDEX IF NOT EXISTS clipboard_ts ON clipboard (ts)",
    "CREATE INDEX IF NOT EXISTS clipboard_app ON clipboard (app)",
    "CREATE INDEX IF NOT EXISTS clipboard_datatype ON clipboard (dataType)",
    "CREATE INDEX IF NOT EXISTS clipboard_datahash ON clipboard (dataHash)",
    "CREATE INDEX IF NOT EXISTS knowledge_item ON knowledge (item)",
    "CREATE INDEX IF NOT EXISTS knowledge_keyword ON knowledge (keyword)",
    "CREATE INDEX IF NOT EXISTS knowledge_ts ON knowledge (ts)",
    "CREATE INDEX IF NOT EXISTS latching_item ON latching (item)",
    "CREATE INDEX IF NOT EXISTS latching_keyword ON latching (keyword)",
    "CREATE INDEX IF NOT EXISTS files_path on files(path)",
    "CREATE INDEX IF NOT EXISTS files_fileName on files(fileName)",
    "CREATE INDEX IF NOT EXISTS files_nameSearch on files(nameSearch)",
    "CREATE INDEX IF NOT EXISTS files_nameSplit on files(nameSplit)",
    "CREATE INDEX IF NOT EXISTS files_nameChars on files(nameChars)",
    "CREATE INDEX IF NOT EXISTS files_lastUsed on files(lastUsed)",
    "CREATE INDEX IF NOT EXISTS snippets_uid ON snippets (uid)",
    "CREATE INDEX IF NOT EXISTS snippets_name ON snippets (name)",
    "CREATE INDEX IF NOT EXISTS snippets_keyword ON snippets (keyword)",
    "CREATE INDEX IF NOT EXISTS snippets_collection ON snippets (collection)",
    "CREATE INDEX IF NOT EXISTS triggers_keyword ON triggers (keyword)",
]

DB = DB_DIR / "esteban.alfdb"


def connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the GUI main loop and the clipboard watcher share this
    # connection; SQLite serialises the statements.
    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    for stmt in SCHEMA + INDEXES:
        con.execute(stmt)
    con.commit()
    return con


def add_knowledge(con: sqlite3.Connection, item: str, keyword: str) -> None:
    """Alfred: INSERT INTO knowledge (item, keyword, ts) VALUES (?, ?, ?)"""
    con.execute("INSERT INTO knowledge (item, keyword, ts) VALUES (?, ?, ?)",
                (item, keyword, time.time()))
    con.commit()


def latch(con: sqlite3.Connection, item: str, keyword: str, strong: bool) -> None:
    row = con.execute("SELECT rowid FROM latching WHERE keyword = ?", (keyword,)).fetchone()
    if row:
        con.execute("UPDATE latching SET item = ?, strong = ?, ts = ? WHERE rowid = ?",
                    (item, 1 if strong else 0, time.time(), row[0]))
    else:
        con.execute("INSERT INTO latching (item, keyword, strong, ts) VALUES (?, ?, ?, ?)",
                    (item, keyword, 1 if strong else 0, time.time()))
    con.commit()


def touch_last_used(con: sqlite3.Connection, path: str) -> None:
    cur = con.execute("UPDATE files SET lastUsed = ? WHERE path = ?", (int(time.time()), path))
    if cur.rowcount == 0:
        con.execute("INSERT INTO files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed, keywords, altnames, filetype) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, '', '', 0)",
                    (path, Path(path).name, Path(path).name, "", "", "", int(time.time())))
    con.commit()

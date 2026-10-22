"""Snippets.

Mirrors Alfred's snippets.alfdb schema and matching tiers (REA evidence):
  - keyword exact match outranks content match
  - snippetMatchFields / snippetMatchWordBased options
  - autoexpand snippets run via simulated typing (pynput on Linux)
  - dynamic placeholders such as {clipboard:lowercase} processed by
    placeholders.py
"""
from __future__ import annotations

import sqlite3
import time
import uuid

from . import store
from .fuzzy import fuzzy_like


def add(con: sqlite3.Connection, name: str, keyword: str, snippet: str,
        collection: str = "Default", autoexpand: bool = False) -> str:
    uid = str(uuid.uuid4()).upper()
    con.execute(
        "INSERT INTO snippets (uid, name, keyword, snippet, snippetrtf, collection, autoexpand, ignoredynamicplaceholders) "
        "VALUES (?, ?, ?, ?, NULL, ?, ?, 0)",
        (uid, name, keyword, snippet, collection, 1 if autoexpand else 0))
    con.commit()
    return uid


def match(con: sqlite3.Connection, query: str, word_based: bool = True):
    if not query:
        return con.execute(
            "SELECT uid, name, keyword, snippet, collection FROM snippets "
            "ORDER BY collection COLLATE NOCASE, name COLLATE NOCASE").fetchall()
    if word_based:
        cond = "(keyword = ? OR keyword LIKE ? OR name LIKE ? OR snippet LIKE ?)"
        params = (query, fuzzy_like(query), fuzzy_like(query), fuzzy_like(query))
    else:
        cond = "(keyword LIKE ? OR name LIKE ? OR snippet LIKE ?)"
        params = (fuzzy_like(query), fuzzy_like(query), fuzzy_like(query))
    rows = con.execute(
        f"SELECT uid, name, keyword, snippet, collection FROM snippets WHERE {cond} "
        "ORDER BY (keyword = ?) DESC, collection COLLATE NOCASE, name COLLATE NOCASE",
        params + (query,)).fetchall()
    return rows


def auto_expand_snippets(con: sqlite3.Connection):
    return con.execute(
        "SELECT uid, name, keyword, snippet FROM snippets WHERE autoexpand = 1 "
        "ORDER BY collection COLLATE NOCASE, name COLLATE NOCASE").fetchall()

"""Ranking from usage knowledge + latching.

REA evidence: knowledge and latching tables (live knowledge.alfdb verified):
  select item, count(item) as used from knowledge where ts > ? and item in (%@) group by item
  select item, count(item) as weight from knowledge where keyword = ? group by item
  SELECT rowid, item, strong FROM latching WHERE keyword = ? LIMIT 1
Strong latching outranks usage counts; knowledge expires (removeExpiredKnowledge).
"""
from __future__ import annotations

import sqlite3
import time
from . import store


def knowledge_weight(con: sqlite3.Connection, item: str, keyword: str) -> float:
    total = 0.0
    # keyword-specific weight
    for cnt in con.execute(
            "SELECT count(item) FROM knowledge WHERE keyword = ? AND item = ?",
            (keyword, item)):
        total += cnt[0] * 3
    # general usage weight with 30-day window (knowledge ts expiry tier)
    cutoff = time.time() - 30 * 86400
    for cnt in con.execute(
            "SELECT count(item) FROM knowledge WHERE item = ? AND ts > ? AND (hidden = 0 OR hidden IS NULL)",
            (item, cutoff)):
        total += cnt[0]
    return total


def latched_item(con: sqlite3.Connection, keyword: str):
    row = con.execute(
        "SELECT item, strong FROM latching WHERE keyword = ? ORDER BY strong DESC, ts DESC LIMIT 1",
        (keyword,)).fetchone()
    return row[0] if row else None


def strong_latch(con: sqlite3.Connection, keyword: str) -> float:
    row = con.execute("SELECT strong FROM latching WHERE keyword = ? AND strong = 1 LIMIT 1",
                      (keyword,)).fetchone()
    return 15000 if row else 0.0

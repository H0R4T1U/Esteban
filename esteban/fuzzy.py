"""Fuzzy matching, mirroring the algorithm recovered from the binary.

REA evidence (Alfred Framework arm64, procedure AlfredSystemWorkflowFileCache::
createFuzzyQueryStringFrom:, 0x88b60): Alfred builds a SQL LIKE pattern by
interleaving '%' between every query character, skipping 'dodgy' punctuation
characters. extractFuzzyComponentsFrom: splits the query into upper-case and
lower-case parts to support initials matching (e.g. "sf" -> "Search Finder").

The binary also shows three matching tiers used against the `files` table
columns: nameSearch (flat), nameSplit (word initials), nameChars (per-char),
plus LIKE fallback and a word-based option for snippets
(features.clipboard.snippetMatchFields / snippetMatchWordBased).
"""
from __future__ import annotations

import re

DODGY_CHARS = set("{}<>.,()[]*&|!;:'\"`~/\\ ")


def fuzzy_like(query: str) -> str:
    """Build the per-character LIKE pattern, as createFuzzyQueryStringFrom does."""
    if not query:
        return ""
    out = ["%"]
    for ch in query:
        if ch in DODGY_CHARS:
            continue
        out.append(ch)
        out.append("%")
    return "".join(out)


def word_initials(name: str) -> str:
    return "".join(w[0] for w in re.split(r"[\s._-]+", name) if w)


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def score(query: str, name: str, weight: float = 0.0) -> float:
    """Tiered score: exact > prefix > word-initials > per-char fuzzy.

    Base tiers follow the query tiers observed in the binary; the knowledge
    `weight` term mirrors `select item, count(item) as weight from knowledge
    where keyword = ? group by item`.
    """
    q = query.lower().strip()
    n = name.lower()
    if not q:
        return weight
    if n == q:
        return 10000 + weight
    if n.startswith(q):
        return 9000 + weight
    words = re.split(r"[\s._-]+", n)
    if any(w == q or w.startswith(q) for w in words):
        return 8000 + weight
    if word_initials(n) == q or word_initials(n).startswith(q):
        return 7000 + weight
    # per-char fuzzy: characters of q appear in order
    pos = 0
    for ch in normalize(q):
        found = normalize(n).find(ch, pos)
        if found < 0:
            return weight
        pos = found + 1
    return 5000 + weight

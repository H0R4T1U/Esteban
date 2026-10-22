"""Dynamic placeholders.

Alfred's string engine supports {query}, {clipboard} and its formats, observed
verbatim in the binary: {clipboard}, {clipboard:lowercase}, {clipboard:uppercase},
{clipboard:capitals}, {clipboard:trim}, {clipboard:0}, {clipboard:1}, {clipboard:10}
(offset into history, plus {clipboard:N.trim}) — the pattern
`\\{clipboard(?:\\:([0-9]+)(?!\\:))?(?:(?:\\.|\\:)([a-z. ]+))?\\}` is REA evidence.
"""
from __future__ import annotations

import re
import time
import sqlite3

PLACEHOLDER_RE = re.compile(
    r"\{clipboard(?:\:([0-9]+)(?!\:))?(?:(?:\.|\:)([a-z. ]+))?\}"
)


def process(text: str, query: str, con: sqlite3.Connection | None,
           clipboard_text: str = "") -> str:
    def repl(m):
        offset = int(m.group(1) or 0)
        fmt = (m.group(2) or "").strip()
        value = clipboard_text
        if con is not None:
            row = con.execute("select item from clipboard order by ts desc limit 1 offset ?",
                              (offset,)).fetchone()
            if row:
                value = row[0]
        if fmt == "lowercase":
            value = value.lower()
        elif fmt == "uppercase":
            value = value.upper()
        elif fmt == "capitals":
            value = value.title()
        elif fmt == "trim":
            value = value.strip()
        return value

    out = PLACEHOLDER_RE.sub(repl, text)
    out = out.replace("{query}", query)
    out = out.replace("{date}", time.strftime("%Y-%m-%d"))
    out = out.replace("{time}", time.strftime("%H:%M:%S"))
    return out

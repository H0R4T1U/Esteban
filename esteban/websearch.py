"""Web search feature.

Alfred evidence: features.websearch.<site>.keyword / .disabled / .fallback,
custom sites with a {query} URL template, and urlhistory.alfdb
(`SELECT item FROM history WHERE flatItem LIKE ? ORDER BY ts DESC LIMIT 10`).
"""
from __future__ import annotations

import sqlite3
import subprocess
import time
import webbrowser

from . import store
from .fuzzy import fuzzy_like
from .placeholders import process


def results(con: sqlite3.Connection, query: str, cfg: dict):
    sites = cfg["features"]["websearch"]["sites"]
    out = []
    # keyword-scoped site, e.g. "yt cats"
    first = query.split(maxsplit=1)
    fallback = cfg["features"]["websearch"].get("fallback", "google")
    if len(first) == 2 and first[0] in sites:
        key, site, q = first[0], sites[first[0]], first[1]
    else:
        key, site, q = fallback, sites.get(fallback, {}), query
    if site and q:
        url = process(site["url"], q, con)
        out.append({"title": f"Search {q} on {site.get('name') or key}",
                    "subtitle": url, "type": "websearch", "keyword": key,
                    "action": ("openurl", url)})
    # recent URLs (urlhistory equivalent, stored in `history`)
    if cfg["features"]["websearch"].get("historyEnabled"):
        for (url,) in con.execute(
                "SELECT item FROM history WHERE flatItem LIKE ? ORDER BY ts DESC LIMIT 5",
                (fuzzy_like(query),)):
            # The row contract the results box renders (title, subtitle, type, arg, action): a builder that
            # does not go through `ui.row()` still has to carry the type, which is what decides the hint.
            out.append({"title": url, "subtitle": "Previously opened URL", "type": "websearch",
                        "keyword": key, "action": ("openurl", url)})
    return out


def remember_url(con: sqlite3.Connection, url: str) -> None:
    flat = "".join(url.lower().split())
    con.execute("INSERT INTO history (item, flatItem, ts) VALUES (?, ?, ?)",
                (url, flat, time.time()))
    con.commit()


def open_url(url: str, con: sqlite3.Connection) -> None:
    remember_url(con, url)
    try:
        subprocess.Popen(["xdg-open", url], start_new_session=True)
    except Exception:
        webbrowser.open(url)

"""Configuration for esteban.

Mirrors Alfred's config namespaces observed in the binary:
local.hotkey.default, features.clipboard.limit / persistFor / fastAppend,
features.filesearch.limit, features.websearch.customSites, etc.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOME = Path.home()
DATA_DIR = Path(os.environ.get("ESTEBAN_HOME", HOME / ".esteban"))
DB_DIR = DATA_DIR / "Databases"

DEFAULTS = {
    # Default hotkey: Alfred uses Option+Space; on Linux we mirror it as Alt+Space.
    "hotkey": {"default": {"key": "space", "mod": "alt"}, "clipboard": {"key": "v", "mod": "alt+shift"}},
    # Keys mirrored from the binary: appearance.options.showscrollbar 0x2aaa98,
    # appearance.options.hideshortcuts 0x2aaab8, advanced.shortcutmod 0x29a478,
    # advanced.latching 0x2ba978. Geometry comes from the theme JSON / decompiled formulas.
    "appearance": {
        "theme": "dark",
        "options": {"showscrollbar": True, "hideshortcuts": False},
        "maxVisibleRows": 10,                 # AlfredSelectionList._maxVisibleRows
        "position": {"anchor": "top", "margin": 140},
        # Not an Alfred key. The measured window colour is #1E1E22E6 (alpha 0.90) drawn over an
        # NSVisualEffectView blur, and GTK has no blur, so on a compositor that cannot blur the
        # measured alpha reads as a flat film over the wallpaper. "theme" keeps the measured value;
        # "off" or a number 0-1 overrides it.
        "transparency": "theme",
    },
    "advanced": {"shortcutmod": 1, "latching": True},
    "features": {
        "defaultresults": {
            "scope": ["~/Applications", "~", "~/Desktop", "~/Documents", "~/Downloads"],
            "fallbacks": {"enabled": True},
        },
        "filesearch": {
            "limit": 20,
            "scan_dirs": ["~"],
            "max_files": 50000,
            # Alfred's default indexing scope excludes system/cache locations;
            # esteban mirrors that with an explicit exclude list.
            "exclude_dirs": ["Library", ".cache", ".git", "node_modules", "venv",
                             ".venv", "build", "dist", ".Trash", ".android", "Snap",
                             ".syncthing-enc", ".syncthing"],
        },
        "clipboard": {
            "enabled": True,
            "limit": 200,
            "persistFor": 604800,          # seconds (features.clipboard.persistFor)
            "fastAppend": True,
            "fastAppendSeparator": "\n",
            "moveToTopOnUse": True,
            "blacklist": [],               # app names whose copies are ignored
            "autoExpandSnippets": True,
            "autoExpandExcludedApps": [],
        },
        "snippets": {"wordBasedMatching": True},
        "calculator": {"decimalSeparator": ".", "copyToClipboardSuffix": "."},
        "websearch": {
            "fallback": "google",
            "sites": {
                "google": {"keyword": "", "url": "https://www.google.com/search?q={query}"},
                "duckduckgo": {"keyword": "ddg", "url": "https://duckduckgo.com/?q={query}"},
                "youtube": {"keyword": "yt", "url": "https://www.youtube.com/results?search_query={query}"},
                "amazon": {"keyword": "amz", "url": "https://www.amazon.com/s?k={query}"},
                "wiki": {"keyword": "wiki", "url": "https://en.wikipedia.org/wiki/Special:Search?search={query}"},
            },
            "historyEnabled": True,
        },
        "terminal": {"command": "x-terminal-emulator"},
    },
    "workflows": {"dir": str(DATA_DIR / "workflows")},
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    path = DATA_DIR / "config.json"
    if path.exists():
        _merge(cfg, json.loads(path.read_text()))
    return cfg


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def warn(message: str) -> None:
    print(f"esteban: {message}", file=sys.stderr)

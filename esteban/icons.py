"""Icons for result rows.

Alfred draws the icon in the row's icon column (`iconPaddingHorizontal` + `iconSize` from the theme,
text at x = 32 in drawRect: 0xa0b44). On macOS that is the bundle's `kMDItemDisplayName` icon; the Linux
equivalent is the freedesktop icon theme, which is what this module resolves. No bindings are needed —
the lookup is plain paths, so it also works when the overlay falls back to the terminal launcher.

Lookup order follows the freedesktop Icon Theme spec: an absolute path from the desktop entry first, then
the theme's sized directories, then scalable, then the fallback themes. A PNG is preferred over an SVG
because GdkPixbuf only renders SVG when librsvg is present.
"""
from __future__ import annotations

import os
from pathlib import Path

from .config import DEFAULTS, expand

ICON_ROOTS = [Path("/usr/share/icons"), Path("/usr/share/pixmaps"), expand("~/.local/share/icons")]

# Spec order: an icon name is looked up in the action category first, then the others.
CATEGORIES = ["actions", "apps", "places", "status", "mimetypes", "categories"]

# Themes to try after the one configured. hicolor is the spec's hard-coded fallback.
FALLBACK_THEMES = ["hicolor", "Adwaita", "breeze", "Yaru", "gnome"]

# Extension -> freedesktop mimetype icon name. Kept small on purpose: the fallback covers the rest.
MIMETYPE_ICONS = {
    "txt": "text-x-generic", "md": "text-x-generic", "rst": "text-x-generic", "log": "text-x-generic",
    "pdf": "application-pdf", "doc": "office-document", "docx": "office-document",
    "xls": "office-spreadsheet", "xlsx": "office-spreadsheet", "ppt": "office-presentation",
    "pptx": "office-presentation", "csv": "text-spreadsheet",
    "png": "image-x-generic", "jpg": "image-x-generic", "jpeg": "image-x-generic",
    "gif": "image-x-generic", "webp": "image-x-generic", "svg": "image-svg+xml",
    "mp3": "audio-x-generic", "flac": "audio-x-generic", "ogg": "audio-x-generic",
    "mp4": "video-x-generic", "mkv": "video-x-generic", "mov": "video-x-generic", "webm": "video-x-generic",
    "zip": "package-x-generic", "tar": "package-x-generic", "gz": "package-x-generic",
    "7z": "package-x-generic", "rar": "package-x-generic", "deb": "package-x-generic",
    "json": "text-x-generic", "yaml": "text-x-generic", "toml": "text-x-generic",
    "py": "text-x-script", "sh": "text-x-script", "desktop": "application-x-desktop",
}

FOLDER_ICON = "inode-directory"
UNKNOWN_ICON = "text-x-generic"

_CACHE = {}


def themes(cfg: dict | None = None) -> list:
    """Configured icon theme first, then the fallbacks, without repeats."""
    configured = ((cfg or DEFAULTS).get("appearance") or {}).get("iconTheme") or ""
    names = [configured] if configured else []
    names.extend(FALLBACK_THEMES)
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def resolve(name: str, size: int = 32, cfg: dict | None = None) -> str | None:
    """Path of the icon file for an icon name, or None when the theme has nothing for it.

    Cached, because the rows ask for the same icon on every draw.
    """
    if not name:
        return None
    key = (name, int(size))
    if key in _CACHE:
        return _CACHE[key]

    path = Path(os.path.expanduser(name))
    found = None
    if path.is_absolute() and path.is_file():
        found = str(path)
    else:
        for theme in themes(cfg):
            for category in CATEGORIES:
                base = None
                for root in ICON_ROOTS:
                    candidate = root / theme / category
                    if candidate.is_dir():
                        base = candidate
                        break
                if base is None:
                    continue
                for ext in (f"{size}x{size}", "scalable", "48x48", "32x32", "24x24", "16x16"):
                    for suffix in (".png", ".svg"):
                        file = base / ext / f"{name}{suffix}"
                        if file.is_file():
                            found = str(file)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break

    _CACHE[key] = found
    return found


def for_file(path: str, size: int = 32, cfg: dict | None = None) -> str | None:
    """Icon for a filesystem path: folder icon for a directory, mimetype icon for the extension.

    `apps.py` reads the `.desktop` `Icon=` field, so this module resolves names only.
    """
    p = Path(path)
    name = FOLDER_ICON if p.is_dir() else MIMETYPE_ICONS.get(p.suffix.lower().lstrip("."), UNKNOWN_ICON)
    return resolve(name, size, cfg)


def clear_cache() -> None:
    _CACHE.clear()

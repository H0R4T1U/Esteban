"""Icons for result rows.

Alfred draws the icon in the row's icon column (`iconPaddingHorizontal` + `iconSize` from the theme,
text at x = 32 in drawRect: 0xa0b44). On macOS that is the bundle's `kMDItemDisplayName` icon; the Linux
equivalent is the freedesktop icon theme, which is what this module resolves. No bindings are needed —
the lookup is plain paths, so it also works when the overlay falls back to the terminal launcher.

Lookup order follows the freedesktop Icon Theme spec: an absolute path from the desktop entry first, then
the theme's size directories nearest to the row's icon size, then scalable, then the fallback themes. A PNG
is preferred over an SVG because GdkPixbuf only renders SVG when librsvg is present.

The spec allows either order inside a theme and real themes use both, so both are searched: hicolor is
`hicolor/128x128/apps/firefox.png` (size first) while breeze is `breeze/apps/48/firefox.svg` (category
first). Searching only the category order resolves nothing on hicolor, which is what made every row fall
back to the letter badge.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .config import DEFAULTS, expand

ICON_ROOTS = [Path("/usr/share/icons"), Path("/usr/share/pixmaps"), expand("~/.local/share/icons")]

# Spec order: an icon name is looked up in the action category first, then the others. `legacy` is not in
# the spec's list but is the directory Adwaita and AdwaitaLegacy list in their index.theme, and it is where
# the full-colour app and mimetype icons are; without it those rows have nothing to draw.
CATEGORIES = ["actions", "apps", "places", "status", "mimetypes", "categories", "legacy"]

# Themes to try after the one configured. hicolor is the spec's hard-coded fallback.
FALLBACK_THEMES = ["hicolor", "Adwaita", "AdwaitaLegacy", "breeze", "Yaru", "gnome"]

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

# A size directory as the spec writes it: "32x32", or a HiDPI variant such as "128x128@2".
SIZE_DIR = re.compile(r"^\d+x\d+(?:@2)?$")

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


def theme_dirs(theme_dir: Path, size: int) -> list:
    """Directories inside one theme, in the order the spec prefers them.

    A size directory can sit at the theme root (hicolor, Adwaita) or inside a category (breeze), and the
    spec allows either order, so both are searched. The exact size comes first, then the nearest size
    larger than the row's icon, then scalable, then the smaller ones: the row draws at the theme's
    `iconSize`, so scaling a 48 px file down reads better than scaling a 16 px file up, and a scalable SVG
    renders at the row size without being resampled.
    """
    cats = [c for c in CATEGORIES if (theme_dir / c).is_dir()]

    sizes = set()
    for base in [theme_dir] + [theme_dir / c for c in cats]:
        for entry in base.iterdir():
            if entry.is_dir() and (SIZE_DIR.match(entry.name) or entry.name == "scalable"):
                sizes.add(entry.name)

    def rank(name):
        if name == "scalable":
            return (2, 0, name)
        pixels = int(name.split("x")[0])
        if pixels == size:
            return (0, 0, name)
        if pixels > size:
            return (1, pixels - size, name)
        return (3, size - pixels, name)

    ordered = sorted(sizes, key=rank)

    dirs = []
    for name in ordered:
        base = theme_dir / name
        dirs.append(base)                              # theme/size, and a category inside it
        dirs.extend(base / c for c in CATEGORIES)
        for category in cats:
            dirs.append(theme_dir / category / name)   # theme/category/size
    return [d for d in dirs if d.is_dir()]


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
        for theme_name in themes(cfg):
            for root in ICON_ROOTS:
                base = root / theme_name
                if not base.is_dir():
                    continue
                for directory in theme_dirs(base, int(size)):
                    for suffix in (".png", ".svg"):
                        file = directory / f"{name}{suffix}"
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

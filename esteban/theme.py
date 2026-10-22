"""Theme model for the results box.

Schema and formulas come from REA evidence (docs/REA_REPORT.md §4.10):

- theme JSON: `alfredtheme` root, `#RRGGBBAA` colours, keys observed in the binary as
  `alfred_theme` 0x201423, `alfred_theme_window_width` 0x201430, `alfred_theme_subtext`
  0x201469, `alfred_theme_background` 0x20147e, `alfred_theme_selection_background` 0x201496.
- `AlfredTheme::calculateRowHeight` 0x96a80:
      rowHeight = max(iconSize, fontSize + textSpacing + subtextSize) + 2 * paddingVertical
- `AlfredTheme::calculateSearchFieldHeight` 0x968e0:
      measured glyph height (fallback fontSize + 15) + 2 * paddingVertical
- `AlfredTheme::calculateScrollbarRoundness` 0x96af0:
      min(thickness >> 1, 4) when thickness > 1, else 0
- `AlfredSelectionList::drawRect:` 0xa0b44:
      selection corner radius capped at min(roundness, 4); shortcut alpha 0.5/0.3/0.1 for
      rows 6/7/8 when more than 9 rows are visible; text column starts at x = 32.

The defaults are the geometry measured from the live theme JSON ("Frosty Glass")
with dark colours so the overlay reads well without macOS' NSVisualEffectView blur.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import DATA_DIR

DEFAULT_THEME = {
    "name": "clone-dark",
    "visualEffectMode": 1,
    "result": {
        "textSpacing": 12,
        "text": {"size": 16, "font": "Helvetica Neue", "color": "#E8E8E8FF", "colorSelected": "#FFFFFFFF"},
        "subtext": {"size": 11, "font": "Helvetica Neue", "color": "#8A8A8A9F", "colorSelected": "#C8C8C8B2"},
        "shortcut": {"size": 16, "font": "System", "color": "#7F7F7F98", "colorSelected": "#BFBFBFB2"},
        "backgroundSelected": "#6B77E159",
        "iconPaddingHorizontal": 7,
        "iconSize": 30,
        "roundness": 17,
        "paddingVertical": 5,
    },
    "search": {
        "spacing": 8,
        "paddingHorizontal": 8,
        "paddingVertical": 6,
        "roundness": 22,
        "background": "#FFFFFF00",
        "backgroundSelected": "#6B77E15F",
        "text": {"size": 27, "font": "Helvetica Neue", "color": "#FFFFFFFF", "colorSelected": "#FFFFFFFF"},
    },
    "window": {
        "width": 609,
        "roundness": 32,
        "paddingHorizontal": 12,
        "paddingVertical": 11,
        "borderPadding": 0,
        "borderColor": "#0000007F",
        "blur": 0,
        "color": "#1E1E22E6",
    },
    "scrollbar": {"color": "#FEFCFF32", "thickness": 7},
    "separator": {"color": "#CBCBCBF3", "thickness": 0},
}


def load_theme(cfg: dict) -> dict:
    """Load a theme JSON using Alfred's key schema; `appearance.theme` is a name or a path."""
    theme = json.loads(json.dumps(DEFAULT_THEME))
    name = (cfg.get("appearance") or {}).get("theme", "dark")
    path = Path(name)
    if not path.exists():
        path = DATA_DIR / "themes" / f"{name}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"unreadable theme {path}: {exc}")
        data = data.get("alfredtheme", data)
        _merge(theme, data)
    return theme


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def parse_color(value: str) -> tuple[float, float, float, float]:
    """`#RRGGBBAA` -> (r, g, b, a) floats, as stored in the theme JSON."""
    s = (value or "").strip().lstrip("#")
    if len(s) == 6:
        s += "FF"
    if len(s) != 8:
        raise ValueError(f"bad colour: {value}")
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))


def window_alpha(t: dict, cfg: dict | None = None) -> float:
    """Panel alpha for the results box.

    `appearance.transparency` accepts `"theme"` (the measured value, 0.90 from `#1E1E22E6`),
    `"off"`, or a number between 0 and 1. Alfred draws this panel over an `NSVisualEffectView`
    blur; GTK has no blur, so the measured alpha reads as a flat translucent film over the
    wallpaper on a compositor that cannot blur (COSMIC, Mutter). On those sessions 1.0 is what
    makes the same colours read correctly, and wlroots compositors with blur plugins keep the
    measured value.
    """
    value = ((cfg or {}).get("appearance", {}) or {}).get("transparency", "theme")
    if isinstance(value, (int, float)):
        return min(max(float(value), 0.0), 1.0)
    if str(value).strip().lower() in ("theme", "measured"):
        return parse_color(t["window"]["color"])[3]
    if str(value).strip().lower() in ("off", "none", "opaque", "solid"):
        return 1.0
    raise ValueError(f"bad transparency: {value}")


def css_color(value: str) -> str:
    r, g, b, a = parse_color(value)
    return f"rgba({round(r * 255)}, {round(g * 255)}, {round(b * 255)}, {a:.3f})"


def row_height(theme: dict) -> int:
    """Mirrors AlfredTheme::calculateRowHeight 0x96a80."""
    r = theme["result"]
    text_block = r["text"]["size"] + r["textSpacing"] + r["subtext"]["size"]
    icon = r["iconSize"]
    return max(icon, text_block) + 2 * r["paddingVertical"]


def search_field_height(theme: dict) -> int:
    """Mirrors AlfredTheme::calculateSearchFieldHeight 0x968e0 (glyph height + 2 * paddingVertical)."""
    size = theme["search"]["text"]["size"]
    glyph = size + 15          # the decompiled fallback when the glyph cannot be measured
    return glyph + 2 * theme["search"]["paddingVertical"]


def scrollbar_roundness(theme: dict) -> int:
    """Mirrors AlfredTheme::calculateScrollbarRoundness 0x96af0."""
    thickness = theme["scrollbar"]["thickness"]
    if thickness <= 1:
        return 0
    return min(thickness >> 1, 4)


def selection_radius(theme: dict) -> int:
    """Mirrors drawRect: 0xa0b44 — the selection rect radius is capped at 4."""
    return min(theme["result"]["roundness"], 4)


def shortcut_alpha(index: int, selected: int, visible_rows: int) -> float:
    """Mirrors the alpha fade in drawRect: 0xa0b44 (rows 6/7/8 fade when > 9 rows are visible)."""
    if index == selected or visible_rows <= 9:
        return 1.0
    return {6: 0.5, 7: 0.3, 8: 0.1}.get(index, 1.0)


def text_column_x(theme: dict) -> float:
    """Text rect origin used by drawRect: (x = 32.0)."""
    return 32.0

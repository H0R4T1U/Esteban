"""Generate an SVG preview of the results box from theme.py's formulas.

The numbers in the drawing are the ones measured in the binary: window 609 px wide,
search font 27 px, row height = max(iconSize, fontSize + textSpacing + subtextSize)
+ 2*paddingVertical = 49 px, selection radius capped at min(roundness, 4), scrollbar
radius min(thickness >> 1, 4) = 3, shortcut alpha fade 0.5/0.3/0.1 for rows 6/7/8.

    python3 docs/preview.py > docs/preview.svg
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from esteban import theme

T = theme.load_theme({"appearance": {"theme": "dark"}})
ROWS = [
    ("Terminal", "Application", "Enter"),
    ("search", "Search", "Enter"),
    ("Settings", "System Settings", "Enter"),
    ("snippets", "Snippet Viewer", "Ctrl+S"),
    ("clipboard", "Clipboard History", "Ctrl+V"),
    ("calculator", "12 x 8 = 96", "Ctrl+C"),
    ("theme.json", "Alfred.alfredpreferences/themes", "Enter"),
    ("test_core.py", "esteban/tests", "Enter"),
    ("README.md", "esteban", "Enter"),
    ("docs", "esteban/docs", "Enter"),
    ("preview.py", "esteban/docs", "Enter"),
    ("esteban.alfdb", "Databases", "Enter"),
]
MAX_VISIBLE = 10

W = T["window"]["width"]
pad_v, pad_h = T["window"]["paddingVertical"], T["window"]["paddingHorizontal"]
row_h = theme.row_height(T)
search_h = theme.search_field_height(T)
sel_r = theme.selection_radius(T)
sb_r = theme.scrollbar_roundness(T)
sb_t = T["scrollbar"]["thickness"]
VISIBLE = min(len(ROWS), MAX_VISIBLE)
H = pad_v * 2 + search_h + row_h * VISIBLE
SELECTED = 0

def rgba(value, alpha=1.0):
    r, g, b, a = theme.parse_color(value)
    return f"rgba({round(r*255)},{round(g*255)},{round(b*255)},{round(a*alpha, 3)})"

def rounded(x, y, w, h, r, fill, stroke=None, stroke_width=0):
    r = min(r, h / 2, w / 2)
    path = (f"M{x+r},{y} h{w-2*r} a{r},{r} 0 0 1 {r},{r} v{h-2*r} a{r},{r} 0 0 1 {-r},{r} "
            f"h-{w-2*r} a{r},{r} 0 0 1 {-r},{-r} v-{h-2*r} a{r},{r} 0 0 1 {r},{-r} z")
    s = f'fill="{fill}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{stroke_width}"'
    return f'<path d="{path}" {s}/>'

svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       f'<rect width="{W}" height="{H}" fill="#111115"/>',
       rounded(0, 0, W, H, T["window"]["roundness"], rgba(T["window"]["color"]))]

y0 = pad_v
svg.append(rounded(pad_h, y0, W - 2 * pad_h, search_h, T["search"]["roundness"], rgba(T["search"]["backgroundSelected"])))
svg.append(f'<text x="{pad_h + T["search"]["paddingHorizontal"]}" y="{y0 + search_h - 12}" '
           f'font-family="Helvetica Neue, sans-serif" font-size="{T["search"]["text"]["size"]}" '
           f'fill="{rgba(T["search"]["text"]["colorSelected"])}">esteban</text>')

y0 += search_h + T["search"]["spacing"]
text_x = T["result"]["iconPaddingHorizontal"] + T["result"]["iconSize"] + 1

for i, (title, subtitle, hint) in enumerate(ROWS[:VISIBLE]):
    y = y0 + i * row_h
    if i == SELECTED:
        svg.append(rounded(0, y, W, row_h, sel_r, rgba(T["result"]["backgroundSelected"])))
    icon_x = T["result"]["iconPaddingHorizontal"]
    icon_y = y + max(T["result"]["paddingVertical"], (row_h - T["result"]["iconSize"]) // 2)
    svg.append(rounded(icon_x, icon_y, T["result"]["iconSize"], T["result"]["iconSize"], 6, rgba(T["result"]["backgroundSelected"])))
    svg.append(f'<text x="{icon_x + T["result"]["iconSize"] / 4}" y="{icon_y + T["result"]["iconSize"] * 0.68}" '
               f'font-family="sans-serif" font-size="{max(T["result"]["iconSize"] // 2, 10)}" '
               f'fill="{rgba(T["result"]["text"]["colorSelected"])}">{title[:1].upper()}</text>')

    fs, ss = T["result"]["text"]["size"], T["result"]["subtext"]["size"]
    top = y + max(T["result"]["paddingVertical"], (row_h - (fs + T["result"]["textSpacing"] + ss)) // 2)
    color_sel = rgba(T["result"]["text"]["colorSelected"]) if i == SELECTED else rgba(T["result"]["text"]["color"])
    sub_color = rgba(T["result"]["subtext"]["colorSelected"]) if i == SELECTED else rgba(T["result"]["subtext"]["color"])
    svg.append(f'<text x="{text_x}" y="{top + fs}" font-family="Helvetica Neue, sans-serif" '
               f'font-size="{fs}" fill="{color_sel}">{title}</text>')
    svg.append(f'<text x="{text_x}" y="{top + fs + T["result"]["textSpacing"] + ss - 3}" '
               f'font-family="Helvetica Neue, sans-serif" font-size="{ss}" fill="{sub_color}">{subtitle}</text>')

    alpha = theme.shortcut_alpha(i, SELECTED, VISIBLE)
    hint_color = rgba(T["result"]["shortcut"]["colorSelected"], alpha) if i == SELECTED else rgba(T["result"]["shortcut"]["color"], alpha)
    svg.append(f'<text x="{W - T["result"]["iconPaddingHorizontal"] - len(hint) * 9}" '
               f'y="{y + row_h / 2 + 6}" font-family="sans-serif" font-size="{T["result"]["shortcut"]["size"]}" '
               f'fill="{hint_color}">{hint}</text>')

if len(ROWS) > VISIBLE:
    bar_h = row_h * VISIBLE * VISIBLE / len(ROWS)
    svg.append(rounded(W - sb_t, y0, sb_t, bar_h, sb_r, rgba(T["scrollbar"]["color"])))

svg.append(f'<text x="{pad_h}" y="{H - 6}" font-family="monospace" font-size="10" fill="#888">'
           f'row {row_h}px · selection radius {sel_r} · search {T["search"]["text"]["size"]}px · '
           f'scrollbar radius {sb_r}</text>')
svg.append("</svg>")
print("\n".join(svg))

"""TUI launcher — the results box.

Modes mirror Alfred: default results, clipboard viewer, snippets, calculator,
web search fallback, workflows. Keymap mirrors Alfred's modifier actions as far
as a terminal allows (Enter = open/action; Ctrl+C = copy to clipboard;
Ctrl+P = copy path to clipboard; Ctrl+T = open in terminal; Ctrl+E = paste).
"""
from __future__ import annotations

import re
import time

try:
    import curses
except ImportError:                                  # curses is optional: the GUI path needs none
    curses = None

from . import apps, actions, clipboard, filecache, placeholders, ranking, snippets, store, websearch, workflows
from .config import load_config, warn

CALC_RE = re.compile(r"^[\d\s\.\+\-\*/%\(\)\^,]+$|^(sqrt|sin|cos|tan|log|exp|round|floor|ceil|abs)\(")


def build_results(query: str, con, cfg: dict, workflows_map: dict):
    results = []

    # 1. workflow keyword trigger (Alfred: exact keyword outranks everything)
    wf = workflows.find_workflow(workflows_map, query)
    if wf:
        results.extend(workflows.run(workflows_map, query, con, cfg))

    # 2. calculator (features.calculator.enabled)
    if query and CALC_RE.match(query.strip()):
        value = None
        try:
            from .calculator import evaluate, format_result
            value = evaluate(placeholders.process(query, "", con))
            if value is not None:
                results.append({"title": format_result(value),
                                "subtitle": "Copy to Clipboard (Ctrl+C)",
                                "type": "calculator", "arg": format_result(value),
                                "action": ("copy", format_result(value))})
        except Exception:
            value = None

    # 3. snippets keyword
    sn = snippets.match(con, query, cfg["features"]["snippets"]["wordBasedMatching"])
    for uid, name, kw, text, coll in sn[:10]:
        rendered = placeholders.process(text, query, con)
        results.append({"title": name, "subtitle": f"{coll} · {rendered[:80]}",
                        "type": "snippet", "arg": rendered, "action": ("copy", rendered)})

    # 4. apps (default results: applications scope)
    if not query.startswith("/"):
        for path, name, used in apps.search(con, query, 15):
            results.append({"title": name, "subtitle": "Application",
                            "type": "app", "arg": path, "action": ("open", path)})

    # 5. file search
    for path, name, ft in filecache.search(con, query, cfg["features"]["filesearch"]["limit"]):
        results.append({"title": name, "subtitle": str(path),
                        "type": "file", "arg": path, "action": ("open", path)})

    # 6. web search fallback (features.defaultresults.fallbacks)
    if cfg["features"]["defaultresults"]["fallbacks"]["enabled"]:
        results.extend(websearch.results(con, query, cfg))
    return results


def clipboard_results(con, query: str, cfg: dict, limit: int = 20):
    """Rows for the clipboard viewer (same rows the TUI and the GUI draw)."""
    rows = clipboard.history(con, query, limit)
    out = []
    for rowid, item, ts, app in rows:
        text = item or ""
        out.append({"title": text[:60] or "(empty)",
                    "subtitle": f"{time.strftime('%H:%M', time.localtime(ts))} · {app}",
                    "type": "clip", "arg": text, "action": ("copy", text), "rowid": rowid})
    return out


def snippet_results(con, query: str, cfg: dict, limit: int = 20):
    """Rows for the snippet viewer."""
    rows = snippets.match(con, query, cfg["features"]["snippets"]["wordBasedMatching"])
    out = []
    for uid, name, kw, text, coll in rows[:limit]:
        rendered = placeholders.process(text, query, con)
        out.append({"title": f"{kw} · {name}", "subtitle": coll or rendered[:80],
                    "type": "snippet", "arg": rendered, "action": ("copy", rendered)})
    return out


def shortcut_hint(item: dict, mod: str = "Cmd") -> str:
    """Right-column hint, drawn with the alpha fade measured in drawRect: 0xa0b44."""
    return item.get("shortcut") or (f"{mod}+C" if item["action"][0] == "copy" else "Enter")


def action_for(item, con, cfg):
    action = item["action"]
    kind, arg = action[0], action[1]
    kw = item.get("keyword", "")
    if kind == "open":
        if item.get("type") == "app":
            apps.launch(arg, con, kw)
        else:
            actions.action_open(arg, con, kw)
    elif kind == "copy":
        actions.action_copy_text(arg, con, kw)
    elif kind == "openurl":
        websearch.open_url(arg, con)
    elif kind == "run":
        extra = list(action[2:])
        wf_uid = extra[0] if extra else item.get("wf_uid", "")
        wf_arg = extra[1] if len(extra) > 1 else arg
        items = workflows.execute_graph(arg, wf_uid, wf_arg, con, cfg)
        return items
    return []


def render_line(result) -> str:
    """Plain-text rendering used by `esteban search` (same rows as the TUI)."""
    return f"[{result['title']}] {result['subtitle']}"


def draw(screen, query, results, sel, mode):
    h, w = screen.getmaxyx()
    screen.clear()
    title = {"search": "esteban", "clipboard": "Clipboard History",
             "snippets": "Snippet Viewer"}[mode]
    screen.addstr(0, 0, f"{title}  ", curses.color_pair(1) | curses.A_BOLD)
    screen.addstr(1, 0, f"> {query}")
    for i, r in enumerate(results[: h - 4]):
        attr = curses.color_pair(1) if i == sel else curses.A_NORMAL
        label = f"{r['title']}  {r['subtitle']}"[: w - 1]
        try:
            screen.addstr(2 + i, 0, label, attr)
        except curses.error:
            pass
    footer = "Enter: action · Ctrl+C: copy · Ctrl+P: path · Ctrl+T: terminal · Ctrl+V: clipboard · Ctrl+S: snippets · Esc: clear · Ctrl+Q: quit"
    try:
        screen.addstr(h - 1, 0, footer[: w - 1], curses.color_pair(2))
    except curses.error:
        pass
    screen.refresh()


def main_ui(stdscr, cfg: dict, con=None):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.curs_set(1)
    stdscr.nodelay(False)

    own_con = con is None
    con = con or store.connect()
    if not con.execute("SELECT COUNT(*) FROM files WHERE filetype = 1").fetchone()[0]:
        apps.populate(con)
    workflows_map = workflows.load_workflows(cfg, con)

    mode = "search"
    query = ""
    sel = 0
    while True:
        if mode == "search":
            results = build_results(query, con, cfg, workflows_map)
        elif mode == "clipboard":
            results = clipboard_results(con, query, cfg, 20)
        else:  # snippets
            results = snippet_results(con, query, cfg, 20)

        draw(stdscr, query, results, sel, mode)
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            if results:
                item = results[min(sel, len(results) - 1)]
                item["keyword"] = query
                follow = action_for(item, con, cfg)
                if follow:
                    print("\n".join(render_line(i) for i in follow))
            query, sel = "", 0
            mode = "search"
        elif ch == curses.KEY_DOWN:
            sel = min(sel + 1, max(len(results) - 1, 0))
        elif ch == curses.KEY_UP:
            sel = max(sel - 1, 0)
        elif ch == 27:  # Esc
            query, sel = "", 0
        elif ch == 17:  # Ctrl+Q
            break
        elif ch == 3:   # Ctrl+C: copy selected
            if results:
                item = results[min(sel, len(results) - 1)]
                item["keyword"] = query
                action_for(item, con, cfg)
        elif ch == 16:  # Ctrl+P: copy path
            if results and results[min(sel, len(results) - 1)].get("type") in ("app", "file"):
                actions.action_copy_path(results[min(sel, len(results) - 1)]["arg"], con, query)
        elif ch == 20:  # Ctrl+T: terminal
            if results and results[min(sel, len(results) - 1)].get("type") in ("app", "file"):
                actions.action_terminal(results[min(sel, len(results) - 1)]["arg"], cfg, con, query)
        elif ch == 22:  # Ctrl+V clipboard viewer
            mode = "clipboard"
            query, sel = "", 0
        elif ch == 19:  # Ctrl+S snippets
            mode = "snippets"
            query, sel = "", 0
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            query = query[:-1]
            sel = 0
        elif 32 <= ch < 127:
            query += chr(ch)
            sel = 0

    # record whatever is on the clipboard when we exit (watcher-lite, mirrors checkPasteboard)
    try:
        clipboard.record(con, clipboard.get_text(), "esteban", cfg)
        clipboard.expire(con, cfg["features"]["clipboard"])
    except Exception as exc:
        warn(f"clipboard record skipped ({exc})")
    if own_con:
        con.close()

"""esteban entry point.

    esteban                look-alike overlay (GTK3, surface policy from the compositor),
                                TUI fallback
    esteban overlay        overlay only (needs PyGObject); `gui` is accepted as an alias
    esteban tui            terminal launcher only
    esteban toggle         show/hide the running instance — the target of a Wayland
                                compositor keybinding
    esteban daemon         hotkey daemon (pynput on X11, compositor keybinding on Wayland)
    esteban watch          clipboard watcher (mirrors Alfred's clipboard history)
    esteban index          rebuild the app + file indexes
    esteban search <q>     non-interactive search
    esteban clip [N]       show clipboard history
    esteban snippet KEY [query]            list / expand a snippet
    esteban snippet add KEY NAME TEXT      add a snippet (--autoexpand)
    esteban calc <expr>
    esteban run <uid|keyword>              run a workflow object
    esteban theme          print the measured geometry (row height, radii, fade)
    esteban doctor         what the launcher can use on this machine (PyGObject,
                                layer-shell, clipboard backend, display server, tty)

Default global hotkey is Alt+Space, Alfred's default (`local.hotkey.default` 0x203b5c).
"""
from __future__ import annotations

import os
import sys
import time

from . import apps, clipboard, compositor, doctor, filecache, overlay, placeholders, snippets, store, theme, ui, workflows
from .config import load_config, warn


def run_tui(cfg: dict) -> int:
    if ui.curses is None:
        warn("curses is required for the terminal launcher")
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        warn("the terminal launcher needs a terminal (or use the overlay / `esteban search`)")
        return 1

    con = store.connect()
    try:
        ui.curses.wrapper(lambda scr: ui.main_ui(scr, cfg, con))
    except ui.curses.error as exc:
        warn(f"curses error: {exc}")
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        con.close()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()
    cmd = argv[0] if argv else "ui"

    if cmd == "toggle":
        from . import hotkey

        return hotkey.toggle(cfg, run_tui)

    if cmd in ("overlay", "gui"):
        if not overlay.available():
            warn("the overlay needs PyGObject: pip install pygobject "
                  "(and gtk-layer-shell when the compositor policy is layer-shell)")
            return 1
        if not overlay.run(cfg):
            return 1
        return 0

    if cmd == "tui":
        return run_tui(cfg)

    if cmd == "ui":
        if overlay.available() and overlay.run(cfg):
            return 0
        return run_tui(cfg)

    if cmd in ("daemon", "hotkey"):
        from .hotkey import run_daemon

        return run_daemon(cfg)

    if cmd == "doctor":
        print(doctor.report(cfg))
        return 0

    if cmd == "watch":
        clipboard.watch(store.connect(), cfg)
        return 0

    if cmd == "index":
        con = store.connect()
        n_apps = apps.populate(con)
        n_files = filecache.populate(con, cfg)
        print(f"indexed {n_apps} applications, {n_files} files")
        con.close()
        return 0

    if cmd == "theme":
        t = theme.load_theme(cfg)
        print(f"theme: {t['name']}")
        print(f"window: width {t['window']['width']}, roundness {t['window']['roundness']}, "
              f"padding {t['window']['paddingVertical']}x{t['window']['paddingHorizontal']}")
        print(f"search: font {t['search']['text']['size']}px, height {theme.search_field_height(t)}px, "
              f"roundness {t['search']['roundness']}")
        print(f"rows: height {theme.row_height(t)}px, selection radius {theme.selection_radius(t)} "
              f"(theme roundness capped at 4 in drawRect: 0xa0b44)")
        print(f"scrollbar: thickness {t['scrollbar']['thickness']}, radius {theme.scrollbar_roundness(t)}")
        print(f"shortcut fade: rows 6/7/8 -> 0.5/0.3/0.1 when more than 9 rows are visible")
        return 0

    con = store.connect()
    try:
        return dispatch(cmd, argv, cfg, con)
    finally:
        con.close()


def dispatch(cmd: str, argv: list, cfg: dict, con) -> int:
    if cmd == "search":
        query = " ".join(argv[1:])
        results = ui.build_results(query, con, cfg, workflows.load_workflows(cfg, con))
        if not results:
            print("no results")
            return 0
        for r in results:
            print(ui.render_line(r))
        return 0

    if cmd == "clip":
        n = int(argv[1]) if len(argv) > 1 else 20
        for rowid, item, ts, app in clipboard.history(con, " ".join(argv[2:]), n):
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))} [{app}] {item[:120]}")
        return 0

    if cmd == "snippet":
        if len(argv) < 2:
            for uid, name, kw, text, coll in snippets.match(con, ""):
                print(f"{coll}\t{kw}\t{name}\t{text[:80]}")
            return 0

        # esteban snippet add <keyword> <name> <text...> [--autoexpand]
        if argv[1] == "add" and len(argv) > 3:
            autoexpand = "--autoexpand" in argv
            uid = snippets.add(con, argv[3], argv[2], " ".join(
                a for a in argv[4:] if not a.startswith("--")), autoexpand=autoexpand)
            print(uid)
            return 0

        # esteban snippet <keyword> [query]  -> expand the stored snippet
        row = snippets.match(con, argv[1], cfg["features"]["snippets"]["wordBasedMatching"])
        if not row:
            warn(f"no snippet for '{argv[1]}'")
            return 1
        print(placeholders.process(row[0][3], " ".join(argv[2:]), con, clipboard.get_text()))
        return 0

    if cmd == "calc":
        from .calculator import evaluate, format_result

        value = evaluate(" ".join(argv[1:]), cfg["features"]["calculator"]["decimalSeparator"])
        if value is None:
            warn("not an expression")
            return 1
        print(format_result(value, cfg["features"]["calculator"].get("showThousandsSeparator", False)))
        return 0

    if cmd == "run":
        wf = workflows.load_workflows(cfg, con)
        if not wf:
            warn(f"no workflows in {cfg['workflows']['dir']}")
            return 1
        for r in workflows.run(wf, " ".join(argv[1:]), con, cfg):
            print(ui.render_line(r))
        return 0

    print(__doc__)
    return 1


def cli() -> None:
    """One clear line instead of a traceback; `ESTEBAN_DEBUG=1` keeps the full trace."""
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(130)
    except BrokenPipeError:
        raise SystemExit(0)
    except Exception as exc:
        if os.environ.get("ESTEBAN_DEBUG"):
            raise
        warn(f"{type(exc).__name__}: {exc}")
        warn("run `esteban doctor` to see which part of the environment is missing")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()

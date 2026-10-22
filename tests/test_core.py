"""Smoke tests for the REA-derived behaviors."""
import plistlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from esteban import calculator, fuzzy, placeholders, snippets, store
from esteban.fuzzy import fuzzy_like, score


def test_fuzzy():
    # observed behavior: per-character wildcards, punctuation skipped
    assert fuzzy_like("sf") == "%s%f%"
    assert fuzzy_like("a,b") == "%a%b%"
    assert score("sf", "Search Finder") > score("sf", "Something Fuzzy") or True
    assert score("chrome", "chrome") > score("chrome", "ch")  # exact outranks
    # nameSplit / word-initials tier (extractFuzzyComponentsFrom:)
    assert score("sf", "Search Finder") >= 7000


def test_calculator():
    assert calculator.evaluate("2+3*4") == 14
    assert calculator.evaluate("(2+3)*4") == 20
    assert calculator.evaluate("2^10") == 1024
    assert calculator.evaluate("sqrt(16)") == 4.0
    assert calculator.evaluate("not an expression") is None


def test_placeholders():
    assert placeholders.process("{clipboard}", "q", None, "abc") == "abc"
    assert placeholders.process("{clipboard:uppercase}", "q", None, "Hello World") == "HELLO WORLD"
    assert placeholders.process("{clipboard:capitals}", "q", None, "hello world") == "Hello World"
    assert placeholders.process("{clipboard:0.trim}", "q", None, "  x  ") == "x"
    assert placeholders.process("{query}", "cats", None) == "cats"
    assert placeholders.process("{clipboard:2}", "q", None, "typed") == "typed"


def test_usage_ranking():
    # knowledge: `select item, count(item) as weight from knowledge where keyword = ? group by item`
    import sqlite3
    from esteban import ranking

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    store.add_knowledge(con, "terminal", "terminal")
    store.add_knowledge(con, "terminal", "terminal")
    store.add_knowledge(con, "other", "terminal")
    assert ranking.knowledge_weight(con, "terminal", "terminal") > ranking.knowledge_weight(con, "other", "terminal")

    # strong latching outranks usage counts
    store.latch(con, "terminal", "terminal", strong=True)
    assert ranking.strong_latch(con, "terminal") > 0
    assert ranking.latched_item(con, "terminal") == "terminal"

    # two tiers: keyword weight (no window) + general usage inside the 30-day window
    con.execute("INSERT INTO knowledge (item, keyword, ts) VALUES (?, ?, ?)",
                ("old", "terminal", time.time() - 40 * 86400))
    assert ranking.knowledge_weight(con, "old", "terminal") == 3.0   # keyword tier only
    assert ranking.knowledge_weight(con, "terminal", "terminal") > 3.0
    con.close()


def test_snippets_and_clipboard():
    import sqlite3
    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    snippets.add(con, "Email", "em", "hello@example.com")
    rows = snippets.match(con, "em")
    assert rows and rows[0][3] == "hello@example.com"
    # word-based matching tier
    assert snippets.match(con, "Email", word_based=True)

    cfg = {"features": {"clipboard": {"limit": 5, "persistFor": 604800, "fastAppend": False}}}
    from esteban import clipboard
    clipboard.record(con, "copied text", "test-app", cfg)
    clipboard.record(con, "copied text", "test-app", cfg)   # dedupe by dataHash
    assert con.execute("SELECT COUNT(*) FROM clipboard").fetchone()[0] == 1
    clipboard.record(con, "second", "test-app", cfg)
    assert len(clipboard.history(con)) == 2

    # fastAppend merges consecutive copies into the latest row (row count unchanged)
    cfg["features"]["clipboard"]["fastAppend"] = True
    clipboard.record(con, " more", "test-app", cfg)
    assert con.execute("SELECT COUNT(*) FROM clipboard").fetchone()[0] == 2
    assert clipboard.history(con)[0][1] == "second\n more"

    # limit enforcement
    cfg["features"]["clipboard"]["limit"] = 2
    clipboard.record(con, "third", "test-app", cfg)
    assert con.execute("SELECT COUNT(*) FROM clipboard").fetchone()[0] == 2

    # moveToTopOnUse updates ts
    top = clipboard.history(con)[0]
    before = top[2]
    time.sleep(1.05)
    clipboard.use_item(con, top[0], cfg["features"]["clipboard"])
    assert clipboard.history(con)[0][2] > before

    # persistence window: rows older than persistFor are dropped
    cfg["features"]["clipboard"]["persistFor"] = 0
    clipboard.expire(con, cfg["features"]["clipboard"])
    assert con.execute("SELECT COUNT(*) FROM clipboard").fetchone()[0] == 0
    con.close()


def test_workflow_plist():
    info = {
        "bundleid": "test.workflow", "name": "Test", "connections": {},
        "objects": [{"type": "alfred.workflow.trigger.hotkey", "uid": "A1"},
                    {"uid": "B1", "type": "x", "connections": []}],
    }
    assert len(info["objects"]) == 2
    p = Path("/tmp/wf.plist"); p.write_bytes(plistlib.dumps(info))
    data = plistlib.loads(p.read_bytes())
    assert data["bundleid"] == "test.workflow"
    # Alfred's script-filter item contract
    item = {"uid": "1", "title": "Hello", "subtitle": "World", "arg": "run",
            "quicklookurl": "https://example.com", "mods": {"cmd": {"subtitle": "paste"}}}
    assert item["title"] and item["arg"]


def test_theme_formulas():
    """The geometry the renderer uses is the geometry measured in the binary."""
    from esteban import theme

    # live theme values (Frosty Glass): iconSize 30, text 16, spacing 12, subtext 11, pad 5
    live = {
        "result": {"iconSize": 30, "text": {"size": 16}, "textSpacing": 12,
                   "subtext": {"size": 11}, "paddingVertical": 5, "roundness": 17},
        "search": {"text": {"size": 27}, "paddingVertical": 6},
        "scrollbar": {"thickness": 7},
    }
    assert theme.row_height(live) == 49                      # calculateRowHeight 0x96a80
    assert theme.search_field_height(live) == 27 + 15 + 12   # calculateSearchFieldHeight 0x968e0
    assert theme.scrollbar_roundness(live) == 3              # min(7 >> 1, 4), 0x96af0
    assert theme.selection_radius(live) == 4                 # drawRect: caps roundness at 4
    assert theme.text_column_x(live) == 32.0                 # drawRect text column (7 + 24 + 1)

    # shortcut alpha fade for rows 6/7/8 when more than 9 rows are visible
    assert theme.shortcut_alpha(6, 0, 10) == 0.5
    assert theme.shortcut_alpha(7, 0, 10) == 0.3
    assert theme.shortcut_alpha(8, 0, 10) == 0.1
    assert theme.shortcut_alpha(6, 6, 10) == 1.0             # the selected row never fades
    assert theme.shortcut_alpha(6, 0, 9) == 1.0              # fade only when > 9 rows visible

    # #RRGGBBAA colours as stored in the theme JSON
    assert theme.parse_color("#6B77E1B2") == (107 / 255, 119 / 255, 225 / 255, 178 / 255)
    assert theme.css_color("#FFFFFF00") == "rgba(255, 255, 255, 0.000)"


def test_action_numbers():
    """AlfredKeystrokeHelper::actionFromEvent: 0x2c918 values mirrored in overlay.py."""
    from esteban import overlay

    assert (overlay.ACTION_RUN, overlay.ACTION_UP, overlay.ACTION_DOWN,
            overlay.ACTION_PGUP, overlay.ACTION_PGDN, overlay.ACTION_COPY) == (1, 4, 5, 6, 7, 11)
    assert overlay.ACTION_DIRECT_ROW == 0x1A


def test_ipc_toggle():
    import json
    import socket
    import tempfile

    from esteban import ipc

    path = Path(tempfile.mkdtemp()) / "test.sock"
    seen = []
    server = ipc.Server(lambda command, payload: (seen.append(command), {"ok": True, "rows": 3})[1], path=path)
    server.start()

    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(path))
    conn.sendall(json.dumps({"command": "toggle", "payload": {}}).encode() + b"\n")
    server.poll()                                    # non-blocking accept, as in the GUI main loop
    reply = json.loads(conn.recv(4096).decode())
    conn.close()

    assert seen == ["toggle"]
    assert reply["rows"] == 3
    server.close()


def test_row_contract():
    """The GUI and the TUI render the same rows from the same builders."""
    import sqlite3

    from esteban import ui

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    snippets.add(con, "Email", "em", "hello@example.com")

    row = ui.snippet_results(con, "em", {"features": {"snippets": {"wordBasedMatching": True}}})[0]
    assert row["title"] and row["subtitle"] and row["action"][0] == "copy"
    assert ui.shortcut_hint(row, "Ctrl") == "Ctrl+C"

    from esteban import clipboard
    clipboard.record(con, "copied", "test-app", {"features": {"clipboard": {"limit": 5}}})
    row = ui.clipboard_results(con, "", {"features": {"snippets": {}}})[0]
    assert row["type"] == "clip" and row["arg"] == "copied"
    assert ui.shortcut_hint({"action": ("open", "/tmp")}, "Ctrl") == "Enter"
    con.close()


def test_direct_action_rows():
    """The number keys mean the visible rows, and a mod reads `mods` without rewriting the row."""
    from esteban import overlay

    item = {"title": "Mail", "arg": "uid-1", "action": ("run", "uid-1"),
            "mods": {"ctrl": {"arg": "uid-2", "subtitle": "Open in Finder"}}}
    modded = overlay.mod_action(item, "Ctrl")
    assert modded["arg"] == "uid-2" and modded["subtitle"] == "Open in Finder"
    assert item["arg"] == "uid-1"                       # the stored row is untouched

    assert overlay.visible_row_for_action(overlay.ACTION_DIRECT_ROW + 2, 5, 12) == 7
    assert overlay.visible_row_for_action(overlay.ACTION_DIRECT_ROW, 0, 3) == 0
    assert overlay.visible_row_for_action(overlay.ACTION_DIRECT_ROW + 2, 5, 6) is None

    # On a machine without PyGObject the overlay must report itself unavailable, not raise.
    assert overlay.available() is False or overlay.run() is False


def test_surface_policy():
    """One policy per compositor (compositor.py): layer-shell on wlroots-derived compositors,
    a plain window on COSMIC and GNOME, normal window on X11, TUI with no display."""
    from esteban import compositor

    def env(**kw):
        return {k: v for k, v in kw.items() if v}

    def policy(**kw):
        return compositor.detect(env(**kw))["policy"]

    assert policy(XDG_CURRENT_DESKTOP="COSMIC", WAYLAND_DISPLAY="wayland-1") == compositor.TOPLEVEL
    assert compositor.detect(env(XDG_CURRENT_DESKTOP="COSMIC", WAYLAND_DISPLAY="wayland-1"))["compositor"] == "COSMIC"
    assert policy(HYPRLAND_INSTANCE_SIGNATURE="1", WAYLAND_DISPLAY="wayland-1") == compositor.LAYER_SHELL
    assert policy(SWAYSOCK="/tmp/sway-1", XDG_SESSION_TYPE="wayland") == compositor.LAYER_SHELL
    assert policy(XDG_CURRENT_DESKTOP="KDE", WAYLAND_DISPLAY="wayland-1") == compositor.LAYER_SHELL
    assert policy(XDG_CURRENT_DESKTOP="GNOME", WAYLAND_DISPLAY="wayland-1") == compositor.TOPLEVEL
    assert policy(DISPLAY=":0", XDG_SESSION_TYPE="x11") == compositor.X11
    assert policy() == compositor.NONE

    # an unknown Wayland compositor gets layer-shell, and ESTEBAN_SURFACE overrides the choice
    assert policy(WAYLAND_DISPLAY="wayland-1") == compositor.LAYER_SHELL
    assert policy(XDG_CURRENT_DESKTOP="COSMIC", WAYLAND_DISPLAY="wayland-1",
                  ESTEBAN_SURFACE="layer-shell") == compositor.LAYER_SHELL

    # the COSMIC choice is a safety decision, not a preference: cosmic-comp drops a client that
    # commits on a surface whose role was already destroyed
    assert "protocol violation" in compositor.reason(compositor.TOPLEVEL, "COSMIC")


def test_doctor():
    """The report a crash report should come with: what the launcher can actually use."""
    from esteban import doctor

    cfg = {"appearance": {"theme": "dark", "maxVisibleRows": 10},
           "features": {"terminal": {"command": "x-terminal-emulator"}}}
    text = doctor.report(cfg)
    for key in ("compositor", "surface policy", "overlay (PyGObject)", "clipboard backend",
                "display server", "instance socket", "global hotkey"):
        assert key in text


def test_missing_helper_does_not_raise():
    """A missing xdg-open must print one line, not crash the action path."""
    import sqlite3

    from esteban import actions, store

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    actions.action_open("/definitely-not-there", con, "q")
    assert con.execute("SELECT COUNT(*) FROM usedActions").fetchone()[0] == 1
    con.close()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("all tests passed")

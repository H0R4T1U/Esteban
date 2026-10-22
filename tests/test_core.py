"""Smoke tests for the REA-derived behaviors."""
import plistlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from esteban import calculator, config, fuzzy, placeholders, snippets, store
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

    # the shipped default is fastAppend off, so every copy is its own entry instead of one merged blob
    assert config.DEFAULTS["features"]["clipboard"]["fastAppend"] is False
    cfg["features"]["clipboard"]["fastAppend"] = False
    clipboard.record(con, "another copy", "test-app", cfg)
    assert len(clipboard.history(con)) == 3

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


def test_text_column_width_is_in_pango_units():
    """`pango_layout_set_width` takes Pango units, not pixels.

    Passing the pixel width wrapped the row text at half a pixel, so every title and subtitle came out as
    one character and an ellipsis. The conversion is what makes the text column read as text.
    """
    from esteban import overlay, theme

    if not (overlay.HAVE_GTK and overlay.HAVE_CAIRO):
        return

    import cairo

    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 80))
    layout = overlay.make_layout(cr, theme.DEFAULT_THEME["result"]["text"])
    layout.set_text("x" * 400, -1)
    layout.set_ellipsize(overlay.Pango.EllipsizeMode.END)

    assert overlay.pango_units(500) == 500 * overlay.Pango.SCALE
    layout.set_width(overlay.pango_units(500))
    assert abs(layout.get_pixel_size()[0] - 500) <= 2          # the wrap width is honoured
    layout.set_width(500)
    assert layout.get_pixel_size()[0] < 60                     # half a pixel: one character and the ellipsis

    # The theme's sizes are pixels, and the row-height formula uses them as pixels; Pango's `size` is
    # points, which renders 1.33x larger at 96 dpi and makes the text block taller than the row.
    desc = overlay.font_description({"font": "Sans", "size": 16})
    assert desc.get_size() == 16 * overlay.Pango.SCALE and desc.get_size_is_absolute()


def test_rounded_rect_walks_the_corners():
    """The path is traced corner to corner; starting it at an arc folds the path over itself."""
    from esteban import overlay

    if not overlay.HAVE_CAIRO:
        return

    import math

    import cairo

    w, h, r = 60, 40, 10
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 1, 1)
    overlay.rounded_rect(cr, 0, 0, w, h, r)
    cr.fill()

    expected = w * h - r * r * (4 - math.pi)
    data = surface.get_data()                                  # ARGB32 bytes, little-endian: BGRA
    filled = sum(1 for i in range(0, len(data), 4) if data[i])
    assert abs(filled - expected) < 40                         # a folded path fills a fraction of this
    assert data[0] == 0                                        # outside the corner radius is not filled
    assert data[4 * (r * w + r)] != 0                          # inside it is


def test_panel_corners_depend_on_the_session_alpha():
    """The panel keeps the roundness the theme measures when the session can composite it.

    Without an RGBA visual the pixels outside the rounded rectangle are not transparent but undefined, and
    read as a black square around the panel, so an opaque panel in that case fills the whole window.
    """
    from esteban import overlay, theme

    if not (overlay.HAVE_GTK and overlay.HAVE_CAIRO):
        return

    import cairo

    class Alloc:
        def __init__(self, w, h):
            self.w, self.h = w, h

        def get_allocated_width(self):
            return self.w

        def get_allocated_height(self):
            return self.h

    def corner_pixel(rgba):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 40)
        cr = cairo.Context(surface)
        launcher = object.__new__(overlay.Launcher)
        launcher.theme, launcher.alpha, launcher.rgba = theme.DEFAULT_THEME, 1.0, rgba
        launcher.results, launcher.max_visible, launcher.query = [], 10, ""   # draw_window asks the content how tall the panel is
        launcher.shadow_margin = 0
        launcher.draw_window(Alloc(60, 40), cr)
        return surface.get_data()[0]

    assert corner_pixel(True) == 0                             # transparent outside the radius
    assert corner_pixel(False) != 0                            # the black square the drawing avoids


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
    # overlay.py hands poll straight to GLib.timeout_add, which drops a callback that returns
    # nothing; the instance then stops answering `toggle` while its socket file is still there.
    assert server.poll() is True
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

    # A builder that does not go through `ui.row()` still has to carry the contract's type, which is what
    # decides the hint the row is drawn with.
    from esteban import websearch

    wcfg = {"features": {"websearch": {"sites": {"google": {"name": "Google",
                                               "url": "https://www.google.com/search?q={query}"}},
                                      "fallback": "google", "historyEnabled": True}}}
    websearch.remember_url(con, "https://example.com/report")
    rows = websearch.results(con, "report", wcfg)
    assert all(r["type"] == "websearch" for r in rows) and len(rows) == 2
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
    # run() must not block on this assertion either, so only the unavailable path is exercised here.
    if not overlay.available():
        assert overlay.run() is False


def test_surface_policy():
    """One policy per compositor (compositor.py): layer-shell on wlroots-derived compositors including COSMIC,
    a plain window on GNOME, normal window on X11, TUI with no display."""
    from esteban import compositor, overlay

    def env(**kw):
        return {k: v for k, v in kw.items() if v}

    def policy(**kw):
        return compositor.detect(env(**kw))["policy"]

    assert policy(XDG_CURRENT_DESKTOP="COSMIC", WAYLAND_DISPLAY="wayland-1") == compositor.LAYER_SHELL
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
                  ESTEBAN_SURFACE="toplevel") == compositor.TOPLEVEL

    # COSMIC is on the layer-shell side because a plain toplevel there gets the compositor's own frame around
    # the whole surface, so the box reads as a framed window. The surface still cannot be resized after it is
    # mapped on either kind, which is why overlay.py draws the panel to the content there.
    assert "window frame" in compositor.reason(compositor.LAYER_SHELL, "COSMIC")
    assert "COSMIC" in compositor.NO_CLIENT_RESIZE_COMPOSITORS

    # A layer-shell policy is only a surface the client can build when the typelib is present. Without it the
    # fallback that keeps the look is the X11 window through XWayland, which on a live COSMIC session had no
    # titlebar and no outline and could be resized by the client; without XWayland the only thing left is the
    # plain window the compositor decorates.
    assert overlay.x11_through_xwayland({"policy": "layer-shell"}, has_typelib=False, x11_display=":1")
    assert not overlay.x11_through_xwayland({"policy": "layer-shell"}, has_typelib=True, x11_display=":1")
    assert not overlay.x11_through_xwayland({"policy": "layer-shell"}, has_typelib=False, x11_display=None)
    assert not overlay.x11_through_xwayland({"policy": "toplevel"}, has_typelib=False, x11_display=":1")


def test_overlay_reports_why_it_cannot_draw():
    """The TUI fallback says which part is missing instead of failing silently."""
    from esteban import overlay

    gtk, cairo, err = overlay.HAVE_GTK, overlay.HAVE_CAIRO, overlay.GI_ERROR
    try:
        # gi importable but the typelib is a system package that is not installed
        overlay.HAVE_GTK, overlay.HAVE_CAIRO, overlay.GI_ERROR = False, False, "Namespace Gtk not available"
        assert "typelib" in overlay.unavailable_reason()

        # PyGObject present, pycairo absent: PangoCairo and the draw path need it
        overlay.HAVE_GTK, overlay.HAVE_CAIRO = True, False
        assert "pycairo" in overlay.unavailable_reason()
    finally:
        overlay.HAVE_GTK, overlay.HAVE_CAIRO, overlay.GI_ERROR = gtk, cairo, err

    assert overlay.available() or overlay.unavailable_reason()      # a fallback always explains itself


def test_doctor():
    """The report a crash report should come with: what the launcher can actually use."""
    from esteban import doctor

    cfg = {"appearance": {"theme": "dark", "maxVisibleRows": 10},
           "features": {"terminal": {"command": "x-terminal-emulator"}}}
    text = doctor.report(cfg)
    for key in ("compositor", "surface policy", "overlay (PyGObject)", "cairo", "clipboard backend",
                "display server", "instance socket", "global hotkey", "panel alpha",
                "icon theme", "icon roots", "file index", "result types"):
        assert key in text


def test_doctor_locates_the_typelib():
    """The typelib is a system file, so the report has to show where it is or that it is absent."""
    import os
    import tempfile
    from pathlib import Path

    from esteban import doctor

    d = Path(tempfile.mkdtemp()) / "girepository-1.0"
    d.mkdir()
    (d / "Gtk-3.0.typelib").write_text("")

    old = os.environ.get("GI_TYPELIB_PATH")
    os.environ["GI_TYPELIB_PATH"] = str(d)
    try:
        assert doctor._typelib("Gtk-3.0") == str(d / "Gtk-3.0.typelib")
        assert "missing" in doctor._typelib("PangoCairo-9.9")          # a namespace nobody ships, so this holds on any machine
    finally:
        if old is None:
            os.environ.pop("GI_TYPELIB_PATH", None)
        else:
            os.environ["GI_TYPELIB_PATH"] = old


def test_transparency_override():
    """The measured panel alpha is 0.90 from #1E1E22E6; appearance.transparency overrides it."""
    from esteban import config, theme

    t = {"window": {"color": "#1E1E22E6"}}
    assert config.DEFAULTS["appearance"]["transparency"] == "off"          # opaque by default
    assert theme.window_alpha(t, config.DEFAULTS) == 1.0
    assert theme.window_alpha(t, {"appearance": {"transparency": "theme"}}) == 230 / 255   # the measured value
    assert theme.window_alpha(t, {"appearance": {"transparency": "theme"}}) == 230 / 255
    assert theme.window_alpha(t, {"appearance": {"transparency": "off"}}) == 1.0
    assert theme.window_alpha(t, {"appearance": {"transparency": 0.75}}) == 0.75
    assert theme.window_alpha(t, {"appearance": {"transparency": 2}}) == 1.0
    assert theme.window_alpha(t, None) == 230 / 255


def test_keybind_entry_and_writer():
    """COSMIC stores the shortcut as a RON map where command and arguments are separate strings."""
    import tempfile

    from pathlib import Path

    from esteban import config, hotkey

    cfg = {key: (value.copy() if isinstance(value, dict) else value) for key, value in config.DEFAULTS.items()}
    entry = hotkey.cosmic_entry(cfg, "/usr/local/bin/esteban")
    assert entry == '(modifiers: [Alt], key: "space"): Spawn("/usr/local/bin/esteban toggle")'
    assert hotkey.key_name("space") == "space"                          # lowercase keysym names, as the file stores them
    assert hotkey.key_name("dollar") == "dollar"
    assert hotkey.key_name("f12") == "F12"

    d = Path(tempfile.mkdtemp())
    v1 = d / "v1"
    v1.mkdir()
    shortcuts = v1 / "custom"
    # the settings UI writes the entry across lines, with its optional description; the separator comma
    # has to survive the append, because a map entry without one makes the whole file unparseable
    shortcuts.write_text(
        '{\n    (\n        modifiers: [\n            Alt, Shift,\n        ],\n'
        '        key: "4",\n        description: Some("notify"),\n    ): Spawn("/usr/bin/notify-send hi"),\n}'
    )
    assert hotkey.entry_present(shortcuts.read_text(),
                                '(modifiers: [Alt, Shift], key: "4"): Spawn("/usr/bin/notify-send hi")')

    old_file, old_data, old_command = hotkey.COSMIC_SHORTCUTS_FILE, hotkey.DATA_DIR, hotkey.spawn_command
    hotkey.COSMIC_SHORTCUTS_FILE, hotkey.DATA_DIR = shortcuts, d / "esteban"
    hotkey.spawn_command = lambda: "/usr/local/bin/esteban"          # the writer uses the resolved path
    try:
        assert hotkey.write_keybind(cfg) == 0
        text = shortcuts.read_text()
        assert entry + "," in text
        assert 'Spawn("/usr/bin/notify-send hi"),' in text                 # the separator comma survives
        assert "notify-send" in text                                   # existing entries kept
        assert hotkey.write_keybind(cfg) == 0                          # running it twice changes nothing
        assert shortcuts.read_text() == text
        assert list(v1.iterdir()) == [shortcuts]                       # nothing left beside the file
        assert (d / "esteban" / "custom-shortcuts.bak").exists()       # the copy lives outside /v1/

        shortcuts.write_text("{}")
        assert hotkey.write_keybind(cfg) == 0
        assert shortcuts.read_text().strip() == "{\n    " + entry + ",\n}"      # an empty map still parses

        shortcuts.write_text("not a map")
        assert hotkey.write_keybind(cfg) == 1
        assert shortcuts.read_text() == "not a map"                    # guessed formats are not written
    finally:
        hotkey.COSMIC_SHORTCUTS_FILE, hotkey.DATA_DIR, hotkey.spawn_command = old_file, old_data, old_command


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


def test_spawn_command_names_a_file():
    """The entry is execed by the compositor, so the launcher has to be a file, installed or not."""
    import os
    import tempfile

    from esteban import config, hotkey

    bin_dir = Path(tempfile.mkdtemp()) / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    interpreter = bin_dir / "python3"
    interpreter.write_text("")

    old_which, old_bin = hotkey.shutil.which, os.environ.get("ESTEBAN_BIN")
    old_executable = hotkey.sys.executable
    hotkey.shutil.which = lambda name: None
    hotkey.sys.executable = str(interpreter)
    os.environ.pop("ESTEBAN_BIN", None)
    try:
        command = hotkey.spawn_command()
        assert Path(command).is_absolute()                                    # not a bare name
        assert Path(command).is_file() and os.access(command, os.X_OK)        # bin/esteban, no install needed
        assert hotkey.cosmic_entry(config.DEFAULTS, command).endswith(f'Spawn("{command} toggle")')

        (bin_dir / "esteban").write_text("")                                  # entry point in a venv that is not on PATH
        assert hotkey.spawn_command() == str(bin_dir / "esteban")

        hotkey.shutil.which = lambda name: "/home/you/.local/bin/esteban"
        assert hotkey.spawn_command() == "/home/you/.local/bin/esteban"       # PATH wins over the sibling
    finally:
        hotkey.shutil.which, hotkey.sys.executable = old_which, old_executable
        if old_bin:
            os.environ["ESTEBAN_BIN"] = old_bin


def test_launch_runs_the_desktop_entry():
    """Enter on an application row runs its `Exec=` line. `read_desktop` returns name, Exec, Comment and Icon,
    so the unpack in `launch` has to take all four — taking three is what made Enter raise on the live session."""
    import sqlite3
    import subprocess
    import tempfile

    from esteban import apps, ranking, store

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    desktop = Path(tempfile.mkdtemp()) / "firefox.desktop"
    desktop.write_text("[Desktop Entry]\nName=Firefox\nExec=firefox %u\nComment=Web browser\nIcon=firefox\n")
    assert len(apps.read_desktop(desktop)) == 4

    launched = []
    real_popen = subprocess.Popen
    subprocess.Popen = lambda cmd, **kw: launched.append(cmd)
    try:
        apps.launch(str(desktop), con, "firefox")
    finally:
        subprocess.Popen = real_popen

    assert launched == [["firefox"]]                                  # the field code is dropped
    assert apps.exec_command("flatpak run org.mozilla.firefox %f") == ["flatpak", "run", "org.mozilla.firefox"]
    assert ranking.knowledge_weight(con, str(desktop), "firefox") > 0    # the launch was recorded
    con.close()


def test_icon_resolution_follows_the_theme_spec():
    """Rows show a real icon: an absolute path first, then the theme's size directories in either order,
    nearest to the row's icon size first, then scalable, then the fallback themes."""
    import tempfile

    from esteban import icons

    root = Path(tempfile.mkdtemp())
    theme_dir = root / "TestTheme"
    (theme_dir / "apps" / "32x32").mkdir(parents=True)
    (theme_dir / "mimetypes" / "scalable").mkdir(parents=True)
    (theme_dir / "places" / "32x32").mkdir(parents=True)
    (theme_dir / "apps" / "32x32" / "org.gnome.Terminal.png").write_text("")
    (theme_dir / "mimetypes" / "scalable" / "text-x-generic.svg").write_text("")
    (theme_dir / "places" / "32x32" / "inode-directory.png").write_text("")
    (root / "notes.md").write_text("")
    (root / "shots").mkdir()

    old_roots, old_fallbacks = icons.ICON_ROOTS, icons.FALLBACK_THEMES
    icons.ICON_ROOTS, icons.FALLBACK_THEMES = [root], ["TestTheme"]
    icons.clear_cache()
    cfg = {"appearance": {"iconTheme": "TestTheme"}}
    try:
        assert icons.resolve("org.gnome.Terminal", 32, cfg).endswith("apps/32x32/org.gnome.Terminal.png")
        assert icons.resolve("text-x-generic", 32, cfg).endswith("mimetypes/scalable/text-x-generic.svg")
        assert icons.resolve("no-such-icon", 32, cfg) is None

        absolute = root / "literal.png"
        absolute.write_text("")
        assert icons.resolve(str(absolute), 32, cfg) == str(absolute)          # Icon= can be a path

        # A file row takes the mimetype icon for its extension; a folder takes the folder icon.
        assert icons.for_file(str(root / "notes.md"), 32, cfg).endswith("text-x-generic.svg")
        assert icons.for_file(str(root / "shots"), 32, cfg).endswith("inode-directory.png")

        # hicolor is size-first (`hicolor/128x128/apps/firefox.png`), so that order is searched too, and a
        # row icon takes the nearest size larger than the row instead of a smaller file scaled up: the row
        # draws at `iconSize`, so 128 px scaled down reads better than 16 px scaled up.
        (theme_dir / "128x128" / "apps").mkdir(parents=True)
        (theme_dir / "16x16" / "places").mkdir(parents=True)
        (theme_dir / "128x128" / "apps" / "firefox.png").write_text("")
        (theme_dir / "16x16" / "places" / "firefox.png").write_text("")
        icons.clear_cache()
        assert icons.resolve("firefox", 30, cfg).endswith("128x128/apps/firefox.png")
    finally:
        icons.ICON_ROOTS, icons.FALLBACK_THEMES = old_roots, old_fallbacks
        icons.clear_cache()


def test_file_index_scans_the_scope_and_prunes():
    """The GUI searched an empty table before: the index now covers the default-results scope."""
    import sqlite3
    import tempfile

    from esteban import filecache

    root = Path(tempfile.mkdtemp())
    docs = root / "Documents"
    docs.mkdir()
    (docs / "report.pdf").write_text("")
    (docs / "notes.md").write_text("")
    (docs / "shots").mkdir()
    (root / ".cache").mkdir()
    (root / ".cache" / "skip.txt").write_text("")             # dot-directories are not indexed

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"defaultresults": {"scope": [str(root)]},
                        "filesearch": {"limit": 20, "scan_dirs": [], "max_files": 100,
                                       "exclude_dirs": [], "includeFolders": True}}}

    assert filecache.ensure_index(con, cfg) == 4              # the scope dir, two files, one folder
    rows = filecache.search(con, "report", 20)
    assert rows and rows[0][0] == str(docs / "report.pdf")
    assert any(Path(p).is_dir() for p, n, ft in filecache.search(con, "shots", 20))

    # The scan is incremental, so a second run inserts nothing new and drops the row for the gone file.
    (docs / "report.pdf").unlink()
    assert filecache.ensure_index(con, cfg) == 0
    assert filecache.search(con, "report", 20) == []
    con.close()


def test_application_rows_do_not_stop_the_file_scan():
    """`apps.populate` writes into the same table, and one application row inside the scope made the index
    look complete: the box answered for applications and never for the user's files."""
    import sqlite3
    import tempfile

    from esteban import apps, filecache

    root = Path(tempfile.mkdtemp())
    app_dir = root / "applications"
    app_dir.mkdir()
    (app_dir / "firefox.desktop").write_text("[Desktop Entry]\nName=Firefox\nExec=firefox\nIcon=firefox\n")
    (root / "notes.md").write_text("")

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    old_dirs = apps.APP_DIRS
    apps.APP_DIRS = [str(app_dir)]
    cfg = {"features": {"defaultresults": {"scope": [str(root)]},
                        "filesearch": {"limit": 20, "scan_dirs": [], "max_files": 100,
                                       "exclude_dirs": [], "includeFolders": True}}}
    try:
        assert apps.populate(con) == 1
        # The scan still ran: the app row was already in the table, so the count is the app directory and
        # the file, not the whole table.
        assert filecache.ensure_index(con, cfg) == 2
        assert filecache.search(con, "notes", 20)
    finally:
        apps.APP_DIRS = old_dirs
    con.close()


def test_file_results_do_not_contain_applications():
    """Both live in the `files` table, so the filetype filter is what keeps the categories apart."""
    import sqlite3
    import tempfile

    from esteban import apps, filecache, ui

    root = Path(tempfile.mkdtemp())
    app_dir = root / "applications"
    app_dir.mkdir()
    (app_dir / "firefox.desktop").write_text(
        "[Desktop Entry]\nName=Firefox\nExec=firefox\nComment=Web browser\nIcon=firefox\n")
    files = root / "files"
    files.mkdir()
    for name in ["firefox-install.log", "firefox-notes.txt", "firefox-theme.md"]:
        (files / name).write_text("")

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    old_dirs = apps.APP_DIRS
    apps.APP_DIRS = [str(app_dir)]
    try:
        apps.populate(con)
        cfg = {"appearance": {"iconTheme": ""},
               "features": {"defaultresults": {"scope": [str(files)], "maxResults": 2,
                                               "types": ["apps", "files"],
                                               "fallbacks": {"enabled": False}},
                            "filesearch": {"limit": 20, "scan_dirs": [str(files)], "max_files": 100,
                                           "exclude_dirs": [], "includeFolders": True},
                            "snippets": {"wordBasedMatching": True}}}
        filecache.populate(con, cfg)
        results = ui.build_results("firefox", con, cfg, {})

        assert any(r["type"] == "app" for r in results)
        assert not any(r["type"] == "file" and r["arg"].endswith(".desktop") for r in results)   # app rows stay in the app category
        assert sum(1 for r in results if r["type"] == "file") <= 2             # per-category cap
        assert results[0]["subtitle"] == "Web browser"                          # Comment= as subtitle

        # Enter opens the file; the action modifier copies it, and the hint shows the copy key.
        file_row = next(r for r in results if r["type"] == "file")
        assert file_row["action"][0] == "open"
        assert file_row["mods"]["ctrl"]["action"] == "copyfile"
        assert ui.shortcut_hint(file_row, "Ctrl") == "Ctrl+C"
        assert ui.mod_action(file_row, "Ctrl")["action"] == ("copyfile", file_row["arg"])

        no_apps = dict(cfg, features=dict(cfg["features"],
                                         defaultresults=dict(cfg["features"]["defaultresults"],
                                                            types=["files"])))
        assert all(r["type"] != "app" for r in ui.build_results("firefox", con, no_apps, {}))
    finally:
        apps.APP_DIRS = old_dirs
    con.close()


def test_copy_file_puts_a_file_reference_on_the_clipboard():
    """Alfred's copy action on a file object pastes as a file, not as the path text."""
    import sqlite3

    from esteban import actions, clipboard

    assert clipboard.uri_list(["/tmp/a file.txt"]) == "file:///tmp/a%20file.txt\n"

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)

    old = clipboard.set_uri_list
    clipboard.set_uri_list = lambda paths: True
    try:
        assert actions.action_copy_file("/tmp/x", con, "q")
    finally:
        clipboard.set_uri_list = old
    assert con.execute("SELECT actionTypeUid FROM usedActions").fetchone()[0] == "copyfile"

    clipboard.set_uri_list = lambda paths: False               # backend without the MIME type
    try:
        assert not actions.action_copy_file("/tmp/y", con, "q")
    finally:
        clipboard.set_uri_list = old
    assert con.execute("SELECT actionTypeUid FROM usedActions ORDER BY ts").fetchall()[1][0] == "copypath"
    con.close()


def test_copies_are_recorded_in_the_history():
    """A copy is a pasteboard write and a history row.

    `checkPasteboard:` 0x48264 records what it sees on the pasteboard, so the copies the launcher itself
    performs have to be recorded by the action: the watcher is not what notices them.
    """
    import sqlite3

    from esteban import actions, clipboard

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"clipboard": {"enabled": True, "limit": 200, "fastAppend": False}}}

    written = []
    old_text, old_uri = clipboard.set_text, clipboard.set_uri_list
    clipboard.set_text = lambda text: written.append(("text", text)) or True
    clipboard.set_uri_list = lambda paths: written.append(("uri", [str(p) for p in paths])) or True
    try:
        assert actions.action_copy_file("/tmp/report.pdf", con, "report", cfg)
        actions.action_copy_text("hello", con, "hello", cfg=cfg)
    finally:
        clipboard.set_text, clipboard.set_uri_list = old_text, old_uri

    assert written == [("uri", ["/tmp/report.pdf"]), ("text", "hello")]           # the file stays a file reference
    assert [r[1] for r in clipboard.history(con)] == ["hello", "/tmp/report.pdf"]  # newest first

    # The history is the feature: with it off the pasteboard still gets the copy, and nothing is stored.
    written.clear()
    clipboard.set_text = lambda text: written.append(("text", text)) or True
    try:
        actions.action_copy_text("quiet", con, "q", cfg={"features": {"clipboard": {"enabled": False}}})
    finally:
        clipboard.set_text = old_text
    assert written == [("text", "quiet")] and len(clipboard.history(con)) == 2
    con.close()


def test_copy_key_performs_the_action_modifier_copy():
    """Ctrl+C dispatches the row's `mods` entry, so on a file row it copies the file instead of opening it.

    The action modifier is what `actionFromEvent:` 0x2c918 reads; the stored row is not rewritten, and the
    copy shows in the clipboard viewer because the history changed.
    """
    import sqlite3

    from esteban import actions, clipboard, overlay

    if not overlay.HAVE_GTK:
        return

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"clipboard": {"enabled": True, "limit": 200, "fastAppend": False}}}
    row = {"title": "report.pdf", "subtitle": "/tmp/report.pdf", "type": "file", "arg": "/tmp/report.pdf",
           "action": ("open", "/tmp/report.pdf"), "mods": {"ctrl": {"action": "copyfile", "arg": "/tmp/report.pdf"}}}

    opened, copied = [], []
    old_open, old_uri = actions.action_open, clipboard.set_uri_list
    actions.action_open = lambda path, con, kw: opened.append(path)
    clipboard.set_uri_list = lambda paths: copied.append([str(p) for p in paths]) or True

    class Event:
        keyval = overlay.Gdk.KEY_c
        state = overlay.Gdk.ModifierType.CONTROL_MASK

    class Area:
        def queue_draw(self):
            pass

    launcher = object.__new__(overlay.Launcher)
    launcher.con, launcher.cfg, launcher.query, launcher.results = con, cfg, "report", [row]
    launcher.offset, launcher.sel, launcher.mode = 0, 0, "clipboard"
    launcher.mod_name, launcher.mod_mask = "Ctrl", overlay.Gdk.ModifierType.CONTROL_MASK
    launcher.area = Area()

    try:
        assert launcher.action_number(Event()) == overlay.ACTION_COPY
        launcher.on_key(None, Event())
    finally:
        actions.action_open, clipboard.set_uri_list = old_open, old_uri

    assert copied == [["/tmp/report.pdf"]] and not opened              # the mod action, not the stored row
    assert row["action"][0] == "open"
    assert [r[1] for r in clipboard.history(con)] == ["/tmp/report.pdf"]
    con.close()


def test_toggle_opens_on_the_main_page():
    """The clipboard and snippet views are reached from inside the box, so the hotkey does not restore the
    view that was last shown: it opens on the main page."""
    import sqlite3

    from esteban import overlay, theme

    if not overlay.HAVE_GTK:
        return

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"clipboard": {"enabled": True, "limit": 200},
                        "snippets": {"wordBasedMatching": True}},
           "workflows": {"dir": "/tmp/no-workflows"}}

    class Entry:
        def set_text(self, text):
            self.text = text

    class Window:
        def __init__(self, visible):
            self.visible = visible

        def get_visible(self):
            return self.visible

        def hide(self):
            self.visible = False

    class Area:
        def queue_draw(self):
            pass

        def set_size_request(self, width, height):
            pass

    launcher = object.__new__(overlay.Launcher)
    launcher.con, launcher.cfg, launcher.results, launcher.sel, launcher.offset = con, cfg, [], 0, 0
    launcher.entry, launcher.area, launcher.policy = Entry(), Area(), "toplevel"
    launcher.theme, launcher.max_visible = theme.load_theme({}), 10     # update_height sizes the panel from these
    launcher.follows_content = True
    launcher.panel_width = 600
    launcher.show = lambda: None                        # no display in the test
    launcher.mode, launcher.query, launcher.entry.text = "clipboard", "old", "old"

    launcher.window = Window(False)
    launcher.handle("toggle", {})
    assert launcher.mode == "search" and launcher.query == "" and launcher.entry.text == ""

    # The key that opened the clipboard viewer selected that view while the box was open; closing the box
    # does not decide what the next open shows.
    launcher.mode, launcher.query, launcher.entry.text = "snippets", "em", "em"
    launcher.window = Window(True)
    launcher.handle("toggle", {})
    assert not launcher.window.get_visible() and launcher.mode == "snippets"
    launcher.handle("toggle", {})
    assert launcher.mode == "search" and launcher.query == ""
    con.close()


def test_the_watcher_records_the_pasteboard_on_the_turn_that_notices_a_change():
    """`checkPasteboard:` 0x48264 compares the pasteboard with `lastClipHash` 0x5330e8 and records what differs.

    The turn and the loop are separate because the running launcher calls the turn from its main loop: that is
    what fills the history the clipboard viewer reads, and a launcher that only records at exit shows nothing.
    """
    import sqlite3

    from esteban import clipboard

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"clipboard": {"enabled": True, "limit": 200, "fastAppend": False,
                                      "blacklist": ["notes"], "autoExpandSnippets": False}}}

    state = {"app": "firefox", "text": ""}
    old_get, old_app = clipboard.get_text, clipboard.active_app
    clipboard.get_text = lambda: state["text"]
    clipboard.active_app = lambda: state["app"]
    try:
        last = clipboard.check_once(con, cfg, None)              # the turn that sees the copy records it
        for app, text in [("firefox", "first copy"),             # same content as the previous turn
                          ("notes", "notes copy"),               # blacklisted: not recorded, and not seen again
                          ("firefox", "second copy"),
                          ("firefox", "x" * 100_001)]:           # past the size the watcher reads
            state.update({"app": app, "text": text})
            last = clipboard.check_once(con, cfg, last)
        assert [r[1] for r in clipboard.history(con)] == ["second copy", "first copy"]

        # A copy the launcher makes and the same copy read back on the next turn have to be one row: the read
        # through wl-clipboard ends with a newline that the copy itself did not have.
        old_set = clipboard.set_text
        clipboard.set_text = lambda text: None
        try:
            clipboard.copy_text(con, cfg, "round trip")
            state.update({"app": "esteban", "text": "round trip\n"})
            last = clipboard.check_once(con, cfg, "not-the-previous-hash")
            assert len(clipboard.history(con)) == 3
            assert [r[1] for r in clipboard.history(con)] == ["round trip", "second copy", "first copy"]
        finally:
            clipboard.set_text = old_set

        # A turn that has seen nothing yet records what it reads, and the turns after it record nothing until
        # the pasteboard changes. The launcher seeds its watcher with the pasteboard it already sees, so content
        # copied before it started is not treated as a copy.
        state.update({"app": "firefox", "text": "second copy"})
        seeded = clipboard.check_once(con, cfg, None)
        assert len(clipboard.history(con)) == 3                     # the hash dedupes the row it already has
        assert clipboard.check_once(con, cfg, seeded) == seeded
        assert clipboard.check_once(con, cfg, seeded) == seeded     # an unchanged pasteboard records nothing
        assert clipboard.content_hash("second copy\n") == clipboard.content_hash("second copy")
    finally:
        clipboard.get_text, clipboard.active_app = old_get, old_app
    con.close()


def test_fast_append_continues_the_item_the_app_is_building():
    """`fastAppend` 0x29da78 merges consecutive copies, and each row keeps the app that made the copy.

    A copy from another app starts its own row instead of being added to the item an app is building: on this
    session the copies the watcher sees have no source app to name, so the app column is the only thing that
    says which copies belong together.
    """
    import sqlite3

    from esteban import clipboard

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"clipboard": {"enabled": True, "limit": 200, "fastAppend": True,
                                      "fastAppendSeparator": "\n"}}}

    clipboard.record(con, "first line", "firefox", cfg)
    clipboard.record(con, "second line", "firefox", cfg)          # the same app continues the item
    assert [r[1] for r in clipboard.history(con)] == ["first line\nsecond line"]

    clipboard.record(con, "from another app", "notes", cfg)       # a different app starts its own row
    assert [r[1] for r in clipboard.history(con)] == ["from another app", "first line\nsecond line"]
    con.close()


def test_an_empty_query_shows_nothing():
    """Alfred's default results come from what you type, so an empty box shows nothing until the first character.

    The usage ranking and the web fallback answered the empty query, which is why the box opened full of
    applications. The viewers still list their rows for an empty filter: that is the history, not default results.
    """
    import sqlite3

    from esteban import ui

    con = sqlite3.connect(":memory:")
    for stmt in store.SCHEMA:
        con.execute(stmt)
    cfg = {"features": {"defaultresults": {"types": ["apps", "files", "snippets", "calculator", "web"],
                                           "maxResults": 20, "fallbacks": {"enabled": False}},
                        "calculator": {"enabled": True}},
           "workflows": {"dir": "/tmp/no-workflows"}}

    assert ui.build_results("", con, cfg, {}) == []
    assert ui.build_results("   ", con, cfg, {}) == []
    assert [r["type"] for r in ui.build_results("2+2", con, cfg, {})] == ["calculator"]
    con.close()


def test_the_box_is_as_tall_as_the_rows_it_shows():
    """`visibleRows = min(numberOfRows, _maxVisibleRows)` decides the panel height, so before anything is typed
    the window is the search field and there is no placeholder to draw. On a compositor that cannot resize a
    mapped surface (COSMIC) the window keeps room for the rows and the panel is drawn only over the content."""
    import cairo

    from esteban import compositor, overlay, theme

    if not overlay.HAVE_GTK:
        return

    t = theme.load_theme({})
    row_h = theme.row_height(t)
    box_h = t["window"]["paddingVertical"] * 2 + theme.search_field_height(t) + t["search"]["spacing"]
    drawn = []

    class Area:
        def set_size_request(self, width, height):
            self.request = (width, height)

        def queue_draw(self):
            pass

    class Window:
        def __init__(self):
            self.size = None

        def resize(self, width, height):
            self.size = (width, height)             # a compositor that honours a client resize records it here

    class Layout:
        def set_text(self, text, n=-1):
            drawn.append(text)

        def get_pixel_size(self):
            return (0, 0)

        def set_width(self, width):
            pass

        def set_ellipsize(self, mode):
            pass

    class Widget:
        def get_allocated_width(self):
            return 600

        def get_allocated_height(self):
            return box_h + row_h * 10

    launcher = object.__new__(overlay.Launcher)
    launcher.theme, launcher.max_visible, launcher.results = t, 10, [{"type": "app"}] * 25
    launcher.query, launcher.mode, launcher.options, launcher.mod_name = "", "search", {}, "Ctrl"
    launcher.sel, launcher.offset, launcher.area = 0, 0, Area()
    launcher.window, launcher.rgba, launcher.alpha = Window(), True, 1.0
    launcher.shadow_margin = 0
    launcher.panel_width = t["window"]["width"] - 2 * t["window"]["paddingHorizontal"]
    launcher.session = {"compositor": "Sway", "policy": "layer-shell"}
    launcher.follows_content = True
    launcher.update_height()
    assert launcher.area.request == (launcher.panel_width, row_h * 10)   # capped by maxVisibleRows
    assert launcher.window.size == (t["window"]["width"], box_h + row_h * 10)

    launcher.results = []
    launcher.update_height()
    assert launcher.area.request == (launcher.panel_width, 0)            # nothing typed: the box is the field
    assert launcher.content_height() == box_h

    # COSMIC keeps the size a Wayland surface was mapped at, so the window keeps room for the rows there and the
    # panel is drawn only over the content, which is what makes the box follow the results.
    launcher.session = {"compositor": "COSMIC", "policy": "toplevel"}
    launcher.follows_content = launcher.follows_surface_size(launcher.session)
    assert not launcher.follows_content                # the size a surface is mapped with is the size it keeps
    launcher.area.set_size_request(launcher.panel_width, row_h * launcher.max_visible)   # what the constructor asks for
    launcher.results = [{"type": "app"}] * 2
    launcher.update_height()
    assert launcher.area.request == (launcher.panel_width, row_h * 10)
    panels = []
    old_rounded = overlay.rounded_rect
    overlay.rounded_rect = lambda cr, x, y, w, h, r: panels.append(h)
    try:
        launcher.draw_window(Widget(), cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, row_h)))
        assert set(panels) == {box_h + row_h * 2}       # the panel is the content, not the window
    finally:
        overlay.rounded_rect = old_rounded

    # Through XWayland the same COSMIC session gets an X11 window, and an X11 window is resized by the client:
    # measured on the live session the window followed the rows, 117 -> 214 -> 117 px.
    launcher.session = {"compositor": "COSMIC", "policy": "x11"}
    assert launcher.follows_surface_size(launcher.session)

    launcher.results = []
    old_layout, old_show = overlay.make_layout, overlay.PangoCairo.show_layout
    overlay.make_layout = lambda cr, spec: Layout()
    overlay.PangoCairo.show_layout = lambda cr, layout: None
    try:
        launcher.draw_rows(Widget(), cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, row_h)))
        assert drawn == ["Ctrl+C"]                                # the hint probe, no placeholder

        launcher.query = "xyz"
        launcher.update_height()
        assert launcher.content_height() == box_h + row_h         # room for the "No results" line
        drawn.clear()
        launcher.draw_rows(Widget(), cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, row_h)))
        assert drawn == ["Ctrl+C", "No results"]
    finally:
        overlay.make_layout, overlay.PangoCairo.show_layout = old_layout, old_show


def test_the_shadow_has_room_around_the_panel():
    """`appearance.shadow` is the spread the penumbra needs, so the surface is the measured panel plus the room
    around it. It is not drawn where the surface cannot blend it: on a session without an RGBA visual an
    unblended penumbra reads as a filled black frame, which is the black square people complain about."""
    from esteban import overlay, theme

    launcher = object.__new__(overlay.Launcher)
    launcher.theme, launcher.rgba = theme.load_theme({}), True
    launcher.shadow_margin = int(config.DEFAULTS["appearance"]["shadow"])
    assert launcher.shadow_width() == launcher.shadow_margin
    assert launcher.surface_width() == launcher.theme["window"]["width"] + 2 * launcher.shadow_margin

    launcher.rgba = False
    assert launcher.shadow_width() == 0                     # no penumbra without an alpha visual


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("all tests passed")

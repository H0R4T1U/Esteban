"""The results box on Linux — one widget, one policy.

The surface kind is chosen once, from the compositor (see `compositor.py`):

    layer-shell   Hyprland, Sway, Wayfire, KWin, other wlroots-derived compositors: an
                  exclusive overlay surface, which is the only way a client can sit on top of
                  everything and still get keyboard focus.
    toplevel      COSMIC and GNOME: a plain undecorated window. COSMIC does speak
                  wlr-layer-shell, but a commit on a surface whose role was already destroyed
                  is a protocol violation there and the compositor drops the connection, so a
                  launcher that hides and re-shows a layer surface can kill itself; window
                  teardown is fine on COSMIC. Mutter does not implement layer-shell at all.
    x11           a normal undecorated window.
    none          no display session, and the caller falls back to the TUI in `ui.py`.

Look and behaviour are the REA measurements, kept in `theme.py`: width 609, search font 27
(field height 54), row height 49, selection radius `min(roundness, 4)`, scrollbar radius
`min(thickness >> 1, 4)`, the shortcut alpha fade, and the text column at x = 32, all from
`AlfredSelectionList::drawRect:` 0xa0b44 and `AlfredTheme::calculate*` 0x96a80 / 0x968e0 / 0x96af0.

Keys mirror the action numbers recorded from `AlfredKeystrokeHelper::actionFromEvent:` 0x2c918 and
`AlfredSelectionList::performKeyEquivalent:` 0xa1620, including `row + offset - 1` for the number
keys (the number keys address the visible rows) and `highlightNext` 0xa1ad0 wrapping the selection
back to row 0. `advanced.shortcutmod` 0x29a478 = 1 selects Control, otherwise the Super key.

Lifecycle rule, because of the COSMIC behaviour above: the window is never destroyed after it has
been unmapped, and quitting leaves the main loop instead of destroying the window — closing the
display connection ends the session cleanly on every compositor.
"""
from __future__ import annotations

import os
import signal

from . import actions, clipboard, compositor, filecache, icons, ipc, store, theme, ui, workflows
from .config import load_config, warn

ACTION_RUN, ACTION_UP, ACTION_DOWN, ACTION_PGUP, ACTION_PGDN, ACTION_COPY = 1, 4, 5, 6, 7, 11
ACTION_DIRECT_ROW = 0x1A
PI = 3.141592653589793

try:
    import gi

    # Every namespace is pinned before it is imported. Without a pin gi loads whichever version is
    # in the typelib path and warns ("Gtk was imported without specifying a version first"), so on a
    # GTK4-only machine the version actually loaded is not the one the drawing code expects.
    for _namespace, _version in (("GLib", "2.0"), ("Gdk", "3.0"), ("GdkPixbuf", "2.0"),
                                 ("Gtk", "3.0"), ("Pango", "1.0"), ("PangoCairo", "1.0")):
        gi.require_version(_namespace, _version)

    from gi.repository import GLib, Gdk, GdkPixbuf, Gtk, Pango, PangoCairo
    HAVE_GTK = True
    GI_ERROR = ""
except Exception as exc:
    # Two failures that look identical from outside: PyGObject itself is missing (pip),
    # or the system package carrying the typelibs is missing. They need different fixes,
    # so keep the message and let `doctor` show it.
    HAVE_GTK = False
    GI_ERROR = str(exc) or type(exc).__name__

try:
    import cairo
    HAVE_CAIRO = True
except ImportError:
    try:
        import cairocffi                                   # PyGObject also accepts cairocffi
        HAVE_CAIRO = True
    except ImportError:
        HAVE_CAIRO = False

try:
    gi.require_version("GtkLayerShell", "1.0")
    from gi.repository import GtkLayerShell
    HAVE_SHELL = True
except Exception:
    GtkLayerShell = None
    HAVE_SHELL = False


def available() -> bool:
    return HAVE_GTK and HAVE_CAIRO


def unavailable_reason() -> str:
    """Why the results box cannot be drawn — printed by `doctor` and by the TUI fallback."""
    if available():
        return ""
    if HAVE_GTK:
        return "PyGObject is installed but cairo is not (pip install pycairo)"
    if "Namespace Gtk not available" in GI_ERROR or "typelib" in GI_ERROR.lower():
        return f"{GI_ERROR} — that typelib comes from the system GTK package, not from pip"
    return f"PyGObject is not installed ({GI_ERROR})"


def fallback_note(cfg: dict) -> str:
    """One line saying why this session takes the TUI path instead of drawing the box."""
    if not available():
        return unavailable_reason()
    session = compositor.detect()
    if session["policy"] == compositor.NONE:
        return ("no display session (no WAYLAND_DISPLAY and no DISPLAY here) — the overlay needs a "
                "graphical session; a user service started before login does not see it")
    return ""


def mod_action(item, mod_name: str) -> dict:
    """The row as it behaves while the action modifier is held (`mods` in the item contract).

    The contract lives in `ui.py`, so the GUI and the terminal launcher read the same row and the same
    `mods`; Alfred's `actionFromEvent:` 0x2c918 dispatches the copy, never the stored row.
    """
    return ui.mod_action(item, mod_name)


def visible_row_for_action(action: int, offset: int, count: int) -> int | None:
    """Which row a number key means — `row + offset - 1` from 0xa15e0, i.e. the visible rows."""
    if action < ACTION_DIRECT_ROW:
        return None
    row = offset + (action - ACTION_DIRECT_ROW)
    return row if row < count else None


def run(cfg: dict | None = None, con=None, bind_hotkey: bool = False) -> bool:
    """Show the results box; returns False when no window can be used (caller falls back to the TUI)."""
    if not available():
        return False
    cfg = cfg or load_config()
    session = compositor.detect()
    if session["policy"] == compositor.NONE:
        return False

    if not Gtk.init_check():
        warn("Gtk cannot be initialized in this session — using the terminal launcher")
        return False

    try:
        display = Gdk.Display.open("")
    except Exception as exc:
        warn(f"no display available ({exc}) — using the terminal launcher")
        return False
    if con is None:
        con = store.connect()

    launcher = Launcher(cfg, con, session)
    try:
        launcher.build()
    except Exception as exc:
        warn(f"overlay failed ({exc}) — using the terminal launcher")
        con.close()
        return False

    server = ipc.Server(launcher.handle)
    try:
        server.start()
    except RuntimeError as exc:
        warn(str(exc))
        con.close()
        return False
    launcher.server = server
    GLib.timeout_add(100, server.poll)

    listener = None
    if bind_hotkey:
        from . import hotkey

        # pynput listens on its own thread, so the window call goes through the main loop.
        listener = hotkey.bind(cfg, lambda: GLib.idle_add(launcher.show))

    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(launcher.quit))

    def index_files():
        """The results box cannot answer for files until the index has rows.

        `ensure_index` is incremental, so a launch costs one walk of the scope and picks up what appeared
        since the last one, and it runs as an idle callback so the window shows before the scan. The
        results are rebuilt afterwards whatever the scan found, because the box that opened over an empty
        table showed nothing.
        """
        try:
            filecache.ensure_index(con, cfg)
            launcher.rebuild()
            launcher.area.queue_draw()
        except Exception as exc:
            warn(f"file index failed ({exc})")
        return False

    GLib.idle_add(index_files)

    seen = {"hash": None}

    def poll_clipboard():
        """One turn of `checkPasteboard:` 0x48264 from the main loop.

        The clipboard viewer reads the history, and the history is filled by the polling turns: a launcher
        that only records the pasteboard when it exits shows nothing while it runs.
        """
        try:
            seen["hash"] = clipboard.check_once(con, cfg, seen["hash"])
        except Exception as exc:
            warn(f"clipboard poll failed ({exc})")
        return True

    clip = (cfg["features"].get("clipboard") or {})
    if clip.get("enabled") and clipboard.backend() != "none":
        # Alfred starts the watcher with lastClipHash, so what is already on the pasteboard when the launcher
        # starts is not treated as a copy; the copies that arrive after it are.
        seen["hash"] = clipboard.content_hash(clipboard.get_text())
        GLib.timeout_add(int(float(clip.get("interval", 1.0)) * 1000), poll_clipboard)

    launcher.show()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    finally:
        if listener:
            listener.stop()
        server.close()
        try:
            clipboard.record(con, clipboard.get_text(), "esteban", cfg)
        except Exception:
            pass
        con.close()
    return True


# ------------------------------------------------------------------ drawing helpers


def color(value: str, alpha: float = 1.0):
    r, g, b, a = theme.parse_color(value)
    return (r, g, b, a * alpha)


def font_description(spec: dict):
    """The font for a row or the field.

    Theme sizes are pixels in the theme JSON, and the row-height formula uses them as pixels. Pango's
    `size` is points, which renders 1.33x larger at 96 dpi, so the text block came out taller than the
    row measured by `calculateRowHeight` 0x96a80. The size is therefore applied as an absolute size.
    """
    desc = Pango.FontDescription.from_string(spec.get("font") or "Sans")
    desc.set_absolute_size(int(spec["size"]) * Pango.SCALE)
    return desc


def pango_units(pixels: int) -> int:
    """`pango_layout_set_width` takes Pango units, not pixels.

    Passing the pixel width set the wrap width to half a pixel, so every title and subtitle ellipsized
    to a single character — the rows read as icon plus "Enter" with no text. Widths are converted here.
    """
    return max(int(pixels), 1) * Pango.SCALE


def one_line(text: str) -> str:
    return " ".join((text or "").split())


def make_layout(cr, spec: dict):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(font_description(spec))
    return layout


def rounded_rect(cr, x, y, w, h, radius):
    """The rounded rectangle CoreGraphics draws, walked in order.

    Starting the path at the first arc means cairo opens the subpath at the arc's start point and then
    joins the corner centres with straight lines, which folds the path over itself and reads as diagonal
    wedges across the panel and the selection. The path is walked corner to corner instead, and the radius
    is clamped so a rect narrower than the radius cannot fold.
    """
    r = max(int(radius), 0)
    if r == 0:
        cr.rectangle(x, y, w, h)
        return
    r = min(r, w // 2, h // 2)
    cr.new_path()
    cr.move_to(x + r, y)
    cr.arc(x + w - r, y + r, r, -PI / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, PI / 2)
    cr.arc(x + r, y + h - r, r, PI / 2, PI)
    cr.arc(x + r, y + r, r, PI, 3 * PI / 2)
    cr.close_path()


class Launcher:
    def __init__(self, cfg: dict, con, session: dict):
        self.cfg = cfg
        self.con = con
        self.session = session
        self.policy = session["policy"]
        self.theme = theme.load_theme(cfg)
        self.alpha = theme.window_alpha(self.theme, cfg)

        self.mode = "search"
        self.query = ""
        self.sel = 0
        self.offset = 0                     # Alfred's _offset: first visible row
        self.results = []
        self.max_visible = int(cfg["appearance"].get("maxVisibleRows", 10))
        self.options = cfg["appearance"].get("options", {})
        self.mod_name = "Ctrl" if cfg.get("advanced", {}).get("shortcutmod", 1) == 1 else "Super"
        self.mod_mask = Gdk.ModifierType.CONTROL_MASK if self.mod_name == "Ctrl" else Gdk.ModifierType.MOD4_MASK
        self.pixbuf_cache = {}
        self.rgba = False                       # set by build(), draw_window uses it for the corners
        self.server = None

        window = self.theme["window"]
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("esteban")
        self.window.set_resizable(False)
        self.window.set_decorated(False)
        self.window.set_accept_focus(True)
        self.window.set_size_request(window["width"], -1)
        self.window.set_app_paintable(True)

        self.entry = Gtk.Entry()
        self.entry.set_has_frame(False)
        self.entry.set_placeholder_text("Search")
        # calculateSearchFieldHeight 0x968e0: glyph height + 2 * search paddingVertical. Without this the
        # entry takes whatever height the system theme hands it, which is why the field looked different
        # on every desktop.
        self.entry.set_size_request(window["width"] - 2 * window["paddingHorizontal"],
                                    theme.search_field_height(self.theme))

        self.area = Gtk.DrawingArea()
        self.area.set_app_paintable(True)         # the panel behind the rows is drawn by draw_window, not by the system theme
        # The content width stays requested so the rows fill the panel. The height is the rows the box shows
        # (`update_height`), so before anything has been typed it is just the search field — except on a
        # compositor that cannot change a mapped surface's size (COSMIC, measured), where the window keeps the
        # height it was mapped at and has to be mapped with room for the rows from the start; there the panel is
        # drawn only over the content (`draw_window`) so the box still follows the results.
        self.panel_width = window["width"] - 2 * window["paddingHorizontal"]
        self.follows_content = session.get("compositor") not in compositor.NO_CLIENT_RESIZE_COMPOSITORS
        self.area.set_size_request(self.panel_width,
                                   0 if self.follows_content else theme.row_height(self.theme) * self.max_visible)

        # `search.spacing` (8 px) is the measured gap between the field and the first row; the window
        # padding (11 x 12) is the content inset, so nothing sits flush against the panel edge.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.theme["search"]["spacing"])
        box.set_margin_top(window["paddingVertical"])
        box.set_margin_bottom(window["paddingVertical"])
        box.set_margin_start(window["paddingHorizontal"])
        box.set_margin_end(window["paddingHorizontal"])
        box.pack_start(self.entry, False, False, 0)
        box.pack_start(self.area, False, False, 0)
        self.window.add(box)

        self.window.connect("draw", self.draw_window)
        self.window.connect("key-press-event", self.on_key)
        self.window.connect("delete-event", self.on_delete)
        self.area.connect("draw", self.draw_rows)
        self.entry.connect("changed", self.on_entry_changed)
        self.entry.connect("activate", self.on_entry_activate)

    # ------------------------------------------------------------------ surface policy

    def build(self) -> None:
        visual = self.rgba_visual()
        self.rgba = bool(visual)
        if visual:
            self.window.set_visual(visual)          # RGBA, so the rounded corners are transparent
        elif self.alpha < 1.0:
            # Without an RGBA visual the panel cannot be translucent: the alpha is composited as an
            # opaque black rectangle, which is the other thing people read as "transparency looks bad".
            self.alpha = 1.0
            warn("this session has no RGBA visual, so the panel is drawn opaque")
        self.apply_css()
        if self.policy == compositor.LAYER_SHELL and HAVE_SHELL and GtkLayerShell.is_supported():
            self.use_layer_shell()
        else:
            self.window.set_position(Gtk.WindowPosition.CENTER)

    def rgba_visual(self):
        """The RGBA visual when the session has one; None on a session that does not."""
        try:
            screen = Gdk.Display.get_default().get_default_screen()
            return screen.get_rgba_visual() if screen else None
        except Exception:
            return None

    def apply_css(self) -> None:
        search = self.theme["search"]
        provider = Gtk.CssProvider()
        provider.load_from_data(
            (".esteban-search { font-family: \"%s\"; font-size: %dpx; padding: %dpx %dpx; "
             "background-color: transparent; color: %s; caret-color: %s; border: none; }\n"
              ".esteban-rows { background-color: transparent; border: none; }\n"
             % (search["text"].get("font") or "Sans", search["text"]["size"],
                search["paddingVertical"], search["paddingHorizontal"],
                theme.css_color(search["text"]["color"]),
                theme.css_color(search["text"]["colorSelected"]))).encode())
        self.entry.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.entry.get_style_context().add_class("esteban-search")
        self.area.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.area.get_style_context().add_class("esteban-rows")

    def use_layer_shell(self) -> None:
        """An exclusive overlay surface. Anchoring the top edge is what lets the compositor
        hand keyboard focus to it when it is mapped."""
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusivity(self.window, GtkLayerShell.Exclusivity.NONE)
        GtkLayerShell.set_anchor_edge(self.window, GtkLayerShell.Edge.TOP, True)
        try:
            GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        except Exception:
            pass

        width, height = self.monitor_size() or (0, 0)
        margin = int(self.cfg["appearance"].get("position", {}).get("margin", 140))
        left = max(0, (width - self.theme["window"]["width"]) // 2)
        GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.TOP, margin)
        GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.LEFT, left)

    def monitor_size(self):
        """The screen size for centring; None when the display exposes no monitor."""
        try:
            monitor = Gdk.Display.get_default().get_monitor(0)
            if monitor:
                geometry = monitor.get_geometry()
                return geometry.width, geometry.height
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ window

    def on_delete(self, widget, event):
        """Leave the main loop without destroying the window: a destroy after an unmap is the
        order COSMIC reports as a protocol violation, and exiting the loop closes the connection
        instead."""
        self.quit()
        return True

    def quit(self) -> None:
        Gtk.main_quit()

    def visible_rows(self) -> int:
        """`visibleRows = min(numberOfRows, _maxVisibleRows)`."""
        rows = min(len(self.results), self.max_visible)
        if not rows and self.query:
            rows = 1                        # a typed query that matches nothing keeps one row of height
        return rows

    def content_height(self) -> int:
        """The height the content needs: paddings + the field + the gap + the rows it shows."""
        t = self.theme
        return (t["window"]["paddingVertical"] * 2 + theme.search_field_height(t)
                + t["search"]["spacing"] + theme.row_height(t) * self.visible_rows())

    def draw_window(self, widget, cr):
        t = self.theme["window"]
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        if self.rgba:
            # Only the part the content fills is painted, so the box reads as the search field plus the rows
            # it has rather than a tall empty panel: the rest of the surface stays transparent.
            h = min(h, self.content_height())
        r, g, b, _ = theme.parse_color(t["color"])
        cr.set_source_rgba(r, g, b, self.alpha)
        if self.alpha >= 1.0 and not self.rgba:
            # An opaque panel must not depend on the compositor honouring surface alpha: the area
            # outside the rounded rectangle would be cleared and read as black, which is the black
            # square around the panel people complain about. Fill the whole window instead.
            cr.rectangle(0, 0, w, h)
            cr.fill()
        else:
            # With an RGBA visual the corner pixels really are transparent, so the panel keeps the
            # roundness the theme JSON measures (32) instead of reading as a sharp rectangle.
            rounded_rect(cr, 0, 0, w, h, t["roundness"])
            cr.fill()
        if t.get("borderPadding"):
            cr.set_source_rgba(*theme.parse_color(t["borderColor"]))
            rounded_rect(cr, 0, 0, w, h, t["roundness"])
            cr.set_line_width(t["borderPadding"])
            cr.stroke()
        return False                       # the entry and the rows draw on top

    # ------------------------------------------------------------------ results

    def rebuild(self) -> None:
        if self.mode == "search":
            self.results = ui.build_results(self.query, self.con, self.cfg,
                                            workflows.load_workflows(self.cfg, self.con))
        elif self.mode == "clipboard":
            self.results = ui.clipboard_results(self.con, self.query, self.cfg, 20)
        else:
            self.results = ui.snippet_results(self.con, self.query, self.cfg, 20)
        if self.sel >= len(self.results):
            self.sel = max(len(self.results) - 1, 0)
        self.offset = 0
        self.update_height()

    def update_height(self) -> None:
        """The box is as tall as the rows it shows, so it starts as the search field.

        Where the compositor lets the client change the size of a mapped surface the size request does it and a
        `resize` is asked for as well; on COSMIC both are ignored after mapping (measured), so the window is
        mapped with room for `maxVisibleRows` and `draw_window` paints the panel only over the content instead —
        which is what makes the box follow the number of results there.
        """
        if self.follows_content:
            self.area.set_size_request(self.panel_width, theme.row_height(self.theme) * self.visible_rows())
        try:
            self.window.resize(self.theme["window"]["width"], self.content_height())
        except Exception:
            pass
        self.area.queue_draw()

    def set_query(self, query: str) -> None:
        self.query = query
        self.sel = 0
        self.rebuild()
        self.area.queue_draw()

    def draw_rows(self, widget, cr):
        t = self.theme["result"]
        row_h = theme.row_height(self.theme)
        visible = min(len(self.results), self.max_visible)
        width = widget.get_allocated_width()
        pad_h = t["iconPaddingHorizontal"]
        icon_size = t["iconSize"]
        text_x = pad_h + icon_size + 1        # drawRect's text column, x = 32 with the default icon
        gap = t["textSpacing"]

        # The hint column is reserved before the text is laid out: a long path stops before the shortcut
        # instead of running underneath it.
        hint_w = 0
        if not self.options.get("hideshortcuts"):
            probe = make_layout(cr, t["shortcut"])
            probe.set_text(f"{self.mod_name}+C", -1)
            hint_w = probe.get_pixel_size()[0] + pad_h
        text_w = max(width - text_x - hint_w - pad_h, 20)

        if not self.results:
            if not self.query:
                return False              # nothing typed yet: an empty box draws nothing
            empty = make_layout(cr, t["subtext"])
            empty.set_text("No results", -1)
            cr.set_source_rgba(*color(t["subtext"]["color"]))
            cr.move_to(text_x, max(t["paddingVertical"], (row_h - empty.get_pixel_size()[1]) // 2))
            PangoCairo.show_layout(cr, empty)
            return False

        for i in range(visible):
            row = self.offset + i
            if row >= len(self.results):
                break
            item = self.results[row]
            y = i * row_h
            selected = row == self.sel

            if selected:
                cr.set_source_rgba(*theme.parse_color(t["backgroundSelected"]))
                rounded_rect(cr, 0, y, width, row_h, theme.selection_radius(self.theme))
                cr.fill()

            self.draw_icon(cr, item, pad_h, y + max(t["paddingVertical"], (row_h - icon_size) // 2), icon_size)

            title = make_layout(cr, t["text"])
            title.set_text(one_line(item["title"]), -1)
            title.set_width(pango_units(text_w))
            title.set_ellipsize(Pango.EllipsizeMode.END)
            sub = make_layout(cr, t["subtext"])
            sub.set_text(one_line(item["subtitle"]), -1)
            sub.set_width(pango_units(text_w))
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            title_h, sub_h = title.get_pixel_size()[1], sub.get_pixel_size()[1]
            # The block is centred in the row with the glyph heights, not the nominal ones, so a row whose
            # text is taller than `textSize + textSpacing + subtextSize` still fits inside `rowHeight`.
            top = y + max(0, (row_h - (title_h + gap + sub_h)) // 2)

            cr.set_source_rgba(*color(t["text"]["colorSelected"] if selected else t["text"]["color"]))
            cr.move_to(text_x, top)
            PangoCairo.show_layout(cr, title)

            cr.set_source_rgba(*color(t["subtext"]["colorSelected"] if selected else t["subtext"]["color"]))
            cr.move_to(text_x, top + title_h + gap)
            PangoCairo.show_layout(cr, sub)

            if not self.options.get("hideshortcuts"):
                hint = make_layout(cr, t["shortcut"])
                hint.set_text(ui.shortcut_hint(item, self.mod_name), -1)
                sw, sh = hint.get_pixel_size()
                alpha = theme.shortcut_alpha(row, self.sel, visible)
                cr.set_source_rgba(*color(t["shortcut"]["colorSelected"] if selected
                                          else t["shortcut"]["color"], alpha))
                cr.move_to(width - sw - pad_h, y + (row_h - sh) // 2)
                PangoCairo.show_layout(cr, hint)

        if self.options.get("showscrollbar") and len(self.results) > visible:
            sb = self.theme["scrollbar"]
            thickness, radius = sb["thickness"], theme.scrollbar_roundness(self.theme)
            bar_h = max(row_h * visible * visible / len(self.results), row_h)
            y = bar_h * self.offset / max(len(self.results) - visible, 1)
            cr.set_source_rgba(*theme.parse_color(sb["color"]))
            rounded_rect(cr, width - thickness, y, thickness, bar_h, radius)
            cr.fill()
        return False

    def draw_icon(self, cr, item, x, y, size):
        path = item.get("icon")
        if path and not os.path.isabs(path):
            path = icons.resolve(path, size, self.cfg)     # an icon-theme name from a desktop entry
        if path:
            pixbuf = self.pixbuf_cache.get(path)
            if pixbuf is None:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
                except Exception:
                    pixbuf = False
                self.pixbuf_cache[path] = pixbuf
            if pixbuf:
                cr.save()
                cr.translate(x, y)
                Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                cr.paint()
                cr.restore()
                return

        cr.save()
        cr.set_source_rgba(*theme.parse_color(self.theme["result"]["backgroundSelected"]))
        rounded_rect(cr, x, y, size, size, min(6, size // 4))
        cr.fill()
        badge = make_layout(cr, {"font": "Sans", "size": max(size // 2, 10)})
        badge.set_text((item["title"] or "?")[:1].upper(), -1)
        cr.set_source_rgba(*color(self.theme["result"]["text"]["colorSelected"]))
        cr.move_to(x + size / 4, y + size / 4)
        PangoCairo.show_layout(cr, badge)
        cr.restore()

    # ------------------------------------------------------------------ keys

    def action_number(self, event) -> int:
        key = event.keyval
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return ACTION_RUN
        if key == Gdk.KEY_Up:
            return ACTION_UP
        if key == Gdk.KEY_Down:
            return ACTION_DOWN
        if key == Gdk.KEY_Page_Up:
            return ACTION_PGUP
        if key == Gdk.KEY_Page_Down:
            return ACTION_PGDN
        if key in (Gdk.KEY_c, Gdk.KEY_C) and event.state & self.mod_mask:
            return ACTION_COPY
        if event.state & self.mod_mask and Gdk.KEY_1 <= key <= Gdk.KEY_9:
            return ACTION_DIRECT_ROW + (key - Gdk.KEY_1)
        return 0

    def on_key(self, widget, event):
        action = self.action_number(event)
        if action == ACTION_RUN:
            self.perform(self.offset + self.sel)
            return True
        if action == ACTION_COPY:
            # `actionFromEvent:` 0x2c918 dispatches the copy the action modifier defines, so Ctrl+C on a file
            # row is the file copy, not the row's default action. The TUI reads the same `mods`.
            self.perform(self.offset + self.sel, self.mod_name)
            return True
        if action == ACTION_UP:
            self.sel = max(self.sel - 1, 0)
            self.area.queue_draw()
            return True
        if action == ACTION_DOWN and self.results:
            self.sel = (self.sel + 1) % len(self.results)      # highlightNext 0xa1ad0 wraps
            self.area.queue_draw()
            return True
        if action in (ACTION_PGUP, ACTION_PGDN):
            target = self.sel - self.max_visible if action == ACTION_PGUP else self.sel + self.max_visible
            self.sel = max(0, min(target, max(len(self.results) - 1, 0)))
            self.area.queue_draw()
            return True
        if action >= ACTION_DIRECT_ROW:
            row = visible_row_for_action(action, self.offset, len(self.results))
            if row is not None:
                self.perform_direct(row)
            return True

        key = event.keyval
        if key == Gdk.KEY_Escape:
            if self.query:
                self.entry.set_text("")
                self.set_query("")
            else:
                self.window.hide()
            return True
        if not (event.state & self.mod_mask):
            return False                   # typing goes to the search field
        if key == Gdk.KEY_v:
            self.mode = "clipboard"
        elif key == Gdk.KEY_s:
            self.mode = "snippets"
        elif key in (Gdk.KEY_p, Gdk.KEY_P):            # copy path
            self.run_action("copypath")
            return True
        elif key in (Gdk.KEY_t, Gdk.KEY_T):            # browse in terminal
            self.run_action("terminal")
            return True
        elif key in (Gdk.KEY_e, Gdk.KEY_E):            # paste keystroke
            clipboard.paste()
            return True
        elif key in (Gdk.KEY_q, Gdk.KEY_Q):
            self.quit()
            return True
        else:
            return False
        self.entry.set_text("")
        self.set_query("")
        return True

    def run_action(self, kind: str) -> None:
        if not self.results:
            return
        item = self.results[self.offset + self.sel]
        target = item.get("path") or item.get("arg") or ""
        if kind == "copypath":
            actions.action_copy_path(target, self.con, self.query)
        elif kind == "terminal":
            actions.action_terminal(target, self.cfg, self.con, self.query)
        self.area.queue_draw()

    def perform_direct(self, row: int) -> None:
        """Direct action row (0xa15e0): fire the row's `mods` entry for the action modifier."""
        if row < 0 or row >= len(self.results):
            return
        self.perform(row, self.mod_name)

    def perform(self, index: int, mod: str | None = None) -> None:
        if not self.results or index < 0 or index >= len(self.results):
            return
        self.perform_item(self.results[index], mod)

    def perform_item(self, item, mod: str | None = None) -> None:
        item["keyword"] = self.query
        follow = ui.action_for(item, self.con, self.cfg, mod)
        if follow:
            self.results = follow
            self.offset, self.sel = 0, 0
            self.mode = "search"
        elif self.mode == "clipboard" and item["action"][0] in ("copy", "copyfile", "copypath"):
            self.rebuild()          # the history changed, so the viewer shows the copy
        self.area.queue_draw()

    def on_entry_changed(self, entry):
        self.set_query(entry.get_text())

    def on_entry_activate(self, entry):
        self.perform(self.offset + self.sel)

    # ------------------------------------------------------------------ ipc

    def handle(self, command: str, payload: dict) -> dict:
        if command == "toggle":
            if self.window.get_visible():
                self.window.hide()
            else:
                self.open_main()
        elif command == "show":
            self.open_main()
        elif command == "hide":
            self.window.hide()
        elif command == "query":
            query = str(payload.get("query", ""))
            self.mode = "search"                  # a query is the main page, not the last view
            self.entry.set_text(query)
            self.set_query(query)
            self.show()
        elif command == "quit":
            self.quit()
        return {"ok": True, "mode": self.mode, "rows": len(self.results),
                "policy": self.policy, "pid": os.getpid()}

    def open_main(self) -> None:
        """Open the box on the default results view.

        The clipboard and snippet views are reached from inside the box with their own keys, so coming back
        through the hotkey does not restore the view that was last shown: the box opens on the main page with
        an empty search box.
        """
        self.mode = "search"
        self.entry.set_text("")
        self.set_query("")
        self.show()

    def show(self) -> None:
        self.window.show_all()
        try:
            self.window.present()           # ask for focus on a plain window; a layer surface gets it when mapped
        except Exception:
            pass
        try:
            self.entry.grab_focus()
        except Exception:
            pass

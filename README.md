# esteban

A launcher for Linux modeled on Alfred 5. A global hotkey opens a results box, typing filters the rows,
Enter runs the row's action, and the box is as tall as the rows it shows.

**Language:** Python 3. **Interface:** the GTK3 results box, with the terminal launcher as fallback when
there is no display session. The surface kind is chosen from the compositor — layer-shell on the
wlroots-derived compositors including COSMIC, plain window on GNOME, normal window on X11.

esteban is an independent implementation written from reverse-engineering evidence of the shipped macOS
app: the feature set, the database schema, the geometry and the behaviour are what the analysis measured,
not what was guessed. No code or assets from Alfred are copied, and nothing calls its private APIs. Where
macOS has no Linux equivalent, the substitute is named where it is used — XDG desktop entries for
Spotlight/LaunchServices, a polling watcher for the pasteboard change callback, the compositor keybinding
plus a Unix socket for Carbon `RegisterEventHotKey`, `xdotool`/`ydotool` for CGEvent posting.

Alfred is a trademark of Running with Crayons Ltd. esteban is not affiliated with or endorsed by them.

The full analysis — classes, frameworks, the files Alfred writes, and the code pointer for every feature —
is in [`docs/REA_REPORT.md`](docs/REA_REPORT.md), with the finding-by-finding record in
[`FINDINGS.md`](FINDINGS.md). The measured geometry is reproduced in `esteban/theme.py` and drawn by
`esteban/overlay.py`; [`docs/preview.svg`](docs/preview.svg) renders the results box from those formulas.

## Quick start

```bash
pip install ".[overlay,hotkey]"     # esteban + PyGObject (overlay) + pynput (X11 hotkey)
esteban index                       # build the XDG app index and the file index
esteban                             # open the box; falls back to the terminal launcher without a display
```

The typelibs have to come from the system, not from pip, so the overlay needs the GTK3 and Pango packages
(`gtk3`, `pango`, `gobject-introspection`, `python-gobject`, `pycairo`). For the layer-shell path install
`gtk-layer-shell`; for the clipboard path install `wl-clipboard` or `xclip`, and `ydotool` for simulated
paste. `esteban doctor` names whatever the machine is missing.

The hotkey is **Alt+Space**, mirroring Alfred's Option+Space default. Wayland compositors own global keys,
so the key is bound in the compositor and points at `esteban toggle`; on X11 the daemon binds it directly.
See [Global hotkey](#global-hotkey).

## What works today

- **Results box**: the measured geometry (row height 49 px, window width 609 px, roundness 32, text column
  at 32 px), selection fade, `Down` wraps to row 0, number keys with the action modifier fire the row's
  `mods` action. The box height follows `min(numberOfRows, maxVisibleRows)`, so it does not keep empty space.
- **Apps**: XDG `.desktop` index, Enter launches the `Exec=` line, the freedesktop icon theme resolves the
  row icon column.
- **Files and folders**: incremental index over `features.filesearch.scan_dirs`, folders indexed so a folder
  row can be opened, per-category caps, `features.defaultresults.types` decides which categories may appear.
- **Copying**: the action modifier copies. On a file row that is the file itself as `text/uri-list`, which is
  what a file manager pastes as a file; on a text row it is the text. Every copy is its own history entry
  (`fastAppend` is off by default), deduped by `dataHash`, with `persistFor` expiry and a source-app blacklist.
- **Snippets** with dynamic placeholders, **calculator**, **web search** with `{query}` templates and URL
  history, **workflows** (`info.plist` objects and connections, script-filter items), **Universal Actions**
  (open, copy, copy path, terminal, reveal), **usage ranking** (knowledge weight, strong latching, 30-day window).
- **Single instance** over a Unix socket, so the hotkey shows or hides the running instance, and a daemon
  that owns that socket.
- **Terminal launcher** as fallback, sharing the row contract and the row builders with the overlay.

## Keys

`Enter` runs the row's action · action modifier (Control when `advanced.shortcutmod` is 1, otherwise Super)
`+C` copies, `+P` copies the path as text, `+T` opens the folder in the terminal, `+E` sends the paste
keystroke · number keys with the action modifier run the row's `mods` action · `Up`/`Down` navigate, `Down`
wraps · `PgUp`/`PgDn` page · `Ctrl+V` clipboard viewer · `Ctrl+S` snippet viewer · `Esc` clears the query,
then hides the window · `Ctrl+Q` quits.

The default hotkey is Alt+Space; the clipboard viewer also has the configured Alt+Shift+V.

## Configuration

`~/.esteban/config.json` (defaults in `config.py`, `ESTEBAN_HOME` moves the data dir). Database:
`~/.esteban/Databases/esteban.alfdb`, using Alfred's table names. Workflows: directories containing an
`info.plist` with `objects` and `connections`. Themes: `~/.esteban/themes/<name>.json` in Alfred's theme
JSON schema (`alfredtheme` root, `#RRGGBBAA` colours).

```json
{
  "appearance": {
    "theme": "dark",
    "iconTheme": "breeze",
    "maxVisibleRows": 10,
    "position": { "anchor": "top", "margin": 140 },
    "transparency": "off",
    "shadow": 16,
    "hairline": true
  },
  "advanced": { "shortcutmod": 1, "latching": true },
  "features": {
    "defaultresults": {
      "maxResults": 20,
      "types": ["files", "snippets", "calculator", "web"]
    },
    "filesearch": {
      "limit": 20,
      "scan_dirs": ["~/Desktop", "~/Documents", "~/Downloads", "~"],
      "includeFolders": true
    },
    "clipboard": { "limit": 200, "interval": 1.0, "fastAppend": false }
  }
}
```

## Which surface the results box uses

The policy is decided once, from the session (`compositor.py`, printed by `esteban doctor`):

| Session | Surface | Why |
|---|---|---|
| Hyprland, Sway, Wayfire, River, KDE Plasma (KWin), other wlroots-derived compositors | wlr-layer-shell overlay | an exclusive layer surface is the only way a client sits above everything, and it gets keyboard focus when mapped |
| COSMIC (cosmic-comp) | wlr-layer-shell overlay | COSMIC decorates a plain window, toplevel or X11, with its own rounded outline and titlebar around the whole surface, which is what makes a box that sizes itself to its content read as a framed window. A layer surface is not decorated, so it is the only way to get just the panel; that path needs the `GtkLayerShell` typelib (`gtk-layer-shell`). Without it the box can only be a normal window: an X11 window through XWayland loses its titlebar, because cosmic-comp honours the Motif no-decorations hint GTK3 sets, but keeps the outline, which the compositor draws for the focused window whatever the client asks for. |
| GNOME | plain undecorated window | Mutter does not implement layer-shell |
| X11 | normal undecorated window | no layer-shell protocol; a window manager that honours the Motif hint leaves no titlebar |
| no display session | the terminal launcher in `ui.py` | nothing to draw on |

`ESTEBAN_SURFACE=layer-shell|toplevel|x11|none` overrides the choice.

Two rules follow from the COSMIC behaviour and hold on every compositor: a layer surface is never destroyed
after it has been unmapped, and quitting leaves the main loop instead of destroying the window, so closing
the display connection ends the session cleanly and no commit is ever sent on a roleless surface.

The box is as tall as the rows it shows: `visible_rows()` is min(`numberOfRows`, `_maxVisibleRows`), which is
what `calculateSearchFieldHeight` 0x968e0 and `calculateRowHeight` 0x96a80 add up to. On a compositor that
honours a client resize the window follows that height. On COSMIC it does not: the surface keeps the size it
had when it was mapped, so there the box is mapped with room for `maxVisibleRows` and the panel is drawn only
over the content, which is what makes the visible box still grow and shrink with the results. The fixed area
is the one thing this cannot fix — a layer surface takes pointer input over its whole area, so a click in the
transparent part below the panel does not reach the window behind it.

## The panel as a card

Nothing on Linux blurs the wallpaper behind the panel, so the measured colour alone reads as a flat shape
pasted on the screen rather than a card floating above it. `appearance.shadow` is the spread around the panel
(16 px, 0 turns it off); cairo has no blur, so the penumbra is built from rings of rounded rectangles,
outermost and faintest first, that pile up towards the edge. When the theme's `borderPadding` is 0 the panel
edge gets a 1 px hairline, because a panel with no decoration around it reads better with one;
`appearance.hairline` turns that line off on its own. Both are look choices, not evidence: the colours,
padding, roundness and row geometry stay as measured, and the surface is the measured panel width plus the
room the penumbra needs. Without an RGBA visual the shadow is not drawn at all, because an unblended penumbra
is a filled black frame.

### Transparency

The measured window colour is `#1E1E22E6`, alpha 0.90, and Alfred draws it over an `NSVisualEffectView` blur
while the theme's own `blur` key is 0. GTK has no blur, so on a compositor that cannot blur (COSMIC, Mutter)
the same colour is a flat translucent film: over a busy wallpaper the panel reads muddy, and the rounded
corners let the desktop show through.

`appearance.transparency` controls it, and `esteban theme` prints the value in effect:

| Value | Effect |
|---|---|
| `"off"` (default) | opaque panel in the measured colour `#1E1E22` |
| `"theme"` | the measured alpha, 0.90 — flat on any compositor that cannot blur |
| `0`–`1` | the alpha to use |

The default is opaque because nothing on Linux blurs: the same colour that reads as frosted glass on macOS
reads as a translucent film over the wallpaper here. Compositors that blur (KWin, Hyprland with a blur
plugin) are where `"theme"` looks closer to Alfred. Only the panel behind the rows changes; the row,
selection, text and border colours stay as measured. When the panel is opaque it is filled as the whole
window rectangle rather than only the rounded rectangle, so it does not depend on the compositor honouring
surface alpha — otherwise the corners are cleared and read as black.

Two other things worth checking on a COSMIC session:

- **No RGBA visual.** Without one the compositor paints the alpha as an opaque black rectangle, so the panel
  looks like a black box rather than a translucent one. `overlay.py` asks for `Gdk.Screen.get_rgba_visual()`
  and, when the session has none, draws the panel opaque and says so instead of drawing black. A Wayland
  surface has to carry alpha for any translucency at all.
- **The compositor's decoration.** An undecorated GTK3 toplevel on COSMIC still gets the compositor's own
  rounded corners, outline and active hint around the whole surface, which doubles up with the 32 px radius
  drawn here. A client cannot turn that off on a toplevel, so COSMIC is on the layer-shell side of the policy
  table.
- **The system theme painting over the rows.** COSMIC themes GTK3 apps, so a `DrawingArea` that is not
  app-paintable receives the theme's opaque background — a solid block inside the panel, with the panel colour
  only around it. The rows area is app-paintable with a transparent CSS background, so the panel is drawn by
  one fill and the rows draw on top of it.

## Commands

```bash
esteban index          # build the XDG app index and file index
esteban                # overlay; falls back to the terminal launcher when no display exists
esteban overlay        # overlay only (`gui` still works as an alias)
esteban tui            # terminal launcher only
esteban toggle         # show/hide the running instance (the Wayland keybinding target)
esteban daemon         # the instance that owns the toggle socket
esteban watch          # clipboard watcher
esteban theme          # print the measured geometry
esteban doctor         # compositor, surface policy, PyGObject, clipboard backend, tty
esteban keybind        # the compositor keybinding entry for the configured combo
esteban search "sf"    # non-interactive fuzzy search
esteban clip 20        # clipboard history
esteban snippet em     # expand a snippet
esteban calc "2^10"
esteban run hello
```

Installing is what makes `esteban` available outside the project directory. Without it the package only runs
from the checkout (`python3 -m esteban.main ...` from the project root), and anything that has to name a
file — a desktop shortcut, a systemd user service, an autostart entry — cannot use a bare `esteban`, because
it is execed with the PATH the compositor or systemd was started with, not the login shell's. `bin/esteban`
is the alternative for an uninstalled checkout: it resolves its own location, puts the project root on
`sys.path`, and works from any directory, so an absolute path to it is a valid target.

## Global hotkey

Wayland compositors own global keys, so bind the key in the compositor and point it at `esteban toggle`,
which sends the command to the running instance over `$XDG_RUNTIME_DIR/esteban.sock`. On X11
`esteban daemon` binds Alt+Space directly with pynput.

**COSMIC**: COSMIC Settings → Keyboard → Custom Shortcuts, add a shortcut whose command is
`esteban toggle`. The same list is plain text at
`~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom`, and that file is a RON **map**, so each
entry is a `key: value` pair:

```text
{
    (
        modifiers: [
            Alt,
        ],
        key: "space",
    ): Spawn("/home/you/.local/bin/esteban toggle"),
}
```

Three things in that file are easy to get wrong, and each one makes the key look dead:

- `Spawn` takes **one string**, the whole command line, because cosmic-comp execs it as
  `/bin/sh -c <that string>`. Writing the command and its argument as two arguments is not the grammar, and
  cosmic-comp skips the entry with `Expected closing )`.
- entries are comma-separated. A missing separator comma makes the whole file unparseable
  (`ExpectedComma` in `journalctl --user`), which drops every custom shortcut at once.
- keys are stored as lowercase keysym names (`"space"`, `"4"`, `"dollar"`) with function keys as written
  (`"F12"`), so a capitalised `"Space"` never matches.
- the program has to be named as a file, because the entry is execed with the compositor's PATH, not a
  shell's — `esteban keybind` uses the installed launcher, or `bin/esteban` of the checkout when nothing is
  installed, and prints which one it used.

`esteban keybind` prints the entry for the configured combo with the resolved launcher path, says whether
that entry is already in the file, and whether an instance is answering on the socket.
`esteban keybind --write` appends it — only when the file is already the map the settings UI writes, keeping
existing entries and leaving nothing beside the file: every file under `/v1/` is read as a config key, so a
backup there breaks the whole reload. After writing, cosmic-settings-daemon has to read the file again
(relogin, or `systemctl --user restart cosmic-settings-daemon`). If a hand-written entry is not picked up on
a given build, add the same shortcut through COSMIC Settings — that path is the reliable one
(pop-os/cosmic-epoch#2481).

If the key does nothing, check in this order:

1. `cat ~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom` — the entry has to be inside the
   map, with `key: "space"` as written by the file, and the command as an absolute path.
2. `esteban keybind` — it says whether the entry is in the file, whether the launcher path resolves, and
   whether anything is answering on the socket.
3. Test the key on its own before blaming esteban: bind Alt+Space to the single string
   `/usr/bin/touch /tmp/keypress`. If the file appears, the compositor is grabbing the key and the problem is
   on the esteban side; if it does not, the chord never reaches the compositor (`wev` shows whether a key
   reaches an app).
4. Check `journalctl --user` for the parse errors above — a rejected entry or a missing comma is reported
   there the moment cosmic-comp reads the file, and nothing runs until the file parses.
5. The key only fires a command, and the command needs a listening instance: run `esteban daemon` in a
   terminal and press the key — the terminal prints `toggle -> running instance`. Nothing visible happens
   when nothing is listening, because a shortcut spawns a process with no terminal to print in.
6. Restart the settings daemon (`systemctl --user restart cosmic-settings-daemon`) or log out and back in
   after editing the file.

`Super` already opens the COSMIC launcher, so pick a free key.

Other compositors:

- Hyprland / Sway: `binds = ALTSPACE, exec = "esteban toggle"`
- KDE Plasma: System Settings → Shortcuts → an action that runs `esteban toggle`
- GNOME: Settings → Keyboard → Custom Shortcuts (the overlay is a normal window there)

The key only works while an instance is listening, so start `esteban daemon` at session start (a startup
entry or a systemd user service). The daemon is the instance that owns the socket: on a display it runs the
overlay and shows or hides itself when the key fires; headless it only listens and opens a terminal launcher.
`toggle` and the daemon must see the same `XDG_RUNTIME_DIR` — the client looks for the socket there and falls
back to the data dir, so a mismatch means the key appears to do nothing.

```ini
# ~/.config/systemd/user/esteban.service
[Unit]
Description=esteban instance (owns the toggle socket)

[Service]
ExecStart=%h/.local/bin/esteban daemon
Restart=on-failure

[Install]
WantedBy=default.target
```

A user service starts before the session exports `WAYLAND_DISPLAY`, so it comes up headless; either start
the daemon inside the session or import the variable once per login
(`systemctl --user import-environment WAYLAND_DISPLAY`). A layer surface needs `WAYLAND_DISPLAY` to connect,
and X11 through XWayland needs `DISPLAY`.

On wlroots compositors (Hyprland, Sway, KWin, Wayfire, COSMIC) an exclusive layer-shell surface receives
keyboard focus when it is mapped, so hiding and re-showing it keeps the typing path working. On GNOME the
overlay is an ordinary window and focus follows the usual window rules. On COSMIC focus was measured on the
X11 window through XWayland — on the first show and after every hide/show cycle — but not yet on a real layer
surface, because that needs the typelib.

## If esteban falls back to the terminal launcher

`esteban doctor` prints the reason it takes the terminal path; the usual ones:

- **PyGObject is there but the `Gtk-3.0` typelib is not.** The typelib comes from the system GTK package,
  not from pip. Debian/Ubuntu: `sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
  gir1.2-pango-1.0`. Arch: `sudo pacman -S python-gobject python-cairo gobject-introspection gtk3 pango`.
  A `pip install pygobject` inside a venv only gives the bindings; the typelibs must still be on the system,
  and the venv must be the one that runs `esteban`.
- **pycairo (or cairocffi) is missing** — `PangoCairo` and the drawing path need it. The `cairo` line in
  `doctor` shows this separately from PyGObject.
- **A different Python is running.** A venv or pipx environment cannot see the system `python3-gi` at all,
  so inside it only `pip install pygobject pycairo` works; otherwise create the venv with
  `--system-site-packages`. `doctor` prints `interpreter` and, when it is inside a venv, says this.
  Check the same interpreter `esteban` uses: `which esteban`, then
  `python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print('ok')"`.
- **A namespace pin failed, which is what the warning means.** `overlay.py` pins every namespace before
  importing it (`GLib 2.0`, `Gdk 3.0`, `GdkPixbuf 2.0`, `Gtk 3.0`, `Pango 1.0`, `PangoCairo 1.0`). If gi says
  a namespace "was imported without specifying a version first", the pin for it failed and gi loaded whatever
  version the typelib path had — usually Gtk 4.0 on a system that only carries GTK4. Every pin has to resolve
  for the overlay to draw:

  ```bash
  python3 - <<'EOF'
  import gi
  for ns, v in (("GLib", "2.0"), ("Gdk", "3.0"), ("GdkPixbuf", "2.0"),
                ("Gtk", "3.0"), ("Pango", "1.0"), ("PangoCairo", "1.0")):
      try:
          gi.require_version(ns, v)
          print(f"{ns} {v}: ok")
      except ValueError as exc:
          print(f"{ns} {v}: {exc}")
  EOF
  ```

- **No `WAYLAND_DISPLAY` in the environment of the process.** A systemd user service starts before the
  session exports it, so the daemon comes up headless and only listens. `esteban doctor` inside the session
  shows `policy none`; start the daemon in the session, or export the variable once per login.

`doctor` also prints `GI_TYPELIB_PATH`, `interpreter` and the path of the `Gtk-3.0` and `PangoCairo-1.0`
typelibs it would load, so the missing package is named instead of guessed.

## Tests

```bash
python3 tests/test_core.py
```

37 tests, run offscreen, derived from the evidence: the fuzzy LIKE builder and `dodgyChars`, the calculator,
the placeholder formats, usage ranking (knowledge count, strong latching, the 30-day window), the clipboard
behaviours (dedupe, fastAppend, limit, `moveToTopOnUse`, persistence), the workflow `info.plist` and
script-filter item contract, the theme geometry formulas, the action numbers and the visible-row mapping for
number keys, the surface policy per compositor and the X11-through-XWayland fallback, the panel height
following the visible rows and the drawn panel on a compositor that cannot resize a mapped surface, the shadow
room and the configurable panel edge, the reason the results box reports when it cannot be drawn, the typelib
lookup `doctor` prints, the panel alpha override, the COSMIC keybind entry (lowercase keysym names,
one-string `Spawn`, comma-separated entries) and its writer, the launcher path being a real file when nothing
is installed, the toggle IPC round-trip, the row contract shared by the terminal launcher and the overlay, the
icon-theme lookup order and the mimetype icon for a file row, the file index honouring the default-results
scope and pruning paths that no longer exist, the per-category result cap and the `types` filter, the
`text/uri-list` body a file copy puts on the clipboard, the desktop entry read and the `Exec=` command
assembled for a launch, and the fact that a missing helper prints one line instead of raising.

## Project layout

```
esteban/
  config.py       defaults mirroring the observed feature namespaces
  store.py        .alfdb schemas copied verbatim from the binary + knowledge/latching writes
  fuzzy.py        createFuzzyQueryStringFrom port (per-char LIKE, dodgy chars skipped)
  ranking.py      knowledge weight + strong latching
  apps.py         XDG .desktop index (the Linux equivalent of Spotlight/LaunchServices)
  filecache.py    incremental index, tiers nameSearch/nameSplit/nameChars
  icons.py        freedesktop icon theme resolution for the row icon column
  clipboard.py    watcher, dataHash dedupe, fastAppend, expiry, paste
  snippets.py     keyword > word-based > LIKE matching tiers, autoexpand
  placeholders.py {query}, {clipboard[:N][:format]}
  calculator.py   AST-whitelist evaluator (GCMathParser equivalent, `^` -> `**`)
  websearch.py    site keywords, {query} templates, url history
  workflows.py    info.plist objects/connections graph, script-filter item contract
  actions.py      open / copy / copy path / terminal / reveal + usedActions
  theme.py        theme JSON schema + the measured geometry formulas
  compositor.py   session detection and the surface policy (layer-shell / toplevel / x11 / none)
  overlay.py      GTK3 results box: policy-aware surface, Cairo/Pango drawing, keys, IPC handler
  ipc.py          single-instance Unix socket, `esteban toggle`
  hotkey.py       pynput on X11, compositor keybinding on Wayland (COSMIC custom shortcut)
  doctor.py       environment report for the paths that fail on Linux
  ui.py           terminal results box (fallback) + the shared row builders
  main.py         CLI entry point
tests/test_core.py  behavior tests derived from the evidence
docs/REA_REPORT.md  the full analysis
docs/preview.svg    the results box rendered from the measured numbers
FINDINGS.md         the finding-by-finding record, each claim tagged observed / runtime / inference
bin/esteban         launcher for an uninstalled checkout
examples/           a sample workflow (info.plist with objects and connections)
```

Local REA working files — the `evidence/` JSON exports, the live-database copies in `snapshots/`, and
`analysis/slices` — are not committed; the reports are the committed record.

## Behaviour mirrored from the evidence

- **Fuzzy LIKE**: `fuzzy_like("sf")` → `%s%f%`; punctuation in `dodgyChars` is skipped.
- **Ranking tiers**: exact > prefix > word > word-initials > per-char fuzzy, then knowledge weight
  (keyword-specific count + general usage inside a 30-day window), with strong latching outranking raw counts.
- **Clipboard**: dedupe by `dataHash`, `fastAppend` merges consecutive copies into the latest row using
  `fastAppendSeparator` (off by default, so each copy is its own entry), `moveToTopOnUse` bumps `ts`,
  `persistFor` expiry, blacklist by source app, polling watcher as the `checkPasteboard:` equivalent.
- **Snippets**: keyword exact match outranks content match, word-based matching option, autoexpand on new
  clipboard content, placeholder formats `lowercase`/`uppercase`/`capitals`/`trim` and history offsets
  `{clipboard:N}`.
- **Workflows**: `objects` + `connections` from `info.plist`; script-filter item contract
  `uid`/`title`/`subtitle`/`arg`/`quicklookurl`/`mods`; hotkey trigger metadata.
- **Results box**: row height and radii as measured, selection fade, `Down` wraps to row 0
  (`highlightNext` 0xa1ad0), number keys with the action modifier fire the row's `mods` action. Enter runs the
  stored default action and the action modifier reads `mods` without rewriting the row, so a file row opens on
  Enter and copies on the action modifier; snippet, calculator, and clipboard rows copy because their default
  action is a copy.
- **Empty query** returns no rows, and "No results" is printed only when a query exists.
- **Default hotkey**: Alt+Space, mirroring Alfred's Option+Space default.

## The look (measured, not guessed)

From the live theme JSON and the decompiled formulas:

| Value | Measured | Reproduced in `theme.py` |
|---|---|---|
| window width | 609 px, roundness 32, padding 11 × 12 | `DEFAULT_THEME["window"]` |
| search font | 27 px, field height 54 px, roundness 22 | `search_field_height()` |
| row height | `max(iconSize, fontSize + textSpacing + subtextSize) + 2*paddingVertical` = **49 px** | `row_height()` |
| selection radius | `min(roundness, 4)` = **4** | `selection_radius()` |
| scrollbar | thickness 7, radius `min(thickness >> 1, 4)` = **3** | `scrollbar_roundness()` |
| shortcut fade | rows 6/7/8 → alpha 0.5 / 0.3 / 0.1 when > 9 rows are visible | `shortcut_alpha()` |
| text column | drawRect x = 32 px (`iconPaddingHorizontal + icon + 1`) | `text_column_x()` |
| action modifier | `advanced.shortcutmod` 1 → Control, otherwise Command/Super | `config["advanced"]["shortcutmod"]` |
| panel alpha | window colour `#1E1E22E6` → 0.90, drawn over `NSVisualEffectView` blur (`blur` key 0) | `window_alpha()` |
| content inset | window padding 11 × 12 around the content, `search.spacing` 8 px between the field and the first row | `overlay.py` (box margins and spacing) |

Row icons: Alfred draws the bundle icon in the row's icon column; the Linux equivalent is the freedesktop icon
theme, resolved for the same column (`iconPaddingHorizontal` 7 + `iconSize` 30) — the desktop entry's `Icon=`
field first as an absolute path, then the theme directories in spec order (actions, apps, places, status,
mimetypes), sized directories before scalable, the configured theme before the fallbacks, and PNG before SVG
because GdkPixbuf renders SVG only when librsvg is present. File rows take the mimetype icon for the extension
and the folder icon for a directory; a row whose icon cannot be resolved keeps the letter badge. Titles and
subtitles are ellipsized so a long path stops before the hint column instead of running under it.

## Evidence and provenance

Targets analyzed with REA (Ghidra provider):

| Artifact | What it is |
|---|---|
| `/Applications/Alfred 5.app/Contents/MacOS/Alfred` | Mach-O universal binary |
| `alfred_framework_arm64` | arm64 slice of `Alfred Framework.framework` — the core engine; SHA-256 `dcc8e3c3eda75ba79f080b66bb3e53268783c53ca569c4547c52b195df8043e3`, 22929 procedures, 54146 strings |
| `~/Library/Application Support/Alfred/Databases/*.alfdb` | live SQLite databases (clipboard, knowledge, filecache, snippets, actions, urlhistory) |
| `Alfred.alfredpreferences/preferences/**`, `themes/**/theme.json` | live feature preferences and the live theme values |

Addresses below are in the arm64 framework slice and come from observed strings and symbols; live-database
observations are marked as such. Every claim in `FINDINGS.md` is tagged **[observed]**, **[runtime]** or
**[inference]** and cites its REA Evidence ID.

| Feature | Evidence | esteban module |
|---|---|---|
| Global hotkey (default Option+Space) | `local.hotkey.default` 0x203b5c; `Starting global hotkey handler` 0x1febd2; `RegisterHotkeyCombo[%ld,%ld,%ld]` 0x1feb4c (Carbon `_RegisterEventHotKey` in `registerCombo` **0x6c68**); `Double toggle for mods %d` 0x1fec95 | `hotkey.py` + `ipc.py` |
| Results window / results box | `AlfredSelectionList::drawRect:` **0xa0b44**, `performKeyEquivalent:` **0xa1620**, `highlightNext` **0xa1ad0**, `getDirectActionRowFromAction:` **0xa15e0** | `overlay.py`, `ui.py` |
| Theme geometry (the look) | `calculateRowHeight` **0x96a80**, `calculateSearchFieldHeight` **0x968e0**, `calculateScrollbarRoundness` **0x96af0**, live theme JSON + `alfred_theme*` keys 0x201423–0x201496 | `theme.py` |
| App & default-results index | Spotlight metadata selectors: `com.apple.application-bundle` 0x2029c0, `kMDItemDisplayName` 0x2031aa, query `kMDItemDisplayName = '%@'cd \|\| kMDItemAlternateNames = '%@'cd` 0x2160de | `apps.py` (XDG `.desktop`, Linux equivalent) |
| File search + fuzzy matching | `createFuzzyQueryStringFrom:` **0x88b60**, `dodgyChars` 0x5339dd, `extractFuzzyComponentsFrom:` 0x88964, `AlfredWordSearch::fastMatchesQuery:sequential:options:` **0xbc8f0**; `files` schema 0x20db99; `features.filesearch.limit` 0x202e6e | `fuzzy.py`, `filecache.py` |
| Clipboard history | `checkPasteboard:` **0x48264**, `lastClipHash` 0x5330e8, `setupClipboardWatcher` 0x48104, `setupBlacklist` 0x47f28, `clipboardDataFolder` 0x47f04, keys `…showscrollbar` 0x2aaa98 / `enabledFiles` 0x29d618 / `fastAppend` 0x29da78; schema 0x206eff (live DB verified identical) | `clipboard.py` |
| Snippets + dynamic placeholders | `snippets` schema 0x229864, `AlfredSnippetExpansionManager::globalKeyDown:` **0x16e8b8**, match fields 0x206235/0x20625b, placeholder help 0x22f6ff | `snippets.py`, `placeholders.py` |
| Calculator | `GCMathParser::evaluate:` **0x7bb94** / **0x7bd04** | `calculator.py` |
| Web search + URL history | fallback key 0x200df2, `customSites` 0x207846, `AlfredURLHistoryManager` 0x236eb4, `history(item, flatItem, ts decimal)` 0x222a85 | `websearch.py` |
| Usage ranking | `sortResults:withQuery:` **0x116da8**, `latchResultToKnowledge:` **0x116754**, `addResultToKnowledge:` 0x116990, `advanced.latching` 0x2ba978, schemas 0x222e5e/0x22315f | `ranking.py` |
| Universal Actions | `handleAction:` **0x5990** + adapters Applications/Folders/Emails/Browsers/RecentDocuments, `browseinterminal` 0x1ff0b8, `openTerminalAtPath:` 0xb8aac, `copytoclipboard` 0x20cf3f, `usedActions` 0x21500e | `actions.py` |
| Workflows | `AlfredWorkflowManager` 0x152b4, `rebuildResults` 0x17aa0, `connections` 0x20406c, `alfred.workflow.input.scriptfilter` 0x1feeec, item keys `quicklookurl` 0x2016a7 and `mods` 0x2016ce | `workflows.py` |
| Paste / key simulation | `AlfredKeyComboHelper::simulateKeyChar:code:mod:debug:` **0x27d40** + `ignoreTapsForAboutQuarterOfASecond` | `clipboard.py` (`xdotool`/`ydotool`) |

## Limits

- Behavioural clone from observed evidence, not a reimplementation of Alfred's private APIs. Scoring
  constants and tier order are inferences from the observed query tiers and match fields, and they are
  documented as inference in the module docstrings.
- The overlay is a GTK window; there is no `NSVisualEffectView` blur equivalent, so the theme's window colour
  alpha is used as-is and the panel is given a soft shadow instead. Layer-shell surfaces are supported on the
  wlroots-derived compositors, not on GNOME.
- Compositor decorations are not something a client can decline on a plain window, so on a compositor that
  outlines the focused window (COSMIC) only a layer surface gives just the panel.
- Crash handling is defensive: missing PyGObject, no RGBA visual, no display, non-tty stdin, missing
  `curses`, no clipboard backend, pynput on pure Wayland, a missing `xdg-open` or terminal, and an
  already-running instance each print one clear line instead of a traceback. `ESTEBAN_DEBUG=1` keeps the full
  traceback, and `esteban doctor` reports what the machine is missing.
- The look can only be confirmed on a real session: Wayland offers no way to synthesize the key or take a
  screenshot from a script, so focus, decorations, and the panel are checked by pressing the hotkey — after
  `esteban doctor`, then `esteban`, then a few hide/show cycles.
- No license file is committed yet.

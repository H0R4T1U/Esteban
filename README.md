# esteban

A Linux launcher modeled on Alfred 5, built from reverse-engineering evidence of the shipped macOS
app. Interface: **look-alike overlay** (GTK3, surface kind chosen from the compositor — layer-shell
on wlroots-derived compositors, plain window on COSMIC and GNOME, normal window on X11) with the
**TUI launcher** as fallback, plus a global hotkey. Language: **Python 3**.

The full analysis — classes, frameworks, files Alfred writes, and the code pointer for every
feature — is in [`docs/REA_REPORT.md`](docs/REA_REPORT.md). The measured geometry is reproduced
in `esteban/theme.py` and drawn by `esteban/overlay.py`;
[`docs/preview.svg`](docs/preview.svg) renders the results box from those formulas.

Targets analyzed with REA (Ghidra provider):

| Artifact | What it is |
|---|---|
| `/Applications/Alfred 5.app/Contents/MacOS/Alfred` | Mach-O universal binary |
| `alfred_framework_arm64` | arm64 slice of `Alfred Framework.framework` — the core engine; SHA-256 `dcc8e3c3eda75ba79f080b66bb3e53268783c53ca569c4547c52b195df8043e3`, 22929 procedures, 54146 strings |
| `~/Library/Application Support/Alfred/Databases/*.alfdb` | live SQLite databases (clipboard, knowledge, filecache, snippets, actions, urlhistory) |
| `Alfred.alfredpreferences/preferences/**`, `themes/**/theme.json` | live feature preferences and the live theme values |

Addresses below are in the arm64 framework slice and come from observed strings/symbols;
live-database observations are marked as such.

## Core features identified

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

## Architecture

```
esteban/
  config.py       defaults mirroring the observed feature namespaces
  store.py        .alfdb schemas copied verbatim from the binary + knowledge/latching writes
  fuzzy.py        createFuzzyQueryStringFrom port (per-char LIKE, dodgy chars skipped)
  ranking.py      knowledge weight + strong latching
  apps.py         XDG .desktop index (equivalent of Spotlight/LaunchServices)
  filecache.py    incremental index, tiers nameSearch/nameSplit/nameChars
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
  ui.py           TUI results box (fallback) + the shared row builders
  main.py         CLI entry point
tests/test_core.py  behavior tests derived from the evidence
docs/REA_REPORT.md  the full analysis
docs/preview.svg    the results box rendered from the measured numbers
```

Local REA working files — the `evidence/` JSON exports, the live-database copies in
`snapshots/`, and `analysis/slices` — are not committed; the report is the committed record.

## Behaviour mirrored from the evidence

- **Fuzzy LIKE**: `fuzzy_like("sf")` → `%s%f%`; punctuation in `dodgyChars` is skipped.
- **Ranking tiers**: exact > prefix > word > word-initials > per-char fuzzy, then knowledge
  weight (keyword-specific count + general usage inside a 30-day window), with strong latching
  outranking raw counts.
- **Clipboard**: dedupe by `dataHash`, `fastAppend` merges consecutive copies into the latest row
  using `fastAppendSeparator`, `moveToTopOnUse` bumps `ts`, `persistFor` expiry, blacklist by
  source app, polling watcher as the `checkPasteboard:` equivalent.
- **Snippets**: keyword exact match outranks content match, word-based matching option, autoexpand
  on new clipboard content, placeholder formats `lowercase`/`uppercase`/`capitals`/`trim` and
  history offsets `{clipboard:N}`.
- **Workflows**: `objects` + `connections` from `info.plist`; script-filter item contract
  `uid`/`title`/`subtitle`/`arg`/`quicklookurl`/`mods`; hotkey trigger metadata.
- **Results box**: row height and radii as measured above, selection fade, `Down` wraps to row 0
  (`highlightNext` 0xa1ad0), number keys with the action modifier fire the row's `mods` action.
- **Default hotkey**: Alt+Space, mirroring Alfred's Option+Space default.

## Running on Linux (COSMIC, other Wayland compositors, X11)

```bash
pip install ".[overlay,hotkey]"             # esteban + PyGObject (overlay) + pynput (X11 hotkey)
sudo dnf install gtk-layer-shell            # Fedora: the layer-shell typelib
sudo apt install gtk-layer-shell            # Debian / Ubuntu / Pop!_OS: the same
sudo pacman -S python-gobject python-cairo gobject-introspection gtk3 pango   # Arch / CachyOS (gtk3 and pango carry the typelibs)
sudo dnf install wl-clipboard ydotool       # Wayland clipboard + simulated paste
sudo apt install wl-clipboard ydotool       # the same on deb-based systems
sudo pacman -S wl-clipboard ydotool         # the same on Arch
```

Installing is what makes `esteban` available outside the project directory. Without it the package only
runs from the checkout (`python3 -m esteban.main ...` from the project root), and anything that has to
name a file — a desktop shortcut, a systemd user service, an autostart entry — cannot use a bare
`esteban`, because it is execed with the PATH the compositor or systemd was started with, not the login
shell's. `bin/esteban` is the alternative for an uninstalled checkout: it resolves its own location, puts
the project root on `sys.path`, and works from any directory, so an absolute path to it is a valid target.
`esteban keybind` uses it when nothing is on PATH, and says which path it used. It also takes the entry
point script sitting next to the interpreter that runs esteban — that is the usual venv case, where the
file exists but PATH does not contain the venv's bin.

### If `esteban` falls back to the TUI

`esteban doctor` prints the reason it takes the terminal path; the usual ones:

- **PyGObject is there but the `Gtk-3.0` typelib is not.** The typelib comes from the system GTK
  package, not from pip: `gtk3` on deb systems, `gtk3` on Arch (CachyOS), `gtk3` on Fedora.
  Debian/Ubuntu: `sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-pango-1.0`.
  Arch/CachyOS: `sudo pacman -S python-gobject python-cairo gobject-introspection gtk3 pango`.
  A `pip install pygobject` inside a venv only gives you the bindings; the typelibs must still be
  on the system, and the venv must be the one that runs `esteban`.
- **pycairo (or cairocffi) is missing** — `PangoCairo` and the drawing path need it. The `cairo`
  line in `doctor` shows this separately from PyGObject.
- **A different Python is running.** A venv or pipx environment cannot see the system `python3-gi`
  at all, so inside it only `pip install pygobject pycairo` works; otherwise create the venv with
  `--system-site-packages`. `doctor` prints `interpreter` and, when it is inside a venv, says this.
  Check the same interpreter `esteban` uses: `which esteban`, then
  `python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print('ok')"`.
- **A namespace pin failed, which is what the warning means.** `overlay.py` pins every namespace
  before importing it (`GLib 2.0`, `Gdk 3.0`, `GdkPixbuf 2.0`, `Gtk 3.0`, `Pango 1.0`,
  `PangoCairo 1.0`). If gi says a namespace "was imported without specifying a version first", the
  pin for it failed and gi loaded whatever version the typelib path had — usually Gtk 4.0 on a
  system that only carries GTK4. Every pin has to resolve for the overlay to draw:

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

- **No `WAYLAND_DISPLAY` in the environment of the process.** A systemd user service starts before
  the session exports it, so the daemon comes up headless and only listens. `esteban doctor` from
  inside the session shows `policy none`; start the daemon in the session, or export the variable
  once per login: `systemctl --user import-environment WAYLAND_DISPLAY`.

`doctor` also prints `GI_TYPELIB_PATH`, `interpreter` and the path of the `Gtk-3.0` / `PangoCairo-1.0`
typelibs it would load, so the missing package is named instead of guessed.

```bash
esteban index          # build the XDG app index and file index
esteban                # overlay; falls back to the TUI when no display exists
esteban overlay        # overlay only (`gui` still works as an alias)
esteban tui            # terminal launcher only
esteban toggle         # show/hide the running instance (the Wayland keybinding target)
esteban daemon         # the instance that owns the toggle socket
esteban watch          # clipboard watcher
esteban theme          # print the measured geometry
esteban doctor         # compositor, surface policy, PyGObject, clipboard backend, tty
esteban search "sf"    # non-interactive fuzzy search
esteban clip 20        # clipboard history
esteban snippet em     # expand a snippet
esteban calc "2^10"
esteban run hello
```

### Which surface the results box uses

The policy is decided once, from the session (`compositor.py`, printed by `esteban doctor`):

| Session | Surface | Why |
|---|---|---|
| Hyprland, Sway, Wayfire, River, KDE Plasma (KWin), other wlroots-derived compositors | wlr-layer-shell overlay | an exclusive layer surface is the only way a client sits above everything, and it gets keyboard focus when mapped |
| COSMIC (cosmic-comp) | plain undecorated window | COSMIC does speak wlr-layer-shell, but a commit on a surface whose role was already destroyed is a protocol violation there and the compositor drops the connection — a launcher that hides and re-shows a layer surface can kill itself. Window teardown is fine on COSMIC. |
| GNOME | plain undecorated window | Mutter does not implement layer-shell |
| X11 | normal undecorated window | no layer-shell protocol |
| no display session | the TUI in `ui.py` | nothing to draw on |

`ESTEBAN_SURFACE=layer-shell|toplevel|x11|none` overrides the choice.

Two rules follow from the COSMIC behaviour, and they hold on every compositor: a layer surface is
never destroyed after it has been unmapped, and quitting leaves the main loop instead of destroying
the window — closing the display connection ends the session cleanly, so no commit is ever sent on
a roleless surface.

### Transparency

The measured window colour is `#1E1E22E6`, alpha 0.90, and Alfred draws it over an
`NSVisualEffectView` blur while the theme's own `blur` key is 0. GTK has no blur, so on a compositor
that cannot blur (COSMIC, Mutter) the same colour is a flat translucent film: over a busy wallpaper
the panel reads muddy, and the rounded corners let the desktop show through.

`appearance.transparency` controls it, and `esteban theme` prints the value in effect:

| Value | Effect |
|---|---|
| `"off"` (default) | opaque panel in the measured colour `#1E1E22`, which reads as solid black |
| `"theme"` | the measured alpha, 0.90 — flat on any compositor that cannot blur |
| `0`–`1` | the alpha to use |

The default is opaque because nothing on Linux blurs: the same colour that reads as frosted glass on
macOS reads as a translucent film over the wallpaper here. Compositors that blur (KWin, Hyprland with a
blur plugin) are where `"theme"` looks closer to Alfred. Only the panel behind the rows changes; the row,
selection, text and border colours stay as measured. When the panel is opaque it is filled as the whole
window rectangle rather than only the rounded rectangle, so it does not depend on the compositor honouring
surface alpha — otherwise the corners are cleared and read as black, which is the black square around the
panel.

```json
// ~/.esteban/config.json
{ "appearance": { "transparency": "off" } }
```

Two other things that read as "bad" and are worth checking on a COSMIC session:

- **No RGBA visual.** Without one the compositor paints the alpha as an opaque black rectangle, so the
  panel looks like a black box rather than a translucent one. `overlay.py` asks for
  `Gdk.Screen.get_rgba_visual()` and, when the session has none, draws the panel opaque and says so
  instead of drawing black. A Wayland surface has to carry alpha for any translucency at all.
- **The compositor's decoration.** An undecorated GTK3 window on COSMIC still gets the compositor's own
  rounded corners, shadow and active hint, which can double up with the 32 px radius drawn here. A client
  cannot change that; an opaque panel is what removes the visible mismatch.
- **The system theme painting over the rows.** COSMIC themes GTK3 apps, so a `DrawingArea` that is not
  app-paintable receives the theme's opaque background — a solid block inside the panel, with the panel
  colour only around it. The rows area is app-paintable with a transparent CSS background, so the panel is
  drawn by one fill and the rows draw on top of it.

### Global hotkey

Wayland compositors own global keys, so bind the key in the compositor and point it at
`esteban toggle`, which sends the command to the running instance over
`$XDG_RUNTIME_DIR/esteban.sock`. On X11 `esteban daemon` binds Alt+Space directly
with pynput.

**COSMIC**: COSMIC Settings → Keyboard → Custom Shortcuts, add a shortcut whose command is
`esteban toggle`. The same list is plain text at
`~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom`, and that file is a RON **map**, so
each entry is a `key: value` pair:

```text
{
    (
        modifiers: [
            Alt,
        ],
        key: "space",
    ): Spawn("/home/you/.local/bin/esteban", "toggle"),
}
```

Three things in that file are easy to get wrong, and each one makes the key look dead:

- the command and its arguments are **two separate strings** — `Spawn("esteban toggle")` tries to exec a
  program named `esteban toggle`
- keys are stored as lowercase keysym names (`"space"`, `"4"`, `"dollar"`) with function keys as written
  (`"F12"`), so a capitalised `"Space"` never matches
- the program has to be named as a file, because the entry is execed with the compositor's PATH, not a
  shell's — `esteban keybind` uses the installed launcher, or `bin/esteban` of the checkout when nothing
  is installed, and prints which one it used

`esteban keybind` prints the entry for the configured combo with the resolved launcher path, says
whether that entry is already in the file, and whether an instance is answering on the socket.
`esteban keybind --write` appends it — only when the file is already the map the settings UI writes,
keeping existing entries and leaving nothing beside the file: every file under `/v1/` is read as a
config key, so a backup there breaks the whole reload. After writing, cosmic-settings-daemon has to
read the file again (relogin, or `systemctl --user restart cosmic-settings-daemon`). If a hand-written
entry is not picked up on your build, add the same shortcut through COSMIC Settings — that path is the
reliable one (pop-os/cosmic-epoch#2481).

If the key does nothing, check in this order:

1. `cat ~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom` — the entry has to be inside the
   map, with `key: "space"` as written by the file, and the command as an absolute path.
2. `esteban keybind` — it says whether the entry is in the file, whether the launcher path resolves, and
   whether anything is answering on the socket.
3. Test the key on its own before blaming esteban: bind Alt+Space to `/usr/bin/touch` with argument
   `/tmp/keypress`. If the file appears, the compositor is grabbing the key and the problem is on the
   esteban side; if it does not, the chord never reaches the compositor (`wev` shows whether a key reaches
   an app).
4. The key only fires a command, and the command needs a listening instance: run `esteban daemon` in a
   terminal and press the key — the terminal prints `toggle -> running instance`. Nothing visible happens
   when nothing is listening, because a shortcut spawns a process with no terminal to print in.
5. Restart the settings daemon (`systemctl --user restart cosmic-settings-daemon`) or log out and back in
   after editing the file.

`Super` already opens the COSMIC launcher, so pick a free key. `esteban doctor` prints the
instructions for the session it is run in, the panel alpha in effect, and the state of the keybind file.

Other compositors:

- Hyprland / Sway: `binds = ALTSPACE, exec = "esteban toggle"`
- KDE Plasma: System Settings → Shortcuts → an action that runs `esteban toggle`
- GNOME: Settings → Keyboard → Custom Shortcuts (the overlay is a normal window there)

The key only works while an instance is listening, so start `esteban daemon` at session
start (a startup entry / systemd user service). The daemon is the instance that owns the socket:
on a display it runs the overlay and shows or hides itself when the key fires; headless it only
listens and opens a terminal launcher. `toggle` and the daemon must see the same
`XDG_RUNTIME_DIR` — the client looks for the socket there and falls back to the data dir, so a
mismatch means the key appears to do nothing. `esteban doctor` prints the socket path it
would use and whether an instance is answering.

Start the instance with a systemd user service so it is listening before the first key press
(a user service gets `XDG_RUNTIME_DIR` from systemd, so client and daemon agree):

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

On wlroots compositors (Hyprland, Sway, KWin, Wayfire) an exclusive layer-shell surface receives
keyboard focus when it is mapped, so hiding and re-showing it keeps the typing path working. On
COSMIC and GNOME the overlay is an ordinary window and focus follows the usual window rules; on
COSMIC the window manager may place it as a tile, so `Super+G` (toggle floating) is what makes it
behave like an overlay.

### GUI keys

`Enter` runs the action · `Ctrl+C` copies · `Ctrl+P` copies the path · `Ctrl+T` opens in the
terminal · `Ctrl+E` sends the paste keystroke · number keys with the action modifier run the
row's `mods` action · `Up`/`Down` navigate (`Down` wraps) · `PgUp`/`PgDn` page · `Ctrl+V`
clipboard viewer · `Ctrl+S` snippet viewer · `Esc` clears the query, then hides the window ·
`Ctrl+Q` quits. The action modifier is Control when `advanced.shortcutmod` is 1, otherwise Super.

Config: `~/.esteban/config.json` (defaults in `config.py`).
Database: `~/.esteban/Databases/esteban.alfdb` using Alfred's table names.
Workflows: directories containing an `info.plist` with `objects` and `connections`.
Themes: `~/.esteban/themes/<name>.json` in Alfred's theme JSON schema (`alfredtheme` root,
`#RRGGBBAA` colours).

## Tests

```bash
python3 tests/test_core.py
```

Nineteen tests pass: fuzzy LIKE builder, calculator, placeholder formats, usage ranking (knowledge
count, strong latching, 30-day window), clipboard behaviours (dedupe, fastAppend, limit,
moveToTopOnUse, persistence), the workflow `info.plist` / script-filter item contract, the theme
geometry formulas, the action numbers and the visible-row mapping for number keys, the surface
policy per compositor (COSMIC and GNOME get a plain window, wlroots-derived compositors get
layer-shell, X11 a normal window, no display the TUI), the reason the results box reports when it
cannot be drawn, the typelib lookup `doctor` prints, the panel alpha override, the COSMIC keybind entry
(lowercase keysym names, two-argument `Spawn`) and its writer (RON map only, existing entries kept,
nothing left beside the settings file), the launcher path being a real file when nothing is installed,
the toggle IPC round-trip, the row contract shared by the TUI
and the overlay, the environment report, and the fact that a missing helper prints one line instead of
raising.

## Notes and limits

- Behavioural clone from observed evidence, not a reimplementation of Alfred's private APIs.
  XDG desktop entries replace Spotlight/LaunchServices; polling replaces the pasteboard change
  callback; the compositor keybinding + socket replaces Carbon `RegisterEventHotKey`;
  `xdotool`/`ydotool` replace CGEvent posting.
- The overlay is a GTK window; there is no `NSVisualEffectView` blur equivalent, so the theme's
  window colour alpha is used as-is. Layer-shell surfaces are supported on Hyprland, Sway, KWin
  and Wayfire, not on GNOME.
- Scoring constants and tier order are inferences from the observed query tiers and match fields;
  they are documented as inference in the module docstrings.
- Crash handling is defensive: missing PyGObject, no RGBA visual, no display, non-tty stdin,
  missing `curses`, no clipboard backend, pynput on pure Wayland, a missing `xdg-open`/terminal,
  and an already-running instance each print one clear line instead of a traceback.
  `ESTEBAN_DEBUG=1` keeps the full traceback when you want it, and `esteban doctor`
  reports what the machine is missing.
- What still needs a real session to verify: the overlay itself. On COSMIC the two things to check
  are that hide → show cycles do not drop the Wayland connection (the toplevel policy exists to keep
  that off the layer-shell path), and that the custom shortcut runs `esteban toggle` while an
  instance is listening. `esteban doctor` first, then `esteban`, then a few hide/show
  cycles.

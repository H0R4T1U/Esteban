# Alfred 5 (macOS) — reverse-engineering report

Analysis done with REA. All addresses are in the arm64 slice of Alfred's core engine
(`alfred_framework_arm64`, SHA-256 `dcc8e3c3eda75ba79f080b66bb3e53268783c53ca569c4547c52b195df8043e3`,
22 929 procedures, 54 146 strings). Live observations of the running install are marked *live*.

## 1. Process model

- **Language/UI**: Objective-C + AppKit. 2 051 Objective-C classes in the slice, **1 904 internal**
  (the rest belong to linked system frameworks). No Swift type metadata of substance — the engine is Obj-C.
- **Shape**: `Alfred.app` is a thin launcher; the engine lives in `Alfred Framework.framework`.
  Helper processes: `Configurer` (`@rpath/libConfigurer64.dylib` — the preferences UI is a separate
  helper app), `Alfred Assistant` (copied into Application Support, *live*).
- **Hotkeys**: Carbon `EventHotKey` (`_RegisterEventHotKey`, `_GetApplicationEventTarget`) — see
  `AlfredHotkeyCombo::registerCombo` **0x6c68**, log `RegisterHotkeyCombo[%ld,%ld,%ld]` **0x1feb4c**,
  `RegisterHotkeyMods[%ld,%ld,%ld]` **0x1feb72**, double-tap for modifier-only combos **0x1fec95**,
  default key stored under `local.hotkey.default` **0x203b5c**.
- **Storage**: SQLite through FMDB (`FMDatabase`, `FMStatement`, `FMResultSet`, `FMDatabaseQueue`,
  `FMDatabasePool`) over `…/Alfred/Databases/*.alfdb`.
- **Input simulation**: CGEvent posting (`AlfredKeystrokeHelper`) with a self-ignoring window
  (`ignoreTapsForAboutQuarterOfASecond`), e.g. `AlfredKeyComboHelper::simulateKeyChar:code:mod:debug:` **0x27d40**.

### Internal class census (by subsystem prefix)

| Prefix | Count | Subsystem |
|---|---|---|
| `AlfredWorkflow*` | 245 | workflow engine: `info.plist` graph, script filter, runtimes, editor UI |
| `AlfredFeature*` | 60 | per-feature configuration (default results, file search, web search, universal actions, …) |
| `AlfredUniversalActions*` | 52 | Universal Actions: adapters Applications / Folders / Emails / Browsers / RecentDocuments, `handleAction:` **0x5990** |
| `AlfredRemote*` | 40 | Remote (phone) features, `remote.alfred.alfredpreferences` |
| `AlfredSystem*` | 30 | LaunchServices/metadata integration, `AlfredSystemWorkflowFileCache` (fuzzy SQL) |
| `AlfrediTunes*` | 30 | iTunes/Music integration |
| `AlfredConfigurer*` | 25 | Configurer helper app bridge |
| `AlfredMarkdown*` | 23 | Markdown rendering (workflow README / snippets) |
| `AlfredGallery*` | 20 | Powerpack Gallery |
| `AlfredTroubleshooting*` | 13 | diagnostics |
| `AlfredOnboarding*` | 11 | onboarding |
| `AlfredAutomation*` | 7 | Automation tasks |
| `AlfredClipboard*` | 7 | clipboard history + pasteboard helper |
| `AlfredBuffer*` | 4 | results buffers (`AlfredBufferView calculateMaxVisibleItems` **0x4515b6**) |
| `AlfredHotkey*` | 4 | `AlfredHotkeyCombo`, `AlfredHotkeyManager`, `AlfredHotkey`, `AlfredHotkeyView` |
| `AlfredSnippet*` | 6 | snippets + collections |
| `AlfredPlaceholder*` | 2 | dynamic placeholders |
| `AlfredTheme*` / `AlfredStyleKit` | — | theme JSON, row-height/roundness formulas, SketchKit drawing |
| `AlfredSelectionList` | 1 | the results box itself (`drawRect:` **0xa0b44**) |
| `GCMathParser` | 1 | calculator parser |
| `AlfredWordSearch`, `AlfredKeyword`, `AlfredKnowledgeManager`, `AlfredUsageHistory`, `AlfredFileCache`, `AlfredURLHistoryManager`, `AlfredCSVParser`, `AlfredShellHelper`, `AlfredKeyComboHelper`, `AlfredTextHelper`, `AlfredPermissions`, `AlfredLoginItem`, `AlfredUpdate`, `AlfredLicense`, `AlfredProxyHelper`, `AlfredSoundManager`, `AlfredDropSource`, `AlfredWebBookmarks`, `AlfredPDFKit` | — | per-feature helpers |

## 2. Frameworks it calls

| Framework / library | What it is used for (evidence) |
|---|---|
| AppKit | windows, `NSTextView`, `NSTableView`, `NSVisualEffectView` (glass), `NSPasteboard` (`generalPasteboard`, `pasteboardWithName:`), `NSAppleScript`, `NSUserNotification`, `NSTask`, `NSWorkspace`, `NSSpeechSynthesizer` |
| Foundation | `NSUserDefaults` (preference keys), JSON, file paths |
| CoreFoundation | CFStrings for every preference key, `CFStringEncoding` handling |
| QuartzCore / CoreGraphics | rounded-rect drawing in `AlfredSelectionList::drawRect:` 0xa0b44, `CALayer`/`CAShapeLayer`/`CATextLayer` |
| CoreImage | icon/theme effects |
| CoreServices / Spotlight | metadata queries: `com.apple.application-bundle` **0x2029c0**, `kMDItemDisplayName` **0x2031aa**, query `kMDItemDisplayName = '%@'cd \|\| kMDItemAlternateNames = '%@'cd` **0x2160de** |
| QuickLook | `QLPreviewPanel` + item key `quicklookurl` **0x2016a7** |
| PDFKit | `PDFDocument`/`PDFView` previews |
| AddressBook | Universal Actions → Contacts (`…/AddressBook/Sources/` 0x20bf7b, `Metadata/` 0x20bfae) |
| Carbon | `RegisterEventHotKey` (global hotkeys) |
| libsqlite3 + FMDB | all `.alfdb` databases |
| IOKit / Security / SystemConfiguration | power, keychain, network |
| iTunesLibrary | Music integration |
| `@rpath/libConfigurer64.dylib` | preferences helper app |

## 3. Files Alfred writes

All under `~/Library/Application Support/Alfred/` (string **0x203e08**; versioned form
`~/Library/Application Support/Alfred %ld/` **0x23123c**). Verified against the live install (*live*).

| Path | Written by | Purpose |
|---|---|---|
| `prefs.json` | prefs manager | sync/preferences location (`Setting v5 sync to '%@' in prefs.json` 0x203efb, `Updated prefs.json …` 0x2092af/0x20932b) |
| `usage.data` | `AlfredUsageHistory` (0x227f20) | usage statistics blob |
| `history.json` | results history writer (0x205038) + `history(item, flatItem, ts decimal)` table 0x222a85 | last results per query |
| `Databases/clipboard.alfdb` | `AlfredClipboardManager` | clipboard history |
| `Databases/clipboard.alfdb.data/` | `clipboardDataFolder` 0x47f04, string 0x2058f0 | clipboard payload files (images, files) |
| `Databases/knowledge.alfdb` | `AlfredKnowledgeManager` | usage ranking + latching |
| `Databases/filecache.alfdb` | `AlfredFileCache` + `writeMetadataForCachePath` 0x10a828 | file index |
| `Databases/snippets.alfdb` | `AlfredSnippetsManager` | snippet collections |
| `Databases/actions.alfdb` | `usedActions(actionTypeUid, fileType, ts decimal)` 0x21500e | per-file preferred action |
| `Databases/bookmarks.alfdb` | `AlfredWebBookmarks` | bookmarks |
| `Databases/urlhistory.alfdb` | `AlfredURLHistoryManager` 0x236eb4, 0x231467 | web-search history |
| `Alfred.alfredpreferences/` | preferences | `preferences/**` plist keys, `resources/`, `workflows/`, `themes/`, `remote/` |
| `Alfred.alfredpreferences/themes/<theme.id>/theme.json` | `AlfredThemeImporter` (`alfred.preferences.themeimported` 0x1ff81b, `macOS Theme '%@'` 0x1ffefd) | theme JSON (*live*: the analyzed theme is `theme.urlimport.921E6C7E-…/theme.json`) |
| `Plugins/`, `Gallery/workflows/`, `Gallery/data/` | plugin + gallery managers | drop-in plugins, gallery downloads |
| `Automation/Tasks/` | `AlfredAutomation` | scheduled tasks |
| `Assistant/Alfred Assistant` | installer copy (0x22b7e7, permission failure text 0x22b823) | assistant helper |
| `Workflow Data/<bundleid>/`, `alfred_workflow_cache/` | workflow runtime (0x2015c0) | per-workflow persistent + cache storage |
| `/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/` | cache writer | shared workflow cache |
| `~/Library/Application Support/1Password 4/3rd Party Integration/` | `Alfred1Password*` | 1Password bridge (0x232d06) |
| `…/com.apple.LSSharedFileList.ApplicationRecentDocuments` | LaunchServices fallback (0x23253b) | recent documents default results |

## 4. Feature-by-feature: where the code is

### 4.1 Global hotkey
- `AlfredHotkeyCombo::initWithMod:key:` 0x6608, `addHotkey:` 0x675c, `registerCombo` **0x6c68**
  (Carbon `_GetApplicationEventTarget` + `_RegisterEventHotKey`), `deregisterCombo` 0x6d94.
- `AlfredHotkeyManager::sharedManager` + `addTapListener_`; handler start string
  `Starting global hotkey handler` 0x1febd2; modifier-only double-tap 0x1fec95.
- Default: `local.hotkey.default` 0x203b5c (Option+Space). Clipboard hotkey stored in
  `hotkey/prefs.plist` with `interval` for the pasteboard poll.

### 4.2 Query → results (fuzzy matching)
- SQL fuzzy builder: `AlfredSystemWorkflowFileCache::createFuzzyQueryStringFrom:` **0x88b60**
  — builds `char + '%' + char + '%'…` per character, skipping `dodgyChars` (**0x5339dd**,
  punctuation set), capacity `len*2+2`.
- `extractFuzzyComponentsFrom:` **0x88964** — word split (word-initials tier).
- Non-SQL matching: `AlfredWordSearch::matchesQuery:mode:` 0xbc760,
  `fastMatchesQuery:sequential:options:` 0xbc8f0.
- Keyword matching: `AlfredKeyword::matchesQuery:` 0x159dec, `keyword:matchesQuery:partial:arg:` 0x159f78.
- File index table: `files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed,
  keywords, altnames, filetype)` **0x20db99**; `features.filesearch.limit` 0x202e6e.

### 4.3 Ranking
- `AlfredKnowledgeManager::sortResults:withQuery:` **0x116da8** — base/key/used weights.
- `latchResultToKnowledge:` **0x116754**, `addResultToKnowledge:` 0x116990.
- Queries: `select item, count(item) as weight from knowledge where keyword = ? group by item`
  **0x22362f**; `… as used from knowledge where ts > ? and item in (%@) group by item` **0x2235ce**
  (30-day usage tier); `SELECT rowid, item, strong FROM latching WHERE keyword = ? LIMIT 1` **0x223281**;
  `Strongly latching '%@' to '%@'` 0x2232cb; `advanced.latching` **0x2ba978**.
- Schemas: `knowledge(item, keyword, ts decimal, hidden)` **0x222e5e**,
  `latching(item, keyword, strong decimal, ts)` **0x22315f**.

### 4.4 Clipboard history
- `AlfredClipboardManager::checkPasteboard:` **0x48264** — `changeCount` polling, `lastClipHash`
  0x5330e8, half-second dedupe window.
- `setupClipboardWatcher` 0x48104 (`Configuring Clipboard Watcher` 0x2059b7), `setupBlacklist` 0x47f28
  (`features.clipboard.blacklist` 0x205865, app-name based), `clipboardDataFolder` 0x47f04.
- `updateClipboardHistoryWithString:…` **0x48b04** — insert (0x205fb0) + `delete from clipboard where dataHash = ?`.
- Options: `local.features.clipboard.enabledFiles` 0x29d618, `enabledImages` 0x29d5f8,
  `features.clipboard.ignoreConcealed` 0x29d878, `ignoreAutoGenerated` 0x29d8d8,
  `fastAppend` **0x29da78** (+ `fastAppendSeparator` 0x205f2a), `persistFor` 0x2068e6,
  `moveToTopOnUse` 0x206b1c, `limit` 0x205de0.
- Skips: `com.runningwithcrayons.alfred.clipping` pasteboard, transient/concealed/auto-generated
  types, 1Password, remote clipboard.
- Schema: `clipboard(item, ts decimal, app, apppath, dataType integer, dataHash)` **0x206eff** (live-verified).

### 4.5 Snippets + dynamic placeholders
- `AlfredSnippetsManager`, `AlfredSnippetExpansionManager::globalKeyDown:` **0x16e8b8**
  (autoexpand on keystroke), `loadAllSnippetCollections` 0x271313.
- Matching: `features.clipboard.snippetMatchFields` 0x206235, `snippetMatchWordBased` 0x20625b.
- Placeholder formats from help text 0x22f6ff: `{clipboard}`, `{clipboard:lowercase}` 0x208515,
  `:uppercase`, `:capitals`, `:trim`, `{clipboard:N}` history offsets, `{query}`, `{clipboard:words}`, `{clipboard:chars}`, `{date}`.
- Schema: `snippets (uid, name, keyword, snippet, collectionId, autoexpand)` **0x229864**.

### 4.6 Calculator
- `_OBJC_CLASS_$_GCMathParser` **0x3dfd55**, `mathParser` 0x234f34,
  `GCMathParser::evaluate:` **0x7bb94** / **0x7bd04** (shunting-yard style operator stack).
- `features.calculator.decimalSeparator`, `showThousandsSeparator`, `copyToClipboardSuffix` `.`.

### 4.7 Web search
- `features.websearch.google.fallback` 0x200df2, `features.websearch.customSites` 0x207846,
  `AlfredURLHistoryManager` 0x236eb4, `urlhistory.alfdb` 0x231467.
- `history(item, flatItem, ts decimal)` 0x222a85 (default-results history).

### 4.8 Universal Actions
- `AlfredUniversalActionsManager` / `handleAction:` **0x5990**, `AlfredUniversalActionsFilterer`,
  adapters: Applications, Folders, Emails, Browsers (+scheme handler), RecentDocuments,
  `AlfredUniversalActionsViewPreviewText` / `PreviewURL` / `PreviewMultiple`.
- Action UIDs: `alfred.workflow.action.browseinterminal` **0x1ff0b8**
  (`AlfredShellHelper::openTerminalAtPath:` 0xb8aac, `runCommandInTerminal:` 0xb894c,
  `features.terminal.command` 0x2201d2), `.copytoclipboard` **0x20cf3f**.
- Preferred action per file type: `usedActions(actionTypeUid, fileType, ts decimal)` 0x21500e.

### 4.9 Workflows
- `AlfredWorkflowManager` **0x152b4**, `rebuildResults` **0x17aa0**; `connections` 0x20406c.
- Script filter: `alfred.workflow.input.scriptfilter` **0x1feeec**; item contract keys
  `uid`/`title`/`subtitle`/`arg`/**`quicklookurl`** 0x2016a7/**`mods`** 0x2016ce.
- Workflow storage: `Workflow Data/<bundleid>` 0x2015c0, `alfred_workflow_cache`.

### 4.10 Results box rendering (the look)
- `AlfredTheme::calculateRowHeight` **0x96a80** —
  `rowHeight = max(iconSize, fontSize + textSpacing + subtextSize) + 2*paddingVertical`.
  For the live theme: `max(30, 16+12+11) + 2*5 = 49` px.
- `AlfredTheme::calculateSearchFieldHeight` **0x968e0** — measured glyph height (fallback
  `fontSize + 15`) + `2*paddingVertical`; live theme search font size **27**, padding 6.
- `AlfredTheme::calculateScrollbarRoundness` **0x96af0** — `min(thickness >> 1, 4)` when thickness > 1, else 0
  (live theme thickness 7 → radius 3).
- `AlfredSelectionList::drawRect:` **0xa0b44** —
  `visibleRows = min(numberOfRows, _maxVisibleRows)`; selection rounded rect radius
  **`min(result.roundness, 4)`**; icon column then text at x = 32 px;
  shortcut text alpha fades per row index when more than 9 rows are visible
  (**0.5 / 0.3 / 0.1** for rows 6 / 7 / 8), skipped for the selected row and when
  `appearance.options.hideshortcuts` **0x2aaab8**; scrollbar drawn when
  `appearance.options.showscrollbar` **0x2aaa98**.
- Live theme JSON key schema (esteban reads the same schema):
  `result.{text, subtext, shortcut, textSpacing, iconPaddingHorizontal, roundness, paddingVertical,
  iconSize, backgroundSelected}`, `search.{text, background, backgroundSelected, roundness,
  paddingHorizontal, paddingVertical, spacing}`, `window.{color, borderColor, roundness, width,
  paddingHorizontal, paddingVertical, borderPadding, blur}`, `scrollbar.{color, thickness}`,
  `separator.{color, thickness}`, `visualEffectMode`, `credit`, `name`.
  Colors are `#RRGGBBAA`. Keys `alfred_theme` 0x201423, `alfred_theme_window_width` 0x201430,
  `alfred_theme_subtext` 0x201469, `alfred_theme_background` 0x20147e,
  `alfred_theme_selection_background` 0x201496.

### 4.11 Key handling / action numbers
- `AlfredKeystrokeHelper::actionFromSelector:` **0x2c5b8**, `actionFromEvent:` **0x2c918**:
  1 = Enter (run), 4 = Up, 5 = Down, 6 = PageUp, 7 = PageDown, 11 = Cmd+C, 0x1c–0x24 = number-key action rows,
  0x1a = the "direct action row" signal used by `performKeyEquivalent:`.
- `AlfredSelectionList::performKeyEquivalent:` **0xa1620** — resolves an action; if there is a
  direct action row for it (`getDirectActionRowFromAction:` **0xa15e0**) it fires the action at
  `row + offset - 1`, otherwise it delegates navigation; records `lastKeyEventWasRepeat`
  (repeat-key guard) and delegates `selectionList:performAction:selectedRow:`.
  The clone mirrors `row + offset - 1` as `offset + (number - 1)` in `overlay.visible_row_for_action()`,
  so the number keys address the visible rows rather than the whole result list.
- `highlightNext` **0xa1ad0** — wraps the selection back to 0 at the end of the list.
- `control:textView:doCommandBySelector:` **0xa1748** — search field key routing (Enter → action).
- `advanced.shortcutmod` **0x29a478** — 1 means Control is the action modifier, otherwise Command.

## 5. Linux recreation — the mapping

Implemented in `esteban` (Python 3, stdlib-first):

| Alfred (macOS) | Linux equivalent in esteban |
|---|---|
| Carbon `RegisterEventHotKey` | pynput on X11; on Wayland a compositor keybinding running `esteban toggle`, which sends the toggle over a Unix socket (`ipc.py`) |
| AppKit window + `NSVisualEffectView` | GTK3 results box (`overlay.py`); the surface kind is chosen per session by `compositor.py`: layer-shell on wlroots-derived compositors, plain window on COSMIC and GNOME, normal window on X11, TUI as last fallback |
| `AlfredSelectionList::drawRect:` | Cairo/Pango renderer using the same formulas: row height, `min(roundness,4)` selection radius, scrollbar radius `min(thickness>>1,4)`, shortcut alpha fade |
| `AlfredTheme` JSON | `theme.py` reads Alfred's theme JSON schema (`alfredtheme` root, `#RRGGBBAA` colors) |
| Spotlight/LaunchServices | XDG `.desktop` entries (`apps.py`) |
| `checkPasteboard:` | `wl-clipboard` / `xclip` polling watcher (`clipboard.py`) |
| CGEvent paste | `xdotool` (X11) / `ydotool` (Wayland) |
| `openTerminalAtPath:` | `features.terminal.command` + `xdg-open` |
| `*.alfdb` SQLite | same table names in `~/.esteban/Databases/esteban.alfdb` |

See `README.md` for the feature→evidence table and usage.

Two rules in esteban come from the compositor side rather than from Alfred, and they explain the
shape of `overlay.py`: cosmic-comp reports a commit on a surface whose role has already been
destroyed as a protocol violation and drops the client's connection, so the results box never
destroys a surface after it has been unmapped and quitting leaves the main loop instead of
destroying the window; and on COSMIC and GNOME the box is a plain window, because that path's
teardown is safe there while layer-shell's is not.

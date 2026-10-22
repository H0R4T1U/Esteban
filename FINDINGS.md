# Alfred 5 — reverse-engineering findings

Report produced with REA (Ghidra 12.1.4 provider). Every claim below is tagged
**[observed]** (returned by an REA tool from the shipped artifact), **[runtime]**
(observed on the live system with OS tools, no REA Evidence ID), or **[inference]**
(the author's interpretation). Each observed claim cites its REA Evidence ID.

Machine-readable copy of all evidence: `evidence/rea_evidence_bundle_full.json`
(209 records; 184 ghidra, 14 composed-workflow, 7 sqlite, 2 analysis-view, 1 native-macos,
1 artifact-graph). Older `evidence/rea_evidence_bundle.json` is a partial earlier export
(88 records) — the newer file is the authoritative citation source. Those exports, `analysis/`
and `snapshots/` are local REA artifacts and are gitignored: `snapshots/` is a copy of a live
Alfred database and contains personal data, so this report is the committed record.

## 1. Target identity

| Item | Value | Evidence |
|---|---|---|
| Bundle | `/Applications/Alfred 5.app`, `com.runningwithcrayons.Alfred`, 5.7.1 build 2307 | **[observed]** `Info.plist` |
| Main implementation | `Contents/Frameworks/Alfred Framework.framework/Versions/A/Alfred Framework` | **[observed]** |
| `Contents/MacOS/Alfred` | thin launcher, not the engine | **[observed]** |
| Mach-O | universal, `MH_DYLIB` (file_type 6), x86_64 at file offset 16384, **arm64 at file offset 5832704** | **[observed]** `ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57` |
| arm64 UUID | `FFF543AA-F649-38D3-A2F2-2C5022D5E36B`, 40 load commands, 648 undefined symbols, 29662 symtab entries | `ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57` |
| Build | platform MACOS, minOS 11.0, SDK 15.2, linker LD 1115.7.3 | same record |
| Inventory analyzed | 22,980 procedures, 54,025 strings, 37 segments, document `target-dcc8e3c3eda7.bin` | `ev_8bd79a411054dc8c2d715df4d93edddd9d5deb066bd54d4eed42ca024a45488a` |
| Thinned arm64 slice | sha256 `dcc8e3c3eda75ba79f080b66bb3e53268783c53ca569c4547c52b195df8043e3` | `ev_8bd79a411054dc8c2d715df4d93edddd9d5deb066bd54d4eed42ca024a45488a` |

**Why a thinned slice:** Ghidra and Kuna reject universal Mach-O inputs, so analysis
runs on the arm64 slice extracted from file offset 5832704. **[inference]** — this is a
tooling constraint, not a property of Alfred.

### Linked frameworks (exhaustive, 24 `LC_LOAD_DYLIB`)

`ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57`, facet `dependencies`
(paged view `ev_d05343ce1f3de6eaa53dd25bb2e6748d0fd7ec29fd836def36dbe90821ea3bc3`):

Cocoa, AppKit, Foundation, CoreFoundation, CoreGraphics, CoreImage, QuartzCore,
ApplicationServices, CoreServices, ImageIO, PDFKit, QuickLook, AddressBook, iTunesLibrary,
Carbon, IOKit, SystemConfiguration, Security, Quartz, `/usr/lib/libsqlite3.dylib`,
`libobjc.A.dylib`, `libc++.1.dylib`, `libSystem.B.dylib`, `@rpath/libConfigurer64.dylib`.

`@rpath` resolution `ev_bb07430e8322aaef7a232aee646abd2b36cd39fddc423247996867091b4e6ad7`:
rpaths are `@executable_path/../Frameworks` and `@loader_path/Frameworks`; the second is
absent, the first resolves to `Contents/Frameworks/libConfigurer64.dylib`, which is present
on disk. So `libConfigurer64.dylib` is a **bundled third-party C++ dependency**, not an Alfred class. **[observed]** resolution, **[inference]** that it is third-party.

---

## 2. Feature → classes → frameworks → files

### 2.1 Hotkeys and double-tap

- Classes: `AlfredHotkeyCombo`, `AlfredHotkeyManager`.
- Framework: **Carbon** — `AlfredHotkeyCombo::registerCombo` calls `_RegisterEventHotKey`
  **[observed]** `ev_b6b1816dbc9be7bcfb07f1463b765ff4834d50b1964585d6c43b84117615e255`.
  The import `_RegisterEventHotKey` appears in the arm64 import table
  (`ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57`).
- Double-tap thresholds **0.25 s / 0.3 s** are literal constants inside
  `AlfredHotkeyManager::checkTap` **[observed]**
  `ev_aa47425160140d3b238810b63210a8a4dfdd7ce6444884bbaa78902e8e203d13`; modifiers come from
  `_GetCurrentEventKeyModifiers` (Carbon).
- Files written: none. Hotkey state is preference data, written through
  `AlfredPreferences::updatePreferences:force:` (see §2.12).
- Unknown: `AlfredHotkeyManager::_myHotKeyHandler` is not a resolvable Ghidra procedure name;
  only string and `objc_stub` evidence exists for the handler.

### 2.2 Search dispatch

- `AlfredFeatureFactory::createFeatures` enumerates feature types: FileSearch, WebSearch,
  UniversalActions, Dictionary, Calculator, Contacts, Clipboard, Snippets, iTunes **[observed]**
  `ev_cca663d3c04dc198fa124d6c8cdbe0cfbd7e52ef1080eb744e7f32fab0df4b2e`.
- Provider list built by `AlfredInternalSearchManager::init`
  **[observed]** `ev_a294804150d70761592c31f6f61cf89fb4e3934620d591fb372c4e05477e38b5`.
- Keyword matching: `AlfredKeyword::keyword:matchesQuery:partial:arg:`
  **[observed]** `ev_8f208a5580c34c4f49e36c9a8f2bff2f3c489d3349a247c1e1ff782739bf16d9`.
- Action routing by modifier keys: `AlfredActionHelper::performActionForMods:query:result:visibleResults:`
  **[observed]** `ev_623385b3d8d7880f2dc8f28dc0f7641a404370452b08a33ce93a4ccb0b84e69e`.
- Result dispatch entry point: `resultsForQuery:`
  **[observed]** `ev_890d09cc1fe6f09a7c5972ed2c6938ba68e21c2cb95ce9c5b34dc226fe83c727`.
- Files written: knowledge + usage rows per result shown/acted on (§2.11).

### 2.3 File search (SQLite index + Spotlight)

Two separate mechanisms, both observed:

1. **Own index**: `AlfredSystemWorkflowFileCache::resultsForQueryString:includePreferences:`
   queries the `files` table **[observed]**
   `ev_e96991d78ca0034cda9f71229f8ae46e161dfd3fb139776ec7117e27add7581f`.
   `files` schema verified against a quiescent snapshot
   **[observed]** `ev_809c18209e47ae62c601fe97d14c32d6adb2a3ed5ac8898c8ad44d377364af3a`:
   `CREATE TABLE files (path, fileName, name, nameSearch, nameSplit, nameChars, lastUsed integer,
   keywords, altnames, filetype integer)` + 9 indexes.
2. **Spotlight/Metadata**: `AlfredMetadataQuerier::queryString:variables:scopeFolderMatchTerms:`
   builds a predicate over `kMDItemDisplayName` / `kMDItemAlternateNames` **[observed]**
   `ev_361c247ca64090d014c4f2dbea9b351eb476663c48fe95975aaf3ed950a3c400`.
   The execution path is the CoreServices C API, confirmed by direct imports:
   `_MDQueryCreate`, `_MDQueryExecute`, `_MDQueryGetResultAtIndex`, `_MDQueryGetResultCount`,
   `_MDQuerySetMaxCount`, `_MDQuerySetSearchScope`, `_MDQuerySetSortOptionFlagsForAttribute`,
   `_MDQueryStop`, `_kMDQueryScopeComputer` **[observed]**
   `ev_48e0148a20051024736396372c5925b11eeb4fff13489c5ae37bfc92defb021e` and the import facet of
   `ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57`.
   `NSMetadataQuery` is **not** in the class inventory (`ev_f74d093a64a6453666c751aa071ce7e81223e161dcd330ea6367dde40f8b7151`), so the
   query goes through the private MDQuery C API, not the Foundation class. **[observed]** + small inference.

Files written: `Databases/filecache.alfdb` plus an atomically written cache blob by
`AlfredFileCache::saveData:expiry:looseReload:` via `writeToFile_atomically:` **[observed]**
`ev_a69bb36df92ea238fe9aa033ada2491178d5952a32b232da93db6c010a724781`; cache folder resolves to
`Application Support/Alfred/Caches` `ev_0cd8276959a968aed7b794e0d8fb39d4d90a342613b633b237560f1d69256844`,
and the `Caches` path literal is `ev_19c9f03c270821c59d7f085b7d63278fcd786abb3f278f80417ab187f067447a`.

### 2.4 Clipboard history

- Class: `AlfredClipboardManager`; framework **AppKit** (`NSPasteboard`, `NSPasteboardItem`
  in the class inventory `ev_f74d093a64a6453666c751aa071ce7e81223e161dcd330f2cab29d09fd98933434a7eaa6ef`... see §4 note; full class list is `ev_f74d093a64a6453666c751aa071ce7e81223e161dcd330ea6367dde40f8b7151`).
- Polling model: `checkPasteboard:` reads `generalPasteboard` and compares `changeCount`
  **[observed]** `ev_666a35c92390ee099a0f2871f4b3e1576e9cc557374dd29993b72ca6c499a970` — a
  polling loop, not a change callback. **[observed]**
- Row insert: `updateClipboardHistoryWithString:data:dataType:appName:appPath:append:`
  **[observed]** `ev_b8e1cc0af078a33da106237618895885afd74d3902841a195cbcdc0ee0e5eab4`.
- Files written: `Databases/clipboard.alfdb` (`ev_a340c07541bda86bc508377b97cadb01de060896d64aec1a52720c9817efaa86`)
  and `Databases/clipboard.alfdb.data` for the payload blobs
  (`ev_ce1fd853daf8c57f4d10c47b2e6bf72615e347ea093d190978e2a40392899fb2`; folder function
  `ev_49c5414eea1f6004bd71cc24a98f573fd0e7da6680f6e4e13400a933d519f195`).
- Schema verified against a snapshot **[observed]** `ev_6a9cdecb073f8951af07ab09c9acc67e35fa0f4d4be3b4765471c414b049221a`:
  `CREATE TABLE clipboard(item, ts decimal, app, apppath, dataType integer, dataHash)` + 5 indexes.

### 2.5 Snippets and auto-expand

- Class `AlfredSnippetsManager::setupSnippetDB` creates `triggers` and `snippets` and their
  indexes **[observed]** `ev_4e890fcd2b4098a44bcbb87f43b320fcd76d8c1aa137c29eb1310d6d42d6c508`;
  schema verified against a snapshot **[observed]** `ev_1613fca0eb5195f72c04a1d9aa20d733537c308cde8535ddfeb63239af4f3da7`.
- Auto-expand uses a **CoreGraphics event tap**: `AlfredSnippetExpansionManager::startSnippetExpansion`
  calls `_CGEventTapCreate` **[observed]** `ev_df540c8fa42c6bed0def0dbcd5ce9885a52ba8c9f1b7fbfd562fe98bf71df5f7`,
  gated by `AlfredPermissionsManager::isTrustedIfNotRequestPermissions` (Accessibility trust).
- Files written: `Databases/snippets.alfdb`.

### 2.6 Knowledge, latching, usage, URL history

- `AlfredKnowledgeManager::addResultToKnowledge:withQuery:` inserts into `knowledge` and then
  calls `latchResultToKnowledge:withQuery:` **[observed]** `ev_308d94bdd97c38fcbcfef9957796f4435733d8bddf8d1c4d94c00d871ce8eee4`;
  `addInputUidToKnowledgeOnActioningChild` writes a `hidden = 1` row for chained inputs.
- Schema + migration: `AlfredKnowledgeManager::setupDB` checks `user_version == 4`, otherwise
  deletes the database and recreates it; a `_dispatch_once` vacuum runs at startup
  **[observed]** `ev_a4c1939685b002c6bda72006fa5cd232b77dbd7c189d0c3a0754268d1573cf41`.
  Live schema **[observed]** `ev_78eff0985ea0a5c1bbbf4d04404765749261c3a668e987158d984281f88b02d0`:
  `knowledge`, `other`, `recentdocs`, `latching` (12 indexes).
- URL history: `AlfredURLHistoryManager::addURLToHistroy:` → `history` table
  **[observed]** `ev_b4ba1ad50bb392337c807063b8bbf767f3550b6006b1a2320063363a96a288a6`; schema
  `ev_81f99f950545cbb3eb2c2d79f582bcc9f9ad506a1739bb4ed5eea6dd631a9983`.
- Usage totals: `AlfredUsageHelper::syncTotalUsageData` hashes (since, count), formats a string,
  base64-encodes it, and writes it atomically as `usage.data` in the application-support folder
  **[observed]** `ev_19034ee91a29663155628c01db85fc839d89c78b0ffdf3817c781669d393ea70`;
  it runs only when the main window is not visible (`checkWriteUsage:` `ev_41045295d6f9871a8db48b2df2b3eacef96a46a2097cf2de2a878f8e199a0730`).
- Action usage: `usedActions` schema **[observed]** `ev_73a7586d04c04094b9df7d83628fe7de54f6df6216e48197bd795fa47d7293f4`.

### 2.7 Contacts

- Framework: **AddressBook** (`ABAddressBook`, `ABPerson`, `ABSearchElement` in the class inventory).
- `AlfredContactsQuerierOperation::start` calls
  `ABPerson::searchElementForProperty...` **[observed]** `ev_9fa09b4c53d1439711c4c4b954b39b85ba546aae8898a642109126a8aa071c44`.
- UI adapter `AlfredUniversalActionsViewAdapterEmails::loadContactsMatching:` posts the
  notification `alfred_contactsquery_results_updated` **[observed]** `ev_29adc97c757fc3a4cad61b6ab2bb32fa188c56fee0b49caade7da8ddb78922c9`.
- Files written: none specific to contacts (results feed knowledge writes).

### 2.8 Music (iTunes/Music)

- Framework: **iTunesLibrary** (`ITLibrary` in the class inventory).
- `AlfrediTunesAPIParser::parseLibrary` calls `libraryWithAPIVersion:error:` **[observed]**
  `ev_7d3a83ba0faca1eeb99ee3e33e450d525e1d2b9e842e2bb2a2cf05f80aec4d50`. A separate XML parser
  class `AlfrediTunesXMLParser` also exists in the class inventory.
- Files written: `iTunes.alfdb` / `iTunes_%@.alfdb` path literals
  **[observed]** `ev_a340c07541bda86bc508377b97cadb01de060896d64aec1a52720c9817efaa86`.

### 2.9 Web bookmarks and web search

- `AlfredWebBookmarksManager::createDB` builds the database at a temp path
  `%@/AlfredTmp.%@.alfdb` and then `moveInDBFromTmpPath:` **[observed]**
  `ev_f56c431e7c6c30f6b91e009aebe1bf1f090bbbd5736cb387ce386bd49f893c28`.
- Query shape: `SELECT source, title, url, folder FROM bookmarks WHERE ... ORDER BY title`
  and `searchWords LIKE` **[observed]** `ev_c6e6c2c2120a9a5b8d821953e57de03ea0e2ed1f7f69f8d79d71695b0fda10ca`.
- Files written: `Databases/bookmarks.alfdb`
  **[observed]** `ev_a340c07541bda86bc508377b97cadb01de060896d64aec1a52720c9817efaa86`;
  `history.json` **[observed]** `ev_de894a37609c8d822217eb5629af434ec0ded8ed06dbbf94880679aae3c3af26`.

### 2.10 Remote (Alfred Remote / workflow remote pages)

- `AlfredRemoteManager::startRemoteServer` launches a **separate process** with `NSTask`
  pointing at the bundle resource `Alfred Remote Server` in `serverCurrentDirectory`
  **[observed]** `ev_3a3110fa9112370b9734e81d66c0e7aa6124ff84539648a3a880959ddfb5e2c8`.
- Cross-process messaging is `NSDistributedNotificationCenter` with a `senderUUID` de-duplication
  **[observed]** `ev_6cab70259d1739638c20f4c29d79675c57e74ffec11f9723ba474595bb0100f8`,
  `ev_a6c239bf2bd6d005e4f7e60be13121d0f5e80b369d6be620e44a51dcdaa9dca1`,
  `ev_8f49da21d126de607bb7196b1fa269039b2480b24e49c2f5b814fbe6c2679f35`.
  `handleRemoteActionNotification:` reads `pages/pages.data` with keys `itemuid`, `pageuid`,
  `confirmed` **[observed]** `ev_8f810ed46ca7e402d48c9b6934539bf810af3dfed542d082aff697dac2d2027a`.
- Negative search: no socket, `NetService`, or ZeroConf symbols exist in the framework.
  **[observed, bounded]** — so the network layer lives in the helper process, not the framework.
- Files written: `.../remote/pages/pages.data` **[observed]**
  `ev_f84890d54a08824c15e7379c832af75a462b58e1e2a4a4a8af6951504f7242e6`.

### 2.11 QuickLook, PDF, image preview

- Frameworks: **QuickLook** and **PDFKit**.
- `_QLThumbnailImageCreate` is a direct import **[observed]** (import facet of
  `ev_4eb37c3397e41961b5474e3a2626991095ffcaa2eb8c724f0a8a19b39df69a57`), and
  `AlfredDefaultResult::generateQuicklookURL` produces the preview URL used by the workflow
  item contract **[observed]** `ev_c48665ce430c2011912cd1858e70effb846d48df43c455f0ce9783b16d449508`.
- PDFKit usage: `PDFDocument`/`PDFView` classes plus `initWithURL:` and
  `configurePDFDisplayMode`; the workflow UI config type is `AlfredWorkflowUserInterfacePDFConfigData`.
  **[observed]** class inventory `ev_f74d093a64a6453666c751aa071ce7e81223e161dcd330ea6367dde40f8b7151`.

### 2.12 Preferences and files Alfred writes

- `AlfredPreferences::updatePreferences:force:` writes one file per `keyPath` under
  the preferences folder as `prefs.plist` **[observed]** `ev_e781e067661d819e281b0923c5a461d91a469e36b7402e3b1f7b416eaf0ffb54`;
  folders come from `AlfredHelper::preferencesFolder` `ev_48eff2d9ff81a36ad8cdb5fa429453bbdf49e8ca7457090d2a2689f53e576a92`
  and `AlfredHelper::applicationSupportFolder` `ev_1cfe41831feeb2a96cad4d64e17ceb75d162dcf1045eb830cdec01a86faf4105`.
- Path literals **[observed]**: `prefs.json` `ev_ecc7140d5ad88926ae3aa6a081bddfa9982ec66e3ac06c5031c04ebdd8f5a57b`
  (note: this ID was previously recorded with a truncated hash; corrected here), `history.json`
  `ev_de894a37609c8d822217eb5629af434ec0ded8ed06dbbf94880679aae3c3af26`, `prefs.plist`
  `ev_7bbc848bc5d764b0855b24269254ca3097876135d7989e5feccb91951611f62d`, `Workflow Data`
  `ev_021d9b10407a16b66b24add086e9f8952421f7e1c45da729f5c9f3338f25a42e`, `Caches`
  `ev_19c9f03c270821c59d7f085b7d63278fcd786abb3f278f80417ab187f067447a`, `Gallery/workflows/` +
  `data/gallery.json` `ev_0e11c4c36537a370f1e3c882175e823c1825bc06aa711203bfd9b3d9e4215086`, `Plugins`
  `ev_43a950ca77389b7b1b3ed28b4240660f4ed9e77565a8f69f1073ca1820e1c181`,
  `Databases/clipboard.alfdb.data` `ev_ce1fd853daf8c57f4d10c47b2e6bf72615e347ea093d190978e2a40392899fb2`.

**Runtime observation** (**[runtime]**, no REA Evidence ID): `~/Library/Application Support/Alfred/`
on this machine contains `Databases/` (the six `.alfdb` files snapshotted in `snapshots/`),
`prefs.json`, `history.json`, `usage.data`, `Alfred.alfredpreferences/`, and `Automation/Tasks/`.
Alfred was live as PID 1406 during the session and `lsof` showed the databases open. This
corroborates the static path literals; it is not REA evidence.

### 2.13 Scripts, automation, licensing

- `AlfredScriptTaskOperation::start` executes workflow script actions **[observed]**
  `ev_ed46cd0523828b1d467e745550739eae96e9cafb1cee04f8a586ea767ca1ec31`; the Terminal action runs
  asynchronously on `_dispatch_get_global_queue` `ev_c5c2192983a267ebe2f0ecad53278a9b7d4d100152093b4b1ebfb59d6ac24713`.
- `AlfredScriptBridge::compileScript:` calls `osacompile -o %@.scpt` through `_system()` and caches
  the result in the cache folder; source comes from bundled `.applescript.src` **[observed]**
  `ev_8e44ff1f1f7d7b6556fc4ad2f8999e160b15c375bf8b982d35c1313f20779f36`.
- `AlfredAutomationTaskGroup::saveGroup` persists automation task groups **[observed]**
  `ev_57a889ec33a53d894d9fe38b374bb8e28cdbe7e770ff949bb49a907af661e8d7` (matches the live
  `Automation/Tasks/` directory, **[runtime]**).
- Licensing: `AlfredLicense::licenseWithPackagedBase64License:error:` parses a
  `BEGINALFREDLICENSE` … `ENDALFREDLICENSE` envelope and extracts binary fields **[observed]**
  `ev_bca220ad44fd2a21523f9e2ba8cb22ebcfb6d5d87a17d4ca37dfaafdfa21ac25`. Obfuscated helper
  functions (e.g. `_qrwG9chHdy1498`) gate Powerpack/permission checks — **[observed]** as
  symbols, **[inference]** that they are feature gates.

---

## 3. Files Alfred writes — summary

| File / directory | Written by | Evidence |
|---|---|---|
| `Databases/{clipboard,knowledge,filecache,snippets,urlhistory,actions,bookmarks}.alfdb` | FMDB → `_sqlite3_open` (`ev_e9ef0678680c78466b05f9142ace250b5d95374268184423cc31d4413e185aaa`), path literals `ev_a340c07541bda86bc508377b97cadb01de060896d64aec1a52720c9817efaa86` | observed |
| `Databases/clipboard.alfdb.data` | `clipboardDataFolder` `ev_49c5414eea1f6004bd71cc24a98f573fd0e7da6680f6e4e13400a933d519f195`, `ev_ce1fd853daf8c57f4d10c47b2e6bf72615e347ea093d190978e2a40392899fb2` | observed |
| `Caches/` + atomic cache blobs | `ev_a69bb36df92ea238fe9aa033ada2491178d5952a32b232da93db6c010a724781`, `ev_0cd8276959a968aed7b794e0d8fb39d4d90a342613b633b237560f1d69256844` | observed |
| `usage.data` | `AlfredUsageHelper::syncTotalUsageData` `ev_19034ee91a29663155628c01db85fc839d89c78b0ffdf3817c781669d393ea70` | observed |
| `prefs.json`, `history.json`, `prefs.plist` per keyPath | `ev_ecc7140d5ad88926ae3aa6a081bddfa9982ec66e3ac06c5031c04ebdd8f5a57b`, `ev_de894a37609c8d822217eb5629af434ec0ded8ed06dbbf94880679aae3c3af26`, `ev_7bbc848bc5d764b0855b24269254ca3097876135d7989e5feccb91951611f62d`, `ev_e781e067661d819e281b0923c5a461d91a469e36b7402e3b1f7b416eaf0ffb54` | observed |
| `Workflow Data/`, `Gallery/workflows/`, `data/gallery.json`, `Plugins/` | `ev_021d9b10407a16b66b24add086e9f8952421f7e1c45da729f5c9f3338f25a42e`, `ev_0e11c4c36537a370f1e3c882175e823c1825bc06aa711203bfd9b3d9e4215086`, `ev_43a950ca77389b7b1b3ed28b4240660f4ed9e77565a8f69f1073ca1820e1c181` | observed |
| `remote/pages/pages.data` | `ev_f84890d54a08824c15e7379c832af75a462b58e1e2a4a4a8af6951504f7242e6` | observed |
| `*.scpt` compiled AppleScript cache | `ev_8e44ff1f1f7d7b6556fc4ad2f8999e160b15c375bf8b982d35c1313f20779f36` | observed |
| `Automation/Tasks/` | `ev_57a889ec33a53d894d9fe38b374bb8e28cdbe7e770ff949bb49a907af661e8d7` | observed (class), runtime (directory exists) |

---

## 4. Remaining unknowns

- No runtime capture record exists in the bundle: the live-file observations came from OS tools,
  so they cannot be cited as REA Evidence.
- Row order and per-row scoring constants in `ranking.py` remain inference; the query shapes are
  observed, the weights are not.
- `AlfredHotkeyManager::_myHotKeyHandler` cannot be decompiled by name.
- The network transport of Alfred Remote is not observable from the framework; it is in the
  helper binary, which was opened but not deep-analyzed.
- `GCMathParser::evaluate:` resolves only by address `0x7bb94` (`ev_ff9a772778a1c94fe7e64e60aeb52a0a4dd1eb9e3bd1fc83698a52e34ced1418`), not by symbol.
- `get_navigation_context` is unsupported for the Ghidra provider; queries must pass
  `document = target-dcc8e3c3eda7.bin`.

---

## 5. Mapping to the Linux clone (`esteban/`)

Observed behaviour vs design choice, kept separate:

| Observed in Alfred | esteban | Design choice (not observed behaviour) |
|---|---|---|
| Carbon `RegisterEventHotKey` + double-tap 0.25/0.3 s | `hotkey.py` | `pynput` replaces Carbon; double-tap thresholds carried over |
| Polling `checkPasteboard:` (`changeCount`) | `clipboard.py` | polls `wl-clipboard`/`xclip` instead of `NSPasteboard` |
| MDQuery/Spotlight index | `apps.py` | XDG `.desktop` index replaces Spotlight/LaunchServices |
| SQLite schemas | `store.py` | schemas copied verbatim from evidence |
| knowledge/latching/usage | `ranking.py`, `usage.py` | same tables; weights are documented inference |
| `usage.data` base64 write | `usage.py` | writes to XDG data dir, same format pipeline |
| AddressBook contacts | `contacts.py` | vCard files replace AddressBook |
| Web bookmarks (`source,title,url,folder,searchWords`) | `bookmarks.py` | reads Chrome JSON / xdg bookmarks; `source` values are inference |
| `NSDistributedNotificationCenter` + `senderUUID` dedupe | `notifications.py` | Unix domain socket replaces distributed notifications |
| QuickLook/PDF preview | `preview.py` | freedesktop thumbnail spec replaces QuickLook |
| iTunesLibrary | `music.py` | scanned music directory replaces iTunesLibrary |
| Remote pages + `itemuid/pageuid/confirmed` | `remote.py` | same JSON keys, local file + socket bus |
| `BEGINALFREDLICENSE` envelope | `license.py` | no DRM enforcement; parser only |
| `prefs.plist` per keyPath + `prefs.json` | `prefs.py` | single JSON file, mirrors per-keyPath write semantics |
| Automation task groups | `automation.py` | JSON files under XDG dir replace `Automation/Tasks/` |

Tests: `python3 tests/test_core.py` — 11 tests pass, covering the observed query shapes,
schemas, usage/usage.data pipeline, notification dedupe, license envelope parsing, and the
workflow item contract.

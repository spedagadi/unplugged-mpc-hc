# Unplugged 1.2.0 handover

Date: 2026-10-22

## 1. Summary

1.2.0 is a UI-only release on top of 1.1.1. The engine (`s3engine.dll`), LAV
filters, MPCVR and the installer's filter registration are unchanged.

- **Poster library**: the Media Library is now a poster grid with Movies,
  TV Shows and Folders tabs. It is backed by a persistent SQLite index that
  re-syncs in the background at every start. Artwork comes from local files
  first, then OMDb.
- **Settings panel tidy**: clearer section headers, all sections collapsed by
  default (accordion), and a trimmed Output tab.
- **Super Resolution switch**: an On/Off switch. Turning it on also sets the
  settings it depends on.

State at handover:

- Built, committed, tagged `v1.2.0` and pushed. The installer has not been
  installed and run.
- The 1.2.0 installer has not been given to any users.
- Not validated on the target HTPC: Super Resolution on RTX hardware, a large
  or NAS library, and TV-show libraries with real OMDb data. Only five movies
  on `D:\` were tested live.

## 2. Repository and release state

| Item | Value |
| --- | --- |
| Repository | `C:\code\unplugged-mpc-hc`, branch `zion-s3-shell` |
| Release commit | `19c1f24da` release: Unplugged 1.2.0 |
| Fix commit (tag target) | `508ffbf0d` fix(1.2.0): re-download a poster the user deleted |
| Tag | `v1.2.0` → `508ffbf0d`, annotated, pushed |
| Previous release | `v1.1.1` → `c27424eab` |

The `v1.2.0` tag was **moved once**, with the maintainer's explicit approval,
from `19c1f24da` to `508ffbf0d`. That was acceptable because 1.2.0 had not
been distributed. Anyone who fetched the old tag needs
`git fetch --tags --force`. Do not move it again: any further change is 1.2.1.

`C:\code\unplugged-VideoRenderer` and `C:\code\LAVFilters` were not touched in
this release.

## 3. Poster library

### Files

| File | Role |
| --- | --- |
| [media/library.py](../src/unplugged-ui/src/mpvprocessor/media/library.py) | SQLite index, background sync thread, OMDb fetch phase |
| [media/artwork.py](../src/unplugged-ui/src/mpvprocessor/media/artwork.py) | sidecar, folder and Kodi names; MKV/MP4 embedded covers; thumbnails |
| [media/name_parse.py](../src/unplugged-ui/src/mpvprocessor/media/name_parse.py) | file name → title, year, season, episode |
| [media/omdb.py](../src/unplugged-ui/src/mpvprocessor/media/omdb.py) | OMDb client (urllib over HTTPS) |
| `media/_omdb_key.py` | **API key: gitignored, never commit** (see §6) |
| [ui/media_library_panel.py](../src/unplugged-ui/src/mpvprocessor/ui/media_library_panel.py) | poster grid UI (rewritten; public API unchanged plus `shutdown()`) |

### Storage

- Database: `%LOCALAPPDATA%\Unplugged\library\library.db` (WAL mode).
- Thumbnail cache: `%LOCALAPPDATA%\Unplugged\library\art\`, 360×540 JPEG
  files named by SHA-1 of their key.
- The index is a cache of the disk. A corrupt database is moved aside to
  `library.corrupt-<time>` and rebuilt; that costs one rescan and never stops
  the player from starting.

### Sync rules

These rules protect user data.

- A sync runs at every start and from the Rescan button, on a daemon thread.
  The UI thread never touches the filesystem; it doesn't even check whether a
  NAS folder exists.
- Only a **complete** walk may mark files missing. An unreachable root, or any
  unreadable folder or entry, keeps its titles. Titles missing for 30 days
  (`MISSING_PURGE_DAYS`) are purged.
- Removing a library folder deletes its titles immediately (a user decision).
  Titles indexed under a folder that was removed mid-sync are cleaned up at
  the end of that sync.
- The worker commits per file, so it never holds the SQLite write lock across
  filesystem work. `set_roots()` returns False and the panel shows a message
  if the database is busy; there is no crash or freeze.
- Skipped during the walk: hidden and system folders, `extras`, `trailers`,
  `samples` and similar folders, `*-trailer` and `*-sample` files, and
  anything deeper than 10 levels.
- Bumping `PARSER_VERSION` re-titles every file at the next sync.

### Artwork priority

1. Sidecar: `<stem>-poster`, `-cover`, `<stem>`, `-thumb`, `-fanart`.
2. Folder art (`poster`, `folder`, `cover`, `movie`, `show`), used only when
   the folder holds a single film.
3. Embedded cover (MKV attachment, MP4 `covr`). A file is read only when new
   or changed.
4. OMDb.

TV shows get a show poster from `poster.jpg` in a folder named after the show.
Season art comes from `seasonNN-poster` or the season folder's folder art.
OMDb supplies show-level posters only.

### OMDb behaviour

- Lookup order: exact title + year (`t=`), then search (`s=`), then `i=`.
  OMDb's `t=` is fuzzy, so a result is accepted only when the normalised title
  matches (ignoring punctuation and a leading The/A/An) and the year is within
  ±1. Otherwise the result is NOT_FOUND and a placeholder tile is shown, never
  a wrong poster.
- Images that are not poster-shaped (height/width < 1.25) are rejected. IMDb
  serves cast headshots for new titles with no poster yet. The
  `img.omdbapi.com` poster API is then tried.
- Downloaded posters are saved **next to the media** as `<stem>-poster.jpg`,
  or `<show>\poster.jpg` when the folder is named after the show. Existing
  files are never overwritten. A read-only folder falls back to the cache only.
- A deleted downloaded poster is fetched and saved again at the next start
  (maintainer's choice).
- A title OMDb doesn't know is retried after 7 days (`OMDB_RETRY_DAYS`).
- The daily budget is 900 requests (`OMDB_DAILY_REQUESTS`), tracked in the
  `meta` table. Being offline or hitting the request limit stops the online
  phase for that sync; the local library is unaffected.

### Config (AppConfig in [model.py](../src/unplugged-ui/src/mpvprocessor/config/model.py))

| Field | Default | Meaning |
| --- | --- | --- |
| `library_online_art` | `True` | Fetch posters from OMDb |
| `library_save_posters` | `True` | Write downloaded posters next to the media |
| `omdb_api_key` | `""` | Overrides the key built into the app |
| `library_tab` | `"movies"` | Last tab shown |
| `media_folder` | | 1.1.x single folder; migrated into library roots once, then kept as the first root |

### Known limits

- There is no way in the UI to fix a wrong or missing match. Workaround: drop
  the right `<stem>-poster.jpg` next to the file and press Rescan.
- No season posters from OMDb, no backdrops or details page, no watched or
  resume state in the grid.
- OMDb doesn't list some 2026 titles (for example *The Weight*), so they keep
  the placeholder tile.
- A user's own wrong poster file is treated as their artwork and is never
  replaced.

## 4. Settings panel and Super Resolution

File: [ui/s3shell_panel.py](../src/unplugged-ui/src/mpvprocessor/ui/s3shell_panel.py)
(plus scroll support in [settings_window.py](../src/unplugged-ui/src/mpvprocessor/ui/settings_window.py)).

- Section headers are built from the sections that are visible. All sections
  start collapsed and work as an accordion (one open at a time).
- The Output tab shows Calibration LUT, scaling algorithms, Super Resolution
  and Save as PNG. 18 other Output rows are hidden as dev rows; their values
  still load from and save to the INI.
- `out.superRes` is a toggle. The INI and engine keep MPCVR's number: On = 4
  (`SUPERRES_1440p`), Off = 0. Any legacy non-zero value loads as On.
- Turning it on (`_enable_superres`) also forces the shader video processor
  (`shaderVP`) on and moves `texFormat` from 10-bit or 16f to Auto. These are
  written to the INI and sent in one `apply_settings` call. Turning it off
  changes nothing else.
- Hardware limits: no Super Resolution for 10-bit or HDR sources; NVIDIA RTX
  or Intel only. Windows display settings and the NVIDIA Control Panel are
  outside the app.

## 5. Other changes

- [main_window.py](../src/unplugged-ui/src/mpvprocessor/ui/main_window.py):
  - The library panel is larger (about 86% of the window width, up to 1800 px)
    and spans from the status bar to the control bar.
  - `closeEvent` calls `_media_library.shutdown()`, which stops the sync
    thread.
- [unplugged.spec](../src/unplugged-ui/unplugged.spec): `email` and `http` are
  no longer excluded, because `urllib` needs them. Without this the packaged
  app silently fetches no posters.
- Version bumped to 1.2.0 in `__init__.py`, `pyproject.toml` and
  `distrib\unplugged.iss`.
- `.gitignore`: added `_omdb_key.py`.

## 6. Building a release

```powershell
# 1. App (PyInstaller). "Build complete" with exit code 1 is normal.
cd C:\code\unplugged-mpc-hc\src\unplugged-ui
C:\code\unplugged\app\.venv\Scripts\python.exe -m PyInstaller --noconfirm --workpath build\release-1.2.0 unplugged.spec

# 2. Installer (gated: versions, VC++ redist, licences, then Inno Setup)
cd ..\..\distrib
powershell -ExecutionPolicy Bypass -File .\build_unplugged_setup.ps1
```

- `media\_omdb_key.py` must exist on the build machine; it contains
  `OMDB_API_KEY = "<key>"`. It is gitignored, so a fresh clone builds an app
  without OMDb posters unless the key is set in the user's config. Because the
  key ships inside the app, treat it as public.
- Quick test without installing: copy `C:\Program Files\Unplugged` to a test
  folder, then copy `dist\Unplugged` over it. `dist` lacks the `.ax` filters.
  `C:\UnpluggedTest` is set up this way.
- Ad-hoc test scripts are kept in the session folder, not in the repo:
  `lib_test.py` (back end), `lib_omdb_test.py` (OMDb with fakes) and
  `lib_ui_test.py` (offscreen UI). Offscreen runs need
  `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\Windows\Fonts`.

## 7. Validation done

- Back-end, OMDb and UI test scripts: all pass, including after the review
  fixes and the deleted-poster fix.
- Live OMDb against `D:\` (5 movies):
  - Dune, Oddity, 28 Years Later: The Bone Temple and By Any Means show the
    correct posters (checked visually).
  - The Weight (2026) correctly gets no match.
- Deleted-poster tests:
  - A movie on `D:\` with the real OMDb: the poster was saved again.
  - A TV show with a faked OMDb: `poster.jpg` was saved again, and a sync with
    nothing deleted made no extra requests.
- Review fixes:
  - A scan with an unreadable entry keeps all titles.
  - `set_roots` during a sync returns at once.
  - A folder removed mid-sync leaves no orphan titles.
- One code review over all 1.1.1 → 1.2.0 UI changes. Its three findings
  (partial scan marking titles missing, SQLite lock blocking the UI, orphan
  titles after removing a folder) are all fixed.
- Packaged app smoke run from `C:\UnpluggedTest`: posters fetched on a clean
  database.

Not done: install-and-run of the final installer, an upgrade from 1.1.1 with an
existing `media_folder`, a NAS or offline-drive library, a large library
(thousands of files), and Super Resolution on real hardware.

## 8. Artifacts

```text
distrib\out\Unplugged-setup-1.2.0.exe
  Size 185,974,630 bytes   Product version 1.2.0
  SHA-256 65600E1A01637F142E6D709AF95ABF5147BB30993A44353771DA770FEB65F7D3

src\unplugged-ui\dist\Unplugged\Unplugged.exe
  Size 2,435,535 bytes
  SHA-256 E0568B82F31B5ED81B0834A4488041A63A599D24835B94E547B2CEC56FA94FD8

src\unplugged-ui\dist\Unplugged\_internal\s3engine.dll   (unchanged engine)
  SHA-256 0BC47AB9B36EB6FA3760563E1F7D2F5200E7ED825EE3FABFE5129988432F3984
```

`Unplugged-setup-1.1.1-panel-test.exe` in `distrib\out` is an old test build;
do not distribute it.

## 9. Side effects on the dev machine

- `D:\` has `<stem>-poster.jpg` files next to four movies, written by the
  library. They are safe to delete; the app will download them again.
- `%LOCALAPPDATA%\Unplugged\library\` holds the dev database and thumbnails.
- `C:\UnpluggedTest` is a test copy of the app.

## 10. Next steps

1. Install `Unplugged-setup-1.2.0.exe` over 1.1.1 on the HTPC and check:
   - the version shown in the UI;
   - that the 1.1.1 `media_folder` is migrated into the library;
   - posters, and Enter/Back navigation with the remote;
   - Super Resolution On with a 1080p SDR file on RTX hardware.
2. Publish the installer with its SHA-256. Release notes should mention that
   posters are written next to media files, and that this can be turned off
   (`library_save_posters`).
3. Backlog:
   - a "Fix match" UI, a details or backdrop view, season posters, and
     watched or resume state;
   - a tuning guide doc, NLS/zoom/crop aspect presets, FLIRC and Skip remote
     navigation, and progressive disclosure for HDR/ZION settings.

Git (GitHub Desktop's bundled copy):

```powershell
$git = 'C:\Users\satee\AppData\Local\GitHubDesktop\app-3.6.7\resources\app\git\cmd\git.exe'
& $git -C C:\code\unplugged-mpc-hc ls-remote origin refs/heads/zion-s3-shell 'refs/tags/v1.2.0^{}'
```

The working tree contains unrelated tracked build outputs (`tools\...\*.obj`,
`s3engine.lib` and others) and untracked probe and log files. Always stage
explicit paths and never `git add .`.

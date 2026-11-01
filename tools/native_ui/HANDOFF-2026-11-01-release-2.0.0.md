# Handoff — 2026-11-01 — Unplugged 2.0.0 released

Written for a fresh session. The 2.0.0 release is tagged and pushed; this
document is the state, the fixes made on release day, and what remains.

---

## 1. Release state

| What | Where |
|---|---|
| App repo | `C:\code\unplugged-mpc-hc` branch `zion-s3-shell` |
| Release tag | **`v2.0.0`** → commit `bc08ff5af` (annotated tag object `3bcb80a8`) |
| Release commit | `e66be1146` (2.0.0 snapshot), then merge `bc08ff5af` with the remote upload below |
| Renderer | `C:\code\unplugged-VideoRenderer` `zion-ml-phase0`, commit `8e4f9a5` |
| LAV | `C:\code\LAVFilters` `master` already public; ffmpeg submodule `750103e0` public on `lav0.83-decklink` |
| Installer | `distrib\out\Unplugged-setup-2.0.0.exe`, 127,017,620 bytes |
| SHA-256 | `666AA55491E39B764AC2D5980876D9072653350D5E1690896426C361EF26BAED` |

**The upstream MPC-HC `2.0.0` tag already exists (clsid2, 2023).** It was left
untouched; the product release tag is `v2.0.0`. The remote branch also carried
an “Add files via upload” commit of an older 350-line `settings-guide.md`; it was
merged and the conflict resolved in favour of the audited guide.

---

## 2. What changed on release day

### Library index / folders

- `Lib::Open()` now **creates** `%LOCALAPPDATA%\Unplugged\library\` + `art\` and
  the SQLite schema (same `media/library.py` contract), then runs the ALTER
  migrations. Before, a clean machine had no `library.db`, `SetRoots` returned
  false, and the Folders card’s **Done** did nothing and would not close.
- `SetRoots` removes roots **softly** (`present=0`); it no longer deletes rows.
- `ScanAll` no longer runs `DELETE FROM items WHERE root NOT IN (roots)` — the
  hard delete also destroyed art when a folder was removed during a scan. It is
  `HideOrphanRoots()` now (present=0), and `SetRoots` / `OnScanDone` call it too.
- Scan and poster passes carry **generation tokens** (`g_scanGen`, `g_artGen`).
  `StartScan`/`StartArtFetch` supersede rather than refuse; workers check
  `ScanCancelled()`/`g_artGen` and roll back their open directory transaction;
  `OnScanDone`/`OnArtDone` ignore stale generations. The status label therefore
  always belongs to the current scan.
- New DB columns: `art_tries`, `art_next_try`, `genre_checked`.

### Posters

- `ExistingArtFor(title, imdb)` checks `art\omdb_<id>.jpg/png` and
  `art\wiki_<safe title>.jpg/png` **before any network call**. This is how a
  re-added folder and a renamed file recover their poster with zero requests.
- Failures schedule exponential backoff (30 s → 24 h, jittered). A 60 s lazy
  timer in `CPosterPane` (`SetTimer(21)`, `HasArtWorkDue()`) starts a pass only
  when work is due. Rescan clears the retry state.
- Duplicate titles share one `omdb_<id>` file; the second fetch **reuses** the
  file even while the grid holds it open through GDI+.
- One network item per ~120 ms; OMDb `Request limit reached` / `Invalid API key`
  stops the pass.
- Per-URL logging: `got/bytes/fmt/dims/shaped/wide`, plus Wikipedia page/file/
  image steps.
- The OMDb key is **compiled in obfuscated**: `tools/native_ui/gen_omdb_key.ps1`
  (PreBuildEvent) reads the untracked `_omdb_key.py` and writes the gitignored
  `omdb_key_generated.h`. No key file ships. Extracting it is still possible with
  a debugger — a proxy is the only true secret (see Open items).

### NLS defaults

- Enable NLS stays **Off**; the stock profile now fills immediately:
  Bars 100, **Axis Split**, Split 50, Strength 100, Centre 45, Curve 1.2,
  Max distortion 140, Fill mode Auto, **Fill limit 200** (was 105).
- `MigrateNlsDefaults()` (`ui.nlsDefaultsV=2`) rewrites **only** a stored value
  exactly equal to the old default 105 → 200, in the base INI and every preset
  file. User-tuned Axis/Strength/etc. are untouched.
- Proof: `nls_proof` leg `auto-lim200` on a 2.2:1 title →
  `need=19, limit=200, filling=1, warp=11, crop=0`; `auto-def140` (limit 105)
  refuses. Note: `nls_proof.cpp` is the harness; the app itself does not run it.

### Zion / presets

- `MpcPlayer` publishes the renderer’s own `active: yes/no` as `ml.active`; the
  Info panel shows `ZION GRADE` (`Active` / `Inactive (Mode is Off)` /
  `Off (switch is off)` / `Bypassed (passthrough)`).
- `WritePresetDefaults` stores **engine values** (`optvals[defOpt]`), not option
  indices; a fresh Preset 1 used to apply `ml.mode=0` (Off) and veto the grade.
- The ML enable switch re-asserts `ml.mode` on **every** enable, not just the
  Off→Auto bump.

### Docs

- `docs/settings-guide.md` audited against the row table: every visible row is
  present; defaults match. Fixed: preset scope contradiction, first-start
  presets, Esc/VP key claims, live-vs-next-open markers, limitations; the
  “Hidden developer rows” bullet was removed at the operator’s request.
- `docs/RELEASE-NOTES-2.0.0.md` carries the final installer size/hash.

---

## 3. Verification evidence

| Test | Result |
|---|---|
| Fresh profile (`LOCALAPPDATA` redirected) | `library.db` + `art\` created; `library: index open, 0 present titles` |
| Fresh Preset 1 | `zion.enabled=1`, `zion.toneMode=2` |
| Disk recovery | Bad Apples: `reuse: file on disk`, no URL attempts |
| Backoff + timer | `retry 1 in 24s`, `retry 2 in 49s`; timer fired at 60 s |
| Root soft-removal | 245 F:\ rows `present=0`; 37 art + 208 show_art preserved; Rescan restored 245 unchanged |
| NLS defaults | fresh profile `nlsAxis=3, nlsFillLimit=200, nlsStrength=100, nls=0` |
| NLS engine | proof table in §2 |

---

## 4. Build & package

```powershell
$env:PATH = "$env:LOCALAPPDATA\GitHubDesktop\app-3.6.7\resources\app\git\cmd;" + $env:PATH
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"   # ENGINE_EXIT=0
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"    # S3ENGINE_BUILD_EXIT=0
Copy-Item tools\s3engine\s3engine.dll bin\app\Release\ -Force
& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' `
  'C:\code\unplugged-mpc-hc\tools\native_ui\native_ui.vcxproj' /p:Configuration=Release /p:Platform=x64
# renderer:
cmd /c "C:\code\unplugged-VideoRenderer\_rebuild_mpcvr.bat"
# ingest:
cmd /c "C:\code\unplugged-mpc-hc\tools\decklink_monitor\build_monitor.bat"
& '...\MSBuild.exe' 'src\thirdparty\DeckLinkSource\DeckLinkSource.vcxproj' `
  '/p:Configuration=Release Filter' /p:Platform=x64 /p:SolutionDir=C:\code\unplugged-mpc-hc\
Copy-Item bin\Filters_x64\DeckLinkSource.ax src\thirdparty\DeckLinkSource\bin\Filters_x64\ -Force
# stage + installer:
Copy-Item bin\app\Release\Unplugged.exe dist\Unplugged-2.0.0\ -Force
Copy-Item tools\s3engine\s3engine.dll dist\Unplugged-2.0.0\ -Force
Copy-Item tools\decklink_monitor\decklink_monitor.dll dist\Unplugged-2.0.0\ -Force
Copy-Item docs\settings-guide.md dist\Unplugged-2.0.0\docs\ -Force
powershell -File C:\code\unplugged-mpc-hc\distrib\build_unplugged_setup.ps1
```

The installer gate compares the staged exe/s3engine/monitor/guide hashes with the
build outputs. Stage **all four** after every rebuild or it refuses (or worse,
ships stale).

---

## 5. Traps

1. **Scan generations.** Any new scan/art loop must check `ScanCancelled()` /
   `g_artGen`; geometry or DB writes after a folder edit can re-present a
   removed root. The scan rolls back its open directory transaction on cancel.
2. **Never hard-delete orphan rows.** `HideOrphanRoots()` only. Art is the
   recovery source for a re-added folder.
3. **`art_checked` is not a verdict.** It is the last attempt; `art_tries` +
   `art_next_try` decide the retry, and empty-art rows retry.
4. **Key files are gitignored**: `_omdb_key.py` and `omdb_key_generated.h`.
   Never commit either; the generator reads the key at build time.
5. **Upstream `2.0.0` tag exists.** Product tags are `vX.Y.Z`.
6. **`git` is not on PATH** (GitHub Desktop copy); the commit-msg hook is
   installed in the main and renderer repos and strips AI attribution.
7. **Auto fill needs a confirmed bar band.** On live capture it appears after a
   moment; `fill refused` in `[NLS]` means the band was not valid yet.
8. **MSBuild may skip a relink** if the exe is newer than the source. Check
   mtimes, don’t trust “build succeeded”.
9. **Log locations:** dev exe → `bin\app\Release\native_ui_log.txt`; installed
   app → `%LOCALAPPDATA%\Unplugged\logs\native_ui_log.txt`; engine →
   `%USERPROFILE%\.unplugged\logs\engine.log`; renderer →
   `{app}\filters\mpcvr_trace.log` or the per-user logs folder.

---

## 6. Open items

- **Operator to test the fixed folder flow on the running app:** add a drive,
  remove it mid-scan, re-add it, remove while posters fetch. Watch for
  `library scan: starting ... (gen N)`, `cancelled`, `stale done ... ignored`,
  `orphan roots hidden`; posters must return from disk on re-add.
- **Their library DB was emptied by the pre-fix test.** Add the drives back; the
  art files remain in `%LOCALAPPDATA%\Unplugged\library\art\` and should be
  reused without re-downloading.
- **Mid-scan removal not yet executed end-to-end** (the synthetic test was
  interrupted). The generation/rollback code is in place; verify with the log
  lines above.
- **OMDb key secrecy.** The obfuscated blob defeats `strings`, not a debugger.
  If the paid key’s quota is abused, implement the proxy (lookup + poster
  endpoints, cache, rate limit) and rotate.
- **Scan progress messages** (`WM_APP+28`) do not carry a generation; a stale
  progress line can briefly show old counts. Done messages do carry it.
- Release notes short-form text and the AVSForum one-liner were provided in the
  session but are not stored in the repo.

---

## 7. Where to look

- `tools/native_ui/native_ui.cpp` — `Lib` (index/scan/art), `CPosterPane`
  (generations, timer), `CFoldersCard`, preset/migration code.
- `src/mpchc_engine/MpcPlayer.cpp` — NLS helpers (`NlsSplitFactors`,
  `NlsPartialFill`, `NlsFillAction`), ML active publish.
- `docs/settings-guide.md`, `docs/RELEASE-NOTES-2.0.0.md`.
- Prior handoffs: `HANDOFF-2026-10-30-late.md` (NLS mechanics),
  `HANDOFF-2026-10-30-evening.md`.
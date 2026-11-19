# Handover — Unplugged 2.3.0 (ClipGuard)

Written 2026-11-18.

- App repository: `C:\code\unplugged-mpc-hc`, branch `zion-s3-shell`, HEAD `7b18fe3f5`.
- Renderer repository: `C:\code\unplugged-VideoRenderer`, HEAD `4e2227d`, tag `v2.2.1`.
- LAV repository: unchanged from 2.2.0.

## Start here

2.3.0 replaces the old DBLE compensation with **ClipGuard**, integrated natively
into the app and the renderer. The code for the planned scope is in the tree and
has passed targeted development tests. What remains is **packaging, the
install-over regression, and three release-document corrections** — not feature
work.

Do not publish the existing `distrib\out\Unplugged-setup-2.3.0.exe`. It was
built on 13 November and bundles the old renderer staging
(`UnpluggedRenderer-0.10.9.2637`, Bilinear chroma default). The current renderer
staging is `0.11.0.2637` with KrigBilateral, and `distrib\unplugged.iss` already
points at it. The installer must be rebuilt.

The standalone renderer has already shipped separately as **2.2.1**. It is the
same 0.11.0.2637 binary the app bundles. Do not create a 2.3.0 renderer package;
do not reuse the `v2.2.2` number (it was created and then folded back into
`v2.2.1` on 18 November).

## 1. Scope of the release

- Remove the 2.2.0 final-pass DBLE path completely (shader + engine fields).
- Port ClipGuard 2.25.4 natively into the renderer (`CDbleFix`) and expose it
  through `Settings_t.clipGuard`; no shared memory, no `clipguard.ini`.
- Replace the app's **DBLE COMPENSATION** settings section with **CLIPGUARD**
  under Tone Mapping, including the overlay and hotkeys.
- Migrate a 2.2.0 user's DBLE configuration on first launch.
- Keep look-ahead Off by default and force it Off in live capture.
- Make the overlay and its diagnostic View session-only (always launch Off /
  Normal).
- Update the settings guide and release notes.

Not in scope: presets carrying ClipGuard (it is classified as a device setting),
standalone 3D LUT authoring, HDR passthrough behaviour.

## 2. How the feature flows

```
native rail row (hdr.cg*)
  -> settings.ini  (%LOCALAPPDATA%\Unplugged\settings.ini)
  -> MpcPlayer::HdrSettings (cg*)
  -> Settings_t::clipGuard (renderer header struct)
  -> CDbleFix::SetNativeSettings
  -> DX11 post-scale pass: measure -> apply -> overlay
```

- The renderer receives the whole block once through `Configure`/`SetSettings`.
  `CDbleFix` only polls the contributor's old shared-memory path when
  `m_native == false`.
- Measurement and application happen in the DX11 post-scale chain, on the
  finished SDR picture, before the final display-transfer / LUT pass.
- The app supplies the visible-picture safe rect on every Layout
  (`hdr.cgOsdX/Y/W/H`). The overlay anchors bottom-left inside that rect so the
  status and settings panels never cover it.
- `hdr.cgLog` is a one-shot request counter: the app increments it on F11, the
  renderer writes the last 30 s of readout plus a screenshot under
  `%LOCALAPPDATA%\Unplugged\logs\clipguard`.

## 3. Settings contract

All keys are in `[hdr]` of the app settings INI and map 1:1 to
`ClipGuardSettings` in the renderer.

| Key | UI label | Range / values | Default |
| --- | --- | --- | --- |
| `hdr.cgEnabled` | Enable ClipGuard | Off / On | Off |
| `hdr.cgStrength` | Strength | 0 .. 1, step 0.01 | 0.35 |
| `hdr.cgShape` | Fix shape | 0 Normal, 1 Anchor | 1 Anchor |
| `hdr.cgFixStart` | Fix starts (%) | 1 .. 50, step 0.5 | 10 |
| `hdr.cgFull` | Full effect (%) | 0.5 .. 49.5, step 0.5 | 3 |
| `hdr.cgKnee` | Highlight start | 0.20 .. 0.95 | 0.40 |
| `hdr.cgColor` | Color protect | 0 .. 1 | 0.90 |
| `hdr.cgText` | Text skip (%) | 0 .. 100 | 25 |
| `hdr.cgHot` | Hot spot | 0 .. 1 | 0.60 |
| `hdr.cgHotBelow` | Hot spot below (%) | 0 .. 20 | 3.0 |
| `hdr.cgGraded` | Graded spot | 0 .. 1, step 0.05 | 0.50 |
| `hdr.cgGrid` | Grid | 0 Normal (128x72), 1 Fine (256x144) | 1 Fine |
| `hdr.cgLookAhead` | Look-ahead | 0 / 2 / 4 / 6 frames | 0 Off |
| `hdr.cgView` | View | 0 Normal, 1 Fix areas, 2 Split, 3 Side by side | 0 |
| `hdr.cgOsd` | OSD | Off / On | Off |
| `hdr.cgOsdPin` | OSD pinned | On / Off | On |
| `hdr.cgOsdSel` | selected overlay row | 0 .. 20 | 0 |
| `hdr.cgOsdX/Y/W/H` | safe rect (px) | set by Layout, not a user row | 0 |
| `hdr.cgLog` | F11 request | one-shot counter | 0 |

Rules enforced in code:

- **Device rows.** Every `hdr.cg*` key is a `PresetDeviceRow`: never written
  into a preset, never marks a preset dirty, and changing it while Default is
  active must not trip the read-only notice. The reason is the same as SDR nits
  and display transfer: the projector's dimming behaviour belongs to the room,
  not to a look.
- **Look-ahead.** `MpcPlayer` forces `cgLookAhead = 0` when a DeckLink device is
  open. Holding frames would desync live HDMI audio.
- **Overlay is session-only.** At startup the app rewrites `hdr.cgOsd=False` and
  `hdr.cgView=0` and saves, even if the INI said otherwise.
- **Gating.** Views and the fix pass are gated on `enabled`; with ClipGuard off
  the picture must be untouched. This was a 2.2.0 regression (red tint) and must
  not come back.

### Migration from DBLE (once per profile)

`MigrateDbleToClipGuard` runs at startup, before presets, only when the raw INI
did **not** already contain `hdr.cgEnabled`. That raw-file check matters: the INI
is seeded with defaults in memory before migration, so an in-memory lookup can
never tell a fresh profile from a 2.2.0 profile.

Mapping:

| Old | New |
| --- | --- |
| `hdr.dble` | `hdr.cgEnabled` |
| `hdr.dbleStrength` | `hdr.cgStrength` |
| `hdr.dbleTrigger` | `hdr.cgFixStart` |
| `hdr.dbleTrigger / 4` (min 0.5) | `hdr.cgFull` |
| `hdr.dbleKnee` | `hdr.cgKnee` |
| — | `cgShape=0` Normal (old squeeze) |
| — | `cgGrid=0` Normal |
| — | `cgColor/Text/Hot/HotBelow/Graded = 0` |
| — | `cgLookAhead=0`, `cgView=0`, `cgOsd=False` |

If `hdr.dble` is absent, nothing is written — a fresh install stays Off.

## 4. Files

### App repository (all currently uncommitted)

| File | Change |
| --- | --- |
| `tools/native_ui/native_ui.cpp` | CLIPGUARD rows replace DBLE; migration; F7-F11 and Ctrl+Alt hotkeys; overlay state, plain-arrow grab, restart row; app version 2.3.0; earlier display-surface and `%s` frame-capture fixes |
| `tools/native_ui/Unplugged.rc` | file/product version 2.3.0 |
| `src/mpchc_engine/MpcPlayer.h` | `HdrSettings` DBLE fields replaced by `cg*` with defaults |
| `src/mpchc_engine/MpcPlayer.cpp` | `hdr.cg*` parser, `Settings_t.clipGuard` mapping in both directions, look-ahead forced 0 for DeckLink |
| `distrib/unplugged.iss` | app 2.3.0; `FiltersSrc` -> `UnpluggedRenderer-0.11.0.2637`; `AppSrc` -> `dist\Unplugged-2.3.0` |
| `docs/settings-guide.md` | ClipGuard section, device-row list, hotkeys, recipes, migration note, 2.3.0 stamp |
| `tools/s3engine/s3engine.dll`, `.obj` | rebuilt engine output; tracked binaries, include them in the commit |

Relevant untracked files:

- `docs/RELEASE-NOTES-2.3.0.md` — draft, currently **wrong**: it cites
  `UnpluggedRenderer-setup-2.3.0.exe` and stale hashes.
- `docs/ClipGuard-Settings-Guide.pdf` — contributor reference, keep.
- `docs/clipguard-*.png` — test screenshots; decide whether to keep before commit.

### Renderer repository (committed at `4e2227d`, tag `v2.2.1`)

| File | Change |
| --- | --- |
| `Source/ClipGuard.h` | native port of the contributed DBLEFix: measurement, tracking, anchor/hot/graded logic, overlay, F11 logging |
| `Source/ClipGuardSettings.h` | plain settings block carried in `Settings_t` |
| `Source/IVideoRenderer.h` | `ClipGuardSettings clipGuard`; DBLE fields removed; renderer defaults (SDR 80, Unplugged curve, ML Auto, Krig chroma, etc.) |
| `Source/DX11VideoProcessor.cpp/.h` | measure/apply/look-ahead ring/overlay; DBLE final-pass code removed |
| `Shaders/d3d11/ps_final_pass.hlsl` | DBLE code and uniforms removed; cbuffer reduced to 16 floats |
| `Source/VideoRenderer.cpp` | registry load/save for `clipGuard`, startup `Configure(m_Sets)`, defaults |
| `Source/PropPage.cpp` | standalone HDR page: core ClipGuard controls, complete Output gamut / Display transfer lists |
| `Source/VideoProcessor.h` | `m_clipGuard`, Krig default |
| `Include/Version.h` | 0.11.0.2637 |
| `distrib/*` | standalone 2.2.1 package, Readme, version |

## 5. Build and package

Build order matters: the engine exposes `Settings_t`; a stale `s3engine.dll` built
against a different layout crashed the app at startup with a dump. Rebuild and
re-stage everything the payload contains.

```powershell
# 1. Renderer (only if renderer source changed)
Push-Location C:\code\unplugged-VideoRenderer
MSBuild.exe MpcVideoRenderer.sln /p:Configuration=Release /p:Platform=x64 /m /nologo /verbosity:minimal
Pop-Location
# refresh the staging folder the app installer consumes
Push-Location C:\code\unplugged-VideoRenderer\distrib
cmd /c make_dist.cmd
Pop-Location

# 2. Engine
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"

# 3. s3engine
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"

# 4. Native app
MSBuild.exe C:\code\unplugged-mpc-hc\tools\native_ui\native_ui.vcxproj `
  /p:Configuration=Release /p:Platform=x64 /m /nologo /verbosity:minimal

# 5. DeckLink monitor (only if its source changed)
cmd /c "C:\code\unplugged-mpc-hc\tools\decklink_monitor\build_monitor.bat"

# 6. Stage the payload
Copy-Item C:\code\unplugged-mpc-hc\bin\app\Release\Unplugged.exe,
          C:\code\unplugged-mpc-hc\bin\app\Release\s3engine.dll,
          C:\code\unplugged-mpc-hc\bin\app\Release\decklink_monitor.dll `
  C:\code\unplugged-mpc-hc\dist\Unplugged-2.3.0\ -Force
Copy-Item C:\code\unplugged-mpc-hc\docs\settings-guide.md `
  C:\code\unplugged-mpc-hc\dist\Unplugged-2.3.0\docs\ -Force

# 7. Build the installer (do not use -ExecutionPolicy Bypass)
& C:\code\unplugged-mpc-hc\distrib\build_unplugged_setup.ps1
```

`build_unplugged_setup.ps1` gates:

- app `ProductVersion` must start with `2.3.0`;
- `docs\settings-guide.md` must carry `For **Unplugged 2.3.0**`;
- staged `Unplugged.exe`, `s3engine.dll`, `decklink_monitor.dll` must hash-match
  `bin\app\Release`;
- staged `docs\settings-guide.md` must hash-match the repo copy;
- every `Source` path in `unplugged.iss` must exist (renderer, LAV,
  DeckLinkSource, redist).

The renderer payload comes from
`unplugged-VideoRenderer\_bin\UnpluggedRenderer-0.11.0.2637`; `make_dist.cmd`
refreshes it from `_bin\Filter_x64`.

## 6. Test status

### Verified during development

- ClipGuard runs in Video Processor mode; engine log shows `[CG] en=1` and the
  Picture/Fix/White readout changes with scene content.
- Overlay draws in the safe rect; F11 writes the CSV and BMP under
  `%LOCALAPPDATA%\Unplugged\logs\clipguard`.
- DBLE -> ClipGuard migration validated against a simulated 2.2.0 profile:
  enabled state, strength, trigger, full effect (trigger/4) and knee preserved;
  Normal shape, no hot/graded/text, no look-ahead.
- Overlay stays anchored while the status/settings panels open and close.
- 3840x2160 window: the one-pixel host line is gone; OSD does not drift.
- Media Player mode no longer shows Video Processor as active from stale
  defaults; header reads `MEDIA SOURCE`.
- Ctrl+S frame capture works from the installed app (the earlier `%S` bug is
  fixed).
- Standalone renderer 2.2.1: saved settings apply at startup (no property-page
  visit needed); fresh-install defaults are ML Auto + Unplugged curve + Krig.

### Still to verify before release

- [ ] Install the rebuilt 2.3.0 over 2.2.0 on a profile that has real DBLE
      configured; confirm the migration and that presets/library survive.
- [ ] Fresh-profile run (settings wiped) with the rebuilt installer: ClipGuard
      Off, overlay Off, View Normal, Krig chroma.
- [ ] Preset behaviour: with Default active, change a `hdr.cg*` row and confirm
      no dirty marker and no read-only notice; create/apply a custom preset and
      confirm ClipGuard is neither stored nor changed by it.
- [ ] All hotkeys in both modes: F7/F8/F9/F10/F11, Ctrl+Alt+0/D, arrows only
      while the overlay is visible, Restart row.
- [ ] Look-ahead 0/2/4/6 in file playback; confirm forced 0 with a DeckLink
      device open (log or engine dump).
- [ ] Standalone renderer property page: core ClipGuard controls save and apply.
- [ ] HDR passthrough untouched; ClipGuard inert when off.
- [ ] Uninstall/reinstall and standalone-renderer coexistence.
- [ ] Check the app after a reboot for the session-only overlay reset.

## 7. Traps already paid for

1. **Stale native = startup crash.** Changing `Settings_t` without rebuilding
   `s3engine.dll`/engine produced a dump on launch. The installer gate now
   hash-checks the three natives and the guide; keep it.
2. **Migration must read the raw INI.** The in-memory map is seeded with defaults
   before migration, so `IniGet("hdr.cgEnabled")` is always non-empty. Use
   `RawIniHasKey` before `LoadSettingsIni`.
3. **`std::max` is a Windows macro.** In migration code use a ternary; otherwise
   the build fails at `std::max`.
4. **Overlay must not move upward.** It once anchored to a measured bottom bar
   that fluctuated. It now uses the safe rect from Layout. Keep the panel size
   stable: reserve readout width and six lines, and cache the render-target size
   per window.
5. **Overlay saved On reappears at launch.** It is session state; force
   `cgOsd=False`, `cgView=0` at startup and save.
6. **Look-ahead desyncs live audio.** Always force 0 when
   `decklinkDevice_` is non-empty, regardless of the INI.
7. **Wide-format bug.** `swprintf_s(..., "%Sunplugged...")` used `%S` (narrow)
   with a wide buffer, producing a relative filename in Program Files. The fixed
   path is `%s` in both frame-save functions.
8. **Fix-off must be pixel-identical.** Any view or pass not gated on `enabled`
   will tint or process the picture; this was the 2.2.0 red-highlight bug.
9. **Property-page changes need re-registration.** Adding or changing a COM
   property page requires `regsvr32` again before the player can see it.
10. **Don't tidy by deleting untracked logs.** The repo root is full of
    `_build_*.log` and probe artifacts; they are not part of 2.3.0.

## 8. Open items and corrections before release

1. **Rebuild the app installer.** The current one is from 13 November and
   bundles renderer 0.10.9.2637 (Bilinear chroma). The tree expects 0.11.0.2637.
2. **Fix `docs/RELEASE-NOTES-2.3.0.md`.**
   - It lists `UnpluggedRenderer-setup-2.3.0.exe`, which does not exist and must
     not be created. The standalone renderer release is 2.2.1; either link to it
     or drop the row.
   - Replace both size/hash rows with the actual rebuilt artifacts.
   - Confirm every claim against the shipped property page; the earlier draft
     claimed features the standalone renderer does not expose.
3. **Website.** `website/guide.html` is already 2.3.0/ClipGuard, but
   `website/index.html` and `website/download.html` still describe 2.2.0/DBLE as
   the latest release. Regenerate the release data and update both pages after
   the installer hash is final.
4. **Cosmetic cleanup (optional, low risk).**
   - `tools/native_ui/native_ui.cpp` line ~1463 still says "DBLE compensation"
     in the `PresetDeviceRow` comment.
   - The overlay hotkey IDs and a few locals still carry `DBLE`/`dble` names;
     renaming is not worth the churn before release.
5. **Stale artifacts removed/left.**
   - Removed: `UnpluggedRenderer-setup-2.2.2.exe` and
     `UnpluggedRenderer-setup-2.3.0.exe`.
   - Kept but stale: `distrib\out\Unplugged-setup-2.3.0.exe` (13 November).
6. **Decide the preset question explicitly.** ClipGuard currently behaves like
   SDR nits / display transfer: one INI value per machine, never in a preset. If
   that is not wanted, changing it requires touching `PresetDeviceRow`, the
   preset writer and the docs together.

## 9. Release checklist

- [ ] Clean-profile smoke test of the rebuilt installer.
- [ ] Install-over-2.2.0 upgrade test with a real DBLE profile.
- [ ] Record installer size and SHA-256.
- [ ] Correct release notes and remove the non-existent renderer 2.3.0 download.
- [ ] Commit the app tree: the six source/doc files plus the two tracked
      s3engine binaries. Exclude logs and probe output.
- [ ] Tag the app repository `v2.3.0` (annotated) and push branch + tag.
- [ ] Renderer: already `v2.2.1` at `4e2227d`; do not move or recreate it unless
      renderer code changes, in which case build a new renderer package version.
- [ ] LAV: unchanged. Decide whether to tag it `v2.3.0` for consistency with the
      2.2.0 release convention; no binary needs rebuilding.
- [ ] Update website download/index/release data.
- [ ] Do not attach the standalone renderer 2.3.0 package; there is none.

## 10. Where to look first

- App rows and overlay UI: `tools/native_ui/native_ui.cpp`, search
  `CLIPGUARD`.
- Migration: `MigrateDbleToClipGuard` (`native_ui.cpp` ~1669), called from
  `Create2` (~9628).
- Engine mapping: `MpcPlayer.cpp`, search `clipGuard`.
- Renderer algorithm: `Source/ClipGuard.h`, search `BeginFrame`, `Measure`,
  `Apply`, `Render`.
- Renderer hooks: `Source/DX11VideoProcessor.cpp`, search `ClipGuard`
  (~1021, ~5382, ~8168, ~8911, ~9653, ~10481).
- Settings guide: `docs/settings-guide.md`, section `### ClipGuard`.
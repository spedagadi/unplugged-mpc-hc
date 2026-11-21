# Handover — Unplugged 2.3.0 release state (2026-11-21)

This is the release handoff after the projector 10-bit / SDR BT.2020 tests
passed. Both repositories are committed, tagged and pushed. The installers are
built locally; GitHub release assets and the website are the remaining release
steps.

## Repositories and tags

| Repo | Branch | Commit | Tag `v2.3.0` |
| --- | --- | --- | --- |
| `unplugged-mpc-hc` | `zion-s3-shell` | `36456d07a` | annotated tag `c221fee04` -> `36456d07a` |
| `unplugged-VideoRenderer` | `zion-ml-phase0` | `8cf2d01` | annotated tag `72f6ff3` -> `8cf2d01` |

Both tags were **force-moved** from older commits:

- app `15281ba57` -> `36456d07a`
- renderer `b58a0be` -> `8cf2d01`

Collaborators must run `git fetch --tags --force` to see the new tag targets.
Both branches are pushed and clean apart from untracked logs/artifacts.

## Release artifacts

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `distrib/out/Unplugged-setup-2.3.0.exe` | 125,595,846 | `87E3EF6E13B96AD2EA60D5481F7B3FFBBA7BC711BA5D2453EB36C86BC2B4FB70` |
| `unplugged-VideoRenderer/distrib/out/UnpluggedRenderer-setup-2.3.0.exe` | 41,804,451 | `D43244D161E7DDC9D7C15565A3A310666CD72D9CDD0F5F2F63A3580E75526B94` |

Both installers must be uploaded. The app installer already contains the
matching renderer build; do not publish a 2.3.0 app with the 2.2.1 renderer or
vice versa.

## What changed in this release

### Aspect-aware NLS / IMAX

- `NlsAspectPoll` accepts a **0.05 detection tolerance above Native max**:
  effective Native <= 1.95 with the 1.90 row. Real 1.90 IMAX detected at
  1.926/1.941 now stays **Native**, `bars=0 crop=0/0`.
- Entering Native from Scope or Small-bars uses `nativeMax + 0.05`; leaving
  Native requires `> nativeMax + 0.05`. The old code required dropping to 1.85,
  which misclassified every IMAX cut as Small-bars.
- Small-bars still applies 100 % bar removal; a 2.00 film is not swallowed by
  the tolerance.
- Verified on a 3840x2160 canvas with Spider-Man: Far From Home:
  `1.941 -> native`, `2.415 -> scope`, alternating cleanly.
- Native 1.200/1.333/1.501/1.79/1.85 and scope 2.370/2.388/2.415 unchanged.
- Lock band is forced off while the aspect rule is on.
- A real 2.00:1 title is **not** in the library; the Small-bars window was
  proven with the documented threshold-move fallback (Scope min 2.60).

### 2.2.0 migration

- Follow source -> Display gamut BT.2020; SDR BT.2020 **Off** (old SDR was 709).
- BT.709 -> Auto (BT.709); SDR Off.
- BT.2020 -> Display gamut BT.2020; SDR BT.2020 **On** (preserves old SDR).
- DCI-P3 -> Display gamut DCI-P3; SDR Off (no SDR P3 signal).
- `hdr.tenBitSdr` is internal, ignored and preset-ineligible.

### 10-bit / gamut / SDR BT.2020

- 10-bit is automatic when the display link reports 10 bpc; no toast and no
  fake force-10-bit switch. The Info panel shows `OUTPUT DEPTH`.
- SDR defaults to BT.709. **SDR BT.2020 (projector)** is the only SDR wide-gamut
  switch. Display gamut applies to HDR/DV only.
- Projector tests passed for 10-bit SDR BT.2020 and HDR->SDR BT.2020.
- 4K60 over HDMI may still be 8-bit; DisplayPort or a lower refresh is the
  bandwidth lever.

### Renderer property page

- **3D LUT** group: file picker, Off / Gamma only / Greyscale / Full 3D, Clear.
  Path and mode persist in renderer settings and reload on graph/device rebuild.
- **SDR BT.2020 (projector)** checkbox next to Output gamut.
- **10-bit** note: output follows the display link; set 10 bpc in the GPU driver.
- ClipGuard controls remain out of the property page; ClipGuard is a separate
  release.
- `Settings_t` gained the LUT path/mode fields, so app, `s3engine.dll` and
  renderer were rebuilt together. This is the ABI trap for the next session.

### Documentation

- `docs/settings-guide.md`: simplified 10-bit/gamut guidance; simple
  "does the display have SDR BT.2020?" rule; migration table; Name-free public
  docs; ClipGuard sections removed.
- `docs/NLS-ASPECT-TEST-PLAN.md`: 16:9 canvas requirement, Native tolerance.
- `docs/RELEASE-NOTES-2.3.0.md`: both installer hashes, renderer property-page
  features, IMAX fix.
- Internal audit files updated with the field evidence.

## Test status

Passed:

- Projector 10-bit + SDR BT.2020 (reported 2026-11-21).
- NLS native/scope/IMAX, Lock band, scope 50 %, forced Small-bars, regression
  on native and scope titles.
- App and renderer builds are clean; installer gates passed.

Still worth doing:

- **Visual smoke test of the new renderer property page in MPC-HC/MPC-BE**
  (3D LUT load, mode, Apply, graph restart, persistence).
- Install-over-2.2.0 upgrade test on a real profile.
- Real 2.00:1 content for the Small-bars window.
- P3 SDR remains a documented compromise (no SDR P3 signal).

## Remaining release work

1. Create the GitHub releases for both `v2.3.0` tags and upload the two setup
   files. Use the short community bullets / release notes in
   `docs/RELEASE-NOTES-2.3.0.md`.
2. Verify the uploaded asset sizes and SHA-256 values above.
3. Update `website/release.json`, `website/index.html` and
   `website/download.html` to 2.3.0 and both downloads.
4. Tell collaborators the tags were force-moved: `git fetch --tags --force`.
5. Optional next renderer feature: opt-in **Match display refresh** on the
   property page. The renderer knows `m_rtAvgTimePerFrame` and already has
   DisplayConfig + `ChangeDisplaySettingsExW`; frame matching is deliberately
   app/player-side today. Do not claim it in 2.3.0.
6. Coordinate the separate ClipGuard release; no ClipGuard UI/hotkeys in the
   shell or renderer property page.

## Build traps

- **Renderer x64 only.** `build_mpcvr.cmd` stops on the x86 link
  (`OrtGetApiBase`, `OrtSessionOptionsAppendExecutionProvider_DML` unresolved).
  Build x64 directly:
  ```powershell
  cmd /c "CALL ""C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat"" -arch=amd64 -host_arch=amd64 -no_logo >nul && cd /d C:\code\unplugged-VideoRenderer && MSBuild.exe MpcVideoRenderer.sln /nologo /maxcpucount /nodeReuse:true /target:Build /p:Configuration=Release /p:Platform=x64"
  ```
  Then `distrib\build_renderer_setup.ps1`.
- **Settings_t ABI.** Any change to `IVideoRenderer.h` Settings_t requires:
  renderer x64 build -> `make_dist.cmd` -> rebuild engine
  (`tools\engine_s3\rebuild_engine.bat`) -> `tools\s3engine\build_s3engine.bat`
  -> native UI MSBuild -> re-stage app -> rebuild app installer.
- **App installer staging.** Stage `Unplugged.exe`, `s3engine.dll`,
  `decklink_monitor.dll` and `docs/settings-guide.md` into
  `dist\Unplugged-2.3.0`; `build_unplugged_setup.ps1` hash-gates them.
- **Guide stamp.** `docs/settings-guide.md` must say
  `For **Unplugged 2.3.0**` or the installer gate fails.
- **Tag pushes.** Existing tags were force-updated; ordinary `git fetch` will
  keep the old ones. Use `git fetch --tags --force`.
- **Do not mix builds.** The app and standalone renderer 2.3.0 packages are a
  pair because of the Settings_t change.

## Key files

- `docs/RELEASE-NOTES-2.3.0.md` — release notes and hashes.
- `docs/settings-guide.md` — public guide, name-free, no ClipGuard.
- `docs/NLS-ASPECT-TEST-PLAN.md` — NLS field test evidence.
- `docs/FEEDBACK-AUDIT-2.3.0.md`, `docs/USER-REPORTS.md`,
  `docs/AUDIT-2.3.0-COMPLETE.md` — internal audit.
- `tools/native_ui/native_ui.cpp` — NLS tolerance/migration, 10-bit advice.
- `C:\code\unplugged-VideoRenderer\Source\PropPage.cpp` — LUT/SDR BT2020 UI.
- `C:\code\unplugged-VideoRenderer\Source\DX11VideoProcessor.cpp` — LUT apply.
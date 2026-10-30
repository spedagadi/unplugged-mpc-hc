# Handoff - 2026-10-30, late session (bidirectional NLS)

Written for a fresh session. Supersedes **§9** of `HANDOFF-2026-10-30-evening.md`
(the approved-but-unimplemented feature) and answers **§7** (the contract now
describes the build). Everything else in the evening handoff still stands.

App is NOT running at the end. `Unplugged.exe`, `s3engine.dll` and
`mpchc_engine.lib` were rebuilt and staged; the engine log shows the run.

---

## 1. What shipped

| Commit | What |
|---|---|
| `0f6e224d2` | `tools/native_ui/` is finally in git (source, project, docs, WebView2 vendor); obj/snapshots/screenshots ignored |
| `7fbbbb3eb` | the engine's two sessions of uncommitted work (NLS, geometry, picture canvas, chapters, the pumping op-loop) |
| `9cfc2f106` | s3engine: chapter thumbnails, `stopgraph`, `videorect`, `step`, `chapter` |
| `71375cf37` | renderer: subtitle queue-leg witness (diagnostic only) |
| `a7a7543e0` | sub_proof: English legs, gate each subtrack on "playing", engine path in argv[2] |
| `f37701088` | 2.0.0 installer paths; the settings guide covers Geometry/NLS/keys |
| `d0d1227aa` | the PyQt 1.3.1 work (window-scoped input, video as its own top-level) |
| `71959f47a` | **bidirectional NLS** (+ two ordering defects it exposed, + the INI optvals fix) |
| `7379970d9` | UI-CONTRACT now describes the chrome that actually shipped |

`src/unplugged-ui/` and `tools/mpc_audio_ax/` still carry uncommitted *build
output*; no source there is uncommitted.

---

## 2. Bidirectional NLS - what was built

The evening handoff's §9B formula had a sign error: `sy = pow(k, 1-s)` gives
`sx*sy = k`, which does not correct the aspect ratio (at s = 0.5 both axes get
the same factor, so the picture's shape does not change). The correction needs
`sx / sy == k` with `sx * sy == 1` at the midpoint:

```
sx = k^s,  sy = k^(s-1)        k = clientAR / activeAR
```

- `s = 1` → `(k, 1)`: bit-for-bit the old horizontal-only pass.
- `s = 0` → `(1, 1/k)`: the same correction paid on y.
- `s = 0.5` → e.g. k = 0.806 gives 0.899 / 1.113: neither axis carries it all.

Per axis, `Max distortion` caps the warp in **both** directions; whatever the cap
refuses is covered by cropping the axis that has slack (sides when the picture is
still too wide, top/bottom when it is still too narrow). Stretch never crops, so
Stretch is never capped.

Code:
- `src/mpchc_engine/NlsShader.h` - both axes mapped, each with its own protected
  centre (the protected region stays a rectangle, not a cross). An axis at 1.0
  early-outs to the identity, which is what makes the single-axis modes exact.
- `MpcPlayer.cpp` - `NlsSplitFactors()` and `NlsFillAction()` are the ONE
  definitions; `ResizeVideo` (geometry) and `ApplyPostFx` (shader) both call them.
- Shell - Axis is now `Horizontal | Vertical | Split` (the old "Auto" entry was
  hard-wired to horizontal and lied), new `Split` row 0-100 (default 50),
  `Max stretch` renamed `Max distortion`. **Axis defaults to Horizontal**, so
  the dial is opt-in and the default picture is unchanged.

The engine values are `geo.nlsAxis` = 1/2/3 and `geo.nlsSplit` = 0..1. A stored
`0` (the old Auto) falls back to Horizontal on load.

---

## 3. Two real defects the feature exposed (both fixed)

**A. The shader was always one settings-change behind.** `ApplyPostFx` baked the
factors that `ResizeVideo` had *published*, but a settings push can arrive on a
thread that is not the graph thread - where `ResizeVideo` **defers** to the live
thread. So the Split leg injected the previous Horizontal pass, and the Crop leg
got a warp injected on top of its crop. Fixed by deriving both the split factors
and the fill decision from the settings in one shared function each; the
published atomics are now only for the status JSON.

This bug predates the split (it is why NLS changes used to need a second nudge),
and it is invisible in the logs unless you line the `[NLS]` line up against the
`[SETTINGS] received` lines of the *same* push.

**B. `IniValue` wrote the option INDEX, `LoadSettingsIni` matched ENGINE values.**
Any row exposing a subset of an enum (`upscaling` {4,5}, `chromaScaling` {2,3},
`texFormat` {0,8,10,16}, HD audio {1,0}, ...) came back as its row default on the
next launch - and the new Axis row would have resurrected Split as Vertical.
`IniValue` now writes `optvals[opt]` (the tone-curve branch already did). Old
files self-heal on first launch: an unmatched stored number falls back to the row
default and is re-seeded as the engine value.

---

## 4. Verification

**Offline model + shader compile** (no app needed):

```powershell
python -I tools\engine_s3\nls_math_check.py `
  "C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\fxc.exe"
```

Checks: horizontal-only regression against the old formula, `sx/sy == k`,
`cx/cy` making the protected centre exactly isotropic over the whole split/cap
grid, Stretch never cropping, `map_radius` monotone with fixed endpoints, and
the *generated* HLSL compiling for `ps_4_0`. Currently 0 failures.

**Runtime, against the staged DLL** (`nls_proof.exe`; needs a letterboxed file,
defaults to `C:\htpc\Everest.2015_4kuhd.mkv`, a 2.2:1 title here):

```
nls_proof.exe [dll] [file] [outdir]
```

| leg | engine published (nls.warp / crop) | [NLS] log |
|---|---|---|
| off | 0 / 0 | - |
| stretch-h | 20 / 0 | horizontal 0.807/1.000 |
| split50 | 11 / 0 | split 0.899/1.113 |
| split50 + Max distortion 110 (Auto) | 10 / 3 | split 0.909/1.100, [GEOM] dest 641 wide |
| split100 | 20 / 0 | split 0.807/1.000 (= horizontal) |
| horizontal | 20 / 0 | horizontal 0.807/1.000 |
| vertical | 24 / 0 | vertical 1.000/1.239 |
| crop | 0 / 0 | "no pass ... (crop to fill)" |

**Trap:** frame grabs are NOT a reliable witness while paused. `GrabFrame`
returns the last DRAWN frame, and a settings change does not always force a
redraw - the Crop leg's BMP still matched Horizontal. Read `[NLS]`/`[GEOM]` for
geometry; use the BMPs only for shape.

**Persistence** verified by editing `geo.nlsAxis` in
`%LOCALAPPDATA%\Unplugged\s3_shell.ini` and relaunching: 3 (Split) survives; the
old 0 normalises to 1.

---

## 5. Still open (unchanged unless noted)

- **§3A NLS softness** - the "hard-edged text" report. The split makes it *worse*
  on paper (two axes resampled); confirm on a text-heavy title before widening
  the kernel to Catmull-Rom.
- **§3B DV source reported as HDR10** - fingerprint classification on the live
  path (`dovi=0`, BT2020 + PQ + no ST2086). Read `MpcPlayer.cpp` around the DV
  recognition comment first.
- **§3C `MLParams_t` field 4** - checked: the HLSL declares `MLShadowDehaze` but
  **never reads it**, and C++ fills that slot with a hardcoded `0.0f`
  (`shadowStrength`). So it is a naming lie, not a live bug; the day a shader
  reads that slot it will read 0. Rename when the renderer is next rebuilt.
- **§3D "Report a problem" still not wired.**
- **§3E subtitles `drew=0`** - the queue-leg witness now exists
  (`[live] subq: depth= rtNow= cached= lastHr= hit= geoHr=`); one run against a
  file with subtitles will name the failing branch.

---

## 6. Traps paid for this session

1. **A settings push that arrives is not a settings push that applies** - and a
   value that was *published* is not the value the *current* push wants. Any
   cross-thread published state read back on the same push lags by one.
2. **The renderer's window is created on the op-loop thread**, so anything that
   touches it from a settings push defers. Do not read its outputs in the same
   call.
3. **`IniValue` stores engine values, not indices** (see §3B).
4. `git` is not on PATH (use the GitHub Desktop copy); PowerShell here-strings
   with `'@` are fragile for long commit messages - write the message to a file
   and use `git commit -F`.
5. The shell's `native_ui_log.txt` is opened in the process CWD, not beside the
   exe. Start the app from `bin\app\Release` or look in the repo root.
6. The installer gate checks guide coverage - a new settings row needs a row in
   `docs/settings-guide.md`.

---

## 7. The Auto gate - operator decision after end-user feedback

An end user described the intended use: a 185" 16:9 screen, scope content, and
"how much of the black bars can you get rid of ... a sweet spot, then zoom the
rest away", tune-to-taste, and the same tools working the other way for a native
scope screen. Two things blocked that out of the box:

- Auto refused to fill when the correction exceeded **Fill limit** (105 %), and
  scope -> 16:9 needs 134 %, so the screen stayed letterboxed until the user
  found that row. (Auto's k > 1 direction was already exempt, which is why a
  traditional scope screen with 16:9 content always filled.)
- **Stretch** never crops, so the artifact budget was off in the mode people
  pick when they say "fill it".

Operator constraint: **whatever changes, do not break the traditional
scope-screen setup.** So the rule added is narrow, and only fires on an explicit
act:

```
Auto fills when  (correction within Fill limit)
              OR (the per-axis distortion the fill needs is ABOVE Max distortion)
```

Setting Max distortion *below* the correction is a stated budget ("I will take
at most 10 %"), so Auto fills and crops the rest. At the **default** 140 % the
second clause is false, so every previously-letterboxed case still letterboxes.

Verified (nls_proof, 2.2:1 title, Fill limit left at the 105 % default):

| leg | result |
|---|---|
| auto-def140 (cap 140) | `filling=0`, "fill refused", dest 571x321 - identical to before |
| auto-def110 (cap 110) | `filling=1`, warp 9 %, crop 13 %, dest 705 wide |
| 16:9-on-scope / 4:3-on-16:9 | fill, unchanged (k > 1 path) |

`nls_math_check.py` now asserts both sides of that table.

**Deferred by the operator:** a lock across titles ("keep 1 aspect ratio" for
every title, not just within one). *Lock band* stays per-title until the end
user has tested it on a couple of titles and says a cross-title lock is wanted.

---

## 8. Build / staging (unchanged from the evening handoff)

```powershell
$env:PATH = "$env:LOCALAPPDATA\GitHubDesktop\app-3.6.7\resources\app\git\cmd;" + $env:PATH
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"      # ENGINE_EXIT=0
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"       # S3ENGINE_BUILD_EXIT=0
Copy-Item tools\s3engine\s3engine.dll bin\app\Release\ -Force
& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' `
  'C:\code\unplugged-mpc-hc\tools\native_ui\native_ui.vcxproj' /p:Configuration=Release /p:Platform=x64
```

`Stop-Process -Name Unplugged` first - the app locks its own exe.
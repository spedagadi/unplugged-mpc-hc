# Handoff - 2026-10-30, evening session (native UI 2.0.0)

Written for a fresh session. The morning handoff (`HANDOFF-2026-10-30.md`) is still
worth reading for the *failed* investigation; this one supersedes its section 4,
because the dead-input defect was found and fixed. The design contract
(`UI-CONTRACT.md`) is still the governing document **except** where noted in §7.

App is NOT running at the end of this session. `Unplugged.exe` was rebuilt last at
16:0x and `s3engine.dll` staged.

---

## 1. The dead-input defect: FOUND AND FIXED (was unsolved all morning)

**Root cause.** `SetDecklinkCapture` starts `m_gopThread`, the ops-queue executor
("the ONLY thread that may mutate the capture card + graph"). `RunDecklinkRebuild`
runs `Open()` there, and `Open() -> ConfigureRendererWindow() -> put_Owner ->
Init(true) -> CreateWindowExW` **creates the renderer's window on that thread**.
That thread's whole loop was `m_gopCv.wait(...)` - it never called
`GetMessage`/`PeekMessage` in its life.

So in VP mode the picture was a **hung window inside our own process**, from birth.
A click on it made Windows service input through that thread; because the queues
are shared, the whole app stopped collecting mouse AND keyboard while posted
messages, `WM_TIMER` and the 5 ms `GetCursorPos` sampler kept running. That is the
exact fingerprint the morning session could not explain, and it also explains the
old "only Task Manager can close it" (cross-thread `DestroyWindow` blocks on a
thread that never pumps).

**Fix.** `MpcPlayer::DecklinkOpLoop` now pumps `PeekMessageW`/`DispatchMessageW`
while it waits, at the same ~5 ms cadence as the live thread (same rule, same
comment style as `MpcPlayer.cpp:459-466`).

**Proof (before -> after):**
`IsHungAppWindow(VRWindow)` TRUE from birth (5 consecutive 5 s sent-message
timeouts) -> FALSE, replies in 0-3 ms; a click on the picture now reaches the host
(`[press] down target=UnpluggedVideoHost`) and keys still work afterwards.

**Trap paid for:** synthetic input (`SendInput`/`mouse_event`) is silently
swallowed while any window in the process is hung. It looks exactly like the defect
and cost two misread runs. Diagnose from outside first: `EnumChildWindows` the
frame, then `IsHungAppWindow` + `SendMessageTimeout(WM_NULL, 2000)` per window and
compare per-thread. UI thread answering in 0 ms while another answers never is the
signature.

---

## 2. Every fix built this session

All are in `src/mpchc_engine/MpcPlayer.cpp` (engine) or
`tools/native_ui/native_ui.cpp` (shell) unless stated.

| # | Fix | Acceptance evidence |
|---|---|---|
| 1 | `DecklinkOpLoop` pumps while waiting | `IsHungAppWindow=false`; input survives a picture click |
| 2 | Band latch re-derives geometry AND warp (`m_videoRectPending` set at the latch) | `ratio=0.991` with the band, was `1.346` |
| 3 | A first latch of "no bars" needs `kRelatchTicks` like a real band | no 0/0 latch on the opening frames |
| 4 | **Auto refuses to fill until the band is confirmed** (`bandValid`) | 0 warps with `bars=0/0` at start-up; fills 4 s in |
| 5 | `TaskbarReserve()` returns 0 while the frame is topmost; `OnActivate` applies topmost BEFORE `Layout()` | transport bar bottom 1426/1440, was 1378 |
| 6 | Recorded preset is hard-applied before the first `PushAll` | `ml.mode` identical on consecutive launches (was 2/0/2/0) |
| 7 | ML **enable switch is the master**: enabling while `TONE CURVE -> Mode` is Off sets Mode to Auto (row + push + persist) | `[ML] apply enable=1 mode=2`, `active: yes` |
| 8 | `[ML] apply enable/mode -> settings(enable/mode ...)` telemetry | completes the click->engine->renderer trail |
| 9 | Settings-rail icons: square 32 px box, all six glyphs from `Segoe UI Symbol` | one face, no per-glyph substitution |
| 10 | "Report a problem" moved from the title strip to the System tab as a `kind==3` action row (`__report`, CTA "Report..."); Info now occupies the old slot | renders in System tab; row excluded from `PUSHALL` (100 keys unchanged) |
| 11 | Auto-hide hides **every** pane, rails included (`SetUi(false)`) | log `chrome: idle timer -> hide ALL panes` |

### Why 6 and 7 were needed (the ML "enable does nothing" hunt)

`bActive = m_bML && (m_iMLMode == ML_Manual || bAutoReady)` and `bAutoReady` itself
requires `m_iMLMode == ML_Auto`. With `Mode = Off`, the enable switch is inert by
construction, however it is delivered.

- `PresetInitFromIni()` recorded *which* preset was active but never applied it, so
  the first `PushAll` sent the base-ini value on some launches and the preset's on
  others -> `ml.mode` alternated 2/0/2/0 with no user input. Fixed by #6.
- `Preset 1` itself carried the contradictory pair `enable=1, mode=0`. Fixed by #7,
  which persists `toneMode=2` back into the preset.

`gammaPredict=FAIL` was **downstream**, not a cause: the model only predicts once
the grade is active.

### The trail that now exists for any "the control did nothing" report

1. shell: `CMD {"a":"set","sets":"..."} (key) rc=0`
2. engine: `[SETTINGS] received key = value`
3. engine: `[ML] apply ... -> settings(...)` / `[TASTE] apply ...` (boundary proof)
4. renderer: `[live] ml: <mode> ... active: <yes|no>` and `pipeline: ...`

---

## 3. Open defects, with the evidence already gathered

### A. NLS: text looks hard-edged / aliased  (quality, not correctness)

NLS itself is unlikely to be the only suspect: its pass does explicit 4-tap
bilinear, and the bar crop is a 1.36x *enlargement* (softens, does not alias). What
is actually in effect on this machine:

```
preset   out.upscaling=5   out.chromaScaling=3   out.downscaling=5
base ini out.upscaling=1   out.chromaScaling=1   out.downscaling=0
postfx.deband=1  debandRange=16  debandThresh=32  debandGrain=24
```

**Cheapest falsification first (no build):** set the upscaler back to the base value
(1), then toggle deband off. If the hard edges survive both, it is the NLS sampling
and the next step is a wider kernel - the Catmull-Rom that `HANDOVER-1.3.1` records
as offered and deferred - not a "better" bilinear.

### B. Dolby Vision source is reported as HDR10

Live line at the time of the report:

```
pipeline: ... dovi=0 ... tf=15 prim=9 ... sdata=0 rcll=-1 rfall=-1 cllsz=0
```

`tf=15` = PQ, `prim=9` = BT.2020, `sdata=0`/`rcll=-1` = **no ST 2086 at all**. That
combination is exactly this project's recorded DV fingerprint, but the panel keys
off `dovi=`, which the renderer sets only when it consumed a valid DV **RPU**
(`m_Dovi.bValid`). On an HDMI capture from a TV stick the DV dynamic metadata does
not arrive as an RPU - the card gives us the PQ base layer only. So `dovi=0` is
honest and the panel faithfully repeats it.

**Proposed fix:** on the live path, when `dovi=0`, classify by fingerprint
(BT2020 + PQ + no ST2086) before falling back to HDR10. `hdr.preferDoVi=1` is
already set, so the preference side is not the issue. Check `MpcPlayer.cpp:2018`
(the DV recognition comment) before changing anything - a P5 file already had a
`dovi=0` false negative once.

### C. `MLParams_t` field 4 is mis-mapped (renderer)

C++ `DX11VideoProcessor.h:193+` has **`MLShadowStrength`** where
`Shaders/d3d11/ps_ml_gamma.hlsl` declares **`MLShadowDehaze`**, and the C++ struct
has **no `MLShadowDehaze` member at all**. Size is guarded
(`static_assert(sizeof(MLParams_t) == 368)`) so it cannot overflow, but the shader
reads the wrong value in that slot. Everything after field 4 is *not* shifted; the
apparent further divergences are array-count artefacts (`_reserved[6]`,
`FaceBox[16]`, `FaceTrackId[4]`).

### D. "Report a problem" is still not wired

It logs `report a problem clicked (not wired)` exactly as the old strip button did.
Needs a destination: issues URL, mailto, or a diagnostics bundle.

### E. Subtitles `drew=0` (older, still open)

See `HANDOVER-1.3.1-native-ui.md` §4. Unchanged this session; the live line still
reads `subs: render11=2346 drew=0 noQueue=0`.

---

## 4. Housekeeping - do this before a release build

1. **`src/mpchc_engine/MpcPlayer.cpp` carries eight fixes and is uncommitted.**
2. **Nothing under `tools/native_ui/` is tracked by git at all**
   (`git ls-files` has no entry). The morning session lost 5,489 lines to a scripted
   edit with no VCS to fall back on. Add the source (ignore `*.bak-*` and
   `*.damaged`) and commit the engine.
3. Commit-msg hooks strip AI trailers; never rewrite history (see the
   `ai-attribution-scrub` memory).
4. Packaging: any engine change needs `s3engine.dll` restaged into whatever ships.
   The registered renderer in `C:\Program Files\Unplugged\filters\` is newer than
   whatever is in `dist\`.

---

## 5. Build / staging (all verified today)

```powershell
$env:PATH = "$env:LOCALAPPDATA\GitHubDesktop\app-3.6.7\resources\app\git\cmd;" + $env:PATH
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"      # ENGINE_EXIT=0
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"       # S3ENGINE_BUILD_EXIT=0
Copy-Item tools\s3engine\s3engine.dll bin\app\Release\ -Force
& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' `
  'C:\code\unplugged-mpc-hc\tools\native_ui\native_ui.vcxproj' /p:Configuration=Release /p:Platform=x64
```

The app locks its own exe - `Stop-Process -Name Unplugged` before relinking.

**Logs:** shell `bin\app\Release\native_ui_log.txt`; engine
`%USERPROFILE%\.unplugged\logs\engine.log`; renderer
`%LOCALAPPDATA%\Unplugged\logs\mpcvr_trace.log`.

**Verification without clicking** (the app answers these from outside):
`EnumChildWindows` the frame -> find `VRWindow` -> `IsHungAppWindow` +
`SendMessageTimeout(WM_NULL)`. Pine rects prove layout. `[live]` lines prove the
renderer's own state.

---

## 6. Traps paid for this session

1. **Synthetic input is not a probe while a window in the process is hung** - see §1.
2. `SendInput`/`mouse_event`/`keybd_event` from PowerShell work fine against this
   app once nothing is hung; no elevation needed.
3. **A preset can silently override the base ini at startup** - and the app logged
   nothing about applying it because it never did.
4. **`ml.enable` and `ml.mode` are two controls for one feature.** `Mode = Off`
   wins. The enable switch is now the master.
5. **A settings push that "arrives" is not a settings push that "applies".**
   `[SETTINGS] received` is logged before the group dispatch; `[ML] apply` is the
   boundary that matters.
6. **`git` is not on PATH** - use the GitHubDesktop copy as above.
7. **PowerShell `$Host` is read-only**; don't name a variable `$host`.
8. `SetWindowRgn` on the host, the 50 ms HostProc dedupe and the `videorect` path
   are load-bearing - read the comments before touching `Layout()`.

---

## 7. The contract now contradicts the build (needs a decision, not a patch)

`UI-CONTRACT.md` requires **I1/I2/V2: the chrome is static - no auto-hide, no idle
timer, no reveal gesture**, and §6 says to *delete* `TID_CHROME`, `OnChromeIdle`,
`PointerSample`, `EdgeCheck`, `InBottomDock` and the `SetUi` state. That work was in
the version lost to the bad cut and was never redone - **all of it is still in the
tree and is now wanted**: the operator has asked for auto-hide that covers every
pane, including the rails (fix #11), and for the bottom-edge reveal.

So today's build deliberately violates V2/I1 as written. Either the contract is
rewritten to describe auto-hide-everything, or the next person will "fix" this
back. Do not silently leave the two disagreeing.

---

## 8. What the operator confirmed working at the end of the session

- Input survives clicking the picture, in media player **and** video processor mode.
- ML grade enable/disable works and the panel, engine and renderer agree.
- Auto-hide hides top, bottom and both rails while a title plays; the media dialog
  still shows the top and bottom panels (by design).
- NLS applies on acquisition once bar detection is stable, deterministically.
- Transport bar sits at the screen edge.

---

## 9. REQUESTED FEATURE - bidirectional NLS (approved, not implemented)

Operator decision, 2026-10-30: **expose the dial on both axes.** Origin is a power
user's request: *"scope -> 16:9 is pretty hard... there's that sweet spot in image
artifacts, and then if you want more you're just going to have to zoom it away."*
They want to sit between "zero distortion + minimum crop" and "zero loss + maximum
distortion", and to do it on **both** axes, not one.

### What exists today (and why it blocks them)

1. **One axis only.** `NlsShader.h:104-123`: `map_radius` is applied to `src.x` OR
   `src.y`; the other coordinate is a plain `lerp`. The engine picks with
   `vertical = (pendingNls_.axis == 2)` - so **Axis = Auto is hard-wired to
   horizontal and never chooses**. The dropdown's "Auto" label is a lie today.
2. **The warp/crop dial only exists for `ratioAR >= 1`.** In
   `MpcPlayer::ResizeVideo`:
   ```cpp
   warpRatio = (ratioAR >= 1.0) ? ((mode==1) ? ratioAR : min(ratioAR, cap)) : ratioAR;
   cropScale = (ratioAR >= 1.0) ? max(1.0, ratioAR / warpRatio) : 1.0;   // forced
   ```
   So scope-on-16:9 (`ratioAR = 1.778/2.39 = 0.744`, the hard direction) is
   all-or-nothing: a full 24 % squeeze, or a full 24 % crop.

### Design to implement

**A. Shader** (`src\mpchc_engine\NlsShader.h` - engine-owned, injected into
MPCVR's post-scale chain, so this is an **engine + s3engine rebuild and NO `.ax`
change**):
- replace the single `ratio` with a per-axis pair `(sx, sy)`; keep one `CENTRE`
  and `CURVE` applied **per axis** so the protected region stays a rectangle.
- `main()` calls `map_radius` on both axes; the active-rect lerp is unchanged.
- `sy = 1` must reproduce today's horizontal-only output exactly, and vice versa -
  the change is a superset, not a replacement.

**B. Engine** (`MpcPlayer::ResizeVideo`):
- correction `k = ratioAR`; split share `s` in [0,1] = horizontal's share.
- `sx = pow(k, s)`, `sy = pow(k, 1-s)` - a geometric split keeps image area and is
  symmetric: `s=1` is today, `s=0` is vertical-only, `s=0.5` is even.
- cap each axis's distortion by `Max distortion` in **both** directions, then
  `cropScale = max(1, remainder)` and the geometry zoom takes the rest.
- publish `sx`, `sy`, warp % and crop % in the `[NLS]` log line (they are already
  stored as `m_nlsWarpPct` / `m_nlsCropPct`, `MpcPlayer.cpp:1173-1174`).

**C. Shell** (`tools\native_ui\native_ui.cpp`, NON-LINEAR STRETCH section):
- `kNlsAxis` / `kNlsAxisV` (`:344-345`) gain a 4th entry: `Auto | Horizontal |
  Vertical | Split`. Make Auto actually choose, or delete it and default to Split.
- new row `Split` 0..100 (default 50) = the share given to horizontal.
- rename `Max stretch` (`geo.nlsMax`) to **Max distortion** - it will cap both
  directions, so the old label would be wrong.

**D. Acceptance tests**
- `Axis=Split, Split=50, Max distortion=110` on a 2.35 title at 3840x2160: the log
  shows a warp on **both** axes, each <= 10 %, crop ~14 %, and the picture is
  measurably less distorted per axis than `Stretch`.
- `Axis=Horizontal` and `Axis=Vertical` reproduce today's single-axis frames
  exactly (regression - compare frame grabs).
- `Fill mode=Crop` unchanged: zero distortion, minimum crop.
- `Fill mode=Stretch` still never crops.

**E. Risks to design for**
- Two-axis resampling softens more (both axes interpolated) - check text/sharpness.
- Per-axis centre protection is mandatory, or the protected region becomes a cross.
- The split must stay monotone so no axis can mirror, and `pow(k, s)` must be
  guarded when `k <= 0`.

### Related decision still open
"Never lose picture through cropping" was stated as a requirement, but `Crop` mode
is also the only zero-distortion way to fill a screen. If it becomes policy that the
app never crops, say so explicitly - it removes the option this user is asking for.
# Unplugged 2.2.0 — plan

Status: draft for review, 2026-11-10. No code changes yet.

2.2.0 is a six-item release: two small correctness fixes, one ingest
reliability fix that needs reproduction first, and three renderer features
that touch the same output stage and must be sequenced together.

The renderer and the app ship from different repos but as one release. 2.2.0
is also the point to end the split between the package version and the
renderer build number: bump the renderer's `Version.h` and `revision.h` to
2.2.0 before building, so the app installer, the staging folder and the
standalone renderer installer all carry the same version.

---

## 1. Default config fix for Video Processor

**Problem.** On a fresh install there is no `app_config.json`.
`WriteConfigValue` only replaces keys that already exist, so the first-run
wizard cannot persist `app_mode` or `active_input_url`. The app relaunches
into Media Player, and Video Processor gets
`SetDecklinkCapture deviceName=''` then "No signal detected".

Reproduced 2026-11-05: first run wrote `mode='video_processor'
input='decklink://…'` only in memory, then `config mode='' input=''` after
the restart.

**Approach.**
1. Seed a complete default config at startup when the file is absent or
   unreadable (before the first read), with `first_run=true`,
   `app_mode="media_player"`, `active_input_url=""`, and every key
   `WriteConfigValue` can write. The wizard then persists normally.
2. Make `WriteConfigValue` insert a missing key instead of silently logging
   `key absent` — a defensive fix for any future key added to a shipped
   profile.
3. Treat a corrupt/truncated config as absent: keep a `.bak`, reseed, log.
4. Do not rely on the installer copying a config; the app must heal itself.
5. Keep the fresh-install sequence exactly as it is: the seeded
   `first_run=true` still opens the wizard, and the user chooses Media
   Player or Video Processor. No automatic jump into VP.

**Files.** `tools/native_ui/native_ui.cpp` (config load/write), possibly
`distrib/unplugged.iss` only for documentation.

**Acceptance.** Fresh profile + no config + SeenSetup marker cleared: wizard
chooses Video Processor and a DeckLink port, restart lands in VP with the
port and capture starts. Upgrade from 2.1.0 keeps existing values. Deleting
one key does not break persistence.

**Risk.** Low. Main trap: seeding `first_run` incorrectly on an existing
install (must not re-run the wizard when a valid config exists).

---

## 2. Hold the display awake for the whole session

**Problem.** 2.1.0 never calls `SetThreadExecutionState`. After the Windows
screen-off timeout the GPU stops driving HDMI; the projector reports "No
signal" and only input wakes it. Reproduced 2026-11-06 with a 60 s timeout:
capture continued at 24 fps, `draw` throttled to 4.4 fps while the output was
off, and a keypress restored the picture.

**Approach.**
- This is an HTPC player with nobody at the keyboard: hold the display awake
  for the **entire time the app runs**, not only while a file is playing.
- Call `SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED |
  ES_SYSTEM_REQUIRED)` once on the UI thread at startup, and clear it with
  `SetThreadExecutionState(ES_CONTINUOUS)` on shutdown before the window
  closes.
- There is no API to read the previous per-app state. A continuous request
  is a flag this thread adds; clearing it returns control to the user's
  power plan, which is the correct "what it was before". The request is also
  released automatically when the UI thread exits, so the clear is belt and
  braces, not the only release.
- Log the acquire/release once. Keep it on the pumping UI thread; never call
  it from the engine or a worker.

**Files.** `tools/native_ui/native_ui.cpp` (startup and shutdown paths).

**Acceptance.** With `monitor-timeout-ac=1`: 10 minutes of idle, file
playback, and live capture all stay lit. Closing the app lets the display
sleep again on the next timeout, and `powercfg /requests` (elevated) shows
no DISPLAY request from Unplugged after exit.

**Risk.** Low. The only subtlety is the thread: a per-thread request on the
pumping UI thread, released on exit.

---

## 3. Display transfer characteristics, including SDR source-follow

**Problem.** The HDR→SDR path hardcodes 2.2:
`ps_convert_pq_to_sdr.hlsl:983` (`pow(color, 1.0/2.2)`), and the GT7 branch
converts code back to linear with the same assumption (`:642`). The taste
and ML shaders operate in that 2.2 code space. There is no user control, so
a projector calibrated to 2.4 or BT.1886 cannot be matched. SDR currently
passes through, so its transfer follows the source only because nothing
touches it; there is no way to convert an SDR source to a chosen display
transfer.

**Control model.**
One setting, **Display transfer**: `Follow source` (default), `2.2`, `2.4`,
`BT.1886`, `sRGB`, `2.0`.

- **SDR, Follow source**: pass through, exactly 2.1.0 behaviour.
- **SDR, explicit target**: decode the source's display-referred transfer to
  linear, then encode with the target. The source transfer comes from the
  media type (`MFVideoTransFunc`: BT.709, sRGB, gamma 1..8, BT.2020 OETF).
- **HDR→SDR, Follow source**: use 2.2, the reference the tone map and the
  taste/grade chain are authored in. This preserves the 2.1.0 look.
- **HDR→SDR, explicit target**: keep the tone map and the 2.2 internal
  chain, then convert 2.2 code → linear → target at the final stage.

**Where it runs.** The **final pass**, which already hosts dither and the
calibration LUT and is the last display-referred stage. The internal chain
stays in 2.2 code space, so the ML grade and taste controls keep their
meaning. Extend the final-pass constant buffer with the input space and
target transfer. Force the final pass whenever a conversion is needed, even
with dither and LUT off.

Order inside the final pass:

1. input code → linear (2.2 for the tone-mapped path, the source transfer
   for an SDR conversion);
2. linear → target display transfer;
3. DBLE roll-off, if enabled (section 5; it is defined in target code);
4. calibration 3D LUT;
5. dither.

BT.1886 uses `hdr.blackNits` and `hdr.sdrNits`; with black = 0 it reduces
to 2.4. sRGB is the piecewise curve, not a 2.2 power.

**Open interpretation.** BT.709 SDR is an OETF, not a display EOTF. For an
explicit conversion the display-referred decode should be the reference
EOTF (BT.1886 for video), not the OETF inverse; otherwise the image
darkens by the OETF/1886 difference. sRGB and plain-gamma sources decode
with their own curve. This policy needs a decision before implementation.

**Files.** `Shaders/d3d11/ps_final_pass.hlsl` (both 8-bit and 10-bit
variants), `DX11VideoProcessor.cpp/.h` (final-pass cbuffer, enable, source
transfer), settings plumbing in both repos, `tools/native_ui` rows.

**Acceptance.** A linear ramp measured at the output gives the expected code
for each transfer. 2.2 / Follow source is bit-identical to 2.1.0 for both
SDR and HDR. SDR conversion is correct for BT.709, sRGB and plain-gamma
sources. ML on and off both get the conversion. The LUT applies after the
transfer, and the readme says LUTs must be authored for the selected
transfer.

**Risk.** Medium. The final pass is shared with dither and the LUT; getting
the order wrong shifts every calibrated picture. The BT.709 interpretation
is a real colour-science decision, not a code detail.

---

## 4. Output gamut, including SDR source-follow and DCI-P3

**Problem.** `hdr.outputGamut` is 0 = BT.709, 1 = BT.2020. Projectors with a
P3 mode have no correct target, so 2020 content is either left wide (wrong
primaries) or squeezed to 709 (lost gamut). SDR currently passes through
with no way to follow the source primaries or convert to a chosen target.

**Control model.**
One setting, **Output gamut**: `Follow source` (default), `BT.709`,
`BT.2020`, `DCI-P3 (D65)`.

- **SDR, Follow source**: pass through, exactly 2.1.0 behaviour.
- **SDR, explicit target**: convert source primaries → target in linear
  light, with the existing gamut-cap treatment for out-of-gamut colours.
- **HDR→SDR, Follow source**: use BT.709, the current default and the gamut
  the tone-mapped SDR output is authored for. This preserves the 2.1.0
  look.
- **HDR→SDR, explicit target**: convert the tone-mapped signal to the
  selected target. BT.2020 remains available for wide-gamut projectors;
  DCI-P3 is the new option.

**P3 definition.** Consumer projectors label their P3 mode with D65 white,
so this release adds **DCI-P3 (D65)** only. DCI-white P3 is a possible
follow-up.

**Implementation.** Add 2020→P3 and 709→P3 matrices in linear light next to
the existing 2020→709 conversion. Extend the gamut cap/constrain
(`GamutConstrain`, `MLGamutCap`, `MLGamutMap709` pattern in
`ps_ml_chroma.hlsl`) to the P3 target. The setting applies to the SDR
tone-mapped output; HDR passthrough keeps the BT.2020 container and the
display maps it. Plumb through the same settings surfaces as the transfer.

**Source detection.** The media type exposes BT.601/BT.709/BT.2020
primaries. Windows does not define Display P3 as a media-type primaries
value, so P3-tagged SDR content will usually arrive tagged 709 or unknown;
the plan supports conversion from the primaries that are actually signalled
and documents that limitation.

**Files.** `ps_convert_pq_to_sdr.hlsl`, `ps_ml_chroma.hlsl`,
`ps_final_pass.hlsl` (SDR conversion path if it belongs there),
`DX11VideoProcessor.cpp/.h`, settings plumbing, both UIs.

**Acceptance.** Known primaries and skin/vegetation patches measured on the
projector in P3 mode; out-of-gamut patches do not clip or hue-shift
unexpectedly; 709 and 2020 paths unchanged; SDR Follow source is
bit-identical to 2.1.0; presets round-trip; the standalone property page
exposes it.

**Risk.** Medium. Matrices and white point must be exact; the gamut cap is
shared with the ML chroma stage. Verify with the calibration patch set
rather than by eye alone.

---

## 5. DBLE compensation (submitted fix)

**Source.** `C:\code\DBLEFix` — a GPL v3 patch (`dblefix.patch`), a prebuilt
modified `unplugged_vr.ax`, a launcher, `dble.ini` and a README.

**What it does.** In dark scenes it rolls off highlights so the projector's
dynamic laser dimming (DBLE) does not clip them. The roll-off is
hue-preserving, identity below the knee, slope 1 at the knee, monotone, and
maps 1.0 to a ceiling. It runs in `ps_ml_chroma.hlsl`, only with SDR output
and only when the ML feature extractor is ready. Settings: enable, strength
(1.0 puts peak white at 50 %), trigger nits, highlight start.

**Approach.**
- Do **not** ship the submitted binary or the launcher. Apply the math to
  source and rebuild.
- **Independent of the ML grade.** The submitted patch reads
  `m_MLMeanNitsRaw` / `m_bMLFeaturesReady` / `cutNow` from the ML feature
  extractor, so it dies when the grade is off. DBLE needs the scene mean and
  the cut flag only. Add a lightweight scene-statistics path that runs when
  DBLE is enabled: reuse the ML extractor's values when they are available,
  otherwise compute a downsampled luma mean and a cut detector in the
  renderer. DBLE then works with the grade Off, Auto or Manual.
- **Applied in the final pass, after the target display transfer.** The
  knee and ceiling are target-code values, so they follow the transfer the
  user configured (2.2, 2.4, BT.1886, sRGB, 2.0). This is the order in
  section 3: decode, encode target, DBLE roll-off, LUT, dither. The roll-off
  is therefore correct on any target TRC and the calibration LUT still sees
  a display-referred signal.
- Keep the submitted roll-off shape: hue-preserving, identity below the
  knee, slope 1 at the knee, monotone, 1.0 maps to the ceiling.
- Settings: enable, strength (1.0 puts peak white at 50 %), trigger nits
  (scene mean, linear light), highlight start (target code). Add fields to
  `HdrSettings`, rows under TONE CURVE (or a small DBLE group), property
  page controls, preset persistence, and one `[live] dble=` diagnostic
  line. No `dble.ini`, no status file.
- Keep the SDR-output constraint: the feature exists for SDR projection,
  and HDR passthrough is untouched.
- Credit the submitter in the release notes and the About/readme; confirm
  the GPL contribution is intentional.

**Interactions.** The submitted cbuffer grows 368 → 384, but DBLE moves out
of `ps_ml_chroma` into the final pass, so the ML cbuffer does not need the
fields at all. This also removes any coupling to the ML shader layout. The
final-pass constant buffer grows once for the transfer, P3 and DBLE.
`dble.ini` / `dble_status.txt` disappear: Program Files is read-only, and
the native setting is the source of truth.

**Acceptance.** Dark scenes with DBLE on/off show the intended peak
reduction; bright scenes are bit-identical; strength, trigger and knee are
monotone; scene cuts snap and no pumping within a shot; DBLE works with the
ML grade Off, Auto and Manual; SDR only; the projector's DBLE stops
clipping. Repeat the dark-scene test at 2.2 and 2.4 target TRC to prove the
ceiling follows the configured transfer.

**Risk.** Medium-low. The new scene-statistics path and the final-pass
integration are the work; the submitted math is small and already reviewed
against the patch.

---

## 6. Prime Video episode-transition renegotiation

**Problem.** In VP mode, when an episode ends and the next begins, Prime
Video changes output format (SDR menu ↔ HDR episode, 24p ↔ 25p/60p). The
ingest path tears the graph down and sometimes fails to re-acquire, leaving
the "No signal detected" card.

**Known evidence (2026-11-05 engine log).** One transition produced a stop,
a 2 s settle, a rebuild, and then a second rebuild; gaps of 3.5–6.5 s. The
filter deliberately does not renegotiate in-session (a renderer access
violation was observed when it did). The monitor's 1 s unlock gate can
decide `Stop`, and the engine's `SOURCE FORMAT CHANGED` can fire again after
the first rebuild.

**2026-11-10 correction — the crash was a stale test binary.** A captured
AV in `unplugged_vr.ax` (`CDeckLinkOutputPin::ForwardLoop` →
renderer receive) came from a **Nov 3 dev renderer** in
`bin\app\Release\filters` (hash `B454…`), not the shipped Nov 4 renderer
(hash `4055…`). The PDB mismatch proved it. After replacing the test
payload with the shipped renderer, six-plus 25p SDR ↔ 50p HDR transitions
(09:52–09:54) completed without a crash.

What remains on the shipped build is the renegotiation cost, not a crash:
the log still shows repeated signal loss/re-acquire around each flip, one
transition producing two reloads (09:54:17 and 09:54:19) and about four
seconds before the first new frame. That is the part worth fixing.

**Process finding.** The dev/test app folder is not staged from the current
renderer, so it can silently load an old filter and manufacture failures
that the shipped build does not have. Add a test-payload gate: compare
`bin\app\Release\filters\unplugged_vr.ax` (and the other filter binaries)
against the current renderer dist before any reproduction session, exactly
as the installer build script already checks the packaged app. This is the
same stale-native trap recorded for the application payload.

**Approach.**
1. **Reproduce and classify first.** Confirmed reproducible on this machine.
   Run Prime Video autoplay through several episode transitions with engine
   logging, timestamp each transition, and classify the failure as:
   (a) `Stop` with no following `Launch`; (b) `EnableVideoInput` failing in
   a loop; (c) monitor stuck `locked=0`; (d) UI 10-attempt card exhausted;
   (e) reload storm (two rebuilds per transition). Do not design the fix
   until the failing branch is named.
2. **One reload per transition.** Rebase the committed format to the reload
   target and suppress the second `SOURCE FORMAT CHANGED` that fires after a
   rebuild.
3. **Short unlock ≠ stop.** If the monitor re-locks within the stability
   gate and the format is unchanged, resume without a teardown. Keep the
   teardown for genuine format changes.
4. **Re-arm after failure.** A new lock event must restart acquisition even
   after the UI's retry card has expired; keep a slow retry while the card
   is visible.
5. **Do not do unsafe in-session renegotiation.** The renderer AV is real;
   if it is ever revisited, serialise the media-type change onto the render
   thread as its own project.
6. Add a one-line `[INGEST] transition:` summary per episode change so a
   user's report is diagnosable from one grep.

**Files.** `src/mpchc_engine/MpcPlayer.cpp` (decider, settle, reload,
self-heal), `src/thirdparty/DeckLinkSource/DeckLinkSource.cpp` (only if the
unlock path needs it), `tools/native_ui` (acquire retry), diagnostics.

**Acceptance.** 20 consecutive episode transitions with the same source and
player: no failure card, picture returns in under 3 s, no double reload, and
a genuine source loss still produces the correct card and recovers on
re-lock.

**Risk.** Medium-high. This is the only item whose failure mode is not yet
fully known; the first milestone is the log classification, not a fix.

---

## Cross-cutting work

**Renderer version.** Bump `Include/Version.h` to 2.2.0 and `revision.h`'s
`REV_NUM` at the start of the release. `make_dist.cmd` will produce
`UnpluggedRenderer-2.2.0.<rev>`; update `unplugged.iss`'s `FiltersSrc`, the
standalone installer's `RendererBuild`/`MyAppVersion`, and the renderer
staging gates. This ends the 2.1.0 / 0.10.8.2637 split.

**Settings ABI.** New `HdrSettings` fields cross the engine→renderer
boundary. App, engine and renderer must be rebuilt and shipped together.
The standalone renderer must expose the same settings through its property
pages, because no engine pushes them in MPC-HC/MPC-BE.

**Build order.** Renderer (shaders + .ax) → engine lib → native shell → app
installer → standalone renderer installer. The renderer installer build gate
already refuses a stale staging folder.

**Test matrix.**
- Fresh install (no config, no SeenSetup) and upgrade from 2.1.0; the wizard
  still asks for the mode.
- Screen timeout: 10 minutes idle, file playback, live capture, then exit
  and confirm the display can sleep again.
- Gamma: Follow source is bit-identical to 2.1.0; explicit targets convert
  SDR BT.709/sRGB/gamma sources and HDR→SDR; ML on/off; with and without a
  calibration LUT.
- P3: SDR Follow source and explicit conversions; HDR→SDR to P3; primaries,
  skin/vegetation, out-of-gamut patches; 709 and 2020 unchanged.
- DBLE: dark/bright scenes, strength/trigger/knee, cuts, ML Off/Auto/Manual,
  SDR only, projector DBLE on, repeated at 2.2 and 2.4 target transfer.
- Ingest: 20 Prime Video episode transitions; genuine source loss/re-lock.
- Regression: NLS 2.1.0 suite, HDR10/DV, library, diagnostics zip,
  MPC-HC/MPC-BE standalone, both installers, uninstall/restore.

**Milestones.**
1. Week 1: config fix, screen awake; reproduce and classify the ingest
   failure. These are independent and low risk.
2. Week 2: ingest fixes; final-pass foundation (input space, target
   transfer, source SDR conversion, P3 matrices).
3. Week 3: DBLE on the final pass with independent scene statistics;
   property pages, presets, diagnostics.
4. Week 4: version bump, builds, full matrix, release notes, 2.2.0
   installers.

---

## Decisions

**Resolved.**

1. Gamma includes SDR: Follow source plus explicit targets, not an HDR-only
   control.
2. Gamut includes SDR: Follow source plus explicit targets, with DCI-P3
   (D65) added.
3. DBLE is independent of the ML grade; the submitted dependency is
   replaced by its own scene statistics.
4. DBLE follows the target TRC the user configures, so it moves to the
   final pass after the display encode.
5. Prime Video is reproducible on this machine; classification comes first.
6. Screen stays awake for the whole app runtime and is released on shutdown.
7. Fresh-install sequence is unchanged: the wizard still asks the user to
   choose Media Player or Video Processor.

**Still open (technical, answer before the relevant milestone).**

1. ~~BT.709 SDR conversion: decode with BT.1886 as the display-referred
   reference, or with the BT.709 OETF inverse.~~ **Resolved: A.** BT.709
   video decodes with BT.1886 as the display-referred reference; sRGB and
   plain-gamma sources decode with their own curves; then encode the target.
2. "Follow source" for HDR→SDR: fall back to the 2.1.0 references (2.2,
   BT.709) so defaults do not change. Confirm.
3. DBLE scene statistics: reuse the tone mapper's scene stats where they
   exist, otherwise a new downsampled mean + cut detector. Decide the source
   domain (content nits).
4. P3-tagged SDR detection: Windows media types do not signal Display P3;
   accept the limitation or add an ICC/profile-aware path later.
5. Prime Video capture session: source device, player, and the episode
   transitions to record.
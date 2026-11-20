# Unplugged 2.3.0

2.3.0 replaces the simple DBLE compensation with **ClipGuard**, the contributed
projector highlight-compensation system, integrated into Unplugged and the
standalone renderer. It also rebuilds the internal subtitle stack, makes frame
rate matching work in both modes, makes NLS black-bar removal aspect-aware, and
replaces the separate 10-bit / SDR BT.2020 / output-gamut rows with one
**Display gamut** setting. 10-bit output is automatic whenever the display link
supports it.

| Download | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.3.0.exe` | 125,596,507 bytes | `2B679218FD652E006796B829784C36813DD89694A2F6B22E85414B9A0C5DEC83` |

The standalone renderer remains at its 2.2.1 release; no new renderer package is
published with 2.3.0.

## New Features

- **ClipGuard replaces DBLE compensation.** The compensation runs in the
  renderer. This build hides the tuning rows and exposes a single
  **ClipGuard → Configure** row under **Tone Mapping**, which opens the
  ClipGuard package installed next to Unplugged; if the package is missing the
  app says so instead of opening anything. The controls below describe the
  system's behaviour.
- **Fix shape Normal / Anchor.** Anchor keeps the peak of large bright areas
  (windows, lit walls) so the projector's laser dimming does not pump, and cuts
  gently below it while preserving local ratios. Normal squeezes every
  highlight above Highlight start.
- **Hot spot** dims small intense lights (headlamps, flashlights, streetlights)
  in dark scenes, with tracking and easing; **Graded spot** gently dims small
  graded highlights such as a lit face or shirt shoulder.
- **Color protect and Text skip.** Saturated colours can be exempted from the
  roll-off, and titles/credits/star fields hold the fix off for that frame.
- **Grid Normal / Fine** (128×72 or 256×144) and **Look-ahead** (Off / 2 / 4 / 6
  frames). Look-ahead is Off by default and is forced Off in live capture.
- **Full ClipGuard overlay.** The contributed panel shows the settings, keys and
  readout (Picture, Fix, White, Peak, spots, ADL before/after, GPU/CPU cost).
  `F7`/`Ctrl+Alt+0` show/hide, `F8`/`Ctrl+Alt+D` enable, `F9` Fix areas, `F10`
  Hot spot, `F11` saves the last 30 s plus a screenshot. Arrows adjust while the
  overlay is visible. The overlay and its diagnostic View always start **Off**
  and **Normal** at launch: they are session tools, not a saved viewing state.
- **ClipGuard 2.62 companion support.** ClipGuard.exe owns the settings while it
  runs (shared memory); without it the app's stored block is used. The
  calibration LUT is looked up next to the renderer first, then in
  `%LOCALAPPDATA%\ClipGuard`.
- **Standalone renderer.** The HDR property page no longer carries ClipGuard
  controls; ClipGuard has its own application. The renderer still applies the
  stored ClipGuard block.

## Playback and interface

- **Frame rate matching in both modes.** The setting applies to file playback
  and to live Video Processor capture. When the display cannot be switched the
  app shows `Frame rate matching: ON  Input: <src> Hz  Output: <display> Hz`
  with the reason in red underneath, instead of leaving the user to guess; the
  original mode is restored on stop.
- **Aspect-aware NLS.** Black-bar removal follows the detected picture aspect:
  up to 1.90 nothing is zoomed, 1.90–2.15 removes the bars without cropping, and
  2.15 and wider uses the user's own scope tuning. A 16:9 or IMAX section inside
  a scope title is never zoomed, and the Lock control does not override the rule.
- **Internal subtitle stack rebuilt** on MPC-HC's engine. SRT/ASS/SSA/WebVTT/
  MOV_TEXT text subtitles draw, alongside PGS, VobSub and DVB. New **Text size**
  (default 65 %) and bottom-bar placement for scope titles.
- **Themed dropdowns** for the Audio, HD audio and Subtitles rows.
- **Keyboard-only operation.** Tab/Shift+Tab move the focus ring; Left/Right
  step the focused slider; Enter or a double-click opens an exact-value box;
  typing a number (or F2) opens it directly. No mouse required.
- **Info panel** reports display refresh separately from presented FPS, and the
  output bit depth.
- **One Display gamut setting; 10-bit is automatic.** HDR → Display Target →
  **Display gamut** (`Auto (BT.709)` / `BT.2020` / `DCI-P3`) derives the output
  conversion, the SDR BT.2020 declaration and WCG ownership. 10-bit output is
  automatic whenever the display link reports 10 bpc, including for 8-bit SDR
  sources. The old 10-bit SDR, SDR BT.2020 and Output gamut rows are internal.
- **Update card renders release notes.** Headings, bullets, rules and table rows
  are formatted; long notes scroll with the wheel instead of showing raw
  markdown.
- **16-bit live frame capture.** Ctrl+S keeps the renderer's 16-bit surface when
  it supplies one.
- **SDR policy for the ML grade.** An SDR title disables the grade with an
  on-screen notice; the opt-in is remembered.
- **Static Nits** steps by 1 instead of 5.

## Bug Fixes

- **No double roll-off.** The 2.2.0 final-pass DBLE path is removed, so only
  ClipGuard processes highlights.
- **Upgrading keeps the user’s DBLE configuration.** A 2.2.0 profile with
  `hdr.dble*` is mapped to ClipGuard on first launch: enabled/disabled state,
  strength, trigger and highlight start are preserved; it uses Normal shape,
  no Hot spot/Graded spot/Text skip and no look-ahead, matching the old
  behaviour.
- **ClipGuard cannot tint or process with the fix off.** Its views and passes
  are gated on ClipGuard being enabled.
- **Network libraries work.** A library rooted on a UNC path (`\\server\share`)
  no longer marks every title UNAVAILABLE; the share is probed with the trailing
  separator Windows requires.
- **4K is no longer scaled by the window edge.** The geometry canvas is the
  monitor rect, not the window client, so the 2.2.0 surface (3834×2154 on a
  150% display) is gone: with the chrome hidden the canvas is exactly
  3840×2160, and Fit mode Source is pixel-for-pixel 1:1. Fixed aspect 1.78
  still fits to 3840×2157 by definition (1.78 is not exactly 16:9); use Source
  for 1:1.
- **Toggling the ML grade no longer flashes.** The frame after an ML on/off
  change runs the ML steps as a copy while the new state settles, then the real
  grade resumes.
- **Scope content loses its bars again.** The aspect rule's scope window has its
  own **Scope bar removal** value (default 100 %); tuning edits are kept in any
  window and preset autosave no longer overwrites them with a forced value.
- **8-bit SDR gets a 10-bit chain on a 10-bit display.** The renderer's Auto
  texture format now follows the display link as well as the source depth.
- **WCG is journaled in both directions.** A display state the app forces for
  the session is restored on exit and repaired after a crash.
- **2.2.0 fixes are retained:** display transfer, DCI-P3, fresh-install config,
  keep-awake, scene stability, capture renegotiation and Ctrl+S frame capture.

## Upgrade

Install over 2.2.0. The media library, presets and calibration data are
preserved. On first launch, an existing DBLE configuration is migrated to
ClipGuard — if DBLE was On, ClipGuard is On with the old strength/trigger/
highlight start and Normal shape. If DBLE was Off, ClipGuard starts Off. The
overlay is always Off at launch; press `F7` to show it.

## Known Limitations

- ClipGuard is SDR-output only; HDR passthrough is untouched.
- Look-ahead delays video relative to audio. It is Off by default and forced
  Off in Video Processor mode; in file playback add the same delay on the
  receiver if it is enabled.
- The standalone renderer property page no longer carries ClipGuard controls;
  ClipGuard has its own application and the renderer applies the stored block.
- The ClipGuard package is installed separately next to Unplugged. Without it,
  the Configure row shows a notice and opens nothing.
- **The display link depth is not settable by the app.** A forced 8 bpc in the
  GPU driver is a hard cap; WCG still enables, but the link stays 8-bit.
- **SDR BT.2020 auto-switching is display-dependent.** Many displays only switch
  to BT.2020 for HDR. Force the display to BT2020 and set **Display gamut =
  BT.2020**; the app cannot change the display's EDID or internal gamut.
- External subtitle files are not supported; subtitle tracks must be inside the
  container.
- The LAV and DeckLinkSource binaries are unchanged from 2.2.0.

## Credits

ClipGuard is based on the contributed ClipGuard source (2.60.0/2.62.0), with Fix
shape Anchor and the large-bright-area approach by Konstantin (SpykeVision).
GNU GPL v3; source is in the Unplugged renderer repository.
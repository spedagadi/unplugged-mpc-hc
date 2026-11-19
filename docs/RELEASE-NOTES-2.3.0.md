# Unplugged 2.3.0

2.3.0 replaces the simple DBLE compensation with **ClipGuard**, the contributed
projector highlight-compensation system, integrated into Unplugged and the
standalone renderer. It also rebuilds the internal subtitle stack, makes frame
rate matching work in both modes, and makes NLS black-bar removal aspect-aware.

| Download | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.3.0.exe` | 125,576,442 bytes | `25904E8A2D9D2AF872170B98B4B382E691541C9799EA69B8DF5DF03DF6ECE75F` |

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
- **Safe-area anchoring.** The panel stays at the bottom-left of the visible
  picture and moves out from under the status/settings panels.
- **Standalone renderer.** The HDR property page carries the ClipGuard core
  (Enable, Strength, Fix starts, Highlight start, View, OSD); the full set lives
  in the Unplugged ClipGuard section.

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
- **10-bit SDR output.** With Windows set to 10 bpc, Unplugged drives a 10-bit
  swap chain. It owns the Windows WCG state for the session and restores it on
  exit; a crash is journaled and repaired on the next launch.
- **SDR BT.2020 test signal** row under Output, for checking a display's BT.2020
  handling with SDR content.
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
- The standalone renderer property page exposes the core controls; the complete
  ClipGuard set is in the Unplugged application.
- The ClipGuard package is installed separately next to Unplugged. Without it,
  the Configure row shows a notice and opens nothing.
- External subtitle files are not supported; subtitle tracks must be inside the
  container.
- The LAV and DeckLinkSource binaries are unchanged from 2.2.0.

## Credits

ClipGuard is based on the contributed ClipGuard 2.25.4 source, with Fix shape
Anchor and the large-bright-area approach by Konstantin (SpykeVision). GNU GPL
v3; source is in the Unplugged renderer repository.
# Unplugged — feature guide

Unplugged is a video processor and player for the HTPC: it takes live HDMI in
through a Blackmagic DeckLink card, or plays local files, and tone-maps HDR to
your display with a grade you control. Everything below is what the shipped
1.0 does, written for the person holding the remote.

---

## Getting started

**Requirements**

- Windows 10 or 11, 64-bit.
- Microsoft Visual C++ 2015–2022 x64 runtime. The installer uses it if you
  drop `vc_redist.x64.exe` next to the setup before compiling; otherwise your
  machine must already have it (most do).
- A Blackmagic DeckLink card for live capture. File playback needs no card.

**Installing**

- The installer needs administrator rights. Double-clicking it raises the
  Windows consent prompt; on a machine where elevation is impossible it stops
  and tells you to right-click → *Run as administrator* instead of failing
  halfway.
- Two licence pages are mandatory: the Blackmagic DeckLink SDK licence, and
  Unplugged's own end-user terms (three short clauses: your use is your
  responsibility; no warranty; third-party components are governed by their
  own licences, which ship in the `licenses` folder of the installed product).
- DirectShow filters are registered at install and unregistered at uninstall.

**First run**

A setup wizard asks whether this machine is a **Video Processor** (live
capture) or a **Media Player** (files). Choosing Video Processor shows every
port on your DeckLink card with its live signal state, lets you name each one
("Apple TV", "Projector box"…) and pick the active input. The wizard re-runs
after every install, and on demand from the settings rail.

---

## The two modes

- **Video Processor** — live HDMI in, processed and presented full-screen.
  Acquisition is automatic and self-healing: plug, unplug, source renegotiates
  from SDR to HDR mid-session, and the picture follows without intervention.
- **Media Player** — a library of local files with the same renderer and the
  same grade behind it.

Switch at any time from the transport bar or the settings rail. If something
is playing, Unplugged asks first and stops it before switching. Switching back
never loses your settings.

**Controls**

- `Up arrow` (global, from any window) — show or hide the on-screen chrome:
  status, settings rail, transport.
- `Space` — pause / resume. `M` — mute.
- Transport bar: play/pause, position, seek, duration, mute, volume.
- The seek bar and volume sit on one row; on an overscanned display everything
  stays inside the visible area.

---

## Live capture

- **Source tab** lists every port on every DeckLink card: your friendly name
  (or the port's hardware name until you name it), and a live badge —
  locked with SDR / HDR PQ / HDR HLG, or *no signal*.
- **Switch inputs on the fly** by clicking a row. Capture restarts on the new
  port; nothing else about your session changes.
- **Rename ports** from the same tab; names persist and appear everywhere the
  port does.
- Dolby Vision over HDMI is recognised and handled as its own case (see
  *Picture* below); HDR10 metadata (MaxCLL, MaxFALL, mastering display) is read
  from the card when the source carries it.
- Signal loss is tolerated, not fatal: brief dropouts wait out a grace window
  before anything is torn down, so a source renegotiating its format does not
  bounce you to a spinner.

---

## File playback

- Containers and codecs through the bundled LAV fork: MKV, MP4, BDMV-rip
  HEVC/AVC, TrueHD/Atmos, DTS-HD, AC-3 and the rest.
- **Subtitles**, embedded and rendered in-picture:
  - text tracks (SRT/ASS/SSA) and bitmap tracks (PGS, VobSub);
  - the full track list in the Playback tab, with language and format, plus an
    *Off* entry; switching is live and stays at your position;
  - the list is what the file actually contains, including a source's
    "forced" and "SDH" variants.
- **Audio tracks** switch live, in place, without restarting the file.
- **Bitstream or PCM**: bitstream passes encoded audio (TrueHD, DTS-HD) to
  your receiver; PCM decodes in the app. In bitstream the receiver owns the
  level, so the app's volume and mute dim themselves with a tooltip saying so
  rather than pretending to work.
- Settings that need a graph rebuild (audio mode, swap effect, texture
  format…) re-open the file **at the position you were at**, not from zero.

---

## Picture

The grade is the product. Everything here lives in the settings rail under
**HDR** and **ZION**.

**Tone curve.** Two choices by default, because in practice it is a two-way
decision and Unplugged picks the right one per source automatically:

- **Unplugged** — the house curve, used for Dolby Vision of any provenance;
- **GT7 Adapt** — for HDR10, adapting to the master's measured peak.

Eight more curves (ACES, Reinhard, Mobius, BT.2390, Reference, GT7, the
scene-adaptive spline…) exist and work; `ui.showAllTonemappers=true` in the
INI restores the full list for A/B work.

**Taste dials** (small, stepped, safe at zero):

- **Exposure** — input gain in thirds of a stop, applied before the curve so
  the shoulder absorbs it instead of clipping;
- **Shadow detail** — spreads dark values apart without lifting black;
- **Contrast** — a symmetric curve about mid grey; black, mid and white stay
  exactly put;
- **Highlight desat** — tames the cyan cast HDR masters carry into dusk skies;
- **Gamut capacity** — how far out-of-gamut colour is pulled toward the
  display's edge.

Zero on every dial is an exact no-op, so a look you like is never disturbed
by the dials you don't touch.

**Display Target** — the numbers that describe *your screen*, set once from a
measurement report, not per film:

- **Static nits (max)** — your display's measured peak white;
- **Display black (nits)** — its measured black, so shadows are not mapped
  into a black level the panel cannot show;
- **SDR display nits** (in Tone Mapping) — where diffuse white sits; the
  headroom above it is what highlights live in;
- **Windows HDR** and **Subtitle/OSD brightness**.

**Calibration LUT** — load a DisplayCAL `.cube` describing the panel; applied
as the final pass, separate from the tone mapper (which describes the
signal). An enable toggle A/Bs it without losing the loaded file.

**Peak and metadata.** With HDR10 static metadata the master's MaxCLL sizes
the highlight ceiling; without any (Dolby Vision over HDMI, live capture) the
curve falls back to a measured scene peak. The status rail shows the peak in
use, and the engine log records which source supplied it.

---

## Keeping it tidy

- **Reset grade to defaults** (Zion tab) restores every grade row to its
  shipped value after a mis-drag, with a confirm and an audit line naming what
  moved.
- **Reset renderer settings** (System → App) forgets what a previous session
  or machine left in the renderer's registry, then re-applies your rail
  settings.
- Your settings live in `%USERPROFILE%\.unplugged\` and **survive uninstall
  and reinstall** — a re-install never costs you a tuned grade. The setup
  wizard returning after an install is the only thing that resets.
- A few expert rows (soft-knee trio, Prefer DV, tray icon) are hidden by
  default; `ui.showGradeInternals=true` in the INI reveals them. Hidden rows
  still honour a value set by hand.

---

## Known limitations, stated plainly

- Bitstream audio puts volume and mute in the receiver's hands; the app's
  controls dim rather than lie.
- Subtitle styling (font, size, position) applies to text tracks; bitmap
  tracks arrive pre-rendered.
- A rebuild-only setting change re-opens the source; playback resumes at the
  same position after a brief re-buffer.
- The calibration LUT describes one display. Moving the box to another panel
  means another measurement.

## When something misbehaves

Logs, in order of usefulness:

- `%USERPROFILE%\.unplugged\` — your settings (`s3_shell.ini`, `app_config.json`)
  and `logs\`, the app's audit trail and daily logs;
- `s3engine.log` in the install folder — the engine's graph, teardown and
  subtitle trail;
- `panel.log` under the install folder's `_internal\mpvprocessor\ui\` — every
  click the settings rail received;
- the renderer's trace, off by default, for frame-level questions.

A report that includes the last twenty lines of the engine log answers most
questions without a round trip.

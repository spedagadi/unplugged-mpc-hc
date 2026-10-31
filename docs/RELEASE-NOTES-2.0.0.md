# Unplugged 2.0.0

Unplugged is now one native Windows application, and this release adds the dial
for fitting a scope film to a 16:9 screen: non-linear stretch that works on
**both axes**, so the correction can be shared instead of spent all in one
direction. Also new: presets that save themselves, an update check, and Dolby
Vision correctly recognised over HDMI.

## What's new

### A native app

- The player and the settings panel are one native Windows program. There is no
  Python runtime bundled or loaded, the download is about a third smaller than
  1.3.0 (127 MB vs 186 MB), and the app starts without the Python startup delay.
- The settings rail keeps every section from 1.3.x — Playback, Source, HDR,
  Zion, Output, System — and changes reach the picture as you make them, on a
  paused frame too.
- **Auto-hide, including the rails.** During playback the top strip, the
  transport bar and both settings rails hide. Move the pointer to the bottom
  edge (or press **↑ / F1 / Esc**) to bring them back; while the pointer is on
  the settings panel it stays up, so you can tune without losing it.
- **Fixed: clicking the picture could freeze all mouse and keyboard input.**
  The picture's window was created on a thread that never processed messages;
  a click on it made Windows route input through a window that could not
  answer. It now processes messages, and input survives any click on the video.
- The transport bar sits at the screen edge instead of floating above it.

### Non-linear stretch on both axes

A 2.39:1 film on a 16:9 screen leaves black bars, and every fixed answer to
that has a cost: stretching evenly breaks shapes, warping only the horizontal
axis bends faces near the edges, cropping throws picture away. 2.0.0 turns
that into dials:

- **Bars removed (0–100 %)** — how much of the letterbox the picture grows
  into. 0 is the film at its own aspect with no distortion; 100 fills the
  screen. Taking half the bars costs half the distortion.
- **Axis: Horizontal / Vertical / Split**, with a **Split** percentage for the
  share each axis takes. Split 50 % turns a 24 % correction into about 12 %
  up-and-down plus 12 % sideways — the same fill, half the distortion per
  axis.
- **Max distortion (100–150 %)** caps the warp per axis in both directions;
  whatever the warp refuses is covered by cropping the axis that has slack.
- **Fill mode: Auto / Stretch / Crop / Off**, plus **Fill limit** for the
  largest correction Auto will fill with, and **Lock band** to keep one shape
  for titles that switch aspect mid-film (IMAX sequences).
- **Centre protection** (up to 90 %) keeps a uniform, undistorted band around
  the middle of the picture and pushes the correction into the rim.
- Everything applies **live, including on a paused frame**, and **N** toggles
  it. The Info panel's **Warp / Crop** row shows what the current settings are
  actually costing, so "why does it look like that" has a number next to it.

### Presets

- **Default** is a read-only baseline: picture changes while it is active are
  refused, with a warning card in the centre of the screen and an **OK** button.
- **Custom presets save themselves** — there is no Apply button. Clicking a
  preset in the card switches to it immediately, and the card stays open so
  you can compare setups on the same frame.
- **Playback** and **Source** are never part of a preset and never locked:
  audio mode, input device and port rescanning belong to the machine, not to a
  look.

### Update check

- Once a day, in the background, Unplugged asks GitHub for the latest release.
  When something newer exists, a card appears at start with the release notes
  and a link to the download page. It notifies only — nothing installs itself.
- Can be turned off in **System → App**; **Check for updates now** always works.

### Dolby Vision over HDMI, correctly reported

- The first-run HDMI capture dialog and the Info panel now report a Dolby
  Vision source as **Dolby Vision**. Previously the same signal was shown as
  SDR in both places, because the card reports it with no HDR flag of its own.
- The signal's dynamic metadata (MaxCLL / MaxFALL / mastering display) is read
  from the card and from files, and feeds the tone curve.

### Settings guide

- The full guide now ships with the app (`docs\settings-guide.md`) and follows
  the rail section for section: every visible control, its range, its default,
  and what the picture does when you move it.

## Upgrading from 1.3.x

- **Uninstall 1.3.x first** (Windows Settings → Apps → Unplugged). 2.0.0 is a
  different application; installing over the old one leaves the old Python
  files behind.
- **Your settings are kept.** The new app reads the same
  `%LOCALAPPDATA%\Unplugged\s3_shell.ini`, so your picture settings, presets
  and display calibration carry over. Give the Display Target numbers a quick
  look after upgrading.
- Your library folders are kept (they come from
  `%USERPROFILE%\.unplugged\app_config.json`).
- The first-time setup runs once: choose Live capture (HDMI) or Media player,
  pick your input and your media folder.

## Requirements

- Windows 10 or 11, x64.
- Microsoft Visual C++ 2015–2022 x64 runtime — bundled and installed silently
  by the setup; skipped when an equal or newer one is already present.
- A Blackmagic DeckLink card for live capture. File playback needs no card.

## Good to know

- Live HDMI capture handles 4K and HDR; Dolby Vision over HDMI is treated as
  its own case, and SDR, HDR10 and HLG are detected automatically.
- Two tone curves: **Unplugged** (the default, and the right choice for Dolby
  Vision) and **GT7 Adapt** (the manual choice for HDR10/HLG, which sizes the
  highlights from the master's own MaxCLL). The taste trims — Exposure, Shadow
  detail, Contrast — work on both.
- **Display Target** values (SDR display nits, static nits, display black) are
  per-display calibration, not per-title taste: set them once from a
  measurement and leave them.
- A `.cube` calibration LUT can be applied as the final pass, for a display
  whose panel is calibrated independently of tone mapping.
- In bitstream audio mode the receiver decodes, so the app's volume and mute
  controls are disabled by design; use PCM for in-app volume.
- The setup shows two licence pages: the Blackmagic DeckLink SDK licence and
  this project's end-user terms.

## Known limitations

- **Report a problem** records a log line only; no report is sent yet.
- **Playback → Delay** (audio lip-sync) saves but does not act yet.
- **Zion → Chroma → Mode** saves but the default behaviour always runs.
- Subtitle *styling* (font, size, colour) is not in the panel; track selection
  is.
- **Super Resolution** is a SDR-path feature: it does not apply to HDR or
  10-bit sources.
- With strong non-linear stretch, fine text can look slightly soft — both axes
  are being resampled. Lower **Strength** or **Centre protection** if it
  bothers you.
- Disc images (ISO) and BDMV folder playback are not supported; rip to a file.

## Download

| File | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.0.0.exe` | 127,000,899 bytes | `43DDF45A2C8E2949D1F0D46012EA15B4FB69D3FB1427DBE292366F166C0E7C00` |

## Source and licences

The binaries in this installer are built from four public repositories:

- https://github.com/spedagadi/unplugged-mpc-hc (application, engine, installer)
- https://github.com/spedagadi/unplugged-VideoRenderer (video renderer)
- https://github.com/spedagadi/unplugged-LAVFilters (modified LAV Filters)
- https://github.com/spedagadi/unplugged-ffmpeg (FFmpeg with the DeckLink
  capture path; pinned by the LAV repository's submodule)

The modified LAV Filters and FFmpeg are GPL-licensed; their complete
corresponding source is the repositories above, which is the offer the GPL
requires and which remains available for at least three years. See
`distrib/licenses/lav_gpl_source_offer.txt`.

Two binaries are derived from the Blackmagic DeckLink SDK headers
(`DeckLinkSource.ax`, `decklink_monitor.dll`). The SDK licence and the required
copyright notice accompany them in the installer and in `distrib/licenses/`.

This product is not affiliated with or endorsed by the MPC-HC, LAV Filters,
FFmpeg or Blackmagic Design projects.
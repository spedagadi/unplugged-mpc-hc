# Unplugged 1.0.0

HDR capture and playback for the HTPC: live HDMI in through a Blackmagic
DeckLink card with tone mapping, and local file playback through the same
renderer. Built on MPC-HC's filter architecture with the Unplugged video
renderer and a fork of LAV Filters.

## Installer

`Unplugged-setup-1.0.0.exe` â€” SHA-256
`0C366E17BBC21FA65E10019FD02C494F48F33A815E0AC55CA8E07D7AE102FB6F`

The setup registers its DirectShow filters at install time and unregisters them
at uninstall. It shows two mandatory licence pages: the Blackmagic DeckLink SDK
licence, and this project's end-user terms.

## Requirements

- Windows 10/11 x64.
- Microsoft Visual C++ 2015-2022 x64 runtime. It is NOT bundled: drop
  `vc_redist.x64.exe` into `distrib\redist\` before compiling the installer to
  have it installed silently, otherwise the target machine must already carry
  it.
- A Blackmagic DeckLink card for capture. File playback needs no card.

## What is in this release

- Live DeckLink ingest with HDR/SDR handling, DV profile-7 and profile-5
  recognition, and self-healing acquisition.
- File playback with embedded subtitles through MPC-HC's internal subtitle
  path (text and bitmap tracks), a Source tab listing every DeckLink input with
  friendly names and live signal state, and on-the-fly input switching.
- Tone mapping: GT7 / GT7 Adapt / Hable / Reference and the experimental
  spline, with per-display calibration (peak, black, SDR white) in the
  Display Target section.
- First-run setup for choosing capture or playback mode, re-runnable from the
  Source tab and from System.

## Source and licences

The binaries in this installer are built from four public repositories, tagged
`v1.0.0`:

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
(`filters\DeckLinkSource.ax`, `_internal\decklink_monitor.dll`). The SDK licence
and the required copyright notice accompany them in the installer and in
`distrib/licenses/`.

This product is not affiliated with or endorsed by the MPC-HC, LAV Filters,
FFmpeg or Blackmagic Design projects.

## Known limitations

- In bitstream audio mode the receiver decodes, so the application's volume and
  mute controls are disabled by design; switch to PCM for in-app volume.
- Changing a rebuild-only setting (audio mode, swap effect, texture format)
  re-opens the source; playback resumes at the position it stopped at.
- The settings rail's Display Target values are per-display calibration, not
  per-title taste: set them once from a measurement report.

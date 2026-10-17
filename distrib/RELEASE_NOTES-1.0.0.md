# Unplugged 1.0.0

HDR capture and playback for the HTPC: live HDMI in through a Blackmagic
DeckLink card with tone mapping, and local file playback through the same
renderer. Built on MPC-HC's filter architecture with the Unplugged video
renderer and a fork of LAV Filters.

## Installer

`Unplugged-setup-1.0.0.exe` - 184,760,167 bytes, SHA-256
`ACAB7D11FA4128BE5E0026925C012D0C0515F15F07AF6CFE07E4237CB1624DD1`

The setup registers its DirectShow filters at install time and unregisters them
at uninstall. It shows two mandatory licence pages: the Blackmagic DeckLink SDK
licence, and this project's end-user terms.

## Requirements

- Windows 10/11 x64.
- Microsoft Visual C++ 2015-2022 x64 runtime: bundled and installed silently by
  the setup. It is skipped only when `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`,
  `MSVCP140.dll` and `MSVCP140_1.dll` are all present in System32 at the bundled
  version or newer - the four names `filters\onnxruntime.dll` imports, which is
  what needs them. Either answer is recorded in the install log (logging is on by
  default). Building the installer refuses to run if `distrib\redist\
  vc_redist.x64.exe` is missing, not Microsoft-signed, or a different version than
  the installer's threshold; see `distrib\vc_runtime.iss` and its harness
  `distrib\run_vc_check.ps1`.
- A Blackmagic DeckLink card for capture. File playback needs no card.

## What is in this release

- Live DeckLink ingest with HDR/SDR handling, Dolby Vision over HDMI recognised
  as its own case, and self-healing acquisition.
- File playback with embedded subtitles through MPC-HC's internal subtitle
  path (text and bitmap tracks), a Source tab listing every DeckLink input with
  friendly names and live signal state, and on-the-fly input switching.
- Tone mapping with **Unplugged** as the default curve for every HDR source
  (HDR10 and Dolby Vision alike) and **GT7 Adapt** as the manual choice that
  lets a master's own MaxCLL size the highlights; per-display calibration
  (peak, black, SDR white) lives in the Display Target section.
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

- Disc images (ISO) and BDMV folder/playlist playback are not supported; rip to
  a file.
- Dolby Vision in files (profile 5) is not supported in Media Player mode. DV
  over HDMI is a capture-path feature and is handled there.
- In bitstream audio mode the receiver decodes, so the application's volume and
  mute controls are disabled by design; switch to PCM for in-app volume.
- Changing a rebuild-only setting (audio mode, swap effect, texture format)
  re-opens the source; playback resumes at the position it stopped at.
- The settings rail's Display Target values are per-display calibration, not
  per-title taste: set them once from a measurement report.

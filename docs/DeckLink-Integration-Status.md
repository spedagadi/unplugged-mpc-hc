# DeckLink HDMI Input — Integration Status

> Status checkpoint 2026-09-10. Companion: `Ingest-Architecture.md`, `DeckLink-Capture-Low-Latency.md`.

## Where the pieces live (all committed)

| Repo | Commit | What landed |
|---|---|---|
| LAVFilters `master` | `724c32e1` | `decklink://` input in LAVSplitterSource (avdevice link, URL+query parsing, distinct HRESULTs, `DECKLINK_BUILD_TAG` traces) + `test_lav_decklink` spike |
| mpc-hc `zion-s3-shell` | `a0749d1c1` | `DeckLinkMonitor` (500 ms poll of `decklink_monitor.dll` w/ 2 s open-retry + log sink), `MpcPlayer` signal/stream-info exposure, LIVE panel (CAPTURE INPUT / DEMUXER→REC / RENDERER IN), working VP/Media bottom-bar buttons, quote-stripped `--decklink-device` |
| VideoRenderer `zion-ml-phase0` | `732da5f` | `Settings_t.iInputColorSpace` override (applied after `SpecifyExtendedFormat` in `InitMediaType`, re-derived on media-type change) + `rendererIn:` line in `GetMLStats` + ICS traces into `ml_debug.csv` |
| decklink_monitor (unplugged) | (pre-existing) | `decklink_monitor.dll` — read-only `IDeckLinkStatus` polling; exports `VFSignalInfo` (cs/dr/depth/chroma/lock/WxH/fps), `vf_dl_build_url` |

## Current signal path (implemented)

```
HDMI source (movie player / STB / AVR)
  │
  ├─ decklink_monitor.dll (read-only status) ──► DeckLinkMonitor thread (500ms)
  │      lock/cs/dr/depth/chroma/WxH/fps → LIVE panel CAPTURE INPUT
  │      change → vf_dl_build_url → restart request (ICS + new URL)
  ▼
LAVSplitterSource  ←  decklink://<device>?video_input=hdmi&raw_format=…&no_audio=1
  │  av_find_input_format("decklink") → FFmpeg decklink indev
  │  (forced format_code from the monitor when signal locked — no 3s autodetect)
  ▼
LAVVideo → MPCVR  (iInputColorSpace pushed via Settings; rendererIn telemetry)
  VIDEO-ONLY (no_audio=1) — HDMI audio routes to the AVR separately
```

## Verified so far

- **Engine keying off decklink_monitor on real hardware**: HTPC log shows
  `vf_dl_open rc=0`, signal `locked=1 cs=0 dr=0 depth=10 | 720x486 30000/1001fps il=1`
  (NTSC 10-bit 4:2:2 SDR), correct `format_code=ntsc` URL built, ICS=1 mapped,
  restart requested. The monitor→URL→LIVE-panel chain works on the card.
- **Spike (LAV alone)**: `test_lav_decklink.exe` loads the bundled
  `LAVSplitter.ax` by explicit path, prints version + each stage HRESULT +
  `av_strerror` text. On a no-card machine it shows `AVERROR_EXTERNAL`
  ("Generic error in an external library") — the expected device-QI failure.
- **Distinct failure HRESULTs** now reach callers (`done:` honored the set HR
  instead of collapsing to `E_FAIL`).

## Open on the HTPC (next run)

1. **`Test-LAV-DeckLink.cmd "DeckLink Quad HDMI Recorder (1)"`** — does the
   bundled LAV open `decklink://` alone? If `Load OK` → fault is shell-side;
   if `av_strerror='…'` → the card refused something specific. Build tag on
   every `[decklink]` line cross-checks which `.ax` ran (bundle must contain a
   **fresh** LAV — earlier HTPC registration pointed at a stale copy; distinct
   codes proved it).
2. **s3_shell VP mode after LAV confirmed** — full graph open, LIVE panel
   values, movie↔menu restart timing.
3. If 1 still fails on the card: capture FFmpeg's `av_log` output
   (`dbgLog` text may show the exact `ff_decklink_init_device` / autodetect
   branch).

## Known gaps / not done

- FFmpeg decklink indev currently matches devices by **exact strcmp**; the
  monitor uses substring. A name mismatch would fail LAV but not the monitor —
  candidate hardening if the spike shows device-not-found on the HTPC.
- Interlaced (720x486i) input: field handling through the graph is untested.
- 3 s autodetect stall remains for the very first open (probe URL has no
  `format_code`); refined on first signal report.
- `_test_vp.cmd` harness removed from the bundle (it auto-`TASKKILL`ed the
  shell — caused the "screen blanks + auto shutdown" seen on the HTPC).
- DecklinkMonitor open-retry logs "device not opened yet" every 500 ms while a
  card is absent — fine for diagnosis, could be throttled later.

## Deploy bundle

`VideoRenderer\_bin\decklink-s3-shell.zip` — contains s3_shell + monitor +
LIVE-panel build, `test_lav_decklink.exe` + `Test-LAV-DeckLink.cmd`, fresh
LAVFilters-x64 (decklink build), MPCVR (ICS build) + models, install/uninstall
cmd. First HTPC step after extracting: `Test-LAV-DeckLink.cmd`, then
`Install-Register.cmd` (admin), then VP mode.
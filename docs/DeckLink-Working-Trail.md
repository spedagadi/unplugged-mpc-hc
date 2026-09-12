# DeckLink HDMI Ingest — Working Trail (as of 2026-09-12)

The piece-by-piece history of the DeckLink HDMI capture → MPCVR render pipeline,
so work can be picked up on a fresh HTPC clone. Companion docs:
`DeckLink-Integration-Status.md`, `Ingest-Architecture.md`,
`DeckLink-Capture-Low-Latency.md`, `STATUS-2026-09-07.md`.

## Goal

`s3_shell.exe` (UI/control) → `MpcPlayer` (engine) builds a graph that ingests a
DeckLink HDMI input as live video, grades it with the Zion ML pipeline (MPCVR),
and **bypasses HDMI audio to the AVR** (bitstream — MPCVR never sees it).

## System map

| Piece | Repo / branch | Role |
|---|---|---|
| `s3_shell.exe` | mpc-hc `zion-s3-shell` | Frameless control UI: Playback sheet, LIVE panel, VP/Media mode, ML/HDR/OUTPUT rows |
| `MpcPlayer` (mpchc_engine.lib) | mpc-hc `zion-s3-shell` | Graph builder: LAVSplitterSource(`decklink://`) → decoder → MPCVR; audio → LAVAudio + MpcAudioRenderer (WASAPI-exclusive bitstream) |
| `DeckLinkMonitor` | mpc-hc `zion-s3-shell` | 500 ms poll of `decklink_monitor.dll`; on signal/format change posts `kCmdDecklinkRestart` → Stop/Open/Play with the monitor's refined URL |
| LAVSplitterSource | LAVFilters `master` | Accepts `decklink://<device>?…` URLs, links the FFmpeg decklink indev |
| FFmpeg `libavdevice/decklink_dec` | LAVFilters `ffmpeg` submodule | Capture source (no_audio = video-only when HDMI audio goes to the AVR) |
| MPCVR (VideoRenderer) | VideoRenderer `zion-ml-phase0` | Renderer + Zion ML grade; `iInputColorSpace` override for the DeckLink raw input |
| `decklink_monitor.dll` | external (unplugged), pre-existing | Read-only `IDeckLinkStatus` polling; exports `VFSignalInfo` (lock/cs/dr/depth/chroma/WxH/fps) + `vf_dl_build_url` |

## Live capture URL

```
decklink://<device>?video_input=hdmi&signal_loss_action=repeat&no_audio=1&raw_format=uyvy422
```

`no_audio=1` = video-only ingest (HDMI audio routed to AVR separately); the FFmpeg
decklink decoder now gates stream creation, `EnableAudioInput` and the audio packet
path on that flag.

## Per-repo commits (current SHAs on the GitHub forks)

### LAVFilters — `unplugged-LAVFilters`, branch `master`

| SHA | What |
|---|---|
| `b9b84879` | `decklink://` input in LAVSplitterSource (avdevice link, URL+query parsing, distinct HRESULTs, `DECKLINK_BUILD_TAG` traces) + `test_lav_decklink` spike |
| `9b53f194` | ffmpeg **submodule bump** → `270f7d55e9` |

> ⚠️ **The ffmpeg submodule commit `270f7d55e9` (branch `lav0.83-decklink`) exists
> only in the local clone at `C:\Code\LAVFilters\ffmpeg`.** Its origin is LAV's
> private gitea and it is NOT pushed anywhere. A fresh `git clone` of the fork
> cannot fetch it. Either copy the whole `C:\Code\LAVFilters` folder to the HTPC
> (includes the submodule checkout), or push `lav0.83-decklink` to a new
> `unplugged-FFmpeg` repo and repoint `.gitmodules`, then everything clones.

FFmpeg submodule content (`270f7d55e9`):
- `libavdevice/decklink_dec.cpp` — `no_audio` support: read_header skips the audio
  stream, gates `EnableAudioInput` + audio frame path on `ctx->audio_st`
- wild DeckLink SDK headers vendored in `decklink/` (sidecar-free build)

### mpc-hc — `unplugged-mpc-hc`, branch `zion-s3-shell`

| SHA | What |
|---|---|
| `a0749d1c1` | DeckLink LIVE panel + signal monitor: `DeckLinkMonitor` (500 ms poll, 2 s open-retry), `MpcPlayer` `Set/StopDecklinkCapture` + `GetDecklinkSignalInfo` + `VideoStreamInfo`, VP/Media bottom-bar buttons, `--decklink-device` CLI |
| `7a0f3d00a` | docs: Integration-Status + STATUS-2026-09-07 + Ingest-Architecture |
| `04d6d761a`…`d30c7cdba` | person-skin settings → shadow dehaze → autoAdjustable → highlight shoulder |
| `9fa4d3296` | **settings persistence** (`s3_shell.ini` beside the exe) + **Bitstream default, all HD codecs on** |

Engine mechanics: `ConnectAudio` CoCreates `CLSID_MpcAudioRenderer` first (falls back
to DSound); LAV bitstream config is applied **before pin connect**; renderer cfg
mode = `MODE_WASAPI_EXCLUSIVE_BITSTREAM` vs shared.

### VideoRenderer — `unplugged-VideoRenderer`, branch `zion-ml-phase0`

| SHA | What |
|---|---|
| `732da5f` | MPCVR `iInputColorSpace` override (applied after `SpecifyExtendedFormat` in `InitMediaType`, re-derived on media-type change) + `rendererIn:` line in `GetMLStats` + ICS traces into `ml_debug.csv` |
| `8d39d1b`…`e7cb4da` | seg cadence fix, per-instance skin gate, stutter gating, person parking, dehaze (`c1d235f`), shoulder (`e7cb4da`) |
| `873133e` | vendored `Source/onnxrt/` (ONNX Runtime + yolo models) — fresh clones build |
| `2b7a35f` | docs: ZION_ML_GRADE status checkpoint |

## Verified so far

- **HTPC 2026-09-07**: gamma tracks + Dolby Atmos bitstream confirmed. MpcAudioRenderer
  has a regsvr32 quirk — needs the `InprocServer32` of `{601D2A2B-9CDE-40bd-8650-0485E3522727}`
  pinned to the .ax path.
- DeckLink capture graph builds over `decklink://` probe URL; monitor auto-restarts on
  signal/format change (`kCmdDecklinkRestart`) with colour-space re-push.
- s3_shell persists and re-applies settings on every open/restart (fresh-graph reset fixed).

## Open / next on the HTPC

1. **ffmpeg submodule replicability** (the ⚠️ above) — copy the folder, or push to a
   sibling repo and repoint `.gitmodules`.
2. **Verify bitstream default + persistence on the HTPC box** (Audio row shows
   Bitstream/all-ON on first launch; a changed setting survives restart).
3. **S4 capture polish** (per Ingest-Architecture): signal-loss relock behaviour,
   format-change latency; `CLiveSource` link-vs-lift decision.
4. **TrueHD / DTS-HD MA parity** beyond Atmos; PCM speaker fallback still works.
5. **Zion-on-live ingest validation**: ICS correctness (auto → 709/2020), sky/person
   tone legs on the live signal, ZION_ML_GRADE.md parked stage-5 resume path.

## Moving to the HTPC (clone-safe checklist)

1. Clone `unplugged-mpc-hc` (`zion-s3-shell`) + `unplugged-VideoRenderer` (`zion-ml-phase0`).
2. LAVFilters: **copy your local folder** (submodule caveat), don't clone.
3. Extract `s3_shell_htpc.zip` (the deploy bundle — binaries + models + `register_all.cmd`),
   run `register_all.cmd` elevated, start `bin\s3_shell.exe`.
4. Diagnose via `s3_shell_diag.log` (`[AUDIO] CoCreate… hr=` / `mode=`, `[DECKLINK][shell]`
   lines) and the LIVE panel.
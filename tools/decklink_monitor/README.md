# decklink_monitor.dll

Read-only DeckLink signal monitor used by `s3engine.dll` (`DeckLinkMonitor`) and by the
shell's first-run HDMI dialog. It queries `IDeckLinkStatus`, which needs no exclusive
device lock, so it works while the capture pipeline owns the card.

## Export contract — do not trim this list

`DeckLinkMonitor::EnsureLoaded()` requires **`vf_dl_open` AND `vf_dl_build_url`**:

```
vf_dl_open, vf_dl_get_signal_info, vf_dl_build_url, vf_dl_close, vf_dl_enumerate_devices
```

If `vf_dl_build_url` is missing the engine logs `monitor Start FAILED — resetting monitor`
and ingest never starts, **even though the card reports signal locked**. That is what a
2026-10-31 rebuild from the older `mpv-videoprocessor` fork of the source did — that fork
predates `vf_dl_build_url`. Always build from *this* copy.

Also exported (legacy callers): `vf_dl_signal_locked`, `vf_dl_get_mode`,
`vf_dl_get_dynamic_range`, `vf_dl_poll_all_ports`.

## Build

```
build_monitor.bat [sdk_include_dir]
```

Default SDK is `C:\code\LAVFilters\ffmpeg\decklink`. MSVC x64, static CRT, no dependency
beyond `ole32`/`oleaut32`/`kernel32` — verify with
`dumpbin /dependents decklink_monitor.dll`.

Verify after any build:

```
dumpbin /exports decklink_monitor.dll | findstr vf_dl_
```

9 exports, `vf_dl_build_url` among them.

## `vf_dl_poll_all_ports` dr values

| value | meaning |
|-------|---------|
| 0     | SDR |
| 1     | HDR PQ |
| 2     | HDR HLG |
| 3     | Dolby Vision — card reports BT.2020 with no player-type HDR flag (Dolby's VSIF replaces the HDR10 InfoFrame). This is 1.3.0's `is_likely_dolby_vision()` rule. |
| -1    | unknown |

The DV rule lives in the poll itself because the first-run dialog has no graph running and
therefore no engine to ask.

## Staging

Copy the built DLL to **all** of:

- `bin\app\Release\decklink_monitor.dll`
- `dist\Unplugged-<version>\decklink_monitor.dll`
- `tools\engine_s3\decklink_monitor.dll` (reference copy used by proofs)

then rebuild the installer — `distrib\build_unplugged_setup.ps1` has a stale-native hash
gate that will refuse a mismatched payload.
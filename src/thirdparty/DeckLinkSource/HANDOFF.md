# DeckLink ingest via DirectShow — handoff

State as of 2026-09-13 (late, after the AV-latency work). Intended as the
jump-start for a fresh session. If this file is stale on your bench, re-verify
the two claims marked *[verify]* before building on them.

## 1. Why this exists

The HTPC DeckLink chain is:

```
DeckLink HDMI -> ffmpeg indev (queue_size=128M fifo) -> LAVSplitter (12-pkt queue)
             -> LAVVideo -> MPCVR (ML grade) -> display
```

- Audio goes physically to the AVR (HDMI bitstream, `no_audio=1` in the URL).
- Symptom: video ran **>500 ms behind audio** (AVR's max lip-sync offset ran
  out). Root cause found: the ffmpeg decklink packet queue **drops the NEWEST
  packet when full** (`ff_decklink_packet_queue_put`, decklink_common.cpp), so
  once it fills during graph construction it stays pinned to the *oldest*
  backlog forever — the demuxer can never roll forward to live frames.
- Mitigations landed in libav: `live_frames=N` drop-stale-at-read option
  (`&live_frames=4` in the URL built by decklink_monitor) + LAV/ffmpeg + a
  renderer present-lag meter (`RenderStats_t::presentLatencyMs` surfaced as the
  LIVE panel **Latency** row + `lag=` on the `[RENDER]` log line).
- That fixed the fifo backlog (log proves: `live_frames mode ENABLED`, `dropped
  4 aged`, queue capped at 4, `lag=0 drop=0 drawFps=23.98`) **but the user
  reported the AVR still needs >500 ms** — i.e. a residual constant exists
  somewhere else in the chain and the relative lag meter cannot see it (it
  cancels constant latencies). Do NOT assume it's gone.

This spawned the decision: **replace ffmpeg/LAV ingest with our own DeckLink
DirectShow source filter** so the whole path stays measureable, one bounded
queue, no forks.

## 2. Phase 1 — capture-session spike (DONE, validated)

Tool: `C:\code\unplugged\decklink_spike\decklink_capture_spike.c` + `_build_spike.sh`
(build: msys2 gcc + `LAVFilters/ffmpeg/decklink/DeckLinkAPI_i.c` + `-I…/decklink`).

Results on the bench:
- Raw SDK session streams at full cadence (1080p50: 300 frames, 50 fps exact,
  0 missed; also caught a `4k23` = 3840x2160@23.98 signal).
- Pixel format: **v210 10-bit 4:2:2** (`v210`).
- **`GetHardwareReferenceTimestamp` is wall-aligned**: (wall − hwRef) ≈ −28 ms
  ±14 ms (≈1 frame + callback schedule). => absolute capture→screen latency is
  directly measurable from hwRef. Critical fact for the filter's timestamps.
- `GetDisplayMode(bmdModeUnknown)` → E_INVALIDARG on this SDK/driver. You must
  enable with a safe fixed mode + `bmdVideoInputEnableFormatDetection` and let
  `VideoInputFormatChanged` drive renegotiation.
- The naive renegotiation in the spike **churned**: every restart re-fired the
  change event (including `events=0x04` = `bmdVideoInputColorspaceChanged` on
  HDR content) → 54 restarts / 20 s and inflated missed-gaps. Lesson: only
  restart on a *display-mode* difference; treat colorspace-only events as
  metadata (they are the HDR/PQ cue on HDMI).

## 3. Inspiration

`C:\code\videoprocessor\src\VideoProcessor-Lib\` (Dennis Fleurbaaij video
processor; GPLv3 — use as inspiration, do NOT copy wholesale):
- `ACaptureDevice` / `blackmagic_decklink/BlackMagicDeckLinkCaptureDevice` —
  capture device abstraction (StartCapture/StopCapture, ITimingClock,
  SetFrameOffsetMs for future-offset timestamps, HardwareLatencyMs).
- `EpochBoundedQueue` / `CaptureFrameQueue` — bounded, stale/overflow-discard
  queue with metrics.
- `microsoft_directshow/live_source_filter/` — `CLiveSource` filtering + output
  pin (`CUnbufferedLiveSourceVideoOutputPin` = deliver immediately).

## 4. Phase 2 — DeckLinkSource filter (BUILDS + REGISTERED 2026-09-13)

File: **`C:\code\unplugged-mpc-hc\src\thirdparty\DeckLinkSource\DeckLinkSource.cpp`**
(~460 lines, single-file push source filter):
- One video output pin, media type v210 (VIDEOINFOHEADER2, colorimetry packed
  into `dwControlFlags` extended bits from state: colorspace {unk,601,709,
  bt2020} x eotf {gamma,PQ,HLG}).
- `CaptureState` (critical section) shared between the DeckLink input thread,
  the pin, and a worker thread.
- `StartCaptureSession(deviceName)` — C++ DeckLink discovery; enable
  `bmdFormat10BitYUV` with `bmdVideoInputEnableFormatDetection`; StartStreams
  from the **worker** (never inside the SDK callback).
- Capture callback: hwRef(µs) → sample times (×10 → 100 ns), copies v210 (row
  stride via `GetRowBytes()`), `SetDiscontinuity` on first frame, delivers via
  the pin (via a public `AcquireSample` shim over protected
  `GetDeliveryBuffer`).
- `VideoInputFormatChanged`: **mode-diff-only restart** (idempotent, debounced),
  colorspace/eotf metadata update from `bmdVideoInputColorspaceChanged`.
- Registration boilerplate + new CLSID
  `{8C2F2A32-27B1-4E61-A1BE-7884F2410E7A}`.

### Build state (2026-09-13 — compiles clean, registered)
- **DeckLink C++ SDK vendored (12.4)**: `DeckLinkAPI_h.h` + `DeckLinkAPIVersion.h`
  copied from `C:\code\videoprocessor\3rdparty\blackmagic_decklink\` (the MIDL
  C++ API; LAVFilters' `decklink/*` are the WIDL C vtbl API and were NOT used).
  `DeckLinkAPI_i.c` hand-lists the GUIDs (IID_IDeckLink*, IID_IDeckLinkInput[Callback],
  CLSID_CDeckLinkIterator) via `<initguid.h>` + `DEFINE_GUID` — the MIDL header
  only *declares* them. Also defines CLSID_DeckLinkSource there.
- **Project**: `DeckLinkSource.vcxproj` (standalone; `Release Filter|x64` → `.ax`),
  modeled on `src/filters/source/SubtitleSource/`. PCH off (`NotUsing`), include
  `..\BaseClasses`, ProjectReference pins BaseClasses via
  `<Properties>Configuration=Release;Platform=x64</Properties>` (BaseClasses has
  no "Release Filter" config). `DeckLinkSource.def` = the four `Dll*` exports.
- **Build**: `tools\engine_s3\build_decklink_source.bat` (vsdevcmd + msbuild).
  Clean, 0 warnings. Output:
  `src\thirdparty\DeckLinkSource\bin\Filters_x64\DeckLinkSource.ax`.
- **Fixed in the draft before it compiled** (all latent bugs):
  - worker thread was never started — now spawned in `StartCaptureSession`;
  - `StopCaptureSession` could hang `join()` — now signals the worker, stops
    streams, joins, *then* releases interfaces;
  - callback held the state CS across `AcquireSample`/`Deliver` — now snapshots
    state under the lock and delivers outside it;
  - no `DllMain` → registration dies (g_hInst null) — added the `DllEntryPoint`
    shim (LAV pattern);
  - `MEDIASUBTYPE_v210` const (FOURCC GUID) matching MPCVR's MediaTypes.h;
  - `dwControlFlags` now packs the WHOLE `DXVA2_ExtendedFormat` value (MPCVR
    reads it as-is); the draft's `ef.value << 16` was wrong. BT2020=9 / 2084=15
    / HLG=16 in the 5-bit fields — the MF constants MPCVR compares against
    (SDK dxva2api.h lacks them, defined locally);
  - `<d3d9.h>` must precede `<dxva2api.h>`.
- **Registered**: `regsvr32 /s` (elevated). CLSID
  `{8C2F2A32-27B1-4E61-A1BE-7884F2410E7A}` = "DeckLink Source",
  ThreadingModel=Both.
- Not yet: Phase-2b bounded drop-stale deliver queue; in-place media-type
  renegotiation (monitor rebuild + size-gate drop is the current resync).
- RESOLVED: the 1080↔4k stride overrun — the callback size-gate DROPS (never
  clips) any frame whose dims differ from the connected type.

### Session status 2026-09-13 — NEAR-LIVE INGEST WORKING (video on screen)
- Direct path live and rendering: DeckLink → DeckLinkSource (v210→P010) → MPCVR
  at 4K/23.98 + 1080p50, PQ/HDR on HDR sources; recv≈drawFps, fail=0.
- **Color pipeline is honest**: `SetSignalMeta` (control-interface method) lets
  the engine push the monitor's detected cs/dr into the filter so the media type
  advertises BT.2020/PQ from the FIRST connect (was BT.709 default → washed-out
  at Auto-ICS). An in-callback IDeckLinkStatus query for the same info STALLED
  capture — never do SDK status calls on the capture path. Engine maps the
  monitor's cs/dr in BuildGraph before StartCapture.
- **Stop/deadlock fixed**: Inactive never calls StopStreams on the graph thread
  (in-flight Deliver against a stopping renderer = freeze). `stopPending` makes
  callbacks bail; the worker stops the card asynchronously. Restart churn
  debounced (1.5 s) in the shell — the source oscillates modes/HDR aggressively.
- Sample timestamps are GRAPH-RELATIVE (hwRef anchored at first delivered frame);
  absolute hwRef times schedule hours into the future (DirectShow clock) and
  wedge the renderer. MPCVR's presentLatencyMs is a relative gauge — an absolute
  capture→present gauge is still an open item.
- LIVE panel upgraded (vocab aligned with unplugged's Python status_panel):
  CHAIN (backlog/drift/renegotiations) · CAPTURE INPUT (real mode, frames) ·
  VIDEO SOURCE (BT.2020/PQ/Bitrate) · RENDERER IN · TONE MAPPING (algorithm=
  curve, SDR target peak read from MPCVR) · DISPLAY OUTPUT (Target TRC = output
  transfer fN only, Cs, Prim — driven by MPCVR's live swapchain domain).
- Run rules: exactly ONE s3_shell (card is single-owner; a second instance parks
  with no video), launch with `--decklink-device "DeckLink Quad HDMI Recorder (1)"`.
  Persisted defaults: convertToSdr=1 (user's display), toneMapCurve Hable,
  maxNits 1000; sdrNits/MPCVR owns the SDR target value.

### Engine wiring + bench status (2026-09-13) — SEE THIS BEFORE TOUCHING
- `MpcPlayer::BuildGraph` now CoCreates `CLSID_DeckLinkSource` for `decklink://`
  URLs and connects its v210 pin straight to MPCVR. Control via a new shared
  `IDeckLinkSourceControl` (`DeckLinkSourceControl.h`): `StartCapture(BSTR)`
  (blocks ≤3 s for the first detected format → real media type at connect),
  `StopCapture()`, `SetLogSink(ctx, fn)` — filter telemetry routes into the
  shell diag log as `[DECKLINK][src] ...`. LAV path remains the fallback when
  the .ax isn't registered. s3_shell.cpp needed NO changes.
- **Card verified live on this machine**: DeckLink Quad HDMI Recorder, 4 HDMI
  ins, source present on input (1) but OSCILLATES 1080p50 ↔ 4k23 and toggles HDR
  (cs=2/PQ via EDID; monitor reports `locked=1 cs=2 dr=1 depth=12 0x0 0/0fps` —
  the monitor never resolves dims; capture is 10-bit v210). The raw-SDK spike
  streams both modes fine.
- **Latent draft bug caught + fixed**: `CaptureState.active/started/enabled/
  everStarted/quit` were UNINITIALIZED — the worker read garbage `started!=0`
  and skipped Enable/Start entirely (no frames). Zero-initialized now.
- **BLOCKER for direct video — MPCVR cannot host raw v210 samples**: MPCVR's
  `CustomAllocator` sizes every sample from `biSizeImage` of its own transformed
  copy of the media type (`SetNewMediaType`, CalcImageSize → GetAlignmentSize +
  DIBSIZE). For v210 that yields ~2.5-2.67 B/px but the SDK's row-padded layout
  ((w+47)/48)×128×h needs ~2.67 B/px → the granted buffer (e.g. 20,736,000 B for
  3840×2160) is smaller than the copy need (22,118,400 B) → first version
  memcpy'd out of bounds (AV in DeckLinkSource.ax, crash #0xc0000005).
  The "MPCVR supports v210" assumption came from the LIVE panel showing the
  DEMUXER type — the renderer never received raw v210 before (LAVVideo decoded
  it).
- **SOLVED — output P010 (10-bit 4:2:0), converted in the filter**: v210→P010
  conversion added (`V210ToP010` in DeckLinkSource.cpp, scalar, averaged vertical
  chroma — adapted from VideoProcessor-Lib's CV210toP010VideoFrameFormatter,
  which the user asked about; GPLv3, inspiration-level reuse of the standard
  v210 packing). P010 is LAVVideo's production HDR path: MPCVR granted the full
  24,883,200 B buffer (w*h*3, no clamp), `vf` connect OK, and **live 4K video
  renders**: `[RENDER] recv=1xxx drawFps≈24 fail=0` at 3840×2160/23.98 with
  PQ/HLG (tf=15 hdr=1) passed in dwControlFlags. 2026-09-13: direct ingest
  video ON.
- **Timestamps are now graph-RELATIVE** (not absolute hwRef): DirectShow clocks
  begin near 0 at graph start, so absolute hwRef sample times would schedule
  frames hours in the future and the renderer never releases the capture thread
  (a stop-the-world freeze after the first frame — Play never completed). The
  filter re-anchors `rtBaseUs` to the first *delivered* frame's hwRef; stream
  time then advances 1:1 with capture (inactive/resets re-anchor). MPCVR's
  `presentLatencyMs` is itself a RELATIVE gauge (wall-delta − stream-delta), so
  nothing absolute is lost — the >500 ms constant-latency question still needs
  an external absolute measurement (walk the remaining Phase-2b item).
- Still to do: crash-free stop hardening (the pre-P010 memcpy crash is gone;
  teardown invariants logged), the absolute-latency measurement (present-wall −
  hwRef as its own gauge), in-place renegotiation on resolution change (monitor
  rebuild is the current resync), remove the temporary debug StateLogs once the
  bench is stable.
- Gotcha if re-adding a solution build: `Filters.sln` sets `SolutionDir`, so the
  same project emits the .ax to the repo-root `bin\Filters_x64\` instead of the
  local `bin\Filters_x64\`. Keep standalone msbuild as the canonical path.

## 5. Planned graph (target)

```
DeckLinkSource.ax (v210 pin)  ->  MPCVR          (direct, no LAVVideo)
```
- `MpcPlayer::BuildGraph` gets a `bDeckLinkDirect` branch (CoCreate the CLSID,
  `StartCaptureSession(device)` **after** connect so ingest starts last), old
  LAV path stays as fallback.
- LIVE panel already has the `Latency` row (works for any renderer that sets
  `RenderStats_t::presentLatencyMs`).
- MPCVR supports v210 input (LIVE panel showed `fmt v210` through the LAV
  path).

## 6. Still-open from the latency thread (do not drop)

- The **>500 ms residual** was never isolated. With the direct-source filter +
  hwRef timestamps the absolute number becomes visible: present-wall − hwRef;
  if it still reads large with `live_frames=4` semantics replaced by our own
  queue (Phase-2b: bounded drop-stale queue on the deliver path, depth 2-3),
  instrument stage-by-stage (allocator wait, pin Deliver, DWM, GPU grade).
- Cadence auto-refresh work (48/96/120 Hz for 24p, projector 23.976 mode):
  commits d25a99c/2b723d0 in `unplugged-VideoRenderer` + c4b000ca8 in mpc-hc.
  Projector test pending; the LCD was 50/100 Hz only.

## 7. Repos / builds

- Engine+shell: `unplugged-mpc-hc` — `tools/engine_s3/rebuild_engine.bat`,
  `build_s3_shell.bat` (msbuild, x64).
- DeckLinkSource filter: `unplugged-mpc-hc` —
  `tools/engine_s3/build_decklink_source.bat`; output
  `src/thirdparty/DeckLinkSource/bin/Filters_x64/DeckLinkSource.ax` (regsvr32 it).
- Renderer: `unplugged-VideoRenderer` — `_rebuild_mpcvr.bat`; registered at
  `_bin\MpcVideoRenderer-0.10.8.2632\MpcVideoRenderer64.ax` (regsvr32 it after
  copying; dist step fails on version-header, .ax still builds).
- Monitor DLL: `unplugged\decklink_monitor\_build_monitor.sh` (gcc; deployed to
  `tools/engine_s3/decklink_monitor.dll`; builds the URL incl. `live_frames=4`).
- LAV/ffmpeg fork: `LAVFilters` — `_rebuild_ffmpeg.sh`; filters land in
  `LAVFilters/bin_x64` (registered path for LAVSplitter/LAVVideo).
- Git: commits are NOT pushed (use GitHub Desktop); mpc-hc branch zion-s3-shell.
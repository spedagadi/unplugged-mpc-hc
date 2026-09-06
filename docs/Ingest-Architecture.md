# MPC-HC — DeckLink Ingest + Playback Architecture

> **Status:** iterating. Markers: ✅ decided · 🟡 working direction · ❓ open.
> Last updated: 2026-09-06. Companion docs:
> [`DeckLink-Capture-Low-Latency.md`](DeckLink-Capture-Low-Latency.md)
> (verified libav option set) and `C:\Code\LAVFilters\build_ffmpeg.sh`.

## ✅ Form factor — DECIDED (2026-09-06): "B"

**Unified, single-window, full-screen surface** (the Unplugged layout): one
window where the video and all UI surfaces (left LIVE pane, right rail, bottom
bar, wallpaper) are composited together. An in-proc engine layer
(`mpchc_engine`, §5.5) owns playback/capture; the UI layer (§5.6) owns
everything on-screen and talks to the engine over a JSON command/property/event
dialect. MPC-HC's built-in **web server** is *not* the spine — it is (a) the
prototype control channel for a host prototype today, (b) the vocabulary seed
for the JSON dialect, and (c) the future companion/IR remote protocol.

## 1. Goals

Build the DeckLink **ingest + playback product** on the mpc-hc stack, with an
Unplugged-derived, IR-remote-first UI:

- **Two application modes** driving two different graphs (§3).
- **Engine/UI separation** like Unplugged (PyQt host ⇄ mpv engine): a headless
  in-proc engine with a stable command/event API; the UI layer is the product
  and owns models/panels/state (§5.5/5.6).
- **Unified window**: panels + video composited in one surface (form factor B).
- **Always-on read-only signal monitoring** feeding open-time libav flags, the
  live panel, and a reconnect/session FSM (§5.3/5.4).
- **Low-latency capture** per the verified flag set (§6).
- Branded **animated splash + idle wallpaper** (§5.7) and **first-run
  onboarding** (§5.8).

**Non-goals / out of scope (v1):** recording to disk; network/URL streaming UI;
interactive DVD/BD menus (deferred, API-reserved); re-architecting mpc-hc's
legacy chrome (it stays as a fallback player); DVD/BD **main-feature** playback
is free via LAV and kept.

## 2. Verified stack (all built & green)

| Piece | Where | Verified |
|---|---|---|
| MPC-HC dev build | `C:\Code\mpc-hc\bin\mpc-hc_x64 Lite\mpc-hc64.exe` (Release Lite x64) | ✅ loads registered LAV + MPCVR-Zion |
| LAV Filters (registered) | `C:\Code\LAVFilters\bin_x64\` (+ sidecars) | ✅ decode works in MPC-HC |
| DeckLink-capable FFmpeg | `C:\Code\LAVFilters\bin_x64\avdevice-lav-63.dll` | ✅ built |
| MPCVR-Zion (renderer) | `C:\Code\VideoRenderer` | ✅ loads in MPC-HC |
| DeckLink SDK headers | `C:\Code\LAVFilters\ffmpeg\decklink\` (v12.5.1) | ✅ |
| Signal watchdog | `C:\Code\unplugged\decklink_monitor\decklink_monitor.dll` | ✅ A/B-proven |
| Web server (prototype/protocol seed) | mpc-hc `WebServer.cpp` (JSON endpoints) | ✅ in-tree |
| Engine lift classes | `FGManager.cpp`, `BaseGraph.cpp`, `FGFilter*`, `MediaFormats.*` | ✅ headers UI-free |

## 3. Two application modes

| | **Video Processor (VP)** — ingest | **Media Player** |
|---|---|---|
| Source | DeckLink (`decklink://`) | Local files (DVD/BD main-feature via LAV) |
| Video | decode → MPCVR-Zion | decode → MPCVR-Zion |
| Audio | **not fed to DirectX** — AVR owns it | played via audio renderer |
| Graph | video-only (audio off at source) | full audio+video |
| Reconnect/mode-switch | video-graph-only rebuild | normal restart |

✅ **Mode is mutable at runtime**: chosen on first-run, switchable from the
right rail and the bottom bar's **VP | Media Player** buttons.

## 4. Control topology (form factor B)

```
                        UI LAYER (the product — one window, full-screen)
   ┌──────────────┐  ┌───────────────────────┐  ┌──────────────────────────┐
   │ Left LIVE    │  │ Right rail            │  │ Session FSM + Ingest     │
   │ pane (rows)  │  │ Playback|System>Zion  │  │ Controller (reconnect &  │
   └──────────────┘  │ + bottom bar (VP|Med) │  │ mode-switch, signal host)│
   ┌──────────────┐  └───────────────────────┘  └──────────────────────────┘
   │ Wallpaper +  │        ▲   JSON dialect (command / property / event)
   │ Splash       │        │   MpcPlayer API — in-proc
   └──────────────┘        │
   ┌──────────────┐        ▼
   │ Video surface│   ENGINE SEAM: mpchc_engine (headless, own pump thread)
   │ (MpcRender ) │   ┌─────────────────────────────────────────────┐
   └──────────────┘   │ graph built from FGManager/BaseGraph classes │
        ▲ present     │ Capture Source · LAV Split/Audio/Video ·      │
        └─────────────│ audio renderer (Media) · MPCVR (presenter)    │
                      └─────────────────────────────────────────────┘
```

## 5. Components

### 5.1 Capture source  🟡 new DirectShow filter
`src/filters/DeckLinkCapture/` — DS push-source wrapping LAV avdevice via
`LoadLibrary` (two-libav isolation, §8). Applies the mode-parameterised
open-flag dict. Pushes `AVPacket`→`IMediaSample` out its video pin (VP) or
A/V pins (Media). ❓ DS source filter vs push-source fed by controller thread;
per-mode audio pins.

### 5.2 Signal monitor  ✅ port `decklink_monitor.dll` as-is
Read-only `IDeckLinkStatus` poll while capture holds the device. Host-owned
(UI layer). ❓ always-on when a DeckLink device is configured? (Unplugged polls
pre-capture for live port status in setup and first-run.)

### 5.3 Session FSM (reconnect + mode switch)  🟡 graph-in-place, host-owned
States **IDLE / VP / MEDIA**; transitions for signal drop → re-acquire
(debounce, `restart_cooldown`, `max_restart_attempts`), mode switch
(stop → teardown → build the other graph), and media open/stop. A mode switch
is a reconnect with a different open-flag dict. Lives in the UI layer; speaks
to the engine only through the seam.

### 5.4 Ingest controller  ✅ host-owned
Mode → open-flag dict, capture launch, signal wiring, reconnect, live-panel
push. The renderer never decides anything; the engine never draws anything.

### 5.5 Engine seam — `mpchc_engine`  ✅ v1 shipped (S2, 2026-09-06)
Headless static library in the mpc-hc solution (`src/mpchc_engine/`,
registered under `Libraries` in `mpc-hc.sln`, builds Release/x64 with the
repo props and `MPCHC_WINSDK_VER=10.0.26100.0`). Thin DirectShow controller
informed by `FGManager` patterns — does **not** wholesale-lift `FGManager`
(see S0 findings) — with just enough of the mpc-hc renderer-setup contract
(`IExFilterConfig` flags) for MPCVR to present standalone.

Exposes the **MpcPlayer API** — command/property/event form (mpv-model),
transport-agnostic (in-proc first; the same shape can ride a localhost
socket for the companion remote later):

- **commands** (v1 shipped): `Open`, `Play`, `Pause`, `Stop`, `Seek`,
  `ResizeVideo`, `AttachRenderTarget(HWND)`, `SetRenderer(...)`. Planned:
  tracks, screenshot, `open(decklink://…)` (S4).
- **properties** (v1 shipped): `GetSnapshot` / `SnapshotJson` — state,
  position, duration, source. Planned: volume, rate, streams, HDR/video
  params, signal state, latency.
- **events** (v1 shipped): `SetEventCallback(fn(name, snapshot))` emits
  `opening / opened / state / time / error`. Planned: EOF (from
  `EC_COMPLETE`), signal, HDR, settings-changed.
- **render binding** (v1 shipped): `AttachRenderTarget(HWND)` — the UI
  layer owns the video-host HWND; the engine wires it via
  `IMFVideoDisplayControl::SetVideoWindow`, `IVideoWindow::put_Owner /
  put_WindowStyle / put_MessageDrain`, `IExFilterConfig::Flt_SetBool("less
  Redraws"/"d3dFullscreenControl", true)`, and sizes via
  `SetVideoPosition` + `IBasicVideo::SetDestinationPosition` +
  `IVideoWindow::SetWindowPosition`. Renderer-agnostic:
  `Renderer::Auto | VMR9 | EVR | MPCVR` (VMR9/EVR proved the seam; MPCVR-
  Zion proved the product path). Later: caller-provided D3D11 swapchain,
  the libmpv `mpv_render_context` analog.

Acceptance driver: `tools/engine_s2/s2_driver.cpp` +
`build_s2_driver.bat`. CLI: `s2_driver.exe [--renderer auto|vmr9|evr|mpcvr]
<file>`. Creates a `WS_OVERLAPPEDWINDOW` host, blocking `GetMessage` loop,
`WM_TIMER` auto-stop — user-verified on H.264 SMPTE bars and real content
(`Exodus.mp4`).

API requirements inventory: **Appendix A**. Settings = registry-backed keyed
get/set (same keys as Options/MPCVR page — rail & page cannot drift); each key
typed **live-apply** vs **next-start**.

**Not in S2 yet** (deferred, no current blocker): full MPCVR allocator-
presenter path (aggregation into `CMPCVRAllocatorPresenter` + `ISubRender`/
`ISubRender11` callbacks) for subtitles/OSD — requires linking/lifting
`SubPic` + `VideoRenderers` scaffolding. Play-to-EOF (`EC_COMPLETE`
listener) and property-observe polling on a background thread.

### 5.6 UI layer — the product  🟡 new composite host
Frameless full-screen app (the "PyQt replacement"): composite window with video
sub-rect + panel surfaces. Owns Session FSM, signal monitor, input/IR mapping,
first-run, splash, wallpaper. Panels **drawn here** (native/D2D, optionally
WebView2 surfaces), never pushed into the renderer. Links `mpchc_engine`
in-proc. `mpc-hc.exe` stays as the fallback Media player until the engine
crosses the acceptance checklist (§9 S6).

### 5.7 Splash + wallpaper  🟡 UI-layer
- Splash: Unplugged HTML animation assets via **WebView2** (Win11), static
  fallback.
- Wallpaper: cover-crop brand backdrop painted by the UI layer as layer-0
  (idle/behind video).

### 5.8 First-run onboarding  🟡 UI-layer
Enumerate DeckLink ports (live lock indicators), assign friendly names, choose
mode (Step 1 = mode, Step 2 = input; Unplugged `FirstRunDialog` port).
Persistence: registry `app_mode` + port alias map. ❓ wizard re-runnable? —
Unplugged surfaces input config in Settings.

## 6. Signal → capture flag mapping  (unchanged, verified)

See `DeckLink-Capture-Low-Latency.md`. Open dict per mode+signal: `raw_format`
(1=uyvy422, 2=yuv422p10, 3..5=RGB), `fflags=nobuffer`, `analyzeduration=0`,
`rtbufsize=32M`, `video_pts=wallclock`, `audio_input=<disable>` in VP ❓verify,
color hints → renderer, device URL = friendly-name map.

## 7. Decision record

- **Form factor B** chosen over A (console + mpc-hc window / webserver-as-spine):
  video + panels in ONE window requires in-proc engine + render binding, which
  the webserver model cannot provide.
- **Engine seam `mpchc_engine`** (lib-project) chosen over (a) headless
  `mpc-hc.exe` via IPC — no such surface exists; (b) rewriting MainFrm — no.
- **Webserver** = prototype channel + protocol seed + companion remote.
- **Renderer (MPCVR)** demoted to presenter-only (+ later render binding);
  panel drawing stays out of it.

## 8. Two-libav-in-one-process risk  ❓ must validate

`mpchc_engine` links mpc-hc's internal static FFmpeg for playback; VP capture
loads LAV `avdevice`/`avformat` DLLs. Validate no global-state collisions
(lazy runtime loading, per-instance contexts). Probe during S4 hardware smoke.

## 9. Engineering milestones (dependency-first)

| # | Deliverable | Gate |
|---|---|---|
| **S0** | ✅ **DONE 2026-09-06** — spike driver `tools/engine_spike/` (thin DShow controller, ~130 LOC). open→play→seek proven through LAV Splitter (`extract compiles standalone; hidden deps surfaced` → see §9 findings). | — |
| **S1** | ✅ **DONE 2026-09-06** — rolled into S2 render binding. Standalone spike `tools/engine_spike/s1_windowed.cpp` proved graph + hosting mechanics; visible-video proof achieved via `MpcPlayer::AttachRenderTarget` + MPCVR through the engine seam (`tools/engine_s2/s2_driver.exe`), user-verified on H.264 bars and real content. | B’s premise proven end-to-end; standalone spike superseded. |
| **S2** | ✅ **DONE 2026-09-06** — engine seam v1 shipped: `src/mpchc_engine/` static library + `MpcPlayer` API (command/property/event) + render binding + visible acceptance driver `tools/engine_s2/s2_driver.exe`. Renderer-agnostic (`Auto/VMR9/EVR/MPCVR`); MPCVR-Zion path user-verified. | API round-trip from a driver + visible frames. |
| **S3** | UI shell skeleton: composite host + panels binding S2 | Unplugged layout live against real engine |
| **S4** | VP/capture: DeckLink source, VP graph-build, signal monitor, FSM reconnect + mode switch | hardware smoke + two-libav probe |
| **S5** | Full surfaces: left pane, rail (Playback / System>Zion), bottom bar, first-run, splash/wallpaper | first-run UX complete |
| **S6** | Parity: engine vs mpc-hc.exe acceptance checklist; fallback retirement decision | checkable Go/No-Go |

### S0 findings (2026-09-06, `tools/engine_spike`)
1. **Wholesale cargo-lift of FGManager is a false start**: `FGManager.cpp` pulls
   `MainFrm.h`, `mplayerc.h`, `SyncAllocatorPresenter.h`, `MpcAudioRenderer.h`,
   `DeCSS/VobFile.h` — it's app-entangled, not a clean engine class. The
   engine will be a **thin DShow controller** informed by FGManager *patterns*,
   plus selective lifts (e.g. FakeFilterMapper2/filter-preference) as needed.
2. **The spine works**: `IGraphBuilder::RenderFile` → `IMediaControl/Seeking/
   EventEx` gives play/seek/status in ~130 LOC, through registered LAV Splitter,
   with no mpc-hc code. Position/seek/EC_COMPLETE all verified.
3. **Filter preference must be engine-controlled**: RenderFile picked the MS
   DMO decoder and "Video Renderer", not LAVVideo/MPCVR — the engine will pin
   preferred filters (mpc-hc's FakeFilterMapper2 pattern), which S1 needs for
   MPCVR anyway.

## 10. Scope (v1) — locked at design

**In:** VP DeckLink ingest + signal/reconnect; Media local files (DVD/BD
main-feature via LAV); unified B UI; first-run; splash/wallpaper; rail settings
(Playback + Zion); bottom-bar mode switch.
**Out (deferred):** recording; network/URL surfaces; disc menus (API-reserved);
legacy chrome parity.

## 11. Open questions

- Capture-source shape; per-mode audio pins (§5.1).
- Monitor lifecycle = always-on when device configured? (§5.2)
- VP `audio_input` knob spelling (§6).
- Two-libav isolation probe (§8).
- ~~Render-binding depth v1 — HWND vs swapchain (§5.5).~~ **Resolved
  2026-09-06**: v1 is child HWND via `AttachRenderTarget(HWND)`; D3D11
  swapchain caller-provided path deferred to a later revision.
- Full MPCVR allocator-presenter integration inside `mpchc_engine`
  (aggregation + `ISubRender`/`ISubRender11` callbacks for subtitles/OSD)
  — defer until a product need forces it; basic MPCVR video presentation
  works without it in S2 (§5.5).
- Friendly-name storage; wizard re-runnability (§5.8).
- Mode-switch carryover semantics (what "seamless" means across a switch).

## 12. References
- `C:\Code\mpc-hc\docs\DeckLink-Capture-Low-Latency.md`
- `C:\Code\LAVFilters\build_ffmpeg.sh`
- `C:\Code\unplugged\decklink_monitor\` (`.c`, `build.bat`, dll)
- Unplugged `app/src/mpvprocessor/ui/` (right_panel, status_panel, first_run,
  splash, mode_selector)
- mpc-hc `WebServer.cpp` / `WebClientSocket.cpp` (protocol vocabulary)
- Memory `lav-build-and-mpcvr-tray.md` (build recipes + env quirks)

---

# Appendix A — Engine-Seam API Requirements

Every product interaction is one of three shapes (mpv-model): **command**
(request/response), **property** (get/set/observe), **event** (engine→host
push). Live = applies mid-playback; next-start = registry + rebuild-on-switch.

### A. Lifecycle & setup
- Splash show/dismiss (host-only). First-run: choose mode, enumerate ports,
  assign friendly names (host/monitor). Mode switch VP⇄Media: command `mode`.
- Session init/destroy/idle (engine). Re-run onboarding from Settings (host).

### B. Transport (Media)
- open file/URL; next/prev; play/pause/stop/toggle (cmd, live). Seek absolute
  /relative/frame-step/chapter (cmd, live). time+duration (prop, observe, live).
  rate/speed (prop, live). EOF/error/state (event). repeat/shuffle (prop, live).

### C. Media structure & streams
- stream lists + current (prop observe). audio track select + audio-delay
  (prop, live). subtitle track select + subtitle-delay + off/forced (prop,
  live). chapters list+jump (cmd/prop). media info/title (prop).

### D. Audio output
- volume/mute/balance (prop, live). audio device / bitstream passthrough
  (prop, next-start). default device (next-start). VP: no surface (audio never
  enters graph).

### E. Video/picture
- aspect/zoom/pan (prop, live). rotation (prop, live). screenshot (cmd, live).
  fullscreen/windowed/exclusive (prop, live). video params + HDR metadata
  (prop observe).

### F. DeckLink / VP
- open/close capture; device/port enumeration (prop). live status: lock,
  format, DR, depth/chroma, latency (prop observe). reconnect policy
  (prop, next-start). hold/warm-up at acquire (prop/event, live). ingest
  screenshot (cmd). monitoring AR/zoom (prop).

### G. Renderer — all MPCVR (+Zion) settings  *(keyed settings schema)*
- tone-mapping, deband, dither, scaling, colors, gamut, device/format, present/
  exclusive, OSD/stats (keyed get/set; next-start unless MPCVR live-applies).
- Zion: model path, per-feature enables, profiles (keyed, next-start; existing
  registry keys reused so rail & property page can't drift).

### H. Telemetry/status → host (events + observable props)
- state, position tick, streams, HDR, signal, latency, errors, heartbeat.

### I. Persistence/system
- settings load/save (registry, same keys as today); per-instance overrides;
  logging; error surfacing.
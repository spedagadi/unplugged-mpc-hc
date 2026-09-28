#pragma once

#include <atomic>
#include <atlbase.h>
#include <condition_variable>
#include <dshow.h>

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include "DeckLinkSourceControl.h"
#include "DeckLinkMonitor.h"   // measures the wire — publishes settled facts only
#include "IngestController.h"  // the single ingestion decider — facts in, intent out

class MpcPlayer final {
public:
    enum class State {
        Idle,
        Opening,
        Paused,
        Playing,
        Stopped,
        Ended,
        Error,
    };

    enum class Renderer {
        Auto,
        VMR9,
        EVR,
        MPCVR,
    };

    enum class TrackKind {
        Video,
        Audio,
        Subtitle,
    };

    enum class AudioMode {
        PCM,
        Bitstream,
    };

    struct BitstreamConfig {
        bool ac3 = true;          // HTPC: bitstream is the default, all HD codecs on
        bool eac3 = true;
        bool trueHd = true;
        bool dts = true;
        bool dtsHd = true;
        bool dtsHdFraming = true;
    };

    struct Snapshot {
        State state = State::Idle;
        LONGLONG position = 0;
        LONGLONG duration = 0;
        int volume = 100;
        bool muted = false;
        std::wstring source;
    };

    struct TrackInfo {
        TrackKind kind = TrackKind::Video;
        std::wstring name;
        std::wstring lang;    // human language from the stream LCID ("" if none)
        std::wstring codec;   // friendly codec ("E-AC-3", "TrueHD", …) from the subtype
        bool active = false;
    };

    struct AudioDeviceInfo {
        std::wstring name;
        std::wstring id;
        bool isDefault = false;
    };

    // Mirrors the ML fields of the MPCVR-Zion Settings_t (IVideoRenderer.h).
    struct MlSettings {
        bool  enable = false;
        int   mode = 0;                    // 0=Disable, 1=Manual, 2=Auto
        bool  toneCurveEnabled = true;
        bool  gammaEnabled = true;
        float gamma = 1.0f;                // [0.5, 1.5]
        bool  shadowEnabled = true;
        float shadow = 2.0f;               // strength tier: 0=Off 1=Low 2=Med 3=High 4=VHi 5=Saturate
        float shadowDehaze = 0.0f;       // 0..1 scale-down of the model shadow-toe lift (lifted-black haze control)
        float highlightRolloffCtrl = 0.0f; // signed offset on the model's rolloff in Auto (rim highlight softening); 0 = model as-is
        float gammaTopUp = 0.0f;           // signed offset ADDED to the model's gamma in Auto (midtone lift); 0 = model as-is
        bool  highlightEnabled = true;
        float highlight = 0.0f;            // [-0.3, 0.4]
        bool  chromaEnabled = true;
        bool  huntEnabled = true;
        float hunt = 0.80f;
        bool  chNeutralEnabled = true;
        float chNeutral = 1.20f;
        bool  chFireEnabled = true;
        float chFire = 1.35f;
        bool  chKneeEnabled = true;
        float chKnee = 0.55f;
        bool  chSkinEnabled = true;
        float chSkin = 0.95f;
        bool  debugLog = false;
        bool  debugCopy = false;
        bool  shadowDebugVis = false;  // heatmap overlay showing shadow enhancement zones
        float shadowZoneCeil = 0.20f;
        float shadowSkinProtect = 1.0f;
        float shadowRatioCap = 1.40f;
        bool  contrastEnabled = true;
        float contrast = 0.15f; // micro-contrast clarity strength [0, 0.5]
        float contrastZoneLo = 0.15f;
        float contrastSkinProtect = 0.65f;  // MC damping on person-skin (stage 4)
        float contrastRatioCap = 1.40f;
        bool  contrastDebugVis = false;
        bool  skyEnabled = false;      // sky semantic segmentation (stage-2 overlay) — default OFF
        bool  skyDebugVis = false;     // cyan sky-mask overlay for validation
        float skyStrength = 0.6f;      // sky tone-leg blend amount [0, 1]
        bool  personEnabled = false;   // person skin protection (default OFF; enable when validated)
        float personStrength = 1.0f;   // LUT-only-inside-people gate [0,1]; 0 = legacy
        bool  personOverlay = false;   // magenta person-mask overlay (validation)
        float skinPreserve = 0.0f;     // stage-5 skin tone (default OFF)
        bool  faceProtectEnabled = true;
        float faceStrength = 0.80f;    // face gamma protection [0,1]
        float faceFeather = 0.04f;     // SDF feather width in UV
        float faceExpand = 1.50f;      // box expansion factor
        bool  faceDebugVis = false;    // red rectangle overlay on detected faces
        bool  barsEnabled = true;      // P0: repaint detected letterbox bars to black
        bool  barsHighlight = false;   // P0: red-rect debug overlay on detected bars
        uint32_t configSeq = 0;        // monotonic config-change counter for diagnostics
    };

    struct HdrSettings {
        // Consume a Dolby Vision RPU whenever one is present, preferring it over
        // HDR10 static metadata. Default true (PotPlayer parity): the renderer's
        // DV-ingest gate is `m_bHdrPreferDoVi || !SourceIsHDR10orHLG()`, and a DV
        // Profile 5 file is tagged PQ so SourceIsHDR10orHLG() is true — the gate
        // only opens through the first term. For a Profile 5 (IPTPQc2) source the
        // RPU is the ONLY thing that yields correct colour, so the default has to
        // be true. For non-DV sources it is inert (the side-data GetSideData fails).
        bool preferDoVi = true;
        bool convertToSdr = true;
        int  sdrDisplayNits = 50;
        int  toggleDisplay = 0;            // HDRTD_Disabled..HDRTD_OnOff
        int  displayMaxNits = 1000;
        // Display BLACK in nits (measured; e.g. 0.16 for a projector at bb1.0).
        // The tone mapper builds its destination range as [min, max] — without
        // this it assumes the display's black is absolute zero. 0.0 = previous
        // behaviour. Float because sub-1-nit blacks are the norm.
        float displayMinNits = 0.0f;
        // Tone-mapped SDR output gamut: 0 = BT.709 (standard), 1 = keep BT.2020
        // for a display whose gamut exceeds Rec.709.
        int  outputGamut = 0;
        // The CONTENT's peak luminance, nits — the top of the range the tone curves
        // map FROM. Distinct from displayMaxNits, which is the DISPLAY's peak.
        //
        // Without it the scene-referred curves (ACES/Reinhard/Mobius/BT.2390)
        // normalise by a fixed 1000-nit guess, and a range several times larger than
        // the content makes those curves render far too dark.
        //
        // On the DeckLink capture path this is now driven by the SIGNAL. The card
        // does report ST 2086 (MaxCLL) over HDMI — the old "unsupported" note was a
        // bug in how we read it, not a limit of the card. RefreshLive pushes the
        // card's MaxCLL here whenever one is present, so this default only applies
        // before the first read, or on a signal carrying no static metadata at all
        // (DV, SDR). The panel's Title peak row is the fallback for exactly those.
        float titlePeakNits = 1000.0f;
        // Hable knee: display-relative light below which Hable is replaced by
        // identity. 0 = pure Hable (the previous behaviour, exactly).
        float hableKnee = 0.0f;
    // Soft-plus pre-compressor on the Hable path. knee <= 0 = off (identical to
    // before it existed); knee/width are display-relative (1.0 = display white).
    // Soft-knee pre-compressor. The LOW knee (0.21) is deliberate and is the default
    // for all content: ultra-bright DV/HDR masters (e.g. Furiosa) need compression to
    // start early or the sky/cloud band clips and loses clarity. It is safe at a low
    // knee because the compressor is detail-preserving (it compresses a local base
    // and restores the per-pixel residual), so mid-tone texture no longer collapses
    // into 8-bit "oil-painting" patches the way the old pointwise form did at ratio>1.
    float softKnee      = 0.21f;
    float softKneeRatio = 2.48f;
    float softKneeWidth = 0.42f;
    // The Hable curve's 1.0 in nits, decoupled from display white. 203 = libplacebo's
    // SDR diffuse white (clouds are content below that), 0 = sdrNits (legacy).
    float refWhiteNits  = 203.0f;
    float highlightNeutral = 0.9f;   // 0..1: PQ->SDR head pulls toward neutral
    float chromaExp = 1.35f;         // STAGE 1 delivery-only: value carried, not applied
    // GT7 operator (toneMapCurve 8). Defaults are Polyphony's own constants; the
    // curve's shape parameters are NOT exposed because they are what make it GT7.
    //   gt7Blend: 0 = raw per-channel "skewed" curve, 1 = luminance from that pass
    //   with chroma from the original colour. The hue dial.
    //   gt7Fade*: the chroma fade window, in units of the ceiling's ICtCp I (PQ
    //   codes, so the window sits far lower in nits than the numbers suggest).
    // Read when curve 8 (GT7) or 10 (GT7 Adapt) is selected; softKnee* is reused as
    // GT7's pre-fit. gt7Adapt is Adapt's only extra input: how much of the peak the
    // curve maps FROM comes from the measured scene peak instead of static metadata.
    // 0 = identical to plain GT7, 1 = scene peak alone. See TONE_CURVE_GT7_ADAPT.
    float gt7Blend     = 0.6f;
    float gt7FadeStart = 0.98f;
    float gt7FadeEnd   = 1.16f;
    float gt7Adapt     = 0.25f;
        int  osdBrightness = 0;
        int  toneMapCurve = 5;             // 1=ACES 2=Reinhard 3=Hable 4=Mobius 5=BT.2390 7=Reference 8=GT7 9=Spline 10=GT7 Adapt
        bool hdrPassthroughRaw = false;    // demo: show raw HDR/DV on SDR
        // Experimental tone mapping (libplacebo port). A separate axis from the
        // shipped tone mapping: 0 leaves every existing curve untouched, which is
        // what makes it safe to A/B against the current picture on a calibrated
        // display. 0 = off, 1 = libplacebo spline.
        int   experimentalToneMapper = 0;
        // pl_tone_map_spline "Contrast": higher is steeper (closer to clip).
        // 0.00 .. 1.50, default 0.50.
        float toneLutContrast = 0.50f;
        // Spline shadow-pivot scale (litmus dial for the spline's black floor):
        // scales the scene average that drives the spline's knee/pivot. 1.0 =
        // libplacebo as-is; lower = deeper blacks. 0.00 .. 1.00.
        float toneLutPivotScale = 1.0f;
    };

    struct OutSettings {
        bool useD3D11 = true;
        int  texFormat = 0;                // 0/8/10/16
        bool vpNV12 = true;
        bool vpP01x = true;
        bool vpYUY2 = true;
        bool vpOther = true;
        int  deinterlace = 1;              // 0/1/2
        bool deintDouble = true;
        bool deintBlend = false;
        bool shaderVPScaling = true;
        int  superRes = 0;
        bool rtxVideoHdr = false;
        int  chromaScaling = 1;
        int  upscaling = 2;
        int  downscaling = 2;
        bool interpolate50 = true;
        bool useDither = true;
        int  swapEffect = 1;
        bool exclusiveFS = false;
        bool vBlank = false;
        bool adjustPresent = true;
        bool reinitDisplay = false;
        bool showStats = false;
        bool trayIcon = true;
    };

    // Post-render effects delivered as MPCVR post-scale custom shaders (see
    // PostFxShaders.h). NOT part of Settings_t — they reach the renderer through
    // IExFilterConfig, so this crosses no binary boundary with the .ax. Defaults
    // are conservative for film (the shader authors' values were game-tuned).
    struct PostFxState {
        bool  sharpenEnabled   = false;
        float sharpenStrength  = 1.0f;   // Adaptive Sharpen curve_height, 0.3..1.5
        bool  debandEnabled    = false;
        float debandThreshold  = 32.0f;  // cut-off; higher = stronger, eats detail
        float debandRange      = 16.0f;  // initial radius (px), grows per iteration
        int   debandIterations = 1;      // 1..4 (>4 useless)
        float debandGrain      = 24.0f;  // dither added over residual bands
    };

    using EventCallback = std::function<void(std::string_view eventName, const Snapshot&)>;
    using LogSink = std::function<void(const char*)>;

    void SetLogSink(LogSink sink) { logSink_ = std::move(sink); }

    MpcPlayer();
    ~MpcPlayer();

    MpcPlayer(const MpcPlayer&) = delete;
    MpcPlayer& operator=(const MpcPlayer&) = delete;

    // Setup
    HRESULT SetEventCallback(EventCallback);
    HRESULT AttachRenderTarget(HWND);
    HRESULT SetRenderer(Renderer);

    // Transport
    HRESULT Open(std::wstring_view source);
    HRESULT Play();
    HRESULT Pause();
    HRESULT Stop();
    HRESULT Seek(LONGLONG position);
    HRESULT ResizeVideo();

    // Full teardown for app exit (DESIGN.md ordered script): stop the capture
    // feeder at the SDK, disconnect, join the source threads, THEN stop the
    // graph — otherwise mediaControl_->Stop() waits forever on a decklink
    // source that keeps delivering into the renderer (observed: window closes
    // but the process survives as a zombie, capture still running). Also stops
    // the monitor and the ops-queue executor. Idempotent.
    void Shutdown();

    // Audio / volume
    HRESULT SetVolume(int percent);
    HRESULT SetMuted(bool);
    HRESULT SetAudioEnabled(bool);
    HRESULT GetAudioEnabled(bool&) const;
    HRESULT SetAudioMode(AudioMode);
    HRESULT GetAudioMode(AudioMode&) const;
    HRESULT SetBitstreamConfig(const BitstreamConfig&);
    HRESULT GetBitstreamConfig(BitstreamConfig&) const;

    // Streams
    HRESULT GetTracks(std::vector<TrackInfo>&) const;
    HRESULT SetAudioTrack(int posIndex);
    HRESULT SetSubtitleTrack(int posIndex);

    // Audio endpoints. GetAudioDevices enumerates WASAPI render endpoints;
    // SetAudioDevice routes playback to one of them (through MpcAudioRenderer
    // when it is registered; otherwise the DSound fallback keeps the default).
    HRESULT GetAudioDevices(std::vector<AudioDeviceInfo>&) const;
    HRESULT SetAudioDevice(const std::wstring& endpointId, const std::wstring& endpointName);
    HRESULT GetAudioDevice(std::wstring& endpointId, std::wstring& endpointName) const;

    // MPCVR-Zion bridges
    HRESULT SetMlSettings(const MlSettings&);
    HRESULT GetMlSettings(MlSettings&) const;
    HRESULT SetHdrSettings(const HdrSettings&);
    HRESULT GetHdrSettings(HdrSettings&) const;
    HRESULT SetOutSettings(const OutSettings&);
    HRESULT GetOutSettings(OutSettings&) const;
    HRESULT GetProcessorInfo(std::wstring&) const;

    // Write the renderer's live settings back to MPCVR's own registry key
    // (HKCU\Software\MPC-BE Filters\MPC Video Renderer).
    //
    // IVideoRenderer::SetSettings applies LIVE ONLY — it never persists. A graph
    // rebuild (the decklink monitor self-heals on any signal change) constructs
    // a fresh MPCVR whose constructor re-reads that key, so without this call
    // every pushed setting is silently discarded and whatever was last stored
    // there wins instead. That made the same toggle appear to work one day and
    // do nothing the next.
    HRESULT SaveRendererSettings();
    // The user's settings INTENT, independent of whether a graph exists. A push
    // that arrives before the renderer does is remembered here and applied when
    // the graph is built, instead of being dropped (old behaviour: dropped, but the
    // caller still got S_OK). Settings that shape media-type negotiation — above
    // all bConvertToSdr, which picks which converter shader is built — must be in
    // place BEFORE the pins connect, or they do not take until something else
    // forces a rebuild, which reads as "the control works sometimes".
    HdrSettings pendingHdr_{};
    MlSettings  pendingMl_{};
    OutSettings pendingOut_{};
    PostFxState pendingPostFx_{};
    bool hasHdr_ = false, hasMl_ = false, hasOut_ = false, hasPostFx_ = false;
    void ApplyPendingSettings();

    // Cached audio status for the UI: a `,"audio":{"mode":N,"tracks":[…]}` JSON
    // fragment, rebuilt on graph-safe threads (end of BuildGraph, after a track
    // select) — never read from the poll worker, which must not touch the graph.
    std::string m_audioJson;
    int m_audioTrackCount = 0;   // audio tracks in m_audioJson; 0 → retry on the live tick
    void RebuildAudioJson();

    // Inject (or clear+re-inject) the post-scale post-fx shaders through
    // IExFilterConfig. Idempotent: it re-injects only when the generated source
    // changed or the renderer instance is new (graphGen_ moved), so an unrelated
    // settings push or a live tick does not trigger a recompile.
    void ApplyPostFx();
    std::string m_lastSharpenSrc, m_lastDebandSrc;   // dedup cache
    unsigned    m_postFxGraphGen = 0xFFFFFFFF;        // graph generation last injected on
    // Write the frame the renderer is currently producing to a 32-bit BMP.
    // Goes through the real pipeline, so an A/B of two settings is a byte
    // comparison rather than a memory of what the picture looked like.
    HRESULT GrabFrame(const std::string& utf8Path);

    // Display calibration 3D LUT (.cube). An empty path unloads.
    // Sent as an IExFilterConfig BIN command rather than a Settings_t field, so
    // the struct never has to carry a path across the COM boundary.
    // mode: 0 = off, 1 = gamma only, 2 = greyscale, 3 = full 3D (default).
    HRESULT LoadCubeLut(const std::string& utf8Path, int mode = 3);
    HRESULT GetMlStats(std::wstring&) const;

    // Renderer frame accounting (LIVE panel / PERFORMANCE / RENDERER OUT):
    // receive-side frame counts + dropped/skipped/failed tallies.
    struct RenderStats {
        unsigned framesReceived = 0;   // total input frames seen by the renderer
        unsigned framesDrawn = 0;      // frames actually presented
        unsigned dropped = 0;          // receive-side drops
        unsigned skipped = 0;          // double-rate skip path
        unsigned failed = 0;           // render failures
        double   drawFps = 0.0;        // presented frames per second (measured)
        double   presentLatencyMs = 0; // on-screen frame's lag vs capture time
    };
    HRESULT GetRendererStats(RenderStats&) const;

    // DeckLink HDMI capture (live input via LAVSplitterSource + decklink:// URL)
    // Video-only: no audio is ingested (HDMI audio routes to the AVR separately).
    struct VideoStreamInfo {   // what the demuxer handed out (LIVE panel / DEMUXER → REC)
        bool valid = false;
        int  width = 0, height = 0;
        int  avgTimePerFrame100ns = 0;                 // 100 ns units; 0 = unknown
        int  pixelFormat = 0;                          // 0=UYVY 1=v210 2=NV12 3=other
        bool interlaced = false;
        int  transferFunction = 0;                     // DXVA2_ExtendedFormat transfer (0=Unknown, 15=PQ/2084, 16=HLG, ...)
        int  colorspace = 0;                           // 0=unknown 1=BT.601 2=BT.709 3=BT.2020 (primaries)
        bool hdr = false;                              // transfer is PQ(2084)/HLG → HDR source
        std::wstring subtypeName;                      // e.g. "UYVY", "P010"
    };

    struct DecklinkSettings {
        int  inputColorSpace = 0;   // ICS_Auto / ICS_BT601 / ICS_BT709 / ICS_BT2020_* (IVideoRenderer.h)
        bool videoOnly = true;      // always true for now (no audio ingest)
        int  lastMode = 0;          // last BMDDisplayMode fourcc observed
        int  lastColorSpace = -1;   // 0=601 1=709 2=2020
        int  lastDynamicRange = -1; // 0=SDR 1=PQ 2=HLG
        bool signalLocked = false;
    };
    // The ONLY way ingestion changes state. Called by the IngestController with
    // its decision; queues an op for the executor, which is the only thing that
    // creates or destroys a graph. Non-blocking, coalescing (latest wins).
    void HandleIngestDecision(const IngestController::Decision& d);
    // Delivery-stall monitor ("ingested vs displayed"): called from RefreshLive's
    // snapshot tick with the filter's counters. Posts a Reload only for the
    // stale-media-type signature (arrived advancing, delivered frozen, gate
    // climbing) — see the implementation for why that is the safe discriminator.
    void CheckDeliveryStall(const DeckLinkSourceStats& dl, const RenderStats& r);
    void CheckSourceFormatChange(const DeckLinkSourceStats& dl);
    void RequestDecklinkReload(const char* why);   // post a Reload, logged with the reason
    HRESULT SetDecklinkCapture(const std::wstring& deviceName); // start the monitor + decider
    HRESULT StopDecklinkCapture();                              // stop the signal monitor
    HRESULT SetDecklinkInputColor(int ics);
    // Derive the input colour space from the negotiated media type (authoritative)
    // and push it. Called at the end of BuildGraph, once videoStreamInfo_ is
    // populated, so it overrides the monitor's colours-space-first guess.
    int  IcsFromMediaType() const;
    void ApplyIcsFromMediaType();                     // push ICS override to the renderer
    void SetDecklinkDevice(const std::wstring& deviceName) { decklinkDevice_ = deviceName; }
    // List DeckLink capture devices (UTF-8 names, one per HDMI input), used to
    // wire VP -> HDMI when no device was passed on the CLI.
    int  GetDecklinkDevices(std::vector<std::string>& names) const;
    // Latest signal snapshot (CAPTURE INPUT / LIVE panel) from the monitor.
    bool GetDecklinkSignalInfo(int& locked, int& colorspace, int& dynamicRange,
                               int& depth, int& chroma, int& w, int& h,
                               int& fpsNum, int& fpsDen, int& interlace) const;
    const std::wstring& DecklinkUrlForRestart() const { return pendingDecklinkUrl_; }
    const DecklinkSettings& GetDecklinkSettings() const { return decklinkSettings_; }
    const VideoStreamInfo& GetVideoStreamInfo() const { return videoStreamInfo_; }
    DecklinkSettings& DecklinkState() { return decklinkSettings_; }
    // Live ingest snapshot from the direct DeckLinkSource filter (LIVE panel).
    // False when no direct capture session is attached (e.g. LAV fallback).
    bool GetDeckLinkSourceStats(DeckLinkSourceStats& out) const;

    // Live telemetry cache (LIVE panel). A dedicated refresh worker (engine
    // thread, ~1 s cadence) snapshots the renderer/filter stats — the UI must
    // NEVER read the renderer itself: a read landing on the UI tick during an
    // HDMI blip freezes the app (observed). UI uses only these cache getters.
    void RefreshLive();
    bool GetLiveRendererStats(RenderStats& o) const;
    bool GetLiveMlStats(std::wstring& o) const;
    bool GetLiveMlSettings(MlSettings& o) const;
    bool GetLiveHdrSettings(HdrSettings& o) const;
    bool GetLiveOutSettings(OutSettings& o) const;
    bool GetLiveDeckLinkSourceStats(DeckLinkSourceStats& o) const;

    // Snapshot / events
    HRESULT PumpEvents();
    HRESULT GetSnapshot(Snapshot&) const;
    std::string SnapshotJson() const;

    // Compact JSON blob for the (PyQt) client UI: state + render + decklink +
    // signal + media type + key settings, all from the thread-safe live cache.
    // This is the polling contract for engine_bridge.py — the UI never talks
    // direct COM/DS.
    std::string GetUiStatusJson() const;

    // P2 settings protocol: apply "grp.name=value" pairs (semicolon-separated),
    // e.g. "hdr.sdrNits=204;ml.gamma=1.1;out.dither=0". Groups: hdr / ml / out.
    // Each value is parsed by the target field's type and written through to
    // MPCVR live via the matching Set*Settings. Returns S_OK once all sets are
    // applied (unknown names are skipped, never fatal).
    HRESULT ApplySettingsFlat(const std::vector<std::string>& sets);

private:
    HRESULT BuildGraph(std::wstring_view source);
    // DeckLink lifecycle ops — ONE executor thread owns every card+graph
    // mutation (DESIGN.md ordered teardown). All initiators post here; nothing
    // else ever calls Open/Stop for the capture path.
    void RunDecklinkRebuild();          // executor: ordered teardown + relaunch
    // The ordered teardown (DESIGN.md), extracted so the Stop path and the
    // rebuild path cannot drift apart. Executor only, under m_graphMtx.
    void TeardownDecklinkGraph();
    void DecklinkOpLoop();              // executor thread body
    void DisconnectDecklinkPins();      // source-out <-> renderer-in, before any join
    HRESULT AddRenderer(CComPtr<IBaseFilter>&);
    HRESULT ConfigureRendererWindow();
    HRESULT ConnectVideoPin(IBaseFilter* source, IPin* decIn); // try-connect over output pins
    void    CaptureSourceMediaType(IPin* srcPin); // record demuxer media type → LIVE panel
    void    ApplyDecklinkColorToRenderer(); // push ICS override pre-connect
    void    ApplyDecklinkLowLatency(IBaseFilter* splitter); // shrink LAV output queue for live capture
    void    ApplyMediaColorToRenderer(IPin* decOut); // push ICS override from the decoded media type (HDR files)
    HRESULT ConnectAudio(IBaseFilter* splitter);
    HRESULT ApplyVolume();
    HRESULT ApplyBitstreamConfig();   // LAV Audio passthrough config
    HRESULT ApplyRendererConfig();    // MpcAudioRenderer mode + device
    HRESULT SelectStream(TrackKind kind, int posIndex);
    HRESULT Notify(std::string_view eventName);
    HRESULT UpdateSnapshot() const;
    static void __cdecl DeckLinkSourceLogBridge(void* ctx, const char* line);
    void UpdateIcsFromFilter();      // filter cs/eotf → ICS override state (pre-connect)
    // The settings-apply work item the UI queues instead of writing the renderer
    // itself. Runs on the executor, i.e. serialized against graph mutation.
    void QueueSettingsApply();   // any thread: remember + queue, never writes
    void ApplySettingsOp();      // executor only, under m_graphMtx
    // A settings change that only a REBUILD can deliver safely: posted as a
    // Reload, so BuildGraph applies it pre-connect. See ApplyPendingSettings.
    void RequestSettingsRebuild();
    // True only for the duration of BuildGraph's own ApplyPendingSettings call,
    // where the graph is not yet connected and every field is safe to push.
    bool m_inGraphBuild = false;

    CComPtr<IGraphBuilder> graph_;
    CComPtr<IMediaControl> mediaControl_;
    CComPtr<IMediaSeeking> mediaSeeking_;
    CComPtr<IMediaEventEx> mediaEvent_;
    CComPtr<IBaseFilter> splitter_;
    CComPtr<IBaseFilter> renderer_;
    CComPtr<IBaseFilter> audioDecoder_;
    CComPtr<IBaseFilter> audioRenderer_;
    EventCallback eventCallback_;
    HWND renderTarget_ = nullptr;
    Renderer rendererKind_ = Renderer::Auto;
    int volumePercent_ = 100;
    bool muted_ = false;
    bool audioEnabled_ = true;
    AudioMode audioMode_ = AudioMode::Bitstream;   // HTPC: bitstream by default
    BitstreamConfig bitstream_;
    std::wstring audioDeviceId_, audioDeviceName_;
    bool audioRendererIsMpcAudio_ = false;   // true when MpcAudioRenderer won the CoCreate
    // Bumped on every graph build. A new generation means a NEW MPCVR instance
    // that re-read the registry, so the UI must re-push its settings — exposed
    // as "gen" in GetUiStatusJson for exactly that.
    uint32_t graphGen_ = 0;
    std::wstring decklinkDevice_;
    DecklinkSettings decklinkSettings_;
    VideoStreamInfo videoStreamInfo_;        // captured at graph connect (DEMUXER → REC)
    CComPtr<IDeckLinkSourceControl> decklinkControl_;  // current direct filter (retired on rebuild)
    std::wstring decklinkUrl_;               // source the decklink graph was opened with
    std::wstring pendingDecklinkUrl_;        // latest monitor-advised URL (shell → restart)
    // The previous capture session, released by the executor at the next teardown
    // (see TeardownDecklinkGraph step 5/5). Replaces the detached retire thread.
    CComPtr<IDeckLinkSourceControl> m_retiredControl;
    std::unique_ptr<DeckLinkMonitor> decklinkMonitor_;   // MEASURES the wire — decides nothing
    // The single ingestion decider: consumes settled facts, emits intents.
    // It holds no graph and cannot act — see IngestController.h.
    std::unique_ptr<IngestController> ingest_;
    // Ops queue (the executor): the ONLY thing that mutates card + graph.
    std::mutex              m_gopMtx;
    std::condition_variable m_gopCv;
    std::wstring            m_gopUrl;      // target URL carried by the pending op
    IngestController::Intent m_gopIntent = IngestController::Intent::None;
    bool                    m_gopQueued = false;        // a graph op is pending
    // A settings-apply op, tracked separately from the graph op so a settings
    // push is never lost by coalescing against a rebuild. Serviced by the same
    // executor thread, which is what serializes it against graph mutation.
    bool                    m_gopApplyQueued = false;
    bool                    m_gopStop = false;
    std::thread             m_gopThread;
    // Delivery-stall state (CheckDeliveryStall) — live-tick only.
    unsigned long long m_stallLastDelv    = 0;
    unsigned long long m_stallLastArrived = 0;
    unsigned long long m_stallLastGate    = 0;
    unsigned long long m_stallLastDrawn   = 0;   // renderer "displayed" counter
    unsigned long long m_stallLastRecv    = 0;   // renderer "received" counter
    int                m_stallTicks       = 0;
    // A held-back (renegotiation-shaping) setting in Media mode has no executor to
    // rebuild onto, so the live tick re-opens the current source to apply it
    // pre-connect — the tone-curve row bug on files.
    bool m_fileRebuildPending = false;
    // Source-format change state (CheckSourceFormatChange): the SOURCE filter is
    // the dimension measurer (the monitor DLL reports none); dims settling for 2 s
    // and differing from the committed format → the decider asks for a Reload.
    int m_srcCommittedW = 0, m_srcCommittedH = 0, m_srcCommittedN = 0, m_srcCommittedD = 0;
    int m_srcChangeTicks = 0;
    // Serializes every graph-mutating call (Open/Stop/Play/Seek + the restart
    // worker) so no two threads touch the graph — the minimal-threading rule.
    // Recursive: the restart worker calls the public API under the same lock.
    std::recursive_mutex m_graphMtx;
    // Live telemetry cache + its refresh worker (UI must not touch the renderer).
    mutable std::mutex m_liveMtx;
    RenderStats           m_liveRender{};
    std::wstring          m_liveMl;
    MlSettings            m_liveMlS{};
    HdrSettings           m_liveHdr{};
    OutSettings           m_liveOut{};
    DeckLinkSourceStats   m_liveDl{};
    // Renderer-reported transfer/primaries (parsed from the pipeline readout in
    // RefreshLive). The pin media type often carries NO color info on file paths
    // (flags=0), while the renderer knows the truth from the decoded stream —
    // this is the fallback that fills the panel's Transfer/Primaries/HDR rows.
    int m_liveRenderTf   = 0;
    int m_liveRenderPrim = 0;
    // Whether the renderer consumed a Dolby Vision RPU (m_Dovi.bValid) on this
    // source — parsed from the pipeline dump's dovi= token. A DV Profile 5 file
    // carries no colour description in its VUI, so the panel's tf=/prim= rows read
    // "PQ / BT.2020" — technically what the base layer is ANNOTATED as after the
    // decoder's promotion — while the real EOTF is IPTPQc2 reshaped by the RPU.
    // The panel labels the signal "Dolby Vision" from this flag, not from tf.
    int m_liveDovi = 0;
    // The file's own ST 2086 (MaxCLL/MaxFALL / mastering max/min) as the
    // RENDERER read it from the decoded sample side data (its m_lastHdr10.hdr10)
    // — parsed from the pipeline dump's cll=/fall=/mmax=/mmin= tokens in
    // RefreshLive. Feeds the panel's MaxCLL/MaxFALL/Mastering rows on the file
    // path, where the DeckLink dl.* values (which also drive those rows on the
    // capture path) are always zero.
    int m_liveMdrCll  = 0;   // MaxContentLightLevel, cd/m²
    int m_liveMdrFall = 0;   // MaxFrameAverageLightLevel, cd/m²
    int m_liveMdrMmax = 0;   // MaxMasteringLuminance, cd/m²
    int m_liveMdrMmin = 0;   // MinMasteringLuminance, 0.0001 cd/m² (DXGI_HDR_METADATA scale)
    std::atomic<bool>     m_liveStop{ false };
    std::atomic<bool>     m_liveReady{ false };   // graph exists — safe to touch the renderer
    std::thread           m_liveThread;
    LogSink logSink_;
    void Log(const char* fmt, ...) const;    // routes to logSink_
    mutable Snapshot snapshot_;
};

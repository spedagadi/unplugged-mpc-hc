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
#include "DeckLinkMonitor.h"   // signal monitor — the ingest-change MASTER (DESIGN.md)

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
        bool preferDoVi = false;
        bool convertToSdr = true;
        int  sdrDisplayNits = 50;
        int  toggleDisplay = 0;            // HDRTD_Disabled..HDRTD_OnOff
        int  displayMaxNits = 1000;
        int  osdBrightness = 0;
        int  toneMapCurve = 5;             // 1=ACES 2=Reinhard 3=Hable 4=Mobius 5=BT.2390
        bool hdrPassthroughRaw = false;    // demo: show raw HDR/DV on SDR
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
    // Post a DeckLink rebuild to the single ops-queue executor (non-blocking,
    // coalescing). The monitor, the filter restart callback, and the shell call
    // THIS instead of Open() — the executor is the only graph owner.
    void PostDecklinkRebuild();
    HRESULT SetDecklinkCapture(const std::wstring& deviceName); // start the signal monitor (MASTER)
    HRESULT StopDecklinkCapture();                              // stop the signal monitor
    HRESULT SetDecklinkInputColor(int ics);                     // push ICS override to the renderer
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
    static void __cdecl DeckLinkRestartBridge(void* ctx);
    void RequestDecklinkRestart();   // filter format-change → guarded graceful rebuild
    void UpdateIcsFromFilter();      // filter cs/eotf → ICS override state (pre-connect)

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
    std::wstring decklinkDevice_;
    DecklinkSettings decklinkSettings_;
    VideoStreamInfo videoStreamInfo_;        // captured at graph connect (DEMUXER → REC)
    CComPtr<IDeckLinkSourceControl> decklinkControl_;  // current direct filter (retired on rebuild)
    std::wstring decklinkUrl_;               // source the decklink graph was opened with
    std::wstring pendingDecklinkUrl_;        // latest monitor-advised URL (shell → restart)
    std::unique_ptr<DeckLinkMonitor> decklinkMonitor_;   // the signal MASTER
    // Ops queue (the executor): all rebuilds funnel through here.
    std::mutex              m_gopMtx;
    std::condition_variable m_gopCv;
    std::wstring            m_gopUrl;      // target URL carried by the pending op
    bool                    m_gopQueued = false;
    bool                    m_gopStop = false;
    std::thread             m_gopThread;
    // Serializes every graph-mutating call (Open/Stop/Play/Seek + the restart
    // worker) so no two threads touch the graph — the minimal-threading rule.
    // Recursive: the restart worker calls the public API under the same lock.
    std::recursive_mutex m_graphMtx;
    std::atomic<bool> m_restartPending { false };   // one restart at a time
    unsigned long long m_lastDlvSnapshot = 0;       // delivered counter at last restart decision
    // Live telemetry cache + its refresh worker (UI must not touch the renderer).
    mutable std::mutex m_liveMtx;
    RenderStats           m_liveRender{};
    std::wstring          m_liveMl;
    MlSettings            m_liveMlS{};
    HdrSettings           m_liveHdr{};
    OutSettings           m_liveOut{};
    DeckLinkSourceStats   m_liveDl{};
    std::atomic<bool>     m_liveStop{ false };
    std::atomic<bool>     m_liveReady{ false };   // graph exists — safe to touch the renderer
    std::thread           m_liveThread;
    LogSink logSink_;
    void Log(const char* fmt, ...);          // routes to logSink_
    mutable Snapshot snapshot_;
};

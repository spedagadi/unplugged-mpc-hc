#pragma once

#include <atlbase.h>
#include <dshow.h>

#include <functional>
#include <string>
#include <string_view>
#include <vector>

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
        bool ac3 = false;
        bool eac3 = false;
        bool trueHd = false;
        bool dts = false;
        bool dtsHd = false;
        bool dtsHdFraming = false;
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
        float contrastSkinProtect = 1.0f;
        float contrastRatioCap = 1.40f;
        bool  contrastDebugVis = false;
        bool  skyEnabled = true;       // sky semantic segmentation (stage-2 overlay)
        bool  skyDebugVis = false;     // cyan sky-mask overlay for validation
        float skyStrength = 0.6f;      // sky tone-leg blend amount [0, 1]
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

    // Snapshot / events
    HRESULT PumpEvents();
    HRESULT GetSnapshot(Snapshot&) const;
    std::string SnapshotJson() const;

private:
    HRESULT BuildGraph(std::wstring_view source);
    HRESULT AddRenderer(CComPtr<IBaseFilter>&);
    HRESULT ConfigureRendererWindow();
    HRESULT ConnectAudio(IBaseFilter* splitter);
    HRESULT ApplyVolume();
    HRESULT ApplyBitstreamConfig();   // LAV Audio passthrough config
    HRESULT ApplyRendererConfig();    // MpcAudioRenderer mode + device
    HRESULT SelectStream(TrackKind kind, int posIndex);
    HRESULT Notify(std::string_view eventName);
    HRESULT UpdateSnapshot() const;

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
    AudioMode audioMode_ = AudioMode::PCM;
    BitstreamConfig bitstream_;
    std::wstring audioDeviceId_, audioDeviceName_;
    bool audioRendererIsMpcAudio_ = false;   // true when MpcAudioRenderer won the CoCreate
    mutable Snapshot snapshot_;
};

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
        // All-default ON: the demo targets an AVR over HDMI; every HD format
        // passes through so the receiver decodes.
        bool ac3 = true;
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
        float shadow = 0.0f;               // [0.0, 0.5]
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
        bool  crEnabled = false;
        float crStrength = 0.30f;
        bool  radiEnabled = false;
        float radiKnee = 0.60f;
        float radiStrength = 0.30f;
        bool  debugLog = false;
        bool  debugCopy = false;
    };

    struct HdrSettings {
        bool preferDoVi = false;
        bool convertToSdr = true;
        int  sdrDisplayNits = 125;
        int  toggleDisplay = 0;            // HDRTD_Disabled..HDRTD_OnOff
        int  displayMaxNits = 1000;
        int  osdBrightness = 0;
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
    AudioMode audioMode_ = AudioMode::Bitstream;   // demo default: HDMI bitstream passthrough
    BitstreamConfig bitstream_;
    std::wstring audioDeviceId_, audioDeviceName_;
    bool audioRendererIsMpcAudio_ = false;   // true when MpcAudioRenderer won the CoCreate
    mutable Snapshot snapshot_;
};

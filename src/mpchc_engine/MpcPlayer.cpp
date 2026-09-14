#include "MpcPlayer.h"

#include <windows.h>
#include <versionhelpers.h>
#include <d3d9.h>
#include <dvdmedia.h>
#include <dxva2api.h>
#include <evr.h>
#include <control.h>   // IQualProp (renderer perf counters)
#include <mfidl.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <FilterInterfaces.h>
#include <IVideoRenderer.h>
#include <LAVAudioSettings.h>
#include <LAVSplitterSettings.h>
#include <atlstr.h>
#include "MpcAudioRenderer/IMpcAudioRenderer.h"
#include "DeckLinkSourceControl.h"
#include "DeckLinkAPI_h.h"   // device enumeration (vendored C++ SDK) — no monitor DLL

#include <algorithm>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cmath>
#include <cstring>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>
#include <utility>
#include <vector>

namespace {

const CLSID CLSID_MPCVR = {0x71F080AA, 0x8661, 0x4093, {0xB1, 0x5E, 0x4F, 0x69, 0x03, 0xE7, 0x7D, 0x0A}};
const CLSID CLSID_LAVSplitter = {0x171252A0, 0x8820, 0x4AFE, {0x9D, 0xF8, 0x5C, 0x92, 0xB2, 0xD6, 0x6B, 0x04}};
const CLSID CLSID_LAVSplitterSource = {0xB98D13E7, 0x55DB, 0x4385, {0xA3, 0x3D, 0x09, 0xFD, 0x1B, 0xA2, 0x63, 0x38}};
const CLSID CLSID_LAVVideo = {0xEE30215D, 0x164F, 0x4A92, {0xA4, 0xEB, 0x9D, 0x4C, 0x13, 0x39, 0x0F, 0x9F}};
const CLSID CLSID_LAVAudio = {0xE8E73B6B, 0x4CB3, 0x44A4, {0xBE, 0x99, 0x4F, 0x7B, 0xCB, 0x96, 0xE4, 0x91}};
const CLSID CLSID_MpcAudioRenderer = {0x601d2a2b, 0x9cde, 0x40bd, {0x86, 0x50, 0x04, 0x85, 0xe3, 0x52, 0x27, 0x27}};
const CLSID CLSID_DeckLinkSource = {0x8c2f2a32, 0x27b1, 0x4e61, {0xA1, 0xBE, 0x78, 0x84, 0xF2, 0x41, 0x0E, 0x7A}};  // src/thirdparty/DeckLinkSource
// DeckLink SDK GUIDs the engine needs for device enumeration. The vendored
// header DECLARES the canonical EXTERN_C names (defined in the filter's own
// module, not linked here), so these local copies use distinct identifiers.
const GUID g_clsidDeckLinkIterator = {0xba6c6f44, 0x6da5, 0x4dce, {0x94, 0xaa, 0xee, 0x2d, 0x13, 0x72, 0xa6, 0x76}};
const GUID g_iidDeckLink           = {0xc418fbdd, 0x0587, 0x48ed, {0x8f, 0xe5, 0x64, 0x0f, 0x0a, 0x14, 0xaf, 0x91}};

// MEDIASUBTYPE_v210 — 'v210' 4CC GUID. Defined in wmcodecdsp.h/axextend but
// not pulled by dshow.h alone; declare the well-known bytes here. (FOURCC
// 'v210' = 0x30313276; the previous 0x38303176 spelling was 'v108'.)
static const GUID MEDIASUBTYPE_v210_GUID = {0x30313276, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};
static const GUID MEDIASUBTYPE_P010_GUID = {0x30313050, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};  // DeckLinkSource direct output

CComPtr<IPin> FindPin(const CComPtr<IBaseFilter>& filter, PIN_DIRECTION dir)
{
    CComPtr<IEnumPins> pins;
    if (!filter || FAILED(filter->EnumPins(&pins))) return nullptr;
    CComPtr<IPin> pin;
    ULONG got = 0;
    while (pins->Next(1, &pin, &got) == S_OK) {
        PIN_DIRECTION d = PINDIR_INPUT;
        if (SUCCEEDED(pin->QueryDirection(&d)) && d == dir) return pin;
        pin.Release();
    }
    return nullptr;
}

CComPtr<IPin> FindUnconnectedPin(const CComPtr<IBaseFilter>& filter, PIN_DIRECTION dir)
{
    CComPtr<IEnumPins> pins;
    if (!filter || FAILED(filter->EnumPins(&pins))) return nullptr;
    CComPtr<IPin> pin;
    ULONG got = 0;
    while (pins->Next(1, &pin, &got) == S_OK) {
        PIN_DIRECTION d = PINDIR_INPUT;
        CComPtr<IPin> connected;
        if (SUCCEEDED(pin->QueryDirection(&d)) && d == dir
            && (FAILED(pin->ConnectedTo(&connected)) || !connected)) {
            return pin;
        }
        pin.Release();
    }
    return nullptr;
}

std::string Utf8(std::wstring_view v)
{
    if (v.empty()) return {};
    const int n = WideCharToMultiByte(CP_UTF8, 0, v.data(), (int)v.size(), nullptr, 0, nullptr, nullptr);
    std::string s((size_t)n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, v.data(), (int)v.size(), s.data(), n, nullptr, nullptr);
    return s;
}

const char* StateName(MpcPlayer::State s)
{
    switch (s) {
    case MpcPlayer::State::Idle: return "idle";
    case MpcPlayer::State::Opening: return "opening";
    case MpcPlayer::State::Paused: return "paused";
    case MpcPlayer::State::Playing: return "playing";
    case MpcPlayer::State::Stopped: return "stopped";
    case MpcPlayer::State::Ended: return "ended";
    case MpcPlayer::State::Error: return "error";
    }
    return "unknown";
}

// LAV Splitter pin-name classifier — matches the previous "pin-name Video/Audio/Subtitle" rule.
MpcPlayer::TrackKind ClassifyStreamName(const std::wstring& name)
{
    auto starts = [](const std::wstring& s, std::wstring_view p) {
        if (s.size() < p.size()) return false;
        for (size_t i = 0; i < p.size(); ++i) {
            if (towlower(s[i]) != towlower(p[i])) return false;
        }
        return true;
    };
    if (starts(name, L"S:") || starts(name, L"Sub")) return MpcPlayer::TrackKind::Subtitle;
    if (starts(name, L"A:") || starts(name, L"Audio")) return MpcPlayer::TrackKind::Audio;
    return MpcPlayer::TrackKind::Video;
}

}   // namespace


void MpcPlayer::Log(const char* fmt, ...)
{
    if (!logSink_) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    logSink_(buf);
}

MpcPlayer::MpcPlayer() = default;

MpcPlayer::~MpcPlayer()
{
    if (mediaControl_) mediaControl_->Stop();
    if (renderer_) {
        if (CComQIPtr<IVideoWindow> pVW = renderer_) {
            pVW->put_Visible(OAFALSE);
            pVW->put_Owner(0);
        }
    }
}

HRESULT MpcPlayer::SetEventCallback(EventCallback cb)
{
    eventCallback_ = std::move(cb);
    return S_OK;
}

HRESULT MpcPlayer::AttachRenderTarget(HWND target)
{
    renderTarget_ = target;
    if (renderer_ && renderTarget_) return ConfigureRendererWindow();
    return S_OK;
}

HRESULT MpcPlayer::SetRenderer(Renderer r)
{
    rendererKind_ = r;
    return S_OK;
}

HRESULT MpcPlayer::Open(std::wstring_view source)
{
    // The graph is single-owner: every thread that mutates it (UI calls, the
    // filter-driven restart worker) goes through this lock.
    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);

    if (source.empty()) return E_INVALIDARG;

    if (mediaControl_) mediaControl_->Stop();
    if (renderer_) {
        if (CComQIPtr<IVideoWindow> pVW = renderer_) {
            pVW->put_Visible(OAFALSE);
            pVW->put_Owner(0);
        }
    }
    graph_.Release();
    mediaControl_.Release();
    mediaSeeking_.Release();
    mediaEvent_.Release();
    splitter_.Release();
    renderer_.Release();
    audioDecoder_.Release();
    audioRenderer_.Release();

    snapshot_ = {};
    snapshot_.state = State::Opening;
    snapshot_.source.assign(source);
    snapshot_.volume = volumePercent_;
    snapshot_.muted = muted_;
    Notify("opening");

    const HRESULT hr = BuildGraph(source);
    if (FAILED(hr)) {
        snapshot_.state = State::Error;
        Notify("error");
        return hr;
    }

    snapshot_.state = State::Paused;
    UpdateSnapshot();
    Notify("opened");
    return S_OK;
}

HRESULT MpcPlayer::Play()
{
    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
    if (!mediaControl_) return VFW_E_NOT_FOUND;
    const HRESULT hr = mediaControl_->Run();
    if (SUCCEEDED(hr)) {
        snapshot_.state = State::Playing;
        UpdateSnapshot();
        Notify("state");
    }
    return hr;
}

HRESULT MpcPlayer::Pause()
{
    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
    if (!mediaControl_) return VFW_E_NOT_FOUND;
    const HRESULT hr = mediaControl_->Pause();
    if (SUCCEEDED(hr)) {
        snapshot_.state = State::Paused;
        UpdateSnapshot();
        Notify("state");
    }
    return hr;
}

HRESULT MpcPlayer::Stop()
{
    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
    if (!mediaControl_) return VFW_E_NOT_FOUND;
    const HRESULT hr = mediaControl_->Stop();
    if (SUCCEEDED(hr)) {
        snapshot_.state = State::Stopped;
        UpdateSnapshot();
        Notify("state");
    }
    return hr;
}

HRESULT MpcPlayer::Seek(LONGLONG position)
{
    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
    if (!mediaSeeking_) return VFW_E_NOT_FOUND;
    position = std::max<LONGLONG>(0, position);
    const HRESULT hr = mediaSeeking_->SetPositions(&position, AM_SEEKING_AbsolutePositioning, nullptr, AM_SEEKING_NoPositioning);
    if (SUCCEEDED(hr)) {
        UpdateSnapshot();
        Notify("time");
    }
    return hr;
}

HRESULT MpcPlayer::ResizeVideo()
{
    if (!renderer_ || !renderTarget_) return S_OK;
    RECT rc = {};
    GetClientRect(renderTarget_, &rc);
    const int clientW = rc.right;
    const int clientH = rc.bottom;
    if (clientW <= 0 || clientH <= 0) return S_OK;

    // AR-corrected source size from MPCVR: width is scaled by DAR.
    long vw = 0, vh = 0;
    if (CComQIPtr<IBasicVideo> pBV = renderer_) {
        long srcL = 0, srcT = 0;
        if (FAILED(pBV->GetSourcePosition(&srcL, &srcT, &vw, &vh))) {
            vw = vh = 0;
        }
    }
    RECT dest = rc;
    if (vw > 0 && vh > 0) {
        const double videoAR = (double)vw / (double)vh;
        const double clientAR = (double)clientW / (double)clientH;
        int destW = clientW;
        int destH = clientH;
        if (clientAR > videoAR) {
            destW = (int)(clientH * videoAR + 0.5);
        } else if (clientAR < videoAR) {
            destH = (int)(clientW / videoAR + 0.5);
        }
        const int destX = (clientW - destW) / 2;
        const int destY = (clientH - destH) / 2;
        dest = {destX, destY, destX + destW, destY + destH};
    }

    if (CComQIPtr<IMFGetService> pGS = renderer_) {
        CComPtr<IMFVideoDisplayControl> pVDC;
        if (SUCCEEDED(pGS->GetService(MR_VIDEO_RENDER_SERVICE, IID_PPV_ARGS(&pVDC))) && pVDC) {
            pVDC->SetVideoPosition(nullptr, &dest);
        }
    }
    if (CComQIPtr<IBasicVideo> pBV = renderer_) {
        pBV->SetDefaultSourcePosition();
        pBV->SetDestinationPosition(dest.left, dest.top, dest.right - dest.left, dest.bottom - dest.top);
    }
    if (CComQIPtr<IVideoWindow> pVW = renderer_) {
        pVW->SetWindowPosition(0, 0, clientW, clientH);
    }
    return S_OK;
}

HRESULT MpcPlayer::SetVolume(int percent)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    volumePercent_ = percent;
    snapshot_.volume = percent;
    return ApplyVolume();
}

HRESULT MpcPlayer::SetMuted(bool m)
{
    muted_ = m;
    snapshot_.muted = m;
    return ApplyVolume();
}

HRESULT MpcPlayer::SetAudioEnabled(bool on)
{
    audioEnabled_ = on;
    muted_ = !on;
    snapshot_.muted = !on;
    return ApplyVolume();
}

HRESULT MpcPlayer::GetAudioEnabled(bool& on) const
{
    on = audioEnabled_;
    return S_OK;
}

HRESULT MpcPlayer::SetAudioMode(AudioMode m)
{
    audioMode_ = m;
    return ApplyBitstreamConfig();
}

HRESULT MpcPlayer::GetAudioMode(AudioMode& m) const
{
    m = audioMode_;
    return S_OK;
}

HRESULT MpcPlayer::SetBitstreamConfig(const BitstreamConfig& b)
{
    bitstream_ = b;
    return ApplyBitstreamConfig();
}

HRESULT MpcPlayer::GetBitstreamConfig(BitstreamConfig& b) const
{
    b = bitstream_;
    return S_OK;
}

HRESULT MpcPlayer::ApplyBitstreamConfig()
{
    if (!audioDecoder_) return S_FALSE;
    CComQIPtr<ILAVAudioSettings> las = audioDecoder_;
    if (!las) return S_FALSE;
    // No registry persistence — matches the "demo/no-persistence" rule for this shell.
    las->SetRuntimeConfig(TRUE);
    const bool on = (audioMode_ == AudioMode::Bitstream);
    las->SetBitstreamConfig(Bitstream_AC3,    on && bitstream_.ac3    ? TRUE : FALSE);
    las->SetBitstreamConfig(Bitstream_EAC3,   on && bitstream_.eac3   ? TRUE : FALSE);
    las->SetBitstreamConfig(Bitstream_TRUEHD, on && bitstream_.trueHd ? TRUE : FALSE);
    las->SetBitstreamConfig(Bitstream_DTS,    on && bitstream_.dts    ? TRUE : FALSE);
    las->SetBitstreamConfig(Bitstream_DTSHD,  on && bitstream_.dtsHd  ? TRUE : FALSE);
    las->SetDTSHDFraming(on && bitstream_.dtsHdFraming ? TRUE : FALSE);
    // Keep the audio renderer in sync (mode change while playing).
    ApplyRendererConfig();
    return S_OK;
}

HRESULT MpcPlayer::SetAudioDevice(const std::wstring& endpointId, const std::wstring& endpointName)
{
    audioDeviceId_ = endpointId;
    audioDeviceName_ = endpointName;
    if (!graph_ || !audioRenderer_) return S_OK;  // stored now, applied at ConnectAudio
    return ApplyRendererConfig();
}

HRESULT MpcPlayer::GetAudioDevice(std::wstring& endpointId, std::wstring& endpointName) const
{
    endpointId = audioDeviceId_;
    endpointName = audioDeviceName_;
    return S_OK;
}

HRESULT MpcPlayer::ApplyVolume()
{
    if (!graph_) return S_OK;
    CComQIPtr<IBasicAudio> ba = graph_;
    if (!ba) return S_OK;
    long db = 0;
    if (muted_ || volumePercent_ <= 0) {
        db = -10000;
    } else {
        const double frac = volumePercent_ / 100.0;
        db = (long)(2000.0 * std::log10(frac));
        if (db < -10000) db = -10000;
        if (db > 0) db = 0;
    }
    return ba->put_Volume(db);
}

HRESULT MpcPlayer::PumpEvents()
{
    if (!mediaEvent_) return S_OK;
    long code = 0;
    LONG_PTR p1 = 0, p2 = 0;
    while (mediaEvent_->GetEvent(&code, &p1, &p2, 0) == S_OK) {
        if (code == EC_COMPLETE) {
            if (mediaControl_) mediaControl_->Stop();
            snapshot_.state = State::Ended;
            UpdateSnapshot();
            Notify("eof");
        } else if (code == EC_ERRORABORT || code == EC_USERABORT) {
            snapshot_.state = State::Error;
            Notify("error");
        }
        mediaEvent_->FreeEventParams(code, p1, p2);
    }
    return S_OK;
}

HRESULT MpcPlayer::GetSnapshot(Snapshot& s) const
{
    if (!graph_) {
        s = snapshot_;
        return S_OK;
    }
    const HRESULT hr = UpdateSnapshot();
    s = snapshot_;
    return hr;
}

std::string MpcPlayer::SnapshotJson() const
{
    Snapshot s;
    GetSnapshot(s);
    std::ostringstream j;
    j << "{\"state\":\"" << StateName(s.state)
      << "\",\"position\":" << s.position
      << ",\"duration\":" << s.duration
      << ",\"volume\":" << s.volume
      << ",\"muted\":" << (s.muted ? "true" : "false")
      << ",\"source\":\"" << Utf8(s.source) << "\"}";
    return j.str();
}

HRESULT MpcPlayer::ConnectAudio(IBaseFilter* splitter)
{
    if (!splitter) return E_POINTER;

    CComPtr<IBaseFilter> audioDecoder;
    HRESULT hrA = audioDecoder.CoCreateInstance(CLSID_LAVAudio);
    std::cout << "[AUDIO] CoCreate LAVAudio hr=0x" << std::hex << (unsigned long)hrA << std::dec << "\n";
    if (FAILED(hrA)) return S_FALSE;

    HRESULT hrB = graph_->AddFilter(audioDecoder, L"LAV Audio");
    CComPtr<IBaseFilter> audioRenderer;
    // Prefer the registered MpcAudioRenderer (WASAPI device routing + bitstream).
    // Falls back to the system DirectSound renderer when it is not registered.
    HRESULT hrC = audioRenderer.CoCreateInstance(CLSID_MpcAudioRenderer);
    audioRendererIsMpcAudio_ = SUCCEEDED(hrC);
    if (FAILED(hrC)) {
        audioRendererIsMpcAudio_ = false;
        hrC = audioRenderer.CoCreateInstance(CLSID_DSoundRender);
    }
    std::cout << "[AUDIO] AddFilter LAVAudio hr=0x" << std::hex << (unsigned long)hrB
              << " CoCreate(renderer=" << (audioRendererIsMpcAudio_ ? "MpcAudioRenderer" : "DSound")
              << ") hr=0x" << (unsigned long)hrC << std::dec << "\n";
    if (FAILED(hrB) || FAILED(hrC)) {
        if (SUCCEEDED(hrB)) graph_->RemoveFilter(audioDecoder);
        return S_FALSE;
    }
    HRESULT hrD = graph_->AddFilter(audioRenderer, L"Audio Renderer");
    if (FAILED(hrD)) {
        graph_->RemoveFilter(audioDecoder);
        return S_FALSE;
    }

    // Apply LAV bitstream config BEFORE pin connect (LAV requirement).
    audioDecoder_ = audioDecoder;
    ApplyBitstreamConfig();

    CComPtr<IPin> splitOut = FindUnconnectedPin(splitter, PINDIR_OUTPUT);
    CComPtr<IPin> decIn = FindUnconnectedPin(audioDecoder, PINDIR_INPUT);
    HRESULT hrE = (splitOut && decIn) ? graph_->Connect(splitOut, decIn) : E_POINTER;

    CComPtr<IPin> decOut = FindUnconnectedPin(audioDecoder, PINDIR_OUTPUT);
    CComPtr<IPin> rndIn = FindUnconnectedPin(audioRenderer, PINDIR_INPUT);
    HRESULT hrF = (decOut && rndIn) ? graph_->Connect(decOut, rndIn) : E_POINTER;
    std::cout << "[AUDIO] connect pin hrE=0x" << std::hex << (unsigned long)hrE
              << " dec->render hrF=0x" << (unsigned long)hrF << std::dec << "\n";

    if (FAILED(hrE) || FAILED(hrF)) {
        graph_->RemoveFilter(audioRenderer);
        graph_->RemoveFilter(audioDecoder);
        audioDecoder_.Release();
        return S_FALSE;
    }
    audioRenderer_ = audioRenderer;
    // Apply mode + device to the audio renderer NOW (before Run), then hand the
    // LAV decoder its bitstream config so both halves agree on the output.
    ApplyRendererConfig();
    return S_OK;
}

HRESULT MpcPlayer::ApplyRendererConfig()
{
    if (!audioRenderer_) return S_FALSE;
    CComQIPtr<IMpcAudioRendererFilter> mar = audioRenderer_;
    if (!mar) return S_FALSE;

    const bool bitstream = audioMode_ == AudioMode::Bitstream;
    mar->SetWasapiMode(bitstream ? MODE_WASAPI_EXCLUSIVE_BITSTREAM : MODE_WASAPI_SHARED);
    mar->SetBitExactOutput(bitstream ? TRUE : FALSE);
    if (!audioDeviceId_.empty()) {
        mar->SetDeviceId(CString(audioDeviceId_.c_str()), CString(audioDeviceName_.c_str()));
    }
    const HRESULT hr = mar->Apply();
    std::cout << "[AUDIO] renderer cfg mode=" << (bitstream ? "bitstream" : "shared")
              << " device='" << Utf8(audioDeviceName_) << "' apply=0x"
              << std::hex << (unsigned long)hr << std::dec << "\n";
    return hr;
}

HRESULT MpcPlayer::BuildGraph(std::wstring_view source)
{
    HRESULT hr = graph_.CoCreateInstance(CLSID_FilterGraph);
    if (FAILED(hr)) return hr;

    // Retire the previous direct filter OFF the UI thread: its destructor joins
    // the SDK worker, whose StopStreams can block while the HDMI source is
    // mid-signal-change (UB820 stop→menu freeze observed). The retired reference
    // is dropped by a background cleanup thread; the UI thread proceeds without
    // ever waiting on the old card's SDK teardown.
    static std::mutex                        s_retireMtx;
    static std::vector<CComPtr<IDeckLinkSourceControl>> s_retired;
    if (decklinkControl_) {
        {
            std::lock_guard<std::mutex> lk(s_retireMtx);
            s_retired.push_back(std::move(decklinkControl_));
        }
        static bool s_retireThreadStarted = false;
        if (!s_retireThreadStarted) {
            s_retireThreadStarted = true;
            std::thread([]() {
                for (;;) {
                    std::this_thread::sleep_for(std::chrono::seconds(3));
                    std::vector<CComPtr<IDeckLinkSourceControl>> gone;
                    {
                        std::lock_guard<std::mutex> lk(s_retireMtx);
                        gone.swap(s_retired);
                    }
                    if (gone.empty()) continue;
                    for (auto& p : gone) p.Release();   // destructor (worker join) runs here
                    gone.clear();
                    if (s_retired.empty()) {
                        // Nothing left to retire for a long while; loop forever is fine
                        // (one lazy thread per process, ~free).
                    }
                }
            }).detach();
        }
    }

    // DeckLink HDMI capture: LAVSplitterSource demuxes the decklink:// URL
    // itself (video-only — no_audio). No separate splitter, no audio path.
    const bool bDeckLink = (_wcsnicmp(source.data(), L"decklink://", 11) == 0);
    Log("[DECKLINK][engine] BuildGraph bDeckLink=%d source='%.*S'", (int)bDeckLink, 140, source.data());
    if (bDeckLink) decklinkUrl_ = std::wstring(source);   // the filter-driven restart re-opens this

    CComPtr<IBaseFilter> sourceFilter;
    CComPtr<IBaseFilter> splitter;
    bool bDeckLinkDirect = false;
    if (bDeckLink) {
        // Direct ingest (phase 3): our DeckLinkSource filter CoCreates when it
        // is registered — v210 output pin → MPCVR directly, no ffmpeg/LAV in the
        // path. Falls back to the LAV URL chain when the filter is absent.
        hr = sourceFilter.CoCreateInstance(CLSID_DeckLinkSource);
        if (SUCCEEDED(hr)) {
            bDeckLinkDirect = true;
            Log("[DECKLINK][engine] direct DeckLinkSource filter");
            hr = graph_->AddFilter(sourceFilter, L"DeckLink Source (direct)");
            if (FAILED(hr)) {
                Log("[DECKLINK][engine] AddFilter(direct source) FAILED hr=0x%08X", (unsigned)hr);
                return hr;
            }
            // Device name rides the URL: decklink://<device>?opts...
            std::wstring dev;
            if (source.size() > 11) {
                std::wstring_view rest = source.substr(11);
                const size_t q = rest.find(L'?');
                dev.assign(rest.substr(0, q));
            }
            CComQIPtr<IDeckLinkSourceControl> ctl = sourceFilter;
            if (!ctl) {
                Log("[DECKLINK][engine] QI IDeckLinkSourceControl FAILED");
                return E_NOINTERFACE;
            }
            // Filter telemetry → engine Log → shell diag log (chain observability).
            ctl->SetLogSink(this, &MpcPlayer::DeckLinkSourceLogBridge);
            // The MONITOR advises the signal meta (master); bake it into the
            // media type so the first connect is already correct.
            {
                int sl = -1, scs = -1, sdr = -1, sd = 0, sch = -1,
                    sw = 0, sh = 0, sfn = 0, sfd = 0, sitl = 2;
                if (GetDecklinkSignalInfo(sl, scs, sdr, sd, sch, sw, sh, sfn, sfd, sitl) && sl == 1) {
                    ctl->SetSignalMeta((scs == 2) ? 3 : (scs == 0) ? 1 : (scs == 1) ? 2 : 0,
                                       (sdr == 1) ? 2 : (sdr == 2) ? 3 : 0);
                    Log("[DECKLINK][engine] monitor meta → SetSignalMeta cs=%d dr=%d", scs, sdr);
                }
            }
            CComBSTR b(dev.c_str());
            hr = ctl->StartCapture(b);
            Log("[DECKLINK][engine] StartCapture('%S') hr=0x%08X (bounded wait for first format)",
                dev.c_str(), (unsigned)hr);
            if (FAILED(hr)) return hr;
            decklinkControl_ = ctl;   // retain for GetDeckLinkSourceStats (retired on rebuild)
        } else {
            Log("[DECKLINK][engine] direct DeckLinkSource unavailable (hr=0x%08X) — LAV fallback", (unsigned)hr);
            Log("[DECKLINK][engine] CoCreateInstance(CLSID_LAVSplitterSource)...");
            hr = sourceFilter.CoCreateInstance(CLSID_LAVSplitterSource);
            if (FAILED(hr)) {
                Log("[DECKLINK][engine] CoCreate LAVSplitterSource FAILED hr=0x%08X", (unsigned)hr);
                return hr;
            }
            hr = graph_->AddFilter(sourceFilter, L"DeckLink Source (LAV)");
            if (FAILED(hr)) {
                Log("[DECKLINK][engine] AddFilter(source) FAILED hr=0x%08X", (unsigned)hr);
                return hr;
            }
            CComQIPtr<IFileSourceFilter> pFS = sourceFilter;
            if (!pFS) {
                Log("[DECKLINK][engine] QI IFileSourceFilter FAILED");
                return E_POINTER;
            }
            Log("[DECKLINK][engine] IFileSourceFilter::Load(url)...");
            hr = pFS->Load(std::wstring(source).c_str(), nullptr);
            Log("[DECKLINK][engine] Load hr=0x%08X", (unsigned)hr);
            if (FAILED(hr)) return hr;
            splitter = sourceFilter;   // acts as the demuxer/splitter in one
        }
    } else {
        hr = graph_->AddSourceFilter(std::wstring(source).c_str(), L"source", &sourceFilter);
        if (FAILED(hr)) return hr;
        hr = splitter.CoCreateInstance(CLSID_LAVSplitter);
        if (FAILED(hr)) return hr;
        hr = graph_->AddFilter(splitter, L"LAV Splitter");
        if (FAILED(hr)) return hr;
    }

    CComPtr<IBaseFilter> decoder;
    if (!bDeckLinkDirect) {
        hr = decoder.CoCreateInstance(CLSID_LAVVideo);
        if (FAILED(hr)) return hr;
        hr = graph_->AddFilter(decoder, L"LAV Video");
        if (FAILED(hr)) return hr;
    }

    hr = AddRenderer(renderer_);
    if (FAILED(hr) || !renderer_) return FAILED(hr) ? hr : E_FAIL;
    hr = graph_->AddFilter(renderer_, L"Video Renderer");
    if (FAILED(hr)) return hr;

    if (renderTarget_) ConfigureRendererWindow();

    if (bDeckLinkDirect) {
        // v210 out → MPCVR input, straight. The direct source captures WITHOUT
        // LAVVideo, so record its negotiated type for the LIVE panel here.
        ApplyDecklinkColorToRenderer();   // pre-connect ICS (monitor-advised)
        CComPtr<IPin> rndIn = FindPin(renderer_, PINDIR_INPUT);
        CComPtr<IPin> srcOut = FindPin(sourceFilter, PINDIR_OUTPUT);
        if (!rndIn || !srcOut) return E_POINTER;
        Log("[DECKLINK][engine] direct connect v210 -> MPCVR input...");
        hr = graph_->Connect(srcOut, rndIn);
        Log("[DECKLINK][engine] direct renderer connect hr=0x%08X", (unsigned)hr);
        if (FAILED(hr)) return hr;
        CaptureSourceMediaType(srcOut);   // DEMUXER → REC (LIVE panel)
    } else if (bDeckLink) {
        // Push the forced input colour space BEFORE pin negotiation so the very
        // first media type/ICS override application uses it.
        ApplyDecklinkColorToRenderer();
        // DeckLink source has only output pins (video when no_audio); try to
        // connect the video one to the decoder input.
        CComPtr<IPin> decIn = FindPin(decoder, PINDIR_INPUT);
        if (!decIn) return E_POINTER;
        Log("[DECKLINK][engine] connecting source video pin -> LAVVideo input...");
        hr = ConnectVideoPin(sourceFilter, decIn);
        Log("[DECKLINK][engine] ConnectVideoPin hr=0x%08X", (unsigned)hr);
        if (FAILED(hr)) return hr;
        Log("[DECKLINK][engine] DeckLink graph: source->decoder connected (no audio)");
    } else {
        CComPtr<IPin> srcOut = FindPin(sourceFilter, PINDIR_OUTPUT);
        CComPtr<IPin> splIn = FindPin(splitter, PINDIR_INPUT);
        if (!srcOut || !splIn) return E_POINTER;
        hr = graph_->Connect(srcOut, splIn);
        if (FAILED(hr)) return hr;

        CComPtr<IPin> splOut = FindPin(splitter, PINDIR_OUTPUT);
        CComPtr<IPin> decIn = FindPin(decoder, PINDIR_INPUT);
        if (!splOut || !decIn) return E_POINTER;
        hr = graph_->Connect(splOut, decIn);
        if (FAILED(hr)) return hr;
    }

    if (!bDeckLinkDirect) {
        CComPtr<IPin> decOut = FindPin(decoder, PINDIR_OUTPUT);
        CComPtr<IPin> rndIn = FindPin(renderer_, PINDIR_INPUT);
        if (!decOut || !rndIn) return E_POINTER;
        hr = graph_->Connect(decOut, rndIn);
        if (FAILED(hr)) return hr;
        if (!bDeckLink) {
            // Record the decoder->renderer media type (LIVE panel DEMUXER->REC and
            // the HDR color/transfer source for ApplyMediaColorToRenderer).
            CaptureSourceMediaType(decOut);
        }
    }

    hr = graph_.QueryInterface(&mediaControl_);
    if (FAILED(hr)) return hr;
    hr = graph_.QueryInterface(&mediaSeeking_);
    if (FAILED(hr)) return hr;
    graph_.QueryInterface(&mediaEvent_);

    splitter_ = splitter;
    if (bDeckLinkDirect) {
        // Direct ingest: no LAV splitter queue to tune (phase-2b bounded queue
        // replaces it later).
    } else if (bDeckLink) {
        ApplyDecklinkLowLatency(splitter);   // shrink LAV output queue: live capture
    } else {
        // HDR media file: the decoder passes PQ/HLG in the media type, but
        // MPCVR's auto-ICS can resolve it to SDR (G22P709) depending on the
        // graph handoff. Force the ICS to match the decoded transfer so the ML
        // grade + tone-map see the real HDR signal (mirrors the decklink path).
        ApplyMediaColorToRenderer(FindPin(decoder, PINDIR_OUTPUT));
    }
    if (!bDeckLink) {
        ConnectAudio(splitter);
    }
    ApplyVolume();

    if (renderTarget_) {
        if (CComQIPtr<IVideoWindow> pVW = renderer_) pVW->put_Visible(OATRUE);
        ResizeVideo();
    }
    return S_OK;
}

// DeckLinkSource.ax telemetry (SetLogSink) → engine Log → shell diag log.
void __cdecl MpcPlayer::DeckLinkSourceLogBridge(void* ctx, const char* line)
{
    static_cast<MpcPlayer*>(ctx)->Log("%s", line);
}

// Try-connect the source's output pins to the decoder input. With no_audio (the
// DeckLink path) there is a single video output pin; a try-loop keeps this robust
// if an audio stream is ever present (stream order audio=0, video=1).
HRESULT MpcPlayer::ConnectVideoPin(IBaseFilter* source, IPin* decIn)
{
    if (!source || !decIn) return E_POINTER;
    CComPtr<IEnumPins> pins;
    HRESULT hr = source->EnumPins(&pins);
    if (FAILED(hr) || !pins) return hr ? hr : E_UNEXPECTED;
    CComPtr<IPin> pin;
    ULONG got = 0;
    while (pins->Next(1, &pin, &got) == S_OK) {
        PIN_DIRECTION d = PINDIR_INPUT;
        if (SUCCEEDED(pin->QueryDirection(&d)) && d == PINDIR_OUTPUT) {
            if (SUCCEEDED(graph_->Connect(pin, decIn))) {
                // Record what the demuxer actually handed out — the media type
                // negotiated on this output pin (LIVE panel / DEMUXER -> REC).
                CaptureSourceMediaType(pin);
                return S_OK;
            }
        }
        pin.Release();
    }
    return VFW_E_CANNOT_CONNECT;
}

// Read the connected media type on the (now-connected) source output pin and
// stash the stream properties for the LIVE panel. Called once per graph build
// (decklink mode); static until the next restart.
void MpcPlayer::CaptureSourceMediaType(IPin* srcPin)
{
    videoStreamInfo_ = {};
    if (!srcPin) return;
    AM_MEDIA_TYPE mt = {};
    if (FAILED(srcPin->ConnectionMediaType(&mt))) return;

    videoStreamInfo_.valid = true;
    if (mt.formattype == FORMAT_VideoInfo2 && mt.pbFormat) {
        const VIDEOINFOHEADER2* vih2 = reinterpret_cast<const VIDEOINFOHEADER2*>(mt.pbFormat);
        videoStreamInfo_.width  = vih2->bmiHeader.biWidth;
        videoStreamInfo_.height = labs(vih2->bmiHeader.biHeight);
        videoStreamInfo_.avgTimePerFrame100ns = (int)vih2->AvgTimePerFrame;
        videoStreamInfo_.interlaced = !!(vih2->dwInterlaceFlags & AMINTERLACE_IsInterlaced);
    } else if (mt.formattype == FORMAT_VideoInfo && mt.pbFormat) {
        const VIDEOINFOHEADER* vih = reinterpret_cast<const VIDEOINFOHEADER*>(mt.pbFormat);
        videoStreamInfo_.width  = vih->bmiHeader.biWidth;
        videoStreamInfo_.height = labs(vih->bmiHeader.biHeight);
        videoStreamInfo_.avgTimePerFrame100ns = (int)vih->AvgTimePerFrame;
    }

    if (mt.subtype == MEDIASUBTYPE_UYVY) { videoStreamInfo_.pixelFormat = 0; videoStreamInfo_.subtypeName = L"UYVY"; }
    else if (mt.subtype == MEDIASUBTYPE_v210_GUID) { videoStreamInfo_.pixelFormat = 1; videoStreamInfo_.subtypeName = L"v210"; }
    else if (mt.subtype == MEDIASUBTYPE_NV12) { videoStreamInfo_.pixelFormat = 2; videoStreamInfo_.subtypeName = L"NV12"; }
    else if (mt.subtype == MEDIASUBTYPE_P010_GUID) { videoStreamInfo_.pixelFormat = 4; videoStreamInfo_.subtypeName = L"P010"; }
    else {
        videoStreamInfo_.pixelFormat = 3;
        videoStreamInfo_.subtypeName = L"(raw)";
    }
    // Transfer function + primaries: read the extended format from dwControlFlags
    // (PQ/HLG → HDR; primaries → colorspace for the LIVE panel).
    if (mt.formattype == FORMAT_VideoInfo2 && mt.pbFormat) {
        const VIDEOINFOHEADER2* vih2 = reinterpret_cast<const VIDEOINFOHEADER2*>(mt.pbFormat);
        if (vih2->dwControlFlags & AMCONTROL_COLORINFO_PRESENT) {
            DXVA2_ExtendedFormat xf = {};
            xf.value = vih2->dwControlFlags;
            videoStreamInfo_.transferFunction = (int)xf.VideoTransferFunction;
            videoStreamInfo_.hdr = (xf.VideoTransferFunction == MFVideoTransFunc_2084 ||
                                    xf.VideoTransferFunction == MFVideoTransFunc_HLG);
            // MF/DXVA2 extension values (BT2020 primaries = 9; BT709 = 2).
            videoStreamInfo_.colorspace =
                (xf.VideoPrimaries == 9) ? 3 :
                (xf.VideoPrimaries == 2) ? 2 : 1;
        }
    }
    Log("[ENGINE] source media type: %dx%d itl=%d avg=%d fmt=%d tf=%d hdr=%d",
        videoStreamInfo_.width, videoStreamInfo_.height,
        videoStreamInfo_.interlaced, videoStreamInfo_.avgTimePerFrame100ns,
        videoStreamInfo_.pixelFormat, videoStreamInfo_.transferFunction,
        videoStreamInfo_.hdr ? 1 : 0);
    // Free the media type (DeleteMediaType is a base-class helper not linked here;
// AM_MEDIA_TYPE allocates only pbFormat).
    if (mt.cbFormat && mt.pbFormat) CoTaskMemFree(mt.pbFormat);
}

// Push the forced input colour space onto the renderer before the graph runs.
void MpcPlayer::ApplyDecklinkColorToRenderer()
{
    if (!renderer_) {
        Log("[DECKLINK][engine] ApplyDecklinkColorToRenderer: no renderer yet");
        return;
    }
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) {
        Log("[DECKLINK][engine] ApplyDecklinkColorToRenderer: renderer lacks IVideoRenderer");
        return;
    }
    Settings_t s;
    vr->GetSettings(s);
    s.iInputColorSpace = decklinkSettings_.inputColorSpace;
    Log("[DECKLINK][engine] pushing iInputColorSpace=%d to MPCVR", s.iInputColorSpace);
    vr->SetSettings(s);
}

// Live DeckLink capture must not accumulate frames in LAVSplitter's output
// queue (default 350 packets ≈ 7 s at 50 fps of latency). Cap it low enough to
// stay visually-latency-free, but not so low that the drain bursts underflow
// (stutter). 12 packets ≈ 0.25 s at 50 fps — absorbs scheduler jitter without
// adding perceptible latency.
void MpcPlayer::ApplyDecklinkLowLatency(IBaseFilter* splitter)
{
    if (!splitter) return;
    CComQIPtr<ILAVFSettings> settings = splitter;
    if (!settings) {
        Log("[DECKLINK][engine] ApplyDecklinkLowLatency: splitter lacks ILAVFSettings");
        return;
    }
    HRESULT hr = settings->SetMaxQueueSize(12);
    Log("[DECKLINK][engine] ApplyDecklinkLowLatency: SetMaxQueueSize(12) hr=0x%08X", (unsigned)hr);
}

// HDR media file: read the transfer function the decoder handed down in the
// negotiated media type and force MPCVR's input colour space to match (PQ/HLG)
// so SourceIsHDR() is true and the ML grade grades real HDR, not a G22P709
// misread. Mirrors the DeckLink path's explicit ICS push.
void MpcPlayer::ApplyMediaColorToRenderer(IPin* decOut)
{
    if (!renderer_ || !decOut) return;
    // CaptureSourceMediaType(decOut) ran first and filled videoStreamInfo_
    // (width/height/transfer). For HDR files force MPCVR's input colour space
    // from the actual decoded transfer (mirrors the decklink ICS push), so
    // SourceIsHDR() is true and the ML grade grades the real HDR signal.
    // TEMP-HACK: the decoder's media type reports transfer Unknown (tf=0) even
    // for HDR10, so also force PQ whenever the decoded pixel format is 10-bit —
    // a 10-bit frame almost always means HDR, and this is how the "washed out"
    // hack is being bisected.
    int ics = ICS_Auto;
    switch (videoStreamInfo_.transferFunction) {
    case MFVideoTransFunc_2084: ics = ICS_BT2020_PQ; break;
    case MFVideoTransFunc_HLG:   ics = ICS_BT2020_HLG; break;
    default: break;
    }
    if (ics == ICS_Auto) {
        const bool isP010 = (videoStreamInfo_.pixelFormat == 3 ||
                             videoStreamInfo_.subtypeName.find(L"010") != std::wstring::npos ||
                             videoStreamInfo_.subtypeName.find(L"P010") != std::wstring::npos);
        if (isP010) {
            ics = ICS_BT2020_PQ;   // TEMP-HACK: 10-bit decoded → assume PQ
            Log("[ENGINE] ApplyMediaColorToRenderer: TEMP-HACK tf=%d fmt=P010 → force PQ",
                videoStreamInfo_.transferFunction);
        }
    }
    if (ics == ICS_Auto) {
        Log("[ENGINE] ApplyMediaColorToRenderer: transfer=%d not HDR — leave ICS auto",
            videoStreamInfo_.transferFunction);
        return;
    }
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return;
    Settings_t s;
    vr->GetSettings(s);
    s.iInputColorSpace = ics;
    Log("[ENGINE] ApplyMediaColorToRenderer: pushing iInputColorSpace=%d (tf=%d)",
        ics, videoStreamInfo_.transferFunction);
    vr->SetSettings(s);
}

HRESULT MpcPlayer::AddRenderer(CComPtr<IBaseFilter>& out)
{
    Renderer choice = rendererKind_;
    if (choice == Renderer::Auto) {
        choice = renderTarget_ ? Renderer::MPCVR : Renderer::EVR;
    }
    HRESULT hr = E_FAIL;
    switch (choice) {
    case Renderer::MPCVR:
        hr = out.CoCreateInstance(CLSID_MPCVR);
        if (SUCCEEDED(hr)) return S_OK;
        [[fallthrough]];
    case Renderer::VMR9:
        hr = out.CoCreateInstance(CLSID_VideoMixingRenderer9);
        if (SUCCEEDED(hr)) return S_OK;
        [[fallthrough]];
    case Renderer::EVR:
        hr = out.CoCreateInstance(CLSID_EnhancedVideoRenderer);
        if (SUCCEEDED(hr)) return S_OK;
        break;
    case Renderer::Auto:
        break;
    }
    return hr;
}

HRESULT MpcPlayer::ConfigureRendererWindow()
{
    if (!renderer_ || !renderTarget_) return S_OK;
    if (CComQIPtr<IMFGetService> pGS = renderer_) {
        CComPtr<IMFVideoDisplayControl> pVDC;
        if (SUCCEEDED(pGS->GetService(MR_VIDEO_RENDER_SERVICE, IID_PPV_ARGS(&pVDC))) && pVDC) {
            pVDC->SetVideoWindow(renderTarget_);
            pVDC->SetAspectRatioMode(MFVideoARMode_PreservePicture);
        }
    }
    if (CComQIPtr<IVideoWindow> pVW = renderer_) {
        pVW->put_Owner(reinterpret_cast<OAHWND>(renderTarget_));
        pVW->put_WindowStyle(WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN);
        pVW->put_MessageDrain(reinterpret_cast<OAHWND>(renderTarget_));
    }
    if (CComQIPtr<IExFilterConfig> pCfg = renderer_) {
        pCfg->Flt_SetBool("lessRedraws", true);
        pCfg->Flt_SetBool("d3dFullscreenControl", true);
    }
    return S_OK;
}

HRESULT MpcPlayer::Notify(std::string_view name)
{
    if (eventCallback_) eventCallback_(name, snapshot_);
    return S_OK;
}

HRESULT MpcPlayer::UpdateSnapshot() const
{
    if (!mediaSeeking_) return S_OK;
    LONGLONG p = 0, d = 0;
    HRESULT hr = mediaSeeking_->GetPositions(&p, nullptr);
    if (SUCCEEDED(hr)) hr = mediaSeeking_->GetDuration(&d);
    if (SUCCEEDED(hr)) { snapshot_.position = p; snapshot_.duration = d; }
    return hr;
}

// ── MPCVR-Zion settings bridge ───────────────────────────────────────────────
// The engine talks directly to MPCVR's IVideoRenderer interface (Settings_t).

namespace {

void ApplyMlToSettings(const MpcPlayer::MlSettings& m, Settings_t& s)
{
    s.bMLEnabled = m.enable;
    s.iMLMode = m.mode;
    s.bMLToneCurveEnabled = m.toneCurveEnabled;
    s.bMLGammaEnabled = m.gammaEnabled;
    s.fMLGamma = m.gamma;
    s.bMLShadowEnabled = m.shadowEnabled;
    s.fMLShadow = m.shadow;
    s.fMLShadowDehaze = m.shadowDehaze;
    s.fMLHighlightRolloffCtrl = m.highlightRolloffCtrl;
    s.bMLHighlightEnabled = m.highlightEnabled;
    s.fMLHighlight = m.highlight;
    s.bMLChromaEnabled = m.chromaEnabled;
    s.bMLHuntEnabled = m.huntEnabled;
    s.fMLHunt = m.hunt;
    s.bMLChromaNeutralEnabled = m.chNeutralEnabled;
    s.fMLChromaNeutral = m.chNeutral;
    s.bMLChromaFireEnabled = m.chFireEnabled;
    s.fMLChromaFire = m.chFire;
    s.bMLChromaKneeEnabled = m.chKneeEnabled;
    s.fMLChromaKnee = m.chKnee;
    s.bMLChromaSkinEnabled = m.chSkinEnabled;
    s.fMLChromaSkinProtect = m.chSkin;
    s.bMLDebugLog = m.debugLog;
    s.bMLDebugCopy = m.debugCopy;
    s.bMLShadowDebugVis = m.shadowDebugVis;
    s.fMLShadowZoneCeil = m.shadowZoneCeil;
    s.fMLShadowSkinProtect = m.shadowSkinProtect;
    s.fMLShadowRatioCap = m.shadowRatioCap;
    s.bMLContrastEnabled = m.contrastEnabled;
    s.fMLContrast = m.contrast;
    s.fMLContrastZoneLo = m.contrastZoneLo;
    s.fMLContrastSkinProtect = m.contrastSkinProtect;
    s.fMLContrastRatioCap = m.contrastRatioCap;
    s.bMLContrastDebugVis = m.contrastDebugVis;
    s.bMLSkyEnabled = m.skyEnabled;
    s.bMLSkyDebugVis = m.skyDebugVis;
    s.fMLSkyStrength = m.skyStrength;
    s.bMLPersonEnabled = m.personEnabled;
    s.fMLPersonStrength = m.personStrength;
    s.bMLPersonDebugVis = m.personOverlay;
    s.fMLSkinPreserve = m.skinPreserve;
    s.bMLFaceProtectEnabled = m.faceProtectEnabled;
    s.fMLFaceProtect = m.faceStrength;
    s.fMLFaceFeather = m.faceFeather;
    s.fMLFaceExpand = m.faceExpand;
    s.bMLFaceDebugVis = m.faceDebugVis;
    s.bMLBars = m.barsEnabled;
    s.bMLBarsHighlight = m.barsHighlight;
    s.configSeq = m.configSeq;
    OutputDebugStringA("[ENGINE] ApplyMlToSettings");
    char buf[512];
    snprintf(buf, sizeof(buf),
        "[ENGINE] configSeq=%u enable=%d mode=%d toneCurve=%d gamma=%.3f(en=%d) shadow=%.3f(en=%d) "
        "highlight=%.3f(en=%d) chroma=%d hunt=%.2f(en=%d) chN=%.2f(en=%d) chF=%.2f(en=%d) "
        "knee=%.2f skin=%.2f bars=%d barsHL=%d debugLog=%d debugCopy=%d sizeof(Settings_t)=%zu\n",
        m.configSeq, (int)m.enable, m.mode, (int)m.toneCurveEnabled,
        m.gamma, (int)m.gammaEnabled, m.shadow, (int)m.shadowEnabled,
        m.highlight, (int)m.highlightEnabled, (int)m.chromaEnabled,
        m.hunt, (int)m.huntEnabled, m.chNeutral, (int)m.chNeutralEnabled,
        m.chFire, (int)m.chFireEnabled, m.chKnee, m.chSkin,
        (int)m.barsEnabled, (int)m.barsHighlight,
        (int)m.debugLog, (int)m.debugCopy, sizeof(Settings_t));
    OutputDebugStringA(buf);
}

void ReadMlFromSettings(const Settings_t& s, MpcPlayer::MlSettings& m)
{
    m.enable = s.bMLEnabled;
    m.mode = s.iMLMode;
    m.toneCurveEnabled = s.bMLToneCurveEnabled;
    m.gammaEnabled = s.bMLGammaEnabled;
    m.gamma = s.fMLGamma;
    m.shadowEnabled = s.bMLShadowEnabled;
    m.shadow = s.fMLShadow;
    m.shadowDehaze = s.fMLShadowDehaze;
    m.highlightRolloffCtrl = s.fMLHighlightRolloffCtrl;
    m.highlightEnabled = s.bMLHighlightEnabled;
    m.highlight = s.fMLHighlight;
    m.chromaEnabled = s.bMLChromaEnabled;
    m.huntEnabled = s.bMLHuntEnabled;
    m.hunt = s.fMLHunt;
    m.chNeutralEnabled = s.bMLChromaNeutralEnabled;
    m.chNeutral = s.fMLChromaNeutral;
    m.chFireEnabled = s.bMLChromaFireEnabled;
    m.chFire = s.fMLChromaFire;
    m.chKneeEnabled = s.bMLChromaKneeEnabled;
    m.chKnee = s.fMLChromaKnee;
    m.chSkinEnabled = s.bMLChromaSkinEnabled;
    m.chSkin = s.fMLChromaSkinProtect;
    m.debugLog = s.bMLDebugLog;
    m.debugCopy = s.bMLDebugCopy;
    m.shadowDebugVis = s.bMLShadowDebugVis;
    m.shadowZoneCeil = s.fMLShadowZoneCeil;
    m.shadowSkinProtect = s.fMLShadowSkinProtect;
    m.shadowRatioCap = s.fMLShadowRatioCap;
    m.contrastEnabled = s.bMLContrastEnabled;
    m.contrast = s.fMLContrast;
    m.contrastZoneLo = s.fMLContrastZoneLo;
    m.contrastSkinProtect = s.fMLContrastSkinProtect;
    m.contrastRatioCap = s.fMLContrastRatioCap;
    m.contrastDebugVis = s.bMLContrastDebugVis;
    m.skyEnabled = s.bMLSkyEnabled;
    m.skyDebugVis = s.bMLSkyDebugVis;
    m.skyStrength = s.fMLSkyStrength;
    m.personEnabled = s.bMLPersonEnabled;
    m.personStrength = s.fMLPersonStrength;
    m.personOverlay = s.bMLPersonDebugVis;
    m.skinPreserve = s.fMLSkinPreserve;
    m.faceProtectEnabled = s.bMLFaceProtectEnabled;
    m.faceStrength = s.fMLFaceProtect;
    m.faceFeather = s.fMLFaceFeather;
    m.faceExpand = s.fMLFaceExpand;
    m.faceDebugVis = s.bMLFaceDebugVis;
    m.barsEnabled = s.bMLBars;
    m.barsHighlight = s.bMLBarsHighlight;
    m.configSeq = s.configSeq;
}

void ApplyHdrToSettings(const MpcPlayer::HdrSettings& h, Settings_t& s)
{
    s.bHdrPreferDoVi = h.preferDoVi;
    s.bConvertToSdr = h.convertToSdr;
    s.iSDRDisplayNits = h.sdrDisplayNits;
    s.iHdrToggleDisplay = h.toggleDisplay;
    s.iHdrDisplayMaxNits = h.displayMaxNits;
    s.iHdrOsdBrightness = h.osdBrightness;
    s.iHdrLocalToneMappingType = h.toneMapCurve;
    s.bHDRPassthroughRaw = h.hdrPassthroughRaw;
}

void ReadHdrFromSettings(const Settings_t& s, MpcPlayer::HdrSettings& h)
{
    h.preferDoVi = s.bHdrPreferDoVi;
    h.convertToSdr = s.bConvertToSdr;
    h.sdrDisplayNits = s.iSDRDisplayNits;
    h.toggleDisplay = s.iHdrToggleDisplay;
    h.displayMaxNits = s.iHdrDisplayMaxNits;
    h.osdBrightness = s.iHdrOsdBrightness;
    h.toneMapCurve = s.iHdrLocalToneMappingType;
    h.hdrPassthroughRaw = s.bHDRPassthroughRaw;
}

void ApplyOutToSettings(const MpcPlayer::OutSettings& o, Settings_t& s)
{
    s.bUseD3D11 = o.useD3D11;
    s.iTexFormat = o.texFormat;
    s.VPFmts.bNV12 = o.vpNV12;
    s.VPFmts.bP01x = o.vpP01x;
    s.VPFmts.bYUY2 = o.vpYUY2;
    s.VPFmts.bOther = o.vpOther;
    s.iVPDeinterlacing = o.deinterlace;
    s.bDeintDouble = o.deintDouble;
    s.bDeintBlend = o.deintBlend;
    s.bVPScaling = o.shaderVPScaling;
    s.iVPSuperRes = o.superRes;
    s.bVPRTXVideoHDR = o.rtxVideoHdr;
    s.iChromaScaling = o.chromaScaling;
    s.iUpscaling = o.upscaling;
    s.iDownscaling = o.downscaling;
    s.bInterpolateAt50pct = o.interpolate50;
    s.bUseDither = o.useDither;
    s.iSwapEffect = o.swapEffect;
    s.bExclusiveFS = o.exclusiveFS;
    s.bVBlankBeforePresent = o.vBlank;
    s.bAdjustPresentTime = o.adjustPresent;
    s.bReinitByDisplay = o.reinitDisplay;
    s.bShowStats = o.showStats;
    s.bTrayIcon = o.trayIcon;
}

void ReadOutFromSettings(const Settings_t& s, MpcPlayer::OutSettings& o)
{
    o.useD3D11 = s.bUseD3D11;
    o.texFormat = s.iTexFormat;
    o.vpNV12 = s.VPFmts.bNV12;
    o.vpP01x = s.VPFmts.bP01x;
    o.vpYUY2 = s.VPFmts.bYUY2;
    o.vpOther = s.VPFmts.bOther;
    o.deinterlace = s.iVPDeinterlacing;
    o.deintDouble = s.bDeintDouble;
    o.deintBlend = s.bDeintBlend;
    o.shaderVPScaling = s.bVPScaling;
    o.superRes = s.iVPSuperRes;
    o.rtxVideoHdr = s.bVPRTXVideoHDR;
    o.chromaScaling = s.iChromaScaling;
    o.upscaling = s.iUpscaling;
    o.downscaling = s.iDownscaling;
    o.interpolate50 = s.bInterpolateAt50pct;
    o.useDither = s.bUseDither;
    o.swapEffect = s.iSwapEffect;
    o.exclusiveFS = s.bExclusiveFS;
    o.vBlank = s.bVBlankBeforePresent;
    o.adjustPresent = s.bAdjustPresentTime;
    o.reinitDisplay = s.bReinitByDisplay;
    o.showStats = s.bShowStats;
    o.trayIcon = s.bTrayIcon;
}

}   // namespace


HRESULT MpcPlayer::SetMlSettings(const MlSettings& m)
{
    if (!renderer_) {
        OutputDebugStringA("[ENGINE] SetMlSettings: renderer_ is null, returning S_FALSE\n");
        return S_FALSE;
    }
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) {
        OutputDebugStringA("[ENGINE] SetMlSettings: QI for IVideoRenderer failed, returning S_FALSE\n");
        return S_FALSE;
    }
    Settings_t s;
    vr->GetSettings(s);
    char buf[256];
    snprintf(buf, sizeof(buf), "[ENGINE] SetMlSettings: configSeq=%u, pre-GetSettings sizeof=%zu\n",
        m.configSeq, sizeof(Settings_t));
    OutputDebugStringA(buf);
    ApplyMlToSettings(m, s);
    vr->SetSettings(s);
    OutputDebugStringA("[ENGINE] SetMlSettings: vr->SetSettings() called, returning S_OK\n");
    return S_OK;
}

HRESULT MpcPlayer::GetMlSettings(MlSettings& m) const
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    ReadMlFromSettings(s, m);
    return S_OK;
}

HRESULT MpcPlayer::SetHdrSettings(const HdrSettings& h)
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    ApplyHdrToSettings(h, s);
    vr->SetSettings(s);
    return S_OK;
}

HRESULT MpcPlayer::GetHdrSettings(HdrSettings& h) const
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    ReadHdrFromSettings(s, h);
    return S_OK;
}

HRESULT MpcPlayer::SetOutSettings(const OutSettings& o)
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    ApplyOutToSettings(o, s);
    vr->SetSettings(s);
    return S_OK;
}

HRESULT MpcPlayer::SetDecklinkCapture(const std::wstring& deviceName)
{
    Log("[DECKLINK][engine] SetDecklinkCapture begin deviceName='%S'", deviceName.c_str());
    if (decklinkDevice_ == deviceName && decklinkMonitor_ && decklinkMonitor_->IsRunning()) {
        Log("[DECKLINK][engine] already capturing '%S' — no-op", deviceName.c_str());
        return S_OK;
    }
    StopDecklinkCapture();

    decklinkDevice_ = deviceName;
    if (deviceName.empty()) {
        Log("[DECKLINK][engine] empty device name — capture off");
        return S_OK;
    }

    decklinkMonitor_ = std::make_unique<DeckLinkMonitor>();
    decklinkMonitor_->SetLogSink(logSink_);
    // Master contract (DESIGN.md): the monitor observes the signal; on a
    // CONFIRMED stable change it advises the engine, which relays to the UI.
    decklinkMonitor_->SetRestartCallback([this](const DeckLinkMonitor::RestartRequest& req) {
        decklinkSettings_.signalLocked = !req.signalLost;
        Log("[DECKLINK][engine] monitor advised: signalLost=%d ics=%d url='%s'",
            req.signalLost, req.ics, req.url.c_str());
        if (!req.url.empty()) {
            pendingDecklinkUrl_.assign(req.url.begin(), req.url.end());
            decklinkSettings_.inputColorSpace = req.ics;
            Notify("decklink:signal");
            return;
        }
        decklinkSettings_.signalLocked = false;
        Notify("decklink:lost");
    });

    const std::string narrow(deviceName.begin(), deviceName.end());
    if (!decklinkMonitor_->Start(narrow)) {
        Log("[DECKLINK][engine] monitor Start FAILED — resetting monitor");
        decklinkMonitor_.reset();
        return HRESULT_FROM_WIN32(ERROR_DLL_NOT_FOUND);
    }
    Log("[DECKLINK][engine] SetDecklinkCapture OK");
    return S_OK;
}

HRESULT MpcPlayer::StopDecklinkCapture()
{
    if (decklinkMonitor_) {
        decklinkMonitor_->Stop();
        decklinkMonitor_.reset();
    }
    decklinkDevice_.clear();
    pendingDecklinkUrl_.clear();
    return S_OK;
}

bool MpcPlayer::GetDecklinkSignalInfo(int& locked, int& colorspace, int& dynamicRange,
                                      int& depth, int& chroma, int& w, int& h,
                                      int& fpsNum, int& fpsDen, int& interlace) const
{
    if (!decklinkMonitor_) return false;
    DeckLinkMonitor::SignalInfo si;
    if (!decklinkMonitor_->GetLastSignalInfo(si)) return false;
    locked        = si.locked;
    colorspace    = si.colorspace;
    dynamicRange  = si.dynamic_range;
    depth         = si.pixel_depth;
    chroma        = si.chroma;
    w             = si.width;
    h             = si.height;
    fpsNum        = si.frame_rate_num;
    fpsDen        = si.frame_rate_den;
    interlace     = si.interlace;
    return true;
}

bool MpcPlayer::GetDeckLinkSourceStats(DeckLinkSourceStats& out) const
{
    out = {};
    if (!decklinkControl_) return false;
    return SUCCEEDED(decklinkControl_->GetStats(&out));
}

int MpcPlayer::GetDecklinkDevices(std::vector<std::string>& names) const
{
    // Direct SDK enumeration (no monitor DLL): safe, bounded, on the caller.
    names.clear();
    CComPtr<IDeckLinkIterator> it;
    if (FAILED(it.CoCreateInstance(g_clsidDeckLinkIterator, NULL, CLSCTX_ALL)) || !it)
        return -1;
    CComPtr<IDeckLink> dev;
    while (it->Next(&dev) == S_OK) {
        CComBSTR bname;
        if (SUCCEEDED(dev->GetDisplayName(&bname)) && bname && *bname) {
            char nm[384] = {};
            WideCharToMultiByte(CP_UTF8, 0, bname, -1, nm, sizeof(nm), NULL, NULL);
            if (nm[0]) names.emplace_back(nm);
        }
        dev.Release();
    }
    return (int)names.size();
}

// Filter's reported cs/eotf → the MPCVR input-colour-space override (pre-connect).
void MpcPlayer::UpdateIcsFromFilter()
{
    DeckLinkSourceStats ds;
    if (!GetDeckLinkSourceStats(ds)) return;
    int ics = 0;
    if      (ds.colorspace == 3 && ds.eotf == 2) ics = ICS_BT2020_PQ;
    else if (ds.colorspace == 3 && ds.eotf == 3) ics = ICS_BT2020_HLG;
    else if (ds.colorspace == 3)                  ics = ICS_BT2020_SDR;
    else if (ds.colorspace == 2)                  ics = ICS_BT709;
    else if (ds.colorspace == 1)                  ics = ICS_BT601;
    decklinkSettings_.inputColorSpace = ics;
    Log("[DECKLINK][engine] filter meta (cs=%d eotf=%d) → ICS %d", ds.colorspace, ds.eotf, ics);
}

// The FILTER is the format-change authority now (its SDK event, raised on its
// worker). We rebuild gracefully — off the UI thread, serialized by the graph
// lock so no two threads ever touch the graph together.
void __cdecl MpcPlayer::DeckLinkRestartBridge(void* ctx)
{
    static_cast<MpcPlayer*>(ctx)->RequestDecklinkRestart();
}

void MpcPlayer::RequestDecklinkRestart()
{
    // Skip a rebuild only when the graph is ACTUALLY SHOWING video (delivered
    // advanced since the last decision — e.g. the format echo right after an
    // open). If the graph is black/gate-dropping (delivered stagnant), ALWAYS
    // rebuild: that is the self-heal path for a stale media type.
    DeckLinkSourceStats ds;
    const bool showing = GetDeckLinkSourceStats(ds) && ds.framesDelivered > m_lastDlvSnapshot;
    m_lastDlvSnapshot = ds.framesDelivered;
    if (showing) {
        Log("[DECKLINK][engine] restart requested while video is flowing — skipped");
        return;
    }
    if (m_restartPending.exchange(true)) {
        Log("[DECKLINK][engine] restart requested while one is pending — skipped");
        return;
    }
    Log("[DECKLINK][engine] rebuild requested (gate-drop/format change) — graceful rebuild on worker");
    std::thread([this]() {
        UpdateIcsFromFilter();
        {
            std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
            if (!decklinkUrl_.empty()) {
                const std::wstring url = decklinkUrl_;
                const HRESULT hrO = Open(url);
                const HRESULT hrP = Play();
                Log("[DECKLINK][engine] rebuild done: Open hr=0x%08X Play hr=0x%08X",
                    (unsigned)hrO, (unsigned)hrP);
            }
        }
        m_restartPending = false;
        Notify("opened");
    }).detach();
}

HRESULT MpcPlayer::SetDecklinkInputColor(int ics)
{
    decklinkSettings_.inputColorSpace = ics;
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    s.iInputColorSpace = ics;
    vr->SetSettings(s);
    return S_OK;
}

HRESULT MpcPlayer::GetOutSettings(OutSettings& o) const
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    Settings_t s;
    vr->GetSettings(s);
    ReadOutFromSettings(s, o);
    return S_OK;
}

HRESULT MpcPlayer::GetProcessorInfo(std::wstring& out) const
{
    out.clear();
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    return vr->GetVideoProcessorInfo(out);
}

HRESULT MpcPlayer::GetMlStats(std::wstring& out) const
{
    out.clear();
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    vr->GetMLStats(out);
    return S_OK;
}

HRESULT MpcPlayer::GetRendererStats(RenderStats& stats) const
{
    stats = RenderStats{};
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    ::RenderStats_t r;
    vr->GetRenderStats(r);
    stats.framesReceived = r.framesReceived;
    stats.framesDrawn    = r.framesDrawn;
    stats.dropped        = r.dropped;
    stats.skipped        = r.skipped;
    stats.failed         = r.failed;
    stats.drawFps        = r.drawFps;
    stats.presentLatencyMs = r.presentLatencyMs;
    return S_OK;
}

// ── Streams (LAV Splitter IAMStreamSelect) ────────────────────────────────────
HRESULT MpcPlayer::GetTracks(std::vector<TrackInfo>& out) const
{
    out.clear();
    if (!splitter_) return S_FALSE;
    CComQIPtr<IAMStreamSelect> sel = splitter_;
    if (!sel) return S_FALSE;
    DWORD count = 0;
    if (FAILED(sel->Count(&count)) || count == 0) return S_OK;
    for (DWORD i = 0; i < count; ++i) {
        AM_MEDIA_TYPE* pmt = nullptr;
        DWORD flags = 0;
        LCID lcid = 0;
        DWORD groupNr = 0;
        WCHAR* pName = nullptr;
        IUnknown* pObj = nullptr;
        IUnknown* pUnk = nullptr;
        if (FAILED(sel->Info(i, &pmt, &flags, &lcid, &groupNr, &pName, &pObj, &pUnk))) continue;
        TrackInfo t;
        t.name = pName ? pName : L"";
        t.active = (flags & AMSTREAMSELECTINFO_ENABLED) != 0;
        t.kind = ClassifyStreamName(t.name);
        out.push_back(t);
        if (pmt) { if (pmt->pbFormat) CoTaskMemFree(pmt->pbFormat); CoTaskMemFree(pmt); }
        if (pName) CoTaskMemFree(pName);
        if (pObj) pObj->Release();
        if (pUnk) pUnk->Release();
    }
    return S_OK;
}

HRESULT MpcPlayer::SelectStream(TrackKind kind, int posIndex)
{
    if (!splitter_) return S_FALSE;
    CComQIPtr<IAMStreamSelect> sel = splitter_;
    if (!sel) return S_FALSE;
    DWORD count = 0;
    if (FAILED(sel->Count(&count))) return S_FALSE;

    int nth = 0;
    for (DWORD i = 0; i < count; ++i) {
        AM_MEDIA_TYPE* pmt = nullptr;
        DWORD flags = 0;
        LCID lcid = 0;
        DWORD groupNr = 0;
        WCHAR* pName = nullptr;
        IUnknown* pObj = nullptr;
        IUnknown* pUnk = nullptr;
        HRESULT hr = sel->Info(i, &pmt, &flags, &lcid, &groupNr, &pName, &pObj, &pUnk);
        std::wstring name = (SUCCEEDED(hr) && pName) ? pName : L"";
        if (pmt) { if (pmt->pbFormat) CoTaskMemFree(pmt->pbFormat); CoTaskMemFree(pmt); }
        if (pName) CoTaskMemFree(pName);
        if (pObj) pObj->Release();
        if (pUnk) pUnk->Release();
        if (FAILED(hr)) continue;
        if (ClassifyStreamName(name) != kind) continue;
        if (nth == posIndex) {
            return sel->Enable(i, AMSTREAMSELECTENABLE_ENABLE);
        }
        ++nth;
    }
    return E_INVALIDARG;
}

HRESULT MpcPlayer::SetAudioTrack(int posIndex)
{
    return SelectStream(TrackKind::Audio, posIndex);
}

HRESULT MpcPlayer::SetSubtitleTrack(int posIndex)
{
    return SelectStream(TrackKind::Subtitle, posIndex);
}

// ── Audio endpoints (WASAPI MMDevice) ────────────────────────────────────────
HRESULT MpcPlayer::GetAudioDevices(std::vector<AudioDeviceInfo>& out) const
{
    out.clear();
    CComPtr<IMMDeviceEnumerator> pEnum;
    HRESULT hr = pEnum.CoCreateInstance(__uuidof(MMDeviceEnumerator));
    if (FAILED(hr)) return hr;

    CComPtr<IMMDevice> defaultDev;
    LPWSTR defaultId = nullptr;
    if (SUCCEEDED(pEnum->GetDefaultAudioEndpoint(eRender, eMultimedia, &defaultDev)) && defaultDev) {
        defaultDev->GetId(&defaultId);
    }

    CComPtr<IMMDeviceCollection> coll;
    if (FAILED(pEnum->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &coll))) {
        if (defaultId) CoTaskMemFree(defaultId);
        return S_OK;
    }
    UINT n = 0;
    coll->GetCount(&n);
    for (UINT i = 0; i < n; ++i) {
        CComPtr<IMMDevice> dev;
        if (FAILED(coll->Item(i, &dev)) || !dev) continue;
        LPWSTR id = nullptr;
        dev->GetId(&id);
        CComPtr<IPropertyStore> props;
        std::wstring name;
        if (SUCCEEDED(dev->OpenPropertyStore(STGM_READ, &props)) && props) {
            PROPVARIANT v; PropVariantInit(&v);
            if (SUCCEEDED(props->GetValue(PKEY_Device_FriendlyName, &v)) && v.vt == VT_LPWSTR && v.pwszVal) {
                name = v.pwszVal;
            }
            PropVariantClear(&v);
        }
        AudioDeviceInfo info;
        info.id = id ? id : L"";
        info.name = name;
        info.isDefault = defaultId && id && wcscmp(defaultId, id) == 0;
        out.push_back(info);
        if (id) CoTaskMemFree(id);
    }
    if (defaultId) CoTaskMemFree(defaultId);
    return S_OK;
}

#include "MpcPlayer.h"

#include <windows.h>
#include <versionhelpers.h>
#include <d3d9.h>
#include <dxva2api.h>
#include <evr.h>
#include <mfidl.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <FilterInterfaces.h>
#include <IVideoRenderer.h>
#include <LAVAudioSettings.h>
#include <atlstr.h>
#include "MpcAudioRenderer/IMpcAudioRenderer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <sstream>
#include <utility>
#include <vector>

namespace {

const CLSID CLSID_MPCVR = {0x71F080AA, 0x8661, 0x4093, {0xB1, 0x5E, 0x4F, 0x69, 0x03, 0xE7, 0x7D, 0x0A}};
const CLSID CLSID_LAVSplitter = {0x171252A0, 0x8820, 0x4AFE, {0x9D, 0xF8, 0x5C, 0x92, 0xB2, 0xD6, 0x6B, 0x04}};
const CLSID CLSID_LAVVideo = {0xEE30215D, 0x164F, 0x4A92, {0xA4, 0xEB, 0x9D, 0x4C, 0x13, 0x39, 0x0F, 0x9F}};
const CLSID CLSID_LAVAudio = {0xE8E73B6B, 0x4CB3, 0x44A4, {0xBE, 0x99, 0x4F, 0x7B, 0xCB, 0x96, 0xE4, 0x91}};
const CLSID CLSID_MpcAudioRenderer = {0x601d2a2b, 0x9cde, 0x40bd, {0x86, 0x50, 0x04, 0x85, 0xe3, 0x52, 0x27, 0x27}};

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

    CComPtr<IBaseFilter> sourceFilter;
    hr = graph_->AddSourceFilter(std::wstring(source).c_str(), L"source", &sourceFilter);
    if (FAILED(hr)) return hr;

    CComPtr<IBaseFilter> splitter;
    hr = splitter.CoCreateInstance(CLSID_LAVSplitter);
    if (FAILED(hr)) return hr;
    hr = graph_->AddFilter(splitter, L"LAV Splitter");
    if (FAILED(hr)) return hr;

    CComPtr<IBaseFilter> decoder;
    hr = decoder.CoCreateInstance(CLSID_LAVVideo);
    if (FAILED(hr)) return hr;
    hr = graph_->AddFilter(decoder, L"LAV Video");
    if (FAILED(hr)) return hr;

    hr = AddRenderer(renderer_);
    if (FAILED(hr) || !renderer_) return FAILED(hr) ? hr : E_FAIL;
    hr = graph_->AddFilter(renderer_, L"Video Renderer");
    if (FAILED(hr)) return hr;

    if (renderTarget_) ConfigureRendererWindow();

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

    CComPtr<IPin> decOut = FindPin(decoder, PINDIR_OUTPUT);
    CComPtr<IPin> rndIn = FindPin(renderer_, PINDIR_INPUT);
    if (!decOut || !rndIn) return E_POINTER;
    hr = graph_->Connect(decOut, rndIn);
    if (FAILED(hr)) return hr;

    hr = graph_.QueryInterface(&mediaControl_);
    if (FAILED(hr)) return hr;
    hr = graph_.QueryInterface(&mediaSeeking_);
    if (FAILED(hr)) return hr;
    graph_.QueryInterface(&mediaEvent_);

    splitter_ = splitter;
    ConnectAudio(splitter);
    ApplyVolume();

    if (renderTarget_) {
        if (CComQIPtr<IVideoWindow> pVW = renderer_) pVW->put_Visible(OATRUE);
        ResizeVideo();
    }
    return S_OK;
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
}

void ReadHdrFromSettings(const Settings_t& s, MpcPlayer::HdrSettings& h)
{
    h.preferDoVi = s.bHdrPreferDoVi;
    h.convertToSdr = s.bConvertToSdr;
    h.sdrDisplayNits = s.iSDRDisplayNits;
    h.toggleDisplay = s.iHdrToggleDisplay;
    h.displayMaxNits = s.iHdrDisplayMaxNits;
    h.osdBrightness = s.iHdrOsdBrightness;
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

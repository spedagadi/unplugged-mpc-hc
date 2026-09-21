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

MpcPlayer::MpcPlayer()
{
    // Live-telemetry refresh worker: snapshots renderer/filter stats off the
    // UI thread (~1 s cadence). The UI reads only the cache — it must never
    // touch the renderer/card directly (see GetLive* docs).
    m_liveThread = std::thread([this]() {
        while (!m_liveStop) {
            RefreshLive();
            std::this_thread::sleep_for(std::chrono::milliseconds(1000));
        }
    });
}

MpcPlayer::~MpcPlayer()
{
    m_liveStop = true;
    if (m_liveThread.joinable()) m_liveThread.join();
    Shutdown();   // ordered card+graph teardown; idempotent
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

    m_liveReady = false;   // live cache must not touch the renderer mid-graph-op
    if (source.empty()) return E_INVALIDARG;

    Log("[GRAPH] Open: starting ordered teardown of the old graph");
    TeardownDecklinkGraph();
    Log("[GRAPH] Open: teardown complete — building the new graph");

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
    m_liveReady = true;   // graph + renderer fully wired — live cache may touch them now
    return S_OK;
}

// DeckLink ordered teardown (DESIGN.md): stop the feeder at the source,
// disconnect the renderer, THEN join the source's threads. Never drop a graph
// while the source's delivery thread can be inside the renderer — that
// join-into-live-receive is the movie→menu hang.
//
// Both the rebuild path (Open) and the Stop path call this, so the order exists
// in exactly one place. Executor only, always under m_graphMtx.
void MpcPlayer::TeardownDecklinkGraph()
{
    // Each step is bracketed BEFORE and AFTER. This is the destructive sequence —
    // a fault here takes the process with it, and the surviving log cannot say
    // how far it got. With the brackets, the last "…: enter" with no matching
    // "…: done" names the exact step that died, which is the difference between
    // "the renderer faulted during StopDelivery" and "during graph release".
    if (decklinkControl_) {
        Log("[TEARDOWN] 1/4 StopDelivery (halt the feeder) — enter");
        decklinkControl_->StopDelivery();     // SDK stops invoking — no new frames
        Log("[TEARDOWN] 1/4 StopDelivery — done");
        Log("[TEARDOWN] 2/4 disconnect source↔renderer pins — enter");
        DisconnectDecklinkPins();             // in-flight Deliver now returns fast
        Log("[TEARDOWN] 2/4 disconnect pins — done");
        Log("[TEARDOWN] 3/4 StopCapture (join worker+forwarder, release SDK) — enter");
        decklinkControl_->StopCapture();      // join worker+forwarder (safe now) + release SDK
        Log("[TEARDOWN] 3/4 StopCapture — done");
        // graph_.Release() below drops the filter object; its destructor's
        // StopCaptureSession finds non-joinable threads — no wait.
    }

    Log("[TEARDOWN] 4/4 stop graph + release filters/renderer — enter");
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
    Log("[TEARDOWN] 4/4 stop graph + release — done");

    // Release the PREVIOUS capture session here — the quiescent point. Its
    // destructor joins the SDK worker; that join measured 47 ms at this stage
    // because the ordered script has already stopped and disconnected
    // everything. Doing it here is what removes the detached retire thread, and
    // with it the only remaining actor that destroyed a filter while a live
    // graph was delivering into the renderer. Bracketed, so a fault here names
    // itself rather than looking like the next component's.
    if (m_retiredControl) {
        Log("[TEARDOWN] 5/5 release the retired capture session (its destructor joins the SDK worker) — enter");
        m_retiredControl.Release();
        Log("[TEARDOWN] 5/5 release the retired capture session — done");
    }
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

void MpcPlayer::Shutdown()
{
    Log("[DECKLINK][engine] Shutdown (ordered teardown)");
    // Stop the DECIDER first: while it is alive it can still emit an intent, and
    // an intent arriving mid-shutdown is a graph op racing the teardown.
    if (ingest_) {
        ingest_->Stop();
        ingest_.reset();
    }
    // Then arm the executor stop so no queued op can start while we tear down.
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopStop = true;
        m_gopQueued = false;
        m_gopApplyQueued = false;
        m_gopIntent = IngestController::Intent::None;
    }
    m_gopCv.notify_all();

    {
        // DESIGN.md order: STOP the feeder at the SDK, disconnect the renderer,
        // join the source's threads — only THEN stop the graph. mediaControl_>
        // Stop() waits on the renderer whose present thread is fed by our
        // forwarder; without the ordered stop it never returns (observed: exit
        // path zombie — window gone, capture still delivering).
        std::lock_guard<std::recursive_mutex> lk(m_graphMtx);
        if (decklinkControl_) {
            decklinkControl_->StopDelivery();
            DisconnectDecklinkPins();
            decklinkControl_->StopCapture();
        }
        if (mediaControl_) mediaControl_->Stop();
    }

    if (m_gopThread.joinable()) m_gopThread.join();
    if (decklinkMonitor_) {
        decklinkMonitor_->Stop();
        decklinkMonitor_.reset();
    }
    decklinkDevice_.clear();
    pendingDecklinkUrl_.clear();
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

    // New graph => new MPCVR => its constructor re-reads the registry, so the
    // settings the UI pushed into the previous instance no longer apply. The
    // counter lets the UI notice and re-push (see "gen" in GetUiStatusJson).
    ++graphGen_;
    Log("[GRAPH] BuildGraph enter — generation now %u", (unsigned)graphGen_);

    // Hold the previous direct filter for release by the EXECUTOR, at the next
// teardown — not by a detached thread (2026-09-21).
    //
    // This used to hand the old filter to a detached 3-second cleanup thread,
    // which ran its destructor — joining the SDK worker, stopping streams —
    // WHILE the new graph was live and delivering into the renderer. DESIGN.md
    // invariant 5 forbids exactly that shape ("No .detach() threads"; "Never
    // create a thread whose exit waits on a thread that is inside the component
    // the waiting path destroys"), and it landed on the fault twice: the log
    // ends at a `[DECKLINK][src] StopDelivery` carrying no `[TEARDOWN]` bracket,
    // so it came from a destructor, ~2 s after a rebuild — inside the retire
    // thread's own cycle.
    //
    // TeardownDecklinkGraph releases it instead: at that point the old graph is
    // stopped, disconnected and joined, and the new one does not exist yet. That
    // is the quiescent point the ordered script already defines, and the join
    // measured 47 ms there rather than blocking. The UI never waits either — the
    // executor is not the UI thread, which was the whole reason the detached
    // thread was added.
    if (decklinkControl_) {
        // Hand it to the executor's next teardown instead of a detached thread.
        // Any previously-held one is released here too — this runs ON the
        // executor, under m_graphMtx, between graphs.
        m_retiredControl.Release();
        m_retiredControl = std::move(decklinkControl_);
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
    Log("[GRAPH] adding the renderer filter to the graph — enter");
    hr = graph_->AddFilter(renderer_, L"Video Renderer");
    Log("[GRAPH] renderer added hr=0x%08X", (unsigned)hr);
    if (FAILED(hr)) return hr;

    // Apply the user's settings BEFORE the pins negotiate. Any setting that
    // decides which shader gets built (bConvertToSdr, the VP formats, the input
    // colour space) is consumed during negotiation, so pushing it afterwards only
    // works if something forces a re-negotiation — which is how Convert to SDR
    // ended up applying on some starts and not others.
    //
    // m_inGraphBuild makes this push unrestricted: the pins are not connected, the
    // renderer is not active, and Configure()'s destructive paths are all behind
    // an `if (!m_pFilter->GetActive()) return;` — so every field, including the
    // rebuild-only ones, is safe here. This is the one place a held-back setting
    // is actually delivered.
    m_inGraphBuild = true;
    ApplyPendingSettings();
    m_inGraphBuild = false;

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

    // Last word on the input colour space, for every source kind. By here the graph
    // has negotiated, so videoStreamInfo_ carries the transfer function the signal
    // actually declares — which is what settles BT.2020 vs BT.709 (see
    // ApplyIcsFromMediaType). Placed after the connects so it wins over the
    // monitor's advice and the decoder-path guess above.
    if (bDeckLinkDirect || bDeckLink) {
        Log("[GRAPH] applying the input colour space from the negotiated media type — enter");
        ApplyIcsFromMediaType();
        Log("[GRAPH] input colour space applied — done");
    }

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
        if (SUCCEEDED(hr)) {
            // BISECT PROBE (2026-09-21): the abort (0xc0000409, no handler, no
            // dump) fires at exactly this handoff — the renderer immediately
            // calls a raw function pointer into s3engine.dll, which is built
            // WITHOUT /guard:cf (see tools/s3engine/build_s3engine.bat), so its
            // functions are not in the process CFG bitmap and the renderer's
            // guarded indirect call can fail-fast. Setting this to true rebuilds
            // the sink path; false disables it to prove the linkage.
            constexpr bool kAttachRendererSink = false;
            if (kAttachRendererSink) {
                // Inject the OPTIONAL high-level log sink (IMpcvrLogSink). The
                // renderer's own account of init, media-type/signal changes and
                // deinit then lands in THIS log, on this clock, in sequence with
                // the engine's and the signal monitor's lines.
                if (CComQIPtr<IMpcvrLogSink> ls = out) {
                    ls->SetLogSink(this, &MpcPlayer::DeckLinkSourceLogBridge);
                    Log("[ENGINE] renderer log sink attached (IMpcvrLogSink) — renderer lines now share this log");
                } else {
                    Log("[ENGINE] renderer exposes no IMpcvrLogSink — renderer will not log");
                }
            } else {
                Log("[ENGINE] renderer log sink ATTACH DISABLED (bisect probe: CFG cross-module callback)");
            }
            return S_OK;
        }
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
    s.fMLGammaTopUp = m.gammaTopUp;
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
    m.gammaTopUp = s.fMLGammaTopUp;
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

// Fields the renderer CANNOT take on a live graph, and why.
//
// DX11VideoProcessor::Configure() is a cascade of early returns: for
// changeHDR / changeInputColor / changeWindow / changeVP / changeRTXVideoHDR it
// calls ReleaseSwapChain() / m_pFilter->Init(true) / InitMediaType() and RETURNS.
// Everything after that (the comment says "changes that do not require a global
// rebuild") frees and recreates GPU resources — shaders and textures — which the
// render thread samples WITHOUT holding m_RendererLock (CMpcVideoRenderer::
// DoRenderSample takes no lock at all, and neither does ProcessSample).
//
// So a live push of any of these races the render thread with no mutual
// exclusion. That is not theoretical: it is the access violation at a fixed
// address in MpcVideoRenderer64.ax this project has hit repeatedly, most
// recently `Configure — renegotiation triggered … hdr=1 active=1` immediately
// followed by InitMediaType on a delivering graph.
//
// The benign flags are deliberately NOT in this list: changeLuminanceParams is a
// constant-buffer write (SetShaderLuminanceParams) and changeResizeStats only
// recomputes statistics — neither frees anything — which is why the tone-map and
// grade rails keep working live.
//
// Returns true when anything here differs, and in that case restores dst's copies
// to the live values so the push cannot act on them. The caller then rebuilds.
bool HoldBackNegotiationFields(Settings_t& dst, const Settings_t& live)
{
    bool differs = false;
    auto hold = [&differs](auto& d, const auto& l) {
        if (d != l) { differs = true; d = l; }
    };

    // Configure() -> changeHDR (media-type re-derivation)
    hold(dst.iHdrLocalToneMappingType, live.iHdrLocalToneMappingType);
    hold(dst.iHdrToggleDisplay,        live.iHdrToggleDisplay);
    hold(dst.bHdrPassthrough,          live.bHdrPassthrough);
    // Configure() -> changeVP (video-processor re-init)
    hold(dst.bHdrPreferDoVi,           live.bHdrPreferDoVi);
    hold(dst.bVPScaling,               live.bVPScaling);
    hold(dst.iVPDeinterlacing,         live.iVPDeinterlacing);
    hold(dst.VPFmts.bNV12,             live.VPFmts.bNV12);
    hold(dst.VPFmts.bP01x,             live.VPFmts.bP01x);
    hold(dst.VPFmts.bYUY2,             live.VPFmts.bYUY2);
    hold(dst.VPFmts.bOther,            live.VPFmts.bOther);
    // Configure() -> changeRTXVideoHDR
    hold(dst.bVPRTXVideoHDR,           live.bVPRTXVideoHDR);
    // Configure() -> changeWindow (swap chain / device)
    hold(dst.iSwapEffect,              live.iSwapEffect);
    hold(dst.bExclusiveFS,             live.bExclusiveFS);
    // Configure() -> rebuilds shaders / textures the render thread is sampling
    hold(dst.iTexFormat,               live.iTexFormat);
    hold(dst.iChromaScaling,           live.iChromaScaling);
    hold(dst.iUpscaling,               live.iUpscaling);
    hold(dst.iDownscaling,             live.iDownscaling);
    hold(dst.bUseDither,               live.bUseDither);
    hold(dst.iVPSuperRes,              live.iVPSuperRes);
    hold(dst.iHdrOsdBrightness,        live.iHdrOsdBrightness);
    return differs;
}

void ApplyHdrToSettings(const MpcPlayer::HdrSettings& h, Settings_t& s)
{
    s.bHdrPreferDoVi = h.preferDoVi;
    s.bConvertToSdr = h.convertToSdr;
    s.iSDRDisplayNits = h.sdrDisplayNits;
    s.iHdrToggleDisplay = h.toggleDisplay;
    s.iHdrDisplayMaxNits = h.displayMaxNits;
    s.fHdrDisplayMinNits = h.displayMinNits;
    s.iOutputGamut = h.outputGamut;
    s.fHdrTitlePeakNits = h.titlePeakNits;
    s.fHdrHableKnee = h.hableKnee;
    s.iHdrOsdBrightness = h.osdBrightness;
    s.iHdrLocalToneMappingType = h.toneMapCurve;
    s.bHDRPassthroughRaw = h.hdrPassthroughRaw;
    s.iExperimentalToneMapper = h.experimentalToneMapper;
    s.fToneLutContrast = h.toneLutContrast;
}

void ReadHdrFromSettings(const Settings_t& s, MpcPlayer::HdrSettings& h)
{
    h.preferDoVi = s.bHdrPreferDoVi;
    h.convertToSdr = s.bConvertToSdr;
    h.sdrDisplayNits = s.iSDRDisplayNits;
    h.toggleDisplay = s.iHdrToggleDisplay;
    h.displayMaxNits = s.iHdrDisplayMaxNits;
    h.displayMinNits = s.fHdrDisplayMinNits;
    h.outputGamut = s.iOutputGamut;
    h.titlePeakNits = s.fHdrTitlePeakNits;
    h.hableKnee = s.fHdrHableKnee;
    h.osdBrightness = s.iHdrOsdBrightness;
    h.toneMapCurve = s.iHdrLocalToneMappingType;
    h.hdrPassthroughRaw = s.bHDRPassthroughRaw;
    h.experimentalToneMapper = s.iExperimentalToneMapper;
    h.toneLutContrast = s.fToneLutContrast;
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


// Ask the graph owner to apply remembered settings. This is the UI's entry
// point, and it deliberately does NOT write the renderer itself.
//
// Why (2026-09-21): the UI thread used to call ApplyPendingSettings() directly,
// holding no m_graphMtx, while the executor could be mid-teardown. SetSettings →
// Configure → for a changed changeHDR row → ReleaseSwapChain() + InitMediaType()
// is a media-type renegotiation on a live renderer, from a thread that does not
// own the graph — the fault class already recorded for the HDR-passthrough
// toggle. The setting is remembered here; the executor applies it, serialized
// against every graph mutation, which is also what makes a push that arrives
// during a rebuild land on the NEW renderer instead of a dying one.
void MpcPlayer::QueueSettingsApply()
{
    if (!m_gopThread.joinable()) {
        // No capture session, so there is no executor and no rebuild can be in
        // flight: the graph is only mutated by UI transport calls, which are on
        // THIS thread. Applying directly keeps live tuning working in file
        // playback (Media Player mode) exactly as before — the serialization
        // this function adds is only needed where a rebuild can race, which is
        // the capture path.
        ApplyPendingSettings();
        return;
    }
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopApplyQueued = true;    // coalescing: a burst of rows → one apply
    }
    m_gopCv.notify_one();
}

void MpcPlayer::ApplySettingsOp()
{
    ApplyPendingSettings();
}

HRESULT MpcPlayer::SetMlSettings(const MlSettings& m)
{
    pendingMl_ = m;
    hasMl_ = true;
    QueueSettingsApply();
    return renderer_ ? S_OK : S_FALSE;
}

HRESULT MpcPlayer::SaveRendererSettings()
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return S_FALSE;
    // Persist to HKCU\Software\MPC-BE Filters\MPC Video Renderer so a rebuilt
    // graph comes back up with these values instead of a stale key.
    return vr->SaveSettings();
}

// Grab the frame the renderer is CURRENTLY producing into a 32-bit BMP.
//
// This exists because "the picture did not change" is the hardest class of bug
// in this pipeline to argue about: the setting is applied, the status echo
// agrees, and the only remaining question — did it reach the pixels — has no
// answer anywhere in the engine. GetCurrentImage runs the real pipeline (the
// post-scale ring, so the tone-map correction is in it), which makes an A/B of
// two settings a byte comparison instead of a memory of what it looked like.
HRESULT MpcPlayer::GrabFrame(const std::string& utf8Path)
{
    if (!renderer_ || utf8Path.empty()) return S_FALSE;

    CComQIPtr<IBasicVideo> bv = renderer_;
    if (!bv) {
        Log("[ENGINE] GrabFrame: the renderer exposes no IBasicVideo");
        return E_NOINTERFACE;
    }

    long size = 0;
    HRESULT hr = bv->GetCurrentImage(&size, nullptr);   // ask for the size first
    if (FAILED(hr) || size <= 0) {
        Log("[ENGINE] GrabFrame: GetCurrentImage(size) hr=0x%08X size=%ld", (unsigned)hr, size);
        return hr;
    }

    std::vector<BYTE> dib((size_t)size);
    hr = bv->GetCurrentImage(&size, (long*)dib.data());
    if (FAILED(hr)) {
        Log("[ENGINE] GrabFrame: GetCurrentImage(data) hr=0x%08X", (unsigned)hr);
        return hr;
    }

    wchar_t wpath[MAX_PATH] = {};
    MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, wpath, MAX_PATH);
    FILE* f = nullptr;
    if (_wfopen_s(&f, wpath, L"wb") != 0 || !f) {
        Log("[ENGINE] GrabFrame: cannot open the output file");
        return E_FAIL;
    }

    // The buffer is a BITMAPINFOHEADER followed by top-down BGRX rows — that is
    // the layout callers of IBasicVideo::GetCurrentImage expect, so it is written
    // out as a self-describing .bmp with the 14-byte file header in front.
    const BITMAPINFOHEADER* bih = (const BITMAPINFOHEADER*)dib.data();
    const DWORD offBits = (DWORD)(sizeof(BITMAPFILEHEADER) + bih->biSize);
    BITMAPFILEHEADER fh = {};
    fh.bfType    = 0x4D42;   // 'BM'
    fh.bfOffBits = offBits;
    fh.bfSize    = offBits + bih->biSizeImage;
    fwrite(&fh, sizeof(fh), 1, f);
    fwrite(dib.data(), 1, (size_t)size, f);
    fclose(f);

    // Mean luma of the captured frame — the objective answer to "is the image
    // black?". This is what told us the renderer PRESENTS 50fps while the screen
    // reads black for an entirely reasons outside the counters; the luma number
    // separates "black pixels out of the renderer" from "window not on screen".
    double lumaSum = 0.0;
    size_t lumaCount = 0;
    const BYTE* px = dib.data() + sizeof(BITMAPINFOHEADER);
    const size_t pxBytes = std::min((size_t)bih->biSizeImage,
                                    (size_t)size - sizeof(BITMAPINFOHEADER));
    for (size_t i = 0; i + 2 < pxBytes && i < 8ull * 1024 * 1024; i += 4) {
        lumaSum += 0.114 * px[i] + 0.587 * px[i + 1] + 0.299 * px[i + 2];
        lumaCount++;
    }
    Log("[ENGINE] GrabFrame: wrote %ldx%ld to %s  meanLuma=%.2f/255",
        (long)bih->biWidth, (long)bih->biHeight, utf8Path.c_str(),
        lumaCount ? lumaSum / (double)lumaCount : -1.0);
    return S_OK;
}

HRESULT MpcPlayer::LoadCubeLut(const std::string& utf8Path, int mode)
{
    if (!renderer_) return S_FALSE;
    CComQIPtr<IExFilterConfig> cfg = renderer_;
    if (!cfg) return S_FALSE;

    // The filter's handler ignores a zero-size blob, so an unload is sent as a
    // single NUL — which trims to the empty path that means "clear".
    static const char kNul = '\0';
    const bool unloading = utf8Path.empty();
    LPVOID p = unloading ? (LPVOID)&kNul : (LPVOID)utf8Path.data();
    const int n = unloading ? 1 : (int)utf8Path.size();
    const HRESULT hr = cfg->Flt_SetBin("cmd_loadCubeLut", p, n);

    // Mode is a separate command so A/B-ing modes never re-parses the file.
    // Sent after the load, which leaves the mode untouched.
    if (mode >= 0 && mode <= 3) {
        cfg->Flt_SetInt("cubeLutMode", mode);
    }
    return hr;
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
    // Remember first, always — the renderer may not exist yet.
    pendingHdr_ = h;
    hasHdr_ = true;
    QueueSettingsApply();
    return renderer_ ? S_OK : S_FALSE;
}

// Push the remembered settings intent onto whatever renderer exists right now.
//
// The bug this closes: these pushes used to bail with S_FALSE whenever renderer_
// was null — while ApplySettingsFlat still returned S_OK to the caller. Anything
// the UI sent before the graph existed was therefore silently lost, and the
// renderer came back up on Settings_t defaults. Settings consumed at media-type
// negotiation — above all bConvertToSdr, which decides WHICH converter shader gets
// built — then stayed wrong until some later graph rebuild happened to re-push,
// which is exactly the "convert to SDR is intermittent" behaviour.
//
// Calling it from BuildGraph, before the pins connect, follows the rule
// ApplyDecklinkColorToRenderer() already follows for the input colour space: a
// setting that shapes negotiation has to be in place before negotiation happens.
void MpcPlayer::ApplyPendingSettings()
{
    if (!renderer_) return;
    CComQIPtr<IVideoRenderer> vr = renderer_;
    if (!vr) return;

    Settings_t s;
    vr->GetSettings(s);          // s = what the renderer holds right now
    const Settings_t live = s;   // keep the live values for the hold-back below
    if (hasHdr_) {
        // The card's own ST 2086 MaxCLL is the real content peak, and it WINS over
        // the panel's Title peak row — that row stays the fallback for signals with
        // no static metadata (DV, SDR), which is why nothing is overridden when
        // hasHdrStaticMeta is 0.
        //
        // Applied HERE, on the settings-apply path, and deliberately NOT in
        // RefreshLive: that runs on the ~1 s snapshot worker, and writing to the
        // renderer from there (which rebuilds the tone LUT) stalled the playback
        // clock past the UI's 5 s signal-loss timeout, so capture restarted every
        // 8 s and the acquiring overlay never cleared.
        HdrSettings h = pendingHdr_;
        DeckLinkSourceStats dl{};
        if (GetLiveDeckLinkSourceStats(dl) && dl.hasHdrStaticMeta) {
            if (h.titlePeakNits != dl.hdrMaxCLL) {
                Log("[ENGINE] Title peak <- signal MaxCLL=%.0f (panel %.0f)  [ST 2086 from the card]",
                    dl.hdrMaxCLL, h.titlePeakNits);
            }
            h.titlePeakNits = dl.hdrMaxCLL;
        }
        ApplyHdrToSettings(h, s);
    }
    if (hasMl_)  ApplyMlToSettings(pendingMl_, s);
    if (hasOut_) ApplyOutToSettings(pendingOut_, s);
    // Instrumented 2026-09-20: SetSettings rebuilds the tone LUT and can BLOCK
    // indefinitely while the graph is mid-rebuild. ENTER without RETURN in the
    // engine log is the smoking gun for the UI freeze.
    // On a LIVE graph, hold back everything the renderer cannot take safely, so this
// push is structurally incapable of renegotiating a media type or freeing a
// resource the render thread is sampling. Inside BuildGraph (m_inGraphBuild) the
// pins are not connected yet, so everything IS safe and goes through — which is
// also how the held-back values eventually take effect.
    bool needRebuild = false;
    if (!m_inGraphBuild) {
        needRebuild = HoldBackNegotiationFields(s, live);
        if (needRebuild) {
            Log("[ENGINE] settings: a rebuild-only row changed (curve/toggle/dovi/swap/"
                "scaling/tex/dither/osd). Held back from the live renderer and rebuilding "
                "instead — BuildGraph re-applies it before the pins connect.");
        }
    }

    Log("[ENGINE] ApplyPendingSettings: SetSettings ENTER");
    vr->SetSettings(s);
    Log("[ENGINE] ApplyPendingSettings: SetSettings RETURN");
    Log("[ENGINE] ApplyPendingSettings: hdr=%d ml=%d out=%d pushed rebuild=%d",
        hasHdr_ ? 1 : 0, hasMl_ ? 1 : 0, hasOut_ ? 1 : 0, needRebuild ? 1 : 0);

    if (needRebuild) RequestSettingsRebuild();
}

// Ask the graph owner to rebuild, which is how a rebuild-only setting reaches the
// renderer: BuildGraph applies every pending group BEFORE the pins connect, so
// the value lands in the media-type decision it shapes, with no live
// renegotiation and no resource freed under the render thread.
void MpcPlayer::RequestSettingsRebuild()
{
    if (!m_gopThread.joinable()) return;   // no capture graph — nothing to rebuild
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopIntent = IngestController::Intent::Reload;
        // m_gopUrl is left as-is; RunDecklinkRebuild falls back to decklinkUrl_.
        m_gopQueued = true;
    }
    Log("[DECKLINK][engine] settings rebuild requested — Reload posted to the executor");
    m_gopCv.notify_one();
}

// Ask the graph owner to rebuild for a stated reason. Same Reload intent as a
// signal change, distinguished only in the log, so the executor is the single
// place a rebuild is ever performed.
void MpcPlayer::RequestDecklinkReload(const char* why)
{
    if (!m_gopThread.joinable()) return;
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopIntent = IngestController::Intent::Reload;
        // m_gopUrl is left as-is; RunDecklinkRebuild falls back to decklinkUrl_.
        m_gopQueued = true;
    }
    Log("[DECKLINK][engine] Reload requested (%s) — posted to the executor", why);
    m_gopCv.notify_one();
}

// Delivery-stall monitor — "frames displayed" vs "frames received", built to
// the rules this project logged during the 2026-09-21 crash chase.
//
// The first version keyed on the SOURCE's counters (delivered/gate) and missed
// the actual blank: the user observed "Renderer Recv" and "Delivered" BOTH
// advancing while the screen stayed black — the graph and the filter are fine,
// only the PRESENT stops. "Displayed" is the renderer's own framesDrawn, which
// this tick already reads. So there are TWO stalls to catch:
//
//   A) DISPLAYED frozen while frames ARE being received (recv/delv advancing):
//      the present path has stopped — exactly the observed blank. Reload fixes
//      it by bringing up a fresh renderer that re-inits the swap chain/present.
//   B) DELIVERED frozen while ARRIVED advances and GATE climbs: the size gate
//      discarding every frame — the stale-media-type variant from before.
//
// Either fires after kStallTicks consecutive seconds, while Playing and locked,
// and posts a Reload to the executor (coalesced, so it cannot storm). "Arrived
// and delivered both frozen" is the card having stopped — not ours to force.
void MpcPlayer::CheckDeliveryStall(const DeckLinkSourceStats& dl, const RenderStats& r)
{
    constexpr int          kStallTicks = 2;   // 2 consecutive seconds
    const bool running = (snapshot_.state == State::Playing) && renderer_;
    if (!running || !decklinkSettings_.signalLocked) {
        m_stallTicks = 0;
        m_stallLastDelv = dl.framesDelivered;
        m_stallLastArrived = dl.framesArrived;
        m_stallLastGate = dl.gateDropped;
        m_stallLastDrawn = r.framesDrawn;
        m_stallLastRecv  = r.framesReceived;
        return;
    }

    const bool displayedAdvancing = r.framesDrawn != m_stallLastDrawn;
    const bool receivedAdvancing  = r.framesReceived != m_stallLastRecv;
    const bool arriving     = dl.framesArrived != m_stallLastArrived;
    const bool gateClimbing = dl.gateDropped > m_stallLastGate;
    m_stallLastDrawn    = r.framesDrawn;
    m_stallLastRecv     = r.framesReceived;
    m_stallLastDelv    = dl.framesDelivered;
    m_stallLastArrived = dl.framesArrived;
    m_stallLastGate    = dl.gateDropped;

    if (displayedAdvancing) {                 // actually presented — healthy
        m_stallTicks = 0;
        return;
    }

    // displayed frozen here. Is anything still being received?
    const bool typeMismatch = arriving && gateClimbing;   // (B) size-gate signature
    const bool receiving    = receivedAdvancing;          // (A) filter still delivers
    if (!typeMismatch && !receiving) return;              // card stopped — not ours

    if (++m_stallTicks < kStallTicks) return;

    m_stallTicks = 0;
    if (receiving) {
        Log("[DECKLINK][engine] DISPLAY STALL CONFIRMED: framesDrawn frozen for %d s while "
            "frames are still received (delv=%llu drawn=%u) — presenting stopped, requesting a rebuild",
            (int)kStallTicks, (unsigned long long)dl.framesDelivered, (unsigned)r.framesDrawn);
        RequestDecklinkReload("display stall (receiving but not presenting)");
    } else {
        Log("[DECKLINK][engine] DELIVERY STALL CONFIRMED: delivered frozen for %d s with gate "
            "dropping %llu type-mismatched frames — stale media type, requesting a rebuild",
            (int)kStallTicks, (unsigned long long)dl.gateDropped);
        RequestDecklinkReload("delivery stall (stale media type)");
    }
}

// Source-format change monitor — the resolution the DECIDER could not see.
//
// The monitor DLL reports no dimensions (every poll reads 0x0 0/0), so a pure
// resolution change never produced a fact and the graph stayed on the OLD size —
// the observed DV→menu black (the filter reported src=4K50 while its own media
// type and frames stayed 1080p50, and the renderer drew the wrong-size stream).
// The SOURCE filter is the dimension measurer: GetStats carries the true frame
// dims and self-heals them. So when THOSE settle on a new format, the decider
// asks the executor to rebuild onto it.
void MpcPlayer::CheckSourceFormatChange(const DeckLinkSourceStats& dl)
{
    constexpr int kSettleTicks = 2;      // two consecutive seconds
    const bool valid = dl.width > 0 && dl.height > 0 && dl.fpsNum > 0 && dl.fpsDen > 0;
    if (!valid) { m_srcChangeTicks = 0; return; }

    const bool firstSeen = (m_srcCommittedW == 0 && m_srcCommittedH == 0);
    if (firstSeen) {                       // baseline, never fire on the first
        m_srcCommittedW = dl.width; m_srcCommittedH = dl.height;
        m_srcCommittedN = dl.fpsNum;  m_srcCommittedD = dl.fpsDen;
        m_srcChangeTicks = 0;
        return;
    }

    const bool same = (dl.width == m_srcCommittedW && dl.height == m_srcCommittedH &&
                       dl.fpsNum == m_srcCommittedN && dl.fpsDen == m_srcCommittedD);
    if (same) { m_srcChangeTicks = 0; return; }

    if (++m_srcChangeTicks < kSettleTicks) return;

    Log("[DECKLINK][engine] SOURCE FORMAT CHANGED: %dx%d@%d/%d held for %d s (was %dx%d@%d/%d) — "
        "requesting a rebuild onto the new format",
        (int)dl.width, (int)dl.height, (int)dl.fpsNum, (int)dl.fpsDen, (int)kSettleTicks,
        (int)m_srcCommittedW, (int)m_srcCommittedH, (int)m_srcCommittedN, (int)m_srcCommittedD);
    m_srcCommittedW = dl.width; m_srcCommittedH = dl.height;
    m_srcCommittedN = dl.fpsNum;  m_srcCommittedD = dl.fpsDen;
    m_srcChangeTicks = 0;
    RequestDecklinkReload("source format change (dimension-blind monitor covered)");
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
    pendingOut_ = o;
    hasOut_ = true;
    QueueSettingsApply();
    return renderer_ ? S_OK : S_FALSE;
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

    // The monitor's ONLY outbound edge: a settled fact, handed to the decider.
    // It used to post a graph rebuild from here, which is what made a measurer a
    // lifecycle decider. Nothing in this callback touches the graph, and nothing
    // acts on it: OnFact records and wakes.
    decklinkMonitor_->SetFactCallback([this](const DeckLinkMonitor::SignalFact& f) {
        if (ingest_) ingest_->OnFact(f);
    });

    // The decider: consumes facts and emits an intent. It cannot act — its sink
    // only queues an op for the executor below.
    ingest_ = std::make_unique<IngestController>();
    ingest_->SetLogSink(logSink_);
    ingest_->SetDecisionSink([this](const IngestController::Decision& d) {
        HandleIngestDecision(d);
    });

    // The ops-queue executor — the ONLY thread that may mutate the capture
    // card + graph. Started with the monitor, joined at stop.
    if (!m_gopThread.joinable()) {
        m_gopStop = false;
        m_gopQueued = false;
        m_gopApplyQueued = false;
        m_gopThread = std::thread([this]() { DecklinkOpLoop(); });
        Log("[DECKLINK][engine] ops-queue executor started");
    }
    ingest_->Start();

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
    // Order matters: stop the DECIDER first, so it cannot emit a new intent while
    // we are tearing its consumers down; then the monitor that feeds it; then the
    // executor. Reverse of how they were started.
    if (ingest_) {
        ingest_->Stop();
        ingest_.reset();
    }
    if (decklinkMonitor_) {
        decklinkMonitor_->Stop();
        decklinkMonitor_.reset();
    }
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopStop = true;
        m_gopQueued = false;
        m_gopApplyQueued = false;
        m_gopIntent = IngestController::Intent::None;
    }
    m_gopCv.notify_all();
    if (m_gopThread.joinable()) m_gopThread.join();
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

void MpcPlayer::RefreshLive()
{
    // Runs on the DEDICATED refresh thread — never the UI. NO renderer/graph
    // access until the graph exists: the worker can race the UI's renderer_
    // assignment at init (a CComPtr read + AddRef on a mid-create object AVs).
    if (!m_liveReady) return;
    // Reads may block on the renderer during a signal blip; that cost belongs
    // here, not the UI.
    RenderStats         r;
    std::wstring        ml;
    MlSettings          mls{};
    HdrSettings         hd{};
    OutSettings         ou{};
    DeckLinkSourceStats dl{};
    GetRendererStats(r);
    GetMlStats(ml);
    GetMlSettings(mls);
    GetHdrSettings(hd);
    GetOutSettings(ou);
    GetDeckLinkSourceStats(dl);

    // The signal-driven Title peak is applied in ApplyPendingSettings, NOT here.
    //
    // This function is a SNAPSHOT — see the contract in MpcPlayer.h. Writing to the
    // renderer from it (GetSettings + SetSettings, which rebuilds the tone LUT) was
    // tried and stalled the playback clock long enough that the UI's signal monitor
    // declared NO_SIGNAL and restarted capture every 8 s (its 5 s loss timeout plus
    // its 3 s cooldown), so the acquiring overlay re-appeared forever. Nothing in
    // here may mutate the renderer.
    static int s_dbgn = 0;
    if ((++s_dbgn % 5) == 0) {
        // Carry the renderer's own one-line account of which converter is live
        // into the log. GetMLStats is the only channel that says what the
        // renderer DID (MPCVR's DLog is a no-op in Release), and having it in the
        // engine log means the state of a RUNNING app can be read from a file
        // instead of needing a second engine instance — which cannot exist while
        // the app holds the DeckLink.
        //
        // Without this, "the control did nothing" can only be argued from the
        // code path; with it, the pipeline line says so outright.
        auto Field = [&ml](const wchar_t* key) -> std::wstring {
            const size_t at = ml.find(key);
            if (at == std::wstring::npos) return L"?";
            const size_t from = at + wcslen(key);
            const size_t to = ml.find(L'\n', from);
            return ml.substr(from, to == std::wstring::npos ? std::wstring::npos : to - from);
        };
        const std::wstring pipe = Field(L"pipeline:");
        Log("[live] recv=%u draw=%.1f lag=%.0fms renderer=%d pipeline:%ls src=%dx%d@%d/%d gateDrops=%llu",
            r.framesReceived, r.drawFps, r.presentLatencyMs, renderer_ != nullptr,
            pipe.empty() ? L" ?" : pipe.c_str(),
            (int)dl.width, (int)dl.height, (int)dl.fpsNum, (int)dl.fpsDen,
            (unsigned long long)dl.gateDropped);
        // The HDR block the engine is actually holding, next to the renderer's own
        // account of what it built from it. These two are read back FROM the
        // renderer (GetHdrSettings → GetSettings), so a value here that differs from
        // the panel row is the divergence itself, visible without needing a second
        // engine instance (impossible while the app holds the DeckLink).
        Log("[live] hdr: sdrNits=%d blackNits=%.3f convSdr=%d gamut=%d expTm=%d tmContrast=%.2f dispNits=%d",
            hd.sdrDisplayNits, hd.displayMinNits, hd.convertToSdr ? 1 : 0, hd.outputGamut,
            hd.experimentalToneMapper, hd.toneLutContrast, hd.displayMaxNits);
    }
    // (The delivery watchdog lived here: it read the renderer's frame counters and
    // posted a graph rebuild when they froze. Removed 2026-09-21. It was a
    // renderer→graph-destruction cycle, and it could not answer the only question
    // that mattered — a frozen counter is the signature of BOTH a genuine stall
    // and a legitimate movie→menu renegotiation, so it fired into transitions.
    // Ingestion state now changes only when the IngestController says so, and it
    // decides from settled FACTS (which include the format), not from a proxy.)
    //
    // This tick remains a pure SNAPSHOT: it reads and caches, and mutates nothing.
    // The one action it may take — asking the graph owner to rebuild on a
    // CONFIRMED delivery stall — is a notification to the ops queue, exactly the
    // posting side of the snapshot contract (the same reasoning the removed
    // watchdog documented, but now keyed on the SOURCE's own counters, debounced,
    // and routed through the one executor).
    CheckDeliveryStall(dl, r);
    CheckSourceFormatChange(dl);

    {
        std::lock_guard<std::mutex> lk(m_liveMtx);
        m_liveRender = r;
        m_liveMl = std::move(ml);
        m_liveMlS = mls;
        m_liveHdr = hd;
        m_liveOut = ou;
        m_liveDl = dl;
    }
}

bool MpcPlayer::GetLiveRendererStats(RenderStats& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveRender;
    return true;
}
bool MpcPlayer::GetLiveMlStats(std::wstring& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveMl;
    return true;
}
bool MpcPlayer::GetLiveMlSettings(MlSettings& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveMlS;
    return true;
}
bool MpcPlayer::GetLiveHdrSettings(HdrSettings& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveHdr;
    return true;
}
bool MpcPlayer::GetLiveOutSettings(OutSettings& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveOut;
    return true;
}
bool MpcPlayer::GetLiveDeckLinkSourceStats(DeckLinkSourceStats& o) const
{
    std::lock_guard<std::mutex> lk(m_liveMtx);
    o = m_liveDl;
    return true;
}

std::string MpcPlayer::GetUiStatusJson() const
{
    // Polling contract for the (PyQt) client UI. Everything read here goes
    // through the engine's thread-safe/live cache — never the graph directly.
    Snapshot sn{};          GetSnapshot(sn);
    RenderStats rs{};       GetLiveRendererStats(rs);
    DeckLinkSourceStats dl; GetLiveDeckLinkSourceStats(dl);
    const auto& vs = GetVideoStreamInfo();
    const auto& s = GetDecklinkSettings();
    HdrSettings hdr{};      GetLiveHdrSettings(hdr);
    int sigLocked = 0, sigCs = 0, sigDr = 0, sigDepth = 0, sigChroma = 0, sigW = 0, sigH = 0,
        sigNum = 0, sigDen = 0, sigIl = 0;
    GetDecklinkSignalInfo(sigLocked, sigCs, sigDr, sigDepth, sigChroma, sigW, sigH, sigNum, sigDen, sigIl);

    const char* st = sn.state == State::Playing ? "playing"
                   : sn.state == State::Paused   ? "paused"
                   : sn.state == State::Stopped  ? "stopped"
                   : sn.state == State::Error    ? "error" : "idle";

    MlSettings ml{};        GetLiveMlSettings(ml);
    OutSettings out{};      GetLiveOutSettings(out);

    char b1[2300];
    snprintf(b1, sizeof(b1),
        "{\"gen\":%u,\"state\":\"%s\",\"pos\":%lld,\"dur\":%lld,\"vol\":%d,\"muted\":%d,"
        "\"render\":{\"recv\":%u,\"draw\":%.2f,\"lagMs\":%.1f,\"drop\":%u,\"skip\":%u,\"fail\":%u},"
        "\"dl\":{\"stream\":%d,\"w\":%d,\"h\":%d,\"fpsNum\":%d,\"fpsDen\":%d,\"cs\":%d,\"eotf\":%d,"
        "\"arrived\":%llu,\"delv\":%llu,\"skip\":%llu,\"gate\":%llu,\"qdrop\":%llu,\"reneg\":%llu,\"refUs\":%llu,"
        // HDR static metadata the CARD parsed (ST 2086). Five specifiers here MUST
        // stay matched by five arguments further down — adding one without the other
        // is undefined behaviour, and it presents as the whole UI going blank rather
        // than as anything pointing here. MSVC's C4473 catches it: build with
        // warnings visible, not filtered to "error".
        "\"hdrMeta\":%d,\"maxCLL\":%.0f,\"maxFALL\":%.0f,\"masterMax\":%.0f,\"masterMin\":%.4f},"
        "\"signal\":{\"locked\":%d,\"w\":%d,\"h\":%d,\"fpsNum\":%d,\"fpsDen\":%d,\"cs\":%d,\"dr\":%d,\"depth\":%d,\"chroma\":%d,\"il\":%d},"
        "\"media\":{\"valid\":%d,\"w\":%d,\"h\":%d,\"fps\":%.3f,\"subtype\":\"%ls\",\"hdr\":%d},"
        "\"cfg\":{\"ics\":%d,\"convSdr\":%d,\"sdrNits\":%d}",
        (unsigned)graphGen_,
        st, (long long)sn.position, (long long)sn.duration, sn.volume, sn.muted ? 1 : 0,
        rs.framesReceived, rs.drawFps, rs.presentLatencyMs, rs.dropped, rs.skipped, rs.failed,
        dl.streaming, dl.width, dl.height, dl.fpsNum, dl.fpsDen, dl.colorspace, dl.eotf,
        (unsigned long long)dl.framesArrived, (unsigned long long)dl.framesDelivered,
        (unsigned long long)dl.framesSkipped, (unsigned long long)dl.gateDropped,
        (unsigned long long)dl.droppedQueue, (unsigned long long)dl.renegotiations,
        (unsigned long long)dl.lastRefUs,
        dl.hasHdrStaticMeta, dl.hdrMaxCLL, dl.hdrMaxFALL, dl.hdrMasteringMaxNits, dl.hdrMasteringMinNits,
        sigLocked, sigW, sigH, sigNum, sigDen, sigCs, sigDr, sigDepth, sigChroma, sigIl,
        vs.valid ? 1 : 0, vs.width, vs.height,
        vs.avgTimePerFrame100ns > 0 ? 10000000.0 / vs.avgTimePerFrame100ns : 0.0,
        vs.subtypeName.c_str(), vs.hdr ? 1 : 0,
        s.inputColorSpace, hdr.convertToSdr ? 1 : 0, hdr.sdrDisplayNits);

    // P2 settings block — short keys matching the ApplySettingsFlat protocol.
    char b2[4096];
    snprintf(b2, sizeof(b2),
        ",\"hdr\":{\"preferDoVi\":%d,\"convSdr\":%d,\"sdrNits\":%d,\"dispNits\":%d,"
        "\"curve\":%d,\"toggle\":%d,\"osdBrt\":%d,\"raw\":%d,\"blackNits\":%.3f,\"gamut\":%d,"
        "\"titlePeak\":%.1f,\"hableKnee\":%.3f,\"expTm\":%d,\"tmContrast\":%.3f},"
        "\"ml\":{\"enable\":%d,\"mode\":%d,\"gamma\":%.3f,\"shadow\":%.3f,\"shDehaze\":%.3f,"
        "\"highlight\":%.3f,\"hiRoll\":%.3f,\"gammaTopUp\":%.3f,\"hunt\":%.3f,\"chN\":%.3f,\"chF\":%.3f,"
        "\"knee\":%.3f,\"skin\":%.3f,\"contrastEnable\":%d,\"contrast\":%.3f,"
        "\"csZoneLo\":%.3f,\"csCap\":%.3f,\"csSkin\":%.3f,"
        "\"face\":%d,\"faceStr\":%.3f,\"faceFeather\":%.3f,\"faceExpand\":%.3f,"
        "\"sky\":%d,\"skyStr\":%.3f,\"person\":%d,\"persStr\":%.3f,\"skinPres\":%.3f,"
        "\"bars\":%d,\"barsHighlight\":%d,\"debugLog\":%d,\"debugCopy\":%d,"
        "\"shadowZoneCeil\":%.3f,\"shadowSkin\":%.3f,\"shadowCap\":%.3f,"
        "\"shadowVis\":%d,\"contrastVis\":%d,\"faceVis\":%d,\"skyVis\":%d,\"personOv\":%d},"
        "\"out\":{\"d3d11\":%d,\"tex\":%d,\"nv12\":%d,\"p010\":%d,\"yuy2\":%d,\"other\":%d,"
        "\"deint\":%d,\"deintDb\":%d,\"deintBl\":%d,\"shaderVP\":%d,"
        "\"chroma\":%d,\"upsc\":%d,\"downsc\":%d,\"superRes\":%d,\"rtxVideoHdr\":%d,"
        "\"interpolate50\":%d,\"dither\":%d,\"swapEffect\":%d,\"exclusiveFS\":%d,"
        "\"vblank\":%d,\"adjust\":%d,\"reinit\":%d,\"showStats\":%d,\"tray\":%d}}",
        hdr.preferDoVi ? 1 : 0, hdr.convertToSdr ? 1 : 0, hdr.sdrDisplayNits, hdr.displayMaxNits,
        hdr.toneMapCurve, hdr.toggleDisplay, hdr.osdBrightness, hdr.hdrPassthroughRaw ? 1 : 0,
        hdr.displayMinNits, hdr.outputGamut,
        hdr.titlePeakNits, hdr.hableKnee,
        hdr.experimentalToneMapper, hdr.toneLutContrast,
        ml.enable ? 1 : 0, ml.mode,
        ml.gamma, ml.shadow, ml.shadowDehaze, ml.highlight, ml.highlightRolloffCtrl, ml.gammaTopUp,
        ml.hunt, ml.chNeutral, ml.chFire, ml.chKnee, ml.chSkin,
        ml.contrastEnabled ? 1 : 0, ml.contrast,
        ml.contrastZoneLo, ml.contrastRatioCap, ml.contrastSkinProtect,
        ml.faceProtectEnabled ? 1 : 0, ml.faceStrength, ml.faceFeather, ml.faceExpand,
        ml.skyEnabled ? 1 : 0, ml.skyStrength,
        ml.personEnabled ? 1 : 0, ml.personStrength, ml.skinPreserve,
        ml.barsEnabled ? 1 : 0, ml.barsHighlight ? 1 : 0,
        ml.debugLog ? 1 : 0, ml.debugCopy ? 1 : 0,
        ml.shadowZoneCeil, ml.shadowSkinProtect, ml.shadowRatioCap,
        ml.shadowDebugVis ? 1 : 0, ml.contrastDebugVis ? 1 : 0, ml.faceDebugVis ? 1 : 0,
        ml.skyDebugVis ? 1 : 0, ml.personOverlay ? 1 : 0,
        out.useD3D11 ? 1 : 0, out.texFormat,
        out.vpNV12 ? 1 : 0, out.vpP01x ? 1 : 0, out.vpYUY2 ? 1 : 0, out.vpOther ? 1 : 0,
        out.deinterlace, out.deintDouble ? 1 : 0, out.deintBlend ? 1 : 0,
        out.shaderVPScaling ? 1 : 0,
        out.chromaScaling, out.upscaling, out.downscaling,
        out.superRes, out.rtxVideoHdr ? 1 : 0,
        out.interpolate50 ? 1 : 0, out.useDither ? 1 : 0,
        out.swapEffect, out.exclusiveFS ? 1 : 0,
        out.vBlank ? 1 : 0, out.adjustPresent ? 1 : 0, out.reinitDisplay ? 1 : 0,
        out.showStats ? 1 : 0, out.trayIcon ? 1 : 0);

    return std::string(b1) + std::string(b2);
}

// P2: apply flat "grp.name=value" pairs. Groups hdr/ml/out map to the structs
// above; unknown names are skipped. Read-modify-write each group once.
HRESULT MpcPlayer::ApplySettingsFlat(const std::vector<std::string>& sets)
{
    HdrSettings hdr{};   bool hAny = false;
    MlSettings  ml{};    bool mAny = false;
    OutSettings out{};   bool oAny = false;
    // Seed from the live renderer when there is one, because that IS the current
    // intent; otherwise seed from the remembered intent, because there is nothing
    // live to read. The old code seeded only from the renderer and then dropped the
    // whole push when it did not exist — so a push that arrived before the graph
    // was built was lost while the caller still saw S_OK.
    if (renderer_) {
        GetHdrSettings(hdr); GetMlSettings(ml); GetOutSettings(out);
    } else {
        hdr = pendingHdr_; ml = pendingMl_; out = pendingOut_;
    }

    const auto vd = [](const std::string& v) { return atof(v.c_str()); };
    const auto vb = [](const std::string& v) {
        return v == "true" || v == "1" || atof(v.c_str()) > 0.0;
    };

    for (const auto& s : sets) {
        const size_t eq = s.find('=');
        if (eq == std::string::npos) continue;
        const std::string key = s.substr(0, eq);
        const std::string v   = s.substr(eq + 1);
        const size_t dot = key.find('.');
        if (dot == std::string::npos) continue;
        const std::string grp  = key.substr(0, dot);
        const std::string name = key.substr(dot + 1);

        // A group applies if ANY of its names was recognised: an unknown name
        // must not veto the recognised ones. (It used to, when the unknown was
        // the last entry of its group — the flag was cleared per-name.)
        if (grp == "hdr") {
            bool hit = true;
            if      (name == "preferDoVi") hdr.preferDoVi = vb(v);
            else if (name == "convSdr")    hdr.convertToSdr = vb(v);
            else if (name == "sdrNits")    hdr.sdrDisplayNits = (int)vd(v);
            else if (name == "dispNits")   hdr.displayMaxNits = (int)vd(v);
            else if (name == "blackNits")  hdr.displayMinNits = (float)vd(v);
            else if (name == "gamut")      hdr.outputGamut = (int)vd(v);
            else if (name == "titlePeak")  hdr.titlePeakNits = (float)vd(v);
            else if (name == "hableKnee")  hdr.hableKnee = (float)vd(v);
            else if (name == "curve")      hdr.toneMapCurve = (int)vd(v);
            else if (name == "toggle")     hdr.toggleDisplay = (int)vd(v);
            else if (name == "osdBrt")     hdr.osdBrightness = (int)vd(v);
            else if (name == "raw")        hdr.hdrPassthroughRaw = vb(v);
            else if (name == "expTm")      hdr.experimentalToneMapper = (int)vd(v);
            else if (name == "tmContrast") hdr.toneLutContrast = (float)vd(v);
            else hit = false;
            hAny = hAny || hit;
        } else if (grp == "ml") {
            bool hit = true;
            if      (name == "enable")         ml.enable = vb(v);
            else if (name == "mode")           ml.mode = (int)vd(v);
            else if (name == "toneEnable")     ml.toneCurveEnabled = vb(v);
            else if (name == "gamma")          ml.gamma = (float)vd(v);
            else if (name == "shadow")         ml.shadow = (float)vd(v);
            else if (name == "shDehaze")       ml.shadowDehaze = (float)vd(v);
            else if (name == "highlight")      ml.highlight = (float)vd(v);
            else if (name == "hiRoll")         ml.highlightRolloffCtrl = (float)vd(v);
            else if (name == "gammaTopUp")     ml.gammaTopUp = (float)vd(v);
            else if (name == "hunt")           ml.hunt = (float)vd(v);
            else if (name == "chN")            ml.chNeutral = (float)vd(v);
            else if (name == "chF")            ml.chFire = (float)vd(v);
            else if (name == "knee")           ml.chKnee = (float)vd(v);
            else if (name == "skin")           ml.chSkin = (float)vd(v);
            else if (name == "contrastEnable") ml.contrastEnabled = vb(v);
            else if (name == "contrast")       ml.contrast = (float)vd(v);
            else if (name == "csZoneLo")       ml.contrastZoneLo = (float)vd(v);
            else if (name == "csCap")          ml.contrastRatioCap = (float)vd(v);
            else if (name == "csSkin")         ml.contrastSkinProtect = (float)vd(v);
            else if (name == "face")           ml.faceProtectEnabled = vb(v);
            else if (name == "faceStr")        ml.faceStrength = (float)vd(v);
            else if (name == "faceFeather")    ml.faceFeather = (float)vd(v);
            else if (name == "faceExpand")     ml.faceExpand = (float)vd(v);
            else if (name == "sky")            ml.skyEnabled = vb(v);
            else if (name == "skyStr")         ml.skyStrength = (float)vd(v);
            else if (name == "person")         ml.personEnabled = vb(v);
            else if (name == "persStr")        ml.personStrength = (float)vd(v);
            else if (name == "skinPres")       ml.skinPreserve = (float)vd(v);
            else if (name == "bars")           ml.barsEnabled = vb(v);
            else if (name == "barsHighlight")  ml.barsHighlight = vb(v);
            else if (name == "debugLog")       ml.debugLog = vb(v);
            else if (name == "debugCopy")      ml.debugCopy = vb(v);
            else if (name == "shadowVis")      ml.shadowDebugVis = vb(v);
            else if (name == "shadowZoneCeil") ml.shadowZoneCeil = (float)vd(v);
            else if (name == "shadowSkin")     ml.shadowSkinProtect = (float)vd(v);
            else if (name == "shadowCap")      ml.shadowRatioCap = (float)vd(v);
            else if (name == "contrastVis")    ml.contrastDebugVis = vb(v);
            else if (name == "faceVis")        ml.faceDebugVis = vb(v);
            else if (name == "skyVis")         ml.skyDebugVis = vb(v);
            else if (name == "personOv")       ml.personOverlay = vb(v);
            else hit = false;
            mAny = mAny || hit;
        } else if (grp == "out") {
            bool hit = true;
            if      (name == "d3d11")         out.useD3D11 = vb(v);
            else if (name == "tex")           out.texFormat = (int)vd(v);
            else if (name == "nv12")          out.vpNV12 = vb(v);
            else if (name == "p010")          out.vpP01x = vb(v);
            else if (name == "yuy2")          out.vpYUY2 = vb(v);
            else if (name == "other")         out.vpOther = vb(v);
            else if (name == "deint")         out.deinterlace = (int)vd(v);
            else if (name == "deintDb")       out.deintDouble = vb(v);
            else if (name == "deintBl")       out.deintBlend = vb(v);
            else if (name == "shaderVP")      out.shaderVPScaling = vb(v);
            else if (name == "chroma")        out.chromaScaling = (int)vd(v);
            else if (name == "upsc")          out.upscaling = (int)vd(v);
            else if (name == "downsc")        out.downscaling = (int)vd(v);
            else if (name == "superRes")      out.superRes = (int)vd(v);
            else if (name == "rtxVideoHdr")   out.rtxVideoHdr = vb(v);
            else if (name == "interpolate50") out.interpolate50 = vb(v);
            else if (name == "dither")        out.useDither = vb(v);
            else if (name == "swapEffect")    out.swapEffect = (int)vd(v);
            else if (name == "exclusiveFS")   out.exclusiveFS = vb(v);
            else if (name == "vblank")        out.vBlank = vb(v);
            else if (name == "adjust")        out.adjustPresent = vb(v);
            else if (name == "reinit")        out.reinitDisplay = vb(v);
            else if (name == "showStats")     out.showStats = vb(v);
            else if (name == "tray")          out.trayIcon = vb(v);
            else hit = false;
            oAny = oAny || hit;
        }
    }

    // Remember the merged intent, then push it to whatever renderer exists. The
    // remembering is what makes a pre-graph push survive; the push is what makes a
    // post-graph one take effect.
    if (hAny) { pendingHdr_ = hdr; hasHdr_ = true; }
    if (mAny) { pendingMl_  = ml;  hasMl_  = true; }
    if (oAny) { pendingOut_ = out; hasOut_ = true; }
    // UI-thread entry point: remember, and let the graph owner apply. Never
    // write the renderer from here — see QueueSettingsApply().
    QueueSettingsApply();
    return S_OK;
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
    const bool have = GetDeckLinkSourceStats(ds);
    // Log even when the stats are unavailable: this used to return before logging,
    // so "no filter meta line" could mean either "never called" or "called without
    // stats", and that ambiguity is what kept the stale ICS invisible.
    if (!have) {
        Log("[DECKLINK][engine] filter meta: stats unavailable, ICS left at %d",
            decklinkSettings_.inputColorSpace);
        return;
    }
    int ics = 0;
    // EOTF DOMINATES; colours space is only a fallback for SDR.
    //
    // PQ and HLG are defined only in BT.2020, so an EOTF of PQ or HLG means the
    // signal is BT.2020 no matter what the colours-space flag says. Testing
    // colours space first meant a source reporting cs=2 (709) with eotf=2 (PQ) —
    // exactly what this capture box emits for HDR10 — resolved to ICS_BT709, and
    // MPCVR was then told to treat HDR10 as SDR BT.709.
    //
    // The consequence is not subtle: the media type reaches the renderer as
    // BT.709 with a gamma transfer function, so its transfer function is never
    // 2084, so the PQ->SDR converter is NEVER selected — which is why "Convert to
    // SDR" did nothing, and why it did nothing only SOMETIMES: the box reports cs=3
    // on some titles and cs=2 on others, so the answer changed with the content.
    if      (ds.eotf == 2 || ds.eotf == 4) ics = ICS_BT2020_PQ;   // 4 = DV, PQ-coded
    else if (ds.eotf == 3)                 ics = ICS_BT2020_HLG;
    else if (ds.colorspace == 3)           ics = ICS_BT2020_SDR;
    else if (ds.colorspace == 2)           ics = ICS_BT709;
    else if (ds.colorspace == 1)           ics = ICS_BT601;
    Log("[DECKLINK][engine] filter meta (cs=%d eotf=%d) → ICS %d (was %d)",
        ds.colorspace, ds.eotf, ics, decklinkSettings_.inputColorSpace);
    decklinkSettings_.inputColorSpace = ics;
}

// (DeckLinkRestartBridge and RequestDecklinkRestart lived here. The bridge was
// the filter's restart callback — written, but never registered, so the filter
// could not initiate a rebuild at all; and RequestDecklinkRestart was a second
// decider that inferred "stalled" from renderer counters, which cannot be told
// apart from a legitimate renegotiation. Both are gone: the IngestController
// decides, HandleIngestDecision queues, the executor acts.)

// THE ops-queue entry point, and the only way ingestion changes state. Called
// by the IngestController with its decision. Non-blocking and coalescing: the
// EXECUTOR thread performs the work, never this caller.
void MpcPlayer::HandleIngestDecision(const IngestController::Decision& d)
{
    if (d.intent == IngestController::Intent::None) return;

    // Record the fact that produced the decision (signal lock state, ICS advice)
    // — this is state the UI displays; the graph is not touched here.
    decklinkSettings_.signalLocked = (d.intent != IngestController::Intent::Stop);
    if (!d.url.empty()) {
        pendingDecklinkUrl_.assign(d.url.begin(), d.url.end());
        decklinkSettings_.inputColorSpace = d.ics;
    }

    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        m_gopIntent = d.intent;           // coalesce: latest decision wins
        if (!d.url.empty()) m_gopUrl.assign(d.url.begin(), d.url.end());
        m_gopQueued = true;
    }
    Log("[DECKLINK][engine] op POSTED to executor: %s url='%s'",
        IngestController::IntentName(d.intent), d.url.c_str());
    m_gopCv.notify_one();
    Notify(d.intent == IngestController::Intent::Stop ? "decklink:lost" : "decklink:signal");
}

// The single executor: every graph mutation for the capture path runs here,
// strictly ordered. The monitor, the decider, the UI and the filter only POST.
void MpcPlayer::DecklinkOpLoop()
{
    for (;;) {
        bool runGraph = false, runApply = false;
        {
            std::unique_lock<std::mutex> lk(m_gopMtx);
            m_gopCv.wait(lk, [this] { return m_gopStop || m_gopQueued || m_gopApplyQueued; });
            if (m_gopStop) break;
            // The graph op goes first: a settings push that arrived during a
            // rebuild is then applied onto the NEW renderer, which is the point
            // of routing it through here at all.
            if (m_gopQueued)           { m_gopQueued = false; runGraph = true; }
            else if (m_gopApplyQueued) { m_gopApplyQueued = false; runApply = true; }
        }
        if (runGraph) RunDecklinkRebuild();
        else if (runApply) { std::lock_guard<std::recursive_mutex> lk(m_graphMtx); ApplySettingsOp(); }
    }
}

void MpcPlayer::RunDecklinkRebuild()
{
    IngestController::Intent intent = IngestController::Intent::None;
    std::wstring url;
    {
        std::lock_guard<std::mutex> lk(m_gopMtx);
        intent = m_gopIntent;
        url = m_gopUrl;
        m_gopUrl.clear();
        m_gopIntent = IngestController::Intent::None;
    }
    if (url.empty()) url = decklinkUrl_;

    std::lock_guard<std::recursive_mutex> lk(m_graphMtx);

    if (intent == IngestController::Intent::Stop) {
        Log("[DECKLINK][engine] executor: STOP (ordered teardown, no relaunch)");
        TeardownDecklinkGraph();
        snapshot_ = {};
        snapshot_.state = State::Stopped;
        if (ingest_) ingest_->OnIngestActive(false);
        Notify("state");
        return;
    }

    Log("[DECKLINK][engine] EXECUTOR: %s dequeued from the ops queue — starting ordered teardown + relaunch url='%s'",
        intent == IngestController::Intent::Launch ? "LAUNCH" : "RELOAD",
        url.empty() ? "<empty>" : "decklink://…");
    UpdateIcsFromFilter();
    if (!url.empty()) {
        // Open() embodies the ordered teardown (StopDelivery → disconnect →
        // StopCapture) then builds the fresh graph on this thread.
        Log("[DECKLINK][engine] EXECUTOR: calling Open(url) — enter");
        const HRESULT hrO = Open(url);
        Log("[DECKLINK][engine] EXECUTOR: Open returned hr=0x%08X — calling Play", (unsigned)hrO);
        const HRESULT hrP = Play();
        Log("[DECKLINK][engine] EXECUTOR: rebuild done: Open hr=0x%08X Play hr=0x%08X",
            (unsigned)hrO, (unsigned)hrP);
        // Tell the decider ingestion is running, so its next decision is Reload
        // rather than Launch. This is the only thing it learns about the graph.
        const bool active = SUCCEEDED(hrO) && SUCCEEDED(hrP);
        if (ingest_) ingest_->OnIngestActive(active);
        Log("[DECKLINK][engine] EXECUTOR: informed the decider ingestActive=%d", active ? 1 : 0);
        // (The post-reload auto-grab lived here. REVERTED same day: GetCurrentImage
        // blocks the renderer while a live graph is streaming, so running it from
        // the 1 s snapshot tick wedged startup acquisition — overlay stuck, frame
        // frozen. Live snapshots must never call blocking renderer methods.)
    }
    Notify("opened");
}

void MpcPlayer::DisconnectDecklinkPins()
{
    // Quiesce the renderer path BEFORE joining the source's threads: an
    // in-flight Deliver that would otherwise block inside MPCVR now returns
    // immediately. Called only from the executor under the graph lock, with
    // decklinkControl_ still attached to the OLD graph.
    if (!graph_) return;
    if (decklinkControl_) {
        CComQIPtr<IBaseFilter> sf = decklinkControl_;   // the decklink filter
        CComPtr<IPin> srcOut = FindPin(sf, PINDIR_OUTPUT);
        if (srcOut) graph_->Disconnect(srcOut);         // not-connected → HR ignored
    }
    CComPtr<IPin> rndIn = FindPin(renderer_, PINDIR_INPUT);
    if (rndIn) graph_->Disconnect(rndIn);
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

// Derive the input colour space from the media type the graph ACTUALLY negotiated.
//
// This is the authoritative source, and the engine already logs it ("source media
// type: ... tf=15 hdr=1"). The two earlier paths both fail in practice on the
// DeckLink-direct graph:
//   * the monitor's advice resolves colours space BEFORE the EOTF, so a PQ signal
//     flagged cs=2 comes back as BT.709;
//   * UpdateIcsFromFilter() reads the source filter's stats, which are unavailable
//     during a rebuild — it logs "stats unavailable" and leaves the stale value in
//     place.
// So BT.709 won every time, and MPCVR was told to treat HDR10 as SDR. That is what
// made "Convert to SDR" inert: the renderer's transfer function was never 2084, so
// the PQ->SDR converter was never built, at any setting.
//
// The transfer function settles it on its own — PQ and HLG exist only in BT.2020 —
// so EOTF is tested first and the primaries are only a fallback for SDR.
int MpcPlayer::IcsFromMediaType() const
{
    if (videoStreamInfo_.transferFunction == MFVideoTransFunc_2084) return ICS_BT2020_PQ;
    if (videoStreamInfo_.transferFunction == MFVideoTransFunc_HLG)  return ICS_BT2020_HLG;
    if (videoStreamInfo_.colorspace == 3) return ICS_BT2020_SDR;
    if (videoStreamInfo_.colorspace == 1) return ICS_BT601;
    return ICS_BT709;
}

void MpcPlayer::ApplyIcsFromMediaType()
{
    const int ics = IcsFromMediaType();
    Log("[ENGINE] media-type ICS: tf=%d hdr=%d cs=%d -> ICS %d (monitor/filter said %d)",
        videoStreamInfo_.transferFunction, videoStreamInfo_.hdr ? 1 : 0,
        videoStreamInfo_.colorspace, ics, decklinkSettings_.inputColorSpace);
    if (ics == decklinkSettings_.inputColorSpace) return;
    SetDecklinkInputColor(ics);
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

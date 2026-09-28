// DeckLinkSource.cpp — HTPC DeckLink ingest as a DirectShow source filter.
//
// Phase 2, picture-first: raw DeckLink SDK (no ffmpeg/LAV). Capture thread
// copies v210 into media samples delivered by the output pin. Sample timestamps
// are the card's hardware-reference clock (wall-aligned per the Phase-1 spike),
// giving an absolute end-to-end latency reference. Format handling is
// idempotent: only a real display-mode change restarts capture (from a worker,
// never inside the SDK callback); colorspace events update state only.
//
// Inspiration only: VideoProcessor-Lib (BlackMagicDeckLinkCaptureDevice,
// CLiveSource / CUnbufferedLiveSourceVideoOutputPin).

#include <streams.h>

#include <atlbase.h>   // CComPtr, CComBSTR
#include <cstdarg>     // StateLog
#include <cstdio>      // vsnprintf
#include <string.h>
#include <thread>      // std::thread (capture-session worker)

#include "DeckLinkAPI_h.h"   // DeckLink C++ SDK (vendored; GUIDs live in DeckLinkAPI_i.c)
#include "DeckLinkSourceControl.h"   // IDeckLinkSourceControl (engine control surface)

// 2026-09-20 — every COM status/metadata query made on the VideoInputFrameArrived
// callback thread is "known to stall this driver" (the two blocks below say so,
// and the worker's format-change handler moves its status read onto the worker
// thread for exactly that reason). The raw spike — whose callback ONLY counts —
// streams 294 frames with 0 missed gaps, while this filter's callback went silent
// ~26 frames in, wedged in that same in-callback query work. Both blocks are
// gated on this one flag until their reads are relocated to the worker thread.
// Off = the callback only copies + delivers, which is the proven-safe path.
constexpr bool kInCallbackDriverQueries = false;

// VIDEOINFOHEADER2 + AMCONTROL_* colorimetry bits, and DXVA2_ExtendedFormat for
// packing that colorimetry into dwControlFlags. The SDK's dshow.h covers the
// former only up to FORMAT_VideoInfo; the V2 format lives in dvdmedia.h.
// dxva2api.h needs D3DFORMAT, so d3d9.h must come first.
#include <dvdmedia.h>
#include <d3d9.h>
#include <dxva2api.h>

// MEDIASUBTYPE_v210 ('v210' FOURCC media subtype) is not in the SDK's uuids.h.
// Same GUID value MPCVR's MediaTypes.h accepts. The OUTPUT is P010 (see below):
// MPCVR's allocator sizes raw v210 samples at ~2.5 B/px but the SDK's row-padded
// layout needs ~2.67 B/px, so raw v210 can never fit an MPCVR sample — the
// filter converts to P010 (10-bit 4:2:0, LAVVideo's production HDR path).
const GUID MEDIASUBTYPE_v210 = {
    0x30313276, 0x0000, 0x0010, { 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71 }
};
// MEDIASUBTYPE_P010 ('P010' FOURCC GUID; 10-bit 4:2:0 in 16-bit words). The
// SDK defines it as data in strmiids.lib but does NOT declare it in a header —
// declare the extern and let the linker supply the value.
EXTERN_C const GUID MEDIASUBTYPE_P010;

// Extended-color enum values absent from the SDK's dxva2api.h enums. Their
// numeric twins in MF (MFVideoPrimaries_BT2020=9, MFVideoTransFunc_2084=15,
// MFVideoTransFunc_HLG=16) are what MPCVR compares the packed fields against,
// so these numbers are normative for the v210 media type bitfields 22-31.
enum {
    DXVA2_VideoPrimaries_BT2020  = 9,
    DXVA2_VideoTransFunc_2084    = 15,
    DXVA2_VideoTransFunc_HLG     = 16,
};

// Filter CLSID (new, registered by DllRegisterServer)
// {8C2F2A32-27B1-4E61-A1BE-7884F2410E7A}
DEFINE_GUID(CLSID_DeckLinkSource,
    0x8c2f2a32, 0x27b1, 0x4e61, 0xa1, 0xbe, 0x78, 0x84, 0xf2, 0x41, 0x0e, 0x7a);

// ---------------------------------------------------------------------------
// Shared capture state (locked; touched by capture thread + filter threads)
// ---------------------------------------------------------------------------
struct CaptureState {
    CRITICAL_SECTION lock;
    LONG   active = 0;        // pin active (deliver allowed)
    LONG   stopPending = 0;    // teardown: capture callbacks bail out without AcquireSample
    LONG   enableRetry = 0;    // Enable failed — worker re-tries every 500 ms until the card accepts
    LONG   started = 0;       // card is streaming
    LONG   enabled = 0;       // EnableVideoInput succeeded (avoids re-enable w/o stop)
    LONG   everStarted = 0;   // capture has been started once (pre-connect start allowed)
    LONG   quit = 0;          // StopCaptureSession requested — worker exits
    LONG   width  = 0;        // negotiated/detected size when signalled
    LONG   height = 0;
    LONG   fpsNum = 50000;    // default 50 fps until mode known
    LONG   fpsDen = 1000;
    BMDDisplayMode mode = bmdModeHD1080p50;
    BMDDisplayMode pendingMode = bmdModeHD1080p50;
    LONG   formatOutstanding = 0;  // a format change arrived and is unhandled
    LONG   colorspace = 0;    // 0=unk 1=601 2=709 3=bt2020
    LONG   eotf = 0;          // 0=unk 1=gamma 2=PQ 3=HLG
    unsigned long long frames = 0, skipped = 0, delivered = 0;
    unsigned long long gateDropped = 0, renegotiations = 0, formatEvents = 0, droppedQueue = 0;
    LONG64 prevRefUs = 0;     // last hwRef (µs); fallback for a failed/zero read
    LONG64 rtBaseUs = 0;      // hwRef anchor → graph-relative sample times
    HANDLE restartEvent = nullptr;
    HANDLE firstDataEvent = nullptr;   // auto-reset: first format/frame detected
    LONG   metaProbe = 0;              // one-shot per session: dump SDK signal/metadata
    LONG   hdrMetaTick = 0;            // countdown to the next ST 2086 hand-off (1 Hz)
    LONG   hdrMetaLogged = 0;          // values logged once, then only when they change
    double hdrCll = 0.0, hdrFall = 0.0, hdrMaxMLL = 0.0, hdrMinMLL = 0.0;  // last read
    // ST 2086 is read OFF the SDK callback: the callback hands a ref-held frame to
    // the worker (which owns all SDK calls), so no metadata COM work runs on the
    // delivery thread. hdrSampleFrame is AddRef'd by the callback, Release'd by the
    // worker (or teardown); hdrSamplePending guards one-in-flight.
    IDeckLinkVideoInputFrame* hdrSampleFrame = nullptr;
    LONG   hdrSamplePending = 0;
    HANDLE hdrSampleEvent = nullptr;   // auto-reset: callback → worker
    LONG   twelve = 0;                 // 1 while the 12-bit probe stream is the active capture
    LONG   twelveProbe = 0;            // one-shot per session: ask for a 12-bit capture, measure, revert
    LONG   modeApplied = 0;            // detected display mode has been applied once
    void* logCtx = nullptr;            // engine log sink (SetLogSink); OutputDebugStringA fallback
    DeckLinkSourceLogFn logFn = nullptr;
    void* restartCtx = nullptr;            // engine restart notification (fires on the worker)
    DeckLinkRestartFn restartFn = nullptr;
    DWORD64 lastRebuildMs = 0;         // gate-drop throttle: rebuild request ≤1.5 s apart

    CaptureState() {
        InitializeCriticalSection(&lock);
        // restartEvent manual-reset (wake), firstDataEvent auto-reset (one-shot),
        // hdrSampleEvent auto-reset (callback hands a frame to the worker).
        restartEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        firstDataEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        hdrSampleEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    }
    ~CaptureState() {
        // Release any frame still held for the worker before tearing down.
        if (hdrSampleFrame) { hdrSampleFrame->Release(); hdrSampleFrame = nullptr; }
        DeleteCriticalSection(&lock);
        if (restartEvent) CloseHandle(restartEvent);
        if (firstDataEvent) CloseHandle(firstDataEvent);
        if (hdrSampleEvent) CloseHandle(hdrSampleEvent);
    }

    void Lock()   { EnterCriticalSection(&lock); }
    void Unlock() { LeaveCriticalSection(&lock); }
};

// Route filter telemetry (format events, frame counts, worker starts) to the
// engine's log via the SetLogSink callback — without one, fall back to
// OutputDebugStringA (DebugView). The sink is configured once before capture
// starts, so reading logFn/logCtx outside the lock is benign.
static void StateLog(CaptureState* st, const char* fmt, ...)
{
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (st->logFn) st->logFn(st->logCtx, buf);
    else OutputDebugStringA(buf);
}

// ---------------------------------------------------------------------------
// Capture callback (runs on the DeckLink input thread)
// ---------------------------------------------------------------------------
class CDeckLinkOutputPin;   // full type below (callback needs AcquireSample)

class CDeckLinkCaptureCallback : public IDeckLinkInputCallback {
public:
    CDeckLinkCaptureCallback(CDeckLinkOutputPin* pin, CaptureState* st,
                             IDeckLinkInput* input)
        : m_pin(pin), m_st(st), m_input(input), m_ref(1) {}

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_IDeckLinkInputCallback) {
            AddRef();
            *ppv = this;
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&m_ref); }
    STDMETHODIMP_(ULONG) Release() override { return InterlockedDecrement(&m_ref); }

    STDMETHODIMP VideoInputFormatChanged(BMDVideoInputFormatChangedEvents,
        IDeckLinkDisplayMode*, BMDDetectedVideoInputFormatFlags) override;
    STDMETHODIMP VideoInputFrameArrived(IDeckLinkVideoInputFrame*, IDeckLinkAudioInputPacket*) override;

private:
    CDeckLinkOutputPin* m_pin;
    CaptureState*   m_st;
    IDeckLinkInput* m_input;   // borrowed (filter owns)
    ULONG           m_ref;
};

// ---------------------------------------------------------------------------
// Output pin (push model: delivery happens on the capture thread)
// ---------------------------------------------------------------------------
class CDeckLinkOutputPin : public CBaseOutputPin {
public:
    CDeckLinkOutputPin(CBaseFilter* pFilter, CCritSec* pLock, HRESULT* phr)
        : CBaseOutputPin(NAME("DeckLink Video"), pFilter, pLock, phr, L"Video")
    {}

    HRESULT GetMediaType(int i, CMediaType* pmt) override;
    HRESULT DecideBufferSize(IMemAllocator* p, ALLOCATOR_PROPERTIES* props) override;
    HRESULT CheckMediaType(const CMediaType* pmt) override;
    HRESULT SetMediaType(const CMediaType* pmt) override;   // stash negotiated size
    HRESULT Active() override;
    HRESULT Inactive() override;

    // Owned capture session (set by the engine before the graph runs)
    IDeckLink*  m_dev = nullptr;
    IDeckLinkInput* m_input = nullptr;
    CDeckLinkCaptureCallback* m_cb = nullptr;   // set on the SDK; never deref after Set
    CaptureState* StatePtr() { return &m_st; }
    std::thread m_worker;

    HRESULT StartCaptureSession(const wchar_t* deviceName);
    void    StopDelivery();            // phase 1: halt at SDK, no join, no renderer wait
    void    JoinCaptureThreads();      // phases 2-3: join+release; after StopDelivery AND pin disconnect
    void    StopCaptureSession();      // == StopDelivery + JoinCaptureThreads
    void    SetLogSink(void* ctx, DeckLinkSourceLogFn fn);
    void    SetRestartCb(void* ctx, DeckLinkRestartFn fn);
    void    GetStats(DeckLinkSourceStats& out);

    LONG ConnWidth() const  { return m_connWidth; }    // read under m_st.lock
    LONG ConnHeight() const { return m_connHeight; }

    // Public shim over the protected base GetDeliveryBuffer — the capture
    // callback (not a pin method) cannot call it directly.
    HRESULT AcquireSample(IMediaSample** ppSample) {
        return GetDeliveryBuffer(ppSample, nullptr, nullptr, 0);
    }

    // Bounded forwarder queue (Phase-2b): the SDK callback NEVER blocks on the
    // renderer. It enqueues the sample here; ForwardLoop (its own thread)
    // Delivers it. If the renderer is slow the queue fills and the callback
    // drops the NEWEST frame — the card is never stuck behind MPCVR.
    bool EnqueueSample(IMediaSample* s);    // true = enqueued (ownership moves)

private:
    CaptureState m_st;
    LONG m_connWidth = 0;       // negotiated media type dims (delivery size gate)
    LONG m_connHeight = 0;
    enum { kQDepth = 3 };
    IMediaSample* m_q[kQDepth] = {};
    int m_qHead = 0, m_qTail = 0;
    HANDLE m_dataEvent = nullptr;
    std::thread m_forwarder;
    void WorkerLoop();          // negotiate + start/stop (never in callback)
    void ForwardLoop();         // pop + Deliver + Release (never in callback)
    void SampleHdrMetadata();   // ST 2086 read of a callback-handed frame (worker only)
};

// ---------------------------------------------------------------------------
// v210 -> P010 conversion (10-bit 4:2:2 → 10-bit 4:2:0).
//
// Reference-inspiration: CV210toP010VideoFrameFormatter (VideoProcessor-Lib,
// GPLv3). The algorithm is the standard v210 packing; this is our own lean
// scalar implementation with averaged vertical chroma (reference AVERAGE mode).
//
// v210 row: 4 × 32-bit words carry 6 pixels + 3 chroma pairs. The output is
// P010: Y plane (w*h uint16) then interleaved UV (w*(h/2) uint16), 3 B/px.
// Only full 6-pixel packs are converted (our modes 1920/3840 are 6-divisible).
// ---------------------------------------------------------------------------
static LONG P010Size(LONG w, LONG h) { return (LONG)((LONGLONG)w * h * 3); }

static void V210ToP010(const BYTE* src, LONG srcStride,
    BYTE* dst, LONG dstBytes, LONG w, LONG h)
{
    const uint32_t packsPerLine = (uint32_t)w / 6;
    const uint32_t lineBytes = (uint32_t)(srcStride);

    // Require the full frame; the allocator is sized from the same P010Size()
    // math as the media type, so a shortfall means the connection is broken —
    // bail rather than emit a truncated frame.
    if (dstBytes < P010Size(w, h)) return;

    uint16_t* const dstY = reinterpret_cast<uint16_t*>(dst);
    uint16_t* const dstUV = dstY + (ptrdiff_t)w * h;

    // Average an even-line chroma code (already 10-bit << 6) with the odd-line
    // code of the same position: (evenCode + oddCode + 1)/2, written in-place.
    auto avgChroma = [](uint16_t& evenValue, uint16_t oddCode) {
        const uint16_t avg = (uint16_t)((((uint32_t)(evenValue >> 6) + oddCode + 1U) >> 1) << 6);
        evenValue = avg;
    };

    for (LONG line = 0; line < h; ++line) {
        const uint32_t* s = reinterpret_cast<const uint32_t*>(src + (ptrdiff_t)line * lineBytes);
        uint16_t* y  = dstY + (ptrdiff_t)line * w;
        uint16_t* uv = dstUV + (ptrdiff_t)(line >> 1) * w;
        const bool even = (line & 1) == 0;

        for (uint32_t p = 0; p < packsPerLine; ++p) {
            uint32_t val;
            uint16_t u, v, y1, y2;

            // 6 pixels + 3 chroma pairs per 4 words; Y from the middle channel
            // of each word + the outer channels of words 1/3 (standard v210).
            val = *s++; u = (uint16_t)(val & 0x3FF); y1 = (uint16_t)((val >> 10) & 0x3FF); v = (uint16_t)((val >> 20) & 0x3FF);
            if (even) { *y++ = (uint16_t)(y1 << 6); *uv++ = (uint16_t)(u << 6); *uv++ = (uint16_t)(v << 6); }
            else      { *y++ = (uint16_t)(y1 << 6); avgChroma(uv[0], u); avgChroma(uv[1], v); uv += 2; }

            val = *s++; y1 = (uint16_t)(val & 0x3FF); u = (uint16_t)((val >> 10) & 0x3FF); y2 = (uint16_t)((val >> 20) & 0x3FF);
            if (even) { *y++ = (uint16_t)(y1 << 6); *y++ = (uint16_t)(y2 << 6); *uv++ = (uint16_t)(u << 6); }
            else      { *y++ = (uint16_t)(y1 << 6); *y++ = (uint16_t)(y2 << 6); avgChroma(uv[0], u); uv += 1; }

            val = *s++; v = (uint16_t)(val & 0x3FF); y1 = (uint16_t)((val >> 10) & 0x3FF); u = (uint16_t)((val >> 20) & 0x3FF);
            if (even) { *y++ = (uint16_t)(y1 << 6); *uv++ = (uint16_t)(v << 6); *uv++ = (uint16_t)(u << 6); }
            else      { *y++ = (uint16_t)(y1 << 6); avgChroma(uv[0], v); avgChroma(uv[1], u); uv += 2; }

            val = *s++; y1 = (uint16_t)(val & 0x3FF); v = (uint16_t)((val >> 10) & 0x3FF); y2 = (uint16_t)((val >> 20) & 0x3FF);
            if (even) { *y++ = (uint16_t)(y1 << 6); *y++ = (uint16_t)(y2 << 6); *uv++ = (uint16_t)(v << 6); }
            else      { *y++ = (uint16_t)(y1 << 6); *y++ = (uint16_t)(y2 << 6); avgChroma(uv[0], v); uv += 1; }
        }
    }
}

// ---------------------------------------------------------------------------
// Media type — P010 in VIDEOINFOHEADER2 (protocol parameters from the state).
// DataFrame: Y plane (DWORD-padded) then interleaved UV — LAVVideo's P010
// convention (3 B/px), which MPCVR's allocator + vpP01x path already handle.
// ---------------------------------------------------------------------------
static void FillP010MediaType(CMediaType* pmt, const CaptureState& s)
{
    const LONG w  = s.width  > 0 ? s.width  : 1920;
    const LONG h  = s.height > 0 ? s.height : 1080;
    const REFERENCE_TIME avg = (s.fpsNum > 0 && s.fpsDen > 0)
        ? (10000000LL * s.fpsDen) / s.fpsNum : 400000LL;

    VIDEOINFOHEADER2* vih = (VIDEOINFOHEADER2*)pmt->AllocFormatBuffer(sizeof(VIDEOINFOHEADER2));
    ZeroMemory(vih, sizeof(VIDEOINFOHEADER2));
    vih->rcSource.left = 0; vih->rcSource.top = 0;
    vih->rcSource.right = w; vih->rcSource.bottom = h;
    vih->rcTarget = vih->rcSource;
    vih->AvgTimePerFrame = avg;

    BITMAPINFOHEADER& bi = vih->bmiHeader;
    bi.biSize = sizeof(BITMAPINFOHEADER);
    bi.biWidth = w;
    bi.biHeight = h;
    bi.biPlanes = 1;
    bi.biBitCount = 16;                 // 10-bit data in 16-bit words
    bi.biCompression = MAKEFOURCC('P', '0', '1', '0');
    bi.biSizeImage = (DWORD)P010Size(w, h);

    // Colorimetry (defaults; HDR events overwrite colorspace/eotf in state).
    // MPCVR reads dwControlFlags as a whole DXVA2_ExtendedFormat and only
    // rewrites the low SampleFormat bits — a shifted copy would put the color
    // fields in the wrong bits, so the full packed value is written directly.
    DXVA2_ExtendedFormat ef = {};
    ef.NominalRange = DXVA2_NominalRange_16_235;                 // studio range for YUV
    ef.VideoTransferMatrix = (s.colorspace == 1) ? DXVA2_VideoTransferMatrix_BT601
                            : DXVA2_VideoTransferMatrix_BT709;
    ef.VideoPrimaries = (s.colorspace == 3) ? DXVA2_VideoPrimaries_BT2020
                       : DXVA2_VideoPrimaries_BT709;
    ef.VideoTransferFunction = (s.eotf == 2 || s.eotf == 4) ? DXVA2_VideoTransFunc_2084   // 4 = DV, PQ-coded
                             : (s.eotf == 3) ? DXVA2_VideoTransFunc_HLG
                             : DXVA2_VideoTransFunc_709;
    vih->dwControlFlags = ef.value | AMCONTROL_USED | AMCONTROL_COLORINFO_PRESENT;

    pmt->SetType(&MEDIATYPE_Video);
    pmt->SetSubtype(&MEDIASUBTYPE_P010);
    pmt->SetFormatType(&FORMAT_VideoInfo2);
    pmt->SetTemporalCompression(FALSE);
    pmt->SetSampleSize(vih->bmiHeader.biSizeImage);
}

// ---------------------------------------------------------------------------
// Pin implementation
// ---------------------------------------------------------------------------
HRESULT CDeckLinkOutputPin::CheckMediaType(const CMediaType* pmt)
{
    return (pmt->majortype == MEDIATYPE_Video &&
            pmt->subtype == MEDIASUBTYPE_P010) ? S_OK : E_INVALIDARG;
}

HRESULT CDeckLinkOutputPin::SetMediaType(const CMediaType* pmt)
{
    // Remember the exact dimensions the downsteram connected to. The capture
    // callback drops (never clips) any frame whose real size differs, so a
    // 4K frame can never be copied into a 1080-sized sample buffer.
    const HRESULT hr = CBaseOutputPin::SetMediaType(pmt);
    if (SUCCEEDED(hr) && pmt && pmt->formattype == FORMAT_VideoInfo2 && pmt->pbFormat) {
        const VIDEOINFOHEADER2* vih = reinterpret_cast<const VIDEOINFOHEADER2*>(pmt->pbFormat);
        m_st.Lock();
        m_connWidth  = vih->bmiHeader.biWidth;
        m_connHeight = labs(vih->bmiHeader.biHeight);
        // Log the colourimetry that is going INTO the connected media type, alongside
        // the state it came from. Without this the two ends of the handoff were logged
        // separately (the detection here, the parsed value in the engine) and they
        // disagreed with no way to see where — the engine read tf=15 from a media type
        // the state said should carry 709.
        DXVA2_ExtendedFormat wrote = {};
        wrote.value = vih->dwControlFlags;
        StateLog(&m_st, "[DECKLINK][src] SetMediaType: %dx%d (state %dx%d) cs=%d eotf=%d -> tf=%d prim=%d",
            m_connWidth, m_connHeight, m_st.width, m_st.height,
            m_st.colorspace, m_st.eotf,
            (int)wrote.VideoTransferFunction, (int)wrote.VideoPrimaries);
        m_st.Unlock();
    }
    return hr;
}

HRESULT CDeckLinkOutputPin::GetMediaType(int iPosition, CMediaType* pmt)
{
    if (iPosition < 0) return E_INVALIDARG;
    if (iPosition > 0) return VFW_S_NO_MORE_ITEMS;
    m_st.Lock();
    FillP010MediaType(pmt, m_st);
    m_st.Unlock();
    return S_OK;
}

HRESULT CDeckLinkOutputPin::DecideBufferSize(IMemAllocator* pAlloc, ALLOCATOR_PROPERTIES* props)
{
    // Size for the NEGOTIATED media type (SetMediaType ran before allocator
    // negotiation and stashed the connected dims), not the mutable detect-state:
    // m_st.width/height can still be the pre-detection default (or flip during a
    // mode change) here, which under-sizes the sample and lets a 4K v210 copy
    // overrun the buffer (the "COPY CLAMPED" truncation / first-crash).
    m_st.Lock();
    const LONG w = m_connWidth  > 0 ? m_connWidth  : (m_st.width  > 0 ? m_st.width  : 1920);
    const LONG h = m_connHeight > 0 ? m_connHeight : (m_st.height > 0 ? m_st.height : 1080);
    props->cBuffers = 3;                       // small: latency over slack
    props->cbBuffer = P010Size(w, h);
    props->cbAlign = 1;
    props->cbPrefix = 0;
    m_st.Unlock();
    ALLOCATOR_PROPERTIES actual = {};
    const HRESULT hr = pAlloc->SetProperties(props, &actual);
    m_st.Lock();
    StateLog(&m_st,
        "[DECKLINK][src] DecideBufferSize: req %dx%d->%d B  SetProperties hr=0x%08X actual %d B x%d (conn=%dx%d state=%dx%d)",
        w, h, props->cbBuffer, (unsigned)hr, actual.cbBuffer, actual.cBuffers,
        m_connWidth, m_connHeight, m_st.width, m_st.height);
    m_st.Unlock();
    if (FAILED(hr)) return hr;
    return (actual.cBuffers < props->cBuffers || actual.cbBuffer < props->cbBuffer)
        ? E_FAIL : S_OK;
}

HRESULT CDeckLinkOutputPin::Active()
{
    m_st.Lock();
    if (m_st.width <= 0) { m_st.width = 1920; m_st.height = 1080; }
    m_st.Unlock();
    HRESULT hr = CBaseOutputPin::Active();
    InterlockedExchange(&m_st.stopPending, 0);
    InterlockedExchange(&m_st.active, 1);
    SetEvent(m_st.restartEvent);
    return hr;
}

HRESULT CDeckLinkOutputPin::Inactive()
{
    InterlockedExchange(&m_st.active, 0);
    InterlockedExchange(&m_st.stopPending, 1); // new deliveries bail; in-flight ones
    SetEvent(m_st.restartEvent);               // are bounded by the renderer releasing
    // Do NOT call StopStreams from the graph thread: the SDK blocks that call
    // until the in-flight capture callback returns, and that callback can be
    // parked inside Deliver against the renderer which THE SAME stop is tearing
    // down — a graph-thread deadlock (observed: freeze on Stop). The worker
    // stops the card on its own thread once it sees stopPending+inactive.
    m_st.rtBaseUs = 0;                         // re-anchor stream time on next start
    return CBaseOutputPin::Inactive();
}

// ---------------------------------------------------------------------------
// Capture session lifecycle (upstream of the graph)
// ---------------------------------------------------------------------------
void CDeckLinkOutputPin::SetLogSink(void* ctx, DeckLinkSourceLogFn fn)
{
    m_st.Lock();
    m_st.logCtx = ctx;
    m_st.logFn = fn;
    m_st.Unlock();
}

void CDeckLinkOutputPin::SetRestartCb(void* ctx, DeckLinkRestartFn fn)
{
    m_st.Lock();
    m_st.restartCtx = ctx;
    m_st.restartFn = fn;
    m_st.Unlock();
}

void CDeckLinkOutputPin::GetStats(DeckLinkSourceStats& out)
{
    m_st.Lock();
    out.framesArrived  = m_st.frames;
    out.framesDelivered = m_st.delivered;
    out.framesSkipped  = m_st.skipped;
    out.droppedQueue   = m_st.droppedQueue;
    out.gateDropped    = m_st.gateDropped;
    out.renegotiations = m_st.renegotiations;
    out.formatEvents   = m_st.formatEvents;
    out.width  = m_st.width;
    out.height = m_st.height;
    out.fpsNum = m_st.fpsNum;
    out.fpsDen = m_st.fpsDen;
    out.colorspace = m_st.colorspace;
    out.eotf = m_st.eotf;
    out.streaming = m_st.started;
    out.lastRefUs = (m_st.prevRefUs > 0) ? (unsigned long long)m_st.prevRefUs : 0;
    // Gate on the value, not on a "we have read it" flag: a failed or not-yet-settled
    // read leaves zeros behind, and publishing those would announce real metadata.
    const bool hdrOk = (m_st.hdrCll > 1.0 && m_st.hdrCll <= 10000.0);
    out.hasHdrStaticMeta    = hdrOk ? 1 : 0;
    out.hdrMaxCLL           = hdrOk ? (float)m_st.hdrCll : 0.0f;
    out.hdrMaxFALL          = hdrOk ? (float)m_st.hdrFall : 0.0f;
    out.hdrMasteringMaxNits = hdrOk ? (float)m_st.hdrMaxMLL : 0.0f;
    out.hdrMasteringMinNits = hdrOk ? (float)m_st.hdrMinMLL : 0.0f;
    m_st.Unlock();
}

HRESULT CDeckLinkOutputPin::StartCaptureSession(const wchar_t* deviceName)
{
    // Session already up (this instance is single-shot; the engine uses a fresh
    // filter per graph build). Guard so a stray double-call cannot orphan the
    // previous discovery.
    if (m_input) {
        StateLog(&m_st, "[DECKLINK][src] StartCaptureSession ignored (session already up)");
        return S_FALSE;
    }

    // Standard DeckLink discovery (same path as decklink_monitor/spike). Runs on
    // the calling (engine, STA/MT graph) thread so errors surface synchronously.
    // DeckLink interface objects are non-agile custom in-proc COM (Both): direct
    // calls from the worker and the capture thread are legal and are serialized
    // under CaptureState.lock.
    char narrow[256] = {};
    if (deviceName) WideCharToMultiByte(CP_UTF8, 0, deviceName, -1, narrow, sizeof(narrow), NULL, NULL);
    StateLog(&m_st, "[DECKLINK][src] StartCaptureSession device='%s'", narrow);

    CComPtr<IDeckLinkIterator> it;
    HRESULT hr = it.CoCreateInstance(CLSID_CDeckLinkIterator, NULL, CLSCTX_ALL);
    if (FAILED(hr) || !it) {
        StateLog(&m_st, "[DECKLINK][src] iterator CoCreate FAILED hr=0x%08X", (unsigned)hr);
        return hr;
    }

    CComPtr<IDeckLink> dev;
    BOOL found = FALSE;
    while (it->Next(&dev) == S_OK) {
        CComBSTR bname;
        if (FAILED(dev->GetDisplayName(&bname))) continue;
        char nm[256] = {};
        WideCharToMultiByte(CP_UTF8, 0, bname, -1, nm, sizeof(nm), NULL, NULL);
        if (!narrow[0] || strstr(nm, narrow) || strcmp(nm, narrow) == 0) { found = TRUE; break; }
        dev.Release();
    }
    if (!found) {
        StateLog(&m_st, "[DECKLINK][src] device '%s' NOT FOUND", narrow);
        return HRESULT_FROM_WIN32(ERROR_DEVICE_NOT_CONNECTED);
    }

    CComPtr<IDeckLinkInput> input;
    hr = dev->QueryInterface(IID_IDeckLinkInput, (void**)&input);
    if (FAILED(hr) || !input) {
        StateLog(&m_st, "[DECKLINK][src] QI IDeckLinkInput FAILED hr=0x%08X", (unsigned)hr);
        return hr;
    }

    m_dev = dev.Detach();
    m_input = input.Detach();

    // REMOVED 2026-09-18: the IDeckLinkHDMIInputEDID read probe. It answered its
    // question — this card's input EDID already reports bmdDynamicRangeHDRStaticPQ,
    // so it does advertise HDR, and yet the source still sends no ST.2086 payload —
    // but it was added in the same session that capture regressed (connected media
    // type stuck at 1080p while the source streamed 4K24, so ~99% of frames were
    // gate-dropped). A QI plus GetInt on the EDID interface is the only plausible
    // thing that could have disturbed the EDID handshake, so it is gone until that
    // is ruled out. If it is ever needed again, prove capture stays healthy first.

    // Wire the capture callback — the SDK input thread only invokes
    // VideoInputFrameArrived / VideoInputFormatChanged after SetCallback, and
    // it AddRefs the callback for us (drop our local ref right after the set).
    m_cb = new CDeckLinkCaptureCallback(this, &m_st, m_input);
    hr = m_input->SetCallback(m_cb);
    StateLog(&m_st, "[DECKLINK][src] SetCallback hr=0x%08X", (unsigned)hr);
    m_cb->Release();
    m_cb = nullptr;              // SDK owns it now; never deref here

    // Boot the session + forwarder threads. The forwarder owns Deliver; the
    // callback enqueues (bounded) and never blocks on the renderer.
    ResetEvent(m_st.firstDataEvent);
    InterlockedExchange(&m_st.quit, 0);
    if (!m_dataEvent) m_dataEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!m_worker.joinable())
        m_worker = std::thread(&CDeckLinkOutputPin::WorkerLoop, this);
    if (!m_forwarder.joinable() && m_dataEvent)
        m_forwarder = std::thread(&CDeckLinkOutputPin::ForwardLoop, this);
    SetEvent(m_st.restartEvent);               // worker: enable + start

    // Block (bounded) until the first detected format or frame is known, so the
    // caller can connect with the REAL media type instead of 1080p50 defaults.
    // Graceful: on timeout we carry on with defaults; the size gate in the
    // callback makes a later real format safe (frames dropped until resync).
    m_st.Lock();
    const bool needFormat = (m_st.width <= 0);
    m_st.Unlock();
    if (needFormat) {
        StateLog(&m_st, "[DECKLINK][src] waiting up to 3s for the first format event...");
        const DWORD w = WaitForSingleObject(m_st.firstDataEvent, 3000);
        m_st.Lock();
        StateLog(&m_st, "[DECKLINK][src] first format wait=%u -> %lux%lu @ %lu/%lu fps",
            (unsigned)w, (unsigned long)m_st.width, (unsigned long)m_st.height,
            (unsigned long)m_st.fpsNum, (unsigned long)m_st.fpsDen);
        m_st.Unlock();
    } else {
        StateLog(&m_st, "[DECKLINK][src] format already known, continuing");
    }
    return S_OK;
}

void CDeckLinkOutputPin::StopDelivery()
{
    // PHASE 1 of the ordered teardown (DESIGN.md): halt the FEEDER at the
    // source WITHOUT joining anything and WITHOUT waiting on the renderer.
    //   1. SetCallback(nullptr): the SDK stops invoking us — nothing new can
    //      enter the pipeline. It never blocks on the renderer.
    //   2. Flags + wake: the forwarder drains/abandons, the worker runs its
    //      quit path (StopStreams + DisableVideoInput — the worker is the ONLY
    //      thread allowed to call those synchronously; calling from here can
    //      block on an in-flight Deliver against a live renderer).
    if (m_input) m_input->SetCallback(nullptr);
    m_st.Lock();
    const bool wasStreaming = m_st.started != 0;
    m_st.Unlock();
    InterlockedExchange(&m_st.stopPending, 1);
    InterlockedExchange(&m_st.quit, 1);
    InterlockedExchange(&m_st.active, 0);
    SetEvent(m_st.restartEvent);
    if (m_dataEvent) SetEvent(m_dataEvent);
    StateLog(&m_st, "[DECKLINK][src] StopDelivery (streaming=%d in=%d)",
        wasStreaming, m_input != nullptr);
}

void CDeckLinkOutputPin::JoinCaptureThreads()
{
    // PHASES 2-3: join the source's threads. SAFE ONLY AFTER StopDelivery AND
    // after the caller disconnected this pin from the renderer (an in-flight
    // Deliver then returns immediately). Both threads exit via their quit
    // flags; joining them is just waiting for their current iteration.
    if (m_dataEvent) SetEvent(m_dataEvent);
    if (m_forwarder.joinable()) m_forwarder.join();
    if (m_worker.joinable()) m_worker.join();
    if (m_dataEvent) { CloseHandle(m_dataEvent); m_dataEvent = nullptr; }
    if (m_input) { m_input->Release(); m_input = nullptr; }
    if (m_dev)   { m_dev->Release();   m_dev = nullptr; }
}

void CDeckLinkOutputPin::StopCaptureSession()
{
    StopDelivery();
    JoinCaptureThreads();
}

// Read ST 2086 from the frame the callback handed off. Runs on the worker thread
// (CoInit MTA), never in the SDK delivery callback — this is the whole point of the
// hand-off. Takes ownership of the held frame ref and releases it here.
void CDeckLinkOutputPin::SampleHdrMetadata()
{
    IDeckLinkVideoInputFrame* frame = (IDeckLinkVideoInputFrame*)InterlockedExchangePointer(
        (PVOID*)&m_st.hdrSampleFrame, nullptr);
    InterlockedExchange(&m_st.hdrSamplePending, 0);
    if (!frame) return;

    CComPtr<IDeckLinkVideoFrameMetadataExtensions> meta;
    if (SUCCEEDED(frame->QueryInterface(IID_IDeckLinkVideoFrameMetadataExtensions, (void**)&meta)) && meta) {
        double cll = 0.0, fall = 0.0, mMax = 0.0, mMin = 0.0;
        const HRESULT hCll  = meta->GetFloat(bmdDeckLinkFrameMetadataHDRMaximumContentLightLevel, &cll);
        const HRESULT hFall = meta->GetFloat(bmdDeckLinkFrameMetadataHDRMaximumFrameAverageLightLevel, &fall);
        const HRESULT hMax  = meta->GetFloat(bmdDeckLinkFrameMetadataHDRMaxDisplayMasteringLuminance, &mMax);
        const HRESULT hMin  = meta->GetFloat(bmdDeckLinkFrameMetadataHDRMinDisplayMasteringLuminance, &mMin);

        // Only publish if the content-light pair came back; a failed read must not
        // overwrite a good one with zeros.
        if (SUCCEEDED(hCll) && SUCCEEDED(hFall) && cll > 1.0 && cll <= 10000.0) {
            m_st.Lock();
            const bool changed = (m_st.hdrMetaLogged == 0)
                || cll != m_st.hdrCll || fall != m_st.hdrFall
                || mMax != m_st.hdrMaxMLL || mMin != m_st.hdrMinMLL;
            m_st.hdrCll = cll;     m_st.hdrFall = fall;
            m_st.hdrMaxMLL = mMax; m_st.hdrMinMLL = mMin;
            if (changed) {
                m_st.hdrMetaLogged = 1;
                StateLog(&m_st, "[HDRMETA] frame %llu  MaxCLL=%g  MaxFALL=%g  masteringMax=%g  masteringMin=%g",
                    m_st.frames, cll, fall, mMax, mMin);
            }
            m_st.Unlock();
        } else if (m_st.hdrMetaLogged == 0) {
            StateLog(&m_st, "[HDRMETA] read failed (hr cll/fall/max/min = 0x%08X/0x%08X/0x%08X/0x%08X) — frame flagged HDR but no usable values",
                (unsigned)hCll, (unsigned)hFall, (unsigned)hMax, (unsigned)hMin);
        }
    }
    frame->Release();
}

// ---------------------------------------------------------------------------
// Worker loop: owns Enable/Start/Stop and idempotent renegotiation
// ---------------------------------------------------------------------------
void CDeckLinkOutputPin::WorkerLoop()
{
    // The worker issues no its own activations (discovery runs on the engine
    // thread), but a COINIT_MULTITHREADED apartment here mirrors ffmpeg's
    // decklink and keeps SDK calls well-formed.
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    StateLog(&m_st, "[DECKLINK][src] worker entered");

    for (;;) {
        // Park until an event OR — when an Enable retry is pending — wake every
        // 500 ms to try again. This is the convergence rule: the monitor's
        // command stands; the capture keeps trying until the card accepts it
        // (an Enable that fails because the HDMI is mid-renegotiation must NOT
        // park forever, or the relaunched graph stays black).
        m_st.Lock();
        const bool retryPending = (m_st.enableRetry != 0);
        m_st.Unlock();
        const DWORD waitMs = retryPending ? 500 : INFINITE;
        // Wait on both the restart cue and the ST 2086 hand-off. The metadata read
        // belongs here (worker thread), never in the SDK delivery callback.
        HANDLE waits[2] = { m_st.restartEvent, m_st.hdrSampleEvent };
        const DWORD wr = WaitForMultipleObjects(2, waits, FALSE, waitMs);
        if (wr == WAIT_OBJECT_0 + 1) {                 // a frame was handed off → read it
            SampleHdrMetadata();
            continue;                                   // no restart work; keep waiting
        }
        if (wr == WAIT_OBJECT_0) ResetEvent(m_st.restartEvent);

        m_st.Lock();
        if (m_st.quit) {
            if (m_st.hdrSampleFrame) { m_st.hdrSampleFrame->Release(); m_st.hdrSampleFrame = nullptr; }
            m_st.hdrSamplePending = 0;
            StateLog(&m_st, "[DECKLINK][src] worker quit"); m_st.Unlock(); break;
        }
        if (!m_input)  { m_st.Unlock(); continue; }   // only between spawn+set
        StateLog(&m_st, "[DECKLINK][src] worker woke: active=%d stop=%d started=%d retry=%d",
            m_st.active, m_st.stopPending, m_st.started, m_st.enableRetry);

        // Asynchronous teardown: the graph thread must never block on
        // StopStreams (an in-flight Deliver against the renderer being stopped
        // would deadlock it); the worker owns the SDK stop. Runs on this
        // thread — never inside an SDK callback.
        if (!m_st.active && m_st.stopPending && m_st.started) {
            m_input->StopStreams(); m_st.started = 0;
            StateLog(&m_st, "[DECKLINK][src] card stopped (async teardown path)");
        }

        // Start pre-connect on the very first wake (mode detection → the caller
        // connects with the real media type); afterwards stream only while the
        // pin is active. All SDK calls below are serialized under the CS and are
        // never made from inside a callback.
        const bool wantStream = (m_st.active != 0) || (m_st.everStarted == 0);

        // Idempotent renegotiation: only a real display-mode difference forces a
        // restart; a colorspace-only event (HDR cue) never restarts. modeDiff is
        // evaluated BEFORE the !started test so a change during streaming is
        // applied (not swallowed).
        bool modeDiff = false;
        if (m_st.formatOutstanding) {
            m_st.formatOutstanding = 0;
            if (m_st.pendingMode != m_st.mode) {
                modeDiff = true;
                m_st.mode = m_st.pendingMode;
            }
            m_st.modeApplied = 1;      // real detected mode is now in m_st.mode
            StateLog(&m_st, "[DECKLINK][src] applied detected mode=%#x (pre-connect)", (unsigned)m_st.mode);
        }

        // 12-bit capture probe — ONE shot per session. Runs AFTER the mode apply
        // above so the request uses the REAL detected mode (the earlier probe
        // runs used the pre-detection default Hp50 → bogus 1080p50/black 12-bit
        // stream, and after detection locked 4K the card REFUSED that mode with
        // E_ACCESSDENIED). Does the driver accept bmdFormat12BitRGB at the real
        // mode? If yes, the card's color processor converts wire YUV→R12B and we
        // measure the true bit depth (callback logs low-nibble entropy), then
        // revert to v210 so real delivery is untouched.
        if (m_st.twelveProbe == 0 && !m_st.quit && m_input && m_st.modeApplied) {
            m_st.twelveProbe = 1;
            // Run the whole probe OUTSIDE the CS (we hold it at this point).
            // StopStreams/DisableVideoInput wait for an in-flight SDK callback
            // to return; if the callback is parked at the CS (as it is whenever
            // we hold it across the stream window) that is a hard deadlock —
            // observed this exact way on the first probe run (s3_shell hang).
            m_st.Unlock();
            const BMDDisplayMode pMode = (BMDDisplayMode)m_st.mode;
            const HRESULT hrP = m_input->EnableVideoInput(pMode,
                bmdFormat12BitRGB, bmdVideoInputEnableFormatDetection);
            StateLog(&m_st, "[12bit] EnableVideoInput(12BitRGB mode=%#x) hr=0x%08X%s",
                pMode, (unsigned)hrP,
                SUCCEEDED(hrP) ? " — ACCEPTED" : " — refused (10-bit front-end)");
            if (SUCCEEDED(hrP)) {
                m_st.Lock();
                m_st.twelve = 1;
                m_st.Unlock();
                const HRESULT hrS = m_input->StartStreams();
                StateLog(&m_st, "[12bit] StartStreams hr=0x%08X — capturing probe frames for LSB analysis", (unsigned)hrS);
                Sleep(1500);            // callbacks run their LSB/byte dump meanwhile
                if (m_input) { m_input->StopStreams(); m_input->DisableVideoInput(); }
                m_st.Lock();
                m_st.twelve = 0;
                m_st.Unlock();
                StateLog(&m_st, "[12bit] stopped probe, reverted to the v210 path");
            }
            m_st.Lock();                 // re-acquire — the normal path below continues
        }

        bool notifyRestart = false;    // format changed → engine should gracefully rebuild
        void* renegCtx = nullptr;
        DeckLinkRestartFn renegFn = nullptr;

        if (modeDiff || (wantStream && !m_st.started)) {
            if (modeDiff) {
                m_st.renegotiations++;
                StateLog(&m_st, "[DECKLINK][src] mode change → restart (reneg #%llu)", m_st.renegotiations);
                // Authoritative colours + EOTF from the DeckLink status. Safe
                // here: this is the WORKER thread, not an SDK callback (reading
                // the status inside a callback was what stalled the driver).
                // Feeds the live panel + next media type, and flags the engine
                // to rebuild so the NEW format drives delivery.
                CComPtr<IDeckLinkStatus> ist;
                if (SUCCEEDED(m_input->QueryInterface(IID_IDeckLinkStatus, (void**)&ist)) && ist) {
                    LONGLONG v = 0;
                    if (SUCCEEDED(ist->GetInt(bmdDeckLinkStatusDetectedVideoInputColorspace, &v))) {
                        // 0 (unknown) is a real answer and must stay 0, not become
                        // "BT.709". The old `: 2` fallback reported a detection that
                        // had not happened, so an unrecognised value was announced as
                        // BT.709 and the panel showed it as fact. 0 already behaves as
                        // BT.709 in the media type below (both else-branches default
                        // to 709), so nothing downstream changes — only the claim does.
                        m_st.colorspace = (v == (LONGLONG)bmdColorspaceRec2020) ? 3
                                        : (v == (LONGLONG)bmdColorspaceRec601)  ? 1
                                        : (v == (LONGLONG)bmdColorspaceRec709)  ? 2 : 0;
                    }
                    // OBSERVATION ONLY — the two mode status items, logged side by side.
                    //
                    // DetectedVideoInputMode is the mode the SOURCE is sending;
                    // CurrentVideoInputMode is the mode we are CAPTURING IN. When they
                    // disagree the connected media type is stale, and the capture
                    // callback's size gate then discards every frame whose dimensions
                    // differ from it — which is exactly how a 4K24 source being
                    // captured at a 1080p media type lost 446 of 451 frames, with the
                    // only visible symptom a stutter in the picture.
                    //
                    // Nothing acts on this yet, deliberately: the same disagreement
                    // during StartCapture is normal (the card reports a default mode
                    // before the source's is known), so a guard needs to tell those
                    // apart before it may force a renegotiation. Log it first and see
                    // what the healthy and unhealthy cases actually look like.
                    if (SUCCEEDED(ist->GetInt(bmdDeckLinkStatusDetectedVideoInputMode, &v))) {
                        const unsigned long long det = (unsigned long long)v;
                        LONGLONG cur = 0;
                        const bool haveCur = SUCCEEDED(ist->GetInt(bmdDeckLinkStatusCurrentVideoInputMode, &cur));
                        const unsigned long long curM = haveCur ? (unsigned long long)cur : 0;
                        StateLog(&m_st, "[DECKLINK][src] modes: detected=%#llx current=%#llx%s conn=%dx%d%s",
                            det, curM, haveCur ? "" : " (current unreadable)",
                            (int)m_connWidth, (int)m_connHeight,
                            (haveCur && det != curM) ? "  <-- MISMATCH: source mode != capture mode" : "");
                    }
                    if (SUCCEEDED(ist->GetInt(bmdDeckLinkStatusVideoInputSignalLocked, &v))) {
                        StateLog(&m_st, "[DECKLINK][src] signalLocked=%lld", (long long)v);
                    }
                    if (SUCCEEDED(ist->GetInt(bmdDeckLinkStatusDetectedVideoInputDynamicRange, &v))) {
                        if (v & bmdDynamicRangeHDRStaticHLG)      m_st.eotf = 3;
                        else if (v & bmdDynamicRangeHDRStaticPQ)  m_st.eotf = 2;
                        // DV fingerprint (probed 2026-09-14, Dune DV disc):
                        // player sends BT.2020 but REPLACES the HDR10 static
                        // InfoFrame with Dolby's own → dsdr reads SDR. The
                        // pixels are PQ-coded DV (FEL-fused). eotf=4 (DV) keeps
                        // the media type PQ (2084) so a rebuild landing on this
                        // state still builds HDR, while the panel can still
                        // say "Dolby Vision" instead of collapsing to HDR10.
                        else if (m_st.colorspace == 3) m_st.eotf = 4;
                        // Everything else IS SDR, and this has to be stated rather
                        // than left to inheritance. Without this branch eotf kept
                        // whatever the PREVIOUS title set, so a later SDR signal
                        // was still announced as PQ — and the media type went out
                        // as 2084, so the renderer decoded gamma-encoded SDR as PQ
                        // and tone-mapped it again.
                        //
                        // Observed on a Dolby Vision Profile 5 title from an Oppo:
                        // P5 is single-layer with no HDR10 base layer, the Oppo sees
                        // a capture card whose EDID advertises no HDR, and so it
                        // converts DV to SDR and signals cs=2/dsdr=0 honestly. The
                        // stale eotf then made Unplugged treat that SDR output as
                        // PQ. (P7 survives this because it carries an HDR10 base
                        // layer, so the Oppo can fall back to HDR instead.)
                        else m_st.eotf = 0;
                    }
                    StateLog(&m_st, "[DECKLINK][src] format change: status cs=%d eotf=%d — engine rebuild requested",
                        m_st.colorspace, m_st.eotf);
                }
                // Fire only once the graph is actually connected (conn>0 or
                // frames delivered): the FIRST detection during StartCapture is
                // what the connect uses — a rebuild echo there would loop.
                if (m_connWidth > 0 || m_st.delivered > 0) {
                    notifyRestart = true;
                    renegCtx = m_st.restartCtx;
                    renegFn  = m_st.restartFn;
                }
            }
            // ── In-session renegotiation is NOT ours to do ───────────────────
            //
            // On a mode change while the graph is already connected and
            // delivering, renegotiating here re-enables the input and re-pushes
            // this pin's media type — which lands in the RENDERER as
            // CMpcVideoRenderer::SetMediaType, re-deriving its media type via
            // InitMediaType() on THIS worker thread and queuing a second swap
            // consumed inside DoRenderSample. The render path holds no lock, so
            // that is an access violation at a fixed address in
            // MpcVideoRenderer64.ax — observed 2026-09-21, immediately after a
            // `VideoInputFormatChanged` on disc stop (movie -> menu).
            //
            // Rebuilding the graph is the ENGINE's job, and DESIGN.md already
            // says how: step 5 of the teardown script launches a FRESH filter
            // instance, which enables the input with the new mode in a clean SDK
            // session. The monitor sees the colour-space/dynamic-range change and
            // the ingest decider requests a Reload, so the transition still
            // completes — without this pin ever changing the renderer's media
            // type mid-stream.
            //
            // Known cost, deliberate: a change that alters ONLY the resolution
            // (colour space and dynamic range identical) produces no monitor fact,
            // so nothing requests the rebuild. The size gate drops those frames,
            // so the picture stays black until something else forces a rebuild.
            // Closing that needs the filter's measured format fed to the ingest
            // decider as a fact — the follow-up to this change.
            const bool graphConnected = (m_connWidth > 0 || m_st.delivered > 0);
            const bool midStreamModeDiff = modeDiff && graphConnected;
            if (midStreamModeDiff) {
                StateLog(&m_st, "[DECKLINK][src] mode change while connected (mode=%#x) — NOT "
                    "renegotiating in-session; waiting for the engine to rebuild", (unsigned)m_st.mode);
            }

            if (!midStreamModeDiff && m_st.started) { m_input->StopStreams(); m_st.started = 0; }
            // A mode change needs a fresh Enable; a failed-enable reset needs a
            // Disable too so the retry (next Active wake) does not re-enable
            // while already enabled.
            if (!midStreamModeDiff && modeDiff && m_st.enabled) { m_input->DisableVideoInput(); m_st.enabled = 0; }
            if (!midStreamModeDiff && !m_st.enabled) {
                const HRESULT hrE = m_input->EnableVideoInput(m_st.mode,
                    bmdFormat10BitYUV, bmdVideoInputEnableFormatDetection);
                if (FAILED(hrE)) {
                    // Card busy / signal mid-renegotiation. Do NOT give up: arm
                    // the 500 ms retry so the capture converges to the monitor's
                    // command the moment the card accepts (otherwise a relaunch
                    // landing during the flip stays black forever).
                    m_st.enableRetry = 1;
                    StateLog(&m_st, "[DECKLINK][src] EnableVideoInput FAILED hr=0x%08X — retrying in 500 ms",
                        (unsigned)hrE);
                    m_input->DisableVideoInput(); m_st.enabled = 0;
                } else {
                    m_st.enableRetry = 0;
                    StateLog(&m_st, "[DECKLINK][src] EnableVideoInput OK mode=%#x fmt=v210 det=on",
                        (unsigned)m_st.mode);
                    m_st.enabled = 1;
                }
                if (!m_st.enabled) {
                    // Park briefly: the 500 ms wait at the top of the loop wakes
                    // us to re-attempt Enable. No active/event dependency.
                    m_st.everStarted = 1;
                    m_st.Unlock();
                    continue;
                }
            }
            if (!midStreamModeDiff) {
                const HRESULT hrS = m_input->StartStreams();
                m_st.started = (hrS == S_OK);
                m_st.everStarted = 1;
                StateLog(&m_st, "[DECKLINK][src] StartStreams hr=0x%08X (mode=%#x)", (unsigned)hrS,
                    (unsigned)m_st.mode);
                if (modeDiff) SetEvent(m_st.firstDataEvent);   // a restart is itself a format cue
            }
        }
        m_st.Unlock();

        // Format-change notification — fired OUTSIDE the CS, on this worker
        // thread, so the engine can rebuild without ever blocking us.
        if (notifyRestart && renegFn) renegFn(renegCtx);
    }

    // Quit path: stop the card if the engine teardown did not already, and
    // disable the input (resets driver state for the next session).
    m_st.Lock();
    m_st.enableRetry = 0;
    if (m_st.started)                { m_input->StopStreams();  m_st.started = 0; }
    if (m_st.enabled)                { m_input->DisableVideoInput(); m_st.enabled = 0; }
    m_st.Unlock();
    CoUninitialize();
}

// ---------------------------------------------------------------------------
// Bounded forwarder queue (Phase-2b). The SDK callback never delivers — it
// enqueues; ForwardLoop delivers on its own thread. Bounded to 3 in-flight
// samples: if the renderer stalls, the queue fills and the callback drops the
// NEWEST frame, so the card is never the one blocking.
// ---------------------------------------------------------------------------
bool CDeckLinkOutputPin::EnqueueSample(IMediaSample* s)
{
    m_st.Lock();
    const int next = (m_qTail + 1) % kQDepth;
    if (next == m_qHead) {                 // full → drop the newest (bounded)
        m_st.droppedQueue++;
        StateLog(&m_st, "[DECKLINK][src] forwarder queue FULL — dropped newest (#%llu)", m_st.droppedQueue);
        m_st.Unlock();
        return false;
    }
    m_q[m_qTail] = s;
    m_qTail = next;
    SetEvent(m_dataEvent);
    m_st.Unlock();
    return true;
}

void CDeckLinkOutputPin::ForwardLoop()
{
    for (;;) {
        WaitForSingleObject(m_dataEvent, INFINITE);
        IMediaSample* s = nullptr;
        m_st.Lock();
        const bool quit = (m_st.quit != 0);
        if (m_qHead != m_qTail) { s = m_q[m_qHead]; m_qHead = (m_qHead + 1) % kQDepth; }
        const bool active = (m_st.active != 0);
        const bool empty = (m_qHead == m_qTail);
        if (!empty) SetEvent(m_dataEvent);      // more work queued — keep the wake hot
        else if (quit) { m_st.Unlock(); break; }
        m_st.Unlock();
        if (s) {
            if (active) Deliver(s);             // may block on the renderer — never the card
            s->Release();
        }
    }
    StateLog(&m_st, "[DECKLINK][src] forwarder exited");
}

// ---------------------------------------------------------------------------
// Capture callback implementations
// ---------------------------------------------------------------------------
STDMETHODIMP CDeckLinkCaptureCallback::VideoInputFormatChanged(
    BMDVideoInputFormatChangedEvents events,
    IDeckLinkDisplayMode* newMode,
    BMDDetectedVideoInputFormatFlags detectedSignalFlags)
{
    (void)events; (void)detectedSignalFlags;
    if (!newMode) return S_OK;

    BMDDisplayMode dm = newMode->GetDisplayMode();
    BMDTimeValue fNum = 0, fDen = 0;
    newMode->GetFrameRate(&fNum, &fDen);
    const LONGLONG w = newMode->GetWidth();    // SDK 12.x: direct returns
    const LONGLONG h = newMode->GetHeight();

    m_st->Lock();
    m_st->formatEvents++;
    m_st->pendingMode = dm;
    // GetFrameRate returns (frameDuration, frameScale); the rate is
    // frameScale / frameDuration (e.g. 1001/24000 = 23.976). Store as
    // fpsNum/fpsDen in the frames-per-second fraction convention the defaults
    // (50000/1000 = 50) and AvgTimePerFrame/rtEnd math already use — storing
    // the raw pair the other way inverted every derived number (23.97 s/frame).
    if (fNum > 0 && fDen > 0) { m_st->fpsNum = (LONG)fDen; m_st->fpsDen = (LONG)fNum; }
    if (w > 0 && h > 0) { m_st->width = (LONG)w; m_st->height = (LONG)h; }
    // Colorspace / EOTF hints: the card reports these through DetectedFlags
    // (bmdDetectedVideoInputRGB444/YCbCr422) and the frame flags (HDR TX);
    // we update metadata only, no restart. NOTE: a DeckLink status query for
    // the real BT.2020 primaries was tried here and STALLED the capture
    // (GetInt on the SDK callback thread under the CS) — the monitor-driven
    // ICS override carries the real color-space instead.
    // The 4:2:2/4:4:4 detected-flag carries NO primary information — forcing
    // BT.709 here is what made an HDR HDMI signal (BT.2020, YCbCr4:2:2) report
    // BT.709 to the renderer and the panel (2026-09-15 bench). The authoritative
    // primaries come from the WORKER's bmdDeckLinkStatusDetectedVideoInput-
    // Colorspace read (outside SDK callbacks — a status query in-callback
    // stalled the capture historically) and the monitor's SetSignalMeta.
    (void)detectedSignalFlags;
    if (events & bmdVideoInputColorspaceChanged) {
        // DO NOT invent an EOTF here. This used to force `eotf = 2` (PQ) on the
        // theory that "the 0x04 event precedes HDR content on HDMI", to be refined
        // later by per-frame flag reads in a "Phase 2b" that was never implemented.
        // Nothing refined it, so it simply OVERWROTE the worker's real measurement:
        // captured live, the worker read the card status and logged cs=2 eotf=0,
        // then this callback set eotf=2 ten milliseconds later, and the media type
        // went out as 2084/PQ for an SDR signal.
        //
        // It also made the reported state depend on which of the two ran last — the
        // same signal read eotf=2 or eotf=0 from one run to the next, which is the
        // intermittency that made "Convert to SDR" and the HDR detection look
        // unreliable. Readings previously taken as "HDR10 detected" (cs=2 eotf=2)
        // were often this forced value rather than a detection.
        //
        // The EOTF has exactly one authoritative source, and it is not a callback:
        // bmdDeckLinkStatusDetectedVideoInputDynamicRange, read on the WORKER
        // (a status query inside an SDK callback stalled the driver historically —
        // see the note below). That read distinguishes HLG, PQ, the DV fingerprint
        // (BT.2020 + SDR) and plain SDR on its own.
        //
        // The cost is that the very first media type may be built before the
        // worker's first read lands, so a cold start on HDR content can begin as
        // SDR and correct on the rebuild that the worker's format-change already
        // requests. That is preferable to announcing PQ for content that is not.
        StateLog(m_st, "[DECKLINK][src] colorspaceChanged event — EOTF left to the worker's status read (eotf=%d)",
            m_st->eotf);
    }
    m_st->formatOutstanding = 1;
    m_st->Unlock();
    StateLog(m_st, "[DECKLINK][src] VideoInputFormatChanged mode=%#x %lux%lu @ %.3f fps (%lu/%lu) flags=%#x",
        (unsigned)dm, (unsigned long)w, (unsigned long)h,
        (fDen > 0 && fNum > 0) ? ((double)fDen / (double)fNum) : 0.0,
        (unsigned long)fDen, (unsigned long)fNum, (unsigned)detectedSignalFlags);
    // `w`/`h` are logged above but the state only takes them when both are > 0, so a
    // 0 would leave width/height stale while the mode and rate updated — the card
    // would enable the new mode, the media type would be built from the OLD size, and
    // the capture callback's size gate would then discard every frame of the new one.
    // (Observed 2026-09-18: source 4K24, media type 1080p, 446 of 451 frames dropped.)
    // Log the take explicitly so that failure is distinguishable from a wrong mode.
    if (!(w > 0 && h > 0)) {
        StateLog(m_st, "[DECKLINK][src] !! GetWidth/GetHeight returned %lldx%lld — dimensions NOT updated (state stays %ldx%ld)",
            (long long)w, (long long)h, (long)m_st->width, (long)m_st->height);
    }
    SetEvent(m_st->firstDataEvent);    // a format is known → release StartCapture wait
    SetEvent(m_st->restartEvent);      // worker renegotiates (mode-diff only)
    return S_OK;
}

STDMETHODIMP CDeckLinkCaptureCallback::VideoInputFrameArrived(
    IDeckLinkVideoInputFrame* videoFrame, IDeckLinkAudioInputPacket* audioPacket)
{
    (void)audioPacket;
    if (!videoFrame) return S_OK;

    const LONG realW = (LONG)videoFrame->GetWidth();
    const LONG realH = (LONG)videoFrame->GetHeight();
    void* rbCtx = nullptr;                 // throttle-fired rebuild request (after Unlock)
    DeckLinkRestartFn rbFn = nullptr;

    // Snapshot the state needed for delivery under the lock (short) so the
    // pin's AcquireSample/Deliver below never run while holding it (they can
    // block on renderer buffers; holding the CS there would wedge the worker
    // and the stop path). The SDK releases the frame once this callback returns,
    // so the v210 bytes are copied here, never retained.
    m_st->Lock();
    m_st->frames++;
    const bool isFirstFrame = (m_st->frames == 1);
    const bool isFirstDlv   = (m_st->delivered == 0);
    const LONG connW        = m_pin->ConnWidth();
    const LONG connH        = m_pin->ConnHeight();
    // Size gate: deliver only when the frame matches the negotiated media type.
    // DROP, never clip — a 4K frame copied into a 1080-sized sample would
    // overrun the shared allocator buffer. Mismatch = a format change is pending
    // (the monitor rebuild resyncs); counted as skipped.
    const bool deliver = (m_st->active != 0) && (m_st->stopPending == 0) &&
                         (connW > 0) && (realW == connW) && (realH == connH) &&
                         (m_st->twelve == 0);          // R12B probe frames never reach the v210 path
    const LONG stride = videoFrame->GetRowBytes();
    const LONG fpsNum = m_st->fpsNum;
    const LONG fpsDen = m_st->fpsDen;
    if (m_st->width <= 0 && realW > 0) {        // no format event seen yet
        m_st->width = realW; m_st->height = realH;
    }
    if (!deliver) {
        m_st->skipped++;
        if (connW > 0 && (realW != connW || realH != connH)) {
            m_st->gateDropped++;              // dims differ from the connected type
            // Correct the STATE from the frame before asking for a rebuild.
            //
            // This is what makes the self-heal below able to converge. The state only
            // ever takes its dimensions from a format EVENT (see the `width <= 0`
            // case above), so if that event does not re-fire — which is what happens
            // once the handshake has settled on the wrong mode — width/height stay
            // stale, GetMediaType rebuilds the SAME wrong type, the frames still
            // mismatch, and the rebuild repeats every 1.5 s forever. Observed
            // 2026-09-18: the card was torn down and rebuilt on that cadence while
            // 446 of 451 frames were gate-dropped, and only an app restart recovered
            // it. The FRAME's dimensions are ground truth — the card is delivering
            // them — so the state is corrected from those.
            if (realW > 0 && realH > 0 && (m_st->width != realW || m_st->height != realH)) {
                StateLog(m_st, "[DECKLINK][src] size gate: state %ldx%ld != frames %ldx%ld — taking the frame's size",
                    (long)m_st->width, (long)m_st->height, (long)realW, (long)realH);
                m_st->width = realW; m_st->height = realH;
            }
            // The connected type is STALE — request an engine rebuild so the
            // new format drives delivery. Throttled: the SDK can fire many
            // mismatched frames while the graph is mid-flip, and the engine
            // rebuilds serially; 1.5 s keeps it calm. This is the self-heal
            // path ("blank because the graph holds an old media type").
            const DWORD64 nowMs = GetTickCount64();
            if (m_st->restartFn && nowMs - m_st->lastRebuildMs > 1500) {
                m_st->lastRebuildMs = nowMs;
                rbCtx = m_st->restartCtx;
                rbFn  = m_st->restartFn;
            }
        }
    }
    if (isFirstFrame) SetEvent(m_st->firstDataEvent);
    // Telemetry — periodically surface arrived/skipped/delivered + why not
    // delivered (size gate vs pin inactive), so monitor→source→renderer is
    // observable in the shell log.
    if ((m_st->frames % 25) == 1 || isFirstFrame) {
        StateLog(m_st,
            "[DECKLINK][src] frame %llu: %lux%lu @ %lu/%lu arrived=%llu skip=%llu dlv=%llu active=%d conn=%lux%lu",
            m_st->frames, (unsigned long)realW, (unsigned long)realH,
            (unsigned long)fpsNum, (unsigned long)fpsDen,
            m_st->frames, m_st->skipped, m_st->delivered,
            m_st->active, (unsigned long)connW, (unsigned long)connH);
    }

    // hwRef (µs, wall-aligned) → graph-relative sample time. DirectShow clocks
    // begin near 0 at graph start; absolute hwRef values would schedule the
    // frame hours in the future and the renderer would never release it. We
    // re-anchor the base on the first *delivered* frame (after each Active/
    // start), so the stream time advances 1:1 with capture from there — MPCVR's
    // relative present-latency gauge stays valid (same semantics as the LAV
    // path). If the SDK returns 0 (no reference lock yet), carry the previous
    // frame forward so never a spurious zero timestamp.
    BMDTimeValue refTime = 0;
    videoFrame->GetHardwareReferenceTimestamp(1000000, &refTime, nullptr);
    if (refTime == 0 && m_st->prevRefUs != 0) {
        const LONG64 avgUs = (fpsNum > 0) ? (1000000LL * fpsDen) / fpsNum : 20000LL;
        refTime = m_st->prevRefUs + avgUs;
    }
    if (refTime != 0) m_st->prevRefUs = refTime;
    if (deliver && m_st->rtBaseUs == 0) m_st->rtBaseUs = refTime;
    const LONG64 rtRelUs = (m_st->rtBaseUs != 0 && refTime >= m_st->rtBaseUs)
        ? (refTime - m_st->rtBaseUs) : 0;
    m_st->Unlock();
    if (rbFn) rbFn(rbCtx);      // gate-throttled rebuild request (non-blocking)

    // 12-bit probe frames (R12B): log the layout + a bit-depth signature. Real
    // 12-bit data from the card's converter has entropy in every byte's low
    // nibble; 10-bit sampled-then-padded data has near-zero low-nibble entropy
    // (the LSB padding bits stay 0). Raw bytes are dumped too so the layout
    // can be read offline.
    if (m_st->twelve == 1) {
        void* src = nullptr;
        if (videoFrame->GetBytes(&src) == S_OK && src) {
            const BYTE* p = (const BYTE*)src;
            const LONG rb = videoFrame->GetRowBytes();
            const long cap = std::min<long>(rb * realH, 256L * 1024);
            long nz = 0;
            for (long i = 0; i < cap; ++i) if (p[i] & 0x0F) nz++;
            char hex[96] = {};
            for (int i = 0; i < 32 && i < rb; ++i) sprintf_s(hex + i * 2, sizeof(hex) - i * 2, "%02X", p[i]);
            StateLog(m_st, "[12bit] frame %lld %ldx%ld rowbytes=%ld | lowNibbleNz=%ld/%ld (%.2f%%) head8=%s",
                (long long)m_st->frames, (long)realW, (long)realH, (long)rb,
                nz, cap, cap ? (100.0 * nz / cap) : 0.0, hex);
        }
    }

    // HDR-signal probe — one frame per DISTINCT signal. Dumps everything the SDK will
    // tell us about this input, raw. Bench question: does the card parse HDMI
    // InfoFrame colorimetry + ST 2086, or not? Nothing user-visible; this block is
    // deleted once the answers are in.
    //
    // Re-armed by the worker on a format change, so it lands on the HDR frame rather
    // than on frame 1 (see metaProbes).
    if (kInCallbackDriverQueries && m_st->metaProbe == 0) {
        // ONE frame per session, deliberately. This queries IDeckLinkStatus on the SDK
        // callback thread, and a status query in-callback is known to stall this
        // driver. Re-arming it per format change (tried 2026-09-18) broke capture:
        // the card stayed on a 1080p mode while the source was 4K, so 49 of 51 frames
        // were gate-dropped and the signal classification came back cs=0 eotf=0.
        // If this ever needs to run on an HDR frame, do the status read on the WORKER
        // and only pass the result here.
        m_st->metaProbe = 1;
        CComPtr<IDeckLinkStatus> st;
        if (m_input && SUCCEEDED(m_input->QueryInterface(IID_IDeckLinkStatus, (void**)&st))) {
            LONGLONG v = 0;
            if (SUCCEEDED(st->GetInt(bmdDeckLinkStatusDetectedVideoInputColorspace, &v)))
                StateLog(m_st, "[PROBE] dscl (colorspace) = 0x%llX", (unsigned long long)v);
            if (SUCCEEDED(st->GetInt(bmdDeckLinkStatusDetectedVideoInputDynamicRange, &v)))
                StateLog(m_st, "[PROBE] dsdr (dyn. range) = 0x%llX", (unsigned long long)v);
            if (SUCCEEDED(st->GetInt(bmdDeckLinkStatusCurrentVideoInputPixelFormat, &v)))
                StateLog(m_st, "[PROBE] cvip (pix fmt)    = 0x%llX  (%u-bit YUV/RGB payload)",
                    (unsigned long long)v, (v == 0x76323130ull) ? 10 : (v == 0x52313242ull || v == 0x5231324cull) ? 12 : (v == 0x72323130ull) ? 10 : (v == 0x32767579ull) ? 8 : 0);
            // EDID the card PRESENTS to the source (the Integral): its max color
            // depth + any Dolby VSVDB decide what the Integral is even allowed
            // to send. 12-bit on the wire REQUIRES the EDID to claim it.
            BYTE edid[256] = {};
            unsigned int esz = sizeof(edid);
            const HRESULT hrE = st->GetBytes(bmdDeckLinkStatusReceivedEDID, edid, &esz);
            if (SUCCEEDED(hrE)) {
                StateLog(m_st, "[PROBE] receivedEDID bytes=%u extBlocks=%u", esz, (unsigned)edid[126]);
                char hex[70] = {};
                for (int b = 0; b < 256; b += 16) {
                    int n = 0;
                    for (int i = 0; i < 16 && (b + i) < (int)esz; ++i)
                        n += sprintf_s(hex + n, sizeof(hex) - n, "%02X ", edid[b + i]);
                    StateLog(m_st, "[PROBE]  EDID[%03d] %s", b, hex);
                }
            } else {
                StateLog(m_st, "[PROBE] receivedEDID GetBytes FAILED (hr=0x%08X)", (unsigned)hrE);
            }
        }
        CComPtr<IDeckLinkVideoFrameMetadataExtensions> meta;
        if (videoFrame && SUCCEEDED(videoFrame->QueryInterface(IID_IDeckLinkVideoFrameMetadataExtensions, (void**)&meta))) {
            // THE ACCESSOR TYPE IS THE WHOLE BALLGAME, and getting it wrong once
            // cost us months. Blackmagic's own DeckLinkAPI.idl splits these:
            //
            //   /* Colorspace Metadata - Integers */  bmdDeckLinkFrameMetadataColorspace
            //   /* HDR Metadata        - Integers */  bmdDeckLinkFrameMetadataHDRElectroOpticalTransferFunc
            //   /* HDR Metadata        - Floats   */  primaries x8, white point x2,
            //                                         mastering min/max, MaxCLL, MaxFALL
            //
            // The first version of this probe called GetInt on all fourteen and
            // printed "<unsupported>" for any failure. The twelve float-typed ones all
            // failed, and the two integer-typed ones succeeded — which is exactly what
            // a type mismatch looks like, and is precisely the evidence we recorded as
            // "the card cannot supply ST 2086 over HDMI". It was never true.
            //
            // Every failure now prints its HRESULT, so a wrong accessor can never
            // again be mistaken for genuine non-support.
            const DWORD flags = videoFrame->GetFlags();
            StateLog(m_st, "[PROBE] frame flags=0x%08X  containsHDRMeta=%d  noInputSource=%d",
                (unsigned)flags,
                (flags & bmdFrameContainsHDRMetadata) ? 1 : 0,
                (flags & bmdFrameHasNoInputSource) ? 1 : 0);

            StateLog(m_st, "[PROBE] IDeckLinkVideoFrameMetadataExtensions available — ST 2086:");

            const struct { BMDDeckLinkFrameMetadataID id; const char* name; } intIds[] = {
                { bmdDeckLinkFrameMetadataColorspace,                    "colorspace   " },
                { bmdDeckLinkFrameMetadataHDRElectroOpticalTransferFunc, "EOTF         " },
            };
            for (const auto& e : intIds) {
                LONGLONG v = 0;
                const HRESULT hr = meta->GetInt(e.id, &v);
                if (SUCCEEDED(hr)) StateLog(m_st, "[PROBE]   %s = %lld", e.name, (long long)v);
                else                StateLog(m_st, "[PROBE]   %s = n/a (hr=0x%08X)", e.name, (unsigned)hr);
            }

            // Units per the .idl: primaries/white point 0.0-1.0; maxMLL and the two
            // content-light values 1-65535 cd/m2; minMLL 0.0001-6.5535 cd/m2.
            const struct { BMDDeckLinkFrameMetadataID id; const char* name; } floatIds[] = {
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesRedX,          "primRx       " },
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesRedY,          "primRy       " },
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesGreenX,        "primGx       " },
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesGreenY,        "primGy       " },
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesBlueX,         "primBx       " },
                { bmdDeckLinkFrameMetadataHDRDisplayPrimariesBlueY,         "primBy       " },
                { bmdDeckLinkFrameMetadataHDRWhitePointX,                   "whiteptX     " },
                { bmdDeckLinkFrameMetadataHDRWhitePointY,                   "whiteptY     " },
                { bmdDeckLinkFrameMetadataHDRMaxDisplayMasteringLuminance,  "maxMLL nits  " },
                { bmdDeckLinkFrameMetadataHDRMinDisplayMasteringLuminance,  "minMLL nits  " },
                { bmdDeckLinkFrameMetadataHDRMaximumContentLightLevel,      "MaxCLL  nits " },
                { bmdDeckLinkFrameMetadataHDRMaximumFrameAverageLightLevel, "MaxFALL nits " },
            };
            for (const auto& e : floatIds) {
                double d = 0.0;
                const HRESULT hr = meta->GetFloat(e.id, &d);
                if (SUCCEEDED(hr)) StateLog(m_st, "[PROBE]   %s = %g", e.name, d);
                else                StateLog(m_st, "[PROBE]   %s = n/a (hr=0x%08X)", e.name, (unsigned)hr);
            }
        } else {
            StateLog(m_st, "[PROBE] IDeckLinkVideoFrameMetadataExtensions UNAVAILABLE on frame");
        }
    }

    // HDR static metadata (ST 2086) — handed off to the worker, NOT read here. The
    // SDK delivery callback is documented-sensitive to work (this driver dropped
    // frames when metadata COM calls ran in it), so the callback does only O(1):
    // notice an HDR-flagged frame ~1 Hz, AddRef it, and wake the worker to do the
    // QI/GetFloat reads. ST 2086 is static per title, so 1 Hz misses nothing. Not
    // gated on kInCallbackDriverQueries (that flag is for the in-callback *probe*);
    // this is a hand-off, not a query.
    if (videoFrame && (videoFrame->GetFlags() & bmdFrameContainsHDRMetadata)
            && InterlockedDecrement(&m_st->hdrMetaTick) <= 0) {
        InterlockedExchange(&m_st->hdrMetaTick, 24);            // next hand-off ~1 s at 24 fps
        if (InterlockedCompareExchange(&m_st->hdrSamplePending, 1, 0) == 0) {
            videoFrame->AddRef();                               // keep alive for the worker
            m_st->hdrSampleFrame = videoFrame;                  // one in flight (guarded above)
            SetEvent(m_st->hdrSampleEvent);
        }
    }

    if (!deliver) return S_OK;

    IMediaSample* pSample = nullptr;
    HRESULT hr = m_pin->AcquireSample(&pSample);
    if (SUCCEEDED(hr) && pSample) {
        BYTE* dst = nullptr;
        const LONG sampleBytes = (LONG)pSample->GetSize();
        HRESULT hrG = pSample->GetPointer(&dst);
        if (SUCCEEDED(hrG) && dst) {
            void* src = nullptr;
            videoFrame->GetBytes(&src);
            if (src) {
                // Convert v210 (10-bit 4:2:2, SDK row-padded stride) → P010
                // (10-bit 4:2:0) into the sample. sampleBytes is the rendered
                // budget — the converter clamps to it without overrunning.
                if (m_st->delivered < 3)
                    StateLog(m_st,
                        "[DECKLINK][src] convert v210->P010: dst=%p src=%p stride=%d %dx%d need=%d sampleBytes=%d",
                        dst, src, stride, realW, realH, P010Size(realW, realH), sampleBytes);
                V210ToP010((const BYTE*)src, stride, dst, sampleBytes, realW, realH);
            } else {
                StateLog(m_st, "[DECKLINK][src] GetBytes returned NULL src");
            }
        } else {
            StateLog(m_st, "[DECKLINK][src] GetPointer failed/empty (hr=0x%08X dst=%p sampleBytes=%d)",
                (unsigned)hrG, dst, sampleBytes);
        }
        REFERENCE_TIME rtStart = rtRelUs * 10;             // µs -> 100 ns (graph-relative)
        REFERENCE_TIME rtEnd = rtStart + (10000000LL * fpsDen) / fpsNum;
        pSample->SetTime(&rtStart, &rtEnd);
        pSample->SetDiscontinuity(isFirstDlv);   // first *delivered* frame re-cues
        m_st->Lock();
        m_st->delivered++;
        if (isFirstDlv)
            StateLog(m_st, "[DECKLINK][src] FIRST FRAME DELIVERED (rtStart=%lld us)",
                (long long)refTime);
        m_st->Unlock();
        // Hand off to the forwarder — the SDK thread never blocks on Deliver.
        if (!m_pin->EnqueueSample(pSample)) pSample->Release();
    }
    return S_OK;
}

// ---------------------------------------------------------------------------
// Filter
// ---------------------------------------------------------------------------
class CDeckLinkSource : public CBaseFilter, public IDeckLinkSourceControl {
public:
    static CUnknown* WINAPI CreateInstance(LPUNKNOWN pUnk, HRESULT* phr) {
        return new CDeckLinkSource(pUnk, phr);
    }
    DECLARE_IUNKNOWN;

    CDeckLinkSource(LPUNKNOWN pUnk, HRESULT* phr)
        : CBaseFilter(NAME("DeckLinkSource"), pUnk, &m_lock, CLSID_DeckLinkSource)
    {
        m_pPin = new CDeckLinkOutputPin(this, &m_lock, phr);
    }
    ~CDeckLinkSource() {
        if (m_pPin) {
            m_pPin->StopCaptureSession();
            delete m_pPin;
        }
    }

    STDMETHODIMP NonDelegatingQueryInterface(REFIID riid, void** ppv) override
    {
        if (riid == __uuidof(IDeckLinkSourceControl))
            return GetInterface(static_cast<IDeckLinkSourceControl*>(this), ppv);
        return CBaseFilter::NonDelegatingQueryInterface(riid, ppv);
    }

    // IDeckLinkSourceControl
    STDMETHODIMP StartCapture(BSTR deviceName) override
    {
        if (!m_pPin) return E_POINTER;
        return m_pPin->StartCaptureSession(deviceName ? deviceName : L"");
    }
    STDMETHODIMP StopDelivery() override
    {
        if (m_pPin) m_pPin->StopDelivery();
        return S_OK;
    }
    STDMETHODIMP StopCapture() override
    {
        if (m_pPin) m_pPin->StopCaptureSession();
        return S_OK;
    }
    STDMETHODIMP SetLogSink(void* ctx, DeckLinkSourceLogFn fn) override
    {
        if (!m_pPin) return E_POINTER;
        m_pPin->SetLogSink(ctx, fn);
        return S_OK;
    }
    STDMETHODIMP GetStats(DeckLinkSourceStats* p) override
    {
        if (!p || !m_pPin) return E_POINTER;
        m_pPin->GetStats(*p);
        return S_OK;
    }
    STDMETHODIMP SetSignalMeta(int colorspace, int eotf) override
    {
        if (!m_pPin) return E_POINTER;
        m_pPin->StatePtr()->Lock();
        m_pPin->StatePtr()->colorspace = colorspace;   // 0..3 (601/709/2020)
        m_pPin->StatePtr()->eotf = eotf;               // 0/2/3 (gamma/PQ/HLG)
        m_pPin->StatePtr()->Unlock();
        return S_OK;
    }
    STDMETHODIMP SetRestartCallback(void* ctx, DeckLinkRestartFn fn) override
    {
        if (!m_pPin) return E_POINTER;
        m_pPin->SetRestartCb(ctx, fn);
        return S_OK;
    }

    int GetPinCount() override { return 1; }
    CBasePin* GetPin(int n) override { return (n == 0) ? (CBasePin*)m_pPin : nullptr; }
    CDeckLinkOutputPin* Pin() { return m_pPin; }

private:
    CCritSec m_lock;
    CDeckLinkOutputPin* m_pPin = nullptr;
};

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------
static const WCHAR g_name[] = L"DeckLink Source";

CFactoryTemplate g_Templates[] = {
    { (LPWSTR)g_name, &CLSID_DeckLinkSource, CDeckLinkSource::CreateInstance, nullptr, nullptr }
};
int g_cTemplates = 1;

// BaseClasses' DllEntryPoint drives g_hInst (registration reads the module
// name) + DllInitClasses; without a DllMain shim the default no-op entrypoint
// leaves g_hInst null and regsvr32 fails. Same shim LAVVideo uses.
extern "C" BOOL WINAPI DllEntryPoint(HINSTANCE, ULONG, LPVOID);
extern "C" BOOL WINAPI DllMain(HINSTANCE hDllHandle, DWORD dwReason, LPVOID lpReserved)
{
    return DllEntryPoint(hDllHandle, dwReason, lpReserved);
}

STDAPI DllRegisterServer()
{
    return AMovieDllRegisterServer2(TRUE);
}
STDAPI DllUnregisterServer()
{
    return AMovieDllRegisterServer2(FALSE);
}
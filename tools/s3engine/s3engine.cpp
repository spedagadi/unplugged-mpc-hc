// s3engine.dll — C-ABI host over mpchc_engine (MpcPlayer) for the PyQt client
// UI (C:\code\unplugged\app). The professional UI stays as-is; everything the
// UI needs crosses this ABI: attach the video window, start the self-healing
// DeckLink capture, poll a JSON status blob, send transport commands.
//
//  ABI (UTF-8 strings, caller-owned buffers):
//    int  s3_attach(int64_t hwnd)                          // video window for MPCVR
//    int  s3_start_device(const char* device_utf8)         // e.g. "DeckLink Quad HDMI Recorder (1)"
//    int  s3_stats(char* buf, int cap)                     // JSON (see MpcPlayer::GetUiStatusJson)
//    int  s3_cmd(const char* json_utf8)                    // {"a":"play"} {"a":"pause"} {"a":"stop"}
//                                                          // {"a":"stopgraph"} {"a":"seek","pos":N}
//    void s3_shutdown(void)                                // ordered teardown (DESIGN.md)
//    int  s3_version(char* buf, int cap)
//    int  s3_recent_log(char* buf, int cap)                // last engine log lines, newest last,
//                                                          // '\n'-separated; oldest dropped to fit
//
// Threading: any thread may call; the engine's own locks + the ops-queue
// executor own the graph. CoInitialize is attempted lazily and tolerates an
// already-initialized apartment (e.g. Qt's STA main thread).

#include <windows.h>
#include <ole2.h>
#include <dshow.h>
#include <uuids.h>
#include <atomic>
#include <vector>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <deque>
#include <mutex>
#include <string>
#include <thread>

#include "MpcPlayer.h"

// ---- offline chapter thumbnails -------------------------------------------------
// Second, temporary graph: LAV Splitter -> LAV Video -> SampleGrabber -> Null.
// It never touches the live playback graph; the UI runs this on a worker thread and
// caches the resulting 16:9 frame. HDR is whatever LAV's RGB conversion produces
// (approximate); SDR is exact.
// File mode graph is the same one MpcPlayer builds: File Source (Async) -> LAV
// Splitter -> LAV Video. (LAVSplitterSource by extension resolves to the codec-pack
// copy and its first output is already video, which cannot feed LAV Splitter.)
static const CLSID CLSID_AsyncReaderThumb = {0xE436EBB5,0x524F,0x11CE,{0x9F,0x53,0x00,0x20,0xAF,0x0B,0xA7,0x70}};
static const CLSID CLSID_LavSplitterThumb = {0x171252A0,0x8820,0x4AFE,{0x9D,0xF8,0x5C,0x92,0xB2,0xD6,0x6B,0x04}};
static const CLSID CLSID_LavVideoThumb    = {0xEE30215D,0x164F,0x4A92,{0xA4,0xEB,0x9D,0x4C,0x13,0x39,0x0F,0x9F}};
static const CLSID CLSID_SampleGrabberThumb = {0xC1F400A0,0x3F08,0x11D3,{0x9F,0x0B,0x00,0x60,0x08,0x03,0x9E,0x37}};
static const CLSID CLSID_NullRendererThumb  = {0xC1F400A4,0x3F08,0x11D3,{0x9F,0x0B,0x00,0x60,0x08,0x03,0x9E,0x37}};
static const IID   IID_ISampleGrabberThumb  = {0x6B652FFF,0x11FE,0x4FCE,{0x92,0xAD,0x02,0x66,0xB5,0xD7,0xC7,0x8F}};
struct ISampleGrabberCBX : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SampleCB(double,IMediaSample*)=0;
    virtual HRESULT STDMETHODCALLTYPE BufferCB(double,BYTE*,long)=0;
};
struct ISampleGrabberX : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SetOneShot(BOOL)=0;
    virtual HRESULT STDMETHODCALLTYPE SetMediaType(const AM_MEDIA_TYPE*)=0;
    virtual HRESULT STDMETHODCALLTYPE GetConnectedMediaType(AM_MEDIA_TYPE*)=0;
    virtual HRESULT STDMETHODCALLTYPE SetBufferSamples(BOOL)=0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentBuffer(long*,long*)=0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentSample(IMediaSample**)=0;
    virtual HRESULT STDMETHODCALLTYPE SetCallback(ISampleGrabberCBX*,long)=0;
};
static void ThumbFreeMt(AM_MEDIA_TYPE& mt){
    if(mt.cbFormat&&mt.pbFormat) CoTaskMemFree(mt.pbFormat);
    if(mt.pUnk) mt.pUnk->Release();
    ZeroMemory(&mt,sizeof(mt)); }
class ThumbGrabCB : public ISampleGrabberCBX {
public:
    std::atomic<long> samples{0};
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid,void** ppv) override {
        if(!ppv) return E_POINTER;
        if(riid==IID_IUnknown||riid==IID_ISampleGrabberThumb){ *ppv=this; AddRef(); return S_OK; }
        *ppv=nullptr; return E_NOINTERFACE; }
    ULONG STDMETHODCALLTYPE AddRef() override { return 2; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE SampleCB(double,IMediaSample*) override { samples++; return S_OK; }
    HRESULT STDMETHODCALLTYPE BufferCB(double,BYTE*,long) override { samples++; return S_OK; }
};

// MFC is statically linked into this DLL (mpchc_engine.lib is UseOfMfc Static), and the
// subtitle stack made that load-bearing: the allocator-presenter and the pass-thru
// filter construct CStrings and windows. In mpc-hc.exe a CWinApp initialises MFC; a DLL
// hosted by a non-MFC process (python, or the proof harness) gets NO initialisation
// unless it asks, and afxCurrentInstanceHandle stays null until the first CString or
// CWinThread touch reads through it — observed as 0xC0000005 inside CreateRenderer on
// the first subtitle-enabled graph build (2026-10-14).
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hInst);
        AfxWinInit(hInst, nullptr, ::GetCommandLineW(), SW_SHOWNORMAL);
    }
    return TRUE;
}

// The module's CWinApp. AfxWinInit sets the instance handle, but AfxGetApp() still
// returns null without an app object, and the subtitle decoders (CRenderedTextSubtitle
// and friends) call it — observed as 0xC0000005 inside CLAVOutputPin::Connect on the
// first subtitle pin, with the AV frames inside the decoder's construction. mpc-hc.exe
// gets this object from its own app class; a regular DLL statically linked to MFC has
// to declare one, which is exactly what the MFC DLL wizard generates.
class CS3EngineApp : public CWinApp
{
public:
    BOOL InitInstance() override { return TRUE; }
};
static CS3EngineApp theS3EngineApp;

static void EngineLog(const char* line);   // defined below; the crash hooks need it first

// ─ Crash self-diagnosis: the engine prints its own stack at the moment of death ─
//
// This process kept dying with 0xc0000409 (STATUS_STACK_BUFFER_OVERRUN), which
// is how the CRT's abort() reports itself. WER writes no dump for __fastfail,
// so the stack died with the process. These hooks catch the three ways a Release
// MSVC binary ends up in abort() — the CRT invalid-parameter handler, an
// unhandled C++ exception (set_terminate), and a raw unhandled SEH — and in each
// case log WHY it happened and print a symbolised stack to the engine log BEFORE
// terminating. The renderer's PDB sits beside its .ax, so its frames resolve;
// the engine's own frames resolve from any PDB dbghelp can find.
#include <windows.h>
#include <dbghelp.h>

static void S3LogAndStack(const char* why)
{
    EngineLog("==== CRASH SELF-DIAGNOSIS ====");
    EngineLog(why);

    HANDLE hp = GetCurrentProcess();
    SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS | SYMOPT_LOAD_LINES);
    SymInitialize(hp, nullptr, TRUE);

    void* addrs[24] = {};
    const USHORT n = CaptureStackBackTrace(1, 24, addrs, nullptr);
    for (USHORT i = 0; i < n; ++i) {
        DWORD64 a = (DWORD64)addrs[i];
        union {
            char data[sizeof(SYMBOL_INFO) + 255];
            SYMBOL_INFO sym;
        } u = {};
        u.sym.SizeOfStruct = sizeof(SYMBOL_INFO);
        u.sym.MaxNameLen = 255;
        DWORD64 disp = 0;
        char line[768];
        if (SymFromAddr(hp, a, &disp, &u.sym)) {
            IMAGEHLP_LINE64 li = { sizeof(IMAGEHLP_LINE64) };
            DWORD ld = 0;
            if (SymGetLineFromAddr64(hp, a, &ld, &li) && li.FileName)
                _snprintf_s(line, sizeof(line), _TRUNCATE,
                            "[STACK] %-32s+0x%llx  %s:%u",
                            u.sym.Name, (unsigned long long)disp,
                            li.FileName, li.LineNumber);
            else
                _snprintf_s(line, sizeof(line), _TRUNCATE,
                            "[STACK] %-32s+0x%llx",
                            u.sym.Name, (unsigned long long)disp);
        } else {
            _snprintf_s(line, sizeof(line), _TRUNCATE, "[STACK] 0x%llx",
                        (unsigned long long)a);
        }
        EngineLog(line);
    }
}

static void __cdecl S3InvalidParam(const wchar_t* expr, const wchar_t* fn,
                                   const wchar_t* file, unsigned line, uintptr_t r)
{
    S3LogAndStack("== cause: CRT invalid_parameter (the usual 0xc0000409 source) ==");
    std::abort();
}

static void __cdecl S3Terminate()
{
    S3LogAndStack("== cause: unhandled C++ exception -> set_terminate ==");
    std::abort();
}

static LONG WINAPI S3UnhandledFilter(EXCEPTION_POINTERS* ep)
{
    S3LogAndStack("== cause: unhandled SEH exception ==");
    return EXCEPTION_CONTINUE_SEARCH;
}

static void S3InstallCrashHooks()
{
    static bool done = [] {
        _set_invalid_parameter_handler(S3InvalidParam);
        std::set_terminate(S3Terminate);
        SetUnhandledExceptionFilter(S3UnhandledFilter);
        return true;
    }();
    (void)done;
}

// ---------------------------------------------------------------------------
// The single sink. EVERY line in the audit trail comes through here — engine,
// signal monitor, ingest decider, and the DeckLinkSource filter (which logs via
// MpcPlayer's bridge). Two properties this must have, both learned the hard way
// while chasing the 2026-09-21 crash:
//
//   * WALL-CLOCK TIMESTAMP on every line. The Windows crash records carry only a
//     wall-clock time, so without one here a run cannot be lined up against a
//     fault — "which line was the last one before it died" is unanswerable.
//     Elapsed-ms is added too, for ordering within a second.
//   * SERIALISED writes. The append is not atomic for a long line, and several
//     threads log concurrently, so an unsynchronised pair interleaves — observed
//     as a line whose beginning belongs to a different line ("aming=0 in=1)").
//     A log that garbles lines cannot be used as evidence.
// Keep exactly ONE previous run. An investigation needs the log of the run that
// died, and the very next launch would otherwise append straight over it — which
// is almost how the evidence for the 2026-09-21 crash was lost. Rotation runs
// once per process, before the first line, and only when the log has grown past
// a size where it is more noise than signal (the per-poll trace makes it grow
// ~1 MB/hour, so this bounds it without touching a short session).
//
// WHERE: %USERPROFILE%\.unplugged\logs\engine.log, beside the UI's unplugged.log.
// The installed app's working directory is Program Files, which a user process
// cannot write, so the old CWD-relative s3engine.log silently never existed in
// the field. Only if that per-user folder cannot be created does it fall back to
// s3engine.log in the working directory (the old behaviour).
struct EngineLogPaths { std::wstring cur, prev; };
static const EngineLogPaths& LogPaths() {
    static const EngineLogPaths p = [] {
        EngineLogPaths r{ L"s3engine.log", L"s3engine.prev.log" };
        wchar_t prof[MAX_PATH] = {};
        const DWORD n = GetEnvironmentVariableW(L"USERPROFILE", prof, MAX_PATH);
        if (n == 0 || n >= MAX_PATH) return r;
        std::wstring dir = std::wstring(prof) + L"\\.unplugged";
        CreateDirectoryW(dir.c_str(), nullptr);
        dir += L"\\logs";
        CreateDirectoryW(dir.c_str(), nullptr);
        const DWORD a = GetFileAttributesW(dir.c_str());
        if (a == INVALID_FILE_ATTRIBUTES || !(a & FILE_ATTRIBUTE_DIRECTORY)) return r;
        r.cur  = dir + L"\\engine.log";
        r.prev = dir + L"\\engine.prev.log";
        return r;
    }();
    return p;
}

static void RotateLogOnce() {
    static bool done = [] {
        const EngineLogPaths& p = LogPaths();
        WIN32_FILE_ATTRIBUTE_DATA fad{};
        if (!GetFileAttributesExW(p.cur.c_str(), GetFileExInfoStandard, &fad)) return true;
        const unsigned long long sz =
            ((unsigned long long)fad.nFileSizeHigh << 32) | fad.nFileSizeLow;
        if (sz < 8ull * 1024ull * 1024ull) return true;
        DeleteFileW(p.prev.c_str());
        MoveFileW(p.cur.c_str(), p.prev.c_str());
        return true;
    }();
    (void)done;
}

// The last lines the engine logged, kept in memory as well, so the error report
// the user copies carries them even if the log file could not be written.
// The UI pulls these through s3_recent_log().
static std::mutex s_recentMtx;
static std::deque<std::string> s_recent;
static constexpr size_t kRecentLines = 800;

static void EngineLog(const char* line) {
    static std::mutex s_logMtx;
    static const unsigned long long s_t0 = GetTickCount64();
    RotateLogOnce();

    SYSTEMTIME st{};
    GetLocalTime(&st);
    const unsigned long long elapsed = GetTickCount64() - s_t0;

    char stamped[1024];
    _snprintf_s(stamped, sizeof(stamped), _TRUNCATE,
                "%02u:%02u:%02u.%03u +%7llu  %s",
                st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, elapsed, line);

    {
        std::lock_guard<std::mutex> lk(s_logMtx);
        static bool s_first = true;
        if (FILE* f = _wfopen(LogPaths().cur.c_str(), L"a")) {
            if (s_first) {
                // Runs are appended to one file; mark where this one starts.
                fprintf(f, "\n==== s3engine session %04u-%02u-%02u %02u:%02u:%02u pid=%lu ====\n",
                        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
                        GetCurrentProcessId());
                s_first = false;
            }
            fputs(stamped, f); fputc('\n', f); fclose(f);
        }
    }
    {
        std::lock_guard<std::mutex> lk(s_recentMtx);
        s_recent.emplace_back(stamped);
        while (s_recent.size() > kRecentLines) s_recent.pop_front();
    }
    OutputDebugStringA(stamped);
    OutputDebugStringA("\n");
}
static MpcPlayer* g_player() {
    static MpcPlayer s_player;       // lazily constructed on first use
    static bool s_logged = [] {
        S3InstallCrashHooks();       // a fatal abort now prints its own stack first
        s_player.SetLogSink(EngineLog);
        return true;
    }();
    (void)s_logged;
    return &s_player;
}
static void EnsureCom() {
    static bool s_done = false;
    if (s_done) return;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (hr != RPC_E_CHANGED_MODE && FAILED(hr)) {
        // Already-initialized or failed — the caller's apartment already lives;
        // DirectShow graphs still build on STA. Nothing to do.
    }
    s_done = true;
}

static int ToWide(const char* utf8, wchar_t* w, int cap) {
    if (!utf8) return 0;
    const int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, w, cap);
    if (n <= 0 && cap > 0) w[0] = 0;
    return n;
}

// Reads a flat JSON field by name (string value, or bare number). Our own UI
// generates every payload, so a full parser isn't warranted — but dispatching
// on the "a" field is, because a settings value can legitimately contain words
// like "play" or "seek" and used to mis-dispatch the whole command.
// Declared outside the extern "C" block below: it returns a C++ type.
static std::string JsonField(const std::string& s, const char* key)
{
    const std::string k = std::string("\"") + key + "\"";
    size_t p = s.find(k);
    if (p == std::string::npos) return std::string();
    p += k.size();
    while (p < s.size() && (s[p] == ' ' || s[p] == '\t' || s[p] == ':')) ++p;
    std::string out;
    if (p < s.size() && s[p] == '"') {
        for (++p; p < s.size() && s[p] != '"'; ++p) {
            if (s[p] == '\\' && p + 1 < s.size()) ++p;
            out += s[p];
        }
        return out;
    }
    while (p < s.size() && ((s[p] >= '0' && s[p] <= '9') || s[p] == '-' || s[p] == '.'))
        out += s[p++];
    return out;
}

// ---------------------------------------------------------------------------
extern "C" {

__declspec(dllexport) int s3_attach(int64_t hwnd)
{
    EnsureCom();
    if (!hwnd) return -1;
    g_player()->AttachRenderTarget(reinterpret_cast<HWND>((INT_PTR)hwnd));
    g_player()->SetRenderer(MpcPlayer::Renderer::MPCVR);
    return 0;
}

__declspec(dllexport) int s3_start_device(const char* deviceUtf8)
{
    EnsureCom();
    wchar_t d[128] = {};
    ToWide(deviceUtf8 ? deviceUtf8 : "", d, 128);
    const HRESULT hr = g_player()->SetDecklinkCapture(d);
    return (int)hr;
}

// ---- chapter thumbnail extraction ----------------------------------------------
static std::wstring ThumbWide(const char* s){
    if(!s||!*s) return std::wstring();
    int n=MultiByteToWideChar(CP_UTF8,0,s,-1,nullptr,0);
    if(n<=1) return std::wstring();
    std::vector<wchar_t> b((size_t)n);
    MultiByteToWideChar(CP_UTF8,0,s,-1,b.data(),n);
    return std::wstring(b.data(),(size_t)n-1);
}
static bool PinOffers(IPin* p,const GUID& major){
    IEnumMediaTypes* e=nullptr; if(!p||FAILED(p->EnumMediaTypes(&e))||!e) return false;
    AM_MEDIA_TYPE* mt=nullptr; bool ok=false;
    while(e->Next(1,&mt,nullptr)==S_OK){
        if(mt->majortype==major) ok=true;
        ThumbFreeMt(*mt); CoTaskMemFree(mt); mt=nullptr;
        if(ok) break; }
    e->Release(); return ok;
}
static IPin* ThumbPin(IBaseFilter* f,PIN_DIRECTION dir,bool videoOnly){
    IEnumPins* e=nullptr; if(!f||FAILED(f->EnumPins(&e))||!e) return nullptr;
    IPin* p=nullptr; IPin* found=nullptr;
    while(e->Next(1,&p,nullptr)==S_OK){
        PIN_DIRECTION d;
        if(SUCCEEDED(p->QueryDirection(&d))&&d==dir&&(!videoOnly||PinOffers(p,MEDIATYPE_Video))){ found=p; break; }
        p->Release(); }
    e->Release(); return found;
}
static bool WriteBmpThumb(const std::wstring& path,const BYTE* data,long size,const BITMAPINFOHEADER& bih){
    if(!data||size<=0) return false;
    BITMAPFILEHEADER fh={};
    fh.bfType=0x4D42; fh.bfOffBits=sizeof(fh)+sizeof(BITMAPINFOHEADER); fh.bfSize=fh.bfOffBits+(DWORD)size;
    BITMAPINFOHEADER ih=bih;
    ih.biSize=sizeof(BITMAPINFOHEADER); ih.biCompression=BI_RGB; ih.biSizeImage=(DWORD)size;
    FILE* f=_wfopen(path.c_str(),L"wb"); if(!f) return false;
    bool ok=fwrite(&fh,1,sizeof(fh),f)==sizeof(fh)&&fwrite(&ih,1,sizeof(ih),f)==sizeof(ih)&&
            fwrite(data,1,(size_t)size,f)==(size_t)size;
    fclose(f); return ok;
}
// Builds a throwaway graph and writes one BMP at `seconds`. Returns S_OK/HRESULT.
extern "C" __declspec(dllexport) int s3_chapter_thumb(const char* fileUtf8,double seconds,
                                                      const char* outBmpUtf8)
{
    std::wstring file=ThumbWide(fileUtf8), out=ThumbWide(outBmpUtf8);
    if(file.empty()||out.empty()) return E_INVALIDARG;
    HRESULT co=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    bool uninit=SUCCEEDED(co);
    HRESULT hr=S_OK; const char* stage="init";
    IGraphBuilder* graph=nullptr; IBaseFilter* srcF=nullptr; IBaseFilter* split=nullptr;
    IBaseFilter* dec=nullptr; IBaseFilter* grabF=nullptr; IBaseFilter* nullF=nullptr;
    IFileSourceFilter* src=nullptr; ISampleGrabberX* grab=nullptr;
    IMediaControl* ctl=nullptr; IMediaSeeking* seek=nullptr;
    IPin* srco=nullptr; IPin* si=nullptr;
    IPin* so=nullptr; IPin* di=nullptr; IPin* dout=nullptr; IPin* gi=nullptr;
    IPin* go=nullptr; IPin* ni=nullptr;
    ThumbGrabCB cb;
    do {
        stage="create graph";
        hr=CoCreateInstance(CLSID_FilterGraph,nullptr,CLSCTX_INPROC_SERVER,IID_IGraphBuilder,(void**)&graph);
        if(FAILED(hr)) break;
        stage="create file source";
        hr=CoCreateInstance(CLSID_AsyncReaderThumb,nullptr,CLSCTX_INPROC_SERVER,IID_IBaseFilter,(void**)&srcF);
        if(FAILED(hr)) break;
        stage="create splitter";
        hr=CoCreateInstance(CLSID_LavSplitterThumb,nullptr,CLSCTX_INPROC_SERVER,IID_IBaseFilter,(void**)&split);
        if(FAILED(hr)) break;
        stage="create decoder";
        hr=CoCreateInstance(CLSID_LavVideoThumb,nullptr,CLSCTX_INPROC_SERVER,IID_IBaseFilter,(void**)&dec);
        if(FAILED(hr)) break;
        stage="create grabber";
        hr=CoCreateInstance(CLSID_SampleGrabberThumb,nullptr,CLSCTX_INPROC_SERVER,IID_IBaseFilter,(void**)&grabF);
        if(FAILED(hr)) break;
        stage="create null";
        hr=CoCreateInstance(CLSID_NullRendererThumb,nullptr,CLSCTX_INPROC_SERVER,IID_IBaseFilter,(void**)&nullF);
        if(FAILED(hr)) break;
        graph->AddFilter(srcF,L"File Source (Async)");
        graph->AddFilter(split,L"LAV Splitter");
        graph->AddFilter(dec,L"LAV Video Decoder");
        graph->AddFilter(grabF,L"SampleGrabber");
        graph->AddFilter(nullF,L"Null Renderer");
        stage="file source QI";
        if(FAILED(srcF->QueryInterface(IID_IFileSourceFilter,(void**)&src))||!src){ hr=E_NOINTERFACE; break; }
        stage="load";
        hr=src->Load(file.c_str(),nullptr);
        if(FAILED(hr)) break;
        stage="connect source-splitter";
        srco=ThumbPin(srcF,PINDIR_OUTPUT,false);
        si=ThumbPin(split,PINDIR_INPUT,false);
        if(!srco||!si){ hr=VFW_E_NOT_FOUND; break; }
        hr=graph->ConnectDirect(srco,si,nullptr);
        if(FAILED(hr)) break;
        stage="grabber QI";
        if(FAILED(grabF->QueryInterface(IID_ISampleGrabberThumb,(void**)&grab))||!grab){ hr=E_NOINTERFACE; break; }
        AM_MEDIA_TYPE mt={};
        mt.majortype=MEDIATYPE_Video; mt.subtype=MEDIASUBTYPE_RGB32; mt.formattype=FORMAT_VideoInfo;
        mt.cbFormat=sizeof(VIDEOINFOHEADER); mt.pbFormat=(BYTE*)CoTaskMemAlloc(mt.cbFormat);
        if(!mt.pbFormat){ hr=E_OUTOFMEMORY; break; }
        ZeroMemory(mt.pbFormat,mt.cbFormat);
        VIDEOINFOHEADER* vih=(VIDEOINFOHEADER*)mt.pbFormat;
        vih->bmiHeader.biSize=sizeof(BITMAPINFOHEADER); vih->bmiHeader.biWidth=0;
        vih->bmiHeader.biHeight=0; vih->bmiHeader.biPlanes=1; vih->bmiHeader.biBitCount=32;
        stage="set grabber type";
        hr=grab->SetMediaType(&mt);
        ThumbFreeMt(mt);
        if(FAILED(hr)) break;
        grab->SetCallback(&cb,0);
        grab->SetBufferSamples(TRUE); grab->SetOneShot(FALSE);
        stage="connect split-dec";
        so=ThumbPin(split,PINDIR_OUTPUT,true);
        di=ThumbPin(dec,PINDIR_INPUT,true);
        if(!so||!di){ hr=VFW_E_NOT_FOUND; break; }
        hr=graph->ConnectDirect(so,di,nullptr);
        if(FAILED(hr)) break;
        stage="connect dec-grab";
        dout=ThumbPin(dec,PINDIR_OUTPUT,true);
        gi=ThumbPin(grabF,PINDIR_INPUT,true);
        if(!dout||!gi){ hr=VFW_E_NOT_FOUND; break; }
        hr=graph->ConnectDirect(dout,gi,nullptr);
        if(FAILED(hr)) break;
        stage="connect grab-null";
        go=ThumbPin(grabF,PINDIR_OUTPUT,false);
        ni=ThumbPin(nullF,PINDIR_INPUT,false);
        if(!go||!ni){ hr=VFW_E_NOT_FOUND; break; }
        hr=graph->ConnectDirect(go,ni,nullptr);
        if(FAILED(hr)) break;
        stage="seek";
        graph->QueryInterface(IID_IMediaSeeking,(void**)&seek);
        if(seek){
            LONGLONG t=(LONGLONG)((seconds>0.0?seconds:0.0)*10000000.0);
            seek->SetPositions(&t,AM_SEEKING_AbsolutePositioning,nullptr,AM_SEEKING_NoPositioning);
        }
        stage="pause";
        graph->QueryInterface(IID_IMediaControl,(void**)&ctl);
        if(!ctl){ hr=E_NOINTERFACE; break; }
        hr=ctl->Pause();
        if(FAILED(hr)) break;
        stage="run";
        hr=ctl->Run();
        if(FAILED(hr)) break;
        stage="wait sample";
        for(int i=0;i<240&&cb.samples.load()==0;++i) Sleep(50);
        if(cb.samples.load()==0){ hr=HRESULT_FROM_WIN32(ERROR_TIMEOUT); break; }
        stage="buffer";
        AM_MEDIA_TYPE cmt={};
        hr=grab->GetConnectedMediaType(&cmt);
        if(FAILED(hr)) break;
        VIDEOINFOHEADER* v=cmt.pbFormat?((VIDEOINFOHEADER*)cmt.pbFormat):nullptr;
        long size=0; grab->GetCurrentBuffer(&size,nullptr);
        if(size<=0||!v){ ThumbFreeMt(cmt); hr=E_FAIL; break; }
        std::vector<BYTE> buf((size_t)size);
        long got=size;
        hr=grab->GetCurrentBuffer(&got,(long*)buf.data());
        if(SUCCEEDED(hr)&&got>0){
            BITMAPINFOHEADER bih=v->bmiHeader;
            if(bih.biHeight==0&&vih) bih.biHeight=vih->bmiHeader.biHeight;
            if(!WriteBmpThumb(out,buf.data(),got,bih)) hr=E_FAIL;
        } else hr=E_FAIL;
        ThumbFreeMt(cmt);
    } while(false);
    if(ctl) ctl->Stop();
    if(srco)srco->Release(); if(si)si->Release();
    if(so)so->Release(); if(di)di->Release(); if(dout)dout->Release(); if(gi)gi->Release();
    if(go)go->Release(); if(ni)ni->Release();
    if(seek)seek->Release(); if(ctl)ctl->Release(); if(src)src->Release(); if(grab)grab->Release();
    if(srcF)srcF->Release(); if(split)split->Release(); if(dec)dec->Release();
    if(grabF)grabF->Release(); if(nullF)nullF->Release();
    if(graph)graph->Release();
    if(uninit) CoUninitialize();
    { char msg[512];
      _snprintf_s(msg,sizeof(msg),_TRUNCATE,"[THUMB] '%s' t=%.1f hr=0x%08X stage=%s",
                  fileUtf8,seconds,(unsigned)hr,stage);
      EngineLog(msg); }
    return (int)hr;
}

__declspec(dllexport) int s3_stats(char* buf, int cap)
{
    if (!buf || cap <= 0) return -1;
    // NOTE: this used to call g_player()->PumpEvents() so that end-of-title would be
    // noticed. It must NOT: s3_stats runs on the UI thread, PumpEvents takes the graph
    // mutex, and the engine's refresh thread takes that same mutex and then sends
    // window messages TO the UI thread. A UI thread blocked on the mutex plus a
    // refresh thread blocked on the UI thread is a deadlock -- observed as a black
    // frame and a frozen app the moment a file played. The pump now lives on the
    // refresh thread (MpcPlayer's live-tick loop).
    //
    // What the UI thread DOES own is the renderer's window, so the detach that the
    // refresh thread requests at end-of-title is cashed in here, on the poll.
    g_player()->ApplyPendingWindowDetach();
    // Same rule for NLS: the live thread watches the renderer's detected black
    // band and asks for a re-injection when it moves; the shader list is mutated
    // here, on the thread that already pushes settings.
    g_player()->ApplyPendingNlsRefresh();
    const std::string j = g_player()->GetUiStatusJson();
    const size_t n = j.size();
    if (n + 1 > (size_t)cap) {
        memcpy_s(buf, (size_t)cap, j.data(), (size_t)cap - 1);
        buf[cap - 1] = 0;
        return (int)(cap - 1);
    }
    memcpy(buf, j.data(), n);
    buf[n] = 0;
    return (int)n;
}

__declspec(dllexport) int s3_recent_log(char* buf, int cap)
{
    if (!buf || cap <= 0) return -1;
    std::deque<std::string> lines;
    {
        std::lock_guard<std::mutex> lk(s_recentMtx);
        lines = s_recent;
    }
    // Keep the newest lines that fit: walk back from the end, then emit in order.
    size_t budget = (size_t)cap - 1;
    size_t first = lines.size();
    while (first > 0 && lines[first - 1].size() + 1 <= budget) {
        budget -= lines[first - 1].size() + 1;
        --first;
    }
    size_t n = 0;
    for (size_t i = first; i < lines.size(); ++i) {
        memcpy(buf + n, lines[i].data(), lines[i].size());
        n += lines[i].size();
        buf[n++] = '\n';
    }
    buf[n] = 0;
    return (int)n;
}

__declspec(dllexport) int s3_cmd(const char* jsonUtf8)
{
    EnsureCom();
    if (!jsonUtf8) return -1;
    const std::string s(jsonUtf8);
    const std::string a = JsonField(s, "a");

    if (a == "play")  return (int)g_player()->Play();
    if (a == "pause") return (int)g_player()->Pause();
    // Live capture has nothing to stop — the engine owns start/stop and the
    // self-healing monitor drives transitions, so "stop" stays a benign pause.
    if (a == "stop")  return (int)g_player()->Pause();
    // File playback's real Stop: mediaControl_->Stop() plus DetachRendererWindow()
    // so the last frame stops covering the host/wallpaper when the library opens.
    // Kept separate from "stop" so live capture keeps its benign-pause contract.
    if (a == "stopgraph") return (int)g_player()->Stop();
    if (a == "open") {
        // Media Player mode — a real FILE, not a DeckLink device. This was the
        // route previously taken: the UI called s3_start_device with the file path
        // as if it were a capture device, no lock ever arrived, no fact fired, and
        // the graph never launched — state sat at "opening" forever.
        // {"a":"open","url":"C:\\Movies\\x.mkv"}
        const std::string url = JsonField(s, "url");
        std::wstring wurl;
        if (!url.empty()) {
            const int n = MultiByteToWideChar(CP_UTF8, 0, url.c_str(),
                                              (int)url.size(), nullptr, 0);
            wurl.resize((size_t)(n > 0 ? n : 0));
            if (n > 0) MultiByteToWideChar(CP_UTF8, 0, url.c_str(),
                                           (int)url.size(), &wurl[0], n);
        }
        const HRESULT hr = g_player()->Open(wurl);
        if (SUCCEEDED(hr)) g_player()->Play();
        char why[512];
        _snprintf_s(why, sizeof(why), _TRUNCATE, "[S3] open url='%S' hr=0x%08X",
                    wurl.c_str(), (unsigned)hr);
        EngineLog(why);
        return (int)hr;
    }
    if (a == "seek") {
        const std::string pos = JsonField(s, "pos");
        long long n = 0;
        for (size_t i = 0; i < pos.size(); ++i)
            if (pos[i] >= '0' && pos[i] <= '9') n = n * 10 + (pos[i] - '0');
        return (int)g_player()->Seek(n);   // pos in 100 ns units (JS seconds * 1e7)
    }
    if (a == "set") {
        // P2 settings: {"a":"set","sets":"hdr.sdrNits=204;ml.gamma=1.1;..."}
        const std::string body = JsonField(s, "sets");
        std::vector<std::string> sets;
        size_t start = 0;
        for (size_t i = 0; i <= body.size(); ++i) {
            if (i == body.size() || body[i] == ';') {
                if (i > start) sets.push_back(body.substr(start, i - start));
                start = i + 1;
            }
        }
        return (int)g_player()->ApplySettingsFlat(sets);
    }
    if (a == "videorect") {
        // {"a":"videorect","x":..,"y":..,"w":..,"h":..} — the picture canvas inside
        // the shell's client while chrome occupies the rest. w or h <= 0 clears it.
        // The renderer's WINDOW is never resized for this: only the destination rect
        // moves, which is safe during a live capture.
        return (int)g_player()->SetVideoRect(atoi(JsonField(s, "x").c_str()),
                                             atoi(JsonField(s, "y").c_str()),
                                             atoi(JsonField(s, "w").c_str()),
                                             atoi(JsonField(s, "h").c_str()));
    }
    if (a == "resize") {
        // {"a":"resize"} — re-place the renderer's window into the current
        // client rect of the attach target. The Qt shell resizes the viewport
        // widget when the rails go up/down (video-yields-space); a native
        // child window does NOT follow its parent's size on its own, so the
        // shell must ask, exactly like s3_shell.cpp does on WM_SIZE.
        return (int)g_player()->ResizeVideo();
    }
    if (a == "step") {
        // {"a":"step","dir":1|-1} — one frame duration, paused first.
        return (int)g_player()->StepFrame(atoi(JsonField(s, "dir").c_str()));
    }
    if (a == "chapter") {
        // {"a":"chapter","dir":1|-1} — next/prev splitter chapter mark.
        return (int)g_player()->SeekChapter(atoi(JsonField(s, "dir").c_str()));
    }
    if (a == "track") {
        // {"a":"track","index":N} — select the Nth AUDIO stream (audio-relative
        // index, same as the status JSON's audio.tracks[].i). Live via IAMStreamSelect.
        const std::string idx = JsonField(s, "index");
        return (int)g_player()->SetAudioTrack(idx.empty() ? -1 : atoi(idx.c_str()));
    }
    if (a == "volume") {
        // {"a":"volume","percent":N} — 0..100, clamped again in MpcPlayer::SetVolume.
        // Applied through IBasicAudio on the graph, so it is real in PCM mode; in
        // bitstream mode the receiver decodes and owns the level, and the UI says so
        // instead of pretending the slider works.
        const std::string p = JsonField(s, "percent");
        return (int)g_player()->SetVolume(p.empty() ? 100 : atoi(p.c_str()));
    }
    if (a == "mute") {
        // {"a":"mute","on":0|1}
        const std::string on = JsonField(s, "on");
        return (int)g_player()->SetMuted(on.empty() ? 0 : atoi(on.c_str()) != 0);
    }
    if (a == "subvisible") {
        // {"a":"subvisible","on":0|1} — show/hide the current subtitle without changing
        // which stream is selected, i.e. MPC-HC's "Subtitles" toggle rather than its
        // track menu. The engine keeps the flag, so a track change honours it too.
        const std::string on = JsonField(s, "on");
        return (int)g_player()->SetSubtitlesEnabled(on.empty() ? 1 : atoi(on.c_str()) != 0);
    }
    if (a == "subtrack") {
        // {"a":"subtrack","index":N} — select the Nth subtitle stream, or -1 to clear.
        // Same shape as "track": the engine enables it on the splitter AND hands the
        // matching ISubPicProvider to the presenter, so the change is visible on the
        // next presented frame without a graph rebuild.
        const std::string idx = JsonField(s, "index");
        return (int)g_player()->SetSubtitleTrack(idx.empty() ? -1 : atoi(idx.c_str()));
    }
    // Audio mode (PCM↔Bitstream) rides the "set" path as audio.mode — no action here.
    // Persist the renderer's live settings to MPCVR's own registry key. SetSettings
    // is live-only, so without this a graph rebuild re-reads a stale key and every
    // pushed setting is silently lost. The UI sends this once a change settles.
    if (a == "save") return (int)g_player()->SaveRendererSettings();
    // {"a":"resetrenderer"} — delete the renderer's persisted Settings_t (current key and
    // the legacy key it migrates from) so the next graph starts from compiled defaults.
    if (a == "resetrenderer") return (int)g_player()->ResetRendererSettings();
    if (a == "lut") {
        // {"a":"lut","file":"C:\\...\\display.cube","mode":2}
        //   empty file unloads; mode 0=off 1=gamma 2=greyscale 3=full (default)
        const std::string m = JsonField(s, "mode");
        return (int)g_player()->LoadCubeLut(JsonField(s, "file"),
                                            m.empty() ? 3 : atoi(m.c_str()));
    }
    // {"a":"grab","file":"C:\\...\\frame.bmp"}
    // Write the frame the renderer is producing right now. The point is A/B
    // evidence: apply a setting, grab, apply another, grab, and compare the two
    // files — "the picture did not change" stops being a judgement call.
    if (a == "grab") return (int)g_player()->GrabFrame(JsonField(s, "file"));
    // {"a":"rendererdump","file":"C:\\...\\renderer.txt"}
    // The renderer's own live state (IVideoRenderer::GetMLStats) as text. This is
    // how a machine checks a claim like "the mapper is running": the settings echo
    // proves the value was stored, and only the renderer can say what it did with
    // it. The MPCVR-side DLog is a no-op in Release builds, so this is the only
    // channel that carries it.
    if (a == "rendererdump") {
        const std::string path = JsonField(s, "file");
        if (path.empty()) return 0;
        std::wstring text;
        if (FAILED(g_player()->GetMlStats(text)) || text.empty()) return -1;
        // GetMLStats emits UTF-16; narrow it so the dump is readable by anything.
        const int need = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                             nullptr, 0, nullptr, nullptr);
        std::string utf8((size_t)(need > 0 ? need : 0), '\0');
        if (need > 0) {
            WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                utf8.data(), need, nullptr, nullptr);
        }
        FILE* f = nullptr;
        if (fopen_s(&f, path.c_str(), "wb") != 0 || !f) return -1;
        fwrite(utf8.data(), 1, utf8.size(), f);
        fclose(f);
        return 0;
    }
    return 0;
}

__declspec(dllexport) void s3_shutdown(void)
{
    // Bounded teardown: never block the caller forever. The engine's teardown
    // can wait on the graph lock (a rebuild mid-flight on the ops-queue
    // executor); running it on a detached worker and waiting at most 10 s
    // means the UI thread can never freeze on shutdown (the adopt-or-abandon
    // rule). Idempotent: a second call returns immediately.
    static std::atomic<bool> s_shutting(false);
    if (s_shutting.exchange(true)) return;
    HANDLE done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    std::thread t([done] {
        g_player()->Shutdown();
        if (done) SetEvent(done);
    });
    t.detach();
    if (done) {
        // Keep delivering messages SENT to this thread while we wait. A filter's
        // destructor on the worker may SendMessage() a window this thread owns (MPCVR
        // sends WM_CLOSE to its video window); a plain wait deadlocks that until the
        // timeout. QS_SENDMESSAGE + PM_QS_SENDMESSAGE dispatches only inbound sent
        // messages — posted input/paint/timer messages stay queued, so no UI re-entry.
        const ULONGLONG deadline = GetTickCount64() + 10000;
        for (;;) {
            const ULONGLONG now = GetTickCount64();
            if (now >= deadline) break;
            const DWORD r = MsgWaitForMultipleObjects(1, &done, FALSE,
                                                      (DWORD)(deadline - now), QS_SENDMESSAGE);
            if (r != WAIT_OBJECT_0 + 1) break;   // signalled, timed out, or failed
            MSG msg;
            PeekMessageW(&msg, nullptr, 0, 0, PM_NOREMOVE | PM_QS_SENDMESSAGE);
        }
        CloseHandle(done);
    }
}

__declspec(dllexport) int s3_version(char* buf, int cap)
{
    static const char V[] = "s3engine 0.1 (mpchc_engine)";
    const size_t n = strlen(V);
    if (cap <= 0) return (int)n;
    const size_t c = (n + 1 < (size_t)cap) ? n + 1 : (size_t)cap;
    memcpy(buf, V, c - 1);
    buf[c - 1] = 0;
    return (int)(c - 1);
}

} // extern "C"
// s3engine.dll — C-ABI host over mpchc_engine (MpcPlayer) for the PyQt client
// UI (C:\code\unplugged\app). The professional UI stays as-is; everything the
// UI needs crosses this ABI: attach the video window, start the self-healing
// DeckLink capture, poll a JSON status blob, send transport commands.
//
//  ABI (UTF-8 strings, caller-owned buffers):
//    int  s3_attach(int64_t hwnd)                          // video window for MPCVR
//    int  s3_start_device(const char* device_utf8)         // e.g. "DeckLink Quad HDMI Recorder (1)"
//    int  s3_stats(char* buf, int cap)                     // JSON (see MpcPlayer::GetUiStatusJson)
//    int  s3_cmd(const char* json_utf8)                    // {"a":"play"} {"a":"pause"} {"a":"stop"} {"a":"seek","pos":N}
//    void s3_shutdown(void)                                // ordered teardown (DESIGN.md)
//    int  s3_version(char* buf, int cap)
//
// Threading: any thread may call; the engine's own locks + the ops-queue
// executor own the graph. CoInitialize is attempted lazily and tolerates an
// already-initialized apartment (e.g. Qt's STA main thread).

#include <windows.h>
#include <ole2.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>

#include "MpcPlayer.h"

static void EngineLog(const char* line);   // defined below; the crash hooks need it first

// ─ Crash self-diagnosis: the engine prints its own stack at the moment of death ─
//
// This process kept dying with 0xc0000409 (STATUS_STACK_BUFFER_OVERRUN), which
// is how the CRT's abort() reports itself. WER writes no dump for __fastfail,
// so the stack died with the process. These hooks catch the three ways a Release
// MSVC binary ends up in abort() — the CRT invalid-parameter handler, an
// unhandled C++ exception (set_terminate), and a raw unhandled SEH — and in each
// case log WHY it happened and print a symbolised stack to s3engine.log BEFORE
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
static void RotateLogOnce() {
    static bool done = [] {
        WIN32_FILE_ATTRIBUTE_DATA fad{};
        if (!GetFileAttributesExW(L"s3engine.log", GetFileExInfoStandard, &fad)) return true;
        const unsigned long long sz =
            ((unsigned long long)fad.nFileSizeHigh << 32) | fad.nFileSizeLow;
        if (sz < 8ull * 1024ull * 1024ull) return true;
        DeleteFileW(L"s3engine.prev.log");
        MoveFileW(L"s3engine.log", L"s3engine.prev.log");
        return true;
    }();
    (void)done;
}

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
        if (FILE* f = _wfopen(L"s3engine.log", L"a")) {
            fputs(stamped, f); fputc('\n', f); fclose(f);
        }
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

__declspec(dllexport) int s3_stats(char* buf, int cap)
{
    if (!buf || cap <= 0) return -1;
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
    // Persist the renderer's live settings to MPCVR's own registry key. SetSettings
    // is live-only, so without this a graph rebuild re-reads a stale key and every
    // pushed setting is silently lost. The UI sends this once a change settles.
    if (a == "save") return (int)g_player()->SaveRendererSettings();
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
    if (done) WaitForSingleObject(done, 10000);
    if (done) CloseHandle(done);
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
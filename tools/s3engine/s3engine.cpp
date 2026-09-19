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
#include <cstring>
#include <thread>

#include "MpcPlayer.h"

// ---------------------------------------------------------------------------
static void EngineLog(const char* line) {
    if (FILE* f = _wfopen(L"s3engine.log", L"a")) { fputs(line, f); fputc('\n', f); fclose(f); }
    OutputDebugStringA(line);
    OutputDebugStringA("\n");
}
static MpcPlayer* g_player() {
    static MpcPlayer s_player;       // lazily constructed on first use
    static bool s_logged = [] { s_player.SetLogSink(EngineLog); return true; }();
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
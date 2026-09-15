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

#include <cstring>

#include "MpcPlayer.h"

// ---------------------------------------------------------------------------
static MpcPlayer* g_player() {
    static MpcPlayer s_player;       // lazily constructed on first use
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
    if (s.find("\"play\"") != std::string::npos)  return (int)g_player()->Play();
    if (s.find("\"pause\"") != std::string::npos) return (int)g_player()->Pause();
    if (s.find("\"stop\"") != std::string::npos)  return (int)g_player()->Pause();
    if (s.find("\"seek\"") != std::string::npos) {
        const size_t p = s.find("\"pos\"");
        if (p != std::string::npos) {
            long long pos = 0;
            for (size_t i = p + 6; i < s.size() && s[i] >= '0' && s[i] <= '9'; ++i)
                pos = pos * 10 + (s[i] - '0');
            return (int)g_player()->Seek(pos);   // pos in 100 ns units (JS seconds * 1e7)
        }
    }
    return 0;
}

__declspec(dllexport) void s3_shutdown(void)
{
    g_player()->Shutdown();
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
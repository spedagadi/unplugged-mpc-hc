// eof_proof.cpp -- executable proof for the end-of-file path, against the EXACT
// s3engine.dll the packaged app loads.
//
// It mirrors the app's threading model on purpose: ONE thread runs a Windows
// message loop AND polls s3_stats on a timer, because the renderer drains its
// messages into that window. Starving the loop is the deadlock this test exists
// to rule out; a separate watchdog thread fails the run if the poll ever goes
// silent, which is what a frozen UI thread looks like from outside.
//
// Pass criteria, printed as a timeline:
//   1. s3_cmd open returns and the poll keeps answering      (no hang/crash on open)
//   2. state reaches "playing"                               (playback actually runs)
//   3. state leaves "playing" afterwards                     (EOF is DETECTED)
//   4. three further polls answer after that                 (no post-EOF deadlock)
//   5. s3_shutdown returns                                   (clean teardown)
// Any failure exits non-zero with the last observed state and the stall point.

#include <windows.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <atomic>

typedef int (*fn_attach)(long long);
typedef int (*fn_cmd)(const char*);
typedef int (*fn_stats)(char*, int);
typedef int (*fn_shutdown)();

static fn_attach  p_attach;
static fn_cmd     p_cmd;
static fn_stats   p_stats;
static fn_shutdown p_shutdown;

static HWND g_hwnd = 0;
static std::atomic<long long> g_polls{0};
static std::atomic<long long> g_lastPollMs{0};
static std::atomic<int> g_done{0};
static std::string g_lastState;
static bool g_sawPlaying = false;
static bool g_sawEndAfterPlaying = false;
static int  g_postEndPolls = 0;
static DWORD g_t0 = 0;

static std::string StateOf(const char* j) {
    const char* k = strstr(j, "\"state\":\"");
    if (!k) return "?";
    k += 9;
    const char* e = strchr(k, '"');
    if (!e) return "?";
    return std::string(k, e - k);
}

static void Note(const char* what) {
    printf("[%7u ms] %s\n", GetTickCount() - g_t0, what);
    fflush(stdout);
}

static void PollOnce() {
    char buf[8192];
    int n = p_stats(buf, sizeof(buf));
    g_polls++;
    g_lastPollMs = GetTickCount();
    if (n <= 0) { Note("poll returned <=0"); return; }
    buf[n] = 0;
    std::string st = StateOf(buf);
    if (st != g_lastState) {
        printf("[%7u ms] state: %s -> %s\n", GetTickCount() - g_t0,
               g_lastState.empty() ? "(none)" : g_lastState.c_str(), st.c_str());
        fflush(stdout);
        g_lastState = st;
    }
    if (st == "playing") g_sawPlaying = true;
    else if (g_sawPlaying && (st == "idle" || st == "stopped" || st == "ended")) {
        if (!g_sawEndAfterPlaying) {
            g_sawEndAfterPlaying = true;
            Note("EOF DETECTED: state left 'playing'");
        }
        g_postEndPolls++;
        if (g_postEndPolls >= 3 && !g_done) {
            g_done = 1;
            Note("post-EOF polls answered; shutting down");
            int rc = p_shutdown();
            printf("[%7u ms] s3_shutdown rc=%d\n", GetTickCount() - g_t0, rc);
            PostQuitMessage(0);
        }
    }
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_TIMER) { PollOnce(); return 0; }
    return DefWindowProc(h, m, w, l);
}

int main(int argc, char** argv) {
    const char* dll = "C:\\code\\unplugged-mpc-hc\\src\\unplugged-ui\\dist\\Unplugged\\_internal\\s3engine.dll";
    const char* file = (argc > 1) ? argv[1]
        : "C:\\Users\\satee\\Pictures\\calibrate\\calibrate.mkv";

    g_t0 = GetTickCount();
    HMODULE hm = LoadLibraryA(dll);
    if (!hm) { printf("FAIL: cannot load %s (err %lu)\n", dll, GetLastError()); return 2; }
    p_attach   = (fn_attach)GetProcAddress(hm, "s3_attach");
    p_cmd      = (fn_cmd)GetProcAddress(hm, "s3_cmd");
    p_stats    = (fn_stats)GetProcAddress(hm, "s3_stats");
    p_shutdown = (fn_shutdown)GetProcAddress(hm, "s3_shutdown");
    if (!p_attach || !p_cmd || !p_stats || !p_shutdown) { printf("FAIL: missing exports\n"); return 2; }
    Note("loaded the staged s3engine.dll");

    WNDCLASSA wc = {};
    wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandle(0); wc.lpszClassName = "eofproof";
    RegisterClassA(&wc);
    g_hwnd = CreateWindowExA(0, "eofproof", "eofproof", WS_OVERLAPPEDWINDOW, 0, 0, 640, 360, 0, 0, wc.hInstance, 0);
    if (!g_hwnd) { printf("FAIL: no window\n"); return 2; }
    // Deliberately NOT ShowWindow: proves nothing needs a visible surface.

    // Watchdog: the poll timer runs on this thread's message loop. If the loop ever
    // blocks (the deadlock we are ruling out), polls stop and this fires.
    std::thread watchdog([] {
        while (!g_done) {
            Sleep(500);
            long long age = (long long)GetTickCount() - g_lastPollMs.load();
            if (g_lastPollMs && age > 6000) {
                printf("FAIL: poll silent for %lld ms -- message loop blocked (deadlock)\n", age);
                fflush(stdout);
                ExitProcess(3);
            }
            long long total = (long long)GetTickCount() - g_t0;
            if (total > 180000) {
                printf("FAIL: 180 s without reaching post-EOF; last state='%s' sawPlaying=%d\n",
                       g_lastState.c_str(), (int)g_sawPlaying);
                fflush(stdout);
                ExitProcess(4);
            }
        }
    });
    watchdog.detach();

    int rc = p_attach((long long)(intptr_t)g_hwnd);
    printf("[%7u ms] s3_attach rc=%d\n", GetTickCount() - g_t0, rc);

    // The app pushes a settings block before opening; without convertToSdr an HDR
    // file has no connectable output on an SDR path and Open fails 0x80040216.
    // Mirror the minimum the media-player path needs, in the ABI's own flat form.
    rc = p_cmd("{\"a\":\"set\",\"sets\":\"hdr.convertToSdr=1;hdr.sdrNits=127;hdr.toneMapCurve=7;ml.enable=1;ml.mode=0\"}");
    printf("[%7u ms] s3_cmd set rc=%d\n", GetTickCount() - g_t0, rc);

    // JSON-escape the path. The app sends json.dumps, which escapes backslashes;
    // hand-built JSON with raw '\' made the engine parse "C:Users..." and LAV fail
    // to open a file that does not exist -- a harness bug that looked like an
    // engine regression for one run.
    std::string esc;
    for (const char* c = file; *c; ++c) {
        if (*c == '\\' || *c == '"') esc += '\\';
        esc += *c;
    }
    std::string open = std::string("{\"a\":\"open\",\"url\":\"") + esc + "\"}";
    rc = p_cmd(open.c_str());
    printf("[%7u ms] s3_cmd open rc=%d  (%s)\n", GetTickCount() - g_t0, rc, file);
    if (rc != 0) { Note("open failed"); return 2; }

    SetTimer(g_hwnd, 1, 200, nullptr);
    MSG msg;
    while (GetMessage(&msg, 0, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessage(&msg); }
    KillTimer(g_hwnd, 1);

    printf("\nRESULT: polls=%lld sawPlaying=%d eofDetected=%d postEndPolls=%d lastState=%s\n",
           g_polls.load(), (int)g_sawPlaying, (int)g_sawEndAfterPlaying, g_postEndPolls,
           g_lastState.c_str());
    if (g_sawPlaying && g_sawEndAfterPlaying && g_postEndPolls >= 3) {
        printf("PASS: open did not hang, playback ran, EOF was detected, poll stayed alive, shutdown clean\n");
        return 0;
    }
    printf("FAIL: criteria not met\n");
    return 1;
}

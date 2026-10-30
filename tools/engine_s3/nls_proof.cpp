// nls_proof.cpp -- drives the staged s3engine.dll through the bidirectional-NLS
// configurations and records what the engine actually published for each one.
//
// Why a harness: the split moves the correction onto the second axis, and a wrong
// sign still "fills the screen" - it just distorts the other way. The numbers in
// the status JSON (nls.warp / nls.crop) and the frame grabs are the evidence that
// the geometry did what the settings asked, without anyone having to judge a
// picture by eye.
//
//   nls_proof.exe [dll] [file] [outdir]
//
// Pass criteria (checked against the printed table + the engine log):
//   - Horizontal and Split 100 publish the SAME per-axis factors (0.807/1.000
//     on the 2.2:1 test title), and both match the pre-split horizontal pass.
//   - Split 50 warps BOTH axes (0.899/1.113 here) - neither axis carries the
//     whole correction.
//   - Split 50 + Max distortion 110 clamps each axis and the geometry crops the
//     slack axis ([GEOM] dest wider than client).
//   - Vertical leaves the horizontal axis at 1.000 and puts 1/k on y.
//   - Crop mode logs "no pass (crop to fill)"; Off logs warp 0.
//
// NOT a criterion: frame equality. A grab returns the renderer's last DRAWN
// frame, and while paused a settings change does not always force a redraw, so
// the BMPs lag the numbers (measured: the Crop leg's frame still matched
// Horizontal). Read the [NLS]/[GEOM] lines for geometry; look at the BMPs only
// for shape.

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

static fn_attach   p_attach;
static fn_cmd      p_cmd;
static fn_stats    p_stats;
static fn_shutdown p_shutdown;

static HWND g_hwnd = 0;
static std::atomic<long long> g_lastPollMs{0};
static std::atomic<int> g_phase{0};
static std::string g_lastState;
static DWORD g_t0 = 0;
static DWORD g_phaseAt = 0;
static int g_cfg = 0;

struct Cfg {
    const char* name;
    const char* sets;
    const char* bmp;
};

// Every leg starts from the same title, the same frame and the same tone map;
// only the NLS rows move. Fill limit is opened up on the Auto legs so the caps
// are what decides, not the "would I letterbox" refusal.
static const Cfg kCfgs[] = {
    { "off",            "geo.nls=0",
      "nls_proof_0_off.bmp" },
    { "stretch-h",      "geo.nls=1;geo.nlsFillMode=1;geo.nlsAxis=1;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2;geo.nlsMax=1.4",
      "nls_proof_1_stretch_h.bmp" },
    { "split50",        "geo.nlsFillMode=1;geo.nlsAxis=3;geo.nlsSplit=0.5;geo.nlsMax=1.4",
      "nls_proof_2_split50.bmp" },
    { "split50-auto110", "geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsMax=1.1",
      "nls_proof_3_split50_cap110.bmp" },
    { "split100",       "geo.nlsFillMode=1;geo.nlsFillLimit=1.05;geo.nlsAxis=3;"
                        "geo.nlsSplit=1.0;geo.nlsMax=1.4",
      "nls_proof_4_split100.bmp" },
    { "horizontal",     "geo.nlsAxis=1",
      "nls_proof_5_horizontal.bmp" },
    { "vertical",       "geo.nlsAxis=2;geo.nlsSplit=0.0",
      "nls_proof_6_vertical.bmp" },
    { "crop",           "geo.nlsFillMode=2;geo.nlsAxis=1",
      "nls_proof_7_crop.bmp" },
};

static std::string g_outDir;

static std::string FieldOf(const char* j, const char* key) {
    const std::string k = std::string("\"") + key + "\":\"";
    const char* p = strstr(j, k.c_str());
    if (!p) return std::string();
    p += k.size();
    const char* e = strchr(p, '"');
    return e ? std::string(p, e - p) : std::string();
}

static std::string ObjOf(const char* j, const char* key) {
    const std::string k = std::string("\"") + key + "\":{";
    const char* p = strstr(j, k.c_str());
    if (!p) return std::string();
    p += k.size() - 1;
    const char* e = strchr(p, '}');
    return e ? std::string(p, e - p + 1) : std::string();
}

static void Note(const char* what) {
    printf("[%7u ms] %s\n", GetTickCount() - g_t0, what);
    fflush(stdout);
}

static int Cmd(const char* json) {
    int rc = p_cmd(json);
    printf("[%7u ms] cmd %-58s rc=%d\n", GetTickCount() - g_t0, json, rc);
    fflush(stdout);
    return rc;
}

static std::string JsonEscape(const std::string& in) {
    std::string out;
    for (char c : in) {
        if (c == '\\' || c == '"') out += '\\';
        out += c;
    }
    return out;
}

static std::string Stats() {
    static char buf[16384];
    const int n = p_stats(buf, sizeof(buf));
    if (n <= 0) return std::string();
    buf[n] = 0;
    return std::string(buf, (size_t)n);
}

static bool Grab(const char* name) {
    const std::string path = g_outDir + "\\" + name;
    const int rc = p_cmd(("{\"a\":\"grab\",\"file\":\"" + JsonEscape(path) + "\"}").c_str());
    printf("[%7u ms] grab %-34s rc=%d\n", GetTickCount() - g_t0, name, rc);
    fflush(stdout);
    return rc == 0;
}

static void PollOnce() {
    std::string j = Stats();
    g_lastPollMs = GetTickCount();
    if (j.empty()) return;
    const std::string st = FieldOf(j.c_str(), "state");
    if (st != g_lastState) {
        printf("[%7u ms] state: %s -> %s\n", GetTickCount() - g_t0,
               g_lastState.empty() ? "(none)" : g_lastState.c_str(), st.c_str());
        fflush(stdout);
        g_lastState = st;
    }

    const DWORD now = GetTickCount();
    switch (g_phase) {
    case 0:
        if (st == "playing") { Note("playing"); g_phase = 1; g_phaseAt = now; }
        break;
    // Freeze on one frame: the geometry must update while paused (the app does the
    // same), and every leg is then the same picture.
    case 1:
        if (now - g_phaseAt > 1200) {
            Cmd("{\"a\":\"seek\",\"pos\":3000000000}");   // 5:00
            g_phase = 2; g_phaseAt = now;
        }
        break;
    case 2:
        if (now - g_phaseAt > 2500) {
            Cmd("{\"a\":\"pause\"}");
            g_phase = 3; g_phaseAt = now;
        }
        break;
    case 3:
        if (now - g_phaseAt > 700) {
            g_cfg = 0;
            printf("\n%-18s %s\n", "CONFIG", "status JSON nls{...}");
            Cmd((std::string("{\"a\":\"set\",\"sets\":\"") + kCfgs[0].sets + "\"}").c_str());
            g_phase = 4; g_phaseAt = now;
        }
        break;
    // One leg of the table: settle, grab, publish the engine's own numbers.
    case 4:
        if (now - g_phaseAt > 900) {
            Grab(kCfgs[g_cfg].bmp);
            printf("%-18s %s\n", kCfgs[g_cfg].name, ObjOf(j.c_str(), "nls").c_str());
            fflush(stdout);
            if (++g_cfg >= (int)(sizeof(kCfgs) / sizeof(kCfgs[0]))) {
                Note("table done");
                g_phase = 9;
                PostQuitMessage(0);
                break;
            }
            Cmd((std::string("{\"a\":\"set\",\"sets\":\"") + kCfgs[g_cfg].sets + "\"}").c_str());
            g_phaseAt = now;
        }
        break;
    default:
        break;
    }
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_TIMER) PollOnce();
    if (m == WM_DESTROY) PostQuitMessage(0);
    return DefWindowProc(h, m, w, l);
}

int main(int argc, char** argv) {
    const char* dll = (argc > 1) ? argv[1]
        : "C:\\code\\unplugged-mpc-hc\\bin\\app\\Release\\s3engine.dll";
    const char* file = (argc > 2) ? argv[2] : "C:\\htpc\\Everest.2015_4kuhd.mkv";
    g_outDir = (argc > 3) ? argv[3] : "C:\\code\\unplugged-mpc-hc\\tools\\engine_s3";

    g_t0 = GetTickCount();
    HMODULE hm = LoadLibraryA(dll);
    if (!hm) { printf("FAIL: cannot load %s (err %lu)\n", dll, GetLastError()); return 2; }
    p_attach   = (fn_attach)GetProcAddress(hm, "s3_attach");
    p_cmd      = (fn_cmd)GetProcAddress(hm, "s3_cmd");
    p_stats    = (fn_stats)GetProcAddress(hm, "s3_stats");
    p_shutdown = (fn_shutdown)GetProcAddress(hm, "s3_shutdown");
    if (!p_attach || !p_cmd || !p_stats || !p_shutdown) { printf("FAIL: missing exports\n"); return 2; }
    printf("engine under test: %s\nfile: %s\n", dll, file);

    WNDCLASSA wc = {};
    wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandle(0); wc.lpszClassName = "nlsproof";
    RegisterClassA(&wc);
    g_hwnd = CreateWindowExA(0, "nlsproof", "nlsproof", WS_OVERLAPPEDWINDOW,
                             0, 0, 640, 360, 0, 0, wc.hInstance, 0);
    if (!g_hwnd) { printf("FAIL: no window\n"); return 2; }

    std::thread watchdog([] {
        while (g_phase != 9) {
            Sleep(500);
            const long long age = (long long)GetTickCount() - g_lastPollMs.load();
            if (g_lastPollMs && age > 8000) {
                printf("FAIL: poll silent for %lld ms at phase %d\n", age, (int)g_phase);
                fflush(stdout);
                ExitProcess(3);
            }
            if ((long long)GetTickCount() - g_t0 > 180000) {
                printf("FAIL: timeout at phase %d lastState=%s\n", (int)g_phase, g_lastState.c_str());
                fflush(stdout);
                ExitProcess(4);
            }
        }
    });
    watchdog.detach();

    printf("[%7u ms] s3_attach rc=%d\n", GetTickCount() - g_t0, (int)p_attach((long long)(intptr_t)g_hwnd));

    // The minimum the media path needs (same as sub_proof): SDR conversion on a
    // known curve, grading on - the NLS rows are the only variable.
    Cmd("{\"a\":\"set\",\"sets\":\"hdr.convertToSdr=1;hdr.sdrNits=127;hdr.toneMapCurve=7;ml.enable=1;ml.mode=0\"}");
    Cmd((std::string("{\"a\":\"open\",\"url\":\"") + JsonEscape(file) + "\"}").c_str());

    SetTimer(g_hwnd, 1, 200, nullptr);
    MSG msg;
    while (GetMessage(&msg, 0, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessage(&msg); }
    KillTimer(g_hwnd, 1);
    p_shutdown();
    printf("\nRESULT: phase=%d lastState=%s\n", (int)g_phase, g_lastState.c_str());
    return g_phase == 9 ? 0 : 1;
}
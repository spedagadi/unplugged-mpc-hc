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
//     slack axis ([GEOM] dest wider than client). Max 101/105/110/116 must give
//     DIFFERENT warp/crop pairs; identical numbers mean the cap is not reaching
//     both the geometry and the shader (the 2026-11-03 dead-parameter state).
//   - Vertical leaves the horizontal axis at 1.000 and puts 1/k on y.
//   - Crop mode logs "no pass (crop to fill)"; Off logs warp 0.
//   - Auto always fills to Bars removed (Fill limit is retired): bars100 fills
//     fully, bars50 keeps half the bars at half the correction, bars0 is the
//     plain fit rect with no pass and no crop.
//   - Post-NLS crop limits: auto-capX0 reports cxn=0 with a dest narrower than
//     the window (bars, not a cut); auto-capX10 reports cxn=10. Crop mode
//     follows Bars removed: bars0 is the fit rect, bars100 covers.
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
#include <vector>

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
    // The Max distortion budget, Fill limit retired: both legs fill, but 140
    // lets the warp take more of the correction and 110 pushes the difference
    // into the geometry crop. (This leg pair predates the retirement of Fill
    // limit; geo.nlsFillLimit is still accepted and ignored.)
    { "auto-def140",    "geo.nlsFillMode=0;geo.nlsFillLimit=1.05;geo.nlsAxis=1;geo.nlsMax=1.4",
      "nls_proof_8_auto_def140.bmp" },
    { "auto-def110",    "geo.nlsFillMode=0;geo.nlsFillLimit=1.05;geo.nlsAxis=1;geo.nlsMax=1.1",
      "nls_proof_9_auto_def110.bmp" },
    // The 2.0.0 stock defaults after 2026-11-01: Auto, Fill limit 200, Axis Split
    // 50, full strength. This is the leg that answers "does enabling NLS fill a
    // scope title with everything left at default" - it must fill, at Split 50's
    // per-axis cost, with no crop.
    { "auto-lim200",    "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_13_auto_lim200.bmp" },
    // Bars removed is authoritative in Auto too (regression 2026-11-03): the
    // geometry must follow the dial. The old code forced barFill=1.0 in Auto
    // while the shader kept reading the slider, so the destination stayed fully
    // filled and lowering the value only removed the shader's compensation -
    // "the image gets squeezed horizontally". On a clean scope source:
    //   bars100 -> dest = full client, ratio < 1
    //   bars50  -> dest half-way between fit and fill, ratio closer to 1
    //   bars0   -> dest = the plain fit rect, no NLS pass at all
    { "auto-bars100",   "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=1;"
                        "geo.nlsBars=1;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_22_auto_bars100.bmp" },
    { "auto-bars50",    "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=1;"
                        "geo.nlsBars=0.5;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_23_auto_bars50.bmp" },
    { "auto-bars0",     "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=1;"
                        "geo.nlsBars=0;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_24_auto_bars0.bmp" },
    // POST-NLS CROP LIMITS. Auto at Max 100 is the pure-crop baseline; the X
    // limit then decides how much of the residue may actually be cut. capX0
    // must show cxn=0 and a dest smaller than the window (bars); capX10 must
    // show cxn=10. Crop mode must now follow Bars removed: 0 = fit, 100 = cover.
    { "auto-capX0",     "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=1;"
                        "geo.nlsMax=1.0;geo.nlsCropX=0;geo.nlsCropY=0.5;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_25_auto_capX0.bmp" },
    { "auto-capX10",    "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=1;"
                        "geo.nlsMax=1.0;geo.nlsCropX=0.1;geo.nlsCropY=0.5;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_26_auto_capX10.bmp" },
    { "crop-bars0",     "geo.nls=1;geo.nlsFillMode=2;geo.nlsBars=0;geo.nlsAxis=1;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0.5;geo.nlsCropY=0.5;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_27_crop_bars0.bmp" },
    { "crop-bars50",    "geo.nls=1;geo.nlsFillMode=2;geo.nlsBars=0.5;geo.nlsAxis=1;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0.5;geo.nlsCropY=0.5;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_28_crop_bars50.bmp" },
    { "crop-bars100",   "geo.nls=1;geo.nlsFillMode=2;geo.nlsBars=1;geo.nlsAxis=1;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0.5;geo.nlsCropY=0.5;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_29_crop_bars100.bmp" },
    // The always-visible case: Bars removed 0 leaves the fit rect (ratio 1),
    // so only the Post-NLS crop should inject a pass. This is the 16:9-title-
    // on-16:9-screen report: no warp, no geometry crop, but the picture must
    // still zoom when X-Crop is raised.
    { "crop-only-x10",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=0;geo.nlsAxis=1;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0.1;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_30_crop_only_x10.bmp" },
    // AXIS COMPARISON on a 2.39 test frame with a perfect centre circle.
    // Same correction, same budgets; only the axis distribution moves.
    // Horizontal leaves height untouched; Split 50 scales the protected
    // centre uniformly (sx == sy), pushing the anisotropy into the rim.
    { "axis-horiz",     "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=1;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_31_axis_horiz.bmp" },
    { "axis-split25",   "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.25;geo.nlsMax=1.4;geo.nlsCropX=0;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_32_axis_split25.bmp" },
    { "axis-split50",   "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsMax=1.4;geo.nlsCropX=0;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_33_axis_split50.bmp" },
    { "axis-split75",   "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.75;geo.nlsMax=1.4;geo.nlsCropX=0;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_34_axis_split75.bmp" },
    { "axis-vertical",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsBars=1;geo.nlsAxis=2;"
                        "geo.nlsMax=1.4;geo.nlsCropX=0;geo.nlsCropY=0;"
                        "geo.nlsStrength=1;geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_35_axis_vertical.bmp" },
    // 28 Years Later / AVSForum workflow legs (2026-11-01): Crop is the zero-
    // distortion reference; Auto at Max 101 should be nearly identical, then
    // raising Max should trade crop for warp, ending at no crop.
    { "crop-ref",       "geo.nls=1;geo.nlsFillMode=2;geo.nlsAxis=3;geo.nlsSplit=0.5;"
                        "geo.nlsBars=1;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_14_crop_ref.bmp" },
    { "auto101-split",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsBars=1;geo.nlsMax=1.01;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_15_auto101_split.bmp" },
    { "auto105-split",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsBars=1;geo.nlsMax=1.05;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_16_auto105_split.bmp" },
    { "auto110-split",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsBars=1;geo.nlsMax=1.10;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_17_auto110_split.bmp" },
    { "auto116-split",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsBars=1;geo.nlsMax=1.16;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_18_auto116_split.bmp" },
    { "auto101-horiz",  "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=1;"
                        "geo.nlsBars=1;geo.nlsMax=1.01;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_19_auto101_horiz.bmp" },
    { "auto101-bars50", "geo.nls=1;geo.nlsFillMode=0;geo.nlsFillLimit=2.0;geo.nlsAxis=3;"
                        "geo.nlsSplit=0.5;geo.nlsBars=0.5;geo.nlsMax=1.01;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_20_auto101_bars50.bmp" },
    { "crop-bars50",    "geo.nls=1;geo.nlsFillMode=2;geo.nlsAxis=3;geo.nlsSplit=0.5;"
                        "geo.nlsBars=0.5;geo.nlsMax=1.4;geo.nlsStrength=1;"
                        "geo.nlsCenter=0.45;geo.nlsCurve=1.2",
      "nls_proof_21_crop_bars50.bmp" },
    // Rim mode: protect the middle almost to the edge and dump the whole
    // correction into a narrow rim (the operator's "extreme at the edges, keep
    // the centre intact"). Horizontal axis, because a stretching axis cannot be
    // protected past ~1/ratio.
    { "rim-protect",    "geo.nlsFillMode=1;geo.nlsAxis=1;geo.nlsMax=1.4;geo.nlsCenter=0.9;"
                        "geo.nlsCurve=2.9",
      "nls_proof_10_rim.bmp" },
    // Partial bar fill: the picture grows into half the letterbox, so the
    // correction must be about half of the full fill's and a bar must remain.
    { "bars50",         "geo.nlsFillMode=1;geo.nlsAxis=1;geo.nlsMax=1.4;geo.nlsCenter=0.45;"
                        "geo.nlsCurve=1.2;geo.nlsBars=0.5",
      "nls_proof_11_bars50.bmp" },
    { "bars0",          "geo.nlsBars=0",
      "nls_proof_12_bars0.bmp" },
};

static std::string g_outDir;
static double g_seekSec = 300.0;   // argv[4]: where to seek before the legs
static double g_watchSec = 0.0;    // argv[5]: >0 = play this long, no test legs

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

// Screen capture of the harness window. The engine's `grab` returns the
// renderer's input frame, BEFORE the post-scale shaders - useless for judging
// NLS. This BitBlts the composited window (the D3D swap chain in windowed mode
// is on the desktop), so the warp/crop under test is in the picture.
static HWND g_renderChild = nullptr;
static BOOL CALLBACK FindChildProc(HWND h, LPARAM) {
    wchar_t cls[128] = {};
    GetClassNameW(h, cls, 128);
    printf("[child] %p class=%ls\n", (void*)h, cls);
    if (!g_renderChild) g_renderChild = h;
    return TRUE;
}

static bool GrabScreen(const char* name) {
    if (!g_renderChild) EnumChildWindows(g_hwnd, FindChildProc, 0);
    HWND target = g_renderChild ? g_renderChild : g_hwnd;
    RECT rc{};
    GetClientRect(target, &rc);
    const int w = rc.right, h = rc.bottom;
    if (w <= 0 || h <= 0) return false;
    HDC sdc = GetDC(nullptr), mdc = CreateCompatibleDC(sdc);
    HBITMAP bm = CreateCompatibleBitmap(sdc, w, h);
    HGDIOBJ old = SelectObject(mdc, bm);
    // PrintWindow with PW_RENDERFULLCONTENT composites a D3D child (BitBlt of
    // the desktop returns the window's white background for a swap chain).
    BOOL ok = PrintWindow(target, mdc, 0x00000003 /*FULLCONTENT|CLIENTONLY*/);
    if (!ok) {
        POINT pt{0, 0};
        ClientToScreen(target, &pt);
        ok = BitBlt(mdc, 0, 0, w, h, sdc, pt.x, pt.y, SRCCOPY);
    }
    std::vector<unsigned char> buf((size_t)w * h * 4);
    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w;
    bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    GetDIBits(mdc, bm, 0, (UINT)h, buf.data(), &bi, DIB_RGB_COLORS);
    SelectObject(mdc, old);
    DeleteObject(bm);
    DeleteDC(mdc);
    ReleaseDC(nullptr, sdc);
    const std::string path = g_outDir + "\\screen_" + name;
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    BITMAPFILEHEADER fh{};
    fh.bfType = 0x4D42;
    fh.bfOffBits = sizeof(fh) + sizeof(bi.bmiHeader);
    fh.bfSize = fh.bfOffBits + (DWORD)buf.size();
    fwrite(&fh, 1, sizeof(fh), f);
    fwrite(&bi.bmiHeader, 1, sizeof(bi.bmiHeader), f);
    fwrite(buf.data(), 1, buf.size(), f);
    fclose(f);
    printf("[%7u ms] screen %-32s ok=%d\n", GetTickCount() - g_t0, name, (int)ok);
    fflush(stdout);
    return ok == TRUE;
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
            char sb[96];
            snprintf(sb, sizeof(sb), "{\"a\":\"seek\",\"pos\":%.0f}", g_seekSec * 10000000.0);
            Cmd(sb);
            g_phase = 2; g_phaseAt = now;
        }
        break;
    case 2:
        if (now - g_phaseAt > 2500) {
            if (g_watchSec > 0.0) {
                // Watch mode: play across the requested span without pausing or
                // pushing config legs, then quit. Used for aspect transitions
                // (scope <-> IMAX) where the question is what the band latch and
                // geometry do over time, not what one paused frame looks like.
                if (now - g_phaseAt > (DWORD)(g_watchSec * 1000.0)) {
                    Note("watch done");
                    g_phase = 9;
                    PostQuitMessage(0);
                }
                break;
            }
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
            GrabScreen(kCfgs[g_cfg].bmp);
            printf("%-18s %s\n", kCfgs[g_cfg].name, ObjOf(j.c_str(), "nls").c_str());
            fflush(stdout);
            if (++g_cfg >= (int)(sizeof(kCfgs) / sizeof(kCfgs[0]))) {
                Note("table done");
                g_phase = 20;
                break;
            }
            Cmd((std::string("{\"a\":\"set\",\"sets\":\"") + kCfgs[g_cfg].sets + "\"}").c_str());
            g_phaseAt = now;
        }
        break;
    // The picture CANVAS moving on a paused frame: the shell hides its chrome and
    // asks for the vacated area. The destination rect must follow AND be redrawn,
    // or the old (smaller) picture stays on screen with black were the panel was.
    case 20:
        if (now - g_phaseAt > 600) {
            Cmd("{\"a\":\"videorect\",\"x\":0,\"y\":66,\"w\":624,\"h\":249}");
            Note("videorect -> chrome-up canvas (paused)");
            g_phase = 21; g_phaseAt = now;
        }
        break;
    case 21:
        if (now - g_phaseAt > 900) {
            Cmd("{\"a\":\"videorect\",\"x\":0,\"y\":0,\"w\":0,\"h\":0}");
            Note("videorect -> cleared (chrome hidden, paused)");
            g_phase = 22; g_phaseAt = now;
        }
        break;
    case 22:
        if (now - g_phaseAt > 900) {
            Note("videorect legs done");
            g_phase = 9;
            PostQuitMessage(0);
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
    if (argc > 4) g_seekSec = atof(argv[4]);
    if (argc > 5) g_watchSec = atof(argv[5]);

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
    // The screen capture below reads the composited desktop; keep this window
    // above everything so the grab is the rendered frame, not another app.
    ShowWindow(g_hwnd, SW_SHOW);
    SetWindowPos(g_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
    SetForegroundWindow(g_hwnd);

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
    if (g_watchSec > 0.0) {
        // Reproduce an aspect transition with the operator's Auto recipe: fill
        // to Bars removed 100, no cap binding, Horizontal axis.
        Cmd("{\"a\":\"set\",\"sets\":\"geo.nls=1;geo.nlsBars=1;geo.nlsFillMode=0;"
            "geo.nlsAxis=1;geo.nlsMax=1.4;geo.nlsStrength=1;geo.nlsCenter=0.45;"
            "geo.nlsCurve=1.2\"}");
    }
    Cmd((std::string("{\"a\":\"open\",\"url\":\"") + JsonEscape(file) + "\"}").c_str());

    SetTimer(g_hwnd, 1, 200, nullptr);
    MSG msg;
    while (GetMessage(&msg, 0, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessage(&msg); }
    KillTimer(g_hwnd, 1);
    p_shutdown();
    printf("\nRESULT: phase=%d lastState=%s\n", (int)g_phase, g_lastState.c_str());
    return g_phase == 9 ? 0 : 1;
}
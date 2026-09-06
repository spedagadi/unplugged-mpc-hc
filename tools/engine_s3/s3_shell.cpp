// s3_shell.cpp — S3: UI shell skeleton bound to MpcPlayer.
//
// One window; video fills the client; overlay panels float above it.
// RIGHT rail = tabbed (Playback | System). System = hierarchical settings
// (Unplugged model): icon rail (SOURCE/HDR/ZION/OUTPUT/SYSTEM) → categories →
// rows that are exactly three types: toggle · cycle (next-value live) ·
// slider (no text entry). Row values currently bind to a live-apply stub that
// prints the setting key; real MPCVR binding is the next milestone.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <commdlg.h>
#include <dshow.h>
#include <atlbase.h>

#include "MpcPlayer.h"

#include <cstring>
#include <cmath>
#include <iostream>
#include <string>
#include <vector>
#include <functional>
#include <string_view>
#include <algorithm>

// -- theme (Unplugged tokens) ------------------------------------------------
namespace {
constexpr COLORREF COL_BG      = RGB(0x0E, 0x0E, 0x10);
constexpr COLORREF COL_PANEL   = RGB(0x0E, 0x0E, 0x10);
constexpr COLORREF COL_BORDER  = RGB(0x24, 0x24, 0x28);
constexpr COLORREF COL_ACCENT  = RGB(0xE8, 0x55, 0x1F);
constexpr COLORREF COL_ACCENT2 = RGB(0xFF, 0x8A, 0x4C);
constexpr COLORREF COL_TEXT    = RGB(0xF2, 0xF2, 0xF2);
constexpr COLORREF COL_MID     = RGB(0x8A, 0x8A, 0x90);
constexpr COLORREF COL_LO      = RGB(0x5A, 0x5A, 0x5A);
constexpr COLORREF COL_OK      = RGB(0x4C, 0xAF, 0x50);

// UI scale: everything is authored at 96dpi and multiplied by g_scale for the
// actual display, so the whole shell resizes with the screen resolution.
float g_scale = 1.0f;
int S(float v) { return (int)(v * g_scale + 0.5f); }

int kLeftW = 260;
int kRightW = 440;   // fixed width for ALL tabs (no widen/squeeze); scales with DPI
int kBottomH = 140;
int kPad = 16;
int kRowH = 22;
int kBtnH = 34;

// Right-rail geometry
int kTabH = 34;
int kRailW = 80;
int kCatH = 26;
int kSysRowH = 40;
int kIconH = 58;     // icon tabs sized to hold a real glyph + under-label
int kIconStep = 64;  // icon tab + gap

void InitGeometry() {
    g_scale = GetDpiForSystem() / 96.0f;
    kLeftW = S(260); kRightW = S(440);
    kBottomH = S(140); kPad = S(16); kRowH = S(22); kBtnH = S(34);
    kTabH = S(34); kRailW = S(80); kCatH = S(26); kSysRowH = S(40);
    kIconH = S(58); kIconStep = S(64);
}

enum Cmd : int {
    kCmdNone = 0,
    kCmdOpen, kCmdPlayPause, kCmdStop, kCmdSeekBack, kCmdSeekFwd,
    kCmdModeVP, kCmdModeMedia,
    kCmdRepaint,
};
}  // namespace

// -- globals -----------------------------------------------------------------
HWND g_hwnd = nullptr;
HWND g_hVideo = nullptr;
HWND g_hLeft = nullptr;
HWND g_hRight = nullptr;
HWND g_hBottom = nullptr;

MpcPlayer* g_player = nullptr;
MpcPlayer::Renderer g_renderer = MpcPlayer::Renderer::MPCVR;
std::wstring g_openFile;
bool g_editMode = true;   // WATCH ⇄ EDIT via Up arrow

// Right rail state
enum class RailTab { Playback = 0, System = 1 };
RailTab g_railTab = RailTab::System;
int g_sysGroup = 2;       // default group = ZION
int g_lastAppliedRow = -1;

// -- row model (toggle · cycle · slider) --------------------------------------
enum class RowType { Toggle, Cycle, Slider };
struct Row {
    const wchar_t* label = nullptr;
    RowType type = RowType::Toggle;
    int group = 0;                         // kSysGroups index
    const wchar_t* section = nullptr;      // sub-section header (TONE CURVE / CHROMA / …)
    std::vector<const wchar_t*> options;   // cycle
    int opt = 0;
    float min = 0, max = 100, val = 50;    // slider — SAME domains as MPCVR controls
    float defaultVal = 50;                 // position when its mode != Manual
    int gate = 0;                          // 0=none, 1=tone-curve, 2=chroma, 3=detail
    bool on = false;                       // toggle
    const char* key = "?";                 // MPCVR config key (binding stub)
    bool live = true;                      // live-apply vs next-start
    bool disabled = false;                 // hard lock: master off or group off
    bool adjustable = true;                // slider drag allowed (Manual only)
    bool enabledFlag = true;               // per-control enable (its dialog checkbox)
    bool hasUncheck = true;                // false = parameter-only (no enable box)
};
std::vector<Row> g_rows;
int g_toneModeRow = -1;    // index of the tone-curve Mode row
int g_chromaModeRow = -1;  // index of the chroma Mode row
int g_detailModeRow = -1;  // index of the detail Mode row

bool ModeManual(int row) {
    return row >= 0 && row < (int)g_rows.size() && g_rows[row].opt == 1;
}
bool ToneManual()   { return ModeManual(g_toneModeRow); }
bool ChromaManual() { return ModeManual(g_chromaModeRow); }
bool DetailManual() { return ModeManual(g_detailModeRow); }

enum RowGroup : int {
    kGroupSource = 0,
    kGroupHdr = 1,
    kGroupZion = 2,     // "OUT"/"HDR" etc. are Windows macros; never use as names
    kGroupOutput = 3,
    kGroupSystem = 4,
};

// Global master: "Enable ML grade". When off, every Zion control is locked.
bool g_mlMasterEnable = false;

int SectionMode(int modeRow) {
    return (modeRow >= 0 && modeRow < (int)g_rows.size()) ? g_rows[modeRow].opt : 2;
}
bool SecManual(int modeRow) { return SectionMode(modeRow) == 1; }
bool SecActive(int modeRow) { return SectionMode(modeRow) != 2; }

// Two independent gates:
//   - "disabled"  = HARD lock (master Enable off, or the group's mode Off).
//                   The per-control checkbox is also locked then.
//                   Auto/Default do NOT grey the rows.
//   - "adjustable"= slider drag allowed: not hard-locked AND control checkbox
//                   on AND the section is in Manual (Auto/Default = model-driven).
// Non-Manual sections snap their sliders to the stored defaults.
void UpdateGates() {
    const bool toneM = SecManual(g_toneModeRow), chrM = SecManual(g_chromaModeRow), detM = SecManual(g_detailModeRow);
    const bool toneA = SecActive(g_toneModeRow), chrA = SecActive(g_chromaModeRow), detA = SecActive(g_detailModeRow);
    for (size_t i = 0; i < g_rows.size(); ++i) {
        Row& r = g_rows[i];
        if (strcmp(r.key, "zion.enabled") == 0) { r.disabled = r.adjustable = false; continue; }
        // HDR/OUTPUT/SYSTEM groups are independent settings — never ML-locked.
        if (r.group != kGroupZion) { r.disabled = false; r.adjustable = true; continue; }
        const bool modeRow = (int)i == g_toneModeRow || (int)i == g_chromaModeRow || (int)i == g_detailModeRow;
        if (modeRow) { r.disabled = !g_mlMasterEnable; r.adjustable = false; continue; }

        bool hardLive = g_mlMasterEnable;
        bool secM = true, secA = true;
        if (r.gate == 1) { secM = toneM; secA = toneA; }
        else if (r.gate == 2) { secM = chrM; secA = chrA; }
        else if (r.gate == 3) { secM = detM; secA = detA; }
        r.disabled = !hardLive || !secA;             // hard lock only when OFF/master
        r.adjustable = !r.disabled && r.enabledFlag && secM;
        if (r.type == RowType::Slider && !secM) r.val = r.defaultVal;   // Auto/Default/Off snap
    }
}

// Real MPCVR dialog inventory \u2192 rows.

void BuildRows() {
    if (!g_rows.empty()) return;

    // -- ZION (live ML grading + debug) --
    // Slider domains match MPCVR's dialog EXACTLY (PropPage MLSlider table).
    auto add = [&](const wchar_t* label, RowType t, int group, const char* key, bool live,
                   const wchar_t* section = nullptr, std::vector<const wchar_t*> options = {},
                   int opt = 0, float min = 0, float max = 100, float val = 50,
                   float defaultVal = 50, int gate = 0, bool on = false) {
        Row r;
        r.label = label; r.type = t; r.group = group; r.key = key; r.live = live;
        r.section = section; r.options = options; r.opt = opt;
        r.min = min; r.max = max; r.val = val; r.defaultVal = defaultVal;
        r.gate = gate; r.on = on;
        g_rows.push_back(r);
    };

    add(L"Enable ML grade", RowType::Toggle, kGroupZion, "zion.enabled", true, nullptr, {}, 0, 0, 0, 0, 0, 0, true);

    add(L"Mode", RowType::Cycle, kGroupZion, "zion.toneMode", true, L"TONE CURVE",
        {L"Auto", L"Manual", L"Off"}, 0);   // demo default: Auto
    g_toneModeRow = (int)g_rows.size() - 1;
    add(L"Gamma", RowType::Slider, kGroupZion, "zion.gamma", true, L"TONE CURVE", {}, 0, 0.50f, 1.50f, 1.00f, 1.00f, 1);
    add(L"Shadow", RowType::Slider, kGroupZion, "zion.shadow", true, L"TONE CURVE", {}, 0, 0.00f, 0.50f, 0.00f, 0.00f, 1);
    add(L"Highlight", RowType::Slider, kGroupZion, "zion.highlight", true, L"TONE CURVE", {}, 0, -0.30f, 0.40f, 0.00f, 0.00f, 1);

    add(L"Mode", RowType::Cycle, kGroupZion, "zion.chromaMode", true, L"CHROMA",
        {L"Default", L"Manual", L"Off"}, 0);   // demo default: Default
    g_chromaModeRow = (int)g_rows.size() - 1;
    add(L"Hunt", RowType::Slider, kGroupZion, "zion.hunt", true, L"CHROMA", {}, 0, 0.00f, 1.00f, 0.80f, 0.80f, 2);
    add(L"Ch-N", RowType::Slider, kGroupZion, "zion.chN", true, L"CHROMA", {}, 0, 1.00f, 1.50f, 1.20f, 1.20f, 2);
    add(L"Ch-F", RowType::Slider, kGroupZion, "zion.chF", true, L"CHROMA", {}, 0, 1.00f, 1.50f, 1.35f, 1.35f, 2);
    add(L"Knee", RowType::Slider, kGroupZion, "zion.knee", true, L"CHROMA", {}, 0, 0.10f, 0.90f, 0.55f, 0.55f, 2);
    add(L"Skin", RowType::Slider, kGroupZion, "zion.skin", true, L"CHROMA", {}, 0, 0.50f, 1.00f, 0.95f, 0.95f, 2);

    add(L"Mode", RowType::Cycle, kGroupZion, "zion.detailMode", true, L"DETAIL",
        {L"Auto", L"Manual", L"Off"}, 2);   // baseline: Off → CR/Res unchecked
    g_detailModeRow = (int)g_rows.size() - 1;
    add(L"CR strength", RowType::Slider, kGroupZion, "zion.cr", true, L"DETAIL", {}, 0, 0.00f, 0.50f, 0.30f, 0.30f, 3);
    add(L"Res knee", RowType::Slider, kGroupZion, "zion.resKnee", true, L"DETAIL", {}, 0, 0.40f, 0.90f, 0.60f, 0.60f, 3);
    add(L"Res strength", RowType::Slider, kGroupZion, "zion.resStr", true, L"DETAIL", {}, 0, 0.00f, 0.60f, 0.30f, 0.30f, 3);

    add(L"Passthrough", RowType::Toggle, kGroupZion, "zion.debugCopyShaders", false, L"DEBUG");
    add(L"Frame log", RowType::Toggle, kGroupZion, "zion.debugFrameLog", false, L"DEBUG");

    // -- HDR (independent output settings; exact MPCVR dialog semantics) --
    add(L"Prefer DV over PQ/HLG", RowType::Toggle, kGroupHdr, "hdr.preferDoVi", true, L"TONE MAPPING");
    add(L"Convert to SDR", RowType::Toggle, kGroupHdr, "hdr.convertToSdr", true, L"TONE MAPPING");
    add(L"SDR display nits", RowType::Slider, kGroupHdr, "hdr.sdrNits", true, L"TONE MAPPING", {}, 0, 25.0f, 400.0f, 125.0f, 125.0f);
    add(L"Windows HDR", RowType::Cycle, kGroupHdr, "hdr.toggleDisplay", true, L"DISPLAY TARGET",
        {L"Do not change", L"On (fullscreen)", L"On", L"On/off (fullscreen)", L"On/off"}, 0);
    add(L"Static nits (max)", RowType::Slider, kGroupHdr, "hdr.maxNits", true, L"DISPLAY TARGET", {}, 0, 200.0f, 10000.0f, 1000.0f, 1000.0f);
    add(L"Subtitle/OSD brightness", RowType::Slider, kGroupHdr, "hdr.osdBright", true, L"DISPLAY TARGET", {}, 0, 0.0f, 100.0f, 0.0f, 0.0f);

    // -- OUTPUT (Video Processing) --
    add(L"Use Direct3D 11", RowType::Toggle, kGroupOutput, "out.useD3D11", true, L"VIDEO PROCESSING");
    add(L"Texture format", RowType::Cycle, kGroupOutput, "out.texFormat", true, L"VIDEO PROCESSING",
        {L"Auto", L"8-bit", L"10-bit", L"16-bit float"}, 0);
    add(L"VP NV12", RowType::Toggle, kGroupOutput, "out.vpNV12", true, L"VIDEO PROCESSING");
    add(L"VP P01x", RowType::Toggle, kGroupOutput, "out.vpP01x", true, L"VIDEO PROCESSING");
    add(L"VP YUY2", RowType::Toggle, kGroupOutput, "out.vpYUY2", true, L"VIDEO PROCESSING");
    add(L"VP Other", RowType::Toggle, kGroupOutput, "out.vpOther", true, L"VIDEO PROCESSING");
    add(L"Deinterlacing", RowType::Cycle, kGroupOutput, "out.deinterlace", true, L"VIDEO PROCESSING",
        {L"Disable", L"Enable", L"Hack future frames"}, 1);
    add(L"Double frame rate", RowType::Toggle, kGroupOutput, "out.deintDouble", true, L"VIDEO PROCESSING");
    add(L"Blend deint 4:2:0", RowType::Toggle, kGroupOutput, "out.deintBlend", true, L"VIDEO PROCESSING");
    add(L"Shader VP resize", RowType::Toggle, kGroupOutput, "out.shaderVP", true, L"VIDEO PROCESSING");
    add(L"Super Resolution", RowType::Cycle, kGroupOutput, "out.superRes", true, L"VIDEO PROCESSING",
        {L"Disable", L"SD", L"720p", L"1080p", L"1440p"}, 0);
    add(L"RTX Video HDR", RowType::Toggle, kGroupOutput, "out.rtxVideoHdr", true, L"VIDEO PROCESSING");
    add(L"Chroma upsampling", RowType::Cycle, kGroupOutput, "out.chromaScaling", true, L"VIDEO PROCESSING",
        {L"Nearest", L"Bilinear", L"CatmullRom", L"KrigBilateral"}, 1);
    add(L"Upscaling", RowType::Cycle, kGroupOutput, "out.upscaling", true, L"VIDEO PROCESSING",
        {L"Nearest", L"Mitchell", L"CatmullRom", L"Lanczos2", L"Lanczos3", L"Jinc2"}, 2);
    add(L"Downscaling", RowType::Cycle, kGroupOutput, "out.downscaling", true, L"VIDEO PROCESSING",
        {L"Box", L"Bilinear", L"Hamming", L"Bicubic", L"BicubicSharp", L"Lanczos"}, 2);
    add(L"Interpolate at 50%", RowType::Toggle, kGroupOutput, "out.interpolate50", true, L"VIDEO PROCESSING");
    add(L"Use dithering", RowType::Toggle, kGroupOutput, "out.useDither", true, L"VIDEO PROCESSING");
    // -- OUTPUT (Output) --
    add(L"Swap effect", RowType::Cycle, kGroupOutput, "out.swapEffect", true, L"OUTPUT",
        {L"Discard", L"Flip"}, 1);
    add(L"Exclusive fullscreen", RowType::Toggle, kGroupOutput, "out.exclusiveFS", true, L"OUTPUT");
    add(L"Wait for VBlank", RowType::Toggle, kGroupOutput, "out.vBlank", true, L"OUTPUT");
    add(L"Adjust present time", RowType::Toggle, kGroupOutput, "out.adjustPresent", true, L"OUTPUT");
    add(L"Reinit on display change", RowType::Toggle, kGroupOutput, "out.reinitDisplay", true, L"OUTPUT");
    add(L"Show statistics", RowType::Toggle, kGroupOutput, "out.showStats", true, L"OUTPUT");
    // -- SYSTEM / App --
    add(L"Tray icon", RowType::Toggle, kGroupSystem, "sys.trayIcon", true, L"APP");

    // Parameter-only sliders: no enable box (Knee/Skin feed Ch-N/Ch-F; all HDR
    // controls are plain configuration sliders in the MPCVR dialog).
    for (auto& r : g_rows)
        if (!strcmp(r.key, "zion.knee") || !strcmp(r.key, "zion.skin") ||
            strncmp(r.key, "hdr.", 4) == 0)
            r.hasUncheck = false;

    UpdateGates();
}

std::vector<Row*> ActiveRows() {
    static std::vector<Row*> v;
    v.clear();
    for (auto& r : g_rows) if (r.group == g_sysGroup) v.push_back(&r);
    return v;
}

// -- fonts -------------------------------------------------------------------
namespace {
HFONT g_fSection, g_fLabel, g_fValue, g_fButton, g_fHeader, g_fStatus, g_fIcon;

void LoadInterFonts() {
    const wchar_t* dir = L"C:\\Code\\unplugged\\brand\\fonts\\";
    std::wstring files[] = {
        dir + std::wstring(L"Inter-Regular.ttf"),
        dir + std::wstring(L"Inter-Medium.ttf"),
        dir + std::wstring(L"Inter-SemiBold.ttf"),
        dir + std::wstring(L"Inter-Bold.ttf"),
    };
    for (auto& f : files) AddFontResourceExW(f.c_str(), FR_PRIVATE, 0);
}

HFONT MakeFont(int px, int weight) {
    return CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET,
                       OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                       DEFAULT_PITCH | FF_DONTCARE, L"Inter");
}

void InitFonts() {
    g_fSection = MakeFont(S(11), FW_SEMIBOLD);
    g_fLabel   = MakeFont(S(12), FW_NORMAL);
    g_fValue   = MakeFont(S(13), FW_MEDIUM);
    g_fButton  = MakeFont(S(12), FW_MEDIUM);
    g_fHeader  = MakeFont(S(24), FW_SEMIBOLD);
    g_fStatus  = MakeFont(S(12), FW_NORMAL);
    g_fIcon    = MakeFont(S(30), FW_SEMIBOLD);  // big grouped glyph, comparable to the tab
}
}  // namespace

// -- paint helpers ------------------------------------------------------------
namespace {

void PaintRow(HDC dc, int y, int colW, const wchar_t* label, const wchar_t* value,
              COLORREF vc) {
    RECT a = {kPad, y, kPad + colW - 8, y + kRowH};
    RECT b = {kPad + colW - 4, y, 2 * kPad + colW - 4, y + kRowH};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fLabel);
    SetTextColor(dc, COL_MID);
    DrawTextW(dc, label, -1, &a, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, g_fValue);
    SetTextColor(dc, vc);
    DrawTextW(dc, value, -1, &b, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, fo);
}

int PaintSection(HDC dc, int y, int w, const wchar_t* title) {
    RECT r = {kPad, y, w - kPad, y + 18};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fSection);
    SetTextColor(dc, COL_MID);
    DrawTextW(dc, title, -1, &r, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, fo);
    RECT sep = {kPad, y + 20, w - kPad, y + 21};
    HBRUSH bb = CreateSolidBrush(COL_BORDER); FillRect(dc, &sep, bb); DeleteObject(bb);
    return y + 28;
}

void DrawButton(HDC dc, const RECT& r, const wchar_t* text, bool hot, bool active) {
    HBRUSH bg = CreateSolidBrush(active ? COL_ACCENT : (hot ? RGB(0x23, 0x23, 0x27) : COL_PANEL));
    FillRect(dc, &r, bg); DeleteObject(bg);
    HBRUSH br = CreateSolidBrush(active ? COL_ACCENT2 : COL_BORDER);
    FrameRect(dc, &r, br); DeleteObject(br);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, active ? RGB(0, 0, 0) : COL_TEXT);
    HFONT fo = (HFONT)SelectObject(dc, g_fButton);
    RECT t = r;
    DrawTextW(dc, text, -1, &t, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, fo);
}

struct Btn { Cmd cmd; RECT rc; const wchar_t* label; bool active = false; };
std::vector<Btn> g_rightBtns;
RECT g_seekBar = {};
POINT g_lastMouse = {};

// Unplugged icon groups (verbatim glyphs + tints).
struct SysGroup { const wchar_t* icon; const wchar_t* label; COLORREF col;
                  std::vector<const wchar_t*> cats; };
const SysGroup kSysGroups[] = {
    { L"\u2B21", L"SOURCE", RGB(0x5B, 0x8F, 0xD0), { L"Input Device" } },
    { L"\u25D1", L"HDR",     RGB(0xC8, 0xA0, 0x30), { L"Tone Mapping", L"Peak Detection", L"Contrast Recovery", L"Display Target" } },
    { L"\u2726", L"ZION",    RGB(0xC8, 0x70, 0x40), { L"Zion Core" } },
    { L"\u25A3", L"OUTPUT",  RGB(0x4C, 0xAF, 0x78), { L"Scaling", L"Picture", L"Output" } },
    { L"\u2261", L"SYSTEM",  RGB(0x90, 0x90, 0x90), { L"App" } },
};
constexpr int kSysGroupCount = 5;

RECT g_rowArea;   // rows region inside the System content

struct LayoutEntry { bool header; const wchar_t* text; size_t idx; int y; int h; };
std::vector<LayoutEntry> g_layout;
int g_dragRow = -1;   // row currently being slider-dragged

// Rebuild the group's vertical layout: section headers + rows.
void RebuildLayout() {
    g_layout.clear();
    int y = kTabH + S(60);
    const wchar_t* prev = L"";
    for (auto* r : ActiveRows()) {
        if (r->section && wcscmp(r->section, prev) != 0) {
            g_layout.push_back({true, r->section, (size_t)-1, y, S(26)});
            y += S(26);
            prev = r->section;
        }
        g_layout.push_back({false, nullptr, (size_t)(r - g_rows.data()), y, kSysRowH});
        y += kSysRowH;
    }
    g_rowArea = {kRailW, kTabH + S(60), kRightW, y};
}

// Returns the REAL g_rows index for a row at client y, or -1.
int RowHit(int y) {
    for (auto& e : g_layout)
        if (!e.header && y >= e.y && y < e.y + e.h) return (int)e.idx;
    return -1;
}

void RebuildLayout();
void PushMlToRenderer();
void PullMlFromRenderer();
void PushHdrToRenderer();
void PullHdrFromRenderer();
void PushOutToRenderer();
void PullOutFromRenderer();
void FmtNum(float v, wchar_t* b, size_t n);

// Horizontal slider band for a slider row at layout entry e (client coords).
RECT SliderBand(const LayoutEntry& e, int panelW, const Row& r) {
    RECT b;
    b.left = kRailW + S(150) + (r.hasUncheck ? S(28) : S(4));
    b.right = panelW - kPad - S(58);
    b.top = e.y + kSysRowH * 2 / 5;
    b.bottom = e.y + kSysRowH * 3 / 5;
    return b;
}

// The per-control enable checkbox (left of the slider band).
RECT CheckboxBand(const LayoutEntry& e, int panelW, const Row&) {
    RECT b;
    b.left = kRailW + S(150) + S(2);
    b.top = e.y + (kSysRowH - S(18)) / 2;
    b.right = b.left + S(18);
    b.bottom = b.top + S(18);
    return b;
}

void ApplyRow(int i) {
    if (i < 0 || i >= (int)g_rows.size()) return;
    Row& r = g_rows[i];
    switch (r.type) {
    case RowType::Toggle: r.on = !r.on; break;
    case RowType::Cycle:  r.opt = (r.opt + 1) % (int)r.options.size(); break;
    case RowType::Slider:
        break;  // value set by hit-test before ApplyRow for sliders
    }
    if (strcmp(r.key, "zion.enabled") == 0) {
        g_mlMasterEnable = r.on;
        UpdateGates();   // master off → every Zion control locks
    }
    g_lastAppliedRow = i;
    // Live-apply stub: prints the setting key; MPCVR binding comes next.
    std::wstring v;
    if (r.type == RowType::Toggle) v = r.on ? L"on" : L"off";
    else if (r.type == RowType::Cycle) v = r.options[r.opt];
    else { wchar_t buf[32]; FmtNum(r.val, buf, 32); v = buf; }
    wchar_t keyBuf[64];
    MultiByteToWideChar(CP_ACP, 0, r.key, -1, keyBuf, 64);
    std::wcout << L"[SYS] " << keyBuf << L" = " << v
               << (r.live ? L" (live)" : L" (next-start)") << L"\n";
    if (strncmp(r.key, "zion.", 5) == 0) PushMlToRenderer();
    if (strncmp(r.key, "hdr.", 4) == 0) PushHdrToRenderer();
    if (strncmp(r.key, "out.", 4) == 0 || strcmp(r.key, "sys.trayIcon") == 0) PushOutToRenderer();
    // On a paused frame, master/structural toggles don't re-render inside
    // SetSettings (pipeline is mid-rebuild). Nudge one frame so the edit shows
    // on the still (a ~1-frame seek is imperceptible).
    if (g_player) {
        MpcPlayer::Snapshot sn;
        if (SUCCEEDED(g_player->GetSnapshot(sn)) && sn.state == MpcPlayer::State::Paused) {
            g_player->Seek(sn.position);
        }
    }
}

// ── live bridge: rows ⇄ MPCVR (via MpcPlayer::MlSettings) ─────────────────────
void PushMlToRenderer();
void PullMlFromRenderer();

int RowByKey(const char* key) {
    for (size_t i = 0; i < g_rows.size(); ++i)
        if (strcmp(g_rows[i].key, key) == 0) return (int)i;
    return -1;
}
float RowVal(const char* key) { int i = RowByKey(key); return i >= 0 ? g_rows[i].val : 0.0f; }
bool RowOn(const char* key)  { int i = RowByKey(key); return i >= 0 ? g_rows[i].on : false; }
int RowOpt(const char* key)  { int i = RowByKey(key); return i >= 0 ? g_rows[i].opt : 0; }
bool RowFlag(const char* key) { int i = RowByKey(key); return i >= 0 ? g_rows[i].enabledFlag : true; }

MpcPlayer::MlSettings BuildMlFromRows() {
    MpcPlayer::MlSettings m;
    const int toneOpt = RowOpt("zion.toneMode");   // 0 Auto, 1 Manual, 2 Off
    const int chrOpt  = RowOpt("zion.chromaMode");
    const int detOpt  = RowOpt("zion.detailMode");
    m.enable = RowOn("zion.enabled");
    // Signed-off mapping: the master mode is driven ONLY by the Tone-curve
    // section (MPCVR has a single iMLMode; chroma/detail are subfeature gates).
    m.mode = (toneOpt == 1) ? 1 : (toneOpt == 0 ? 2 : 0);   // Manual / Auto / Disable
    const bool toneOn = toneOpt != 2, chrOn = chrOpt != 2, detOn = detOpt != 2;
    m.toneCurveEnabled = toneOn;   // the dialog's "Tone curve" checkbox
    m.gammaEnabled     = toneOn && RowFlag("zion.gamma");
    m.shadowEnabled    = toneOn && RowFlag("zion.shadow");
    m.highlightEnabled = toneOn && RowFlag("zion.highlight");
    m.gamma = RowVal("zion.gamma");
    m.shadow = RowVal("zion.shadow");
    m.highlight = RowVal("zion.highlight");
    m.chromaEnabled = chrOn;
    m.huntEnabled      = chrOn && RowFlag("zion.hunt");
    m.chNeutralEnabled = chrOn && RowFlag("zion.chN");
    m.chFireEnabled    = chrOn && RowFlag("zion.chF");
    m.chKneeEnabled    = chrOn;   // parameters for Ch-N/Ch-F — always on
    m.chSkinEnabled    = chrOn;
    m.hunt      = RowVal("zion.hunt");
    m.chNeutral = RowVal("zion.chN");
    m.chFire    = RowVal("zion.chF");
    m.chKnee    = RowVal("zion.knee");
    m.chSkin    = RowVal("zion.skin");
    m.crEnabled  = detOn && RowFlag("zion.cr");
    m.radiEnabled = detOn && (RowFlag("zion.resKnee") || RowFlag("zion.resStr"));
    m.crStrength  = RowVal("zion.cr");
    m.radiKnee    = RowVal("zion.resKnee");
    m.radiStrength = RowVal("zion.resStr");
    m.debugLog  = RowOn("zion.debugFrameLog");
    m.debugCopy = RowOn("zion.debugCopyShaders");
    return m;
}

void ApplyMlToRows(const MpcPlayer::MlSettings& m) {
    for (auto& r : g_rows) {
        if      (!strcmp(r.key, "zion.enabled"))   { r.on = m.enable; }
        else if (!strcmp(r.key, "zion.toneCurve")) { r.on = m.toneCurveEnabled; }
        else if (!strcmp(r.key, "zion.toneMode"))  { r.opt = m.toneCurveEnabled ? (m.mode == 1 ? 1 : 0) : 2; }
        else if (!strcmp(r.key, "zion.gamma"))     { r.val = m.gamma; r.enabledFlag = m.gammaEnabled; }
        else if (!strcmp(r.key, "zion.shadow"))    { r.val = m.shadow; r.enabledFlag = m.shadowEnabled; }
        else if (!strcmp(r.key, "zion.highlight")) { r.val = m.highlight; r.enabledFlag = m.highlightEnabled; }
        else if (!strcmp(r.key, "zion.chromaMode")) { r.opt = m.chromaEnabled ? (m.mode == 1 ? 1 : 0) : 2; }
        else if (!strcmp(r.key, "zion.hunt"))      { r.val = m.hunt; r.enabledFlag = m.huntEnabled; }
        else if (!strcmp(r.key, "zion.chN"))       { r.val = m.chNeutral; r.enabledFlag = m.chNeutralEnabled; }
        else if (!strcmp(r.key, "zion.chF"))       { r.val = m.chFire; r.enabledFlag = m.chFireEnabled; }
        else if (!strcmp(r.key, "zion.knee"))      { r.val = m.chKnee; r.enabledFlag = true; }
        else if (!strcmp(r.key, "zion.skin"))      { r.val = m.chSkin; r.enabledFlag = true; }
        else if (!strcmp(r.key, "zion.detailMode")) { r.opt = (m.crEnabled || m.radiEnabled) ? (m.mode == 1 ? 1 : 0) : 2; }
        else if (!strcmp(r.key, "zion.cr"))        { r.val = m.crStrength; r.enabledFlag = m.crEnabled; }
        else if (!strcmp(r.key, "zion.resKnee"))   { r.val = m.radiKnee; r.enabledFlag = m.radiEnabled; }
        else if (!strcmp(r.key, "zion.resStr"))    { r.val = m.radiStrength; r.enabledFlag = m.radiEnabled; }
        else if (!strcmp(r.key, "zion.debugFrameLog")) { r.on = m.debugLog; }
        else if (!strcmp(r.key, "zion.debugCopyShaders")) { r.on = m.debugCopy; }
    }
    g_mlMasterEnable = m.enable;
    UpdateGates();
}

void PushMlToRenderer() {
    if (!g_player) return;
    const HRESULT hr = g_player->SetMlSettings(BuildMlFromRows());
    std::cout << "[BRIDGE] SetMlSettings hr=0x" << std::hex << (unsigned long)hr << std::dec << "\n";
    MpcPlayer::MlSettings back;
    if (SUCCEEDED(g_player->GetMlSettings(back)))
        std::cout << "[BRIDGE] echo enable=" << (back.enable ? 1 : 0)
                  << " mode=" << back.mode
                  << " gamma=" << back.gamma
                  << " shadow=" << back.shadow
                  << " highlight=" << back.highlight << "\n";
}

std::wstring g_mlStats;   // live ML internals from MPCVR (polled, shown in the left pane)

void PullMlFromRenderer() {
    MpcPlayer::MlSettings m;
    if (g_player && SUCCEEDED(g_player->GetMlSettings(m))) {
        ApplyMlToRows(m);
        RebuildLayout();
        InvalidateRect(g_hRight, nullptr, FALSE);
    }
}

// ── HDR bridge (independent of the ML grade) ──────────────────────────────
void PushHdrToRenderer();
void PullHdrFromRenderer();

MpcPlayer::HdrSettings BuildHdrFromRows() {
    MpcPlayer::HdrSettings h;
    h.preferDoVi    = RowOn("hdr.preferDoVi");
    h.convertToSdr  = RowOn("hdr.convertToSdr");
    h.sdrDisplayNits = (int)RowVal("hdr.sdrNits");
    h.toggleDisplay = RowOpt("hdr.toggleDisplay");
    h.displayMaxNits = (int)RowVal("hdr.maxNits");
    h.osdBrightness = (int)RowVal("hdr.osdBright");
    return h;
}

void ApplyHdrToRows(const MpcPlayer::HdrSettings& h) {
    for (auto& r : g_rows) {
        if      (!strcmp(r.key, "hdr.preferDoVi"))    { r.on = h.preferDoVi; }
        else if (!strcmp(r.key, "hdr.convertToSdr"))  { r.on = h.convertToSdr; }
        else if (!strcmp(r.key, "hdr.sdrNits"))       { r.val = (float)h.sdrDisplayNits; }
        else if (!strcmp(r.key, "hdr.toggleDisplay")) { r.opt = h.toggleDisplay; }
        else if (!strcmp(r.key, "hdr.maxNits"))       { r.val = (float)h.displayMaxNits; }
        else if (!strcmp(r.key, "hdr.osdBright"))     { r.val = (float)h.osdBrightness; }
    }
}

void PushHdrToRenderer() {
    if (g_player) g_player->SetHdrSettings(BuildHdrFromRows());
}

void PullHdrFromRenderer() {
    MpcPlayer::HdrSettings h;
    if (g_player && SUCCEEDED(g_player->GetHdrSettings(h))) {
        ApplyHdrToRows(h);
        RebuildLayout();
        InvalidateRect(g_hRight, nullptr, FALSE);
    }
}

// ── OUTPUT / SYSTEM bridge (independent settings) ─────────────────────────
void PushOutToRenderer();
void PullOutFromRenderer();

const int kTexVals[] = {0, 8, 10, 16};  // TEXFMT_AUTOINT/8INT/10INT/16FLOAT

MpcPlayer::OutSettings BuildOutFromRows() {
    MpcPlayer::OutSettings o;
    o.useD3D11 = RowOn("out.useD3D11");
    const int tf = RowOpt("out.texFormat");
    o.texFormat = (tf >= 0 && tf < 4) ? kTexVals[tf] : 0;
    o.vpNV12 = RowOn("out.vpNV12"); o.vpP01x = RowOn("out.vpP01x");
    o.vpYUY2 = RowOn("out.vpYUY2"); o.vpOther = RowOn("out.vpOther");
    o.deinterlace = RowOpt("out.deinterlace");
    o.deintDouble = RowOn("out.deintDouble"); o.deintBlend = RowOn("out.deintBlend");
    o.shaderVPScaling = RowOn("out.shaderVP");
    o.superRes = RowOpt("out.superRes"); o.rtxVideoHdr = RowOn("out.rtxVideoHdr");
    o.chromaScaling = RowOpt("out.chromaScaling");
    o.upscaling = RowOpt("out.upscaling"); o.downscaling = RowOpt("out.downscaling");
    o.interpolate50 = RowOn("out.interpolate50"); o.useDither = RowOn("out.useDither");
    o.swapEffect = RowOpt("out.swapEffect");
    o.exclusiveFS = RowOn("out.exclusiveFS"); o.vBlank = RowOn("out.vBlank");
    o.adjustPresent = RowOn("out.adjustPresent"); o.reinitDisplay = RowOn("out.reinitDisplay");
    o.showStats = RowOn("out.showStats");
    o.trayIcon = RowOn("sys.trayIcon");
    return o;
}

void ApplyOutToRows(const MpcPlayer::OutSettings& o) {
    for (auto& r : g_rows) {
        if      (!strcmp(r.key, "out.useD3D11"))    { r.on = o.useD3D11; }
        else if (!strcmp(r.key, "out.texFormat"))   { r.opt = 0; for (int i = 0; i < 4; ++i) if (kTexVals[i] == o.texFormat) r.opt = i; }
        else if (!strcmp(r.key, "out.vpNV12"))      { r.on = o.vpNV12; }
        else if (!strcmp(r.key, "out.vpP01x"))      { r.on = o.vpP01x; }
        else if (!strcmp(r.key, "out.vpYUY2"))      { r.on = o.vpYUY2; }
        else if (!strcmp(r.key, "out.vpOther"))     { r.on = o.vpOther; }
        else if (!strcmp(r.key, "out.deinterlace")) { r.opt = o.deinterlace; }
        else if (!strcmp(r.key, "out.deintDouble")) { r.on = o.deintDouble; }
        else if (!strcmp(r.key, "out.deintBlend"))  { r.on = o.deintBlend; }
        else if (!strcmp(r.key, "out.shaderVP"))    { r.on = o.shaderVPScaling; }
        else if (!strcmp(r.key, "out.superRes"))    { r.opt = o.superRes; }
        else if (!strcmp(r.key, "out.rtxVideoHdr")) { r.on = o.rtxVideoHdr; }
        else if (!strcmp(r.key, "out.chromaScaling")) { r.opt = o.chromaScaling; }
        else if (!strcmp(r.key, "out.upscaling"))   { r.opt = o.upscaling; }
        else if (!strcmp(r.key, "out.downscaling")) { r.opt = o.downscaling; }
        else if (!strcmp(r.key, "out.interpolate50")) { r.on = o.interpolate50; }
        else if (!strcmp(r.key, "out.useDither"))   { r.on = o.useDither; }
        else if (!strcmp(r.key, "out.swapEffect"))  { r.opt = o.swapEffect; }
        else if (!strcmp(r.key, "out.exclusiveFS")) { r.on = o.exclusiveFS; }
        else if (!strcmp(r.key, "out.vBlank"))      { r.on = o.vBlank; }
        else if (!strcmp(r.key, "out.adjustPresent")) { r.on = o.adjustPresent; }
        else if (!strcmp(r.key, "out.reinitDisplay")) { r.on = o.reinitDisplay; }
        else if (!strcmp(r.key, "out.showStats"))   { r.on = o.showStats; }
        else if (!strcmp(r.key, "sys.trayIcon"))    { r.on = o.trayIcon; }
    }
}

void PushOutToRenderer() {
    if (g_player) g_player->SetOutSettings(BuildOutFromRows());
}

void PullOutFromRenderer() {
    MpcPlayer::OutSettings o;
    if (g_player && SUCCEEDED(g_player->GetOutSettings(o))) {
        ApplyOutToRows(o);
        RebuildLayout();
        InvalidateRect(g_hRight, nullptr, FALSE);
    }
}

// ── Audio control (bottom bar) ────────────────────────────────────────────
bool g_audioOn = true;
RECT g_audBtn = {};
RECT g_timeline = {};
bool g_dragTime = false;
LONGLONG g_dragDur = 0, g_dragTarget = 0;

void ToggleAudio() {
    if (!g_player) return;
    g_audioOn = !g_audioOn;
    g_player->SetAudioEnabled(g_audioOn);
    InvalidateRect(g_hBottom, nullptr, FALSE);
}

// Compact numeric readout: whole numbers print without decimals (10000, 400).
void FmtNum(float v, wchar_t* b, size_t n) {
    if (fabsf(v - roundf(v)) < 0.005f) swprintf_s(b, n, L"%g", v);
    else swprintf_s(b, n, L"%.2f", v);
}

void PaintSysRow(HDC dc, int y, int w, const Row& r) {
    // label (left column of the content pane; sliders need more room)
    const bool isSlider = r.type == RowType::Slider;
    RECT lb = {kRailW + kPad + S(6), y,
               isSlider ? kRailW + S(150) - S(8) : w - S(150), y + kSysRowH};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fLabel);
    SetTextColor(dc, r.disabled ? COL_LO : (r.live ? COL_TEXT : COL_MID));
    DrawTextW(dc, r.label, -1, &lb, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, fo);

    if (isSlider) {
        if (r.hasUncheck) {
            // per-control enable checkbox (mirrors the MPCVR dialog's per-slider box)
            RECT cb = {kRailW + S(150) + S(2), y + (kSysRowH - S(18)) / 2,
                       kRailW + S(150) + S(2) + S(18), y + (kSysRowH - S(18)) / 2 + S(18)};
            HBRUSH cbb = CreateSolidBrush(r.disabled ? COL_LO : (r.enabledFlag ? COL_ACCENT : RGB(0x24, 0x24, 0x28)));
            FillRect(dc, &cb, cbb); DeleteObject(cbb);
            HBRUSH cbr = CreateSolidBrush(r.disabled ? COL_LO : (r.enabledFlag ? COL_ACCENT2 : COL_BORDER));
            FrameRect(dc, &cb, cbr); DeleteObject(cbr);
        }

        const bool off = r.disabled || !r.enabledFlag;
        const int box = r.hasUncheck ? S(28) : S(4);
        RECT band = {kRailW + S(150) + box, y + kSysRowH * 2 / 5, w - kPad - S(58), y + kSysRowH * 3 / 5};
        HBRUSH line = CreateSolidBrush(off ? COL_LO : RGB(0xF2, 0xF2, 0xF2));
        FillRect(dc, &band, line); DeleteObject(line);
        const int span = band.right - band.left;
        int frac = 0;
        if (r.max > r.min && span > 0)
            frac = (int)((r.val - r.min) / (r.max - r.min) * (float)span);
        if (frac > 0) {
            RECT fill = band; fill.right = band.left + frac;
            HBRUSH a = CreateSolidBrush(off ? COL_LO : COL_ACCENT); FillRect(dc, &fill, a); DeleteObject(a);
        }
        const int cx = band.left + frac;
        RECT th = {cx - S(6), band.top - S(4), cx + S(6), band.bottom + S(4)};
        HBRUSH t = CreateSolidBrush(off ? COL_LO : COL_ACCENT2);
        FillRect(dc, &th, t); DeleteObject(t);

        wchar_t mn[16], mx[16], vb[16];
        FmtNum(r.min, mn, 16);
        FmtNum(r.max, mx, 16);
        FmtNum(r.val, vb, 16);
        fo = (HFONT)SelectObject(dc, g_fStatus);
        SetTextColor(dc, COL_MID);
        RECT ra = {band.left, band.bottom + S(3), band.left + S(40), band.bottom + S(19)};
        RECT rb = {band.right - S(40), band.bottom + S(3), band.right, band.bottom + S(19)};
        DrawTextW(dc, mn, -1, &ra, DT_LEFT | DT_TOP | DT_SINGLELINE);
        DrawTextW(dc, mx, -1, &rb, DT_RIGHT | DT_TOP | DT_SINGLELINE);
        SelectObject(dc, fo);
        fo = (HFONT)SelectObject(dc, g_fValue);
        SetTextColor(dc, off ? COL_LO : COL_TEXT);
        RECT vr = {w - S(58), y, w - kPad, y + kSysRowH};
        DrawTextW(dc, vb, -1, &vr, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        return;
    }

    RECT ct = {w - S(148), y, w - kPad, y + kSysRowH};  // control column
    switch (r.type) {
    case RowType::Toggle: {
        RECT sw = {ct.left, y + (kSysRowH - S(22)) / 2, ct.left + S(46), y + (kSysRowH - S(22)) / 2 + S(22)};
        HBRUSH bg = CreateSolidBrush(r.disabled ? COL_LO : (r.on ? COL_ACCENT : RGB(0x2A, 0x2A, 0x2E)));
        FillRect(dc, &sw, bg); DeleteObject(bg);
        HBRUSH br = CreateSolidBrush(r.disabled ? COL_LO : (r.on ? COL_ACCENT2 : COL_BORDER));
        FrameRect(dc, &sw, br); DeleteObject(br);
        fo = (HFONT)SelectObject(dc, g_fStatus);
        SetTextColor(dc, r.disabled ? COL_MID : (r.on ? RGB(0, 0, 0) : COL_MID));
        DrawTextW(dc, r.on ? L"ON" : L"OFF", -1, &sw, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        break;
    }
    case RowType::Cycle: {
        wchar_t buf[64];
        swprintf_s(buf, L"\u3008  %s  \u3009", r.options[r.opt]);
        fo = (HFONT)SelectObject(dc, g_fValue);
        SetTextColor(dc, r.disabled ? COL_LO : COL_ACCENT2);
        RECT tp = {ct.left, y, ct.right, y + kSysRowH};
        DrawTextW(dc, buf, -1, &tp, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        break;
    }
    case RowType::Slider:
        break;  // handled above (early return) — never reaches here
    }
}

// Right-panel tab + System icon rail + rows.
// ── Playback sheet: streams / audio device / hardware ──────────────────────
enum class PlayRowKind { Video = 0, Audio = 1, Subtitle = 2, AudioDevice = 3 };
struct PlayRow { PlayRowKind kind; int index; std::wstring label; std::wstring id; bool active; RECT rc; };
std::vector<PlayRow> g_playRows;
std::wstring g_hwLine;
std::wstring g_selAudioDeviceId, g_selAudioDeviceName;

void RefreshPlaybackInfo() {
    g_playRows.clear();
    if (!g_player) return;
    std::vector<MpcPlayer::TrackInfo> tracks;
    if (SUCCEEDED(g_player->GetTracks(tracks))) {
        int aIdx = 0, sIdx = 0;
        for (auto& t : tracks) {
            PlayRowKind k = (t.kind == MpcPlayer::TrackKind::Video) ? PlayRowKind::Video
                            : (t.kind == MpcPlayer::TrackKind::Audio) ? PlayRowKind::Audio
                            : PlayRowKind::Subtitle;
            PlayRow r;
            r.kind = k;
            r.label = t.name;
            r.active = t.active;
            if (k == PlayRowKind::Video) r.index = 0;
            else if (k == PlayRowKind::Audio) r.index = aIdx++;
            else r.index = sIdx++;
            g_playRows.push_back(r);
        }
    }
    std::vector<MpcPlayer::AudioDeviceInfo> devs;
    if (SUCCEEDED(g_player->GetAudioDevices(devs))) {
        for (auto& d : devs) {
            PlayRow r; r.kind = PlayRowKind::AudioDevice; r.index = 0;
            r.label = d.name + (d.isDefault ? L"  (default)" : L"");
            r.id = d.id;
            r.active = !g_selAudioDeviceId.empty() ? (d.id == g_selAudioDeviceId) : d.isDefault;
            g_playRows.push_back(r);
        }
    }
    if (g_hwLine.empty() && g_player) {
        std::wstring proc;
        if (SUCCEEDED(g_player->GetProcessorInfo(proc))) {
            size_t at = proc.find(L"Graphics adapter");
            if (at != std::wstring::npos) {
                std::wstring line = proc.substr(at);
                size_t nl = line.find(L'\n');
                if (nl != std::wstring::npos) line = line.substr(0, nl);
                g_hwLine = line;
            }
        }
    }
}

// -- Audio-output rows (Playback tab: PCM / Bitstream + per-codec toggles) --
struct AudioOutRow {
    enum class Kind { Mode, Toggle };
    Kind kind;
    const wchar_t* label;
    RECT rc;
};
std::vector<AudioOutRow> g_audioOutRows;

void PaintPlaySheet(HDC dc, int w, int h) {
    // Background below the tab bar only — the Playback|System tabs are drawn
    // first by PaintRight and must stay visible over this sheet.
    RECT bg = {0, kTabH, w, h};
    HBRUSH b = CreateSolidBrush(COL_PANEL); FillRect(dc, &bg, b); DeleteObject(b);

    int y = kTabH + S(12);
    bool needHw = false;
    RECT headerRect;
    auto Section = [&](const wchar_t* title) {
        RECT hr = {kPad, y, w - kPad, y + S(20)};
        SetBkMode(dc, TRANSPARENT);
        HFONT fo = (HFONT)SelectObject(dc, g_fSection);
        SetTextColor(dc, COL_MID);
        DrawTextW(dc, title, -1, &hr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        RECT ds = {kPad, y + S(22), w - kPad, y + S(23)};
        HBRUSH sb = CreateSolidBrush(COL_BORDER); FillRect(dc, &ds, sb); DeleteObject(sb);
        y += S(30);
    };

    Section(L"STREAMS");
    for (auto& r : g_playRows) {
        if (r.kind == PlayRowKind::AudioDevice) { Section(L"AUDIO DEVICE"); needHw = true; }
        RECT rr = {kPad, y, w - kPad, y + S(24)};
        SetBkMode(dc, TRANSPARENT);
        HFONT fo = (HFONT)SelectObject(dc, r.active ? g_fValue : g_fLabel);
        SetTextColor(dc, r.active ? COL_ACCENT2 : COL_TEXT);
        std::wstring kind;
        switch (r.kind) {
        case PlayRowKind::Video: kind = L"V  "; break;
        case PlayRowKind::Audio: kind = L"A  "; break;
        case PlayRowKind::Subtitle: kind = L"S  "; break;
        case PlayRowKind::AudioDevice: kind = L"⌁ "; break;
        }
        std::wstring full = kind + r.label;
        RECT tr = {kPad + S(6), y, w - kPad, y + S(24)};
        DrawTextW(dc, full.c_str(), -1, &tr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        r.rc = rr;
        y += S(26);
    }
    if (needHw) Section(L"HARDWARE");
    if (!g_hwLine.empty()) {
        RECT rr = {kPad, y, w - kPad, y + S(24)};
        SetBkMode(dc, TRANSPARENT);
        HFONT fo = (HFONT)SelectObject(dc, g_fStatus);
        SetTextColor(dc, COL_MID);
        DrawTextW(dc, g_hwLine.c_str(), -1, &rr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
        y += S(28);
    }

    // OUTPUT: HD audio bitstream — PCM/Bitstream cycle + per-codec toggles + DTS-HD framing
    if (g_player) {
        Section(L"OUTPUT");
        MpcPlayer::AudioMode mode = MpcPlayer::AudioMode::PCM;
        MpcPlayer::BitstreamConfig bs{};
        g_player->GetAudioMode(mode);
        g_player->GetBitstreamConfig(bs);
        g_audioOutRows.clear();

        auto Toggle = [&](const wchar_t* label, bool on) {
            RECT rr = {kPad, y, w - kPad, y + S(28)};
            SetBkMode(dc, TRANSPARENT);
            HFONT fo = (HFONT)SelectObject(dc, g_fLabel);
            SetTextColor(dc, COL_TEXT);
            RECT lb = {kPad + S(6), y, w - S(70), y + S(28)};
            DrawTextW(dc, label, -1, &lb, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, fo);
            RECT sw = {w - kPad - S(46), y + S(4), w - kPad, y + S(26)};
            HBRUSH bgb = CreateSolidBrush(on ? COL_ACCENT : RGB(0x2A, 0x2A, 0x2E));
            FillRect(dc, &sw, bgb); DeleteObject(bgb);
            HBRUSH br = CreateSolidBrush(on ? COL_ACCENT2 : COL_BORDER);
            FrameRect(dc, &sw, br); DeleteObject(br);
            fo = (HFONT)SelectObject(dc, g_fStatus);
            SetTextColor(dc, on ? RGB(0, 0, 0) : COL_MID);
            DrawTextW(dc, on ? L"ON" : L"OFF", -1, &sw, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, fo);
            g_audioOutRows.push_back({AudioOutRow::Kind::Toggle, label, rr});
            y += S(30);
        };

        {
            // Mode cycle
            RECT rr = {kPad, y, w - kPad, y + S(28)};
            SetBkMode(dc, TRANSPARENT);
            HFONT fo = (HFONT)SelectObject(dc, g_fLabel);
            SetTextColor(dc, COL_TEXT);
            RECT lb = {kPad + S(6), y, w - S(150), y + S(28)};
            DrawTextW(dc, L"Mode", -1, &lb, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, fo);
            fo = (HFONT)SelectObject(dc, g_fValue);
            SetTextColor(dc, COL_ACCENT2);
            RECT cr = {w - S(148), y, w - kPad, y + S(28)};
            const wchar_t* mtxt = (mode == MpcPlayer::AudioMode::Bitstream) ? L"\u3008  Bitstream  \u3009" : L"\u3008  PCM  \u3009";
            DrawTextW(dc, mtxt, -1, &cr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, fo);
            g_audioOutRows.push_back({AudioOutRow::Kind::Mode, L"Mode", rr});
            y += S(32);
        }
        Toggle(L"AC-3",           bs.ac3);
        Toggle(L"E-AC-3",         bs.eac3);
        Toggle(L"TrueHD",         bs.trueHd);
        Toggle(L"DTS",            bs.dts);
        Toggle(L"DTS-HD",         bs.dtsHd);
        Toggle(L"DTS-HD framing", bs.dtsHdFraming);
    }
}

void PaintRight(HDC dc, int w, int h) {
    RECT r = {0, 0, w, h};
    HBRUSH bg = CreateSolidBrush(COL_PANEL); FillRect(dc, &r, bg); DeleteObject(bg);

    // tab bar
    RECT tabL = {0, 0, w / 2, kTabH};
    RECT tabR = {w / 2, 0, w, kTabH};
    (void)h;
    DrawButton(dc, tabL, L"\u25B6  Playback", g_lastMouse.y < kTabH && g_lastMouse.x < w / 2, g_railTab == RailTab::Playback);
    DrawButton(dc, tabR, L"\u2699  System", g_lastMouse.y < kTabH && g_lastMouse.x >= w / 2, g_railTab == RailTab::System);

    if (g_railTab == RailTab::Playback) {
        PaintPlaySheet(dc, w, h);   // streams / audio device / hardware
        return;
    }

    // SYSTEM tab: icon rail (snug fixed-height tabs, top-aligned)
    const int railTop = kTabH;
    for (int i = 0; i < kSysGroupCount; ++i) {
        const int top = railTop + i * kIconStep;
        RECT g = {0, top, kRailW, top + kIconH};
        HBRUSH gb = CreateSolidBrush(g_sysGroup == i ? RGB(0x1E, 0x1E, 0x20) : COL_PANEL);
        FillRect(dc, &g, gb); DeleteObject(gb);
        if (g_sysGroup == i) {
            RECT bar = {0, g.top, 3, g.bottom};
            HBRUSH ab = CreateSolidBrush(COL_ACCENT); FillRect(dc, &bar, ab); DeleteObject(ab);
        }
        SetBkMode(dc, TRANSPARENT);
        HFONT fo = (HFONT)SelectObject(dc, g_fIcon);
        SetTextColor(dc, kSysGroups[i].col);
        RECT ic = {0, g.top + S(6), kRailW, g.top + S(38)};
        DrawTextW(dc, kSysGroups[i].icon, -1, &ic, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, g_fSection);
        RECT tg = {0, g.top + S(42), kRailW, g.bottom - S(2)};
        SetTextColor(dc, g_sysGroup == i ? COL_TEXT : COL_MID);
        DrawTextW(dc, kSysGroups[i].label, -1, &tg, DT_CENTER);
        SelectObject(dc, fo);
    }

    // Content: category header + rows
    int x0 = kRailW;
    RECT catR = {x0 + kPad, kTabH + S(8), w - kPad, kTabH + S(8) + kCatH};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fSection);
    SetTextColor(dc, COL_MID);
    std::wstring cats;
    for (auto& c : kSysGroups[g_sysGroup].cats) { if (!cats.empty()) cats += L"  \u00B7  "; cats += c; }
    DrawTextW(dc, cats.c_str(), -1, &catR, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, fo);

    if (g_lastAppliedRow >= 0) {
        wchar_t applied[128];
        swprintf_s(applied, L"applied: %hs", g_rows[g_lastAppliedRow].key);
        RECT ar = {x0 + kPad, kTabH + S(34), w - kPad, kTabH + S(54)};
        fo = (HFONT)SelectObject(dc, g_fStatus);
        SetTextColor(dc, COL_OK);
        DrawTextW(dc, applied, -1, &ar, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, fo);
    }

    RebuildLayout();
    for (auto& e : g_layout) {
        if (e.header) {
            RECT hr = {x0 + kPad, e.y, w - kPad, e.y + S(18)};
            SetBkMode(dc, TRANSPARENT);
            HFONT fo = (HFONT)SelectObject(dc, g_fSection);
            SetTextColor(dc, COL_MID);
            DrawTextW(dc, e.text, -1, &hr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, fo);
            RECT ds = {x0 + kPad, e.y + S(20), w - kPad, e.y + S(21)};
            HBRUSH sb = CreateSolidBrush(COL_BORDER); FillRect(dc, &ds, sb); DeleteObject(sb);
        } else {
            PaintSysRow(dc, e.y, w, g_rows[e.idx]);
        }
    }
    RECT sep = {x0 + kPad, g_rowArea.top - 2, w - kPad, g_rowArea.top - 1};
    HBRUSH sb = CreateSolidBrush(COL_BORDER); FillRect(dc, &sep, sb); DeleteObject(sb);
}

void PaintLeft(HDC dc, int w, int h) {
    RECT r = {0, 0, w, h};
    HBRUSH bg = CreateSolidBrush(COL_PANEL); FillRect(dc, &r, bg); DeleteObject(bg);

    RECT hd = {kPad, S(14), w - kPad, S(44)};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fHeader);
    SetTextColor(dc, COL_OK);
    DrawTextW(dc, L"\u25CF", -1, &hd, DT_LEFT);
    RECT tt = {kPad + S(18), S(14), w - kPad, S(44)};
    SetTextColor(dc, COL_TEXT);
    DrawTextW(dc, L"LIVE", -1, &tt, DT_LEFT | DT_VCENTER);
    SelectObject(dc, fo);

    int y = S(60);
    MpcPlayer::Snapshot sn{};
    if (g_player) g_player->GetSnapshot(sn);
    const bool playing = sn.state == MpcPlayer::State::Playing;

    y = PaintSection(dc, y, w, L"PERFORMANCE");
    wchar_t buf[160];
    const wchar_t* st = L"idle";
    switch (sn.state) {
    case MpcPlayer::State::Idle: st = L"idle"; break;
    case MpcPlayer::State::Opening: st = L"opening"; break;
    case MpcPlayer::State::Paused: st = L"paused"; break;
    case MpcPlayer::State::Playing: st = L"playing"; break;
    case MpcPlayer::State::Stopped: st = L"stopped"; break;
    case MpcPlayer::State::Error: st = L"error"; break;
    }
    PaintRow(dc, y, 110, L"State", st, playing ? COL_OK : COL_TEXT); y += kRowH;
    swprintf_s(buf, L"%lld", sn.position);
    PaintRow(dc, y, 110, L"Position", buf, COL_TEXT); y += kRowH;
    swprintf_s(buf, L"%lld", sn.duration);
    PaintRow(dc, y, 110, L"Duration", buf, COL_TEXT); y += kRowH + 6;

    y = PaintSection(dc, y, w, L"VIDEO SOURCE");
    PaintRow(dc, y, 110, L"Resolution", L"\u2014", COL_LO); y += kRowH;
    PaintRow(dc, y, 110, L"Pixel format", L"\u2014", COL_LO); y += kRowH;
    PaintRow(dc, y, 110, L"Codec", L"\u2014", COL_LO); y += kRowH;
    PaintRow(dc, y, 110, L"HDR format", L"\u2014", COL_LO); y += kRowH + 6;

    y = PaintSection(dc, y, w, L"CAPTURE INPUT");
    PaintRow(dc, y, 110, L"Device", L"\u2014 S4", COL_LO); y += kRowH;
    PaintRow(dc, y, 110, L"Signal", L"\u2014 S4", COL_LO); y += kRowH + 6;

    y = PaintSection(dc, y, w, L"ZION ML");
    if (!g_mlStats.empty()) {
        HFONT fz = (HFONT)SelectObject(dc, g_fStatus);
        SetTextColor(dc, COL_MID);
        RECT zr = {kPad, y + S(4), w - kPad, h - kPad};
        DrawTextW(dc, g_mlStats.c_str(), -1, &zr, DT_LEFT | DT_TOP | DT_WORDBREAK);
        SelectObject(dc, fz);
    }
}

void PaintBottom(HDC dc, int w, int h) {
    RECT r = {0, 0, w, h};
    HBRUSH bg = CreateSolidBrush(COL_PANEL); FillRect(dc, &r, bg); DeleteObject(bg);

    // Seekable timeline (drag to scrub, release to seek).
    RECT tl = {kPad, S(12), w - kPad, S(24)};
    HBRUSH tb = CreateSolidBrush(COL_BORDER); FillRect(dc, &tl, tb); DeleteObject(tb);
    MpcPlayer::Snapshot sn{};
    LONGLONG dur = 0, pos = 0;
    if (g_player) { g_player->GetSnapshot(sn); dur = sn.duration > 0 ? sn.duration : 0; }
    pos = g_dragTime ? g_dragTarget : sn.position;
    const int tspan = tl.right - tl.left;
    if (dur > 0 && tspan > 0) {
        const int pw = (int)(tspan * (double)pos / dur);
        if (pw > 0) { RECT fill = tl; fill.right = tl.left + pw; HBRUSH at = CreateSolidBrush(COL_ACCENT); FillRect(dc, &fill, at); DeleteObject(at); }
        const int cx = tl.left + pw;
        RECT th = {cx - S(4), tl.top - S(4), cx + S(4), tl.bottom + S(4)};
        HBRUSH t2 = CreateSolidBrush(COL_ACCENT2); FillRect(dc, &th, t2); DeleteObject(t2);
    }
    g_timeline = tl;

    RECT st = {kPad, S(34), w - kPad, S(56)};
    SetBkMode(dc, TRANSPARENT);
    HFONT fo = (HFONT)SelectObject(dc, g_fStatus);
    SetTextColor(dc, COL_MID);
    DrawTextW(dc, L"WATCH \u21C4 EDIT  (Up)  \u00B7  Space play/pause  \u00B7  \u2190/\u2192 seek  \u00B7  O open  \u00B7  A audio  \u00B7  Esc exits", -1, &st, DT_LEFT);
    SelectObject(dc, fo);
    RECT sep = {kPad, S(58), w - kPad, S(59)};
    HBRUSH bb = CreateSolidBrush(COL_BORDER); FillRect(dc, &sep, bb); DeleteObject(bb);

    RECT vp = {kPad, S(72), kPad + S(150), S(72) + kBtnH};
    RECT mp = {kPad + S(160), S(72), kPad + S(310), S(72) + kBtnH};
    RECT aud = {kPad + S(330), S(72), kPad + S(470), S(72) + kBtnH};
    DrawButton(dc, vp, L"VP   \u2014  S4", false, false);
    DrawButton(dc, mp, L"Media", true, true);
    DrawButton(dc, aud, g_audioOn ? L"Audio  ON" : L"Audio  OFF", false, g_audioOn);
    g_audBtn = aud;
}

}  // namespace

// -- window procs -------------------------------------------------------------
namespace {

LRESULT CALLBACK VideoWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
        HBRUSH b = CreateSolidBrush(COL_BG); FillRect(dc, &ps.rcPaint, b); DeleteObject(b);
        EndPaint(h, &ps); return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_SIZE:
        if (g_player) g_player->ResizeVideo();
        return 0;
    case WM_KEYDOWN:
        PostMessageW(g_hwnd, WM_KEYDOWN, w, l);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

void HandleSysClick(const POINT& p, int panelW, int panelH) {
    if (p.y < kTabH) {
        g_railTab = (p.x < panelW / 2) ? RailTab::Playback : RailTab::System;
        return;
    }
    if (p.x < kRailW) {
        int idx = (p.y - kTabH) / kIconStep;
        if (idx >= 0 && idx < kSysGroupCount) {
            g_sysGroup = idx;
            RebuildLayout();
        }
        return;
    }
    const int rowIdx = RowHit(p.y);
    if (rowIdx < 0) return;
    Row& r = g_rows[rowIdx];
    if (r.type == RowType::Slider) {
        for (auto& e : g_layout) {
            if ((int)e.idx == rowIdx) {
                RECT cb = CheckboxBand(e, panelW, r);
                if (r.hasUncheck && !r.disabled && p.x >= cb.left && p.x <= cb.right) {
                    r.enabledFlag = !r.enabledFlag;          // per-control enable
                    g_lastAppliedRow = rowIdx;
                    UpdateGates();
                    PushMlToRenderer();
                    InvalidateRect(g_hRight, nullptr, FALSE);
                    break;
                }
                RECT band = SliderBand(e, panelW, r);
                if (r.adjustable && p.x >= band.left && p.x <= band.right) {
                    const float f = (float)(p.x - band.left) / (band.right - band.left);
                    r.val = r.min + (r.max - r.min) * f;
                    ApplyRow(rowIdx);
                    g_dragRow = rowIdx;
                    SetCapture(g_hRight);
                }
                break;
            }
        }
    } else if (r.type != RowType::Slider) {
        if (r.disabled) return;   // locked by master-off or section mode off
        ApplyRow(rowIdx);
        if (rowIdx == g_toneModeRow || rowIdx == g_chromaModeRow || rowIdx == g_detailModeRow) {
            UpdateGates();
            RebuildLayout();   // mode != Manual snaps + locks the section's sliders
        }
    }
}

void PaintPanel(HDC dc, HWND h, int w, int hh) {
    if (h == g_hLeft) PaintLeft(dc, w, hh);
    else if (h == g_hRight) PaintRight(dc, w, hh);
    else if (h == g_hBottom) PaintBottom(dc, w, hh);
}

// Coarse "what is the cursor over" token, so hover repaints only on change.
int HoverToken(HWND h, const POINT& p) {
    RECT rc; GetClientRect(h, &rc);
    if (h == g_hBottom) {
        if (p.y < 48) return 50;
        return (p.x < kPad + 150) ? 51 : 52;
    }
    if (h == g_hRight) {
        if (p.y < kTabH) return p.x < rc.right / 2 ? 60 : 61;
        if (g_railTab == RailTab::System && p.x < kRailW) {
            const int idx = (p.y - kTabH) / kIconStep;
            return (idx >= 0 && idx < kSysGroupCount) ? 70 + idx : 90;
        }
        if (g_railTab == RailTab::System && RowHit(p.y) >= 0) return 80;
        return 90;
    }
    return 0;
}
int g_lastHover = -1;

LRESULT CALLBACK PanelWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(h, &ps);
        RECT rc; GetClientRect(h, &rc);
        // Double-buffer: paint offscreen, blit once (kills flicker).
        HDC mem = CreateCompatibleDC(dc);
        HBITMAP bmp = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
        HGDIOBJ old = SelectObject(mem, bmp);
        PaintPanel(mem, h, rc.right, rc.bottom);
        BitBlt(dc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
        SelectObject(mem, old); DeleteObject(bmp); DeleteDC(mem);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_KEYDOWN:
        PostMessageW(g_hwnd, WM_KEYDOWN, w, l);
        return 0;
    case WM_MOUSEMOVE: {
        POINT p = {GET_X_LPARAM(l), GET_Y_LPARAM(l)};
        if (g_dragTime && (w & MK_LBUTTON) && g_timeline.right > g_timeline.left) {
            const int x = p.x - g_timeline.left;
            const int span = g_timeline.right - g_timeline.left;
            if (span > 0 && g_dragDur > 0) {
                double fr = (double)(x) / span;
                if (fr < 0) fr = 0; if (fr > 1) fr = 1;
                g_dragTarget = (LONGLONG)(g_dragDur * fr);
            }
            InvalidateRect(h, nullptr, FALSE);
            return 0;
        }
        if (g_dragRow >= 0 && (w & MK_LBUTTON)) {
            RECT rc; GetClientRect(h, &rc);
            for (auto& e : g_layout) {
                if ((int)e.idx == g_dragRow) {
                    Row& dr = g_rows[g_dragRow];
                    RECT band = SliderBand(e, rc.right, dr);
                    int x = p.x; if (x < band.left) x = band.left; if (x > band.right) x = band.right;
                    const float f = (float)(x - band.left) / (band.right - band.left);
                    dr.val = dr.min + (dr.max - dr.min) * f;
                    ApplyRow(g_dragRow);
                    InvalidateRect(h, nullptr, FALSE);
                    break;
                }
            }
            return 0;
        }
        g_lastMouse = p;
        TRACKMOUSEEVENT tme = {sizeof(tme)};
        tme.dwFlags = TME_LEAVE; tme.hwndTrack = h;
        TrackMouseEvent(&tme);
        const int tok = HoverToken(h, p);
        if (tok != g_lastHover) {          // repaint only on hover change
            g_lastHover = tok;
            InvalidateRect(h, nullptr, FALSE);
        }
        return 0;
    }
    case WM_MOUSELEAVE:
        g_lastHover = -1;
        InvalidateRect(h, nullptr, FALSE);
        return 0;
    case WM_LBUTTONDOWN: {
        POINT p = {GET_X_LPARAM(l), GET_Y_LPARAM(l)};
        RECT rc; GetClientRect(h, &rc);
        if (h == g_hRight) {
            if (g_railTab == RailTab::Playback) {
                // Tabs first — never swallow the Playback/System switcher.
                if (p.y < kTabH) {
                    g_railTab = (p.x < rc.right / 2) ? RailTab::Playback : RailTab::System;
                    InvalidateRect(h, nullptr, FALSE);
                    return 0;
                }
                if (g_player) {
                    for (size_t i = 0; i < g_playRows.size(); ++i) {
                        auto& r = g_playRows[i];
                        if (PtInRect(&r.rc, p)) {
                            if (r.kind == PlayRowKind::Audio) {
                                g_player->SetAudioTrack(r.index);
                                RefreshPlaybackInfo();
                            } else if (r.kind == PlayRowKind::Subtitle) {
                                g_player->SetSubtitleTrack(r.index);
                                RefreshPlaybackInfo();
                            } else if (r.kind == PlayRowKind::AudioDevice) {
                                // Route playback through the chosen WASAPI endpoint
                                // (e.g. an HDMI/AVR). MpcAudioRenderer picks it up;
                                // DSound fallback ignores it and stays on default.
                                g_selAudioDeviceId = r.id;
                                g_selAudioDeviceName = r.label;
                                size_t at = g_selAudioDeviceName.find(L"  (default)");
                                if (at != std::wstring::npos) g_selAudioDeviceName.erase(at);
                                g_player->SetAudioDevice(r.id, g_selAudioDeviceName);
                                for (auto& x : g_playRows) if (x.kind == PlayRowKind::AudioDevice) x.active = false;
                                r.active = true;
                                std::wcout << L"[AUDIO] routed to device: " << g_selAudioDeviceName << L"\n";
                            }
                            InvalidateRect(h, nullptr, FALSE);
                            return 0;
                        }
                    }
                    for (auto& r : g_audioOutRows) {
                        if (!PtInRect(&r.rc, p)) continue;
                        MpcPlayer::AudioMode mode = MpcPlayer::AudioMode::PCM;
                        MpcPlayer::BitstreamConfig bs{};
                        g_player->GetAudioMode(mode);
                        g_player->GetBitstreamConfig(bs);
                        if (r.kind == AudioOutRow::Kind::Mode) {
                            mode = (mode == MpcPlayer::AudioMode::PCM) ? MpcPlayer::AudioMode::Bitstream : MpcPlayer::AudioMode::PCM;
                            g_player->SetAudioMode(mode);
                            std::wcout << L"[AUDIO] mode = " << (mode == MpcPlayer::AudioMode::Bitstream ? L"Bitstream" : L"PCM") << L"\n";
                        } else {
                            if (wcscmp(r.label, L"AC-3") == 0)           bs.ac3 = !bs.ac3;
                            else if (wcscmp(r.label, L"E-AC-3") == 0)    bs.eac3 = !bs.eac3;
                            else if (wcscmp(r.label, L"TrueHD") == 0)    bs.trueHd = !bs.trueHd;
                            else if (wcscmp(r.label, L"DTS") == 0)       bs.dts = !bs.dts;
                            else if (wcscmp(r.label, L"DTS-HD") == 0)    bs.dtsHd = !bs.dtsHd;
                            else if (wcscmp(r.label, L"DTS-HD framing") == 0) bs.dtsHdFraming = !bs.dtsHdFraming;
                            g_player->SetBitstreamConfig(bs);
                            std::wcout << L"[AUDIO] bitstream " << r.label << L"\n";
                        }
                        InvalidateRect(h, nullptr, FALSE);
                        return 0;
                    }
                }
                return 0;
            }
            HandleSysClick(p, rc.right, rc.bottom);
            InvalidateRect(h, nullptr, FALSE);
            return 0;
        }
        if (h == g_hBottom && g_player && PtInRect(&g_timeline, p)) {
            MpcPlayer::Snapshot dsn; g_player->GetSnapshot(dsn);
            g_dragDur = dsn.duration > 0 ? dsn.duration : 0;
            const int x = p.x - g_timeline.left;
            const int span = g_timeline.right - g_timeline.left;
            if (span > 0 && g_dragDur > 0) {
                double fr = (double)(x) / span;
                if (fr < 0) fr = 0; if (fr > 1) fr = 1;
                g_dragTarget = (LONGLONG)(g_dragDur * fr);
            }
            g_dragTime = true;
            SetCapture(h);
            InvalidateRect(h, nullptr, FALSE);
            return 0;
        }
        if (h == g_hBottom && g_player && PtInRect(&g_audBtn, p)) {
            ToggleAudio();
            InvalidateRect(h, nullptr, FALSE);
            return 0;
        }
        return 0;
    }
    case WM_LBUTTONUP:
        if (g_dragTime) {
            g_dragTime = false;
            ReleaseCapture();
            if (g_player) g_player->Seek(g_dragTarget);   // commit the scrub
            InvalidateRect(h, nullptr, FALSE);
            return 0;
        }
        if (g_dragRow >= 0) { ReleaseCapture(); g_dragRow = -1; }
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

// Overlay helpers
void LayoutOverlays(int cx, int cy) {
    const int sbH = kBottomH;
    MoveWindow(g_hLeft, 0, 0, kLeftW, cy - sbH, TRUE);
    MoveWindow(g_hRight, cx - kRightW, 0, kRightW, cy - sbH, TRUE);
    MoveWindow(g_hBottom, 0, cy - sbH, cx, sbH, TRUE);
    const int show = g_editMode ? SW_SHOW : SW_HIDE;
    ShowWindow(g_hLeft, show);
    ShowWindow(g_hRight, show);
    ShowWindow(g_hBottom, show);
    for (HWND hw : {g_hLeft, g_hRight, g_hBottom}) {
        SetWindowPos(hw, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        InvalidateRect(hw, nullptr, FALSE);
    }
}

LRESULT CALLBACK MainWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_SIZE: {
        int cx = LOWORD(l), cy = HIWORD(l);
        if (cx < 100 || cy < 100) break;
        MoveWindow(g_hVideo, 0, 0, cx, cy, TRUE);
        LayoutOverlays(cx, cy);
        if (g_player) g_player->ResizeVideo();
        PostMessageW(h, WM_APP, kCmdRepaint, 0);
        return 0;
    }
    case WM_TIMER:
        if (w == 11) {
            std::wstring raw;
            if (g_player && SUCCEEDED(g_player->GetMlStats(raw))) {
                g_mlStats = raw;
                MpcPlayer::MlSettings ms;
                if (SUCCEEDED(g_player->GetMlSettings(ms))) {
                    wchar_t line[180];
                    swprintf_s(line, L"\n[shell] enable=%d mode=%d gamma=%.2f shadow=%.2f highlight=%.2f",
                               ms.enable ? 1 : 0, ms.mode, ms.gamma, ms.shadow, ms.highlight);
                    g_mlStats += line;
                }
            } else {
                g_mlStats.clear();
            }
            InvalidateRect(g_hLeft, nullptr, FALSE);
            return 0;
        }
        break;
    case WM_APP: {
        if (w == kCmdOpen) {
            OPENFILENAMEW ofn = {sizeof(ofn)};
            wchar_t file[MAX_PATH + 1] = {};
            wchar_t filter[] = L"Media\0*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.ts;*.m2ts\0All\0*.*\0\0";
            ofn.hwndOwner = h; ofn.lpstrFilter = filter; ofn.lpstrFile = file;
            ofn.nMaxFile = MAX_PATH; ofn.Flags = OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR;
            if (GetOpenFileNameW(&ofn) && g_player) {
                g_openFile = file;
                g_player->Stop();
                g_player->Open(g_openFile);
                g_player->Play();
            }
        } else if (w == kCmdPlayPause && g_player) {
            MpcPlayer::Snapshot sn; g_player->GetSnapshot(sn);
            if (sn.state != MpcPlayer::State::Playing) g_player->Play();
            else g_player->Pause();
        } else if (w == kCmdStop && g_player) {
            g_player->Stop();
        } else if (w == kCmdSeekBack && g_player) {
            MpcPlayer::Snapshot sn; g_player->GetSnapshot(sn);
            g_player->Seek(sn.position - 50000000);
        } else if (w == kCmdSeekFwd && g_player) {
            MpcPlayer::Snapshot sn; g_player->GetSnapshot(sn);
            g_player->Seek(sn.position + 50000000);
        }
        InvalidateRect(g_hLeft, nullptr, FALSE);
        InvalidateRect(g_hRight, nullptr, FALSE);
        InvalidateRect(g_hBottom, nullptr, FALSE);
        if (g_player) g_player->ResizeVideo();
        return 0;
    }
    case WM_KEYDOWN: {
        switch (w) {
        case VK_ESCAPE: PostMessageW(h, WM_CLOSE, 0, 0); break;
        case VK_SPACE:  PostMessageW(h, WM_APP, kCmdPlayPause, 0); break;
        case VK_LEFT:   PostMessageW(h, WM_APP, kCmdSeekBack, 0); break;
        case VK_RIGHT:  PostMessageW(h, WM_APP, kCmdSeekFwd, 0); break;
        case 'O':       PostMessageW(h, WM_APP, kCmdOpen, 0); break;
        case 'A':       ToggleAudio(); break;
        case VK_RETURN:  PostMessageW(h, WM_APP, kCmdPlayPause, 0); break;
        case VK_UP:
            g_editMode = !g_editMode;
            { RECT rc; GetClientRect(h, &rc);
              MoveWindow(g_hVideo, 0, 0, rc.right, rc.bottom, TRUE);
              LayoutOverlays(rc.right, rc.bottom); }
            return 0;
        }
        return 0;
    }
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
        HBRUSH b = CreateSolidBrush(COL_BG); FillRect(dc, &ps.rcPaint, b); DeleteObject(b);
        EndPaint(h, &ps); return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

HWND MakePanel(HINSTANCE inst, HWND parent, const wchar_t* cls, int x, int y, int w, int h) {
    WNDCLASSEXW wc = {sizeof(wc)};
    wc.lpfnWndProc = PanelWndProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.lpszClassName = cls;
    RegisterClassExW(&wc);
    return CreateWindowExW(0, cls, L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
        x, y, w, h, parent, nullptr, inst, nullptr);
}

}  // namespace

// -- entry --------------------------------------------------------------------
int wmain(int argc, wchar_t* argv[]) {
    for (int i = 1; i < argc; ++i) {
        if (_wcsicmp(argv[i], L"--renderer") == 0 && i + 1 < argc) {
            const wchar_t* v = argv[++i];
            if (_wcsicmp(v, L"auto") == 0) g_renderer = MpcPlayer::Renderer::Auto;
            else if (_wcsicmp(v, L"vmr9") == 0) g_renderer = MpcPlayer::Renderer::VMR9;
            else if (_wcsicmp(v, L"evr") == 0) g_renderer = MpcPlayer::Renderer::EVR;
            else if (_wcsicmp(v, L"mpcvr") == 0) g_renderer = MpcPlayer::Renderer::MPCVR;
        } else if (g_openFile.empty()) {
            g_openFile = argv[i];
        }
    }

    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    INITCOMMONCONTROLSEX icx = {sizeof(icx)};
    icx.dwICC = ICC_BAR_CLASSES;
    InitCommonControlsEx(&icx);
    // DPI-aware: the whole UI is authored at 96dpi and scaled per-display.
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    GetDpiForSystem();   // ensure the DPI used by InitGeometry reflects awareness
    InitGeometry();
    HINSTANCE inst = GetModuleHandleW(nullptr);
    LoadInterFonts();
    InitFonts();
    BuildRows();

    WNDCLASSEXW mainWc = {sizeof(mainWc)};
    mainWc.lpfnWndProc = MainWndProc;
    mainWc.hInstance = inst;
    mainWc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    mainWc.lpszClassName = L"S3Main";
    RegisterClassExW(&mainWc);

    RECT r = {0, 0, 1280, 720};
    (void)r;   // frameless: window fills the display at startup
    g_hwnd = CreateWindowExW(0, L"S3Main", L"S3 — MPC-HC engine shell",
        WS_POPUP | WS_VISIBLE, 0, 0, CW_USEDEFAULT, CW_USEDEFAULT, nullptr, nullptr, inst, nullptr);
    ShowWindow(g_hwnd, SW_MAXIMIZE);   // maximized, no caption bar

    {
        RECT rc; GetClientRect(g_hwnd, &rc);
        int cx = rc.right, cy = rc.bottom;

        WNDCLASSEXW vc = {sizeof(vc)};
        vc.lpfnWndProc = VideoWndProc;
        vc.hInstance = inst;
        vc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        vc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
        vc.lpszClassName = L"S3Video";
        RegisterClassExW(&vc);
        g_hVideo = CreateWindowExW(0, L"S3Video", L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
            0, 0, cx, cy, g_hwnd, nullptr, inst, nullptr);

        g_hLeft   = MakePanel(inst, g_hwnd, L"S3Left", 0, 0, kLeftW, cy - kBottomH);
        g_hRight  = MakePanel(inst, g_hwnd, L"S3Right", cx - kRightW, 0, kRightW, cy - kBottomH);
        g_hBottom = MakePanel(inst, g_hwnd, L"S3Bottom", 0, cy - kBottomH, cx, kBottomH);
        LayoutOverlays(cx, cy);
        SetTimer(g_hwnd, 11, 500, nullptr);   // poll MPCVR's live ML internals

        MpcPlayer player;
        g_player = &player;
        player.SetEventCallback([](std::string_view, const MpcPlayer::Snapshot&) {
            PostMessageW(g_hwnd, WM_APP, kCmdRepaint, 0);
        });
        HRESULT hrA = player.AttachRenderTarget(g_hVideo);
        HRESULT hrR = player.SetRenderer(g_renderer);
        std::cout << "[INIT] AttachRenderTarget hr=0x" << std::hex << (unsigned long)hrA
                  << " SetRenderer(MPCVR) hr=0x" << (unsigned long)hrR << std::dec << "\n";

        if (!g_openFile.empty()) {
            const HRESULT hrO = player.Open(g_openFile);
            const HRESULT hrP = player.Play();
            std::cout << "[INIT] Open hr=0x" << std::hex << (unsigned long)hrO
                      << " Play hr=0x" << (unsigned long)hrP << std::dec << "\n";
            PullMlFromRenderer();   // seed the ZION rows from MPCVR's real settings
            PullHdrFromRenderer();
            PullOutFromRenderer();
            { bool aOn = false; if (SUCCEEDED(player.GetAudioEnabled(aOn))) g_audioOn = aOn; }
            RefreshPlaybackInfo();

            // Baseline: ALWAYS Tone curve Off, Chroma Default, Detail Off (CR/Res off),
            // regardless of MPCVR's persisted settings from previous runs.
            // Demo default: ML ON, Tone Auto, Chroma Default, Detail Off, every
            // Tone/Chroma option enabled — regardless of MPCVR's saved/zero state.
            for (auto& r : g_rows) {
                if      (!strcmp(r.key, "zion.toneMode"))   r.opt = 0;   // Auto
                else if (!strcmp(r.key, "zion.chromaMode")) r.opt = 0;   // Default
                else if (!strcmp(r.key, "zion.detailMode")) r.opt = 2;   // Off
            }
            g_mlMasterEnable = true;   // Enable ML grade ON
            for (auto& r : g_rows)
                if (r.group == kGroupZion && r.type == RowType::Slider)
                    r.enabledFlag = true;   // all Tone/Chroma options enabled
            UpdateGates();
            RebuildLayout();
            PushMlToRenderer();
            MpcPlayer::MlSettings back;
            if (SUCCEEDED(player.GetMlSettings(back)))
                std::cout << "[BRIDGE] baseline echo enable=" << (back.enable ? 1 : 0)
                          << " mode=" << back.mode
                          << " tone=" << (back.toneCurveEnabled ? 1 : 0)
                          << " chroma=" << (back.chromaEnabled ? 1 : 0)
                          << " cr=" << (back.crEnabled ? 1 : 0)
                          << " radi=" << (back.radiEnabled ? 1 : 0) << "\n";
            std::wstring stats;
            if (SUCCEEDED(player.GetMlStats(stats)))
                std::wcout << L"[STATS] " << stats << L"\n";
            std::wstring proc;
            if (SUCCEEDED(player.GetProcessorInfo(proc)))
                std::wcout << L"[PROC] " << proc << L"\n";
            std::wcout.flush();
        }

        // Media Player default state: open a file picker on startup.
        if (g_openFile.empty()) PostMessageW(g_hwnd, WM_APP, kCmdOpen, 0);

        MSG msg;
        while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        player.Stop();
        g_player = nullptr;
    }

    DestroyWindow(g_hwnd);
    CoUninitialize();
    return 0;
}
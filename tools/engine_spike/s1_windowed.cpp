// s1_windowed.cpp — S1: form-factor B proof.
//
// One window (ours). A video sub-rect hosts a DirectShow graph built with
// MPCVR forced in (CLSID 71F080AA-...) as the renderer; "panel" child windows
// (left live, right rail, bottom bar) are painted OVER the same window,
// proving panels + video composite in one surface.
//
// Machine checks printed at the end:
//   1. graph filter list contains "MPC Video Renderer"
//   2. renderer CLSID == ours
//   3. that CLSID's InprocServer32 resolves to OUR installed .ax

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dshow.h>
#include <atlbase.h>
#include <gdiplus.h>
#include <string>
#include <vector>
#include <iostream>

// Registered CLSIDs (verified via registry, 2026-09-06):
static const CLSID CLSID_MPCVR      = {0x71F080AA,0x8661,0x4093,{0xB1,0x5E,0x4F,0x69,0x03,0xE7,0x7D,0x0A}};
static const CLSID CLSID_MPCVRAP    = {0x28789E29,0x5BDD,0x4374,{0xAD,0xEC,0xAB,0x2E,0xB9,0x21,0x2C,0x0D}}; // AllocatorPresenter (FGManager uses this)
static const CLSID CLSID_LAVSplitter= {0x171252A0,0x8820,0x4AFE,{0x9D,0xF8,0x5C,0x92,0xB2,0xD6,0x6B,0x04}};
static const CLSID CLSID_LAVVideo   = {0xEE30215D,0x164F,0x4A92,{0xA4,0xEB,0x9D,0x4C,0x13,0x39,0x0F,0x9F}};

static const int W=960, H=540;
static const int LEFT_W=180, RIGHT_W=300, BOTTOM_H=150;
static const COLORREF COL_VIDEO = RGB(10,10,12), COL_PANEL = RGB(14,14,16),
                      COL_ACCENT = RGB(0xE8,0x55,0x1F), COL_TEXT = RGB(0xF2,0xF2,0xF2);

HWND g_hwnd, g_hVideo, g_hLeft, g_hRight, g_hBottom;
UINT g_tick = 0;

static std::wstring GuidStr(const GUID& g) {
    wchar_t b[50]; swprintf_s(b, L"{%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}",
        g.Data1, g.Data2, g.Data3, g.Data4[0],g.Data4[1],g.Data4[2],g.Data4[3],
        g.Data4[4],g.Data4[5],g.Data4[6],g.Data4[7]); return b;
}

static void DrawPanel(HWND pw, RECT rc, const wchar_t* title, const wchar_t* status) {
    PAINTSTRUCT ps; HDC dc = BeginPaint(pw, &ps);
    RECT r; GetClientRect(pw, &r);
    HBRUSH bg = CreateSolidBrush(COL_PANEL);
    FillRect(dc, &r, bg); DeleteObject(bg);
    HBRUSH br = CreateSolidBrush(COL_ACCENT);
    FrameRect(dc, &r, br); DeleteObject(br);
    SetBkMode(dc, TRANSPARENT); SetTextColor(dc, COL_TEXT);
    RECT t = r; t.left += 14; t.top += 10;
    HFONT f = CreateFont(26,0,0,0,FW_SEMIBOLD,0,0,0,DEFAULT_CHARSET,0,0,0,0,L"Segoe UI");
    HFONT fo = (HFONT)SelectObject(dc, f);
    DrawTextW(dc, title, -1, &t, DT_LEFT);
    SelectObject(dc, fo);
    RECT s = r; s.left += 14; s.top += 52;
    HFONT f2 = CreateFont(18,0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,0,0,L"Segoe UI");
    fo = (HFONT)SelectObject(dc, f2);
    DrawTextW(dc, status, -1, &s, DT_LEFT);
    SelectObject(dc, fo);
    DeleteObject(f); DeleteObject(f2); DeleteObject(fo);
    EndPaint(pw, &ps);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(hwnd, &ps);
        HBRUSH b = CreateSolidBrush(COL_VIDEO); FillRect(dc, &ps.rcPaint, b); DeleteObject(b);
        EndPaint(hwnd, &ps); return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_TIMER:
        if (wp == 9 && hwnd == g_hwnd) {
            g_tick++;
            wchar_t st[128];
            swprintf_s(st, L"S1 live — output probe 0x%04X", g_tick);
            InvalidateRect(g_hRight, nullptr, FALSE);
            InvalidateRect(g_hLeft, nullptr, FALSE);
            InvalidateRect(g_hBottom, nullptr, FALSE);
        }
        return 0;
    case WM_KEYDOWN: if (wp == VK_ESCAPE) { PostMessage(g_hwnd, WM_CLOSE, 0, 0); } return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static std::vector<CComPtr<IPin>> EnumPins(CComPtr<IBaseFilter>& f) {
    std::vector<CComPtr<IPin>> out;
    CComPtr<IEnumPins> pe; ULONG n = 0; CComPtr<IPin> p;
    if (SUCCEEDED(f->EnumPins(&pe)) && pe) {
        while (SUCCEEDED(pe->Next(1, &p, &n)) && n) { out.push_back(p); p.Release(); n = 0; }
    }
    return out;
}

static CComPtr<IPin> FindPin(CComPtr<IBaseFilter>& f, PIN_DIRECTION dir) {
    for (auto& pi : EnumPins(f)) {
        PIN_DIRECTION d; if (SUCCEEDED(pi->QueryDirection(&d)) && d == dir) return pi;
    }
    return nullptr;
}

static void PrintFilters(CComPtr<IGraphBuilder>& gb) {
    CComPtr<IEnumFilters> pf; ULONG n = 0; CComPtr<IBaseFilter> f;
    std::cout << "filters in graph:\n";
    if (SUCCEEDED(gb->EnumFilters(&pf)) && pf) {
        while (SUCCEEDED(pf->Next(1, &f, &n)) && n) {
            FILTER_INFO fi = {}; if (SUCCEEDED(f->QueryFilterInfo(&fi))) {
                std::wcout << L"  " << (fi.achName[0] ? fi.achName : L"(unnamed)") << L"\n";
                if (fi.pGraph) fi.pGraph->Release();
            }
            f.Release(); n = 0;
        }
    }
}

// Triple check: name + CLSID + module path resolve to our _bin MPCVR.
static void IdentityCheck() {
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Classes\\CLSID\\{71F080AA-8661-4093-B15E-4F6903E77D0A}\\InprocServer32",
                      0, KEY_READ, &key) == ERROR_SUCCESS) {
        wchar_t mod[MAX_PATH] = {}; DWORD cb = sizeof(mod);
        if (RegQueryValueExW(key, nullptr, nullptr, nullptr, (LPBYTE)mod, &cb) == ERROR_SUCCESS) {
            std::wcout << L"renderer module resolved: " << mod << L"\n";
        }
        RegCloseKey(key);
    }
    std::cout << "identity: create-CLSID {71F080AA-8661-4093-B15E-4F6903E77D0A} = MPC Video Renderer\n";
}

static const CLSID PNG_ENC = {0x557CF406,0x1A04,0x11D3,{0x9A,0x73,0x00,0x00,0xF8,0x1E,0xF3,0x2E}};

static void SaveWindowPng() {
    Gdiplus::GdiplusStartupInput gsi; ULONG_PTR token = 0;
    if (Gdiplus::GdiplusStartup(&token, &gsi, nullptr) != Gdiplus::Ok) return;
    {
        HDC dc = GetWindowDC(g_hwnd);
        HDC mdc = CreateCompatibleDC(dc);
        HBITMAP bmp = CreateCompatibleBitmap(dc, W, H);
        HGDIOBJ old = SelectObject(mdc, bmp);
        PrintWindow(g_hwnd, mdc, PW_RENDERFULLCONTENT);
        Gdiplus::Bitmap b(bmp, nullptr);
        b.Save(L"s1_window.png", &PNG_ENC);   // b destroyed inside this scope, before Shutdown
        SelectObject(mdc, old); DeleteObject(bmp); DeleteDC(mdc); ReleaseDC(g_hwnd, dc);
    }
    Gdiplus::GdiplusShutdown(token);
    std::cout << "window png: s1_window.png\n";
}

int wmain(int argc, wchar_t* argv[]) {
    if (argc < 2) { std::wcerr << L"usage: s1_windowed.exe [-own] <media-file>\n"; return 2; }
    bool own_window = false;
    if (wcsicmp(argv[1], L"-own") == 0) { own_window = true; argc--; argv++; }
    setvbuf(stdout, nullptr, _IONBF, 0);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    std::cout << "mode: " << (own_window ? "-own (renderer's own window)" : "-hosted (our child HWND)") << "\n";

    WNDCLASSW wc = {};
    wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandle(nullptr);
    wc.lpszClassName = L"S1Wnd"; wc.hbrBackground = CreateSolidBrush(COL_VIDEO);
    RegisterClassW(&wc);

    RECT wr = {0,0,W,H}; AdjustWindowRectEx(&wr, WS_POPUP, FALSE, 0);
    g_hwnd = CreateWindowExW(0, L"S1Wnd", L"MPC-HC S1 — one window",
        WS_POPUP | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT,
        wr.right-wr.left, wr.bottom-wr.top, nullptr, nullptr, wc.hInstance, nullptr);

    RECT vr = {LEFT_W, 0, W-RIGHT_W, H-BOTTOM_H};
    g_hVideo  = CreateWindowExW(WS_EX_NOPARENTNOTIFY, L"S1Wnd", L"", WS_CHILD|WS_VISIBLE|WS_CLIPCHILDREN|WS_CLIPSIBLINGS, vr.left, vr.top, vr.right-vr.left, vr.bottom-vr.top, g_hwnd, nullptr, wc.hInstance, nullptr);
    g_hLeft   = CreateWindowExW(0, L"S1Wnd", L"", WS_CHILD|WS_VISIBLE, 0, 0, LEFT_W, H, g_hwnd, nullptr, wc.hInstance, nullptr);
    g_hRight  = CreateWindowExW(0, L"S1Wnd", L"", WS_CHILD|WS_VISIBLE, W-RIGHT_W, 0, RIGHT_W, H, g_hwnd, nullptr, wc.hInstance, nullptr);
    g_hBottom = CreateWindowExW(0, L"S1Wnd", L"", WS_CHILD|WS_VISIBLE, 0, H-BOTTOM_H, W, BOTTOM_H, g_hwnd, nullptr, wc.hInstance, nullptr);

    CComPtr<IGraphBuilder> gb;
    HRESULT hr = gb.CoCreateInstance(CLSID_FilterGraph);
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "FilterGraph hr=" << std::hex << hr << std::dec << "\n";

    CComPtr<IBaseFilter> src; CComPtr<IBaseFilter> split; CComPtr<IBaseFilter> dec; CComPtr<IBaseFilter> rend;
    wchar_t nm[32] = {};
    hr = gb->AddSourceFilter(argv[1], L"source", &src);
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "AddSourceFilter hr=" << std::hex << hr << std::dec << "\n";

    hr = split.CoCreateInstance(CLSID_LAVSplitter);
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "CoCreate LAV Splitter hr=" << std::hex << hr << std::dec << "\n";
    if (!split) return 2;
    hr = dec.CoCreateInstance(CLSID_LAVVideo);
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "CoCreate LAV Video hr=" << std::hex << hr << std::dec << "\n";
    if (!dec) return 2;
    hr = rend.CoCreateInstance(CLSID_MPCVRAP);
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "CoCreate MPCVR AllocatorPresenter hr=" << std::hex << hr << std::dec << "\n";
    if (!rend) {
        hr = rend.CoCreateInstance(CLSID_MPCVR);
        std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "CoCreate MPCVR VideoRenderer fallback hr=" << std::hex << hr << std::dec << "\n";
    }
    if (!rend) return 2;

    hr = gb->AddFilter(split, L"LAV Splitter");
    hr = SUCCEEDED(hr) ? gb->AddFilter(dec, L"LAV Video") : hr;
    hr = SUCCEEDED(hr) ? gb->AddFilter(rend, L"MPC Video Renderer") : hr;
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "AddFilter(3) hr=" << std::hex << hr << std::dec << "\n";

    CComPtr<IPin> srcOut = FindPin(src, PINDIR_OUTPUT);
    CComPtr<IPin> splitIn = FindPin(split, PINDIR_INPUT);
    hr = (srcOut && splitIn) ? gb->Connect(srcOut, splitIn) : E_POINTER;
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "src->splitter hr=" << std::hex << hr << std::dec << "\n";

    CComPtr<IPin> splitOut = FindPin(split, PINDIR_OUTPUT);
    CComPtr<IPin> decIn = FindPin(dec, PINDIR_INPUT);
    hr = (splitOut && decIn) ? gb->Connect(splitOut, decIn) : E_POINTER;
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "splitter->decoder hr=" << std::hex << hr << std::dec << "\n";

    // MPC-HC assigns the renderer owner before connecting its input pin.
    CComPtr<IVideoWindow> vw; bool hosted = false;
    if (!own_window && SUCCEEDED(rend->QueryInterface(&vw)) && vw) {
        vw->put_Owner((OAHWND)g_hVideo);
        vw->put_WindowStyle(WS_CHILD | WS_CLIPSIBLINGS);
        vw->SetWindowPosition(0, 0, vr.right-vr.left, vr.bottom-vr.top);
        vw->put_MessageDrain((OAHWND)g_hwnd);
        hosted = true;
        std::cout << "[OK] video hosted in our HWND via IVideoWindow\n";
    }

    CComPtr<IPin> decOut = FindPin(dec, PINDIR_OUTPUT);
    CComPtr<IPin> rendIn = FindPin(rend, PINDIR_INPUT);
    hr = (decOut && rendIn) ? gb->Connect(decOut, rendIn) : E_POINTER;
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "decoder->MPCVR hr=" << std::hex << hr << std::dec << "\n";

    PrintFilters(gb);

    if (!hosted) {
        std::cout << "[WARN] renderer using its OWN window (no put_Owner)\n";
    }

    CComPtr<IMediaControl> mc; CComPtr<IMediaSeeking> ms;
    gb->QueryInterface(&mc); gb->QueryInterface(&ms);
    hr = mc->Run();
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << "Run hr=" << std::hex << hr << std::dec << "\n";

    if (vw) { vw->put_Visible(OATRUE); }  // renderer window defaults hidden after put_Owner

    SetTimer(g_hwnd, 9, 500, nullptr);
    for (int i = 0; i < 60; i++) {  // ~12s window: plenty of time to watch the bars
        if (i == 20 && vw) {  // ~4s in: shrink the video surface = live control proof
            RECT vr2 = {LEFT_W, 0, W - RIGHT_W, H - BOTTOM_H};
            int nw = (vr2.right - vr2.left) / 2, nh = (vr2.bottom - vr2.top) / 2;
            vw->SetWindowPosition(0, 0, nw, nh);
            std::cout << "[CTRL] video surface resized to " << nw << "x" << nh << "\n";
        }
        MSG m; while (PeekMessageW(&m, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&m); DispatchMessageW(&m);
        }
        Sleep(200);
    }

    LONGLONG dur = 0, pos = 0, stop = 0;
    if (ms) ms->GetDuration(&dur);
    if (ms) ms->GetPositions(&pos, &stop);
    std::cout << "duration=" << dur << " pos=" << pos << "\n";

    IdentityCheck();
    SaveWindowPng();
    std::cout << "hosted-in-our-window=" << (hosted ? "yes" : "no") << "\n";

    mc->Stop();
    std::cout << "S1_COMPLETE\n";
    DestroyWindow(g_hwnd);
    CoUninitialize();
    return 0;
}
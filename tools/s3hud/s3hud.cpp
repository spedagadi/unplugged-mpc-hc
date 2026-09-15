// s3hud â€” HTPC DeckLink HUD shell (Dear ImGui overlay over the video).
//
// Architecture (2026-09-15 decision): the UI is an immediate-mode overlay
// rendered by Dear ImGui into a borderless, topmost, per-pixel-alpha D3D11
// window floating over the MPCVR video window. NO OS child-window panels, no
// focus-dependent key routing (input is polled/hooked explicitly) â€” the
// components that cost the win32 shell three days of stability work are gone
// by construction. The engine (mpchc_engine + DeckLinkSource.ax) is used
// directly (same process, call methods, no interop layer), and it is
// self-healing: the monitor's confirmed signal change post-rebuilds internally
// (ops-queue executor), so this UI never drives transitions.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <shellapi.h>
#include <d3d11.h>
#include <dxgi1_2.h>

#include <cstdio>
#include <string>
#include <vector>
#include <mutex>
#include <deque>

#include "MpcPlayer.h"
#include "DeckLinkSourceControl.h"

#include "imgui.h"
#include "imgui_impl_dx11.h"

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

// ---------------------------------------------------------------------------
// Engine handle (single instance, in-process)
// ---------------------------------------------------------------------------
static MpcPlayer g_player;
static HWND       g_videoHwnd = nullptr;   // main video window (MPCVR attaches here)
static HWND       g_hudHwnd   = nullptr;   // topmost ImGui overlay window
static bool       g_showPanels = true;
static bool       g_quit = false;

// Input bridge: keyboard hook â†’ queue; mouse polled per frame.
static std::mutex     g_keyMtx;
static std::deque<int> g_keys;
static HHOOK           g_hook = nullptr;

static LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN)) {
        const KBDLLHOOKSTRUCT* kb = reinterpret_cast<const KBDLLHOOKSTRUCT*>(lParam);
        std::lock_guard<std::mutex> lk(g_keyMtx);
        if (g_keys.size() < 32) g_keys.push_back((int)kb->vkCode);
    }
    return CallNextHookEx(nullptr, nCode, wParam, lParam);
}

// ---------------------------------------------------------------------------
// Video window (MPCVR presents into it)
// ---------------------------------------------------------------------------
static void applog(const char* s) {
    if (FILE* f = _wfopen(L"s3hud_diag.log", L"a")) { fputs(s, f); fputc('\n', f); fclose(f); }
    OutputDebugStringA(s); OutputDebugStringA("\n");
}

static LRESULT CALLBACK VideoWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_ERASEBKGND: return 1;
    case WM_SIZE:
        g_player.ResizeVideo();
        return 0;
    case WM_DESTROY: applog("[APP] WM_DESTROY on VIDEO window"); PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

// ---------------------------------------------------------------------------
// HUD overlay window â€” click-through except over interactive ImGui panels
// (Hit-testing uses rects we record while composing the panels each frame â€”
// no dependency on ImGui's internal window list.)
// ---------------------------------------------------------------------------
static std::vector<RECT> g_panelRects;
static void RecordPanel(int x, int y, int w, int h) {
    RECT r; r.left = x; r.top = y; r.right = x + w; r.bottom = y + h;
    g_panelRects.push_back(r);
}
static bool CursorOverPanel(POINT screenPt) {
    for (const RECT& r : g_panelRects)
        if (screenPt.x >= r.left && screenPt.x <= r.right &&
            screenPt.y >= r.top  && screenPt.y <= r.bottom)
            return true;
    return false;
}

static LRESULT CALLBACK HudWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_NCHITTEST: {
        POINT pt = { GET_X_LPARAM(l), GET_Y_LPARAM(l) };
        return CursorOverPanel(pt) ? HTCLIENT : HTTRANSPARENT;   // swallows to video window
    }
    case WM_ERASEBKGND: return 1;
    case WM_DESTROY: applog("[APP] WM_DESTROY on HUD window"); PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

static void CreateWindows(HINSTANCE inst, int mw, int mh) {
    WNDCLASSEXW vc = { sizeof(vc) };
    vc.hInstance = inst; vc.lpfnWndProc = VideoWndProc;
    vc.lpszClassName = L"S3HudVideo"; vc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassExW(&vc);
    WNDCLASSEXW hc = { sizeof(hc) };
    hc.hInstance = inst; hc.lpfnWndProc = HudWndProc;
    hc.lpszClassName = L"S3HudOverlay";
    RegisterClassExW(&hc);

    g_videoHwnd = CreateWindowExW(0, L"S3HudVideo", L"S3 HUD",
        WS_POPUP | WS_VISIBLE, 0, 0, mw, mh, nullptr, nullptr, inst, nullptr);
    g_hudHwnd = CreateWindowExW(WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_APPWINDOW,
        L"S3HudOverlay", L"", WS_POPUP | WS_VISIBLE, 0, 0, mw, mh, nullptr, nullptr, inst, nullptr);
}

// ---------------------------------------------------------------------------
// D3D11 device + alpha swapchain for the overlay
// ---------------------------------------------------------------------------
static ID3D11Device*        g_d3d = nullptr;
static ID3D11DeviceContext* g_d3dCtx = nullptr;
static IDXGISwapChain1*     g_swap = nullptr;
static ID3D11RenderTargetView* g_rtv = nullptr;
static HRESULT g_d3dFailHr = S_OK;

static bool InitD3D(HWND hwnd, int w, int h) {
    D3D_FEATURE_LEVEL levels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, 2, D3D11_SDK_VERSION,
        &g_d3d, nullptr, &g_d3dCtx);
    if (FAILED(hr)) {
        g_d3dFailHr = hr;
        hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, 2, D3D11_SDK_VERSION,
            &g_d3d, nullptr, &g_d3dCtx);
    }
    if (FAILED(hr) || !g_d3d || !g_d3dCtx) { if (FAILED(hr)) g_d3dFailHr = hr; return false; }

    CComPtr<IDXGIDevice>  dxgiDev;  g_d3d->QueryInterface(IID_PPV_ARGS(&dxgiDev));
    CComPtr<IDXGIAdapter> adapter;  dxgiDev->GetAdapter(&adapter);
    CComPtr<IDXGIFactory2> factory; adapter->GetParent(IID_PPV_ARGS(&factory));
    if (!factory) { g_d3dFailHr = E_NOINTERFACE; return false; }

    // Per-pixel alpha over the video requires the FLIP presentation model and
    // is picky about the exact combo (Scaling / AlphaMode / SwapEffect). Try a
    // ladder of configurations: ideal alpha-first, then flip without alpha,
    // then the classic discard model as a degraded-but-working fallback.
    struct Try { DXGI_SWAP_EFFECT effect; DXGI_ALPHA_MODE alpha; } tries[] = {
        { DXGI_SWAP_EFFECT_FLIP_DISCARD,    DXGI_ALPHA_MODE_PREMULTIPLIED },
        { DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL, DXGI_ALPHA_MODE_PREMULTIPLIED },
        { DXGI_SWAP_EFFECT_FLIP_DISCARD,    DXGI_ALPHA_MODE_IGNORE },
        { DXGI_SWAP_EFFECT_DISCARD,         DXGI_ALPHA_MODE_IGNORE },
    };
    for (const Try& t : tries) {
        DXGI_SWAP_CHAIN_DESC1 desc = {};
        desc.Width = (UINT)w; desc.Height = (UINT)h;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.Stereo = FALSE;
        desc.SampleDesc = { 1, 0 };
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = (t.effect == DXGI_SWAP_EFFECT_DISCARD) ? 1 : 2;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.SwapEffect = t.effect;
        desc.AlphaMode = t.alpha;

        hr = factory->CreateSwapChainForHwnd(g_d3d, hwnd, &desc, nullptr, nullptr, &g_swap);
        if (SUCCEEDED(hr)) break;
        char b[128];
        snprintf(b, sizeof(b), "s3hud: swapchain try effect=%d alpha=%d hr=0x%08X\n",
            (int)t.effect, (int)t.alpha, (unsigned)hr);
        OutputDebugStringA(b);
    }
    if (!g_swap) { g_d3dFailHr = hr; return false; }

    CComPtr<ID3D11Texture2D> back;
    hr = g_swap->GetBuffer(0, IID_PPV_ARGS(&back));
    if (FAILED(hr) || !back) { g_d3dFailHr = hr; return false; }
    g_d3d->CreateRenderTargetView(back, nullptr, &g_rtv);
    if (!g_rtv) { g_d3dFailHr = E_FAIL; return false; }
    return true;
}

// ---------------------------------------------------------------------------
// Engine wiring + HUD contents
// ---------------------------------------------------------------------------
static void RenderHud() {
    MpcPlayer::Snapshot sn{};   g_player.GetSnapshot(sn);
    MpcPlayer::RenderStats rs{}; g_player.GetLiveRendererStats(rs);
    DeckLinkSourceStats dl{};   g_player.GetLiveDeckLinkSourceStats(dl);
    const auto& vs = g_player.GetVideoStreamInfo();

    const ImGuiViewport* vp = ImGui::GetMainViewport();
    g_panelRects.clear();

    // LEFT â€” LIVE
    RecordPanel(8, 8, 300, 550);
    ImGui::SetNextWindowPos  (ImVec2(8, 8),  ImGuiCond_Always);
    ImGui::SetNextWindowSize (ImVec2(300, 550), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.75f);
    if (ImGui::Begin("LIVE", &g_showPanels, ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize |
                      ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoTitleBar)) {
        const wchar_t* csN = dl.colorspace == 3 ? L"BT.2020" : dl.colorspace == 1 ? L"BT.601"
                           : dl.colorspace == 2 ? L"BT.709" : L"â€”";
        const wchar_t* drN = dl.eotf == 4 ? L"DolbyVision" : dl.eotf == 2 ? L"HDR PQ"
                           : dl.eotf == 3 ? L"HDR HLG" : L"SDR";
        ImGui::TextUnformatted("CAPTURE INPUT");
        if (dl.streaming) {
            char line[96];
            if (dl.width > 0 && dl.height > 0 && dl.fpsDen > 0)
                snprintf(line, sizeof(line), "%dÃ—%d @ %.3f fps  Â·  %ls Â· %ls",
                    dl.width, dl.height, (double)dl.fpsNum / dl.fpsDen, csN, drN);
            else
                snprintf(line, sizeof(line), "%ls Â· %ls", csN, drN);
            ImGui::TextUnformatted(line);
        } else {
            ImGui::TextUnformatted("signal: â€”");
        }
        ImGui::Separator();
        ImGui::TextUnformatted("RENDER");
        ImGui::Text("recv %u   draw %.2f fps   lag %.0f ms", rs.framesReceived, rs.drawFps, rs.presentLatencyMs);
        ImGui::Text("drop %u   skip %u   fail %u", rs.dropped, rs.skipped, rs.failed);

        ImGui::Separator();
        ImGui::TextUnformatted("SOURCE â†’ RENDER");
        ImGui::Text("in %llu   dlv %llu   skip %llu", dl.framesArrived, dl.framesDelivered, dl.framesSkipped);
        ImGui::Text("gate %llu   qDrop %llu   reneg %llu", dl.gateDropped, dl.droppedQueue, dl.renegotiations);
        if (vs.valid) {
            char line[128];
            const double fps = vs.avgTimePerFrame100ns > 0 ? 10000000.0 / vs.avgTimePerFrame100ns : 0.0;
            snprintf(line, sizeof(line), "media %dÃ—%d %ls %.3f fps%s", vs.width, vs.height,
                vs.subtypeName.c_str(), fps, vs.interlaced ? " i" : " p");
            ImGui::TextUnformatted(line);
        }
    }
    ImGui::End();

    // RIGHT â€” TONE (read/write the engine settings live)
    RecordPanel((int)vp->WorkSize.x - 308, 8, 300, 340);
    ImGui::SetNextWindowPos  (ImVec2(vp->WorkSize.x - 308, 8), ImGuiCond_Always);
    ImGui::SetNextWindowSize (ImVec2(300, 340), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.75f);
    if (ImGui::Begin("TONE", nullptr, ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize |
                      ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoTitleBar)) {
        static int curveSel = 5;
        MpcPlayer::HdrSettings hdr{};
        if (SUCCEEDED(g_player.GetHdrSettings(hdr))) {
            curveSel = hdr.toneMapCurve;
            const char* curves[] = { "ACES", "Reinhard", "Hable", "MÃ¶bius", "BT.2390", "ST 2094-10" };
            if (ImGui::Combo("Curve", &curveSel, curves, 6)) {
                hdr.toneMapCurve = curveSel;
                g_player.SetHdrSettings(hdr);
            }
            int target = hdr.convertToSdr ? hdr.sdrDisplayNits : hdr.displayMaxNits;
            if (ImGui::SliderInt("Display nits", &target, 16, 4000, "%d"))
                g_player.SetHdrSettings(hdr);
            ImGui::Checkbox("Convert to SDR", &hdr.convertToSdr);
            if (ImGui::Button("Apply")) g_player.SetHdrSettings(hdr);
        }
        ImGui::Separator();
        MpcPlayer::MlSettings ml{};
        if (SUCCEEDED(g_player.GetMlSettings(ml))) {
            ImGui::Checkbox("ML enhance", &ml.enable);
            if (ImGui::SliderFloat("Gamma", &ml.gamma, 0.5f, 1.5f)) g_player.SetMlSettings(ml);
            if (ImGui::SliderInt("Shadow", (int*)&ml.shadow, 0, 4)) g_player.SetMlSettings(ml);
            if (ImGui::SliderFloat("Contrast", &ml.contrast, 0.0f, 0.5f)) g_player.SetMlSettings(ml);
        }
    }
    ImGui::End();

    // BOTTOM â€” TRANSPORT
    const char* stateN = sn.state == MpcPlayer::State::Playing ? "PLAYING"
                       : sn.state == MpcPlayer::State::Paused   ? "PAUSED"
                       : sn.state == MpcPlayer::State::Stopped  ? "STOPPED" : "â€¦";
    char posb[64]; snprintf(posb, sizeof(posb), "%02d:%02d:%02d",
        (int)(sn.position / 10000000 / 3600), (int)(sn.position / 10000000 / 60 % 60),
        (int)(sn.position / 10000000 % 60));
    ImGui::SetNextWindowPos  (ImVec2(8, vp->WorkSize.y - 48), ImGuiCond_Always);
    ImGui::SetNextWindowSize (ImVec2(vp->WorkSize.x - 16, 40), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.75f);
    RecordPanel(8, (int)vp->WorkSize.y - 48, (int)vp->WorkSize.x - 16, 40);
    if (ImGui::Begin("TRANSPORT", nullptr, ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize |
                      ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoTitleBar)) {
        ImGui::TextUnformatted(stateN);
        ImGui::SameLine(100.0f); ImGui::TextUnformatted(posb);
        ImGui::SameLine(230.0f); ImGui::TextUnformatted("Up: toggle HUD  Space: play/pause  Esc: quit");
    }
    ImGui::End();
}

// ---------------------------------------------------------------------------
int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int)
{
    std::wstring device = L"DeckLink Quad HDMI Recorder (1)";
    {
        int argc = 0;
        LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        for (int i = 1; i + 1 < argc; ++i) {
            if (_wcsicmp(argv[i], L"--decklink-device") == 0) device = argv[i + 1];
        }
        LocalFree(argv);
    }

    // Primary display fullscreen
    const int mw = GetSystemMetrics(SM_CXSCREEN), mh = GetSystemMetrics(SM_CYSCREEN);
    CreateWindows(inst, mw, mh);
    if (!g_videoHwnd || !g_hudHwnd) { MessageBoxA(nullptr, "window create failed", "s3hud", MB_OK); return 1; }

    // Engine â€” direct, self-healing (monitor â†’ executor rebuilds internally)
    {
        g_player.SetLogSink([](const char* line) {
            if (FILE* f = _wfopen(L"s3hud_diag.log", L"a")) { fputs(line, f); fputc('\n', f); fclose(f); }
            OutputDebugStringA(line);
            OutputDebugStringA("\n");
        });
        HRESULT hrA = g_player.AttachRenderTarget(g_videoHwnd);
        HRESULT hrR = g_player.SetRenderer(MpcPlayer::Renderer::MPCVR);
        OutputDebugStringA("s3hud: attach+renderer set\n");
        if (!device.empty()) {
            const HRESULT hrD = g_player.SetDecklinkCapture(device);
            OutputDebugStringA("s3hud: SetDecklinkCapture done\n");
            char b[96]; snprintf(b, sizeof(b), "  hr attach=0x%08X renderer=0x%08X dl=0x%08X\n",
                (unsigned)hrA, (unsigned)hrR, (unsigned)hrD);
            OutputDebugStringA(b);
        }
    }

    if (!InitD3D(g_hudHwnd, mw, mh)) {
        char err[128];
        snprintf(err, sizeof(err), "d3d init failed (hr=0x%08X)", (unsigned)g_d3dFailHr);
        OutputDebugStringA(err); OutputDebugStringA("\n");
        MessageBoxA(nullptr, err, "s3hud", MB_OK);
        return 1;
    }

    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.FontGlobalScale = 1.25f;
    // Manual input bridge: no Win32 backend, so we must own DisplaySize — a
    // (0,0) DisplaySize makes ImGui's NewFrame sanity check assert
    // ("Invalid DisplaySize value!", the bench assert we just hit).
    io.DisplaySize = ImVec2((float)mw, (float)mh);
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui_ImplDX11_Init(g_d3d, g_d3dCtx);
    ImGui::StyleColorsDark();

    g_hook = SetWindowsHookExW(WH_KEYBOARD_LL, LowLevelKeyboardProc, GetModuleHandleW(nullptr), 0);

    // Start engine self-heal launch now that renderer is attached + windows up
    // (SetDecklinkCapture already ran above; the monitor's first confirmed lock
    //  â†’ executor â†’ Open happens on its own).

    bool running = true;
    DWORD lastStatsMs = 0;
    while (running) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
            if (msg.message == WM_QUIT) { applog("[APP] loop exit via WM_QUIT"); running = false; }
        }
        if (!running) break;

        // --- input bridge (independent of Windows focus) ---
        POINT pt; GetCursorPos(&pt);
        ScreenToClient(g_hudHwnd, &pt);
        io.AddMousePosEvent((float)pt.x, (float)pt.y);
        io.AddMouseButtonEvent(0, (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0);
        io.AddMouseButtonEvent(1, (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0);
        io.AddMouseButtonEvent(2, (GetAsyncKeyState(VK_MBUTTON) & 0x8000) != 0);

        {
            std::lock_guard<std::mutex> lk(g_keyMtx);
            while (!g_keys.empty()) {
                const int vk = g_keys.front(); g_keys.pop_front();
                switch (vk) {
                case VK_UP:    g_showPanels = !g_showPanels; break;
                case VK_ESCAPE: applog("[APP] loop exit via Esc"); running = false; break;
                case VK_SPACE: {
                    MpcPlayer::Snapshot s{}; g_player.GetSnapshot(s);
                    if (s.state == MpcPlayer::State::Playing) g_player.Pause();
                    else g_player.Play();
                    break;
                }
                case VK_LEFT: {
                    MpcPlayer::Snapshot s{}; g_player.GetSnapshot(s);
                    g_player.Seek(s.position - 50000000); break;
                }
                case VK_RIGHT: {
                    MpcPlayer::Snapshot s{}; g_player.GetSnapshot(s);
                    g_player.Seek(s.position + 50000000); break;
                }
                default: break;
                }
                io.AddKeyEvent(ImGuiKey_UpArrow, vk == VK_UP);
                io.AddKeyEvent(ImGuiKey_DownArrow, vk == VK_DOWN);
                io.AddKeyEvent(ImGuiKey_LeftArrow, vk == VK_LEFT);
                io.AddKeyEvent(ImGuiKey_RightArrow, vk == VK_RIGHT);
            }
        }

        // --- frame ---
        {
            // Refresh DisplaySize each frame; guard against 0 (hidden/minimized
            // windows on startup) — ImGui asserts on a non-positive DisplaySize.
            RECT rc; GetClientRect(g_hudHwnd, &rc);
            const float dw = (float)(rc.right - rc.left), dh = (float)(rc.bottom - rc.top);
            if (dw > 0 && dh > 0) io.DisplaySize = ImVec2(dw, dh);
        }
        ImGui_ImplDX11_NewFrame();
        ImGui::NewFrame();
        if (g_showPanels) RenderHud();
        ImGui::Render();
        const float clear[4] = { 0, 0, 0, 0 };
        g_d3dCtx->OMSetRenderTargets(1, &g_rtv, nullptr);
        g_d3dCtx->ClearRenderTargetView(g_rtv, clear);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
        const HRESULT hrP = g_swap->Present(1, 0);
        if (hrP == DXGI_ERROR_DEVICE_REMOVED || hrP == DXGI_ERROR_DEVICE_RESET) {
            char b[96]; snprintf(b, sizeof(b), "[APP] loop exit via present failure hr=0x%08X", (unsigned)hrP);
            applog(b);
            running = false;
        }

        if (GetTickCount() - lastStatsMs > 500) {   // stats refresh cadence
            lastStatsMs = GetTickCount();
            g_player.RefreshLive();
        }
    }

    g_player.Shutdown();
    if (g_hook) UnhookWindowsHookEx(g_hook);
    ImGui_ImplDX11_Shutdown();
    ImGui::DestroyContext();
    return 0;
}
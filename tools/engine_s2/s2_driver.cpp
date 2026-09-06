#include "MpcPlayer.h"

#include <atlbase.h>
#include <windows.h>

#include <iostream>

namespace {

const wchar_t* kClassName = L"MpcS2Host";
MpcPlayer* g_player = nullptr;

const char* StateName(MpcPlayer::State state)
{
    switch (state) {
    case MpcPlayer::State::Idle: return "idle";
    case MpcPlayer::State::Opening: return "opening";
    case MpcPlayer::State::Paused: return "paused";
    case MpcPlayer::State::Playing: return "playing";
    case MpcPlayer::State::Stopped: return "stopped";
    case MpcPlayer::State::Ended: return "ended";
    case MpcPlayer::State::Error: return "error";
    }
    return "unknown";
}

void PrintResult(const char* op, HRESULT hr)
{
    std::cout << op << " hr=0x" << std::hex << static_cast<unsigned long>(hr) << std::dec << "\n";
}

LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        HBRUSH b = CreateSolidBrush(RGB(0, 0, 0));
        FillRect(dc, &ps.rcPaint, b);
        DeleteObject(b);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_SIZE:
        if (g_player) {
            g_player->ResizeVideo();
        }
        return 0;
    case WM_TIMER:
        if (wp == 1) {
            KillTimer(hwnd, 1);
            PostMessageW(hwnd, WM_CLOSE, 0, 0);
        }
        // wp == 2: periodic tick for event pump / snapshot polling (driven in main loop)
        return 0;
    case WM_KEYDOWN:
        if (wp == VK_ESCAPE) {
            PostMessageW(hwnd, WM_CLOSE, 0, 0);
        }
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

HWND CreateHostWindow(HINSTANCE inst)
{
    WNDCLASSEXW wc = {sizeof(wc)};
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.lpszClassName = kClassName;
    RegisterClassExW(&wc);

    RECT r = {0, 0, 960, 540};
    AdjustWindowRectEx(&r, WS_OVERLAPPEDWINDOW, FALSE, 0);
    return CreateWindowExW(0, kClassName, L"MPC-HC S2 — engine visible",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left, r.bottom - r.top,
        nullptr, nullptr, inst, nullptr);
}

}

int wmain(int argc, wchar_t* argv[])
{
    const wchar_t* mediaPath = nullptr;
    MpcPlayer::Renderer renderer = MpcPlayer::Renderer::Auto;
    int durationSec = 0;    // 0 = play to EOF
    int volume = 100;
    bool mute = false;
    for (int i = 1; i < argc; ++i) {
        if (_wcsicmp(argv[i], L"--renderer") == 0 && i + 1 < argc) {
            const wchar_t* v = argv[++i];
            if (_wcsicmp(v, L"vmr9") == 0) renderer = MpcPlayer::Renderer::VMR9;
            else if (_wcsicmp(v, L"evr") == 0) renderer = MpcPlayer::Renderer::EVR;
            else if (_wcsicmp(v, L"mpcvr") == 0) renderer = MpcPlayer::Renderer::MPCVR;
            else if (_wcsicmp(v, L"auto") == 0) renderer = MpcPlayer::Renderer::Auto;
        } else if (_wcsicmp(argv[i], L"--duration") == 0 && i + 1 < argc) {
            durationSec = _wtoi(argv[++i]);
        } else if (_wcsicmp(argv[i], L"--volume") == 0 && i + 1 < argc) {
            volume = _wtoi(argv[++i]);
        } else if (_wcsicmp(argv[i], L"--mute") == 0) {
            mute = true;
        } else if (!mediaPath) {
            mediaPath = argv[i];
        }
    }
    if (!mediaPath) {
        std::wcerr << L"usage: s2_driver.exe [--renderer auto|vmr9|evr|mpcvr]"
                      L" [--duration N] [--volume 0..100] [--mute] <media-file>\n";
        return 2;
    }

    const HRESULT initResult = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(initResult)) {
        PrintResult("CoInitializeEx", initResult);
        return 1;
    }

    HINSTANCE inst = GetModuleHandleW(nullptr);
    HWND host = CreateHostWindow(inst);
    if (!host) {
        std::cerr << "CreateHostWindow failed\n";
        CoUninitialize();
        return 1;
    }

    int exitCode = 0;
    {
        MpcPlayer player;
        g_player = &player;

        player.SetEventCallback([](std::string_view eventName, const MpcPlayer::Snapshot& snap) {
            std::cout << "event=" << eventName << " state=" << StateName(snap.state)
                      << " pos=" << snap.position << " dur=" << snap.duration << "\n";
        });

        player.AttachRenderTarget(host);
        player.SetRenderer(renderer);
        player.SetVolume(volume);
        player.SetMuted(mute);

        HRESULT hr = player.Open(mediaPath);
        PrintResult("open", hr);
        if (SUCCEEDED(hr)) {
            hr = player.Play();
            PrintResult("play", hr);
        }

        if (SUCCEEDED(hr)) {
            if (durationSec > 0) {
                SetTimer(host, 1, static_cast<UINT>(durationSec) * 1000u, nullptr);
            }
            SetTimer(host, 2, 100, nullptr);   // event pump
            MSG msg;
            while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
                if (g_player) g_player->PumpEvents();
                MpcPlayer::Snapshot s;
                g_player->GetSnapshot(s);
                if (s.state == MpcPlayer::State::Ended) {
                    PostMessageW(host, WM_CLOSE, 0, 0);
                }
            }
        }

        std::cout << "snapshot=" << player.SnapshotJson() << "\n";
        hr = player.Stop();
        PrintResult("stop", hr);
        exitCode = SUCCEEDED(hr) ? 0 : 1;

        g_player = nullptr;
    }

    DestroyWindow(host);
    UnregisterClassW(kClassName, inst);
    CoUninitialize();
    return exitCode;
}

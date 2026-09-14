#include "DeckLinkMonitor.h"

#include <cstdarg>
#include <cstdio>

namespace {
// 1.5 s grace for HDMI blinks (mirrors the mpv app's _dl_unlock_timer).
constexpr int kUnlockGraceMs = 1500;
} // namespace

// decklink_monitor VFSignalInfo layout (must match decklink_monitor.c):
// 0=colorspace 1=dynamic_range 2=pixel_depth 3=chroma 4=locked 5=width
// 6=height 7=frame_rate_num 8=frame_rate_den 9=interlace 10=field_dominance

void DeckLinkMonitor::Log(const char* fmt, ...)
{
    if (!logSink_) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    logSink_(buf);
}

DeckLinkMonitor::DeckLinkMonitor() = default;
DeckLinkMonitor::~DeckLinkMonitor() { Stop(); }

bool DeckLinkMonitor::EnsureLoaded()
{
    Log("[DECKLINK][monitor] EnsureLoaded begin (dllLoaded=%d)", (int)dllLoaded_);
    if (dllLoaded_) return true;

    // Prefer the DLL next to the executable; fall back to PATH.
    char path[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, path, sizeof(path));
    char* slash = strrchr(path, '\\');
    if (slash) {
        strcpy_s(slash + 1, MAX_PATH - (slash + 1 - path), "decklink_monitor.dll");
        dll_ = LoadLibraryA(path);
    }
    if (!dll_) dll_ = LoadLibraryA("decklink_monitor.dll");
    if (!dll_) {
        Log("[DECKLINK][monitor] LoadLibraryA failed err=%lu", (unsigned long)GetLastError());
        return false;
    }

    fnOpen_       = (FnOpen)GetProcAddress(dll_, "vf_dl_open");
    fnSignalInfo_ = (FnSignalInfo)GetProcAddress(dll_, "vf_dl_get_signal_info");
    fnBuildUrl_   = (FnBuildUrl)GetProcAddress(dll_, "vf_dl_build_url");
    fnClose_      = (FnClose)GetProcAddress(dll_, "vf_dl_close");
    fnEnum_       = (FnEnumDevices)GetProcAddress(dll_, "vf_dl_enumerate_devices");
    Log("[DECKLINK][monitor] loaded dll=%p open=%p signal=%p buildUrl=%p close=%p enum=%p",
        (void*)dll_, (void*)fnOpen_, (void*)fnSignalInfo_, (void*)fnBuildUrl_, (void*)fnClose_, (void*)fnEnum_);

    dllLoaded_ = fnOpen_ && fnBuildUrl_;   // close/signal can be null-tolerant
    return dllLoaded_;
}

int DeckLinkMonitor::EnumerateDevices(std::vector<std::string>& out)
{
    out.clear();
    if (!EnsureLoaded() || !fnEnum_) {
        Log("[DECKLINK][monitor] EnumerateDevices: enum export unavailable");
        return -1;
    }
    constexpr int kMaxDevs = 16;
    char names[kMaxDevs][64] = {};
    int  ports[kMaxDevs] = {};
    int  n = fnEnum_(names, ports, kMaxDevs);
    if (n < 0) { Log("[DECKLINK][monitor] EnumerateDevices failed rc=%d", n); return n; }
    for (int i = 0; i < n && i < kMaxDevs; ++i) {
        out.emplace_back(names[i]);   // one entry per HDMI input port
        Log("[DECKLINK][monitor] EnumerateDevices[%d]='%s' ports=%d", i, names[i], ports[i]);
    }
    Log("[DECKLINK][monitor] EnumerateDevices found %d device(s)", n);
    return n;
}

bool DeckLinkMonitor::Start(const std::string& deviceName, int pollMs)
{
    Log("[DECKLINK][monitor] Start device='%s' pollMs=%d", deviceName.c_str(), pollMs);
    if (running_) {
        Log("[DECKLINK][monitor] Start already running — returning true");
        return true;
    }
    if (!EnsureLoaded()) {
        Log("[DECKLINK][monitor] Start FAILED — decklink_monitor.dll not loaded");
        return false;
    }

    device_ = deviceName;
    pollMs_ = pollMs > 0 ? pollMs : 500;
    stop_ = false;
    running_ = true;
    lastLocked_ = -1;
    lastMode_ = -1;
    lastColorSpace_ = -1;
    lastDynamicRange_ = -1;

    thread_ = std::thread([this] { Loop(); });
    Log("[DECKLINK][monitor] Start OK — poll thread launched");
    return true;
}

void DeckLinkMonitor::Stop()
{
    stop_ = true;
    if (thread_.joinable()) {
        Log("[DECKLINK][monitor] Stop joining poll thread");
        thread_.join();
    }
    running_ = false;
    if (fnClose_) fnClose_();
    Log("[DECKLINK][monitor] Stop complete");
}

int DeckLinkMonitor::MapIcs(const SignalInfo& si) const
{
    // 0=Auto 1=601 2=709 3=2020-SDR 4=2020-PQ 5=2020-HLG (ICS_* in IVideoRenderer.h)
    if (!si.locked) return 0;
    switch (si.colorspace) {
    case 0:  return 1;  // Rec.601
    case 2:  // Rec.2020
        switch (si.dynamic_range) {
        case 1: return 4; // PQ
        case 2: return 5; // HLG
        default: return 3; // 2020-SDR (incl. DV-on-HDMI heuristic)
        }
    default: return 2;  // Rec.709
    }
}

void DeckLinkMonitor::Loop()
{
    // open is retried every kOpenRetryPolls polls until it succeeds, so a
    // card that is not present / not ready at startup is picked up later.
    constexpr int kOpenRetryPolls = 4;    // 4 * pollMs = 2 s at 500 ms
    int openFailures = 0;
    bool opened = false;
    if (fnOpen_) {
        const int rc = fnOpen_(device_.empty() ? nullptr : device_.c_str());
        opened = (rc == 0);
        Log("[DECKLINK][monitor] vf_dl_open rc=%d%s", rc, opened ? "" : " (retrying)");
        if (!opened) openFailures = 1;
    } else {
        Log("[DECKLINK][monitor] vf_dl_open unavailable");
    }

    int unlockedSince = 0;   // consecutive ms signal reported as unlocked
    int pollCount = 0;
    while (!stop_) {
        const DWORD t0 = GetTickCount();
        Sleep(pollMs_);
        pollCount++;

        // Retry the device open periodically (covers driver-not-ready, HDMI
        // port power-up, and the no-DeckLink-present case while testing).
        if (!opened && fnOpen_ && (pollCount % kOpenRetryPolls) == 0) {
            const int rc = fnOpen_(device_.empty() ? nullptr : device_.c_str());
            opened = (rc == 0);
            Log("[DECKLINK][monitor] vf_dl_open retry #%d rc=%d%s",
                ++openFailures, rc, opened ? " -> opened" : "");
            if (opened) {
                unlockedSince = 0;
                lastLocked_ = -1;
                lastColorSpace_ = -1;
                lastDynamicRange_ = -1;
            }
        }
        if (!opened) {
            Log("[DECKLINK][monitor] poll: device not opened yet (card absent or busy) - skipping");
            continue;
        }

        SignalInfo si = {};
        if (!fnSignalInfo_ || fnSignalInfo_(reinterpret_cast<int*>(&si)) != 0) {
            Log("[DECKLINK][monitor] poll: vf_dl_get_signal_info FAILED (device not opened yet?)");
            { std::lock_guard<std::mutex> lk(lock_); lastReadOk_ = false; }
            continue;   // not opened / read failed — retry next tick
        }
        {
            std::lock_guard<std::mutex> lk(lock_);
            lastInfo_ = si;
            lastReadOk_ = true;
        }

        // Verbose per-poll trace — every field the hardware reports, gated on
        // frame-log equivalent (the sink only writes when the shell wants it).
        Log("[DECKLINK][monitor] poll: locked=%d cs=%d dr=%d depth=%d chroma=%d | %dx%d %d/%dfps il=%d lockedSince=%d",
            si.locked, si.colorspace, si.dynamic_range, si.pixel_depth, si.chroma,
            si.width, si.height, si.frame_rate_num, si.frame_rate_den,
            si.interlace, unlockedSince);

        // signal_loss debounce: HDMI blinks report locked=0 briefly.
        if (!si.locked) {
            unlockedSince += pollMs_;
            if (unlockedSince < kUnlockGraceMs) {
                Log("[DECKLINK][monitor] unlock grace holding... unlockedSince=%d", unlockedSince);
                continue;
            }
            Log("[DECKLINK][monitor] signal loss CONFIRMED after grace (%d ms)", unlockedSince);
        } else {
            if (unlockedSince >= kUnlockGraceMs)
                Log("[DECKLINK][monitor] signal re-acquired (was lost for %d ms)", unlockedSince);
            else if (unlockedSince > 0)
                Log("[DECKLINK][monitor] brief unlock recovered within grace (%d ms)", unlockedSince);
            unlockedSince = 0;
        }

        bool changed = false;
        if (si.locked != lastLocked_) { changed = true; lastLocked_ = si.locked; }

        // Map change detection: colorspace or dynamic range shifting is the
        // "movie→menu" switch even when the mode fourcc stays the same (e.g.
        // DV→SDR changes colorspace while DR stays 0).
        if (si.colorspace != lastColorSpace_) { changed = true; lastColorSpace_ = si.colorspace; }
        if (si.dynamic_range != lastDynamicRange_) { changed = true; lastDynamicRange_ = si.dynamic_range; }

        if (changed) {
            Log("[DECKLINK][monitor] CHANGE detected (locked=%d cs=%d dr=%d) — arming 1 s stability gate",
                si.locked, si.colorspace, si.dynamic_range);
        }

        // Stability gate (DESIGN.md): a state is armed as a candidate and only
        // becomes a command once it has been observed continuously for >=
        // kSustainMs AND it differs from the last commanded state. HDMI
        // detection can flicker (menu↔movie flapping); a state that flaps and
        // returns to the already-commanded one must NOT command again — only a
        // genuinely different state that holds 1 s commands. This keeps an
        // unstable wire from repeatedly tearing down a running graph.
        const int key = (si.locked << 16) | ((si.colorspace & 0xff) << 8) | (si.dynamic_range & 0xff);
        if (key != lastSeenKey_) {                 // the wire changed since the last poll
            lastSeenKey_ = key;
            if (key != lastCmdKey_) candidateSince_ = GetTickCount();  // new state → arm window
            else candidateSince_ = MAXDWORD;                           // back to committed state → pin
        }
        if (key != lastCmdKey_ && restartCb_ &&
            (GetTickCount() - candidateSince_) >= kSustainMs) {
            lastCmdKey_ = key;                     // command this state out — no repeat until a different one
            lastSeenKey_ = key;
            candidateSince_ = MAXDWORD;
            Log("[DECKLINK][monitor] state confirmed (held >= %u ms) → command", (unsigned)kSustainMs);
            RestartRequest req;
            req.signalLost = !si.locked;
            req.ics = MapIcs(si);
            if (fnBuildUrl_ && si.locked) {
                char url[512] = {};
                const int n = fnBuildUrl_(device_.empty() ? nullptr : device_.c_str(), url, sizeof(url));
                Log("[DECKLINK][monitor] vf_dl_build_url n=%d url='%s'", n, n > 0 ? url : "(empty)");
                if (n > 0) req.url = url;
            }
            restartCb_(req);
        }

        if (GetTickCount() - t0 > 2000)
            Log("[DECKLINK][monitor] WARNING: poll iteration took %u ms (poll budget exceeded)",
                (unsigned)(GetTickCount() - t0));
    }

    Log("[DECKLINK][monitor] loop exiting");
    if (fnClose_) fnClose_();
}
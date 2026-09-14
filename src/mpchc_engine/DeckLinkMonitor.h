#pragma once

// DeckLink HDMI signal monitor — polls decklink_monitor.dll (read-only
// IDeckLinkStatus) on a worker thread and reports signal/format changes so the
// player can restart the capture graph with the new mode + colour space.
//
// The monitor NEVER touches the DirectShow graph — it only invokes the restart
// callback. The caller is responsible for marshalling that to its UI thread
// (the s3_shell posts a WM_APP message).

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <windows.h>

class DeckLinkMonitor {
public:
    // ics uses the MPCVR ICS_* enum (IVideoRenderer.h): Auto/601/709/2020_*.
    struct RestartRequest {
        std::string url;    // decklink://<device>?... full URL for the new mode
        int ics = 0;        // 0 = Auto
        bool signalLost = false;
    };
    struct SignalInfo {     // mirrors decklink_monitor VFSignalInfo (extended)
        int colorspace = 1;    // 0=601 1=709 2=2020
        int dynamic_range = 0; // 0=SDR 1=PQ 2=HLG
        int pixel_depth = 8;
        int chroma = -1;       // 1=RGB444 0=YCbCr422
        int locked = 0;
        int width = 0, height = 0;
        int frame_rate_num = 0, frame_rate_den = 0;
        int interlace = 2;   // 0=prog 1=interlaced 2=unknown
    };

    using RestartCallback = std::function<void(const RestartRequest&)>;
    using LogSink = std::function<void(const char*)>;   // timestamp-free; caller adds time

    DeckLinkMonitor();
    ~DeckLinkMonitor();

    void SetLogSink(LogSink sink) { logSink_ = std::move(sink); }

    DeckLinkMonitor(const DeckLinkMonitor&) = delete;
    DeckLinkMonitor& operator=(const DeckLinkMonitor&) = delete;

    // Open the named device and start polling every pollMs.
    bool Start(const std::string& deviceName, int pollMs = 500);
    void Stop();

    // Enumerate DeckLink devices the monitor dll can see (used to wire
    // VP -> HDMI when no --decklink-device was passed on the CLI). Returns
    // device display names (UTF-8), generally one per HDMI input port.
    int EnumerateDevices(std::vector<std::string>& out);

    void SetRestartCallback(RestartCallback cb) { restartCb_ = std::move(cb); }
    bool IsRunning() const { return running_; }
    // Latest signal snapshot read by the poll thread (LIVE panel). Copy under
    // the monitor mutex; fields are unchanged after a failed read.
    bool GetLastSignalInfo(SignalInfo& out) const
    {
        std::lock_guard<std::mutex> lk(lock_);
        out = lastInfo_;
        return lastReadOk_;
    }

private:
    void Loop();
    bool EnsureLoaded();           // LoadLibrary decklink_monitor.dll + resolve exports
    int  MapIcs(const SignalInfo&) const;  // colorspace×DR → ICS_*

    // decklink_monitor.dll exports (cdecl)
    using FnOpen = int(__cdecl*)(const char*);
    using FnSignalInfo = int(__cdecl*)(int*);   // VFSignalInfo fields
    using FnBuildUrl = int(__cdecl*)(const char*, char*, size_t);
    using FnClose = void(__cdecl*)();
    using FnEnumDevices = int(__cdecl*)(char(*)[64], int*, int); // names, ports[], max
    FnOpen      fnOpen_ = nullptr;
    FnSignalInfo fnSignalInfo_ = nullptr;
    FnBuildUrl  fnBuildUrl_ = nullptr;
    FnClose     fnClose_ = nullptr;
    FnEnumDevices fnEnum_ = nullptr;
    HMODULE     dll_ = nullptr;
    bool        dllLoaded_ = false;

    std::thread thread_;
    std::atomic<bool> running_ = false;
    std::atomic<bool> stop_ = false;
    RestartCallback restartCb_;
    LogSink logSink_;
    std::string device_;
    int pollMs_ = 500;
    void Log(const char* fmt, ...);   // routes to logSink_ (no-op when unset)

    // last-read signal snapshot for the LIVE panel (guarded)
    mutable std::mutex lock_;
    SignalInfo lastInfo_ = {};
    bool lastReadOk_ = false;

    // last-seen state for change detection
    int lastLocked_ = -1;
    int lastMode_ = -1;
    int lastColorSpace_ = -1;
    int lastDynamicRange_ = -1;
    // 1-second stability gate (DESIGN.md): armed when the wire state CHANGES
    // (lastSeenKey_) to something different from the last commanded state
    // (lastCmdKey_); a command fires once that state holds for kSustainMs. A
    // state returning to the already-committed one never re-fires.
    static constexpr DWORD kSustainMs = 1000;
    int   lastSeenKey_ = -999;
    int   lastCmdKey_ = -999;
    DWORD candidateSince_ = MAXDWORD;
};
#pragma once

// DeckLink HDMI signal monitor — polls decklink_monitor.dll (read-only
// IDeckLinkStatus) on a worker thread and publishes a SETTLED FACT about the
// wire. It measures; it decides nothing.
//
// CONTRACT (component boundary, 2026-09-21):
//   in  : the device
//   out : SignalFact — published only for a state that held for kSustainMs
//   never: touches the DirectShow graph, blocks, or commands another component
//
// It used to hand out a RestartRequest, i.e. it told the engine to rebuild. That
// made a measurer a lifecycle decider. It now publishes the measurement; the
// IngestController decides and the ops-queue executor acts.

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <windows.h>

class DeckLinkMonitor {
public:
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

    // The FACT. Everything here is measured or derived from the device; none of it
    // is an instruction. `url` and `ics` are derivations the DLL glue owns (they
    // need the open device), not decisions — the controller may ignore them.
    struct SignalFact {
        SignalInfo sig{};
        std::string url;        // decklink://<device>?... for the settled format
        int ics = 0;            // MPCVR ICS_* hint (IVideoRenderer.h) — advice only
        unsigned long long seq = 0;   // monotonic; lets a consumer spot reordering
    };

    using FactCallback = std::function<void(const SignalFact&)>;
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

    void SetFactCallback(FactCallback cb) { factCb_ = std::move(cb); }
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

    // What "the state changed" means. The gate key MUST carry the FORMAT, not
    // just locked/cs/dr: a 4K movie → 1080p disc menu keeps cs and dr identical,
    // so a key without the dimensions never changes, no fact is ever published,
    // and the graph is left holding a stale media type — the size gate then drops
    // every frame and the picture stays black for the whole menu. interlace is in
    // here for the same reason (1080i ↔ 1080p).
    struct FactKey {
        int locked = 0, colorspace = 0, dynamic_range = 0;
        int width = 0, height = 0, fpsNum = 0, fpsDen = 0, interlace = 0;
        bool operator==(const FactKey& o) const {
            return locked == o.locked && colorspace == o.colorspace &&
                   dynamic_range == o.dynamic_range && width == o.width &&
                   height == o.height && fpsNum == o.fpsNum &&
                   fpsDen == o.fpsDen && interlace == o.interlace;
        }
        bool operator!=(const FactKey& o) const { return !(*this == o); }
    };
    static FactKey KeyOf(const SignalInfo& si);

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
    FactCallback factCb_;
    LogSink logSink_;
    std::string device_;
    int pollMs_ = 500;
    void Log(const char* fmt, ...);   // routes to logSink_ (no-op when unset)

    // last-read signal snapshot for the LIVE panel (guarded)
    mutable std::mutex lock_;
    SignalInfo lastInfo_ = {};
    bool lastReadOk_ = false;

    // last-seen state for change detection
    int lastMode_ = -1;
    // 1-second stability gate: a state is armed as a candidate when the wire
    // CHANGES (lastSeenKey_) to something different from the last state a FACT was
    // published for (lastCmdKey_); the fact is published once that state has been
    // observed for >= kSustainMs AND on at least kSustainSamples polls, so a slow
    // or blocked read cannot make one sample look like sustained observation.
    // A state returning to the already-published one never re-fires.
    static constexpr DWORD kSustainMs      = 1000;
    static constexpr int   kSustainSamples = 2;
    FactKey lastSeenKey_;
    FactKey lastCmdKey_;
    bool    seenValid_ = false;
    bool    cmdValid_  = false;
    DWORD   candidateSince_   = MAXDWORD;
    int     candidateSamples_ = 0;
    unsigned long long factSeq_ = 0;   // monotonic fact sequence (poll thread only)
};
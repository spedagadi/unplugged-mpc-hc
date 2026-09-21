#pragma once

// IngestController — the SINGLE ingestion authority. Facts in, intent out.
//
// Why this exists (2026-09-21): the engine had no decider. The signal monitor
// both measured AND told the engine to rebuild, and a delivery watchdog inferred
// a lifecycle decision from a frozen frame counter. Every component that can
// decide when to tear the graph down is a component that can crash the process,
// and it made "one graph owner" unenforceable in practice.
//
// CONTRACT (component boundary):
//   in  : DeckLinkMonitor::SignalFact  — a SETTLED wire state, already gated by
//         the monitor (held >= 1 s over >= 2 polls), so every fact here is
//         genuinely a new stable state. That is why this class owns NO threshold
//         of its own: it does not judge whether a change is real, only what it
//         means.
//   out : Decision{Launch|Reload|Stop} — an INTENT. It never touches the graph,
//         the card, or the renderer, and it cannot act on its own intent: the
//         ops-queue executor is the only thing that creates or destroys a graph.
//   back: OnIngestActive() — the owner reports whether ingestion is running, so
//         this class can tell "start" from "restart" without learning anything
//         about graphs, filters or pins.
//
// It runs on its own thread so a slow or blocked caller cannot stall a decision,
// and OnFact() never blocks: it records and wakes.

#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

#include "DeckLinkMonitor.h"

class IngestController {
public:
    enum class Intent {
        None,     // nothing to do (e.g. locked but no usable URL yet)
        Launch,   // begin ingesting the settled format
        Reload,   // the settled format changed — rebuild onto it
        Stop      // the signal is gone for good — tear ingestion down
    };

    static const char* IntentName(Intent i);

    struct Decision {
        Intent intent = Intent::None;
        std::string url;            // Launch / Reload only
        int  ics = 0;               // the monitor's hint; the executor re-derives
        unsigned long long seq = 0; // the fact this came from (traceability)
    };

    using DecisionSink = std::function<void(const Decision&)>;
    using LogSink      = std::function<void(const char*)>;

    IngestController() = default;
    ~IngestController();

    IngestController(const IngestController&) = delete;
    IngestController& operator=(const IngestController&) = delete;

    void SetLogSink(LogSink s) { log_ = std::move(s); }
    void SetDecisionSink(DecisionSink s) { sink_ = std::move(s); }

    void Start();
    void Stop();

    // From the monitor's poll thread. Non-blocking. Records the fact and wakes
    // the decider — it does not decide here, and it never acts.
    void OnFact(const DeckLinkMonitor::SignalFact& f);

    // From the graph owner: is ingestion currently running? Lets the decider
    // choose Launch vs Reload without knowing what a graph is.
    void OnIngestActive(bool active) { ingestActive_ = active; }

private:
    void Loop();
    void Emit(Intent intent, const DeckLinkMonitor::SignalFact& f, const char* why);
    void Log(const char* fmt, ...);

    std::thread             thread_;
    std::atomic<bool>       stop_{ false };
    std::atomic<bool>       ingestActive_{ false };
    std::mutex              mtx_;
    std::condition_variable cv_;
    bool                    haveFact_ = false;
    DeckLinkMonitor::SignalFact fact_{};

    DecisionSink sink_;
    LogSink      log_;
};
#include "IngestController.h"

#include <cstdarg>
#include <cstdio>
#include <windows.h>

const char* IngestController::IntentName(Intent i)
{
    switch (i) {
    case Intent::Launch: return "Launch";
    case Intent::Reload: return "Reload";
    case Intent::Stop:   return "Stop";
    default:             return "None";
    }
}

IngestController::~IngestController()
{
    Stop();
}

void IngestController::Start()
{
    if (thread_.joinable()) return;
    stop_ = false;
    thread_ = std::thread([this]() { Loop(); });
    Log("[INGEST] decider started");
}

void IngestController::Stop()
{
    {
        std::lock_guard<std::mutex> lk(mtx_);
        stop_ = true;
        haveFact_ = false;
    }
    cv_.notify_all();
    if (thread_.joinable()) thread_.join();
    Log("[INGEST] decider stopped");
}

void IngestController::OnFact(const DeckLinkMonitor::SignalFact& f)
{
    // Record and wake. Deliberately no decision and no action on this thread: it
    // is the monitor's poll thread, and a measurer must not be able to run a
    // chain of consequences from its own callback.
    Log("[INGEST] RECEIVED fact seq=%llu (on the monitor's thread; deciding on ours)", f.seq);
    {
        std::lock_guard<std::mutex> lk(mtx_);
        if (haveFact_ && f.seq < fact_.seq) {
            // A newer fact is already queued — this one is stale (facts are
            // latest-wins). Worth seeing: it means the monitor is publishing
            // faster than we decide, which is a different problem from a stall.
            Log("[INGEST] DROP stale fact seq=%llu (already holding seq=%llu)", f.seq, fact_.seq);
            return;
        }
        fact_ = f;                 // latest wins — the queue coalesces too
        haveFact_ = true;
    }
    cv_.notify_one();
}

void IngestController::Loop()
{
    for (;;) {
        DeckLinkMonitor::SignalFact f{};
        {
            std::unique_lock<std::mutex> lk(mtx_);
            cv_.wait(lk, [this] { return stop_ || haveFact_; });
            if (stop_) break;
            f = fact_;
            haveFact_ = false;
        }

        const auto& s = f.sig;
        // Deciding, and the two inputs the decision actually turns on. The
        // logged `wasIngesting` is the whole reason Launch and Reload differ —
        // without it a "Reload when it should have been Launch" looks arbitrary.
        Log("[INGEST] DECIDING seq=%llu  locked=%d cs=%d dr=%d %dx%d %d/%d il=%d  wasIngesting=%d  url='%s'",
            f.seq, s.locked, s.colorspace, s.dynamic_range,
            s.width, s.height, s.frame_rate_num, s.frame_rate_den, s.interlace,
            ingestActive_ ? 1 : 0, f.url.c_str());

        // The monitor already settled this state, so this is a pure mapping from
        // meaning to intent. No threshold lives here.
        if (!s.locked) {
            // Sustained loss — the monitor confirmed it past its own grace.
            if (ingestActive_) Emit(Intent::Stop, f, "signal lost");
            else               Log("[INGEST] signal lost while not ingesting — nothing to do");
            continue;
        }

        if (f.url.empty()) {
            // Locked, but no usable URL was derived — nothing actionable yet.
            // Emitting anything here would tear down a working graph on a
            // detail we do not actually have.
            Emit(Intent::None, f, "locked but no URL derived");
            continue;
        }

        Emit(ingestActive_ ? Intent::Reload : Intent::Launch, f,
             ingestActive_ ? "settled format changed" : "first settled lock");
    }
    Log("[INGEST] decider loop exiting");
}

void IngestController::Emit(Intent intent, const DeckLinkMonitor::SignalFact& f, const char* why)
{
    if (intent == Intent::None) return;
    if (!sink_) {
        Log("[INGEST] no decision sink installed — dropping %s", IntentName(intent));
        return;
    }
    Decision d;
    d.intent = intent;
    d.url    = f.url;
    d.ics    = f.ics;
    d.seq    = f.seq;
    Log("[INGEST] DECISION %s (%s) ics=%d url='%s' — handing to the graph owner "
        "(boundary: decider→executor)", IntentName(intent), why, d.ics, d.url.c_str());
    sink_(d);   // posts to the graph owner; returns immediately
    Log("[INGEST] DECISION %s handed off (executor accepted the op)", IntentName(intent));
}

void IngestController::Log(const char* fmt, ...)
{
    if (!log_) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    log_(buf);
}
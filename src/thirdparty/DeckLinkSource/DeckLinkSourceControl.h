// DeckLinkSourceControl.h — engine → DeckLinkSource.ax control interface.
//
// Deliberately minimal: no ATL, no DirectShow, no DeckLink headers, so both the
// engine (mpchc_engine) and the filter (DeckLinkSource.cpp) can include it.
// The IID comes from __declspec(uuid) — use __uuidof(IDeckLinkSourceControl).

#pragma once

#ifndef __DeckLinkSourceControl_h__
#define __DeckLinkSourceControl_h__

#include <windows.h>

// Log callback driven by the filter's capture/session telemetry. ctx is the
// opaque handle passed to SetLogSink (the engine passes its MpcPlayer*).
typedef void(__cdecl* DeckLinkSourceLogFn)(void* ctx, const char* line);

// Live capture snapshot (LIVE panel / CHAIN + CAPTURE INPUT rows). C-layout so
// the engine can read it without DeckLink types.
struct DeckLinkSourceStats {
    unsigned long long framesArrived = 0;    // SDK frames seen
    unsigned long long framesDelivered = 0;  // frames pushed to the renderer
    unsigned long long framesSkipped = 0;    // not delivered (inactive or gate)
    unsigned long long droppedQueue = 0;     // forwarder queue full → dropped the newest
    unsigned long long gateDropped = 0;      // skipped: dims != connected media type
    unsigned long long renegotiations = 0;   // worker restarts on a real mode change
    unsigned long long formatEvents = 0;     // VideoInputFormatChanged calls
    int  width = 0;                          // last detected/connected mode
    int  height = 0;
    int  fpsNum = 50000;                     // rate = fpsNum/fpsDen (e.g. 24000/1001)
    int  fpsDen = 1000;
    int  colorspace = 0;                     // 0=unknown 1=BT.601 2=BT.709 3=BT.2020
    int  eotf = 0;                           // 0=gamma 2=PQ 3=HLG 4=DV(PQ-coded, no static HDR flag)
    int  streaming = 0;                      // card is streaming
    unsigned long long lastRefUs = 0;        // hwRef of last captured frame (wall-aligned µs)

    // HDR static metadata (ST 2086) the card parsed from the HDMI HDR InfoFrame.
    //
    // This DOES work over HDMI. The old "the card cannot supply ST 2086" note was
    // wrong twice over: the twelve ST 2086 metadata IDs are FLOAT-typed and were
    // being read with GetInt, and the probe that reported them ran once per session
    // on frame 1 — before the signal settles, when every read returns E_UNEXPECTED.
    // Measured 2026-09-18 on an HDR10 disc: MaxCLL 300, MaxFALL 237, mastering
    // 1000 / 0.0001 nits, all S_OK, agreeing with the HDFury's own readout.
    //
    // hasHdrStaticMeta is plausibility-gated in GetStats, so a zero MaxCLL means
    // "no usable reading yet" — never "this signal is SDR".
    int   hasHdrStaticMeta = 0;
    float hdrMaxCLL = 0.0f;                  // MaxCLL, nits
    float hdrMaxFALL = 0.0f;                 // MaxFALL, nits
    float hdrMasteringMaxNits = 0.0f;        // mastering display peak, nits
    float hdrMasteringMinNits = 0.0f;        // mastering display black, nits
};

// Format-change notification (the SDK's VideoInputFormatChanged, propagated
// from the filter's worker — never from the SDK callback thread). The engine
// uses it to gracefully rebuild the capture graph so the NEW format drives
// ingestion; this REPLACES the old decklink_monitor polling (removed).
typedef void(__cdecl* DeckLinkRestartFn)(void* ctx);

// {A13F5876-CC46-45D4-9379-C9D130BBB749}
interface __declspec(uuid("A13F5876-CC46-45D4-9379-C9D130BBB749"))
IDeckLinkSourceControl : public IUnknown
{
    // Begin ingest on the named DeckLink capture input (display-name substring
    // is accepted; an empty name picks the first device). BLOCKS until the first
    // detected format is known (bounded wait) so the graph can connect with the
    // real media type instead of defaults. Safe to call again only after a
    // StopCapture (or on a fresh filter instance).
    STDMETHOD(StartCapture(BSTR deviceName)) PURE;

    // PHASE 1 of teardown (DESIGN.md ordered script): halt delivery at the
    // SDK — SetCallback(nullptr) so no new frames can enter, then flags+wake so
    // the forwarder drains/abandons and the worker runs its StopStreams path.
    // NO joins, never waits on the renderer, safe from any thread. Must precede
    // any graph teardown that drops this filter's last reference.
    STDMETHOD(StopDelivery()) PURE;

    // PHASE 2-3: complete teardown. Join the forwarder + worker (the caller
    // must have run StopDelivery AND disconnected this source's output pin from
    // the renderer first, so an in-flight Deliver returns immediately), then
    // release the SDK objects. Idempotent; StopCapture() == StopDelivery() +
    // Join... so calling this twice is safe.
    STDMETHOD(StopCapture()) PURE;

    // Route the filter's telemetry to the caller's logging (frames arrived /
    // skipped / delivered, worker starts, mode changes — everything that makes
    // the decklink monitor → source → renderer chain observable). ctx is echoed
    // back to fn verbatim; may be null. Without a sink the lines go to
    // OutputDebugStringA.
    STDMETHOD(SetLogSink(void* ctx, DeckLinkSourceLogFn fn)) PURE;

    // Live capture snapshot for the LIVE panel (frames/gate/renegotiations +
    // current detected mode + last hwRef). Safe to call anytime while the
    // session exists; returns S_FALSE when no capture is attached.
    STDMETHOD(GetStats(DeckLinkSourceStats* pStats)) PURE;

    // Push the signal's actual colour space / EOTF into the media type the
    // filter advertises. The DeckLink streams YCbCr whose true primaries are
    // not visible to the capture path (a live status query there stalled the
    // driver), but the engine's signal monitor knows them (bt2020/pq etc.).
    // colorspace: 0=unknown 1=BT.601 2=BT.709 3=BT.2020 · eotf: 0=gamma 2=PQ 3=HLG.
    // Safe anytime; takes effect on the media type at the next GetMediaType.
    STDMETHOD(SetSignalMeta(int colorspace, int eotf)) PURE;

    // Arm the format-change notification. fn(ctx) is called from the filter's
    // WORKER thread after a REAL display-mode change has been detected and the
    // card renegotiated — the engine should Stop→Open the graph (the call
    // itself is non-blocking; the filter never waits on the caller).
    STDMETHOD(SetRestartCallback(void* ctx, DeckLinkRestartFn fn)) PURE;
};

#endif // __DeckLinkSourceControl_h__
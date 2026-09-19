# DeckLink ingest — pipeline design (monitor as master)

Owner: HTPC DeckLink chain (UB820 HDMI → DeckLinkSource → MPCVR → display).
Status: signed off; implemented in stages. Monitor is the ONLY decision-maker
about the HDMI signal. NO code path may second-guess it.

## Roles

| Component | Role | Constraint |
|---|---|---|
| decklink_monitor (poll 500ms) | MASTER: observes lock/cs/dr/mode/dims; emits a command on a *confirmed stable* change | NEVER touches the graph, NEVER blocks |
| Ops queue (engine, ONE executor thread) | The ONLY piece that mutates card + graph. Every rebuild/stop/launch is an op executed FIFO here. All other threads POST ops, never execute | One transition at a time; per-op ordered script (below); ops coalesce (latest command wins) |
| DeckLinkSource.ax (filter) | Captures at the command's meta; exposes StopDelivery (halt at SDK, NO join) vs JoinCaptureThreads (join, executor-only, after disconnect) | Gate-drop = safety net only |
| s3_shell (UI) | Relays monitor→ops queue; paints; reads stats | Never calls Open()/Stop() on the UI thread for decklink; never blocks on the card |

## State machine

IDLE --monitor: first *confirmed* lock--> LAUNCH --> RUNNING
RUNNING --monitor: cs/dr/dims/lock changed (confirmed)--> TERMINATE --> RELAUNCH
any --monitor: sustained locked=0--> TERMINATE --> IDLE

LAUNCH = Open(url)+StartCapture (real format)+connect+Play, meta baked in.

## TERMINATE — the ordered teardown script (ONE executor thread runs ALL of it)

Order is the whole design. Any deviation re-opens the movie→menu hang. Each
step runs to completion before the next.

```
1. STOP the feeder at the source, instantly:
     decklinkControl->StopDelivery()
       = SetCallback(nullptr)          // SDK stops invoking us — nothing new enters
       + stopPending/quit/active flags + wake (forwarder drains, worker exits)
       + StopStreams() + DisableVideoInput()
     NO joins here. Safe from any thread; never waits on the renderer.
2. Quiesce the renderer path:
     disconnect the decklink source pin from the renderer's input pin
     (IPin disconnect). An in-flight Deliver now returns immediately.
3. Join the source's threads. SAFE ONLY AFTER 1+2:
     decklinkControl->StopCapture()  (= StopDelivery no-op + join forwarder
     + join worker + release SDK objects). Bounded wait: on timeout the
     threads are ABANDONED, never waited on forever.
4. Recheck input format: the op carries the monitor's confirmed meta
   (mode/cs/eotf/ics after its >=1s gate); re-read status is allowed, never
   blocking on the SDK callback thread.
5. Launch the new graph: fresh filter instance (fresh SDK session = clean),
   StartCapture, connect, Play.
```

WHY ordering is fatal (the 2026-09-14 hang): tearing the graph without step 1
means the filter destructor — running on whatever thread dropped the last ref,
historically the UI or a .detach() thread — joins the forwarder while it is
inside Deliver() into the renderer that same thread is destroying. A join into
a live receive is not resolvable by any lock/ordering other than stopping the
feeder and disconnecting the receiver first.

## Invariants (must hold; they are the whole point of the design)

1. A monitor command ALWAYS executes (no suppression / no "looks the same").
2. Stability gate: a state must be observed continuously >= 1 s (2+ equal
   polls) before it becomes a command. Flapping never flushes the pipeline;
   latest-observed state wins when it settles.
3. Coalesce, don't veto: a command mid-transition updates the target meta; the
   executor re-runs with the latest command when the current transition ends.
4. ONE graph owner: the ops-queue executor thread. UI, monitor, and filter
   callbacks only POST operations. No .detach() threads, no UI-thread Open().
5. StopDelivery precedes every join; disconnect precedes every join; joins are
   bounded (timeout → abandon). Never create a thread whose exit waits on a
   thread that is inside the component the waiting path destroys.
6. Post is non-blocking and mergeable: a burst of confirmed commands settles
   into one rebuild, executed exactly once, in order.

## Sources of ops (who posts what — the only legal initiators)

| Source | Op |
|---|---|
| monitor (its thread) → shell → engine | Rebuild{url, meta} (never Open directly) |
| filter restart callback / gate-throttle (filter worker) | Rebuild{} (post only — never a direct engine call) |
| s3_shell UI commands | Stop / Rebuild / ApplyIcs |
| executor | executes; also owns the initial LAUNCH |

## Keep (already built, proven, non-negotiable)

- Monitor 1 s stability gate (feeds the op's meta).
- Enable-retry (500 ms) for card lock convergence.
- Forwarder bounded drop-newest queue (streaming backpressure).
- Graph lock around Open/Stop/Play/Seek (belt under the single-owner).
- UI reads only the live-stats cache.

## Stages (delivery order)

1. Stable signal: monitor first confirmed lock → LAUNCH → video visible.
2. Stop (UB820 menu flip): monitor change → graceful terminate, no freeze.
3. Relaunch on the confirmed new meta; cycle repeats.
Verify each stage before moving on. Video must be visibly playing at the end
of stage 1.
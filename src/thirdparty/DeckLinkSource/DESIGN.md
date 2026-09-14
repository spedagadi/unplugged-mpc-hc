# DeckLink ingest — pipeline design (monitor as master)

Owner: HTPC DeckLink chain (UB820 HDMI → DeckLinkSource → MPCVR → display).
Status: signed off; implemented in stages. Monitor is the ONLY decision-maker
about the HDMI signal. NO code path may second-guess it.

## Roles

| Component | Role | Constraint |
|---|---|---|
| decklink_monitor (poll 500ms) | MASTER: observes lock/cs/dr/mode/dims; emits a command on a *confirmed stable* change | Never touches the graph |
| Executor (engine, one serialized path) | Runs the command: terminate → (old session released) → launch | One transition at a time; latest command wins |
| DeckLinkSource.ax (filter) | Captures at the command's meta; no opinion on format changes | Gate-drop = safety net only |
| s3_shell (UI) | Relays monitor→UI→executor; paints; reads stats | Never blocks on the card |

## State machine

IDLE --monitor: first *confirmed* lock--> LAUNCH --> RUNNING
RUNNING --monitor: cs/dr/dims/lock changed (confirmed)--> TERMINATE --> RELAUNCH
any --monitor: sustained locked=0--> TERMINATE --> IDLE

LAUNCH = Open(url)+StartCapture (real format)+connect+Play, meta baked in.
TERMINATE = graceful: async Inactive; old filter retired off-thread; launch
waits until the old session's StopStreams has returned (card free).

## Invariants (must hold; they are the whole point of the design)

1. A monitor command ALWAYS executes (no suppression / no "looks the same").
2. Stability gate: a state must be observed continuously >= 1 s (2+ equal
   polls) before it becomes a command. Flapping never flushes the pipeline;
   latest-observed state wins when it settles.
3. Coalesce, don't veto: a command mid-transition updates the target meta; the
   executor re-runs with the latest command when the current transition ends.
4. One executor: all transitions serialized by the graph lock.

## Deleted second-authority experiments (do not resurrect)

- Filter restart callback (SetRestartCallback) / gate-throttle rebuilds.
- Engine "delivered advancing" guard / filter-driven restart worker.
- Shell restart suppression globals (g_buildCs/g_buildDr/RecordGraphOpen).

## Keep (already built, proven, non-negotiable)

- Async Inactive (never block the UI on the card).
- Off-thread filter retirement (retire list).
- Graph lock around Open/Stop/Play/Seek.

## Stages (delivery order)

1. Stable signal: monitor first confirmed lock → LAUNCH → video visible.
2. Stop (UB820 menu flip): monitor change → graceful terminate, no freeze.
3. Relaunch on the confirmed new meta; cycle repeats.
Verify each stage before moving on. Video must be visibly playing at the end
of stage 1.
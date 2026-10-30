# Unplugged UI contract (v2.0.0)

Status: **draft for approval.** No code is changed against this document until it is approved.

Scope: the UI composition and its interaction rules. Files: `tools/native_ui/native_ui.cpp`,
`src/mpchc_engine`, `unplugged-VideoRenderer`.

This document exists because two days were spent patching symptoms of a composition that was
never defined. Everything below is a **requirement** (what the app must do), an **invariant**
(a property that makes a class of failure impossible), or a **rule of change** (how work is
done so the two days are not repeated). If a change cannot be justified against this document,
it is not made.

---

## 1. Definitions

- **Frame** - the single top-level window of the app (`CMainFrame`).
- **Chrome** - the panels: top strip, transport bar, status rail, settings rail.
- **Pane** - one chrome panel; a child window of the frame.
- **View / host** - `g_host`, the child window the renderer draws into. MPCVR parents its own
  drawing window to it.
- **Picture rect** - the rectangle inside the window that belongs to the picture (destination
  rect).
- **Band** - the region of the window owned by one chrome panel.
- **Capture graph** - the live DeckLink graph (VideoProcessor mode). Its streaming thread holds
  the renderer's lock while presenting.
- **Deferred rect** - a picture-rect request stored by the renderer and applied by its render
  thread.

---

## 2. Requirements

### 2.1 Layout

- **L1.** The window is divided into non-overlapping areas: one band per visible chrome panel,
  and the remainder is the picture rect.
- **L2.** The chrome is never drawn over the picture, and the picture is never drawn over the
  chrome.
- **L3.** The picture keeps its shape: the same aspect, crop and NLS warp whether or not a rail
  is visible. Only its size on screen changes.
- **L4.** No control is laid out in a region the Windows shell can cover; the taskbar band is
  excluded from layout.
- **L5.** The layout is computed in exactly one place (`Layout()`), from the window size and the
  current panel visibility. No other code positions windows.

### 2.2 Interaction

- **I1.** The chrome has exactly ONE up/down state (`m_uiUp`), changed in exactly one place
  (`SetUi`). While it is up and something is showing (video processor, or file playback with no
  card up) it auto-hides after 2.5 s with no pointer or keyboard activity; any activity re-arms
  the deadline. Hiding is unconditional: EVERY pane goes, the status and settings rails included,
  together with any help card, tip or overlay. This is the operator's requirement (2026-10-30) and
  replaces the earlier "static chrome" rule.
- **I2.** Panel visibility changes through an explicit user action (Info / Settings / Up / F1 /
  Esc) or the idle deadline above. There is no hover reveal; the only pointer gesture is the
  bottom-edge band, which raises the transport bar while the chrome is down.
- **I2a.** Settings cards and dialogs suspend the idle deadline; the library screen owns its own
  chrome and never auto-hides.
- **I3.** Every control that is drawn does something. A control with no meaning in the current
  mode is not drawn.
- **I4.** Clicking a control always produces its action. No visible control is inert.
- **I5.** Global keys work regardless of focus: F2 (VideoProcessor), F3 (media player),
  F5 (restart capture), Up/Esc, N.
- **I6.** The cursor is the system's, except over playing video: it hides after 2.5 s idle and
  returns on any pointer movement or when the chrome is up.
- **I7.** Panels talk to the frame only by posting `WM_APP+n`. A pane never reaches into the
  frame, the engine, or another panel.

### 2.3 Real-time behaviour (this is a live TV path)

- **R1.** The UI thread never calls into the renderer: not for geometry, not for stats, not for
  resize.
- **R2.** The picture rect may change at any moment, including while a capture graph is
  streaming, without blocking, freezing, or dropping the graph.
- **R3.** No chrome operation may cause a swap-chain resize (`ResizeBuffers`).
- **R4.** A freeze is a release blocker; a slow frame is not.

### 2.4 Modes

- **M1.** VideoProcessor mode (live capture): the transport bar offers only controls that are
  meaningful there (Restart, mode switch, NLS). The mode switch must always be usable - it is
  the way out of a failed capture.
- **M2.** Media player mode (file playback): full transport controls.
- **M3.** The rails are available in both modes and are the route to settings.
- **M4.** Switching modes restarts the graph; two graphs never run.

---

## 3. Invariants and the failures they prevent

Each invariant makes a class of failure impossible, rather than unlikely.

| # | Invariant | Failure class removed (all observed 29-30 Oct) |
|---|---|---|
| V1 | One rectangle per owner: chrome bands and picture rect are disjoint by construction. | Chrome visible but dead because the renderer's window owned the chrome pixels (`WindowFromPoint` returned `VRWindow` at strip, bar and rails). |
| V2 | One chrome state (`SetUi`); the idle deadline is the only automatic hide and hides every pane; the bottom edge is the only reveal gesture. | Chrome that disagrees with the screen; a reveal that cannot be re-entered; an auto-hide that leaves the app looking dead. |
| V3 | One top-level window; panes and host are its children; cards are transient. | Activation split: a chrome click activated a second top-level, the frame went inactive, the keyboard died. |
| V4 | No UI-thread call into the renderer; picture-rect changes are deferred to the render thread. | Freeze inside `SetWindowPosition` / `SetDestinationPosition` during capture (Windows `AppHangB1`; log stops dead at the moment of a chrome change). |
| V5 | The layout excludes the taskbar band. | Transport bar laid out under `Shell_TrayWnd`: play, seek, volume and both mode buttons were clicks on the taskbar. |
| V6 | The picture rect is computed from the bands, never from the window. | Chrome toggles re-warping the picture (ragged text) because the geometry canvas changed with the chrome. |

---

## 4. Composition

Windows:

1. **Frame** - the only top-level window owned by the app.
2. **Top strip** - child, band: top.
3. **Status rail** - child, band: left (only when enabled).
4. **Settings rail** - child, band: right (only when enabled).
5. **Transport bar** - child, band: bottom, above the taskbar band.
6. **Video host** - child, rectangle: the remainder. MPCVR's drawing window is created by MPCVR
   and parented to the host.
7. **Cards** (confirm, setup, folders, help, preset, toast, title, splash, library, acquire,
   tips) - transient top-level popups opened on demand.

Rules:

- The host is a child of the frame and always corresponds to the **picture rect**, not the
  window. The host's client rect is the engine's geometry canvas.
- The engine sizes the renderer's window to the host **once per graph**, in
  `ConfigureRendererWindow`. That is the only place a renderer window size is set.
- The picture rect is applied through the **deferred rect** path: the UI requests it; the
  render thread applies it before the next frame.

Why this is mpc-hc's composition: controls own their bands, the view is the remainder, the view
is never resized during playback in a way that touches the swap chain, and there is one input
window hierarchy. We differ only in that the renderer accepts the new rectangle asynchronously,
because our renderer also serves a live capture.

---

## 5. Required change in the renderer (the missing piece)

`unplugged-VideoRenderer`, `CMpcVideoRenderer`:

- `SetDestinationPosition` and `SetVideoPosition` must **store** the requested rectangle and
  return immediately. No `m_RendererLock` acquisition on the caller's thread.
- The render thread applies the stored rectangle at the start of its next render, where it
  already owns the renderer.
- No window resize and no `ResizeBuffers` on this path.

This is what makes **R2** true, and therefore what makes live rail toggling possible in
VideoProcessor mode. Without it the only honest options are "rails cannot toggle during
capture" or "rails over the picture"; both are rejected.

---

## 6. Component audit

| Component | Decision | Note |
|---|---|---|
| `CUiWnd`, drawing/text helpers, `CardAA` | keep | pure; no chrome knowledge |
| `CTopStrip`, `CStatusRail`, `CSettingsRail`, `CTransportBar` | keep | self-contained; talk to the frame only via `WM_APP+n` |
| Cards (confirm, setup, folders, help, preset, toast, title, splash, library, acquire, tips) | keep | transient popups |
| Settings / preset / INI / library store | keep | data layer |
| Engine bridge (`Cmd`, status parsing) | keep | with rule R1 enforced |
| `CMainFrame` chrome section: layout, visibility state, three timers, reveal gesture, pointer sampler, cursor ownership, z-order re-raise | replace | the tangle that caused the two days |
| `TID_CHROME`, `TID_POINTER`, `ChromeTimerArm/Stop`, `OnChromeIdle`, `PointerSample`, `EdgeCheck`, `InBottomDock`, `SetUi`/`ApplyChrome` state, cursor machinery, `videorect`/refit path | delete | mostly already removed; the refit path is replaced by the deferred rect |
| Single file layout of `native_ui.cpp` (~7k lines) | defer | housekeeping after release; not a blocker |

---

## 7. Out of scope for v2.0.0

- Hover reveal (the bottom-edge band is the only pointer gesture). Auto-hide IS in scope: see I1.
- NLS kernel upgrade (bilinear to Catmull-Rom). Current state: bilinear, compiled and injected.
- Dolby Vision P5 plumbing.
- Splitting `native_ui.cpp` into multiple translation units.
- Porting the panes to MFC `CControlBar` subclasses. The composition matters, not the base
  class.

---

## 8. Acceptance tests (objective; run by product)

Layout

- **A1.** With rails on and off, no chrome pixel hit-tests to the video window, and no video
  pixel hit-tests to a pane.
- **A2.** Toggling any rail leaves the picture's shape unchanged (aspect and NLS identical);
  only its size changes.
- **A3.** Every transport-bar control responds while the taskbar is visible.

Interaction

- **A4.** Every drawn control produces its action, in both modes, in one pass: Info, Settings,
  Preset, Min, Close, Restart, VideoProcessor, Media player, NLS, play, pause, seek, volume,
  mute, one settings row, one library tile, Stop.
- **A5.** Nothing changes on a timer: leaving the app untouched for five minutes leaves the
  chrome exactly as it was.
- **A6.** F2 / F3 / F5 / Up / Esc / N work with any panel focused.

Real-time

- **A7.** Toggle Info and Settings repeatedly (at least ten times) during a live DeckLink
  capture: no freeze, capture continues, UI stays responsive.
- **A8.** Leave a capture running for 30 minutes: no UI stalls, no graph restarts.

---

## 9. Rules of change (so the two days are not repeated)

1. **No change without an invariant.** Every edit names the requirement or invariant it serves,
   or it is not made.
2. **One change per build**, with its acceptance test stated before the build.
3. **No new state.** A timer, a flag or a "mode" is added only when a requirement cannot be met
   without it, and the addition is called out for approval.
4. **No new instrumentation** to explain a failure unless an acceptance test failed; the
   instrument is removed once the cause is fixed.
5. **"Fixed" means product confirmed it** - not that a log looked right.
6. **Revert on failure.** No building on a step that did not pass its test. The pre-surgery
   backup `native_ui.cpp.bak-int-removal` is kept until sign-off.

---

## 10. Open items requiring product approval

| # | Item | Proposal | If unanswered |
|---|---|---|---|
| O1 | VP transport bar contents | Draw only Restart, VideoProcessor, Media player, NLS. Play/seek/volume/mute not drawn in VP. | Keep current (drawn, disabled, logged) |
| O2 | Renderer change scope | Deferred destination rect as in section 5; rebuild `MpcVideoRenderer64.ax`. | Do not ship the layout change without it |
| O3 | Release gate | Sign-off requires A1-A8 to pass. Anything not passing ships disabled, not hidden. | - |

---

## 11. Appendix - measured failures this contract is built on

| When | Measurement | Consequence |
|---|---|---|
| 29 Oct 22:15 | `AppHangB1` in `Unplugged.exe`; log stops at `video rect ->` | UI-thread renderer call froze the app |
| 30 Oct 10:26 | `(1720,1402) -> Shell_TrayWnd rect=(0,1392)-(3440,1440)` | transport bar and mode buttons under the taskbar |
| 30 Oct 11:07 | `strip`, `bar`, `video` all hit-test to `VRWindow` | renderer window above every pane; chrome owned by the picture |
| 30 Oct 10:28 | `[strip] press (250,16) -> info` then `ui: live status shown` | the strip works when a press reaches it |
| 30 Oct 10:33 | `[GEOM] client=3436x1332` vs `3436x1436` | chrome changed the NLS canvas; picture re-warped (ragged text) |
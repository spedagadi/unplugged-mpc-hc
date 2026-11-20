# Unplugged 2.3.0 — complete audit, by reporter

2026-11-20 · working tree `zion-s3-shell` + renderer `zion-ml-phase0`.

This is the single view of every report and request gathered for the 2.3.0 cycle,
including the projector/10-bit work and the ClipGuard 2.60/2.62 hand-off. The
existing files stay as the detailed evidence:
[USER-REPORTS.md](USER-REPORTS.md), [FEEDBACK-AUDIT-2.3.0.md](FEEDBACK-AUDIT-2.3.0.md),
[NLS-ASPECT-TEST-PLAN.md](NLS-ASPECT-TEST-PLAN.md), [SUBTITLE-AUDIT.md](SUBTITLE-AUDIT.md).

**Status legend**

| Status | Meaning |
| --- | --- |
| **Fixed** | Root cause fixed, built, and deployed to the dev machine. |
| **Verified** | The reporter or a field test confirmed the fix. |
| **Retest** | Fixed but the reporter has not confirmed on their setup. |
| **Open** | Not fixed. |
| **Limitation** | External to the app, or by design; documented in the guide. |
| **On hold** | Agreed but not scheduled. |
| **Unsupported** | Feature does not exist. |

## Summary

| Ref | Reporter | Type | Area | Status |
| --- | --- | --- | --- | --- |
| UR-0001 | legeirk | Bug | Library / UNC share | **Fixed + Verified** |
| UR-0002 | legeirk | Bug | Graph open on a K-Lite machine (`0x80040217`) | **Open** — needs 2.3.0 reproduction |
| UR-0003 | va_lemon | Bug/Feature | Static nits step 5; merge nits rows | **Fixed** — step 1; merge not applicable |
| UR-0004 | va_lemon | Bug | 4K output 3831×2152 instead of 3840×2160 | **Fixed + Verified** |
| UR-0005 | VHT | Bug/Feature | Internal subtitles show nothing | **Internal Fixed + Verified**; external **Unsupported** |
| UR-0006 | Unnamed | Bug | Video Processor dead after wiping settings | **Fixed + Verified** |
| UR-0007 | ramiroalvaro.ra / sammy1001 | Feature | Aspect-aware NLS (2.00 / IMAX / native 16:9) | **Fixed + Field-verified** |
| UR-0008 | sammy1001 | Bug | FFTB "glowing rectangle" on a projector | **Fixed (DWM ring)**; retest pending |
| UR-0009 | va_lemon | Feature | Webhook / Home Assistant metrics | **On hold** |
| UR-0010 | va_lemon | Feature | Keyboard-only slider adjustment | **Fixed**; retest pending |
| UR-0011 | va_lemon | Bug | No frame-rate matching (everything 60 Hz) | **Fixed + Projector-verified** |
| UR-0012 | Unnamed (2.1.0 feedback) | Feature | SDR → BT.2020 missing | **Fixed** — unified Display gamut |
| UR-0013 | Unnamed (2.1.0 feedback) | Bug | No frame-rate change | Duplicate of UR-0011 — **Fixed** |
| UR-0014 | Unnamed (2.1.0 feedback) | Bug | Playback controls disabled | **Open** — diagnostics bundle needed |
| UR-0015 | Unnamed (2.1.0 feedback) | Bug/Taste | "madVR looks better; colours off; crushed dark detail" | **Open** — needs a same-title A/B bundle |
| UR-0016 | Sateesh | Bug | ML grade on/off flashed a wrong frame | **Fixed** — renderer transition copy |
| UR-0017 | Sateesh | Bug | NLS scope sections kept their bars; scope tuning lost | **Fixed + Verified** |
| UR-0018 | Sateesh | Bug/Feature | Projector 10-bit / Auto gamut / washed-out colour | **Fixed** — one Display gamut axis; display-side limit documented |
| UR-0019 | Sateesh (audit) | Bug | 8-bit SDR source stayed 8-bit on a 10-bit display | **Fixed** — renderer Auto follows the link |
| UR-0020 | Sateesh | Bug | Update card showed raw markdown | **Fixed + Verified** |
| UR-0021 | Sateesh / Peter Biancardi | Bug | Property page still carried ClipGuard controls | **Fixed** — controls removed |
| UR-0022 | Peter Biancardi | Feature | ClipGuard 2.60.0 + 2.62.0 integration | **Merged**; field test pending |
| UR-0023 | Sateesh | Bug | ClipGuard overlay may sit under the bottom bar | **Open** — verify placement |
| UR-0024 | Sateesh | Limitation | NVIDIA forced 8 bpc caps WCG at 8-bit | **Limitation** — documented |
| UR-0025 | Sateesh | Limitation | SDR BT.2020 auto-switch is display-dependent | **Limitation** — documented |
| UR-0026 | Sateesh (audit) | Risk | ClipGuard shared-memory version not checked | **Open (low)** |
| UR-0027 | Sateesh / Peter Biancardi | Design | ClipGuard.exe outranks the app when running | **By design** — notice not yet added |
| UR-0028 | Sateesh | Bug | Playback keys leaked from the open settings pane; a paused frame stepped (looked like playback) and Enter toggled pause | **Fixed** |
| UR-0029 | Sateesh | Bug | Engine auto-selected the first subtitle track on graph open | **Fixed** |
| UR-0030 | Sateesh | Clarification | NLS turned on around Ctrl+S captures | **Not a bug** — `N` is the NLS key; Ctrl+S does not touch it |

## New in this cycle (19–20 November)

### UR-0016 — ML grade toggle flashed a wrong frame (Sateesh)
**Symptom.** Toggling ML grade with the panels open showed one ugly frame before
the new state settled.
**Cause.** `UpdateMLActive()` reset the per-activation state and the post-scale
step count changed; the first frame after the transition ran the grade shaders
with reset parameters.
**Fix.** Renderer `dff277d`: a one-frame transition flag makes the ML steps run
through the copy shader; the bars pass is excluded from both the step count and
the render side so the pipeline stays aligned.
**State.** Fixed, deployed. Reporter retest pending.

### UR-0017 — NLS scope sections kept their bars (Sateesh)
**Symptom.** Spider-Man: Far From Home in scope kept the letterbox; entering an
IMAX section showed 100 % removal, and the scope tuning was thrown away when it
was edited during an IMAX cut.
**Cause.** The aspect rule held a snapshot of *Bars removed* captured on first
apply (it was 0), and slider edits were only captured while the scope window was
active; the code path was in the toggle handler, not `PushRow`, so slider drags
never reached it. Preset autosave could also write the forced window values back
over the tuning.
**Fix.** App `ee6058df5`: **Scope bar removal** row (default 100 %), edits
captured in every window with the window override immediately re-imposed, preset
autosave writes the tuning instead of the forced value, release restores it.
**Evidence.** `nlsaspect: 2.415 -> scope (bars=100 …)`, `1.941 -> small-bars`,
back to scope; reporter confirmed "it locks well".

### UR-0018 — 10-bit and projector gamut were a five-way guessing game (Sateesh)
**Symptom.** The projector on **Auto** presented an 8-bit PC EDID and treated
SDR BT.2020 as BT.709 (washed out). NVIDIA's depth box was greyed; the app's
`10-bit SDR` / `SDR BT.2020` / `Output gamut` rows could be combined into states
that could not work, and the retired **Output gamut** was still in the UI.
**Cause.** Three rows asked mechanism, not intent; the display's own EDID/gamut
is outside the app's control.
**Fix.** App `bc5becc42`, renderer `a9893cd`, guide `d55e21946`:
- One **Display gamut** row in HDR → Display Target (`Auto (BT.709)` / `BT.2020` /
  `DCI-P3`). It derives the output conversion, SDR P2020 declaration, WCG
  ownership (journaled and restored in both directions) and the 10-bit path.
- `10-bit SDR output`, `SDR signal: BT.2020` and `Output gamut` are internal
  (grade internals only); a one-time migration derives the new row from them.
- Renderer Auto now chooses a 10-bit internal format whenever the display link
  reports 10 bpc, not only when the source is >8-bit.
- The guide's 10-bit section is a three-step setup plus a short symptom table.
**Evidence.** `displaygamut: migrated outGamut=1 sdrBt2020=1 -> 1`,
`displaygamut: BT.2020 -> outGamut=1 sdrBt2020=1`, `output depth: 10-bit RGB WCG`.
Reporter confirmed the monitor reports `SDR, 10-bit` on BT.2020 and the colours
are sane.
**Remaining (UR-0025).** A display whose Auto gamut ignores SDR BT.2020 must be
forced to BT2020 manually; the app cannot change the display's EDID or gamut.

### UR-0019 — 8-bit SDR stayed 8-bit on a 10-bit display (audit)
**Cause.** `UpdateTexParams(AUTO)` looked only at the source depth, so an 8-bit
Blu-ray produced an 8-bit internal texture; `Preferred10BitOutput()` then kept
the swap chain 8-bit even though the link was 10-bit.
**Fix.** Renderer `a9893cd`: Auto also uses `m_DisplayBitsPerChannel >= 10`.
**State.** Fixed, built. Field test: play an 8-bit SDR title on the 10-bit link
and check the renderer frame log `swfmt=24` (R10G10B10A2).

### UR-0020 — Update card showed raw markdown (Sateesh)
**Fix.** App `3c4199f77`: release bodies are parsed into headings, bullets,
rules and table rows; inline markers, HTML tags/comments and links are reduced
to text; long notes word-wrap and scroll with the wheel, with a slim scrollbar.
The QA override (`ui.updateTestVersion`) now carries a markdown sample.
**State.** Verified by the reporter.

### UR-0021 — Property page still carried ClipGuard (Sateesh / Peter Biancardi)
**Fix.** Renderer `70ae00d`: ClipGuard controls and the stale "More ClipGuard
controls are in the Unplugged ClipGuard section" note removed; the page still
passes the stored ClipGuard block through. ClipGuard belongs to its companion
app.
**State.** Fixed, built.

### UR-0022 — ClipGuard 2.60.0 and 2.62.0 (Peter Biancardi)
**Merged.** `f945f9e` (2.60.0: `CClipGuard`, shared-memory ownership, LUT,
temporal dither, 13-slot look-ahead, F6 banner) and `d715f55` (2.62.0: LUT lookup
next to the filter then `%LOCALAPPDATA%\ClipGuard`; Test-only Source row removed).
Our ML-transition fix `dff277d` sits on top.
**Ownership.** `ClipGuard.exe` → native `Settings_t` block → `clipguard.ini`.
The app's ClipGuard rows are hidden; its hotkeys are inert while the companion is
running (UR-0027).
**Open checks.** Projector A/B of the 2.60 algorithm, look-ahead 12-frame memory,
overlay placement (UR-0023), `[CG]` cost.

### UR-0028 — playback keys leaked from the settings pane (Sateesh)
**Symptom.** With a frame paused, switching **Display gamut** made the picture
advance; Enter could start playback; subtitles and NLS appeared to change on
their own.
**Evidence.** `KEY vk=27` (Right) with **no** "settings rail consumed" line,
immediately followed by `[ENGINE] step dir=1`. The engine log also shows
`paused redraw after a geometry/settings change`: the pipeline never resumed —
the player was stepping frames. `KEY vk=20` (Space) toggles pause; `KEY vk=4E`
(N) is the NLS key and appears before each Ctrl+S capture.
**Cause — two, both real.**
1. **The graph rebuilt.** `out.sdrBt2020` was in the engine's rebuild-only list,
   so changing Display gamut tore the graph down and re-opened it; the re-open
   resumed at the current position, losing the pause:
   `settings: a rebuild-only row changed ...` then
   `[GRAPH] Open: resume at 2059.0 s`. This is the "video plays" that was
   reported.
2. **Keys leaked.** The settings rail consumed keys only after keyboard mode was
   armed (Tab or click). With the pane visible but not armed, Left/Right fell
   through to the player (`StepFrameKey` while paused) and Enter fell through to
   play/pause.
**Fix.**
- **Engine:** SDR BT.2020 is no longer held back. The renderer already applies it
  live (`Configure()` detects `bSdrBt2020`, sets `changeWindow`, and
  `InitSwapChain` re-creates the swap chain on the next frame), so no graph
  re-open occurs and the paused frame stays paused.
- **App `f8a4bb7a0`:** the first Left/Right arms the rail; option rows cycle
  with Left/Right/Enter; Enter is consumed instead of reaching the player.
**Related — UR-0029.** The engine auto-selected the first subtitle stream on
graph open; the app now owns the choice (default Off) and re-asserts it with
`subtrack enforce -1` when the engine differs.

## Existing reports — detail pointers

- **UR-0001 legeirk** — UNC root needs the trailing separator; verified by the
  reporter. See [USER-REPORTS.md](USER-REPORTS.md#ur-0001).
- **UR-0002 legeirk** — K-Lite codec-pack graph failure `0x80040217`; separate
  from UR-0001; needs a 2.3.0 engine run on a K-Lite machine.
- **UR-0003 va_lemon** — Static nits step is now 1; there is only one nits row,
  so there was nothing to merge.
- **UR-0004 va_lemon** — monitor-rect canvas; Source 1:1 at 3840×2160; verified.
- **UR-0005 VHT** — internal subtitle stack replaced with MPC-HC's; text subtitles
  verified. PGS/VobSub and scope-bar placement still need the spot-check. External
  subtitle files are **not supported**.
- **UR-0006 Unnamed** — wiped-profile Video Processor resolves the first/locked
  DeckLink port; verified per HANDOVER §3.8.
- **UR-0007 ramiroalvaro.ra / sammy1001** — aspect-aware NLS; field-verified on a
  real mixed-aspect title; Native is the symmetric branch.
- **UR-0008 sammy1001** — FFTB rectangle is DWM's 1–2 px light ring; `DONOTROUND`
  + `BORDER_COLOR = NONE`; ask for a retest on 2.3.0.
- **UR-0009 va_lemon** — webhook/Home Assistant publisher; **on hold** (design
  presented, no API agreed).
- **UR-0010 va_lemon** — Tab/shift focus, arrows step, Enter/double-click/F2
  exact entry; fixed, user retest pending.
- **UR-0011 va_lemon** — refresh matching in player and VP; verified on the
  projector at 4K23 (display ran 3840×2160@23).
- **UR-0012/0013 Unnamed (2.1.0)** — SDR→BT.2020 and no frame-rate change are
  addressed by Display gamut / refresh matching.
- **UR-0014/0015 Unnamed (2.1.0)** — disabled playback controls and "colours off /
  crushed dark / madVR better" need a diagnostics bundle and a same-title A/B.

## Open items and external limitations

| Item | Owner / reporter | Action |
| --- | --- | --- |
| UR-0002 K-Lite `0x80040217` | legeirk | Reproduce on 2.3.0 with K-Lite; capture `s3engine.log` and the Async Reader line |
| External subtitle files | VHT | Feature gap; no external-subtitle path |
| Webhook | va_lemon | On hold; publish nls.picAspect / refresh / colour space when resumed |
| Playback controls disabled | Unnamed (2.1.0) | Ask for the bundle; check whether a hung window or a disabled graph |
| "madVR looks better / colours off" | Unnamed (2.1.0) | Same-title A/B on 2.3.0; check Display gamut and 10-bit first |
| FFTB ring retest | sammy1001 | Retest on a 2.3.0 installer |
| ClipGuard overlay placement | Sateesh | Open overlay with the transport bar up; 2.60 anchors to the video rect, not the app safe area |
| ClipGuard look-ahead memory | Sateesh / Peter | 4K + 12-frame look-ahead: VRAM and drops; native settings cap at 6 |
| Shared-memory version | Sateesh | `ExeAlive()` checks magic + tick, not `version`; add a version check |
| ClipGuard ownership notice | Sateesh / Peter | App hotkeys are inert while ClipGuard.exe runs; add one notice or disable them |
| NVIDIA forced 8 bpc | Sateesh | Hard cap; WCG runs at 8-bit; documented in the guide |
| SDR BT.2020 auto-switch | Sateesh | Display-dependent; force the display to BT2020 and set Display gamut BT.2020 |
| 4K60 + 10-bit RGB | — | Exceeds HDMI 2.0; use YCbCr 4:2:2 at 60 Hz or 23/24 Hz |

## Release state (2026-11-20)

- **Shared installer (2026-11-19 21:51):** `distrib\out\Unplugged-setup-2.3.0.exe`,
  125,602,127 bytes, SHA-256 `3809414C0BD896F5ADE01513993C48001CBA18E7D2B2CB171D91C965FCAB5FA1`.
  It predates the ML flash fix, ClipGuard 2.62, the unified Display gamut, the
  renderer Auto fix, the markdown card and the rewritten guide.
- **Current tree:** app `bc5becc42` (unified gamut), `d55e21946` (guide),
  `3c4199f77` (markdown), `ee6058df5` (NLS scope); renderer `f945f9e` (2.60),
  `dff277d` (ML transition), `d715f55` (2.62), `a9893cd` (Auto 10-bit).
- **Tags:** app `v2.3.0` at `8df301f66` (initial 2.3.0 commit); renderer
  `v2.3.0` at `70ae00d`. Neither has been moved to the current tree.
- **Next:** rebuild the installer from the current tree, update the release-note
  hash, move both `v2.3.0` tags to the release commits, then field-test the
  remaining rows above.
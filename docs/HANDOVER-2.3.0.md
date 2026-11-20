# Handover — Unplugged 2.3.0 (final cycle)

Written 2026-11-18, end of the development session that followed
[HANDOVER-2.3.0-clipguard.md](HANDOVER-2.3.0-clipguard.md). This document
supersedes that one for **current tree state**; read the ClipGuard handover for
the ClipGuard design detail, which is unchanged.

- App repository: `C:\code\unplugged-mpc-hc`, branch `zion-s3-shell`, HEAD
  `7b18fe3f5` (**everything below is uncommitted**).
- Renderer repository: `C:\code\unplugged-VideoRenderer`, HEAD `4e2227d`, tag
  `v2.2.1` — not touched in this session.
- LAV: unchanged from 2.2.0.

## 0. State in one paragraph

The 2.3.0 feature set is complete in the working tree: ClipGuard (previous
cycle), the UNC library fix, the monitor-rect 4K canvas, a rebuilt subtitle
stack, themed playback dropdowns, display-refresh matching (now in **both**
modes), subtitle size and scope-bar placement, the engine-driven SDR/ML-grade
policy, and the wiped-profile Video Processor default-input fix (§3.8,
**verified 2026-11-18**).
The user field-verified the UNC fix, the 4K canvas, subtitle drawing (`good
work subtitles work great`) and the final DV/SDR classifier (`that appears to
work`). What remains is **packaging, release documents, and the field tests in
§8** — not feature work.

**First action next session:** package (§5) and correct the release notes (§6).
The refresh-matching field test and the remaining §8 items need the projector or
the Hisense TV — the MSI convenience panel cannot show any rate from 23–30 Hz.

## 1. Working tree

```
59 files changed, 2673 insertions(+), 6069 deletions(-)
```

The deletion bulk is the subtitle stack replacement (§3.3). Tracked binaries
under `tools/s3engine/` (`s3engine.dll`, `.lib`, `.exp`, `.obj`) are modified by
the builds and belong in the release commit.

New/untracked documents to add when committing:

- `docs/HANDOVER-2.3.0.md` (this file)
- `docs/HANDOVER-2.3.0-clipguard.md`
- `docs/RELEASE-NOTES-2.3.0.md`
- `docs/USER-REPORTS.md`
- `docs/SUBTITLE-AUDIT.md`
- `docs/unc-library-test-plan.md`

`src/Subtitles.fork-backup/` is the **old fork stack kept only as a local
reference**. Do not commit it and do not let it reach the payload.

The repository root is full of `_build_*.log`, `_link*.log`, probe PNGs and
other session artifacts (all untracked). They are not part of 2.3.0; do not
"tidy" them into a commit.

## 2. Workstream A — ClipGuard

**Packaging separation (2026-11-18).** Agreed with the ClipGuard author: the
feature ships as the author's own package/zip for users who want it, separate
from the Unplugged release. In the app the 15 tuning rows (`hdr.cg*`) are
hidden behind `dev=1` (still pushed and persisted, so a package's presets keep
working) and the rail shows one row: **HDR → Tone Mapping → ClipGuard →
Configure** (`__clipguardCfg`, `WM_APP+60`; no one-item CLIPGUARD section). Configure opens **`<exe>\clipguard` and nothing
else** — no fallback paths and no creating an empty folder, because a missing
folder is precisely "ClipGuard is not installed". Missing → the two-line notice
card: **"ClipGuard is not installed"** with the red reason "Install the
ClipGuard package next to Unplugged to use this feature."; a ShellExecute
failure → "ClipGuard could not be opened". Verified:

```
clipguard: configure -> '…\bin\app\Release\clipguard'
clipguard: not installed - notice shown          (folder absent)
```

(no error line when the folder exists and opens).

Unchanged from [HANDOVER-2.3.0-clipguard.md](HANDOVER-2.3.0-clipguard.md):
native port in the renderer (`CDbleFix` / `Settings_t.clipGuard`), DBLE
migration, session-only overlay, look-ahead forced Off in live capture. The open
packaging items in that document still apply and are restated in §7.

## 3. Workstream B — changes made 2026-11-18

### 3.1 UR-0001 — UNC libraries marked every title UNAVAILABLE

**Root cause.** `MpcLibrary::PathRoot()` returned drive roots with a trailing
separator but UNC roots without one. `GetDriveTypeW("\\\\server\\share")`
returns `DRIVE_NO_ROOT_DIR` (1) even on a reachable share;
`"\\\\server\\share\\"` returns `DRIVE_REMOTE` (4). `RootReachable()` rejects
`DRIVE_NO_ROOT_DIR`, so every title under a UNC root was marked unavailable.

**Fix.** `tools/native_ui/native_ui.cpp` — `PathRoot()` keeps the separator
after the share name and appends one for a bare share
([native_ui.cpp:8452](../tools/native_ui/native_ui.cpp)). Reproduced and proven
with `\\localhost\C$` (1) vs `\\localhost\C$\` (4).

**Status.** Fixed, builds clean, logic verified. Field confirmation on a share
still pending (the user will run `tools/unc_test/setup_movies_share.ps1` on
this PC and install 2.3.0 on the second PC — see §8).

### 3.2 UR-0004 — 4K output was scaled to 3831×2152

**Cause.** 2.2.0 deflated the work rect by `EDGE_BLEED` on top of the frame
bleed; the 2.3.0 first cut removed the deflate but used the window client,
which is +2 px vs the monitor.

**Fix.** `WorkR()` now maps the **monitor rect** (`MONITORINFO.rcMonitor`) into
the client, centred, and `Create2` creates `g_host` on that rect so the first
`Layout` does not resize a live swap chain
([native_ui.cpp:10083](../tools/native_ui/native_ui.cpp)). A startup line makes
it checkable from a bundle:

```
work rect: client 3842x2162 -> monitor 3840x2160 (3840x2160 at 1,1)
```

**Status.** Field-verified by the reporter: `DISPLAY 3840 × 2160`, Fit mode
**Source = 1:1**. Fixed aspect 1.78 still maps to 3840×2157 by definition;
documented in `settings-guide.md`.

### 3.3 Subtitles — rebuilt on MPC-HC's own stack

The fork carried a newer MPC-BE-era `src/Subtitles` with a libass path. It
produced 10×10 subpictures (8× frame-size maths) and text never drew. Patching
was abandoned; the directory was **replaced wholesale** with the reference
stack from `C:\code\mpc-hc-develop\src\Subtitles` (internal RTS rasterizer, no
libass). The old stack is at `src/Subtitles.fork-backup/` (local reference).

Removed fork-only files: `LibassContext.*`, `OpenTypeLangTags.*`,
`FreeTypePathTools.*`, `SubRendererSettings.*`, `STSStyle.h`.

Shims required by the reference stack:

- `SubtitleHelpers.cpp`: `ISO639XToLanguage(str, true)` → one-argument form.
- `RenderingCache.h`: `#include <atlcoll.h>` and
  `using KINARGTYPE = typename KTraits::INARGTYPE;`.
- `stdafx.h`: `<cmath>`, `<functional>`.
- Removed `SubRendererSettings` includes/calls from
  `src/mpchc_engine/SubtitlePlayerGlobals.cpp` and `src/mpc-hc/AppSettings.h`.

Presenter work (the draw leg):

- `MPCVRAllocatorPresenter::RenderEx3` now calls
  `__super::SetPosition(CRect(viewportRect), CRect(croppedVideoRect))`; before
  this the presenter's video rect stayed empty and the subpic was 0×0.
- `SetSubPicProvider` restores a full canvas if `m_videoRect` is still empty.
- `SubPicAllocatorPresenterImpl::AlphaBltSubPic` applies the size scale and
  then the scope bottom-bar placement
  ([SubPicAllocatorPresenterImpl.cpp:123](../src/SubPic/SubPicAllocatorPresenterImpl.cpp)):
  - scale `m_subScale` percent about the horizontal centre, anchored at the
    bottom edge of the destination;
  - if `windowRect.bottom - videoRect.bottom > 1` (a bottom black bar exists),
    move the subpicture down to 2 % above the window bottom;
  - scale first, then place, so a grown subtitle still fits the bar.
- `m_subScale` defaults to **65** (`SubPicAllocatorPresenterImpl.h:48`),
  clamped 25…300.

Engine/UI plumbing:

- `MpcPlayer::SetSubtitleScale(int)` ([MpcPlayer.cpp:5551](../src/mpchc_engine/MpcPlayer.cpp)),
  applied through `static_cast<DSObjects::CMPCVRAllocatorPresenter*>` — the
  method is not on `ISubPicAllocatorPresenter`. Re-applied in
  `ApplySubtitleProvider`.
- `s3engine.cpp:715` handles `{"a":"subscale","percent":N}`, fallback 65.
- UI row `{0,1,L"SUBTITLES",L"Text size","pb.subScale",50,200,5,65,...}` at
  `native_ui.cpp:725`; `PushRow` special-cases it and startup pushes it after
  `s3_attach` (`native_ui.cpp:10014`).
- `ParseTracks` starts at `active = -1` so the row shows **Off**, not a
  phantom "English" selection.

**Status.** User-verified on the installed 2.3.0: text subtitles draw. Still to
confirm on scope content: the bar pin and 65 % size together, plus a PGS and a
VobSub title (§8).

### 3.4 Playback rows are themed dropdowns

`CMenu` was replaced by `CListPicker` (`native_ui.cpp:2471`): dark panel,
accent left edge, check mark, hover, wheel and keyboard, 12 visible rows,
`▾` affordance replacing `‹ ›`. It is used for the playback **Audio**, **HD
audio** and **Subtitles** rows. `audio.mode` keeps its own handling. Any
`kind==2` row not converted still cycles.

### 3.5 Display-refresh matching

- New device-ish row `out.matchRefresh` (**default On**, no engine push):
  `{4,0,L"OUTPUT",L"Match display refresh","out.matchRefresh",...}` and added
  to `PresetDeviceRow`.
- On every open (`MpcLibrary::Play`, `PlayContextPath`, `StartNext`):
  `MatchRefreshBegin(path, notify)`. It probes the file with the installed
  `ffprobe`, maps the cadence, enumerates modes at the current resolution with
  `EnumDisplaySettingsExW`, switches with
  `ChangeDisplaySettingsExW(CDS_FULLSCREEN)` and logs:

  ```
  setting=ON current=... modes at WxH: ...
  apply ... (was ...)
  apply result rc=... actual=...
  ```

  Restore (`MatchRefreshRestore`) on stop, close, VP switch and when the row
  is turned off; `WM_REFRESH_MATCH` (`WM_APP+59`) handles the live toggle.
  A toast is shown only when the user toggles the row.
- Cadence map: 23.976→23/24, 24→24/23, 25→25, 29.97→29/30, 30→30/29,
  47.952→48/47, 48→48, 50→50, 59.94→60/59, 60→60/59. The first that the
  monitor exposes is applied.
- **Limitation proven on the dev display:** 3840×2160 exposes only 59/60 Hz,
  so 23.976 content stays at 59/60 and the log says so. This is correct
  behaviour, not a failure. The projector must be tested for real 23/24 modes.

Info panel correction:

- `CurrentRefreshHz()` uses the **app's monitor**
  (`GetMonitorInfo` → `EnumDisplaySettingsExW(mi.szDevice)`) — the old
  `GetDeviceCaps(VREFRESH)` read the primary DC, which is wrong on multi-monitor.
- PERFORMANCE now shows **DISPLAY REFRESH** (`N Hz`) and **PRESENT FPS**
  (`draw`), instead of one "DISPLAY FPS" row that conflated the renderer's
  presented cadence with the scan-out rate.

**Video Processor leg (added late on 2026-11-18, field-requested).**
`out.matchRefresh` is an app setting and must act in both modes. A capture's
cadence only exists once the stream runs, so `LiveRefreshPoll`
([native_ui.cpp](../tools/native_ui/native_ui.cpp), `StartVp` region) reads
`dl.fpsNum/fpsDen` from the status JSON every poll (the card's own signal-mode
read stays `0/0`; `signal.*` is only a fallback), requires the same cadence for
three polls (~1 s) and then applies the **same** `MatchRefreshPrefs` table via
the same `MatchRefreshSwitch`. One decision per cadence. The matched rate is
left in place across a source re-lock (a 50 Hz menu → 24 Hz film must not bounce
the panel through the desktop rate); the desktop mode is restored on VP exit,
`RelaunchProcess`, close, and when the row is turned Off.

Feedback: unlike the file path (whose silent decision hides behind a title
open), the live leg passes `notify=1` **always**, so the same
`No 23/24 Hz mode at WxH — display stays at 60 Hz` toast that Media Player shows
is shown in VP too, once per cadence, and `refresh: notice shown '…'` records it
in the log. Without this, a 60 Hz panel makes the feature look broken.

Verified in the log (VP, disc menu then film):

```
refresh: live cadence 50000/1000
refresh: live fps=50.000 target=50/50 current=60 Hz
refresh: No 50/50 Hz mode at 3840x2160
refresh: notice shown 'No 50/50 Hz mode at 3840x2160'
refresh: live cadence 24000/1000
refresh: live fps=24.000 target=23/24 current=60 Hz
refresh: No 23/24 Hz mode at 3840x2160
refresh: notice shown 'No 23/24 Hz mode at 3840x2160'
```

**Why it cannot switch on the dev machine (measured 2026-11-18, not an app
defect).** The active display is `MSI MD342CQP` — the 3440×1440 *viewing
panel*, driven at a non-native 3840×2160. Independent enumeration shows **125
modes and not one refresh between 23 and 30 Hz at any resolution** (rates:
50, 56, 59, 60, 70, 72, 75, 100, 119, 120; 3840×2160 offers only 60 and 59;
native 3440×1440 offers 50 and 100). The `HISENSE` and `DENON-AVRHD` EDIDs
cached on the same output **do** advertise 3840×2160 @ 23.976/24/25/30 — the
real 4K target can match, the convenience panel cannot. Field proof must be
run on the TV/projector, not on this panel, in **either** mode.

### 3.6 SDR content policy — engine owns the classification

**Requirement.** SDR titles get ML grade disabled by default, with an on-screen
message; the user can opt in. The label must appear **only after a decision** —
never on a guess, never on a DV/HDR title.

**Why the first two implementations failed.** The log of the 16:58 DV P8 test
shows the whole story:

```
16:58:56.240  [ENGINE] source media type: 3840x2160 ... tf=0 hdr=0 (flags=0x00000000)
16:58:56.4    app: SDR verdict (renderer's first pipeline read: tf=5, dovi=0)
16:58:57.684  app: class=DV (renderer now reports tf=15, prim=9, dovi=1)
16:58:59.699  [live] pipeline: ... dovi=1 ... tf=15 prim=9 ... cll=1546 fall=306 mmax=4000
```

Three separate defects:

1. The pipeline tokens (`dovi=`, `tf=`, `cll=` …) were parsed only inside the
   **1-in-5 log throttle** in `RefreshLive` — up to ~5 s stale. The app's 3 s
   streak could therefore decide SDR before the DV flag had been read once.
2. Renderer-derived fields were only assigned when a token was present and were
   never reset per graph, so a DV flag leaked into the next title.
3. SDR was inferred from *missing* fields. A DV P8 pin carries no colour info
   (`flags=0`, `tf=0`), the renderer's first read says `tf=5`, and the DV truth
   arrives ~1.3 s later with the first processed samples. "Not HDR yet" is not
   "SDR".

**Final architecture.**

Engine (`MpcPlayer`):

- Pipeline tokens parsed **every tick**; only logging stays throttled
  (`MpcPlayer.cpp:4300` region).
- New `m_livePiping` ("the renderer has described this graph") and
  `m_clsFirstFrameAt` ("first frame received for this graph"); reset with the
  renderer-derived cache in `Open()`.
- `media.cls` (0 SDR, 1 HDR10, 2 HLG, 3 DV) and `media.known`, computed in
  `GetUiStatusJson` ([MpcPlayer.cpp:4648](../src/mpchc_engine/MpcPlayer.cpp)):
  - DV: `dovi > 0` → immediate.
  - HLG: transfer 16 → immediate.
  - HDR10: transfer 15, `vs.hdr`, or any static metadata > 10 → immediate.
  - SDR: `m_livePiping` **and** a known non-PQ/HLG transfer **and** a settle
    of **≥48 received frames and ≥3 s since the graph's first frame**.
  - Anything else → `known=0`, and the app must do nothing.
- `srcHash` (FNV-1a over the source path, published top-level) identifies the
  graph the class belongs to.
- `m_liveDovi`, `m_liveRenderTf/Prim`, `m_liveMdr*`, `m_livePiping`,
  `m_clsFirstFrameAt` reset at every `Open`.

App (`native_ui.cpp`):

- Reads only `media.cls`, `media.known`, `srcHash`; deleted
  `MediaContentClass`, `m_sdrStreak`, `m_sdrPathAt`, the 10-sample streak and
  the 3 s title-age gate.
- `sameSrc` (hash of `m_mediaPath` vs `srcHash`) gates everything — the
  previous graph's finished verdict can never be applied to a newly opened
  title.
- `UpdateSdrMl(cls, known)` ([native_ui.cpp:10420](../tools/native_ui/native_ui.cpp)):
  - `known=0` → nothing, silent.
  - `cls≠0` → restore a grade an earlier SDR title turned Off; no label.
  - `cls=0`, not yet acted for this title → opt-in check, then disable
    (engine only, `g_rowNoSave`) and show the toast **once**.
  - `zion.sdrGrade=True` → leave the grade as the user set it, log only.
- User opt-in: toggling `zion.enabled` while an SDR title plays writes
  `zion.sdrGrade`, clears `m_sdrAuto`. Persistent per machine.
- Restores on stop, library, close and VP switch.

**Decision matrix (current, final):**

| Engine says | Grade | Label |
| --- | --- | --- |
| `known=0` | untouched | none |
| DV / HDR10 / HLG | untouched; restores if a prior SDR title disabled it | none |
| SDR, no opt-in, grade On | turned Off (not persisted) | once, after the settle |
| SDR, no opt-in, grade already Off | unchanged | once, after the settle |
| SDR, `zion.sdrGrade=True` | untouched | none |
| VP / live capture | policy not applied | none |
| stop / library / close / VP switch | restores pre-SDR value | none |

**Accepted limitations.** If the renderer never publishes a transfer at all,
or never reaches 48 frames / 3 s, no SDR verdict is issued — silence is chosen
over a possible false disable. A stream that reveals DV *after* the settle
(>3 s / 48 frames) would still be mis-decided; no such title has been observed
and the 16:58 evidence puts the reveal at ~1.3 s.

**Verified.** User: DV P8 title no longer shows the label (`that appears to
work`). SDR titles still get the label after the settle.

### 3.7 Other UI corrections

- PERFORMANCE rows: `DISPLAY REFRESH` and `PRESENT FPS` (see §3.5).
- `settings-guide.md`: Fixed aspect clarified — 1.78 is not exactly 16:9;
  Source is the 1:1 mode.

### 3.8 Wiped profile: Video Processor starts with no input

**Report.** After wiping Unplugged settings, Video Processor does not work —
"default config is not found". Log:

```
config mode='media_player' ... input=''
vp: s3_start_device('') rc=0x00000000
acquire: FAILED - no signal after retries
```

**Cause.** `%USERPROFILE%\.unplugged\app_config.json` was reseeded with
`"active_input_url": ""`, and `s3_start_device("")` is defined by the ABI as
**capture off**, not "pick a default". `StartVp` then ran the 10-attempt
acquire card against nothing, which reports "no signal" for a configuration
that was never made.

**Fix.** `StartVp` now defaults an empty input to the first port the card
exposes — a **locked** port first, otherwise the first — using the same rule as
`CSetupCard::Scan()`. The choice is written to `active_input_url` and the
SOURCE rows are refreshed, so the tab and the next launch agree. If the card
exposes no ports, it logs that instead of pretending there is a signal problem.
([native_ui.cpp](../tools/native_ui/native_ui.cpp), `StartVp`, ~9865.)

Expected log on a wiped profile with the card present:

```
vp: no saved input -> default 'decklink://DeckLink Quad HDMI Recorder (1)' (ports=4)
vp: s3_start_device('DeckLink Quad HDMI Recorder (1)') rc=0x00000000 ...
```

`app_config.json` then carries that URL (or the device at another port if a
locked one wins), and the SOURCE tab shows it as active. With no ports at all
the line is `vp: no saved input and no DeckLink ports found` and the normal
failure card remains the honest outcome.

**Wipe/reproduce.** An empty `active_input_url` is a legitimate state — setup
can be completed without an input, and deleting `%LOCALAPPDATA%\Unplugged` /
`%USERPROFILE%\.unplugged` does not always replay the wizard, because
`SeenSetup` lives in `HKCU\Software\Unplugged`. The fix does not depend on how
the input became empty: it resolves the port at `StartVp`, on every entry to
Video Processor. To force a true first-run, delete the registry value as well
and decide deliberately whether that is what you are testing.

**Status.** **Retested and PASSED 2026-11-18 17:17** on a still-wiped profile
with the dev build ([native_ui.cpp](../tools/native_ui/native_ui.cpp) `StartVp`
~9872). Log:

```
17:17:25.238  config wrote active_input_url
17:17:25.238  vp: no saved input -> default 'decklink://DeckLink Quad HDMI Recorder (1)' (ports=4)
17:17:25.244  SOURCE ports=4 active='decklink://DeckLink Quad HDMI Recorder (1)'
17:17:25.245  vp: s3_start_device('DeckLink Quad HDMI Recorder (1)') rc=0x00000000 took=0ms
17:17:31.289  vp: signal acquired (1 frames drawn) - overlay dismissed
```

`app_config.json` now carries the URL, the SOURCE tab is active, and the next
launch needs no fix path. Engine and `s3engine.dll` unchanged by this fix.

### 3.9 Output depth — the Info panel now states it, and 10-bit SDR is proven

**Requirement.** The Info panel must say what depth the picture is actually
presented at, because "is deep colour on?" was being answered by guesswork.

**Row.** PERFORMANCE gains **OUTPUT DEPTH** next to DISPLAY REFRESH
([native_ui.cpp](../tools/native_ui/native_ui.cpp) `CurrentOutputDepth`, ~133):
`10-bit RGB WCG`, `8-bit RGB SDR`, `10-bit YCbCr 4:2:2 SDR`, or `—`. It is read
from `GET_ADVANCED_COLOR_INFO_2` for the app's monitor — **the same call the
renderer makes** to choose its swap chain — with the legacy
`GET_ADVANCED_COLOR_INFO` fallback. Local structs are used on purpose: the SDK
gates `_2` behind `NTDDI_WIN11_GA`. A change is logged as
`output depth: 10-bit RGB WCG`.

**Why the number matters.** The renderer presents `R10G10B10A2` only when
`bHdrOutput` (HDR display mode) **or** `Preferred10BitOutput()`
(`m_DisplayBitsPerChannel >= 10` **and** a 10-bit internal texture); otherwise
its swap chain is `B8G8R8A8` regardless of how deep the source is
([DX11VideoProcessor.cpp:5476](../c:/code/unplugged-VideoRenderer/Source/DX11VideoProcessor.cpp#L5476)).

**Windows 10-bit SDR — what it takes (measured 2026-11-18).**
`DISPLAYCONFIG_SET_WCG_STATE` succeeds and switches the compositor to WCG, but
`bitsPerColorChannel` stayed **8** until the **GPU driver's output colour depth**
was set to **10 bpc** (NVIDIA Control Panel → Change resolution → Output colour
depth). After that, at 3440×1440@50 over HDMI:

```
ACI2: bits=10  encoding=RGB  activeMode=WCG
app : output depth: 10-bit RGB WCG
ml_debug.csv: swfmt=24  (= R10G10B10A2; previously 87 = B8G8R8A8)
```

So the CM3588 result (10-bit SDR scanout) **is reachable on Windows**, but the
link depth belongs to the driver, not the app: there is no public API to set it.
`SET_HDR_STATE` is the only other lever and that is HDR, not SDR 10-bit.

**How to verify the swap chain without a probe.** The renderer's
`filters\ml_debug.csv` writes `swfmt` per frame when the row
**Zion → Debug → Frame log** (`zion.debugFrameLog`) is on. 24 =
`R10G10B10A2_UNORM`, 87 = `B8G8R8A8_UNORM`. The renderer holds the file open
exclusively, so it can only be read **after the app closes**. The setting lives
in `%LOCALAPPDATA%\Unplugged\s3_shell.ini` — **not** `settings.ini`; a value
written to the wrong file is silently ignored (this cost time today).

**Display note.** The MSI MD342CQP exposes 50 and 100 Hz at 3440×1440 and 60/59
at 3840×2160 — no 23–30 Hz at any resolution, so refresh matching cannot change
rate on it (see §3.5).

**Feature: `hdr.tenBitSdr` — "10-bit SDR output" (HDR tab → DISPLAY TARGET,
default Off).** This is the half of the CM3588 behaviour Windows lets an app
own. **Applied once at startup, after the splash** (`TenBitBegin` in the timer-4
branch), so the composition holds for the whole Unplugged session; `StartVp` and
the three file-play paths call it again idempotently (F5/capture restarts).
- if Windows HDR is active → no-op (already 10-bit);
- if WCG is active → `SET_WCG_STATE(0)`, journaled in `ui.wcgRestore` **before**
  the change. It stays off until Unplugged closes or relaunches (restored in
  `OnClose` / `RelaunchProcess`) or the row is turned Off. Titles, stops and
  mode switches do **not** toggle it — per-playback toggling bounced the desktop
  through WCG and resynced the display on every stop;
- if the link is still 8 bpc → a once-per-launch card naming the GPU vendor's
  control-panel path, because the link depth is the driver's and has no API.

Crash safety: `TenBitCrashRecovery()` runs after `LoadSettingsIni` and
re-enables WCG if a previous run died between disable and restore.

Verified 2026-11-18 (row On, driver at 10 bpc, WCG on at launch):

```
18:05:13  output depth: 10-bit RGB WCG
18:05:18  10bit: WCG disabled for playback
18:05:18  output depth: 10-bit RGB SDR
18:05:18  10bit: link 10-bit RGB SDR - target state
18:05:34  10bit: WCG restore ok          <- on close
```

and the OS probe after close reads `bits=10 mode=WCG`, i.e. the user's state
was returned. The Info panel's OUTPUT DEPTH shows which state is in force.

**16-bit frame capture (added with the 10-bit work).** A 10-bit frame cannot be
proven from an 8-bit capture, and the old grab path guaranteed 8 bits in three
places. Fixed end to end:
- The renderer already supported it: `allowDeepColorBitmaps` makes
  `GetDisplayedImage` return 48-bit RGB from the back buffer. The engine now
  sets that flag in `ConfigureRendererWindow` (and logs a failure).
- `MpcPlayer::GrabFrame` now reads `IExFilterConfig::Flt_GetBin("displayedImage")`
  first (back buffer, 48-bit, `LocalFree`d), falling back to
  `IBasicVideo::GetCurrentImage` — which hard-codes 32-bit. The luma diagnostic
  follows the DIB's real depth (6 bytes/pixel for 48-bit).
- The app converts the DIB with **WIC**, not GDI+ (whose PNG encoder is 8-bit).
  WIC's BMP *decoder* refuses `biBitCount=48`, so the DIB is handed to WIC as an
  in-memory bitmap (`CreateBitmapFromMemory`), then encoded to PNG.
- **Channel order:** the DIB is **BGR at both depths** (BMP convention). Declaring
  the 48-bit buffer as `GUID_WICPixelFormat48bppRGB` swapped red and blue — a
  deep-red garment captured as violet. The source is `48bppBGR`, the PNG target
  `48bppRGB`; the format converter does the swap.
- **Ctrl+S works in Video Processor** now (live frame; file playback still
  requires pause). `SaveFrameQuick` writes to `Pictures\Unplugged\<date>\`.

Verified 2026-11-18: engine `wrote 3440x-1440 48bpp`, app
`frame capture -> … (16-bit per channel)`, PNG IHDR `bitDepth=16 colorType=2`.
The capture is the **display back buffer**, so its size follows the current
mode (3440×1440 here), not the 4K canvas. For a depth A/B, `out.texFormat` =
8-bit forces an 8-bit internal texture and therefore an 8-bit swap chain without
touching the composition.

### 3.10 Denoise investigation (open; no code yet)

Source in the field test is **Apple TV over DeckLink**. Dark-scene grain was
measured in both the SDR and the PQ captures (HDR passthrough) with the same
spatial pattern, so it is **source/stream compression**, not the renderer.

- Noise vs luma (10-bit): **2.6** at luma 64–127 → **0.9** at 448–511. A bright
  corner measured 0.67, dark ones 2.16 — the correlation is brightness, not
  position.
- Ruled out: `postfx.debandGrain` 24→0 (byte-identical captures),
  `hdr.shadowLift` 2→0 (2.16→2.25), 10-bit itself (only prevents added
  dither/banding). Apple TV exposes no NR control.
- Options: masked post-FX shader (cheap, but post-tone-map); NVIDIA **Maxine
  Video Effects** (Denoise / Artifact Reduction; CUDA-D3D11 interop, model
  redistribution licence); **open ONNX models on the existing DirectML path** —
  FFDNet/NAFNet for grain, FBCNN for compression artifacts, FastDVDNet for
  temporal (needs frame history). Caveat: models are trained on 8-bit gamma,
  PQ input needs domain conversion.
- **Next step:** offline ONNX evaluation (FFDNet at low σ, FBCNN) on frozen
  frames before any integration; judge sky-noise reduction against grass/skin
  softening. Capture instruments are in §3.9 and
  `UNPLUGGED_DEEP_CAPTURE=0`.

### 3.11 NLS aspect rule — two-window bars (implemented 2026-11-18)

Origin: UR-0007 (power user, 2.2.0). **No detection bug**: the engine already
tracks the live band and re-latches on a scope↔IMAX cut (`MpcPlayer.cpp:4220-4238`)
and `NlsBarHeight()` is a no-op with no bars (`1128-1133`). The gap is policy:
`geo.nlsBars` / `nlsCropX` / `nlsCropY` are single values for every title, the
Post-NLS crop is applied unconditionally (`3709-3728`), and `Lock band`
deliberately freezes the band (`4228-4230`) so it cannot help mixed-aspect films.

Design:

| Window | Detected aspect | NLS | Bars removed | Post-NLS X/Y crop |
| --- | --- | --- | --- | --- |
| Native | ≤ 1.95 (1.90 row + 0.05 tolerance) | bypass | 0 | 0 |
| Small bars | 1.95 – 2.15 | on | 100 | 0 |
| Scope | ≥ 2.15 | on | user's scope tuning | user's |

- The 0.05 tolerance above the Native row is deliberate: a real 1.90 IMAX
  section detects at 1.92–1.94 (measured 1.926/1.941 on Spider-Man: Far From
  Home). Without it the IMAX cut landed in Small bars and was zoomed. Entering
  Native uses `aspect <= Native max + 0.05`; leaving needs
  `> Native max + 0.05`. A 2.00 film stays in Small bars.
- Engine publishes `nls.picAspect` (detected active picture aspect) and
  `nls.conf` (confidence) in the status JSON.
- Classification in `PollStats`: ±0.05 deadband around each bound, switch only
  after 3 consecutive polls (~0.9 s) with confidence ≥ 0.8; an uncertain read
  holds the current window. The native tolerance is applied on entry from any
  window, so a 1.90/1.94 IMAX section is native from scope, small-bars and
  start-up alike.
- On a window change the app overrides the NLS rows engine-only (`g_rowNoSave`,
  like the SDR policy) and restores the user's values on stop / rule Off.
- When the rule is On, **Lock band is ignored and greyed** (it would stop the
  format tracking the rule depends on).
- Info panel: `DETECTED ASPECT 2.36 · window: Scope`; log every switch.
- Rows under a new NLS section: rule On/Off (default Off), Native upper bound,
  Scope lower bound, and the three windows' values.

**Implemented (2026-11-18).** Engine publishes `nls.picAspect/known` from the
latched band (`GetUiStatusJson`); the app's `NlsAspectPoll` (file-static, called
from `PollStats`) classifies with the deadband + 3-poll rule and applies
`geo.nlsBars`/`nlsCropX`/`nlsCropY` engine-only through `g_rowNoSave`; release
runs on stop, close and rule-Off. Verified on a scope source:

```
19:41:31  nlsaspect: 2.462 -> scope (bars=100 crop=0/0)
19:40:55  nlsaspect: 2.462 -> small-bars (bars=100 crop=0/0)   (threshold moved to 2.60)
19:40:38  nlsaspect: released - user values restored           (on close)
```

Native (<=1.90) still needs a 16:9 or IMAX source to field-verify; the
classification is the symmetric branch. Note the row range caps Native max at
2.10, so a test cannot force Native on a 2.46 source by threshold alone.

### 3.12 SDR BT.2020 signal — test row (2026-11-19)

Row: **HDR → Display Target → "SDR signal: BT.2020"** (`out.sdrBt2020`, device
row). Purpose: ask a projector/monitor to auto-switch to its wide-gamut mode by
carrying a BT.2020 colourimetry flag in an SDR signal.

How it works (no API writes the AVI InfoFrame; the GPU derives it from the
swap-chain colour space):

- Renderer declares the SDR swap chain `DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P2020`
  in `InitSwapChain`, guarded by `CheckColorSpaceSupport` (fallback P709).
  `Settings_t.bSdrBt2020`; a change recreates the swap chain via `changeWindow`.
- The **image must already be BT.2020**: set **Output gamut = BT.2020**
  (`hdr.outputGamut=1`); declaring P2020 over 709 values would desaturate.
- The app forces **WCG on** while the row is on (`TenBitBegin` precedence over
  the 10-bit-SDR row's WCG-off), journaling/restoring like the other display
  state.
- Engine: `OutSettings.sdrBt2020`, status `out.sdrBt2020`, and a rebuild-only
  hold so a toggle takes effect before the pins connect.

Verified on the dev box:

```
ml_debug: SDR_BT2020 check hr=0x00000000 support=0x3
ml_debug: SDR_BT2020 set   hr=0x00000000
frames  : swapcs=G22P2020  swfmt=24   (10-bit SDR, BT.2020)
app     : bt2020: WCG on for SDR BT.2020 signal ok  → output depth 10-bit RGB WCG
```

**Open:** whether the display actually switches. Windows does not report the
InfoFrame; the evidence must be the projector/monitor's own signal-info screen.
Many displays auto-switch only on HDR metadata, in which case this row is a
no-op for them.

## 4. Build, stage, run

```powershell
# 1. Engine (after any MpcPlayer.* change)
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"

# 2. s3engine (links mpchc_engine.lib; produces tools\s3engine\s3engine.dll)
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"

# 3. Stage the DLL where the dev app loads it
Copy-Item C:\code\unplugged-mpc-hc\tools\s3engine\s3engine.dll `
          C:\code\unplugged-mpc-hc\bin\app\Release\s3engine.dll -Force

# 4. Native app (writes straight to bin\app\Release\Unplugged.exe)
cmd /c "call ""C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat"" -arch=amd64 -host_arch=amd64 -no_logo >nul && msbuild C:\code\unplugged-mpc-hc\tools\native_ui\native_ui.vcxproj /p:Configuration=Release /p:Platform=x64 /nologo /verbosity:minimal"

# 5. Renderer: only if renderer source changed (it did not in this session)
MSBuild C:\code\unplugged-VideoRenderer\MpcVideoRenderer.sln /p:Configuration=Release /p:Platform=x64
```

Artifacts and logs:

| Thing | Path |
| --- | --- |
| Dev app | `bin\app\Release\Unplugged.exe` |
| Dev app log | `bin\app\Release\native_ui_log.txt` |
| Installed app log | `%LOCALAPPDATA%\Unplugged\logs\native_ui_log.txt` |
| Engine log | `%USERPROFILE%\.unplugged\logs\engine.log` |
| Settings INI | `%LOCALAPPDATA%\Unplugged\s3_shell.ini` (NOT `settings.ini` — `SettingsIniPath()` names it `s3_shell.ini`) |
| Renderer filter | `bin\app\Release\filters\unplugged_vr.ax` |

`rebuild_engine.bat` needs `ML_MPCVR_INCLUDE`, `LAV_INCLUDE`,
`DECKLINK_INCLUDE` (already inside the script). The s3engine link requires the
static libs in `bin\lib\Release_x64` produced by
`tools/engine_s3/build_subtitle_stack.bat`; run that if the subtitle stack is
rebuilt from scratch.

## 5. Packaging — what the installer must carry

**Do not publish `distrib\out\Unplugged-setup-2.3.0.exe`** (13 November). It
bundles the old renderer (0.10.9.2637, Bilinear chroma). `distrib/unplugged.iss`
already expects `UnpluggedRenderer-0.11.0.2637`.

The staged payload `dist\Unplugged-2.3.0\` is also stale (13 November):
`Unplugged.exe` 13/11 22:15, `s3engine.dll` 13/11 21:22. Re-stage from
`bin\app\Release` before building:

```powershell
Copy-Item C:\code\unplugged-mpc-hc\bin\app\Release\Unplugged.exe,
          C:\code\unplugged-mpc-hc\bin\app\Release\s3engine.dll,
          C:\code\unplugged-mpc-hc\bin\app\Release\decklink_monitor.dll `
          C:\code\unplugged-mpc-hc\dist\Unplugged-2.3.0\ -Force
Copy-Item C:\code\unplugged-mpc-hc\docs\settings-guide.md `
          C:\code\unplugged-mpc-hc\dist\Unplugged-2.3.0\docs\ -Force
& C:\code\unplugged-mpc-hc\distrib\build_unplugged_setup.ps1
```

The script gates app `ProductVersion` 2.3.0, the settings-guide stamp, hash
equality of the three staged natives and the guide, and the existence of every
`Source` path in `unplugged.iss`. Keep those gates.

## 6. Release notes and website — must be corrected

`docs/RELEASE-NOTES-2.3.0.md` is still the ClipGuard draft:

1. **Remove the `UnpluggedRenderer-setup-2.3.0.exe` row.** That package does
   not exist and must not be created. The standalone renderer release is
   **2.2.1** (`v2.2.2` was folded back into it).
2. Replace both size/hash rows with the rebuilt installer's real values.
3. Add the session features, which are currently missing from the notes:
   - internal subtitle stack rebuilt on MPC-HC's engine; text subtitles
     (SRT/ASS/SSA/WebVTT/MOV_TEXT) draw, alongside PGS/VobSub/DVB;
   - subtitle **Text size** (default 65 %) and scope **bottom-bar placement**;
   - themed **dropdown** playback rows (Audio, HD audio, Subtitles);
   - **Match display refresh** (default On, visible control, logged
     request/result, restored on stop);
   - **SDR auto-disable of the ML grade**, with an on-screen notice and a
     persistent user opt-in;
   - the Info panel now reports **display refresh** separately from presented
     FPS.
4. Confirm every claim against the shipped build.

`website/index.html` and `website/download.html` still describe 2.2.0/DBLE;
`website/guide.html` is already 2.3.0. Regenerate release data and update both
after the installer hash is final.

## 7. Release checklist

- [ ] Re-stage `dist\Unplugged-2.3.0` from `bin\app\Release` (§5).
- [ ] Rebuild and test the installer; record size and SHA-256.
- [ ] Correct `docs/RELEASE-NOTES-2.3.0.md` (§6) and the website.
- [ ] Clean-profile smoke test; install-over-2.2.0 test with a real DBLE
      profile and a library on a UNC share.
- [ ] Preset behaviour: `hdr.cg*` rows never stored/dirty; `out.matchRefresh`
      is a device row too.
- [ ] Commit the tree: the 59 modified/deleted files, the new docs, and the
      four tracked `tools/s3engine` binaries. Exclude `src/Subtitles.fork-backup`
      and all session logs/PNGs.
- [ ] Tag `v2.3.0` (annotated), push branch + tag.
- [ ] Renderer: stays `v2.2.1` at `4e2227d`; no new renderer package.
- [ ] LAV: unchanged.
- [ ] Do not attach or publish the old 13-November setup.

## 8. Field tests outstanding

1. **Wiped-profile Video Processor (§3.8)** — **DONE 2026-11-18**: verified on
   the wiped profile (empty `active_input_url`) with the dev build; see the log
   in §3.8. A true first-run (delete `HKCU\Software\Unplugged` too) is still
   untested but reaches the same `StartVp` path.
2. **UNC library on the second PC** — share `D:\Movies` from this PC
   (`tools/unc_test/setup_movies_share.ps1`, elevated; not run yet), install
   2.3.0 on the other machine, confirm posters lose UNAVAILABLE, Play opens,
   and pulling the share re-marks it within 5 s.
3. **Refresh matching on the projector** — confirm the display exposes 23/24 Hz
   modes and the log shows `refresh: apply … actual=23/24`; confirm the same in
   **Video Processor** (`refresh: live fps=… target=…` then `apply`), and that
   the notice does **not** appear when the mode exists. Do not expect a switch
   on the MSI MD342CQP: it has no rate between 23 and 30 Hz (§3.5).
4. **Subtitle placement** — a scope title with a bottom black bar: text sits in
   the bar at 65 %, does not extend up into the picture; a PGS title and a
   VobSub title still draw; forced-subtitle track selection still works.
5. **Dropdowns** — Audio, HD audio, Subtitles: themed, clickable, selection
   sticks across re-open.
6. **SDR policy on all three classes** — SDR title: label after the settle,
   grade Off, opt-in persists; HDR10 title: no label, grade untouched; DV P8:
   no label at any point (already confirmed once).
7. **UR-0002** — `0x80040217` on a K-Lite machine. Reproduce on the 2.3.0
   engine and check whether `[GRAPH] File Source (Async) Load hr=…` appears
   before the failure (see USER-REPORTS.md).
8. **UR-0003** — Static nits step/range and hiding it while Convert to SDR.
   Decision pending; options in USER-REPORTS.md.

## 9. Traps this session paid for

1. **UNC roots need the trailing separator.** `GetDriveTypeW` says
   `DRIVE_NO_ROOT_DIR` without it. Any new volume/root probe must keep it.
2. **`src/SubPic/SubPicAllocatorPresenterImpl.cpp` is legacy Windows-1252.**
   Edit it with PowerShell `Get-Content -Raw` / `Set-Content -Encoding Default`,
   or the file is re-encoded and the diff becomes the whole file.
3. **The fork's libass subtitle path cannot be repaired piecemeal.** It
   produced 10×10 subpics from 8×-frame maths. The working stack is MPC-HC's
   internal RTS, swapped wholesale; do not reintroduce libass without the
   `SubRendererSettings` dependency graph.
4. **A subtitle provider with an empty video rect draws nothing.** The engine
   never called `SetPosition`; `RenderEx3` must pass the viewport and cropped
   video rect, and `SetSubPicProvider` must fall back to the full canvas.
5. **Scale the subtitle destination, not the texture.** Scaling at blit time
   keeps authored ASS/PGS look; place into the bottom bar only when a bar
   exists (`windowRect.bottom - videoRect.bottom > 1`).
6. **System popup menus ignore the app theme and disabled items look broken.**
   Use `CListPicker`.
7. **`std::max` / `std::min` are Windows macros.** Use the unqualified form or
   a ternary in this codebase.
8. **Never infer SDR from missing fields.** The DV P8 evidence is in §3.6: pin
   `tf=0`, first renderer read `tf=5/dovi=0`, DV `tf=15/dovi=1` 1.3 s later.
9. **Parse renderer pipeline tokens every tick.** They lived inside the
   1-in-5 log throttle; that 5 s staleness is what made the old 3 s rule fire
   before the DV flag was ever read.
10. **Reset renderer-derived cache in `Open`.** Tokens are assigned only when
    present, so without a reset a DV flag survives into the next title.
11. **Gate a class on its source.** `srcHash` prevents the previous graph's
    verdict being applied to a newly opened title during the open gap.
12. **Display refresh ≠ presented FPS.** Never read the primary display's
    capabilities; use the app's monitor. Present the two numbers separately.
13. **Do not publish the 13-November installer.** It carries the old renderer.
14. **`s3_start_device("")` means capture OFF, not "use the default".** A
    wiped profile has an empty `active_input_url`; `StartVp` must resolve a
    port before calling the engine (§3.8).
15. **A live cadence comes from `dl.fpsNum/fpsDen`, not `signal.*`.** The
    card's signal-mode read is `0/0` while streaming; only the running stream
    knows its rate (§3.5).
16. **Restore the display mode before any relaunch.** `s_refSaved` is
    process-local, so `RelaunchProcess` from a matched VP session used to leave
    the desktop at the source's rate forever. The restore lives in
    `RelaunchProcess` itself now.
17. **`OnDisplayChange` must re-place to the window's monitor, not the
    primary.** A matched VP session may be on the secondary 4K display;
    re-placing to the primary would yank it there on the very switch that was
    meant to fix pacing.
18. **A silent no-op reads as a bug.** The file path only reports a missing
    mode when the user toggles the row; in VP there is no title open to hide
    behind, so the live leg always shows the toast (once per cadence) and logs
    `refresh: notice shown`. Keep `notify=1` there.
19. **This test machine cannot prove refresh matching at all.** MSI MD342CQP
    (the convenience panel) exposes no 23–30 Hz mode at any resolution;
    Hisense/Denon EDIDs do. Measure on the TV/projector.
20. **Working rule.** The user performs picture testing; do not capture
    screenshots/frames unless asked.

## 10. Where to look first

| Topic | Location |
| --- | --- |
| UNC root probe | `native_ui.cpp` `PathRoot()` (~8452) |
| Work rect / 4K canvas | `native_ui.cpp` `WorkR()` (~10083), `Create2` host creation |
| Playback dropdown | `native_ui.cpp` `CListPicker` (~2471) |
| Refresh matching (file) | `native_ui.cpp` `MatchRefresh*` (~6494), `CurrentRefreshHz` (~124) |
| Refresh matching (live) | `native_ui.cpp` `LiveRefreshPoll` (~9872), called from `PollStats` |
| Output depth (Info row) | `native_ui.cpp` `CurrentOutputDepth` (~133); renderer gate `Preferred10BitOutput` |
| SDR policy (app) | `native_ui.cpp` `UpdateSdrMl` (~10420), `PollStats` class block (~10490) |
| SDR policy (engine) | `MpcPlayer.cpp` `contentClass` (~4648), pipeline parse (~4300), reset in `Open` |
| Subtitle size / bar | `SubPicAllocatorPresenterImpl.cpp` (~123) |
| Subtitle provider / position | `MPCVRAllocatorPresenter.cpp` `RenderEx3`, `SetSubPicProvider` |
| Engine subtitle scale | `MpcPlayer.cpp` `SetSubtitleScale` (~5551) |
| Protocol | `s3engine.cpp` `{"a":"subscale","percent":N}` (~715) |
| ClipGuard | see HANDOVER-2.3.0-clipguard.md §10 |
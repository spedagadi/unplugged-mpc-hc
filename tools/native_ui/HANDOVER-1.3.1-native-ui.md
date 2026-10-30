# HANDOVER — native C++/MFC "Unplugged" UI (v1.3.1 work in progress)

Written 2026-10-26 for a fresh session. Read this first. The PyQt6 1.3.0 app
(`src/unplugged-ui/src/mpvprocessor/`) is the SPECIFICATION; `native_ui.cpp` is the
single-file port. The user's standing rule: replicate 1.3.0 exactly, verify before
handing over, never make the user the test harness.

---

## 1. What this deliverable is

`tools/native_ui/native_ui.cpp` — one MFC file, ASCII-only with \uXXXX escapes
(PowerShell re-encoding corrupted UTF-8 literals once; do not reintroduce UTF-8).
It links `tools/s3engine/s3engine.dll` (the engine C ABI: `s3_attach`, `s3_cmd`,
`s3_stats`, `s3_start_device`, `s3_shutdown`).

Why native at all: the PyQt6 chrome cannot receive mouse/keyboard over the Direct3D
video surface. 1.3.0's layout/colours/metrics are copied from its Python sources;
where this file deviates it says so in a comment.

### Build / deploy (exact commands)

```
MSBuild tools\native_ui\native_ui.vcxproj /p:Configuration=Release /p:Platform=x64
cmd /c tools\engine_s3\rebuild_engine.bat          # mpchc_engine.lib
cmd /c tools\s3engine\build_s3engine.bat           # s3engine.dll
copy tools\s3engine\s3engine.dll tools\native_ui\s3engine.dll      # app
copy tools\s3engine\s3engine.dll tools\engine_s3\s3engine.dll      # sub_proof harness
```

Vendored / side-by-side dependencies (all required at runtime):
- `tools/native_ui/vendor/webview2/` — WebView2.h + WebView2LoaderStatic.lib (static; no DLL ships).
- `tools/native_ui/decklink_monitor.dll` — Blackmagic signal monitor; `LoadLibrary`d by the
  engine from the EXE directory. Without it `s3_start_device` returns 0x80070485
  (ERROR_DLL_INIT_FAILED). It ships next to s3_shell.exe and inside the installed app.
- WebView2 Evergreen runtime (installed: 155.0.4283.62). `winsqlite3.dll` from System32
  (loaded at runtime for the library index; no third-party SQLite in the project).
- GDI+ and dwmapi linked via `#pragma comment`.

### Logs (where each one lives — this cost real time to learn)

| Log | Path |
|---|---|
| native UI | `tools/native_ui/native_ui_log.txt` (timestamped, `t=` ms since first line) |
| ENGINE | `%USERPROFILE%\.unplugged\logs\engine.log` — NOT s3engine.log |
| renderer | `%LOCALAPPDATA%\Unplugged\logs\mpcvr_trace.log` |
| Qt 1.3.0 audit | `%USERPROFILE%\.unplugged\logs\unplugged.log` |

Crash forensics without a debugger: WER `Fault offset` + `tools/native_ui/native_ui.pdb`
-> resolve RVA to file:line with dbghelp (`SymFromAddr`/`SymGetLineFromAddr64`,
`SizeOfStruct` must be 88 on x64). A working resolver script existed in `%TEMP%\symresolve.ps1`
(ephemeral — copy it into the repo if you need it again).

---

## 2. Window architecture (as built 2026-10-25/26)

```
CMainFrame            WS_POPUP, full monitor +2px bleed each side (EDGE_BLEED),
                      WS_EX_TOPMOST while active (OnActivate), DWM corner pref DONOTROUND,
                      DWMWA_BORDER_COLOR = COLOR_NONE (kills the 1-2px light ring)
  UnpluggedVideoHost  child, inset 2px; HostProc subclass forwards WM_MOUSE*/WM_KEY*
                      up to the frame; 50ms identical-message dedupe (MPCVR's
                      put_MessageDrain posts a SECOND copy of every input message)
    MPCVR child       created by the engine ON THE THREAD THAT BUILDS THE GRAPH.
                      Never build a graph on a thread that will exit: the renderer
                      window is orphaned with no pump -> black screen, audio only.
  CPosterPane         child: the media library grid (media mode idle screen)
  CSplashPane         child 520x400: WebView2 hosting splash-A-release.html
  COverlay            TOP-LEVEL WS_EX_TOPMOST|NOACTIVATE|TOOLWINDOW; region = union of
                      visible panes; children: CTopStrip, CStatusRail, CSettingsRail,
                      CTransportBar. Exists because the capture surface composites
                      above the frame's child tree (see defect B).
  CConfirmCard        TOP-LEVEL popup, NON-MODAL (no EnableWindow, no nested loop)
  CAcquireCard        TOP-LEVEL popup, NON-MODAL (VP "Acquiring signal" screen)
```

Startup: attach -> splash (5s QTimer, independent of load state, like 1.3.0) -> branch on
`app_config.json app_mode`: `media_player` -> library; `video_processor` -> `StartVp()`;
else library. File open is posted (WM_APP+1) and runs **on the UI thread on purpose**
(see the black-screen lesson above); the splash hides the ~1.2s stall.

Config: `%USERPROFILE%\.unplugged\app_config.json` (json.dump indent=2, i.e. a space after
every colon — a naive `"key":"` search silently returns nothing). Keys used:
`app_mode`, `media_folder`, `last_played`, `library_tab`, `active_input_url`.
`WriteMode()` rewrites only the app_mode value, preserving everything else.

Library data: `%LOCALAPPDATA%\Unplugged\library\library.db` (SQLite WAL) +
`...\library\art\*.jpg` (360x540 thumbs). Read-only; queries mirror `media/library.py`
verbatim. Wallpaper: `src/unplugged-ui/assets/images/unplugged_wallpaper.png`, drawn
CONTAINED over `RGB(10,10,10)` (background_widget.py), pre-scaled once into a 32bpp
canvas (a per-paint 4K bicubic cost 223-297ms and caused a 3.2s stall).

---

## 3. Verified working (with the evidence that proves it)

- Splash animation: your HTML, untouched; `splash NavigationCompleted success=1`;
  corners smooth (region removed; card + 1.5px border drawn by GDI+ AA; pane pad is a
  pixel-exact copy of the wallpaper behind it).
- Library: real posters from 1.3.0's own index/cache; tabs/breadcrumb/status/Play/VP
  per `media_library_panel.py`; single click selects, double click or Play opens;
  `last_played` preselected with orange caption + badge; info line = label / EXT / size / path.
- Media playback: open, transport, seek, volume, pcm/bitstream, chapters, rails (earlier days).
- Close: X raises the non-modal confirm; Yes -> `s3_shutdown()` (bounded 10s, pumps sent
  messages) -> WM_CLOSE -> exit. Alt+F4 same path. Esc dismisses, Enter confirms.
- Mode persistence: `app_mode` written in place; VP launch goes straight to capture.
- VP capture: `s3_start_device('DeckLink Quad HDMI Recorder (1)') rc=0x00000000`,
  `vp: signal acquired (N frames drawn)`, acquire overlay dismissed on `render.draw>0`.
- Perf: splash->library 3.2s -> 157ms after the wallpaper canvas cache.

---

## 4. OPEN DEFECT A — subtitles do not render on selection (media mode)

This is the live task. Everything below is measured; nothing here is opinion.

### The chain
1. Rail sends `{"a":"subtrack","index":opt-1}` (opt 0 = "Off" -> -1). Engine `rc=0`.
2. Engine log: `[SUBS] subtitle pins found=1 target=0 spliced=1; initial selection=Off`
   then on each pick `[SUBS] subpic provider attached` / `subtitle track N -> rendering=N spliced=1`.
3. Engine counters, line `[live] subs: render11=... drew=... lastRt=... noQueue=...`
   (MpcPlayer.cpp ~3323): `render11` = presenter's DrawSubtitles callbacks,
   `drew` = successful AlphaBltSubPic, `noQueue` = dropped-for-empty-queue.
4. Observed on EVERY engine binary tested (installed 1.3.0 24/10, dist 25/10, fresh 26/10):
   `render11` climbs past 1000, `drew=0`, `noQueue=0`, `lastRt` tracking the playhead.
   Engine's own comment (MPCVRAllocatorPresenter.cpp:180-183) defines this signature:
   "this stream delivers no data (calls climb, drew stays 0)".
5. So: the presenter is asked correctly, at correct times, and the subtitle queue is empty.
   The decoder for the selected stream was never built.

### Why (the mechanism)
`SpliceSubtitleFilters(targetRel)` inserts a `CTextPassThruFilter` between the splitter's
ONE subtitle pin and the `CNullTextRenderer` sink. It runs once at graph build while the
demuxer selection is still "Off", so `ConnectDirect` negotiates whatever type LAV offers
then. `IAMStreamSelect::Enable` afterwards does NOT re-type an existing connection, so
`CSubtitleInputPin::CompleteConnect` (where libass/CPGSSub/CVobSub is chosen) never runs
for the real stream. The file's own comment says the enabled stream is the selector
(MpcPlayer.cpp ~1769) — the enable simply happened too late.

### What was tried (do not repeat these)
- 26/10 ~10:40 — live un-splice + re-splice on track change. Re-splice then found
  `pins found=0`: after disconnecting, the pin's FIRST enumerated media type no longer
  classifies as Text/Subtitle (the code only inspects `EnumMediaTypes` entry 0). Abandoned.
- 26/10 11:05 — CURRENT BUILD: mirror the audio pattern. `pendingSubTrack_` +
  `m_fileRebuildPending`; `BuildGraph` calls `SelectStream(Subtitle, pendingSubTrack_)`
  immediately before `SpliceSubtitleFilters(0)`; `Open()` resets it for a new source;
  `SetSubtitleTrack` queues and re-opens (position preserved). **User reports it still
  does not render.** Not yet re-measured with counters after this change.

### First things to check in the new session (in this order)
1. **Does the file even have subtitle events at the tested time?** The harness seeks to
   4:30. `ffprobe -select_streams s:0 -show_entries packet=pts_time` on
   `D:\Movies\28.Years.Later.The.Bone.Temple.2026.mkv`. If events start later, `drew=0`
   is expected everywhere and the whole diagnosis above is wrong. (This check was queued
   and never run.)
2. Instrument `CSubtitleInputPin::CompleteConnect` with a Log — it currently logs nothing,
   so "the decoder was never built" is inferred, not observed. Find the sink source with
   `grep CSubtitleInputPin src/mpchc_engine src/filters`.
3. Read LAV's `IAMStreamSelect::Enable` for media-subtitle pins in `c:\code\LAVFilters`
   (demuxer/LAVSplitter.cpp): does enabling a stream on an already-connected media-subtitle
   pin retag it, or does it require a reconnect? If it requires reconnect, the correct fix
   is to disconnect/reconnect that ONE pin after Enable (not re-run the whole splice).
4. Compare with MPC-HC's own path referenced at MpcPlayer.cpp:4274
   (`CMainFrame::InsertTextPassThruFilter`, MainFrm.cpp:18902-18935).
5. `tools/engine_s3/sub_proof.exe` now takes `argv[2]` = engine DLL path (it used to
   hard-code the packaged dist DLL and silently test a stale binary). Its PNG grabs were
   NOT rewritten by recent runs and its three reported frame sizes were identical — find
   out why before trusting its visual proof.

Objective pass/fail for any fix: `[live] subs: ... drew=N` with N>0, and text visible in a
frame grab at a timestamp that has events.

---

## 5. OPEN DEFECT B — chrome invisible over VP capture

Symptom: in video processor mode Up toggles state (`ui: up` in the log, panes visible and
topmost among the frame's children) but nothing appears over the live capture.

Evidence gathered:
- `chrome up: topChild=<pane> topPane=(0,0,3436,44) vis=1` — panes ARE shown and topmost
  among frame children.
- Pixels inside the strip rect read the video, not 14,14,16.
- A top-level WS_EX_TOPMOST popup (the confirm card) was ALSO covered (probe read
  224,236,250 where its orange button should be) — so this is not a child-z-order problem.
- The process owns exactly one visible top-level window (the frame) while this happens.
- Conclusion reached: the capture presents above the HWND tree (composition/overlay plane),
  so no amount of SetWindowPos inside the frame helps.

Current implementation state (built, UNVERIFIED by the user, who says it still fails):
- `COverlay` top-level topmost window holding the four chrome panes, region = union of
  panes, follows the frame's topmost state in OnActivate.
- `ApplyVpLayout()`: in VP mode the video host is inset so it never occupies the strip/bar
  pixels; Up toggles the rails and narrows the video further. Logs
  `vp layout: video=(...) strip=(...) bar=(...) overlap=none|YES` — read that line.
- Duplicate-input dedupe lives in BOTH HostProc (50ms identical message) and
  `CMainFrame::OnKeyDown` (60ms same vk) — the frame receives each key twice in VP mode
  (own + drained copy), which made Up toggle up-and-down in one press.

Measurement pitfalls (each one produced a false conclusion once):
- Screen captures are INVALID unless the app is foreground at capture time; the app drops
  topmost on deactivation by design, so a capture taken while the user types elsewhere
  shows their desktop. Use AttachThreadInput + SetForegroundWindow immediately before.
- Row-mean comparisons are useless over a live HDMI source (content changes between shots).
  Probe fixed pixels, or better read the `vp layout:` log line.

---

## 6. Smaller known defects / deviations

- `Subtitle/OSD brightness` slider built 0..100 but the renderer clamps that field to 0..2
  (VideoRenderer.cpp:462). Wrong range on its face; fix the mapping.
- Library `Folders...` and `Rescan` buttons log only (no scanner reimplemented by design;
  the index already exists). `Video Processor` button performs the mode switch.
- Mode switch after any graph has run RESTARTS the process (1.3.0's `_switch_mode` rule);
  before that it switches in place. `m_graphRan` is set by both file open and capture start.
- Splash/confirm/acquire cards are WS_EX_NOACTIVATE so they never steal activation.

## 7. Traps already paid for (do not re-pay)

- `CreateEx(..., nID)` on a NON-child window passes nID as hMenu. Passing 909 made the
  confirm dialog silently fail to exist for days.
- `DrawText` ignores DT_VCENTER without DT_SINGLELINE; TxtW now forces the pairing.
- GDI `RoundRect`/`CreateRoundRectRgn` take an ellipse DIAMETER; Qt border-radius is a RADIUS.
  Clip strictly OUTSIDE the painted curve or the corner shears.
- COM `[in]` parameters in async Invoke callbacks are valid only during the call — AddRef
  to keep. Storing raw gave a freed controller: grey splash + AV in put_Bounds.
- `std::max/std::min` are windef macros; use IMAX/IMIN in this file.
- `s3_stats` returning <=0 must not skip the z-order heal (VP mode has no stats early).
- Never tear the engine down synchronously from a UI handler that the renderer can
  SendMessage into; `s3_shutdown` is bounded and pumps sent messages.
- A detached thread running `Open` orphans the renderer window (black screen, audio only).

## 8. Process rules from the user (binding)

- No workflows / no subagents (explicitly banned after repeated waste).
- Never hand over an unverified build; verify it yourself first.
- Replicate 1.3.0 from its source; never paraphrase from memory.
- One feature at a time; keep runs on their machine short and announced.
- They pay for results; long diagnostic spirals are unacceptable — prefer the smallest
  measurement that can falsify the current hypothesis.

## 9. Current machine state

- `app_config.json`: `app_mode=video_processor` (user switched), `media_folder=D:\`,
  `library_tab=movies`, `last_played=Shaun...mkv`,
  `active_input_url=decklink://DeckLink Quad HDMI Recorder (1)`.
- `D:\Movies`: 28.Years.Later.The.Bone.Temple.2026.mkv (28 subtitle tracks),
  By.Any.Means.2026.mkv, Dune.2021.mkv, Oddity.2024.mkv.
- Latest builds: native_ui.exe 26/10 ~10:0x (overlay + VP layout), s3engine.dll 26/10 11:05
  (pending-subtitle-at-connect). Both UNVERIFIED by the user for defects A and B.

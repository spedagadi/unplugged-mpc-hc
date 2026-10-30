# Native UI — week task list (2026-10-27 → 2026-10-30)

Reference implementation: PyQt 1.3.0 under `src/unplugged-ui/src/mpvprocessor/`.
Port: `tools/native_ui/native_ui.cpp` (+ engine `src/mpchc_engine/` when required).

Working rules
- One task at a time. Build and verify before marking DONE.
- Verification = engine log/counter/readback or a captured frame, never "looks wired".
- Record the evidence line under each task when its status changes.
- Use 1.3.0 source as the specification; note deliberate deviations.
- Update this file at the end of every day.

Status: TODO | WIP | VERIFY | DONE | BLOCKED

| ID | Task | Target | Status |
|---|---|---|---|
| T1 | Default to English | Tue 27 | DONE |
| T2 | History: watched + continue, survives storage detach | Wed 28 | VERIFY |
| T3 | Slider input: wheel + focus/up-down arrows, all sliders | Tue 27 | VERIFY |
| T4 | Context help banner left of the focused control | Wed 28 | VERIFY |
| T5 | Aspect ratio management / NLS | Thu 29 | WIP (core done, see log) |
| T6 | IR remote integration | Fri 30 | TODO |
| T7 | Add/remove presets | Thu 29 | DONE |
| T8 | Support Unplugged in video-processor (VP) mode | Fri 30 | TODO |
| T9 | Dolby Vision P5 colours (decoder → renderer config + fixed IPT conversion) | after release | TODO |

Side work done during T5 (not on the list, all verified unless noted)
- Chrome: edge-reveal panes (left/right/bottom), whole-chrome idle auto-hide,
  cursor hide/show owned by the poll, stuck tooltip fix, panels suppressed in the
  library, auto-hide no longer blocked by a visible pane.
- Display: text now scales with the DPI layout (300 % was unreadable), 300 %
  status panel scrolls, display-mode changes re-place the window.
- Playback: Ctrl+S frame capture to Pictures\Unplugged\<date>\frame_NNNN.png,
  stop clears playback UI, mute icon redrawn, volume slider clamped to what the
  audio path can do.
- Library: storage availability is checked eagerly (shelves + TV shows), shown on
  the poster (`!` badge + UNAVAILABLE strip), Play disabled with the reason.
- Engine/renderer: bar band per-frame + latched, geometric crop (single resample),
  MC relocated after the warp, squeeze support, fill modes, scaler pruning,
  `barsNow`/`activeFrac`/`display`/`nls` in the status JSON.

Carried-over defect outside this list
- Subtitles: provider attaches and the probe sees an ACTIVE event at the playhead, but
  `render11` climbs and `drew=0`. Fault is in the subpic queue/blit leg (engine/renderer,
  not the splice). If this is promoted, it should replace T6 or T8 this week.

## T9 — Dolby Vision P5 colours (after the release)

Found 2026-10-29 while chasing a P5 TV-show colour cast:

- **LAV demuxer** is DV-aware (`LAVFDemuxer.cpp:3074` reads `AV_PKT_DATA_DOVI_CONF` and
  creates the enhancement-layer substream for P7).
- **LAV Video decoder** has no DOVI handling at all — the frame's DV side data is dropped
  and nothing about the config reaches the output media type.
- **Renderer** has no parser: `m_Dovi` is only ever read (`DX11VideoProcessor.cpp`), never
  filled, so `bValid` is permanently false. P5 is therefore rendered as ordinary
  BT.2020 YCbCr, which is the wrong-colour symptom.

Two pieces of work:
1. **Plumbing** (hours): carry the DOVI config from the decoder to the renderer. The
   HDR10+ path already proves the mechanism — MPC-BE's `IMediaSideData` per-sample blobs.
   Done when the engine log prints the profile.
2. **P5 conversion** (the real cost, ~a day): P5's constants (IPT matrix, C2 curve) are
   PROFILE constants, so correct colour does not need the RPU — it needs the profile
   known and an IPTPQc2 → IPT → BT.2020 PQ shader branch. The RPU would add dynamic
   per-scene tone mapping, which is separate and later.

Blocker to call it done: a short P5 clip on the test machine. Without one the conversion
cannot be verified, and an unverified colour transform is worse than the current state.

Priority: explicitly AFTER the release.

---

## T1 — Default to English
Goal (confirmed): when a media file opens, choose **English AUDIO only**. Subtitles stay
under the user's/subtitle-mode control.

Audit first
- 1.3.0 behaviour for audio defaults (`main_window.py` playback start, LAV splitter
  preference) and how the rail's active audio flag is chosen.
- Does "English" accept eng/English GB/SDH variants? Default: accept any English until
  told otherwise.

Implementation points
- Engine: select English audio at connect (same pending/connect-time rule used for the
  audio track so no live renegotiation).
- UI: rail highlights the chosen audio track.
- Config: decide whether the preference is fixed or persisted.

Acceptance
- A multi-language file opens on the English audio track.
- Engine log shows the audio selection; the rail matches.
- A file with no English falls back deterministically (document the fallback).
- Subtitles are not implicitly enabled by this task.

## T2 — History: watched and continue
Goal: watch/resume history persists even when the media volume is detached, at least for a
bounded retention period.

Audit first
- Current library schema and where watched/resume state lives (`media/library.py`,
  `library.db`), and whether paths on `D:\` are the only store.
- 1.3.0 library tab/shelf semantics for Continue/Watched.

Implementation points
- Store history in the LOCAL library DB, independent of the media drive.
- Keep entries when the source is missing; mark unavailable rather than delete.
- Resume position updates on pause/close/periodic checkpoint; ignore bogus positions.
- Decide retention/cleanup policy.

Acceptance
- Play 2+ minutes from `D:\`, detach `D:\`, restart app: history entry still listed and
  marked unavailable, not silently dropped.
- Reattach `D:\`, open the entry: resume reaches the stored position.
- Watched state survives restart and detach.

## T3 — Slider input: wheel and keyboard
Goal: every slider responds to mouse wheel; focused sliders respond to Up/Down.

Reference
- `s3shell_panel.py`: `wheelEvent`, `_nudge`, focus model; one increment per notch,
  int rows vs 2-decimal float rows.

Implementation points
- Wheel over a slider track: one step per notch; do not scroll the panel.
- Click/focus a slider; Up/Down changes one step; keep focus visible.
- Apply and persist through the existing live `PushRow` path.
- Audit EVERY slider row, including DEV rows when internals are shown.

Acceptance
- For each slider: wheel changes by exactly one step, value readout updates, engine
  receives it, INI persists it.
- Up/Down works on a focused slider and not on another row type.
- No value change when the wheel is outside a slider.

## T4 — Context help banner
Goal: a help banner appears left of the settings rail for the focused/hovered control,
as in 1.3.0.

Reference
- `ui/help_store.py`, `ui/help_card.py`, guide markdown; focus/hover source in
  `s3shell_panel.py` (`row_focused`, `row_updated`).

Implementation points
- Port the help text source for every displayed row.
- Banner geometry: left of the rail, stays on-screen, no clipping/overlap, rounded card.
- Show on hover and keyboard focus; update live value where 1.3.0 does.
- With `ui.helpBanner` ON, keep the full card on screen after the pointer leaves
  a row; no timed strip/badge collapse (user decision 2026-10-28). Hide only when
  the setting is OFF or the settings rail is not part of the visible surface.

Acceptance
- Every visible row has correct help text.
- Banner never covers the control it describes; text is readable at 4K and 1080p.
- The last row stays readable with the pointer elsewhere; switching group or
  collapsing a section re-picks a visible row instead of leaving stale text.

## T5 — Aspect ratio management / NLS
Goal (confirmed): **NLS = non-linear stretch**. Aspect controls include Auto / 16:9 / 4:3 /
Zoom-crop / Non-linear stretch.

Audit first
- Locate 1.3.0's aspect surface and renderer interface.
- Determine where the control belongs (OUTPUT/Picture vs playback).
- Confirm exact NLS mapping expected (centre protected, sides stretched).

Implementation points
- Presets: Auto / 16:9 / 4:3 / Zoom-crop / Non-linear stretch (final list from audit).
- Apply live through the renderer/engine interface; persist in the shared INI.
- Preserve video geometry; NLS must stretch only by its intended mapping.

Acceptance
- Each mode visibly changes geometry on a known test pattern; switching back restores Auto.
- Selection persists across restart and graph rebuild.
- No letterbox/crop regression in the library or VP layout.

## T6 — IR remote integration
Goal (confirmed): **FLIRC / keyboard-emulating receiver**. The remote already arrives as
normal keyboard shortcuts; support them through the existing key path — no separate HID stack.

Audit first
- Capture the exact key codes FLIRC emits for this remote.
- Compare with the 1.3.0 key map and current native WATCH/EDIT/library key handling.

Implementation points
- Map: Up/Down/Left/Right, OK/Enter, Back/Esc, Play/Pause, Stop, Volume +/-, mute,
  Home/library, and mode shortcuts where 1.3.0 defines them.
- Input must not steal focus from the video surface or get swallowed by the D3D child.
- Reuse the existing key path/dedupe; no second competing hotkey system.

Acceptance
- Each mapped key performs one action with the remote; no double-press/dedupe failures.
- Works in WATCH, EDIT/settings and library contexts consistently with 1.3.0.
- Logs record the received key and resulting action.

## T7 — Add/remove presets
Goal: users can create and delete presets, not just view/apply them.

Reference
- `preset_manager_dialog.py`, `profiles/manager.py`, preset activation/loading paths.

Implementation points
- Create preset from current settings; name entry and validation.
- Delete preset with confirmation (non-modal card, same family as other confirms).
- List refresh and persistence across restart; activating a preset re-pushes settings.
- Preserve active preset when creating/deleting others.

Acceptance
- Add -> appears immediately, survives restart, applies its values.
- Delete -> confirmation, removed from disk/list, active preset not left dangling.
- No silent overwrite of an existing preset name.

## T8 — Support Unplugged in VP (external repo)
Goal (confirmed): integration target is a **different repository**:
`https://github.com/billslack2/videoprocessor` — not this repo's DeckLink video-processor mode.

Audit first (BLOCKING)
- Clone/read the repo, its README, build system and extension points.
- Define the concrete deliverable with the user: embed/launch Unplugged as its player?
  share the settings/engine interface? replace its rendering path?
- Determine whether it consumes `s3engine.dll`, MPCVR, or another backend, and what
  "support" means at the ABI/UI boundary.

Implementation points (provisional)
- Add the integration at the repo's own extension point; do not fork its architecture.
- Reuse Unplugged's engine/settings surface where compatible; document any adapter layer.
- Keep modes/inputs/resolution settings working in the host project.

Acceptance (to finalise after audit)
- The host repo builds with Unplugged integrated.
- The documented workflow starts, renders, and changes settings without leaving the host UI.
- No duplicated settings store or conflicting renderer registration.

---

## Day plan

### Tuesday 27
- T3 slider wheel/keyboard (fast, low risk; establishes focus model reused by T4).
- T1 default English AUDIO (audit + implement + verify; subtitles unaffected).

### Wednesday 28
- T2 history persistence (schema/storage first, then UI).
- T4 context help banner (reuses focus model).

### Thursday 29
- T5 aspect/NLS (audit first; needs the questions below answered).
- T7 presets add/remove.

### Friday 30
- T6 FLIRC remote key mapping (reuse existing key path).
- T8 external videoprocessor repo: audit/clone first; define deliverable with the user,
  then implement only what the audit shows is needed. Largest item - timebox it.
- End-of-week regression + update this file + update HANDOVER.

## Open questions to answer before their task starts
1. T8 (blocking): after auditing `https://github.com/billslack2/videoprocessor`, what is
   the exact deliverable — embedded Unplugged player, shared engine/settings, or a
   compatibility adapter? Everything else in T8 follows from that.
2. T1: accept any English variant (eng, English GB, English SDH) for audio? Default is yes.

Resolved 2026-10-27:
- T1 = English AUDIO only.
- T5 = non-linear stretch.
- T6 = FLIRC keyboard-emulating receiver.
- T8 = external repo https://github.com/billslack2/videoprocessor.

## Verification log
- 2026-10-27 T1 DONE — Dune opened: `[GRAPH] default English audio track 2 applied at connect hr=0x00000000`
  (English TrueHD Atmos; German tracks 0/1 correctly skipped). 28.Years (single English audio) chose track 0.
- 2026-10-27 T2 VERIFY — close checkpoint wrote
  `history write 'D:\Movies\28.Years...mkv' pos=826.7 watched=0 rc=101`.
  Sheet UI replaced the old History tab: rendered `TO CONTINUE` shelf, `UNWATCHED`
  grid and always-present `WATCHED` shelf (screenshot: 2+5+0, 8 cols at 3440x1440).
  After the 30 s continue threshold: `library: movies sections continue=1 unwatched=6
  watched=0`; Enter on the focused continue tile logged
  `library: play 'D:\Movies\28.Years...mkv' resume=826.7s` and
  `open dispatching ...`.
  Refinement (same day): rails now use the grid's exact tile size (uniform posters,
  column count 5..10 chosen so >=1.25 grid rows fit), and the green timeline sits
  BENEATH each continue poster with `13% watched · 1:35:26 left` under it. Evidence:
  checkpoint `history write ... pos=834.4 dur=6560.4 watched=0 rc=101`, then the
  library rendered at 13% (capture inspected 1:1 and 4x for the bar fill).
  Remaining: watched-shelf visual, unavailable/detached check, TV section check.
- 2026-10-27 Library folders (new, parity gap) — the header's `Folders…` button now opens
  the 1.3.0 `FoldersDialog` (roots list with `(not reachable)`, `Add folder…` via the
  Windows folder picker, `Remove`, `Done`). `Done` writes `roots` with `set_roots`
  semantics (normalise, dedupe, drop folders inside another root, delete removed roots'
  items) and starts a background scan. The scanner is the 1.3.0 walk ported natively
  (`.mkv`/`.mp4`, same skip dirs/suffixes, name_parse rules, sidecar/folder/season art,
  missing→present=0 after a complete walk). Evidence:
  `folders dialog: added 'D:\Shows'` → `library: roots set to 1 (was 1)` (D:\Shows is
  inside the existing D:\ root, correctly dropped) → `library scan done in 5203ms:
  11 new, 4 updated, 8 missing` → `library scan: UI reloaded (6 tiles)`; second scan
  `15 updated` in 15ms (no churn). Sheet headers renamed `Continue...` / `New`.
- 2026-10-27 Online posters (OMDb) — added because the new scanner left The Penguin
  without art: movies/shows with no sidecar now get the same OMDb lookup as 1.3.0
  (`t=<title>&type=movie|series`, poster URL with `img.omdbapi.com` fallback, portrait
  ratio check). Key comes from `omdb_api_key` in app_config.json, then the shipped
  `_omdb_key.py`. Evidence: `library art: 'The Penguin' -> ...\art\omdb_tt15435876.jpg`;
  the poster renders on the TV Shows tab (`tv sections continue=0 unwatched=1`).
  `Bad Apples` OMDb's poster URLs are dead (both Amazon and img.omdbapi 404), so a
  last-resort Wikipedia lookup was added for movies: article `<Title> (<year> film)`,
  a File:* containing "poster", imageinfo URL, portrait check. Evidence:
  `library art: 'Bad Apples' -> Wikipedia ...\art\wiki_bad_apples.jpg`, visible in the grid.
- 2026-10-27 Media-player playback controls (new):
  - Arrows: tap ±10 s while playing; tap one frame while paused; hold ramps
    playing 10→30→60 s and paused 1→5→10→30→60 s (200 ms timer + GetAsyncKeyState,
    ignores OS auto-repeat). Shift+arrow = immediate ±60 s.
  - PgUp/PgDn = previous/next chapter; Space/Enter play-pause; S = stop; Esc ladder
    (chrome → stop); Home/End start/end; 0–9 jump 0–90 %; +/- volume; M mute.
  - Stop writes history, pauses, cancels auto-next, hides the chapter tip and returns
    to the library; the item is in Continue and the Play button reads Resume.
  - Transport bar has an on-screen Stop button (rounded square) right of pause, live
    only while a file is playing (dim otherwise). Click → same stop path. Evidence:
    `stop button pressed`, `stop (button) pos=32.5 dur=6204.5 -> library`.
  - Chapters: stats names now parsed; timeline draws chapter ticks + a tinted current
    segment; hovering the bar shows `time · Chapter N of M · name` in a top-level tip;
    seek/chapter/frame/volume/stop show a 2 s toast over the video.
  - Evidence: stop at 5.5 s of a 20 s chaptered clip →
    `stop (S) pos=5.5 dur=20.0 -> library`, `sections continue=3 unwatched=5 watched=0`;
    Enter then `library: play '...Aaa.Playtest...' resume=5.5s`.
    `chapter jump dir=1 -> 3/3 t=12.00 'Ending'`; engine `[ENGINE] step dir=1 ...`;
    hold log `seek ... (+10 s)` then `(+30 s)`; captures verified the chapter tooltip
    (`0:07 · Chapter 2 of 3 · Middle`) and the seek toast.
  - Fixed while testing: `WriteHistory` marked every clip shorter than 30 s watched
    (flat 30 s end window); the window now scales with duration (5..30 s).
- 2026-10-28 Full "New" page selection — opening the full section used to reset scroll
  to 0 while keeping the current selection, so the selected title (and the Play/info
  line) could be far below the viewport with no ring visible. Entering a full section
  now ensures a valid selection and centres its row before painting. Verified:
  `full section new (42 items) sel=35 'The Dog Stars' scroll=559`, ring + info visible.
- 2026-10-28 "App stalled" after one click — the hover-detail card is a topmost
  window; it was NOT hit-test transparent, so once it appeared under the pointer it
  swallowed every subsequent click and the library looked frozen. The media tip,
  chapter tip and toast now carry WS_EX_TRANSPARENT (mouse passes through; the pane
  receives the click and hides the card). Verified by clicking three different TV
  show tiles in sequence: `lib CLICK section=1 idx=0/1/2`.
- 2026-10-28 TV Continue item click — a Continue episode (e.g. Andor) now opens its
  series at that season's episode list on a single click, so the user can choose any
  episode; it no longer just selects (or plays). Verified: click on the Andor
  Continue tile → breadcrumb `TV Shows › Andor › Season 2` with all five episodes
  listed and S02E01 selected. Movie Continue items remain select-only.
- 2026-10-28 Single-click series navigation — a single click on a SHOW now opens it:
  a one-season show goes straight to its episode list; a multi-season show shows the
  season list first (one click per season). Single click on a season opens its
  episodes; a click on a file only selects it. Verified: one click on Born to Be Wild
  (1 season) landed directly on its five episode tiles; info line says
  "Click or Enter to choose a season/episode".
- 2026-10-28 Episode selection — container tiles now advertise and expose the next
  level: the info line for a show says "Enter to choose a season", for a season
  "Enter to choose an episode"; a single click on a season (or folder) opens its
  contents immediately (shows stay selected so Play can start the series). Episode
  tiles select on one click, then Play/double-click starts the file. Verified: one
  click on "Season 1" opened the five episode tiles; Enter then played S01E01.
- 2026-10-28 Collapsible Watched rail — the Watched section is collapsed by default
  (header only) so the New grid gets the height; a `+` button at the right of its
  header expands the horizontal, scrollable watched row, and becomes `−` to collapse.
  Expanding also happens on Down from the last New row; collapsing while a watched
  tile is selected moves the cursor back to New. Full-page Watched remains reachable
  by clicking its header when it overflows. Verified: collapsed layout gives New
  ~3 rows; click logged `library: watched rail expanded` and the row/`−` appeared.
- 2026-10-28 Wheel scrolling — a notch now moves `max(100 px, tileH/3)` (was 72 px),
  wheel direction follows Windows (down = forward), high-resolution deltas are
  multi-notch, and no repaint happens at the scroll bounds. The pane reuses one
  persistent 4K back buffer instead of allocating a compatible bitmap per paint.
  Verified: six notches moved 0→114→228→342→456→570 px and the grid advanced a row;
  paint log shows only the first new-row paint at 63 ms, subsequent wheel paints
  below the 40 ms threshold.
- 2026-10-28 Scroll performance + bad ffprobe data.
  - Scroll: near-2:3 posters (e.g. OMDb 380x562 in a 2:3 cell) are drawn straight
    from the decoded cache; redrawing them through a composed/blurred cell bitmap was
    adding a first-reveal stall per tile. Poster interpolation is HighQualityBilinear.
    Slow-paint instrumentation (>40ms) now logs the scroll/full state. After the
    change, wheel paints in the New grid were below the 40ms threshold; only initial
    startup paints (art/probe refresh at scroll=0) remain.
  - ffprobe: stderr was merged into the stdout pipe. A warning/error line made the
    "JSON" non-empty, ParseProbe found no streams and cached an all-zero record as
    done. stderr now goes to NUL, the process exit code must be 0, ParseProbe rejects
    JSON without streams, and ProbeRows re-queues any all-zero/invalid record.
    Civil War re-probed: `dur=6526.4, br=84.2 Mbps, 3840x2160, DV P7, TrueHD Atmos
    7.1`. 86 other bad records are queued for the background pass.
- 2026-10-28 Posters: online-only + fit/no-crop.
  - Art is now taken ONLY from OMDb (Wikipedia fallback), never an MKV embedded
    cover, sidecar or folder image. `art_checked` + weekly retry replaces existing
    non-online art in the background; rescans preserve `omdb_`/`wiki_` art instead of
    reverting to sidecar/embedded art. Nope moved from the cropped 360x540 embedded
    thumb to `omdb_tt10954984.jpg` (380x562, full poster with the NOPE title).
  - PaintPoster now uses CONTAIN (whole artwork visible), never cover-crop; leftover
    cell area is filled with a dimmed blurred copy of the same art
    (`BlurFor`, cached per art+cell size), so a non-2:3 poster is neither cropped nor
    letterboxed with hard bars. 2:3 art still fills the cell exactly.
  - Old cached 360x540 thumbnails were cropped at generation time (1.3.0
    KeepAspectRatioByExpanding); they cannot be un-cropped locally, so they are being
    replaced by the online originals during the poster pass.
- 2026-10-27 Blank poster after Stop — `RefreshArtTiles` copied an episode's empty
  `art` column over the fallback poster (`show_art`/`season_art`) when the poster pass
  ran after returning to the library. It now only overwrites with a NON-empty value;
  verified by forcing an art refresh (9 rows updated) and confirming Andor's Continue
  poster stayed visible.
- 2026-10-27 TV + chrome fixes (reported bugs):
  1. Series seasons are explicit: entering a show now always shows the season list
     (`Season 1`, `Season 2`...) instead of auto-selecting the only season. Breadcrumb
     stays `TV Shows › Show`.
  2. Library Play works on show/season tiles: `PlayShow` resumes the in-progress
     episode, else the first unwatched, else the first present. Evidence:
     `library: play series 'Andor' -> S02E01` then a normal `open`.
  3. DV P5 gamut: DV masters are BT.2020 even when the container omits primaries;
     probe now sets it and the card also corrects BT.709→BT.2020 for DV/P8 titles.
     Verified Andor card: `Dolby Vision P5 · BT.2020` (not SDR/BT.709).
  4. Chrome recovery in media selection: `F1` toggles the chrome in any mode, and Esc
     while the chrome is down in the library brings it back (instead of doing nothing).
     Verified `ui: down` → `ui: up` for both Esc and F1.
- 2026-10-27 "probing..." forever (Arundhati) — the probe cache could hold a
  `probe_key` with an EMPTY `probe_json` (a failed/migrated write), so `ProbeRows`
  treated the file as already probed. It now re-queues any row whose result is empty;
  verified by probing Arundhati: `{"dur":7881.514,"br":14703109,"res":"1920x1080",
  "hdr":"SDR","audio":"AC-3 5.1"}`. The remaining empty rows (25) drain through the
  background queue over subsequent passes.
- 2026-10-27 Dolby Vision profiles — Everest was reported as falsely DV. ffprobe on
  the actual file shows `side_data_type: DOVI configuration record`, `dv_profile: 8`,
  `dv_bl_signal_compatibility_id: 1` (and the filename says DV.HDR10P.HYBRID), so the
  file really carries an injected P8 RPU even though the title never had a Dolby
  Vision release. The card now treats P8 as METADATA on a normal base layer:
  `HDR10 · BT.2020` (gold) plus a violet `DV P8 metadata · base layer HDR10` line;
  P5/P7 (true DV masters) stay `Dolby Vision P5/P7`. Probe cache bumped to `p3`;
  141 old DV rows are queued for a background re-probe. Verified Everest:
  `"hdr":"HDR10","dv":1,"dvp":8,"dvbl":1`.
- 2026-10-27 Responsiveness + colour coding:
  - Scan no longer fetches posters before showing the grid: `ScanAll` only walks/indexes,
    the UI reloads immediately, then a background OMDb pass fills posters/genres in
    batches (refreshing tiles every ~500 ms without a full Reload), and only when that
    finishes does the ffprobe pass start. All three run on workers; keys/hover keep
    working. Status line: `Updating library...` → `Fetching posters... n/n` →
    `Reading media details... n/n`.
  - Verified order: `library scan done in 360ms` (283-title disc) → UI reload →
    `art: starting background poster/genre pass` → `probe: probing missing media facts`;
    a Down keypress during the pass was handled (UI not blocked).
  - Hover card colours: Dolby Vision violet, HDR10 gold, HLG teal, SDR grey; HD audio
    green, lossy audio grey; probing lines dimmed. Card refresh throttled during the
    probe pass to avoid flicker/log spam.
- 2026-10-27 Hover details (Genre / Year / Duration / HDR-Gamut / Bitrate / HD Audio):
  - DB gains `probe_json`, `probe_key`, `genre`. A background ffprobe pass
    (`-show_format -show_streams`, one file at a time, 20 s timeout) fills duration,
    overall bitrate, resolution/fps, transfer/primaries, DV flag, MaxCLL/FALL and the
    best English audio track (codec/profile/channels, HD flag); cache key includes a
    `p1|size|mtime` version so changed files re-probe.
  - OMDb lookups now also capture `Genre` for movies and shows (same request as the
    poster pass), so no extra API call for titles that already had a poster.
  - 350 ms hover card beside the cursor: title, `year · genre`, `duration · Mbps`,
    `Dolby Vision/HDR10/HLG/SDR · gamut [· MaxCLL]`, `TrueHD Atmos 7.1 (HD)`; unknown
    lines read `probing...`. Shows show genre + episode count and use the first
    present episode for the technical lines; folders are ignored.
  - Evidence: 252 present rows got genres (`Dune` = Action/Adventure/Drama), probe pass
    reached 104/283 files in the test window (`Dune` = DV · BT.2020 · 67.3 Mbps ·
    TrueHD Atmos 7.1 HD; `Bad Apples` = SDR · 15.2 Mbps · E-AC3 5.1). Captures verified
    both the movie card and the TV card (`Andor`: genre + 12 episodes + probing lines).
  - ffprobe lookup: exe dir / tools / repo fallback / `C:\htpc` dev path / PATH; the
    release package needs an ffprobe next to the app (prefer an LGPL build).
- 2026-10-27 Chapter names — inspected the new disc's remuxes with ffprobe: their
  MKV chapter titles are literally "Chapter 01".."Chapter 06", so LAV/our engine were
  reporting the real metadata, not a fallback. The UI now treats `Chapter <digits>` as
  generic and shows only `Chapter 3 of 8` in the tooltip/toast instead of duplicating
  it; real names (test clip: Opening/Middle/Ending) still show as
  `Chapter 2 of 3 · Middle`.
- 2026-10-27 Large-library overflow + clipping:
  - Root cause of the overlap: `PaintPoster` replaced the GDI+ clip with its own
    rounded path and then `ResetClip()`, destroying the grid/shelf viewport clip after
    the first tile. A scrolled library painted grid rows over Continue and Watched.
    The viewport/shelf rect is now passed into `PaintPoster` and applied as an
    intersection per poster.
  - Overflowing sections get a full page: header chevron when items exceed the band
    capacity; Up from the first row focuses the header (or click it); Enter/click opens
    the section full-width (same poster grid, ribbon + count, `< Back (Esc)`); Esc/Back
    returns to the sheet. Non-overflowing sections never show the chevron.
  - Evidence with the 283-title library: `library: open full section 1`,
    `library: full section new (65 items)`; captures verified the scrolled overview has
    no bleed into the other bands, the full page renders 9 columns, and Esc returns.
- 2026-10-27 Title normalisation — captions/info now run through `NormTitle`: only
  all-lowercase titles are title-cased (small words a/an/the/and/... stay lowercase
  except first/last; hyphen segments capitalised). Mixed-case/acronym titles are
  untouched. "the dog stars" now renders "The Dog Stars" like the other captions;
  captions remain one style (13 px bold title, 11 px sub) for movies and series.
- 2026-10-27 Section headers — uniform 14 px bold name (`Continue` / `New` /
  `Watched`) + a 4x18 px vertical colour ribbon (Continue violet #9B7BD8 - kept away
  from the orange accent, New blue, Watched gold #C8A030 because green is reserved
  for the continue progress bar) + 11 px right-aligned count (`N title(s)`). The explanatory hints were
  removed (user: over-explaining); no more orange underlines. Empty sections keep a
  single muted line. Header band 34 px. Verified on a capture.
- 2026-10-27 SYSTEM settings (new): `Show context banner for settings` and
  `Play next item automatically`, both `noeng` (INI only, not pushed to the renderer),
  default On, seeded as `ui.helpBanner` / `ui.autoNext`. The banner row gates
  `CSettingsRail::ShowHelp` (off hides immediately, hover/focus show nothing).
  Auto-next: context is captured at Play (section snapshot + TV show/season/episode);
  on a real `state=ended` (not Stop) it writes the finished item as watched, shows an
  "Up next" card with a 5 s countdown (Play now / Cancel), then opens the next item.
  TV advances episodes, then seasons; stop at end of the show/section (user's choice).
  Evidence with two 2 s clips in a temporary folder (removed afterwards):
  `library: play ctx ... idx=0` → `auto-next: next item 'Aab Autonext 2099' at 1/8` →
  `auto-next: ... in 5s` → capture shows the card (title + `Playing in 3 s...`) →
  `auto-next: playing '...\Aab.Autonext.2099.mkv' resume=0.0s` → next countdown fired.
  Also fixed: the INI seed save failed with err=5 because the read `ifstream` was still
  open; closed before `SeedIni`, keys now persist (`ui.autoNext=True`,
  `ui.helpBanner=True`) and load (`ini loaded ... helpBanner=0` when set False).
- 2026-10-27 Scan feedback — Rescan now actually starts a scan (it only reloaded the
  DB before). While scanning: Rescan becomes dim `Scanning...` and the status line shows
  `Updating library...`, then `Fetching posters... n/total` (worker posts WM_APP+28).
  Captured at 250 ms into a scan: both texts visible. Unreachable roots are appended to
  the idle status as `Not reachable: <folder>` (1.3.0 media_library_panel.py:693-703).
- 2026-10-27 Play From Beginning — new button left of Play, visible always but enabled
  ONLY for a playable tile in the Continue section (`BeginEnabled()`); disabled in New,
  Watched and the flat Folders/TV drill-down grids. Evidence:
  `lib PLAY FROM BEGINNING pressed sec=1 enabled=0` in New (no playback) and
  `lib PLAY FROM BEGINNING pressed sec=0 enabled=1` +
  `library: play FROM BEGINNING 'D:\Movies\28.Years...mkv' resume=0.0s`, after Up moved
  the cursor to the Continue shelf.
- 2026-10-27 T3 VERIFY — wheel + focused Up/Down call `StepRow`; each step logs `slider step '<label>' -> <value>`
  and goes through PushRow/INI. Needs a full all-slider audit in the UI.
- 2026-10-27 T4 VERIFY — `help: 79 guide entries ... settings-guide.md`; card logs `help show '<row>'`
  on row change. Needs visual placement/text check.
- 2026-10-28 Single-click model (user decision: "Continue resumes"):
  - Continue movie or episode poster -> resume immediately (`Play`, honours
    `last_pos > 5s`). Continue TV tiles also draw a distinct `EPISODES >` chip at
    the poster's top-left; the chip (and the whole caption strip beneath the poster)
    opens that series at the episode's season instead of playing. New/Watched files
    still only select; show/season/folder tiles still open on one click.
  - The old Continue TV branch (single click opened the season list) was removed.
  - Evidence: `lib CLICK section=0 idx=0 (Andor)` +
    `library: play ... Andor.S02E02... resume=1376.8s`; chip click ->
    `library: episodes 'Andor' season 2` with no `library: play` line and the
    Season 2 grid captured; New tile `lib CLICK section=1 idx=0 (Born to Be Wild)`
    with no play line; Movies Continue `lib CLICK section=0 idx=0 (Dune)` +
    `library: play 'D:\Movies\Dune.2021.mkv' resume=15.6s`.
- 2026-10-28 Seasons + episode status:
  - The episode grid for a show with more than one present season now has a visible
    `Season 1` / `Season 2` ... strip above the posters. The current season is
    outlined in the orange accent; hovering a season button (or the strip's chevrons
    when the row overflows) fills it with the accent. Clicking a season swaps the
    grid in place (`library: season N selected`); the wheel over the strip scrolls
    it horizontally. Single-season shows keep the old no-strip layout.
  - The Continue tile's `EPISODES >` chip turns accent orange on mouse-over (user
    confirmed live). The chip and poster caption still open the season list; the
    poster itself resumes.
  - Every episode tile now carries its own status: `Watched` (full green 100%
    timeline + green check), `n% watched · <time> left` (partial green timeline),
    or `Not started` (empty grey track). This uses `last_pos`/`duration`/`watched`
    from the episode row, so a long season no longer loses where the user is.
  - Evidence: `library: episodes 'For All Mankind' seasons=2 selected=1 strip=1`;
    captures show Season 1 selected + Season 5 hovered with the accent fill, and
    the orange Episodes chip. Andor S2 shows `Watched`, `53% watched · 20:58 left`
    and `Not started` on consecutive episode tiles. (The multi-season case needs
    real data the test library does not carry: two temporary `uitest-*` rows were
    inserted for the layout proof, then deleted; `fake_left=0`,
    `famm_seasons=1` after cleanup.)
- 2026-10-28 Poster misses fixed:
  - `Euphoria US`: the scanner title came from the folder, but OMDb only knows the
    show as `Euphoria`. `FetchPoster` now tries the literal title first and then
    strips a trailing country tag (`US`/`UK`/`AU`/`CA`/`IE`/`NZ`) before giving up;
    the log shows `matched OMDb as 'Euphoria'` and the 380x562 portrait is cached.
  - `Born to Be Wild` (2025): OMDb has the series but only a 300x169 promotional
    still; `img.omdbapi` 404s. Poster selection now prefers a 2:3 portrait and
    keeps a wide-but-valid image as a last resort; the renderer's existing
    contain + blurred backdrop path displays it instead of a green placeholder.
    Log: `-> ...\omdb_tt28445317.jpg (wide fallback)`.
  - Shows with no online art are now asked for a poster even on a genre-only
    lookup, so a recent failed `art_checked` cannot hide newly matched art.
  - Evidence: `art: 4 rows updated`; DB show_art set for both; files verified at
    380x562 and 300x169; TV grid capture shows Euphoria's portrait and Born to Be
    Wild's still with blurred fill. (`art_checked` was reset once for these two
    titles to force the retry after the lookup fix.)
- 2026-10-28 Series destination chip (user decision: destination chip + season
  chooser):
  - Every series card now labels the chip by where it goes: one season ->
    `EPISODES >`; multiple seasons -> `SEASONS (N) >`. Continue keeps the chip
    persistent (poster still resumes); New/Watched reveal it on hover.
  - Continue multi-season chip/caption now opens the season list, not the current
    season's episodes (`library: seasons 'Andor' (2)` verified with a temporary
    second season; the Season 1/Season 2 chooser was captured). Single-season
    Continue still opens its only episode list (`EPISODES >`).
  - New show tiles keep their existing click behaviour: single season -> episodes,
    multiple -> season list; the hover chip now names that destination. Watched's
    subtitle gained `Watched · N seasons` so the count is visible before hover.
  - Fixed the New/Watched chip hover target: it was computed with `ShelfR` (the
    horizontal rails) for section 1, so the chip never turned accent in New.
    Section 1 now uses `GridR`; the orange hover was captured on a New tile.
  - Temporary `uitest-*` season rows used for the multi-season checks were deleted
    afterwards (`fake=0`, Andor/For All Mankind back to 1 season).
- 2026-10-28 Stop now clears the video surface:
  - StopToLibrary sent `{"a":"pause"}`. Pause keeps the graph alive and leaves the
    renderer's last frame parented in the host, so the stopped picture stayed
    visible around/behind the library.
  - Added `{"a":"stopgraph"}` to s3engine: it calls `MpcPlayer::Stop()` (real
    `IMediaControl::Stop()` + `DetachRendererWindow()`), while the old `stop`
    stays a benign pause for live capture. StopToLibrary uses it and invalidates
    the host so its wallpaper repaints immediately.
  - Evidence: `stop (button) ... -> library (stopgraph rc=0)`; capture after Stop
    shows the library/wallpaper with no Dune frame. Replaying Dune after the stop
    rebuilt normally (`open rc=0 took=1328ms`) and a second stop again returned
    `stopgraph rc=0`.
  - s3engine.dll was rebuilt and staged into tools/native_ui.
- 2026-10-28 Library landing selection:
  - A fresh app start or a tab switch now starts on Continue (then New, then
    Watched). Folders keeps its first-item selection. Log:
    `library: fresh selection sec=0 idx=0`.
  - The persisted `last_played` still gets its play badge, but no longer steals
    the cold-start selection; `lastPlayedSession` is only set by a play in this
    run. After playing and stopping, the stopped title is reselected
    (`library: selection lastPlayed sec=0 idx=0`) and moves to the front of
    Continue because the section is sorted by `last_seen`.
  - Internal reloads preserve the user's current section instead of snapping to
    New when the section's own selection had been reset.
  - Evidence: cold-start capture has Dune selected in Continue and the info/Resume
    row; after playing 28 Years Later and stopping, that title is first and
    selected; switching to Folders shows the D: root selected.
- 2026-10-28 Stop clears the whole playback UI:
  - The transport bar kept the old position/duration and its chapter ticks after a
    stop, because the stopped graph still reports them and `PollStats` kept
    feeding `m_bar`. `StopToLibrary` now clears chapters, position, duration,
    bitstream/dim, audio state and the chapter tooltip, and resets the bar state
    to 0/0 with no chapters. `GoLibrary` calls the same reset so every landing on
    the library is clean.
  - `PollStats` now only accepts position/duration/chapters while
    `InFilePlayback()` is true; a stopped graph's stale chapter list can no longer
    repaint the timeline. Non-file mode still keeps volume/mute and the VP bar.
  - Evidence: playing 28 Years Later reported 8 chapters, then Stop logged
    `playback UI cleared (timeline/chapters=8)`; the capture after Stop shows the
    library with no transport timeline.
- 2026-10-28 Context help stays displayed:
  - With `ui.helpBanner` ON the card no longer disappears when the pointer leaves
    a row. `CSettingsRail` remembers the last row and keeps the full card on
    screen; moving through gaps/section headers no longer hides it, and there is
    no timed collapse to a strip/badge.
  - If no row has been shown yet, it picks the first actually visible row (not a
    row in a collapsed section). Switching group or opening/closing a section
    re-picks the visible row; turning the setting OFF hides the card immediately.
  - The card is hidden when the settings rail is not part of the visible surface
    (library, chrome down, VP setup), so it cannot float over the poster wall.
  - `SetUi(true)` asks the rail for the remembered/default row, so the card is
    present as soon as settings are shown; `ClearKeyFocus` resets the memory when
    the chrome drops.
- 2026-10-28 T7 presets (VERIFY):
  - Top-right `Preset <name> ▾` control opens a preset card. It enumerates
    `Default` plus custom presets from `%LOCALAPPDATA%\Unplugged\presets\*.ini`;
    clicking a row applies it immediately.
  - `Default` is virtual and always present. It is built from the compiled row
    defaults (`defOn/defVal/defOpt`) and its Save/Rename/Delete actions are
    disabled and rejected in the backend. Custom presets support New (snapshot of
    current settings), Save (overwrite active custom), Rename, and Delete (with
    an in-card confirmation). Names are validated and cannot silently overwrite.
  - Preset values cover persistent rows of kind 0/1/2/4, excluding `ui.*` system
    preferences. Applying pushes every changed row through `PushRow`, so the
    engine, INI and future graph rebuild all see the preset.
  - Changing a preset-eligible setting while `Default` is active marks the label
    `Default *` (now drawn in the accent colour) and raises the warning card once:
    "Default is read-only. Create a preset to save changes." New from that card
    snapshots the modified settings into a custom preset.
  - FIXED 2026-10-28: the card no longer opens itself. It used to pop up on the
    FIRST settings change while on Default — including a NLS toggle mid-drag —
    because `OnPresetDirty` called `ShowWarning()`, which also takes foreground.
    The top strip now carries the whole message (accent-coloured `Default *`,
    tooltip "Unsaved changes — choose or create a preset"); the card opens only
    on a user click on the preset control, and when that happens on a dirty
    Default it opens with the create-preset header.
    Evidence: `preset: Default changed -> top-strip marker only (no auto-open)`
    with no card line after it; a click gives
    `preset picker open (dirty on Default -> create-preset header)` then
    `preset card open (warn=1, ...)`.
  - Evidence: `preset card open (warn=0, active='Default', count=1)`;
    `preset created 'Test One'`; `preset apply 'Default' changed=41` and
    `preset apply 'Test One' changed=41`; `preset rename 'Test One' -> 'Demo'`;
    `preset delete 'Demo'` followed by `preset apply 'Default' changed=41`;
    presets folder empty afterwards. Warning card captured:
    `preset card open (warn=1, active='Default')`, with the full warning text.
  - Remaining verification: exercise the warning through a real settings-rail
    value change (the card capture was triggered through the same WM_APP+38
    handler; the `PushRow -> PresetNoteRowChanged` call site is wired but was not
    driven by a live slider/toggle in this pass). Also re-check active-preset
    persistence across a restart.
- 2026-10-28 Transport item/seek buttons + hover affordances:
  - Transport bar now has previous item (`23EE`), fast backward, play/pause,
    fast forward, next item (`23ED`) and stop. Back/forward seek by 30 s; previous/
    next use the library playback context (`PrevBefore` added beside `NextAfter`):
    episode-to-episode when playback started from an episode list, otherwise the
    previous/next playable tile in the section playback started from. Missing
    entries are skipped; end/start shows a toast. Starting another item writes the
    current position to history and swaps via the normal open path. Manual
    previous/next always start the new item at 0:00 (no last-played resume);
    auto-next keeps its own resume rule.
  - Every transport/top-strip/library control now has a hover tooltip (the
    transport uses its existing chapter tip; the rest use one shared top-level
    `CChapterTip`). Settings rows keep the richer context-help card instead.
  - `CUiWnd::HandAt` + `WM_SETCURSOR` gives a hand cursor over interactive panes:
    transport controls/timeline/volume, top-strip controls, library buttons/tabs/
    tiles/season strip/series chips, settings rows/headers, preset rows/buttons.
  - Mid-play item switch fix: pressing Next while Andor was playing hung inside
    `Cmd(open)`'s teardown because the old graph was still live. `PlayContextPath`
    now shows the "Next episode/Next item" toast, writes history, calls
    `{"a":"stopgraph"}` (detach renderer), then posts the normal open.
    Verified live: Andor S02E02 -> Next -> `auto-next: next episode S02E03`,
    `item switch: stopgraph rc=0`, `next item '03. Harvest'`, `open rc=0
    took=1250ms`; app stayed responsive. Previous returned to S02E02 with its
    saved resume (1454.2s), and FF/FB logged `seek ... (+30 s)` / `(-30 s)`.
    The transport-bar button hit-test itself was not screenshot-captured; the
    WM_APP handlers it posts were exercised end-to-end.
- 2026-10-28 Top-of-video "Now Playing" panel:
  - The 48 px transport strip was too tight for a title. A separate decorated
    top-level topmost panel now appears at the top-centre of the window, over the
    video: accent bar, `NOW PLAYING`, title (18 bold) and the SxxEyy/episode line
    (12 accent).
  - It shows on playback start and whenever the seek bar is hovered/dragged
    (`WM_APP+45` from the transport timeline), then auto-hides after 4.2 s; every
    new seek interaction resets the timer. Stop/library hides it immediately.
  - The title comes from the library item: show + SxxEyy (+ episode label when
    known) for TV, movie title/year otherwise; next/previous refresh it.
  - Evidence: capture shows `NOW PLAYING / Andor / S02E01` at 560x92, top-centre;
    after 5 s `IsWindowVisible=False`. Build clean.
- 2026-10-28 Cursor reset:
  - `CUiWnd::OnSetCursor` now always resolves the pointer itself: hand when
    `HandAt(p)` is true, arrow otherwise, instead of falling back to CWnd with a
    stale hand/busy cursor. `HostProc` also forces the arrow over the video host.
  - `HandAt` extended to the confirm/folders dialogs in addition to transport,
    top strip, library, settings and preset surfaces.
  - Build clean. This is a cursor-state fix; if an OS busy/spinner cursor still
    appears it is a separate blocked-work indicator, not the pane hand cursor.
- 2026-10-28 Backward-compatible chrome + persistent Info/Settings toggles:
  - Media-mode startup/stop lands on the media selection with the top strip and
    transport bar; status/settings appear only if the user previously enabled
    them. Defaults are off.
  - Top strip `Info` (left) and `Settings` (right) toggle their panels
    independently. Hover turns the label/border accent; active state stays accent.
  - Panel choice is persisted as `ui.showInfo` / `ui.showSettings` in
    `s3_shell.ini`. If off, Up/F1/double-click full chrome will not resurrect the
    panel; only the explicit button turns it back on. Verified: toggles wrote
    `True`, a restart started with `ui: up full=0 panels info=1 settings=1`, then
    toggles wrote `False`; test left both off.
  - Up keeps its old meaning: from hidden it opens the chrome (full level); a
    second Up hides it. F1/double-click do the same. Seeking does not override an
    explicitly chosen panel; the Now Playing banner still appears.
  - Overlay region is recomputed from the visible panes. Build clean.
- 2026-10-28 Uniform top-right preset layout:
  - The preset-name field is now a fixed 180 px slot with `DT_END_ELLIPSIS`
    instead of sizing to the current name. Switching between short/long preset
    names no longer moves the `Preset` label, `Settings` button, minimize or
    close controls.
  - Build clean.
- 2026-10-28 Compact preset card:
  - The fixed 400x470 card was mostly empty. It now sizes to content: width
    360; list mode is `160 + N*34` px tall for up to six visible rows (scrolls
    beyond), input mode 252 px, delete confirmation 232 px. A one-preset list is
    194 px, four presets 296 px.
  - Mode changes call `Place()` so New/Rename and Delete immediately shrink the
    card; cancel/commit restore list size. Delete no longer shows an empty list
    behind the confirmation.
  - Capture: 4-preset list at 360x296, compact and readable. Build clean.
- 2026-10-28 Preset auto-save + self-toggling card:
  - Custom presets are live now. `PresetNoteRowChanged` marks the preset dirty and
    a 300 ms debounce (`WM_APP+48` -> timer 12) writes the full preset file; the
    label only shows `*` while pending. Switching preset/creating/renaming or
    closing the app flushes the pending write. New/Rename/Delete remove the need
    for an explicit Save; the Save button is gone.
  - Card hint now says `Changes save automatically to this preset.` when a custom
    preset is active. Default remains read-only.
  - Clicking the top-right Preset control now toggles the card: open -> close ->
    open. X still works. Evidence: `preset picker close (toggle)` and card
    hidden.
  - Compact card now uses three buttons (New/Rename/Delete); verified 5-preset
    list at 360x330. Auto-save code path is wired; a live settings-change test is
    still pending.
- 2026-10-28 Simplified preset flow (supersedes Manage mode):
  - List rows only SELECT a preset; the card stays open. Buttons are
    New / Apply / Rename / Delete (no Save, no Manage/Done).
  - `New…`: name prompt; creates a copy of the compiled Default preset, applies
    it, and closes the card. The user is then on the new preset and settings
    changes auto-save through the 300 ms debounce.
  - `Apply`: applies the selected preset and closes the card.
  - `Rename`/`Delete` act on the selected preset; both are disabled for Default.
    Delete uses the compact confirmation.
  - Hint: `Changes save automatically. Select a preset, then Apply.` Selected row
    gets the highlight; the active preset keeps the accent bar.
  - Verified capture: 5-preset list at 360x330 with New/Apply/Rename/Delete,
    Bright selected, card stayed open; build clean. Live auto-save triggered by a
    real settings-rail change is still the remaining check.
- 2026-10-28 T5a geometry foundation (WIP):
  - New OUTPUT > GEOMETRY settings: Fit mode (Source / Fixed aspect / Fill
    screen), Fixed aspect, Zoom %, Pan X/Y. INI/preset-backed.
  - Engine `GeometrySettings` applies in `MpcPlayer::ResizeVideo`: fixed AR,
    fill, zoom crop and pan across the overflow; live pushes resize without a
    graph rebuild. `geo.zoom`/`geo.pan` are UI percentages converted to
    0.5..2.0 / -1..1 when pushed.
  - Verified geometry numerically from the renderer trace:
    - Fill: `geo.mode=2` stretches the picture to the window (user confirmed).
    - Fixed 1:1: 16:9 source renders `vidRect 1436x1436`, centred pillarbox.
    - Fill + Zoom 150% + Pan 50/50: `vidRect (-430,-180)-(4724,1974)` over a
      3436x1436 window, proving zoom crop and both pan axes.
  - s3_shell.ini restored to the default `geo.mode=0`, aspect 1.78, zoom 100,
    pan 0/0 after the tests.
  - Remaining: T5b NLS (the geometry foundation is now verified).
- 2026-10-28 T5b NLS first slice (WIP):
  - New NON-LINEAR STRETCH settings: Enable, Axis (Auto/Horizontal/Vertical),
    Strength, Centre protection, Curve, Max stretch. INI/preset-backed.
  - `NlsShader.h` is our own post-scale HLSL pass: protected-centre radius map,
    active-rectangle bounds, axis selection, ratio cap. It maps the active picture
    onto the full window, leaving subtitles outside the warp.
  - Engine builds the active bounds from the renderer's bar report
    (`bars: top/bot`) plus source/window aspect; enabling NLS also forces Fill
    geometry so the post-scale surface is the full window.
  - Open gaps before this is DONE: bars are sampled when the shader is injected,
    not continuously (a bar change needs a settings re-push); 4K60 cost and the
    no-ML-bar case are unverified; the live NLS visual test has not run yet.
    NLS is reset off in s3_shell.ini after the build. (Bar sampling and the
    active-picture math are fixed below; the other gaps stand.)
- 2026-10-28 Media card aspect ratio:
  - ffprobe now records a display aspect (`display_aspect_ratio`, else pixel
    aspect via `sample_aspect_ratio`, else width:height) as `ar` in probe JSON.
    Probe key bumped `p3` -> `p4`, so existing rows re-probe in the background.
  - Hover card line now reads `duration · bitrate · aspect`, e.g.
    `2h 11m · 67.3 Mbps · 16:9`; old p3 records fall back to a ratio derived from
    `res` until they are re-probed.
  - Build clean. Live hover capture/log not obtained in this pass.
- 2026-10-28 NLS mapping continuity fix:
  - The first NLS pass used a protected-centre linear band joined to a power
    curve that matched only the value at the boundary; the slope jumped there,
    producing the visible density step (user screenshot on 3440x1440 with 16:9
    content).
  - `NlsShader.h` now uses a cubic Hermite for the outer band, matching both
    value and slope at the centre boundary and easing to the source edge
    (edgeSlope = 1 - (ratio-1)*curve, floored at 0.20). Centre=0 uses a single
    smooth power curve.
  - Builds rebuilt: engine lib -> s3engine.dll. Live visual comparison pending.
- 2026-10-28 NLS uses the detected bar band (VERIFIED live, 3440x1440):
  - Answer to "is black bar detection active?": YES. Renderer trace from a live
    2160p DV title on the 3440x1440 screen:
    `[NLS] horizontal bars=180/180 of 1436 activeV=0.125..0.875 frameAR=1.778
     activeAR=2.373 winAR=2.393 ratio=1.009`.
    180 rows of 1436 = 12.5 % at each edge, i.e. the 2.39:1 picture inside a
    16:9 frame — the detector is measuring the right band. No forcing needed.
  - Why the bars survived anyway — two defects, both fixed in `ApplyPostFx`:
    1. The shader was only generated when `ratio > 1.005`, where ratio came from
       `W / activeH` — a window width over a source-frame height. For scope
       content on a scope screen the genuine remaining mismatch after cropping
       is ~1 %, so the crop was skipped exactly in the case it was needed.
       Now the active picture AR is `frameAR / hA` and the axis/ratio come from
       `winAR / activeAR`; the crop is applied whenever a band is present,
       independently of the warp (crop-only is a legitimate NLS state).
    2. The band was read once at injection time. A 4-minute-old sample read 0/0
       and baked `activeV 0.000..1.000` — no crop at all. `RefreshLive` now
       watches `bars: top/bot` every tick and `s3_stats` (UI thread) cashes in
       `ApplyPendingNlsRefresh()` -> re-inject when the band moves (1.5 s
       throttle; the band is a 90-frame union, so it moves at scene rate).
       Observed end-to-end: `18:55:36 bars=0/0 activeV=0.000..1.000` then
       `18:55:38 bars=180/180 activeV=0.125..0.875` with no user action.
  - Also fixed: toggling only `geo.nls` did not resize the video (ResizeVideo
    was gated on `hasGeom_`), so the fill geometry NLS depends on could be
    missed; now gated on `hasGeom_ || hasNls_`.
  - Screen capture of the running app: picture fills the full 3440x1440 frame,
    no top/bottom bars, geometry undistorted (ratio 1.009 ≈ identity).
- 2026-10-28 Up stopped toggling chrome after touching the settings rail (FIXED):
  - Repro from the log: user toggled NLS in the settings pane, then pressed Up.
    `KEY vk=26` appeared five times with no following `ui:` line; the last one
    toggled. Cause: `CSettingsRail::Key` claimed VK_UP/VK_DOWN to step sliders and
    move its row focus, and any click in the pane sets `m_kb`, so the frame's
    `m_settings.KeyFocused() && m_settings.Key(vk)` early-return ate the toggle.
    Movement of the invisible focus ring occasionally walked out of range, which
    is why the fifth press worked.
  - Rail now consumes only Left/Right (row focus). Up is always the full-chrome
    toggle, Down stays volume. A `settings rail consumed key vk=..` log line now
    makes any future swallow visible next to `KEY vk=26`.
  - User confirmation: verified on the running app after the rebuild.
- 2026-10-28 T5b: micro contrast moved across the warp, band made per-frame
  (requested: MC is the operator users prefer, so it must run after NLS, once):
  - Renderer: `DrawMLMicroContrast()` is now one shared helper used by BOTH
    positions. With `cmd_mlPostWarpMC` on, the grade block skips the MC draw and
    it is drawn after the custom post-scale chain — same single draw, same ring
    step count (the `StepSetting()` moves with the draw; an unmatched advance
    would leave the last pass writing into a ring texture). Off = chain unchanged.
  - Engine sets the flag from `ApplyPostFx` (`!nlsSrc.empty()`), on every call so
    a stale ON cannot outlive NLS being switched off, and logs the transition:
    `[NLS] micro contrast moved AFTER the warp (single draw)` (VERIFIED live).
  - Deband stays where it was — after NLS, before MC's new position — so it
    never grains the letterbox and MC enhances a de-banded, already-warped base.
    Adaptive Sharpen (off by default, per user preference) still runs last of
    the custom chain, i.e. before MC; acceptable while it is opt-in.
  - Band source changed from the 90-frame UNION to the PER-FRAME band:
    the union is a running min/max and a dark scene whose top rows dip under the
    detector's threshold grows it until the window rolls over. Measured live:
    `bars=688/598 of 1436` → `activeAR 17.0` → NLS zoomed the picture. The
    renderer now reports `barsNow: top=.. bot=..` as fractions of frame height;
    `RefreshLive` gates (symmetric within 1.5 %, neither bar > 45 %), requires the
    same band on two consecutive ticks, and `ApplyPostFx` rejects any band
    implying an active AR > 2.9 (widest real format ≈ 2.76). Verified:
    `bars=180/180 activeAR=2.373 ratio=1.009` stable, no 688/598 spikes.
- 2026-10-28 Launch with a file argument did not open it (FIXED):
  - `InitInstance` set the open intent and relied on the splash timer posting
    `WM_APP+1`, but that post did not exist — the app came up on the library and
    sat there, which reads as a hang (observed while verifying the MC change).
  - The timer now posts the launch intent after the splash, and the hardcoded
    `D:\Movies\Dune.2021.mkv` default is gone: only a file actually named on the
    command line is an open intent, so no launch opens anything unasked.
    Verified: `splash finished -> open the launch file` then playback from 0:00.
- 2026-10-28 T5b: aliasing fixed by moving the crop into the geometry:
  - Symptom: bad anti-aliasing on thin lines ("20th Century Studios" logo) with
    NLS on, 2.39 content on the 3440x1440 panel.
  - Cause: the crop was done by the post-scale NLS shader. Fill geometry had
    already resampled the frame (3840x2160 -> 3436x1436, 0.665 vertical), then the
    shader cropped 0.125..0.875 and magnified it 1.33x with a bilinear tap — two
    resamples, and the second one is what makes lines crawl.
  - Fix: `ResizeVideo` now grows the DESTINATION rect by 1/hA so the active band
    lands exactly on the window (the bars fall outside it). Fill + crop is ONE
    resize with the renderer's scaler. The NLS shader no longer crops (active
    bounds are the whole frame) and, when the residual aspect mismatch is under
    2 %, it is not injected at all — measured: `crop-only ... ratio=1.009 — no
    shader pass`. MC is then drawn in its normal grade position (no warp to move
    past), which the same log line records.
  - Pan footgun fixed: with the picture filling the window exactly, pan room was
    computed from the BAR-inflated destination, so a stored Pan Y of 0.15 (left
    over from the T5a test) slid the image up: 36 px black at the top, content
    lost at the bottom. Pan room now comes from the ACTIVE picture size
    (`destH*hA`), and the clamp keeps the active band covering the window — at
    zoom 1 the room is zero. Logged: `geom crop ... dest=(0,-257) 3436x1951`.
  - Residual black sliver (7-13 px top and bottom) came from the detector's
    144-row grid: its boundary is a box average and lands a row inside the real
    bar. The engine biases the confirmed band by one detector row (1/144) and
    rejects a 0/0 report (a phantom one-row band). Screen measurement after the
    fix: content from row 2 to row 1437 of 1440 — no sliver.
- 2026-10-28 Scalers pruned to the quality set (user: use the best, drop the rest):
  - Downscaling: Lanczos (default) + Bicubic sharp. Box, Bilinear, Hamming and
    Bicubic removed.
  - Upscaling: Jinc2m (default) + Lanczos3. Nearest, Mitchell, Catmull-Rom and
    Lanczos2 removed.
  - Chroma: KrigBilateral (default) + Catmull-Rom. Nearest and Bilinear removed.
  - Rows carry `optvals` so the INI/preset still store the ENGINE enum value and
    a pruned value cannot silently remap onto whatever moved into its index; a
    stored value that is no longer offered falls back to the row default.
    Verified after restart: `received out.downsc = 5, out.upsc = 5, out.chroma = 3`.
- 2026-10-28 T5b: the band is latched, not followed (title-card artifact):
  - Symptom: on a black title card ("THE SHIELD" art on black) the crop cut into
    the artwork — the detector read the card's black background as bars and the
    geometry followed it within a couple of ticks.
  - Bars are a property of the TITLE, not the shot, and luminance alone cannot
    tell a letterbox from art on black. Engine rules now:
    * a frame is only evidence when it has picture in it — the renderer reports
      `activeFrac` (share of cells with anything above the crop level) and frames
      below 0.45 can neither create nor move a band;
    * first confidence: two consecutive picture-bearing ticks → `band latched`;
    * replacement: the new band must hold 6 consecutive picture ticks (real IMAX
      scene changes survive, a fade or a card does not);
    * the latch resets on a graph-generation change (new title).
  - Until the band is KNOWN the geometry stays Source — a launch that begins on a
    black card is not stretched to fill on a guess (verified: candidate 0/0 while
    the card plays, `band latched 125/125` when the picture starts, then a
    `crop-only ... no shader pass` injection).
  - Observed during the intro after the fix: one transient candidate (132/125,
    activeFrac 0.528) that reverted the next tick and never replaced the latch —
    exactly the case that used to cut the art.
  - Renderer: `GetMLStats` gained the `activeFrac:` line.
- 2026-10-28 Chrome auto-hide (bars-only) + stuck hover tip:
  - Bars-only chrome now hides itself after 4 s of no pointer activity — the
    common case being: bring the chrome up, seek, then stop touching anything.
    Deliberately narrow: only when the BARS are the whole chrome (no live-status
    or settings panel — those are explicit choices and stay), only while a file
    is playing (the library needs its top bar), never in VP mode (the rails are
    the only route to the controls there), never over a confirm/preset/setup/
    folders card, and never during a seek or volume drag (`CTransportBar::Busy`).
  - Activity is a single timestamp fed by the frame, the top strip and the
    transport bar — their mouse messages land in the overlay window and never
    reach the frame, so feeding only the frame would have hidden the bars while
    the pointer was over them. Clicks feed it too (a seek click without movement
    would otherwise carry the old stamp).
    Verified: `ui: up` then `chrome: bars-only idle 4172ms -> auto-hide` ->
    `ui: down`.
  - The hover tip used to stay on screen when the chrome hid (it is its own
    top-level window, so the pane gets no mouse-leave): `SetUi` now clears the
    shared tip and the transport overlay on any chrome visibility change.
    Reported as "the Minimize card is stuck" after pressing Up.
- 2026-10-28 Cursor hides on idle playback (FIXED):
  - Reported: the cursor never hides while playing with no activity.
  - Cause: visibility was `ShowCursor(TRUE)` on every FRAME mouse-move paired with
    one `ShowCursor(FALSE)` from timer 3. The top strip, transport bar and
    settings rail live in the overlay window, so their moves never reached the
    frame: every such move was a show with no matching hide, and the per-thread
    ShowCursor counter drifted positive — one hide was never enough again.
  - Now ONE owner: `CursorHide()/CursorShow()` normalise the counter (loop to a
    negative/positive state) and the 300 ms poll drives them — hidden after
    2.5 s idle while a file plays, shown on any activity (frame, top strip,
    transport bar and settings rail all feed `UiActivity()`), and never hidden
    over a confirm/preset/setup/folders card or in the library. Timer 3's cursor
    path is gone.
    Verified: `cursor hidden (idle during playback)` / `cursor shown (activity)`.
- 2026-10-28 NLS refuses to fill a window that would need a big stretch:
  - Reported on a 3840x2160 display: 16:9-window + 2.39 content gave elongated
    heads. That is NLS doing exactly what it was told — removing the bars means
    stretching the picture 1.36x vertically, and no centre-protected warp makes
    that look right.
  - Rule: the geometric fill/crop only runs when the active picture is at most 5 %
    wider than the window (`activeAR <= winAR * 1.05`). That covers the real
    scope-film-on-a-scope-screen case (measured 0.9 %) and refuses the rest, which
    then stays letterboxed at its own aspect with no shader pass at all.
    Logged: `fill refused: picture AR 2.415 wider than window 1.780 — letterboxed`
    then `no pass ... (fill refused: letterboxed at its own aspect)`.
  - A band that geometry refused to crop is also never warped — the old
    `haveBars && !geomCrop` condition injected a warp that would have distorted a
    picture being shown at its own aspect.
  - Confirmed on screen (user, 3840x2160): full frame with black bars above and
    below, no stretching.
- 2026-10-28 Display-mode changes re-place the window:
  - A WS_POPUP frame keeps the monitor size it was created with, so after a
    resolution change the right/bottom of the window sat off-screen and the
    picture looked cut. `OnDisplayChange` now re-places the frame to the primary
    monitor's rect; WM_SIZE then resizes the host, the overlay and the engine.
  - Note for future captures: native_ui is per-monitor DPI aware, so a
    DPI-unaware screenshot tool captures 2560x1440 logical pixels of a 4K screen.
- 2026-10-28 Fill budget is a user setting ("Fill limit"):
  - New OUTPUT > NON-LINEAR STRETCH row `Fill limit` (`geo.nlsFillLimit`,
    100-200 %, default 105 %): how much vertical stretch filling may cost before
    it is refused. 100 % = never fill vertically; 136 %+ = fill a 16:9 screen with
    2.39 content (elongated heads, but the user's choice).
  - Engine: `NlsSettings::fillLimit`, parsed and clamped 1.0-2.0; the geometric
    crop test is `activeAR <= winAR * fillLimit`. Persisted in the INI and presets
    like every other NLS row; changing it re-runs `ResizeVideo` on the same push.
  - Horizontal filling (16:9 content on a scope screen) is deliberately not
    governed by it — that is what NLS is for.
  - Verified both ways on the 3840x2160 display: default 105 % logs
    `fill refused: picture AR 2.415 needs 36% vertical stretch, limit 5%`;
    with 140 % the same title logs `geom crop ... 3828x2918` and
    `vertical ... ratio=1.354` (fills, warp injected). Restored to 105 % after.
  - Settings guide updated with the row and its meaning.
- 2026-10-28 Text now scales with the rest of the UI (300 % display):
  - Reported: at 300 % Windows scaling the rail was huge with tiny labels — big
    empty controls, unreadable text.
  - Cause: every rect/control/row used `Px()` (MulDiv(v, g_dpi, 96)) but fonts
    were created at RAW device pixels (`CreateFont(-13, ...)`), i.e. the two
    halves of the layout scaled differently. At 96 dpi they coincide, which is why
    it only showed up above 100 %.
  - `TxtG`, `TxtBlock` and `MkFont` now size fonts with `Px(px)` too. At 96 dpi
    `Px` is the identity, so 100 % rendering is unchanged; above it the layout is
    uniformly scaled, which is what a DPI-aware window is supposed to do.
  - Consequence worth knowing: at 300 % a 4K screen behaves as a 1280x720 desktop,
    so the settings rail occupies 340/1280 ≈ 27 % of the width. If that reads as
    too much at large scalings, the next step is a responsive rail cap — the
    scaling itself is now coherent.
- 2026-10-28 Live status panel scrolls (300 % display):
  - At 300 % the row column no longer fits and the panel simply drew until the
    window ended — the remaining values were unreachable ("stuck, cannot see all
    details").
  - `CStatusRail` now keeps a design-px scroll offset, paints inside a clip below
    the header (a part-scrolled row can never paint over "Live"), clamps to the
    measured content height, and takes `ON_WM_MOUSEWHEEL` (one notch = 40 design
    px). A position bar at the right edge appears only when the content
    overflows, so "scrollable" is never mistaken for "truncated".
  - `LogF("status rail scroll=%d contentH=%d")` on every notch for verification.
- 2026-10-28 Ctrl+S quick frame capture (paused only):
  - Shortcut writes straight to `%USERPROFILE%\Pictures\Unplugged\<yyyy-mm-dd>\frame_NNNN.png`.
    One folder per day orders captures by date by construction; the counter is
    scanned from what is already in the folder, so nothing is ever overwritten —
    across sessions too. No dialog: a modal file picker over a paused frame blocks
    the UI thread and interrupts the thing the user is looking at.
  - Only while PAUSED. While playing it shows `Pause the picture to save a frame`
    instead: a "save" that grabs whichever frame the decoder happened to be showing
    is a coin toss. Plain `S` still stops playback; the Ctrl branch is checked first.
  - The OUTPUT → "Save frame as PNG" row keeps its Save-As dialog; both routes share
    `GrabFrameToPng()` (engine grab -> temp BMP -> GDI+ PNG).
  - Verified by synthetic keys: while paused
    `frame saved -> C:\Users\satee\Pictures\Unplugged\2026-10-28\frame_0001.png`
    (3840x2160, 6.5 MB); while playing the same chord wrote no file.
- 2026-10-28 NLS for a 16:9 screen: fill cost + band lock:
  - User request (relayed): a 185" 16:9 owner wants to fill with NLS via zoom /
    crop / stretch without hunting in the dark, scope-screen owners want the
    mirror case, and both want ONE aspect that does not switch mid-film.
  - Live panel now shows, while NLS is on: `FILL COST` (what filling THIS title
    needs, in % vertical stretch), `FILL LIMIT` (the user's budget) and `FILLING`
    (yes/no). Engine publishes it in the status JSON as
    `"nls":{"on":..,"need":..,"limit":..,"filling":..}`; `need` is computed in
    ApplyPostFx from the same activeAR/winAR the fill decision uses, so the number
    shown is the number the decision compares against — no separate estimate.
    A 2.39 film on a 16:9 screen reads ~36 %, on a scope screen ~1 %.
  - New `Lock band` row (`geo.nlsLock`): the first confident band is kept for the
    whole title, so a film that switches aspect (IMAX sequences) keeps ONE shape
    instead of re-latching after ~5 s. Off = previous behaviour.
  - Mirror case needs no new knob: content narrower than the window always fills
    horizontally (16:9 -> 21:9 is the classic ~34 %), and the fill limit does not
    apply to it.
- 2026-10-28 Fill limit now covers wide FRAMES, not only encoded bars:
  - Reported on a 3840x2160 display: Euphoria showed vertical stretch and objects
    twisted as the camera panned. Its media type is `3840x1740` — the picture is
    2.207:1, wider than the 1.78 window, so filling needs 24 % VERTICAL stretch.
  - The budget test only ran on the "title has encoded bars" path (`m_nlsBandValid`),
    so a wide-frame title with no bars was filled unconditionally and the warp
    spent 24 % of distortion across the picture.
  - The fill decision is now one test for both shapes, in `ResizeVideo`:
    `activeAR <= clientAR * fillLimit`, where `activeAR = frameAR / hA`
    (hA = 1 when there are no bars). Refusal keeps the picture at its own aspect;
    `m_nlsFillOk` carries the decision to `ApplyPostFx` (the warp is only injected
    when geometry actually filled) and to the INFO panel's `FILLING` row.
  - Verified: `fill refused: picture AR 2.207 needs 24% vertical stretch, limit
    5% — letterboxed`, `[GEOM] dest=(0,208) 3832x1736` (letterboxed), no NLS pass.
    Raising Fill limit past 125 % lets it fill for anyone who wants that trade.
- 2026-10-28 NLS gains the SQUEEZE (the mirror of the stretch):
  - User: "rather than throwing away, why can't we have a gradual squeeze
    horizontally?" — and they were right; my "crop or nothing" answer was wrong.
  - Geometry fills the window with the active band vertically and the full width
    horizontally, so ANY aspect mismatch is a HORIZONTAL scale of
    `ratioAR = winAR / activeAR`:
    * ratioAR > 1 (picture narrower, e.g. 16:9 on 21:9): the sides are magnified —
      the classic NLS stretch;
    * ratioAR < 1 (picture wider, e.g. Euphoria 2.207 on 16:9): the sides are drawn
      IN gradually, centre native, nothing cropped — the squeeze.
  - `Auto` axis is therefore always horizontal. Choosing vertical for the wide case
    was the bug behind "heads stretched and objects twisting" on a 3840x2160
    display: it warped the wrong axis.
  - Shader: `map_radius` now runs for ratio < 1 as well (the same monotone curve;
    the old `ratio <= 1.0001` early-out turned every squeeze into an identity).
    Deadband is |ratio-1| <= 0.02 in both directions.
  - `Fill limit` now budgets the correction EITHER WAY: fill only if
    `ratioAR <= limit` and `1/ratioAR <= limit`. Euphoria needs 24 %, so the
    default 105 % still refuses it (letterboxed); 130 % enables the squeeze.
  - Verified: 105 % -> `fill refused: picture AR 2.207 needs a 24% squeeze, limit
    5% — letterboxed`; 130 % -> `[GEOM] mode=2` + `horizontal … ratio=0.807`
    injected. INI left at 130 so the effect is visible on the next Euphoria load.
- 2026-10-28 Fill mode: Auto / Stretch / Crop / Off:
  - At 36 % the squeeze is visible on faces ("hard squeezing changing proportions
    of people"), so it must be a choice rather than the only behaviour.
  - `Fill mode` (`geo.nlsFillMode`), four outcomes decided in ResizeVideo:
    * Stretch - warp inside Fill limit, otherwise letterbox;
    * Crop - uniform scale until the picture covers the window, cut the overflow
      (zero distortion, spends picture);
    * Auto (default) - warp while the correction is inside Fill limit, CROP
      beyond it;
    * Off - never fill.
  - Crop geometry: `scale = max(clientW, clientH * frameAR / hA)`,
    dest = (scale, scale/frameAR), centred — the active band covers the height and
    whichever axis overflows is cut. No warp pass is injected on top
    (`m_nlsCropFill` gates ApplyPostFx).
  - Verified on Bone Temple (2.415 on 1.781, needs 36 %) with limit 120:
    `[NLS] crop to fill: picture AR 2.415 on 1.781 window -> 5197x2923 (no warp)`
    and `[GEOM] dest=(-682,-328) 5197x2923` — filled, nothing distorted.
    Same title at limit 140 with Fill mode Stretch/Auto still warps (ratio 0.737),
    which is the visible-squeeze case the user reported.
- 2026-10-29 Edge-reveal chrome + panels suppressed in the library:
  - Pointing at a screen edge wakes the pane that lives there: left = live status,
    right = settings, bottom = transport. Zones are ~2.5 % of the edge, centred on
    that edge's middle (left/right middle 70 % of height, bottom middle 80 % of
    width), and only an ENTRY fires, so travel across the picture never pops them.
  - Two bugs found by the user before I had verified anything: (1) `GoLibrary`
    set the suppression flag but `SetUi(true,false)` early-returns when up/full
    already match, so an already-visible rail survived; the panes are now hidden
    unconditionally there. (2) The reveal honoured ui.showInfo/ui.showSettings,
    which are OFF by default, so the gesture did nothing — the gesture now IS the
    request: the pane is shown regardless and is transient (retracts when the
    pointer leaves that edge, or after the 4 s idle), so nothing gets pinned.
  - Verified with real windows: `hot zone 1 -> reveal`, `pane visible=1`, then
    `hot zone 1 -> retract`; after stop, every `UnpluggedUiPane` child reports
    IsWindowVisible = false (only the overlay itself stays up).
- Open design note for T2: 1.3.0 has only the `watched`/`last_pos` schema fields, no history UI or resume code.
  This is a deliberate new feature; History reuses `items`, including `present=0` rows until the normal purge.- 2026-10-29 Chrome redesign: ONE visibility state (region), ONE transition, hide only from a reset timer.
  - The old design had four owners of "is the chrome up" - `m_uiUp`, each pane's
    `IsWindowVisible`, `ShowWindow` on the overlay, and its window REGION - driven by a
    300 ms poll that read `GetCursorPos` and compared a timestamp. They could disagree,
    and the reported symptom ("reacts to the mouse but nothing is clickable until I
    alt-tab", "auto-hides and immediately goes dead") is exactly a shown overlay with a
    live region and no chrome behind it: it ate every press.
  - Now: the overlay window is created once, shown once, and NEVER hidden. Chrome down =
    EMPTY window region (zero area paints nothing and hit-tests to nothing); chrome up =
    union of the visible panes. `Cover()` builds an empty region when there are no panes
    (a NULL region means the FULL window - the trap that started this), and the empty
    region is set at creation, before the first transition.
  - Reveal is driven by the input message: `CMainFrame::OnMouseMove` gets the point and
    calls `ChromeZoneCheck(p)`. `HostProc` converts the forwarded mouse message from
    host-client to frame-client before posting it up (the host sits at the EDGE_BLEED
    offset; a constant offset error is still an error, and the bleed scales with DPI).
    MPCVR drains WM_MOUSEMOVE (VideoRenderer.cpp:2837) so moves over the video arrive.
  - Hide is driven by ONE timer: `TID_CHROME`, armed by `SetUi(true)` and re-armed by
    `UiActivity()` (coalesced to 200 ms), never by a timestamp comparison. `OnChromeIdle`
    re-arms instead of returning when a card is up / the library owns the screen / a
    drag is in progress, so a transient condition delays the hide instead of cancelling
    it for good.
  - Verified (posted moves + Up key + real mouse, `native_ui_log.txt`):
    `frame mouse move (3420,720) chrome down` -> `hot zone 1->2` -> `ui: up` ->
    `overlay region: 3 pane(s) -> union`; leaving the edge -> `retract` ->
    `overlay region: 2 pane(s)`; exactly 4000 ms after the last activity ->
    `ui: down` -> `overlay region: 0 pane(s) -> EMPTY`; UP toggles up/down with the
    region following every time. Instruments added: `overlay region: N pane(s)` on
    change, `frame mouse move ... chrome down` (throttled 1 s) for the reveal path.
- 2026-10-29 SUPERSEDES the entry above: pointer state is SAMPLED, not inferred from messages.
  - What broke: the message-driven reveal left the app dead after auto-hide in VP mode - the
    pointer sat on the renderer's DirectX child, so "the pointer moved" was never observed by
    the window that mattered, the edge gesture never fired, and `CursorHide()` (a per-thread
    ShowCursor count) was never balanced back. The pointer was invisible over the video
    ("no mouse, had to kill it from the taskbar") while the film kept playing.
  - The model: ONE sample of `GetCursorPos` every 100 ms (`TID_POINTER`, `PointerSample`).
    It is the only place that decides (a) the pointer moved, (b) the edge gesture,
    (c) cursor visibility. Messages (`OnMouseMove`, pane hovers via `UiActivity`) are an
    accelerator only: they show the cursor and reset the idle clock on the message itself;
    they set no state. A sample cannot be lost or swallowed, so a missed message costs one
    tick (100 ms) instead of desynchronising the app.
  - Cursor is DERIVED and re-asserted on every sample: hidden only while something plays,
    no card is up, and neither pointer nor keyboard has been used for 2.5 s. Being re-asserted
    is the point - a hidden cursor can no longer get stuck for want of a message.
  - `PointIsOurs(p)` (WindowFromPoint + pid) gates the sample, so a browser covering a
    backgrounded player cannot pop our chrome; geometry alone cannot tell those apart.
  - Chrome visibility still has exactly one writer (`SetUi`), one state (the overlay REGION -
    empty = not there), and one hider (the idle timer). No ShowWindow of the overlay anywhere.
  - Single-instance guard: named mutex `Unplugged.Desktop.2.Single`; a second launch activates
    the running window and exits (two copies = one black capture from a stolen DeckLink input
    plus two stacked topmost overlays).
  - Verified with the real cursor (`SetCursorPos` round trip), one instance:
    `second instance -> activated existing window ... exiting` (2nd process exited, 1 running);
    `cursor hidden` at 2.5 s idle -> move to the right edge -> `cursor shown` + `hot zone 0->2`
    + `ui: up` + `overlay region: 3 pane(s)` within the same 100 ms tick; leaving the edge ->
    `retract` -> `2 pane(s)`; 4 s idle -> `ui: down` -> `EMPTY (chrome down)`;
    then move to the LEFT edge while the cursor was still hidden -> `cursor shown` + `hot zone 0->1`
    + reveal. That last step is the exact case that used to leave the pointer invisible.
- 2026-10-29 ROOT CAUSE of "the chrome becomes uninteractive": the chrome click was activating the OVERLAY.
  - Instrument: `CMainFrame::PreTranslateMessage` logs every left press with the target window, the
    class of the window under the cursor at that pixel, whether it is ours, and the foreground/frame
    handles. One reproduction, one line, no guessing.
  - Measured before the fix (presses DID reach the panes; activation was the failure):
      activate state=0                                  <- frame loses activation on the click
      [press] down target=UnpluggedUiPane underIsOurs=1 fg=0x110A50 frame=0x2C086A
      [Mouse] pane click while inactive -> activating the frame
      activate state=1 / activate state=0               <- undone 3 ms later
    `CUiWnd::OnMouseActivateMsg` activated the frame by hand and then returned MA_ACTIVATE - which tells
    Windows to activate the click's top-level window, and a pane's top-level is the OVERLAY. So every
    chrome click handed activation to the overlay and took it away from the frame:
      * the keyboard was addressed to a window with no key handler -> Up/Esc/F2/F3/Space dead;
      * the frame went WA_INACTIVE -> our own OnActivate rule dropped it out of topmost.
    Both read as "the chrome is there but nothing I do works".
  - Fix: `OnMouseActivateMsg` returns MA_NOACTIVATE (deliver the press, do not activate) and activates
    the FRAME explicitly; the overlay additionally hands activation straight back to the frame if
    anything ever activates it. The app now has exactly ONE activatable window.
  - Verified with real SendInput clicks on the chrome after a rebuild:
      [press] down target=UnpluggedUiPane underIsOurs=1 fg=0x240934 frame=0x240934     (fg == frame)
      [press] up   ... fg=0x240934 frame=0x240934
      [press] down ... fg=0x240934 frame=0x240934   (second click, still the frame)
    and NO `activate state=0` after either click. Before the fix the same clicks logged
    `fg=<overlay>` plus an immediate `state=0`.

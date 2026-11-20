# User reports — bugs and feature requests

Started 2026-11-18 for the 2.3.0 cycle.

One row per report, with the evidence that diagnosed it and what happened to it.

A report is only "fixed" when the root cause is proven and the build carries the
fix; "shipped" additionally means it is in a released installer.

## How a report arrives

Users send a diagnostics bundle from the app (**Help → Diagnostics**, or the problem-report mail link). The zip contains:

- `environment.txt` — app version, GPU, displays, binary versions, health- `s3_shell.ini` — the engine settings (library roots are in the index, not here)
- `presets/*.ini`
- `logs/native_ui_log.peruser.txt` — the app log (library, availability, art)
- `logs/engine.log` — engine operations (graph open/teardown, settings pushes)
- `logs/s3engine.log` — the engine's own log (DirectShow graph detail)Read order for a playback/library report: `environment.txt` (which build), then `native_ui_log` for `library` / `play refused` / `S3 open` lines, then`engine.log` for the graph result, then `s3engine.log` for the HRESULT.

## Tracker

Reports UR-0008 onward (projector/10-bit, ClipGuard 2.60/2.62, update card) are
indexed in [AUDIT-2.3.0-COMPLETE.md](AUDIT-2.3.0-COMPLETE.md); the rows below are
the original UR-0001–0007 evidence.

| ID | Date | Version | Symptom | Status |
| --- | --- | --- | --- | --- |
| UR-0001 | 2026-11-15 | 2.2.0 | Network library: every title shows UNAVAILABLE | **Fixed** (2.3.0 tree) |
| UR-0002 | 2026-11-15 | 2.2.0 | Open on the same share fails `0x80040217` | **Open** — needs reproduction on 2.3.0 |
| UR-0003 | 2026-11-18 | ? | Static nits steps by 5; asks to merge the two nits rows | **Open** — discussed, no decision |
| UR-0004 | 2026-11-18 | 2.2.0 | 4K output scaled 3840x2160 → 3831x2152 in every fit mode | **Fixed + field-verified** |
| UR-0005 | 2026-11-18 | ? | Internal subtitles (English and non-English) do not show; MPC-HC also fails | **Fixed** (2.3.0 tree) — stack rebuilt on MPC-HC's engine; text subtitles draw, user-verified. PGS/VobSub and scope-bar placement still to spot-check; see [SUBTITLE-AUDIT.md](SUBTITLE-AUDIT.md) |
| UR-0006 | 2026-11-18 | 2.3.0 dev | After wiping Unplugged settings, Video Processor does not work — "default config not found"; acquire reports no signal | **Fixed** (built, retest pending) — `StartVp` resolves the first/locked port when no input is saved |
| UR-0007 | 2026-11-18 | 2.2.0 | NLS is global: a scope tuning over-zooms 2.00:1 films, IMAX/16:9 sections and native 16:9; Lock band does not help | **Implemented** (2.3.0 tree) — aspect-aware NLS; scope and small-bars verified, Native needs 16:9/IMAX field content |

## UR-0001 — network library marks every title UNAVAILABLE

**Reporter.** User with ~981 titles on `\\Htpc\d` (Movies + Recorded TV), RTX3050, Windows 11. Bundle: `Unplugged-diagnostics-20261115-153433`.

**Symptom.** "Not able to use media player — the videos come up as unavailable."The library scans correctly, then every poster carries the UNAVAILABLE band and Play is refused with "Storage unavailable: reconnect `\\Htpc\d`".

**Evidence**

- `
library scan done in 36578ms: 921 new, 0 updated, 0 missing` — the scan reads  the share without error, so the files are there and reachable.

- Immediately after the scan, 921 × `
library: '<path>' is now UNAVAILABLE`.

- The shallow 5 s refresh also reports `unavailable=918` — i.e. it is the  **volume-root** probe failing, not the per-file stat.

- No `is now available` line ever appears; the state never recovers.

**Root cause.** `Mpc Library:: Path Root()` returned drive roots with theirtrailing separator (`C:\`) but UNC roots without one (`\\Htpc\d`). Windowsreports `Get Drive Type W("\\\\server\\share")` as `DRIVE_NO_ROOT_DIR` (1) even ona reachable share; with the separator (`\\server\share\`) it reports`DRIVE_REMOTE` (4). `Root Reachable()` requires `!= DRIVE_NO_ROOT_DIR`, so every UNC-rooted title failed. Reproduced on the dev machine:
```
\\localhost\C$    drive Type=1   -> unavailable
\\localhost\C$\   drive Type=4   -> available
```
Local drives were unaffected because `Path Root` already appended their slash, which is why the bug only reaches users whose library lives on a share.

**Fix.** `tools/native_ui/native_ui.cpp` — `Path Root()` now keeps the separatorafter the share name (and adds one for a bare share). A nonexistent share stillreports unreachable, so the badge and the Play refusal keep working for genuinelymissing storage.

**Verification**- Old vs new logic against real UNC paths: `\\localhost\C$\...` → drive Type 4,  reachable; `\\localhost\No Such Share\...` → unreachable (correct).

- Native UI Release x64 builds clean.

- Still to do on a machine with a share: confirm posters lose the band, Play  opens, and pulling the share marks it unavailable again within 5 s.

## UR-0002 — open on the same share fails `0x80040217`

**Reporter.** Same user and bundle as UR-0001. An earlier October diagnostic(`unplugged-diagnostics.txt`) from the same machine shows the same failure, sothis is not new to 2.2.

0.

**Symptom.** `s3engine.log` session 07:37:55:
```
[GRAPH] Build Graph enter — generation now 1Build Graph b Deck Link=0 source='\\htpc\d\Recorded TV\Frasier\…mkv'… renderer added hr=0x00000000[GRAPH] Open: Build Graph FAILED hr=0x80040217        (VFW_E_CANNOT_CONNECT)
```
**Why this is separate from UR-0001.** UR-0001 refuses Play before the engine iscalled. This session *did* call the engine, so the two are different paths. The73 ms gap between `renderer added` and the failure is the signature documentedfor the codec-pack graph bug in[ISSUE-mpcaudiorenderer-silence.md](ISSUE-mpcaudiorenderer-silence.md) §7: K-Lite maps `HKCR\Media Type\Extensions\.mkv` to LAV Splitter Source, so`Add Source Filter` hands back a demuxer and the next `Connect Direct` fails with`VFW_E_CANNOT_CONNECT`. That machine has K-Lite and MPC-BE per the Octoberdiagnostic.**Why it is not closed as "the share was asleep".** A dead UNC path should fail`File Source (Async) Load` with `0x80070035`, and the log would say so. Here theload line is not printed at all, and the failure lands after the renderer isadded.**Open question.** The 1.1.1 fix pins `CLSID_Async Reader` for any path without`://`, which includes UNC, and logs `
[GRAPH] File Source (Async) Load hr=…`.
Neither that line nor `[FILTER] video renderer module=…` appears in thissession, so the shipped 2.2.0 engine may predate that instrumentation. Do notchange graph code until the 2.3.0 engine is observed on a codec-pack machine: confirm the Async Reader line appears, and whether the open succeeds.**Reproduction needed.** 2.3.0 build, K-Lite installed, library on a UNC share, play a title with the share up. Capture `s3engine.log`. If the Async Reader lineis present and the connect still fails, the pinned-source path itself needswork; if the line is absent, the engine build/layout is suspect.

## UR-0003 — Static nits step and the two nits rows

**Report.** "The Static Nits slider under HDR → Display Target only allowsadjustments in increments of 5 rather than 1. Could this setting be combinedwith the max nits slider under the Tone Mapping menu?"**What the rows are**| Row | Key | Range / step | What reads it |
| --- | --- | --- | --- |
| SDR display nits (Tone Mapping) | `hdr.sdr Nits` | 25…400, step 1 | the PQ→SDR converter (`Luminance Scale = 10000/sdr Nits`, and the final divide). This is the SDR-output white. |
| Static nits (max) (Display Target) | `hdr.max Nits` → `disp Nits` → `i Hdr Display Max Nits` | 10…1000, step 5 | **HDR output only**: DV L2 target selection and `Set HDR10Shader Params`. Not read by the SDR converter. |
| Title peak (nits) (Curve Settings) | `hdr.title Peak` | 100…4000, step 1 | the content peak the curve squeezes from. |**Findings**- Step 5 is real (`slider step 'Static nits (max)' -> 125/130/…` in the  2026-11-10 log), and the guide already promises "1 nit per click". The 1.3.0  Python UI offered 200…10000; the native rail narrowed it to 10…1000.

- In SDR output (Convert to SDR = On — this user's case) `max Nits` is inert.  The guide's claim that it is "the destination the tone curve maps to" is  wrong for that path; it applies to HDR output.

- Merging the two rows is not safe: one is display **white** (SDR), the other  display **peak** (HDR). On an SDR projector they collapse to the same  physical number, which is why the request sounds reasonable.**Options (undecided)**1. Hide or grey `Static nits (max)` while Convert to SDR is On, with "HDR   output only" help.

2. Keep it, relabel to `Display peak (HDR output)`, and correct the guide.

3. Either way: step 5 → 1, and widen the range (the engine accepts 10000).

4. Optional convenience: a "match SDR white" action when converting to SDR.

## UR-0004 — 4K output scaled down in every fit mode

**Report.** Detailed stats show 3840x2160 → 3831x2152. Fit Mode Fixed aspect1.78 on a 16:9 screen; Source and Fill also downscale, at slightly differentsizes; 3840x2160 is never reached.**Confirmed from the 2.2.0 status panel (VP mode, DV source)**`DISPLAY 3834 × 2154 · 1.78:1`. That row is the renderer host's client rect(`display.w/h` = `Get Client Rect(render Target_)`, MpcPlayer.cpp:4591-4595), sothe picture canvas itself is 6 px smaller than the desktop in each dimension.
The 2.2.0 cause is in `Work R()`:
```
// v2.2.0CRect Work R(){ CRect rc; Get Client Rect(rc);               rc.
Deflate Rect(Px(EDGE_BLEED), Px(EDGE_BLEED)); return rc; }
```
The frame bleeds only to hide DWM's ring, but the work rect deflates the clientby the same amount again. At 150% DPI `Px(2) = 3`, so a 3840x2160 desktopbecomes a 3834x2154 canvas, and every fit mode scales into it: Fixed 1.78 → 3834x2154; Source → 3829x2154; Fill → 3834x2154. That is the"never 3840x2160, slightly different per mode" the user reported.**The 2.3.0 tree changes this** — and overshoots. `Work R()` now returns theclient without deflating, and `Layout()` resizes the host to that rect([native_ui.cpp:9763](tools/native_ui/native_ui.cpp#L9763),[9836](tools/native_ui/native_ui.cpp#L9836)). The 2.3.0 build reports**DISPLAY 3842 × 2162** in Media Player: the host is now the *window client*, which is the monitor plus the EDGE_BLEED overhang minus the window'snon-client border — a net **+2 px**. The error changed sign: a 6 px downscalebecame a 2 px overscan (the picture is scaled up and the outer ~1 px iscropped).**Correct definition.** The canvas is the **monitor**, not the client. `Work R()`returns the monitor rect (`MONITORINFO.rc Monitor`) mapped into the client, centred; the host is created at that rect so the first `Layout` does not resizea live swap chain. Expected result: DISPLAY = 3840 × 2160, Source mode = 1:1, Fixed 1.78 = 3840 × 2157 (still by definition).

**Fix applied 2026-11-18** (`tools/native_ui/native_ui.cpp`): `Work R()` maps themonitor rect into the client; `Create2` creates `g_host` on that rect. A newstartup line makes it checkable from a bundle:
```
work rect: client 3842x2162 -> monitor 3840x2160 (3840x2160 at 1,1)
```
Native UI Release x64 builds clean. Verified 2026-11-18 on the dev machine andconfirmed by the reporter on the projector:

- `work rect: client 3842x2162 -> monitor 3840x2160`, wallpaper canvas  3840x2160, full-screen video rect 3840x2160;- status panel reads **DISPLAY 3840 × 2160**;- **Fit mode Source is 1:1** (no scaling in the renderer stats).
Closed. The guide's Fixed aspect row now says 1.78 is not exactly 16:9 and that Source is the 1:1 mode.**One part is still expected**- Fixed aspect 1.78 is not 16:9 (1.777…). Even on a perfect 3840x2160 canvas  the destination is 3840x2157. The row's 0.01 step cannot express 1.7778.

- To get exact 1:1 the user must use **Fit mode = Source**. If Fixed Aspect  should be able to express 16:9 exactly, that needs a finer step or a 16:9  preset — a separate, small decision.

## UR-0005 — internal subtitles do not show

**Report.** "Non-english or english internal subs can't get them to show up.
Tried also mpc-hc with same outcome." No file or diagnostics supplied yet.**Audit.** Full support matrix in [SUBTITLE-AUDIT.md](SUBTITLE-AUDIT.md). Textsubtitles (SRT, ASS/SSA, Web VTT, MOV_TEXT) are accepted and decoded in additionto PGS/VobSub/DVB, so "text is unsupported" is not the explanation. The MPC-HC-same-outcome detail points at a format LAV never exposes — most likely**TTML/IMSC** or **Blu-ray TEXTST**, both absent from LAV's`subtitle_format_map`; the stream then appears in neither player.**Needed**1. `ffprobe -v error -select_streams s -show_entries   stream=index, codec_name, codec_tag_string: stream_tags=language, title, forced   -of json "<file>"`.

2. The diagnostics bundle. Check `[SUBS] pin N offered:` (none = format not   exposed), `subpic provider attached/cleared`, and the `[SUBS] probe` line.**Field test 2026-11-18 (installed 2.3.0, 28 Years Later, Bulgarian).** The textpipeline is reaching the queue:
```
[SUBS] pin 0 offered: UTF8 cb Format=520 dw Offset=520 lang=bul[GRAPH] pending subtitle track 4 applied at connect hr=0x00000000[SUBS] subpic provider attached (subs On=1 cur Sub=4 subs=1)
[live] subq: depth=1 rt Now=2150.69 cached=[2154.28..2155.49] last Hr=0x80004005 hit=0[SUBS] probe: rt=2152.48s -> event 2154.28s..2155.49s (next, not at rt)
[live] subs: render11=363 drew=0 ... (sample after the event, at 2157.49)
```
So: correct decoder, correct language, event parsed and cached — but the 5 s`
[live]` sampler straddled the 1.2 s cue (`rt=2152.48` before it,`rt=2157.49` after it), and `drew` never incremented. `hit=0` at both samples isexpected outside the event, so this is **not yet proof** of a blit failure; itis also not proof that the cue was drawn. The Bulgarian track is sparse there(one cue at 2154.28 in that stretch).**Second field test (14:23, installed 2.3.0, "picked English").** The engine logshows **no track selection at all**: `cur Sub=-1`, provider cleared, and the UIlog has no `subtrack` command after 14:17. The rail was lying: `Parse Tracks`initialised `active = 0`, which is indistinguishable from "track 0 is active", so with the engine at `current:-1` (Off) the Subtitles row displayed**English [eng]** as selected. The user saw English and assumed subtitles wereon; the engine was Off the whole time.

**Fix applied 2026-11-18** (`tools/native_ui/native_ui.cpp`): `Parse Tracks`starts at `active = -1`; the subtitle row maps `-1` to **Off** (index 0) and areal track to `act+1`, and re-syncs when the engine's selection changes withoutthe names changing. Audio keeps its name-change gate (its engine JSON lags are-open). Native UI rebuilt.**Still open: the draw leg.** No test has yet run with a track actually enabledthrough a dense cue. Next test: after the row shows **Off**, select**English (SDH)** (stream 4, cues every 1–3 s from 246 s), seek to 04:10(250 s), play 15 s, then read `%USERPROFILE%\.unplugged\logs\engine.log`:

- `drew` climbs → text rendering works; the Bulgarian result was a missed cue.

- `hit=1`, `geo Hr=0`, `last Hr=E_FAIL` → the DX11 Alpha Blt itself  (`CDX11Sub Pic:: Alpha Blt` → `CDX11Sub Pic Allocator:: Render`).

- `hit=0` with `depth>0` → queue lookup/time base.**Resolution 2026-11-18 — stack replaced.** The fork's MPC-BE-era subtitlestack carried a libass path that produced 10×10 subpictures; patching it wasabandoned. `src/Subtitles` was replaced wholesale with MPC-HC's reference stackfrom `C:\code\mpc-hc-develop` (internal RTS rasterizer, no libass), with threesmall shims (`ISO639XTo Language` arity, `KINARGTYPE`, `<cmath>`/`<functional>`).
The draw leg was fixed in the presenter: `Render Ex3` now sets the viewport andcropped video rect, `Set Sub Pic Provider` falls back to the full canvas when thevideo rect is still empty. Subtitle size is configurable (default 65 %) andscope content pins the text into the bottom black bar. User confirmed textsubtitles draw. The old stack is kept locally at `src/Subtitles.fork-backup/`(reference only; not committed). Remaining checks: a PGS and a VobSub title, forced tracks, and bar placement on scope content — see[HANDOVER-2.3.0.md](HANDOVER-2.3.0.md) §8.

## UR-0006 — Video Processor broken after wiping settings

**Report.** "When we wiped our Unplugged settings we are at a position, videoprocessor is not working as default config is not found."**Evidence (dev log, 17:10).**
```
config mode='media_player' ... input=''vp: s3_start_device('') rc=0x00000000acquire: FAILED - no signal after retries
```
`app_config.json` had been reseeded with `"active_input_url": ""`. The ABIdefines `s3_start_device("")` as **capture off**, so `StartVp` started nocapture and the acquire card spent its 10 attempts reporting "no signal" for aconfiguration that was never made. The SOURCE list had four ports; none wasselected.
Note that wiping `%LOCALAPPDATA%\Unplugged` and `%USERPROFILE%\.unplugged`does not reset first-run: `Seen Setup` is a value under`HKCU\Software\Unplugged`, so the wizard is skipped. The fix does not depend onfirst-run; it resolves the port when VP starts.

**Fix.** `StartVp` (native_ui.cpp, ~9865) now, when `m_input Url` is empty, polls the card and picks the first **locked** port, else the first port — thesame rule as `CSetup Card:: Scan()` — then persists it with`Write Active Input`, refreshes the SOURCE rows and starts capture. With noports it logs `
vp: no saved input and no Deck Link ports found`.

**Verification.** Native UI Release rebuilt. Retest: wipe the two directories, launch, switch to Video Processor; expect`
vp: no saved input -> default '<url>' (ports=N)`, a picture, and`active_input_url` persisted in `app_config.json`.

## Other findings from the 15 Nov bundle (not new bugs)
- **Update card on 2.2.0.** The log shows `remote 2.2.0 local 2.1.0 newer=1`:  the 2.2.0 build shipped `k App Version` stale at 2.1.0, so 2.2.0 users are  offered an update to the version they already run. Already corrected in the  2.3.0 tree (`k App Version = L"2.3.0"`); nothing to do but verify in the build.

- **Stale `segfault.log`.** The bundle carries a Python-era heap-corruption  trace (`0xc0000374`, `mpvprocessor/ui/main_window.py`). The native app does  not run Python; this is a leftover file in `%LOCALAPPDATA%\Unplugged`. It  should not be read as evidence about the current build.

## UR-0007 — NLS is global (aspect-aware NLS request)

**Reporter.** Power user on a scope screen (2.2.0), previously running VideoProcessor + madVR with aspect-dependent zoom profiles.

**Symptom (four cases, one cause).**

1. A scope tuning works, but a 2.00:1 film inherits it and the Post-NLS crop over-zooms the picture.
2. An IMAX (16:9) section inside a scope film inherits the scope crop and is over-zoomed; it needs no zoom at all.
3. Native 16:9 is stretched unless NLS is turned off.
4. `Lock band` did not help with 2 and 3.

**Finding: no detection bug.** The engine tracks the live band and re-latches on a scope<->IMAX format cut (`MpcPlayer.cpp:4220-4238`); `NlsBarHeight()` is already a no-op when there are no bars (`1128-1133`). What is missing is policy: `geo.nlsBars`/`nlsCropX`/`nlsCropY` are single values applied to every title, and the Post-NLS crop is applied unconditionally even when the aspect already matches (`3709-3728`). `Lock band` freezes the band on purpose (`4228-4230`), so it cannot help mixed-aspect content.

**Requested / specified.** Aspect-aware NLS: three windows (Native <=1.90, Small bars 1.90-2.15, Scope >=2.15) with per-window Bars removed and Post-NLS X/Y crops; live classification with a 0.05 deadband and a 3-poll confirmation; when the rule is On, `Lock band` is ignored and greyed. Spec in [HANDOVER-2.3.0.md](HANDOVER-2.3.0.md) section 3.11.

**Status.** **Implemented** in the 2.3.0 tree (2026-11-18). Verified in the log: `nlsaspect: 2.462 -> scope (bars=100 crop=0/0)`, the small-bars window by moving the bound to 2.60, and release on close. Native (<=1.90) awaits a 16:9/IMAX source; see HANDOVER §3.11.

## Feature requests

_None logged yet._

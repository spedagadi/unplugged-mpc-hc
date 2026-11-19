# 2.3.0 — user-feedback audit (2026-11-19)

Source: `C:\htpc\bugs_19_11_2026.txt` (forum reports gathered 19 Nov). This
audits each report against the **2.3.0 working tree** (`zion-s3-shell`, HEAD
`7b18fe3f5` + uncommitted work). "In tree" means built and verified unless the
row says otherwise; it does not mean packaged.

## Summary

| Reporter | Item | Status |
| --- | --- | --- |
| sammy1001 | NLS: scope tuning over-zooms 2.00 films / IMAX / native 16:9; lock band no help | **Fixed in tree** — aspect-aware NLS (UR-0007, HANDOVER §3.11). Field test on IMAX cuts pending |
| sammy1001 | Projector pseudo-FFTB: faint glowing rectangle outline in fully dark scenes | **Fixed (pre-2.3.0, carried through)** — DWM light ring removed; ask reporter to retest on 2.3.0 |
| VHT | Subtitles (internal or external) in MKV show nothing | **Internal fixed + user-verified** (UR-0005). **External: not supported** — feature gap |
| va_lemon | Publish metrics (aspect, refresh, colour space) via webhook / Home Assistant | **Open — feature** |
| va_lemon | Keyboard-only slider adjustment (fine steps without a mouse) | **Fixed in tree** — Tab focus, arrows step, Enter/double-click exact entry |
| va_lemon | Static Nits steps by 5; merge with the max-nits row | **Fixed in tree** — step is 1; only one max-nits row exists, nothing to merge |
| va_lemon | Output downscaled 3840x2160 → 3831x2152 | **Fixed + field-verified** (UR-0004) |
| va_lemon | No frame-rate matching (everything at 60 Hz) | **Fixed in tree** — §3.5 + VP leg. Projector test pending |
| legeirk | 921 NAS titles all UNAVAILABLE | **Fixed + field-verified** (UR-0001) |
| ramiroalvaro.ra | Automatic per-aspect bar removal/zoom (16:9 none, 2.00 100 %, scope 50 %) | **Fixed in tree** — same aspect rule (UR-0007) |

## Details

### sammy1001 — NLS (fixed, field test pending)
The three cases are exactly the aspect rule:
Native ≤ 1.90 (NLS bypass), Small bars 1.90–2.15 (100 %, crops 0), Scope ≥ 2.15
(the user's own tuning, e.g. 50 % + crop). Verified in the dev logs:
`nlsaspect: 2.415 -> scope`, `1.846 -> native`, `2.462 -> small-bars` (threshold
moved), `released - user values restored`. **Remaining:** a real IMAX cut
(Dune / Catching Fire) and the ultrawide note from the user — see
[NLS-ASPECT-TEST-PLAN.md](NLS-ASPECT-TEST-PLAN.md).

### sammy1001 — FFTB rectangle (fixed; retest on 2.3.0)
The "faint glowing rectangle outline" is the **1-2px light ring and rounded
corners Windows 11's DWM paints around a borderless fullscreen window**. With
the projector's laser faded out it is the only light in the room, so it reads as
a glow. Fixed in the native UI (documented in
[HANDOVER-1.3.1-native-ui.md](../tools/native_ui/HANDOVER-1.3.1-native-ui.md)):
`DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_DONOTROUND` (33) and
`DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE` (34) in `OnCreate`, logged as
`corner hr=… border hr=…`. The 2.3.0 monitor-rect canvas (UR-0004) additionally
removed the `EDGE_BLEED` deflate that could leave a wallpaper margin at the
frame edge.

**Action:** ask the reporter to retest on the 2.3.0 installer. If a ring is still
visible, it is downstream of the app (projector processing or the source's own
black level) and needs a capture from his screen.

### VHT — subtitles (internal fixed; external missing)
The internal stack was rebuilt on MPC-HC's engine and text subtitles are
user-verified (UR-0005); PGS/VobSub/DVB and scope-bar placement still need the
spot-check in §8. **External subtitle files are not supported at all** —
`SubtitlePlayerGlobals.cpp` documents that the engine has no external-subtitle
path, and the UI has no "load subtitle file" action. This half of the report is
a feature gap, not a regression.

### va_lemon — webhook (open)
Not implemented. The data now exists internally (`nls.picAspect`, display
refresh, colour space/mode), so a small HTTP publisher that POSTs a JSON
snapshot on change is feasible; ties into Home Assistant/masking/lens memory.
No API/format has been agreed.

### va_lemon — keyboard sliders (fixed)
Keyboard access was impossible before: the frame only offered keys to the rail
once it was already in keyboard mode, which a keyboard-only user could never
enter. Now:
- **Tab / Shift+Tab** move the focus ring and arm keyboard mode;
- **Left/Right step the focused slider** by one `step` (0.001 rows included);
  on toggles/options they still walk the focus;
- **Enter on a focused slider, or a double-click**, opens the shared
  **numeric entry card** — type an exact value, Enter commits (clamped to the
  row's range and rounded to its step), Esc cancels. The value uses the same
  `PushRow` path as the wheel, so INI, preset-dirty and engine push agree.

### va_lemon — Static Nits (fixed)
`hdr.maxNits` step changed 5 → **1**. There is only one max-nits row in 2.3.0,
so the "merge with the Tone Mapping max" half of UR-0003 has nothing to merge.

### va_lemon — 4K scaling (fixed)
UR-0004: the work rect is the monitor rect; Source mode is 1:1 at 3840×2160.
Field-verified by the reporter.

### va_lemon — refresh matching (fixed, field test pending)
§3.5 (file path) and the VP leg (§3.5 extension, 2026-11-18). The dev display
has no 23–30 Hz modes; the projector test is the outstanding item.

### legeirk — NAS unavailable (fixed)
UR-0001: `PathRoot()` keeps the separator after a UNC share so
`GetDriveTypeW` returns `DRIVE_REMOTE`. User-verified.

### ramiroalvaro.ra — per-aspect zoom (fixed)
Same feature as sammy1001. His exact profile is expressible: Native (none),
Small bars 100 % with crops 0, Scope 50 % from his own tuning. Field test
pending.

## Recommendation for the 2.3.0 release

Ship as fixed/verified: aspect rule (field test), subtitles internal, 4K canvas,
refresh matching, NAS fix, wiped-profile VP (UR-0006).

Do **not** claim in the release notes: external subtitles, webhook, keyboard
sliders, static-nits change. Keep the FFTB rectangle as a known open issue
(USER-REPORTS) and ask the reporter for a picture/log bundle.
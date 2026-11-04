# NLS Axis test plan — Horizontal vs Split (2.0.1 candidate)

Purpose: decide, by eye on the real display, whether Split is shippable and what
it does to faces. Nothing here uses the proof harness; every case is run in
Unplugged with the rail visible (the video canvas now matches full screen, so the
effect can be judged without waiting for the chrome to hide).

## Materials

| ID | What | Path | Notes |
| --- | --- | --- | --- |
| M22 | Synthetic axis probe, 2.39:1 | `tools\nls_test_material\nls_split_probe.mp4` | 1920x804. Perfect centre circle r=160, 120 px grid, face-proportion box, rulers. Static 5 s — pause anywhere. |
| M01 | Real face material | `Our Living World S01E01` or Amaran (record the exact title and timestamp) | Pause on a shot with (a) a face/body near centre and (b) a face near the side edge. Record the timestamp. |

The probe is for geometry. The real title is for the eye: the probe cannot tell
you whether a face looks wrong.

## Baseline settings (identical in every case)

| Row | Value |
| --- | --- |
| Enable NLS | On |
| Screen | Auto |
| Bars removed | 100 |
| Strength | 100 |
| Centre protection | 45 |
| Curve | 1.2 |
| Split | 50 (except the Split cases below) |
| Max distortion | 140 |
| Post NLS X-Crop | 0 |
| Post NLS Y-Crop | 0 |
| Fill mode | Auto |
| Lock band | Off |

Only **Axis** (and Split, when Axis = Split) changes between cases.

## Cases — 16:9 screen (3840x2160), M22 (2.39 source)

The correction is k = 1.778 / 2.388 = 0.745. Record the INFO panel's
**WARP H / V** values; they are the quickest proof the case applied.

| Test ID | Axis | Split | Expected WARP H / V | What to look at |
| --- | --- | --- | --- | --- |
| SPLIT-16-H | Horizontal | — | −26 % / 0 % | Reference. Height untouched. Circle at centre becomes an ellipse of aspect ≈0.745; grid spacing compressed horizontally, most at the rim. |
| SPLIT-16-S25 | Split | 25 | −7 % / +25 % | Centre is a uniformly larger copy of the H case (same aspect), rim is stretched vertically. |
| SPLIT-16-S50 | Split | 50 | −14 % / +16 % | Centre same aspect, larger; correction shared. |
| SPLIT-16-S75 | Split | 75 | −20 % / +8 % | Close to Horizontal. |
| SPLIT-16-V | Vertical | — | 0 % / +34 % | Reference only; this is the case the field tester called "too wrong". |

The centre circle's **aspect should be the same in all five** (≈0.745). The
difference is its absolute size and where the distortion lives (centre vs rim).
That is the thing to verify visually: a face in the middle should keep its
proportions in every case; faces near the rim will differ.

## Cases — 16:9 screen, M01 (real face)

| Test ID | Axis | Split | Expected WARP H / V |
| --- | --- | --- | --- |
| SPLIT-FACE-H | Horizontal | — | −26 % / 0 % |
| SPLIT-FACE-S50 | Split | 50 | −14 % / +16 % |

Pause on a face/body shot. Compare SPLIT-FACE-H vs SPLIT-FACE-S50 for head
height/width, shoulder width, leg length, and the face at the frame edge. Play
10 s of motion in each.

## Cases — Scope screen, 16:9 source (M01)

k = 2.39 / 1.778 = 1.343. The same distribution applies in the other direction.

| Test ID | Axis | Split | Expected WARP H / V |
| --- | --- | --- | --- |
| SPLIT-SCOPE-H | Horizontal | — | +34 % / 0 % |
| SPLIT-SCOPE-S50 | Split | 50 | +16 % / −14 % |

These are the polar-opposite case: a scope user filling 16:9 content. Record
whether the rim distortion is acceptable and whether faces elongate.

## Procedure (one case)

1. Open the material. Pause on the chosen frame.
2. Set the baseline rows, then Axis (and Split if needed).
3. Keep the rail up. The video area is now the geometry canvas, so the effect is
   visible without hiding chrome.
4. Read the INFO panel: write `WARP H / V`, `GEOM CROP`, `POST-NLS X-CROP` and
   `POST-NLS Y-CROP` into the Run row.
5. Capture evidence: use the app's save-frame action or Win+Shift+S of the video
   area. Name it `<TestID>_<short-note>.png`.
6. For the face cases, play 10 s of motion and note any pumping or rim crawl.
7. Record Status (Pass / Fail / N/A) and the observation in the workbook.

## Acceptance questions

- Does any case show heads or legs changing length relative to Horizontal?
- Is the centre's circle aspect within ±1 % of Horizontal in the Split cases?
- Does the rim distortion in Split read as less objectionable than the full
  squeeze in Horizontal at the same Bars removed?
- Is there any visible change while the rail is up vs after it hides? (There
  should be none; the canvas is the visible video area.)
- On a face: is Split 50 acceptable, or does the vertical component make it
  look taller to the eye even when the measured aspect is unchanged?

## Result table

Fill these in the workbook (`Test Matrix` sheet, new rows appended) and add one
row per run to `Runs`. Do not delete failures; the decision to ship Split
depends on the evidence:

| Test ID | Status | WARP H/V | Observation | Evidence |
| --- | --- | --- | --- | --- |
| SPLIT-16-H | | | | |
| SPLIT-16-S25 | | | | |
| SPLIT-16-S50 | | | | |
| SPLIT-16-S75 | | | | |
| SPLIT-16-V | | | | |
| SPLIT-FACE-H | | | | |
| SPLIT-FACE-S50 | | | | |
| SPLIT-SCOPE-H | | | | |
| SPLIT-SCOPE-S50 | | | | |
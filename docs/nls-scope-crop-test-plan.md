# Scope-screen crop test — House of the Dragon (2:1 → 2.39)

Field report: on a 21:9/scope screen, 16:9-era framing crops too much in
zoomed-in scenes. The material is actually **2:1** (3840x1920), so the numbers
below are for 2:1 → 2.39. Run this in Unplugged on the scope display with the
rail up; the trial canvas now shows the full-screen composition.

## Material

| ID | Path | Frame | Active | Correction |
| --- | --- | --- | --- | --- |
| M23 | `E:\Dataset\House.of.the.Dragon.S03.2160p.HMAX.WEB-DL.DDP5.1.DV.H.265-NTb\House.of.the.Dragon.S03E01.2160p.REPACK.HMAX.WEB-DL.DDP5.1.DV.H.265-NTb.mkv` | 3840x1920, 2:1 | 2.0 | screen 2.39 / active 2.0 = 1.195 (+19.5 %) |

Pause on a **zoomed-in face** (record the timestamp) and, separately, a wide
shot. The complaint is about the close-ups.

## Cases

Baseline: Enable NLS On, Screen Scope (or Auto; the canvas is the window),
Strength 100, Centre 45, Curve 1.2, Post NLS crops 0, Lock band Off. Only the
rows below change.

| Test ID | Fill mode | Bars removed | Max distortion | Expected INFO | What it shows |
| --- | --- | --- | --- | --- | --- |
| HOTD-CROP-100 | Crop | 100 | — | GEOM CROP ≈ 16 %, warp 0 | Cover: 8 % cut top and bottom. The current complaint case. |
| HOTD-CROP-75 | Crop | 75 | — | CROP < 16 %, side bars | Less vertical cut, bars return at the sides. |
| HOTD-CROP-50 | Crop | 50 | — | CROP ≈ 8 %, more side bars | Halfway to fit. |
| HOTD-CROP-0 | Crop | 0 | — | CROP 0, fit with side bars | No cut at all; the 2:1 frame sits inside the scope screen. |
| HOTD-AUTO-140 | Auto | 100 | 140 | WARP H ≈ +20 %, CROP 0 | All warp, no crop; faces get wider, not cut. |
| HOTD-AUTO-110 | Auto | 100 | 110 | WARP H +10 %, CROP ≈ 8 % | The field user's "some NLS, crop the rest" trade. |

## Procedure

1. Load the episode; pause on the zoomed-in face.
2. Set the baseline, then the case row.
3. Read the INFO panel: `WARP H / V`, `GEOM CROP`, `POST-NLS X/Y-CROP`.
4. Capture the frame (app save-frame or Win+Shift+S) as `<TestID>_face.png`.
5. Play 10 s of the same scene and note any clipping or pumping.
6. Repeat on a wide shot; record both in the workbook `Runs` sheet.

## Acceptance questions

- At which case does the zoomed-in face stop losing the top of the head?
- Is the side-bar return at Crop 50/0 acceptable, or does the smaller picture
  defeat the point of a scope screen?
- Does Auto 110's +10 % width warp read better than the 8 % vertical crop?
- Does Auto 140 avoid clipping entirely, and is +20 % width acceptable on faces?

Row IDs are already in `Test Matrix` (screen Scope, material M23). Record the
numbers and the eye verdict per case; do not delete failures.
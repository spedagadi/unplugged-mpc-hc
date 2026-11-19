# NLS aspect rule — field test plan (2026-11-19)

Closes UR-0007 (aspect-aware NLS) and the 2.3.0 NLS work. The rule is built and
scope/small-bars are verified from live capture; this run proves it on the
media library with real titles.

## Configuration

- HDR → Tone Mapping → **Aspect rule = On**
- Native max aspect **1.90**, Scope min aspect **2.15**, Small-bar removal **100 %**
- Scope window = the user's own Bars removed / Post-NLS X-Y crop tuning
- **Lock band Off** (the rule forces it off and logs if it was On)

## Material (from `library.db`, 23 titles)

Aspects below are the expected theatrical ratios; the app's **DETECTED ASPECT**
row confirms the actual active picture. Dune and Catching Fire are the
mixed-aspect (IMAX) cases.

| Title | Year | Expected | Window to prove |
| --- | --- | --- | --- |
| Zack Snyder's Justice League | 2021 | 1.33 (4:3) | **Native** — no zoom, pillarbox kept |
| The Lighthouse | 2019 | 1.19 | **Native** — no zoom |
| Dune | 2021 | 2.39 + IMAX 1.43/1.90 | **Scope + live Native switch** |
| The Hunger Games: Catching Fire | 2013 | 2.39 + IMAX 1.78 | **Scope + live Native switch** |
| Spider-Man: Far From Home | 2019 | 2.39 | **Scope** |
| Dante's Peak | 1997 | 2.35 | **Scope** |
| The Day After Tomorrow | 2004 | 2.39 | **Scope** |
| The Substance | 2024 | 2.39 | **Scope** |
| Pale Rider | 1985 | 2.39 | **Scope** |
| Shaun the Sheep: The Beast of Mossy Bottom | 2026 | ~1.85 | Native (confirm) |
| 2026 streaming titles (Bad Apples, Primetime, By Any Means, Heart of the Beast, Forgotten Island, Never After Dark, Your Mother Your Mother Your Mother, 28 Years Later: The Bone Temple) | 2026 | unknown | **find the 2.00:1 / Small-bars case** |

**Small-bars case:** if none of the 2026 titles reports 1.90–2.15, prove the
window by temporarily setting Scope min aspect to 2.60 (as in the dev test) and
restore afterwards.

## Procedure

1. Open a title; from the Info panel record **DETECTED ASPECT** and
   **ASPECT WINDOW**. Confirm the log line
   `nlsaspect: <aspect> -> native|small-bars|scope (bars=… crop=…/…)`.
2. **Native titles** (ZSJL, Lighthouse): picture must be its own shape, no
   stretch/crop — BARS REMOVED 0, COST NOW 0, GEOM CROP 0.
3. **Scope titles**: the user's tuning must be in force (BARS REMOVED = the
   configured value; Post-NLS crops as configured; the picture matches the
   baseline look with the rule Off).
4. **Mixed-aspect** (Dune, Catching Fire): watch across an IMAX cut and back.
   Expect one window switch per cut within ~1 s, Native on the 16:9/1.43
   section (no zoom) and Scope restored afterwards. Verify with the log
   timestamps and the Info rows.
5. **Lock band**: turn it On with a title playing; expect
   `nlsaspect: Lock band forced off …` and the rule continuing to track.
6. **Rule Off / stop**: the user's Bars removed and crops must be restored
   (`nlsaspect: released - user values restored`).
7. Record every DETECTED ASPECT in the table above — this becomes the release
   note evidence.

## Pass criteria

- No title is over-zoomed: Native sections are never stretched or cropped.
- A 2.00 title gets the Small-bars window (100 %, crops 0), not the scope crop.
- The scope tuning applies only to scope content.
- Switches are clean (one per cut, no flicker), and the log records each one.
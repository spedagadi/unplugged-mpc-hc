# Unplugged 2.1.0

Bug-fix and NLS release on top of 2.0.0. No library or settings migration is
required: install over 2.0.0 and your library, presets and calibration remain.

| Download | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.1.0.exe` | 127,066,591 bytes | `C29D4D4917942865E1CE53A9B8F2C5977FFE162900423BAFACF7C02A757EC9C4` |

## Non-linear stretch

- **Auto now fills clean sources.** 2.0.0 required a valid detected band, so a
  16:9 or scope picture with no encoded bars did nothing. Auto fills whenever
  the band is known, including “no bars”.
- **Max distortion is a live control again.** It caps the warp per axis; the
  remainder is cropped. 100 % is the zero-warp Crop baseline.
- **Bars removed is authoritative in every fill mode.** Auto no longer forced
  it to 100 % while the shader read the slider (the horizontal-squeeze bug).
- **Crop follows Bars removed.** 0 % keeps the bars, 100 % covers; the old
  branch always covered and ignored the dial.
- **Post NLS X-Crop / Y-Crop.** New per-axis amounts applied after the NLS
  pass, bars first, stretching the remainder to fill. Real time, even when the
  aspect already matches the screen.
- **Aspect transitions.** The detected band is watched per frame (40 ms)
  instead of once a second; scope↔IMAX cuts re-latch immediately and cannot
  leave the old band cropping the new frame for ~20 s.
- **Trial view with the rail up.** Geometry and shader share a screen-aspect
  canvas fitted inside the visible area, and the shader is re-injected on chrome
  toggles — the picture and INFO panel now match full screen.
- **Axis defaults to Horizontal.** Split 25 measured +26 % vertical and
  visibly elongated heads; Split remains an opt-in with a warning, never a
  default. Centre 45, Curve 1.2, Max distortion 140; shipped presets aligned.
- INFO panel reports bars removed, max/current cost, per-axis warp, cap,
  geometry crop and the Post-NLS crops.

## Library and UI

- **Back returns to the full-section page** you drilled from (the “85 titles”
  list), with scroll and selection, instead of dropping to Home.
- **Episode grids draw every visible row** (previously only four thumbnails).
- **Right-click hide/restore is a themed card**, not the default Windows menu;
  the soft hide survives rescans and has “Restore all hidden titles”.
- **Now Playing year is deterministic** — taken from the item, not the tile’s
  state-dependent subtitle.
- **Removed-root duplicates are hidden.** Rows from a folder that is no longer
  registered (e.g. F: → E:) no longer appear as UNAVAILABLE twins; cleanup runs
  at library open as well as after a scan.
- **Series art fills every episode.** The series-art query used MAX(show_art),
  so one episode having the poster made the show look complete. It now repairs
  all rows.
- **Wikipedia poster fallback** now handles films whose article is the plain
  title, JSON-escaped image names, and TV series (`Title (TV series)` etc.).
  It runs even when OMDb is unavailable.
- **OMDb budget protection.** All OMDb calls are counted locally and capped at
  900/day (free key limit is 1,000), surviving restarts; Wikipedia is not
  counted. Large libraries may take several days to populate fully.
- **Rating chips are always present.** Movie, show and Continue tiles no longer
  wait for their background metadata lookup to grow a chip. Continue tiles
  prefer the episode rating, then the series rating, then the season average;
  anything still unknown shows **IMDb N/A** and is replaced when the record
  arrives.

## Renderer

- Left/right bar detection added to the per-frame detector; `barsNow` reports
  all four edges.
- Krig shader generation uses `frameW` instead of the width macro `w`, which
  was rewriting `.w` swizzles and made every Krig converter fall back.

## Known limitations

- **Split / Vertical** introduce a vertical component; faces can look elongated.
  They are opt-in, and Horizontal is the default.
- Per-episode stills are not available from OMDb/Wikipedia; episodes share the
  series poster.
- Windows cannot signal an **SDR BT.2020** gamut flag. HDR10/PQ/2020 is emitted
  when HDR output is on; for SDR the sink should be BT.709 (or set manually).
- The installer still ships the same LAV and DeckLinkSource binaries as 2.0.0.
# Unplugged 2.1.0

2.1.0 builds on the 2.0.0 native player. Non-linear stretch is now a set-once
tool instead of a tuning exercise, the library is more reliable, and a problem
report can be produced in one click.

| Download | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.1.0.exe` | 127,087,675 bytes | `A6CEAF1D3F848C269DDF539A1598180BC76C9C250F951724F0DE58692A1A41EF` |

## Non-linear stretch

- **Auto works on every title.** It fills clean 16:9 and scope sources as well
  as letterboxed ones; no valid bar band is required.
- **Bars removed is authoritative in every fill mode**, and **Crop** now follows
  it too: 0 % keeps the bars, 100 % fills.
- **Max distortion is the warp budget.** It caps the shape change per axis and
  the remainder is cropped; 100 % is the zero-warp Crop baseline.
- **Post NLS X-Crop / Y-Crop** are new per-axis amounts applied after the
  stretch. They crop the whole frame, bars first, and stretch the remainder to
  fill — so they can consume bars left by a partial Bars removed, and only cut
  picture once past the bar width. Changes are visible immediately.
- **Aspect transitions are clean.** The detected band is watched per frame, so
  scope↔IMAX cuts re-latch at once: no stale crop and no NLS drop-out through
  the transition.
- **Tuning with the rail up shows the real result.** Geometry and shader share
  a screen-aspect canvas fitted inside the visible area; the picture and INFO
  numbers match full screen.
- **Horizontal is the default axis.** It keeps height untouched. Split and
  Vertical remain available but introduce a vertical component; they are opt-in.
- **The Screen preset selector is gone.** Its entries were identical and the
  canvas is the screen, so Auto already adapts per title. NLS settings remain
  part of every main preset; there is no separate `nls_presets` folder.

## Library

- **Row-based season, episode and movie views** with poster, plot, file facts
  and IMDb rating chips; movies can switch between posters and rows.
- **Ratings are always present.** Movie, show and Continue tiles show a value or
  **IMDb N/A** immediately, replaced when the record arrives. Continue tiles
  prefer the episode rating, then the series, then the season average.
- **Back returns to the full titles page** you drilled from, with scroll and
  selection, instead of dropping to Home.
- **Every visible episode thumbnail draws** (previously only four).
- **Right-click Hide/Restore is a themed card**, survives rescans, and
  “Restore all hidden titles” brings items back. Rows from a removed folder no
  longer appear as UNAVAILABLE duplicates.
- **Now Playing year is consistent** — read from the item, not its progress
  subtitle.
- **Poster and art reliability.** Wikipedia is a fallback for films and TV
  series when OMDb has no match; a series poster is applied to every episode;
  failures retry with backoff. OMDb calls are capped at 900/day (the free-key
  limit is 1,000), so a very large library may take several days to populate.

## Picture

- Left/right black-bar detection added; the renderer reports all four edges.
- Krig chroma conversion fixed (the generated shader’s width macro was
  rewriting `.w` swizzles, forcing every Krig path to fall back).

## Report a problem

A new card in System creates `Unplugged-diagnostics-<stamp>.zip` on the
Desktop: UI/engine/renderer logs, settings and presets, crash-dump listing, and
an environment report (OS, GPU, displays, binary versions, filter health, codec
registration). It shows the support address with **Copy address**, **Show file**
and an **Email support** action; attach the zip yourself (mailto cannot carry
attachments). Logs are compressed, so the archive is a few MB.

## Upgrade

Install over 2.0.0. The media library, look presets and calibration data are
preserved. No settings migration is required.

## Known limitations

- Split/Vertical stretch introduces a vertical component and can visibly
  elongate faces; Horizontal is the default.
- OMDb/Wikipedia provide one series poster, not unique stills per episode.
- Windows cannot signal an SDR BT.2020 gamut flag. HDR10/PQ/2020 is sent when
  HDR output is on; for SDR the display should be set to BT.709 (or manually).
- The LAV and DeckLinkSource binaries are unchanged from 2.0.0.
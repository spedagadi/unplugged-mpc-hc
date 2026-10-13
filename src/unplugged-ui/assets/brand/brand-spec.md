# unplugged — brand spec

The minimal design system for **unplugged**. Keep it consistent; that's what makes a
long-lived open-source project feel like real software rather than a patchwork.

---

## The idea

A free, open-source, real-time HDR→SDR tone-mapping pipeline (built on mpv + libplacebo)
that runs on hardware you already own — the *unplugged* alternative to the expensive
commercial boxes. The mark is a **signal cable shaped as a tone-mapping roll-off curve**,
terminating in a **plug pulled free of its socket**, with a **spark** at the disconnect:
the "unplugged" moment / the freed signal.

Taglines:
- Splash / invitation: **free your nits**
- Acquisition / arrival: **locked in… no going back!**

---

## Colour

| Token            | Hex        | Use                                              |
|------------------|------------|--------------------------------------------------|
| `orange`         | `#E8551F`  | THE brand colour. Mark, accents, tagline, dot.   |
| `orange-bright`  | `#FF8A4C`  | Flash / highlight state (tagline flare, hovers). |
| `spark`          | `#FF7A3D`  | The spark accent on the static marks/logo.       |
| `spark-snap`     | `#FFFFFF`  | Splash (A) spark — cool electrical snap.         |
| `spark-bloom`    | `#FFE0CC`  | Acquisition (B) spark — warm awakening bloom.    |
| `glow-halo`      | `#FFB080`  | Acquisition (B) soft radial glow behind spark.   |
| `bg`             | `#000000`  | True black — app canvas, splash, video letterbox.|
| `panel`          | `#0E0E10`  | Panels, icon container, wordmark backing.        |
| `border`         | `#242428`  | Subtle 1px separators / icon container edge.     |
| `text-primary`   | `#F2F2F2`  | Wordmark, primary labels.                        |
| `text-secondary` | `#8A8A90`  | Secondary/status text.                           |

> **The three spark colours are intentional, not drift.** The static logo uses warm
> `spark` (#FF7A3D). The two animations deliberately differ: splash A is a *cool white
> snap* (something forcibly released), acquisition B is a *warm bloom* (something coming
> alive). Do not "normalise" them to match — the difference is the design.

### Stroke hierarchy (the mark)
Cable = 9, plug/socket = 7, spark = 4 (thickest cable → thinnest spark). Keep this ratio
if you redraw the mark at other sizes.

### The dot
The orange full-stop after the wordmark is `#E8551F`, ~13px at 54px text, sitting on the
baseline with a ~6px gap. In animations it flares (white, scale ~2.2×) then settles — this
reads as the spark landing as the wordmark's period.

Rule: **~90% greys, one accent (orange), used semantically.** Reserve colour for meaning —
green = good/locked, amber = warning, red = error/dropped-frames/clipping.

---

## Typography

- **UI + wordmark:** Inter (fallback: Segoe UI, system-ui, sans-serif), weight 600 for the
  wordmark, 500 for taglines/labels.
- **Numeric / live values:** a tabular/monospace face (JetBrains Mono, Cascadia Code, or
  IBM Plex Mono) so per-frame numbers don't jitter as digits change width.
- Wordmark: lowercase, letter-spacing ~1px. Taglines: letter-spacing ~2px.

> The wordmark SVGs now specify Inter (the brand font), and the PNGs were rendered with Inter installed.

---

## Spacing & shape

- Spacing unit: **4px**; use multiples everywhere (gaps, padding, margins).
- Corner radius: panels/buttons ~4–6px; icon container ~22% of size. Avoid heavy rounding.
- Flat. No gradients beyond the subtle cable fade, no glassmorphism, no drop shadows
  (except the tagline's brief glow-flare on arrival).

---

## Logo usage

**Wordmark** (`here is unplugged`): README header, About box, splash, external write-ups.
Use the **dark-panel** version on any uncertain/light surface (e.g. GitHub); use the
transparent version only where the background is already dark.

**Mark / icon** (`unplugged is running`): title bar, taskbar, tray, favicon.

Do **not** put the wordmark inside the live stats UI — that's instrument territory; a small
mark as a quiet corner signature at most. Don't over-expose the brand to its own user.

---

## Motion

Three states, sharing the same atoms (spark, orange, cable-curve, plug), scaled to how
often each fires:

| State            | Animation                | Feel                    | Frequency        |
|------------------|--------------------------|-------------------------|------------------|
| App launch       | **A — The Release** (6s) | brisk arrival / snap    | rare → can flourish |
| Capture lock     | **B — The Awakening**    | poetic awakening        | occasional → atmospheric |
| File load        | spark-only (~400ms)      | minimal                 | frequent → subtle |

In production A and B play **once** (no loop); the looping in the HTML files is only for
preview. Drop the fade-and-reset tail when embedding.

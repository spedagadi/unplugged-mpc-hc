# Unplugged Settings Guide

For **Unplugged 1.2.0**. Covers every control visible in the settings panel:
what it does, its full range, and what the picture does when you move it.

## How to get started

**Quick config**

1. Press **Up** on the keyboard to toggle the live status and settings panels
   (Up again hides them).
2. **Convert to SDR** — On.
3. **SDR display nits**, **Static nits (max)** and **Display black (nits)** —
   set to your display's calibrated, measured values.
4. The user trims — **Exposure**, **Shadow detail**, **Contrast** — live on
   the HDR tab.
5. Leave the Zion tab settings on **Auto** where applicable.
6. Calibration LUT files load from **Output → Display calibration**.
7. Frame captures come from **Output → Save frame as PNG**.

**Why that order — three stages, in sequence:**

1. **Calibration settings first.** The tone curve maps HDR into *your*
   display's measured range. A wrong white, black or peak means every
   downstream decision is made for a display you don't own. These numbers are
   set once per display and never used for taste. If you have a measured
   calibration **LUT**, load it at this stage.
2. **Zion grade second.** With **Mode: Auto** and the Band controller On, the
   grade's scene model and closed loop do their work — and they correct what
   calibration measured, so they only make sense after stage 1.
3. **Trims last.** Exposure, Shadow detail and Contrast are the final taste
   layer, and the only controls to touch day-to-day. Trim before calibrating
   and you tune against a moving baseline — every stage-1 or stage-2 change
   rewrites what "right" looks like.

## How the panel works

- Open the settings panel and pick a tab on the left icon rail:
  **▶ Playback · ⬡ Source · ◑ HDR · ✦ Zion · ▣ Output · ≡ System**.
- Each tab is split into **sections**. Sections are an accordion: click a header
  to open it; only one section is open at a time. A tab with a single section
  (Source, System) is always open.
- **Toggles** flip ON/OFF with one click. **Option rows** (`‹ value ›`) cycle
  through their choices — click the right side to advance. **Sliders** are
  dragged on the bar; hover the bar and use the **mouse wheel** for exact
  single steps (1 unit on whole-number rows, 0.01 on decimal rows — this is how
  you land on a measured value like 174 nits).
- Everything applies **live** to the running picture and is saved immediately —
  except rows marked *[next open]* below, which take effect the next time a
  file or capture starts (they change which pipeline the renderer builds).
- Your settings are plain text at `%LOCALAPPDATA%\Unplugged\s3_shell.ini`.
  Every row writes itself there on first start, so you can back it up, or
  hand-edit a value a slider can't reach (like `hdr.maxNits` above 1000).

---

## Playback (media files)

> The Playback tab is dimmed and unreachable during live capture — its controls
> address the file-playing pipeline, which capture never builds.

### Audio

| Setting | Choices | Default | What it does |
| --- | --- | --- | --- |
| **Track** | every audio stream in the file | first track | Picks the language/format. Names come from the file itself: "Deutsch TrueHD Atmos 7.1". |
| **HD audio** | `Bitstream` / `PCM` | `Bitstream` | **Bitstream**: the compressed audio (Dolby, DTS, TrueHD, Atmos) is passed untouched to your receiver, which decodes it and shows its logo. **PCM**: the PC decodes it first — use this if the receiver can't decode the format, or to hear everything through TV speakers. Bitstream is the shipped default: an AVR decodes its own formats better than a PC downmix. |
| **Delay** | −500…+500 ms | 0 | Intended for lip-sync correction. *In this version the slider saves but nothing reacts to it yet — it has no effect.* |

### Subtitles

| Setting | Choices | Default | What it does |
| --- | --- | --- | --- |
| **Track** | `Off` / every subtitle stream | `Off` | Picks the subtitle track. Names keep the format in brackets — `(SRT)` etc. — because only **text** subtitles can be styled; bitmap ones (PGS, VobSub) are images and always look how the disc made them. |

---

## Source (live capture)

One row per physical DeckLink input, plus three actions.

| Row | Shows | What it does |
| --- | --- | --- |
| Port row | name + badge | Click to switch the player to that HDMI input. The active port gets `●`. Badges: `🔒 HDR PQ` = an HDR signal is locked and being carried, `○ no signal` = nothing is plugged in or the source is off, `— unknown` = signal present but not identified yet. |
| **⟳ Rescan inputs** | — | Re-asks the card what is plugged in. Use after connecting a new device. |
| **✎ Rename inputs…** | — | Names your ports ("Console", "Bluray") — the name is yours only; the underlying input is unchanged. |
| **▶ First-time setup… (restarts app)** | — | Restarts the app into the setup wizard. Stops any playback. |

---

## HDR tab

Everything here shapes how an HDR signal arrives on your display, plus a few
post-processing tools. **SDR display nits** and the **Display Target** numbers
are set once — they describe your display, not your taste — and day to day
most people only touch **Tone curve**, **Exposure** and the taste sliders.

### Tone Mapping

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Convert to SDR** | On / Off *[next open]* | On | On: HDR video is tone-mapped into the normal (SDR) range this app renders. Off: the HDR signal is passed on for your TV itself to map — only sensible with an HDR-capable TV in HDR mode. When Off, everything else in this tab and the Zion tab stops mattering, because this app is no longer doing the picture. |
| **SDR display nits** | 25…400 | 50 | The **measured** SDR white luminance of your display — a calibration number like *Static nits (max)* below, never a taste knob. Enter your measured value (a TV in a bright room typically 100–200; a projector in the dark 40–80) and leave it there. What a wrong number does: declared *below* your measurement, the picture runs bright and the highlights pay — the shoulder clips sooner and sky detail goes first; declared *above* it, films render dark with headroom unused. Brightness without lying about your panel is what **Exposure** is for. |
| **Tone curve** | `Unplugged` / `GT7 Adapt` | `Unplugged` | How HDR's brightness range is squeezed into your display's. **Unplugged** — the house curve, and the safe choice for everything Dolby Vision: DV carries its own per-scene mastering and this curve respects it. **GT7 Adapt** — the house curve for HDR10/HLG, which blends the title's declared peak with what each scene measures. The taste trims below work on both; switching curve changes the Curve Settings dials shown. |
| **Exposure** | −5…+5 | 0 | A brightness dial that works **before** the tone curve, in thirds of a stop: ±1 = ±⅓ stop, ±3 = ±1 stop. Because it's pre-curve, the shoulder absorbs it — brightness without spending your highlights. The safest lever when a specific film looks dark or washed. |
| **Shadow detail** | −5…+5 | 0 | How much texture survives in the dark end. **Positive** spreads dark values apart — you see fabric weave, night-scene layout, object edges — while true black stays black (it is *detail*, not a brightness lift). **Negative** compresses blacks together, for a denser, more "filmic" shadow that hides crushed masters. Never greys the image. |
| **Contrast** | −5…+5 | 0 | A symmetric S-curve around mid grey: black, mid grey and white stay exactly where they are, everything between moves away from (positive) or toward (negative) them. Positive = more "pop"; negative = flatter, softer. If you want one dial to taste day-to-day, this is the safe one. |

**Exposure**, **Shadow detail** and **Contrast** are taste trims — they work
the same on both tone curves. The Curve Settings dials are the opposite: they
belong to one curve, so the rail hides them when that curve isn't selected.
(On **Unplugged** no Curve Settings section appears at all — the trims above
are the whole adjustment surface. It reappears with **GT7 Adapt** selected.)

### Curve Settings (appears only for **GT7 Adapt**)

| Setting | Range | Default | What it does |
| --- | --- | --- | --- |
| **Title peak (nits)** | 100…4000 | 1000 | The content peak the curve squeezes from. Leave at 1000 unless you know the disc's MaxCLL. |
| **Auto exposure** | On / Off | Off | Solves the working peak from each scene's measured average instead of guessing (updates at scene cuts, never mid-shot). Use when a title looks consistently a third of a stop off. |
| **Exposure target** | 0.20…0.70 | 0.42 | With Auto exposure On: where the scene average should land (0 = black, 1 = white). |
| **GT7 blend (ch<->UCS)** | 0…1 | 0.6 | How much highlights keep their source colour: 0 = curve re-derives it, 1 = source colour returned intact. |
| **GT7 chroma fade from** | 0.3…2.0 | 0.98 | The level where that colour blend starts. Default leaves it a highlights-only move. |
| **GT7 adapt to scene peak** | 0…1 | 0.25 | How far the peak moves from *Title peak* toward the measured scene peak. Raise for sources without usable metadata (HDMI consoles, streaming apps). |
| **GT7 desaturation** | 0…1 | 0 | Colour pulled out of **highlights only**, in proportion to how hard they were compressed. Mid-tones and skin are untouched. |
| **GT7 shoulder reach** | 0.02…0.90 | 0.25 | Highlight headroom: **lower = longer shoulder**, more brightness band survives before detail merges to white; higher punches mid-highs but clips sooner. The first dial to turn down if explosions clip. |
| **GT7 debug view** | `Off` + 4 greyscale modes | Off | Diagnostic overlays of the curve's internals. Leave Off for watching. |

### Tone Mapping (delivery & gamut)

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Output gamut** | `BT.709 (standard)` / `BT.2020 (wide)` | 709 | The colour space delivered. 709 is what SDR (and effectively every TV's SDR mode) expects. BT.2020 keeps wide colour *only* for a display actually in HDR/wide-gamut mode — on a normal SDR pipeline it makes colours wrong. Leave on 709 unless you know exactly why you changed it. |
| **Gamut capacity (709)** | 0.20…1.00 | 1.00 | Active only with Output gamut = 709. Colours can look garish not when they *exceed* the gamut but when they sit exactly *on its edge* — the maximum for their lightness. This lands each colour at a fraction of its own distance to the edge: 1.00 = off; 0.55 is how much breathing room measured reference software leaves a deep-blue sky. Pale colours have long distances and stay untouched at any setting, so this can never "desaturate the whole film" — only edge-crowded blues/reds relax. |
| **Highlight desat** | 0…1 | 0 | A companion to the row above for **the Unplugged curve**: at higher brightness levels, pull saturation toward the level's own neutral point (hue preserved). Measured against reference renderers, 0.50 matches; 0 is off. Note: it runs inside the grade, so it needs *Enable ML grade* (Zion tab) on. |

### Display Target — calibrate these first

These describe **your TV/projector**, not the content. Set once per display.

| Setting | Range | Default | What it does |
| --- | --- | --- | --- |
| **Windows HDR** | `Do not change` / `On (fullscreen)` / `On` / `On/off (fullscreen)` / `On/off` | Do not change | Whether this app toggles Windows' own HDR mode for the display when playing. Leave `Do not change` if you set HDR/SDR mode in Windows yourself; the others switch it for you at playback start (the "on/off" pair restores your previous state afterwards). |
| **Static nits (max)** | 10…1000 | 1000 | Your display's measured peak white in SDR mode. This is the destination the tone curve maps **to** — get it wrong and everything is wrong. Measured 174 on a projector? Type nothing: drag near it, then mouse-wheel over the bar, 1 nit per click. A display brighter than 1000 nits: edit `hdr.maxNits` in the INI directly (the engine accepts up to 10000). |
| **Display black (nits)** | 0…2 | 0 | Your display's measured black level. At 0 the curve assumes a perfect black and spends shadow detail on range you can't actually see. A projector measuring 0.3: enter 0.3 — the destination range starts there and the shadow band is redistributed into what the panel shows. For OLED (true black), 0 is right. |
| **Subtitle/OSD brightness** | 0…100 | 0 | How bright subtitle and on-screen text renders against the finished picture. 0 = normal. Raise if text gets lost in bright content — it lifts the text layer only, never the film. |

### Post-FX — optional clean-up layers

These run **after** tone mapping and grading, on the final image — they behave
identically on SDR, HDR10 and Dolby Vision sources.

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Adaptive sharpen** | On / Off | Off | Edge-adaptive detail: measures each edge against its local neighbourhood and limits itself, so it adds detail without white halos. Soft SD/HD sources benefit; clean 4K rarely needs it. |
| **Sharpen strength** | 0.3…1.5 | 1.0 | How much of that adaptive detail to add. 0.3 is a whisper, 1.0 strong and still safe, ~1.2+ starts showing its hand on film grain. |
| **Deband** | On / Off | Off | Removes the stepped bands that appear in slow gradients (sky fades, dark walls) — the banding the 10→8-bit conversion creates — by flattening each band edge then covering the work with fine grain. |
| **Deband threshold** | 0…256 | 32 | How small a gradient step gets treated; pushing it high starts eating real picture detail. |
| **Deband range** | 1…64 | 16 | How wide an area is blended per band. |
| **Deband iterations** | 1…4 | 1 | Processing passes; 2 is usually the honest maximum. |
| **Deband grain** | 0…128 | 24 | The noise that hides the blending — 0 exposes it as mush; matching real film grain (~20–30) is the target. |

---

## Zion tab — the grade

The Zion pipeline models your display and content and corrects both. One switch
owns the whole tab, and there's a one-click undo for a session gone wrong.

| Setting | Default | What it does |
| --- | --- | --- |
| **Enable ML grade** | On | The master switch for everything on this tab. Off = the render is pure tone curve + post-FX; every section below becomes decorative. |
| **⟲ Reset grade to defaults** | — | Asks, then restores every row on this tab to its factory value. The quickest way out of a grade you can't diagnose. |

### Tone Curve (grade section)

| Setting | Range | Default | What it does |
| --- | --- | --- | --- |
| **Band controller** | On/Off | On | The closed loop. Instead of applying shadow/gamma/highlight corrections blindly, it solves all three together every frame so the delivered picture lands on fixed house levels (deep shadow, mid, and highlight anchors). While it's On, it *owns* the legacy **Shadow** slider and the manual **Gamma top-up** — those stand down because applying them on top would double the move. Off returns you to the older, open-loop path (the sliders below act directly again). |
| **Mode** | `Auto` / `Manual` / `Off` | Auto | **Auto**: the scene model judges shadow toe, gamma and highlight per scene and applies the corrections itself. **Manual**: the model's per-scene gamma freezes and the sliders become the sole authority — this is the starting point for manual tuning. **Off**: the tone-curve leg of the grade does nothing; micro-contrast and the rest still run. |
| **Shadow** | 0…0.40 | 0 | A legacy multiplicative toe on the dark end. Effective in Manual mode with the Band controller Off (otherwise the controller's own solution overrides it — see its row). Positive opens blacks progressively; past ~0.15 you will start seeing it *everywhere*, because a toe lift is global, not local. |
| **Shadow dehaze** | 0…1 | 0 | Auto-mode correction: the model sometimes lifts shadows for safety, which greys dark scenes (a "haze"). This scales **down** that lift — 1 fully removes the model's shadow boost. It only acts on what the model did, so it cannot grey or crush a scene on its own. If dark Auto-mode scenes look foggy, this is the dial. |
| **Gamma** | 0.5…1.5 | 1.0 | Manual-mode mid-range brightness. Below 1 lighter, above 1 darker, applied around fixed black/white anchors. Ignored in Auto (the model writes it). Not a "brightness" knob for whole titles — that's Exposure or SDR nits. |
| **Gamma top-up** | −0.50…+0.50 | 0 | A signed *offset* on top of the model's own Auto answer — a taste trim that survives scene changes. Positive brightens mids everywhere the model said "normal"; highlights stay put. With the Band controller On, the controller owns this band too (see its row), so test it with the controller Off. |
| **Mid-tone target** | 0…0.95 | 0 | The grade's delivery-referenced brightness dial: where (0=black, 1=white) you want the *scene average* to end up on your screen. The renderer computes what the curve is about to deliver and solves the gamma that lands it — so unlike every earlier brightness route, moving **SDR display nits** afterwards doesn't drag your brightness off this target. 0 = off; 0.42-ish matches a conventional bright-scene average. This is the dial that lets you make the house look brighter *without* costing you clouds. |
| **Highlight** | −0.3…+0.4 | 0 | Gain applied to the bright band above the curve's working range — the level of specular detail, sunlit walls, whites. Positive pushes them up (airier), negative pulls them back. Manual-mode centric. |
| **Highlight shoulder** | −0.2…+0.2 | 0 | Auto-mode correction, the mirror of Shadow dehaze: a signed offset on the model's highlight roll-off. Negative softens the shoulder's grip (bright areas keep separation, more "film"); positive tightens it (punchier but merges faster toward clip). |

### Chroma

Colour saturation shaping — how vivid a colour gets, with a brake for skin.
*(Note: the "Mode" row on this section currently saves but nothing acts on it;
the Default behaviour is what always runs.)*

| Setting | Range | Default | What it does |
| --- | --- | --- | --- |
| **Normal** | 1.0…1.3 | 1.08 | Chroma gain for ordinary-saturation colours: skin, foliage, interiors. The small default boost is the house vividness; 1.0 is pass-through. |
| **Fire** | 1.0…1.3 | 1.15 | Chroma gain for the hottest band — flames, neon, emissives — where extra saturation reads as heat rather than error. |
| **Knee** | 0.1…0.9 | 0.45 | Where "ordinary" stops and "fire" begins, as a saturation level. Lower classifies more of the image into the hot band. |
| **Skin** | 0.5…1.0 | 0.95 | The skin brake: what *fraction* of the boost faces are allowed. 1.0 = faces get the full push, 0.5 = half. Guards against actors going lobster-orange. |

### Micro Contrast

Local clarity — texture inside objects, not edge sharpening. Runs on its own
enable switch even if the tone-curve Mode is Off.

| Setting | Range | Default | What it does |
| --- | --- | --- | --- |
| **Enable** | On/Off | On | Switches the micro-contrast engine. |
| **Strength** | 0…0.5 | 0.15 | How much local contrast to recover. The effect is texture-gated: flat gradients are left alone, real structure gets pushed. Past ~0.3 surfaces mastering noise and grain noise as "detail". |
| **Zone lo** | 0…0.6 | 0.15 | The brightness floor where the engine works at all. Everything below (night scenes' true blacks) is skipped — low-luma is where local contrast invents dirt. Raise it if dark scenes get mottled. |
| **Ratio cap** | 1.0…2.0 | 1.4 | The halo limiter: the maximum contrast ratio one pixel's neighbourhood may be pushed to. Lower = gentler, no rims; higher = stronger effect, but >1.7 on hard edges is where halos come from. |
| **Skin protect** | 0…1 | 0.65 | Faces get only this fraction of the effect — the difference between "pores" and "stubble texture on a model". |

### Debug (diagnostics — leave Off for normal viewing)

| Setting | What it does |
| --- | --- |
| **HDR passthrough** *[next open]* | Bypasses this app's entire picture pipeline and hands the raw signal to the display — the "is it the renderer or the TV" test. On a non-HDR display you'll see flat/green-grey nonsense; that's expected, not broken. Mutually exclusive with the next row by design. |
| **Tone curve passthrough** *[next open]* | Renders the decoded picture *without* tone mapping or grade — a copy of the source through the normal output. The A/B baseline when you suspect the curve. Also auto-switches HDR passthrough off. |
| **Frame log** | Writes a verbose per-frame telemetry line to the engine log (`%USERPROFILE%\.unplugged\logs\engine.log`) — what each stage computed, frame by frame. The thing to turn on when asking "why did the picture change there". |
| **MC heat** | Replaces the picture with a greyscale map of where the micro-contrast engine is working, so a visible seam can be matched to a mask edge. |

### Black Bars

| Setting | Default | What it does |
| --- | --- | --- |
| **Repaint bars** | Off | Overwrites the letterbox mattes with true black every frame. For sources whose "black" bars carry lifted noise or crawl; clean masters don't need it and it's extra GPU work. |
| **Highlight bars** | Off | Tints the detected bar regions so you can see what the app *thinks* is black bar — the way to verify detection before trusting Repaint. |

### Sky Seg

Experimental, off by default: the ML segmentor (ONNX/YOLO) carves the frame
into sky regions so their highlight treatment can differ from the rest.
If you did not go looking for this, leave it off.

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Enable** | On / Off | Off | Switches the sky segmentor on. Off leaves the picture untouched. |
| **Strength** | 0…1 | 0.6 | How much the sky region's special treatment is applied there. |
| **Mask overlay** | On / Off | Off | Diagnostic: paints the detected sky mask so you can see what it locked onto. |

### Person Skin

Experimental, off by default: segments people so faces can be protected while
the rest of the frame is graded.

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Enable** | On / Off | Off | Switches the person segmentor on. |
| **Strength** | 0…1 | 1.0 | How fully the detected region is treated as skin. |
| **Mask overlay** | On / Off | Off | Diagnostic: paints the detected people mask. |
| **Tone preserve** | 0…1 | 0 | How much of a face's original tone survives the grade — raise it to pull skin back toward the source while the rest of the frame stays graded. |

---

## Output tab

### Video Processing

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Super Resolution** | On/Off | Off | The renderer's upscaler for small sources: SD/HD material on a 4K panel gets a genuine reconstruction pass instead of plain interpolation. Turning it On also enables the two plumbing switches it needs (behind the scenes, no action from you). Know its limits: it doesn't engage for 10-bit or HDR sources, needs RTX-class NVIDIA or Intel graphics, and a 4K source on a 4K display has nothing to upscale. Windows' and the NVIDIA panel's own settings are outside this app's reach. |
| **Chroma upsampling** | `Nearest` / `Bilinear` / `CatmullRom` / `KrigBilateral` | Bilinear | How colour from 4:2:0 video (almost all of it) is expanded to full resolution. Nearest: raw blocks — diagnostic only. Bilinear: soft, never wrong. CatmullRom: a bit sharper. KrigBilateral: the sharpest colour edges (best on fine chroma detail like red text), the most GPU work. |
| **Upscaling** | `Nearest` / `Mitchell` / `CatmullRom` / `Lanczos2` / `Lanczos3` / `Jinc2` | CatmullRom | The enlargement filter for smaller-than-display sources. Gentle climb from soft to sharp: Mitchell (very smooth) → CatmullRom (balanced default) → Lanczos2 → Lanczos3 (crisper, small risk of ringing on edges) → Jinc2 (sharpest, ringing-prone on grain). On noisy SD material, sharper is not better. |
| **Downscaling** | `Box` / `Bilinear` / `Hamming` / `Bicubic` / `BicubicSharp` / `Lanczos` | Hamming | Shrinking a source to fit. Hamming is the balanced default: preserves detail without aliasing. Box/Bilinear go soft, Lanczos/BicubicSharp go crisp and can shimmer on fine patterns (thatches, fences). Matters most for 4K→1080p panels. |

### Output

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Show statistics** | On/Off | Off | The renderer's on-screen performance overlay — frame render intervals, dropped frames, GPU figures. What to turn on when asking "is it smooth". |
| **Save frame as PNG** | button | — | Captures the exact frame the renderer drew (not a screen grab: no overlays, no desktop compositing, no colour shift from screen capture) and lets you file it as lossless PNG. The right tool for showing someone a picture question. |

### Display Calibration

| Setting | Choices / range | Default | What it does |
| --- | --- | --- | --- |
| **Calibration LUT** | file picker | unset | Loads a display-calibration `.cube` (e.g. from DisplayCAL) applied as the **final** pass — it shapes what your panel actually emits, separate from tone mapping which shapes the signal. Clearing (mode → Off) frees the texture. |
| **LUT mode** | `Off` / `Gamma only` / `Greyscale` / `Full 3D` | Full 3D | How much of the loaded cube to honour. Gamma only: the neutral lightness curve (for a display whose colour balance is already set). Greyscale: per-channel tone and balance, no channel mixing. Full 3D: everything, including the gamut remap — the complete calibration, with the caveat that 3D cubes gently fade deep saturated colours. |

---

## System tab

### App

| Setting | What it does |
| --- | --- |
| **⟲ Reset renderer settings** | Deletes what the *renderer* stored in the registry (it keeps state of its own, and a previous machine's leftovers can ride along in a copy of the app). Your rail settings are re-applied immediately — this undoes registry state, not your configuration. |
| **▶ First-time setup… (restarts app)** | Restarts into the setup wizard (stops playback). |

---

## Recipes — start here

**"Everything looks dim."**
Check **SDR display nits** holds your display's *measured* white — a number
above the measurement is exactly what renders every film dark, and the fix is
the honest number, not a darker one. Still dim at the measured value →
**Exposure** (+1 = one-third stop; pre-curve, the shoulder absorbs it). A
*specific film* still off on GT7 Adapt → **Auto exposure** On.

**"Bright scenes hurt / whites glare."** Pull **Exposure** down; GT7 Adapt
users whose explosions lose detail → **GT7 shoulder reach** down (0.25→0.15).
Don't reach for **SDR display nits** — that row carries your display's measured
white and stays there.

**"Skies are neon / garish blues."** **Gamut capacity (709)** down to ~0.6;
GT7 curves: **GT7 desaturation** 0.3–0.6. Unplugged curve with grade On:
**Highlight desat** ~0.5.

**"Blacks are grey / no depth."** Check **Display black (nits)** matches a
measured value (a 0.3-black projector told "0 perfect" wastes shadow range).
Auto mode: **Shadow dehaze** up (it strips the model's safety lift). Too much
texture in shadows → **Shadow detail** down.

**"The image feels flat."** **Contrast** +1…+2, or **Micro Contrast** Strength
0.15→0.25. Both at once is usually one too many.

**"Faces look waxy/oily."** Every texture enhancer is a suspect: **Micro
contrast** (Strength down, **Skin protect** up), **Adaptive sharpen** (off or
strength down), **Shadow detail** down.

**"Stepped bands in dark gradients."** **Deband** On, defaults are tuned;
only raise **Threshold** if bands persist, and check **Grain** isn't at 0.

**"DVD/Blu-ray on my 4K TV looks soft."** **Super Resolution** On (RTX GPU,
SDR content). **Upscaling** to Lanczos2 for a crisper baseline — or leave
CatmullRom and let SR do the work.

**New projector/TV?** Measure it (or use published numbers): **SDR display
nits** from your white patch, **Static nits (max)** with the wheel, **Display
black (nits)** from the black patch, load a calibration **LUT** if you have one
— then leave everything else at defaults for a week before tuning taste
controls.

---

## Current limitations

- **Playback → Delay** (audio lip-sync) saves but does nothing yet.
- **Zion → Chroma → Mode** saves but does nothing yet; the Default behaviour
  always runs.
- Small enable-squares drawn beside some sliders are legacy chrome —
  they don't click. Set a slider to its 0/neutral value to bypass it.
- Super Resolution is not available for HDR or 10-bit sources; it is a
  SDR-path feature.
- Subtitle *styling* (font, size, colour) is not in this panel; only track
  selection is.

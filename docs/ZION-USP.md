# Zion Grade — USP and Messaging Strategy

**Purpose:** turn the implementation reference (`unplugged-VideoRenderer/docs/ZION_GRADE_REFERENCE.md`) into a defensible, audience-specific message.  
**Audience:** projector and OLED/QLED owners, HTPC builders, AVSForum technical buyers, value-conscious home-cinema buyers.  
**Rule:** every USP must survive three questions — *so what, prove it, and could a fixed-curve competitor say the same?*

---

## 1. The category and the core promise

**Category:** an ML-driven video processor for the home-cinema PC.

**Core promise:**

> The colorist's correction, learned scene by scene — on the PC you already own.

**One-liner:**

> Most video processors apply a curve. Zion learns the correction a colorist made from the image itself, predicts it per scene, and lands it on your display.

**The strategic opening:** every conventional video processor — BT.2390, a spline, a custom transfer curve — applies a *chosen operator*. Zion predicts a *correction* from the frame, using models trained on Dolby Vision colorist trims. That is the category difference. The base tone mapping is still mathematics; the grade is learned. Say that plainly; it is stronger than pretending the whole chain is AI.

---

## 2. The three-pillar message

| Pillar | Claim | Proof |
|---|---|---|
| **Learned, not fixed** | Three XGBoost models predict shadow toe, mid-tone gamma and highlight roll-off per scene. | 88 features, 1,700 trees, ~4.48 MB of models, CPU inference; trained on DV L2 colorist trims. |
| **Scene-aware, not global** | Sky and people are segmented, so the grade protects what a global curve cannot. | YOLO26 sky/person masks; sky guard relaxation; LUT-only-inside-people skin protection; ICtCp luminance gain. |
| **Open, not a black box** | GPL-3.0 source, shipped models, no subscription, local processing. | Public repos, `.plxgb` and ONNX files in the repo, 127 MB installer, no account. |

The pillars answer three buyer questions: *Why is the picture different? Why does it hold up on real content? Why should I trust it?*

---

## 3. USP candidates, ranked

### USP 1 — “It learns the colorist, not just the curve”

**Claim:** Zion predicts the shadow, mid-tone and highlight correction a Dolby Vision colorist made, instead of applying one fixed transfer function to every scene.

**Why it matters:** a fixed curve is a compromise across an entire film. Zion changes the grade when the scene changes — a dark interior, a bright sky, a face in mixed light — because the correction is inferred from the frame.

**Proof:**
- Three XGBoost regressors: shadow, gamma, highlight.
- 88 features per frame; 1,700 additive trees; ~4.48 MB of model data.
- Training targets come from Dolby Vision L2 colorist trims: `trim_2081_power`, L2 offset, shadow crush, gold-vs-spline highlight delta.
- Sub-millisecond CPU inference; no cloud, no per-frame GPU model.

**Buyer outcome:** highlights roll off instead of clipping; shadows keep texture; mid-tones follow the scene instead of a preset.

**Use it:** hero, AVSForum headline, first feature block, comparison page.

**Do not say:** “reconstructs the original Dolby Vision metadata” or “the whole pipeline is AI.”

---

### USP 2 — “Colorist intent without metadata”

**Claim:** the ML layer works from the image itself, so it can grade live HDMI, HDR10, HLG and SDR sources that carry no Dolby Vision metadata.

**Why it matters:** metadata-free sources are the hard case — consoles, streaming boxes, live sport, HDR10 discs with poor MaxCLL, SDR upscales. A metadata-driven processor has less to work with. Zion infers the correction from 88 frame statistics.

**Proof:**
- Runtime models do not read MaxCLL, L2/RPU data or DV metadata.
- The base tone mapper may still use content/display metadata; the *Zion models* are metadata-free.
- The training signal is DV L2, used offline only.

**Buyer outcome:** a consistent grade across sources, not “great on DV discs, flat on everything else.”

**Use it:** live-HDMI page, AVSForum technical section, FAQ (“Does it need Dolby Vision metadata?”).

**Do not say:** “it reconstructs DV without DV.” It infers a likely correction; it does not recover the original metadata.

---

### USP 3 — “It knows what it is looking at”

**Claim:** sky and person segmentation let the grade protect highlights in the sky and skin on faces — distinctions a global curve cannot make.

**Why it matters:** a global curve either protects highlights everywhere (and flattens faces) or pushes contrast everywhere (and blows skies). Segmentation separates the two.

**Proof:**
- `yolo26n-sem` sky model (Cityscapes sky class 10) at ~10 fps; relaxed highlight guard, softened roll-off, cloud-band lift inside sky.
- `yolo26n-seg` person model (COCO class 0); LUT-only-inside-people skin protection; micro-contrast damping on skin.
- Content-UV mask remap with an in-content gate, so bars never read the mask edge.

**Buyer outcome:** clouds keep detail; faces do not go waxy, over-sharpened or over-saturated.

**Use it:** feature section, A/B demos (“sky detail”, “face close-up”), projector/OLED audience pages.

**Do not say:** “AI understands the scene.” It runs two segmentation models and applies bounded corrections.

---

### USP 4 — “It closes the loop on what your display actually receives”

**Claim:** on GT7/GT7 Adapt, a deterministic band controller solves shadow slope, gamma and roll-off so the *delivered* p25/p50/p99 land on house targets, with the ML prediction as the prior.

**Why it matters:** a source-referred model cannot see what the tone curve, display target or calibration did. The controller measures the delivered picture and corrects the delivery.

**Proof:**
- Scene-locked bands, lift-only target law, secant solve, two passes, cut-snap IIR.
- Delivered-frame statistics instrument.
- `CTL` / `DELIVERED` log lines show anchors, targets, solved values and delivered values.

**Buyer outcome:** consistent brightness and contrast scene to scene; no pumping when objects move through the light.

**Use it:** technical deep-dive, AVSForum, “why it does not pump” section.

**Do not say:** “the controller runs on every curve.” It is currently GT7/GT7 Adapt only. State the gate.

---

### USP 5 — “Brightness moves; color does not”

**Claim:** the grade operates on the I channel of ICtCp and carries the curve's move back as a linear gain on the whole colour, so hue and relative saturation do not drift as the grade adapts.

**Why it matters:** many tone curves change hue and saturation when they change luminance — faces go pale, orange light goes white, deep blues shift. The Zion shaders deliberately avoid that.

**Proof:**
- ICtCp I-channel curve; `rgb_out = ictcp_to_linear(ictcp) * g`.
- Same treatment in micro-contrast.
- Skin LUT sampled in gamma-2.2 Cr/Cb, applied in ICtCp Ct/Cp.

**Buyer outcome:** faces and coloured light stay natural while the grade moves.

**Use it:** feature card, technical explainer, “colour science” section.

**Do not say:** “colour is mathematically perfect.” It is a luminance-preserving design, not a guarantee on every out-of-gamut source.

---

### USP 6 — “Free, open, and yours”

**Claim:** GPL-3.0 source, shipped model files, no subscription, no account, local processing.

**Why it matters:** this audience distrusts black boxes and recurring fees. Open source is a trust signal and a value statement.

**Proof:**
- Four public repositories.
- `.plxgb` and ONNX model files in the renderer repo.
- 127 MB installer; no cloud dependency.
- Settings survive reinstall; update check is notify-only.

**Buyer outcome:** no $5,000 box, no dealer appointment, no vendor lock-in; inspect what the picture is doing.

**Use it:** pricing/value section, footer, AVSForum, “why open source” page.

**Do not say:** “the models are open source” without qualification. The shipped models are in the repo; training data and model cards are planned for release, not shipped today.

---

### USP 7 — “One grade for live HDMI and files”

**Claim:** Video Processor and Media Player modes share the same renderer, tone mapping, Zion Grade and calibration.

**Why it matters:** a console, a streamer and a film library should not look like three different products.

**Proof:** two modes; one pipeline; same ML and shader stages; per-mode settings only where the machine differs.

**Buyer outcome:** one setup, one look, across sources.

**Use it:** “Live TV, movies and games” section, mode comparison table.

---

### USP 8 — “Tunable, not opaque”

**Claim:** Auto/Manual modes, taste dials, passthrough toggles and frame logs let a technical user see and control what the grade is doing.

**Why it matters:** the AVSForum buyer wants to A/B, inspect and tune, not accept a magic picture.

**Proof:** Auto/Manual/Off; exposure/shadow/contrast; debug passthrough; `ml_debug.csv`; delivered stats; model/tree counts.

**Buyer outcome:** the grade is explainable and reversible.

**Use it:** technical page, AVSForum, documentation.

---

## 4. Ranked shortlist

| Rank | USP | Role |
|---|---|---|
| **Primary** | **Learns the colorist, not just the curve** | The category-defining claim. Lead with it. |
| **Secondary** | Colorist intent without metadata | The hard-case proof; strong for live HDMI. |
| **Secondary** | It knows what it is looking at | The most visible, easiest to demo. |
| **Supporting** | Closed loop on delivered picture | The technical credibility layer. |
| **Supporting** | Brightness moves; colour does not | The “why it looks natural” layer. |
| **Supporting** | Free, open, yours | The trust/value closer. |
| **Supporting** | One grade for live and files | The convenience layer. |
| **Supporting** | Tunable, not opaque | The expert-audience layer. |

Lead with picture quality; close with free/open. Do not lead with “AI” as a bare adjective — lead with what the AI *does to the picture*.

---

## 5. Audience mapping

| Audience | What they care about | Lead USP | Supporting |
|---|---|---|---|
| **Projector owners** | HDR highlights, measured nits, scope screens | 1 + 3 | 4, 5 |
| **OLED/QLED owners** | Shadow detail, skin, no clipping | 1 + 3 | 5 |
| **HTPC builders** | Live HDMI + files, DeckLink, Windows | 7 | 6, 8 |
| **AVSForum technical buyers** | Mechanism, proof, tunability | 1 + 2 | 4, 5, 8 |
| **Value shoppers** | No $5k box, no subscription | 6 | 1 |
| **Dolby Vision users** | DV over HDMI, intent | 2 + 1 | 3 |

---

## 6. Homepage copy draft

**Hero**

> **The video processor that learns the colorist.**
>
> Three ML models read every scene and predict how a colorist would shape shadow, mid-tone and highlight — then a closed loop lands the result on your display. Free, open source, on the PC you already own.

**Sub-CTA**

> See the difference · Download free

**Three pillar cards**

1. **Learned, not fixed.** 1,700 trees, 88 features, every frame — trained on Dolby Vision colorist trims, not a preset curve.
2. **Scene-aware, not global.** Sky and people are segmented, so highlights and skin are protected where a global curve cannot.
3. **Open, not a black box.** GPL-3.0, source and models in the repo, no subscription, no cloud.

**Proof strip**

> 3 models · 1,700 trees · 88 features · metadata-free model inference · GPL-3.0

**Comparison section — “Why fixed curves plateau”**

| | Fixed-curve processor | Zion |
|---|---|---|
| What decides the look | One operator + metadata/peak | Learned correction from 88 frame features, per scene |
| Metadata | Often needed | Models need none; base curve may use it |
| Sky and skin | Global | Segmented protection |
| Delivery | Curve applied | Closed-loop solve on delivered bands (GT7) |
| Colour | Can drift with luminance | ICtCp I + luminance gain |
| Transparency | Closed | GPL-3.0, source and models public |

This is a category comparison, not a competitor attack. Keep competitor names off the site.

---

## 7. AVSForum technical pitch

> Most video processors apply a fixed tone curve — BT.2390, a spline, a custom operator. Zion is a learned correction layer: three XGBoost models read 88 frame features and predict how a Dolby Vision colorist shaped shadow toe, gamma and highlight roll-off for that scene. 1,700 trees, sub-millisecond CPU, metadata-free at runtime; the DV L2 intent is used offline as training labels. Sky and person segmentation protect highlights and skin. On GT7, a closed-loop controller solves the delivered p25/p50/p99 with the model as the prior. Source and shipped models are in the repo. The interesting question is not “is it AI?” but “does the delivered picture track the colorist better than a fixed curve?” That is testable.

---

## 8. Proof assets we still need

The USPs are mechanism claims; buyers will ask for evidence.

1. **A/B stills or a slider** — Zion on/off, same frame, same display target. At minimum: a bright sky, a face in mixed light, a dark interior.
2. **HDR10 vs DV vs HLG** — show that the grade holds across metadata conditions.
3. **Delivered stats** — an anonymised `CTL`/`DELIVERED` line or a simple chart showing delivered p25/p50/p99 against target.
4. **Model card** — tree counts, feature vector, training targets, corpus description, limitations.
5. **Reference-rig measurements** — RTX 4070, DeckLink Quad, 120-nit SDR target, frame rate/latency.
6. **Independent review or AVSForum thread** — third-party credibility beats self-claims.
7. **Short video** — 60 seconds: fixed curve vs Zion, sky/skin, NLS, calibration. Video is the highest-dwell content on the site.

Until the A/B asset exists, the strongest honest proof is the implementation itself: 1,700 trees, 88 features, the model files in the repo, and the logs.

---

## 9. Claims to avoid

| Avoid | Why | Say instead |
|---|---|---|
| “Reconstructs the original Dolby Vision metadata” | It infers corrections; it does not recover metadata | “Learns the colorist's correction from the image” |
| “The whole pipeline is AI” | The base tone mapper is deterministic math | “The automatic grade is learned; the base curve is not” |
| “Neural network” for the XGBoost models | They are gradient-boosted trees | “Gradient-boosted trees” or “three ML models” |
| “Trained on 150K scenes” (unqualified) | Corpus/model card not released | “Trained on Dolby Vision colorist trims; the design targets a large DV corpus” |
| “No one else has done this” | Absolute novelty is hard to defend | “Different from fixed-curve processors”; “we are not aware of a shipping consumer processor doing this” |
| “Works on any SDR source” | Native-SDR validation incomplete | “Designed for HDR; SDR path is present but still being validated” |
| “The controller runs on every curve” | It is GT7/GT7 Adapt only | “On GT7, a closed-loop controller…” |
| “The models are open source” (unqualified) | Shipped models are in the repo; training data is not | “Source and shipped models are public; training data/model cards are planned” |

---

## 10. Next actions

1. **Choose the primary USP.** Recommendation: **“Learns the colorist, not just the curve.”**
2. **Build the A/B asset.** Without it, the strongest claim is still a mechanism claim.
3. **Rewrite the homepage Zion section and hero subhead** around the primary + two secondary USPs.
4. **Publish the technical deep-dive** from `ZION_GRADE_REFERENCE.md` as an AVSForum post.
5. **Add a category comparison page** (“fixed curve vs learned correction”), no competitor names.
6. **Add audience landing pages**: projector owners, OLED/QLED owners, HTPC builders, value shoppers.
7. **Release a model card** with tree counts, features, training targets and limitations. This is the credibility multiplier.

---

*The implementation reference is authoritative for facts. This document is the marketing translation; update it when the gate conditions, model metadata or proof assets change.*
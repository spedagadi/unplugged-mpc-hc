"""
Parses an existing mpv.conf file and populates a MpvProfile as best it can.
Unrecognised keys are silently ignored — the goal is a best-effort import
so users don't start from scratch.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import MpvProfile


def _strip(line: str) -> str:
    return line.split("#")[0].strip()


def import_mpv_conf(path: Path, name: str = "") -> MpvProfile:
    p = MpvProfile(name=name or path.stem)
    text = path.read_text(encoding="utf-8", errors="replace")

    kv: dict[str, str] = {}
    for line in text.splitlines():
        line = _strip(line)
        if not line or line.startswith("["):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip()
        else:
            kv[line] = "yes"

    def get(key: str, default=None):
        return kv.get(key, default)

    def flag(key: str) -> bool:
        v = kv.get(key, "").lower()
        return v in ("yes", "true", "1", "")

    # ── HDR override vf filter ────────────────────────────────────────
    vf = get("vf", "")
    if "format=" in vf:
        p.hdr_override.force_hdr_override = True
        m = re.search(r"primaries=([^\s:]+)", vf)
        if m: p.hdr_override.primaries = m.group(1)
        m = re.search(r"gamma=([^\s:]+)", vf)
        if m: p.hdr_override.gamma = m.group(1)
        m = re.search(r"colormatrix=([^\s:]+)", vf)
        if m: p.hdr_override.color_matrix = m.group(1)
        m = re.search(r"colorlevels=([^\s:]+)", vf)
        if m: p.hdr_override.color_levels = m.group(1)

    # ── Tone mapping ──────────────────────────────────────────────────
    if v := get("tone-mapping"):             p.tone_mapping.algorithm = v
    if v := get("tone-mapping-param"):       p.tone_mapping.tone_mapping_param = v
    if "inverse-tone-mapping" in kv:         p.tone_mapping.inverse_tone_mapping = flag("inverse-tone-mapping")

    # ── Peak detection ────────────────────────────────────────────────
    if v := get("hdr-compute-peak"):         p.peak_detection.hdr_compute_peak = v
    if v := get("hdr-peak-percentile"):
        try: p.peak_detection.hdr_peak_percentile = float(v)
        except ValueError: pass
    if v := get("hdr-peak-decay-rate"):
        try: p.peak_detection.hdr_peak_decay_rate = float(v)
        except ValueError: pass
    if v := get("hdr-scene-threshold-low"):
        try: p.peak_detection.hdr_scene_threshold_low = float(v)
        except ValueError: pass
    if v := get("hdr-scene-threshold-high"):
        try: p.peak_detection.hdr_scene_threshold_high = float(v)
        except ValueError: pass
    if "allow-delayed-peak-detect" in kv:
        p.peak_detection.allow_delayed_peak_detect = flag("allow-delayed-peak-detect")

    # ── Contrast recovery ─────────────────────────────────────────────
    if v := get("hdr-contrast-recovery"):
        try: p.contrast_recovery.hdr_contrast_recovery = float(v)
        except ValueError: pass
    if v := get("hdr-contrast-smoothness"):
        try: p.contrast_recovery.hdr_contrast_smoothness = float(v)
        except ValueError: pass

    # ── Display target ────────────────────────────────────────────────
    if v := get("target-trc"):               p.display_target.target_trc = v
    if v := get("target-prim"):              p.display_target.target_prim = v
    if v := get("target-peak"):              p.display_target.target_peak = v
    if v := get("target-contrast"):          p.display_target.target_contrast = v
    if v := get("target-gamut"):             p.display_target.target_gamut = v
    if v := get("target-colorspace-hint"):   p.display_target.target_colorspace_hint = v
    if v := get("hdr-reference-white"):      p.display_target.hdr_reference_white = v

    # ── Gamut mapping ─────────────────────────────────────────────────
    if v := get("gamut-mapping-mode"):       p.gamut_mapping.mode = v

    # ── Dithering ─────────────────────────────────────────────────────
    if v := get("dither"):                   p.dithering.algorithm = v
    if v := get("dither-depth"):             p.dithering.depth = v
    if "temporal-dither" in kv:              p.dithering.temporal = flag("temporal-dither")
    if v := get("temporal-dither-period"):
        try: p.dithering.temporal_period = int(v)
        except ValueError: pass
    if v := get("dither-size-fruit"):
        try: p.dithering.fruit_size = int(v)
        except ValueError: pass
    if v := get("error-diffusion"):          p.dithering.error_diffusion = v

    # ── Deband ───────────────────────────────────────────────────────
    if "deband" in kv:                       p.deband.enabled = flag("deband")
    if v := get("deband-iterations"):
        try: p.deband.iterations = int(v)
        except ValueError: pass
    if v := get("deband-threshold"):
        try: p.deband.threshold = int(v)
        except ValueError: pass
    if v := get("deband-range"):
        try: p.deband.range = int(v)
        except ValueError: pass
    if v := get("deband-grain"):
        try: p.deband.grain = int(v)
        except ValueError: pass

    # ── ICC / LUT ─────────────────────────────────────────────────────
    if v := get("icc-profile"):              p.icc_lut.icc_profile = v
    if "icc-profile-auto" in kv:             p.icc_lut.icc_profile_auto = flag("icc-profile-auto")
    if v := get("icc-intent"):
        try: p.icc_lut.icc_intent = int(v)
        except ValueError: pass
    if v := get("lut"):                      p.icc_lut.lut_file = v
    if v := get("lut-type"):                 p.icc_lut.lut_type = v
    if v := get("image-lut"):                p.icc_lut.image_lut_file = v
    if v := get("target-lut"):               p.icc_lut.target_lut_file = v

    # ── Scaling ───────────────────────────────────────────────────────
    if v := get("scale"):                    p.scaling.scale = v
    if v := get("scale-blur"):
        try: p.scaling.scale_blur = float(v)
        except ValueError: pass
    if v := get("dscale"):                   p.scaling.dscale = v
    if v := get("cscale"):                   p.scaling.cscale = v
    if v := get("tscale"):                   p.scaling.tscale = v
    if "linear-downscaling" in kv:           p.scaling.linear_downscaling = flag("linear-downscaling")

    # ── Output ────────────────────────────────────────────────────────
    if v := get("vo"):                       p.output.vo = v
    if "fullscreen" in kv:                   p.output.fullscreen = flag("fullscreen")

    # ── Performance ───────────────────────────────────────────────────
    if "no-cache" in kv or get("cache") == "no":
        p.performance.no_cache = True
    if "no-demuxer-thread" in kv:            p.performance.no_demuxer_thread = True
    if v := get("audio-buffer"):
        try: p.performance.audio_buffer = float(v)
        except ValueError: pass

    # ── Input / device ────────────────────────────────────────────────
    if v := get("demuxer-lavf-analyzeduration"):
        try: p.input.analyze_duration = float(v)
        except ValueError: pass
    if v := get("demuxer-lavf-probesize"):
        try: p.input.probe_size = int(v)
        except ValueError: pass

    return p

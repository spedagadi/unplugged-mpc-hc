"""
Live settings engine — applies MpvProfile changes to a running MpvEngine.

All property sets go through engine.set_property() which calls libmpv
directly. No pipes, no threads, no ctypes.

LIVE    = can be applied to a running instance immediately
RESTART = requires re-initialising mpv with new args (structural changes)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .mpv_engine import MpvEngine
    from ..config.model import MpvProfile


class ApplyMode(Enum):
    LIVE    = auto()
    RESTART = auto()


@dataclass
class SettingMeta:
    label: str
    mode: ApplyMode
    apply_fn: Optional[Callable] = None


# ─────────────────────────────────────────────────────────────────────
# Apply functions — each sets all props for one logical group
# ─────────────────────────────────────────────────────────────────────

def _sp(engine, name, value):
    engine.set_property(name, value)


def _apply_tone_mapping(engine, p):
    _sp(engine, "tone-mapping", p.tone_mapping.algorithm)
    if p.tone_mapping.tone_mapping_param != "default":
        try:
            _sp(engine, "tone-mapping-param", float(p.tone_mapping.tone_mapping_param))
        except ValueError:
            pass
    _sp(engine, "tone-mapping-max-boost", p.tone_mapping.tone_mapping_max_boost)
    _sp(engine, "inverse-tone-mapping", p.tone_mapping.inverse_tone_mapping)
    _sp(engine, "tone-mapping-visualize", p.tone_mapping.tone_mapping_visualize)


def _apply_peak_detection(engine, p):
    _sp(engine, "hdr-compute-peak", p.peak_detection.hdr_compute_peak)
    _sp(engine, "hdr-peak-percentile", p.peak_detection.hdr_peak_percentile)
    _sp(engine, "hdr-peak-decay-rate", p.peak_detection.hdr_peak_decay_rate)
    _sp(engine, "hdr-scene-threshold-low", p.peak_detection.hdr_scene_threshold_low)
    _sp(engine, "hdr-scene-threshold-high", p.peak_detection.hdr_scene_threshold_high)
    _sp(engine, "allow-delayed-peak-detect", p.peak_detection.allow_delayed_peak_detect)


def _apply_contrast_recovery(engine, p):
    # Zion Core owns contrast recovery only when both enabled AND the model path is set
    # (model path empty = no ML context will load, so libplacebo CR must stay active)
    zion_active = p.zion_core.enabled
    recovery = 0.0 if zion_active else p.contrast_recovery.hdr_contrast_recovery
    _sp(engine, "hdr-contrast-recovery", recovery)
    _sp(engine, "hdr-contrast-smoothness", p.contrast_recovery.hdr_contrast_smoothness)


def _apply_display_target(engine, p):
    _sp(engine, "target-trc", p.display_target.target_trc)
    _sp(engine, "target-prim", p.display_target.target_prim)
    try:
        val = p.display_target.target_peak
        _sp(engine, "target-peak", int(float(val)) if val != "auto" else "auto")
    except (ValueError, TypeError):
        pass
    _contrast = p.display_target.target_contrast
    try:
        if _contrast and _contrast not in ("auto", "inf", ""):
            _contrast = int(float(_contrast))
    except (ValueError, TypeError):
        _contrast = "auto"
    _sp(engine, "target-contrast", _contrast)
    if p.display_target.target_gamut:
        _sp(engine, "target-gamut", p.display_target.target_gamut)
    _sp(engine, "target-colorspace-hint", p.display_target.target_colorspace_hint)
    _ref = p.display_target.hdr_reference_white
    try:
        if _ref and _ref not in ("auto", ""):
            _ref = int(float(_ref))
    except (ValueError, TypeError):
        _ref = "auto"
    _sp(engine, "hdr-reference-white", _ref)
    # Re-send hdr-compute-peak to force libplacebo to recompile the tone
    # mapping shader and pick up the new target-peak value immediately.
    _sp(engine, "hdr-compute-peak", p.peak_detection.hdr_compute_peak)


def _apply_gamut_mapping(engine, p):
    _sp(engine, "gamut-mapping-mode", p.gamut_mapping.mode)
    gm = p.gamut_mapping
    lp = (f"perceptual_deadzone={gm.perceptual_deadzone}"
          f",perceptual_strength={gm.perceptual_strength}"
          f",colorimetric_gamma={gm.colorimetric_gamma}"
          f",softclip_knee={gm.softclip_knee}"
          f",softclip_desat={gm.softclip_desat}"
          f",lut3d_size_I={gm.lut3d_size_I}"
          f",lut3d_size_C={gm.lut3d_size_C}"
          f",lut3d_size_h={gm.lut3d_size_h}"
          f",lut3d_tricubic={'yes' if gm.lut3d_tricubic else 'no'}"
          f",gamut_expansion={'yes' if gm.gamut_expansion else 'no'}")
    engine.apply_libplacebo_opts(lp)


def _apply_dithering(engine, p):
    _sp(engine, "dither", p.dithering.algorithm)
    _sp(engine, "dither-depth", p.dithering.depth)
    _sp(engine, "temporal-dither", p.dithering.temporal)
    _sp(engine, "temporal-dither-period", p.dithering.temporal_period)
    if p.dithering.algorithm == "fruit":
        _sp(engine, "dither-size-fruit", p.dithering.fruit_size)
    elif p.dithering.algorithm == "error-diffusion":
        _sp(engine, "error-diffusion", p.dithering.error_diffusion)


def _apply_deband(engine, p):
    _sp(engine, "deband", p.deband.enabled)
    _sp(engine, "deband-iterations", p.deband.iterations)
    _sp(engine, "deband-threshold", p.deband.threshold)
    _sp(engine, "deband-range", p.deband.range)
    _sp(engine, "deband-grain", p.deband.grain)


def _apply_icc_lut(engine, p):
    il = p.icc_lut
    if il.icc_profile:
        _sp(engine, "icc-profile", il.icc_profile)
    if il.icc_profile_auto:
        _sp(engine, "icc-profile-auto", il.icc_profile_auto)
    _sp(engine, "use-embedded-icc-profile", il.use_embedded_icc_profile)
    _sp(engine, "icc-intent", il.icc_intent)
    _sp(engine, "icc-force-contrast", il.icc_force_contrast)
    _sp(engine, "icc-cache", il.icc_cache)
    if il.lut_file:
        _sp(engine, "lut", il.lut_file)
        _sp(engine, "lut-type", il.lut_type)
    if il.image_lut_file:
        _sp(engine, "image-lut", il.image_lut_file)
        _sp(engine, "image-lut-type", il.image_lut_type)
    if il.target_lut_file:
        _sp(engine, "target-lut", il.target_lut_file)


def _apply_scaling(engine, p):
    _sp(engine, "scale", p.scaling.scale)
    _sp(engine, "dscale", p.scaling.dscale)
    _sp(engine, "cscale", p.scaling.cscale)
    _sp(engine, "tscale", p.scaling.tscale)
    _sp(engine, "scale-blur", p.scaling.scale_blur)
    _sp(engine, "linear-downscaling", p.scaling.linear_downscaling)


def _apply_shaders(engine, p):
    paths = p.shaders.enabled_paths()
    engine.set_property("glsl-shaders", paths)


def _apply_fullscreen(engine, p):
    _sp(engine, "fullscreen", p.output.fullscreen)


def _apply_picture(engine, p):
    _sp(engine, "brightness", p.picture.brightness)
    _sp(engine, "contrast",   p.picture.contrast)
    _sp(engine, "saturation", p.picture.saturation)
    _sp(engine, "hue",        p.picture.hue)
    # Zion Core / The Oracle owns gamma — zero VO gamma to prevent double correction
    zion_active = p.zion_core.enabled
    _sp(engine, "gamma", 0 if zion_active else p.picture.gamma)
    _sp(engine, "sharpen",    p.picture.sharpen)


def _apply_geometry(engine, p):
    _sp(engine, "video-zoom",             p.geometry.video_zoom)
    _sp(engine, "video-pan-x",            p.geometry.video_pan_x)
    _sp(engine, "video-pan-y",            p.geometry.video_pan_y)
    _sp(engine, "video-rotate",           p.geometry.video_rotate)
    if p.geometry.video_aspect_override:
        _sp(engine, "video-aspect-override", p.geometry.video_aspect_override)
    else:
        _sp(engine, "video-aspect-override", "-1")


def _apply_zion_core_params(engine, p):
    """Apply full Zion Core state live. Model is always loaded at startup (CPU RAM only)
    so the enabled toggle just flips modes — no restart needed."""
    zc = p.zion_core
    if not zc.enabled:
        # Turn all ML processing off — model stays resident, zero cost
        _sp(engine, "ml-gamma",     "off")
        _sp(engine, "ml-cr",        "off")
        _sp(engine, "ml-fire-pop",  "off")
        _sp(engine, "ml-radiance",  "off")
        _sp(engine, "ml-chroma",    "off")
        _sp(engine, "ml-shadow",    "off")
        _sp(engine, "ml-highlight", "off")
        _sp(engine, "ml-emulate-sdr", "off")
        # Restore libplacebo CR and VO gamma now that ML is bypassed
        _apply_contrast_recovery(engine, p)
        _apply_picture(engine, p)
        return
    # Oracle
    _sp(engine, "ml-gamma", "auto" if zc.oracle.auto else "manual")
    if not zc.oracle.auto:
        _sp(engine, "ml-gamma-value", zc.oracle.value)
    # Construct CR
    _sp(engine, "ml-cr", "auto" if zc.construct_cr.auto else "manual")
    if not zc.construct_cr.auto:
        _sp(engine, "ml-cr-strength", zc.construct_cr.value)
    # Fire pop — always off
    _sp(engine, "ml-fire-pop", "off")
    # Resonance
    _sp(engine, "ml-radiance", "auto" if zc.resonance.auto else "manual")
    if not zc.resonance.auto:
        _sp(engine, "ml-radiance-knee",     zc.resonance.knee)
        _sp(engine, "ml-radiance-strength", zc.resonance.strength)
    # Spectrum Shift — always manual
    ss = zc.spectrum_shift
    _sp(engine, "ml-chroma",         "manual")
    _sp(engine, "ml-chroma-neutral", ss.neutral_boost)
    _sp(engine, "ml-chroma-fire",    ss.fire_boost)
    _sp(engine, "ml-chroma-knee",    ss.knee)
    _sp(engine, "ml-chroma-skin",    ss.skin_protect)
    # Shadow bilateral
    _sp(engine, "ml-shadow", zc.shadow.mode)
    if zc.shadow.mode == "manual":
        _sp(engine, "ml-shadow-strength", zc.shadow.strength)
    # Highlight bilateral
    _sp(engine, "ml-highlight", zc.highlight.mode)
    if zc.highlight.mode == "manual":
        _sp(engine, "ml-highlight-strength", zc.highlight.strength)
    # SDR→P5 virtual-master bridge (Phase C) — live-toggleable
    _sp(engine, "ml-emulate-sdr", "yes" if zc.emulate_sdr else "no")
    if zc.emulate_sdr:
        _sp(engine, "ml-sdr-virtual-nits", zc.sdr_virtual_nits)
        _sp(engine, "ml-sdr-strength",     zc.sdr_strength)
    # Enforce conflicting VO settings = neutral while Zion Core is active
    _sp(engine, "hdr-contrast-recovery", 0.0)   # Construct CR owns this
    _sp(engine, "gamma", 0)                       # The Oracle owns gamma


# ─────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────

SETTING_GROUPS: dict[str, SettingMeta] = {
    "tone_mapping":      SettingMeta("Tone Mapping",           ApplyMode.LIVE,    _apply_tone_mapping),
    "peak_detection":    SettingMeta("Peak Detection",         ApplyMode.LIVE,    _apply_peak_detection),
    "contrast_recovery": SettingMeta("HDR Contrast Recovery",  ApplyMode.LIVE,    _apply_contrast_recovery),
    "display_target":    SettingMeta("Display Target",         ApplyMode.LIVE,    _apply_display_target),
    "gamut_mapping":     SettingMeta("Gamut Mapping",          ApplyMode.LIVE,    _apply_gamut_mapping),
    "dithering":         SettingMeta("Dithering",              ApplyMode.LIVE,    _apply_dithering),
    "deband":            SettingMeta("Debanding",              ApplyMode.LIVE,    _apply_deband),
    "icc_lut":           SettingMeta("ICC / LUT",              ApplyMode.LIVE,    _apply_icc_lut),
    "scaling":           SettingMeta("Scaling",                ApplyMode.LIVE,    _apply_scaling),
    "shaders":           SettingMeta("GLSL Shaders",           ApplyMode.LIVE,    _apply_shaders),
    "fullscreen":        SettingMeta("Fullscreen",             ApplyMode.LIVE,    _apply_fullscreen),
    "picture":           SettingMeta("Picture",                ApplyMode.LIVE,    _apply_picture),
    "geometry":          SettingMeta("Geometry",               ApplyMode.LIVE,    _apply_geometry),
    "zion_core":         SettingMeta("Zion Core",              ApplyMode.LIVE,    _apply_zion_core_params),
    # Restart-required groups (no apply_fn needed)
    "hdr_override":      SettingMeta("HDR vf Override",        ApplyMode.RESTART, None),
    "input":             SettingMeta("Input Device",           ApplyMode.RESTART, None),
    "output_vo":         SettingMeta("Video Output (vo)",      ApplyMode.RESTART, None),
    "performance":       SettingMeta("Performance / Capture",  ApplyMode.RESTART, None),
    "wallpaper":         SettingMeta("Background",             ApplyMode.RESTART, None),
}


def apply_live_change(group_key: str, engine: "MpvEngine", profile: "MpvProfile") -> bool:
    """
    Apply a setting group to the running engine.
    Returns True if applied live, False if restart is required.
    """
    meta = SETTING_GROUPS.get(group_key)
    if meta is None or meta.mode == ApplyMode.RESTART or meta.apply_fn is None:
        return False
    if not engine.is_playing():
        return False
    try:
        meta.apply_fn(engine, profile)
    except Exception as e:
        import logging
        logging.getLogger("videoforge.engine").warning(
            f"apply_live_change({group_key}) failed: {e}"
        )
    return True


def sync_all_live(engine: "MpvEngine", profile: "MpvProfile") -> None:
    """Push all LIVE groups to the engine at once (called on file load)."""
    if not engine.is_playing():
        return
    for meta in SETTING_GROUPS.values():
        if meta.mode == ApplyMode.LIVE and meta.apply_fn:
            try:
                meta.apply_fn(engine, profile)
            except Exception:
                pass

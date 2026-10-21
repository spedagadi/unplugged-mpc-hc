"""
Profile manager — loads, saves, and lists named MpvProfile JSON files.

Built-in presets follow community best practice (libplacebo "high quality"
preset values + home theater forum consensus).
"""

from __future__ import annotations

from pathlib import Path

from ..config.model import MpvProfile


# Bump this when any built-in profile changes — forces regeneration on next launch
_BUILTIN_VERSION = "2"

_BUILTIN_PROFILE_NAMES = (
    "Default",
    "Projector-HDR10",
    "Projector-HDR10+",
    "Monitor-Desktop",
)


def _builtin_default() -> MpvProfile:
    """
    Default HTPC profile — matches the community-standard mpv config:
    hdr-compute-peak=yes + target-peak=50 for a projector in a dark room.
    target-peak is the display ceiling; compute-peak shapes the tone curve.
    """
    p = MpvProfile(name="Default")

    # HDR override — force BT.2020/PQ metadata for live capture
    p.hdr_override.force_hdr_override = True
    p.hdr_override.color_levels = "limited"
    p.hdr_override.primaries = "bt.2020"
    p.hdr_override.gamma = "pq"
    p.hdr_override.color_matrix = "bt.2020-ncl"
    p.hdr_override.chroma_location = "mpeg2/4/h264"

    # Tone mapping
    p.tone_mapping.algorithm = "spline"
    p.tone_mapping.tone_mapping_param = "default"
    p.tone_mapping.inverse_tone_mapping = False

    # Peak detection
    p.peak_detection.hdr_compute_peak = "yes"
    p.peak_detection.hdr_peak_percentile = 99.995
    p.peak_detection.hdr_peak_decay_rate = 20.0
    p.peak_detection.hdr_scene_threshold_low = 1.0
    p.peak_detection.hdr_scene_threshold_high = 3.0
    p.peak_detection.allow_delayed_peak_detect = False

    # Contrast recovery
    p.contrast_recovery.hdr_contrast_recovery = 0.5
    p.contrast_recovery.hdr_contrast_smoothness = 3.5

    # Display target — 50 nits for a projector in a dark room
    p.display_target.target_peak = "50"
    p.display_target.target_trc = "bt.1886"
    p.display_target.target_prim = "bt.2020"
    p.display_target.target_contrast = "auto"
    p.display_target.target_gamut = ""
    p.display_target.target_colorspace_hint = "auto"

    # Gamut mapping
    p.gamut_mapping.mode = "perceptual"

    # Dithering
    p.dithering.algorithm = "fruit"
    p.dithering.depth = "auto"
    p.dithering.temporal = True

    # Debanding — disabled by default; built-in --deband is GPU-heavy and
    # contributes to demuxer packet backlog on uncompressed 4K capture
    # (matches the proven low-latency reference command). Use a hdeband
    # GLSL shader instead if banding reduction is needed.
    p.deband.enabled = False
    p.deband.iterations = 4
    p.deband.threshold = 48
    p.deband.range = 24
    p.deband.grain = 16

    # Scaling
    p.scaling.scale = "spline36"
    p.scaling.scale_blur = 0.981251
    p.scaling.dscale = "spline36"
    p.scaling.linear_downscaling = False
    p.scaling.cscale = "spline36"
    p.scaling.tscale = "oversample"

    # Output
    p.output.vo = "gpu-next"
    p.output.fullscreen = True

    # Performance / capture
    p.performance.no_cache = True
    # Keep the demuxer on its own thread — disabling it (--no-demuxer-thread)
    # starves packet reads whenever the render thread is busy, causing the
    # "Too many packets in the demuxer packet queues" backlog/stall seen with
    # uncompressed 4K capture (matches the proven low-latency reference,
    # which omits this flag).
    p.performance.no_demuxer_thread = False
    p.performance.audio_buffer = 0.0

    return p


def _builtin_projector_hdr10() -> MpvProfile:
    """
    SDR projector / display — HDR10 content.
    compute-peak=no so target-peak directly controls the tone curve.
    Set target-peak to your projector's measured peak white in nits.
    """
    p = MpvProfile(name="Projector-HDR10")
    p.peak_detection.hdr_compute_peak = "no"   # manual control via target-peak
    p.peak_detection.hdr_peak_percentile = 99.995
    p.contrast_recovery.hdr_contrast_recovery = 0.30
    p.display_target.target_peak = "203"        # change to your projector's nits
    p.display_target.target_trc = "bt.1886"
    p.display_target.target_prim = "bt.2020"
    p.gamut_mapping.mode = "perceptual"
    p.tone_mapping.algorithm = "spline"
    return p


def _builtin_projector_hdr10plus() -> MpvProfile:
    """
    HDR10+ content — has per-scene dynamic metadata.
    compute-peak=no: the dynamic metadata is more accurate than frame analysis.
    tone-mapping=st2094-40: uses the HDR10+ per-scene tone curve directly.
    """
    p = MpvProfile(name="Projector-HDR10+")
    p.peak_detection.hdr_compute_peak = "no"
    p.peak_detection.hdr_peak_percentile = 99.995
    p.contrast_recovery.hdr_contrast_recovery = 0.30
    p.display_target.target_peak = "203"
    p.display_target.target_trc = "bt.1886"
    p.display_target.target_prim = "bt.2020"
    p.gamut_mapping.mode = "perceptual"
    p.tone_mapping.algorithm = "st2094-40"      # uses HDR10+ dynamic metadata
    return p


def _builtin_monitor() -> MpvProfile:
    """SDR monitor — sRGB output, softclip gamut mapping."""
    p = MpvProfile(name="Monitor-Desktop")
    p.peak_detection.hdr_compute_peak = "yes"
    p.peak_detection.hdr_peak_percentile = 99.995
    p.contrast_recovery.hdr_contrast_recovery = 0.30
    p.display_target.target_peak = "200"
    p.display_target.target_trc = "srgb"
    p.display_target.target_prim = "bt.709"
    p.gamut_mapping.mode = "softclip"
    p.tone_mapping.algorithm = "spline"
    p.output.fullscreen = False
    return p


_BUILTINS: dict[str, MpvProfile] = {
    "Default":           _builtin_default(),
    "Projector-HDR10":   _builtin_projector_hdr10(),
    "Projector-HDR10+":  _builtin_projector_hdr10plus(),
    "Monitor-Desktop":   _builtin_monitor(),
}


class ProfileManager:
    def __init__(self, profiles_dir: Path) -> None:
        self._dir = profiles_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ensure_builtins()

    def list_profiles(self) -> list[str]:
        names = []
        for name in _BUILTIN_PROFILE_NAMES:
            if self._path_for(name).exists():
                names.append(name)
        for f in sorted(self._dir.glob("*.json")):
            name = f.stem
            if name not in names:
                names.append(name)
        return names

    def load(self, name: str) -> MpvProfile:
        path = self._path_for(name)
        if path.exists():
            return MpvProfile.load(path)
        if name in _BUILTINS:
            return _BUILTINS[name]
        raise FileNotFoundError(f"Profile not found: {name}")

    def save(self, profile: MpvProfile) -> None:
        profile.save(self._path_for(profile.name))

    def delete(self, name: str) -> None:
        if name in _BUILTIN_PROFILE_NAMES:
            raise ValueError(f"Cannot delete built-in profile: {name}")
        path = self._path_for(name)
        if path.exists():
            path.unlink()

    def rename(self, old_name: str, new_name: str) -> MpvProfile:
        if old_name in _BUILTIN_PROFILE_NAMES:
            raise ValueError(f"Cannot rename built-in profile: {old_name}")
        profile = self.load(old_name)
        profile.name = new_name
        self.save(profile)
        self.delete(old_name)
        return profile

    def duplicate(self, source_name: str, new_name: str) -> MpvProfile:
        profile = self.load(source_name)
        profile.name = new_name
        self.save(profile)
        return profile

    def exists(self, name: str) -> bool:
        return self._path_for(name).exists()

    def _path_for(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
        return self._dir / f"{safe}.json"

    def _ensure_builtins(self) -> None:
        version_file = self._dir / ".builtin_version"
        current = version_file.read_text().strip() if version_file.exists() else ""
        if current != _BUILTIN_VERSION:
            # Built-in definitions changed — regenerate all built-in profiles
            for name in _BUILTIN_PROFILE_NAMES:
                path = self._path_for(name)
                if path.exists():
                    path.unlink()
            version_file.write_text(_BUILTIN_VERSION)
        for name, profile in _BUILTINS.items():
            path = self._path_for(name)
            if not path.exists():
                profile.save(path)

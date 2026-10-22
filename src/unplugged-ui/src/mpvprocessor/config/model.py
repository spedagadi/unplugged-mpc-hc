"""
Configuration data model. Each dataclass maps 1:1 to a group of mpv options.
Serialized to/from JSON for profile persistence; converted to mpv args by serializer.py.
All options target --vo=gpu-next (libplacebo) unless noted.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _default_mpv_executable() -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'mpv.exe')
    # Dev: look next to this file's repo structure, then fall back to a known path
    repo_candidate = Path(__file__).parents[4] / 'mpv' / 'dist' / 'mpv.exe'
    if repo_candidate.exists():
        return str(repo_candidate)
    return r"C:\Code\mpv\dist\mpv.exe"


@dataclass
class InputConfig:
    device: str = "decklink://DeckLink Quad HDMI Recorder"
    # Capture params = the exact set proven-working with the direct mpv test
    # on the HTPC (Unplugged _internal mpv): analyzeduration=0, rtbufsize=32M.
    # Earlier defaults (0.5 / 2G) added probe/ring buffering; this is lower-latency.
    rtbuf_size: str = "32M"
    analyze_duration: float = 0.0
    probe_size: int = 42


@dataclass
class HdrOverrideConfig:
    # Forced until the capture chain can auto-detect HDR vs SDR.
    force_hdr_override: bool = True
    color_levels: str = "limited"
    primaries: str = "bt.2020"
    gamma: str = "pq"
    color_matrix: str = "bt.2020-ncl"
    chroma_location: str = "mpeg2/4/h264"


@dataclass
class ToneMappingConfig:
    # Core algorithm
    algorithm: str = "spline"
    # Per-algorithm tuning param; "default" means let mpv choose
    tone_mapping_param: str = "default"
    # Max brightness boost factor (1.0 = no boost, community standard)
    tone_mapping_max_boost: float = 1.0
    # SDR→HDR inverse tone mapping (gpu-next only)
    inverse_tone_mapping: bool = False
    # Overlay LUT graph for debugging (gpu-next only)
    tone_mapping_visualize: bool = False


@dataclass
class PeakDetectionConfig:
    # auto | yes | no
    # "yes" = mpv measures per-frame (best for HDR10 without dynamic metadata)
    # "no"  = use target-peak directly (required to see target-peak changes)
    hdr_compute_peak: str = "yes"
    # 99.995 = libplacebo "high quality" preset — avoids specular highlight clipping
    hdr_peak_percentile: float = 99.995
    hdr_peak_decay_rate: float = 20.0
    hdr_scene_threshold_low: float = 1.0
    hdr_scene_threshold_high: float = 3.0
    allow_delayed_peak_detect: bool = False


@dataclass
class ContrastRecoveryConfig:
    hdr_contrast_recovery: float = 0.30
    hdr_contrast_smoothness: float = 3.5


@dataclass
class DisplayTargetConfig:
    target_trc: str = "gamma2.2"
    target_prim: str = "bt.2020"
    # 203 = PQ code for 100% SDR reference white — calibrated default
    # Measure your projector/display and set the actual peak nits here
    target_peak: str = "203"
    # contrast ratio or "auto" or "inf" (OLED)
    target_contrast: str = "auto"
    # constrain output gamut; same values as target_prim or empty for none
    target_gamut: str = ""
    # HDR passthrough hint (auto | yes | no)
    target_colorspace_hint: str = "auto"
    # SDR diffuse white in nits (auto | 10-10000)
    hdr_reference_white: str = "auto"


@dataclass
class GamutMappingConfig:
    mode: str = "perceptual"
    # libplacebo perceptual params
    perceptual_deadzone: float = 0.30
    perceptual_strength: float = 0.80
    colorimetric_gamma: float = 1.80
    softclip_knee: float = 0.70
    softclip_desat: float = 0.35
    lut3d_size_I: int = 48
    lut3d_size_C: int = 32
    lut3d_size_h: int = 256
    lut3d_tricubic: bool = False
    gamut_expansion: bool = False


@dataclass
class DitheringConfig:
    # fruit | ordered | error-diffusion | no
    algorithm: str = "fruit"
    # bit depth or "auto" or "no"
    depth: str = "auto"
    temporal: bool = True
    temporal_period: int = 1
    # matrix size exponent for fruit (2-8)
    fruit_size: int = 6
    # error-diffusion kernel
    error_diffusion: str = "sierra-lite"


@dataclass
class DebandConfig:
    enabled: bool = False
    iterations: int = 1
    threshold: int = 48
    range: int = 16
    grain: int = 32


@dataclass
class IccLutConfig:
    icc_profile: str = ""
    icc_profile_auto: bool = False
    use_embedded_icc_profile: bool = True
    # 0=perceptual 1=relative-colorimetric 2=saturation 3=absolute-colorimetric
    icc_intent: int = 1
    icc_force_contrast: str = "no"
    icc_cache: bool = True
    # Adobe .cube LUT applied during color conversion
    lut_file: str = ""
    # auto | native | normalized | conversion
    lut_type: str = "auto"
    # LUT applied during image decoding
    image_lut_file: str = ""
    image_lut_type: str = "auto"
    # Adobe .cube LUT applied after target-trc encoding
    target_lut_file: str = ""


@dataclass
class ShaderEntry:
    """One discovered shader file and its enabled state."""
    path: str = ""
    enabled: bool = False


@dataclass
class ShaderConfig:
    # Folder scanned for .glsl shader files
    shader_dir: str = ""
    # Ordered list of discovered shaders (path + enabled)
    shaders: list = field(default_factory=list)

    def enabled_paths(self) -> list[str]:
        return [s["path"] for s in self.shaders if s.get("enabled")]


@dataclass
class ScalingConfig:
    scale: str = "spline36"
    scale_blur: float = 0.0
    dscale: str = "mitchell"
    linear_downscaling: bool = True
    cscale: str = "spline36"
    tscale: str = "oversample"


@dataclass
class OutputConfig:
    vo: str = "gpu-next"
    fullscreen: bool = True


@dataclass
class PerformanceConfig:
    no_cache: bool = True
    no_demuxer_thread: bool = True
    audio_buffer: float = 0.0
    # Video latency hack (mpv --video-latency-hacks) — drops ~40ms off the
    # DeckLink staging FIFO (measured steady total 125 → 83ms @ 4K24) but was
    # the jitter suspect 45cc321 removed. On by default; disable via the
    # Performance panel if capture jitter shows up.
    video_latency_hacks: bool = True
    # VP drop-until-live acquisition ceiling (--ml-acq-cutover, ms). During
    # capture start, frames whose ingest→present age exceeds this are dropped
    # upstream so the first visible frame is already live (≈ N/1000 s of video
    # ahead of the AVR delay). 0 = disabled. Default 125 ≈ 3 frames @ 24p.
    ml_acq_cutover_ms: int = 125


@dataclass
class PictureConfig:
    # VO equalizer — all 0 = neutral, range -100..100
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    hue: int = 0
    gamma: int = 0
    # libplacebo sharpen — 0.0 = off, positive = sharpen, negative = blur
    sharpen: float = 0.0


@dataclass
class GeometryConfig:
    # Digital zoom — 0.0 = fit window; positive = zoom in
    video_zoom: float = 0.0
    # Pan offset after zoom — 0.0 = centred
    video_pan_x: float = 0.0
    video_pan_y: float = 0.0
    # Aspect ratio override — "" = auto
    video_aspect_override: str = ""
    # Rotation — 0 / 90 / 180 / 270
    video_rotate: int = 0


def _libplacebo_repo() -> Path:
    """Sibling libplacebo source repo (dev tree): .../unplugged/../libplacebo."""
    return Path(__file__).resolve().parents[4].parent / "libplacebo"


def _default_ml_model() -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'xgb_gamma_model.plxgb')
    candidate = _libplacebo_repo() / 'ml' / 'models' / 'xgb_gamma_model.plxgb'
    return str(candidate) if candidate.exists() else ""


def _default_shadow_model() -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'xgb_shadow_recovery.plxgb')
    candidate = _libplacebo_repo() / 'ml' / 'models' / 'xgb_shadow_recovery.plxgb'
    return str(candidate) if candidate.exists() else ""


def _resolve_model_path(stored: str, default: str) -> str:
    """Return the model path the app should actually use.

    ML model files ship relative to the app bundle (sys._MEIPASS when frozen,
    or the repo tree in dev). A stored profile can carry an absolute path from
    another install (e.g. a previous HTPC deploy dir) that does not exist on
    this machine — such stale absolute paths must never win over the bundled
    copy. Frozen builds always resolve relative to the bundle; otherwise keep
    a path only when it actually exists.
    """
    if not stored:
        return default
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / Path(stored).name)
    if Path(stored).exists():
        return stored
    return default


@dataclass
class MlParamMode:
    auto:  bool  = True
    value: float = 0.0


@dataclass
class ResonanceConfig:
    auto:     bool  = True
    knee:     float = 0.6    # 0.4 – 0.9  — where boost starts
    strength: float = 0.30   # 0.0 – 0.6  — boost intensity
    shoulder: float = 0.82   # 0.7 – 0.99 — where boost fades out (prevents fire/face glare)


@dataclass
class SpectrumShiftConfig:
    neutral_boost: float = 1.20   # 1.0 – 1.5
    fire_boost:    float = 1.35   # 1.0 – 1.5
    knee:          float = 0.55   # 0.1 – 0.9
    skin_protect:  float = 0.95   # 0.5 – 1.0


@dataclass
class ShadowBilateralConfig:
    mode:       str   = "auto"  # "off" | "auto" | "manual"
    strength:   float = 0.20    # [0.0, 0.5] bilateral blend in shadow zones
    model_path: str   = field(default_factory=_default_shadow_model)


@dataclass
class HighlightBilateralConfig:
    mode:       str   = "auto"  # "off" | "auto" | "manual"
    strength:   float = 0.15    # [0.0, 0.4] bilateral blend in highlight zones
    model_path: str   = ""      # XGBoost model path (empty = use heuristic)


@dataclass
class ZionCoreConfig:
    enabled:          bool                    = False
    ml_model_path:    str                     = field(default_factory=_default_ml_model)
    oracle:           MlParamMode             = field(default_factory=lambda: MlParamMode(auto=True, value=1.0))
    construct_cr:     MlParamMode             = field(default_factory=lambda: MlParamMode(auto=True, value=0.30))
    resonance:        ResonanceConfig         = field(default_factory=ResonanceConfig)
    spectrum_shift:   SpectrumShiftConfig     = field(default_factory=SpectrumShiftConfig)
    shadow:           ShadowBilateralConfig   = field(default_factory=ShadowBilateralConfig)
    highlight:        HighlightBilateralConfig = field(default_factory=HighlightBilateralConfig)
    # SDR→P5 virtual-master bridge (Phase C): elevate SDR sources to a virtual
    # DV-mastered HDR signal before the ML grade. sdr_virtual_nits is the
    # virtual P5 ceiling (SDR white maps to it after linear-gain expansion).
    emulate_sdr:      bool  = False
    sdr_virtual_nits: float = 1000.0
    sdr_strength:     float = 0.5     # shaped mid-lift (0=linear gain, 1=strong lift)
    # Temporal stability controls
    iir_alpha:        float = 0.10   # base blending weight (adaptive engine scales this down on stable shots)
    gamma_max_delta:  float = 0.02   # XGBoost deadband: predictions within this range are suppressed
    iir_slow_alpha:   float = 0.05   # slow EMA alpha for scene-cut baseline (~20-frame window)


@dataclass
class MpvProfile:
    """A named, saveable set of mpv settings."""
    name: str = "Default"
    input: InputConfig = field(default_factory=InputConfig)
    hdr_override: HdrOverrideConfig = field(default_factory=HdrOverrideConfig)
    tone_mapping: ToneMappingConfig = field(default_factory=ToneMappingConfig)
    peak_detection: PeakDetectionConfig = field(default_factory=PeakDetectionConfig)
    contrast_recovery: ContrastRecoveryConfig = field(default_factory=ContrastRecoveryConfig)
    display_target: DisplayTargetConfig = field(default_factory=DisplayTargetConfig)
    gamut_mapping: GamutMappingConfig = field(default_factory=GamutMappingConfig)
    dithering: DitheringConfig = field(default_factory=DitheringConfig)
    deband: DebandConfig = field(default_factory=DebandConfig)
    icc_lut: IccLutConfig = field(default_factory=IccLutConfig)
    shaders: ShaderConfig = field(default_factory=ShaderConfig)
    scaling: ScalingConfig = field(default_factory=ScalingConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    picture: PictureConfig = field(default_factory=PictureConfig)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    zion_core: ZionCoreConfig = field(default_factory=ZionCoreConfig)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> MpvProfile:
        data = json.loads(text)
        def _load(klass, key):
            raw = data.get(key, {})
            valid = {k: v for k, v in raw.items() if k in klass.__dataclass_fields__}
            return klass(**valid)
        # ShaderConfig.shaders is a plain list, not nested dataclasses
        shader_raw = data.get("shaders", {})
        shader_cfg = ShaderConfig(
            shader_dir=shader_raw.get("shader_dir", ""),
            shaders=shader_raw.get("shaders", []),
        )
        # ZionCoreConfig has nested dataclasses — load each level explicitly
        def _load_zion_core(raw: dict) -> ZionCoreConfig:
            def _mp(d: dict, default_value: float) -> MlParamMode:
                return MlParamMode(
                    auto=d.get("auto", True),
                    value=d.get("value", default_value),
                )
            def _res(d: dict) -> ResonanceConfig:
                return ResonanceConfig(
                    auto=d.get("auto", True),
                    knee=d.get("knee", 0.6),
                    strength=d.get("strength", 0.30),
                    shoulder=float(d.get("shoulder", 0.82)),
                )
            def _ss(d: dict) -> SpectrumShiftConfig:
                return SpectrumShiftConfig(
                    neutral_boost=d.get("neutral_boost", 1.20),
                    fire_boost=d.get("fire_boost", 1.35),
                    knee=d.get("knee", 0.55),
                    skin_protect=d.get("skin_protect", 0.95),
                )
            def _shad(d: dict) -> ShadowBilateralConfig:
                return ShadowBilateralConfig(
                    mode=d.get("mode", "auto"),
                    strength=float(d.get("strength", 0.20)),
                    model_path=_resolve_model_path(
                        d.get("model_path", ""), _default_shadow_model()),
                )
            def _hi(d: dict) -> HighlightBilateralConfig:
                return HighlightBilateralConfig(
                    mode=d.get("mode", "auto"),
                    strength=float(d.get("strength", 0.15)),
                    model_path=_resolve_model_path(d.get("model_path", ""), ""),
                )
            ml_path = _resolve_model_path(
                raw.get("ml_model_path", ""), _default_ml_model())
            return ZionCoreConfig(
                enabled=raw.get("enabled", False),
                ml_model_path=ml_path,
                oracle=_mp(raw.get("oracle", {}), 1.0),
                construct_cr=_mp(raw.get("construct_cr", {}), 0.30),
                resonance=_res(raw.get("resonance", {})),
                spectrum_shift=_ss(raw.get("spectrum_shift", {})),
                shadow=_shad(raw.get("shadow", {})),
                highlight=_hi(raw.get("highlight", {})),
                emulate_sdr=bool(raw.get("emulate_sdr", False)),
                sdr_virtual_nits=float(raw.get("sdr_virtual_nits", 1000.0)),
                sdr_strength=float(raw.get("sdr_strength", 0.5)),
                iir_alpha=float(raw.get("iir_alpha", 0.10)),
                gamma_max_delta=float(raw.get("gamma_max_delta", 0.02)),
                iir_slow_alpha=float(raw.get("iir_slow_alpha", 0.05)),
            )
        return cls(
            name=data.get("name", "Default"),
            input=_load(InputConfig, "input"),
            hdr_override=_load(HdrOverrideConfig, "hdr_override"),
            tone_mapping=_load(ToneMappingConfig, "tone_mapping"),
            peak_detection=_load(PeakDetectionConfig, "peak_detection"),
            contrast_recovery=_load(ContrastRecoveryConfig, "contrast_recovery"),
            display_target=_load(DisplayTargetConfig, "display_target"),
            gamut_mapping=_load(GamutMappingConfig, "gamut_mapping"),
            dithering=_load(DitheringConfig, "dithering"),
            deband=_load(DebandConfig, "deband"),
            icc_lut=_load(IccLutConfig, "icc_lut"),
            shaders=shader_cfg,
            scaling=_load(ScalingConfig, "scaling"),
            output=_load(OutputConfig, "output"),
            performance=_load(PerformanceConfig, "performance"),
            picture=_load(PictureConfig, "picture"),
            geometry=_load(GeometryConfig, "geometry"),
            zion_core=_load_zion_core(data.get("zion_core", {})),
        )

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> MpvProfile:
        # utf-8-sig tolerates a UTF-8 BOM (e.g. profiles written by PowerShell /
        # some editors), which plain utf-8 rejects with JSONDecodeError.
        return cls.from_json(path.read_text(encoding="utf-8-sig"))


@dataclass
class AppConfig:
    mpv_executable: str = field(default_factory=_default_mpv_executable)
    shader_dir: str = ""
    active_profile: str = "Default"
    profiles_dir: str = "profiles"
    wallpaper_path: str = ""
    signal_loss_timeout: float = 5.0
    restart_cooldown: float = 3.0
    max_restart_attempts: int = 5
    ipc_pipe: str = r"\\.\pipe\mpvsocket"
    # "video_processor" | "media_player"
    app_mode: str = "video_processor"
    # Last used media folder for media player mode. Since the poster library the
    # folder list lives in the library database; this is kept as the first folder
    # and migrated into the library once.
    media_folder: str = ""
    # Library tab last shown: "movies" | "tv" | "folders"
    library_tab: str = "movies"
    # Posters from OMDb for titles with no local artwork. omdb_api_key overrides
    # the key shipped with the app. library_save_posters writes each downloaded
    # poster beside the media (<film>-poster.jpg, <show>\poster.jpg).
    library_online_art: bool = True
    omdb_api_key: str = ""
    library_save_posters: bool = True
    # Last played file (remembered for resume)
    last_played: str = ""
    # Calibration output directory (media library "Calibrate colour" button)
    calibration_output_dir: str = ""
    # Playback session preferences (persisted across sessions)
    hwdec: str = "auto-copy"
    # Audio delivery: "" = decode to LPCM here, "auto" = bitstream to the AVR.
    # "auto" is the shipped default because this build runs on an HTPC whose audio goes
    # to a receiver: the AVR decodes Dolby/DTS natively, shows the correct format logo,
    # and does it better than a PC decoder with a stereo downmix in the worst case. The
    # engine agrees (MpcPlayer.h audioMode_ = Bitstream) — until now the UI was overriding
    # it back to LPCM at startup, because this field's default was "" and
    # emit_saved_settings() replays it on every launch.
    audio_mode: str = "auto"
    # Set only when the user picks a mode in the playback panel. It is what makes the
    # migration in load() safe: "" written by an OLD default config was never a choice,
    # so it becomes bitstream; "" written by someone who tapped "Decode to LPCM" is a
    # choice and is left alone. Without this flag there is no way to tell the two apart,
    # because both are the empty string.
    audio_mode_explicit: bool = False
    audio_device: str = "auto"
    deinterlace: bool = False
    # First-run flag — False after user completes initial setup
    first_run: bool = True
    # Active DeckLink input URL (decklink://Device@port)
    active_input_url: str = ""
    # User-defined labels for each input URL — JSON dict stored as string
    input_labels_json: str = "{}"

    def get_input_labels(self) -> dict:
        try:
            return json.loads(self.input_labels_json)
        except Exception:
            return {}

    def set_input_label(self, url: str, label: str) -> None:
        labels = self.get_input_labels()
        if label:
            labels[url] = label
        else:
            labels.pop(url, None)
        self.input_labels_json = json.dumps(labels)

    # Per-user "this install has been set up" marker. app_config.json deliberately
    # survives uninstall (a re-install must not cost anyone their tuned curve), which
    # also meant first_run stayed False across a reinstall and the setup wizard never
    # reappeared. The INSTALLER deletes this registry value on every install
    # (unplugged.iss, ssPostInstall); the app writes it when setup completes. Config
    # keeps the tuning, the marker tracks the install, and the two stop fighting.
    # It lives under Software\Unplugged as a VALUE, not a key, so deleting or writing
    # it cannot touch the renderer's Software\Unplugged\Renderer subkey.
    @staticmethod
    def seen_setup_marker() -> bool:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Unplugged") as k:
                winreg.QueryValueEx(k, "SeenSetup")
                return True
        except OSError:
            return False

    @staticmethod
    def write_seen_setup_marker() -> None:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Unplugged") as k:
            winreg.SetValueEx(k, "SeenSetup", 0, winreg.REG_SZ, "1")

    def label_for(self, url: str) -> str:
        """Return user label for a URL, or a clean default."""
        labels = self.get_input_labels()
        if url in labels:
            return labels[url]
        # Generate clean default from URL
        clean = url.replace("decklink://", "")
        if "@" in clean:
            name, _, port = clean.rpartition("@")
            return f"HDMI {int(port)+1}"
        return clean

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> AppConfig:
        data = json.loads(text)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> AppConfig:
        cfg = cls() if not path.exists() else cls.from_json(path.read_text(encoding="utf-8"))
        # One-time migration, and it is conditional rather than a blunt default change.
        # The whole AppConfig is serialised on every save, so a config written before
        # audio_mode shipped as "auto" already has audio_mode="" stored on disk — and a
        # changed dataclass default would be ignored, leaving the box on LPCM forever.
        # "" with no explicit pick was the OLD default, never a decision, so it becomes
        # bitstream. "" WITH the flag set is a deliberate "Decode to LPCM" and is left
        # exactly where the user put it. Idempotent: after this, the stored value is
        # "auto" and the test no longer fires.
        if not cfg.audio_mode_explicit and cfg.audio_mode == "":
            cfg.audio_mode = "auto"
        return cfg

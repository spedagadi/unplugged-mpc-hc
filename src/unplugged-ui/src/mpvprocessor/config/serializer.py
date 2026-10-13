"""
Converts a MpvProfile into mpv CLI args and mpv.conf content.
All options target --vo=gpu-next (libplacebo).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import MpvProfile


def _vf_format_filter(h) -> str:
    return (
        f"format=colorlevels={h.color_levels}"
        f":primaries={h.primaries}"
        f":gamma={h.gamma}"
        f":colormatrix={h.color_matrix}"
        f":chroma-location={h.chroma_location}"
    )


def _bool(v: bool) -> str:
    return "yes" if v else "no"


def _int_or_keyword(value: str, keywords: tuple, fallback: str) -> str:
    """Validate a value that mpv accepts as a keyword or integer.
    Returns the value unchanged if it's a known keyword, coerces to int if
    it looks numeric, or returns fallback if it's invalid."""
    if value in keywords:
        return value
    try:
        return str(int(float(value)))
    except (ValueError, TypeError):
        return fallback


def _zion_core_args(zc) -> list[str]:
    """Build mpv CLI args for the Zion Core ML pipeline.
    The model is always loaded at startup (CPU-only, 1.3MB RAM) so the enabled
    toggle can flip on/off live without restart. When disabled, all ML modes are
    set to off — the model stays resident but does no work."""
    args: list[str] = []
    # Always load the model if available — negligible RAM, enables live toggle
    if zc.ml_model_path:
        args.append(f"--ml-model={zc.ml_model_path}")
    if zc.shadow.model_path:
        args.append(f"--ml-shadow-model={zc.shadow.model_path}")
    if zc.highlight.model_path:
        args.append(f"--ml-highlight-model={zc.highlight.model_path}")
    if not zc.enabled:
        args += ["--ml-gamma=off", "--ml-cr=off",
                 "--ml-fire-pop=off", "--ml-radiance=off", "--ml-chroma=off",
                 "--ml-shadow=off", "--ml-highlight=off"]
        return args
    # The Oracle (gamma)
    args.append(f"--ml-gamma={'auto' if zc.oracle.auto else 'manual'}")
    if not zc.oracle.auto:
        args.append(f"--ml-gamma-value={zc.oracle.value:.3f}")
    # Construct CR
    args.append(f"--ml-cr={'auto' if zc.construct_cr.auto else 'manual'}")
    if not zc.construct_cr.auto:
        args.append(f"--ml-cr-strength={zc.construct_cr.value:.3f}")
    # Fire pop — always off; Spectrum Shift's fire-boost owns that region
    args.append("--ml-fire-pop=off")
    # Resonance (radiance)
    args.append(f"--ml-radiance={'auto' if zc.resonance.auto else 'manual'}")
    if not zc.resonance.auto:
        args.append(f"--ml-radiance-knee={zc.resonance.knee:.3f}")
        args.append(f"--ml-radiance-strength={zc.resonance.strength:.3f}")
    # Shoulder always emitted (applies in both auto and manual modes)
    args.append(f"--ml-radiance-shoulder={zc.resonance.shoulder:.3f}")
    # Spectrum Shift — always manual, no auto
    ss = zc.spectrum_shift
    args += [
        "--ml-chroma=manual",
        f"--ml-chroma-neutral={ss.neutral_boost:.3f}",
        f"--ml-chroma-fire={ss.fire_boost:.3f}",
        f"--ml-chroma-knee={ss.knee:.3f}",
        f"--ml-chroma-skin={ss.skin_protect:.3f}",
    ]
    # Shadow bilateral
    args.append(f"--ml-shadow={zc.shadow.mode}")
    if zc.shadow.mode == "manual":
        args.append(f"--ml-shadow-strength={zc.shadow.strength:.3f}")
    # Highlight bilateral
    args.append(f"--ml-highlight={zc.highlight.mode}")
    if zc.highlight.mode == "manual":
        args.append(f"--ml-highlight-strength={zc.highlight.strength:.3f}")
    # Temporal stability (adaptive IIR + deadband)
    args += [
        f"--ml-iir-alpha={zc.iir_alpha:.3f}",
        f"--ml-gamma-max-delta={zc.gamma_max_delta:.3f}",
        f"--ml-iir-slow-alpha={zc.iir_slow_alpha:.3f}",
    ]
    # SDR→P5 virtual-master bridge (elevate SDR sources to a virtual HDR
    # master before the ML grade)
    if zc.emulate_sdr:
        args += ["--ml-emulate-sdr",
                 f"--ml-sdr-virtual-nits={zc.sdr_virtual_nits:.0f}",
                 f"--ml-sdr-strength={zc.sdr_strength:.2f}"]
    return args


def build_media_player_args(profile: MpvProfile, ipc_pipe: str,
                            file_path: str, wid: int = 0) -> list[str]:
    """
    Minimal args for local file playback — no capture flags, no HDR override.
    Still applies tone mapping, display target, scaling and dithering so the
    picture quality settings carry over from the active preset.
    """
    args: list[str] = []

    import pathlib
    _home = pathlib.Path.home() / ".unplugged"
    _home.mkdir(exist_ok=True)
    _input_conf = _home / "input_mediaplayer.conf"
    _input_conf.write_text(
        "ctrl+SPACE script-message unplugged-toggle-settings\n",
        encoding="utf-8"
    )
    _log = str(_home / "mpv_mediaplayer.log")
    args += [f"--input-ipc-server={ipc_pipe}"]
    args += [f"--input-conf={_input_conf}"]
    # ipc=debug shows every IPC command sent/received; cplayer=v shows key events
    args += [f"--log-file={_log}",
             "--msg-level=ipc=debug,cplayer=v,vo=v,vd=v,stream=v"]

    if wid:
        args += [f"--wid={wid}"]

    # --fullscreen must NOT be passed when embedded via --wid;
    # unplugged owns the window and fills the screen itself.

    # Tone mapping
    tm = profile.tone_mapping
    args += [f"--tone-mapping={tm.algorithm}"]
    if tm.tone_mapping_param != "default":
        args += [f"--tone-mapping-param={tm.tone_mapping_param}"]
    args += [f"--tone-mapping-max-boost={tm.tone_mapping_max_boost}"]
    if tm.inverse_tone_mapping:
        args += ["--inverse-tone-mapping"]
    if tm.tone_mapping_visualize:
        args += ["--tone-mapping-visualize"]

    # Peak detection — full set matching build_mpv_args
    pd = profile.peak_detection
    if pd.hdr_compute_peak != "yes":
        args += [f"--hdr-compute-peak={pd.hdr_compute_peak}"]
    if pd.hdr_compute_peak != "no":
        args += [
            f"--hdr-peak-percentile={pd.hdr_peak_percentile}",
            f"--hdr-peak-decay-rate={pd.hdr_peak_decay_rate}",
            f"--hdr-scene-threshold-low={pd.hdr_scene_threshold_low}",
            f"--hdr-scene-threshold-high={pd.hdr_scene_threshold_high}",
        ]
        if pd.allow_delayed_peak_detect:
            args += ["--allow-delayed-peak-detect"]
        else:
            args += ["--no-allow-delayed-peak-detect"]

    # Contrast recovery — zeroed only when Zion Core is active with a model path
    cr = profile.contrast_recovery
    zion_active = profile.zion_core.enabled
    args += [
        f"--hdr-contrast-recovery={0.0 if zion_active else cr.hdr_contrast_recovery}",
        f"--hdr-contrast-smoothness={cr.hdr_contrast_smoothness}",
    ]

    # Display target — full set
    dt = profile.display_target
    args += [
        f"--target-trc={dt.target_trc}",
        f"--target-prim={dt.target_prim}",
        f"--target-peak={dt.target_peak}",
        f"--target-contrast={dt.target_contrast}",
        f"--target-colorspace-hint={dt.target_colorspace_hint}",
        f"--hdr-reference-white={dt.hdr_reference_white}",
        f"--gamut-mapping-mode={profile.gamut_mapping.mode}",
    ]
    if dt.target_gamut:
        args += [f"--target-gamut={dt.target_gamut}"]

    # Gamut sub-params via libplacebo-opts
    gm = profile.gamut_mapping
    _lp = (f"perceptual_deadzone={gm.perceptual_deadzone}"
           f",perceptual_strength={gm.perceptual_strength}"
           f",colorimetric_gamma={gm.colorimetric_gamma}"
           f",softclip_knee={gm.softclip_knee}"
           f",softclip_desat={gm.softclip_desat}"
           f",lut3d_size_I={gm.lut3d_size_I}"
           f",lut3d_size_C={gm.lut3d_size_C}"
           f",lut3d_size_h={gm.lut3d_size_h}"
           f",lut3d_tricubic={'yes' if gm.lut3d_tricubic else 'no'}"
           f",gamut_expansion={'yes' if gm.gamut_expansion else 'no'}")
    args += [f"--libplacebo-opts-set={_lp}"]

    # Dithering — full set
    d = profile.dithering
    args += [
        f"--dither={d.algorithm}",
        f"--dither-depth={d.depth}",
        f"--temporal-dither={'yes' if d.temporal else 'no'}",
        f"--temporal-dither-period={d.temporal_period}",
    ]
    if d.algorithm == "fruit":
        args += [f"--dither-size-fruit={d.fruit_size}"]
    elif d.algorithm == "error-diffusion":
        args += [f"--error-diffusion={d.error_diffusion}"]

    # Debanding
    if profile.deband.enabled:
        args += [
            "--deband",
            f"--deband-iterations={profile.deband.iterations}",
            f"--deband-threshold={profile.deband.threshold}",
            f"--deband-range={profile.deband.range}",
            f"--deband-grain={profile.deband.grain}",
        ]

    # Scaling
    sc = profile.scaling
    args += [f"--scale={sc.scale}"]
    if sc.scale_blur > 0:
        args += [f"--scale-blur={sc.scale_blur}"]
    args += [
        f"--dscale={sc.dscale}",
        f"--cscale={sc.cscale}",
        f"--linear-downscaling={'yes' if sc.linear_downscaling else 'no'}",
    ]
    if sc.tscale != "oversample":
        args += [f"--tscale={sc.tscale}"]

    # Picture adjustments
    pic = profile.picture
    if pic.brightness != 0:
        args += [f"--brightness={pic.brightness}"]
    if pic.contrast != 0:
        args += [f"--contrast={pic.contrast}"]
    if pic.saturation != 0:
        args += [f"--saturation={pic.saturation}"]
    if pic.hue != 0:
        args += [f"--hue={pic.hue}"]
    if pic.gamma != 0 and not zion_active:   # The Oracle owns gamma when Zion Core active
        args += [f"--gamma={pic.gamma}"]
    if pic.sharpen != 0.0:
        args += [f"--sharpen={pic.sharpen}"]

    # Geometry
    geo = profile.geometry
    if geo.video_zoom != 0.0:
        args += [f"--video-zoom={geo.video_zoom}"]
    if geo.video_pan_x != 0.0:
        args += [f"--video-pan-x={geo.video_pan_x}"]
    if geo.video_pan_y != 0.0:
        args += [f"--video-pan-y={geo.video_pan_y}"]
    if geo.video_aspect_override:
        args += [f"--video-aspect-override={geo.video_aspect_override}"]
    if geo.video_rotate != 0:
        args += [f"--video-rotate={geo.video_rotate}"]

    # Shaders
    for sp in profile.shaders.enabled_paths():
        args += [f"--glsl-shaders-append={sp}"]

    # Zion Core ML pipeline
    args += _zion_core_args(profile.zion_core)

    # File path (positional — must be last)
    args += [file_path]

    return args


def build_mpv_args(profile: MpvProfile, ipc_pipe: str, wid: int = 0) -> list[str]:
    """Returns the list of CLI args to pass to mpv (excluding the binary itself)."""
    p = profile
    args: list[str] = []

    import pathlib
    _home = pathlib.Path.home() / ".unplugged"
    _home.mkdir(exist_ok=True)
    _log = str(_home / "mpv_capture.log")
    args += [f"--input-ipc-server={ipc_pipe}"]
    args += [f"--log-file={_log}",
             "--msg-level=ipc=debug,cplayer=v,vo=v,vd=v,stream=v"]

    if wid:
        args += [f"--wid={wid}"]

    # ── Performance / buffering ────────────────────────────────────────
    args += ["--no-audio"]
    # Live DeckLink capture MUST be uncached — mpv's cache prefill on a live,
    # non-seekable input can stall playback from ever reaching PLAYING. Forced
    # on for decklink regardless of the profile toggle.
    is_decklink = p.input.device.startswith("decklink://")
    if is_decklink or p.performance.no_cache:
        args += ["--no-cache"]
    # VP acquisition warm-up hold: present black until shaders + ML are warm,
    # so the capture start feels instant-clean (stays in the AVR lip-sync budget).
    if is_decklink:
        args += ["--ml-acq-warm-hold", "--ml-acq-warm-frames=5"]
    # Synchronous demuxer reads for live capture: the demuxer thread reads
    # ahead into the default 150MB buffer (~150ms at capture rate), adding
    # pipeline latency. Forcing --no-demuxer-thread makes the decoder pull
    # frames on demand → lower steady-state latency.
    if is_decklink:
        args += ["--no-demuxer-thread"]
    # NOTE: --swapchain-depth=1 was tried (Round-1) but broke acquisition on
    # this rig (no frame ever presented → acquiring dialog stuck). Reverted;
    # to retest, add it alone and watch the capture log for present/fence.
    # if is_decklink:
    #     args += ["--swapchain-depth=1"]
    if p.performance.no_demuxer_thread:
        args += ["--no-demuxer-thread"]
    # NOTE: `--demuxer-max-bytes=800M` was REMOVED — on a live ~1 GB/s DeckLink
    # stream it let the demuxer read ~0.8 s ahead, adding >500 ms lip-sync
    # latency that blew the AVR's compensation budget. mpv's default (150 MB,
    # ~150 ms @ capture rate) is the low-latency baseline; rtbufsize stays.
    # Live-DeckLink capture avoptions — pinned to the proven-working direct
    # command form (HTPC A/B). Do NOT set analyzeduration >0, probesize, or a
    # large rtbufsize here: analyzeduration delays the first frame, and a 2G
    # rtbuf adds pipeline latency that blows the AVR lip-sync budget.
    args += [
        f"--audio-buffer={p.performance.audio_buffer}",
        "--demuxer-lavf-analyzeduration=0",
        # raw_format=2 = v210 10-bit 4:2:2; video_pts=wallclock enables the
        # frame-age latency diagnostic; fflags=nobuffer stops latency accumulating
        # inside libavformat's decklink path.
        "--demuxer-lavf-o=rtbufsize=32M,raw_format=2,video_pts=wallclock,fflags=nobuffer",
        # libav low-latency knobs (verified: cut capture-side skew ~420 ms):
        # decoder low_delay + drop late frames.
        "--vd-lavc-o=flags=low_delay",
        "--framedrop=decoder",
    ]
    if is_decklink and p.performance.video_latency_hacks:
        args += ["--video-latency-hacks=yes"]
    if is_decklink:
        # Flush the decode→VO queue to 0 before feeding during acquisition
        # (drop-until-live at the queue, complements the present-gate).
        args += ["--ml-acq-drain"]
    # --ml-acq-cutover is a VO-scoped option: it cannot be set via property
    # before the VO exists, so the engine applies it through mpv_set_option_string
    # (see MpvEngine.set_vo_option in mpv_engine.py) at capture start.

    # ── HDR override filter ────────────────────────────────────────────
    if p.hdr_override.force_hdr_override:
        args += [f"--vf={_vf_format_filter(p.hdr_override)}"]

    # ── Video output ───────────────────────────────────────────────────
    if p.output.vo != "gpu-next":
        args += [f"--vo={p.output.vo}"]
    if p.output.fullscreen and not wid:
        args += ["--fullscreen"]

    # ── Tone mapping core ──────────────────────────────────────────────
    tm = p.tone_mapping
    args += [f"--tone-mapping={tm.algorithm}"]
    if tm.tone_mapping_param != "default":
        args += [f"--tone-mapping-param={tm.tone_mapping_param}"]
    args += [f"--tone-mapping-max-boost={tm.tone_mapping_max_boost}"]
    if tm.inverse_tone_mapping:
        args += ["--inverse-tone-mapping"]
    if tm.tone_mapping_visualize:
        args += ["--tone-mapping-visualize"]

    # ── Peak detection ─────────────────────────────────────────────────
    pd = p.peak_detection
    if pd.hdr_compute_peak != "yes":
        args += [f"--hdr-compute-peak={pd.hdr_compute_peak}"]
    if pd.hdr_compute_peak != "no":
        args += [
            f"--hdr-peak-percentile={pd.hdr_peak_percentile}",
            f"--hdr-peak-decay-rate={pd.hdr_peak_decay_rate}",
            f"--hdr-scene-threshold-low={pd.hdr_scene_threshold_low}",
            f"--hdr-scene-threshold-high={pd.hdr_scene_threshold_high}",
        ]
        if pd.allow_delayed_peak_detect:
            args += ["--allow-delayed-peak-detect"]
        else:
            args += ["--no-allow-delayed-peak-detect"]

    # ── Contrast recovery — zeroed only when Zion Core active with model ─
    cr = p.contrast_recovery
    zion_active = p.zion_core.enabled and bool(p.zion_core.ml_model_path)
    args += [
        f"--hdr-contrast-recovery={0.0 if zion_active else cr.hdr_contrast_recovery}",
        f"--hdr-contrast-smoothness={cr.hdr_contrast_smoothness}",
    ]

    # ── Display target ─────────────────────────────────────────────────
    dt = p.display_target
    args += [
        f"--target-trc={dt.target_trc}",
        f"--target-prim={dt.target_prim}",
        f"--target-peak={dt.target_peak}",
        f"--target-contrast={dt.target_contrast}",
        f"--target-colorspace-hint={dt.target_colorspace_hint}",
        f"--hdr-reference-white={dt.hdr_reference_white}",
    ]
    if dt.target_gamut:
        args += [f"--target-gamut={dt.target_gamut}"]

    # ── Gamut mapping ──────────────────────────────────────────────────
    gm = p.gamut_mapping
    args += [f"--gamut-mapping-mode={gm.mode}"]
    # Sub-params passed via --libplacebo-opts (key=value pairs)
    _lp_opts = (
        f"perceptual_deadzone={gm.perceptual_deadzone}"
        f",perceptual_strength={gm.perceptual_strength}"
        f",colorimetric_gamma={gm.colorimetric_gamma}"
        f",softclip_knee={gm.softclip_knee}"
        f",softclip_desat={gm.softclip_desat}"
        f",lut3d_size_I={gm.lut3d_size_I}"
        f",lut3d_size_C={gm.lut3d_size_C}"
        f",lut3d_size_h={gm.lut3d_size_h}"
        f",lut3d_tricubic={'yes' if gm.lut3d_tricubic else 'no'}"
        f",gamut_expansion={'yes' if gm.gamut_expansion else 'no'}"
    )
    args += [f"--libplacebo-opts-set={_lp_opts}"]

    # ── Dithering ─────────────────────────────────────────────────────
    d = p.dithering
    args += [
        f"--dither={d.algorithm}",
        f"--dither-depth={d.depth}",
        f"--temporal-dither={'yes' if d.temporal else 'no'}",
        f"--temporal-dither-period={d.temporal_period}",
    ]
    if d.algorithm == "fruit":
        args += [f"--dither-size-fruit={d.fruit_size}"]
    elif d.algorithm == "error-diffusion":
        args += [f"--error-diffusion={d.error_diffusion}"]

    # ── Deband ────────────────────────────────────────────────────────
    db = p.deband
    if db.enabled:
        args += [
            "--deband",
            f"--deband-iterations={db.iterations}",
            f"--deband-threshold={db.threshold}",
            f"--deband-range={db.range}",
            f"--deband-grain={db.grain}",
        ]

    # ── ICC / LUT ─────────────────────────────────────────────────────
    il = p.icc_lut
    if il.icc_profile:
        args += [f"--icc-profile={il.icc_profile}"]
    if il.icc_profile_auto:
        args += ["--icc-profile-auto"]
    args += [
        f"--use-embedded-icc-profile={'yes' if il.use_embedded_icc_profile else 'no'}",
        f"--icc-intent={il.icc_intent}",
        f"--icc-force-contrast={il.icc_force_contrast}",
        f"--icc-cache={'yes' if il.icc_cache else 'no'}",
    ]
    if il.lut_file:
        args += [f"--lut={il.lut_file}", f"--lut-type={il.lut_type}"]
    if il.image_lut_file:
        args += [f"--image-lut={il.image_lut_file}", f"--image-lut-type={il.image_lut_type}"]
    if il.target_lut_file:
        args += [f"--target-lut={il.target_lut_file}"]

    # ── Picture adjustments ────────────────────────────────────────────
    pic = p.picture
    if pic.brightness != 0:
        args += [f"--brightness={pic.brightness}"]
    if pic.contrast != 0:
        args += [f"--contrast={pic.contrast}"]
    if pic.saturation != 0:
        args += [f"--saturation={pic.saturation}"]
    if pic.hue != 0:
        args += [f"--hue={pic.hue}"]
    if pic.gamma != 0 and not zion_active:   # The Oracle owns gamma when Zion Core active
        args += [f"--gamma={pic.gamma}"]
    if pic.sharpen != 0.0:
        args += [f"--sharpen={pic.sharpen}"]

    # ── Geometry ───────────────────────────────────────────────────────
    geo = p.geometry
    if geo.video_zoom != 0.0:
        args += [f"--video-zoom={geo.video_zoom}"]
    if geo.video_pan_x != 0.0:
        args += [f"--video-pan-x={geo.video_pan_x}"]
    if geo.video_pan_y != 0.0:
        args += [f"--video-pan-y={geo.video_pan_y}"]
    if geo.video_aspect_override:
        args += [f"--video-aspect-override={geo.video_aspect_override}"]
    if geo.video_rotate != 0:
        args += [f"--video-rotate={geo.video_rotate}"]

    # ── Shaders ───────────────────────────────────────────────────────
    enabled_shaders = p.shaders.enabled_paths()
    if enabled_shaders:
        # mpv accepts multiple --glsl-shaders= or a single colon-separated list
        for sp in enabled_shaders:
            args += [f"--glsl-shaders-append={sp}"]

    # ── Scaling ───────────────────────────────────────────────────────
    sc = p.scaling
    args += [f"--scale={sc.scale}"]
    if sc.scale_blur > 0:
        args += [f"--scale-blur={sc.scale_blur}"]
    args += [
        f"--dscale={sc.dscale}",
        f"--cscale={sc.cscale}",
        f"--linear-downscaling={'yes' if sc.linear_downscaling else 'no'}",
    ]
    if sc.tscale != "oversample":
        args += [f"--tscale={sc.tscale}"]

    # ── Zion Core ML pipeline ─────────────────────────────────────────
    args += _zion_core_args(p.zion_core)

    # ── Device URL (positional — must be last) ─────────────────────────
    args += [p.input.device]

    return args


def build_mpv_conf(profile: MpvProfile) -> str:
    """Returns an mpv.conf-style string for the profile."""
    args = build_mpv_args(profile, ipc_pipe="")
    lines = [
        f"# unplugged generated profile: {profile.name}",
        "# Do not edit by hand — managed by unplugged",
        "",
    ]
    for arg in args:
        if arg.startswith("--"):
            lines.append(arg[2:])  # strip leading --
        elif not arg.startswith("decklink://") and arg:
            lines.append(arg)
    return "\n".join(lines) + "\n"


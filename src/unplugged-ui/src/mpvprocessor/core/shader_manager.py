"""
Shader manager: scans a folder for .glsl files, detects conflicts with
libplacebo's built-in processing, and surfaces warnings to the UI.

Conflict severity:
  HARD        — produces wrong output; the conflicting mpv option must be
                overridden before mpv starts.
  SOFT        — redundant / double-processing; warn the user.
  CONDITIONAL — only a problem when a secondary condition is also true.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


class Severity(Enum):
    HARD        = auto()
    SOFT        = auto()
    CONDITIONAL = auto()


@dataclass
class ConflictRule:
    # fnmatch pattern(s) matched against the shader filename (case-insensitive)
    patterns: list[str]
    severity: Severity
    # Human-readable description shown in the UI
    description: str
    # Profile field path e.g. "deband.enabled", "contrast_recovery.hdr_contrast_recovery"
    profile_field: str
    # Value that triggers conflict; None = any non-default / "any"
    conflict_when: object = None
    # Suggested fix shown in the UI
    fix: str = ""


# ─────────────────────────────────────────────────────────────────────
# Conflict rule table (based on mpv/libplacebo gpu-next pipeline)
# ─────────────────────────────────────────────────────────────────────

CONFLICT_RULES: list[ConflictRule] = [
    # ── Tone mapping — HARD ──────────────────────────────────────────
    ConflictRule(
        patterns=["hdr_toys*.glsl", "hdr-toys*.glsl", "*tonemapping*.glsl",
                  "*tonemap*.glsl", "*tone_map*.glsl"],
        severity=Severity.HARD,
        description="Tone-mapping shader conflicts with libplacebo DTM. "
                    "Both pipelines will run — output brightness/colour will be wrong.",
        profile_field="tone_mapping.algorithm",
        conflict_when="any_non_clip",
        fix="Set Tone Mapping algorithm to 'clip' when this shader is enabled.",
    ),

    # ── Debanding — SOFT ─────────────────────────────────────────────
    ConflictRule(
        patterns=["F3B*.glsl", "flash3kyuu_deband*.glsl", "deband*.glsl",
                  "*_deband*.glsl"],
        severity=Severity.SOFT,
        description="Debanding shader + libplacebo --deband = double deband pass. "
                    "Fine detail will be over-smoothed.",
        profile_field="deband.enabled",
        conflict_when=True,
        fix="Disable 'Enable debanding' in settings when using this shader.",
    ),
    # Anime4K restore/denoise also debands effectively
    ConflictRule(
        patterns=["Anime4K_Restore*.glsl", "Anime4K_Denoise*.glsl"],
        severity=Severity.SOFT,
        description="Anime4K restore/denoise smooths the same frequency band as --deband. "
                    "Combined result is over-processed.",
        profile_field="deband.enabled",
        conflict_when=True,
        fix="Disable 'Enable debanding' when using Anime4K restore/denoise shaders.",
    ),

    # ── Sharpening / contrast recovery — SOFT ────────────────────────
    ConflictRule(
        patterns=["FSRCNNX*.glsl", "SSimSuperRes*.glsl"],
        severity=Severity.SOFT,
        description="FSRCNNX/SSimSuperRes sharpens in linear light; "
                    "HDR Contrast Recovery re-injects detail after tone mapping. "
                    "Both active = double sharpening with haloing on bright edges.",
        profile_field="contrast_recovery.hdr_contrast_recovery",
        conflict_when="nonzero",
        fix="Set HDR Contrast Recovery strength to 0.0 when using this shader.",
    ),
    ConflictRule(
        patterns=["adaptive_sharpen*.glsl", "AdaptiveSharpen*.glsl",
                  "cas.glsl", "CAS*.glsl"],
        severity=Severity.SOFT,
        description="Adaptive sharpen / CAS + HDR Contrast Recovery = "
                    "double sharpening on the output-referred image (ringing artefacts).",
        profile_field="contrast_recovery.hdr_contrast_recovery",
        conflict_when="nonzero",
        fix="Set HDR Contrast Recovery strength to 0.0 when using this shader.",
    ),

    # ── Upscaling shaders supersede --scale ──────────────────────────
    ConflictRule(
        patterns=["FSRCNNX*.glsl", "ravu*.glsl", "ravu-lite*.glsl",
                  "ravu-zoom*.glsl", "SSimSuperRes*.glsl"],
        severity=Severity.SOFT,
        description="This shader hooks the luma upscaler. "
                    "The --scale kernel is never called; the configured scaler is wasted.",
        profile_field="scaling.scale",
        conflict_when="any_quality",
        fix="Consider setting Scale to 'bilinear' — the shader handles upscaling.",
    ),
    ConflictRule(
        patterns=["Anime4K_Upscale*.glsl", "Anime4K_*_x*.glsl"],
        severity=Severity.SOFT,
        description="Anime4K upscale hooks both luma and chroma scalers. "
                    "--scale and --cscale are both superseded.",
        profile_field="scaling.scale",
        conflict_when="any_quality",
        fix="Set Scale and Chroma scale to 'bilinear' — Anime4K handles both.",
    ),
    ConflictRule(
        patterns=["SSimDownscaler*.glsl"],
        severity=Severity.SOFT,
        description="SSimDownscaler replaces --dscale for all downscaling paths.",
        profile_field="scaling.dscale",
        conflict_when="any_quality",
        fix="Set Downscale to 'bilinear' — the shader handles downscaling.",
    ),
    ConflictRule(
        patterns=["SSimDownscaler*.glsl"],
        severity=Severity.CONDITIONAL,
        description="SSimDownscaler is calibrated for perceptual (gamma) space. "
                    "Linear downscaling feeds it linear values, degrading SSIM quality.",
        profile_field="scaling.linear_downscaling",
        conflict_when=True,
        fix="Disable 'Linear downscaling' when using SSimDownscaler.",
    ),

    # ── Chroma reconstruction supersedes --cscale ────────────────────
    ConflictRule(
        patterns=["KrigBilateral*.glsl", "ArtCNN_C*Chroma*.glsl",
                  "*Chroma_Upscale*.glsl", "*chroma_upscal*.glsl"],
        severity=Severity.SOFT,
        description="This shader hooks CHROMA_SCALED and fully replaces --cscale "
                    "for chroma upsampling. The cscale kernel is never used.",
        profile_field="scaling.cscale",
        conflict_when="any_quality",
        fix="Set Chroma scale to 'bilinear' — the shader handles chroma reconstruction.",
    ),

    # ── Grain / film noise ────────────────────────────────────────────
    ConflictRule(
        patterns=["filmgrain*.glsl", "film_grain*.glsl", "grain*.glsl",
                  "noise*.glsl", "OOTB*.glsl"],
        severity=Severity.SOFT,
        description="External grain shader + deband-grain > 0 = double noise layer. "
                    "Note: deband-grain only fires when debanding is also enabled.",
        profile_field="deband.grain",
        conflict_when="nonzero",
        fix="Set Deband grain to 0 when using a grain shader.",
    ),
]


# ─────────────────────────────────────────────────────────────────────
# Conflict detection
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ShaderConflict:
    shader_name: str
    rule: ConflictRule


def _get_field(profile, dotted: str):
    """Traverse dotted field path on a profile, e.g. 'deband.enabled'."""
    obj = profile
    for part in dotted.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _is_conflict(rule: ConflictRule, profile) -> bool:
    val = _get_field(profile, rule.profile_field)
    cw = rule.conflict_when
    if cw is None:
        return True
    if cw == "any_non_clip":
        return val not in (None, "clip", "no")
    if cw == "nonzero":
        try:
            return float(val) != 0.0
        except (TypeError, ValueError):
            return False
    if cw == "any_quality":
        return val not in (None, "bilinear", "nearest", "")
    return val == cw


def detect_conflicts(shader_name: str, profile) -> list[ShaderConflict]:
    name_lower = shader_name.lower()
    conflicts = []
    for rule in CONFLICT_RULES:
        matched = any(
            fnmatch.fnmatch(name_lower, pat.lower()) for pat in rule.patterns
        )
        if matched and _is_conflict(rule, profile):
            conflicts.append(ShaderConflict(shader_name=shader_name, rule=rule))
    return conflicts


# ─────────────────────────────────────────────────────────────────────
# Folder scanner
# ─────────────────────────────────────────────────────────────────────

def default_shader_dir(mpv_executable: str) -> Path:
    """Returns <mpv.exe folder>/shaders as the default shader directory."""
    return Path(mpv_executable).parent / "shaders"


def scan_shader_dir(folder: Path) -> list[str]:
    """Return sorted list of absolute .glsl paths found in folder."""
    if not folder.is_dir():
        return []
    return sorted(str(p) for p in folder.glob("*.glsl"))


def sync_shader_list(shader_config, mpv_executable: str) -> None:
    """
    Scan the configured shader_dir (falling back to default) and add any
    new .glsl files to shader_config.shaders. Preserves enabled state for
    files already in the list; removes entries whose files no longer exist.
    """
    folder_str = shader_config.shader_dir
    if not folder_str:
        folder = default_shader_dir(mpv_executable)
        shader_config.shader_dir = str(folder)
    else:
        folder = Path(folder_str)

    found = scan_shader_dir(folder)
    existing = {s["path"]: s["enabled"] for s in shader_config.shaders}

    updated = []
    for path in found:
        updated.append({"path": path, "enabled": existing.get(path, False)})

    shader_config.shaders = updated

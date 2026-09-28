"""
s3shell_panel.py — standalone PyQt6 replica of the s3_shell settings panel.

A direct transcription of tools/engine_s3/s3_shell.cpp:
  PaintRight()   -> paintEvent tab bar + icon rail + content
  PaintSysRow()  -> toggle / cycle / slider rows
  PaintSection() -> section headers
  RebuildLayout() -> y-accumulated row layout
  Palette COL_*, metrics kTabH/kSysRowH/kRailW/kRightW/kPad/kIconH/kIconStep,
  fonts, and the full BuildRows() add(...) table.

Rendering is a single QPainter pass (the GDI model), NOT stacked widgets, so the
layout stays pixel-faithful.
"""

from __future__ import annotations

import os, sys
from pathlib import Path

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QApplication

# The UI font comes from ui/theme.py — the same definition BASE_QSS feeds to
# the stylesheet-driven panels (the status panel). Nothing here builds a font
# of its own, so the rail cannot drift from the rest of the app.
try:
    from .theme import ui_font, panel_qcolor, FONT_PX_LABEL, FONT_PX_VALUE
except ImportError:                     # standalone copy: tools/s3settings_qt
    from PyQt6.QtGui import QFont as _QFont

    FONT_PX_LABEL, FONT_PX_VALUE = 12, 13

    def panel_qcolor():
        return QColor(14, 14, 16, 235)

    def ui_font(px, weight=_QFont.Weight.Normal, spacing=None):
        f = _QFont()
        f.setFamilies(["Inter", "Segoe UI", "SF Pro Display", "Ubuntu"])
        f.setPixelSize(px)
        f.setWeight(weight)
        if spacing is not None:
            f.setLetterSpacing(_QFont.SpacingType.AbsoluteSpacing, spacing)
        return f

# ── logging (kiosk debugging: file next to this module) ──────────────────────
_LOG = Path(__file__).resolve().parent / "panel.log"


def log(*a):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(" ".join(str(x) for x in a) + "\n")
    except OSError:
        pass


def log_exc(where):
    import traceback
    log(where, "EXC:", traceback.format_exc().replace("\n", " | "))

# ── palette (COL_* from s3_shell.cpp) ────────────────────────────────────────
# Panel surface comes from ui/theme.py — the same colour the status rail and
# the bars use, so the frame reads as one material.
BG      = panel_qcolor()
PANEL   = panel_qcolor()
BORDER  = QColor(0x24, 0x24, 0x28)
ACCENT  = QColor(0xE8, 0x55, 0x1F)
ACCENT2 = QColor(0xFF, 0x8A, 0x4C)
TEXT    = QColor(0xF2, 0xF2, 0xF2)
MID     = QColor(0x8A, 0x8A, 0x90)
LO      = QColor(0x5A, 0x5A, 0x5A)
OK      = QColor(0x4C, 0xAF, 0x50)
HOT     = QColor(0x23, 0x23, 0x27)
ACTIVE_BG = QColor(0x1E, 0x1E, 0x20)

# ── metrics (scaled by g_scale=1 in this standalone) ─────────────────────────
RIGHT_W     = 440
RAIL_W      = 80
# The top Playback|System tab bar was retired when PLAYBACK became a rail icon:
# the icon rail is now the only navigation, so the content starts at the top.
LIST_TOP    = 0
CAT_H       = 26
ROW_H       = 40
PAD         = 16
SECT_H      = 26
ICON_H      = 58
ICON_STEP   = 64
CONTROL_W   = 148       # right control column width (w - 148 .. w - pad)
_VALUE_W    = 58

# ── fonts ────────────────────────────────────────────────────────────────────
# Family and sizes deliberately mirror the status panel, which renders its
# subgroups from _SEC_STYLE (12px bold, 1.5px tracking, #E8551F), its row keys
# at 12px and its values at 13px — all in theme.app_font()'s family.
#
# Built lazily: QFontDatabase needs a QGuiApplication, and this module is
# imported in contexts that have not created one yet.
F_SECTION = F_RAIL = F_CAT = F_LABEL = F_VALUE = None
F_BUTTON = F_HEADER = F_STATUS = F_ICON = None
F_GLYPH: dict = {}


def _init_fonts() -> None:
    """Populate the font set once a QApplication exists.

    Every entry is the status panel's own style at the same size and weight —
    subgroup headers == _SEC_STYLE, row labels == _KEY_STYLE, values and
    readouts == _VAL_STYLE — all through theme.ui_font().
    """
    global F_SECTION, F_RAIL, F_CAT, F_LABEL, F_VALUE
    global F_BUTTON, F_HEADER, F_STATUS, F_ICON, F_GLYPH
    if F_SECTION is not None:
        return
    F_SECTION = ui_font(FONT_PX_LABEL, QFont.Weight.Bold, 1.5)   # _SEC_STYLE
    F_LABEL   = ui_font(FONT_PX_LABEL)                           # _KEY_STYLE
    F_VALUE   = ui_font(FONT_PX_VALUE)                           # _VAL_STYLE
    F_STATUS  = ui_font(FONT_PX_VALUE)                           # _VAL_STYLE
    F_RAIL    = ui_font(FONT_PX_LABEL, QFont.Weight.DemiBold, 1.0)
    F_CAT     = ui_font(FONT_PX_LABEL)
    F_BUTTON  = ui_font(FONT_PX_VALUE, QFont.Weight.DemiBold)    # tab title
    F_HEADER  = ui_font(24, QFont.Weight.DemiBold)
    F_ICON    = ui_font(30, QFont.Weight.DemiBold)
    F_GLYPH   = {g: ui_font(px, QFont.Weight.DemiBold)
                 for g, px in GLYPH_OPTICAL.items()}

# ── groups (kSysGroups, verbatim) ────────────────────────────────────────────
GROUPS = [
    # PLAYBACK leads: it is the media-playback surface (audio/subtitle tracks,
    # HD-audio output mode, audio delay). Track enumeration is still engine work
    # — those rows persist to the INI but stay inert until media player mode
    # exposes a track list over the C ABI.
    ("▶", "PLAYBACK", QColor(0x8A, 0x7C, 0xD8), ["Audio", "Subtitles"]),
    ("⬡", "SOURCE", QColor(0x5B, 0x8F, 0xD0), ["Input Device"]),
    ("◑", "HDR",    QColor(0xC8, 0xA0, 0x30), ["Tone Mapping", "Peak Detection",
                                                    "Contrast Recovery", "Display Target",
                                                    "Experimental Tone Mappers"]),
    ("✦", "ZION",   QColor(0xC8, 0x70, 0x40), ["Zion Core"]),
    ("▣", "OUTPUT", QColor(0x4C, 0xAF, 0x78), ["Scaling", "Picture", "Output"]),
    ("≡", "SYSTEM", QColor(0x90, 0x90, 0x90), ["App"]),
]

TOGGLE, CYCLE, SLIDER = "toggle", "cycle", "slider"
FILE = "file"          # a path row: click opens a picker, value is a filename
ACTION = "action"      # a command row: click runs an action (no stored value)

# A display LUT is a COMMAND, not a flat grp.name=value setting, so these rows
# bypass KEY_MAP and go through engine.load_cube_lut() instead.
_LUT_PATH_KEY = "out.cubeLut"
_LUT_MODE_KEY = "out.cubeLutMode"
# Index order IS the engine's mode value: 0=off, 1=gamma, 2=greyscale, 3=full.
_LUT_MODES = ["Off", "Gamma only", "Greyscale", "Full 3D"]

# Mutually exclusive in the renderer (s3_shell.cpp ApplyRow): turning either of
# these ON force-clears the other, and both are then re-pushed.
_PASSTHROUGH = ("hdr.hdrPass", "zion.debugCopyShaders")

# Optical size: the filled ▶ occupies nearly its whole em box, while the outline
# glyphs beside it (⬡  ✦ ▣ ≡) sit well inside theirs. Drawn at the same point
# size it reads far larger, so these are set smaller to match.
GLYPH_OPTICAL = {"▶": 25}

# Sliders whose engine field is an INTEGER — MpcPlayer parses these with
# (int)vd(v), so a fractional value is silently truncated on the way in. The
# rail must not show (or store) precision the renderer will discard. Every other
# slider maps to a float.
INT_SLIDERS = {"hdr.sdrNits", "hdr.maxNits", "hdr.osdBright", "hdr.titlePeak", "postfx.debandIter"}

# The value column is only 42px wide, so a long float overflows and becomes
# unreadable. Same rule as s3_shell.cpp's FmtNum(): whole numbers print bare,
# everything else is capped at 2 decimals.
_SLIDER_DECIMALS = 2


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v))}"
    return f"{v:.{_SLIDER_DECIMALS}f}"

# s3_shell INI key -> engine group/key (MpcPlayer::ApplySettingsFlat names).
# Keys with no engine equivalent map to None (skipped on apply).
KEY_MAP = {
    "zion.enabled": ("ml", "enable"),
    "zion.toneMode": ("ml", "mode"),
    "zion.shadowToe": ("ml", "shadow"),
    "zion.shadowDehaze": ("ml", "shDehaze"),
    "zion.gamma": ("ml", "gamma"),
    "zion.highlight": ("ml", "highlight"),
    "zion.highlightRolloffCtrl": ("ml", "hiRoll"),
    "zion.gammaTopUp": ("ml", "gammaTopUp"),
    # The shadow pedestal row was removed: the measurement that motivated it turned
    # out to be letterbox geometry, and ungated it greys the matte. The renderer term
    # and ml.shPed parse name remain, at 0, for a future black-point control.
    "zion.tgtMid": ("ml", "tgtMid"),
    "zion.chN": ("ml", "chN"),
    "zion.chF": ("ml", "chF"),
    "zion.knee": ("ml", "knee"),
    "zion.skin": ("ml", "skin"),
    "zion.contrast": ("ml", "contrastEnable"),
    "zion.contrastStrength": ("ml", "contrast"),
    "zion.contrastZoneLo": ("ml", "csZoneLo"),
    "zion.contrastRatioCap": ("ml", "csCap"),
    "zion.contrastSkinProtect": ("ml", "csSkin"),
    "zion.contrastDebugVis": ("ml", "contrastVis"),
    "zion.barsRepaint": ("ml", "bars"),
    "zion.barsHighlight": ("ml", "barsHighlight"),
    "hdr.hdrPass": ("hdr", "raw"),
    "zion.debugCopyShaders": ("ml", "debugCopy"),
    "zion.debugFrameLog": ("ml", "debugLog"),
    "zion.skyEnabled": ("ml", "sky"),
    "zion.skyStrength": ("ml", "skyStr"),
    "zion.skyOverlay": ("ml", "skyVis"),
    "zion.personEnabled": ("ml", "person"),
    "zion.personStrength": ("ml", "persStr"),
    "zion.personOverlay": ("ml", "personOv"),
    "zion.skinPreserve": ("ml", "skinPres"),
    "hdr.preferDoVi": ("hdr", "preferDoVi"),
    "hdr.convertToSdr": ("hdr", "convSdr"),
    "hdr.sdrNits": ("hdr", "sdrNits"),
    "hdr.toneMapCurve": ("hdr", "curve"),
    "hdr.toggleDisplay": ("hdr", "toggle"),
    "hdr.maxNits": ("hdr", "dispNits"),
    "hdr.blackNits": ("hdr", "blackNits"),
    "hdr.titlePeak": ("hdr", "titlePeak"),
    "hdr.hableKnee": ("hdr", "hableKnee"),
    "hdr.softKnee":      ("hdr", "softKnee"),
    "hdr.softKneeRatio": ("hdr", "softKneeRatio"),
    "hdr.softKneeWidth": ("hdr", "softKneeWidth"),
    "hdr.refWhite":      ("hdr", "refWhite"),
    "hdr.highlightNeutral": ("hdr", "highlightNeutral"),
    "hdr.chromaExp":      ("hdr", "chromaExp"),
    "hdr.gtBlend":        ("hdr", "gtBlend"),
    "hdr.gtFade":         ("hdr", "gtFade"),
    "hdr.gtAdapt":        ("hdr", "gtAdapt"),
    "hdr.gtAlpha":        ("hdr", "gtAlpha"),
    "hdr.outputGamut": ("hdr", "gamut"),
    "hdr.osdBright": ("hdr", "osdBrt"),
    "hdr.expTm": ("hdr", "expTm"),
    "hdr.tmContrast": ("hdr", "tmContrast"),
    "hdr.tmPivot": ("hdr", "tmPivot"),
    # Post-render effects — delivered as MPCVR post-scale custom shaders, not
    # Settings_t. The engine's "postfx" group parses these names.
    "postfx.sharpen":      ("postfx", "sharpen"),
    "postfx.sharpenStr":   ("postfx", "sharpenStr"),
    "postfx.deband":       ("postfx", "deband"),
    "postfx.debandThresh": ("postfx", "dbThresh"),
    "postfx.debandRange":  ("postfx", "dbRange"),
    "postfx.debandIter":   ("postfx", "dbIter"),
    "postfx.debandGrain":  ("postfx", "dbGrain"),
    # pb.hdAudio is deliberately NOT here: it is a state-echo row (the engine owns the
    # mode and reports it), so push_all re-sending it on every graph generation made
    # the rail push a stale opposite value → mode flip → re-open → gen bump → push
    # again → infinite re-open loop. It is routed imperatively in _apply_engine so it
    # is only sent when the USER clicks it. Same reason pb.audioTrack is absent.
    "out.useD3D11": ("out", "d3d11"),
    "out.texFormat": ("out", "tex"),
    "out.vpNV12": ("out", "nv12"),
    "out.vpP01x": ("out", "p010"),
    "out.vpYUY2": ("out", "yuy2"),
    "out.vpOther": ("out", "other"),
    "out.deinterlace": ("out", "deint"),
    "out.deintDouble": ("out", "deintDb"),
    "out.deintBlend": ("out", "deintBl"),
    "out.superRes": ("out", "superRes"),
    "out.chromaScaling": ("out", "chroma"),
    "out.upscaling": ("out", "upsc"),
    "out.downscaling": ("out", "downsc"),
    "out.useDither": ("out", "dither"),
    "out.vBlank": ("out", "vblank"),
    "out.adjustPresent": ("out", "adjust"),
    "out.reinitDisplay": ("out", "reinit"),
    "out.shaderVP": ("out", "shaderVP"),
    "out.rtxVideoHdr": ("out", "rtxVideoHdr"),
    "out.interpolate50": ("out", "interpolate50"),
    "out.swapEffect": ("out", "swapEffect"),
    "out.exclusiveFS": ("out", "exclusiveFS"),
    "out.showStats": ("out", "showStats"),
    "sys.trayIcon": ("out", "tray"),
}

# Rows whose panel option INDEX is not MPCVR's enum value (IVideoRenderer.h).
# Cycle rows absent here send their index straight through.
#   zion.toneMode    panel Auto/Manual/Off  -> iMLMode 2/1/0 (0 = Disable)
#   hdr.toneMapCurve panel ACES..GT7        -> iHdrLocalToneMappingType 1..5,7,8
#   out.texFormat    panel Auto/8/10/16f    -> iTexFormat 0/8/10/16
VALUE_MAP = {
    "zion.toneMode":    [2, 1, 0],
    # 6 (ST.2094-10) has no panel entry — it is unreachable from this rail, as it
    # always was. GT7 is 8; SPLINE is 9 (the experimental mapper, now a first-class
    # tone-curve option — mutually exclusive with the named curves by construction).
    # GT7 ADAPT is 10: the same operator with the scene peak blended into its peak.
    # Appended last so every existing panel index keeps meaning what it meant.
    "hdr.toneMapCurve": [1, 2, 3, 4, 5, 7, 8, 9, 10],
    "out.texFormat":    [0, 8, 10, 16],
}

# Tone-curve engine values (IVideoRenderer.h TONE_CURVE_*), for the curve-
# conditional "CURVE SETTINGS" rows. Which dial feeds which curve was traced from
# ps_convert_pq_to_sdr.hlsl: maxCLL<-{GT7,BT2390,ST2094,Hable-fallback}, softKnee<-
# {Hable,GT7}, highlightNeutral<-{Hable}, refWhite<-{Hable,GT7}, chromaExp<-
# {Hable + the normalised curves}. ACES/Reinhard/Mobius normalise by sdrNits (not
# maxCLL); REFERENCE reads nothing; SPLINE reads only the scene stats.
CURVE_ACES, CURVE_REINHARD, CURVE_HABLE, CURVE_MOBIUS = 1, 2, 3, 4
CURVE_BT2390, CURVE_ST2094, CURVE_REF, CURVE_GT7, CURVE_SPLINE = 5, 6, 7, 8, 9
CURVE_GT7_ADAPT = 10
# GT7 Adapt shares the whole GT7 branch, so it reads everything GT7 reads — the
# metadata peak (as the static half of its blend), the soft-knee pre-compressor and
# ref white — plus gt7Adapt, which plain GT7 ignores.
CURVES_GT7BOTH  = {CURVE_GT7, CURVE_GT7_ADAPT}
CURVES_MAXCLL   = {CURVE_HABLE, CURVE_BT2390, CURVE_ST2094, CURVE_GT7, CURVE_GT7_ADAPT}
CURVES_SOFTKNEE = {CURVE_HABLE, CURVE_GT7, CURVE_GT7_ADAPT}
CURVES_REFWHITE = {CURVE_HABLE, CURVE_GT7, CURVE_GT7_ADAPT}
CURVES_NEUTRAL  = {CURVE_HABLE}
CURVES_CHROMA   = {CURVE_ACES, CURVE_REINHARD, CURVE_HABLE, CURVE_MOBIUS,
                   CURVE_BT2390, CURVE_ST2094}


class Row:
    def __init__(self, label, type_, group, key, section=None, options=None,
                 opt=0, min_=0, max_=100, val=50, default=50, gate=0,
                 on=False, live=True, uncheck=True, curves=None):
        self.label = label; self.type = type_; self.group = group; self.key = key
        self.section = section; self.options = options or []
        self.opt = opt; self.min = min_; self.max = max_; self.val = val
        self.default = default; self.gate = gate; self.on = on; self.live = live
        self.has_uncheck = uncheck
        # curves: set of TONE-CURVE engine values for which this row is VISIBLE.
        # None = always visible. Lets a dial that only matters for some curves
        # (e.g. highlight-neutral = Hable-only) hide itself otherwise.
        self.curves = curves
        self.text = ""               # FILE rows: the chosen path
        self.enabled = True          # per-control checkbox state


def build_rows():
    """Transcription of BuildRows()'s add(...) table."""
    # GROUPS index: 0 PLAYBACK · 1 SOURCE · 2 HDR · 3 ZION · 4 OUTPUT · 5 SYSTEM
    # (SOURCE has no rows of its own — its group mirrors the status rail)
    P, H, Z, O, S = 0, 2, 3, 4, 5
    r = []

    def add(label, type_, group, key, section=None, options=None, opt=0,
            min_=0, max_=100, val=50, default=50, gate=0, on=False,
            live=True, uncheck=True, curves=None):
        r.append(Row(label, type_, group, key, section, options, opt, min_, max_,
                     val, default, gate, on, live, uncheck, curves))

    # ── PLAYBACK — media-playback surface ────────────────────────────────────
    # Track rows have no engine backing yet (no track-list API across the C ABI);
    # they persist to the INI and become live once media player mode exposes it.
    add("Track", CYCLE, P, "pb.audioTrack", "AUDIO", ["—"], 0, uncheck=False)
    add("HD audio", CYCLE, P, "pb.hdAudio", "AUDIO",
        ["Bitstream", "PCM"], 0, uncheck=False)
    add("Delay", SLIDER, P, "pb.audioDelay", "AUDIO",
        min_=-500, max_=500, val=0, default=0, uncheck=False)
    add("Track", CYCLE, P, "pb.subTrack", "SUBTITLES", ["Off"], 0, uncheck=False)

    add("Enable ML grade", TOGGLE, Z, "zion.enabled", on=True)
    add("Mode",  CYCLE,  Z, "zion.toneMode", "TONE CURVE", ["Auto", "Manual", "Off"], 0)
    add("Shadow", SLIDER, Z, "zion.shadowToe", "TONE CURVE", max_=0.40, val=0, default=0, gate=2)
    add("Shadow dehaze", SLIDER, Z, "zion.shadowDehaze", "TONE CURVE", max_=1.0, val=0, gate=1)
    add("Gamma", SLIDER, Z, "zion.gamma", "TONE CURVE", min_=0.5, max_=1.5, val=1, default=1, gate=1)
    # Signed offset ADDED to the model's gamma in Auto — a top-up on the model's
    # per-scene judgement rather than a replacement for it. Additive, not a
    # multiplier: the model predicting 1.0 ("this scene needs no gamma") is a fixed
    # point for a multiplier, so a multiplier could never brighten the very scenes
    # a top-up exists for. It rides the shader's gamma block, whose fade/hi_g guards
    # keep it a midtone move — the highlights do not move.
    add("Gamma top-up", SLIDER, Z, "zion.gammaTopUp", "TONE CURVE",
        min_=-0.50, max_=0.50, val=0, default=0, gate=1)
    # MID-TONE TARGET — the grade's one closed-loop control, and the reason the
    # "Gamma top-up" above stops being something you have to ride.
    #
    # Every other Zion input is SOURCE-referred: the models read the pre-correction
    # frame, so they emit the same answer no matter what the tone curve did to the
    # picture. Change refWhite or SDR nits and the delivered mid-tone moves a long way
    # while the model's prediction does not move at all — which is what the manual
    # top-up has been quietly compensating for.
    #
    # This is the delivery-side target instead: the level (0 = black, 1 = white) you
    # want the scene average to END UP at. The renderer computes what the curve is
    # about to deliver for this source's average and solves for the gamma that lands it
    # here, so the grade becomes insensitive to the delivery.
    #
    # The payoff is the decoupling: "Scene ref white" goes back to doing one job —
    # how hard the shoulder works, i.e. highlight safety — and luminosity is set here
    # independently. Those two have been the same control, which is why brightening
    # the image kept costing the clouds. 0 = off, and off is today's behaviour exactly.
    add("Mid-tone target", SLIDER, Z, "zion.tgtMid", "TONE CURVE",
        min_=0.0, max_=0.95, val=0, default=0, gate=1)
    add("Highlight", SLIDER, Z, "zion.highlight", "TONE CURVE", min_=-0.3, max_=0.4, val=0, gate=1)
    add("Highlight shoulder", SLIDER, Z, "zion.highlightRolloffCtrl", "TONE CURVE",
        min_=-0.2, max_=0.2, val=0, gate=1)
    add("Mode",  CYCLE,  Z, "zion.chromaMode", "CHROMA", ["Default", "Manual", "Off"], 0)
    add("Ch-N", SLIDER, Z, "zion.chN", "CHROMA", min_=1.0, max_=1.3, val=1.08, default=1.08, gate=2)
    add("Ch-F", SLIDER, Z, "zion.chF", "CHROMA", min_=1.0, max_=1.3, val=1.15, default=1.15, gate=2)
    add("Knee", SLIDER, Z, "zion.knee", "CHROMA", min_=0.1, max_=0.9, val=0.45, default=0.45, gate=2, uncheck=False)
    add("Skin", SLIDER, Z, "zion.skin", "CHROMA", min_=0.5, max_=1.0, val=0.95, default=0.95, gate=2, uncheck=False)
    add("Enable", TOGGLE, Z, "zion.contrast", "MICRO CONTRAST", on=True)
    add("Strength", SLIDER, Z, "zion.contrastStrength", "MICRO CONTRAST", max_=0.5, val=0.15, default=0.15)
    add("Zone lo", SLIDER, Z, "zion.contrastZoneLo", "MICRO CONTRAST", max_=0.6, val=0.15, default=0.15)
    add("Ratio cap", SLIDER, Z, "zion.contrastRatioCap", "MICRO CONTRAST", min_=1.0, max_=2.0, val=1.4, default=1.4)
    add("Skin protect", SLIDER, Z, "zion.contrastSkinProtect", "MICRO CONTRAST", max_=1.0, val=0.65, default=0.65)
    add("HDR passthrough", TOGGLE, Z, "hdr.hdrPass", "DEBUG", live=False)
    add("Tone curve passthrough", TOGGLE, Z, "zion.debugCopyShaders", "DEBUG", live=False)
    add("Frame log", TOGGLE, Z, "zion.debugFrameLog", "DEBUG", live=False)
    add("MC heat", TOGGLE, Z, "zion.contrastDebugVis", "DEBUG", live=False)
    add("Repaint bars", TOGGLE, Z, "zion.barsRepaint", "BLACK BARS", on=True)
    add("Highlight bars", TOGGLE, Z, "zion.barsHighlight", "BLACK BARS")
    add("Enable", TOGGLE, Z, "zion.skyEnabled", "SKY SEG")
    add("Strength", SLIDER, Z, "zion.skyStrength", "SKY SEG", max_=1.0, val=0.6, default=0.6)
    add("Mask overlay", TOGGLE, Z, "zion.skyOverlay", "SKY SEG")
    add("Enable", TOGGLE, Z, "zion.personEnabled", "PERSON SKIN")
    add("Strength", SLIDER, Z, "zion.personStrength", "PERSON SKIN", max_=1.0, val=1.0, default=1.0)
    add("Mask overlay", TOGGLE, Z, "zion.personOverlay", "PERSON SKIN")
    add("Tone preserve", SLIDER, Z, "zion.skinPreserve", "PERSON SKIN", max_=1.0, val=0, default=0)

    # ON by default (PotPlayer parity). A DV Profile 5 file's base layer is
    # IPTPQc2 with no colour description in the VUI; the decoder tags it PQ, which
    # makes the renderer's HDR10/HLG branch win unless preferDoVi is set, and then
    # the RPU — the only thing that yields correct colour for P5 — is never read.
    # Inert on non-DV sources (no RPU to consume).
    add("Prefer DV over PQ/HLG", TOGGLE, H, "hdr.preferDoVi", "TONE MAPPING", on=True)
    add("Convert to SDR", TOGGLE, H, "hdr.convertToSdr", "TONE MAPPING", on=True, live=False)
    add("SDR display nits", SLIDER, H, "hdr.sdrNits", "TONE MAPPING", min_=25, max_=400, val=50, default=50, uncheck=False)
    # Index 4 = BT-2390, which is iHdrLocalToneMappingType's default (IVideoRenderer.h
    # sets it to 5, and VALUE_MAP shifts the panel index by +1). The shell used 2
    # here, but it populates rows by pulling the renderer, so its initial index
    # never reached anything — ours does, and 2 would have seeded Hable.
    # "Reference" (index 5 -> TONE_CURVE_REFERENCE 7) is the upstream
    # VideoRenderer-master converter kept verbatim — per-channel RGB Hable over a
    # fixed 4.8, reading none of the title metadata, scene peak, knee or ICtCp.
    # It exists to isolate a change: if the picture differs between "Hable" and
    # "Reference" the change is in the machinery around the curve, not in Hable.
    # It outranks the experimental mapper and ignores the knee; the Zion rows
    # (Gamma top-up) still apply — zero them for a clean A/B.
    # "GT7" (index 6 -> TONE_CURVE_GT7 8) is Polyphony Digital's operator: a game
    # tonemapper that takes luminance from a per-channel pass and chroma from the
    # ORIGINAL colour, fading it across the highlight band. It is the curve that
    # desaturates a warm head instead of carrying the source's grade at full
    # strength, which is what the I-channel + uniform-gain paths do.
    # "GT7 Adapt" (index 8 -> TONE_CURVE_GT7_ADAPT 10) is the GT7 operator with one
    # different input: the peak it maps FROM is the metadata peak blended toward the
    # measured scene peak. Use it where the peak is a guess (HDMI capture, DV, no
    # MaxCLL); where MaxCLL is real, plain GT7 is the stable choice and is unchanged.
    add("Tone curve", CYCLE, H, "hdr.toneMapCurve", "TONE MAPPING",
        ["ACES", "Reinhard", "Hable", "Mobius", "BT-2390", "Reference", "GT7", "Spline",
         "GT7 Adapt"], 4, uncheck=False)
    # ── CURVE SETTINGS — dials that only matter for specific tone curves ─────
    # Collapsible like any section; each row HIDES itself unless the selected Tone
    # curve actually reads it (see the CURVES_* sets above, traced from
    # ps_convert_pq_to_sdr.hlsl). This stops the rail offering dials that silently
    # do nothing for the active curve.
    #
    # Title peak = the content peak (maxCLL) the curves map FROM — NOT the display's
    # peak. Only GT7 / BT.2390 / ST.2094 read it directly; Hable uses it as the
    # fallback when the measured scene peak is unavailable. ACES/Reinhard/Mobius
    # normalise by sdrNits instead, and Reference/Spline read neither.
    add("Title peak (nits)", SLIDER, H, "hdr.titlePeak", "CURVE SETTINGS",
        min_=100, max_=4000, val=1000, default=1000, uncheck=False,
        curves=CURVES_MAXCLL)
    # Soft-plus pre-compressor (Hable + GT7): re-spreads the highlight band Hable
    # compresses least (the sky). 0 = off. The LOW default knee (0.21) is deliberate:
    # ultra-bright DV/HDR masters need compression to start early or the sky clips.
    # It is safe at a low knee because the compressor is detail-preserving (local base
    # + restored residual), so mid-tone texture no longer "oil-paints" at ratio>1.
    add("Soft knee (0=off)", SLIDER, H, "hdr.softKnee", "CURVE SETTINGS",
        min_=0, max_=4, val=0.21, default=0.21, uncheck=False, curves=CURVES_SOFTKNEE)
    add("Soft knee ratio", SLIDER, H, "hdr.softKneeRatio", "CURVE SETTINGS",
        min_=1.0, max_=5.0, val=2.48, default=2.48, uncheck=False, curves=CURVES_SOFTKNEE)
    add("Soft knee width", SLIDER, H, "hdr.softKneeWidth", "CURVE SETTINGS",
        min_=0.05, max_=1.0, val=0.42, default=0.42, uncheck=False, curves=CURVES_SOFTKNEE)
    # Scene reference white (Hable + GT7 + GT7 Adapt): the input-gain numerator.
    #
    # Default is 105, not libplacebo's 203, and the reason is measured rather than
    # inherited. In the adapted GT7 form only ONE quantity matters:
    #     peak compression = 2.2 * refWhite / sdrNits
    # (maxCLL cancels, because the gain divides by it), so refWhite is not a
    # per-title brightness knob -- it sets how hard the shoulder has to work, for
    # every title. 105 at an 85-nit target is 2.7x, and that single value was
    # validated on two of the most differently-distributed HDR masters available:
    # Everest (991 maxCLL / 220 maxFALL, ratio 4.5) and Furiosa (909 / 140, ratio
    # 6.5), both good, both with cloud texture intact.
    #
    # So the rule is refWhite ~= 1.24 * sdrNits -- 105 at 85, 248 at 200. The
    # libplacebo 203 is the value for a display with headroom; at 85 nits it asks
    # the shoulder for 5.2x and flattens the top of the range.
    add("Scene ref white (nits)", SLIDER, H, "hdr.refWhite", "CURVE SETTINGS",
        min_=50, max_=400, val=105, default=105, uncheck=False, curves=CURVES_REFWHITE)
    # Highlight neutral (Hable ONLY): pulls the top of the PQ->SDR output toward its
    # own luma (the measured warm-white-head fix). 0 = pre-feature picture.
    add("Highlight neutral (head)", SLIDER, H, "hdr.highlightNeutral", "CURVE SETTINGS",
        min_=0.0, max_=1.0, val=0.9, default=0.9, uncheck=False, curves=CURVES_NEUTRAL)
    # Chroma compensation exponent (Hable + the normalised curves). GT7 / Reference /
    # Spline carry their own chroma management and ignore it.
    add("Chroma desat (exp)", SLIDER, H, "hdr.chromaExp", "CURVE SETTINGS",
        min_=-1.0, max_=3.5, val=1.35, default=1.35, uncheck=False, curves=CURVES_CHROMA)
    # NOTE: the old "Hable knee" row is REMOVED. Its cbuffer slot (hableKnee,
    # cbuffer[14]) is declared but never read by any shader branch — dead since the
    # mobius-knee removal — so the dial could never do anything.
    # --- GT7 (Tone curve = GT7) -------------------------------------------------
    # Only read when curve 8 is selected. GT7 carries its OWN chroma management, so
    # "Chroma desat (exp)" and "Highlight neutral (head)" do nothing on it — this is
    # the pair that replaces them. Both are Polyphony's shipped constants by default.
    #
    # Blend: 0 = the raw per-channel curve (strongest de-warming of a highlight, and
    # the side that rotates hue elsewhere), 1 = luminance from that pass with the
    # source's chroma handed back. Measured on the warm-head sample, 0.6 sits at
    # yellow-delta +15 vs Hable's +25 at 400 nits.
    add("GT7 blend (ch<->UCS)", SLIDER, H, "hdr.gtBlend", "CURVE SETTINGS",
        min_=0.0, max_=1.0, val=0.6, default=0.6, uncheck=False, curves=CURVES_GT7BOTH)
    # The chroma fade window START. The width is fixed at GT's 0.18 on the engine
    # side, so one rail moves the whole window. NOTE the units: this is a ratio of
    # the ceiling's ICtCp I in PQ CODES, so 0.98 is ~201 nits and 1.16 is ~546 nits
    # at a 225-nit reference white — i.e. the window covers ordinary video
    # highlights, not the last 2% of the range the numbers imply.
    add("GT7 chroma fade from", SLIDER, H, "hdr.gtFade", "CURVE SETTINGS",
        min_=0.3, max_=2.0, val=0.98, default=0.98, uncheck=False, curves=CURVES_GT7BOTH)
    # GT7 ADAPT only (Tone curve = GT7 Adapt): how far the peak this curve maps FROM
    # moves from the metadata toward the measured scene peak.
    #   peak = maxCLL*(1-w) + measuredScenePeak*w
    # The measurement snaps on a detected scene cut (one frame) and then LOCKS, so
    # this tracks at cuts and never breathes inside a shot.
    # The endpoints are both pictures this box has already shown: 0.0 is plain GT7
    # (metadata alone — the stable HDR10-with-MaxCLL path), 1.0 is full scene
    # tracking, which is the auto-gain failure that blew the Everest night scenes.
    # 0.25 keeps a bad estimate to a quarter of the way, and a peak that is too HIGH
    # only costs a little exposure while one too LOW slams the highlights.
    add("GT7 adapt to scene peak", SLIDER, H, "hdr.gtAdapt", "CURVE SETTINGS",
        min_=0.0, max_=1.0, val=0.25, default=0.25, uncheck=False,
        curves={CURVE_GT7_ADAPT})
    # GT7 SHOULDER REACH — the control that unblocks brightness.
    #
    # GT7's shoulder lands on the display ceiling at a fixed multiple of it and
    # destroys everything above that point: 1.21x at 0.50, 1.47x at 0.25 (Polyphony's
    # value), 1.87x at 0.10. "Scene ref white" puts the content peak at
    # 2.2*refWhite/sdrNits times the ceiling — so raising refWhite to brighten the
    # picture walks content straight past that point and flattens the highlights.
    # That is why brightening has kept costing clouds all day: the two controls were
    # the same decision.
    #
    # LOWER = longer shoulder = more headroom before the clamp, so refWhite can rise
    # with the highlights intact. Raise it and the curve gets punchier but clips
    # sooner. 0.25 is exactly today's picture.
    add("GT7 shoulder reach (low = more headroom)", SLIDER, H, "hdr.gtAlpha", "CURVE SETTINGS",
        min_=0.02, max_=0.90, val=0.25, default=0.25, uncheck=False,
        curves=CURVES_GT7BOTH)
    # SDR output gamut. BT.709 is the standard target. BT.2020 keeps the source's
    # wider colour for a display whose gamut EXCEEDS Rec.709 — not a standards
    # target, and the display must be set to match. Only affects HDR sources:
    # the conversion shader does not run for SDR input.
    add("Output gamut", CYCLE, H, "hdr.outputGamut", "TONE MAPPING",
        ["BT.709 (standard)", "BT.2020 (wide)"], 0, uncheck=False)
    add("Windows HDR", CYCLE, H, "hdr.toggleDisplay", "DISPLAY TARGET",
        ["Do not change", "On (fullscreen)", "On", "On/off (fullscreen)", "On/off"], 0, uncheck=False)
    add("Static nits (max)", SLIDER, H, "hdr.maxNits", "DISPLAY TARGET", min_=200, max_=10000, val=1000, default=1000, uncheck=False)
    # The display's measured BLACK. The tone mapper builds its destination range
    # as [black, max]; at 0 it assumes an ideal black and compresses the shadow
    # end into a range the panel cannot show. Default 0 = previous behaviour.
    add("Display black (nits)", SLIDER, H, "hdr.blackNits", "DISPLAY TARGET",
        min_=0.0, max_=2.0, val=0, default=0, uncheck=False)
    add("Subtitle/OSD brightness", SLIDER, H, "hdr.osdBright", "DISPLAY TARGET", max_=100, val=0, default=0, uncheck=False)

    # ── Spline (experimental) tone-curve parameter ───────────────────────────
    # The spline is now a first-class "Tone curve" option (value 9), mutually
    # exclusive with the named curves — no separate on/off. This is its one real
    # dial: pl_tone_map_spline's "Contrast" (higher = steeper, closer to clip,
    # preserving midtones at the cost of shadow/highlight detail). libplacebo
    # range/default 0.00..1.50. Only meaningful when Tone curve = Spline.
    add("Spline contrast", SLIDER, H, "hdr.tmContrast", "CURVE SETTINGS",
        max_=1.50, val=0.50, default=0.50, uncheck=False, curves={CURVE_SPLINE})
    # LITMUS dial for the spline's black floor. The spline places its knee/pivot from
    # the SCENE AVERAGE; a bright average lifts the whole shadow band (high black
    # floor) and "Contrast" does not move it. This scales that average: 1.0 =
    # libplacebo as-is, drag DOWN to drop the pivot and deepen blacks. If lowering it
    # visibly drops the floor, the pivot is confirmed as the culprit and it becomes
    # the actuator the shadow model later drives.
    add("Spline shadow pivot", SLIDER, H, "hdr.tmPivot", "CURVE SETTINGS",
        min_=0.0, max_=1.0, val=1.0, default=1.0, uncheck=False, curves={CURVE_SPLINE})

    # ── POST-FX — post-render shaders (engine injection, not Settings_t) ──────
    # These run as MPCVR post-scale custom shaders: AFTER the tone-map + grade, on
    # the final SDR gamma image, before subtitles/dither — so they behave the same
    # on SDR, HDR10 and Dolby Vision. Strength is baked into the shader source, so
    # moving a dial regenerates + re-injects it (the engine dedups unchanged values).
    # Adaptive Sharpen (bacondither): edge-adaptive, tanh-limited against local
    # min/max, so it adds detail without ringing. 0.3..1.5; 1.0 is a strong default.
    add("Adaptive sharpen", TOGGLE, H, "postfx.sharpen", "POST-FX")
    add("Sharpen strength", SLIDER, H, "postfx.sharpenStr", "POST-FX",
        min_=0.3, max_=1.5, val=1.0, default=1.0, uncheck=False)
    # Deband (SmartDeband): flatten gradient banding the 10->8-bit tone-map creates,
    # then dither it with grain. Threshold is the cut-off (higher = stronger but eats
    # detail); Grain adds the covering noise (0 = none, pairs with the final dither).
    add("Deband", TOGGLE, H, "postfx.deband", "POST-FX")
    add("Deband threshold", SLIDER, H, "postfx.debandThresh", "POST-FX",
        min_=0, max_=256, val=32, default=32, uncheck=False)
    add("Deband range", SLIDER, H, "postfx.debandRange", "POST-FX",
        min_=1, max_=64, val=16, default=16, uncheck=False)
    add("Deband iterations", SLIDER, H, "postfx.debandIter", "POST-FX",
        min_=1, max_=4, val=1, default=1, uncheck=False)
    add("Deband grain", SLIDER, H, "postfx.debandGrain", "POST-FX",
        min_=0, max_=128, val=24, default=24, uncheck=False)

    # Defaults below are Settings_t::SetDefault() (IVideoRenderer.h:221), NOT
    # invented here: the shell populates its rows by PULLING the renderer at
    # startup, so a row the user has never touched must show what MPCVR is
    # actually doing. Ten of these were hardcoded OFF while MPCVR defaults them
    # ON — including bUseD3D11, which gates the whole DX11 path, and the four
    # VPFmts. Seeding an INI from those wrong defaults would have reconfigured
    # the renderer (D3D11 off, VP formats off, dither off) on first run.
    add("Use Direct3D 11", TOGGLE, O, "out.useD3D11", "VIDEO PROCESSING", on=True)
    add("Texture format", CYCLE, O, "out.texFormat", "VIDEO PROCESSING",
        ["Auto", "8-bit", "10-bit", "16-bit float"], 0, uncheck=False)
    add("VP NV12", TOGGLE, O, "out.vpNV12", "VIDEO PROCESSING", on=True)
    add("VP P01x", TOGGLE, O, "out.vpP01x", "VIDEO PROCESSING", on=True)
    add("VP YUY2", TOGGLE, O, "out.vpYUY2", "VIDEO PROCESSING", on=True)
    add("VP Other", TOGGLE, O, "out.vpOther", "VIDEO PROCESSING", on=True)
    add("Deinterlacing", CYCLE, O, "out.deinterlace", "VIDEO PROCESSING",
        ["Disable", "Enable", "Hack future frames"], 1, uncheck=False)
    add("Double frame rate", TOGGLE, O, "out.deintDouble", "VIDEO PROCESSING", on=True)
    add("Blend deint 4:2:0", TOGGLE, O, "out.deintBlend", "VIDEO PROCESSING")
    add("Shader VP resize", TOGGLE, O, "out.shaderVP", "VIDEO PROCESSING", on=True)
    add("Super Resolution", CYCLE, O, "out.superRes", "VIDEO PROCESSING",
        ["Disable", "SD", "720p", "1080p", "1440p"], 0, uncheck=False)
    add("RTX Video HDR", TOGGLE, O, "out.rtxVideoHdr", "VIDEO PROCESSING")
    add("Chroma upsampling", CYCLE, O, "out.chromaScaling", "VIDEO PROCESSING",
        ["Nearest", "Bilinear", "CatmullRom", "KrigBilateral"], 1, uncheck=False)
    add("Upscaling", CYCLE, O, "out.upscaling", "VIDEO PROCESSING",
        ["Nearest", "Mitchell", "CatmullRom", "Lanczos2", "Lanczos3", "Jinc2"], 2, uncheck=False)
    add("Downscaling", CYCLE, O, "out.downscaling", "VIDEO PROCESSING",
        ["Box", "Bilinear", "Hamming", "Bicubic", "BicubicSharp", "Lanczos"], 2, uncheck=False)
    add("Interpolate at 50%", TOGGLE, O, "out.interpolate50", "VIDEO PROCESSING", on=True)
    add("Use dithering", TOGGLE, O, "out.useDither", "VIDEO PROCESSING", on=True)
    add("Swap effect", CYCLE, O, "out.swapEffect", "OUTPUT", ["Discard", "Flip"], 1, uncheck=False)
    add("Exclusive fullscreen", TOGGLE, O, "out.exclusiveFS", "OUTPUT")
    add("Wait for VBlank", TOGGLE, O, "out.vBlank", "OUTPUT")
    add("Adjust present time", TOGGLE, O, "out.adjustPresent", "OUTPUT", on=True)
    add("Reinit on display change", TOGGLE, O, "out.reinitDisplay", "OUTPUT")
    add("Show statistics", TOGGLE, O, "out.showStats", "OUTPUT")

    # ── OUTPUT — display calibration ─────────────────────────────────────────
    # The projector was calibrated with DisplayCAL; the .cube it produced
    # describes the PANEL, so it is applied last (final pass) and is separate
    # from the tone mapper, which describes the SIGNAL. Click the path row to
    # pick a file; the enable toggle A/Bs it without losing the path.
    add("Calibration LUT", FILE, O, _LUT_PATH_KEY, "DISPLAY CALIBRATION")
    # Gamma only = the cube's neutral diagonal as a LUMINANCE shape, chromaticity
    # untouched — for a display whose grey balance was already set by hand.
    # Greyscale = per-channel diagonal (tone + balance, still no channel mixing).
    # Full 3D   = everything, including the gamut mapping that fades deep colour.
    add("LUT mode", CYCLE, O, _LUT_MODE_KEY, "DISPLAY CALIBRATION",
        _LUT_MODES, 3, uncheck=False)

    # ── OUTPUT — renderer frame capture ──────────────────────────────────────
    # Saves what the RENDERER actually drew (IBasicVideo::GetCurrentImage) to a
    # user-chosen PNG — not a window/desktop capture, so no overlay or
    # compositing ever enters the file. Key has no engine mapping: it is a
    # command, not a setting (KEY_MAP skips it on apply/ini).
    add("Save frame as PNG", ACTION, O, "__capFrame", "OUTPUT")

    add("Tray icon", TOGGLE, S, "sys.trayIcon", "App", on=True)
    return r


class S3ShellPanel(QWidget):
    """The settings panel; paints via a single QPainter pass like the GDI code."""

    def __init__(self, rows=None, ini=None, engine=None, parent=None):
        super().__init__(parent)
        _init_fonts()
        self.rows = rows if rows is not None else build_rows()
        self.ini = ini
        self.engine = engine
        # NOTE: there is deliberately NO registry sync here. MPCVR's
        # SaveSettings() writes the WHOLE Settings_t (~58 fields), including ones
        # this rail does not own — it persisted UseD3D11=0 and the next graph
        # build then took the DX9 path and stopped drawing entirely. State is
        # restored instead by re-pushing the INI whenever the engine reports a
        # new graph generation (see MainWindow._on_s3_status), which covers
        # everything this rail manages without touching fields it does not.
        self.group = 3               # ZION (g_sysGroup default)
        self.collapsed = set()
        self.mouse = QPoint(-1, -1)  # for hover
        self._layout = []            # [(is_header, text/idx, y, h)]
        self._values = {}            # key -> value (from INI)
        # The slider currently being dragged, or None. Set only by a press that
        # landed on a slider's track; see _on_slider_track for why that gate exists.
        self._active_slider = None
        for r in self.rows:
            self._apply_ini(r)
        self.setFixedWidth(RIGHT_W)
        self.setMouseTracking(True)          # section hover highlight + sliders
        saved = self.group
        max_h = 0
        for gi in range(len(GROUPS)):
            self.group = gi
            self._rebuild()
            max_h = max(max_h, self._content_h)
        self.group = saved
        self._rebuild()
        self.setFixedHeight(max_h + PAD)

    # ------------------------------------------------------------- ini bridge
    def _apply_ini(self, r):
        if not self.ini:
            return
        v = self.ini.get(r.key)
        if v is None:
            return
        if r.type == FILE:
            r.text = v.strip()
            return
        try:
            if r.type == TOGGLE:
                r.on = v.strip() in ("1", "true", "True", "on")
            elif r.type == CYCLE:
                r.opt = int(v)
            else:
                r.val = float(v)
        except (TypeError, ValueError):
            pass

    def _ini_value(self, r):
        """The value as the INI stores it — panel-native, so cycles keep their
        option index rather than the engine's translated enum.

        Sliders are written at the precision the field actually carries: an int
        field stores `51`, not `51.0`, and a float stores `0.4`, not
        `0.39999999999999997`. The file is meant to be read and hand-edited.
        """
        if r.type == TOGGLE:
            return r.on
        if r.type == FILE:
            return r.text
        if r.type == CYCLE:
            return r.opt
        return int(round(r.val)) if r.key in INT_SLIDERS else round(r.val, _SLIDER_DECIMALS)

    def seed_ini(self) -> int:
        """Write EVERY mapped row into the INI, so the config is complete.

        Rows only reached the INI when the user touched them, so a setting that
        had never been clicked lived nowhere: not pushed on attach, not
        preserved across a restart, and invisible to anyone reading the file.
        That is why five VIDEO PROCESSING rows (Texture format, Deinterlacing,
        Super Resolution, RTX Video HDR, Interpolate at 50%) were absent while
        their neighbours were present. Existing values win — this only fills in
        what is missing.
        """
        if not self.ini:
            return 0
        want = {}
        for r in self.rows:
            if r.key not in KEY_MAP:
                continue
            v = self._ini_value(r)
            # Also rewrite a value whose stored FORM differs (51.0 -> 51,
            # 0.39999999999999997 -> 0.4). The panel loaded it through
            # _apply_ini, so the rounded value is the same number — only the
            # spelling changes, and the file becomes readable.
            if self.ini.get(r.key) != str(v):
                want[r.key] = v
        if want:
            self.ini.update(want)
            log(f"ini: seeded/normalised {len(want)} keys -> {self.ini.path}")
        return len(want)

    def _set(self, r):
        if self.ini:
            self.ini.set(r.key, self._ini_value(r))

        # s3_shell.cpp: HDR passthrough and tone-curve passthrough are mutually
        # exclusive — turning either ON switches the other OFF. Both configs are
        # then re-pushed, because a stale "off" flag on the other one leaves the
        # renderer in copy mode and the picture never recovers — which is why
        # the two toggles looked identical.
        if r.type == TOGGLE and r.key in _PASSTHROUGH:
            if r.on:
                for other in self.rows:
                    if other.key in _PASSTHROUGH and other is not r and other.on:
                        other.on = False
                        if self.ini:
                            self.ini.set(other.key, False)
            for other in self.rows:
                if other.key in _PASSTHROUGH:
                    self._apply_engine(other)
            return

        self._apply_engine(r)

    # ------------------------------------------------------------- engine bridge
    def _engine_value(self, r):
        """The value to send for row r. The INI stores the panel-native value
        (index into r.options); enums where that index is not MPCVR's value are
        translated here (VALUE_MAP, IVideoRenderer.h)."""
        if r.type == TOGGLE:
            return r.on
        if r.type == CYCLE:
            table = VALUE_MAP.get(r.key)
            if table and 0 <= r.opt < len(table):
                return table[r.opt]
            return r.opt
        return r.val

    def _push_lut(self) -> None:
        """Send the display LUT as a COMMAND, not a flat setting.

        The renderer holds no path in Settings_t — it is told to load a file.
        Sending an empty path clears it, which is how the enable toggle turns the
        LUT off without losing the chosen file.
        """
        if self.engine is None:
            return
        path_row = next((x for x in self.rows if x.key == _LUT_PATH_KEY), None)
        mode_row = next((x for x in self.rows if x.key == _LUT_MODE_KEY), None)
        if path_row is None or mode_row is None:
            return
        mode = mode_row.opt
        # Mode 0 means off, so the file is cleared rather than merely bypassed —
        # that also frees the texture.
        path = path_row.text if mode > 0 else ""
        try:
            self.engine.load_cube_lut(path, mode)
            log(f"lut -> {path or '(cleared)'} mode={mode}")
        except Exception:
            log_exc("push_lut")

    def _apply_engine(self, r):
        if self.engine is None:
            return
        if r.key in (_LUT_PATH_KEY, _LUT_MODE_KEY):
            self._push_lut()
            return
        # Audio track is imperative (s3_cmd "track"), not a settings key — the
        # option index IS the audio-relative track index the engine expects.
        if r.key == "pb.audioTrack":
            try:
                self.engine.select_audio_track(int(r.opt))
                log(f"ui-corr: apply {r.key} -> track {r.opt}")
            except (TypeError, ValueError):
                pass
            return
        # Audio mode likewise: only sent on a real user click (options are
        # ["Bitstream","PCM"] → engine 1/0). Kept out of KEY_MAP so push_all never
        # re-sends it and re-triggers the mode→re-open→gen→push feedback loop.
        if r.key == "pb.hdAudio":
            self.engine.set_audio_mode(1 if int(r.opt) == 0 else 0)
            log(f"ui-corr: apply {r.key} -> mode {1 if int(r.opt) == 0 else 0}")
            return
        mp = KEY_MAP.get(r.key)
        if not mp:
            return
        grp, name = mp
        val = self._engine_value(r)
        # UI-layer correlation line: WHAT the rail sent, timestamped, so it can be
        # lined up ms-for-ms with the engine's "[SETTINGS] received <key> = <val>"
        # and the renderer's "[SHADER-CB] push ..." — three layers, one value.
        log(f"ui-corr: apply {r.key} -> {val}")
        try:
            self.engine.apply_settings({grp: {name: val}})
        except Exception:
            log_exc(f"apply_engine {r.key}")

    def _row(self, key):
        for r in self.rows:
            if r.key == key:
                return r
        return None

    def set_audio_state(self, tracks, current_i, mode):
        """Refresh the PLAYBACK audio rotate rows from the engine's audio block.
        Sets options + current WITHOUT pushing to the engine (no feedback loop) —
        the engine is the source of truth for which track is active and the mode."""
        at = self._row("pb.audioTrack")
        if at is not None and tracks:
            import re
            def _label(t, i):
                # LAV's stream name is descriptive, e.g.
                #   "A: Deutsch TrueHD Atmos 7.1 NIMA4K [ger] (truehd atmos, 48000 Hz, 7.1, s24) [default]"
                # Strip the pin prefix, the "(format)" parenthetical and the "[lang]/
                # [default]" tags to get a readable "Deutsch TrueHD Atmos 7.1".
                nm = (t.get("name") or "").strip()
                if nm:
                    s = re.sub(r'^[A-Za-z]:\s*', '', nm)   # "A: " / "S: " / "V: "
                    s = re.sub(r'\([^)]*\)', '', s)         # drop "(truehd atmos, 48000 Hz, …)"
                    s = re.sub(r'\[[^\]]*\]', '', s)        # drop "[ger]" "[default]"
                    s = " ".join(s.split()).strip()
                    if s:
                        return s
                lang = (t.get("lang") or "").strip()        # fallback if name is empty
                return lang or f"Track {i + 1}"
            at.options = [_label(t, i) for i, t in enumerate(tracks)]
            at.opt = max(0, min(int(current_i), len(at.options) - 1))
        hd = self._row("pb.hdAudio")
        if hd is not None:
            hd.opt = 0 if int(mode) == 1 else 1     # options ["Bitstream", "PCM"]
        self.update()   # repaint the custom-drawn rail

    def push_all(self):
        """Push every mapped INI value to the engine once (engine startup)."""
        if self.engine is None:
            return
        groups = {}
        for r in self.rows:
            mp = KEY_MAP.get(r.key)
            if not mp:
                continue
            grp, name = mp
            groups.setdefault(grp, {})[name] = self._engine_value(r)
        if groups:
            try:
                self.engine.apply_settings(groups)
            except Exception:
                log_exc("push_all")
        # The LUT is not a flat setting, so it is pushed separately — and on every
        # graph generation, like everything else, or a rebuild would drop it.
        self._push_lut()

    # ------------------------------------------------------------ layout
    def _active_curve(self):
        """The engine value of the currently selected Tone curve (or None)."""
        row = self._row("hdr.toneMapCurve")
        if row is None:
            return None
        table = VALUE_MAP.get(row.key)
        if table and 0 <= row.opt < len(table):
            return table[row.opt]
        return row.opt

    def _rebuild(self):
        active = self._active_curve()
        rows = [r for r in self.rows if r.group == self.group]
        self._layout = []
        y = LIST_TOP + 60
        prev = None
        skip = False
        for r in rows:
            # Curve-conditional rows: a dial that only matters for some curves
            # (highlight-neutral = Hable-only, soft-knee = Hable+GT7, …) hides
            # itself otherwise. Checked BEFORE the section header so a section
            # whose rows are all hidden emits no header.
            if r.curves is not None and active not in r.curves:
                continue
            # A section header is emitted only for rows that HAVE a section
            # (shell: `r->section && wcscmp(...)` — "Enable ML grade" has none).
            if r.section is not None and r.section != prev:
                self._layout.append((True, r.section, -1, y, SECT_H))
                y += SECT_H
                prev = r.section
                skip = r.section in self.collapsed
            if skip:
                continue
            self._layout.append((False, r.label, self.rows.index(r), y, ROW_H))
            y += ROW_H
        self._content_h = y
        # (height is fixed once in __init__ — never resize here)

    def sizeHint(self):
        return self.minimumSizeHint()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), PANEL)

        # icon rail
        for i, (glyph, label, tint, _cats) in enumerate(GROUPS):
            top = LIST_TOP + i * ICON_STEP
            g = QRect(0, top, RAIL_W, ICON_H)
            active = (i == self.group)
            if active:
                p.fillRect(g, ACTIVE_BG)
                p.fillRect(QRect(0, top, 3, ICON_H), ACCENT)
            p.setFont(F_GLYPH.get(glyph, F_ICON)); p.setPen(tint)
            p.drawText(QRect(0, top + 6, RAIL_W, 32), Qt.AlignmentFlag.AlignCenter, glyph)
            p.setFont(F_RAIL)
            p.setPen(TEXT if active else MID)
            p.drawText(QRect(0, top + 38, RAIL_W, 20), Qt.AlignmentFlag.AlignCenter, label)
        # (no rail divider — the panel reads as one surface)

        # content
        x0 = RAIL_W
        p.setFont(F_CAT); p.setPen(MID)
        p.drawText(QRect(x0 + PAD, LIST_TOP + 8, RIGHT_W - PAD, CAT_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "  ·  ".join(GROUPS[self.group][3]))

        # (no rule above the first row)

        for is_header, text, idx, y, h in self._layout:
            if is_header:
                self._paint_section(p, text, y)
            else:
                self._paint_row(p, self.rows[idx], y)

    def _paint_section(self, p, title, y):
        # Content area starts at x0 = RAIL_W; chevron + title + separator line
        # (mirrors the shell's PaintRight loop exactly).
        x0 = RAIL_W
        collapsed = title in self.collapsed
        hot = (x0 + PAD <= self.mouse.x() and y <= self.mouse.y() < y + SECT_H)
        # Subgroup header — the same treatment as the status panel's _SEC_STYLE
        # (accent orange, bold, tracked). Chevron tracks the title so the header
        # reads as one accent element; hover brightens to ACCENT2.
        tint = ACCENT2 if hot else ACCENT
        p.setFont(F_SECTION)
        p.setPen(tint)
        p.drawText(QRect(x0 + PAD, y, 18, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "▶" if collapsed else "▼")
        p.drawText(QRect(x0 + PAD + 18, y, RIGHT_W - PAD - (x0 + PAD + 18), 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        # (no rule under section headers — the accent title carries it)

    def _paint_row(self, p, r, y):
        is_slider = r.type == SLIDER
        # label
        p.setFont(F_LABEL); p.setPen(TEXT)
        lb = QRect(RAIL_W + PAD + 6, y,
                   (RAIL_W + 150 - 8) if is_slider else (RIGHT_W - 150),
                   ROW_H)
        p.drawText(lb, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, r.label)

        if is_slider:
            self._paint_slider(p, r, y)
            return

        if r.type == FILE:
            # DisplayCAL .cube filenames carry the whole calibration in the name
            # (target, gamma, black-point), so elide rather than truncate — the
            # tail is the informative half.
            ct = QRect(RIGHT_W - CONTROL_W, y, CONTROL_W - PAD, ROW_H)
            name = Path(r.text).name if r.text else "Set…"
            p.setFont(F_STATUS)
            p.setPen(TEXT if r.text else LO)
            fm = QFontMetrics(p.font())
            p.drawText(ct, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(name, Qt.TextElideMode.ElideMiddle, ct.width()))
            return

        if r.type == ACTION:
            # Command row: right-aligned CTA that reads as clickable.
            ct = QRect(RIGHT_W - CONTROL_W, y, CONTROL_W - PAD, ROW_H)
            p.setFont(F_STATUS)
            p.setPen(ACCENT2 if r.text else ACCENT)
            p.drawText(ct, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "Save…")
            return

        ct = QRect(RIGHT_W - CONTROL_W, y, CONTROL_W - PAD, ROW_H)
        if r.type == TOGGLE:
            w = 46; h = 22
            sw = QRect(ct.right() - w, y + (ROW_H - h) // 2, w, h)
            p.fillRect(sw, ACCENT if r.on else QColor(0x2A, 0x2A, 0x2E))
            p.setPen(QPen(ACCENT2 if r.on else BORDER, 1)); p.drawRect(sw)
            p.setFont(F_STATUS)
            p.setPen(QColor(0, 0, 0) if r.on else MID)
            p.drawText(sw, Qt.AlignmentFlag.AlignCenter, "ON" if r.on else "OFF")
        else:  # cycle
            p.setFont(F_VALUE); p.setPen(MID)
            opt = r.options[r.opt] if r.options else "?"
            p.drawText(ct.adjusted(0, 0, 0, 0), Qt.AlignmentFlag.AlignRight |
                       Qt.AlignmentFlag.AlignVCenter, f"〈  {opt}  〉")

    def _paint_slider(self, p, r, y):
        if r.has_uncheck:
            cb = QRect(RAIL_W + 150 + 2, y + (ROW_H - 18) // 2, 18, 18)
            p.fillRect(cb, ACCENT if r.enabled else QColor(0x24, 0x24, 0x28))
            p.setPen(QPen(ACCENT2 if r.enabled else BORDER, 1)); p.drawRect(cb)

        box = 28 if r.has_uncheck else 4
        band = QRect(RAIL_W + 150 + box, y + ROW_H * 2 // 5,
                     RIGHT_W - PAD - 58 - (RAIL_W + 150 + box), ROW_H // 5)
        p.fillRect(band, TEXT)
        span = band.width()
        frac = int((r.val - r.min) / (r.max - r.min) * span) if r.max > r.min else 0
        if frac > 0:
            p.fillRect(QRect(band.left(), band.top(), frac, band.height()), ACCENT)
        cx = band.left() + frac
        p.fillRect(QRect(cx - 6, band.top() - 4, 12, band.height() + 8), ACCENT2)
        # min / max
        p.setFont(F_STATUS); p.setPen(MID)
        p.drawText(QRect(band.left(), band.bottom() + 3, 40, 16),
                   Qt.AlignmentFlag.AlignLeft, _fmt_num(r.min))
        p.drawText(QRect(band.right() - 40, band.bottom() + 3, 40, 16),
                   Qt.AlignmentFlag.AlignRight, _fmt_num(r.max))
        # value
        p.setFont(F_VALUE); p.setPen(TEXT)
        vr = QRect(RIGHT_W - 58, y, 58 - PAD, ROW_H)
        p.drawText(vr, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _fmt_num(r.val))

    # ------------------------------------------------------------ interaction
    def _hit(self, y):
        for is_header, text, idx, yy, h in self._layout:
            if yy <= y < yy + h:
                return is_header, idx, text
        return None, -1, None

    def mousePressEvent(self, e):
        try:
            self._press(e)
        except Exception:
            log_exc("mousePressEvent")

    def _press(self, e):
        x, y = int(e.position().x()), int(e.position().y())
        log(f"press ({x},{y})")
        # icon rail
        if x < RAIL_W:
            i = (y - LIST_TOP) // ICON_STEP
            if 0 <= i < len(GROUPS):
                log(f"switch rail group -> {i}")
                self.group = i
                self._rebuild(); self.update()
            return
        is_header, idx, text = self._hit(y)
        log(f"hit header={is_header} idx={idx}")
        if is_header:
            (self.collapsed.remove(text) if text in self.collapsed
             else self.collapsed.add(text))
            self._rebuild(); self.update()
            return
        if idx < 0:
            return
        r = self.rows[idx]
        if r.type == TOGGLE:
            r.on = not r.on; self._set(r)
            log(f"toggle {r.key} -> {r.on}")
        elif r.type == CYCLE:
            r.opt = (r.opt + 1) % len(r.options); self._set(r)
            log(f"cycle {r.key} -> {r.opt}")
            # Changing the tone curve changes which dials are relevant — re-lay
            # out so the CURVE SETTINGS rows show/hide immediately.
            if r.key == "hdr.toneMapCurve":
                self._rebuild()
        elif r.type == FILE:
            self._pick_lut_file(r)
        elif r.type == ACTION:
            self._save_frame_png(r)
        else:
            # Only a press ON the track starts a drag. A press on the row's label is
            # not a value change — it used to be, and it set the slider to whatever
            # the label's x implied (the minimum, for anything left of the track).
            self._active_slider = r if self._on_slider_track(r, x) else None
            if self._active_slider is not None:
                self._drag_slider(r, x)
                log(f"slider {r.key} -> {r.val:g}")
            else:
                log(f"slider {r.key} row pressed off-track at x={x} — value unchanged")
        self.update()

    def _pick_lut_file(self, r):
        """A FILE row opens a picker; choosing a .cube loads it immediately."""
        from PyQt6.QtWidgets import QFileDialog

        start = str(Path(r.text).parent) if r.text else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose display calibration LUT", start,
            "Cube LUT (*.cube);;All files (*)")
        if not path:
            return
        r.text = path
        log(f"lut file -> {path}")
        self._set(r)

    def _save_frame_png(self, r):
        """Save the renderer's CURRENT output frame to a user-chosen PNG.

        The engine grabs via IBasicVideo::GetCurrentImage (the frame the renderer
        actually drew — no desktop/window compositing, so no Snipping-Tool-style
        overlay/tone-capture mismatch). The engine writes a BMP; Qt converts to
        PNG so the file is lossless. Outcome is both logged and shown in a
        message box; success is deterministic (engine log has meanLuma + size).
        """
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import os
        import tempfile

        path, _ = QFileDialog.getSaveFileName(
            self, "Save frame as PNG",
            str(Path.home() / "unplugged_frame.png"),
            "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if self.engine is None:
            QMessageBox.warning(self, "Save frame", "Engine not loaded")
            return
        fd, tmp = tempfile.mkstemp(suffix=".bmp")
        os.close(fd)
        try:
            rc = self.engine.capture_frame(tmp)
            if rc != 0:
                raise RuntimeError(f"engine grab failed hr=0x{rc:08X} "
                                   "(engine log has the reason)")
            img = QImage(tmp)
            if img.isNull():
                raise RuntimeError("engine returned no frame image")
            if not img.save(path, "PNG"):
                raise RuntimeError("PNG write failed")
            log(f"frame saved -> {path} ({img.width()}x{img.height()})")
            QMessageBox.information(
                self, "Frame saved",
                f"Saved renderer frame to:\n{path}\n{img.width()} × {img.height()}")
        except Exception as e:   # noqa: BLE001
            log(f"frame save FAILED: {e}")
            QMessageBox.warning(self, "Save frame", f"Failed:\n{e}")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _drag_slider(self, r, x):
        lo, hi = self._slider_span(r)
        frac = (x - lo) / (hi - lo) if hi > lo else 0
        frac = max(0.0, min(1.0, frac))
        val = r.min + frac * (r.max - r.min)
        # Quantise to the precision the field actually carries — an int field
        # would otherwise be truncated downstream while the rail showed the
        # fraction, and a float keeps 2 decimals so the readout stays readable.
        r.val = float(int(round(val))) if r.key in INT_SLIDERS \
            else round(val, _SLIDER_DECIMALS)
        self._set(r)

    @staticmethod
    def _slider_span(r) -> tuple:
        """The draggable x-range of a slider row as (lo, hi).

        ONE definition, shared by the paint, the press gate and the drag, so the
        clickable area can never disagree with the drawn track.
        """
        box = 28 if r.has_uncheck else 4
        lo = RAIL_W + 150 + box
        return lo, RIGHT_W - PAD - 58

    @staticmethod
    def _on_slider_track(r, x) -> bool:
        """True when x is on the slider's TRACK rather than its label.

        This gate is the fix for a setting that changed itself. Both the press and
        the move path used to act on the whole ROW: a click on a slider's label (far
        left of the track) or a drag that merely passed over the row called
        _drag_slider with whatever x the cursor had. Left of the track that clamps
        frac to 0.0, so the value became the slider's MINIMUM — hdr.sdrNits snapped
        to 25 — and _set() persisted it to the INI, which is why it survived a
        restart. A generous knob radius is allowed so grabbing the handle still
        works.
        """
        lo, hi = S3ShellPanel._slider_span(r)
        return (lo - 8) <= x <= (hi + 8)

    def mouseMoveEvent(self, e):
        try:
            self.mouse = e.position().toPoint()
            # Drag ONLY the slider whose track was pressed, and only while the button
            # is still down. Choosing the row by y alone (as this did) meant a drag
            # that merely passed over a slider row rewrote that setting from the
            # cursor's x — at the left it silently pinned the value to the minimum.
            if e.buttons() & Qt.MouseButton.LeftButton and self._active_slider is not None:
                self._drag_slider(self._active_slider, int(e.position().x()))
            self.update()
        except Exception:
            log_exc("mouseMoveEvent")

    def mouseReleaseEvent(self, _e):
        # End the drag. Without this the next move — anywhere — would keep dragging
        # the last-touched slider.
        self._active_slider = None

    def leaveEvent(self, _e):
        self.mouse = QPoint(-1, -1)
        self.update()


class SettingsIni:
    """key=value INI next to the executable; debounced 400 ms save."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_ini_path()
        self.values = {}
        self._dirty = False
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    self.values[k.strip()] = v.strip()
        except OSError:
            pass

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value) -> None:
        self.values[key] = str(value)
        self._dirty = True
        self.save()

    def update(self, pairs: dict) -> None:
        """Merge several values and write once — seeding ~60 keys through set()
        would hit the disk once per key."""
        if not pairs:
            return
        for k, v in pairs.items():
            self.values[k] = str(v)
        self._dirty = True
        self.save()

    def save(self) -> None:
        """Write the INI. A failure is LOGGED, never swallowed.

        Silently ignoring the write makes an unwritable settings file look
        exactly like settings that work and then vanish on the next restart.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# unplugged engine settings (s3_shell schema)"]
            lines += [f"{k}={self.values[k]}" for k in sorted(self.values)]
            self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            log(f"ini: SAVE FAILED {self.path}: {e}")


def default_ini_path() -> Path:
    """Where the settings INI lives — ONE location for every launch mode.

    Dev and the installed build share `%LOCALAPPDATA%\\Unplugged\\s3_shell.ini`,
    so a value tuned in one is live in the other. They used to differ (dev kept
    a repo-local copy), which meant tuning in the dev run silently did nothing
    for the installed app.

    It is per-user rather than beside the exe because the installer targets
    C:\\Program Files\\Unplugged, where a standard user cannot write — and
    SettingsIni.save() used to swallow that failure, so settings would appear to
    work and then quietly not survive a restart.

    Falls back to the app directory only if the per-user location is unusable
    (no LOCALAPPDATA, or a locked-down profile).
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        d = Path(base) / "Unplugged"
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d / "s3_shell.ini"
        except OSError:
            log(f"ini: cannot use {d}, falling back to the app directory")
    # parents[3] is the app root in dev and the exe directory when frozen.
    return Path(__file__).resolve().parents[3] / "s3_shell.ini"

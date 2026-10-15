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

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, pyqtSignal
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
# Same gold the HDR group's rail icon uses, reused for a locked HDR input so "signal
# present" and "HDR" read the same way in both places.
GOLD = QColor(0xC8, 0xA0, 0x30)

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

# Group index for the SOURCE page. Module-level because set_source_state() builds rows at
# runtime, outside build_rows() where the other indices are local names.
SRC = 1

TOGGLE, CYCLE, SLIDER = "toggle", "cycle", "slider"
FILE = "file"          # a path row: click opens a picker, value is a filename
ACTION = "action"      # a command row: click runs an action (no stored value)
# A DeckLink input port: one row per physical port, generated at runtime by
# set_source_state() rather than declared in build_rows() (the port set is a property of
# the hardware, not of the settings table). Clicking one does NOT change anything in the
# panel — it emits input_selected(url) and main_window performs the switch, because the
# engine call, the INI write and the mode flip all belong there.
PORT = "port"

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
INT_SLIDERS = {"hdr.sdrNits", "hdr.maxNits", "hdr.osdBright", "hdr.titlePeak", "postfx.debandIter",
               "hdr.exposureTrim", "hdr.shadowLift", "hdr.punch"}

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
    "zion.ctl": ("ml", "ctl"),
    "zion.ctlWhite": ("ml", "ctlWhite"),
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
    "hdr.gtDesat":        ("hdr", "gtDesat"),
    "hdr.gamutCap":       ("hdr", "gamutCap"),
    # Delivered through the grade's chroma pass (Settings_t.fMLHiDesat), but keyed on the
    # level the viewer receives, so it is named and placed as a delivery control.
    "hdr.hiDesat":        ("hdr", "hiDesat"),
    "hdr.gt7Dbg":         ("hdr", "gt7Dbg"),
    "hdr.exposureTrim":   ("hdr", "expTrim"),
    "hdr.shadowLift":     ("hdr", "shLift"),
    "hdr.punch":          ("hdr", "punch"),
    "hdr.autoRefW":       ("hdr", "autoRefW"),
    "hdr.refWTgt":        ("hdr", "refWTgt"),
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
    "hdr.toneMapCurve": [1, 2, 3, 4, 5, 7, 8, 9, 10, 11],
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

# ---- the Tone curve row's two faces -----------------------------------------
# By default the rail offers exactly the two curves that are supported and
# validated: Reference (Hable) for DV of any provenance, GT7 Adapt for HDR10. The
# other eight exist, work, and are a maintenance and mis-selection surface — ten
# options for what is in practice a two-way decision.
#
# DISPLAY NAME: the Hable-based curve is shown as "Unplugged". Its engine and code
# identity is unchanged — TONE_CURVE_REFERENCE, value 7, "reference" in logs and in
# the renderer — because renaming those would churn every comment, commit and skill
# note that cites them. Only what a human reads in the rail and the status panel
# carries the new name.
#
# `ui.showAllTonemappers=true` in the INI (hand-edited; no row, no UI, never
# written by the app) restores the full list for development and A/B work. That is
# the whole mechanism: a config-only escape hatch, invisible to everyone who does
# not go looking in the file.
CURVE_KEY = "hdr.toneMapCurve"
CURVE_ALL = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11]
CURVE_ALL_LABELS = ["ACES", "Reinhard", "Hable", "Mobius", "BT-2390", "Unplugged",
                    "GT7", "Spline", "GT7 Adapt", "Dynamic & Auto"]
CURVE_SIMPLE = [7, 10]
CURVE_SIMPLE_LABELS = ["Unplugged", "GT7 Adapt"]
CURVE_ALL_INI_KEY = "ui.showAllTonemappers"

# The same escape hatch, for rows marked dev=True: hand-edited, never written by the
# app, never a row of its own. Absent means the internals stay hidden.
#   ui.showGradeInternals=true   -> reveals the soft-knee trio (and any future dev row)
# Hiding is a visibility filter only: the rows still read the INI and still push, so a
# value set by hand is honoured exactly as if the dial were on screen.
DEV_INI_KEY = "ui.showGradeInternals"
# Marks the INI's hdr.toneMapCurve value as an ENGINE value rather than an option
# index. Needed because the two formats overlap on eight of ten values: a stored 5 was
# "Reference" as an index (the sixth option) but is BT-2390 as an engine value. Guessing
# between them silently changes the curve, which is the one thing this row must never
# do. Written by seed_ini the first time the new format is saved; absent means legacy.
CURVE_FMT_KEY = "ui.curveValueIsEngine"
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
                 on=False, live=True, uncheck=True, curves=None, dev=False,
                 wide=False, payload=""):
        self.label = label; self.type = type_; self.group = group; self.key = key
        self.section = section; self.options = options or []
        self.opt = opt; self.min = min_; self.max = max_; self.val = val
        self.default = default; self.gate = gate; self.on = on; self.live = live
        self.has_uncheck = uncheck
        # curves: set of TONE-CURVE engine values for which this row is VISIBLE.
        # None = always visible. Lets a dial that only matters for some curves
        # (e.g. highlight-neutral = Hable-only) hide itself otherwise.
        self.curves = curves
        # dev: hidden unless the INI carries ui.showGradeInternals (see DEV_INI_KEY).
        # For dials that are machinery rather than taste — three interlocking sliders
        # that describe one behaviour, where a wrong combination can produce artefacts
        # (the soft-knee set is the current tenant: its residual interaction is what
        # turned dark flecks inside an explosion black). The row is HIDDEN, not removed:
        # the INI key still applies and still pushes, exactly like the tone-curve escape
        # hatch, so an expert can set it by hand without anyone else being able to
        # discover it by dragging.
        self.dev = dev
        # wide: the VALUE gets the whole content area and the row's own label is dropped.
        # For rows whose value IS the information — the audio and subtitle track names the
        # splitter reports ("Deutsch TrueHD Atmos 7.1", "English SDH (VobSub)") — the 132 px
        # control column elides them into unreadability, and the label ("Track") adds nothing
        # the subgroup header (AUDIO / SUBTITLES) doesn't already say.
        self.wide = wide
        # payload: PORT rows carry the decklink:// URL here (the label is the friendly
        # name, which is not unique and is user-editable, so it cannot be the key).
        self.payload = payload
        self.text = ""               # FILE rows: the chosen path
        self.enabled = True          # per-control checkbox state


def build_rows():
    """Transcription of BuildRows()'s add(...) table."""
    # GROUPS index: 0 PLAYBACK · 1 SOURCE · 2 HDR · 3 ZION · 4 OUTPUT · 5 SYSTEM
    # SOURCE rows are declared here but the port list itself is generated at runtime by
    # set_source_state() — the panel cannot know the hardware's port count at build time.
    P, H, Z, O, S = 0, 2, 3, 4, 5
    r = []

    def add(label, type_, group, key, section=None, options=None, opt=0,
            min_=0, max_=100, val=50, default=50, gate=0, on=False,
            live=True, uncheck=True, curves=None, dev=False, wide=False,
            payload=""):
        r.append(Row(label, type_, group, key, section, options, opt, min_, max_,
                     val, default, gate, on, live, uncheck, curves, dev, wide,
                     payload))

    # ── PLAYBACK — media-playback surface ────────────────────────────────────
    # Track rows have no engine backing yet (no track-list API across the C ABI);
    # they persist to the INI and become live once media player mode exposes it.
    add("Track", CYCLE, P, "pb.audioTrack", "AUDIO", ["—"], 0, uncheck=False, wide=True)
    add("HD audio", CYCLE, P, "pb.hdAudio", "AUDIO",
        ["Bitstream", "PCM"], 0, uncheck=False)
    add("Delay", SLIDER, P, "pb.audioDelay", "AUDIO",
        min_=-500, max_=500, val=0, default=0, uncheck=False)
    add("Track", CYCLE, P, "pb.subTrack", "SUBTITLES", ["Off"], 0, uncheck=False, wide=True)

    add("Enable ML grade", TOGGLE, Z, "zion.enabled", on=True)
    # JOINT BAND CONTROLLER. Solves the three grade actuators (shadow pedestal, gamma,
    # highlight rolloff) TOGETHER so the delivered p25/p50/p95 land on house targets,
    # inverting the grade's own closed-form chain per frame.
    #
    # This replaces stacking three independently-trained corrections: in the shader
    # they compose sequentially (toe, then gamma, then rolloff) while each model was
    # trained as if it acted alone on the source, so a power applied after an additive
    # lift rescales that lift and neither knows. The solver accounts for the
    # composition exactly.
    #
    # ON:  the controller owns pedestal/gamma/rolloff. The legacy multiplicative toe
    #      and the manual top-up stand down, because stacking them would double-act.
    # OFF: today's behaviour exactly.
    add("Band controller", TOGGLE, Z, "zion.ctl", "TONE CURVE", on=False)
    # HOUSE WHITE — RETIRED. Pinned at MlSettings::ctlWhite = 203, which is not a
    # taste value: 203 cd/m² is ITU-R BT.2408's diffuse-white convention, cited at
    # Source/csputils.h:104 as MP_REF_WHITE and used by libplacebo as PL_COLOR_SDR_WHITE.
    # It is also the PQ code pair the grade passes normalise by (SDR_PEAK_NITS 203 /
    # SDR_I_PEAK_PQ 0.5893 in ictcp.hlsl), so the number is load-bearing elsewhere and
    # letting a user move it here only made the two disagree.
    #
    # What the row actually did was never what this label claimed. The 1 - exp(-src/W)
    # law it referred to was replaced months ago by the relative form
    #     target = clamp(level * r^0.75, delivered anchor)   ,  level = 203 / ctlWhite
    # so the dial is now an INVERTED scalar on a curve — higher value = less lift — and
    # at the standards value level is exactly 1.0, i.e. the control was a no-op sitting
    # in the middle of its own slider. Range 100..400 maps to level 2.0..0.51, and the
    # level is clamped to [0.5, 2.0] anyway, so most of the travel did nothing.
    #
    # The one measured value in the retired comment above ("~335 = cloud-safe") is
    # suspect: it predates the fix that makes the band controller predict the curve
    # ACTUALLY RUNNING. On the Unplugged curve the old GT7-based model under-predicted
    # the delivered anchors by up to 0.058 of white through the 42-203 nit range, so the
    # controller was lifting past the picture — and backing house white off to 335 is
    # exactly how you would compensate for that without noticing. If clouds come back as
    # a complaint, the honest place to fix it is the 0.75 exponent or the [0.5,2.0]
    # authority clamp (both taste, neither measured), not a user-facing scalar.
    #
    # The ml.ctlWhite parse stays, so the value remains reachable for A/B without a rail
    # control that can be nudged.
    # add("House white (nits)", SLIDER, Z, "zion.ctlWhite", "TONE CURVE",
    #     min_=100, max_=400, val=203, default=203, gate=1)
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
    # Hidden (dev=True) but NOT removed: the value still lives in the INI and push_all
    # still sends it, so the DV-over-PQ behaviour it selects is unchanged — only the row is
    # gone from the rail. It is a renderer-internals escape hatch, the same class as the
    # soft-knee trio, and leaving it discoverable invited exactly the misconfiguration it
    # exists to override.
    add("Prefer DV over PQ/HLG", TOGGLE, H, "hdr.preferDoVi", "TONE MAPPING", on=True, dev=True)
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
    # "Dynamic & Auto" (index 9 -> TONE_CURVE_DYNAMIC_AUTO 11) is not a curve with
    # settings — the curve itself is SOLVED per scene from the source distribution
    # against fixed house targets, so there is no content peak to enter and no
    # reference white to choose. It ignores Title peak, refWhite, shoulder reach, the
    # knee dials and Adapt entirely. This is the one to use for DV P7 over HDMI, where
    # the stream carries no ST 2086 at all and every other curve is guessing.
    add("Tone curve", CYCLE, H, "hdr.toneMapCurve", "TONE MAPPING",
        ["ACES", "Reinhard", "Hable", "Mobius", "BT-2390", "Unplugged", "GT7", "Spline",
         "GT7 Adapt", "Dynamic & Auto"], 4, uncheck=False)
    # Exposure trim: -3..+3 in thirds of a stop, an INPUT gain applied before the curve
    # on Reference and on the DV identity transfer. Stepped and small on purpose — it is
    # a taste control, and the moment a brightness lever needs a nits value it stops
    # being one. Input gain rather than output: brightening after the curve clips,
    # brightening before it is absorbed by the shoulder.
    add("Exposure trim (1/3 stops)", SLIDER, H, "hdr.exposureTrim", "TONE MAPPING",
        min_=-5, max_=5, val=0, default=0, uncheck=False)
    # S-curve taste, on Reference and the DV identity transfer only.
    # Shadow DETAIL, not shadow lift: it redistributes slope (c' = 1-(1-c)^q), so +
    # spreads dark values apart and reveals their texture while black stays pinned at
    # zero. An additive lift was tried first and rejected — it greys the image and buys
    # no detail. Punch blends toward (or away from) an S about mid code. 0 on both is an
    # exact no-op, so every existing look is safe.
    add("Shadow detail", SLIDER, H, "hdr.shadowLift", "TONE MAPPING",
        min_=-5, max_=5, val=0, default=0, uncheck=False)
    add("Punch", SLIDER, H, "hdr.punch", "TONE MAPPING",
        min_=-5, max_=5, val=0, default=0, uncheck=False)
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
    #
    # HIDDEN BY DEFAULT (dev=True) — three sliders that describe ONE behaviour, and the
    # first drafts of this comment described their interaction wrongly. Measured
    # 2026-10-12/13 on an explosion: knee 0.21 + ratio 2.0 put the local base far above
    # the compressed value, the restored residual carried a large negative constant, and
    # dark detail inside the bright region rendered as BLACK pixels — which read as
    # "clipping" and was nothing of the kind. The compressor is now bounded against that
    # (gt7_tonemap.hlsl: keep <= comp/base), so these values are safe, but a user cannot
    # be expected to hold the interaction of three dials that only make sense together.
    # The INI keys still apply and still push, so an expert can tune them by hand.
    add("Soft knee (0=off)", SLIDER, H, "hdr.softKnee", "CURVE SETTINGS",
        min_=0, max_=4, val=0.21, default=0.21, uncheck=False, curves=CURVES_SOFTKNEE,
        dev=True)
    add("Soft knee ratio", SLIDER, H, "hdr.softKneeRatio", "CURVE SETTINGS",
        min_=1.0, max_=5.0, val=2.48, default=2.48, uncheck=False, curves=CURVES_SOFTKNEE,
        dev=True)
    add("Soft knee width", SLIDER, H, "hdr.softKneeWidth", "CURVE SETTINGS",
        min_=0.05, max_=1.0, val=0.42, default=0.42, uncheck=False,
        curves=CURVES_SOFTKNEE, dev=True)
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
    # RETIRED 2026-10-12 — the row above says "refWhite ~= 1.24 * sdrNits" and then this
    # slider let a user type any number from 50 to 400 anyway. It did: a manual 203.8 at a
    # 127-nit target placed the master's peak at 3.53x the ceiling, GT7's shoulder ran out
    # at 1.87x and min(blended, ceiling) flattened everything between — measured, and the
    # reason explosions clipped while ordinary frames looked fine (nothing else lives that
    # high). The renderer now caps refWhite at the shoulder's own reach (Gt7Reach/sdrNits/
    # 2.2, divided by the exposure trim), which makes any value at or above the cap
    # indistinguishable: a dial whose top two-thirds does nothing is not a control, it is
    # a trap. refWhite is pinned in the engine (HdrSettings::refWhiteNits) and the cap
    # enforces the rest; the honest brightness lever on this curve is "GT7 shoulder
    # reach" (gtAlpha), which buys headroom instead of spending it.
    #
    # Kept in the engine and in Settings_t on purpose: the value is still reachable for
    # A/B work without restoring a rail control, and removing the field would shift the
    # Settings_t layout the filter and the engine share.
    # add("Scene ref white (nits)", SLIDER, H, "hdr.refWhite", "CURVE SETTINGS",
    #     min_=50, max_=400, val=105, default=105, uncheck=False, curves=CURVES_REFWHITE)
    # AUTO EXPOSURE. refWhite was a per-title hand dial: Everest wants ~80, a dark
    # indoor master ~200, and nothing in the metadata says which (one title's MaxFALL
    # of 944 on an indoor drama predicted 20 where 200 was right). What separates them
    # is the measured scene average, so the renderer now solves refWhite from it:
    #     refWhite = T^2.2 * sdrNits * peak / (2.2 * sceneAvg)
    # cut-gated and slew-limited so it moves at scene changes and holds inside a shot.
    # When ON this row's slider is an OVERRIDE and is ignored; when OFF it is the whole
    # story, as it always was. GT7 / GT7 Adapt only — Hable normalises differently.
    # OFF by default, deliberately. The solver is bounded by the shoulder reach now,
    # but its input can lock onto a dark opening frame and set a whole title's
    # exposure from it. Opt in once the anchor is trustworthy; until then the
    # refWhite dial is the honest tool.
    add("Auto exposure", TOGGLE, H, "hdr.autoRefW", "CURVE SETTINGS",
        on=False, curves=CURVES_GT7BOTH)
    # Where the scene average should land, as a fraction of display white. 0.42 is a
    # conventional bright-scene average for SDR; raise for a brighter house look,
    # lower for a darker one. This is the ONE number that replaces per-title refWhite.
    add("Exposure target", SLIDER, H, "hdr.refWTgt", "CURVE SETTINGS",
        min_=0.20, max_=0.70, val=0.42, default=0.42, uncheck=False,
        curves=CURVES_GT7BOTH)
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
    # GT7 DEBUG VIEW — diagnostic. Replaces the picture with one internal quantity of
    # the operator, as greyscale, so a spatial seam shows up as a visible edge instead
    # of having to be inferred from the finished frame. Set it, look at where the seam
    # is, set it back to Off.
    #   chroma scale   the fade's actual output (banding source if it edges)
    #   fade ratio     position inside the fade window
    #   knee crossing  BINARY: where the toe hands to the shoulder (hard contour)
    #   ceiling cross  BINARY: where the pre-clamp value exceeds the ceiling
    add("GT7 debug view", CYCLE, H, "hdr.gt7Dbg", "CURVE SETTINGS",
        ["Off", "Chroma scale", "Fade ratio", "Knee crossing", "Ceiling crossing"], 0,
        uncheck=False, curves=CURVES_GT7BOTH)
    add("GT7 shoulder reach (low = more headroom)", SLIDER, H, "hdr.gtAlpha", "CURVE SETTINGS",
        min_=0.02, max_=0.90, val=0.25, default=0.25, uncheck=False,
        curves=CURVES_GT7BOTH)
    # GT7 DESATURATION — chroma follows the compression, not the gamut.
    #
    # A cobalt HDR sky is comfortably INSIDE the BT.709 triangle, so gamut mapping has
    # no jurisdiction over it and nothing overflowed to fix. The problem is different:
    # SDR at 85 nits cannot carry that much chroma at that luminance without it reading
    # garish. What has to give is saturation, in proportion to how hard the tone curve
    # compressed the luminance — which is what madVR does and we did not.
    #
    # This passes a fraction of the shoulder's own compression through to chroma by
    # moving each pixel toward its neutral point, so HUE is preserved and only
    # saturation is removed. Below the shoulder's knee the compression is 1, so
    # midtones are untouched — it cannot become a global wash.
    # 0 = off (today's picture). Raise it until the sky sits where you want it.
    add("GT7 desaturation", SLIDER, H, "hdr.gtDesat", "CURVE SETTINGS",
        min_=0.0, max_=1.0, val=0.0, default=0.0, uncheck=False,
        curves=CURVES_GT7BOTH)
    # SDR output gamut. BT.709 is the standard target. BT.2020 keeps the source's
    # wider colour for a display whose gamut EXCEEDS Rec.709 — not a standards
    # target, and the display must be set to match. Only affects HDR sources:
    # the conversion shader does not run for SDR input.
    add("Output gamut", CYCLE, H, "hdr.outputGamut", "TONE MAPPING",
        ["BT.709 (standard)", "BT.2020 (wide)"], 0, uncheck=False)
    # GAMUT CAPACITY — only does anything when Output gamut is BT.709.
    #
    # Measured on the Everest sky: we rendered R=0, G=64, B=119 at a gamut fill of
    # exactly 1.00 — sitting ON the edge of the 709 triangle — while madVR rendered
    # the same patch at fill 0.48..0.60 with red present at 25..40. A colour with no
    # red is maximally saturated for its lightness, so that edge position IS the
    # cobalt. "Inside the gamut" was never the safe state: the edge is inside the
    # gamut, and a clamp cannot see it because zero is not below zero.
    #
    # This lands each colour at a fraction of its OWN distance to the boundary. Pale
    # colours have a long distance and are untouched at any setting, so this cannot
    # become a global desaturation; only colours crowded against the edge get pulled
    # in, proportionally to how crowded they are.
    #
    # 1.00 = off (no mapping inside the gamut). ~0.55 is what madVR's sky measures at.
    add("Gamut capacity (709)", SLIDER, H, "hdr.gamutCap", "TONE MAPPING",
        min_=0.20, max_=1.00, val=1.00, default=1.00, uncheck=False)
    # HIGHLIGHT DESATURATION — the level-linked term these curves do not have.
    #
    # Measured on the Dune 12 dusk sky against madVR, seven bands (fillmap.ps1): madVR's
    # gamut fill FALLS as level rises (0.60 -> 0.54 -> 0.43 -> 0.31) while ours RISES
    # (0.74 -> 0.83 -> 0.80 -> 0.57), and RED is the channel that pays — 62 -> 41 and
    # 78 -> 52 codes at matched luma. Less red in a blue-dominant pixel is what reads as
    # cyan. Shadows match madVR to within 0.04, so this is not inherited from the master;
    # it is a desaturation that is simply absent on the Unplugged curve, where "Highlight
    # neutral" and "Chroma desat (exp)" are never read at all (they belong to GT7).
    #
    # It sits with the gamut controls, not in the grade tab, because it is a DELIVERY
    # decision keyed on the level the viewer receives. Mechanically it runs after the band
    # steps (so a grade lift or crush is accounted for) inside the chroma pass, which means
    # it needs "Enable ML grade" on — and on GT7-Adapt, highlightNeutral and GT7 desat pull
    # in this same band too, so the value fitted on curve 7 may be too strong there.
    #
    # Window is fitted, not chosen: smoothstep over I_norm 0.45 -> 0.70, mean error 0.014
    # against the seven measured anchors (a linear ramp to the ceiling scored 0.125, and
    # its failure was the reported symptom — 13% engaged where the cyan lives, 93% on the
    # speculars it should not touch). Skin is protected by the grade's P(skin) weight.
    # 0 = off, byte-identical. 0.50 is the value fitted to curve 7.
    add("Highlight desat", SLIDER, H, "hdr.hiDesat", "TONE MAPPING",
        min_=0.0, max_=1.0, val=0.0, default=0.0, uncheck=False)
    # ── DISPLAY TARGET — per-display calibration, visible and interactive ────
    # These are the numbers a display's measurement report fills in: the ceiling
    # (Static nits), the floor (Display black) and the Windows HDR mode. Set-once-per-
    # display rather than per-title, but they are USER values — a new projector or a
    # re-lamp means new numbers, so the section stays interactive. (Briefly dev-hidden on
    # 2026-10-15 and reverted the same day: hiding the only place a measured calibration
    # can be entered saves nothing and costs the ability to calibrate at all.)
    add("Windows HDR", CYCLE, H, "hdr.toggleDisplay", "DISPLAY TARGET",
        ["Do not change", "On (fullscreen)", "On", "On/off (fullscreen)", "On/off"], 0,
        uncheck=False)
    # min_ was 200, which made a measured 174-nit projector impossible to enter by hand —
    # the slider clamped it back up. Projectors live well below 200 nits.
    add("Static nits (max)", SLIDER, H, "hdr.maxNits", "DISPLAY TARGET", min_=10,
        max_=10000, val=1000, default=1000, uncheck=False)
    # The display's measured BLACK. The tone mapper builds its destination range
    # as [black, max]; at 0 it assumes an ideal black and compresses the shadow
    # end into a range the panel cannot show. Default 0 = previous behaviour.
    add("Display black (nits)", SLIDER, H, "hdr.blackNits", "DISPLAY TARGET",
        min_=0.0, max_=2.0, val=0, default=0, uncheck=False)
    add("Subtitle/OSD brightness", SLIDER, H, "hdr.osdBright", "DISPLAY TARGET", max_=100,
        val=0, default=0, uncheck=False)

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
    r[-1].text = "Save…"      # the ACTION branch draws this CTA, not the label

    add("Tray icon", TOGGLE, S, "sys.trayIcon", "App", on=True)

    # ── SOURCE — DeckLink inputs ─────────────────────────────────────────────
    # set_source_state() inserts the port rows ABOVE these three, so "Rescan" stays put
    # as the list grows. Keys starting "src." are imperative (they emit action_requested)
    # and are deliberately absent from KEY_MAP, so push_all() can never re-send them at
    # startup — the same rule the audio/subtitle track rows follow.
    add("⟳  Rescan inputs", ACTION, SRC, "src.rescan", "Input Device")
    add("✎  Rename inputs…", ACTION, SRC, "src.rename", "Input Device")
    add("▶  First-time setup… (restarts app)", ACTION, SRC, "src.setup", "Input Device")
    # Same action from the app-level page too: someone hunting for "re-run setup" is
    # likelier to open System than Source, and one key means one handler.
    add("▶  First-time setup… (restarts app)", ACTION, S, "src.setup", "App")
    return r


class S3ShellPanel(QWidget):
    """The settings panel; paints via a single QPainter pass like the GDI code."""

    # A DeckLink port row was clicked. The panel changes NOTHING itself: switching the
    # input means an engine call, an INI write and possibly a mode flip, all of which
    # belong to main_window (and are already implemented in _on_input_changed).
    input_selected = pyqtSignal(str)          # the decklink:// URL
    # An "src." action row was clicked (rescan / rename / first-time setup).
    action_requested = pyqtSignal(str)        # the row key

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
        # Read before any layout pass: _rebuild() filters dev rows on it, and a row that
        # is hidden must never be painted on the first frame and removed on the second.
        self.show_internals = self._ini_flag(DEV_INI_KEY)
        self.collapsed = set()
        self.mouse = QPoint(-1, -1)  # for hover
        self._layout = []            # [(is_header, text/idx, y, h)]
        self._values = {}            # key -> value (from INI)
        # The slider currently being dragged, or None. Set only by a press that
        # landed on a slider's track; see _on_slider_track for why that gate exists.
        self._active_slider = None
        for r in self.rows:
            self._apply_ini(r)
        # The Tone curve row's option list depends on a hidden INI flag, so it is
        # configured AFTER the generic INI pass (which would otherwise interpret the
        # stored value against the wrong table).
        self.show_all_curves = self._ini_flag(CURVE_ALL_INI_KEY)
        self._configure_curve_row()
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
                if r.key == CURVE_KEY:
                    return   # interpreted against the active table, below
                r.opt = int(v)
            else:
                r.val = float(v)
        except (TypeError, ValueError):
            pass

    def _ini_flag(self, key) -> bool:
        """A hand-edited INI boolean. Never written by the app, never shown as a row:
        the point of these flags is configuration without a surface."""
        if not self.ini:
            return False
        v = self.ini.get(key)
        if v is None:
            return False
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    def _configure_curve_row(self) -> None:
        """Point the Tone curve row at the table the hidden flag selected, and resolve
        whatever the INI holds — engine value (current format) or option index (legacy)
        — into an option of THAT table.

        A value the active table does not offer falls back to GT7 Adapt rather than to
        the nearest neighbour: silently substituting one curve for another is exactly
        the class of surprise this rail has spent a year eliminating, and GT7 Adapt is
        the safe HDR default while Reference is the DV one (the auto-default below
        picks between them per signal).
        """
        row = self._row(CURVE_KEY)
        if row is None:
            return
        table = CURVE_ALL if self.show_all_curves else CURVE_SIMPLE
        labels = CURVE_ALL_LABELS if self.show_all_curves else CURVE_SIMPLE_LABELS

        engine = None
        raw = self.ini.get(CURVE_KEY) if self.ini else None
        as_engine = self._ini_flag(CURVE_FMT_KEY)
        if raw is not None:
            try:
                v = int(str(raw).strip())
            except (TypeError, ValueError):
                v = None
            if v is not None:
                if as_engine:
                    engine = v if v in CURVE_ALL else None
                elif 0 <= v < len(CURVE_ALL):
                    engine = CURVE_ALL[v]                   # legacy: index into the list
                elif v in CURVE_ALL:
                    engine = v                              # already an engine value
        if engine is None or engine not in table:
            engine = CURVE_GT7_ADAPT if CURVE_GT7_ADAPT in table else table[0]

        VALUE_MAP[CURVE_KEY] = list(table)
        row.options = list(labels)
        row.opt = table.index(engine)

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
            # The curve row stores its ENGINE value, not an option index: the option
            # list changes shape with the hidden show-all flag, and an index that
            # meant "GT7" in a ten-option list must not silently become "GT7 Adapt"
            # in a two-option one.
            if r.key == CURVE_KEY:
                return self._engine_value(r)
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
        # The hidden flag is seeded as well, defaulting to false, so the escape hatch is
        # DISCOVERABLE by reading the file instead of known only from documentation or
        # from someone telling you. It has no row and the app never sets it true; an
        # existing value wins, exactly like every other key here.
        if self.ini.get(CURVE_ALL_INI_KEY) is None:
            want[CURVE_ALL_INI_KEY] = False
        # From this run on the curve row's stored value is an engine value; say so in
        # the file so the next run does not have to guess between the two formats.
        if self.ini.get(CURVE_FMT_KEY) is None:
            want[CURVE_FMT_KEY] = True
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
        # Subtitle track: option 0 is "Off" (MPC-HC's subtitle menu has that entry), so the
        # engine's subtitle-relative index is the option index minus one. Imperative like
        # the audio row — never part of KEY_MAP, so push_all cannot re-send it.
        if r.key == "pb.subTrack":
            try:
                idx = int(r.opt) - 1
                self.engine.select_subtitle_track(idx)
                log(f"ui-corr: apply {r.key} -> subtrack {idx}")
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

    def set_subtitle_state(self, tracks, current_i):
        """Populate the PLAYBACK Subtitles rotate row from the engine's subtitle block.

        Options stay ["Off", track1, track2, ...] — MPC-HC's subtitle menu leads with the
        same Off entry, and _apply_engine maps option -> engine index by minus one. Set
        WITHOUT pushing back to the engine: the engine is the source of truth for which
        stream is enabled, so a poll must not echo a selection."""
        row = self._row("pb.subTrack")
        if row is None:
            return
        import re
        labels = ["Off"]
        for i, t in enumerate(tracks or []):
            # LAV names subtitle streams "S: Deutsch Forced (SRT) [ger]". Keep the "(SRT)"
            # — unlike audio, where the format parenthetical is noise, here it is the one
            # thing that tells a text track from a bitmap one, which decides whether the
            # style row can do anything at all.
            nm = re.sub(r'^[A-Za-z]:\s*', '', (t.get("name") or "").strip())
            nm = re.sub(r'\[[^\]]*\]', '', nm)
            # LAV appends its own machine codec tag after the human one, so the raw name
            # reads "Deutsch Forced (SRT) (subrip)" and "Deutsch SDH (PGS) (pgs)". Drop the
            # machine one by name — a blanket "lowercase parenthetical" rule would take
            # "(auto)" off "Forced Subtitles (auto)", which is the only thing that says what
            # that entry does.
            # Case matters: LAV's machine tag is lowercase ("(pgs)") and the human one is
            # mixed ("(PGS)"). Matching case-insensitively strips both and leaves three
            # tracks named "Deutsch Forced" indistinguishable.
            nm = re.sub(r'\((?:subrip|vobsub|pgs|ass|ssa|mov_text|dvb_teletext|text)\)',
                        '', nm)
            nm = " ".join(nm.split()).strip()
            labels.append(nm or (t.get("lang") or "").strip() or f"Track {i + 1}")
        row.options = labels
        try:
            cur = int(current_i)
        except (TypeError, ValueError):
            cur = -1
        row.opt = 0 if cur < 0 else max(0, min(cur + 1, len(labels) - 1))
        self.update()

    def set_source_state(self, ports, active_url, labels=None):
        """Rebuild the SOURCE group's port rows from a live poll of the DeckLink card.

        Called from main_window's port timer — NEVER from paint: poll_all_ports() is a
        ctypes call into decklink_monitor.dll and paintEvent runs at the panel's refresh
        rate. `ports` is the list of PortStatus (url/locked/unknown/dr_label), `labels`
        the url -> friendly-name map from AppConfig.

        Like set_audio_state/set_subtitle_state this does not push anything: the engine
        and the INI are main_window's, and the rail is showing what is already true.
        """
        labels = labels or {}
        rows = [r for r in self.rows if r.type != PORT]
        new = []
        for port in ports or []:
            url = getattr(port, "url", "") or ""
            row = Row("", PORT, SRC, f"src.port.{url}", "Input Device")
            row.payload = url
            row.on = bool(active_url) and url == active_url
            name = labels.get(url) or self._default_port_name(url)
            row.label = name
            if getattr(port, "locked", False):
                row.text = f"🔒  {getattr(port, 'dr_label', '') or 'SDR'}"
            elif getattr(port, "unknown", False):
                row.text = "—  unknown"
            else:
                row.text = "○  no signal"
            new.append(row)
        # Above the action rows, so "Rescan"/"Rename" don't move as the list grows.
        at = next((i for i, r in enumerate(rows)
                   if r.type == ACTION and (r.key or "").startswith("src.")), len(rows))
        self.rows = rows[:at] + new + rows[at:]
        self._rebuild()
        self.update()

    @staticmethod
    def _default_port_name(url: str) -> str:
        """A readable name for a port nobody has labelled yet.

        decklink://<device> and decklink://<device>@<n> are what the enumerator produces;
        the raw URL is what the config stores, so it stays the key — this is only the
        label shown when the user hasn't named the input themselves.
        """
        s = url.split("://", 1)[-1]
        dev, _, port = s.partition("@")
        if port.isdigit():
            return f"{dev} · in {int(port) + 1}"
        return dev

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
            # Machinery, not taste: hidden unless ui.showGradeInternals is set by hand.
            # Visibility only — the row still holds its INI value and still pushes.
            if r.dev and not self.show_internals:
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

    def _paint_port_row(self, p, r, y):
        """One DeckLink input: ● when active, its friendly name, and a live signal badge.

        The active row also gets the rail's selection fill behind it. The dot alone is
        not enough — at this font size ● and ○ are a two-pixel difference, and picking the
        wrong HDMI input is the kind of mistake that looks like a broken capture rather
        than a wrong setting."""
        rect = QRect(RAIL_W + 2, y, RIGHT_W - RAIL_W - 4, ROW_H)
        if r.on:
            p.fillRect(rect, ACTIVE_BG)
        p.setFont(F_VALUE)
        p.setPen(ACCENT if r.on else MID)
        p.drawText(QRect(rect.left() + 6, y, 18, ROW_H),
                   Qt.AlignmentFlag.AlignCenter, "●" if r.on else "○")
        p.setFont(F_LABEL)
        p.setPen(TEXT if r.on else MID)
        name = QRect(rect.left() + 26, y, rect.width() - 26 - 120, ROW_H)
        fm = QFontMetrics(p.font())
        p.drawText(name, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(r.label, Qt.TextElideMode.ElideRight, name.width()))
        # r.text carries the badge ("🔒 HDR PQ", "○ No signal", "— unknown"), right-aligned
        # in the same control column every other row type uses.
        badge = QRect(rect.right() - 118, y, 112, ROW_H)
        p.setFont(F_STATUS)
        locked = r.text.startswith("🔒")
        p.setPen(GOLD if locked else (MID if r.on else LO))
        p.drawText(badge, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   r.text or "")

    def _paint_row(self, p, r, y):
        if r.type == PORT:
            self._paint_port_row(p, r, y)
            return
        is_slider = r.type == SLIDER
        # label — except on wide rows, where the value takes the label's space (see Row.wide)
        if not (getattr(r, "wide", False) and r.type == CYCLE):
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
            # Command row: right-aligned CTA that reads as clickable. The CTA text lives on
            # the row (set where it is declared) rather than being hardcoded here, because
            # the SOURCE actions are self-describing labels — "⟳ Rescan inputs" needs no
            # second verb squeezed into the control column.
            if not r.text:
                return
            ct = QRect(RIGHT_W - CONTROL_W, y, CONTROL_W - PAD, ROW_H)
            p.setFont(F_STATUS)
            p.setPen(ACCENT2 if r.text else ACCENT)
            p.drawText(ct, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       r.text)
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
            if r.wide:
                # Same grammar as every other cycle row - a chevron at each end with the
                # value between them, centred - but across the whole content area instead of
                # the 132 px control column, and with the redundant "Track" label dropped
                # (the subgroup header already says AUDIO or SUBTITLES). Keeping the
                # brackets around the text matters: chevrons standing alone at the right
                # edge read as a separate widget, and the name looked unclaimed.
                left   = RAIL_W + PAD + 6
                right  = RIGHT_W - PAD
                chevW  = 20
                live   = bool(r.options) and len(r.options) > 1
                fm = QFontMetrics(p.font())
                p.setPen(ACCENT2 if live else BORDER)
                p.drawText(QRect(left, y, chevW, ROW_H),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "‹")
                p.drawText(QRect(right - chevW, y, chevW, ROW_H),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "›")
                avail = max(right - chevW - (left + chevW) - 4, 40)
                p.setPen(TEXT)
                p.drawText(QRect(left + chevW + 2, y, avail, ROW_H),
                           Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(opt, Qt.TextElideMode.ElideMiddle, avail))
                return
            # Elide in the middle, and leave room for the bracket markers: track names come
            # straight from the splitter ("Deutsch Forced (SRT)", "English SDH (VobSub)")
            # and both ends carry information — the language at the front, the format that
            # decides whether styling applies at the back. Drawing the raw string simply ran
            # off the right edge and cut the tail mid-letter.
            fm = QFontMetrics(p.font())
            room = ct.width() - fm.horizontalAdvance("〈  〉") - 2
            shown = fm.elidedText(opt, Qt.TextElideMode.ElideMiddle, max(room, 24))
            p.drawText(ct.adjusted(0, 0, 0, 0), Qt.AlignmentFlag.AlignRight |
                       Qt.AlignmentFlag.AlignVCenter, f"〈  {shown}  〉")

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
        elif r.type == PORT:
            # Nothing changes here: the panel emits the URL and main_window performs the
            # switch (engine call, INI write, possible mode flip).
            if r.payload:
                log(f"ui-corr: source row -> {r.payload}")
                self.input_selected.emit(r.payload)
        elif r.type == ACTION:
            if r.key and r.key.startswith("src."):
                log(f"ui-corr: action row -> {r.key}")
                self.action_requested.emit(r.key)
            else:
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


# old INI key -> new INI key, applied on load by SettingsIni.__init__.
# Use it whenever a row is renamed or moves group, so a tuned value follows the control
# instead of reverting to its default on the next start.
RENAMED_INI_KEYS = {
    "zion.hiDesat": "hdr.hiDesat",   # "Hi-Desat" in the grade tab -> "Highlight desat"
}


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
        # Renamed keys. A row that moves group (zion.hiDesat -> hdr.hiDesat when the
        # control was re-labelled "Highlight desat" and placed with the gamut controls)
        # would otherwise read as "never configured" and silently reset to its default —
        # the user sees a dial they tuned jump back, which reads as the setting never
        # having worked. Carried over only when the new key is absent, so a value chosen
        # after the rename is never overwritten by the old one.
        for old, new in RENAMED_INI_KEYS.items():
            if new not in self.values and old in self.values:
                self.values[new] = self.values[old]

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

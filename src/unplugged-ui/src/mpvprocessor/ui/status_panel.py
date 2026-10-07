"""
Live status panel — shows what mpv is actually running in real time.

Updated via IPC property observers. Shown on the LEFT side of the screen
in EDIT mode alongside the settings panel on the right.

Sections:
  VIDEO SOURCE   — resolution, pixel format, colorspace, fps, HDR metadata
  TONE MAPPING   — active algorithm, measured peak (live), target peak
  DISPLAY OUTPUT — VO, swapchain, TRC, primaries
  PERFORMANCE    — display fps, dropped frames
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

_log = logging.getLogger("unplugged.status_panel")

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame

from PyQt6.QtCore import pyqtSignal as _Signal
from ..core.process_manager import ProcessState
from .theme import FONT_PX_LABEL, FONT_PX_VALUE, PANEL_BG
# Font sizes and the panel surface come from ui/theme.py, so this panel and the
# QPainter-drawn settings rail share one definition and cannot drift.
_PX_L, _PX_V = FONT_PX_LABEL, FONT_PX_VALUE


# NOTE: there is deliberately no module-level _BG or edge rule here. A _BG used
# to exist and was never applied to anything — the panel's surface is set in
# __init__ instead — and the right-hand divider was removed by design.

_SEC_STYLE  = (f"color: #E8551F; font-size: {_PX_L}px; font-weight: bold; "
               "letter-spacing: 1.5px; background: transparent; padding-top: 8px;")

# ── Human-readable lookup tables ─────────────────────────────────────────────

_PIXFMT_PACKED = {
    # YCbCr packed (name → family, subsampling, bits)
    "uyvy422":  ("YCbCr", "4:2:2", 8),   "yuyv422": ("YCbCr", "4:2:2", 8),
    "yvyu":     ("YCbCr", "4:2:2", 8),   "v210":    ("YCbCr", "4:2:2", 10),
    "y210":     ("YCbCr", "4:2:2", 10),  "y216":    ("YCbCr", "4:2:2", 16),
    "v308":     ("YCbCr", "4:4:4", 8),   "v410":    ("YCbCr", "4:4:4", 10),
    "nv12":     ("YCbCr", "4:2:0", 8),   "nv21":    ("YCbCr", "4:2:0", 8),
    "nv16":     ("YCbCr", "4:2:2", 8),   "nv24":    ("YCbCr", "4:4:4", 8),
    "nv20":     ("YCbCr", "4:2:2", 10),  "nv30":    ("YCbCr", "4:4:4", 10),
    "p010":     ("YCbCr", "4:2:0", 10),  "p016":    ("YCbCr", "4:2:0", 16),
    "p210":     ("YCbCr", "4:2:2", 10),  "p410":    ("YCbCr", "4:4:4", 10),
    # RGB packed
    "bgra":     ("RGB", "4:4:4", 8),     "bgr0":    ("RGB", "4:4:4", 8),
    "rgba":     ("RGB", "4:4:4", 8),     "rgb0":    ("RGB", "4:4:4", 8),
    "argb":     ("RGB", "4:4:4", 8),     "0rgb":    ("RGB", "4:4:4", 8),
    "abgr":     ("RGB", "4:4:4", 8),     "rgb24":   ("RGB", "4:4:4", 8),
    "bgr24":    ("RGB", "4:4:4", 8),     "r210":    ("RGB", "4:4:4", 10),
    "r410":     ("RGB", "4:4:4", 10),    "rgb48":   ("RGB", "4:4:4", 16),
    "rgba64":   ("RGB", "4:4:4", 16),    "gbrp":    ("RGB", "4:4:4", 8),
    "gbrap":    ("RGB", "4:4:4", 8),     "gbrp10":  ("RGB", "4:4:4", 10),
    "gbrap10":  ("RGB", "4:4:4", 10),
    # Mono
    "gray":     ("Mono", "—", 8),   "gray9":  ("Mono", "—", 9),
    "gray10":   ("Mono", "—", 10),  "gray12": ("Mono", "—", 12),
    "gray16":   ("Mono", "—", 16),
}

_SUBSAMPLE = {"420": "4:2:0", "422": "4:2:2", "444": "4:4:4",
              "440": "4:4:0", "411": "4:1:1", "410": "4:1:0"}

_HW_PREFIXES = ("d3d11va_", "vaapi_", "vdpau_", "cuda_", "qsv_", "opencl_",
                "dxva2_", "vulkan_", "mediacodec_", "videotoolbox_")


def _pixfmt_label(family: str, subsample: str, bits: int) -> str:
    if family == "Mono":
        return f"Mono · {bits}-bit"
    return f"{family} {subsample} · {bits}-bit"


def humanize_pixfmt(pixfmt: str) -> str:
    """v210 / uyvy422 / yuv422p10le → 'YCbCr 4:2:2 · 10-bit'.

    mpv's video-params.pixelformat arrives straight from FFmpeg's
    av_get_pix_fmt_name(), e.g. planar 10-bit is 'yuv422p10le' and packed
    8-bit is 'uyvy422'. Covers YCbCr/RGB/Mono families, the full subsampling
    set and 8/9/10/12/16-bit depths; drops endianness and HW-wrappers for the
    display string. Unknown formats fall back to the raw name.
    """
    pf = (pixfmt or "").strip().lower()
    if not pf:
        return "—"

    # HW-decoder wrappers (e.g. d3d11va_yuv420p) — label the inner format.
    for hw in _HW_PREFIXES:
        if pf.startswith(hw):
            inner = pf[len(hw):]
            labelled = humanize_pixfmt(inner)
            return f"{labelled} · {hw.rstrip('_')}" if labelled != inner else pf

    if pf in _PIXFMT_PACKED:
        fam, ss, bits = _PIXFMT_PACKED[pf]
        return _pixfmt_label(fam, ss, bits)

    # strip endianness suffix (le/be) — does not change depth
    base = pf
    for suf in ("le", "be", "ne"):
        if base.endswith(suf):
            base = base[:-len(suf)]
            break
    # re-check the packed table (e.g. ffmpeg's p010 is really "p010le")
    if base in _PIXFMT_PACKED:
        fam, ss, bits = _PIXFMT_PACKED[base]
        return _pixfmt_label(fam, ss, bits)

    # planar YCbCr: yuv420p / yuv420p10 / yuv422p12 / yuva444p10
    m = re.match(r"^yuv(a)?(\d{3})p(\d{1,2})?$", base)
    if m:
        ss = _SUBSAMPLE.get(m.group(2), m.group(2))
        bits = int(m.group(3)) if m.group(3) else 8
        return _pixfmt_label("YCbCr", ss, bits)

    # planar RGB: gbrp / gbrap / gbrp10 / gbrap10
    m = re.match(r"^gbra?p(\d{1,2})?$", base)
    if m:
        bits = int(m.group(1)) if m.group(1) else 8
        return _pixfmt_label("RGB", "4:4:4", bits)

    # monochrome: gray / gray10 / gray16
    m = re.match(r"^gray(\d{1,2})?$", base)
    if m:
        bits = int(m.group(1)) if m.group(1) else 8
        return f"Mono · {bits}-bit"

    return pf  # unknown — show the raw name

_COLORSPACE = {
    "bt.709":        "BT.709 (HD)",
    "bt.2020":       "BT.2020 (UHD)",
    "bt.2020-ncl":   "BT.2020 (UHD)",
    "bt.2020-cl":    "BT.2020 (UHD)",
    "bt.601-525":    "BT.601",
    "bt.601-625":    "BT.601",
    "display-p3":    "Display P3",
    "dolbyvision":   "Dolby Vision",
    "smpte240m":     "SMPTE 240M",
}

# The MPCVR input-colour-space override the engine actually pushed (ICS_* values,
# see IVideoRenderer.h). This is the authority: it is what the renderer is grading
# the signal AS, so the panel cannot disagree with the picture.
_ICS_NAMES = {
    1: "BT.601",
    2: "BT.709",
    3: "BT.2020",
    4: "BT.2020 (PQ)",
    5: "BT.2020 (HLG)",
}


def _effective_cs(j: dict, dl: dict, eotf: int) -> str:
    """The colour space in force, not the raw capture flag.

    Two different numbers describe this signal and only one of them is meaningful.

    `dl.cs` is what the capture path DETECTED, and it reports 2 (BT.709) for HDR10
    — normal for this box, and the reason the panel used to label an HDR movie
    "BT.709" while the renderer was grading it BT.2020/PQ. That reads as the
    capture misdetecting the signal, and it sent us looking for a bug in the
    pipeline that was not there.

    `cfg.ics` is what the engine DECIDED to tell MPCVR, derived from the negotiated
    media type with the EOTF first (PQ and HLG exist only in BT.2020, so a PQ
    signal is BT.2020 whatever the colours-space flag says). Prefer it, and fall
    back to the same EOTF-first rule when the override is Auto.
    """
    ics = (j.get("cfg") or {}).get("ics", 0)
    if ics in _ICS_NAMES:
        return _ICS_NAMES[ics]
    if eotf in (2, 3, 4):                       # PQ / HLG / DV are BT.2020 by definition
        return "BT.2020"
    return {1: "BT.601", 2: "BT.709", 3: "BT.2020"}.get(dl.get("cs", 0), "—")

_TRANSFER = {
    "bt.2020":   "BT.2020 (SDR OETF)",
    "bt.1886":   "BT.1886 (Gamma 2.4)",
    "gamma2.2":  "Gamma 2.2",
    "gamma2.8":  "Gamma 2.8",
    "srgb":      "sRGB",
    "pq":        "PQ (HDR10)",
    "hlg":       "HLG",
    "st2084":    "PQ (ST.2084)",
    "st2094-10": "Dynamic HDR (ST.2094-10)",
    "st2094-40": "Dynamic HDR (ST.2094-40)",
    "linear":    "Linear",
    "v-log":     "V-Log",
    "s-log2":    "S-Log2",
    "s-log3":    "S-Log3",
    "log100":    "Log100",
}

_TM_ALGO = {
    "acs":       "ACES (Filmic)",
    "aces":      "ACES (Filmic)",
    "spline":    "Spline",
    "bt.2390":   "BT.2390",
    "bt.2446a":  "BT.2446a",
    "st2094-10": "ST.2094-10 (Dynamic)",
    "st2094-40": "ST.2094-40 (Dynamic)",
    "reinhard":  "Reinhard",
    "mobius":    "Möbius",
    "hable":     "Hable (Filmic)",
    "reference": "Unplugged (Hable) ",
    "gt7":       "GT7 (Polyphony)",
    "gamma":     "Gamma",
    "linear":    "Linear",
    "saturation":"Saturation",
    "clip":      "Clip",
    "lut":       "LUT",
    "auto":      "Auto",
}

# The tone-mapping curve the ENGINE actually holds (HdrSettings.toneMapCurve =
# MPCVR's iHdrLocalToneMappingType — read back from the renderer, so it is what
# will be applied, not what was typed). 1=ACES 2=Reinhard 3=Hable 4=Mobius
# 5=BT.2390. Maps to keys of _TM_ALGO.
_MPCVR_CURVE = {1: "aces", 2: "reinhard", 3: "hable", 4: "mobius", 5: "bt.2390",
                # 7 was missing, so the status panel labelled the Reference curve
                # "Auto" — the readout disagreed with what was rendering.
                7: "reference", 8: "gt7", 0: "auto"}

# Media-file mode transfer map — DXVA2_ExtendedFormat / MFVideoTransferFunction
# field values, VERIFIED against the installed SDK (mfobjects.h: _2084=15, HLG=16,
# 2020=13, 709=5, sRGB=7, 22=4, 28=8). Earlier versions of this table copied
# stale enum numbers from memory (18/19) and mislabelled every HDR10 file's 15
# (MFVideoTransFunc_2084) as "Gamma 2.8" — verified wrong: 15 is PQ. These keys
# feed _TRANSFER, which labels the same names on both capture and file paths.
_MF_TF = {15: "pq", 16: "hlg",
          13: "bt.2020", 12: "bt.2020",   # BT.2020 OETF / constant-luminance
          5: "bt.1886", 11: "bt.1886",    # BT.709 -> BT.1886 display EOTF
          7: "srgb", 4: "gamma2.2", 8: "gamma2.8", 1: "linear"}
# DXVA2_ExtendedFormat primaries: BT.2020=9, BT.709=2 (both the decoder's raw tag
# and the engine's normalized 1/2/3 fallback for BT.601/709/2020).
_MF_PRIM = {2: "bt.709", 9: "bt.2020", 3: "bt.2020", 1: "bt.601-525",
            5: "bt.601-525", 4: "bt.601-625", 6: "bt.601-625"}

# Bytes-per-pixel of the decoded source (media.fmt: 0=UYVY 1=v210 2=NV12
# 3=(raw) 4=P010). Used for the "decoded source bitrate" row on the file path
# where no card/v210 rate exists.
_MF_BYTESPP = {0: 2.0, 1: 8.0 / 3.0, 2: 1.5, 4: 1.5, 3: 1.5}

_GAMUT = {
    "perceptual":  "Perceptual",
    "relative":    "Relative Colorimetric",
    "saturation":  "Saturation",
    "absolute":    "Absolute Colorimetric",
    "linear":      "Linear",
    "darken":      "Darken",
    "warn":        "Warn (clip)",
    "softclip":    "Soft Clip",
    "lut3d":       "3D LUT",
}

_HWDEC = {
    "d3d11va-copy":  "D3D11VA Copy",
    "d3d11va":       "D3D11VA Zero-copy",
    "nvdec-copy":    "NVDEC Copy",
    "nvdec":         "NVDEC Zero-copy",
    "dxva2-copy":    "DXVA2 Copy",
    "dxva2":         "DXVA2",
    "auto-copy":     "Auto Copy",
    "auto":          "Auto",
    "no":            "Software",
    "software":      "Software",
}


def _h(mapping: dict, key: str, fallback: str = "") -> str:
    """Human-readable lookup with graceful fallback."""
    k = (key or "").lower().strip()
    return mapping.get(k, fallback or key or "—")
def _parse_vf_param(vf: str, key: str) -> str:
    """Extract a named param from a vf string like 'format=...:primaries=bt.2020:gamma=pq'."""
    for part in vf.split(":"):
        if part.startswith(key + "="):
            return part[len(key) + 1:]
    return ""


_KEY_STYLE  = f"color: #666666; font-size: {_PX_L}px; background: transparent;"
_VAL_STYLE  = f"color: #e0e0e0; font-size: {_PX_V}px; background: transparent;"
_LIVE_STYLE = f"color: #e0e0e0; font-size: {_PX_V}px; background: transparent;"
_WARN_STYLE = f"color: #ff9800; font-size: {_PX_V}px; background: transparent;"
_DIM_STYLE  = f"color: #444444; font-size: {_PX_V}px; background: transparent; font-style: italic;"
_LOCK_STYLE   = f"color: #35c759; font-size: {_PX_V}px; background: transparent; font-weight: bold;"
_UNLOCK_STYLE = f"color: #e5484d; font-size: {_PX_V}px; background: transparent; font-weight: bold;"


def _section(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_SEC_STYLE)
    return l


class _Row(QWidget):
    """One key/value row."""
    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(0)
        self._key = QLabel(key.upper())
        self._key.setStyleSheet(_KEY_STYLE)
        self._val = QLabel("—")
        self._val.setStyleSheet(_DIM_STYLE)
        self._val.setWordWrap(True)
        layout.addWidget(self._key)
        layout.addWidget(self._val)

    def set(self, value: str, style: str = _VAL_STYLE) -> None:
        if value:
            self._val.setText(value)
            self._val.setStyleSheet(style)
        else:
            self._val.setText("—")
            self._val.setStyleSheet(_DIM_STYLE)

    def set_visible(self, visible: bool) -> None:
        self.setVisible(visible)


class StatusPanel(QWidget):
    # Emitted when DV is detected — suggests switching tone mapping
    dolby_vision_detected = _Signal(int)   # DV profile number
    # Emitted when HDR/SDR state changes — True=HDR active, False=SDR
    hdr_active_changed = _Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Paint the panel surface HERE. The chrome window that hosts this panel
        # is translucent and sits over the video, so a fully transparent panel
        # showed the black video through it — which is why this rail read as
        # pitch black beside the settings rail despite sharing a colour const.
        # The bare `QWidget` rule keeps every child transparent so the rows and
        # section headers still read on top of the surface.
        self.setObjectName("StatusPanel")
        self.setStyleSheet(f"#StatusPanel {{ background: {PANEL_BG}; }}"
                           "QWidget { background: transparent; }")
        # Active vf override from DeckLink detection — used to correct
        # VIDEO SOURCE colorspace/transfer (raw stream headers are always bt.709)
        self._vf_override: str = ""
        self._is_vp: bool = False  # True in video_processor mode — bitrate shown in Gbps
        self._hdr_active: bool = True  # Current HDR state — used to avoid redundant emissions

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header — matches right panel tab bar style
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background: {PANEL_BG};")
        from PyQt6.QtWidgets import QHBoxLayout
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.setSpacing(0)
        # "Live" — left-aligned tab label, same style as right panel tabs
        title = QLabel("Live")
        title.setStyleSheet(
            f"color: #F2F2F2; font-size: {_PX_V}px; font-weight: 600; "
            "background: transparent; padding: 6px 16px; "
            "border-bottom: 2px solid #E8551F;")
        hl.addWidget(title)
        hl.addStretch()
        self._not_running = QLabel("not running")
        self._not_running.setStyleSheet("color:#444; font-size:11px; background:transparent;")
        hl.addWidget(self._not_running)
        root.addWidget(hdr)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                             "QScrollBar:vertical { background: transparent; width: 3px; }"
                             "QScrollBar::handle:vertical { background: rgba(255,255,255,30); border-radius: 2px; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(14, 8, 14, 16)
        self._layout.setSpacing(2)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        self._build_rows()

    def _build_rows(self) -> None:
        L = self._layout

        # ── CAPTURE INPUT (VP mode only) ──────────────────────────────
        self._capture_section = _section("CAPTURE INPUT")
        L.addWidget(self._capture_section)
        self._r_capture_device = self._row("Device")
        self._r_capture_lock   = self._row("Signal")
        self._r_capture_format = self._row("Detected format")
        self._r_capture_vf     = self._row("Active vf override")
        self._r_capture_vf.hide()   # mpv remnant — no vf chains in the MPCVR path
        self._capture_divider = None      # rules removed by design
        # Hidden by default — shown only in VP mode
        self._capture_section.hide()
        self._r_capture_device._key.parent().hide() if False else None
        self._set_capture_visible(False)

        # ── VIDEO SOURCE ──────────────────────────────────────────────
        L.addWidget(_section("VIDEO SOURCE"))
        self._r_resolution  = self._row("Resolution")
        self._r_pixfmt      = self._row("Pixel format")
        self._r_codec       = self._row("Codec")
        self._r_colorspace  = self._row("Colorspace")
        self._r_transfer    = self._row("Transfer (EOTF)")
        self._r_fps_src     = self._row("Source fps")
        self._r_mastering_peak = self._row("Mastering peak")
        self._r_mastering_min  = self._row("Mastering black")
        self._r_sig_peak    = self._row("Signal peak")
        self._r_hdr_format  = self._row("HDR format")
        self._r_bitrate     = self._row("Bitrate")
        # P1: the DeckLink capture path cannot produce these mpv-era values —
        # hide them instead of showing blank/orphan rows (they return when/if
        # the data source exists).
        for orphan in (self._r_codec, self._r_mastering_peak,
                       self._r_mastering_min, self._r_sig_peak):
            orphan.hide()

        # NEW rows for the card's own ST 2086 read, with deliberately NEW names.
        # The mpv-era rows above already have an owner — on_property's video-params
        # handler, which hides them whenever libmpv has no max-luma — and reusing
        # them meant fighting that handler for ownership. These four have exactly
        # one writer: on_s3_status.
        self._r_card_cll    = self._row("MaxCLL")
        self._r_card_fall   = self._row("MaxFALL")
        self._r_card_mmax   = self._row("Mastering max")
        self._r_card_mmin   = self._row("Mastering min")

        self._divider()

        # ── TONE MAPPING ──────────────────────────────────────────────
        L.addWidget(_section("TONE MAPPING"))
        self._r_tm_algo      = self._row("Algorithm")
        self._r_tm_peak_mode  = self._row("Peak mode")
        self._r_measured_peak = self._row("Frame peak")
        self._r_apl           = self._row("APL (avg)")
        self._r_target_peak   = self._row("Target peak")
        self._r_tm_boost     = self._row("Max boost")
        self._r_cr           = self._row("Contrast recovery")
        # Frame peak / APL are live-fed by on_s3_status from the renderer's own
        # measured scene stats (cfg.scPeak/scAvg — PQ code); the rest stay hidden
        # until their P2 settings wiring lands.
        for orphan in (self._r_tm_peak_mode, self._r_tm_boost, self._r_cr):
            orphan.hide()

        self._divider()

        # ── DISPLAY OUTPUT ────────────────────────────────────────────
        # P1: hidden entirely — no capture-path equivalent for these mpv/gpu
        # output rows. Section keeps a ref so it can return with its data.
        self._out_section = _section("DISPLAY OUTPUT")
        L.addWidget(self._out_section)
        self._r_vo          = self._row("Video output")
        self._r_hwdec       = self._row("HW decode")
        self._r_src_trc     = self._row("Content TRC")
        self._r_src_prim    = self._row("Content primaries")
        self._r_out_trc     = self._row("Target TRC")
        self._r_out_prim    = self._row("Target primaries")
        self._r_gamut       = self._row("Gamut mapping")
        self._r_display     = self._row("Display")
        self._out_section.hide()
        for orphan in (self._r_vo, self._r_hwdec, self._r_src_trc,
                       self._r_src_prim, self._r_out_trc, self._r_out_prim,
                       self._r_gamut, self._r_display):
            orphan.hide()

        self._divider()

        # ── ZION CORE ─────────────────────────────────────────────────
        self._zion_section = _section("ZION CORE")
        L.addWidget(self._zion_section)
        self._r_zion_build    = self._row("Build")
        self._r_zion_gamma    = self._row("Oracle γ")
        self._r_zion_cr       = self._row("Construct CR")
        self._r_zion_rad      = self._row("Resonance")
        self._r_zion_chroma   = self._row("Spectrum Shift")
        self._r_zion_shadow   = self._row("Shadow recover")
        self._r_zion_hi       = self._row("Highlight smooth")
        self._r_zion_l1max    = self._row("Scene peak  (L1)")
        self._r_zion_eval     = self._row("Oracle eval")
        self._zion_section.hide()
        for r in (self._r_zion_build, self._r_zion_gamma, self._r_zion_cr,
                  self._r_zion_rad, self._r_zion_chroma,
                  self._r_zion_shadow, self._r_zion_hi,
                  self._r_zion_l1max, self._r_zion_eval):
            r.hide()

        # ── PERFORMANCE ───────────────────────────────────────────────
        L.addWidget(_section("PERFORMANCE"))
        self._r_fps_disp    = self._row("Display fps")
        self._r_dropped     = self._row("Dropped frames")
        self._r_delayed     = self._row("Delayed frames")
        self._r_paused      = self._row("State")

        self._divider()

        # ── RENDER CHAIN (s3 engine: direct DeckLink -> renderer) ──────
        L.addWidget(_section("RENDER CHAIN"))
        self._r_rc_recv    = self._row("Renderer recv")
        self._r_rc_dlv     = self._row("Delivered")
        self._r_rc_skip    = self._row("Skipped")
        self._r_rc_gate    = self._row("Gate dropped")
        self._r_rc_qdrop   = self._row("Queue drop")
        self._r_rc_reneg   = self._row("Renegotiations")
        self._r_rc_lag     = self._row("Present lag")
        self._r_rc_stream  = self._row("Stream time")

        L.addStretch()

    @staticmethod
    def _pq_to_nits(pq: float) -> int:
        m1, m2 = 0.1593017578125, 78.84375
        c1, c2, c3 = 0.8359375, 18.8515625, 18.6875
        tmp = max(0.0, pq ** (1/m2) - c1)
        return round(10000 * (tmp / (c2 - c3 * pq ** (1/m2))) ** (1/m1))

    def _row(self, key: str) -> "_Row":
        r = _Row(key, self._layout.parentWidget())
        self._layout.addWidget(r)
        return r

    def _divider(self) -> None:
        """Horizontal rules were removed by design — sections separate with
        spacing now. Kept as a no-op so the section builders stay unchanged."""
        return

    # ------------------------------------------------------------------
    # Property update interface — called from MainWindow
    # ------------------------------------------------------------------

    def on_property(self, name: str, value) -> None:
        """Route a property-change to the correct row."""
        if value is None:
            return

        # ── VIDEO SOURCE ──────────────────────────────────────────────
        if name == "video-params":
            if not isinstance(value, dict):
                return
            w = value.get("w", "?"); h = value.get("h", "?")
            self._r_resolution.set(f"{w} × {h}")
            self._r_pixfmt.set(humanize_pixfmt(value.get("pixelformat", "")))
            # In capture mode colorspace/transfer come from DeckLink detection
            # (set in update_capture_info), not from raw stream headers which
            # always report bt.709/BT.1886 regardless of HDR content.
            # In media-player mode there is no DeckLink detection — the raw
            # stream metadata IS authoritative, so show it even when a
            # detected/DV pipeline vf_override is latched.
            _log.info(f"video-params: vf_override={self._vf_override!r} "
                      f"colormatrix={value.get('colormatrix')!r} gamma={value.get('gamma')!r}")
            if not self._vf_override or not self._is_vp:
                colormatrix = value.get("colormatrix", "")
                self._r_colorspace.set(_h(_COLORSPACE, colormatrix))
                trc = value.get("gamma", "")
                self._r_transfer.set(_h(_TRANSFER, trc))
                _log.info("video-params: wrote raw stream colorspace/transfer (no vf override active)")
                # In media player mode, detect HDR from stream gamma
                if not self._is_vp:
                    self._emit_hdr_active(trc in ("pq", "hlg", "st2084"))
            else:
                _log.info(f"video-params: skipped raw colorspace/transfer — vf_override active: {self._vf_override!r}")
            colormatrix = value.get("colormatrix", "")
            if colormatrix == "dolbyvision":
                self._r_hdr_format.set("Dolby Vision", _LIVE_STYLE)
                self.dolby_vision_detected.emit(-1)  # -1 = detected from params, profile unknown yet
            # sig-peak: PQ-normalised 0–1 where 1.0 = 10000 nits
            # Only show if it looks like genuine HDR metadata (< 1.5 = reasonable)
            # Mastering display luminance (from HDR10 static metadata)
            # Three rows below are fed by the CARD on the capture path (ST 2086,
            # set by on_s3_status) and by libmpv on the player path. When the card
            # has a reading it is authoritative: without this guard the mpv handler
            # hid them straight after on_s3_status filled them, because max-luma /
            # min-luma / sig-peak never arrive on the capture path — those come from
            # libmpv, which the s3 engine does not use.
            if getattr(self, "_card_hdr_meta", False):
                return

            max_luma = value.get("max-luma")
            min_luma = value.get("min-luma")
            try:
                if max_luma and float(max_luma) > 0:
                    self._r_mastering_peak.set(f"{round(float(max_luma))} nits", _LIVE_STYLE)
                    self._r_mastering_peak.set_visible(True)
                else:
                    self._r_mastering_peak.set_visible(False)
            except (TypeError, ValueError):
                self._r_mastering_peak.set_visible(False)

            try:
                if min_luma is not None and float(min_luma) > 0:
                    self._r_mastering_min.set(f"{float(min_luma):.4f} nits", _VAL_STYLE)
                    self._r_mastering_min.set_visible(True)
                else:
                    self._r_mastering_min.set_visible(False)
            except (TypeError, ValueError):
                self._r_mastering_min.set_visible(False)

            sp = value.get("sig-peak")
            try:
                v = float(sp) if sp is not None else 0.0
                if v > 0.0:
                    nits = round(v * 203)
                    self._r_sig_peak.set(f"{nits} nits", _VAL_STYLE)
                    self._r_sig_peak.set_visible(True)
                else:
                    self._r_sig_peak.set_visible(False)
            except (TypeError, ValueError):
                self._r_sig_peak.set_visible(False)

        elif name == "video-out-params":
            if not isinstance(value, dict):
                return

            # max-pq-y / avg-pq-y: per-frame scene peak/avg as PQ code (0–1)
            # PQ EOTF: nits = 10000 × ((max(0, pq^(1/m2) - c1) / (c2 - c3×pq^(1/m2)))^(1/m1))
            # Simplified good approximation: nits ≈ 10000 × pq^(1/0.1593)
            # But even simpler: multiply by 10000 since PQ is already normalised 0-1=0-10000nits
            max_pq = value.get("max-pq-y")
            avg_pq = value.get("avg-pq-y")

            try:
                if max_pq is not None and float(max_pq) > 0:
                    self._r_measured_peak.set(f"{self._pq_to_nits(float(max_pq))} nits")
                else:
                    self._r_measured_peak.set("—", _DIM_STYLE)
            except Exception:
                self._r_measured_peak.set("—", _DIM_STYLE)

            try:
                if avg_pq is not None and float(avg_pq) > 0:
                    self._r_apl.set(f"{self._pq_to_nits(float(avg_pq))} nits")
                else:
                    self._r_apl.set("—", _DIM_STYLE)
            except Exception:
                self._r_apl.set("—", _DIM_STYLE)

            # Content TRC/primaries — what libplacebo receives from the decoded source
            trc_src = value.get("gamma", "")
            if trc_src:
                self._r_src_trc.set(_h(_TRANSFER, trc_src))
            prim_src = value.get("primaries", "")
            if prim_src:
                self._r_src_prim.set(_h(_COLORSPACE, prim_src))

        elif name == "estimated-vf-fps":
            try:
                self._r_fps_src.set(f"{float(value):.3f} fps")
            except (TypeError, ValueError):
                pass

        elif name == "display-fps":
            try:
                self._r_fps_disp.set(f"{float(value):.1f} Hz")
            except (TypeError, ValueError):
                pass

        elif name in ("frame-drop-count", "decoder-frame-drop-count"):
            try:
                n = int(value)
                self._r_dropped.set(str(n), _WARN_STYLE if n > 0 else _VAL_STYLE)
            except (TypeError, ValueError):
                pass

        elif name == "vo-delayed-frame-count":
            try:
                n = int(value)
                self._r_delayed.set(str(n), _WARN_STYLE if n > 0 else _VAL_STYLE)
            except (TypeError, ValueError):
                pass

        elif name == "track-list":
            # Detect Dolby Vision from track metadata
            if isinstance(value, list):
                for t in value:
                    if t.get("type") == "video" and not t.get("image"):
                        dovi = t.get("dolby-vision-profile")
                        if dovi is not None:
                            profile_names = {
                                5: "Profile 5 — Player-Led",
                                7: "Profile 7 — Dual Layer",
                                8: "Profile 8 — HDR10 compat",
                            }
                            dovi_int = int(dovi)
                            label = profile_names.get(dovi_int,
                                                       f"Profile {dovi_int}")
                            self._r_hdr_format.set(
                                f"Dolby Vision  {label}", _LIVE_STYLE)
                            self.dolby_vision_detected.emit(dovi_int)

        elif name == "video-codec":
            if value:
                # Shorten long codec names
                v = str(value)
                if "H.264" in v or "AVC" in v:
                    self._r_codec.set("H.264 / AVC")
                elif "H.265" in v or "HEVC" in v:
                    self._r_codec.set("H.265 / HEVC", _LIVE_STYLE)
                elif "AV1" in v:
                    self._r_codec.set("AV1", _LIVE_STYLE)
                else:
                    self._r_codec.set(v[:30])

        elif name == "video-bitrate":
            try:
                bps = float(value)
                if self._is_vp:
                    gbps = bps / 1_000_000_000
                    self._r_bitrate.set(f"{gbps:.2f} Gbps", _VAL_STYLE)
                else:
                    mbps = bps / 1_000_000
                    self._r_bitrate.set(f"{mbps:.1f} Mbps")
            except (TypeError, ValueError):
                pass

        elif name == "hwdec-current":
            self._r_hwdec.set(_h(_HWDEC, str(value) if value else "no"))

        elif name == "display-names":
            if value:
                names = value if isinstance(value, list) else [str(value)]
                # Strip \\.\DISPLAY prefix
                clean = [n.replace("\\\\.\\", "").replace("\\\\", "") for n in names]
                self._r_display.set(", ".join(clean))

        # ── TONE MAPPING ──────────────────────────────────────────────
        elif name == "tone-mapping":
            self._r_tm_algo.set(_h(_TM_ALGO, str(value)))

        elif name == "hdr-compute-peak":
            if value is True or value == "yes":
                self._r_tm_peak_mode.set("Per-frame")
            elif value is False or value == "no":
                self._r_tm_peak_mode.set("Manual (target peak)")
            elif value == "auto" or str(value).lower() == "auto":
                self._r_tm_peak_mode.set("Auto")
            else:
                self._r_tm_peak_mode.set(str(value).capitalize())

        elif name == "target-peak":
            try:
                self._r_target_peak.set(f"{int(float(value))} nits")
            except (TypeError, ValueError):
                self._r_target_peak.set(str(value))

        elif name == "tone-mapping-max-boost":
            try:
                self._r_tm_boost.set(f"{float(value):.1f}×")
            except (TypeError, ValueError):
                pass

        elif name == "hdr-contrast-recovery":
            try:
                self._r_cr.set(f"{float(value):.2f}")
            except (TypeError, ValueError):
                pass

        # ── DISPLAY OUTPUT ────────────────────────────────────────────
        elif name == "current-vo":
            self._r_vo.set(str(value))

        elif name == "display-swapchain":
            if value:
                # Simplify the swapchain string for readability
                s = str(value)
                if "G22" in s:
                    self._r_swapchain.set("SDR sRGB (G22)", _VAL_STYLE)
                elif "G10" in s or "scRGB" in s:
                    self._r_swapchain.set("HDR scRGB (G10)", _LIVE_STYLE)
                elif "2084" in s or "PQ" in s:
                    self._r_swapchain.set("HDR PQ", _LIVE_STYLE)
                elif "HLG" in s:
                    self._r_swapchain.set("HDR HLG", _LIVE_STYLE)
                else:
                    self._r_swapchain.set(s[:40])

        elif name == "gamut-mapping-mode":
            self._r_gamut.set(_h(_GAMUT, str(value)))

        elif name == "target-trc":
            if value:
                self._r_out_trc.set(_h(_TRANSFER, str(value)))

        elif name == "target-prim":
            if value:
                self._r_out_prim.set(_h(_COLORSPACE, str(value)))

        elif name == "pause":
            self._r_paused.set("Paused" if value else "Playing",
                               _WARN_STYLE if value else _VAL_STYLE)

        elif name == "display-swapchain":
            self._r_swapchain.set(str(value) if value else "—")

        elif name == "target-peak":
            try:
                self._r_target_peak.set(f"{int(float(value))} nits")
            except (TypeError, ValueError):
                self._r_target_peak.set(str(value))

        elif name == "tone-mapping-max-boost":
            try:
                self._r_tm_boost.set(f"{float(value):.1f}×")
            except (TypeError, ValueError):
                pass

        elif name == "hdr-contrast-recovery":
            try:
                self._r_cr.set(f"{float(value):.2f}")
            except (TypeError, ValueError):
                pass

        elif name == "vo-configured":
            pass  # VO type shown via video-params

        elif name == "current-vo":
            self._r_vo.set(str(value))

        elif name == "gamut-mapping-mode":
            self._r_gamut.set(_h(_GAMUT, str(value)))

        elif name == "pause":
            self._r_paused.set("Paused" if value else "Playing",
                               _WARN_STYLE if value else _VAL_STYLE)

    def _set_capture_visible(self, visible: bool) -> None:
        self._capture_section.setVisible(visible)
        self._r_capture_device.setVisible(visible)
        self._r_capture_lock.setVisible(visible)
        self._r_capture_format.setVisible(visible)
        self._r_capture_vf.setVisible(visible)

    def set_dv_active(self, is_dv: bool) -> None:
        """Hide live peak/APL rows for DV content — those values are DV metadata, not live."""
        self._r_measured_peak.setVisible(not is_dv)
        self._r_apl.setVisible(not is_dv)

    def set_app_mode(self, mode: str) -> None:
        """Show/hide capture section based on VP vs media player mode."""
        self._is_vp = (mode == "video_processor")
        self._set_capture_visible(self._is_vp)

    def seed_configured_output(self, profile) -> None:
        """Show the user-configured tone-mapping/display values.

        mpv does not expose the tone-mapping family (tone-mapping,
        hdr-compute-peak, target-peak, max-boost, target-trc, target-prim,
        gamut-mapping-mode) as readable properties on this build, so observed
        events never arrive for them — without this, those rows stay holes.
        Populate them from the profile so the user always sees their settings;
        a real property event (when one exists) overwrites below.
        """
        tm = profile.tone_mapping
        pd = profile.peak_detection
        dt = profile.display_target
        gm = profile.gamut_mapping
        if tm:
            self._r_tm_algo.set(_h(_TM_ALGO, str(tm.algorithm)), _VAL_STYLE)
            try:
                self._r_tm_boost.set(f"{float(tm.tone_mapping_max_boost):.1f}×", _VAL_STYLE)
            except (TypeError, ValueError):
                pass
        if pd:
            peak = pd.hdr_compute_peak
            if peak in ("yes", True):
                self._r_tm_peak_mode.set("Per-frame", _VAL_STYLE)
            elif peak in ("no", False):
                self._r_tm_peak_mode.set("Manual (target peak)", _VAL_STYLE)
            else:
                self._r_tm_peak_mode.set("Auto", _VAL_STYLE)
        if dt:
            try:
                self._r_target_peak.set(f"{int(float(dt.target_peak))} nits", _VAL_STYLE)
            except (TypeError, ValueError):
                self._r_target_peak.set(str(dt.target_peak), _VAL_STYLE)
            self._r_out_trc.set(_h(_TRANSFER, str(dt.target_trc)), _VAL_STYLE)
            self._r_out_prim.set(_h(_COLORSPACE, str(dt.target_prim)), _VAL_STYLE)
        if gm:
            self._r_gamut.set(_h(_GAMUT, str(gm.mode)), _VAL_STYLE)
        cr = getattr(profile, "contrast_recovery", None)
        if cr is not None:
            try:
                self._r_cr.set(f"{float(cr.hdr_contrast_recovery):.2f}", _VAL_STYLE)
            except (TypeError, ValueError):
                pass

    def update_capture_info(self, device: str, signal_info=None,
                            vf_filter: str = "") -> None:
        """Called when VP signal is acquired or changes."""
        # Clean device name
        clean = device
        if clean.startswith("decklink://"):
            clean = clean[len("decklink://"):]
        if "@" in clean:
            name, _, port = clean.rpartition("@")
            clean = f"{name}  (HDMI {int(port)+1})"
        self._r_capture_device.set(clean)

        if signal_info is not None:
            # Signal locked status
            if signal_info.locked:
                self._r_capture_lock.set("●  LOCKED", _LOCK_STYLE)
            else:
                self._r_capture_lock.set("●  NO SIGNAL", _UNLOCK_STYLE)

            # Detected format
            cs_names  = {0: "BT.601", 1: "BT.709", 2: "BT.2020"}
            gma_names = {0: "SDR (BT.1886)", 1: "HDR PQ (SMPTE ST2084)", 2: "HDR HLG"}
            cs    = cs_names.get(signal_info.colorspace, "?")
            depth = signal_info.pixel_depth
            if signal_info.is_likely_dolby_vision():
                gma   = "Dolby Vision"
                style = _LIVE_STYLE
            else:
                gma   = gma_names.get(signal_info.dynamic_range, "?")
                style = _LIVE_STYLE if signal_info.dynamic_range > 0 else _VAL_STYLE
            _chroma_names = {1: "RGB 4:4:4", 0: "YCbCr 4:2:2"}
            chroma = _chroma_names.get(signal_info.chroma, "")
            fmt = f"{cs}  ·  {gma}  ·  {depth}-bit"
            if chroma:
                fmt += f"  ·  {chroma}"
            self._r_capture_format.set(fmt, style)
        else:
            self._r_capture_lock.set("Locked", _VAL_STYLE)
            self._r_capture_format.set("—", _DIM_STYLE)

        _log.info(f"update_capture_info: vf_filter={vf_filter!r}")
        self._vf_override = vf_filter
        if vf_filter:
            self._r_capture_vf.set("Auto-detected ✓", _LIVE_STYLE)
            self._r_capture_vf._val.setToolTip(vf_filter)
            prim = _parse_vf_param(vf_filter, "primaries")
            gma  = _parse_vf_param(vf_filter, "gamma")
            _log.info(f"update_capture_info: writing colorspace={prim!r} transfer={gma!r}")
            if prim:
                self._r_colorspace.set(_h(_COLORSPACE, prim))
            if gma:
                self._r_transfer.set(_h(_TRANSFER, gma))
            # HDR format from vf — DV if is_likely_dolby_vision, else PQ/HLG/SDR
            if signal_info is not None and signal_info.is_likely_dolby_vision():
                self._r_hdr_format.set("Dolby Vision", _LIVE_STYLE)
            elif gma == "pq":
                self._r_hdr_format.set("HDR10 / PQ", _LIVE_STYLE)
            elif gma == "hlg":
                self._r_hdr_format.set("HLG", _LIVE_STYLE)
            else:
                self._r_hdr_format.set_visible(False)
            self._emit_hdr_active(True)
        else:
            self._r_capture_vf.set("SDR — none needed", _VAL_STYLE)
            self._r_hdr_format.set_visible(False)
            self._emit_hdr_active(False)

    def _emit_hdr_active(self, is_hdr: bool) -> None:
        if is_hdr != self._hdr_active:
            self._hdr_active = is_hdr
            self.hdr_active_changed.emit(is_hdr)

    def set_process_state(self, state: ProcessState) -> None:
        running = state == ProcessState.RUNNING
        self._not_running.setVisible(not running)
        if not running:
            self._clear_all()

    def _clear_all(self) -> None:
        for attr in vars(self):
            obj = getattr(self, attr)
            if isinstance(obj, _Row):
                obj.set("")
        self._set_zion_visible(False)

    # ------------------------------------------------------------------
    # Zion Core live stats — wired to MpvEngine.zion_stats_updated
    # ------------------------------------------------------------------

    def _set_zion_visible(self, visible: bool) -> None:
        self._zion_section.setVisible(visible)
        for r in (self._r_zion_build, self._r_zion_gamma, self._r_zion_cr,
                  self._r_zion_rad, self._r_zion_chroma,
                  self._r_zion_shadow, self._r_zion_hi,
                  self._r_zion_l1max, self._r_zion_eval):
            r.setVisible(visible)

    def _apply(self, row: "_Row", text: str, style: str = _VAL_STYLE,
               reason: str = "") -> None:
        """Set a row AND leave the documented proof.

        `ui-row:` log lines are the deterministic answer to "are these values
        actually applied to the UI labels?" — every write to a panel row that
        produces a change is logged with the engine JSON source (`reason`), so a
        run's s3engine.log + unplugged.log can be lined up field by field. A
        value that repeats (e.g. draw-fps jitter settles) re-asserts at most
        every 5 s so the log stays a trail, not a firehose.
        """
        row.set(text, style)
        now = time.monotonic()
        prev_txt = getattr(row, "_pxt", None)
        prev_ts  = getattr(row, "_pts", 0.0)
        row._pxt = text
        row._pts = now
        if text != prev_txt or now - prev_ts >= 5.0:
            tag = f" [{reason}]" if reason else ""
            _log.info("ui-row: %-18s <- %r%s", row._key.text(), text, tag)

    def on_s3_status(self, j: dict) -> None:
        """Populate the panel (exactly the s3_shell LIVE items) from the
        engine's JSON poll — replaces the mpv-only property plumbing for
        source/render/chain rows."""
        rec = j.get("render") or {}
        dl  = j.get("dl") or {}
        sig = j.get("signal") or {}
        med = j.get("media") or {}

        # ── VIDEO SOURCE ──────────────────────────────────────────────
        is_cap = bool(dl.get("stream"))
        if med.get("valid"):
            self._apply(self._r_resolution, f"{med.get('w')} × {med.get('h')}",
                        reason="media.w/h")
            self._apply(self._r_pixfmt, humanize_pixfmt(med.get("subtype") or ""),
                        reason="media.subtype")
            self._apply(self._r_fps_src, f"{med.get('fps', 0):.3f} fps",
                        reason="media.fps")
        else:
            self._apply(self._r_resolution, "—"); self._apply(self._r_pixfmt, "—")
            self._apply(self._r_fps_src, "—")

        if not is_cap and med.get("valid"):
            # Media mode: no card detection — the stream's OWN colour metadata
            # (decoded by LAV out of the container) is authoritative, so show it
            # directly instead of the capture detect (which reads zero here).
            tfc = _MF_TF.get(med.get("tf", 0), "")
            prim = _MF_PRIM.get(med.get("prim", 0), "")
            # A Dolby Vision RPU overrides the plain transfer-function reading.
            # The base layer of a DV P5 file carries no VUI colour description;
            # the decoder promotes it to PQ so the pipeline builds a tone-mapper,
            # but the signal is really IPTPQc2 reshaped by the RPU. Once the
            # renderer has consumed that RPU (med.dovi==1) the honest label for
            # both the gamut and the EOTF is Dolby Vision, not the promoted PQ.
            dovi = bool(med.get("dovi", 0))
            self._apply(self._r_colorspace, "Dolby Vision" if dovi else _h(_COLORSPACE, prim, "—"),
                        reason="media.prim+dovi")
            self._apply(self._r_transfer, "Dolby Vision" if dovi else _h(_TRANSFER, tfc, "—"),
                        reason="media.tf+dovi")
            mhdr = med.get("hdr")
            if dovi:
                hf, hs = "Dolby Vision", _LIVE_STYLE
            elif med.get("tf") == 15:      # MFVideoTransFunc_2084
                hf, hs = "HDR10 / PQ", _LIVE_STYLE
            elif med.get("tf") == 16:    # MFVideoTransFunc_HLG
                hf, hs = "HLG", _LIVE_STYLE
            elif mhdr:
                hf, hs = "HDR10 / PQ", _LIVE_STYLE
            else:
                hf, hs = "SDR", _VAL_STYLE
            self._apply(self._r_hdr_format, hf, hs, reason="media.dovi/tf/hdr")
            bpp = _MF_BYTESPP.get(med.get("fmt", -1))
            if bpp and med.get("w") and med.get("fps"):
                bit = med["w"] * med["h"] * bpp * 8 * med["fps"]
                self._apply(self._r_bitrate, f"≈ {bit / 1e9:.3f} Gbps",
                            reason="computed w*h*fmt*fps")
            else:
                self._apply(self._r_bitrate, "—")
        else:
            # Capture mode: the card's own detect + raw v210 ingest bitrate.
            cs = dl.get("cs", 0); eotf = dl.get("eotf", 0)
            self._apply(self._r_colorspace, _effective_cs(j, dl, eotf),
                        reason="dl.cs/cfg.ics")
            self._apply(self._r_transfer,
                        "PQ (BT.2084)" if eotf == 2 else
                        "HLG" if eotf == 3 else
                        "Dolby Vision" if eotf == 4 else "—",
                        reason="dl.eotf")
            self._apply(self._r_hdr_format,
                        "Dolby Vision" if eotf == 4 else
                        "HDR10 (PQ)" if eotf == 2 else
                        "HDR HLG" if eotf == 3 else
                        "SDR" if med.get("hdr") else "—",
                        reason="dl.eotf")
            bpp = dl.get("w"), dl.get("h"), dl.get("fpsNum"), dl.get("fpsDen")
            if all(bpp) and bpp[3]:
                bit = ((bpp[0] + 47) // 48) * 128 * bpp[1] * 8 * bpp[2] / bpp[3]
                self._apply(self._r_bitrate, f"{bit / 1e9:.3f} Gbps",
                            reason="raw v210 rate")
            else:
                self._apply(self._r_bitrate, "—")

        # ── CAPTURE INPUT (authoritative engine signal fallback) ──────
        # ST 2086, as the CARD read it. Always-present rows; "—" when there is no
        # reading, which is the honest answer for DV and SDR — those carry no static
        # metadata at all, so there is nothing to show rather than a failed read.
        # Tells on_property's mpv path to stand off these rows while the card is
        # supplying them — otherwise it hides them again on the next video-params.
        self._card_hdr_meta = bool(dl.get("hdrMeta"))
        # Log the transition once per change, printing EXACTLY what the engine's JSON
        # delivered. Without this, "the panel shows nothing" cannot be told apart from
        # "the engine never sent it", and that ambiguity cost a whole evening.
        if self._card_hdr_meta != getattr(self, "_card_hdr_prev", None):
            self._card_hdr_prev = self._card_hdr_meta
            _log.info("s3: card HDR meta=%s  maxCLL=%s maxFALL=%s masterMax=%s masterMin=%s",
                      dl.get("hdrMeta"), dl.get("maxCLL"), dl.get("maxFALL"),
                      dl.get("masterMax"), dl.get("masterMin"))
        if self._card_hdr_meta:
            self._apply(self._r_card_cll, f"{float(dl.get('maxCLL') or 0):.0f} nits",
                        reason="dl.maxCLL")
            self._apply(self._r_card_fall, f"{float(dl.get('maxFALL') or 0):.0f} nits",
                        reason="dl.maxFALL")
            self._apply(self._r_card_mmax, f"{float(dl.get('masterMax') or 0):.0f} nits",
                        reason="dl.masterMax")
            _mn = float(dl.get("masterMin") or 0)
            self._apply(self._r_card_mmin,
                        f"{_mn:.4f} nits" if _mn >= 0.0001 else "<0.0001 nits",
                        reason="dl.masterMin")
        else:
            # File path: the renderer read the content's own ST 2086 (MaxCLL /
            # MaxFALL / master max·min) from the decoded sample side data — the
            # engine carries it as cfg.mdr (parsed from the pipeline dump, mmin
            # in DXGI scale 0.0001 cd/m²). Populate the same four rows from it;
            # "—" only when neither the card nor the renderer has any reading
            # (DV/SDR carry no static metadata at all).
            mdr = (j.get("cfg") or {}).get("mdr") or {}
            # NOTE: must NOT reference the `cfg` local — it is defined later,
            # in the TONE section, and a NameError here kills every row update
            # after this point (regression 2026-09-23, caught by the blank
            # TONE/PERFORMANCE/RENDER CHAIN sections).
            _cll  = int(mdr.get("cll") or 0)
            _fall = int(mdr.get("fall") or 0)
            _mmax = int(mdr.get("mmax") or 0)
            _mmin = int(mdr.get("mmin") or 0)
            got = _cll or _fall or _mmax or _mmin
            self._apply(self._r_card_cll, f"{_cll} nits" if _cll else "—",
                        reason="cfg.mdr.cll")
            self._apply(self._r_card_fall, f"{_fall} nits" if _fall else "—",
                        reason="cfg.mdr.fall")
            self._apply(self._r_card_mmax, f"{_mmax} nits" if _mmax else "—",
                        reason="cfg.mdr.mmax")
            self._apply(self._r_card_mmin,
                        (f"{_mmin / 10000:.4f} nits" if _mmin >= 1
                         else "<0.0001 nits") if _mmin else "—",
                        reason="cfg.mdr.mmin")
            if not got:
                for _r in (self._r_card_cll, self._r_card_fall,
                           self._r_card_mmax, self._r_card_mmin):
                    self._apply(_r, "—", reason="no ST2086 source")

        locked = bool(dl.get("stream")) or bool(sig.get("locked"))
        if locked:
            self._r_capture_lock.set("●  LOCKED", _LOCK_STYLE)
            fmt = f"{dl.get('w')}×{dl.get('h')}"
            if dl.get("fpsDen") and dl.get("fpsNum"):
                fmt += f" @ {dl.get('fpsNum') / dl.get('fpsDen'):.3f} fps"
            # Use ONLY the filter's dl.cs (1=601/2=709/3=2020). The monitor's
            # signal read uses a DIFFERENT numbering (0=601/1=709/2=2020) and
            # sig.cs=2 (2020) rendered as "BT.709" here — observed on the bench.
            fmt += "  ·  " + _effective_cs(j, dl, dl.get("eotf", 0))
            fmt += " · " + ("HDR" if dl.get("eotf") in (2, 3, 4) else "SDR")
            self._r_capture_format.set(fmt)
        else:
            self._r_capture_lock.set("●  NO SIGNAL", _UNLOCK_STYLE)

        # ── TONE (algo from the curve the engine holds; peak/APL measured live) ──
        cfg = j.get("cfg") or {}
        hd = j.get("hdr") or {}
        curve = _MPCVR_CURVE.get(hd.get("curve", 0), "auto")
        self._apply(self._r_tm_algo, _h(_TM_ALGO, curve),
                    reason="hdr.curve")
        tgt = cfg.get("sdrNits")
        if tgt:
            self._apply(self._r_target_peak,
                        f"{tgt} nits (SDR)" if cfg.get("convSdr") else f"{tgt} nits",
                        reason="cfg.sdrNits")
        else:
            self._apply(self._r_target_peak, "—")
        try:
            sp = float(cfg.get("scPeak") or 0)
            sa = float(cfg.get("scAvg") or 0)
        except (TypeError, ValueError):
            sp = sa = 0.0
        self._apply(self._r_measured_peak,
                    f"{self._pq_to_nits(sp)} nits" if sp > 0 else "—",
                    reason="cfg.scPeak")
        self._apply(self._r_apl,
                    f"{self._pq_to_nits(sa)} nits" if sa > 0 else "—",
                    reason="cfg.scAvg")

        # ── PERFORMANCE ───────────────────────────────────────────────
        self._apply(self._r_fps_disp, f"{rec.get('draw', 0):.2f} fps",
                    reason="render.draw")
        self._apply(self._r_dropped, str(rec.get("drop", 0)), reason="render.drop")
        self._apply(self._r_delayed, str(rec.get("skip", 0)), reason="render.skip")
        self._apply(self._r_paused, j.get("state", "idle").upper(), reason="state")

        # ── RENDER CHAIN (delv is framesReceived on the file path — the engine's
        #    JSON maps it so Delivered == Renderer recv holds, see GetUiStatusJson)
        self._apply(self._r_rc_recv, str(rec.get("recv", 0)), reason="render.recv")
        self._apply(self._r_rc_dlv, str(dl.get("delv", 0)),
                    reason="dl.delv (file=recv)")
        self._apply(self._r_rc_skip, str(dl.get("skip", 0)), reason="dl.skip")
        self._apply(self._r_rc_gate, str(dl.get("gate", 0)), reason="dl.gate")
        self._apply(self._r_rc_qdrop, str(dl.get("qdrop", 0)), reason="dl.qdrop")
        self._apply(self._r_rc_reneg, str(dl.get("reneg", 0)), reason="dl.reneg")
        self._apply(self._r_rc_lag, f"{rec.get('lagMs', 0):.0f} ms",
                    reason="render.lagMs")
        ref = dl.get("refUs", 0) or 0
        if ref:
            self._apply(self._r_rc_stream, f"{ref / 1e6:.0f} s", reason="dl.refUs")
        elif j.get("pos"):
            self._apply(self._r_rc_stream, f"{j.get('pos', 0) / 1e7:.0f} s",
                        reason="media pos")
        else:
            self._apply(self._r_rc_stream, "—")

    def on_zion_stats(self, stats: dict) -> None:
        """Update the ZION CORE section from a parsed ML: log line."""
        self._set_zion_visible(True)

        build = stats.get("build", "")
        if build:
            self._r_zion_build.set(build, _DIM_STYLE)

        gamma = stats.get("oracle_gamma", 0.0)
        source = stats.get("oracle_source", "")
        is_model = source == "model"
        g_style = _LIVE_STYLE if is_model else _WARN_STYLE
        self._r_zion_gamma.set(f"{gamma:.3f}  ({source})", g_style)

        cr = stats.get("cr_strength", 0.0)
        cr_mode = stats.get("cr_mode", "")
        if cr_mode == "off":
            self._r_zion_cr.set("off", _DIM_STYLE)
        else:
            self._r_zion_cr.set(f"{cr:.3f}  ({cr_mode})", _VAL_STYLE)

        rs = stats.get("rad_strength", 0.0)
        rk = stats.get("rad_knee", 0.0)
        rm = stats.get("rad_mode", "")
        if rm == "off":
            self._r_zion_rad.set("off", _DIM_STYLE)
        else:
            self._r_zion_rad.set(f"str {rs:.2f}  knee {rk:.2f}  ({rm})", _VAL_STYLE)

        chroma = stats.get("chroma_mode", "")
        self._r_zion_chroma.set(chroma, _DIM_STYLE if chroma == "off" else _VAL_STYLE)

        shad_s = stats.get("shadow_strength", 0.0)
        shad_k = stats.get("shadow_knee", 0.0)
        if shad_s > 0.001:
            self._r_zion_shadow.set(f"str {shad_s:.3f}  knee {shad_k:.2f}", _VAL_STYLE)
        else:
            self._r_zion_shadow.set("off", _DIM_STYLE)

        hi_s = stats.get("highlight_strength", 0.0)
        hi_k = stats.get("highlight_knee", 0.0)
        if hi_s > 0.001:
            self._r_zion_hi.set(f"str {hi_s:.3f}  knee {hi_k:.2f}", _LIVE_STYLE)
        else:
            self._r_zion_hi.set("off", _DIM_STYLE)

        l1max = stats.get("l1max", 0.0)
        if l1max > 0:
            try:
                nits = self._pq_to_nits(l1max)
                self._r_zion_l1max.set(f"{nits} nits  (PQ {l1max:.4f})", _VAL_STYLE)
            except Exception:
                self._r_zion_l1max.set(f"PQ {l1max:.4f}", _VAL_STYLE)
        else:
            self._r_zion_l1max.set("—", _DIM_STYLE)

        eval_ms = stats.get("eval_ms", 0.0)
        iir_ms = stats.get("iir_ms", 0.0)
        self._r_zion_eval.set(f"{eval_ms:.2f} ms eval  /  {iir_ms:.2f} ms IIR", _DIM_STYLE)


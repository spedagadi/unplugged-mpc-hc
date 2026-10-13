"""
Unplugged UI theme — font and colour constants applied app-wide.

Colour roles:
  ACCENT     orange #E8551F  — brand accent (selection, focus, active tab)
  ACCENT_HI  orange #FF8A4C  — hover / highlight state
  PRIMARY    green  #4caf50  — signal locked / good state (keep green — semantic)
  WARNING    amber  #ff9800  — starting/transitioning
  DANGER     red    #f44336  — error/no-signal/stop action
  TEXT_HI    #F2F2F2         — primary text
  TEXT_MID   #8A8A90         — secondary labels
  TEXT_LO    #5a5a5a         — placeholder / disabled / hint text
  SURFACE    rgba(14,14,16,235) — panel background (brand panel colour)
  BORDER     #242428         — subtle 1px separators (brand border)
"""

from __future__ import annotations
from PyQt6.QtGui import QFont, QFontDatabase


# ── Colours ───────────────────────────────────────────────────────────
ACCENT   = "#E8551F"   # Unplugged brand orange — selection, focus, active tab
ACCENT_HI = "#FF8A4C"  # Hover / highlight
PRIMARY  = "#4caf50"   # Keep green for signal-locked / running state
WARNING  = "#ff9800"
DANGER   = "#f44336"
INFO     = "#29b6f6"   # light blue — used for signal/IPC state

TEXT_HI  = "#F2F2F2"
TEXT_MID = "#8A8A90"
TEXT_LO  = "#5a5a5a"

SURFACE    = "rgba(14, 14, 16, 235)"
SURFACE_HI = "rgba(30, 30, 32, 240)"
BORDER     = "#242428"
BORDER_HI  = "rgba(255,255,255,45)"

# ── Panel surface — ONE background for every frame region ─────────────
# The status rail (rgba(8,8,8,220) — near-black), the settings rail (opaque
# #0E0E10) and the bottom bar (a black gradient) were three different colours
# sitting side by side in the same frame. They all use this now.
PANEL_RGB   = (14, 14, 16)      # the brand panel grey
PANEL_ALPHA = 235               # translucent, so the video reads faintly through
PANEL_BG    = f"rgba({PANEL_RGB[0]}, {PANEL_RGB[1]}, {PANEL_RGB[2]}, {PANEL_ALPHA})"
PANEL_HEX   = "#%02X%02X%02X" % PANEL_RGB


def panel_qcolor():
    """The panel surface as a QColor, for QPainter-drawn surfaces."""
    from PyQt6.QtGui import QColor
    return QColor(PANEL_RGB[0], PANEL_RGB[1], PANEL_RGB[2], PANEL_ALPHA)


# ── Font ──────────────────────────────────────────────────────────────
# ONE definition for the whole UI. Stylesheet-driven widgets (the status panel)
# get it through BASE_QSS; QPainter-drawn surfaces (the settings rail) get it
# through ui_font(). Both read the same stack and the same sizes, so the rail
# and the status panel cannot drift apart.
FONT_STACK = ["Inter", "Segoe UI", "SF Pro Display", "Ubuntu"]

FONT_PX_BASE  = 14     # px — readable on high-DPI home theater displays
FONT_PX_VALUE = 13     # values, readouts, secondary text
FONT_PX_LABEL = 12     # row labels, subgroup headers

# Kept for the existing call sites below.
_FONT_SIZE_BASE = FONT_PX_BASE
_FONT_SIZE_SM   = FONT_PX_VALUE
_FONT_SIZE_XS   = FONT_PX_LABEL

_FONT_FAMILY = ", ".join(f'"{f}"' for f in FONT_STACK) + ", sans-serif"


def ui_font(px: int, weight: QFont.Weight = QFont.Weight.Normal,
            spacing: float | None = None) -> QFont:
    """The UI font for QPainter surfaces — same resolution as BASE_QSS.

    Uses the whole stack rather than a single family so it falls back exactly
    the way a stylesheet does, which is what keeps the rail matching the
    status panel.
    """
    f = QFont()
    f.setFamilies(FONT_STACK)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing is not None:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def _load_inter_fonts() -> None:
    """Register the bundled Inter .ttf files so Qt can use them.

    Was a hardcoded `C:\\htpc\\mpv-portable\\assets\\unplugged-brand\\fonts` —
    an HTPC-machine path that does not exist anywhere else. The fonts ship in
    the app's own assets tree now.
    """
    from ..assets import asset

    for ttf in sorted(asset("brand", "fonts").glob("Inter-*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))


def app_font() -> QFont:
    """Return the base application font (Inter preferred)."""
    _load_inter_fonts()
    families = ["Inter", "Segoe UI", "SF Pro Display", "Ubuntu"]
    available = QFontDatabase.families()
    for fam in families:
        if fam in available:
            f = QFont(fam, _FONT_SIZE_BASE)
            f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            return f
    f = QFont()
    f.setFamily("sans-serif")
    f.setPointSize(_FONT_SIZE_BASE)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


# ── QSS snippets (injected into widget stylesheets) ───────────────────
BASE_QSS = f"""
* {{
    font-family: {_FONT_FAMILY};
    font-size: {_FONT_SIZE_BASE}px;
    color: {TEXT_HI};
}}
QToolTip {{
    background: #1e1e1e;
    color: {TEXT_HI};
    border: 1px solid {BORDER_HI};
    border-radius: 4px;
    padding: 5px 10px;
    font-size: {_FONT_SIZE_SM}px;
}}
"""

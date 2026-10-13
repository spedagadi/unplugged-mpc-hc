"""
ui/s3_settings.py — the s3_shell settings panel, ported to Qt 1:1.

Every value here is taken from tools/engine_s3/s3_shell.cpp (the reference):

  panel width 440 · rail 80 (icon tab 58, step 64) · tab bar 34 · row 40 · pad 16
  columns: label at rail+pad, controls right-aligned in [w-148 .. w-pad]
  toggle 46x22 pill (ON = ACCENT bg + black text) · cycle "‹  opt  ›"
  slider = thin band (ACCENT fill, ACCENT2 thumb) + min/max under it + value right
  fonts: section 11 semibold · label 12 · value 13 · button 12 · icon 30 semibold
  palette: BG/PANEL #0E0E10 · BORDER #242428 · ACCENT #E8551F · ACCENT2 #FF8A4C
           TEXT #F2F2F2 · MID #8A8A90 · LO #5A5A5A · OK #4CAF50

Persistence matches the shell: s3_shell.ini next to the executable, debounced
400 ms, pushed to the engine at startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSlider, QStackedWidget, QVBoxLayout,
                             QWidget)

# ─ palette (COL_* from s3_shell.cpp) ───────────────────────────────────────
BG      = "#0E0E10"
BORDER  = "#242428"
ACCENT  = "#E8551F"
ACCENT2 = "#FF8A4C"
TEXT    = "#F2F2F2"
MID     = "#8A8A90"
LO      = "#5A5A5A"
OK      = "#4CAF50"

PANEL_W   = 440
RAIL_W    = 80
TAB_H     = 34
ICON_H    = 58
ICON_STEP = 64
ROW_H     = 40
PAD       = 16

# glyph, label, tint, categories  (kSysGroups, verbatim)
GROUPS = [
    ("⬡", "SOURCE", "#5B8FD0", ["Input Device"]),
    ("◑", "HDR",    "#C8A030", ["Tone Mapping", "Display Target"]),
    ("✦", "ZION",   "#C87040", ["Chroma", "Micro Contrast", "Black Bars",
                                     "Sky Seg", "Person Skin", "Debug"]),
    ("▣", "OUTPUT", "#4CAF78", ["Video Processing", "Output"]),
    ("≡", "SYSTEM", "#909090", ["App"]),
]

TOGGLE, SLIDER, CYCLE = "toggle", "slider", "cycle"

# group, section, label, kind, ini key, options | (min,max,default,decimals)
ROWS = [
    (1, "Tone Mapping", "Prefer DV over PQ/HLG", TOGGLE, "hdr.preferDoVi", None),
    (1, "Tone Mapping", "Convert to SDR",        TOGGLE, "hdr.convertToSdr", None),
    (1, "Tone Mapping", "SDR display nits",      SLIDER, "hdr.sdrNits", (25, 400, 50, 0)),
    (1, "Tone Mapping", "Soft knee (off=0)",    SLIDER, "hdr.softKnee", (0, 4, 0.6, 2)),
    (1, "Tone Mapping", "Soft knee ratio",      SLIDER, "hdr.softKneeRatio", (1, 5, 2.48, 2)),
    (1, "Tone Mapping", "Soft knee width",      SLIDER, "hdr.softKneeWidth", (0.05, 1, 0.42, 2)),
    (1, "Tone Mapping", "Scene ref white (nits)", SLIDER, "hdr.refWhite", (50, 400, 203, 0)),
    (1, "Tone Mapping", "Highlight neutral (head)", SLIDER, "hdr.highlightNeutral",
        (0, 1.0, 0.9, 2)),
    (1, "Tone Mapping", "Chroma desat (exp)",      SLIDER, "hdr.chromaExp",
        (-1.0, 3.5, 1.35, 2)),
    (1, "Tone Mapping", "Tone curve",            CYCLE,  "hdr.toneMapCurve",
        ["ACES", "Reinhard", "Hable", "Mobius", "BT-2390"]),
    (1, "Display Target", "Windows HDR",         CYCLE,  "hdr.toggleDisplay",
        ["Do not change", "On (fullscreen)", "On", "On/off (fullscreen)", "On/off"]),
    (1, "Display Target", "Static nits (max)",   SLIDER, "hdr.maxNits", (200, 10000, 1000, 0)),
    (1, "Display Target", "Subtitle/OSD brightness", SLIDER, "hdr.osdBright", (0, 100, 0, 0)),
]


def settings_ini_path() -> Path:
    """Next to the executable (dev tree: the app dir), like the shell's."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parents[3]
    cand = base / "s3_shell.ini"
    try:
        with open(cand, "a", encoding="utf-8"):
            return cand
    except OSError:
        home = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".unplugged"
        home.mkdir(parents=True, exist_ok=True)
        return home / "s3_shell.ini"


class SettingsIni:
    def __init__(self, path: Path) -> None:
        self.path, self.values, self._dirty = path, {}, False
        self._t = QTimer(); self._t.setSingleShot(True); self._t.setInterval(400)
        self._t.timeout.connect(self.save)
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    self.values[k.strip()] = v.strip()
        except OSError:
            pass

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value) -> None:
        self.values[key] = str(value); self._dirty = True; self._t.start()

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            lines = ["# unplugged engine settings (s3_shell schema)"]
            lines += [f"{k}={self.values[k]}" for k in sorted(self.values)]
            self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._dirty = False
        except OSError:
            pass


# ── control widgets (drawn to the shell's metrics) ──────────────────────────
class _RowLabel(QLabel):
    def __init__(self, text: str, live: bool) -> None:
        super().__init__(text)
        self.setStyleSheet(f"color: {TEXT if live else MID}; font-size: 12px;")


class _Toggle(QPushButton):
    def __init__(self, on: bool) -> None:
        super().__init__("ON" if on else "OFF")
        self.setCheckable(True); self.setChecked(on)
        self.setFixedSize(46, 22)
        self.setStyleSheet(
            f"QPushButton {{ background: #2A2A2E; border: 1px solid {BORDER};"
            f" color: {MID}; font-size: 12px; }}"
            f"QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT2};"
            f" color: #000000; }}")
        self.toggled.connect(lambda v: self.setText("ON" if v else "OFF"))


class _Cycle(QPushButton):
    def __init__(self, options: list, index: int) -> None:
        super().__init__()
        self._opts = options; self._i = max(0, min(index, len(options) - 1))
        self._refresh()
        self.setFixedWidth(140)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {MID};"
            f" text-align: right; font-size: 13px; }}")
        self.clicked.connect(self._next)

    def _refresh(self) -> None:
        self.setText(f"〈  {self._opts[self._i]}  〉")

    def _next(self) -> None:
        self._i = (self._i + 1) % len(self._opts)
        self._refresh()

    def index(self) -> int:
        return self._i


class _SliderRow(QWidget):
    """band + min/max under it + value right — the shell's slider row."""

    def __init__(self, lo, hi, val, dec) -> None:
        super().__init__()
        self._dec = dec
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * 10), int(hi * 10))
        self.slider.setValue(int(val * 10))
        self.slider.setFixedWidth(150)
        self.slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 4px; background: {TEXT}; }}"
            f"QSlider::sub-page:horizontal {{ background: {ACCENT}; }}"
            f"QSlider::handle:horizontal {{ width: 12px; margin: -4px 0;"
            f" background: {ACCENT2}; }}")
        self.min_lbl = QLabel(f"{lo:g}"); self.max_lbl = QLabel(f"{hi:g}")
        for l in (self.min_lbl, self.max_lbl):
            l.setStyleSheet(f"color: {MID}; font-size: 11px;")
        self.val_lbl = QLabel(f"{val:.{dec}f}")
        self.val_lbl.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        self.val_lbl.setFixedWidth(56)
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(
            lambda v: self.val_lbl.setText(f"{v / 10:.{dec}f}"))
        lay.addWidget(self.slider)
        lay.addWidget(self.min_lbl); lay.addWidget(self.max_lbl)
        lay.addWidget(self.val_lbl)


class S3SettingsPanel(QWidget):
    def __init__(self, engine=None, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.ini = SettingsIni(settings_ini_path())
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {BG};")

        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(self._build_rail())

        right = QVBoxLayout(); right.setContentsMargins(0, 0, 0, 0); right.setSpacing(0)
        right.addWidget(self._build_tabbar())
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_group_pages())
        self._stack.addWidget(QLabel("Playback — later"))
        right.addWidget(self._stack, 1)
        root.addLayout(right, 1)
        self._stack.setCurrentIndex(0)

    # ---------------------------------------------------------------- rail
    def _build_rail(self) -> QWidget:
        rail = QWidget(); rail.setFixedWidth(RAIL_W)
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setStyleSheet(f"background: {BG};")
        v = QVBoxLayout(rail); v.setContentsMargins(0, TAB_H, 0, 0); v.setSpacing(0)
        for i, (glyph, label, tint, _c) in enumerate(GROUPS):
            b = QPushButton()
            b.setFixedSize(RAIL_W, ICON_H)
            b.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            b.setStyleSheet(
                f"QPushButton {{ background: {BG}; border: none; }}"
                f"QPushButton:hover {{ background: #1E1E20; }}")
            bl = QVBoxLayout(b); bl.setContentsMargins(0, 4, 0, 2); bl.setSpacing(0)
            gl = QLabel(glyph); tl = QLabel(label)
            gl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            gl.setStyleSheet(f"color: {tint}; font-size: 22px; background: transparent;")
            tl.setStyleSheet(f"color: {MID}; font-size: 11px; letter-spacing: 1px;"
                             f" background: transparent;")
            bl.addWidget(gl); bl.addWidget(tl)
            for child in (gl, tl):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            b.clicked.connect(lambda _=False, idx=i: self._show_group(idx))
            v.addWidget(b)
        v.addStretch()
        return rail

    def _show_group(self, idx: int) -> None:
        self._group_stack.setCurrentIndex(idx)

    def _build_tabbar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(TAB_H)
        h = QHBoxLayout(bar); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        for text in ("▶  Playback", "⚙  System"):
            b = QPushButton(text); b.setFixedHeight(TAB_H)
            b.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            b.setStyleSheet(
                f"QPushButton {{ background: {BG}; border: 1px solid {BORDER};"
                f" color: {TEXT}; font-size: 12px; }}"
                f"QPushButton:hover {{ background: #232327; }}")
            h.addWidget(b)
        return bar

    # ------------------------------------------------------------- content
    def _build_group_pages(self) -> QWidget:
        self._group_stack = QStackedWidget()
        for gi, (_g, _l, _t, cats) in enumerate(GROUPS):
            page = QWidget()
            page.setStyleSheet(f"background: {BG};")
            v = QVBoxLayout(page); v.setContentsMargins(PAD, 8, PAD, 8); v.setSpacing(2)

            # category line — the shell lists the group's categories joined by ·
            cat = QLabel("  ·  ".join(cats))
            cat.setStyleSheet(f"color: {MID}; font-size: 11px; font-weight: 600;")
            cat.setFixedHeight(26)
            v.addWidget(cat)

            cur_sec = None
            for (rg, sec, label, kind, key, spec) in [r for r in ROWS if r[0] == gi]:
                if sec != cur_sec:
                    cur_sec = sec
                    line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
                    line.setFixedHeight(1)
                    line.setStyleSheet(f"background: {BORDER}; border: none;")
                    v.addWidget(line)
                v.addWidget(self._make_row(label, kind, key, spec))
            v.addStretch()

            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._group_stack.addWidget(page)
        self._group_stack.setCurrentIndex(1)          # HDR first
        return self._group_stack

    def _make_row(self, label: str, kind: str, key: str, spec) -> QWidget:
        w = QWidget(); w.setFixedHeight(ROW_H)
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        h.addWidget(_RowLabel(label, live=True))
        h.addStretch()

        cur = self.ini.get(key)

        if kind == TOGGLE:
            on = str(cur) in ("1", "True", "true")
            t = _Toggle(on)
            t.toggled.connect(lambda v, k=key: self._commit(k, 1 if v else 0))
            h.addWidget(t)

        elif kind == SLIDER:
            lo, hi, dflt, dec = spec
            try:
                val = float(cur) if cur is not None else float(dflt)
            except (TypeError, ValueError):
                val = float(dflt)
            sr = _SliderRow(lo, hi, val, dec)
            # write on RELEASE only (agreed)
            sr.slider.sliderReleased.connect(
                lambda k=key, s=sr, d=dec: self._commit(k, round(s.slider.value() / 10, d or 3)))
            h.addWidget(sr)

        elif kind == CYCLE:
            idx = 0
            if cur is not None:
                try:
                    idx = int(cur)
                except ValueError:
                    idx = 0
            c = _Cycle(spec, idx)
            c.clicked.connect(lambda _=False, k=key, wgt=c: self._commit(k, wgt.index()))
            h.addWidget(c)

        return w

    # ---------------------------------------------------------------- io
    def _commit(self, key: str, value) -> None:
        self.ini.set(key, value)
        grp, name = key.split(".", 1)
        if self.engine is not None:
            try:
                self.engine.apply_settings({grp: {name: value}})
            except Exception:
                pass

    def push_all(self) -> None:
        if self.engine is None or not self.ini.values:
            return
        groups: dict[str, dict] = {}
        for k, v in self.ini.values.items():
            if "." not in k:
                continue
            g, name = k.split(".", 1)
            try:
                val = float(v) if ("." in v or v.lstrip("-").isdigit()) else v
            except ValueError:
                val = v
            groups.setdefault(g, {})[name] = val
        try:
            self.engine.apply_settings(groups)
        except Exception:
            pass
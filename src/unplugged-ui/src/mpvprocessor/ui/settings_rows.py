"""
Shared row widgets and page class for remote-friendly two-level navigation panels.

Used by SettingsPanel and PlaybackControlsPanel.
"""
from __future__ import annotations

from typing import List, Optional

import math as _math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QDialog, QLineEdit, QSlider,
)

# ── Display-name lookup tables ─────────────────────────────────────────────────
_DISPLAY_TRC = {
    "auto":      "Auto  (mpv default)",
    "gamma1.8":  "Gamma 1.8  (Apple RGB)",
    "gamma2.0":  "Gamma 2.0",
    "gamma2.2":  "Gamma 2.2  (sRGB reference)",
    "gamma2.4":  "Gamma 2.4  (cinema / projector)",
    "gamma2.6":  "Gamma 2.6",
    "gamma2.8":  "Gamma 2.8  (BT.470-BG)",
    "srgb":      "sRGB  (IEC 61966-2-4)",
    "bt.1886":   "BT.1886  (HDTV, infinite contrast)",
    "linear":    "Linear light",
    "pq":        "PQ  (HDR10 / ST.2084)",
    "hlg":       "HLG  (Hybrid Log-Gamma)",
    "prophoto":  "ProPhoto RGB (ROMM)",
    "v-log":     "V-Log  (Panasonic VARICAM)",
    "s-log1":    "S-Log1  (Sony)",
    "s-log2":    "S-Log2  (Sony)",
}
_DISPLAY_PRIM = {
    "auto":        "Auto",
    "bt.709":      "BT.709 (HD)",
    "bt.2020":     "BT.2020 (UHD)",
    "bt.601-525":  "BT.601-525 (NTSC)",
    "bt.601-625":  "BT.601-625 (PAL)",
    "display-p3":  "Display P3 (Apple)",
    "dci-p3":      "DCI-P3 (Cinema)",
    "bt.470m":     "BT.470M",
    "apple":       "Apple RGB",
    "adobe":       "Adobe RGB",
    "prophoto":    "ProPhoto RGB",
    "cie1931":     "CIE 1931",
    "v-gamut":     "V-Gamut (Panasonic)",
    "s-gamut":     "S-Gamut (Sony)",
}
_DISPLAY_TM = {
    # Valid --tone-mapping values per mpv options.rst
    # NOTE: 'saturation' is a gamut-mapping mode, NOT a tone-mapping algorithm.
    "auto":       "Auto",
    "spline":     "Spline",
    "bt.2390":    "BT.2390",
    "bt.2446a":   "BT.2446a",
    "st2094-40":  "ST.2094-40 (HDR10+)",
    "st2094-10":  "ST.2094-10 (DV fallback)",
    "reinhard":   "Reinhard",
    "mobius":     "Möbius",
    "hable":      "Hable (Filmic)",
    "gamma":      "Gamma",
    "linear":     "Linear",
    "clip":       "Clip (no tone-map)",
}
_DISPLAY_GAMUT = {
    # Valid --gamut-mapping-mode values per mpv options.rst
    # NOTE: 'softclip' does not exist in mpv — it was a UI error.
    "auto":       "Auto",
    "perceptual": "Perceptual",
    "relative":   "Relative Colorimetric",
    "saturation": "Saturation",
    "absolute":   "Absolute Colorimetric",
    "desaturate": "Desaturate",
    "linear":     "Linear",
    "darken":     "Darken",
    "warn":       "Warn (debug)",
    "clip":       "Clip (hard)",
}
_DISPLAY_PEAK = {
    "yes": "Per-frame", "no": "Manual", "auto": "Auto",
}
_DISPLAY_KERN = {
    "spline36": "Spline36", "mitchell": "Mitchell", "catmull_rom": "Catmull-Rom",
    "lanczos": "Lanczos", "bicubic": "Bicubic", "bilinear": "Bilinear",
    "ewa_lanczos": "EWA Lanczos", "ewa_lanczossharp": "EWA Lanczos Sharp",
}

__all__ = [
    "_BG", "_ROW_NORMAL", "_ROW_FOCUSED", "_ROW_H",
    "_show_entry_dialog",
    "_Row", "_CategoryRow", "_EnumRow", "_BoolRow",
    "_IntRow", "_FloatRow", "_ActionRow", "_PickerRow", "_RowPage",
    "_DISPLAY_TRC", "_DISPLAY_PRIM", "_DISPLAY_TM", "_DISPLAY_GAMUT",
    "_DISPLAY_PEAK", "_DISPLAY_KERN",
]

# ── Colours ───────────────────────────────────────────────────────────────────
_BG          = "transparent"
# Scoped to objectName="row" so the border never cascades to child labels
_ROW_NORMAL  = "QWidget#row { background: transparent; border-radius: 6px; }"
_ROW_FOCUSED = "QWidget#row { background: transparent; border: 1px solid rgba(232,85,31,200); border-radius: 6px; }"
_ROW_H       = 52   # px — comfortable for remote
_SLIDER_H    = 56   # px — slider area height when expanded

_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 4px; background: rgba(255,255,255,20); border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 20px; height: 20px; border-radius: 10px;
    background: #E8551F; margin: -8px 0;
}
QSlider::sub-page:horizontal { background: #E8551F; border-radius: 2px; }
QSlider::add-page:horizontal { background: rgba(255,255,255,12); border-radius: 2px; }
"""

# ── Row types ─────────────────────────────────────────────────────────────────

class _Row(QWidget):
    """Base focusable row.  Subclasses handle ←→ value changes."""
    activated = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        self.setMinimumHeight(_ROW_H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._focused = False
        self._refresh_style()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Fixed-height top strip: label + value
        self._top = QWidget()
        self._top.setFixedHeight(_ROW_H)
        self._top.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(self._top)
        # Asymmetric margins: 14px left, 24px right — values breathe away from edge
        hl.setContentsMargins(14, 0, 24, 0)
        hl.setSpacing(8)

        self._label = QLabel(label)
        self._label.setStyleSheet("color:#cccccc; font-size:12px; background:transparent;")
        hl.addWidget(self._label, 1)

        self._value_lbl = QLabel("")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value_lbl.setStyleSheet("color:#E8551F; font-size:12px; font-weight:600; background:transparent;")
        self._value_lbl.setMaximumWidth(130)   # prevent very long values from reaching the edge
        hl.addWidget(self._value_lbl)

        outer.addWidget(self._top)

    def set_focused(self, v: bool):
        self._focused = v
        self._refresh_style()

    def _refresh_style(self):
        self.setStyleSheet(_ROW_FOCUSED if self._focused else _ROW_NORMAL)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Sync page focus index before acting so keyboard follow-up is correct
            page = getattr(self, "_page_ref", None)
            if page is not None and self in page._rows:
                page._focus_idx = page._rows.index(self)
                page._update_focus()
            self.handle_enter()
        elif event.button() == Qt.MouseButton.RightButton:
            self.handle_left()
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        # Strict rule: wheel only changes value on the EXPLICITLY focused row
        # (selected via click or keyboard navigation).  On any unfocused row
        # the event is ignored by this widget and propagated to the parent
        # scroll area so the list scrolls instead.
        if not self._focused:
            event.ignore()   # let QScrollArea handle it — scrolls the list
            return
        if event.angleDelta().y() > 0:
            self.handle_right()
        else:
            self.handle_left()
        event.accept()

    def handle_left(self): pass
    def handle_right(self): pass
    def handle_enter(self): self.activated.emit()


class _CategoryRow(_Row):
    """Top-level list entry — shows chevron."""
    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self._value_lbl.setText("›")
        self._value_lbl.setStyleSheet("color:#555; font-size:18px; background:transparent;")
        if self._focused:
            self._value_lbl.setStyleSheet("color:#E8551F; font-size:18px; background:transparent;")

    def _refresh_style(self):
        super()._refresh_style()
        if not hasattr(self, "_value_lbl"):
            return
        color = "#E8551F" if self._focused else "#555"
        self._value_lbl.setStyleSheet(f"color:{color}; font-size:18px; background:transparent;")


class _EnumRow(_Row):
    """Cycles through a list of string options with ← →."""
    value_changed = pyqtSignal(str)

    def __init__(self, label: str, options: List[str], current: str,
                 display_map: dict = None, parent=None):
        super().__init__(label, parent)
        self._options = options
        self._display_map = display_map
        self._idx = options.index(current) if current in options else 0
        self._show()

    def _show(self):
        val = self._options[self._idx] if self._options else "—"
        if val != "—":
            if self._display_map is not None and val in self._display_map:
                display = self._display_map[val]
            else:
                display = val.upper() if val == val.lower() and len(val) <= 6 else val.capitalize()
        else:
            display = val
        self._value_lbl.setText(display)

    def handle_left(self):
        if self._options:
            self._idx = (self._idx - 1) % len(self._options)
            self._show(); self.value_changed.emit(self._options[self._idx])

    def handle_right(self):
        if self._options:
            self._idx = (self._idx + 1) % len(self._options)
            self._show(); self.value_changed.emit(self._options[self._idx])

    def handle_enter(self): self.handle_right()

    def set_value(self, v: str):
        if v in self._options:
            self._idx = self._options.index(v)
            self._show()


class _BoolRow(_Row):
    """Toggle on/off with Enter or ←/→."""
    value_changed = pyqtSignal(bool)

    def __init__(self, label: str, current: bool, parent=None):
        super().__init__(label, parent)
        self._val = current
        self._show()

    def _show(self):
        self._value_lbl.setText("On" if self._val else "Off")
        color = "#E8551F" if self._val else "#555"
        self._value_lbl.setStyleSheet(f"color:{color}; font-size:14px; font-weight:600; background:transparent;")

    def _toggle(self):
        self._val = not self._val
        self._show(); self.value_changed.emit(self._val)

    def handle_left(self):
        if self._val: self._toggle()
    def handle_right(self):
        if not self._val: self._toggle()
    def handle_enter(self): self._toggle()

    def set_value(self, v: bool):
        self._val = v; self._show()


def _show_entry_dialog(parent: QWidget, label: str, current: str,
                       lo, hi, is_int: bool):
    """
    Inline value-entry dialog. Returns new_value on confirm, None on cancel.
    """
    dlg = QDialog(parent, Qt.WindowType.FramelessWindowHint)
    dlg.setModal(True)
    dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dlg.setStyleSheet("QDialog { background: transparent; }")

    card = QWidget(dlg)
    card.setObjectName("card")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet("""
        QWidget#card {
            background: #111111;
            border: 1.5px solid rgba(100,100,100,200);
            border-radius: 12px;
        }
        QLabel { background: transparent; color: #aaaaaa; font-size: 13px; }
        QLineEdit {
            background: rgba(40,40,40,255);
            border: 1px solid rgba(232,85,31,180);
            border-radius: 6px;
            color: #ffffff;
            font-size: 18px;
            padding: 8px 14px;
        }
    """)

    vl = QVBoxLayout(card)
    vl.setContentsMargins(24, 20, 24, 20)
    vl.setSpacing(10)

    hint = QLabel(f"{label}  ({lo} – {hi})")
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    vl.addWidget(hint)

    edit = QLineEdit(current)
    edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    edit.selectAll()
    vl.addWidget(edit)

    sub = QLabel("Enter to confirm  ·  Esc to cancel")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setStyleSheet("background: transparent; color: #555; font-size: 11px;")
    vl.addWidget(sub)

    card.setFixedWidth(300)
    card.adjustSize()
    dlg.setFixedSize(300, card.height())

    # Centre on parent
    p = parent
    while p.parent():
        p = p.parent()
    pg = p.geometry()
    dlg.move(pg.x() + (pg.width() - 300) // 2,
             pg.y() + (pg.height() - card.height()) // 2)

    result = [None]

    def _confirm():
        txt = edit.text().strip()
        try:
            v = int(txt) if is_int else float(txt)
            v = max(lo, min(hi, v))
            result[0] = v
            dlg.accept()
        except ValueError:
            edit.setStyleSheet(edit.styleSheet() +
                               "QLineEdit { border-color: #f44336; }")

    edit.returnPressed.connect(_confirm)
    dlg.exec()
    return result[0]


_SLIDER_STEPS = 2000   # resolution of all sliders


def _build_slider_widget(row: "_Row") -> QWidget:
    """Create the collapsible slider strip placed below the label row."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    vl = QVBoxLayout(w)
    vl.setContentsMargins(16, 2, 16, 10)
    vl.setSpacing(2)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, _SLIDER_STEPS)
    slider.setStyleSheet(_SLIDER_STYLE)
    vl.addWidget(slider)

    range_row = QHBoxLayout()
    range_row.setContentsMargins(0, 0, 0, 0)
    lo_lbl = QLabel(); lo_lbl.setStyleSheet("color:#444; font-size:11px; background:transparent;")
    hi_lbl = QLabel(); hi_lbl.setStyleSheet("color:#444; font-size:11px; background:transparent;")
    hi_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
    range_row.addWidget(lo_lbl, 1)
    range_row.addWidget(hi_lbl, 1)
    vl.addLayout(range_row)

    w._slider  = slider
    w._lo_lbl  = lo_lbl
    w._hi_lbl  = hi_lbl
    return w


class _IntRow(_Row):
    """Integer with inline expand-on-focus slider. ←/→ for fine nudge."""
    value_changed = pyqtSignal(int)

    def __init__(self, label: str, lo: int, hi: int, current: int,
                 step: int = 1, log_scale: bool = False, parent=None):
        super().__init__(label, parent)
        self._lo, self._hi, self._step = lo, hi, step
        self._log = log_scale and lo > 0
        self._val = current
        self._show()
        self._sw = _build_slider_widget(self)
        self._sw._lo_lbl.setText(str(lo))
        self._sw._hi_lbl.setText(str(hi))
        self.layout().addWidget(self._sw)
        self._sw.hide()
        self._sw._slider.valueChanged.connect(self._on_slider)

    def _val_to_pos(self, v: int) -> int:
        if self._log:
            return round(_SLIDER_STEPS * _math.log(max(1, v) / self._lo)
                         / _math.log(self._hi / self._lo))
        return round(_SLIDER_STEPS * (v - self._lo) / (self._hi - self._lo))

    def _pos_to_val(self, pos: int) -> int:
        if self._log:
            return round(self._lo * (self._hi / self._lo) ** (pos / _SLIDER_STEPS))
        return round(self._lo + pos * (self._hi - self._lo) / _SLIDER_STEPS)

    def _show(self): self._value_lbl.setText(str(self._val))

    def _sync_slider(self):
        s = self._sw._slider
        s.blockSignals(True)
        s.setValue(self._val_to_pos(self._val))
        s.blockSignals(False)

    def _on_slider(self, pos: int):
        v = max(self._lo, min(self._hi, self._pos_to_val(pos)))
        if v != self._val:
            self._val = v; self._show(); self.value_changed.emit(self._val)

    def set_focused(self, focused: bool):
        super().set_focused(focused)
        if focused:
            self._sync_slider()
            self._sw.show()
            # Grow the row so the expanded slider strip sits BELOW the value
            # strip instead of painting over it (the overlap row bug).
            self.setMinimumHeight(_ROW_H + self._sw.sizeHint().height())
        else:
            self._sw.hide()
            self.setMinimumHeight(_ROW_H)

    def handle_left(self):
        v = max(self._lo, self._val - self._step)
        if v != self._val:
            self._val = v; self._show(); self._sync_slider(); self.value_changed.emit(self._val)

    def handle_right(self):
        v = min(self._hi, self._val + self._step)
        if v != self._val:
            self._val = v; self._show(); self._sync_slider(); self.value_changed.emit(self._val)

    def handle_enter(self): pass   # slider is inline — no dialog needed

    def set_value(self, v: int):
        self._val = v; self._show()
        if self._focused: self._sync_slider()


class _FloatRow(_Row):
    """Float with inline expand-on-focus slider. ←/→ for fine nudge."""
    value_changed = pyqtSignal(float)

    def __init__(self, label: str, lo: float, hi: float, current: float,
                 step: float = 0.1, decimals: int = 2,
                 log_scale: bool = False, parent=None):
        super().__init__(label, parent)
        self._lo, self._hi, self._step = lo, hi, step
        self._decimals = decimals
        self._log = log_scale and lo > 0
        self._val = current
        self._show()
        self._sw = _build_slider_widget(self)
        lo_s = f"{lo:.{decimals}f}"; hi_s = f"{hi:.{decimals}f}"
        self._sw._lo_lbl.setText(lo_s); self._sw._hi_lbl.setText(hi_s)
        self.layout().addWidget(self._sw)
        self._sw.hide()
        self._sw._slider.valueChanged.connect(self._on_slider)

    def _val_to_pos(self, v: float) -> int:
        if self._log:
            return round(_SLIDER_STEPS * _math.log(max(1e-9, v) / self._lo)
                         / _math.log(self._hi / self._lo))
        return round(_SLIDER_STEPS * (v - self._lo) / (self._hi - self._lo))

    def _pos_to_val(self, pos: int) -> float:
        if self._log:
            return round(self._lo * (self._hi / self._lo) ** (pos / _SLIDER_STEPS),
                         self._decimals)
        return round(self._lo + pos * (self._hi - self._lo) / _SLIDER_STEPS,
                     self._decimals)

    def _show(self): self._value_lbl.setText(f"{self._val:.{self._decimals}f}")

    def _sync_slider(self):
        s = self._sw._slider
        s.blockSignals(True)
        s.setValue(self._val_to_pos(self._val))
        s.blockSignals(False)

    def _on_slider(self, pos: int):
        v = round(max(self._lo, min(self._hi, self._pos_to_val(pos))), self._decimals)
        if v != self._val:
            self._val = v; self._show(); self.value_changed.emit(self._val)

    def set_focused(self, focused: bool):
        super().set_focused(focused)
        if focused:
            self._sync_slider()
            self._sw.show()
            self.setMinimumHeight(_ROW_H + self._sw.sizeHint().height())
        else:
            self._sw.hide()
            self.setMinimumHeight(_ROW_H)

    def handle_left(self):
        v = round(max(self._lo, self._val - self._step), self._decimals)
        if v != self._val:
            self._val = v; self._show(); self._sync_slider(); self.value_changed.emit(self._val)

    def handle_right(self):
        v = round(min(self._hi, self._val + self._step), self._decimals)
        if v != self._val:
            self._val = v; self._show(); self._sync_slider(); self.value_changed.emit(self._val)

    def handle_enter(self): pass   # slider is inline — no dialog needed

    def set_value(self, v: float):
        self._val = round(v, self._decimals); self._show()
        if self._focused: self._sync_slider()


class _ActionRow(_Row):
    """A row that just fires activated() — used for buttons like 'Configure inputs'."""
    def __init__(self, label: str, sub: str = "", parent=None):
        super().__init__(label, parent)
        self._value_lbl.setText(sub)
        self._value_lbl.setStyleSheet("color:#888; font-size:13px; background:transparent;")


class _PickerRow(_Row):
    """Shows current selection + › and opens a full picker page on Enter/click."""
    picked = pyqtSignal(str)   # emits the selected option string

    def __init__(self, label: str, options: List[str], current: str, parent=None):
        super().__init__(label, parent)
        self._options = options
        self._current = current if current in options else (options[0] if options else "")
        self._show()
        self._value_lbl.setStyleSheet("color:#aaaaaa; font-size:14px; background:transparent;")

    def _show(self):
        self._value_lbl.setText(self._current + "  ›")

    def set_value(self, v: str):
        self._current = v
        self._show()

    def handle_enter(self): self.activated.emit()   # panel intercepts and opens picker page
    def handle_right(self): pass
    def handle_left(self):  pass


# ── Page widget ───────────────────────────────────────────────────────────────

class _RowPage(QWidget):
    """A scrollable list of _Row widgets with keyboard navigation."""
    focus_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[_Row] = []
        self._focus_idx: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 4px; border-radius: 2px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,35); border-radius: 2px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._inner)
        self._list.setContentsMargins(4, 4, 4, 4)
        self._list.setSpacing(3)
        self._list.addStretch()
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)
        self._scroll = scroll

        # Footer widget — lives INSIDE the scroll content, between rows and stretch.
        # Never destroyed by clear() — rescued before clear, re-inserted after build.
        self._footer_slot = QWidget()
        self._footer_slot.setStyleSheet("background: transparent;")
        fl = QVBoxLayout(self._footer_slot)
        fl.setContentsMargins(0, 0, 0, 0)
        # Initially insert before the trailing stretch
        self._list.insertWidget(self._list.count() - 1, self._footer_slot)

    def set_footer(self, widget: QWidget) -> None:
        """Assign a persistent widget as the page footer (flush after last row)."""
        layout = self._footer_slot.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        widget.setParent(self._footer_slot)
        layout.addWidget(widget)
        widget.show()               # reparenting hides — must re-show explicitly
        self._footer_slot.show()

    def _rescue_footer(self) -> None:
        """Remove footer from list layout (keeps it alive — not deleted)."""
        self._list.removeWidget(self._footer_slot)

    def _restore_footer(self) -> None:
        """Re-insert footer after last row, before the trailing stretch."""
        self._list.insertWidget(self._list.count() - 1, self._footer_slot)

    def clear(self):
        self._rescue_footer()
        for r in self._rows:
            r.deleteLater()
        self._rows.clear()
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._focus_idx = 0

    def add_row(self, row: _Row):
        row._page_ref = self
        # Always insert before the footer_slot and stretch
        # footer_slot is at count-2 (before stretch), rows go before it
        footer_pos = self._list.indexOf(self._footer_slot)
        pos = footer_pos if footer_pos >= 0 else self._list.count() - 1
        self._list.insertWidget(pos, row)
        self._rows.append(row)

    def activate(self):
        """Called when this page becomes visible — ensure focus row is highlighted."""
        self._update_focus()

    def _update_focus(self):
        for i, r in enumerate(self._rows):
            r.set_focused(i == self._focus_idx)
        if self._rows:
            self._scroll.ensureWidgetVisible(self._rows[self._focus_idx])
            self.focus_changed.emit(self._rows[self._focus_idx])

    def handle_up(self):
        if not self._rows: return
        self._focus_idx = (self._focus_idx - 1) % len(self._rows)
        self._update_focus()

    def handle_down(self):
        if not self._rows: return
        self._focus_idx = (self._focus_idx + 1) % len(self._rows)
        self._update_focus()

    def handle_left(self):
        if self._rows: self._rows[self._focus_idx].handle_left()

    def handle_right(self):
        if self._rows: self._rows[self._focus_idx].handle_right()

    def handle_enter(self):
        if self._rows: self._rows[self._focus_idx].handle_enter()

    def focused_row(self) -> Optional[_Row]:
        if self._rows: return self._rows[self._focus_idx]
        return None

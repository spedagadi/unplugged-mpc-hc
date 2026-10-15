"""
PlaybackBar — timeline + audio controls overlay.

Shown at the bottom of the window above the control bar when the mouse moves.
Auto-hides with the control bar after 3s of inactivity.

IPC properties observed:
  time-pos   → current playback position in seconds
  duration   → total duration in seconds
  pause      → bool
  mute       → bool
  volume     → 0-100

All seek/volume/mute commands sent via MpvIpcBridge.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QPainter, QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSlider,
)
from .theme import PANEL_BG


def _fmt_time(secs) -> str:
    if secs is None:
        return "--:--"
    try:
        s = int(float(secs))
    except (TypeError, ValueError):
        return "--:--"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


# Panel surface, same as the rails and the top bar (was a black gradient).
_BAR_BG = f"background: {PANEL_BG};"
_BTN = """
QPushButton {
    color: #e0e0e0; background: transparent; border: none;
    font-size: 16px; padding: 2px 6px; min-width: 28px;
}
QPushButton:hover { color: #ffffff; }
"""
_TIME = "color: #cccccc; font-size: 11px; background: transparent;"
_SEEK_GROOVE = """
QSlider::groove:horizontal {
    height: 4px; background: rgba(255,255,255,25); border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #E8551F; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px; height: 14px; border-radius: 7px;
    background: #ffffff; margin: -5px 0;
}
"""
_VOL_GROOVE = """
QSlider::groove:horizontal {
    height: 3px; background: rgba(255,255,255,25); border-radius: 1px;
}
QSlider::sub-page:horizontal {
    background: rgba(255,255,255,60); border-radius: 1px;
}
QSlider::handle:horizontal {
    width: 11px; height: 11px; border-radius: 5px;
    background: #ffffff; margin: -4px 0;
}
"""


class PlaybackBar(QWidget):
    # Emitted when user seeks — float seconds
    seek_requested = pyqtSignal(float)
    pause_toggled  = pyqtSignal()
    mute_toggled   = pyqtSignal()
    volume_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget {{ {_BAR_BG} }}")
        self.setFixedHeight(72)

        self._duration: float = 0.0
        self._position: float = 0.0
        self._seeking = False   # user is dragging the seek bar

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 6, 16, 4)
        root.setSpacing(4)

        # ── Seek bar row ──────────────────────────────────────────────
        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)

        self._pos_lbl = QLabel("0:00")
        self._pos_lbl.setStyleSheet(_TIME)
        self._pos_lbl.setFixedWidth(42)
        seek_row.addWidget(self._pos_lbl)

        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setValue(0)
        self._seek.setStyleSheet(_SEEK_GROOVE)
        self._seek.sliderPressed.connect(self._on_seek_start)
        self._seek.sliderReleased.connect(self._on_seek_end)
        seek_row.addWidget(self._seek, 1)

        self._dur_lbl = QLabel("--:--")
        self._dur_lbl.setStyleSheet(_TIME)
        self._dur_lbl.setFixedWidth(42)
        self._dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._dur_lbl)
        root.addLayout(seek_row)

        # ── Controls row ──────────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setStyleSheet(_BTN)
        self._pause_btn.setToolTip("Pause / Resume  (Space)")
        self._pause_btn.clicked.connect(self.pause_toggled)
        ctrl_row.addWidget(self._pause_btn)

        ctrl_row.addStretch()

        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setStyleSheet(_BTN)
        self._mute_btn.setToolTip("Mute / Unmute  (M)")
        self._mute_btn.clicked.connect(self.mute_toggled)
        ctrl_row.addWidget(self._mute_btn)

        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 130)   # mpv supports 0-130%
        self._vol.setValue(100)
        self._vol.setFixedWidth(90)
        self._vol.setStyleSheet(_VOL_GROOVE)
        self._vol.valueChanged.connect(self.volume_changed)
        ctrl_row.addWidget(self._vol)

        self._vol_lbl = QLabel("100%")
        self._vol_lbl.setStyleSheet(_TIME)
        self._vol_lbl.setFixedWidth(36)
        ctrl_row.addWidget(self._vol_lbl)

        root.addLayout(ctrl_row)

    # ------------------------------------------------------------------
    # State updates — called from MainWindow via IPC property signals
    # ------------------------------------------------------------------

    def update_position(self, pos) -> None:
        if pos is None:
            return
        try:
            self._position = float(pos)
        except (TypeError, ValueError):
            return
        self._pos_lbl.setText(_fmt_time(self._position))
        if self._duration > 0 and not self._seeking:
            self._seek.blockSignals(True)
            self._seek.setValue(int(self._position / self._duration * 1000))
            self._seek.blockSignals(False)

    def update_duration(self, dur) -> None:
        if dur is None:
            return
        try:
            self._duration = float(dur)
        except (TypeError, ValueError):
            return
        self._dur_lbl.setText(_fmt_time(self._duration))

    def update_pause(self, paused) -> None:
        self._pause_btn.setText("▶" if paused else "⏸")

    def update_mute(self, muted) -> None:
        self._mute_btn.setText("🔇" if muted else "🔊")

    def set_volume_active(self, enabled: bool, hint: str = "") -> None:
        """Dim (or light) the volume slider and mute button for the current audio mode.

        In bitstream the receiver decodes and owns the level, so a live slider there is a
        lie: it moves and nothing happens. Dimming it with the reason in the tooltip is
        the honest version, and it is what MPC-HC's own behaviour amounts to.
        """
        for w in (self._vol, self._mute_btn, self._vol_lbl):
            w.setEnabled(enabled)
            if hint:
                w.setToolTip(hint)

    def update_volume(self, vol) -> None:
        try:
            v = int(float(vol))
        except (TypeError, ValueError):
            return
        self._vol.blockSignals(True)
        self._vol.setValue(v)
        self._vol.blockSignals(False)
        self._vol_lbl.setText(f"{v}%")

    def reset(self) -> None:
        self._duration = 0.0
        self._position = 0.0
        self._seek.setValue(0)
        self._pos_lbl.setText("0:00")
        self._dur_lbl.setText("--:--")
        self._pause_btn.setText("⏸")
        self._mute_btn.setText("🔊")

    # ------------------------------------------------------------------
    # Seek interaction
    # ------------------------------------------------------------------

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        self._seeking = False
        if self._duration > 0:
            target = self._seek.value() / 1000.0 * self._duration
            self.seek_requested.emit(target)


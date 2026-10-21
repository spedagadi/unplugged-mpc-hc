"""
Status bar — frameless title bar with drag-to-move and window controls.

Colour coding:
  Signal dot   green/amber/red based on state
  mpv state    colour-coded: Running=green, Crashed=red, else mid-grey
  Preset name  info blue
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

from ..core.signal_monitor import SignalState
from ..core.process_manager import ProcessState
from .theme import PRIMARY, WARNING, DANGER, INFO, TEXT_HI, TEXT_MID, TEXT_LO, BORDER, PANEL_BG


_SIGNAL_COLORS = {
    SignalState.ACTIVE:      PRIMARY,
    SignalState.STARTING:    WARNING,
    SignalState.RESTARTING:  WARNING,
    SignalState.NO_SIGNAL:   DANGER,
    SignalState.IDLE:        TEXT_LO,
}
_SIGNAL_LABELS = {
    SignalState.ACTIVE:      "Active",
    SignalState.STARTING:    "Starting…",
    SignalState.RESTARTING:  "Restarting…",
    SignalState.NO_SIGNAL:   "No Signal",
    SignalState.IDLE:        "Idle",
}
_PROCESS_COLORS = {
    ProcessState.RUNNING:  PRIMARY,
    ProcessState.STARTING: WARNING,
    ProcessState.STOPPING: WARNING,
    ProcessState.CRASHED:  DANGER,
    ProcessState.STOPPED:  TEXT_LO,
}
_PROCESS_LABELS = {
    ProcessState.STOPPED:  "Stopped",
    ProcessState.STARTING: "Starting…",
    ProcessState.RUNNING:  "Running",
    ProcessState.STOPPING: "Stopping…",
    ProcessState.CRASHED:  "Crashed",
}

_WC = f"""
QPushButton {{
    color: {TEXT_LO};
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 0px 5px;
    min-width: 24px;
}}
QPushButton:hover {{ color: {TEXT_HI}; background: rgba(255,255,255,18); border-radius: 3px; }}
"""
_WC_CLOSE = _WC + f"QPushButton:hover {{ background: {DANGER}; color: #fff; }}"


def _lbl(text: str, color: str, size: int = 13) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {color}; font-size: {size}px; background: transparent;")
    return l


def _sep() -> QLabel:
    s = QLabel("·")
    s.setStyleSheet(f"color: {TEXT_LO}; font-size: 13px; background: transparent;")
    return s


class StatusBar(QWidget):
    minimize_clicked = pyqtSignal()
    close_clicked    = pyqtSignal()
    report_clicked   = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget {{ background: {PANEL_BG}; }}")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(8)

        # App version, top-left: what a user reads out when reporting a problem.
        try:
            from .. import __version__ as _ver
        except Exception:   # noqa: BLE001
            _ver = ""
        self._version_lbl = _lbl(f"Unplugged {_ver}".strip(), TEXT_LO, 12)
        self._version_lbl.setToolTip("Installed Unplugged version")
        layout.addWidget(self._version_lbl)

        self._report_btn = QPushButton("Report a problem")
        self._report_btn.setStyleSheet(_WC.replace("font-size: 13px", "font-size: 12px"))
        self._report_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._report_btn.setToolTip("Save a diagnostics file to send to support")
        self._report_btn.clicked.connect(self.report_clicked)
        layout.addWidget(self._report_btn)

        layout.addStretch()

        # Preset name
        preset_tag = _lbl("Preset", TEXT_LO, 12)
        layout.addWidget(preset_tag)

        self._preset_lbl = _lbl("—", TEXT_HI, 13)
        layout.addWidget(self._preset_lbl)

        layout.addSpacing(6)

        # Window controls
        btn_min = QPushButton("–")
        btn_min.setStyleSheet(_WC)
        btn_min.setFixedSize(28, 28)
        btn_min.clicked.connect(self.minimize_clicked)

        btn_close = QPushButton("✕")
        btn_close.setStyleSheet(_WC_CLOSE)
        btn_close.setFixedSize(28, 28)
        btn_close.clicked.connect(self.close_clicked)

        layout.addWidget(btn_min)
        layout.addWidget(btn_close)

    # Drag-to-move
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_pos is not None:
            win = self.window()
            if win and not (win.isFullScreen() or win.isMaximized()):
                delta = e.globalPosition().toPoint() - self._drag_pos
                win.move(win.pos() + delta)
                self._drag_pos = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        win = self.window()
        if win:
            win.showNormal() if win.isFullScreen() else win.showFullScreen()

    # State updates
    def set_app_mode(self, mode: str) -> None:
        """Show signal indicator only in video_processor mode."""
        show = mode == "video_processor"
        pass

    def update_signal_state(self, state: SignalState) -> None:
        pass

    def update_process_state(self, state: ProcessState) -> None:
        pass  # process state label removed — signal dot in status bar is sufficient

    def update_profile(self, name: str) -> None:
        self._preset_lbl.setText(name)


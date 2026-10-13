"""
Mode selector — a two-button toggle shown at the very top of the settings
panel (above all setting groups).

VideoProcessor  |  Media Player

Emits mode_changed("video_processor" | "media_player") when switched.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel

_BTN_ACTIVE = """
QPushButton {
    color: #ffffff;
    background: rgba(76,175,80,160);
    border: 1px solid rgba(76,175,80,200);
    border-radius: 5px;
    padding: 6px 18px;
    font-size: 12px;
    font-weight: 600;
}
"""

_BTN_INACTIVE = """
QPushButton {
    color: #888888;
    background: rgba(40,40,40,180);
    border: 1px solid rgba(255,255,255,18);
    border-radius: 5px;
    padding: 6px 18px;
    font-size: 12px;
}
QPushButton:hover {
    color: #cccccc;
    background: rgba(60,60,60,200);
    border-color: rgba(255,255,255,35);
}
"""


class ModeSelector(QWidget):
    mode_changed = pyqtSignal(str)   # "video_processor" | "media_player"

    def __init__(self, current_mode: str = "video_processor", parent=None) -> None:
        super().__init__(parent)
        self._mode = current_mode
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(12,12,12,220);")
        self.setFixedHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("color:#666; font-size:11px; background:transparent;")
        layout.addWidget(mode_lbl)

        self._btn_vp = QPushButton("📡  Video Processor")
        self._btn_vp.clicked.connect(lambda: self._select("video_processor"))
        layout.addWidget(self._btn_vp)

        self._btn_mp = QPushButton("🎬  Media Player")
        self._btn_mp.clicked.connect(lambda: self._select("media_player"))
        layout.addWidget(self._btn_mp)

        layout.addStretch()
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def current_mode(self) -> str:
        return self._mode

    def _select(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._refresh()
        self.mode_changed.emit(mode)

    def _refresh(self) -> None:
        self._btn_vp.setStyleSheet(
            _BTN_ACTIVE if self._mode == "video_processor" else _BTN_INACTIVE
        )
        self._btn_mp.setStyleSheet(
            _BTN_ACTIVE if self._mode == "media_player" else _BTN_INACTIVE
        )

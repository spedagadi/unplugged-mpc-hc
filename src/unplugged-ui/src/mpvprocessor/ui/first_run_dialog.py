"""
FirstRunDialog — shown on first launch to guide mode selection and input setup.

Flow:
  Step 1: Choose mode (Video Processor / Media Player)
  Step 2 (VP only): Select and label capture inputs, see signal status
  → Emits setup_complete(mode, active_url) when done
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame,
)

from ..config.model import AppConfig
from .input_config_panel import InputConfigPanel


_STYLE = """
QDialog { background: #0f0f0f; }
QWidget { background: transparent; color: #e0e0e0; }
QScrollArea { background: transparent; border: none; }
QLineEdit {
    background: rgba(50,50,50,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 4px; color: #e0e0e0;
    padding: 5px 10px; font-size: 13px; min-width: 180px;
}
QFrame[frameShape="4"] { color: rgba(255,255,255,15); }
"""

_MODE_BTN = """
QPushButton {{
    color: {fg};
    background: rgba(30,30,30,220);
    border: 2px solid {border};
    border-radius: 12px;
    padding: 20px 28px;
    font-size: 14px;
    font-weight: 600;
    min-width: 180px;
    min-height: 100px;
    text-align: center;
}}
QPushButton:hover {{
    background: rgba(50,50,50,240);
    border-color: {hover};
}}
"""

_BTN_PRIMARY = """
QPushButton {
    color: #ffffff; background: rgba(76,175,80,180);
    border: 1px solid rgba(76,175,80,220); border-radius: 6px;
    padding: 9px 28px; font-size: 13px; font-weight: 600;
}
QPushButton:hover { background: rgba(76,175,80,240); }
QPushButton:disabled { background: rgba(50,50,50,150); color: #555; border-color: rgba(255,255,255,15); }
"""
_BTN_SECONDARY = """
QPushButton {
    color: #888; background: transparent;
    border: 1px solid rgba(255,255,255,20); border-radius: 6px;
    padding: 9px 20px; font-size: 12px;
}
QPushButton:hover { color: #ccc; border-color: rgba(255,255,255,40); }
"""



class FirstRunDialog(QDialog):
    setup_complete = pyqtSignal(str, str)  # (mode, active_input_url)

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self.setFixedSize(860, 560)
        self._app_config = app_config
        self._input_panel: InputConfigPanel | None = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._show_step1()
        self._center_on_screen()

    # ------------------------------------------------------------------
    # Step 1 — Mode selection
    # ------------------------------------------------------------------

    def _show_step1(self) -> None:
        self._clear()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 44, 48, 44)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header
        title = QLabel("Welcome to unplugged")
        title.setStyleSheet("color:#ffffff; font-size:22px; font-weight:700;")
        layout.addWidget(title)

        sub = QLabel("How would you like to use unplugged?")
        sub.setStyleSheet("color:#888; font-size:13px;")
        layout.addWidget(sub)

        layout.addSpacing(16)

        # Mode buttons side by side
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        vp_btn = QPushButton("📡  Video Processor\n\nCapture live HDR signal\nfrom DeckLink card\nwith tone mapping")
        vp_btn.setStyleSheet(_MODE_BTN.format(
            fg="#4caf50", border="rgba(76,175,80,120)", hover="rgba(76,175,80,220)"))
        vp_btn.clicked.connect(self._on_vp_selected)
        btn_row.addWidget(vp_btn)

        mp_btn = QPushButton("🎬  Media Player\n\nPlay local files\nMKV, MP4, BD rips\nwith HDR tone mapping")
        mp_btn.setStyleSheet(_MODE_BTN.format(
            fg="#29b6f6", border="rgba(41,182,246,80)", hover="rgba(41,182,246,180)"))
        mp_btn.clicked.connect(lambda: self.setup_complete.emit("media_player", ""))
        btn_row.addWidget(mp_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

        footer = QLabel("You can switch modes anytime from the Settings panel.")
        footer.setStyleSheet("color:#444; font-size:11px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        self._root.addWidget(page)

    # ------------------------------------------------------------------
    # Step 2 — Input selection (VP mode)
    # ------------------------------------------------------------------

    def _on_vp_selected(self) -> None:
        self._clear()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 36, 48, 36)
        layout.setSpacing(14)

        title = QLabel("Select Capture Input")
        title.setStyleSheet("color:#ffffff; font-size:20px; font-weight:700;")
        layout.addWidget(title)

        sub = QLabel("Choose which HDMI port to capture from and give each one a name.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#888; font-size:12px;")
        layout.addWidget(sub)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: rgba(255,255,255,12);")
        layout.addWidget(div)

        self._input_panel = InputConfigPanel(self._app_config)
        layout.addWidget(self._input_panel, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_mp = QPushButton("🎬  Use Media Player instead")
        btn_mp.setStyleSheet(_BTN_SECONDARY)
        btn_mp.setAutoDefault(False)
        btn_mp.clicked.connect(lambda: self.setup_complete.emit("media_player", ""))
        btn_row.addWidget(btn_mp)
        btn_row.addStretch()

        back_btn = QPushButton("Back")
        back_btn.setStyleSheet(_BTN_SECONDARY)
        back_btn.setAutoDefault(False)
        back_btn.clicked.connect(self._show_step1)
        btn_row.addWidget(back_btn)

        self._start_btn = QPushButton("▶  Start Capture")
        self._start_btn.setStyleSheet(_BTN_PRIMARY)
        self._start_btn.setAutoDefault(True)
        self._start_btn.setDefault(True)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        layout.addLayout(btn_row)

        self._root.addWidget(page)

    def _on_start(self) -> None:
        if self._input_panel:
            self._input_panel.save_labels()
            url = self._input_panel.active_url()
        else:
            url = self._app_config.active_input_url or ""
        if url:
            self._app_config.active_input_url = url
        self.setup_complete.emit("video_processor", url)

    # ------------------------------------------------------------------

    def _clear(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _center_on_screen(self) -> None:
        from PyQt6.QtWidgets import QApplication
        from .input_config_panel import _center_on_screen as _cs
        _cs(self)


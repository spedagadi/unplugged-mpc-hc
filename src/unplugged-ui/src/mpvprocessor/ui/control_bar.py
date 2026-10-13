"""
Control bar — bottom overlay strip.
Start · Stop · Restart  |  profile picker  |  Settings
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QComboBox, QLabel, QFrame
from .theme import PRIMARY, DANGER, TEXT_HI, TEXT_MID, TEXT_LO, BORDER, BORDER_HI, PANEL_BG


_BTN = f"""
QPushButton {{
    color: {TEXT_HI};
    background: rgba(255,255,255,12);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 20px;
    font-size: 12px;
    min-width: 74px;
}}
QPushButton:hover   {{ background: rgba(255,255,255,28); border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: rgba(255,255,255,10); }}
QPushButton:disabled {{ color: {TEXT_LO}; border-color: rgba(255,255,255,10); }}
"""
_BTN_START    = _BTN + f"QPushButton {{ border-color: rgba(232,85,31,160); }}"
_BTN_STOP     = _BTN + f"QPushButton {{ border-color: rgba(244,67,54,160); }}"
_BTN_SETTINGS = _BTN + f"QPushButton {{ min-width: 36px; padding: 7px 12px; }}"
_BTN_INFO     = _BTN + f"QPushButton {{ min-width: 36px; padding: 7px 12px; color: rgba(150,200,255,220); }}"
_BTN_RESTART_PENDING = _BTN + (
    "QPushButton { border-color: rgba(255,193,7,200); color: rgba(255,193,7,230); }"
    "QPushButton:hover { border-color: rgba(255,193,7,255); }"
)

_COMBO = f"""
QComboBox {{
    color: {TEXT_MID};
    background: rgba(255,255,255,10);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 11px;
    min-width: 150px;
}}
QComboBox:hover {{ border-color: {BORDER_HI}; color: {TEXT_HI}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: #1a1a1a;
    color: {TEXT_HI};
    selection-background-color: {PRIMARY};
    border: 1px solid {BORDER};
    outline: none;
}}
"""


class ControlBar(QWidget):
    restart_clicked  = pyqtSignal()
    stop_clicked     = pyqtSignal()
    settings_clicked = pyqtSignal()
    profile_selected = pyqtSignal(str)
    manage_clicked   = pyqtSignal()
    mode_changed     = pyqtSignal(str)   # "video_processor" | "media_player"
    info_clicked     = pyqtSignal()      # toggles mpv stats OSD

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget {{ background: {PANEL_BG}; border-radius: 8px; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        self._btn_restart = QPushButton("⟳  Restart")
        self._btn_restart.setStyleSheet(_BTN)
        self._btn_restart.setToolTip(
            "Restart — reconnects signal and resyncs A/V.\n"
            "Use this to fix sync drift in Video Processor mode.")
        self._btn_restart.clicked.connect(self.restart_clicked)
        layout.addWidget(self._btn_restart)

        self._btn_stop = QPushButton("◼  Stop")
        self._btn_stop.setStyleSheet(_BTN_STOP)
        self._btn_stop.setToolTip("Stop playback and return to media library")
        self._btn_stop.clicked.connect(self.stop_clicked)
        self._btn_stop.hide()   # shown only in media player mode while playing
        layout.addWidget(self._btn_stop)

        # (vertical divider removed by design — spacing separates the groups)

        # Mode toggle — always visible, compact
        self._mode_vp = QPushButton("📡")
        self._mode_vp.setToolTip("Video Processor — live HDMI capture")
        self._mode_vp.setFixedSize(34, 34)
        self._mode_vp.clicked.connect(lambda: self._switch_mode("video_processor"))

        self._mode_mp = QPushButton("🎬")
        self._mode_mp.setToolTip("Media Player — play local files")
        self._mode_mp.setFixedSize(34, 34)
        self._mode_mp.clicked.connect(lambda: self._switch_mode("media_player"))

        layout.addWidget(self._mode_vp)
        layout.addWidget(self._mode_mp)
        self._current_mode = "video_processor"
        self._refresh_mode_buttons()

        layout.addStretch()

        # Preset picker
        preset_lbl = QLabel("Preset:")
        preset_lbl.setStyleSheet(f"color: {TEXT_LO}; font-size: 11px; background: transparent;")
        layout.addWidget(preset_lbl)

        self._profile_combo = QComboBox()
        self._profile_combo.setStyleSheet(_COMBO)
        self._profile_combo.currentTextChanged.connect(self.profile_selected)
        layout.addWidget(self._profile_combo)

        self._btn_manage = QPushButton("Manage…")
        self._btn_manage.setStyleSheet(_BTN)
        self._btn_manage.clicked.connect(self.manage_clicked)
        layout.addWidget(self._btn_manage)

        layout.addSpacing(8)

        # ℹ Info — toggles mpv stats OSD showing per-pass GPU timing
        self._btn_info = QPushButton("ℹ")
        self._btn_info.setStyleSheet(_BTN_INFO)
        self._btn_info.setToolTip(
            "Frame timing info\n"
            "Shows per-pass GPU timing: decode, tone map,\n"
            "Zion Core shader passes, upscale, and swap.\n"
            "Click again to dismiss.")
        self._btn_info.setFixedSize(36, 36)
        self._btn_info.clicked.connect(self.info_clicked)
        layout.addWidget(self._btn_info)

        layout.addSpacing(4)

        self._btn_settings = QPushButton("⚙")
        self._btn_settings.setStyleSheet(_BTN_SETTINGS)
        self._btn_settings.setToolTip("Settings  (Ctrl+Space)")
        self._btn_settings.clicked.connect(self.settings_clicked)
        layout.addWidget(self._btn_settings)

        self.set_running(False)
        self._edit_mode = False

        # Install focus glow on all buttons
        from .focus_style import FocusGlow
        for btn in (self._btn_restart, self._btn_stop, self._mode_vp, self._mode_mp,
                    self._btn_manage, self._btn_info, self._btn_settings):
            FocusGlow.install(btn)
        # Make control bar itself focusable for remote / arrow navigation
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_restart_pending(self, pending: bool) -> None:
        """Highlight the Restart button amber when a setting change needs a restart."""
        if pending:
            self._btn_restart.setStyleSheet(_BTN_RESTART_PENDING)
            self._btn_restart.setToolTip(
                "⚠ Restart required — a setting change (e.g. Zion Core on/off) "
                "takes effect after restart.")
        else:
            self._btn_restart.setStyleSheet(_BTN)
            self._btn_restart.setToolTip(
                "Restart — reconnects signal and resyncs A/V.\n"
                "Use this to fix sync drift in Video Processor mode.")

    def set_running(self, running: bool) -> None:
        # Stop button visible only in media player mode while something is playing
        self._btn_stop.setVisible(
            running and self._current_mode == "media_player"
        )

    def set_profiles(self, names: list[str], current: str) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItems(names)
        self._profile_combo.setCurrentText(current)
        self._profile_combo.blockSignals(False)

    def set_current_profile(self, name: str) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.setCurrentText(name)
        self._profile_combo.blockSignals(False)

    def _switch_mode(self, mode: str) -> None:
        if mode != self._current_mode:
            self.mode_changed.emit(mode)

    def _refresh_mode_buttons(self) -> None:
        _active = f"""
QPushButton {{
    background: rgba(232,85,31,160); border: 1px solid rgba(232,85,31,200);
    border-radius: 5px; font-size: 15px; color: #fff;
}}"""
        _inactive = f"""
QPushButton {{
    background: rgba(30,30,30,180); border: 1px solid rgba(255,255,255,20);
    border-radius: 5px; font-size: 15px; color: #777;
}}
QPushButton:hover {{ background: rgba(50,50,50,220); color: #ccc; }}"""
        is_vp = self._current_mode == "video_processor"
        self._mode_vp.setStyleSheet(_active if is_vp else _inactive)
        self._mode_mp.setStyleSheet(_active if not is_vp else _inactive)

    def set_app_mode(self, mode: str) -> None:
        self._current_mode = mode
        self._refresh_mode_buttons()
        # Re-evaluate Stop button visibility for new mode
        self._btn_stop.setVisible(False)   # will show again if running via set_running

    def set_edit_mode(self, active: bool) -> None:
        self._edit_mode = active
        if active:
            self._btn_settings.setStyleSheet(
                _BTN_SETTINGS + f"QPushButton {{ border-color: rgba(232,85,31,200); color: #E8551F; }}"
            )
        else:
            self._btn_settings.setStyleSheet(_BTN_SETTINGS)


"""
RightPanel — tab switcher containing Playback Controls and System Settings.

Tab order: ▶ Playback first, ⚙ System second.
In Video Processor mode, Playback tab is hidden.

Fix: panels are sized via resizeEvent only, no layout manager conflict.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider,
    QSizePolicy,
)

from .theme import ACCENT, TEXT_HI, TEXT_MID, TEXT_LO, PANEL_BG


_TAB_INACTIVE = f"""
QPushButton {{
    color: {TEXT_LO};
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    outline: none;
    padding: 6px 16px;
    min-width: 80px;
}}
QPushButton:hover {{ color: {TEXT_MID}; }}
QPushButton:focus {{ outline: none; }}
"""
_TAB_ACTIVE = f"""
QPushButton {{
    color: {TEXT_HI};
    background: transparent;
    border: none;
    border-bottom: 2px solid {ACCENT};
    outline: none;
    padding: 6px 16px;
    font-weight: 600;
    min-width: 80px;
}}
QPushButton:focus {{ outline: none; }}
"""
_TAB_DISABLED = f"""
QPushButton {{
    color: rgba(60,60,60,200);
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    outline: none;
    padding: 6px 16px;
    min-width: 80px;
}}
QPushButton:focus {{ outline: none; }}
"""
_HEADER_BG = f"background: {PANEL_BG}; border-bottom: 1px solid rgba(255,255,255,8);"
_HDR_H = 44


class RightPanel(QWidget):
    opacity_changed    = pyqtSignal(float)
    app_mode_changed   = pyqtSignal(str)
    restart_requested  = pyqtSignal()    # VP restart / re-acquire signal

    def __init__(self, settings_panel, playback_controls, app_config=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget { background: transparent; }")

        self._settings = settings_panel
        self._playback = playback_controls
        self._app_config = app_config
        self._active = -1
        self._playback_visible = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: tabs + opacity slider ─────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(_HDR_H)
        hdr.setStyleSheet(_HEADER_BG)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.setSpacing(0)

        # Playback tab first
        self._tab_play = QPushButton("▶  Playback")
        self._tab_play.clicked.connect(lambda: self._switch(1))
        hl.addWidget(self._tab_play)

        # System tab second
        self._tab_sys = QPushButton("⚙  System")
        self._tab_sys.clicked.connect(lambda: self._switch(0))
        hl.addWidget(self._tab_sys)

        hl.addStretch()

        # ⟳ Restart button — visible only in VP mode
        self._restart_btn = QPushButton("⟳")
        self._restart_btn.setToolTip(
            "Restart capture — stops mpv and re-acquires the HDMI signal.\n"
            "Use this to fix drift, lipsync issues or delayed start."
        )
        self._restart_btn.setStyleSheet(f"""
            QPushButton {{
                color: {TEXT_MID}; background: transparent;
                border: 1px solid rgba(255,255,255,25);
                border-radius: 4px; font-size: 14px;
                padding: 2px 8px; min-width: 28px;
            }}
            QPushButton:hover {{ color: {TEXT_HI}; border-color: rgba(255,255,255,50); }}
        """)
        self._restart_btn.setFixedHeight(28)
        self._restart_btn.clicked.connect(self.restart_requested)
        self._restart_btn.hide()
        hl.addWidget(self._restart_btn)

        opac_lbl = QLabel("◑")
        opac_lbl.setStyleSheet(f"color:{TEXT_LO}; font-size:13px; background:transparent;")
        opac_lbl.setToolTip("Panel opacity — slide left to see video behind the panel")
        hl.addWidget(opac_lbl)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(40, 100)
        self._opacity_slider.setValue(88)
        self._opacity_slider.setFixedWidth(64)
        self._opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px; background: rgba(255,255,255,30); border-radius: 1px;
            }
            QSlider::handle:horizontal {
                width: 12px; height: 12px; border-radius: 6px;
                background: #E8551F; margin: -4px 0;
            }
            QSlider::sub-page:horizontal { background: #E8551F; border-radius: 1px; }
        """)
        self._opacity_slider.valueChanged.connect(
            lambda v: self.opacity_changed.emit(v / 100.0))
        hl.addWidget(self._opacity_slider)

        root.addWidget(hdr)

        # ── Content area — NO layout, manual geometry via resizeEvent ──
        self._content = QWidget(self)
        self._content.setStyleSheet("background: transparent;")

        # Re-parent both panels; they'll be sized in resizeEvent
        settings_panel.setParent(self._content)
        playback_controls.setParent(self._content)
        settings_panel.hide()
        playback_controls.hide()

        root.addWidget(self._content, 1)

        # ── Help panel [3] — 72px, spans full width, above brand strip ────────
        self._help_panel = QWidget()
        self._help_panel.setFixedHeight(72)
        self._help_panel.setStyleSheet(
            "background: rgba(20,12,6,180);")
        help_vl = QVBoxLayout(self._help_panel)
        help_vl.setContentsMargins(12, 8, 12, 8)
        self._help_lbl = QLabel("")
        self._help_lbl.setWordWrap(True)
        self._help_lbl.setStyleSheet(
            "color:#888; font-size:11px; background:transparent;")
        self._help_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_vl.addWidget(self._help_lbl)
        root.addWidget(self._help_panel)

        # ── Brand strip [2] — 28px, spans full width, at very bottom ─────────
        self._brand_strip = QWidget()
        self._brand_strip.setFixedHeight(28)
        self._brand_strip.setStyleSheet(
            f"background: {PANEL_BG}; border-top: 1px solid rgba(255,255,255,8);")
        brand_hl = QHBoxLayout(self._brand_strip)
        brand_hl.setContentsMargins(12, 0, 12, 0)
        brand_lbl = QLabel("Unplugged")
        brand_lbl.setStyleSheet(
            "color: rgba(232,85,31,180); font-size: 11px; font-weight: bold; "
            "background: transparent;")
        from mpvprocessor import __version__
        ver_lbl = QLabel(f"v{__version__}")
        ver_lbl.setStyleSheet("color: #444; font-size: 10px; background: transparent;")
        brand_hl.addWidget(brand_lbl)
        brand_hl.addStretch()
        brand_hl.addWidget(ver_lbl)
        root.addWidget(self._brand_strip)

        # Connect settings panel help signal → help label
        settings_panel.help_changed.connect(self._help_lbl.setText)
        playback_controls.help_changed.connect(self._help_lbl.setText)

        # Don't switch here — geometry is 0×0. Switch in showEvent.

    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._layout_panels()
        if self._active == -1:
            self._switch(1 if self._playback_visible else 0)
        else:
            # Re-apply visibility — Qt propagates hide to grandchildren so
            # child panels need explicit show() after the parent is reshown.
            self._settings.setVisible(self._active == 0)
            self._playback.setVisible(self._active == 1)
            self._layout_panels()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_panels()

    def _layout_panels(self) -> None:
        w = self._content.width()
        h = self._content.height()
        # Use parent's size as fallback if content not yet sized
        if w == 0 or h == 0:
            w = self.width()
            # tab header (44) + help panel (72) + brand strip (28)
            h = max(0, self.height() - 144)
        if w > 0 and h > 0:
            self._settings.setGeometry(0, 0, w, h)
            self._playback.setGeometry(0, 0, w, h)

    def _switch(self, tab: int) -> None:
        # tab 0 = System, tab 1 = Playback
        if tab == 1 and not self._playback_visible:
            tab = 0
        if self._active == tab:
            return
        self._active = tab
        self._tab_sys.setStyleSheet(_TAB_ACTIVE if tab == 0 else _TAB_INACTIVE)
        self._tab_play.setStyleSheet(
            _TAB_ACTIVE if tab == 1 else
            (_TAB_DISABLED if not self._playback_visible else _TAB_INACTIVE)
        )
        self._layout_panels()
        self._settings.setVisible(tab == 0)
        self._playback.setVisible(tab == 1)

    def set_app_mode(self, mode: str) -> None:
        """Hide Playback tab in Video Processor mode."""
        # Show restart button only in VP mode
        self._restart_btn.setVisible(mode == "video_processor")

        show = mode == "media_player"
        self._playback_visible = show
        self._tab_play.setVisible(show)
        # VP mode: FORCE the System/Settings tab visible. Both panels start
        # hidden and _switch() early-returns when the tab is already active, so
        # the rail ended up showing NOTHING (an empty, non-interactive strip —
        # the "settings panel doesn't respond" symptom).
        if not show:
            self._active = -1          # defeat _switch()'s early-return
            self._switch(0)
        elif show and self._active == -1:
            self._switch(1)

    def show_system_tab(self) -> None:
        self._active = -1              # defeat the early-return
        self._switch(0)

    def show_playback_tab(self) -> None:
        self._switch(1)


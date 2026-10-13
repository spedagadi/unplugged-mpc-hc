"""
AcquireOverlay — modal QDialog shown while acquiring the HDMI capture signal
or while a media file is loading.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QComboBox,
)

from ..config.model import AppConfig


_DLG_STYLE = """
QDialog { background: transparent; }
QLabel { background: transparent; }
"""

_CARD_STYLE = """
QWidget#card {
    background: #0e0e0e;
    border-radius: 16px;
    border: 1.5px solid rgba(100,100,100,180);
}
"""

_SPINNER = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

_BTN_RETRY = """
QPushButton {
    color: #ffffff;
    background: rgba(232,85,31,180);
    border: 1px solid rgba(232,85,31,220);
    border-radius: 6px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton:hover { background: rgba(232,85,31,240); }
"""

_BTN_SECONDARY = """
QPushButton {
    color: #aaaaaa;
    background: rgba(40,40,40,180);
    border: 1px solid rgba(255,255,255,25);
    border-radius: 6px;
    padding: 9px 16px;
    font-size: 12px;
}
QPushButton:hover { color: #ffffff; background: rgba(60,60,60,220); }
"""

_COMBO_STYLE = """
QComboBox {
    color: #cccccc;
    background: rgba(40,40,40,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 12px;
    min-width: 140px;
}
QComboBox:hover { border-color: rgba(232,85,31,160); }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: #1a1a1a;
    border: 1px solid rgba(232,85,31,120);
    color: #cccccc;
    selection-background-color: rgba(232,85,31,80);
}
"""


class AcquireOverlay(QDialog):
    retry_requested        = pyqtSignal()
    switch_to_media_player = pyqtSignal()
    input_selected         = pyqtSignal(str)   # user chose a different input from failure screen
    exit_requested         = pyqtSignal()      # user chose to quit from the failure screen

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self._app_config = app_config
        # NOT modal. With setModal(True) the parent window stays DISABLED after
        # dismiss() (hiding a modal dialog does not end its modality in Qt) —
        # that left the whole shell accepting no mouse input for the rest of the
        # session (root cause of the multi-day "clicks don't work" hunt).
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_DLG_STYLE)
        self.setFixedWidth(560)

        self._spinner_frame = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(80)
        self._spinner_timer.timeout.connect(self._tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._card = QWidget(objectName="card")
        self._card.setStyleSheet(_CARD_STYLE)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._mode_lbl = QLabel("VIDEO PROCESSOR")
        self._mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_lbl.setStyleSheet(
            "color: #E8551F; font-size: 11px; font-weight: 700; "
            "letter-spacing: 2px; background: transparent;")
        layout.addWidget(self._mode_lbl)

        self._icon = QLabel("⠋")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("color: #E8551F; font-size: 40px;")
        layout.addWidget(self._icon)

        self._title = QLabel("Acquiring signal…")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            "color: #ffffff; font-size: 17px; font-weight: 700;")
        layout.addWidget(self._title)

        dev_widget = QWidget()
        dev_widget.setStyleSheet("background: transparent;")
        dev_layout = QHBoxLayout(dev_widget)
        dev_layout.setContentsMargins(0, 0, 0, 0)
        dev_layout.setSpacing(6)
        dev_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_label = QLabel("Input:")
        dev_label.setStyleSheet("color: #666666; font-size: 12px; background: transparent;")
        dev_layout.addWidget(dev_label)
        self._sub = QLabel("")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._sub.setWordWrap(False)
        self._sub.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: 500; background: transparent;")
        dev_layout.addWidget(self._sub)
        layout.addWidget(dev_widget)

        self._attempt = QLabel("")
        self._attempt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._attempt.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(self._attempt)

        # --- Action rows — hidden until show_failed() ---
        self._action_widget = QWidget()
        self._action_widget.setStyleSheet("background: transparent;")
        action_layout = QVBoxLayout(self._action_widget)
        action_layout.setContentsMargins(0, 6, 0, 0)
        action_layout.setSpacing(8)

        # Row 1: Try Again | Switch input — equal width, centred
        row1 = QHBoxLayout()
        row1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row1.setSpacing(8)

        self._retry_btn = QPushButton("↺  Try Again")
        self._retry_btn.setStyleSheet(_BTN_RETRY)
        self._retry_btn.setFixedSize(160, 38)
        self._retry_btn.clicked.connect(self._on_retry)
        row1.addWidget(self._retry_btn)

        self._input_combo = QComboBox()
        self._input_combo.setStyleSheet(_COMBO_STYLE)
        self._input_combo.setPlaceholderText("Switch input…")
        self._input_combo.setFixedSize(160, 38)
        self._input_combo.activated.connect(self._on_input_combo_activated)
        row1.addWidget(self._input_combo)
        action_layout.addLayout(row1)

        # Row 2: Media Player — same total width, centred
        row2 = QHBoxLayout()
        row2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._media_btn = QPushButton("🎬  Open Media Player")
        self._media_btn.setStyleSheet(_BTN_SECONDARY)
        self._media_btn.setFixedSize(328, 38)   # 160 + 8 + 160
        self._media_btn.clicked.connect(self._on_media_player_clicked)
        row2.addWidget(self._media_btn)
        action_layout.addLayout(row2)

        # Row 3: Exit. This dialog is modal over the whole app, so while it is up it
        # is the ONLY surface the user can act on -- without an exit here the only
        # way out of a no-signal failure was the taskbar, which is exactly the kind
        # of escape hatch nobody finds. Emits exit_requested; MainWindow.close()
        # does the ordered shutdown, so this path and the title-bar close are one
        # path, not two.
        row3 = QHBoxLayout()
        row3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._exit_btn = QPushButton("✕  Exit Unplugged")
        self._exit_btn.setStyleSheet(_BTN_SECONDARY)
        self._exit_btn.setFixedSize(328, 38)
        self._exit_btn.clicked.connect(self._on_exit_clicked)
        row3.addWidget(self._exit_btn)
        action_layout.addLayout(row3)

        self._action_widget.hide()
        layout.addWidget(self._action_widget)

    # ------------------------------------------------------------------

    def reset_for_retry(self) -> None:
        self._spinner_timer.stop()
        self._action_widget.hide()
        self._icon.setText("⠋")
        self._icon.setStyleSheet("color: #E8551F; font-size: 40px;")
        self._title.setText("Acquiring signal…")
        self._title.setStyleSheet("color: #ffffff; font-size: 17px; font-weight: 700;")
        self.adjustSize()
        self._center_on_parent()
        self._spinner_timer.start()

    def start_acquiring(self, device: str, max_attempts: int = 10) -> None:
        self._sub.setText(self._app_config.label_for(device))
        self._title.setText("Acquiring signal…")
        self._title.setStyleSheet("color: #e8e8e8; font-size: 15px; font-weight: 600;")
        self._icon.setText("⠋")
        self._icon.setStyleSheet("color: #E8551F; font-size: 36px;")
        self._attempt.setText("")
        self._action_widget.hide()
        self.adjustSize()
        self._center_on_parent()
        self.show()
        self._spinner_timer.start()

    def update_attempt(self, n: int, total: int) -> None:
        self._action_widget.hide()
        self._attempt.setText(f"Attempt {n} of {total}")

    def show_failed(self) -> None:
        self._spinner_timer.stop()
        self._icon.setText("✕")
        self._icon.setStyleSheet("color: #f44336; font-size: 36px;")
        self._title.setText("No signal detected")
        self._title.setStyleSheet("color: #f44336; font-size: 15px; font-weight: 600;")
        self._attempt.setText(
            "Check the capture card is connected and the source device is active.")
        self._attempt.setWordWrap(True)
        self._attempt.setStyleSheet("color: #888888; font-size: 12px;")
        self._populate_input_combo()
        self._action_widget.show()
        self.adjustSize()
        self._center_on_parent()

    def dismiss(self) -> None:
        self._spinner_timer.stop()
        self.setModal(False)          # end modality explicitly (hide alone does not)
        self.hide()
        # Belt: re-enable the parent so a hidden dialog can never leave the
        # shell disabled and ignoring every click.
        p = self.parentWidget()
        if p is not None:
            p.setEnabled(True)

    # ------------------------------------------------------------------

    def _populate_input_combo(self) -> None:
        self._input_combo.blockSignals(True)
        self._input_combo.clear()

        current_url = self._app_config.active_input_url or ""
        labels = self._app_config.get_input_labels()  # {url: user_label}
        others = [(url, lbl) for url, lbl in labels.items() if url != current_url]

        for url, lbl in others:
            self._input_combo.addItem(lbl, url)

        self._input_combo.setVisible(bool(others))
        self._input_combo.blockSignals(False)

    def _tick(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER)
        self._icon.setText(_SPINNER[self._spinner_frame])

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4):
            parent = self.parent()
            if parent:
                parent.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        parent = self.parent()
        if parent:
            parent.close()
        event.ignore()

    def _on_media_player_clicked(self) -> None:
        self.hide()
        self.switch_to_media_player.emit()

    def _on_exit_clicked(self) -> None:
        # Do not hide first: MainWindow.close() owns teardown and shutdown, and
        # closing the parent closes this dialog with it. Hiding here would leave a
        # moment where the app looks alive again on its way out.
        self.exit_requested.emit()

    def _on_retry(self) -> None:
        self._action_widget.hide()
        self._icon.setText("⠋")
        self._icon.setStyleSheet("color: #E8551F; font-size: 36px;")
        self._title.setText("Acquiring signal…")
        self._title.setStyleSheet("color: #e8e8e8; font-size: 15px; font-weight: 600;")
        self._attempt.setText("")
        self.adjustSize()
        self._center_on_parent()
        self._spinner_timer.start()
        self.retry_requested.emit()

    def _on_input_combo_activated(self, index: int) -> None:
        url = self._input_combo.itemData(index)
        if not url:
            return
        self._app_config.active_input_url = url
        self._action_widget.hide()
        self._icon.setText("⠋")
        self._icon.setStyleSheet("color: #E8551F; font-size: 36px;")
        self._title.setText("Acquiring signal…")
        self._title.setStyleSheet("color: #e8e8e8; font-size: 15px; font-weight: 600;")
        self._attempt.setText("")
        self.adjustSize()
        self._center_on_parent()
        self._spinner_timer.start()
        self.input_selected.emit(url)

    def _center_on_parent(self) -> None:
        parent = self.parent()
        if parent:
            pg = parent.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 2
            self.move(x, y)

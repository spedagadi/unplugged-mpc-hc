"""
ConfirmDialog — styled confirmation dialog matching the acquire overlay aesthetic.
Dark card, frameless, always on top. Replaces QMessageBox for mode switching.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)


_CARD_STYLE = """
QWidget#card {
    background: #0e0e0e;
    border-radius: 16px;
    border: 1.5px solid rgba(100,100,100,180);
}
"""

_BTN_CONFIRM = """
QPushButton {
    color: #ffffff;
    background: rgba(232,85,31,180);
    border: 1px solid rgba(232,85,31,220);
    border-radius: 6px;
    padding: 9px 36px;
    font-weight: 600;
    min-width: 100px;
}
QPushButton:hover { background: rgba(232,85,31,240); }
"""

_BTN_CANCEL = """
QPushButton {
    color: #aaaaaa;
    background: rgba(40,40,40,180);
    border: 1px solid rgba(255,255,255,25);
    border-radius: 6px;
    padding: 9px 36px;
    min-width: 100px;
}
QPushButton:hover { color: #ffffff; background: rgba(60,60,60,220); }
"""


class ConfirmDialog(QDialog):
    """
    Styled confirmation dialog.
    Returns True if user confirmed, False if cancelled.
    """

    def __init__(self, title: str, message: str, confirm_label: str = "Yes",
                 parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setFixedSize(480, 210)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QWidget(objectName="card")
        card.setStyleSheet(_CARD_STYLE)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon + title row
        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(title_lbl)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "color: #999999; font-size: 13px; background: transparent;")
        layout.addWidget(msg_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton(confirm_label)
        btn_ok.setStyleSheet(_BTN_CONFIRM)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

        self._center_on_parent(parent)

    def _center_on_parent(self, parent) -> None:
        if parent:
            pg = parent.geometry()
            self.move(
                pg.x() + (pg.width()  - self.width())  // 2,
                pg.y() + (pg.height() - self.height()) // 2,
            )
        else:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                self.move(
                    sg.x() + (sg.width()  - self.width())  // 2,
                    sg.y() + (sg.height() - self.height()) // 2,
                )

    @staticmethod
    def ask(title: str, message: str, confirm_label: str = "Yes",
            parent=None) -> bool:
        dlg = ConfirmDialog(title, message, confirm_label, parent)
        return dlg.exec() == QDialog.DialogCode.Accepted

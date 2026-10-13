"""
CollapsibleGroup — a QGroupBox replacement with a clickable header that
expands/collapses the body. Starts expanded by default.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout
from PyQt6.QtGui import QKeyEvent

# Icon style — plain, no background pill
_ICON_LIVE    = "color: #E8551F; font-size: 13px; background: transparent;"
_ICON_RESTART = "color: #ff9800; font-size: 12px; background: transparent;"


_HEADER_STYLE = """
QWidget#cgHeader {
    background: rgba(38, 38, 38, 200);
    border: 1px solid rgba(255,255,255,18);
    border-radius: 5px;
}
QWidget#cgHeader:hover {
    background: rgba(52, 52, 52, 220);
    border-color: rgba(255,255,255,32);
}
QWidget#cgHeader:focus {
    border: 2px solid #E8551F;
    background: rgba(45, 55, 45, 220);
}
"""

_TITLE_STYLE = "color: #b0b0b0; font-size: 13px; font-weight: 500; padding: 0px; background: transparent;"
_ARROW_STYLE = "color: #555555; font-size: 12px; padding: 0px; background: transparent;"
_BODY_STYLE  = (
    "border: 1px solid rgba(255,255,255,20);"
    "border-top: none;"
    "border-radius: 0 0 4px 4px;"
    "padding: 4px 0px 2px 0px;"
)


class CollapsibleGroup(QWidget):
    """
    Drop-in replacement for QGroupBox with a toggle header and optional
    LIVE / RESTART badge showing whether changes apply without restarting mpv.
    """

    def __init__(self, title: str, expanded: bool = True,
                 badge: str = "", parent=None) -> None:
        """
        badge: "" = no badge, "live" = green LIVE, "restart" = amber RESTART
        """
        super().__init__(parent)
        self._expanded = expanded

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        self._header = QWidget(objectName="cgHeader")
        self._header.setStyleSheet(_HEADER_STYLE)
        self._header.setFixedHeight(30)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        # Make header keyboard-focusable for remote navigation
        self._header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(6)

        self._arrow = QLabel("▼" if expanded else "▶")
        self._arrow.setStyleSheet(_ARROW_STYLE)
        self._arrow.setFixedWidth(12)
        hl.addWidget(self._arrow)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(_TITLE_STYLE)
        hl.addWidget(self._title_lbl, 1)

        if badge == "live":
            icon = QLabel("⚡")
            icon.setStyleSheet(_ICON_LIVE)
            icon.setToolTip("Takes effect immediately — no restart needed")
            hl.addWidget(icon)
        elif badge == "restart":
            icon = QLabel("↺")
            icon.setStyleSheet(_ICON_RESTART)
            icon.setToolTip("Requires mpv restart to take effect")
            hl.addWidget(icon)

        root.addWidget(self._header)

        # ── Body ──────────────────────────────────────────────────────
        self._body = QWidget(objectName="cgBody")
        # Target only the body container itself, not child widgets
        # (child widgets get their :focus styles from the parent panel stylesheet)
        self._body.setStyleSheet(f"QWidget#cgBody {{ {_BODY_STYLE} }}")

        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(8, 4, 8, 6)
        self.body_layout.setSpacing(4)

        root.addWidget(self._body)

        if not expanded:
            self._body.hide()

        # Click or Enter/Space to toggle
        self._header.mousePressEvent = lambda _e: self._toggle()
        self._header.keyPressEvent = self._header_key_press

    # ------------------------------------------------------------------

    def form(self) -> QFormLayout:
        """Add and return a QFormLayout inside the body."""
        f = QFormLayout()
        f.setSpacing(6)
        f.setContentsMargins(0, 0, 0, 0)
        self.body_layout.addLayout(f)
        return f

    def add_widget(self, w: QWidget) -> None:
        self.body_layout.addWidget(w)

    def set_expanded(self, v: bool) -> None:
        self._expanded = v
        self._arrow.setText("▼" if v else "▶")
        self._body.setVisible(v)

    def _header_key_press(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._toggle()
        else:
            QWidget.keyPressEvent(self._header, event)

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)


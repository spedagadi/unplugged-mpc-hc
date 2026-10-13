"""
SplashScreen — frameless overlay shown for 5 seconds at app launch.

Renders splash-A-release.html via WebAnimationView (QWebEngineView).
Shown as an overlay centred on the main window; auto-dismisses after 5s.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from .web_animation import WebAnimationView


_SPLASH_DURATION_MS = 5000
_CARD_W = 520
_CARD_H = 400


def _find_animation(name: str) -> Path:
    from ..assets import asset

    candidates = [
        asset("brand", "animations", name),
        Path(sys.executable).parent / "_internal" / "assets" / "brand" / "animations" / name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


class SplashScreen(QDialog):
    """5-second launch splash overlay. Call show_centered(); finished emits when done."""

    finished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setStyleSheet("QDialog { background: transparent; }")

        # Plain QTimer drives dismiss — independent of WebEngine loading state
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SPLASH_DURATION_MS)
        self._timer.timeout.connect(self._dismiss)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        html_path = _find_animation("splash-A-release.html")
        # play_once=True, no on_finished/duration — timer lives here, not in WebAnimationView
        self._anim = WebAnimationView(
            html_path=html_path,
            play_once=True,
            parent=self,
        )
        self._anim.setStyleSheet("background: transparent;")
        layout.addWidget(self._anim)

    def show_centered(self) -> None:
        """Centre on parent and show; auto-dismisses after 5s."""
        self._center_on_parent()
        self.show()
        self.raise_()
        self._timer.start()

    def _dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self.finished.emit()

    def _center_on_parent(self) -> None:
        parent = self.parent()
        if parent:
            pg = parent.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 2
            self.move(x, y)

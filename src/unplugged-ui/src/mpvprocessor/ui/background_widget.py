"""
Full-window background layer that shows the welcome/idle wallpaper.
Scales the image to CONTAIN it (CSS background-size: contain): the whole frame is
always visible, and an aspect mismatch letterboxes against the near-black canvas
rather than cropping the art. Cover semantics were documented here before, which is
not what paintEvent does -- and for the grade-room wallpaper, cropping to fill would
cut the scopes at the edges, which are the part that reads as this product.
Fades in/out via a QPropertyAnimation on the windowOpacity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QWidget


class BackgroundWidget(QWidget):
    FADE_DURATION_MS = 600

    def __init__(self, default_wallpaper: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._pixmap: Optional[QPixmap] = None
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_anim.setDuration(self.FADE_DURATION_MS)

        self.load_wallpaper(default_wallpaper)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_wallpaper(self, path: Path) -> bool:
        """Load an image file as the wallpaper. Returns True on success."""
        px = QPixmap(str(path))
        if px.isNull():
            return False
        self._pixmap = px
        self.update()
        return True

    def fade_in(self) -> None:
        self._animate_to(1.0)
        self.show()

    def fade_out(self) -> None:
        self._animate_to(0.0)

    def show_instant(self) -> None:
        self.setWindowOpacity(1.0)
        self.show()

    def hide_instant(self) -> None:
        self.hide()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        if not self._pixmap:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(10, 10, 10))
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(10, 10, 10))

        # Contain: scale to fit fully within the widget, letterbox if needed
        widget_ratio = self.width() / self.height()
        img_ratio = self._pixmap.width() / self._pixmap.height()

        if img_ratio > widget_ratio:
            # Image is wider — constrain by width
            scaled_w = self.width()
            scaled_h = int(scaled_w / img_ratio)
        else:
            # Image is taller — constrain by height
            scaled_h = self.height()
            scaled_w = int(scaled_h * img_ratio)

        x = (self.width() - scaled_w) // 2
        y = (self.height() - scaled_h) // 2
        painter.drawPixmap(x, y, scaled_w, scaled_h, self._pixmap)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _animate_to(self, target: float) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

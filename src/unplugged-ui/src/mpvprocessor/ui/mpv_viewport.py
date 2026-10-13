"""
MpvViewport — the QWidget whose HWND we hand to mpv via --wid.

mpv renders directly into this widget's native window handle.
Keep this as simple as possible — no custom paint engine overrides
that can interfere with the compositor on Windows.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget


class MpvViewport(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Must have a stable native HWND
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        # Allow clicks to transfer keyboard focus to mpv's window
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Black when mpv is not yet rendering
        self.setStyleSheet("background: #000000;")

    def hwnd(self) -> int:
        """Return the native Windows HWND as an integer for --wid."""
        return int(self.winId())

"""
ui/video_window.py — the dedicated fullscreen window MPCVR renders into.

Two-window model (2026-09-15): the video lives in its OWN top-level window, and
the Qt UI is a separate translucent TOPMOST window above it. Windows then routes
input by its normal per-window rules — no owned-popup vs child-window z-order
fights, no Qt-vs-D3D swapchain sharing one surface (the class of bug that cost
days on the win32 shell and again on the PyQt overlay).

The app's existing mode logic maps straight onto it:
  IDLE            -> viewport.hide()   + opaque wallpaper in the UI window
  WATCH/EDIT      -> viewport.show()   + translucent UI window (video shows through)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget


class VideoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Window |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setStyleSheet("background: #000000;")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("unplugged-video")

    def hwnd(self) -> int:
        """Native HWND for the engine's s3_attach (MPCVR render target)."""
        return int(self.winId())

    def show_fullscreen(self) -> None:
        scr = QApplication.primaryScreen()
        if scr is not None:
            self.setGeometry(scr.geometry())
        self.show()
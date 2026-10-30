"""
ui/video_window.py — the dedicated fullscreen window MPCVR renders into.

Two-window model (2026-09-15, wired 2026-10-25): the video lives in its OWN
top-level window and the Qt UI is a separate window; the renderer's DirectX
child is NEVER inside the Qt window. A native child inside a Qt window
corrupts that window's focus/activation from within (Qt focusWidget goes
None, key dispatch dies ~1-in-12, every modal/top-level chrome inherits a
poisoned activation state) — that single embedding decision is what made
"Up works once then dead" survive five chrome strategies.

Ex-styles mirror videoprocessor's FullscreenVideoWindow
(FullscreenVideoWindow.cpp:181): TOPMOST so it covers the screen,
TOOLWINDOW so no taskbar button, NOACTIVATE so clicking the video never
steals foreground/keyboard from the Qt window.
"""

from __future__ import annotations

import ctypes

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


class VideoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Window |
                         Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.WindowStaysOnTopHint)
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
        # Win32 ex-styles Qt flags cannot express (NOACTIVATE above all):
        # the video must never become the foreground/keyboard window.
        try:
            h = self.hwnd()
            u = ctypes.windll.user32
            st = u.GetWindowLongPtrW(h, GWL_EXSTYLE)
            u.SetWindowLongPtrW(h, GWL_EXSTYLE,
                                st | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
                                | WS_EX_NOACTIVATE)
        except Exception:  # noqa: BLE001 - styles are best-effort
            pass

"""
core/altf4_hook.py — Alt+F4 as a reliable kiosk command.

RegisterHotKey refuses (or never delivers) Alt+F4 in practice; a low-level
keyboard hook always sees it. We watch for VK_F4 with Alt held, emit a Qt
signal on the app thread, and swallow the key so Windows' default handling
(which would target whatever window happens to be focused) never runs.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import threading

from PyQt6.QtCore import QObject, pyqtSignal

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_F4 = 0x73
VK_MENU = 0x12


class _KbdHookThread(threading.Thread):
    def __init__(self, sink) -> None:
        super().__init__(daemon=True)
        self._sink = sink
        self._user32 = ctypes.windll.user32
        self._id = None
        self._stop = False

    def _proc(self, nCode, wParam, lParam):
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            data = ctypes.cast(lParam, ctypes.POINTER(wintypes.KBDLLHOOKSTRUCT)).contents
            if data.vkCode == VK_F4 and (self._user32.GetAsyncKeyState(VK_MENU) & 0x8000):
                self._sink()
                return 1                      # swallowed — we handle it
        return self._user32.CallNextHookEx(None, nCode, wParam, lParam)

    def run(self) -> None:
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                      ctypes.WPARAM, ctypes.LPARAM)
        self._cb = HOOKPROC(self._proc)
        self._id = self._user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._cb, None, 0)
        if not self._id:
            return
        msg = wintypes.MSG()
        while not self._stop:
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            threading.Event().wait(0.02)
        self._user32.UnhookWindowsHookEx(self._id)

    def stop(self) -> None:
        self._stop = True


class AltF4Hook(QObject):
    triggered = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hook: _KbdHookThread | None = None

    def start(self) -> None:
        if self._hook is None:
            self._hook = _KbdHookThread(self.triggered.emit)
            self._hook.start()

    def stop(self) -> None:
        if self._hook:
            self._hook.stop()
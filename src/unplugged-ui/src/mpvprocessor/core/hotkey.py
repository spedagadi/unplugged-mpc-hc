"""
Global hotkey registration via Win32 RegisterHotKey.

Registers Up arrow (configurable) so unplugged can regain focus
even when mpv owns the foreground window.

Runs a background QThread that polls for WM_HOTKEY messages.
Emits hotkey_pressed on the Qt signal when the hotkey fires.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from typing import Optional

from PyQt6.QtCore import QThread, QObject, pyqtSignal


# Win32 constants
MOD_CONTROL = 0x0002
MOD_ALT     = 0x0001
MOD_SHIFT   = 0x0004
VK_SPACE    = 0x20
VK_UP       = 0x26
VK_F12      = 0x7B
WM_HOTKEY   = 0x0312
PM_REMOVE   = 0x0001

_HOTKEY_ID  = 0xBEEF  # arbitrary unique ID


class _HotkeyThread(QThread):
    fired = pyqtSignal()
    _NEXT_ID = [0xBEEF]          # RegisterHotKey ids must be UNIQUE per process

    def __init__(self, vk: int, modifiers: int, parent=None) -> None:
        super().__init__(parent)
        self._vk = vk
        self._mods = modifiers
        self._stop = False
        # A fixed id made the SECOND registration (Alt+F4) fail silently, so
        # only the first hotkey ever worked.
        self._id = _HotkeyThread._NEXT_ID[0]
        _HotkeyThread._NEXT_ID[0] += 1

    def run(self) -> None:
        user32 = ctypes.windll.user32
        ok = user32.RegisterHotKey(None, self._id, self._mods, self._vk)
        if not ok:
            return

        msg = wintypes.MSG()
        while not self._stop:
            # PeekMessage with a short timeout keeps the thread responsive
            if user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                if msg.message == WM_HOTKEY and msg.wParam == self._id:
                    self.fired.emit()
            self.msleep(20)

        user32.UnregisterHotKey(None, self._id)

    def stop(self) -> None:
        self._stop = True


class GlobalHotkey(QObject):
    """
    Wraps the hotkey thread. Connect hotkey_pressed to your slot.
    Default: Ctrl+Space.
    """
    hotkey_pressed = pyqtSignal()

    def __init__(self, vk: int = VK_UP, modifiers: int = 0,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = _HotkeyThread(vk, modifiers, self)
        self._thread.fired.connect(self.hotkey_pressed)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()
        self._thread.wait(500)

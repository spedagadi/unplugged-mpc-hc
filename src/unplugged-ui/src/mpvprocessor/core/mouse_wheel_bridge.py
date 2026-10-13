"""
core/mouse_wheel_bridge.py — route the mouse wheel to the widget under the
cursor even when the shell lacks Windows keyboard focus.

Windows delivers WM_MOUSEWHEEL to the FOCUSED window, not the hovered one.
On an HTPC where the shell is driven by the global Up-arrow hotkey it may
never be clicked into focus (observed: wheel dead over the status panel while
the pointer is visibly on it). A WH_MOUSE_LL hook observes wheel delta +
cursor position; a Qt timer drains the queue and posts a synthetic
QWheelEvent to the widget under the cursor. Focus-independent, kiosk-correct,
and it never steals focus from other apps.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import queue
import threading

from PyQt6.QtCore import QObject, QTimer, QPoint, QPointF, Qt, QEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QWheelEvent

WH_MOUSE_LL = 14
WM_MOUSEMOVE    = 0x0200
WM_LBUTTONDOWN  = 0x0201
WM_LBUTTONUP    = 0x0202
WM_RBUTTONDOWN  = 0x0204
WM_RBUTTONUP    = 0x0205
WM_MBUTTONDOWN  = 0x0207
WM_MBUTTONUP    = 0x0208
WM_MOUSEWHEEL   = 0x020A

# Buttons we forward as synthetic QMouseEvents (press/release pairs).
_BUTTON_BY_MSG = {
    WM_LBUTTONDOWN: ("press", 1), WM_LBUTTONUP: ("release", 1),
    WM_RBUTTONDOWN: ("press", 2), WM_RBUTTONUP: ("release", 2),
    WM_MBUTTONDOWN: ("press", 4), WM_MBUTTONUP: ("release", 4),
}


class _POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", _POINTL),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MouseHookThread(threading.Thread):
    """Low-level mouse hook on its own message-pumping thread. When the pointer
    is inside our window we set, mouse input is SWALLOWED (return 1) and queued
    for the Qt thread to replay as synthetic events to the hovered widget —
    clicks/wheel/moves become independent of Windows focus AND of MPCVR's owned
    window stacking over the panels. Outside our window, pass through."""

    def __init__(self, sink) -> None:
        super().__init__(daemon=True)
        self._sink = sink
        self._user32 = ctypes.windll.user32
        self._id = None
        self._stop = False
        self._win_hwnd = 0
        self._rect = ctypes.wintypes.RECT()

    def set_window(self, hwnd: int) -> None:
        self._win_hwnd = hwnd
        if hwnd:
            self._user32.GetWindowRect(hwnd, ctypes.byref(self._rect))

    def _inside_our_window(self, x: int, y: int) -> bool:
        r = self._rect
        return (self._win_hwnd and
                r.left <= x < r.right and r.top <= y < r.bottom)

    def _proc(self, nCode: int, wParam, lParam) -> int:
        if nCode == 0:
            data = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            x, y = int(data.pt.x), int(data.pt.y)
            if self._inside_our_window(x, y):
                if wParam == WM_MOUSEWHEEL:
                    delta = int((data.mouseData >> 16) & 0xFFFF)
                    if delta & 0x8000:
                        delta -= 0x10000
                    self._sink(("wheel", delta, x, y))
                    return 1                       # swallowed — synthetic posted
                kind = _BUTTON_BY_MSG.get(wParam)
                if kind is not None:
                    self._sink((kind[0], kind[1], x, y))
                    return 1
                if wParam == WM_MOUSEMOVE:
                    buttons = 0
                    if self._user32.GetAsyncKeyState(0x01) & 0x8000: buttons |= 1
                    if self._user32.GetAsyncKeyState(0x02) & 0x8000: buttons |= 2
                    self._sink(("move", buttons, x, y))
                    return 1
        return self._user32.CallNextHookEx(None, nCode, wParam, lParam)

    def run(self) -> None:
        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, ctypes.WPARAM, ctypes.LPARAM)
        self._cb = HOOKPROC(self._proc)
        self._id = self._user32.SetWindowsHookExW(WH_MOUSE_LL, self._cb, None, 0)
        if not self._id:
            return
        msg = wintypes.MSG()
        while not self._stop:
            # Pump the thread's queue so the installed hook fires.
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            threading.Event().wait(0.015)
        self._user32.UnhookWindowsHookEx(self._id)

    def stop(self) -> None:
        self._stop = True


class MouseWheelBridge(QObject):
    """Run the hook; on the Qt thread, replay wheel deltas to the hovered widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._q = queue.SimpleQueue()
        self._hook: _MouseHookThread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain)

    def start(self, win_hwnd: int = 0) -> None:
        if self._hook is None:
            self._hook = _MouseHookThread(self._q.put)
            if win_hwnd:
                self._hook.set_window(win_hwnd)
            self._hook.start()
            self._timer.start()

    def set_window(self, win_hwnd: int) -> None:
        if self._hook:
            self._hook.set_window(win_hwnd)

    def stop(self) -> None:
        self._timer.stop()
        if self._hook:
            self._hook.stop()

    def _post(self, ev, x: int, y: int) -> None:
        app = QApplication.instance()
        if app is None:
            return
        try:
            w = app.widgetAt(QPoint(x, y))
            if w is not None:
                QApplication.postEvent(w, ev)
        except Exception:
            pass

    def _drain(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        while True:
            try:
                kind, a, b, c = self._q.get_nowait()
            except Exception:
                break
            pos = QPointF(float(b), float(c))
            try:
                if kind == "wheel":
                    from PyQt6.QtGui import QWheelEvent
                    self._post(QWheelEvent(
                        pos, pos, QPoint(0, 0), QPoint(0, a),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False), b, c)
                elif kind in ("press", "release"):
                    from PyQt6.QtGui import QMouseEvent
                    button = {1: Qt.MouseButton.LeftButton,
                              2: Qt.MouseButton.RightButton,
                              4: Qt.MouseButton.MiddleButton}.get(a,
                                Qt.MouseButton.LeftButton)
                    evtype = (QEvent.Type.MouseButtonPress
                              if kind == "press" else QEvent.Type.MouseButtonRelease)
                    buttons = button if kind == "press" else Qt.MouseButton.NoButton
                    self._post(QMouseEvent(evtype, pos, pos, button, buttons,
                                           Qt.KeyboardModifier.NoModifier), b, c)
                elif kind == "move":
                    from PyQt6.QtGui import QMouseEvent
                    held = Qt.MouseButton.NoButton
                    if a & 1: held |= Qt.MouseButton.LeftButton
                    if a & 2: held |= Qt.MouseButton.RightButton
                    self._post(QMouseEvent(QEvent.Type.MouseMove, pos, pos,
                                           Qt.MouseButton.NoButton, held,
                                           Qt.KeyboardModifier.NoModifier), b, c)
            except Exception:
                pass
"""
mpv IPC bridge over a Windows named pipe.

Design:
- ONE handle opened with GENERIC_READ|GENERIC_WRITE
- Reader thread uses PeekNamedPipe + ReadFile (non-blocking poll)
- Reader thread NEVER emits disconnected — the bridge polls thread state
- A QTimer polls thread health every 500ms and triggers reconnect if dead
- Cleanup is always done from the Qt main thread, never from the reader thread
  This avoids the QThread-destroyed-while-running abort()
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import logging
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer


def _make_ipc_logger():
    log_path = Path.home() / ".videoforge" / "videoforge_ipc.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("videoforge.ipc")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s",
                                          datefmt="%H:%M:%S"))
        logger.addHandler(fh)
    return logger

_ipc_log = _make_ipc_logger()

GENERIC_READ   = 0x80000000
GENERIC_WRITE  = 0x40000000
OPEN_EXISTING  = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value
PIPE_NOWAIT    = 0x00000001

OBSERVED_PROPERTIES = [
    "video-params",
    "video-pts-time",
    "idle-active",
    "pause",
]

_NOISY = {"time-pos", "video-pts-time", "audio-pts"}


class _ReaderThread(QThread):
    """
    Reads newline-delimited JSON from a shared pipe handle.
    NEVER emits disconnected — the bridge polls isRunning() instead.
    This avoids the QThread-destroyed-while-running abort().
    """
    message_received = pyqtSignal(dict)

    def __init__(self, handle: int, parent=None) -> None:
        super().__init__(parent)
        self._handle = handle
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        kernel32 = ctypes.windll.kernel32
        buf = b""
        raw_buf = ctypes.create_string_buffer(4096)
        bytes_read = wintypes.DWORD(0)

        while not self._stop:
            if not self._handle:
                break
            avail = wintypes.DWORD(0)
            peek_ok = kernel32.PeekNamedPipe(
                self._handle, None, 0, None,
                ctypes.byref(avail), None
            )
            if not peek_ok:
                break
            if avail.value == 0:
                self.msleep(20)
                continue
            ok = kernel32.ReadFile(
                self._handle, raw_buf, 4096,
                ctypes.byref(bytes_read), None
            )
            if not ok or bytes_read.value == 0:
                break
            buf += raw_buf.raw[: bytes_read.value]
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    self.message_received.emit(json.loads(line.decode("utf-8")))
                except json.JSONDecodeError:
                    pass
        # run() returns normally — Qt can safely clean up the thread object


class MpvIpcBridge(QObject):
    property_changed = pyqtSignal(str, object)
    message_received = pyqtSignal(dict)
    connected        = pyqtSignal()
    disconnected     = pyqtSignal()

    def __init__(self, pipe_path: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pipe_path = pipe_path
        self._handle: int = 0
        self._reader: Optional[_ReaderThread] = None
        self._request_id = 0
        self._pending: dict[int, Callable] = {}

        # Retry connecting until mpv creates the pipe
        self._connect_timer = QTimer(self)
        self._connect_timer.setInterval(200)
        self._connect_timer.timeout.connect(self._try_connect)

        # Poll thread health — detect disconnections on the main thread
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(500)
        self._health_timer.timeout.connect(self._check_health)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> None:
        if not self._connect_timer.isActive():
            self._connect_timer.start()

    def close(self) -> None:
        self._connect_timer.stop()
        self._health_timer.stop()
        self._teardown()

    def is_connected(self) -> bool:
        return self._handle != 0

    def send_command(self, *command, callback: Optional[Callable] = None) -> int:
        self._request_id += 1
        msg = {"command": list(command), "request_id": self._request_id}
        if callback:
            self._pending[self._request_id] = callback
        raw = json.dumps(msg) + "\n"
        try:
            _ipc_log.debug(f"SEND  {raw.strip()}")
        except Exception:
            pass
        self._write(raw)
        return self._request_id

    def set_property(self, name: str, value) -> None:
        self.send_command("set_property", name, value)

    def get_property(self, name: str, callback: Callable) -> None:
        self.send_command("get_property", name, callback=callback)

    def observe_property(self, name: str, observe_id: Optional[int] = None) -> None:
        oid = observe_id if observe_id is not None else (hash(name) & 0xFFFF)
        self.send_command("observe_property", oid, name)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_connect(self) -> None:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(
            self._pipe_path,
            GENERIC_READ | GENERIC_WRITE,
            0, None, OPEN_EXISTING, 0, None,
        )
        if handle == INVALID_HANDLE:
            return

        self._connect_timer.stop()
        self._handle = handle

        # Non-blocking read mode
        kernel32.SetNamedPipeHandleState(
            handle, ctypes.byref(wintypes.DWORD(PIPE_NOWAIT)), None, None
        )

        self._reader = _ReaderThread(handle, self)
        self._reader.message_received.connect(self._on_message)
        self._reader.start()
        self._health_timer.start()

        for prop in OBSERVED_PROPERTIES:
            self.observe_property(prop)

        _ipc_log.debug("CONNECTED to mpv IPC pipe")
        self.connected.emit()

    def _check_health(self) -> None:
        """Called on the Qt main thread every 500ms — detect dead reader."""
        if self._reader is None:
            return
        if not self._reader.isRunning():
            _ipc_log.debug("Reader thread finished — disconnecting")
            self._teardown()
            self.disconnected.emit()

    def _teardown(self) -> None:
        """Clean up handle and reader — always called from the Qt main thread."""
        self._health_timer.stop()
        if self._reader is not None:
            reader = self._reader
            self._reader = None
            reader.stop()
            # Handle already set to 0 below — reader's PeekNamedPipe will fail
            # and it will exit its loop, then run() returns cleanly
            reader.wait(2000)
            if reader.isRunning():
                reader.terminate()
                reader.wait(500)
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = 0

    def _write(self, text: str) -> None:
        handle = self._handle
        if not handle:
            return
        try:
            data = text.encode("utf-8")
            buf = ctypes.create_string_buffer(data)
            written = wintypes.DWORD(0)
            ctypes.windll.kernel32.WriteFile(
                handle, buf, len(data), ctypes.byref(written), None
            )
        except Exception:
            pass

    def _on_message(self, msg: dict) -> None:
        if not self._handle:
            return
        try:
            prop = msg.get("name", "")
            if msg.get("event") != "property-change" or prop not in _NOISY:
                _ipc_log.debug(f"RECV  {json.dumps(msg)}")
        except Exception:
            pass

        self.message_received.emit(msg)

        if msg.get("event") == "property-change":
            self.property_changed.emit(msg.get("name", ""), msg.get("data"))
            return

        req_id = msg.get("request_id")
        if req_id and req_id in self._pending:
            cb = self._pending.pop(req_id)
            try:
                cb(msg)
            except Exception:
                pass

"""
Manages the mpv subprocess lifecycle: spawn, monitor, kill, restart.
Emits Qt signals so the UI can react to state changes without polling.
"""

from __future__ import annotations

import subprocess
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class ProcessState(Enum):
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    CRASHED = auto()


class MpvProcessManager(QObject):
    state_changed = pyqtSignal(ProcessState)
    # Emitted with the exit code when the process exits
    process_exited = pyqtSignal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._state = ProcessState.STOPPED
        self._mpv_args: list[str] = []
        self._mpv_executable = "mpv"

        # Poll timer — checks if the process is still alive every 500 ms
        self._last_stderr: str = ""
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> ProcessState:
        return self._state

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    def configure(self, executable: str, args: list[str]) -> None:
        """Set the mpv binary path and argument list before calling start()."""
        self._mpv_executable = executable
        self._mpv_args = args

    def start(self) -> None:
        if self._state not in (ProcessState.STOPPED, ProcessState.CRASHED):
            return
        self._set_state(ProcessState.STARTING)
        try:
            self._process = subprocess.Popen(
                [self._mpv_executable] + self._mpv_args,
                # Detach stdin so mpv doesn't inherit the console
                stdin=subprocess.DEVNULL,
                # Capture stderr for diagnostics without blocking
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self._set_state(ProcessState.CRASHED)
            return
        self._set_state(ProcessState.RUNNING)
        self._poll_timer.start()

    def stop(self) -> None:
        if self._process is None or self._state == ProcessState.STOPPED:
            return
        self._set_state(ProcessState.STOPPING)
        self._poll_timer.stop()
        try:
            self._process.terminate()
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
        finally:
            self._process = None
            self._set_state(ProcessState.STOPPED)

    def restart(self) -> None:
        """Stop then immediately start. Used by the signal health monitor."""
        self.stop()
        self.start()

    def is_running(self) -> bool:
        return self._state == ProcessState.RUNNING

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_state(self, new_state: ProcessState) -> None:
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state)

    def last_stderr(self) -> str:
        return self._last_stderr

    def _poll(self) -> None:
        if self._process is None:
            return
        code = self._process.poll()
        if code is not None:
            self._poll_timer.stop()
            try:
                stderr = self._process.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                stderr = ""
            self._last_stderr = stderr
            self._process = None
            self.process_exited.emit(code)
            self._set_state(ProcessState.CRASHED if code != 0 else ProcessState.STOPPED)

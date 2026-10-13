"""
Signal health monitor.

Watches mpv's video-params and video-pts-time properties via the IPC bridge.
When no valid video signal is detected for longer than `loss_timeout` seconds,
it transitions to NO_SIGNAL and requests a restart via the process manager.

State machine:
    IDLE ──start()──► STARTING
    STARTING ──video-params valid──► ACTIVE
    ACTIVE ──signal lost > timeout──► NO_SIGNAL
    NO_SIGNAL ──cooldown elapsed──► RESTARTING
    RESTARTING ──process started──► STARTING
    Any state ──stop()──► IDLE
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class SignalState(Enum):
    IDLE = auto()
    STARTING = auto()
    ACTIVE = auto()
    NO_SIGNAL = auto()
    RESTARTING = auto()


class SignalMonitor(QObject):
    state_changed = pyqtSignal(SignalState)
    # Emitted when a restart is needed; connect to MpvProcessManager.restart()
    restart_requested = pyqtSignal()

    def __init__(
        self,
        loss_timeout: float = 5.0,
        restart_cooldown: float = 3.0,
        max_attempts: int = 5,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._loss_timeout = loss_timeout
        self._restart_cooldown = restart_cooldown
        self._max_attempts = max_attempts

        self._state = SignalState.IDLE
        self._last_valid_ts: float = 0.0
        self._restart_attempts = 0

        # Ticks every second to evaluate signal health
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(1000)
        self._check_timer.timeout.connect(self._tick)

        # One-shot timer for restart cooldown
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._do_restart)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> SignalState:
        return self._state

    def start(self) -> None:
        """Call after mpv process is started."""
        self._restart_attempts = 0
        self._last_valid_ts = time.monotonic()
        self._set_state(SignalState.STARTING)
        self._check_timer.start()

    def stop(self) -> None:
        """Call when mpv is stopped intentionally."""
        self._check_timer.stop()
        self._restart_timer.stop()
        self._set_state(SignalState.IDLE)

    def reset_attempts(self) -> None:
        """Reset the consecutive restart counter (e.g. after a manual start)."""
        self._restart_attempts = 0

    # ------------------------------------------------------------------
    # IPC property hooks — connect these to MpvIpcBridge.property_changed
    # ------------------------------------------------------------------

    def on_property_changed(self, name: str, value) -> None:
        if name == "video-params":
            if value is not None:
                self._mark_signal_valid()
            # null video-params means no stream — let the timer handle timeout
        elif name == "time-pos":
            # Playback clock heartbeat. video-pts-time reads None on the DeckLink
            # live path (and video-params only fires once per open), but time-pos
            # advances at 1 Hz during healthy capture, so it is treated as the
            # live-signal heartbeat.
            #
            # CORRECTION (2026-09-20): the comment here used to claim "it freezes
            # when the stream truly stalls". IT DOES NOT, so this monitor cannot see
            # a delivery stall. `time-pos` is MpcPlayer::UpdateSnapshot ->
            # IMediaSeeking::GetPositions — the graph's stream position, which the
            # reference clock keeps advancing while the graph is in Run state,
            # whether or not frames are arriving. A stalled capture therefore keeps
            # this heartbeat alive, `_loss_timeout` never elapses, and no restart
            # fires. That belief is why a permanent black picture looked covered.
            #
            # Stalls belong to the engine's delivery watchdog (MpcPlayer::RefreshLive,
            # which watches the frame counters). THIS monitor owns SIGNAL LOSS — the
            # card reporting unlocked — and that is a different condition.
            if value is not None:
                self._mark_signal_valid()
        elif name == "idle-active":
            if value is True:
                # mpv is idle with no active stream
                pass  # handled by the tick timeout

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _mark_signal_valid(self) -> None:
        self._last_valid_ts = time.monotonic()
        if self._state in (SignalState.STARTING, SignalState.NO_SIGNAL):
            self._restart_attempts = 0
            self._set_state(SignalState.ACTIVE)

    def _tick(self) -> None:
        if self._state not in (SignalState.STARTING, SignalState.ACTIVE):
            return
        elapsed = time.monotonic() - self._last_valid_ts
        if elapsed >= self._loss_timeout:
            self._on_signal_lost()

    def _on_signal_lost(self) -> None:
        if self._state == SignalState.NO_SIGNAL:
            return
        self._set_state(SignalState.NO_SIGNAL)
        if self._restart_attempts >= self._max_attempts:
            # Give up — user must intervene manually
            self._check_timer.stop()
            return
        # Wait for cooldown then restart
        self._restart_timer.start(int(self._restart_cooldown * 1000))

    def _do_restart(self) -> None:
        self._restart_attempts += 1
        self._last_valid_ts = time.monotonic()
        self._set_state(SignalState.RESTARTING)
        self.restart_requested.emit()
        # After emitting, the process manager will restart mpv and call start() again
        self._set_state(SignalState.STARTING)

    def _set_state(self, new_state: SignalState) -> None:
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state)

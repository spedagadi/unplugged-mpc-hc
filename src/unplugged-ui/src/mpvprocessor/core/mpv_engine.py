"""
MpvEngine — wraps python-mpv (libmpv C API) for stable cross-platform operation.

Replaces both process_manager.py and ipc_bridge.py entirely.

libmpv runs inside the Python process — no subprocess, no named pipe,
no Win32 ctypes thread management, no QThread lifecycle issues.

Property changes are sent via direct Python attribute assignment.
Property observations use libmpv callbacks marshalled onto the Qt thread
via a thread-safe Qt signal.

Cross-platform:
  Windows: libmpv-2.dll in the same folder as the mpv executable
  Linux:   libmpv.so installed via package manager (apt install libmpv-dev)
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum, auto
from pathlib import Path
import queue as _queue
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QMetaObject, Qt, Q_ARG, pyqtSlot


log = logging.getLogger("videoforge.engine")


def _to_mpv_url(url: str) -> str:
    """
    Translate the app's internal 'decklink://<device name>' identifier into
    the URL mpv/ffmpeg actually understand: 'av://decklink:<device name>'.
    'decklink://' is not a real mpv protocol — passing it directly fails with
    "No protocol handler found" and the capture silently never starts.
    """
    prefix = "decklink://"
    if url.startswith(prefix):
        return f"av://decklink:{url[len(prefix):]}"
    return url


def _setup_libmpv_path(mpv_executable: str) -> None:
    """
    Add directories to PATH so ctypes.find_library can locate libmpv-2.dll.
    Must be called BEFORE importing mpv.
    Searches in order:
      1. The mpv executable's own folder (configured path)
      2. The running exe's folder (frozen deploy — libmpv-2.dll sits next to Unplugged.exe)
      3. The running exe's _internal folder (PyInstaller onedir)
    """
    candidates = [
        str(Path(mpv_executable).parent),
        str(Path(sys.executable).parent),
        str(Path(sys.executable).parent / "_internal"),
    ]
    current_path = os.environ.get("PATH", "")
    additions = [d for d in candidates if d not in current_path.split(os.pathsep)]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions) + os.pathsep + current_path


class EngineState(Enum):
    IDLE     = auto()   # mpv not initialised
    READY    = auto()   # mpv initialised, no file loaded
    PLAYING  = auto()   # file/stream playing
    PAUSED   = auto()
    ENDED    = auto()   # playback finished
    ERROR    = auto()


class MpvEngine(QObject):
    """
    Single entry point for all mpv operations.

    Signals emitted on the Qt main thread (safe for UI connection):
      state_changed(EngineState)
      property_changed(name, value)   — from any observed property
      log_message(level, component, text)
    """

    state_changed    = pyqtSignal(EngineState)
    property_changed = pyqtSignal(str, object)
    log_message      = pyqtSignal(str, str, str)
    # Parsed Zion Core per-frame stats — emitted ~24×/sec when Oracle is active
    zion_stats_updated = pyqtSignal(dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._mpv = None          # mpv.MPV instance
        self._state = EngineState.IDLE
        self._wid: int = 0
        self._observed: set[str] = set()

        # Pending property changes queued before mpv is ready
        self._pending_props: list[tuple[str, object]] = []

        # ── Thread-safe log queue ─────────────────────────────────────
        # The mpv C event thread calls _on_log() synchronously.  Doing ANYTHING
        # non-trivial there (signal emissions, regex, file I/O) can block or race
        # with libmpv's internal event loop → crash.
        #
        # Fix: _on_log() does ONE atomic put_nowait() into this queue and returns.
        # A QTimer on the Qt main thread drains it every 50ms — all processing
        # (signal emission, regex parse, logging) happens safely on the Qt thread.
        self._log_queue: _queue.SimpleQueue = _queue.SimpleQueue()
        self._log_drain_timer = QTimer(self)
        self._log_drain_timer.setInterval(50)   # 50ms — 20× per second, imperceptible
        self._log_drain_timer.timeout.connect(self._drain_log_queue)
        self._log_drain_timer.start()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self, mpv_executable: str, wid: int = 0,
                   startup_opts: Optional[dict] = None) -> None:
        """
        Load libmpv and create the MPV instance.
        Must be called once before start_file() or start_capture().
        startup_opts: extra kwargs merged into MPV() constructor (e.g. cache, demuxer settings).
        """
        if self._mpv is not None:
            return

        _setup_libmpv_path(mpv_executable)

        try:
            import mpv as _mpv_module
        except OSError as e:
            log.error(f"libmpv load failed: {e}")
            self._set_state(EngineState.ERROR)
            return

        self._wid = wid

        kwargs = {
            "input_vo_keyboard": False,
        }
        if wid:
            kwargs["wid"] = str(wid)
        if startup_opts:
            kwargs.update(startup_opts)

        self._mpv = _mpv_module.MPV(**kwargs)
        # Attach log handler after construction to avoid deadlock during init
        self._mpv.log_handler = self._on_log

        # Track whether we've seen the first real frame for this play() call.
        # DeckLink streams fire start-file → end-file(redirect=4) in a tight
        # reconnect loop before the first frame arrives.  Emitting PLAYING on
        # start-file causes _vp_confirm_playing to dismiss the overlay before
        # any frame is shown, then the redirect end-file re-enters IDLE.
        # Instead we emit PLAYING only when video-params becomes non-None,
        # which means the VO has actually received and decoded a frame.
        self._video_params_seen = False

        # reason values: 0=eof, 1=stop, 2=quit, 3=error, 4=redirect, 5=unknown
        @self._mpv.event_callback("end-file")
        def on_end_file(event):
            try:
                data = getattr(event, "data", None)
                reason = getattr(data, "reason", 0) if data else 0
                if reason == 4:   # MPV_END_FILE_REASON_REDIRECT — DeckLink reconnect loop
                    return        # ignore; mpv will restart automatically
                self._video_params_seen = False
                if reason == 3:   # MPV_END_FILE_REASON_ERROR
                    self._qt_state(EngineState.ERROR)
                else:
                    self._qt_state(EngineState.ENDED)
            except Exception:
                self._video_params_seen = False
                self._qt_state(EngineState.ENDED)

        @self._mpv.event_callback("start-file")
        def on_start_file(event):
            pass  # do not poll — VO is not initialized yet

        @self._mpv.event_callback("file-loaded")
        def on_file_loaded(event):
            pass  # do not poll — first frame not rendered yet

        # Apply any pending property changes
        for name, value in self._pending_props:
            self._set_prop(name, value)
        self._pending_props.clear()

        self._set_state(EngineState.READY)

    def set_vo_option(self, name: str, value) -> None:
        """Apply a VO-scoped option before playback starts.

        mpv does not expose VO options (ml-acq-*) or most launch options as
        readable properties — set_property returns MPV_ERROR_PROPERTY_NOT_FOUND
        and the value silently never lands. mpv_set_option_string works on the
        raw handle (the route the CLI uses) pre-play, so options are in place
        when the VO initialises.
        """
        if self._mpv is None:
            return
        try:
            import ctypes
            lib = ctypes.CDLL("libmpv-2.dll")   # resolvable: path was added by _setup_libmpv_path
            lib.mpv_set_option_string.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            lib.mpv_set_option_string.restype = ctypes.c_int
            h = getattr(self._mpv, "handle")
            rc = lib.mpv_set_option_string(h, name.encode(), str(value).encode())
            if rc != 0:
                log.warning(f"set_option_string({name}={value}) rc={rc}")
        except Exception as e:
            log.warning(f"set_option_string({name}={value}) failed: {e}")

    def apply_options(self, args: list) -> None:
        """Apply launch args via mpv_set_option_string.

        The launcher args we build are options, not properties — every one was
        silently dropped when applied with set_property (verified: -8 for all
        of demuxer-lavf-o / vd-lavc-o / framedrop / video-latency-hacks /
        ml-acq-*). Routing them through set_option_string matches the CLI and
        makes them actually take effect.
        """
        if self._mpv is None:
            return
        try:
            import ctypes
            lib = ctypes.CDLL("libmpv-2.dll")
            lib.mpv_set_option_string.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            lib.mpv_set_option_string.restype = ctypes.c_int
            h = getattr(self._mpv, "handle")
        except Exception as e:
            log.warning(f"apply_options: ctypes init failed: {e}")
            return
        for a in args:
            if not a.startswith("--"):
                continue
            body = a[2:]
            name, _, value = body.partition("=")
            if not name:
                continue
            if not value:
                # bare flag: --no-X is the CLI's inversion spelling → X=no
                value = "no" if name.startswith("no-") else "yes"
                if name.startswith("no-"):
                    name = name[3:]
            try:
                rc = lib.mpv_set_option_string(h, name.encode(), value.encode())
                if rc != 0:
                    log.warning(f"mpv option {name}={value} rc={rc}")
            except Exception as e:
                log.warning(f"mpv option {name}: {e}")

    def shutdown(self) -> None:
        if self._mpv is None:
            return
        try:
            self._mpv.terminate()
        except Exception:
            pass
        self._mpv = None
        self._observed.clear()
        self._set_state(EngineState.IDLE)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self, url: str) -> None:
        """Play a URL (file path or device URL like decklink://...)."""
        if self._mpv is None:
            return
        try:
            self._mpv.play(_to_mpv_url(url))
        except Exception as e:
            log.error(f"play failed: {e}")
            self._set_state(EngineState.ERROR)

    def stop(self) -> None:
        if self._mpv is None:
            return
        try:
            self._mpv.stop()
        except Exception:
            pass
        self._set_state(EngineState.IDLE)

    def pause(self, paused: bool) -> None:
        self.set_property("pause", paused)

    def seek(self, seconds: float) -> None:
        if self._mpv is None:
            return
        try:
            self._mpv.seek(seconds, "absolute")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Options — applied via mpv option interface (set_option_string)
    # ------------------------------------------------------------------

    def apply_libplacebo_opts(self, opts: str) -> None:
        """
        Apply a comma-separated key=value string via libplacebo-opts.
        e.g. "perceptual_deadzone=0.30,softclip_knee=0.70"
        """
        if self._mpv is None:
            return
        try:
            self._mpv.command("change-list", "libplacebo-opts", "set", opts)
        except Exception as e:
            log.warning(f"libplacebo-opts failed: {e}")

    def command(self, *args) -> None:
        """Send an mpv command (e.g. 'script-binding', 'stats/display-stats-toggle')."""
        if self._mpv is None:
            return
        try:
            self._mpv.command(*args)
        except Exception as e:
            log.debug(f"command({args!r}) failed: {e}")

    def set_property(self, name: str, value: object) -> None:
        """Set an mpv property. Queues if mpv not yet ready."""
        if self._mpv is None:
            self._pending_props.append((name, value))
            return
        self._set_prop(name, value)

    def get_property(self, name: str, default=None):
        if self._mpv is None:
            return default
        try:
            # python-mpv uses snake_case attributes for runtime properties
            attr = name.replace("-", "_")
            return getattr(self._mpv, attr, default)
        except Exception:
            return default

    def poll_properties(self, names: list[str]) -> None:
        """Disabled — was a manual polling method that raced with the mpv event
        thread. All property updates come exclusively via observe_property.
        Kept as a no-op so any remaining call sites don't error."""
        pass  # no-op: safe to call but does nothing

    # ------------------------------------------------------------------
    # Property observation
    # ------------------------------------------------------------------

    def observe(self, name: str) -> None:
        """
        Observe an mpv property. Changes are emitted as property_changed(name, value).
        Safe to call multiple times — duplicates are ignored.
        """
        if name in self._observed or self._mpv is None:
            return
        self._observed.add(name)

        # libmpv calls this from its internal thread — relay to Qt via signal
        @self._mpv.property_observer(name)
        def _observer(prop_name, value):
            # This runs on the libmpv thread — use a thread-safe Qt signal
            self._emit_property_change(prop_name, value)

    def _emit_property_change(self, name: str, value) -> None:
        """Called from libmpv thread — queue signal to Qt main thread safely."""
        try:
            # QMetaObject.invokeMethod with AutoConnection safely crosses threads
            QMetaObject.invokeMethod(
                self, "_on_property_qt",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, name),
                Q_ARG(object, value),
            )
        except Exception:
            pass

    @pyqtSlot(str, object)
    def _on_property_qt(self, name: str, value) -> None:
        """Runs on the Qt main thread — safe to emit signals."""
        if name == "video-params" and value is not None and not self._video_params_seen:
            self._video_params_seen = True
            self._set_state(EngineState.PLAYING)
            # All status properties are already observed via observe_property.
            # Their change events fire safely via QueuedConnection as mpv
            # initialises — no explicit poll needed, no race condition.
        self.property_changed.emit(name, value)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> EngineState:
        return self._state

    def is_playing(self) -> bool:
        return self._state == EngineState.PLAYING

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _poll_all_observed(self) -> None:
        """Intentionally disabled — was a polling method that raced with the mpv
        event thread causing access violations. All property updates now come
        exclusively via observe_property QueuedConnection callbacks."""
        pass  # no-op: safe to call but does nothing

    def _set_prop(self, name: str, value: object) -> None:
        try:
            self._mpv[name] = value
        except Exception as e:
            log.debug(f"set_property({name}={value!r}) failed: {e}")

    def _set_state(self, state: EngineState) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)

    def _qt_state(self, state: EngineState) -> None:
        """Called from libmpv thread — queue state change to Qt main thread."""
        try:
            QMetaObject.invokeMethod(
                self, "_on_state_qt",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, state.value),
            )
        except Exception:
            pass

    @pyqtSlot(int)
    def _on_state_qt(self, state_val: int) -> None:
        """Runs on Qt main thread."""
        self._set_state(EngineState(state_val))

    # ── Zion Core log parser ──────────────────────────────────────────────────
    # Parses the per-frame ML: line emitted by vo_gpu_next.c at verbose level.
    # Format:
    #   ML: gamma=0.752(model) cr=0.150(auto) rad=0.300@0.60(auto)
    #        chroma=manual fire=1.00 iir=0.10 l1max=0.7519  [eval=0.1ms iir=0.0ms]
    # Also parses the build stamp:
    #   [Zion] Build #6 (2026-08-27 16:42) — loading model: ...

    import re as _re
    _ML_RE = _re.compile(
        r"gamma=([0-9.]+)\((\w+)\)"
        r".*?cr=([0-9.]+)\((\w+)\)"
        r".*?rad=([0-9.]+)@([0-9.]+)\((\w+)\)"
        r".*?chroma=(\w+)"
        r".*?iir=([0-9.]+)\s"
        r".*?l1max=([0-9.]+)"
        r".*?shad=([0-9.]+)@([0-9.]+)"
        r".*?hi=([0-9.]+)@([0-9.]+)"
        r".*?\[eval=([0-9.]+)ms.*?iir=([0-9.]+)ms\]"
    )
    _BUILD_RE = _re.compile(r"\[Zion\] Build #(\d+) \(([^)]+)\)")
    _zion_build: str = ""

    def _on_log(self, level: str, component: str, message: str) -> None:
        """Called from mpv's C event thread — must return IMMEDIATELY.
        Put the message into the thread-safe queue and return.
        All processing happens on the Qt main thread via _drain_log_queue."""
        try:
            self._log_queue.put_nowait((level, component, message))
        except Exception:
            pass  # queue is unbounded SimpleQueue, put_nowait never blocks/raises

    def _drain_log_queue(self) -> None:
        """Runs on the Qt main thread (QTimer, 50ms interval).
        Drains all pending log messages and does the heavy work safely."""
        processed = 0
        while processed < 200:   # cap per-tick to avoid starving the event loop
            try:
                level, component, message = self._log_queue.get_nowait()
            except _queue.Empty:
                break
            processed += 1

            # Emit for any UI consumers (e.g. debug log panel)
            self.log_message.emit(level, component, message)

            # Python logging
            if level in ("error", "fatal"):
                log.error(f"[mpv/{component}] {message}")
            elif level == "warn":
                log.warning(f"[mpv/{component}] {message}")

            # Zion Core stats: parse ML: lines from vo/gpu-next
            if component != "vo/gpu-next":
                continue
            if message.startswith("[Zion]"):
                m = self._BUILD_RE.search(message)
                if m:
                    self._zion_build = f"#{m.group(1)}  {m.group(2)}"
            elif message.startswith("ML: "):
                m = self._ML_RE.search(message)
                if m:
                    try:
                        stats = {
                            "oracle_gamma":       float(m.group(1)),
                            "oracle_source":      m.group(2),
                            "cr_strength":        float(m.group(3)),
                            "cr_mode":            m.group(4),
                            "rad_strength":       float(m.group(5)),
                            "rad_knee":           float(m.group(6)),
                            "rad_mode":           m.group(7),
                            "chroma_mode":        m.group(8),
                            "iir_alpha":          float(m.group(9)),
                            "l1max":              float(m.group(10)),
                            "shadow_strength":    float(m.group(11)),
                            "shadow_knee":        float(m.group(12)),
                            "highlight_strength": float(m.group(13)),
                            "highlight_knee":     float(m.group(14)),
                            "eval_ms":            float(m.group(15)),
                            "iir_ms":             float(m.group(16)),
                            "build":              self._zion_build,
                        }
                        self.zion_stats_updated.emit(stats)
                    except Exception:
                        pass

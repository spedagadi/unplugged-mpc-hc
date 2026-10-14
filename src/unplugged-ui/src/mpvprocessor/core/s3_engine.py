"""
S3Engine — drop-in replacement for MpvEngine backed by s3engine.dll
(mpchc_engine + DeckLinkSource.ax + MPCVR, the proven C++ pipeline).

The unplugged UI stays exactly as it was (splash, panels, hotkeys, layout);
only the engine layer changes. Everything the UI does crosses a tiny C ABI:

    s3_attach(hwnd)          — put MPCVR into the viewport's native window
    s3_start_device(name)    — begin self-healing DeckLink capture
    s3_stats(buf)            — JSON status blob (MpcPlayer::GetUiStatusJson)
    s3_cmd('{"a":...}')      — transport (play/pause/stop/seek)
    s3_shutdown()            — ordered teardown (DESIGN.md)

Key difference from mpv: the engine is SELF-HEALING. Its internal
decklink_monitor → ops-queue executor does the ordered teardown + relaunch on
any confirmed signal change. The app therefore never drives transitions — the
mpv-era restart loops (start/stop/play on signal events) become harmless no-ops.

MPCVR-specific settings (maLook tvf/libplacebo/zion chains) are not yet mapped:
set_property() for those is logged and ignored until the panel mappings land.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

log = logging.getLogger("unplugged.s3_engine")


class EngineState(Enum):
    # MUST mirror the mpv-era member set the app's code references
    # (EngineState.READY / EngineState.ENDED appear in main_window's state_map
    # and conditionals — an AttributeError there froze the acquire overlay).
    IDLE    = auto()
    READY   = auto()
    LOADING = auto()   # s3 extension (start) — not referenced by the app
    PLAYING = auto()
    PAUSED  = auto()
    ENDED   = auto()
    ERROR   = auto()


def _find_s3engine_dll() -> str:
    """Locate s3engine.dll — the in-repo build output, or a copy bundled with us.

    The app now lives inside mpc-hc, so the engine's build output is reachable
    by walking up rather than by the absolute path this used to hardcode.
    """
    this = Path(__file__).resolve()
    candidates = []
    # core -> mpvprocessor -> src -> unplugged-ui -> src -> <repo root>
    try:
        candidates.append(this.parents[5] / "tools" / "s3engine" / "s3engine.dll")
    except IndexError:
        pass
    # Frozen builds stage the freshly built DLL into _internal/ (and beside the
    # exe). These MUST be checked before the in-package copy below: the spec
    # ships `src/mpvprocessor` wholesale as data, so a stale s3engine.dll left
    # in the source tree would otherwise win and the app would run an old engine
    # with none of the current settings names.
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        candidates.append(Path(_meipass) / "s3engine.dll")
    candidates += [
        Path(sys.executable).parent / "s3engine.dll",   # frozen: beside the exe
        this.parent / "s3engine.dll",                   # next to this module
        this.parent.parent / "s3engine.dll",            # _internal/mpvprocessor/
        Path.cwd() / "s3engine.dll",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "s3engine.dll"   # let ctypes fall back to PATH


def _to_device(url: str) -> str:
    """decklink://<device name>?...  ->  <device name>"""
    prefix = "decklink://"
    if url.startswith(prefix):
        return url[len(prefix):].split("?")[0]
    return url


class S3Engine(QObject):
    state_changed       = pyqtSignal(EngineState)
    property_changed    = pyqtSignal(str, object)
    log_message         = pyqtSignal(str, str, str)
    zion_stats_updated  = pyqtSignal(dict)
    s3_status           = pyqtSignal(dict)   # full engine JSON each poll
                                          # (status_panel.on_s3_status mapper)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lib   = None
        self._attached = False
        self._started  = None          # started device name (or None)
        self._state = EngineState.IDLE
        self._j: dict = {}
        self._observed: set[str] = set()
        self._attach_failed_logged = False

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll)

        # Facade compat with the mpv-era call sites (main_window checks these):
        self._mpv = object()               # truthy sentinel: "engine loaded"
        self._video_params_seen = True     # avoid mpv-specific param-retry paths
        self._path_setup_done = True

    # -- lifecycle -----------------------------------------------------------
    def _load(self) -> bool:
        if self._lib is not None:
            return True
        try:
            path = _find_s3engine_dll()
            self._lib = ctypes.CDLL(path)
            for name, rest in (("s3_attach", [ctypes.c_int64]),
                               ("s3_start_device", [ctypes.c_char_p]),
                               ("s3_stats", [ctypes.c_char_p, ctypes.c_int]),
                               ("s3_cmd", [ctypes.c_char_p]),
                               ("s3_shutdown", [])):
                fn = getattr(self._lib, name)
                fn.restype = ctypes.c_int
                fn.argtypes = rest
            return True
        except Exception as e:   # noqa: BLE001
            log.error("s3engine.dll load failed: %s", e)
            self._lib = None
            return False

    def initialise(self, _mpv_executable: str, wid: int = 0, **_kwargs) -> None:
        if not self._load():
            self.log_message.emit("s3", "error", "s3engine.dll not found")
            return
        if wid and not self._attached:
            rc = self._lib.s3_attach(wid)
            log.info("s3_attach(hwnd=%d) rc=%d", wid, rc)
            self._attached = (rc == 0)
            self.log_message.emit("s3", "info", f"s3 engine attached (hwnd={wid})")

    def play(self, url: str) -> None:
        if not self._load():
            return
        # Media Player mode is a real FILE; only decklink:// URLs are capture.
        # This used to mis-route a file path into s3_start_device, where it was
        # treated as a DeckLink device — no lock ever arrived, so the graph never
        # launched and the UI sat at "opening" forever.
        if not url.startswith("decklink://"):
            self._lib.s3_cmd(json.dumps({"a": "open", "url": url}).encode("utf-8"))
            # THE data feed. The capture path starts this timer below; the file
            # path NEVER DID — so after {"a":"open"} no s3_stats was polled, no
            # property_changed fired, and the bar/panel had nothing to bind
            # (flat duration label, empty status rows). Starting it here makes
            # the engine JSON the UI's source of truth for files too.
            self._timer.start()
            return
        device = _to_device(url)
        if not self._started and device:
            device_b = device.encode("utf-8")
            rc = self._lib.s3_start_device(device_b)
            log.info("s3_start_device('%s') rc=0x%08X", device, rc)
            self._started = device
            self.log_message.emit("s3", "info", f"capture start issued ({device})")
            self._set_state(EngineState.LOADING)
            self._timer.start()

    def stop(self) -> None:
        pass   # engine owns transitions; pause only if desired later

    def pause(self, paused: bool) -> None:
        if self._lib:
            self._lib.s3_cmd(b'{"a":"%s"}' % (b"pause" if paused else b"play"))

    def seek(self, seconds: float) -> None:
        if self._lib and seconds >= 0:
            pos = int(seconds * 1e7)
            self._lib.s3_cmd(json.dumps({"a": "seek", "pos": pos}).encode("utf-8"))

    # P2 settings protocol: apply "grp.name=value" pairs (semicolon-separated),
    # e.g. {"hdr": {"sdrNits": 204}, "ml": {"gamma": 1.1}} -> "hdr.sdrNits=204;..."
    def apply_settings(self, groups: dict) -> None:
        if not self._lib:
            return
        parts: list[str] = []
        for grp, kv in groups.items():
            for k, v in kv.items():
                sval = v if isinstance(v, str) else (
                    json.dumps(v) if isinstance(v, bool) else str(v))
                parts.append(f"{grp}.{k}={sval}")
        if parts:
            cmd = {"a": "set", "sets": ";".join(parts)}
            self._lib.s3_cmd(json.dumps(cmd).encode("utf-8"))

    def select_audio_track(self, index: int) -> None:
        """Pick the Nth audio stream (audio-relative index, live)."""
        if self._lib:
            self._lib.s3_cmd(json.dumps({"a": "track", "index": int(index)}).encode("utf-8"))

    def select_subtitle_track(self, index: int) -> None:
        """Pick the Nth subtitle stream (subtitle-relative index, live).

        The engine's "subtrack" action takes -1 for off, which is how the rail's Off
        entry maps; anything else is enabled through the splitter's IAMStreamSelect and
        reaches the picture through the presenter's subpic queue."""
        if self._lib:
            self._lib.s3_cmd(json.dumps({"a": "subtrack", "index": int(index)}).encode("utf-8"))

    def set_subtitle_visible(self, on: bool) -> None:
        """Show/hide the current subtitle without changing which stream is selected."""
        if self._lib:
            self._lib.s3_cmd(json.dumps({"a": "subvisible", "on": 1 if on else 0}).encode("utf-8"))

    def set_audio_mode(self, mode: int) -> None:
        """0 = decode to PCM, 1 = bitstream. Triggers an engine re-open to apply."""
        self.apply_settings({"audio": {"mode": int(mode)}})

    # NOTE (2026-09-20): a _post_cmd() helper briefly fired s3_cmd on a daemon
    # thread to stop the acquire overlay freezing when SetSettings blocked. That
    # block turned out to be the Discard swap chain (fixed in the renderer), and
    # the off-thread call was a hazard in its own right: any row that sets
    # changeHDR — Tone curve, Convert to SDR, HDR passthrough, toggle display —
    # reaches InitMediaType / ReleaseSwapChain, which must not run off the
    # filter's thread. It faulted the renderer. Kept on the caller's thread, as
    # it was before.

    def save_settings(self) -> None:
        """Persist the renderer's live settings to its own registry key.

        IVideoRenderer::SetSettings applies live only. The renderer's constructor
        reads HKCU\\Software\\Unplugged\\Renderer on startup, so without this a
        graph rebuild — which the engine does on any signal change — brings up a
        fresh instance that has silently discarded everything we pushed.
        """
        if self._lib:
            self._lib.s3_cmd(b'{"a":"save"}')

    def capture_frame(self, bmp_path: str) -> int:
        """Ask the renderer to write its CURRENT output frame as a BMP.

        Uses the engine's renderer-side grab (IBasicVideo::GetCurrentImage) —
        the frame actually drawn, not a window/desktop capture. The engine also
        logs size + meanLuma for the grabbed frame (GrabFrame). Returns the
        HRESULT (0 == S_OK); the caller converts BMP -> PNG.
        """
        if not self._lib:
            return -1
        return int(self._lib.s3_cmd(
            json.dumps({"a": "grab", "file": bmp_path}).encode("utf-8")))

    def load_cube_lut(self, path: str, mode: int = 3) -> None:
        """Load a display calibration .cube 3D LUT; an empty path clears it.

        The renderer samples it in the final pass — the last display-referred
        stage — so it corrects the panel rather than the signal.
        mode: 0=off, 1=gamma only, 2=greyscale, 3=full 3D (default).
        """
        if self._lib:
            self._lib.s3_cmd(json.dumps(
                {"a": "lut", "file": path or "", "mode": int(mode)}).encode("utf-8"))

    def command(self, *args) -> None:
        pass   # mpv-specific (stats OSD etc.) — ignored

    def set_vo_option(self, name: str, value) -> None:
        pass   # mpv VO option — MPCVR equivalents mapped later

    def apply_options(self, args: list) -> None:
        pass   # mpv launch options — ignored

    def apply_libplacebo_opts(self, opts: str) -> None:
        pass   # mpv libplacebo chain — MPCVR tone-map equivalents later

    def poll_properties(self, names: list[str]) -> None:
        self._poll()   # cheap: refresh cache + emit changes

    def shutdown(self) -> None:
        """Stop the poll timer, then the engine's ordered teardown.

        s3_shutdown bounds itself at ~10 s (detached worker + wait) and is
        idempotent. A watchdog floor guarantees the process can NEVER linger as
        a ghost: if the engine teardown, Qt/WebEngine finalization or anything
        else keeps the interpreter alive past 15 s, a daemon thread force-exits
        (os._exit bypasses Python finalization — exactly the force we want at
        that point; a leftover Unplugged holds the DeckLink and blocks relaunch).
        Logged first so the trip reason stays in the log.
        """
        self._timer.stop()
        if self._lib:
            self._lib.s3_shutdown()
            self._lib = None

        def _watchdog() -> None:
            log.error("shutdown watchdog: process still alive 15 s after close — forcing exit")
            os._exit(0)
        threading.Thread(target=lambda: (time.sleep(15), _watchdog()),
                         daemon=True).start()

    # -- properties ------------------------------------------------------------
    def set_property(self, name: str, value) -> None:
        low = name.lower()
        if low == "pause":
            self.pause(bool(value))
        elif low == "mute":
            log.info("s3: mute %s (audio is pass-through; ignored)", value)
        elif low == "volume":
            log.info("s3: volume %s (audio is pass-through; ignored)", value)
        else:
            log.debug("s3: set_property(%s)=%r unsupported — ignored", name, value)
            # mpv-only chains (vf / libplacebo / zion) are intentionally inert
            # until the MPCVR settings mapping lands.

    def get_property(self, name: str, default=None):
        return self._flat_get(name, default)

    def observe(self, name: str) -> None:
        self._observed.add(name)

    def state(self) -> EngineState:
        return self._state

    def is_playing(self) -> bool:
        return self._state == EngineState.PLAYING

    # -- polling ---------------------------------------------------------------
    def _set_state(self, state: EngineState) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _flat_get(self, name: str, default=None):
        j = self._j
        if name == "time-pos":
            return j.get("pos", 0) / 1e7
        if name == "duration":
            return j.get("dur", 0) / 1e7
        if name == "pause":
            return j.get("state") == "paused"
        if name == "volume":
            return j.get("vol", 100)
        if name == "mute":
            return j.get("muted", False)
        if name == "video-params":
            m = j.get("media") or {}
            if m.get("valid"):
                # The panel's decoder (status_panel.on_property) reads STRING keys
                # colormatrix/gamma/pixelformat and maps them through its
                # _COLORSPACE/_TRANSFER/humanize_pixfmt tables. We used to send
                # numbers under colorspace/transfer — those decoded to blank. Map
                # the engine's DXVA2/MF enums to the table names:
                #   tf  = extended-format VideoTransferFunction, REAL SDK values
                #          (mfobjects.h/dxva2api.h: _2084=15, HLG=16, 709=5,
                #          sRGB=7, gamma2.2=4, gamma2.8=8; earlier numbers here
                #          were stale/memory and mislabelled 15 (PQ) as gamma 2.8)
                #   prim = either normalized (1=601 2=709 3=2020) via
                #          CaptureSourceMediaType, or the raw enum fallback from
                #          the renderer (2=709, 9=2020).
                tfc = {15: "pq", 16: "hlg", 13: "bt.2020", 12: "bt.2020",
                       5: "bt.1886", 11: "bt.1886", 7: "srgb",
                       4: "gamma2.2", 8: "gamma2.8", 1: "linear"}.get(
                    m.get("tf", 0), "")
                prm = {2: "bt.709", 9: "bt.2020", 3: "bt.2020", 1: "bt.601-525",
                       5: "bt.601-525", 4: "bt.601-625", 6: "bt.601-625"}.get(
                    m.get("prim", 0), "")
                pxf = m.get("subtype", "")   # "P010"/"v210"/"NV12"/"UYVY" —
                                             # exactly what humanize_pixfmt matches
                return {
                    "w": m["w"], "h": m["h"], "fps": m["fps"],
                    "subtype": pxf,
                    # panel-decode keys (names):
                    "pixelformat": pxf,
                    "colormatrix": prm,
                    "gamma": tfc,
                    # numbers too (for anything reading primitives):
                    "colorspace": m.get("prim", 0),
                    "transfer": m.get("tf", 0),
                    "primaries": m.get("prim", 0),
                    "tf": m.get("tf", 0),
                    "hdr": m.get("hdr", 0),
                }
            return default
        if name == "video-format":
            # DeckLink stats (dl) are always zero in Media mode — there is no
            # DeckLink filter — so fall back to the file's media block, which
            # videoStreamInfo_ populates from the decoder output type.
            dl = j.get("dl") or {}
            if dl.get("w"):
                return f"{dl['w']}x{dl['h']}"
            m = j.get("media") or {}
            if m.get("valid") and m.get("w"):
                return f"{m['w']}x{m['h']}"
            return default
        if name == "signal-lock":
            sig = j.get("signal") or {}
            return bool(sig.get("locked"))
        return default

    def _poll(self) -> None:
        if not self._lib:
            return
        buf = ctypes.create_string_buffer(8192)
        try:
            n = self._lib.s3_stats(buf, len(buf))
        except OSError:
            return
        if n <= 0:
            return
        try:
            self._j = json.loads(buf.value.decode("utf-8"))
        except json.JSONDecodeError:
            return

        state_ = self._j.get("state", "idle")
        # The engine's StateName() is the source of these strings. "ended" is
        # distinct from "idle" and "opening" precisely so the UI can tell a FINISHED
        # TITLE from a mid-stream rebuild-only re-open; collapsing them (as the old
        # engine ternary did, and as mapping "opening" to IDLE here would) makes
        # exit-on-finish fire one second into playback.
        # "stopped" maps to IDLE, not ENDED: a manual stop returns to the library,
        # it must not be mistaken for a title that finished.
        st = {"playing": EngineState.PLAYING,
              "paused":  EngineState.PAUSED,
              "ended":   EngineState.ENDED,
              "stopped": EngineState.IDLE,
              "opening": EngineState.LOADING,
              "idle":    EngineState.IDLE,
              "error":   EngineState.ERROR}.get(state_, EngineState.IDLE)
        self._set_state(st)

        # property events for observed (and key) props
        for prop in ("time-pos", "duration", "pause", "volume", "mute",
                     "video-params", "video-format", "signal-lock"):
            if prop in self._observed or prop in ("time-pos", "pause", "duration", "video-params"):
                self.property_changed.emit(prop, self._flat_get(prop))

        # No MPCVR-Zion telemetry wired yet — do NOT emit zion_stats_updated
        # (it would flash the mpv-era ZION rows, which read different keys).
        self.s3_status.emit(self._j)
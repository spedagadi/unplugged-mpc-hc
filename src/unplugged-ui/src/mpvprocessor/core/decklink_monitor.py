"""
DeckLink signal monitor — Python ctypes wrapper around decklink_monitor.dll.

Polls IDeckLinkStatus (read-only, no exclusive device lock) while mpv/ffmpeg
holds the capture device open. Detects signal loss and format changes.

Emits Qt signals on the main thread:
  signal_locked(bool)       — True = signal present, False = lost
  format_changed(int)       — new display mode hash when format changes
  dynamic_range_changed(int) — 0=SDR, 1=HDR

Usage:
    monitor = DeckLinkMonitor("DeckLink Quad HDMI Recorder")
    monitor.signal_locked.connect(on_locked)
    monitor.start()
    ...
    monitor.stop()
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..assets import asset as _asset

_log = logging.getLogger("unplugged.decklink_monitor")


def _find_dll() -> Optional[str]:
    """Locate decklink_monitor.dll — check app dir, mpv dir, PATH."""
    candidates = [
        # Next to mpv.exe
        Path(os.environ.get("PATH", "").split(os.pathsep)[0]) / "decklink_monitor.dll",
        # Alongside this file
        Path(__file__).parent / "decklink_monitor.dll",
        # Bundled with the app (dev: <app-root>/assets, frozen: _internal/assets)
        _asset("decklink_monitor.dll"),
        # PyInstaller _internal/ (frozen/packaged builds)
        Path(getattr(sys, '_MEIPASS', sys.executable)) / "decklink_monitor.dll",
        Path(sys.executable).parent / "_internal" / "decklink_monitor.dll",
        # Current working directory
        Path.cwd() / "decklink_monitor.dll",
    ]
    # Also search PATH entries
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidates.append(Path(p) / "decklink_monitor.dll")

    for c in candidates:
        if c.exists():
            return str(c)
    return None


class _SignalInfoC(ctypes.Structure):
    _fields_ = [
        ("colorspace",    ctypes.c_int),
        ("dynamic_range", ctypes.c_int),
        ("pixel_depth",   ctypes.c_int),
        ("chroma",        ctypes.c_int),
        ("locked",        ctypes.c_int),
    ]


class SignalInfo:
    """Detected signal properties from DeckLink hardware."""
    COLORSPACE = {0: "bt.601-525", 1: "bt.709", 2: "bt.2020"}
    GAMMA      = {0: "bt.1886",    1: "pq",     2: "hlg"}
    MATRIX     = {0: "bt.601",     1: "bt.709",  2: "bt.2020-ncl"}

    def __init__(self, c: _SignalInfoC) -> None:
        self.colorspace    = c.colorspace    # 0=Rec601 1=Rec709 2=Rec2020
        self.dynamic_range = c.dynamic_range # 0=SDR    1=HDR_PQ 2=HDR_HLG
        self.pixel_depth   = c.pixel_depth   # 8/10/12
        self.chroma        = c.chroma        # 1=RGB444 0=YCbCr422 -1=unknown
        self.locked        = bool(c.locked)

    @classmethod
    def from_facts(cls, colorspace: int, dynamic_range: int, pixel_depth: int,
                   chroma: int, locked: bool) -> "SignalInfo":
        """Build from the engine's pushed facts instead of a local device read."""
        c = _SignalInfoC(colorspace=int(colorspace), dynamic_range=int(dynamic_range),
                         pixel_depth=int(pixel_depth), chroma=int(chroma),
                         locked=1 if locked else 0)
        return cls(c)

    @property
    def is_rgb444(self) -> bool:
        return self.chroma == 1

    def is_hdr(self) -> bool:
        return self.dynamic_range > 0

    def is_likely_dolby_vision(self) -> bool:
        """
        DeckLink cannot signal Dolby Vision through its standard DR field.
        DV content from Apple TV appears as BT.2020 colorspace + SDR dynamic range.
        BT.2020+SDR is not a real-world combination from consumer devices — if we see
        it, the source is almost certainly outputting Dolby Vision.
        """
        return self.colorspace == 2 and self.dynamic_range == 0

    def build_vf_filter(self) -> str:
        """
        Build the --vf=format=... argument for mpv based on detected signal.

        Only override the properties that DeckLink's IDeckLinkStatus reports and
        that cannot be reliably auto-detected from the stream headers:
          - colorlevels: DeckLink ALWAYS outputs limited range — must be forced
          - primaries:   DeckLink colorspace flag → container primaries (bt.2020/709/601)
          - gamma:       DeckLink dynamic range flag → TRC (pq/hlg/bt.1886)
          - colormatrix: derived from colorspace flag

        Deliberately NOT overriding:
          - Mastering display primaries (Rx/Ry Gx/Gy Bx/By Wx/Wy)
          - MaxCLL / MaxFALL / mastering luminance
          These come from SMPTE ST 2086 HDMI metadata in the DeckLink frame callbacks
          (IDeckLinkVideoFrameMetadataExtensions), which FFmpeg extracts automatically
          as AVMasteringDisplayMetadata / AVContentLightMetadata side data and mpv
          propagates to pl_hdr_metadata.  Overriding them here would discard the
          per-frame values FFmpeg correctly detected (e.g. mastered-on-P3 content in
          a BT.2020 container would wrongly get BT.2020 mastering primaries).

        Returns empty string for SDR Rec709 (no override needed).
        """
        if self.dynamic_range == 0 and self.colorspace <= 1:
            # SDR Rec601/Rec709 — let libplacebo handle natively, no override needed
            return ""

        cs  = self.COLORSPACE.get(self.colorspace, "bt.709")
        # BT.2020+SDR is DeckLink's way of signalling Dolby Vision (can't set the DV flag)
        gma = "pq" if self.is_likely_dolby_vision() else self.GAMMA.get(self.dynamic_range, "bt.1886")
        mat = self.MATRIX.get(self.colorspace, "bt.709")

        return (
            f"format=colorlevels=limited"
            f":primaries={cs}"
            f":gamma={gma}"
            f":colormatrix={mat}"
            f":chroma-location=mpeg2/4/h264"
            # mastering display primaries, MaxCLL, MaxFALL intentionally omitted —
            # extracted per-frame by FFmpeg from IDeckLinkVideoFrameMetadataExtensions
        )

    def __repr__(self) -> str:
        cs  = self.COLORSPACE.get(self.colorspace, "?")
        gma = self.GAMMA.get(self.dynamic_range, "?")
        ch  = {1: "RGB444", 0: "YCbCr422", -1: "unknown"}.get(self.chroma, "?")
        return (f"SignalInfo(locked={self.locked}, cs={cs}, gamma={gma}, "
                f"depth={self.pixel_depth}bit, chroma={ch})")


class _DLL:
    """Thin ctypes wrapper, loaded once."""
    _instance: Optional["_DLL"] = None

    _MAX_DEVS = 16

    def __init__(self, path: str) -> None:
        self._lib = ctypes.CDLL(path)
        self._lib.vf_dl_open.restype  = ctypes.c_int
        self._lib.vf_dl_open.argtypes = [ctypes.c_char_p]
        self._lib.vf_dl_signal_locked.restype  = ctypes.c_int
        self._lib.vf_dl_signal_locked.argtypes = []
        self._lib.vf_dl_get_mode.restype  = ctypes.c_int
        self._lib.vf_dl_get_mode.argtypes = []
        self._lib.vf_dl_get_dynamic_range.restype  = ctypes.c_int
        self._lib.vf_dl_get_dynamic_range.argtypes = []
        self._lib.vf_dl_get_signal_info.restype  = ctypes.c_int
        self._lib.vf_dl_get_signal_info.argtypes = [ctypes.POINTER(_SignalInfoC)]
        self._lib.vf_dl_enumerate_devices.restype  = ctypes.c_int
        NamesArray64 = (ctypes.c_char * 64) * self._MAX_DEVS
        self._lib.vf_dl_enumerate_devices.argtypes = [
            NamesArray64, ctypes.POINTER(ctypes.c_int), ctypes.c_int
        ]
        # poll_all_ports — URL array uses 128 chars
        NamesArray128 = (ctypes.c_char * 128) * self._MAX_DEVS
        self._lib.vf_dl_poll_all_ports.restype  = ctypes.c_int
        self._lib.vf_dl_poll_all_ports.argtypes = [
            NamesArray128,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self._lib.vf_dl_close.restype  = None
        self._lib.vf_dl_close.argtypes = []

    @classmethod
    def load(cls) -> Optional["_DLL"]:
        if cls._instance:
            return cls._instance
        if sys.platform != "win32":
            return None   # Linux handles signal loss via engine ENDED state
        path = _find_dll()
        if not path:
            return None
        try:
            cls._instance = cls(path)
            return cls._instance
        except OSError:
            return None


class DeviceInfo:
    """A DeckLink device with its clean name and port URLs."""
    def __init__(self, display_name: str, num_ports: int) -> None:
        self.display_name = display_name
        self.num_ports = num_ports

    def port_urls(self) -> list[str]:
        """Return decklink:// URL(s) for this device."""
        if self.num_ports == 1:
            return [f"decklink://{self.display_name}"]
        return [f"decklink://{self.display_name}@{i}" for i in range(self.num_ports)]

    def __repr__(self) -> str:
        return f"DeviceInfo({self.display_name!r}, ports={self.num_ports})"


class PortStatus:
    """Signal status for one physical input port."""
    DR_LABELS = {0: "SDR", 1: "HDR PQ", 2: "HDR HLG", -1: ""}

    def __init__(self, url: str, locked: int, dr: int) -> None:
        self.url    = url
        self.locked = locked == 1   # True = signal present
        self.unknown = locked < 0  # True = couldn't query (sub-device)
        self.dynamic_range = dr    # 0=SDR 1=PQ 2=HLG -1=unknown

    @property
    def dr_label(self) -> str:
        return self.DR_LABELS.get(self.dynamic_range, "")

    def status_icon(self) -> str:
        if self.unknown:
            return "○"
        return "🔒" if self.locked else "○"

    def status_color(self) -> str:
        if self.locked:
            return "#4caf50" if self.dynamic_range > 0 else "#ffffff"
        return "#555555"

    def __repr__(self) -> str:
        return f"PortStatus({self.url!r}, locked={self.locked}, dr={self.dr_label})"


def poll_all_ports() -> list[PortStatus]:
    """
    Poll signal status for ALL ports across ALL DeckLink devices.
    Read-only — safe to call while mpv holds one of the ports.
    Returns empty list if DLL not available.
    """
    dll = _DLL.load()
    if not dll:
        return []
    MAX = _DLL._MAX_DEVS
    NamesArray128 = (ctypes.c_char * 128) * MAX
    urls    = NamesArray128()
    locked  = (ctypes.c_int * MAX)()
    dr      = (ctypes.c_int * MAX)()
    count = dll._lib.vf_dl_poll_all_ports(urls, locked, dr, MAX)
    result = []
    for i in range(count):
        url = urls[i].value.decode("utf-8", errors="replace").strip()
        if url:
            result.append(PortStatus(url, int(locked[i]), int(dr[i])))
    return result


def enumerate_devices() -> list[DeviceInfo]:
    """
    Enumerate all DeckLink devices via the SDK.
    Returns empty list if DLL not available or no devices found.
    Works without exclusive device lock — safe to call anytime.
    """
    dll = _DLL.load()
    if not dll:
        return []
    MAX = _DLL._MAX_DEVS
    NamesArray = (ctypes.c_char * 64) * MAX
    names = NamesArray()
    ports = (ctypes.c_int * MAX)()
    count = dll._lib.vf_dl_enumerate_devices(names, ports, MAX)
    result = []
    for i in range(count):
        name = names[i].value.decode("utf-8", errors="replace").strip()
        if name:
            result.append(DeviceInfo(name, int(ports[i])))
    return result


class DeckLinkMonitor(QObject):
    """
    Signal facts for the UI — a CONSUMER, not a measurer (2026-09-21).

    It used to poll the device itself every 500 ms AND serve every
    get_signal_info()/is_signal_locked() call straight from the DLL. Both ran on
    the Qt main thread with no budget, so a slow IDeckLinkStatus read (observed at
    2516 ms) froze the UI — and it meant two components measured the same card at
    once, each with its own cache and its own idea of what changed.

    Now the ENGINE is the only measurer: its native monitor owns the device and
    publishes settled facts into the s3_stats JSON. The UI pushes those in via
    update_facts(), and everything here reads the local cache. No timer, no
    vf_dl_open, no device reads on the UI thread.

    Device ENUMERATION still uses the DLL (enumerate_devices / poll_all_ports):
    that is a one-shot setup-time query, not runtime measurement.
    """
    signal_locked        = pyqtSignal(bool)    # True=present False=lost
    format_changed       = pyqtSignal(int)     # new mode hash
    dynamic_range_changed = pyqtSignal(int)    # 0=SDR 1=HDR

    # Platform-independent availability
    available = sys.platform == "win32"

    def __init__(self, device_name: str = "", poll_ms: int = 500,
                 parent=None) -> None:
        super().__init__(parent)
        self._device  = device_name
        self._dll     = _DLL.load()
        self._opened  = False
        self._last_locked = None
        self._last_mode   = None
        self._last_dr     = None
        self._last_cs     = None  # colorspace — needed to detect DV<->SDR switches
        self._cached: Optional[SignalInfo] = None   # facts pushed by the engine

        # Deliberately NO QTimer: this class no longer polls the device. The
        # engine's native monitor is the single measurer; see the class docstring.
        self._poll_ms = poll_ms   # kept for API compatibility

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Attach to the engine's signal facts. Never opens the device.

        Was: vf_dl_open + start a 500 ms poll timer. Both now belong to the
        engine's native monitor — opening the same card from here as well was the
        second measurement path this class no longer has.
        """
        self._opened = True
        self._cached = self._cached or None
        # Reset edge state so the first pushed fact is treated as a change.
        self._last_locked = None
        self._last_mode   = None
        self._last_dr     = None
        self._last_cs     = None
        return True

    def stop(self) -> None:
        """Detach. Does NOT close the device — we never opened it."""
        self._opened = False

    def update_facts(self, facts: dict) -> None:
        """Push the engine's signal facts in (from the s3_stats JSON).

        This is the single source of truth now. Called from _on_s3_status on the
        Qt thread; cheap — it only stores and emits on an edge.
        """
        if not isinstance(facts, dict):
            return
        # Key names come from MpcPlayer::GetUiStatusJson's "signal" block.
        locked = bool(facts.get("locked"))
        info = SignalInfo.from_facts(
            colorspace=facts.get("cs", 1),
            dynamic_range=facts.get("dr", 0),
            pixel_depth=facts.get("depth", 8),
            chroma=facts.get("chroma", -1),
            locked=locked,
        )
        self._cached = info

        # FIRST reading is recorded, never emitted — the same rule the old
        # device poll followed ("skip initial state" / "first poll — just
        # record, don't emit"). Emitting it here was a real bug: the first fact
        # arrives while acquisition is still running, and a format/dr edge
        # drives _vp_restart_capture, which restarts the acquisition overlay,
        # which resets this edge state — so the next poll emitted the same edge
        # again and the overlay looped forever over a perfectly good picture.
        cs = info.colorspace
        dr = info.dynamic_range

        if self._last_locked is None:
            self._last_locked = locked
            self._last_cs = cs
            self._last_dr = dr
            return

        if locked != self._last_locked:
            self._last_locked = locked
            _log.info(f"signal_locked changed -> {locked}")
            self.signal_locked.emit(locked)

        if cs != self._last_cs:
            self._last_cs = cs
            _log.info(f"format changed: cs -> {cs}")
            self.format_changed.emit(int(cs))

        if dr != self._last_dr:
            self._last_dr = dr
            self.dynamic_range_changed.emit(int(dr))

    def is_signal_locked(self) -> bool:
        """Current signal lock state, from the engine's last pushed fact."""
        return bool(self._cached.locked) if self._cached else False

    def get_signal_info(self) -> Optional["SignalInfo"]:
        """The engine's latest signal fact — never a device read."""
        if not self._opened:
            return None
        return self._cached

    # (_poll lived here: three to four synchronous DLL reads per 500 ms tick, on
    # the Qt main thread, with no budget. Deleted — the engine is the measurer
    # now, and update_facts() is how the UI learns what the wire is doing.)

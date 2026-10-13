"""
Calibration measurement session (HDR->SDR LUT raw material).

Plays the authored 4K HDR10 patch clip through the NORMAL playback path and, per
patch, saves one rendered frame + measurement. Nothing here runs unless the user
presses the "Calibrate colour" button — normal playback is untouched.

The session is driven by a step QTimer on the Qt main thread (s3_cmd must stay on
the calling thread). Every tick force-refreshes the engine's status JSON
(`poll_properties`), so the position read is fresh rather than up to one poll
old. Grabs land in the WINDOW inside each 1 s patch — after the tone-map anchor
has settled past the scene-change and clear of the next boundary. A single
warm-up pass waits out the known auto re-open (graph rebuild restarts the clock),
then seeks to 0 so every measurement is taken on the post-settings graph.

Deterministic proof: every grab/measurement logs a `calibrate-row:` line, and the
final measurements.csv / manifest.json carry the renderer's own status echo
(media/hdr/ml/out) for each patch.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

log = logging.getLogger("unplugged.calibrate")

CALIBRATE_VIDEO = r"C:\Users\satee\Pictures\calibrate\calibrate.mkv"
CALIBRATE_CSV = Path(CALIBRATE_VIDEO).parent / "patches.csv"

POLL_MS = 250                # session tick; 450 ms window still guarantees a hit
WARMUP_POS = 1.5             # wait out the auto re-open before seeking clean
SEEK_SETTLE_POS = 0.6        # after seek(0), position must return below this
WINDOW = (0.50, 0.95)        # in-patch capture window, seconds after patch start
GRAB_MAX_CONSEC_FAIL = 8     # consecutive grab failures -> cancel
OVERSHOOT_RETRY_PATCHES = 2  # re-seek attempts when a patch window was missed
TOTAL_DEADLINE_S = 35.0
CROP_FRACTION = 0.08         # measured centre square, side fraction of the frame
PATCH_COUNT = 16
PATCH_SEC = 1.0

# Fallback expected table: (idx, name, r, g, b) — authored LINEAR RGB in NITS,
# the same values gen_patches.py writes. Used only when patches.csv is missing.
DEFAULT_EXPECTED = [
    (0,  "GRAY-0.005", 0.005, 0.005, 0.005),
    (1,  "GRAY-10",    10,    10,    10),
    (2,  "GRAY-25",    25,    25,    25),
    (3,  "GRAY-50",    50,    50,    50),
    (4,  "GRAY-85",    85,    85,    85),
    (5,  "GRAY-120",   120,   120,   120),
    (6,  "GRAY-200",   200,   200,   200),
    (7,  "GRAY-400",   400,   400,   400),
    (8,  "GRAY-1000",  1000,  1000,  1000),
    (9,  "RED-200",    200,   0,     0),
    (10, "GREEN-200",  0,     200,   0),
    (11, "BLUE-200",   0,     0,     200),
    (12, "CYAN-200",   0,     200,   200),
    (13, "MAGENTA-200",200,   0,     200),
    (14, "YELLOW-200", 200,   200,   0),
    (15, "WHITE-1000", 1000,  1000,  1000),
]


def load_expected_table(csv_path: str | Path) -> Optional[list[dict]]:
    """Parse idx,name,r,g,b from the generator's patches.csv.

    Returns None (caller falls back to DEFAULT_EXPECTED) if the file is missing
    or does not line up with the 16-patch clip — never a silent partial table.
    """
    try:
        text = Path(csv_path).read_text(encoding="utf-8").strip().splitlines()
        rows = []
        for line in text[1:]:               # header: idx,name,r,g,b
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            rows.append({"idx": int(parts[0]), "name": parts[1],
                         "r": float(parts[2]), "g": float(parts[3]), "b": float(parts[4])})
        if rows and all(d["idx"] == i for i, d in enumerate(rows)):
            log.info("calibrate-row: expected table loaded from %s (%d patches)",
                     csv_path, len(rows))
            return rows
    except (OSError, ValueError, IndexError) as e:
        log.warning("calibrate-row: expected table %s unreadable — using embedded (%s)",
                    csv_path, e)
    return None


def _default_expected() -> list[dict]:
    return [{"idx": i, "name": n, "r": r, "g": g, "b": b}
            for (i, n, r, g, b) in DEFAULT_EXPECTED]


def measure_center_rgb(img: QImage, fraction: float = CROP_FRACTION) -> dict:
    """Mean RGB (0-255) + per-channel stddev + luma over the centre square.

    stddev is the boundary canary: a grab caught mid-transition shows a stddev an
    order of magnitude above a flat patch, so a contaminated sample is visible in
    the manifest rather than silently measured.
    """
    rgb = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = rgb.width(), rgb.height()
    side = max(4, round(min(w, h) * fraction))
    x0, y0 = (w - side) // 2, (h - side) // 2
    try:                               # fast path: one buffer, direct index
        from PyQt6 import sip          # noqa: PLC0415
        buf = rgb.constBits().asarray(w * h * 3) if hasattr(rgb.constBits(), "asarray") else None
    except Exception:                  # noqa: BLE001
        buf = None
    if buf is not None:
        def samp(o):
            return buf[o], buf[o + 1], buf[o + 2]          # R,G,B (RGB888 rows)
    else:
        def samp(o):                                        # slow fallback
            c = rgb.pixelColor(o % w, o // w)
            return c.red(), c.green(), c.blue()
    sr = sg = sb = sr2 = sg2 = sb2 = 0.0
    n = 0
    for y in range(y0, y0 + side):
        base = y * w * 3 + x0 * 3
        for x in range(side):
            r_, g_, b_ = samp(base + x * 3)
            sr += r_; sg += g_; sb += b_
            sr2 += r_*r_; sg2 += g_*g_; sb2 += b_*b_
            n += 1
    n = n or 1
    mr, mg, mb = sr/n, sg/n, sb/n
    vr = max(0.0, sr2/n - mr*mr); vg = max(0.0, sg2/n - mg*mg); vb = max(0.0, sb2/n - mb*mb)
    return {"r": round(mr, 2), "g": round(mg, 2), "b": round(mb, 2),
            "stddev": round(max(vr, vg, vb) ** 0.5, 3),
            "luma": round(0.114*mb + 0.587*mg + 0.299*mr, 2)}


class CalibrationSession(QObject):
    """One measurement pass over the 16-patch clip. Started by MainWindow."""

    progress = pyqtSignal(int, int)      # done, total
    message  = pyqtSignal(str)           # one-line progress text
    status   = pyqtSignal(str)           # stage name
    finished = pyqtSignal(bool, str)     # ok, summary

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._step)
        self._state = "idle"             # idle|WAIT_STABLE|SEEK_SETTLING|ACTIVE|FINALIZE|CANCELLED
        self._t0 = 0.0
        self._last_j: dict = {}
        self._waiting = 0
        self._patch: dict = {}           # idx -> record
        self._retries: list[int] = []
        self._grabfails = 0
        self._next_patch = 0
        self._out_dir: Optional[Path] = None
        self._video = ""
        self._expected: list[dict] = []
        self._temp: Optional[str] = None
        self._profile_name = ""

    # -- lifecycle --------------------------------------------------------
    def is_active(self) -> bool:
        return self._state not in ("idle", "FINALIZE", "CANCELLED")

    def start(self, engine, video_path: str, out_dir: Path,
              expected: Optional[list[dict]] = None,
              profile_name: str = "",
              patch_count: int = PATCH_COUNT,
              patch_sec: float = PATCH_SEC) -> None:
        if self.is_active():
            return
        self._engine = engine
        self._video = video_path
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._expected = expected or _default_expected()
        self._profile_name = profile_name
        self._count = int(patch_count)
        self._sec = float(patch_sec)
        self._retries = [0] * self._count
        self._next_patch = 0
        self._grabfails = 0
        self._temp = None
        self._patch = {}
        self._last_j = {}
        self._waiting = 0
        # Cache the engine's status blob on the Qt thread (fresh each poll).
        try:
            self._engine.s3_status.connect(self._on_status)
        except Exception as e:   # noqa: BLE001
            log.warning("calibrate: s3_status hook failed (%s) — status echo will be stale", e)
        self._state = "WAIT_STABLE"
        self._t0 = time.monotonic()
        # Session deadline scales with the clip: warm-up + a full pass + margin.
        self._deadline = 6.0 + self._count * self._sec + 12.0
        self._timer.start()
        log.info("calibrate: session started %s -> %s (%d expected)",
                 video_path, self._out_dir, len(self._expected))

    def cancel(self, reason: str = "cancelled") -> None:
        if self._state in ("FINALIZE", "CANCELLED"):
            return
        self._state = "CANCELLED"
        self._timer.stop()
        self._detach()
        self._cleanup()
        log.info("calibrate: cancelled (%s)", reason)
        self.finished.emit(False, reason)

    def _detach(self) -> None:
        if self._engine is not None:
            try:
                self._engine.s3_status.disconnect(self._on_status)
            except (TypeError, RuntimeError):
                pass

    def _cleanup(self) -> None:
        if self._temp:
            try:
                os.remove(self._temp)
            except OSError:
                pass
            self._temp = None

    def _on_status(self, j: dict) -> None:
        self._last_j = j

    # -- the state machine -------------------------------------------------
    def _step(self) -> None:
        if self._state not in ("WAIT_STABLE", "SEEK_SETTLING", "ACTIVE"):
            return
        if self._engine is None:
            self.cancel("engine gone")
            return
        # Force a fresh status blob each tick, so pos read here is current.
        try:
            self._engine.poll_properties([])
        except Exception as e:   # noqa: BLE001
            self.cancel(f"poll failed: {e}")
            return
        j = self._last_j
        pos = j.get("pos", 0) / 1e7
        state = j.get("state", "")
        dur = j.get("dur", 0) / 1e7
        media = j.get("media") or {}

        if time.monotonic() - self._t0 > getattr(self, "_deadline", TOTAL_DEADLINE_S):
            self.cancel("deadline exceeded")
            return

        if self._state == "WAIT_STABLE":
            if state not in ("playing", "paused"):
                return                      # still opening
            if state == "paused":
                self.cancel(f"playback stuck paused (pos={pos:.2f})")
                return
            if pos >= WARMUP_POS and media.get("valid"):
                self._engine.seek(0.0)
                self._state = "SEEK_SETTLING"
                self._waiting = 0
                self.status.emit("SEEK_SETTLING")
                log.info("calibrate-row: warm-up done (pos=%.2f) — seek(0) issued", pos)
            return

        if self._state == "SEEK_SETTLING":
            if pos <= SEEK_SETTLE_POS:
                self._state = "ACTIVE"
                self.status.emit("ACTIVE")
                log.info("calibrate-row: active (pos=%.2f)", pos)
            else:
                self._waiting += 1
                if self._waiting > 4:        # ~1 s without landing
                    self._engine.seek(0.0)
                    if self._waiting > 10:
                        self.cancel(f"seek did not land (pos={pos:.2f})")
            return

        # ACTIVE
        if abs(dur - self._count * self._sec) > 1.0:
            self.cancel(f"file changed under session (dur={dur:.1f}s)")
            return
        if state != "playing":
            self.cancel(f"engine left playing (state={state})")
            return
        self._active_step(pos)

    def _active_step(self, pos: float) -> None:
        i = self._next_patch
        if i < self._count and i not in self._patch:
            lo = i * self._sec + WINDOW[0]
            hi = i * self._sec + WINDOW[1]
            if lo <= pos < hi:
                self._grab_patch(i)
                return
            if pos >= i * self._sec + self._sec - 0.01:   # window missed
                if self._retries[i] < OVERSHOOT_RETRY_PATCHES:
                    self._retries[i] += 1
                    self._engine.seek(i * self._sec + 0.05)
                    self.status.emit(f"retry-patch-{i}")
                    log.info("calibrate-row: patch %d overshot (pos=%.2f) — re-seek %d",
                             i, pos, self._retries[i])
                else:
                    self._patch[i] = {"idx": i, "name": f"PATCH-{i}",
                                      "file": None, "status": "missed",
                                      "measured": {"pos_sec": pos}, "retries": self._retries[i]}
                    log.warning("calibrate-row: patch %d missed (pos=%.2f, retries exhausted)", i, pos)
                    self.progress.emit(len(self._patch), self._count)
                    self._next_patch += 1
            return
        if pos >= self._count * self._sec - 0.01:
            self._finalize()

    # -- measurement -------------------------------------------------------
    def _grab_patch(self, i: int) -> None:
        if self._engine is None:
            return
        fd, tmp = tempfile.mkstemp(suffix=".bmp")
        os.close(fd)
        self._temp = tmp
        rc = self._engine.capture_frame(tmp)
        if rc != 0:
            self._cleanup()
            self._grabfails += 1
            if self._grabfails >= GRAB_MAX_CONSEC_FAIL:
                self.cancel(f"grab failed {GRAB_MAX_CONSEC_FAIL}x (hr=0x{rc:08X})")
            return                               # retry same patch next tick (still in window)
        self._grabfails = 0
        img = QImage(tmp)
        self._cleanup()
        if img.isNull():
            self.cancel("grab returned no frame image")
            return
        j = self._last_j
        hdr = j.get("hdr") or {}
        name = self._expected[i]["name"] if i < len(self._expected) else f"PATCH-{i}"
        fname = f"patch_{i:02d}.png"
        if not img.save(str(self._out_dir / fname), "PNG"):
            self.cancel(f"failed to write {fname}")
            return
        m = measure_center_rgb(img)
        self._patch[i] = {
            "idx": i, "name": name, "file": fname,
            "auth": self._expected[i],
            "measured": dict(m, pos_sec=round(j.get("pos", 0) / 1e7, 3),
                             title_peak_nits=hdr.get("titlePeak", 0.0)),
            "engine": {"media": j.get("media") or {}, "hdr": hdr},
            "retries": self._retries[i], "status": "ok",
        }
        log.info("calibrate-row: patch %02d %-14s -> %s  rgb=(%.2f, %.2f, %.2f) "
                 "luma=%.2f stddev=%.3f titlePeak=%s pos=%.2fs",
                 i, name, fname, m["r"], m["g"], m["b"], m["luma"], m["stddev"],
                 hdr.get("titlePeak"), j.get("pos", 0) / 1e7)
        self.progress.emit(len(self._patch), self._count)
        self.message.emit(f"patch {i+1}/{self._count} · {name}")
        self._next_patch = i + 1

    # -- output -------------------------------------------------------------
    def _finalize(self) -> None:
        if self._state == "FINALIZE":
            return
        self._state = "FINALIZE"
        self._timer.stop()
        self._detach()
        try:
            self._engine.pause(True)
        except Exception as e:   # noqa: BLE001
            log.warning("calibrate: pause at end failed (%s)", e)
        ok = sum(1 for p in self._patch.values() if p.get("status") == "ok")
        missed = self._count - ok
        self._write_outputs()
        summary = (f"saved {ok}/{self._count} patches to {self._out_dir}"
                   + ("" if missed == 0 else f" — {missed} missed"))
        log.info("calibrate: done ok=%d missed=%d -> %s", ok, missed, self._out_dir)
        self.finished.emit(missed == 0, summary)

    def _write_outputs(self) -> None:
        if self._out_dir is None:
            return
        rows = sorted(self._patch.values(), key=lambda p: p["idx"])
        # measurements.csv
        with open(self._out_dir / "measurements.csv", "w", encoding="utf-8-sig") as f:
            f.write("idx,name,r_auth,g_auth,b_auth,meas_r,meas_g,meas_b,"
                    "meas_luma,meas_stddev,title_peak_nits,pos_sec,status,retries\n")
            for p in rows:
                a = p.get("auth") or {}
                m = p.get("measured") or {}
                f.write(f"{p['idx']},{p['name']},{a.get('r','')},{a.get('g','')},{a.get('b','')},"
                        f"{m.get('r','')},{m.get('g','')},{m.get('b','')},"
                        f"{m.get('luma','')},{m.get('stddev','')},"
                        f"{m.get('title_peak_nits','')},{m.get('pos_sec','')},"
                        f"{p.get('status','')},{p.get('retries','')}\n")
        # manifest.json
        (j, last) = self._last_j, {}
        last = {"media": j.get("media") or {}, "hdr": j.get("hdr") or {},
                "ml": j.get("ml") or {}, "out": j.get("out") or {}}
        manifest = {
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "video": {"path": self._video, "duration_sec": self._count * self._sec,
                      "patches": self._count,
                      "expected_source": ("patches.csv" if self._expected is not _default_expected()
                                          else "embedded")},
            "parameters": {"poll_ms": POLL_MS, "warmup_pos_sec": WARMUP_POS,
                           "capture_window": list(WINDOW), "crop_fraction": CROP_FRACTION},
            "engine": last,
            "profile": {"name": self._profile_name},
            "patches": rows,
            "result": {"ok": sum(1 for p in rows if p.get("status") == "ok"),
                       "missed": sum(1 for p in rows if p.get("status") == "missed")},
        }
        with open(self._out_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        log.info("calibrate-row: wrote measurements.csv + manifest.json in %s", self._out_dir)
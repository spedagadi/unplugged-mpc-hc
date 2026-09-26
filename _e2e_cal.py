"""End-to-end calibration run: real S3Engine + CalibrationSession, no UI.

Drives the same pieces the button drives — engine.open/play, per-patch
capture, measurements — in a hidden window (the renderer needs an HWND).
Logs go to stderr and the session's calibrate-row lines to stdout.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent  # noqa: F401
from PyQt6.QtWidgets import QApplication, QMainWindow

from mpvprocessor.core.s3_engine import S3Engine            # noqa: E402
from mpvprocessor.core.calibrate import (                   # noqa: E402
    CalibrationSession, load_expected_table, _default_expected,
)

app = QApplication(sys.argv)
win = QMainWindow()
win.setGeometry(0, 0, 640, 360)
win.hide()

out_root = r"C:\Users\satee\Pictures\calibrate"
args = sys.argv[1:]
video = args[0] if len(args) > 0 else r"C:\Users\satee\Pictures\calibrate\calibrate.mkv"
csvp  = args[1] if len(args) > 1 else r"C:\Users\satee\Pictures\calibrate\patches.csv"
out   = Path(args[2]) if len(args) > 2 else Path(out_root) / "e2e_out"
count = int(args[3]) if len(args) > 3 else 16
psec  = float(args[4]) if len(args) > 4 else 1.0
sdr_nits = int(args[5]) if len(args) > 5 else None   # push this sdrNits before the pass
out.mkdir(parents=True, exist_ok=True)

engine = S3Engine()
rc = engine.initialise("", int(win.winId()))
print(f"[e2e] initialise rc={rc} attached={engine._attached}", flush=True)

expected = load_expected_table(csvp) or _default_expected()
expected = (expected + [{"idx": i, "name": f"PATCH-{i}", "r": 0.0, "g": 0.0, "b": 0.0}
                        for i in range(len(expected), count)])[:count]
print(f"[e2e] expected rows: {len(expected)} (count={count} sec={psec})", flush=True)

session = CalibrationSession()
session.progress.connect(lambda d, t: print(f"[e2e] progress {d}/{t}", flush=True))
session.message.connect(lambda m: print(f"[e2e] msg: {m}", flush=True))
session.status.connect(lambda s: print(f"[e2e] status: {s}", flush=True))
result = {}

def done(ok: bool, summary: str) -> None:
    result["ok"] = ok
    result["summary"] = summary
    print(f"[e2e] DONE ok={ok}: {summary}", flush=True)
    app.quit()

session.finished.connect(done)

# Watchdog: never hang the harness (count*sec + warm-up + margin).
QTimer.singleShot(int(7000 + count * psec) * 100 + 20000,
                  lambda: (print("[e2e] WATCHDOG", flush=True), app.quit()))

print(f"[e2e] playing {video}", flush=True)
engine.play(video)
if sdr_nits is not None:
    engine.apply_settings({"hdr": {"sdrNits": sdr_nits, "convSdr": 1}})
    print(f"[e2e] pushed hdr.sdrNits={sdr_nits} convSdr=1", flush=True)
session.start(engine, video, out, expected, profile_name="e2e",
              patch_count=count, patch_sec=psec)
t0 = time.time()
app.exec()
print(f"[e2e] elapsed {time.time()-t0:.1f}s", flush=True)

pngs = sorted(out.glob("patch_*.png")) if out.exists() else []
print(f"[e2e] png files: {len(pngs)} -> {[p.name for p in pngs]}", flush=True)
if (out / "measurements.csv").exists():
    print(f"[e2e] measurements.csv present ({out / 'measurements.csv'})", flush=True)
if (out / "manifest.json").exists():
    print(f"[e2e] manifest.json present", flush=True)
print(f"[e2e] session result={result}", flush=True)
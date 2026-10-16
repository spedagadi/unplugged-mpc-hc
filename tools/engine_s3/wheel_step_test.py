"""One notch == one increment on the nits sliders, and nowhere else.

The track is 132 px, so drag resolution can never be single-nit on a wide range; the
wheel-over-track fine adjust is what makes 174 landable. This drives wheelEvent() by hand
(constructing QWheelEvent and calling the handler, no Qt dispatch needed) and checks:
  * a notch over the track moves an int slider by exactly 1,
  * the value clamps at the range ends instead of wrapping,
  * a notch over the row's LABEL is ignored (so list scrolling still works there).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtCore import QPoint, QPointF, Qt          # noqa: E402
from PyQt6.QtGui import QWheelEvent                   # noqa: E402
from PyQt6.QtWidgets import QApplication              # noqa: E402

app = QApplication([])

from mpvprocessor.ui.s3shell_panel import S3ShellPanel  # noqa: E402

panel = S3ShellPanel()
panel.group = 2
panel._rebuild()

row = panel._row("hdr.maxNits")
lo, hi = panel._slider_span(row)
track_x = (lo + hi) // 2
label_x = 100                      # left of the track: the label column
row_y = None
for is_header, _t, idx, y, _h in panel._layout:
    if not is_header and panel.rows[idx] is row:
        row_y = y + 20
assert row_y is not None, "maxNits row not in the HDR layout"


def notch(x: int, y: int, dy: int) -> None:
    ev = QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    panel.wheelEvent(ev)


fails = []
row.val = 174.0
notch(track_x, row_y, +120)
print(f"174 + one notch over track -> {row.val:g}")
if row.val != 175.0:
    fails.append(f"up-notch gave {row.val:g}, expected 175")
notch(track_x, row_y, -120)
notch(track_x, row_y, -120)
print(f"then two down-notches      -> {row.val:g}")
if row.val != 173.0:
    fails.append(f"down-notch gave {row.val:g}, expected 173")

notch(label_x, row_y, +120)
print(f"notch over the label       -> {row.val:g} (must be unchanged)")
if row.val != 173.0:
    fails.append("wheel over the label changed the value; list scroll would misfire")

row.val = row.max
notch(track_x, row_y, +120)
print(f"at max, one more up-notch  -> {row.val:g} (must clamp at {row.max:g})")
if row.val != row.max:
    fails.append(f"clamped wrong at top: {row.val:g}")

row.val = row.min
notch(track_x, row_y, -120)
print(f"at min, one more down-notch-> {row.val:g} (must clamp at {row.min:g})")
if row.val != row.min:
    fails.append(f"clamped wrong at bottom: {row.val:g}")

sdr = panel._row("hdr.sdrNits")
print(f"sdrNits row present, range {sdr.min:g}..{sdr.max:g}")

print("\nRESULT:", "FAIL — " + "; ".join(fails) if fails else "PASS — one notch, one increment")
sys.exit(1 if fails else 0)

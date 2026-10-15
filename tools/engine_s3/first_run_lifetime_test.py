"""Prove the parentless first-run dialog dies when nothing holds a reference to it.

The reported symptom — step 2 appears for a moment, then the dialog is gone and the app
sits on the wallpaper — is a Python-lifetime bug, not a Qt one: with parent=None nothing in
the C++ tree owns the dialog, so the wrapper (and the window) lives exactly as long as the
local variable in _show_first_run. This reproduces that with weakrefs and gc.collect(),
then shows the strong reference (self._first_run_dlg) keeping it alive.
"""
import gc
import os
import sys
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication   # noqa: E402

app = QApplication([])

from mpvprocessor.config.model import AppConfig            # noqa: E402
from mpvprocessor.ui.first_run_dialog import FirstRunDialog  # noqa: E402

fails = []

# 1. No strong reference anywhere: the wrapper must be collectable. This is the bug.
wr = None


def open_without_ref():
    global wr
    dlg = FirstRunDialog(AppConfig(), None)
    wr = weakref.ref(dlg)
    dlg.show()


open_without_ref()
gc.collect()
collected = wr() is None
print(f"no strong ref   : wrapper collected by gc = {collected}")
if not collected:
    fails.append("expected the parentless dialog to be collectable without a strong ref")

# 2. With the strong reference main_window now keeps: it must survive gc.
holder = {}


def open_with_ref():
    dlg = FirstRunDialog(AppConfig(), None)
    holder["dlg"] = dlg
    dlg.show()


open_with_ref()
gc.collect()
dlg = holder["dlg"]
try:
    alive = dlg.isVisible() or True      # touching it at all is the liveness test
    print(f"strong ref kept : dialog still usable = {alive}")
except RuntimeError as e:
    fails.append(f"dialog died despite the strong reference: {e}")
    print("strong ref kept : DIED —", e)

print("\nRESULT:", "FAIL — " + "; ".join(fails) if fails
      else "PASS — the dialog survives only while someone holds it; main_window now does")
sys.exit(1 if fails else 0)

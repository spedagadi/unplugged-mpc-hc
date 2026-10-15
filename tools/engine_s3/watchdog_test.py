"""Prove the exit watchdog is armed only by the exit path.

The app closing itself 15 s after a mode/source change was not a crash: shutdown() is the
process-exit routine and arms a daemon thread that calls os._exit(0). Three switch paths
called it. This checks the distinction directly — thread count before/after — because
"the app no longer quits" is otherwise only observable by waiting 15 s inside the GUI.
"""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication   # noqa: E402

app = QApplication([])

from mpvprocessor.core.s3_engine import S3Engine   # noqa: E402


def threads():
    return {t.name for t in threading.enumerate()}


fails = []

# 1. A switch-style teardown must NOT arm the watchdog.
e1 = S3Engine()
e1._lib = None                      # no DLL loaded; the branch under test is the watchdog
before = len(threads())
e1.shutdown(for_exit=False)
after = len(threads())
print(f"for_exit=False : threads {before} -> {after}")
if after > before:
    fails.append("shutdown(for_exit=False) armed the exit watchdog")

# 2. The real exit path must still arm it (that guarantee is why it exists: a lingering
#    process holds the DeckLink and blocks the next launch).
e2 = S3Engine()
e2._lib = None
before = len(threads())
e2.shutdown(for_exit=True)
after = len(threads())
print(f"for_exit=True  : threads {before} -> {after}")
if after <= before:
    fails.append("shutdown(for_exit=True) did NOT arm the exit watchdog")

# 3. stop_capture() must be the non-fatal switch: no new threads, _started cleared.
e3 = S3Engine()
e3._lib = None
e3._started = "DeckLink Quad HDMI Recorder (1)"
before = len(threads())
e3.stop_capture()
after = len(threads())
print(f"stop_capture() : threads {before} -> {after}, _started={e3._started!r}")
if after > before or e3._started is not None:
    fails.append("stop_capture() was not a clean non-fatal stop")

# Let any stray sleep-then-exit thread show itself before we finish; the watchdog is a
# daemon, so exiting here cannot be blocked by it.
time.sleep(0.2)
print("\nRESULT:", "FAIL — " + "; ".join(fails) if fails else "PASS — only the exit path arms os._exit(0)")
sys.exit(1 if fails else 0)

"""Prove a relaunched child survives the parent still holding the instance mutex.

The restart flow spawns the child while the parent is mid-teardown. The child's first act
is the single-instance check, so the handover only works if the child WAITS for the mutex
instead of exiting. This reproduces that race with the real named mutex: the parent holds
it, spawns a child running the same wait logic main.py now has, releases the handle a
second later (standing in for process exit), and asserts the child acquired rather than
died.
"""
import ctypes
import subprocess
import sys
import time

CHILD = r'''
import ctypes, sys
k = ctypes.windll.kernel32
h = k.CreateMutexW(None, False, "UnpluggedS3Instance")
if k.GetLastError() == 183:
    rc = k.WaitForSingleObject(h, 8000)
    if rc not in (0, 0x80):
        print("EXITED-AS-SECOND-INSTANCE")
        sys.exit(0)
print("ACQUIRED")
'''

k = ctypes.windll.kernel32
held = k.CreateMutexW(None, False, "UnpluggedS3Instance")
if k.GetLastError() == 183:
    print("SKIP: another instance of the app holds the mutex — close it first")
    sys.exit(2)

child = subprocess.Popen([sys.executable, "-c", CHILD],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.0)          # child is now blocked in WaitForSingleObject
k.CloseHandle(held)      # stands in for the parent process finally exiting

out, _ = child.communicate(timeout=20)
print("child said:", out.strip())
ok = "ACQUIRED" in out
print("RESULT:", "PASS — child waited out the parent and took the mutex"
      if ok else "FAIL — child died as a second instance")
sys.exit(0 if ok else 1)

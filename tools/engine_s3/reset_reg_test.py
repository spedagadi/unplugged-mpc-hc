"""Plant probe values in both renderer registry keys, call the engine's reset action
through the C ABI, and check in-process whether they are gone. The engine's own log is
not available here (no s3_attach, so MpcPlayer::Log has no sink), which is why the
registry itself is the oracle."""
import ctypes
import os
import sys
import winreg

DLL = r"C:\code\unplugged-mpc-hc\tools\s3engine\s3engine.dll"
FRESH = r"Software\Unplugged\Renderer"
LEGACY = r"Software\MPC-BE Filters\MPC Video Renderer"


def plant(path):
    parent, _, leaf = path.rpartition("\\")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, parent, 0, winreg.KEY_ALL_ACCESS) as p:
        with winreg.CreateKeyEx(p, leaf, 0, winreg.KEY_ALL_ACCESS) as k:
            winreg.SetValueEx(k, "ProbeValue", 0, winreg.REG_DWORD, 1)


def exists(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
            return True
    except OSError:
        return False


plant(FRESH)
plant(LEGACY)
print("planted: fresh =", exists(FRESH), " legacy =", exists(LEGACY))

lib = ctypes.WinDLL(DLL)
lib.s3_cmd.restype = ctypes.c_int
lib.s3_cmd.argtypes = [ctypes.c_char_p]
rc = lib.s3_cmd(b'{"a":"resetrenderer"}')
print("resetrenderer rc =", rc)
print("after: fresh present =", exists(FRESH), " legacy present =", exists(LEGACY))

ok = (not exists(FRESH)) and (not exists(LEGACY))
print("RESULT:", "PASS — both renderer registry keys deleted" if ok
      else "FAIL — a key survived the reset")
sys.exit(0 if ok else 1)

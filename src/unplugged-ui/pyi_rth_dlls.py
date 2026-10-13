"""
PyInstaller runtime hook — runs before any frozen app code.

Adds _internal/ to the Windows DLL search path so ctypes can find the app's
native dependencies (s3engine.dll, decklink_monitor.dll) and their transitive
DLLs, regardless of what %PATH% contains.

This was `pyi_rth_libmpv.py`. The mpv stack is no longer bundled — the engine
layer is s3engine.dll — but the search-path problem it solved is the same, so
the hook stays under a name that matches what it actually does.
"""
import os
import sys

if hasattr(sys, '_MEIPASS') and hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(sys._MEIPASS)
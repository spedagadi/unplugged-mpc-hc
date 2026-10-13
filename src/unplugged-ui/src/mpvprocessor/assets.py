"""Where the app's bundled assets live — one resolver instead of five.

The app used to reach out of its own tree with `Path(__file__).parents[4]`,
which pointed at the *old* repo root (`C:\\code\\unplugged`) and silently
resolved to nothing once the tree moved inside mpc-hc. Everything the app
ships with now lives in-tree under `assets/`, so there is one place to look:

    dev     <app-root>/assets/...            (app-root is the dir holding src/)
    frozen  <exe>/_internal/assets/...       (PyInstaller onedir; sys._MEIPASS)

`sys._MEIPASS` is `_internal` for a onedir build, which is exactly where the
spec file copies `assets/` to.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["asset", "asset_dir"]


def asset_dir() -> Path:
    """The directory holding the bundled assets."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    # src/mpvprocessor/assets.py -> mpvprocessor -> src -> <app-root>
    return Path(__file__).resolve().parents[2] / "assets"


def asset(*parts: str) -> Path:
    """Resolve a path under the assets directory.

    Falls back to `<exe>/_internal/assets/...` when running frozen but with no
    `_MEIPASS` set, which keeps the lookup working for the odd launcher that
    strips it.
    """
    p = asset_dir().joinpath(*parts)
    if p.exists():
        return p
    exe_fallback = Path(sys.executable).parent / "_internal" / "assets"
    return exe_fallback.joinpath(*parts)
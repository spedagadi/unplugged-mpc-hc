"""
WebAnimationView — renders a self-contained HTML fragment (div + embedded <style>)
inside a QWebEngineView with:
  - transparent/black background matching the card
  - play-once mode: all `infinite` animations are replaced with a single forward-fill
  - optional auto-dismiss callback after `duration_ms`

The HTML files from unplugged-brand/animations/ are fragments (no <html>/<head>),
so we wrap them in a minimal host page.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWidgets import QWidget

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False


def _asset_base_url() -> QUrl:
    """Return file:// URL for the animations folder so web fonts can load."""
    from ..assets import asset

    for c in (asset("brand", "animations"),
              Path(sys.executable).parent / "_internal" / "assets" / "brand" / "animations"):
        if c.exists():
            return QUrl.fromLocalFile(str(c) + "/")
    return QUrl("about:blank")


def _play_once(html: str) -> str:
    """Replace `infinite` with `forwards` in all @keyframes animation declarations."""
    return re.sub(r'\binfinite\b', 'forwards', html)


def _wrap_fragment(fragment: str, play_once: bool = True) -> str:
    """Wrap an HTML fragment (div + <style>) in a full page with dark background."""
    if play_once:
        fragment = _play_once(fragment)
    base = _asset_base_url().toString()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: 100%; height: 100%;
    background: transparent;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }}
  /* Card provides the dark bg, border, and rounded corners.
     QWebEngineView is a native widget so border-radius on html/body has no effect —
     we draw the rounded rect inside the page instead.
     padding-bottom compensates for the SVG's ~65px of internal top whitespace
     (cable endpoint is at y=49 of 200-unit viewBox) so the visual content
     lands at the true vertical centre of the card. */
  .anim-card {{
    background: #0e0e10;
    border-radius: 16px;
    border: 1.5px solid rgba(100,100,100,0.7);
    overflow: hidden;
    box-sizing: border-box;
    display: flex; align-items: center; justify-content: center;
    width: 100%; height: 100%;
    padding-bottom: 65px;
  }}
  #stageA, #stageB {{
    min-height: unset !important;
    height: auto !important;
    background: transparent !important;
  }}
</style>
</head>
<body>
<div class="anim-card">
{fragment}
</div>
</body>
</html>"""


class WebAnimationView(QWidget):
    """
    A QWidget that renders an animation HTML fragment via QWebEngineView.
    Falls back to an empty widget if QWebEngineWidgets is not available.
    """

    def __init__(
        self,
        html_path: Path,
        play_once: bool = True,
        on_finished: Optional[Callable] = None,
        duration_ms: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._finished_cb = on_finished
        self._timer: Optional[QTimer] = None

        if not _HAS_WEBENGINE:
            return

        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtGui import QColor

        self._view = QWebEngineView(self)
        # Transparent so the rounded card drawn inside the HTML page is visible
        self._view.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        layout.addWidget(self._view)

        try:
            fragment = html_path.read_text(encoding="utf-8")
        except OSError:
            fragment = "<p style='color:#E8551F;font-family:sans-serif'>Animation not found</p>"

        html = _wrap_fragment(fragment, play_once=play_once)
        base = _asset_base_url()
        self._view.setHtml(html, base)

        if duration_ms > 0 and on_finished:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(duration_ms)
            self._timer.timeout.connect(on_finished)

    def start(self) -> None:
        """Start the auto-dismiss timer (if configured)."""
        if self._timer:
            self._timer.start()

    def stop(self) -> None:
        """Cancel the auto-dismiss timer."""
        if self._timer:
            self._timer.stop()

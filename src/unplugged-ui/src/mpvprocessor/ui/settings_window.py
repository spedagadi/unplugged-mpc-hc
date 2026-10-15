"""
ui/settings_window.py — the single interactive CHROME window.

Design (2026-09-15, bench-verified): widgets inside the main window are NOT
clickable, because the video renderer's window covers the client area for input;
only a real top-level window raised above it receives input, and only a MODAL
one holds that priority — and just one modal can be interactive at a time.

Therefore there is exactly ONE chrome window, hosting every interactive region:

    ┌──────────┬───────────────────────────┬───────────┐
    │  STATUS  │   video shows through     │ SETTINGS  │   frameless,
    │  (left)  │   (transparent middle)    │  (right)  │   translucent, modal
    ├──────────┴───────────────────────────┴───────────┤
    │            transport / control buttons           │
    └──────────────────────────────────────────────────┘

Up shows it (modal over the video); Up again hides it.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QScrollArea

# DIAGNOSTIC A/B (2026-09-15): content-area clicks do not register while the
# rail/tab bar and every other region of this window do. The settings rail is
# the only region hosted inside a container — a QScrollArea — while the status
# rail and both bars are placed directly as children. Flip this to True to
# restore the scroll-area hosting and re-test.
_USE_SCROLL_AREA = False

# Extra clearance above the screen's bottom edge for the transport/control bars.
# The bars sit flush at h - height on a fullscreen borderless window, and on a TV or an
# overscanned monitor the bottom row of pixels is simply not visible — the volume slider
# and the play/seek bar ended up half off the panel the user can see. Both the chrome
# window and the pre-chrome layout in main_window add this, so the two placements agree.
BOTTOM_SAFE_PX = 28


class SettingsWindow(QDialog):
    def __init__(self, app_config, profile, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Dialog |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)                 # required for input priority
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QDialog { background: transparent; }")
        self._status = None
        self._settings = None
        self._settings_scroll_y = 0     # only used when _USE_SCROLL_AREA is off
        self._bars: list = []
        self._rail_left = 300
        self._rail_right = 460
        self._bottom_h = 64
    # ---------------------------------------------------------------
    def adopt(self, status_panel, settings_panel, bars, rail_left: int = 300,
              rail_right: int = 460, top=None) -> None:
        """Take ownership of the shell's panels/bars — this is what makes them
        interactive (they now live in a real window above the video)."""
        self._status = status_panel
        if _USE_SCROLL_AREA:
            # The settings panel is tall (full s3_shell content); wrap it so it
            # scrolls within the rail instead of being clipped.
            self._settings_scroll = QScrollArea(self)
            self._settings_scroll.setWidgetResizable(False)
            self._settings_scroll.setWidget(settings_panel)
            self._settings_scroll.setStyleSheet(
                "QScrollArea { border: none; background: #0E0E10; }"
                "QScrollBar:vertical { width: 8px; background: #0E0E10; }"
                "QScrollBar::handle:vertical { background: #242428; border-radius: 4px; }")
            self._settings = self._settings_scroll
        else:
            # DIAGNOSTIC A: host the panel directly, exactly like the status
            # rail and the bars. The panel keeps its fixed height, so the chrome
            # clips it and this window scrolls it (see wheelEvent).
            self._settings = settings_panel
        self._bars = [b for b in bars if b is not None]
        self._top = top
        self._rail_left = rail_left
        self._rail_right = rail_right
        for w in (self._top, self._status, self._settings, *self._bars):
            if w is None:
                continue
            w.setParent(self)
            w.show()

    def dock(self, host_rect) -> None:
        self.setGeometry(host_rect)
        self._layout_children()

    def _rails_top(self) -> int:
        """Top of the rails — below the status bar strip when there is one.
        StatusBar fixes its own height (44), so measure it rather than assuming
        the 36 requested below."""
        if self._top is None:
            return 0
        return self._top.height() + 4

    def _layout_children(self) -> None:
        r = self.rect()
        w, h = r.width(), r.height()
        bottom_h = self._bottom_h + BOTTOM_SAFE_PX
        # TOP strip (status bar: device/status + minimise/close buttons)
        if self._top is not None:
            self._top.setGeometry(0, 0, w, 36)
            self._top.show()
        rails_top = self._rails_top()
        # Left STATUS rail
        if self._status is not None:
            self._status.setGeometry(0, rails_top, self._rail_left,
                                     h - bottom_h - rails_top)
            self._status.show()
        # Right SETTINGS rail
        if self._settings is not None:
            self._settings_scroll_y = self._clamp_scroll(self._settings_scroll_y)
            self._settings.setGeometry(w - self._rail_right,
                                       rails_top - self._settings_scroll_y,
                                       self._rail_right, h - bottom_h - rails_top)
            self._settings.show()
        # Bottom strip: the CONTROL bar spans full width — its internal stretch
        # pins [Restart · Stop · VP/Media] left and [Preset · Manage · gear]
        # right, exactly mirroring the rails. The play/seek bar sits CENTRED in
        # the gap between them (inactive in VP mode, as expected).
        y = h - bottom_h
        bars = self._bars
        if len(bars) >= 1:
            bars[0].setGeometry(12, y + 6, w - 24, bottom_h - 12)
        if len(bars) >= 2:
            # Use the ACTUAL gap between the control bar's two groups: its
            # internal stretch leaves the middle empty, so measure from the end
            # of the [Restart · Stop · VP/Media] group to the start of the
            # [Preset · Manage] group.
            left_end, right_start = 0, w
            try:
                cb = bars[0]
                if cb.layout() is not None:
                    cb.layout().activate()      # children need real geometry
                mp = getattr(cb, "_mode_mp", None)
                if mp is not None:
                    left_end = 12 + mp.geometry().right() + 10
                from PyQt6.QtWidgets import QLabel
                for lbl in cb.findChildren(QLabel):
                    if lbl.text().strip().startswith("Preset"):
                        right_start = 12 + lbl.geometry().left() - 10
                        break
            except Exception:
                pass
            if right_start - left_end < 300:
                left_end, right_start = 12 + w // 4, w - 12 - w // 4
            bars[1].setGeometry(left_end, y + 6,
                                max(300, right_start - left_end), bottom_h - 12)

    def _clamp_scroll(self, y: int) -> int:
        """Keep the settings panel inside its rail (direct-host mode only)."""
        if self._settings is None:
            return 0
        visible = self.rect().height() - self._bottom_h - self._rails_top()
        overflow = self._settings.height() - visible
        return max(0, min(max(0, overflow), y))

    def wheelEvent(self, event) -> None:       # noqa: N802
        """The panel is taller than the rail and has no scroll container of its
        own in direct-host mode, so this window scrolls it. The panel ignores
        wheel events, which then bubble up to here."""
        if _USE_SCROLL_AREA or self._settings is None:
            return
        dy = event.angleDelta().y()
        if not dy:
            return
        before = self._settings_scroll_y
        self._settings_scroll_y = self._clamp_scroll(before - dy // 3)
        if self._settings_scroll_y != before:
            self._layout_children()
        event.accept()

    def resizeEvent(self, event) -> None:      # noqa: N802
        super().resizeEvent(event)
        self._layout_children()
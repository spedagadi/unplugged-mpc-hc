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

from .help_card import HelpCard, CARD_W
from .help_store import HelpStore

# DIAGNOSTIC A/B (2026-09-15): content-area clicks do not register while the
# rail/tab bar and every other region of this window do. The settings rail is
# the only region hosted inside a container — a QScrollArea — while the status
# rail and both bars are placed directly as children. Flip this to True to
# restore the scroll-area hosting and re-test.
_USE_SCROLL_AREA = False

# Vertical slack kept clear above/below the focused row when the chrome
# auto-scrolls to it — scrolling on every row would feel twitchy from a couch.
ROW_SLACK = 48

# Extra clearance above the screen's bottom edge for the transport/control bars.
# Was 28, added when the two-row playback bar looked half-clipped on an overscanned
# display; with the bar reduced to one row the user asked for it flush to the window
# again, so this is 0. Kept as the single knob rather than deleted: both the chrome window
# and the pre-chrome layout in main_window add it, so raising it later is one line and
# the two placements cannot drift apart.
BOTTOM_SAFE_PX = 0


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
        self._card = None
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
            sig = getattr(settings_panel, "content_changed", None)
            if sig is not None:
                sig.connect(self._on_settings_content_changed)
        # Context help card, pinned left of the settings rail. It follows the
        # panel's focus model (remote keys or hover — one mechanism), so the
        # description of the field the user is ON appears without moving when
        # the settings column scrolls (a bottom-anchored strip vanished off
        # screen on deep tabs — the placement this design replaces).
        if getattr(settings_panel, "row_focused", None) is not None:
            store = HelpStore()
            if store.path is not None:
                self._card = HelpCard(store, settings_panel, parent=self)
                settings_panel.row_focused.connect(self._card.show_for)
                settings_panel.row_updated.connect(self._card.note_value)
            # Second: after the card has re-filled and resized itself, scroll
            # the rail to keep the focused row on screen and re-place the card
            # beside it. Order matters — the card sizes before this positions.
            settings_panel.row_focused.connect(self._on_row_focused)
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
        # The card sits NEXT TO and CENTRED ON the focused row: it travels with
        # the focus. The clamp keeps it inside the visible rail area — on the
        # first and last rows it glides along the edge instead of leaving the
        # screen (the bottom-anchored placement the user reported could do
        # nothing about; centring means it is never further than half a card
        # away from the control it describes).
        if self._card is not None and self._card.isVisibleTo(self):
            ch = self._card.height() or self._card.sizeHint().height()
            rect = None
            if hasattr(self._settings, "focus_row_rect"):
                rect = self._settings.focus_row_rect()
            if rect is not None:
                y = (rails_top - self._settings_scroll_y
                     + rect.center().y() - ch // 2)
            else:
                y = rails_top + 44
            top, bottom = rails_top + 8, h - bottom_h - ch - 8
            self._card.move(max(10, w - self._rail_right - CARD_W - 12),
                            max(top, min(bottom, y)))
            self._card.raise_()
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
        """Keep the settings panel inside its rail (direct-host mode only).

        Scrolls by what the current tab actually paints, not the panel's fixed
        height (sized for the tallest tab fully open), so a short or collapsed tab
        cannot be scrolled into blank space."""
        if self._settings is None:
            return 0
        visible = self.rect().height() - self._bottom_h - self._rails_top()
        content_h = getattr(self._settings, "content_height", None)
        height = content_h() if callable(content_h) else self._settings.height()
        overflow = height - visible
        return max(0, min(max(0, overflow), y))

    def _on_row_focused(self, _row) -> None:
        """Remote/hover focus moved: keep the row itself visible (a card
        centred on an off-screen row describes a control the user can't see),
        then let _layout_children re-place the card beside it."""
        if self._settings is None or not hasattr(self._settings, "focus_row_rect"):
            return
        rect = self._settings.focus_row_rect()
        if rect is None:
            return
        rails_top = self._rails_top()
        visible_bottom = self.rect().height() - self._bottom_h
        screen_top = rails_top - self._settings_scroll_y + rect.top()
        screen_bottom = rails_top - self._settings_scroll_y + rect.bottom()
        scroll = self._settings_scroll_y
        # One row of slack at each edge so walking the list feels smooth, not
        # twitchy — the view only moves when the row would actually leave it.
        if screen_bottom > visible_bottom - ROW_SLACK:
            scroll += screen_bottom - (visible_bottom - ROW_SLACK)
        elif screen_top < rails_top + ROW_SLACK:
            scroll -= (rails_top + ROW_SLACK) - screen_top
        self._settings_scroll_y = self._clamp_scroll(scroll)
        self._layout_children()

    def _on_settings_content_changed(self, shift: int, to_top: bool) -> None:
        if _USE_SCROLL_AREA or self._settings is None:
            return
        self._settings_scroll_y = 0 if to_top else self._settings_scroll_y + shift
        self._layout_children()

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

    def showEvent(self, event) -> None:        # noqa: N802
        super().showEvent(event)
        # Chrome up = remote keys belong to the rail: it navigates, and the
        # focus event shows the first row's card immediately.
        if self._settings is not None:
            self._settings.setFocus(Qt.FocusReason.OtherFocusReason)
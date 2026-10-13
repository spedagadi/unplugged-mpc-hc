"""
Focus style system for TV/remote navigation.

Focus highlighting is done via CSS :focus pseudo-state in each panel's
stylesheet — this is reliable and stylesheet-aware, unlike QGraphicsEffect
which gets reset when stylesheets are reapplied.

FocusGlow.install() / install_all() are kept as no-ops for compatibility
(the CSS handles the visual feedback now).

SettingsNavFilter: QObject event filter for TV-style keyboard navigation.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QWidget, QComboBox, QAbstractSpinBox,
    QCheckBox, QAbstractButton, QScrollArea, QApplication,
)


class FocusGlow:
    """
    No-op stub — focus highlighting is handled by CSS :focus pseudo-state
    in each panel's stylesheet. Kept for API compatibility.
    """
    @classmethod
    def install(cls, widget: QWidget, editing_signal: bool = False) -> None:
        pass

    @classmethod
    def install_all(cls, parent: QWidget) -> None:
        pass


# ── TV-style navigation filter for settings scroll area ─────────────

class SettingsNavFilter(QObject):
    """
    Event filter installed on the settings panel's QScrollArea.
    Routes arrow keys to TV-style navigation:
      ↑ / ↓  — move focus between visible focusable widgets
      ← / →  — change value of focused control
      Enter  — expand/collapse group header, toggle checkbox, open combo
      Escape — unfocus (caller should close settings)
    """

    def __init__(self, scroll: QScrollArea, parent=None) -> None:
        super().__init__(parent or scroll)
        self._scroll = scroll
        scroll.installEventFilter(self)
        # Also intercept on the inner widget
        if scroll.widget():
            scroll.widget().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False

        key_event: QKeyEvent = event  # type: ignore
        key = key_event.key()

        focused = QApplication.focusWidget()

        # ↑ ↓ — move between focusable widgets
        if key == Qt.Key.Key_Up:
            self._move_focus(-1)
            return True
        if key == Qt.Key.Key_Down:
            self._move_focus(1)
            return True

        # ← → — change value of focused control
        if key == Qt.Key.Key_Left:
            return self._change_value(focused, -1)
        if key == Qt.Key.Key_Right:
            return self._change_value(focused, 1)

        # Enter — activate focused control
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return self._activate(focused)

        return False

    # ------------------------------------------------------------------

    def _focusable_widgets(self) -> list[QWidget]:
        """All visible, enabled, focusable widgets in document order."""
        inner = self._scroll.widget()
        if not inner:
            return []
        result = []
        for w in inner.findChildren(QWidget):
            if (w.isVisible() and w.isEnabled() and
                    w.focusPolicy() != Qt.FocusPolicy.NoFocus and
                    not self._is_container(w)):
                result.append(w)
        return result

    def _is_container(self, w: QWidget) -> bool:
        from PyQt6.QtWidgets import QFrame, QScrollArea as SA
        return isinstance(w, (SA,)) or w.__class__.__name__ in ("_Row", "CollapsibleGroup")

    def _move_focus(self, direction: int) -> None:
        widgets = self._focusable_widgets()
        if not widgets:
            return
        focused = QApplication.focusWidget()
        try:
            idx = widgets.index(focused)
        except ValueError:
            idx = -1

        new_idx = (idx + direction) % len(widgets)
        target = widgets[new_idx]
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        # Scroll to make it visible
        self._scroll.ensureWidgetVisible(target, 20, 20)

    def _change_value(self, widget: QWidget | None, delta: int) -> bool:
        if widget is None:
            return False
        if isinstance(widget, QComboBox):
            count = widget.count()
            new_idx = max(0, min(count - 1, widget.currentIndex() + delta))
            widget.setCurrentIndex(new_idx)
            return True
        if isinstance(widget, QAbstractSpinBox):
            if delta > 0:
                widget.stepUp()
            else:
                widget.stepDown()
            return True
        return False

    def _activate(self, widget: QWidget | None) -> bool:
        if widget is None:
            return False
        if isinstance(widget, QCheckBox):
            widget.setChecked(not widget.isChecked())
            return True
        if isinstance(widget, QAbstractButton):
            widget.click()
            return True
        if isinstance(widget, QComboBox):
            widget.showPopup()
            return True
        return False

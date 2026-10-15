"""
InputConfigPanel — reusable DeckLink input configuration widget.

Displays all enumerated ports with live signal status, inline name editing,
and a radio selector for the active input. Used by:
  - FirstRunDialog  (VP setup step)
  - InputConfigDialog  (accessible from Settings → Input Device)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QButtonGroup, QRadioButton,
    QSizePolicy, QDialog,
)

from ..core.decklink_monitor import poll_all_ports, PortStatus
from ..config.model import AppConfig


_ROW_DEFAULT = "background: rgba(30,30,30,255); border-radius: 8px; border: 1px solid rgba(255,255,255,8);"
_ROW_ACTIVE  = "background: rgba(60,25,10,255); border-radius: 8px; border: 1px solid rgba(232,85,31,200);"

_BTN_RESCAN = """
QPushButton {
    color: #aaa; background: transparent;
    border: 1px solid rgba(255,255,255,20); border-radius: 5px;
    font-size: 12px; padding: 4px 14px;
}
QPushButton:hover { color: #fff; border-color: rgba(255,255,255,40); }
"""

_EDIT_STYLE = """
QLineEdit {
    background: rgba(50,50,50,180);
    border: 1px solid rgba(255,255,255,20);
    border-radius: 4px; color: #e0e0e0;
    padding: 4px 8px; min-width: 160px;
}
QLineEdit:focus { border-color: rgba(76,175,80,180); }
"""


class _PortRow(QWidget):
    """One port row: radio · signal badge · raw URL · label editor."""

    def __init__(self, port: PortStatus, app_config: AppConfig,
                 radio_group: QButtonGroup, parent=None) -> None:
        super().__init__(parent)
        self._port = port
        self._app_config = app_config
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_ROW_DEFAULT)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(12, 6, 12, 6)
        hl.setSpacing(12)

        self._radio = QRadioButton()
        self._radio.setStyleSheet("QRadioButton { spacing: 0; }")
        radio_group.addButton(self._radio)
        hl.addWidget(self._radio)

        # Signal badge
        self._badge = QLabel()
        self._badge.setFixedWidth(100)
        self._badge.setStyleSheet("font-size: 12px;")
        hl.addWidget(self._badge)

        # Raw port URL (clean)
        clean = port.url.replace("decklink://", "")
        url_lbl = QLabel(clean)
        url_lbl.setStyleSheet("color:#555; font-size:11px;")
        url_lbl.setFixedWidth(240)
        url_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        hl.addWidget(url_lbl)

        # Name editor
        self._edit = QLineEdit(app_config.label_for(port.url))
        self._edit.setPlaceholderText("e.g. Apple TV")
        self._edit.setStyleSheet(_EDIT_STYLE)
        hl.addWidget(self._edit, 1)

        self._update_badge()

        self._radio.clicked.connect(self._on_radio)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._radio.setChecked(True)
            self._on_radio()
        super().mousePressEvent(event)

    def _on_radio(self) -> None:
        # Highlight is driven by InputConfigPanel based on selected URL
        pass

    def _update_badge(self) -> None:
        p = self._port
        if p.locked:
            dr = p.dr_label or "SDR"
            color = "#4caf50" if p.dynamic_range > 0 else "#e0e0e0"
            self._badge.setText(f"🔒  {dr}")
            self._badge.setStyleSheet(f"color:{color}; font-size:12px;")
        elif p.unknown:
            self._badge.setText("○  —")
            self._badge.setStyleSheet("color:#555; font-size:12px;")
        else:
            self._badge.setText("○  No signal")
            self._badge.setStyleSheet("color:#555; font-size:12px;")

    def refresh(self, port: PortStatus) -> None:
        self._port = port
        self._update_badge()

    @property
    def url(self) -> str:
        return self._port.url

    @property
    def label_text(self) -> str:
        return self._edit.text().strip()

    def set_active(self, active: bool) -> None:
        self.setStyleSheet(_ROW_ACTIVE if active else _ROW_DEFAULT)

    def set_radio_checked(self, checked: bool) -> None:
        self._radio.setChecked(checked)


class InputConfigPanel(QWidget):
    """
    Reusable input configuration panel.

    Signals:
      active_url_changed(url)  — user changed the active port selection
      labels_saved()           — user saved names (via save_labels())
    """
    active_url_changed = pyqtSignal(str)
    labels_saved       = pyqtSignal()

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._ports: list[PortStatus] = []
        self._rows: list[_PortRow] = []
        self._radio_group = QButtonGroup(self)
        self._radio_group.buttonClicked.connect(self._on_radio_clicked)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header row: status text + Rescan button
        hdr = QHBoxLayout()
        self._status_lbl = QLabel("Scanning for DeckLink devices…")
        self._status_lbl.setStyleSheet("color:#666; font-size:12px;")
        hdr.addWidget(self._status_lbl, 1)

        self._rescan_btn = QPushButton("⟳  Rescan")
        self._rescan_btn.setStyleSheet(_BTN_RESCAN)
        self._rescan_btn.clicked.connect(self.scan)
        hdr.addWidget(self._rescan_btn)
        root.addLayout(hdr)

        # Column headers
        col_hdr = QWidget()
        col_hl = QHBoxLayout(col_hdr)
        col_hl.setContentsMargins(12, 0, 12, 0)
        col_hl.setSpacing(12)
        for text, width in (("", 20), ("Signal", 100), ("Port", 240), ("Your name", 0)):
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#444; font-size:11px; font-weight:600;")
            if width:
                lbl.setFixedWidth(width)
            col_hl.addWidget(lbl, 0 if width else 1)
        root.addWidget(col_hdr)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: rgba(255,255,255,12);")
        root.addWidget(div)

        # Scrollable port list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollBar:vertical { width:4px; background:transparent; }"
            "QScrollBar::handle:vertical { background:rgba(255,255,255,30); border-radius:2px; }"
        )
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, 1)

        # Auto-scan after a short delay so the parent can finish rendering. A MEMBER timer,
        # not QTimer.singleShot: singleShot's timer is parentless and holds a bound method,
        # so it fires even after this panel's C++ object has been deleted — which is exactly
        # how a deleted QButtonGroup got touched from _do_scan (crash.log, 2026-10-15).
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(250)
        self._scan_timer.timeout.connect(self.scan)
        self._scan_timer.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Poll DeckLink SDK and rebuild the port list."""
        self._rescan_btn.setEnabled(False)
        self._status_lbl.setText("Scanning…")
        self._status_lbl.setStyleSheet("color:#666; font-size:12px;")
        QTimer.singleShot(50, self._do_scan)

    def save_labels(self) -> None:
        """Persist all name-editor contents to app_config."""
        for row in self._rows:
            self._app_config.set_input_label(row.url, row.label_text)
        self.labels_saved.emit()

    def active_url(self) -> str:
        for row in self._rows:
            if row._radio.isChecked():
                return row.url
        return self._app_config.active_input_url or ""

    def has_ports(self) -> bool:
        return len(self._ports) > 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_scan(self) -> None:
        # Liveness probe: touching any property of a deleted C++ object raises
        # RuntimeError. If this panel was orphaned (its dialog collected), a stray timer
        # must not walk into _rebuild_list and touch the radio group.
        try:
            _ = self._radio_group.exclusive
        except RuntimeError:
            return
        self._ports = poll_all_ports()
        self._rebuild_list()
        self._rescan_btn.setEnabled(True)

    def _rebuild_list(self) -> None:
        # Clear existing rows
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        for btn in self._radio_group.buttons():
            self._radio_group.removeButton(btn)

        # Remove all items except the trailing stretch
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._ports:
            self._status_lbl.setText(
                "⚠  No DeckLink devices found — check drivers and card seating.")
            self._status_lbl.setStyleSheet("color:#ff9800; font-size:12px;")
            empty = QLabel("No capture devices detected.")
            empty.setStyleSheet("color:#555; font-size:13px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return

        n = len(self._ports)
        locked = [p for p in self._ports if p.locked]
        self._status_lbl.setText(
            f"✓  {n} port{'s' if n != 1 else ''} found"
            + (f"  ·  {len(locked)} with signal" if locked else ""))
        self._status_lbl.setStyleSheet("color:#4caf50; font-size:12px;")

        active = self._app_config.active_input_url
        auto_url = (locked[0].url if locked else self._ports[0].url)
        selected_url = active if any(p.url == active for p in self._ports) else auto_url

        for i, port in enumerate(self._ports):
            row = _PortRow(port, self._app_config, self._radio_group)
            self._rows.append(row)
            self._list_layout.insertWidget(i, row)

        self._select(selected_url)

    def _select(self, url: str) -> None:
        for row in self._rows:
            is_active = row.url == url
            row.set_radio_checked(is_active)
            row.set_active(is_active)

    def _on_radio_clicked(self, btn) -> None:
        for row in self._rows:
            checked = row._radio is btn
            row.set_active(checked)
            if checked:
                self._app_config.active_input_url = row.url
                self.active_url_changed.emit(row.url)


_ACCENT      = "#E8551F"
_ACCENT_RGBA = "rgba(232,85,31,220)"

_DLG_STYLE = """
QWidget#card {
    background: #0e0e0e;
    /* The same accent frame FirstRunDialog wears. Both open from the SOURCE page, and a
       grey-bordered card next to an orange one reads as two different applications. */
    border: 1.5px solid rgba(232,85,31,200);
    border-radius: 14px;
}
QWidget  { background: transparent; color: #e0e0e0; }
QScrollArea { background: transparent; border: none; }
QLineEdit {
    background: rgba(50,50,50,255);
    border: 1px solid rgba(255,255,255,25);
    border-radius: 4px; color: #e0e0e0;
    padding: 4px 8px;
}
QLineEdit:focus { border-color: rgba(232,85,31,180); }
"""

_DLG_BTN_PRIMARY = """
QPushButton {
    color: #fff; background: rgba(232,85,31,200);
    border: 1px solid rgba(232,85,31,255); border-radius: 6px;
    padding: 7px 24px; font-weight: 600;
}
QPushButton:hover { background: rgba(232,85,31,255); }
"""
_DLG_BTN_SECONDARY = """
QPushButton {
    color: #888; background: transparent;
    border: 1px solid rgba(255,255,255,20); border-radius: 6px;
    padding: 7px 18px;
}
QPushButton:hover { color: #ccc; border-color: rgba(255,255,255,40); }
"""


def _center_on_screen(widget) -> None:
    """Position widget at screen centre using availableGeometry (respects taskbar)."""
    from PyQt6.QtWidgets import QApplication
    screen = QApplication.primaryScreen()
    if not screen:
        return
    sg = screen.availableGeometry()
    x = sg.x() + (sg.width()  - widget.width())  // 2
    y = sg.y() + (sg.height() - widget.height()) // 2
    widget.move(
        max(sg.x(), min(x, sg.x() + sg.width()  - widget.width())),
        max(sg.y(), min(y, sg.y() + sg.height() - widget.height())),
    )


class InputConfigDialog(QDialog):
    """
    Standalone dialog wrapping InputConfigPanel.
    Emits input_changed(url) when the user saves a new active port.
    """
    input_changed = pyqtSignal(str)

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(800, 480)
        self._app_config = app_config
        self._original_url = app_config.active_input_url

        card = QWidget(self)
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_DLG_STYLE)
        card.setFixedSize(self.width(), self.height())

        root = QVBoxLayout(card)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)

        # Title row with orange accent bar
        title_row = QHBoxLayout()
        accent = QLabel("▌")
        accent.setStyleSheet(f"color:{_ACCENT}; font-size:20px;")
        title_row.addWidget(accent)
        title = QLabel("Configure Capture Inputs")
        title.setStyleSheet("color:#ffffff; font-size:17px; font-weight:700;")
        title_row.addWidget(title)
        title_row.addStretch()
        root.addLayout(title_row)

        sub = QLabel("Select the active input and give each port a name for quick switching.")
        sub.setStyleSheet("color:#666; font-size:12px;")
        root.addWidget(sub)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color: rgba(232,85,31,60);")
        root.addWidget(div)

        self._panel = InputConfigPanel(app_config)
        root.addWidget(self._panel, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_DLG_BTN_SECONDARY)
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save & Close")
        save_btn.setStyleSheet(_DLG_BTN_PRIMARY)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        _center_on_screen(self)

    def _on_save(self) -> None:
        self._panel.save_labels()
        new_url = self._panel.active_url()
        if new_url and new_url != self._original_url:
            self._app_config.active_input_url = new_url
            self.input_changed.emit(new_url)
        self.accept()

    def _on_cancel(self) -> None:
        self._app_config.active_input_url = self._original_url
        self.reject()

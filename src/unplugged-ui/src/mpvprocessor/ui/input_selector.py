"""
InputSelector — DeckLink input port switcher shown in the status bar.

Shows a dropdown of all enumerated ports with live signal lock indicators.
Updates every 2 seconds via SDK polling (no exclusive device lock needed).

Visible only in Video Processor mode.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QDialog,
    QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QFrame,
)

from ..core.decklink_monitor import poll_all_ports, PortStatus
from ..config.model import AppConfig


_COMBO_STYLE = """
QComboBox {
    color: #e0e0e0;
    background: rgba(255,255,255,10);
    border: 1px solid rgba(255,255,255,25);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 12px;
    min-width: 160px;
}
QComboBox:hover { border-color: rgba(255,255,255,45); }
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #1a1a1a;
    color: #e0e0e0;
    border: 1px solid rgba(255,255,255,25);
    selection-background-color: #E8551F;
    outline: none;
}
"""

_LABEL_STYLE = "color: #666666; font-size: 11px; background: transparent;"

_EDIT_DLG_STYLE = """
QDialog { background: #1a1a1a; color: #e0e0e0; }
QLabel  { background: transparent; font-size: 12px; }
QLineEdit {
    background: rgba(50,50,50,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 3px; color: #e0e0e0;
    padding: 4px 8px; font-size: 12px;
}
QPushButton {
    background: rgba(60,60,60,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 4px; color: #e0e0e0;
    padding: 5px 14px; font-size: 12px;
}
QPushButton:hover { background: rgba(90,90,90,220); }
QPushButton#ok { border-color: rgba(232,85,31,180); color: #E8551F; }
"""


class InputSelector(QWidget):
    """
    Compact input selector for the status bar.
    Emits input_changed(url) when user selects a different port.
    """
    input_changed = pyqtSignal(str)   # new decklink:// URL

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._ports: list[PortStatus] = []
        self._inhibit = False

        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel("Input:")
        lbl.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(lbl)

        self._combo = QComboBox()
        self._combo.setStyleSheet(_COMBO_STYLE)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_polling(self) -> None:
        self.refresh()
        self._poll_timer.start()

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    def refresh(self) -> None:
        """Poll all ports and update the dropdown."""
        self._ports = poll_all_ports()
        self._rebuild_combo()

    def current_url(self) -> str:
        """Return the currently selected port URL."""
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._ports):
            return self._ports[idx].url
        return self._app_config.active_input_url or ""

    def set_active_url(self, url: str) -> None:
        """Programmatically select a port URL."""
        self._inhibit = True
        for i, p in enumerate(self._ports):
            if p.url == url:
                self._combo.setCurrentIndex(i)
                break
        self._inhibit = False

    def show_label_editor(self) -> None:
        """Open the label editor dialog."""
        dlg = _LabelEditorDialog(self._ports, self._app_config, self)
        if dlg.exec():
            self._rebuild_combo()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_combo(self) -> None:
        self._inhibit = True
        current = self.current_url() or self._app_config.active_input_url
        self._combo.clear()

        for port in self._ports:
            label = self._app_config.label_for(port.url)
            icon  = port.status_icon()
            dr    = f"  {port.dr_label}" if port.locked and port.dr_label else ""
            display = f"{icon}  {label}{dr}"
            self._combo.addItem(display, port.url)

        if self._ports:
            self._combo.addItem("─────────────", None)
            self._combo.addItem("✎  Edit labels…", "__edit__")

        # Restore selection
        for i, p in enumerate(self._ports):
            if p.url == current:
                self._combo.setCurrentIndex(i)
                break
        else:
            if self._ports:
                self._combo.setCurrentIndex(0)

        self._inhibit = False

    def _on_selection_changed(self, idx: int) -> None:
        if self._inhibit:
            return
        data = self._combo.itemData(idx)
        if data == "__edit__":
            # Revert to previous valid selection then open editor
            self._combo.blockSignals(True)
            self.set_active_url(self._app_config.active_input_url)
            self._combo.blockSignals(False)
            self.show_label_editor()
            return
        if data is None:
            return  # separator
        if data and data != self._app_config.active_input_url:
            self._app_config.active_input_url = data
            self.input_changed.emit(data)


class _LabelEditorDialog(QDialog):
    """Edit friendly names for each input port."""

    def __init__(self, ports: list[PortStatus], app_config: AppConfig,
                 parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(_EDIT_DLG_STYLE)
        self.setWindowTitle("Edit Input Labels")
        self.setFixedWidth(420)
        self._app_config = app_config
        self._edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Name your inputs")
        title.setStyleSheet("color:#ffffff; font-size:14px; font-weight:600;")
        root.addWidget(title)

        sub = QLabel("Give each input a meaningful name (e.g. Apple TV, Blu-ray)")
        sub.setStyleSheet("color:#888; font-size:11px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(255,255,255,15);")
        root.addWidget(line)

        form = QFormLayout()
        form.setSpacing(8)
        for port in ports:
            default = app_config.label_for(port.url)
            icon = port.status_icon()
            dr   = f" · {port.dr_label}" if port.locked and port.dr_label else ""
            row_lbl = QLabel(f"{icon}  {port.url.replace('decklink://','')}{dr}")
            row_lbl.setStyleSheet("color:#aaaaaa; font-size:11px;")
            edit = QLineEdit(default)
            edit.setPlaceholderText(f"e.g. Apple TV")
            self._edits[port.url] = edit
            form.addRow(row_lbl, edit)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Save")
        btn_ok.setObjectName("ok")
        btn_ok.clicked.connect(self._save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

    def _save(self) -> None:
        for url, edit in self._edits.items():
            self._app_config.set_input_label(url, edit.text().strip())
        self.accept()


"""
Preset Manager dialog.

Actions: New · Duplicate · Rename · Delete · Import mpv.conf · Export JSON
Built-in presets cannot be deleted or renamed.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from copy import deepcopy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QFileDialog, QWidget,
)

from ..profiles.manager import ProfileManager, _BUILTIN_PROFILE_NAMES
from ..config.model import MpvProfile
from ..config.serializer import build_mpv_conf
from ..config.conf_importer import import_mpv_conf


_DLG_STYLE = """
QDialog {
    background: #1a1a1a;
    color: #e0e0e0;
}
QListWidget {
    background: #111;
    border: 1px solid rgba(255,255,255,20);
    border-radius: 4px;
    color: #e0e0e0;
    font-size: 12px;
    outline: none;
}
QListWidget::item { padding: 6px 10px; }
QListWidget::item:selected {
    background: rgba(232,85,31,120);
    color: #ffffff;
}
QListWidget::item:hover:!selected { background: rgba(255,255,255,10); }
QPushButton {
    background: rgba(60,60,60,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 4px;
    color: #e0e0e0;
    padding: 6px 14px;
    font-size: 11px;
    min-width: 100px;
}
QPushButton:hover { background: rgba(90,90,90,220); }
QPushButton:disabled { color: #555; border-color: rgba(255,255,255,15); }
QPushButton#danger { border-color: rgba(244,67,54,150); }
QPushButton#danger:hover { background: rgba(244,67,54,80); }
QPushButton#primary { border-color: rgba(232,85,31,180); color: #E8551F; }
QLineEdit {
    background: rgba(50,50,50,200);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 3px;
    color: #e0e0e0;
    padding: 5px 8px;
    font-size: 12px;
}
QLabel { color: #aaaaaa; font-size: 11px; }
QLabel#title { color: #ffffff; font-size: 14px; font-weight: bold; }
"""


def _input_dialog(parent, title: str, prompt: str, default: str = "") -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setStyleSheet(_DLG_STYLE)
    dlg.setFixedWidth(360)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(10)
    layout.addWidget(QLabel(prompt))
    edit = QLineEdit(default)
    layout.addWidget(edit)
    btn_row = QHBoxLayout()
    ok = QPushButton("OK")
    ok.setProperty("class", "primary")
    cancel = QPushButton("Cancel")
    ok.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    btn_row.addStretch()
    btn_row.addWidget(cancel)
    btn_row.addWidget(ok)
    layout.addLayout(btn_row)
    edit.setFocus()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return edit.text().strip()
    return None


class PresetManagerDialog(QDialog):
    """
    Opens as a modal dialog. Emits `preset_activated(MpvProfile)` when the
    user double-clicks a preset or clicks Load. Caller applies it.
    """
    preset_activated = pyqtSignal(object)  # MpvProfile

    def __init__(self, manager: ProfileManager, current_name: str, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._current = current_name

        self.setWindowTitle("Preset Manager")
        self.setStyleSheet(_DLG_STYLE)
        self.setMinimumSize(560, 440)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Title
        title = QLabel("Preset Manager")
        title.setObjectName("title")
        root.addWidget(title)

        sub = QLabel(
            "Presets are saved as JSON files in your unplugged config folder. "
            "Built-in presets (Default, Projector-Cinema, Monitor-Desktop) cannot be deleted."
        )
        sub.setWordWrap(True)
        root.addWidget(sub)

        # List + action buttons side by side
        body = QHBoxLayout()
        body.setSpacing(10)

        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._list.itemDoubleClicked.connect(self._load_selected)
        body.addWidget(self._list, 1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        def btn(label, slot, obj_name=""):
            b = QPushButton(label)
            if obj_name:
                b.setObjectName(obj_name)
            b.clicked.connect(slot)
            btn_col.addWidget(b)
            return b

        self._btn_load      = btn("▶  Load",       self._load_selected,  "primary")
        self._btn_new       = btn("＋  New",         self._new_preset)
        self._btn_duplicate = btn("⊕  Duplicate",   self._duplicate)
        self._btn_rename    = btn("✎  Rename",       self._rename)
        self._btn_delete    = btn("✕  Delete",       self._delete,         "danger")
        btn_col.addSpacing(12)
        self._btn_import    = btn("↓  Import mpv.conf", self._import_conf)
        self._btn_export_json = btn("↑  Export JSON", self._export_json)
        self._btn_export_conf = btn("↑  Export mpv.conf", self._export_conf)
        btn_col.addStretch()
        body.addLayout(btn_col)
        root.addLayout(body)

        # Close
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

        self._refresh()
        self._list.currentRowChanged.connect(self._update_buttons)
        self._update_buttons()

    # ─────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        cur = self._selected_name()
        self._list.clear()
        for name in self._manager.list_profiles():
            item = QListWidgetItem(name)
            if name in _BUILTIN_PROFILE_NAMES:
                item.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(item)
        # Restore selection
        target = cur or self._current
        for i in range(self._list.count()):
            if self._list.item(i).text() == target:
                self._list.setCurrentRow(i)
                break

    def _selected_name(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item else None

    def _update_buttons(self) -> None:
        name = self._selected_name()
        is_builtin = name in _BUILTIN_PROFILE_NAMES
        has_sel = name is not None
        self._btn_load.setEnabled(has_sel)
        self._btn_duplicate.setEnabled(has_sel)
        self._btn_rename.setEnabled(has_sel and not is_builtin)
        self._btn_delete.setEnabled(has_sel and not is_builtin)
        self._btn_export_json.setEnabled(has_sel)
        self._btn_export_conf.setEnabled(has_sel)

    # ── Actions ───────────────────────────────────────────────────────

    def _load_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        profile = self._manager.load(name)
        self._current = name
        self.preset_activated.emit(profile)
        self.accept()

    def _new_preset(self) -> None:
        name = _input_dialog(self, "New Preset", "Enter a name for the new preset:")
        if not name:
            return
        if self._manager.exists(name):
            QMessageBox.warning(self, "Name taken", f"A preset named '{name}' already exists.")
            return
        profile = MpvProfile(name=name)
        self._manager.save(profile)
        self._refresh()

    def _duplicate(self) -> None:
        src = self._selected_name()
        if not src:
            return
        name = _input_dialog(self, "Duplicate Preset", "Name for the duplicate:", f"{src} Copy")
        if not name:
            return
        if self._manager.exists(name):
            QMessageBox.warning(self, "Name taken", f"A preset named '{name}' already exists.")
            return
        self._manager.duplicate(src, name)
        self._refresh()

    def _rename(self) -> None:
        src = self._selected_name()
        if not src or src in _BUILTIN_PROFILE_NAMES:
            return
        name = _input_dialog(self, "Rename Preset", "New name:", src)
        if not name or name == src:
            return
        if self._manager.exists(name):
            QMessageBox.warning(self, "Name taken", f"A preset named '{name}' already exists.")
            return
        self._manager.rename(src, name)
        self._refresh()

    def _delete(self) -> None:
        name = self._selected_name()
        if not name or name in _BUILTIN_PROFILE_NAMES:
            return
        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.delete(name)
            self._refresh()
            self._update_buttons()

    def _import_conf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import mpv.conf", "", "mpv config (*.conf);;All files (*)"
        )
        if not path:
            return
        name = _input_dialog(
            self, "Import Preset",
            "Name for the imported preset:",
            Path(path).stem,
        )
        if not name:
            return
        if self._manager.exists(name):
            reply = QMessageBox.question(
                self, "Overwrite?",
                f"A preset named '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            profile = import_mpv_conf(Path(path), name)
            self._manager.save(profile)
            self._refresh()
            QMessageBox.information(
                self, "Import complete",
                f"Preset '{name}' imported. "
                "Unrecognised mpv options were ignored — please review the settings."
            )
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def _export_json(self) -> None:
        name = self._selected_name()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Preset JSON", f"{name}.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            profile = self._manager.load(name)
            profile.save(Path(path))
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _export_conf(self) -> None:
        name = self._selected_name()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export as mpv.conf", f"{name}.conf", "mpv config (*.conf)"
        )
        if not path:
            return
        try:
            profile = self._manager.load(name)
            Path(path).write_text(build_mpv_conf(profile), encoding="utf-8")
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))



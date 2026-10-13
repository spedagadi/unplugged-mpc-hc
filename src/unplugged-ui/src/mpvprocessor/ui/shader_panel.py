"""
Shader panel — shown inside the settings panel as a group.

Features:
  - Folder path field with browse button and Rescan button
  - Scrollable list of .glsl files, each with a checkbox and conflict badge
  - Per-shader conflict tooltip on hover
  - Conflict summary banner at the top when HARD conflicts are active
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QLineEdit, QScrollArea, QFileDialog, QFrame, QToolTip,
)
from PyQt6.QtGui import QCursor

from ..core.shader_manager import (
    detect_conflicts, sync_shader_list, Severity,
)
from ..config.model import AppConfig, MpvProfile


_BADGE_HARD = (
    "background:#c0392b; color:#fff; border-radius:3px; "
    "padding:1px 5px; font-size:10px; font-weight:bold;"
)
_BADGE_SOFT = (
    "background:#e67e22; color:#fff; border-radius:3px; "
    "padding:1px 5px; font-size:10px; font-weight:bold;"
)
_BADGE_COND = (
    "background:#8e44ad; color:#fff; border-radius:3px; "
    "padding:1px 5px; font-size:10px; font-weight:bold;"
)
_BANNER_HARD = (
    "background:rgba(192,57,43,180); color:#fff; "
    "border-radius:4px; padding:6px 10px; font-size:11px;"
)
_BANNER_SOFT = (
    "background:rgba(230,126,34,150); color:#fff; "
    "border-radius:4px; padding:6px 10px; font-size:11px;"
)


def _badge_style(severity: Severity) -> str:
    return {
        Severity.HARD: _BADGE_HARD,
        Severity.SOFT: _BADGE_SOFT,
        Severity.CONDITIONAL: _BADGE_COND,
    }[severity]


def _badge_label(severity: Severity) -> str:
    return {
        Severity.HARD: "HARD",
        Severity.SOFT: "SOFT",
        Severity.CONDITIONAL: "COND",
    }[severity]


class _ShaderRow(QWidget):
    toggled = pyqtSignal(str, bool)  # (path, enabled)

    def __init__(self, path: str, enabled: bool, conflicts, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        name = Path(path).name

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 1, 4, 1)
        row.setSpacing(5)
        self.setFixedHeight(22)

        self._chk = QCheckBox(name)
        self._chk.setChecked(enabled)
        self._chk.setStyleSheet("color:#e0e0e0; font-size:11px; padding:0px;")
        self._chk.toggled.connect(lambda v: self.toggled.emit(self._path, v))
        row.addWidget(self._chk, 1)

        # Conflict badges
        self._tooltip_lines = []
        for c in conflicts:
            badge = QLabel(_badge_label(c.rule.severity))
            badge.setStyleSheet(_badge_style(c.rule.severity))
            badge.setFixedHeight(18)
            row.addWidget(badge)
            self._tooltip_lines.append(
                f"[{_badge_label(c.rule.severity)}] {c.rule.description}\n→ {c.rule.fix}"
            )

        if self._tooltip_lines:
            self.setToolTip("\n\n".join(self._tooltip_lines))
            self.setMouseTracking(True)

    def set_enabled(self, v: bool) -> None:
        self._chk.blockSignals(True)
        self._chk.setChecked(v)
        self._chk.blockSignals(False)


class ShaderPanel(QWidget):
    """
    Embeds into the settings panel. Emits `changed` whenever the shader
    list or enabled state changes so the parent can re-emit profile_changed.
    """
    changed = pyqtSignal()

    def __init__(self, app_config: AppConfig, profile: MpvProfile, parent=None) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._profile = profile
        self._rows: list[_ShaderRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # ── Folder row ────────────────────────────────────────────────
        folder_row = QWidget()
        fr = QHBoxLayout(folder_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(4)

        self._dir_edit = QLineEdit(self._profile.shaders.shader_dir)
        self._dir_edit.setPlaceholderText("Shader folder path…")
        self._dir_edit.setStyleSheet(
            "background:rgba(50,50,50,200); border:1px solid rgba(255,255,255,30);"
            "border-radius:3px; color:#e0e0e0; padding:3px 6px;"
        )
        self._dir_edit.editingFinished.connect(self._on_dir_changed)
        fr.addWidget(self._dir_edit, 1)

        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(28)
        btn_browse.setStyleSheet(
            "background:rgba(70,70,70,200); border:1px solid rgba(255,255,255,40);"
            "border-radius:3px; color:#e0e0e0; padding:2px;"
        )
        btn_browse.clicked.connect(self._browse)
        fr.addWidget(btn_browse)

        btn_scan = QPushButton("Rescan")
        btn_scan.setStyleSheet(
            "background:rgba(70,70,70,200); border:1px solid rgba(255,255,255,40);"
            "border-radius:3px; color:#e0e0e0; padding:3px 8px; font-size:11px;"
        )
        btn_scan.clicked.connect(self._rescan)
        fr.addWidget(btn_scan)
        root.addWidget(folder_row)

        # ── Conflict banner ───────────────────────────────────────────
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.hide()
        root.addWidget(self._banner)

        # ── Shader list ───────────────────────────────────────────────
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMaximumHeight(180)
        scroll.setSizeAdjustPolicy(QScrollArea.SizeAdjustPolicy.AdjustToContents)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

        self._populate()

    # ─────────────────────────────────────────────────────────────────

    def update_profile(self, profile: MpvProfile) -> None:
        """Called when the parent profile changes so conflicts re-evaluate."""
        self._profile = profile
        self._populate()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Shader Folder",
                                             self._dir_edit.text() or "")
        if d:
            self._dir_edit.setText(d)
            self._profile.shaders.shader_dir = d
            self._rescan()

    def _on_dir_changed(self) -> None:
        self._profile.shaders.shader_dir = self._dir_edit.text()
        self._rescan()

    def _rescan(self) -> None:
        sync_shader_list(self._profile.shaders, self._app_config.mpv_executable)
        self._dir_edit.setText(self._profile.shaders.shader_dir)
        self._populate()
        self.changed.emit()

    def _on_shader_toggled(self, path: str, enabled: bool) -> None:
        for s in self._profile.shaders.shaders:
            if s["path"] == path:
                s["enabled"] = enabled
                break
        self._update_banner()
        self.changed.emit()

    def _populate(self) -> None:
        # Clear all widgets from list layout
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        shaders = self._profile.shaders.shaders

        if not shaders:
            lbl = QLabel("No shaders found. Click Rescan or choose a folder.")
            lbl.setStyleSheet("color:#666; font-size:11px; padding:6px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(lbl)
            self._list_layout.addStretch(1)
            self._update_banner()
            return

        for entry in shaders:
            path = entry["path"]
            enabled = entry.get("enabled", False)
            name = Path(path).name
            conflicts = detect_conflicts(name, self._profile) if enabled else []
            row = _ShaderRow(path, enabled, conflicts, self._list_widget)
            row.toggled.connect(self._on_shader_toggled)
            self._list_layout.addWidget(row)
            self._rows.append(row)

        # Pin rows to top — without this the layout distributes space evenly
        self._list_layout.addStretch(1)
        self._update_banner()

    def _update_banner(self) -> None:
        hard_lines, soft_lines = [], []
        for entry in self._profile.shaders.shaders:
            if not entry.get("enabled"):
                continue
            name = Path(entry["path"]).name
            for c in detect_conflicts(name, self._profile):
                line = f"• {name}: {c.rule.fix}"
                if c.rule.severity == Severity.HARD:
                    hard_lines.append(line)
                else:
                    soft_lines.append(line)

        if hard_lines:
            self._banner.setText(
                "⚠ HARD CONFLICT — mpv will produce wrong output. Fix before starting:\n" +
                "\n".join(hard_lines)
            )
            self._banner.setStyleSheet(_BANNER_HARD)
            self._banner.show()
        elif soft_lines:
            self._banner.setText(
                "⚠ Double-processing — redundant passes active. Recommended fixes:\n" +
                "\n".join(soft_lines)
            )
            self._banner.setStyleSheet(_BANNER_SOFT)
            self._banner.show()
        else:
            self._banner.hide()

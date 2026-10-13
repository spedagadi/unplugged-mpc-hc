"""
Media library panel — shown on the main screen when in Media Player mode.

Layout:
  Top:    folder picker + Scan button + recursive toggle
  Middle: scrollable title grid (title + size + ext badge)
  Bottom: selected file info bar + Play button

Emits play_requested(path_str) when user double-clicks or hits Play.
Remembers last folder and last played in AppConfig.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QCheckBox,
    QFileDialog, QFrame, QAbstractItemView,
)

from ..media.scanner import scan_folder, MediaItem
from ..config.model import AppConfig


_EXT_COLORS = {
    ".mkv":  "#29b6f6",
    ".mp4":  "#66bb6a",
    ".m4v":  "#66bb6a",
    ".mov":  "#ffa726",
    ".avi":  "#ef5350",
    ".wmv":  "#ab47bc",
    ".ts":   "#26c6da",
    ".m2ts": "#26c6da",
    ".iso":  "#ff7043",
    ".bdmv": "#ff7043",
}

_audit = logging.getLogger("unplugged.audit")

_PANEL_STYLE = """
QWidget {
    background: rgba(10,10,10,240);
    color: #e0e0e0;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255,255,255,8);
    border-radius: 0px;
}
QListWidget::item:selected {
    background: rgba(232,85,31,100);
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background: rgba(255,255,255,8);
}
QScrollBar:vertical {
    background: transparent; width: 5px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,30); border-radius: 2px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QLineEdit {
    background: rgba(40,40,40,200);
    border: 1px solid rgba(255,255,255,20);
    border-radius: 4px;
    color: #e0e0e0;
    padding: 4px 8px;
}
QPushButton {
    background: rgba(50,50,50,220);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 5px;
    color: #cccccc;
    padding: 7px 20px;
    outline: none;
}
QPushButton:hover { background: rgba(70,70,70,240); color: #ffffff; border-color: rgba(255,255,255,50); }
QPushButton:focus { outline: none; }
QPushButton:disabled { background: rgba(30,30,30,180); color: #555; border-color: rgba(255,255,255,10); }
QCheckBox { color: #888; }
QCheckBox::indicator { width: 14px; height: 14px;
    border: 1px solid rgba(255,255,255,30); border-radius: 2px;
    background: rgba(40,40,40,200); }
QCheckBox::indicator:checked { background: #E8551F; border-color: #E8551F; }
"""

_PANEL_OUTER_STYLE = (
    "background: rgba(10,10,10,245);"
    "border: 1px solid rgba(255,255,255,18);"
    "border-radius: 10px;"
)


def _ext_badge(ext: str) -> str:
    color = _EXT_COLORS.get(ext, "#888888")
    return f'<span style="color:{color}; font-size:9px; font-weight:bold;">{ext[1:].upper()}</span>'


class _ItemWidget(QWidget):
    """Rich list row: title left, size + ext badge right."""
    def __init__(self, item: MediaItem, is_last_played: bool = False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = item.title
        if is_last_played:
            title = "▶  " + title

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {'#E8551F' if is_last_played else '#e0e0e0'}; "
            f"font-size: 12px; background: transparent;"
        )
        title_lbl.setWordWrap(False)
        layout.addWidget(title_lbl, 1)

        ext_color = _EXT_COLORS.get(item.extension, "#888888")
        meta = QLabel(f'<span style="color:{ext_color}; font-size:9px;">{item.extension[1:].upper()}</span>'
                      f'  <span style="color:#555; font-size:10px;">{item.size_mb:.0f} MB</span>')
        meta.setStyleSheet("background: transparent;")
        meta.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(meta)


class MediaLibraryPanel(QWidget):
    play_requested   = pyqtSignal(str)   # absolute path
    switch_requested = pyqtSignal()      # user wants to switch to Video Processor

    def __init__(self, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._items: list[MediaItem] = []
        self._selected: Optional[MediaItem] = None

        self.setStyleSheet(_PANEL_STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Outer container gets the rounded border so it reads as a floating card
        self.setStyleSheet(
            f"MediaLibraryPanel {{ {_PANEL_OUTER_STYLE} }}\n" + _PANEL_STYLE
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet("background: rgba(0,0,0,180);")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 6, 14, 6)
        hl.setSpacing(8)

        lib_lbl = QLabel("🎬  Media Library")
        lib_lbl.setStyleSheet("color:#ffffff; font-size:13px; font-weight:600; background:transparent;")
        hl.addWidget(lib_lbl)
        hl.addStretch()

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color:#555; font-size:11px; background:transparent;")
        hl.addWidget(self._count_lbl)
        root.addWidget(hdr)

        # ── Folder row ────────────────────────────────────────────────
        folder_bar = QWidget()
        folder_bar.setStyleSheet("background: rgba(18,18,18,200);")
        folder_bar.setFixedHeight(44)
        fl = QHBoxLayout(folder_bar)
        fl.setContentsMargins(12, 6, 12, 6)
        fl.setSpacing(6)

        self._folder_edit = QLineEdit(app_config.media_folder)
        self._folder_edit.setPlaceholderText("Choose a folder with your video files…")
        fl.addWidget(self._folder_edit, 1)

        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse)
        fl.addWidget(btn_browse)

        self._recursive_chk = QCheckBox("Subfolders")
        fl.addWidget(self._recursive_chk)

        btn_scan = QPushButton("Scan")
        btn_scan.clicked.connect(self._scan)
        fl.addWidget(btn_scan)
        root.addWidget(folder_bar)

        # ── Thin divider ──────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: rgba(255,255,255,12);")
        div.setFixedHeight(1)
        root.addWidget(div)

        # ── List ──────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setUniformItemSizes(False)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._list, 1)

        # ── Bottom bar ────────────────────────────────────────────────
        bottom = QWidget()
        bottom.setFixedHeight(56)
        bottom.setStyleSheet("background: rgba(0,0,0,180); border-top: 1px solid rgba(255,255,255,10);")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(12)

        self._info_lbl = QLabel("Select a title to play")
        self._info_lbl.setStyleSheet("color:#666; font-size:11px; background:transparent;")
        bl.addWidget(self._info_lbl, 1)

        # Switch mode button — takes user back to Video Processor (or opens first-run)
        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setObjectName("play")
        self._play_btn.setFixedWidth(160)
        self._play_btn.setEnabled(False)
        self._play_btn.setAutoDefault(False)
        self._play_btn.setDefault(False)
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.clicked.connect(self._on_play)
        bl.addWidget(self._play_btn)

        # Video Processor — the exit from the media library into live capture.
        # Replaces the old "Calibrate colour" button in this slot: calibration is a
        # maintenance task and this is the mode switch a user actually reaches for
        # from the picker. MainWindow owns the engine, so the panel only asks; the
        # confirmation, the playback stop and the capture start live there.
        self._vp_btn = QPushButton("🎥  Video Processor")
        self._vp_btn.setObjectName("videoProcessor")
        self._vp_btn.setFixedWidth(180)
        self._vp_btn.setEnabled(True)
        self._vp_btn.setAutoDefault(False)
        self._vp_btn.setDefault(False)
        self._vp_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vp_btn.clicked.connect(self._on_switch_to_vp)
        bl.addWidget(self._vp_btn)
        root.addWidget(bottom)

        # Auto-scan if folder was remembered
        if app_config.media_folder:
            self._scan()

    # ------------------------------------------------------------------

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Choose Media Folder",
            self._folder_edit.text() or str(Path.home())
        )
        if d:
            self._folder_edit.setText(d)
            self._app_config.media_folder = d
            self._scan()

    def _scan(self) -> None:
        folder = self._folder_edit.text().strip()
        if not folder:
            return
        self._app_config.media_folder = folder
        recursive = self._recursive_chk.isChecked()
        self._items = scan_folder(folder, recursive=recursive)
        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        last = self._app_config.last_played

        for item in self._items:
            is_last = (str(item.path) == last)
            row_widget = _ItemWidget(item, is_last_played=is_last)
            list_item = QListWidgetItem(self._list)
            list_item.setSizeHint(QSize(0, 36))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, row_widget)

        count = len(self._items)
        self._count_lbl.setText(f"{count} title{'s' if count != 1 else ''}")
        self._selected = None
        self._play_btn.setEnabled(False)
        self._info_lbl.setText(
            f"{count} titles found" if count else "No video files found in this folder."
        )

    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if not items:
            self._selected = None
            self._play_btn.setEnabled(False)
            self._info_lbl.setText("Select a title to play")
            return
        item: MediaItem = items[0].data(Qt.ItemDataRole.UserRole)
        self._selected = item
        self._play_btn.setEnabled(True)
        self._info_lbl.setText(
            f"{item.title}   ·   {item.extension[1:].upper()}   ·   {item.size_mb:.0f} MB"
        )

    def _on_double_click(self, _) -> None:
        self._on_play()

    def _on_play(self) -> None:
        if self._selected:
            self._app_config.last_played = str(self._selected.path)
            self.play_requested.emit(str(self._selected.path))

    def _on_switch_to_vp(self) -> None:
        """Route the Video Processor button to MainWindow (it owns the engine)."""
        try:
            _audit.info("media-lib: video processor button pressed")
            self.switch_requested.emit()
        except Exception as e:   # noqa: BLE001
            _audit.error("media-lib: video processor handler failed: %s", e)

    def show_message(self, text: str) -> None:
        """One-line status on the library footer (calibration results etc.)."""
        self._info_lbl.setText(text)

    def refresh_last_played(self) -> None:
        """Re-render the list to update the last-played indicator."""
        self._populate()


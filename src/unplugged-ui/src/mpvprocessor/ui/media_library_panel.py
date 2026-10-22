"""
Media library panel - shown on the main screen in Media Player mode.

A poster grid over the persistent library (media/library.py):

  [Movies] [TV Shows] [Folders]      breadcrumb        status   [Folders…] [Rescan]
  ┌────┐ ┌────┐ ┌────┐ ┌────┐
  │    │ │    │ │    │ │    │   posters; TV drills show > season > episode,
  └────┘ └────┘ └────┘ └────┘   Folders drills the library folders as they are on disk
  info line                                             [▶ Play] [Video Processor]

The grid is filled from the database at once and refreshed as the background
sync reports changes, so opening the app never waits on a disk or a NAS.

Remote/keyboard: arrows move, Enter opens or plays, Backspace/Esc goes back a level
(Esc at the top level is left to the main window).

Emits play_requested(path_str) to play and switch_requested() for Video Processor.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (Qt, pyqtSignal, QSize, QRect, QRectF, QTimer,
                          QAbstractListModel, QModelIndex, QEvent)
from PyQt6.QtGui import (QColor, QPainter, QFont, QPixmap, QLinearGradient, QPen,
                         QPainterPath, QKeyEvent)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListView,
    QStyledItemDelegate, QStyle, QFileDialog, QDialog, QListWidget, QAbstractItemView,
    QStackedLayout, QButtonGroup, QSizePolicy,
)

from ..config.model import AppConfig
from ..media.library import Library, Item

_audit = logging.getLogger("unplugged.audit")
_ORANGE = "#E8551F"

_PANEL_STYLE = """
QWidget { background: transparent; color: #e0e0e0; }
QListView { background: transparent; border: none; outline: none; }
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,40); border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QPushButton {
    background: rgba(50,50,50,220); border: 1px solid rgba(255,255,255,30);
    border-radius: 5px; color: #cccccc; padding: 7px 18px; outline: none;
}
QPushButton:hover { background: rgba(70,70,70,240); color: #ffffff; border-color: rgba(255,255,255,50); }
QPushButton:disabled { background: rgba(30,30,30,180); color: #555; border-color: rgba(255,255,255,10); }
QPushButton[tab="true"] { background: transparent; border: none; color: #888;
    font-size: 13px; font-weight: 600; padding: 6px 12px; border-radius: 0px;
    border-bottom: 2px solid transparent; }
QPushButton[tab="true"]:hover { color: #ddd; }
QPushButton[tab="true"]:checked { color: #ffffff; border-bottom: 2px solid #E8551F; }
"""

_PANEL_OUTER_STYLE = (
    "background: rgba(10,10,10,245);"
    "border: 1px solid rgba(255,255,255,18);"
    "border-radius: 10px;"
)

TAB_MOVIES, TAB_TV, TAB_FOLDERS = "movies", "tv", "folders"
_TAB_TITLES = {TAB_MOVIES: "Movies", TAB_TV: "TV Shows", TAB_FOLDERS: "Folders"}

# Entry kinds in the grid.
K_MOVIE, K_EPISODE, K_SHOW, K_SEASON, K_FOLDER = "movie", "episode", "show", "season", "folder"


class _Entry:
    __slots__ = ("kind", "title", "sub", "art", "key", "item", "ref")

    def __init__(self, kind, title, sub="", art="", key="", item: Item | None = None, ref=None):
        # item: the playable file (movies, episodes). ref: what a container opens
        # (a season number, a folder path).
        self.kind, self.title, self.sub, self.art, self.key, self.item, self.ref = (
            kind, title, sub, art, key, item, ref)


class _Model(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[_Entry] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return e.title
        if role == Qt.ItemDataRole.UserRole:
            return e
        return None

    def set_entries(self, entries: list[_Entry]) -> bool:
        """Returns False when only the contents changed (same tiles in the same
        order): that is updated in place, so posters arriving while the user
        browses do not move the selection or the scroll position."""
        if [e.key for e in entries] == [e.key for e in self.entries] and entries:
            self.entries = entries
            self.dataChanged.emit(self.index(0, 0), self.index(len(entries) - 1, 0))
            return False
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()
        return True


class _PixCache:
    """Decoded poster pixmaps, newest last. ~300 posters at grid size is ~60 MB."""

    def __init__(self, cap: int = 300):
        self.cap = cap
        self.d: dict[tuple[str, int, int], QPixmap] = {}

    def get(self, path: str, w: int, h: int) -> QPixmap | None:
        k = (path, w, h)
        pm = self.d.pop(k, None)
        if pm is None:
            src = QPixmap(path)
            if src.isNull():
                return None
            pm = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
            if len(self.d) >= self.cap:
                self.d.pop(next(iter(self.d)))
        self.d[k] = pm
        return pm

    def clear(self):
        self.d.clear()


def _placeholder_colors(title: str) -> tuple[QColor, QColor]:
    h = int(hashlib.md5(title.encode("utf-8", "replace")).hexdigest()[:6], 16)
    hue = h % 360
    return QColor.fromHsv(hue, 120, 90), QColor.fromHsv((hue + 40) % 360, 140, 35)


class _PosterDelegate(QStyledItemDelegate):
    TEXT_H = 44

    def __init__(self, panel: "MediaLibraryPanel"):
        super().__init__(panel)
        self.panel = panel
        self.cache = _PixCache()

    def sizeHint(self, option, index):
        return self.panel.grid_size()

    def paint(self, p: QPainter, option, index):
        e: _Entry = index.data(Qt.ItemDataRole.UserRole)
        if e is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect.adjusted(8, 8, -8, -6)
        poster = QRect(r.x(), r.y(), r.width(), r.height() - self.TEXT_H)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        last = isinstance(e.item, Item) and self.panel.is_last_played(e.item.path)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(poster), 6, 6)
        p.setClipPath(clip)
        pm = self.cache.get(e.art, poster.width(), poster.height()) if e.art else None
        if pm is not None:
            sx = max(0, (pm.width() - poster.width()) // 2)
            sy = max(0, (pm.height() - poster.height()) // 2)
            p.drawPixmap(poster, pm, QRect(sx, sy, poster.width(), poster.height()))
        else:
            self._placeholder(p, poster, e)
        if not (selected or hover):
            p.fillRect(poster, QColor(0, 0, 0, 40))
        p.setClipping(False)

        if e.kind == K_FOLDER:
            self._badge(p, poster, "\U0001F4C1")
        if last:
            self._badge(p, poster, "▶", QColor(_ORANGE))

        if selected:
            p.setPen(QPen(QColor(_ORANGE), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(poster).adjusted(1.5, 1.5, -1.5, -1.5), 6, 6)
        elif hover:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
            p.drawRoundedRect(QRectF(poster).adjusted(1, 1, -1, -1), 6, 6)

        tr = QRect(r.x(), poster.bottom() + 6, r.width(), 18)
        f = QFont(p.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(_ORANGE) if last else QColor("#ffffff" if selected else "#dddddd"))
        p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(e.title, Qt.TextElideMode.ElideRight, tr.width()))
        if e.sub:
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.Normal)
            p.setFont(f)
            p.setPen(QColor("#888888"))
            sr = tr.translated(0, 18)
            p.drawText(sr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(e.sub, Qt.TextElideMode.ElideRight, sr.width()))
        p.restore()

    def _placeholder(self, p: QPainter, rect: QRect, e: _Entry):
        top, bottom = _placeholder_colors(e.title)
        g = QLinearGradient(rect.topLeft().toPointF(), rect.bottomLeft().toPointF())
        g.setColorAt(0, top)
        g.setColorAt(1, bottom)
        p.fillRect(rect, g)
        f = QFont(p.font())
        f.setPixelSize(max(14, rect.width() // 9))
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(rect.adjusted(12, 12, -12, -12),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, e.title)

    def _badge(self, p: QPainter, poster: QRect, text: str, color=QColor(0, 0, 0, 170)):
        b = QRect(poster.right() - 34, poster.y() + 6, 28, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(b), 5, 5)
        p.setPen(QColor("#ffffff"))
        f = QFont(p.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(b, Qt.AlignmentFlag.AlignCenter, text)


class _Grid(QListView):
    back = pyqtSignal()
    open = pyqtSignal(QModelIndex)

    def keyPressEvent(self, ev: QKeyEvent):
        k = ev.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            idx = self.currentIndex()
            if idx.isValid():
                self.open.emit(idx)
            ev.accept()
            return
        if k in (Qt.Key.Key_Backspace, Qt.Key.Key_Back, Qt.Key.Key_Escape):
            if self.property("can_back"):
                self.back.emit()
                ev.accept()
                return
            ev.ignore()   # top level: let the main window have Esc
            return
        super().keyPressEvent(ev)


class FoldersDialog(QDialog):
    """Add/remove library folders."""

    def __init__(self, folders: list[str], unreachable: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library folders")
        self.setModal(True)
        self.setMinimumSize(560, 360)
        self.setStyleSheet(
            "QDialog { background: #141414; color: #e0e0e0; }"
            "QListWidget { background: #0c0c0c; border: 1px solid #333; color: #ddd; font-size: 13px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: rgba(232,85,31,110); }"
            "QLabel { color: #aaa; }" + _PANEL_STYLE)
        self._unreachable = {os.path.normcase(u) for u in unreachable}
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Unplugged looks in these folders and every folder inside them "
                             "for MKV and MP4 files."))
        self.list = QListWidget()
        for f in folders:
            self._add_row(f)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("Add folder…")
        add.clicked.connect(self._add)
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        row.addWidget(done)
        lay.addLayout(row)

    def _add_row(self, f: str):
        label = f + ("    (not reachable)" if os.path.normcase(f) in self._unreachable else "")
        it = self.list.addItem(label) or self.list.item(self.list.count() - 1)
        it.setData(Qt.ItemDataRole.UserRole, f)

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder to the library", str(Path.home()))
        if d:
            self._add_row(os.path.normpath(d))

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def folders(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]


class MediaLibraryPanel(QWidget):
    play_requested   = pyqtSignal(str)   # absolute path
    switch_requested = pyqtSignal()      # user wants to switch to Video Processor

    def __init__(self, app_config: AppConfig, parent=None, library: Library | None = None) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._selected: Optional[_Entry] = None
        self._tab = getattr(app_config, "library_tab", TAB_MOVIES) or TAB_MOVIES
        if self._tab not in _TAB_TITLES:
            self._tab = TAB_MOVIES
        # Drill-down stack per tab: TV [(show)], [(show, season)]; Folders [path...]
        self._path: list = []
        self._sync_msg = ""

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The outer rule must come AFTER the generic QWidget rule: both are type
        # selectors of equal weight, so the later one wins.
        self.setStyleSheet(_PANEL_STYLE + f"\nMediaLibraryPanel {{ {_PANEL_OUTER_STYLE} }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: tabs, breadcrumb, status, folder buttons ─────────────────
        hdr = QWidget()
        hdr.setObjectName("libHeader")
        hdr.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hdr.setFixedHeight(54)
        hdr.setStyleSheet("#libHeader { background: rgba(0,0,0,180); border-top-left-radius: 10px;"
                          "border-top-right-radius: 10px; }")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 6, 14, 0)
        hl.setSpacing(4)
        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        self._tab_btns = {}
        for key in (TAB_MOVIES, TAB_TV, TAB_FOLDERS):
            b = QPushButton(_TAB_TITLES[key])
            b.setProperty("tab", True)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self._set_tab(k))
            self._tabs.addButton(b)
            self._tab_btns[key] = b
            hl.addWidget(b)
        self._crumb = QLabel("")
        self._crumb.setStyleSheet("color:#bbb; font-size:13px; padding-left:14px;")
        # A long show name must not widen the panel.
        self._crumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(self._crumb, 1)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#777; font-size:11px; padding-right:8px;")
        hl.addWidget(self._status)
        self._folders_btn = QPushButton("Folders…")
        self._folders_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._folders_btn.clicked.connect(self._edit_folders)
        hl.addWidget(self._folders_btn)
        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rescan_btn.clicked.connect(self._rescan)
        hl.addWidget(self._rescan_btn)
        root.addWidget(hdr)

        # ── Grid / empty state ───────────────────────────────────────────────
        body = QWidget()
        self._stack = QStackedLayout(body)
        self._model = _Model(self)
        self._grid = _Grid()
        self._grid.setModel(self._model)
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setFlow(QListView.Flow.LeftToRight)
        self._grid.setWrapping(True)
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setUniformItemSizes(True)
        self._grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.verticalScrollBar().setSingleStep(24)
        self._grid.setMouseTracking(True)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._delegate = _PosterDelegate(self)
        self._grid.setItemDelegate(self._delegate)
        self._grid.selectionModel().currentChanged.connect(self._on_current)
        self._grid.doubleClicked.connect(self._open)
        self._grid.open.connect(self._open)
        self._grid.back.connect(self._back)
        self._stack.addWidget(self._grid)

        self._empty = QWidget()
        el = QVBoxLayout(self._empty)
        el.addStretch()
        self._empty_lbl = QLabel("")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet("color:#888; font-size:15px;")
        el.addWidget(self._empty_lbl)
        self._empty_btn = QPushButton("Add a folder…")
        self._empty_btn.clicked.connect(self._edit_folders)
        eb = QHBoxLayout()
        eb.addStretch()
        eb.addWidget(self._empty_btn)
        eb.addStretch()
        el.addLayout(eb)
        el.addStretch()
        self._stack.addWidget(self._empty)
        root.addWidget(body, 1)

        # ── Bottom bar ───────────────────────────────────────────────────────
        bottom = QWidget()
        bottom.setObjectName("libFooter")
        bottom.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bottom.setFixedHeight(56)
        bottom.setStyleSheet("#libFooter { background: rgba(0,0,0,180); "
                             "border-top: 1px solid rgba(255,255,255,10);"
                             "border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(12)
        self._info_lbl = QLabel("Select a title to play")
        self._info_lbl.setStyleSheet("color:#888; font-size:12px;")
        # The info line carries the full file path; it must elide, not widen the panel.
        self._info_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bl.addWidget(self._info_lbl, 1)
        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setObjectName("play")
        self._play_btn.setFixedWidth(160)
        self._play_btn.setEnabled(False)
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.clicked.connect(self._on_play)
        bl.addWidget(self._play_btn)
        # Video Processor - the exit from the media library into live capture.
        # MainWindow owns the engine, so the panel only asks.
        self._vp_btn = QPushButton("🎥  Video Processor")
        self._vp_btn.setObjectName("videoProcessor")
        self._vp_btn.setFixedWidth(180)
        self._vp_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vp_btn.clicked.connect(self._on_switch_to_vp)
        bl.addWidget(self._vp_btn)
        root.addWidget(bottom)

        # ── Library ──────────────────────────────────────────────────────────
        self._lib = library if library is not None else Library(parent=self)
        if library is None:
            if not getattr(app_config, "library_online_art", True):
                self._lib.omdb_key = ""
            elif getattr(app_config, "omdb_api_key", ""):
                self._lib.omdb_key = app_config.omdb_api_key
            self._lib.write_local = bool(getattr(app_config, "library_save_posters", True))
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._reload)
        self._lib.changed.connect(self._refresh_timer.start)
        self._lib.sync_state.connect(self._on_sync_state)

        # One-time migration from the single "media_folder" of 1.1.x.
        # No isdir() here: a NAS path could block the UI thread. The sync checks it.
        if self._lib.ok and not self._lib.roots() and app_config.media_folder:
            self._lib.set_roots([app_config.media_folder])

        self._tab_btns[self._tab].setChecked(True)
        self._reload()
        self._lib.sync()

    # ── public API used by MainWindow ────────────────────────────────────────
    def show_message(self, text: str) -> None:
        self._info_lbl.setText(text)

    def refresh_last_played(self) -> None:
        self._grid.viewport().update()

    def is_last_played(self, path: str) -> bool:
        last = self._app_config.last_played
        return bool(last) and os.path.normcase(last) == os.path.normcase(path)

    def shutdown(self) -> None:
        self._lib.stop()

    def grid_size(self) -> QSize:
        vw = max(300, self._grid.viewport().width())
        cols = max(3, vw // 210)
        w = vw // cols
        poster_h = int((w - 16) * 1.5)
        return QSize(w, poster_h + _PosterDelegate.TEXT_H + 14)

    # ── events ───────────────────────────────────────────────────────────────
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        QTimer.singleShot(0, self._relayout_grid)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._relayout_grid()
        self._grid.setFocus()

    def _relayout_grid(self) -> None:
        gs = self.grid_size()
        if self._grid.gridSize() != gs:
            self._grid.setGridSize(gs)
            self._delegate.cache.clear()

    # ── navigation ───────────────────────────────────────────────────────────
    def _set_tab(self, tab: str) -> None:
        if tab == self._tab and not self._path:
            return
        self._tab = tab
        self._path = []
        try:
            self._app_config.library_tab = tab
        except Exception:   # noqa: BLE001
            pass
        self._tab_btns[tab].setChecked(True)
        self._reload()

    def _back(self) -> None:
        if self._path:
            came_from = self._path.pop()
            # A one-season show opened straight onto its episodes; going back from
            # there returns to the show list, not to a screen with one season on it.
            if (self._tab == TAB_TV and isinstance(came_from, tuple) and self._path
                    and len(self._lib.seasons(self._path[-1])) == 1):
                came_from = self._path.pop()
            self._reload(select_key=self._entry_key_for(came_from))

    def _entry_key_for(self, level) -> str:
        if self._tab == TAB_TV:
            return f"season:{level[1]}" if isinstance(level, tuple) else f"show:{level}"
        return f"folder:{os.path.normcase(level)}"

    def _open(self, idx: QModelIndex) -> None:
        e: _Entry = idx.data(Qt.ItemDataRole.UserRole)
        if e is None:
            return
        if e.kind == K_SHOW:
            self._path.append(e.title)
            seasons = self._lib.seasons(e.title)
            if len(seasons) == 1:   # a one-season show goes straight to its episodes
                self._path.append((e.title, seasons[0][0]))
            self._reload()
        elif e.kind == K_SEASON:
            self._path.append((self._path[-1], e.ref))
            self._reload()
        elif e.kind == K_FOLDER:
            self._path.append(e.ref)
            self._reload()
        elif e.item is not None:
            self._selected = e
            self._on_play()

    # ── content ──────────────────────────────────────────────────────────────
    def _entries(self) -> tuple[list[_Entry], str]:
        lib = self._lib
        if self._tab == TAB_MOVIES:
            out = []
            for m in lib.movies():
                out.append(_Entry(K_MOVIE, m.title, str(m.year or ""), m.art,
                                  f"item:{os.path.normcase(m.path)}", m))
            return out, "Movies"
        if self._tab == TAB_TV:
            if not self._path:
                return [_Entry(K_SHOW, show, _plural(seasons, "season") if seasons > 1
                               else _plural(eps, "episode"), art, f"show:{show}")
                        for show, art, seasons, eps in lib.shows()], "TV Shows"
            level = self._path[-1]
            if isinstance(level, tuple):
                show, season = level
                out = []
                for ep in lib.episodes(show, season):
                    out.append(_Entry(K_EPISODE, ep.label, ep.extension[1:].upper(),
                                      ep.art or ep.season_art or ep.show_art,
                                      f"item:{os.path.normcase(ep.path)}", ep))
                return out, f"TV Shows  ›  {show}  ›  Season {season}"
            show = level
            out = []
            for season, art, eps in lib.seasons(show):
                out.append(_Entry(K_SEASON, f"Season {season}", _plural(eps, "episode"),
                                  art, f"season:{season}", ref=season))
            return out, f"TV Shows  ›  {show}"
        # Folders
        folder = self._path[-1] if self._path else None
        subs, files = lib.folder_view(folder)
        out = [_Entry(K_FOLDER, os.path.basename(p.rstrip("\\/")) or p, _plural(n, "title"),
                      art, f"folder:{os.path.normcase(p)}", ref=p) for p, art, n in subs]
        for f in files:
            label = f.label if f.kind == "movie" else f"{f.title} S{f.season or 0:02d}E{f.episode or 0:02d}"
            out.append(_Entry(K_MOVIE, label, f.extension[1:].upper(),
                              f.art or f.season_art or f.show_art,
                              f"item:{os.path.normcase(f.path)}", f))
        crumb = "Folders" + "".join(f"  ›  {os.path.basename(p.rstrip(chr(92)+'/')) or p}"
                                    for p in self._path)
        return out, crumb

    def _reload(self, select_key: str | None = None) -> None:
        explicit = select_key is not None
        cur = self._grid.currentIndex()
        if select_key is None and cur.isValid():
            e = cur.data(Qt.ItemDataRole.UserRole)
            select_key = e.key if e else None
        if select_key is None and self._app_config.last_played:
            select_key = f"item:{os.path.normcase(self._app_config.last_played)}"

        entries, crumb = self._entries()
        # A level that emptied (its folder removed, its show deleted) falls back.
        while not entries and self._path:
            self._path.pop()
            entries, crumb = self._entries()
        self._grid.setProperty("can_back", bool(self._path))
        self._crumb.setText(crumb if self._path else "")
        reset = self._model.set_entries(entries)
        if entries and not reset and not explicit:
            # Same tiles, new contents (a poster arrived): leave selection and scroll.
            self._on_current(self._grid.currentIndex())
            self._update_status()
            return

        if entries:
            row = next((i for i, e in enumerate(entries) if e.key == select_key), 0)
            idx = self._model.index(row, 0)
            self._grid.setCurrentIndex(idx)
            self._grid.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
            self._stack.setCurrentWidget(self._grid)
        else:
            self._selected = None
            self._play_btn.setEnabled(False)
            self._stack.setCurrentWidget(self._empty)
            if not self._lib.ok:
                self._empty_lbl.setText("The media library could not be opened.\n"
                                        "See Report a problem for details.")
                self._empty_btn.hide()
            elif not self._lib.roots():
                self._empty_lbl.setText("Add the folders that hold your films and shows.\n"
                                        "Unplugged keeps them in sync every time it starts.")
                self._empty_btn.show()
            elif self._lib.is_syncing():
                self._empty_lbl.setText("Looking for films and shows…")
                self._empty_btn.hide()
            else:
                what = {TAB_MOVIES: "films", TAB_TV: "TV episodes"}.get(self._tab, "MKV or MP4 files")
                self._empty_lbl.setText(f"No {what} found in your library folders.")
                self._empty_btn.hide()
        self._update_status()

    def _on_current(self, cur: QModelIndex, _prev=None) -> None:
        e: _Entry = cur.data(Qt.ItemDataRole.UserRole) if cur.isValid() else None
        self._selected = e
        if e is None:
            self._play_btn.setEnabled(False)
            self._info_lbl.setText("Select a title to play")
            return
        if isinstance(e.item, Item):
            it = e.item
            self._play_btn.setEnabled(True)
            name = it.label if it.kind == "movie" else f"{it.title}  ·  S{it.season or 0:02d}E{it.episode or 0:02d}"
            self._info_lbl.setText(f"{name}   ·   {it.extension[1:].upper()}   ·   "
                                   f"{_size(it.size)}   ·   {it.path}")
        else:
            self._play_btn.setEnabled(False)
            self._info_lbl.setText(f"{e.title}   ·   {e.sub}" if e.sub else e.title)

    def _on_sync_state(self, running: bool, msg: str) -> None:
        self._sync_msg = msg if running else ""
        self._rescan_btn.setEnabled(not running)
        if not running:
            self._refresh_timer.start()
        self._update_status()

    def _update_status(self) -> None:
        bits = []
        if self._sync_msg:
            bits.append(self._sync_msg)
        off = self._lib.unreachable_roots()
        if off:
            bits.append(f"Not reachable: {', '.join(os.path.basename(o.rstrip(chr(92))) or o for o in off)}")
        if not bits:
            n = self._lib.count()
            bits.append(_plural(n, "title") if n else "")
        self._status.setText("   ".join(b for b in bits if b))

    # ── actions ──────────────────────────────────────────────────────────────
    def _edit_folders(self) -> None:
        dlg = FoldersDialog(self._lib.roots(), self._lib.unreachable_roots(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.folders()
        if [os.path.normcase(f) for f in new] == [os.path.normcase(f) for f in self._lib.roots()]:
            return
        _audit.info("media-lib: folders set to %s", new)
        if not self._lib.set_roots(new):
            self.show_message("Could not save the library folders - please try again")
            return
        self._app_config.media_folder = new[0] if new else ""
        self._path = []
        self._reload()
        self._lib.sync()

    def _rescan(self) -> None:
        _audit.info("media-lib: rescan pressed")
        self._lib.sync()

    def _on_play(self) -> None:
        e = self._selected
        if e is not None and isinstance(e.item, Item):
            self._app_config.last_played = e.item.path
            self.play_requested.emit(e.item.path)

    def _on_switch_to_vp(self) -> None:
        """Route the Video Processor button to MainWindow (it owns the engine)."""
        try:
            _audit.info("media-lib: video processor button pressed")
            self.switch_requested.emit()
        except Exception as e:   # noqa: BLE001
            _audit.error("media-lib: video processor handler failed: %s", e)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _size(n: int) -> str:
    gb = n / (1024 ** 3)
    return f"{gb:.1f} GB" if gb >= 1 else f"{n / (1024 ** 2):.0f} MB"

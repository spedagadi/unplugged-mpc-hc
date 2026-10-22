"""
Persistent media library: an SQLite index of the user's video folders plus a cache
of grid-sized poster images, kept in step with the disk by a background sync.

Files
  %LOCALAPPDATA%\\Unplugged\\library\\library.db   the index
  %LOCALAPPDATA%\\Unplugged\\library\\art\\         poster thumbnails (JPEG)

Startup contract
  * The grid is filled from the database immediately. Nothing waits on the disk.
  * A sync then walks every library folder on a background thread and reports
    changes as it goes. New and changed files get a title and artwork; files that
    are gone are marked missing, not deleted.
  * A folder that cannot be reached (NAS asleep, USB drive unplugged) is skipped
    whole, so its titles keep their artwork and come back the moment it returns.
    Titles missing for MISSING_PURGE_DAYS are then removed.

Nothing in here may take playback down with it: every failure is logged and the
library degrades to "no artwork" or "empty", never to an exception in the UI.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from . import artwork, omdb
from .name_parse import parse
from .scanner import VIDEO_EXTENSIONS

_log = logging.getLogger("unplugged.audit")

SCHEMA_VERSION = 1
MISSING_PURGE_DAYS = 30
MAX_DEPTH = 10

# Plex/Jellyfin "extras" folders and the scene-release sample. Showing them as
# films would bury the real titles under trailers and featurettes. Kept to names
# nobody uses for a folder of films ("Other" or "Shorts" could be one).
_SKIP_DIRS = {
    "system volume information", "$recycle.bin", "recycler", "windows",
    "program files", "program files (x86)", "programdata", "appdata",
    "extras", "featurettes", "behind the scenes", "deleted scenes",
    "trailers", "sample", "samples",
}
_SKIP_SUFFIXES = ("-trailer", "-sample", "-featurette", "-behindthescenes",
                  "-deleted", "-interview", ".sample")
_HIDDEN_OR_SYSTEM = 0x2 | 0x4
# Bump when name_parse changes: the next sync re-titles every file once.
PARSER_VERSION = "1"
# Art keys of downloaded posters end with this; see _keep_online.
_ONLINE_TAG = "|omdb"
# OMDb's free tier allows 1,000 requests a day. Stay under it so a large first
# sync finishes over a few days instead of tripping the limit, and leave room for
# anything else using the same key.
OMDB_DAILY_REQUESTS = 900
# A title OMDb did not know is asked again after this long (new releases get added).
OMDB_RETRY_DAYS = 7


def library_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Unplugged" / "library"


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


@dataclass
class Item:
    id: int
    path: str
    folder: str
    size: int
    present: bool
    kind: str
    title: str
    year: int | None
    season: int | None
    episode: int | None
    episode_title: str
    show_folder: str
    art: str
    season_art: str
    show_art: str
    watched: bool
    last_pos: float

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)

    @property
    def extension(self) -> str:
        return os.path.splitext(self.path)[1].lower()

    @property
    def label(self) -> str:
        if self.kind == "episode":
            return f"{self.episode:02d}. {self.episode_title}" if self.episode_title \
                else f"Episode {self.episode}"
        return f"{self.title} ({self.year})" if self.year else self.title


_COLS = ("id, path, folder, size, present, kind, title, year, season, episode, "
         "episode_title, show_folder, art, season_art, show_art, watched, last_pos")


def _item(row) -> Item:
    return Item(row[0], row[1], row[2], row[3] or 0, bool(row[4]), row[5] or "movie",
                row[6] or "", row[7], row[8], row[9], row[10] or "", row[11] or "",
                row[12] or "", row[13] or "", row[14] or "", bool(row[15]),
                float(row[16] or 0))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS roots (pkey TEXT PRIMARY KEY, path TEXT NOT NULL,
    added_at REAL, last_sync REAL, reachable INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    pkey TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    root TEXT NOT NULL,
    folder TEXT NOT NULL,
    size INTEGER, mtime REAL,
    present INTEGER DEFAULT 1, missing_since REAL, added_at REAL,
    kind TEXT, title TEXT, year INTEGER, season INTEGER, episode INTEGER,
    episode_title TEXT, show_folder TEXT,
    art TEXT, art_key TEXT,
    season_art TEXT, season_art_key TEXT,
    show_art TEXT, show_art_key TEXT,
    embedded_checked TEXT,
    watched INTEGER DEFAULT 0, last_pos REAL DEFAULT 0,
    imdb_id TEXT, overview TEXT, meta_checked REAL
);
CREATE INDEX IF NOT EXISTS items_root ON items(root);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind, title);
CREATE TABLE IF NOT EXISTS shows_online (tkey TEXT PRIMARY KEY, imdb_id TEXT,
    art TEXT, art_key TEXT, checked REAL);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=10)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        # A non-database file fails here; the handle must not stay open or the
        # file stays locked and cannot be moved aside.
        con.close()
        raise
    return con


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open (creating or migrating) the index. A file that is not a usable database
    is moved aside and rebuilt: the index is a cache of the disk, so losing it costs
    one rescan, while refusing to start would cost the user their player."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = None
    try:
        con = _connect(db_path)
        con.executescript(_SCHEMA)
        con.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as e:
        _log.error("library: database unusable (%s) - rebuilding", e)
        if con is not None:
            try:
                con.close()
            except Exception:   # noqa: BLE001
                pass
        bad = db_path.with_suffix(f".corrupt-{int(time.time())}")
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                os.replace(p, Path(str(bad) + suffix))
        con = _connect(db_path)
        con.executescript(_SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    con.commit()
    return con


class Library(QObject):
    """Main-thread facade. Queries read the database; sync() starts the worker."""

    changed = pyqtSignal()                 # rows were added/updated/removed
    sync_state = pyqtSignal(bool, str)     # running, human-readable status

    def __init__(self, base_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.base = base_dir or library_dir()
        self.db_path = self.base / "library.db"
        self.art_dir = self.base / "art"
        self._con: sqlite3.Connection | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._again = False
        self._lock = threading.Lock()
        # Online posters: empty key = off. write_local saves each downloaded poster
        # beside the media (Kodi/Plex/Jellyfin names) so it survives a reinstall and
        # other players see it; a read-only folder falls back to the cache.
        self.omdb_key = omdb.default_key()
        self.write_local = True
        try:
            self._con = open_db(self.db_path)
        except Exception as e:   # noqa: BLE001
            _log.error("library: cannot open %s: %s", self.db_path, e)

    @property
    def ok(self) -> bool:
        return self._con is not None

    # ── roots ───────────────────────────────────────────────────────────────
    def roots(self) -> list[str]:
        if not self._con:
            return []
        return [r[0] for r in self._con.execute("SELECT path FROM roots ORDER BY path")]

    def unreachable_roots(self) -> list[str]:
        if not self._con:
            return []
        return [r[0] for r in self._con.execute(
            "SELECT path FROM roots WHERE reachable = 0 ORDER BY path")]

    def set_roots(self, paths: list[str]) -> bool:
        """Replace the folder list. A removed folder's titles go immediately: that
        was a user decision, unlike a drive that merely went away. False if the
        database could not be written (the old list stays)."""
        if not self._con:
            return False
        want = {}
        for p in paths:
            p = os.path.normpath(p.strip())
            if p and _key(p) not in want:
                want[_key(p)] = p
        # A folder inside another library folder is already covered by it.
        keys = sorted(want, key=len)
        kept = {}
        for k in keys:
            if not any(k.startswith(o.rstrip("\\") + "\\") for o in kept):
                kept[k] = want[k]
        try:
            with self._con:
                have = {r[0] for r in self._con.execute("SELECT pkey FROM roots")}
                for k in have - kept.keys():
                    self._con.execute("DELETE FROM roots WHERE pkey = ?", (k,))
                    self._con.execute("DELETE FROM items WHERE root = ?", (k,))
                for k, p in kept.items():
                    self._con.execute(
                        "INSERT INTO roots (pkey, path, added_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(pkey) DO UPDATE SET path = excluded.path",
                        (k, p, time.time()))
        except sqlite3.Error as e:
            _log.error("library: cannot save folders: %s", e)
            return False
        self.changed.emit()
        return True

    # ── queries (main thread) ───────────────────────────────────────────────
    def _q(self, sql: str, args=()) -> list[Item]:
        if not self._con:
            return []
        try:
            return [_item(r) for r in self._con.execute(sql, args)]
        except sqlite3.Error as e:
            _log.error("library: query failed: %s", e)
            return []

    def count(self) -> int:
        if not self._con:
            return 0
        try:
            return self._con.execute(
                "SELECT COUNT(*) FROM items WHERE present = 1").fetchone()[0]
        except sqlite3.Error:
            return 0

    def movies(self) -> list[Item]:
        return self._q(f"SELECT {_COLS} FROM items WHERE present = 1 AND kind = 'movie' "
                       "ORDER BY title COLLATE NOCASE, year")

    def shows(self) -> list[tuple[str, str, int, int]]:
        """(show, poster, seasons, episodes) for each TV show."""
        if not self._con:
            return []
        rows = self._con.execute(
            "SELECT title, MAX(show_art), COUNT(DISTINCT season), COUNT(*), "
            "MAX(season_art) FROM items "
            "WHERE present = 1 AND kind = 'episode' GROUP BY title COLLATE NOCASE "
            "ORDER BY title COLLATE NOCASE").fetchall()
        return [(r[0], r[1] or r[4] or "", r[2], r[3]) for r in rows]

    def seasons(self, show: str) -> list[tuple[int, str, int]]:
        """(season, poster, episodes) for one show."""
        if not self._con:
            return []
        rows = self._con.execute(
            "SELECT season, MAX(season_art), MAX(show_art), COUNT(*) FROM items "
            "WHERE present = 1 AND kind = 'episode' AND title = ? COLLATE NOCASE "
            "GROUP BY season ORDER BY season", (show,)).fetchall()
        return [(r[0], r[1] or r[2] or "", r[3]) for r in rows]

    def episodes(self, show: str, season: int) -> list[Item]:
        return self._q(f"SELECT {_COLS} FROM items WHERE present = 1 AND kind = 'episode' "
                       "AND title = ? COLLATE NOCASE AND season = ? ORDER BY episode",
                       (show, season))

    def folder_view(self, folder: str | None) -> tuple[list[tuple[str, str, int]], list[Item]]:
        """Browse by folder. None = the library folders themselves.
        Returns (subfolders as (path, poster, count), files directly in folder)."""
        if not self._con:
            return [], []
        if folder is None:
            out = []
            for k, p in self._con.execute("SELECT pkey, path FROM roots ORDER BY path"):
                n, art = self._con.execute(
                    "SELECT COUNT(*), MAX(art) FROM items WHERE present = 1 AND root = ?",
                    (k,)).fetchone()
                out.append((p, art or "", n))
            return out, []
        fk = _key(folder)
        prefix = fk.rstrip("\\") + "\\"
        subs: dict[str, list] = {}
        files: list[Item] = []
        for it in self._q(f"SELECT {_COLS} FROM items WHERE present = 1 ORDER BY path"):
            ik = _key(it.folder)
            if ik == fk:
                files.append(it)
            elif ik.startswith(prefix):
                # normcase only folds case and slashes, so offsets match the real path.
                child = it.folder[len(prefix):].split("\\", 1)[0]
                e = subs.setdefault(child.lower(), [os.path.join(folder, child), "", 0])
                e[2] += 1
                art = (it.show_art or it.season_art) if it.kind == "episode" else it.art
                if not e[1] and art:
                    e[1] = art
        files.sort(key=lambda i: (i.season or 0, i.episode or 0, i.title.lower()))
        return sorted((tuple(v) for v in subs.values()), key=lambda t: t[0].lower()), files

    # ── sync ────────────────────────────────────────────────────────────────
    def sync(self) -> None:
        """Start a background sync. If one is running, run once more after it so
        a folder added mid-sync is not missed."""
        if not self._con:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._again = True
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="library-sync",
                                            daemon=True)
            self._thread.start()

    def is_syncing(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self, wait: float = 0.0) -> None:
        self._stop.set()
        t = self._thread
        if t and wait > 0:
            t.join(wait)

    def _run(self) -> None:
        while True:
            try:
                _Sync(self).run()
            except Exception as e:   # noqa: BLE001
                _log.exception("library: sync failed: %s", e)
                self.sync_state.emit(False, "Library scan failed - see the log")
            with self._lock:
                if not self._again or self._stop.is_set():
                    self._thread = None
                    return
                self._again = False


class _Sync:
    """One pass over every library folder, on the worker thread."""

    BATCH = 50

    def __init__(self, lib: Library) -> None:
        self.lib = lib
        self.con = _connect(lib.db_path)
        self.art_dir = lib.art_dir
        self.stop = lib._stop
        self.pending = 0
        self.added = self.updated = self.missing = 0
        row = self.con.execute("SELECT value FROM meta WHERE key = 'parser'").fetchone()
        self.reparse = (row[0] if row else None) != PARSER_VERSION

    def emit_changed(self, force: bool = False) -> None:
        if self.pending and (force or self.pending >= self.BATCH):
            self.con.commit()
            self.pending = 0
            self.lib.changed.emit()

    def run(self) -> None:
        try:
            t0 = time.time()
            roots = self.con.execute("SELECT pkey, path FROM roots").fetchall()
            self.lib.sync_state.emit(True, "Updating library…")
            for rkey, rpath in roots:
                if self.stop.is_set():
                    return
                self.sync_root(rkey, rpath)
            # Titles indexed under a folder the user removed while this pass ran.
            n = self.con.execute(
                "DELETE FROM items WHERE root NOT IN (SELECT pkey FROM roots)").rowcount
            if n:
                self.pending += n
            self.purge()
            if not self.stop.is_set():
                self.con.execute("INSERT OR REPLACE INTO meta VALUES ('parser', ?)",
                                 (PARSER_VERSION,))
            self.emit_changed(force=True)
            self.con.commit()
            _log.info("library: sync done in %.1fs - %d new, %d updated, %d missing",
                      time.time() - t0, self.added, self.updated, self.missing)
            try:
                self.online()
            except Exception as e:   # noqa: BLE001 - posters are optional, the library is not
                _log.exception("library: online posters failed: %s", e)
            self.con.commit()
            self.gc_art()
            self.lib.sync_state.emit(False, "")
        finally:
            self.con.close()

    # ── walking ─────────────────────────────────────────────────────────────
    def sync_root(self, rkey: str, rpath: str) -> None:
        try:
            reachable = os.path.isdir(rpath)
        except OSError:
            reachable = False
        self.con.execute("UPDATE roots SET reachable = ?, last_sync = ? WHERE pkey = ?",
                         (1 if reachable else 0, time.time(), rkey))
        # Never hold the write lock across filesystem work: the UI thread writes
        # too (set_roots) and would block on it.
        self.con.commit()
        if not reachable:
            _log.warning("library: %s not reachable - keeping its titles", rpath)
            self.lib.changed.emit()
            return

        existing = {r[0]: r for r in self.con.execute(
            "SELECT pkey, size, mtime, art_key, season_art_key, show_art_key, "
            "embedded_checked, present, art, season_art, show_art FROM items WHERE root = ?",
            (rkey,))}
        seen: set[str] = set()
        images: dict[str, dict[str, str]] = {}   # dir key -> {lower name: real name}
        complete = self.walk(rpath, rkey, existing, seen, images)

        if complete and not self.stop.is_set():
            # Only a walk that finished may declare files missing: a folder that
            # errored part-way must not cost its titles.
            now = time.time()
            for k, row in existing.items():
                if k not in seen and row[7]:
                    self.con.execute("UPDATE items SET present = 0, missing_since = ? "
                                     "WHERE pkey = ?", (now, k))
                    self.missing += 1
                    self.pending += 1
        self.emit_changed(force=True)

    def walk(self, root: str, rkey: str, existing, seen, images) -> bool:
        complete = True
        stack = [(root, 0)]
        while stack:
            if self.stop.is_set():
                return False
            d, depth = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError as e:
                _log.warning("library: cannot list %s: %s", d, e)
                complete = False
                continue
            names: dict[str, str] = {}
            videos = []
            for e in entries:
                n = e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth >= MAX_DEPTH or n.startswith((".", "$")) \
                                or n.lower() in _SKIP_DIRS:
                            continue
                        st = e.stat(follow_symlinks=False)
                        if getattr(st, "st_file_attributes", 0) & _HIDDEN_OR_SYSTEM:
                            continue
                        stack.append((e.path, depth + 1))
                        continue
                    ext = os.path.splitext(n)[1].lower()
                    if ext in artwork.IMAGE_EXTS:
                        names[n.lower()] = n
                    elif ext in VIDEO_EXTENSIONS:
                        stem = os.path.splitext(n)[0].lower()
                        if stem == "sample" or stem.endswith(_SKIP_SUFFIXES):
                            continue
                        videos.append(e)
                except OSError:
                    # Unreadable entry: this pass cannot vouch for what is missing.
                    complete = False
                    continue
            images[_key(d)] = names
            for e in videos:
                if self.stop.is_set():
                    return False
                try:
                    self.index(e, d, rkey, existing, seen, images, len(videos))
                except Exception as ex:   # noqa: BLE001 - one bad file must not stop the scan
                    _log.warning("library: skipped %s: %s", e.path, ex)
                    seen.add(_key(e.path))
        return complete

    # ── one file ────────────────────────────────────────────────────────────
    def index(self, e, folder: str, rkey: str, existing, seen, images, n_videos: int) -> None:
        pkey = _key(e.path)
        seen.add(pkey)
        st = e.stat()
        size, mtime = st.st_size, st.st_mtime
        row = existing.get(pkey)
        changed = row is None or row[1] != size or abs((row[2] or 0) - mtime) > 1

        p = parse(e.path)
        names = images.get(_key(folder), {})
        stem = os.path.splitext(e.name)[0]

        # Folders that hold the title's art.
        parent = os.path.dirname(folder)
        if p.kind == "episode":
            in_season_dir = p.season is not None and _is_season_dir(os.path.basename(folder))
            show_folder = parent if in_season_dir else folder
        else:
            in_season_dir = False
            show_folder = ""

        # Item art: a sidecar always; the folder poster only when the folder is this
        # film's own (one film inside), or it would paint every film in "Movies" alike.
        art_src = artwork.sidecar_art(stem, names)
        if not art_src and p.kind == "movie" and n_videos == 1:
            art_src = artwork.folder_art(names)
        art_src_path = os.path.join(folder, art_src) if art_src else ""
        changed = changed or self.reparse

        season_src = show_src = ""
        if p.kind == "episode":
            show_names = images.get(_key(show_folder))
            if show_names is None:
                show_names = _list_images(show_folder)
                images[_key(show_folder)] = show_names
            if _folder_names_show(show_folder, p.title):
                s = artwork.folder_art(show_names)
                show_src = os.path.join(show_folder, s) if s else ""
            s = artwork.season_art(p.season or 0, show_names)
            if s:
                season_src = os.path.join(show_folder, s)
            elif in_season_dir:
                s = artwork.folder_art(names)
                season_src = os.path.join(folder, s) if s else ""

        if art_src_path:
            art, art_key = self.thumb(art_src_path, row[3] if row else None,
                                      row[8] if row else "")
            embedded_checked = row[6] if row else None
        else:
            # Embedded cover: read the file only when it is new or changed, and
            # remember the answer either way so an unchanged file is never re-read.
            # A previous answer counts only if it WAS the embedded one: a sidecar
            # poster that has since been deleted must not live on in the grid.
            ident = f"{size}|{int(mtime)}"
            prev = (row is not None and not changed and row[6] == ident
                    and (not row[8] or os.path.exists(row[8])))
            if prev and (not row[3] or row[3].endswith(("|embedded", _ONLINE_TAG))):
                art, art_key = row[8] or "", row[3] or ""
            else:
                art, art_key = self.embedded(e.path, ident)
                if not art:
                    art, art_key = _keep_online(row, 3, 8)
            embedded_checked = ident
        season_art, season_key = self.thumb(season_src, row[4] if row else None,
                                            row[9] if row else "")
        show_art, show_key = self.thumb(show_src, row[5] if row else None,
                                        row[10] if row else "")
        if not show_art and p.kind == "episode":
            show_art, show_key = _keep_online(row, 5, 10)

        values = (e.path, rkey, folder, size, mtime, p.kind, p.title, p.year, p.season,
                  p.episode, p.episode_title, show_folder, art, art_key, season_art,
                  season_key, show_art, show_key, embedded_checked)
        if row is None:
            self.con.execute(
                "INSERT INTO items (path, root, folder, size, mtime, kind, title, year, "
                "season, episode, episode_title, show_folder, art, art_key, season_art, "
                "season_art_key, show_art, show_art_key, embedded_checked, pkey, present, "
                "added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                values + (pkey, time.time()))
            self.added += 1
            self.pending += 1
        else:
            if (not changed and row[7] and (row[3] or "") == art_key
                    and (row[4] or "") == season_key and (row[5] or "") == show_key
                    and (row[8] or "") == art and (row[9] or "") == season_art
                    and (row[10] or "") == show_art):
                return
            self.con.execute(
                "UPDATE items SET path=?, root=?, folder=?, size=?, mtime=?, kind=?, title=?, "
                "year=?, season=?, episode=?, episode_title=?, show_folder=?, art=?, "
                "art_key=?, season_art=?, season_art_key=?, show_art=?, show_art_key=?, "
                "embedded_checked=?, present=1, missing_since=NULL WHERE pkey=?",
                values + (pkey,))
            self.updated += 1
            self.pending += 1
        self.con.commit()
        self.emit_changed()

    def thumb(self, src: str, old_key: str | None, old_art: str) -> tuple[str, str]:
        """Cached thumbnail for an image file, keyed by path + mtime + size so an
        edited poster is picked up and an unchanged one is never re-encoded."""
        if not src:
            return "", ""
        try:
            st = os.stat(src)
        except OSError:
            return "", ""
        key = f"{_key(src)}|{int(st.st_mtime)}|{st.st_size}"
        if key == old_key and old_art and os.path.exists(old_art):
            return old_art, key
        dest = self.art_dir / artwork.cache_name(key)
        if dest.exists() or artwork.make_thumb(src, dest):
            return str(dest), key
        return "", ""

    def embedded(self, path: str, ident: str) -> tuple[str, str]:
        key = f"{_key(path)}|{ident}|embedded"
        dest = self.art_dir / artwork.cache_name(key)
        if dest.exists():
            return str(dest), key
        data = artwork.embedded_cover(path)
        if data and artwork.make_thumb(data, dest):
            return str(dest), key
        return "", ""

    # ── online posters (OMDb) ───────────────────────────────────────────────
    def _budget(self) -> int:
        day = time.strftime("%Y-%m-%d")
        rows = dict(self.con.execute(
            "SELECT key, value FROM meta WHERE key IN ('omdb_day', 'omdb_used')").fetchall())
        used = int(rows.get("omdb_used", "0")) if rows.get("omdb_day") == day else 0
        return max(0, OMDB_DAILY_REQUESTS - used)

    def _spend(self, n: int) -> None:
        day = time.strftime("%Y-%m-%d")
        left = self._budget()
        used = OMDB_DAILY_REQUESTS - left + n
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('omdb_day', ?)", (day,))
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('omdb_used', ?)", (str(used),))
        self.con.commit()

    def online(self) -> None:
        key = self.lib.omdb_key
        if not key or self.stop.is_set():
            return
        self._apply_known_show_art()
        retry = time.time() - OMDB_RETRY_DAYS * 86400
        movies = self.con.execute(
            "SELECT id, pkey, path, folder, title, year FROM items "
            "WHERE present = 1 AND kind = 'movie' AND COALESCE(art, '') = '' "
            "AND (meta_checked IS NULL OR meta_checked < ?) "
            "ORDER BY added_at DESC", (retry,)).fetchall()
        checked = {r[0]: r[1] for r in self.con.execute(
            "SELECT tkey, checked FROM shows_online")}
        shows = []
        for (title,) in self.con.execute(
                "SELECT title FROM items WHERE present = 1 AND kind = 'episode' "
                "GROUP BY title COLLATE NOCASE HAVING MAX(COALESCE(show_art, '')) = ''"
                ).fetchall():
            if (checked.get(title.lower()) or 0) >= retry:
                continue
            folders = [f for (f,) in self.con.execute(
                "SELECT DISTINCT show_folder FROM items WHERE present = 1 AND kind = 'episode' "
                "AND title = ? COLLATE NOCASE", (title,)) if f]
            own = [f for f in folders if _folder_names_show(f, title)]
            shows.append((title, own[0] if own else ""))
        total = len(movies) + len(shows)
        if not total:
            return
        _log.info("library: fetching posters for %d movies, %d shows", len(movies), len(shows))
        done = 0
        for row in movies:
            if self.stop.is_set() or not self._fetch_movie(key, row):
                break
            done += 1
            self.lib.sync_state.emit(True, f"Fetching posters… {done}/{total}")
        else:
            for title, folder in shows:
                if self.stop.is_set() or not self._fetch_show(key, title, folder or ""):
                    break
                done += 1
                self.lib.sync_state.emit(True, f"Fetching posters… {done}/{total}")
        _log.info("library: posters - %d of %d looked up", done, total)

    def _lookup(self, key: str, title: str, year, kind: str):
        """omdb.lookup within the daily budget. None = stop for this sync."""
        if self._budget() < 3:
            _log.info("library: OMDb daily allowance used - continuing tomorrow")
            return None
        spent = [0]
        try:
            r = omdb.lookup(key, title, year, kind, spent)
        finally:
            self._spend(spent[0])
        if isinstance(r, omdb.Abort):
            _log.warning("library: OMDb stopped: %s", r.reason)
            if "limit" in r.reason.lower():
                self._spend(OMDB_DAILY_REQUESTS)
            return None
        return r

    def _store(self, data: bytes, local_path: str, cache_key: str) -> tuple[str, str]:
        """Save beside the media when allowed (never over an existing file), else
        in the cache only. Returns (thumbnail, art key)."""
        if self.lib.write_local and local_path and not os.path.exists(local_path):
            tmp = local_path + ".unplugged-tmp"
            try:
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, local_path)
                art, k = self.thumb(local_path, None, "")
                if art:
                    _log.info("library: saved poster %s", local_path)
                    return art, k
            except OSError as e:
                _log.info("library: cannot write %s (%s) - keeping it in the cache", local_path, e)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        dest = self.art_dir / artwork.cache_name(cache_key)
        if artwork.make_thumb(data, dest):
            return str(dest), cache_key
        return "", ""

    def _fetch_movie(self, key: str, row) -> bool:
        item_id, pkey, path, folder, title, year = row
        r = self._lookup(key, title, year, "movie")
        if r is None:
            return False
        now = time.time()
        if r is omdb.NOT_FOUND:
            _log.info("library: OMDb has no film %r (%s)", title, year)
            self.con.execute("UPDATE items SET meta_checked = ? WHERE id = ?", (now, item_id))
            self.con.commit()
            return True
        data = omdb.poster(key, r)
        if isinstance(data, omdb.Abort):
            _log.warning("library: poster download stopped: %s", data.reason)
            return False
        art = art_key = ""
        if data:
            stem = os.path.splitext(os.path.basename(path))[0]
            local = os.path.join(folder, stem + "-poster" + _img_ext(data))
            art, art_key = self._store(data, local, f"{pkey}|{r.imdb_id}{_ONLINE_TAG}")
        self.con.execute(
            "UPDATE items SET art = CASE WHEN ? <> '' THEN ? ELSE art END, "
            "art_key = CASE WHEN ? <> '' THEN ? ELSE art_key END, "
            "imdb_id = ?, overview = ?, meta_checked = ? WHERE id = ?",
            (art, art, art, art_key, r.imdb_id, r.plot, now, item_id))
        self.con.commit()
        self.lib.changed.emit()
        time.sleep(0.1)
        return True

    def _fetch_show(self, key: str, title: str, folder: str) -> bool:
        r = self._lookup(key, title, None, "series")
        if r is None:
            return False
        now = time.time()
        tkey = title.lower()
        art = art_key = ""
        imdb_id = ""
        if r is not omdb.NOT_FOUND:
            imdb_id = r.imdb_id
            data = omdb.poster(key, r)
            if isinstance(data, omdb.Abort):
                _log.warning("library: poster download stopped: %s", data.reason)
                return False
            if data:
                # Only the show's own folder gets a poster.jpg; a shared "TV" folder
                # would show it for every series in it.
                local = (os.path.join(folder, "poster" + _img_ext(data))
                         if folder and _folder_names_show(folder, title) else "")
                art, art_key = self._store(data, local, f"show:{tkey}|{imdb_id}{_ONLINE_TAG}")
        else:
            _log.info("library: OMDb has no series %r", title)
        self.con.execute("INSERT OR REPLACE INTO shows_online VALUES (?, ?, ?, ?, ?)",
                         (tkey, imdb_id, art, art_key, now))
        if art:
            self.con.execute(
                "UPDATE items SET show_art = ?, show_art_key = ? WHERE kind = 'episode' "
                "AND title = ? COLLATE NOCASE AND COALESCE(show_art, '') = ''",
                (art, art_key, title))
        self.con.commit()
        if art:
            self.lib.changed.emit()
        time.sleep(0.1)
        return True

    def _apply_known_show_art(self) -> None:
        """New episodes of a show whose poster was already fetched get it with no
        request at all."""
        n = 0
        for tkey, art, art_key in self.con.execute(
                "SELECT tkey, art, art_key FROM shows_online WHERE COALESCE(art, '') <> ''"
                ).fetchall():
            if os.path.exists(art):
                n += self.con.execute(
                    "UPDATE items SET show_art = ?, show_art_key = ? WHERE kind = 'episode' "
                    "AND title = ? COLLATE NOCASE AND COALESCE(show_art, '') = ''",
                    (art, art_key, tkey)).rowcount
        if n:
            self.con.commit()
            self.lib.changed.emit()

    # ── housekeeping ────────────────────────────────────────────────────────
    def purge(self) -> None:
        cutoff = time.time() - MISSING_PURGE_DAYS * 86400
        n = self.con.execute("DELETE FROM items WHERE present = 0 AND missing_since < ?",
                             (cutoff,)).rowcount
        if n:
            _log.info("library: removed %d titles missing for %d days", n, MISSING_PURGE_DAYS)
            self.pending += 1

    def gc_art(self) -> None:
        """Delete cached thumbnails no title refers to any more."""
        if self.stop.is_set() or not self.art_dir.is_dir():
            return
        used = set()
        for row in self.con.execute("SELECT art, season_art, show_art FROM items"):
            used.update(os.path.basename(a) for a in row if a)
        for f in self.art_dir.iterdir():
            if f.suffix in (".jpg", ".tmp") and f.name not in used:
                try:
                    f.unlink()
                except OSError:
                    pass


def _img_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _keep_online(row, key_i: int, art_i: int) -> tuple[str, str]:
    """A downloaded poster outlives syncs: the disk has nothing to replace it with."""
    if row is not None and (row[key_i] or "").endswith(_ONLINE_TAG) \
            and row[art_i] and os.path.exists(row[art_i]):
        return row[art_i], row[key_i]
    return "", ""


def _is_season_dir(name: str) -> bool:
    from .name_parse import _season_from_dir
    return _season_from_dir(name) is not None


def _list_images(folder: str) -> dict[str, str]:
    try:
        return {n.lower(): n for n in os.listdir(folder)
                if os.path.splitext(n)[1].lower() in artwork.IMAGE_EXTS}
    except OSError:
        return {}


def _folder_names_show(folder: str, show: str) -> bool:
    """Is this folder the show's own (so its poster.jpg is the show poster), rather
    than a shared "TV" or "Downloads" folder?"""
    from .name_parse import _title_year
    t, _ = _title_year(os.path.basename(folder))
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    return bool(t) and norm(t) == norm(show)

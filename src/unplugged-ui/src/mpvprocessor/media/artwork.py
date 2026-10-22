"""
Find artwork for a video without the network, and cache a grid-sized copy.

Order, first hit wins:
  1. an image beside the file named for it      Heat (1995)-poster.jpg, Heat (1995).jpg
  2. a folder image                             poster.jpg, folder.jpg, cover.jpg
     (only when the folder holds one film, or for a TV show/season folder)
  3. a cover embedded in the file               MKV attachment, MP4 'covr'
The names are the ones Kodi, Plex and Jellyfin write, so an existing library
lights up as-is.

Every reader is bounded: a corrupt or hostile file costs at most a handful of
seeks and MAX_COVER_BYTES of memory, and any exception means "no cover".
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
FOLDER_NAMES = ("poster", "folder", "cover", "movie", "show")
MAX_COVER_BYTES = 12 * 1024 * 1024

# Grid thumbnails: 2:3 posters at about twice the on-screen tile size so they stay
# sharp on a 4K panel.
THUMB_W, THUMB_H = 360, 540


def _pick(names_lower: dict[str, str], stems: tuple[str, ...]) -> str | None:
    for stem in stems:
        for ext in IMAGE_EXTS:
            hit = names_lower.get(stem + ext)
            if hit:
                return hit
    return None


def sidecar_art(video_stem: str, names_lower: dict[str, str]) -> str | None:
    """Image named for this video. names_lower maps lower-case name -> real name
    for every file in the video's folder (one directory listing, no extra I/O)."""
    s = video_stem.lower()
    return _pick(names_lower, (s + "-poster", s + "-cover", s, s + "-thumb", s + "-fanart"))


def folder_art(names_lower: dict[str, str]) -> str | None:
    return _pick(names_lower, FOLDER_NAMES)


def season_art(season: int, names_lower: dict[str, str]) -> str | None:
    """Kodi/Jellyfin season posters live in the show folder as season01-poster.jpg."""
    return _pick(names_lower, (f"season{season:02d}-poster", f"season{season:02d}",
                               f"season{season}-poster", f"season {season}"))


# ── embedded covers ──────────────────────────────────────────────────────────

def embedded_cover(path: str) -> bytes | None:
    try:
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            if ext == ".mkv":
                return _mkv_cover(f)
            if ext in (".mp4", ".m4v"):
                return _mp4_cover(f)
    except Exception:   # noqa: BLE001 - unreadable or malformed: no cover
        return None
    return None


def _read_vint(f, keep_marker: bool) -> tuple[int, int]:
    b = f.read(1)
    if not b:
        raise EOFError
    first = b[0]
    length = 1
    mask = 0x80
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("bad vint")
    value = first if keep_marker else first & (mask - 1)
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        raise EOFError
    for c in rest:
        value = (value << 8) | c
    if not keep_marker and value == (1 << (7 * length)) - 1:
        value = -1   # "unknown size"
    return value, length


_EBML, _SEGMENT, _SEEKHEAD, _SEEK, _SEEKID, _SEEKPOS = (
    0x1A45DFA3, 0x18538067, 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC)
_ATTACHMENTS, _ATTACHED, _FNAME, _FMIME, _FDATA, _CLUSTER = (
    0x1941A469, 0x61A7, 0x466E, 0x4660, 0x465C, 0x1F43B675)


def _mkv_cover(f) -> bytes | None:
    eid, _ = _read_vint(f, True)
    if eid != _EBML:
        return None
    size, _ = _read_vint(f, False)
    f.seek(size, 1)
    eid, _ = _read_vint(f, True)
    if eid != _SEGMENT:
        return None
    _read_vint(f, False)
    seg_data = f.tell()
    file_end = os.fstat(f.fileno()).st_size

    attach_pos = None
    for _ in range(64):   # top-level elements before the first cluster
        if f.tell() >= file_end:
            break
        eid, _ = _read_vint(f, True)
        size, _ = _read_vint(f, False)
        data_start = f.tell()
        if eid == _ATTACHMENTS:
            return _mkv_attachments(f, size)
        if eid == _CLUSTER or size < 0:
            break
        if eid == _SEEKHEAD and size < 64 * 1024 and attach_pos is None:
            attach_pos = _seekhead_attachments(f.read(size))
        f.seek(data_start + size, 0)

    if attach_pos is not None and seg_data + attach_pos < file_end:
        f.seek(seg_data + attach_pos, 0)
        eid, _ = _read_vint(f, True)
        size, _ = _read_vint(f, False)
        if eid == _ATTACHMENTS:
            return _mkv_attachments(f, size)
    return None


def _children(buf: bytes):
    import io
    b = io.BytesIO(buf)
    while b.tell() < len(buf):
        eid, _ = _read_vint(b, True)
        size, _ = _read_vint(b, False)
        if size < 0 or b.tell() + size > len(buf):
            return
        yield eid, buf[b.tell():b.tell() + size]
        b.seek(size, 1)


def _seekhead_attachments(buf: bytes) -> int | None:
    for eid, data in _children(buf):
        if eid != _SEEK:
            continue
        sid = spos = None
        for cid, cdata in _children(data):
            if cid == _SEEKID:
                sid = int.from_bytes(cdata, "big")
            elif cid == _SEEKPOS:
                spos = int.from_bytes(cdata, "big")
        if sid == _ATTACHMENTS and spos is not None:
            return spos
    return None


def _mkv_attachments(f, size: int) -> bytes | None:
    """Pick the best image attachment. The Matroska spec names the main cover
    cover.jpg/cover.png; small_ and _land variants are lower priority."""
    if size < 0 or size > 64 * 1024 * 1024:
        return None
    end = f.tell() + size
    best: tuple[int, int, int] | None = None   # (rank, data_pos, data_len)
    while f.tell() < end:
        eid, _ = _read_vint(f, True)
        esize, _ = _read_vint(f, False)
        if esize < 0:
            return None
        nxt = f.tell() + esize
        if eid == _ATTACHED:
            name = mime = ""
            data_pos = data_len = None
            while f.tell() < nxt:
                cid, _ = _read_vint(f, True)
                csize, _ = _read_vint(f, False)
                if csize < 0:
                    return None
                if cid == _FNAME and csize < 1024:
                    name = f.read(csize).decode("utf-8", "replace").lower()
                elif cid == _FMIME and csize < 256:
                    mime = f.read(csize).decode("ascii", "replace").lower()
                elif cid == _FDATA:
                    data_pos, data_len = f.tell(), csize
                    f.seek(csize, 1)
                else:
                    f.seek(csize, 1)
            if data_pos is not None and (mime.startswith("image/")
                                         or name.endswith(IMAGE_EXTS)):
                stem = os.path.splitext(name)[0]
                rank = (0 if stem == "cover" else 1 if stem.startswith("cover")
                        else 2 if stem in ("poster", "folder") else 4 if "small" in stem
                        else 3)
                if data_len <= MAX_COVER_BYTES and (best is None or rank < best[0]):
                    best = (rank, data_pos, data_len)
        f.seek(nxt, 0)
    if best is None:
        return None
    f.seek(best[1], 0)
    return f.read(best[2])


def _mp4_cover(f) -> bytes | None:
    """moov/udta/meta/ilst/covr/data. moov may be at either end of the file;
    walking box headers costs one seek per top-level box."""
    end = os.fstat(f.fileno()).st_size
    path = (b"moov", b"udta", b"meta", b"ilst", b"covr", b"data")
    lo, hi = 0, end
    for depth, want in enumerate(path):
        found = None
        pos = lo
        for _ in range(4096):
            if pos + 8 > hi:
                break
            f.seek(pos, 0)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size, typ = struct.unpack(">I4s", hdr)
            head = 8
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                head = 16
            elif size == 0:
                size = hi - pos
            if size < head:
                break
            if typ == want:
                found = (pos + head, pos + size)
                break
            pos += size
        if found is None:
            return None
        lo, hi = found
        if want == b"meta":
            lo += 4   # full box: version + flags
        if want == b"data":
            lo += 8   # type indicator + locale
    n = hi - lo
    if n <= 0 or n > MAX_COVER_BYTES:
        return None
    f.seek(lo, 0)
    return f.read(n)


# ── thumbnail cache ──────────────────────────────────────────────────────────

def cache_name(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:24] + ".jpg"


def make_thumb(src: str | bytes, dest: Path) -> bool:
    """Scale-and-crop to a 2:3 poster and save as JPEG. QImage (not QPixmap) is
    safe off the GUI thread."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage
    img = QImage()
    ok = img.loadFromData(src) if isinstance(src, (bytes, bytearray)) else img.load(str(src))
    if not ok or img.isNull():
        return False
    img = img.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    x = max(0, (img.width() - THUMB_W) // 2)
    y = max(0, (img.height() - THUMB_H) // 2)
    img = img.copy(x, y, THUMB_W, THUMB_H)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    if not img.save(str(tmp), "JPG", 88):
        return False
    os.replace(tmp, dest)
    return True

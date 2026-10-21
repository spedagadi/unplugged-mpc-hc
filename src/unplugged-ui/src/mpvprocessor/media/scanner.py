"""
Media library scanner.

Scans a folder (non-recursively by default, optionally recursive) for
video files and returns MediaItem entries sorted by filename.

Recognised extensions are the containers the Media Player graph is validated
for (MKV and MP4). Other types are not listed so a user cannot pick a file the
engine was never tested with.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


VIDEO_EXTENSIONS = {".mkv", ".mp4"}


@dataclass
class MediaItem:
    path: Path
    title: str          # display name (stem, cleaned up)
    size_mb: float
    extension: str

    @property
    def display(self) -> str:
        return self.title

    @property
    def path_str(self) -> str:
        return str(self.path)


def _clean_title(stem: str) -> str:
    """Turn a filename stem into a readable title."""
    # Replace dots and underscores with spaces (common in scene releases)
    t = stem.replace(".", " ").replace("_", " ")
    # Collapse multiple spaces
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip()


def scan_folder(folder: str | Path, recursive: bool = False) -> list[MediaItem]:
    """
    Return a sorted list of MediaItems found in folder.
    recursive=False scans only the top level.
    """
    root = Path(folder)
    if not root.is_dir():
        return []

    pattern = "**/*" if recursive else "*"
    items: list[MediaItem] = []

    for p in root.glob(pattern):
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            size_mb = p.stat().st_size / (1024 * 1024)
        except OSError:
            size_mb = 0.0
        items.append(MediaItem(
            path=p,
            title=_clean_title(p.stem),
            size_mb=round(size_mb, 1),
            extension=p.suffix.lower(),
        ))

    return sorted(items, key=lambda m: m.title.lower())

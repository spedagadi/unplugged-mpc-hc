"""
Turn a video file's path into a title.

Movies:  "Dune.Part.Two.2024.2160p.UHD.BluRay.x265-GRP.mkv" -> Dune Part Two (2024)
Episodes: "The.Bear.S02E05.1080p.WEB.mkv"                  -> The Bear, season 2, episode 5
          "Show Name/Season 1/03 - Pilot.mkv"               -> Show Name, season 1, episode 3

Filenames are often worse than the folders they sit in (Kodi/Plex/Jellyfin users
keep "Title (Year)/Title (Year).mkv"), so a folder that names the film is used when
the file itself gives no year. Nothing here touches the disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath


@dataclass
class ParsedName:
    kind: str            # "movie" | "episode"
    title: str           # movie title, or the show name for an episode
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str = ""


# Everything from the first of these tokens onwards is release detail, not title.
_JUNK = re.compile(
    r"\b(?:2160p|1080[pi]|720p|576[pi]|480[pi]|4k|uhd|hdr10\+?|hdr|dv|dovi|dolby\s?vision|"
    r"blu-?ray|bdrip|brrip|bdremux|remux|web-?dl|web-?rip|webrip|web|hdtv|dvdrip|dvd|"
    r"x26[45]|h\.?26[45]|hevc|avc|xvid|divx|aac|ac3|eac3|dts(?:-hd)?|truehd|atmos|flac|"
    r"ddp?\d?\.?\d?|10bit|8bit|proper|repack|extended|unrated|remastered|"
    r"imax|hybrid|multi|dual|subbed|internal)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)")
_SXXEXX = re.compile(r"\bS(\d{1,2})[ ._-]*E(\d{1,3})(?:[ ._-]*E?\d{1,3})*\b", re.IGNORECASE)
_NXNN = re.compile(r"(?<!\d)(\d{1,2})x(\d{2,3})(?!\d)", re.IGNORECASE)
_SEASON_DIR = re.compile(r"^(?:season|series|staffel|saison|temporada)[ ._-]*(\d{1,2})$|^s(\d{1,2})$",
                         re.IGNORECASE)
_LEADING_EP = re.compile(r"^(?:e|ep|episode)?[ ._-]*(\d{1,3})(?:\b|[ ._-])", re.IGNORECASE)
_BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")


def _tidy(s: str) -> str:
    s = _BRACKETS.sub(" ", s)
    s = s.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+-\s*$", "", s)
    s = re.sub(r"[\s\-(]+$", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" -.")


def _cut_junk(s: str) -> str:
    m = _JUNK.search(s.replace(".", " ").replace("_", " "))
    return s[:m.start()] if m else s


def _title_year(text: str) -> tuple[str, int | None]:
    """Split "Some.Film.1999.1080p..." into ("Some Film", 1999).

    The LAST plausible year before the release junk wins, so "2001 A Space Odyssey
    1968" keeps 2001 in the title and "Blade Runner 2049 (2017)" keeps 2049."""
    head = _cut_junk(text)
    years = list(_YEAR.finditer(head))
    if years:
        y = years[-1]
        title = _tidy(head[:y.start()])
        if title:
            return title, int(y.group(1))
    return _tidy(head) or _tidy(text), None


def _season_from_dir(name: str) -> int | None:
    m = _SEASON_DIR.match(name.strip())
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def parse(path: str | PurePath) -> ParsedName:
    p = PurePath(path)
    stem = p.stem
    parent = p.parent.name
    grand = p.parent.parent.name if p.parent.parent != p.parent else ""
    dir_season = _season_from_dir(parent)

    m = _SXXEXX.search(stem) or _NXNN.search(stem)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        show = _tidy(_cut_junk(stem[:m.start()]))
        show, _ = _title_year(show) if show else ("", None)
        ep_title = _tidy(_cut_junk(stem[m.end():]))
        if not show:
            show = _show_from_dirs(parent, grand, dir_season)
        return ParsedName("episode", show or _tidy(stem), season=season,
                          episode=episode, episode_title=ep_title)

    # "Show/Season 2/05 - Title.mkv": the folder says season, the file starts with a number.
    if dir_season is not None:
        lm = _LEADING_EP.match(stem)
        if lm:
            show = _show_from_dirs(parent, grand, dir_season)
            if show:
                return ParsedName("episode", show, season=dir_season,
                                  episode=int(lm.group(1)),
                                  episode_title=_tidy(_cut_junk(stem[lm.end():])))

    title, year = _title_year(stem)
    if year is None and parent:
        # "Heat (1995)/heat-bluray.mkv": trust the folder when it carries the year.
        ft, fy = _title_year(parent)
        if fy is not None and ft:
            return ParsedName("movie", ft, year=fy)
    return ParsedName("movie", title or _tidy(stem), year=year)


def _show_from_dirs(parent: str, grand: str, dir_season: int | None) -> str:
    name = grand if dir_season is not None else parent
    if not name:
        return ""
    title, _ = _title_year(name)
    return title

"""
OMDb (omdbapi.com) client: find a title's IMDb entry and download its poster.

Runs on the library sync thread only. Every call is bounded by a timeout, and
failures come back as values, never exceptions, so a dead network or a bad
answer can only ever mean "no poster yet".

Results:
  Found(imdb_id, title, year, poster_url, plot)
  NOT_FOUND                    OMDb answered and has no such title
  Abort(reason)                stop asking for this sync: offline, key invalid,
                               daily limit reached
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

_log = logging.getLogger("unplugged.audit")

API = "https://www.omdbapi.com/"
IMG_API = "https://img.omdbapi.com/"
TIMEOUT = 10
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_UA = "Unplugged/1.x (+https://github.com/spedagadi/unplugged-mpc-hc)"


def default_key() -> str:
    """The key shipped with the app lives in an untracked module so it is not in git.
    A build without it simply has online posters off unless the user sets one."""
    try:
        from ._omdb_key import OMDB_API_KEY   # type: ignore
        return OMDB_API_KEY
    except Exception:   # noqa: BLE001
        return ""


@dataclass
class Found:
    imdb_id: str
    title: str
    year: str
    poster_url: str
    plot: str


@dataclass
class Abort:
    reason: str


NOT_FOUND = object()


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("response too large")
    return data


def _query(key: str, spent: list | None = None, **params) -> dict | Abort:
    if spent is not None:
        spent[0] += 1
    params["apikey"] = key
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        return json.loads(_get(url).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # OMDb answers 401 for both a bad key and the daily limit, with a JSON body.
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("Error", "")
        except Exception:   # noqa: BLE001
            msg = ""
        return Abort(f"OMDb HTTP {e.code} {msg}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return Abort(f"network: {e}")
    except ValueError as e:
        return Abort(f"bad response: {e}")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def _title_key(s: str) -> str:
    """_norm without a leading article, so "Matrix" matches "The Matrix"."""
    return re.sub(r"^(the|an|a)(?=[a-z0-9])", "", _norm(s)) or _norm(s)


def _matches(want_title: str, year: int | None, got_title: str, got_year: str) -> bool:
    if _title_key(got_title) != _title_key(want_title):
        return False
    ry = _year_of(got_year)
    return not (year and ry and abs(ry - year) > 1)


def _year_of(s: str) -> int | None:
    m = re.match(r"\s*(\d{4})", s or "")
    return int(m.group(1)) if m else None


def _answer(d: dict) -> Found | object | Abort:
    if d.get("Response") == "True":
        poster = d.get("Poster") or ""
        return Found(d.get("imdbID", ""), d.get("Title", ""), d.get("Year", ""),
                     poster if poster.startswith("http") else "", d.get("Plot", "") or "")
    err = (d.get("Error") or "").lower()
    if "not found" in err:
        return NOT_FOUND
    return Abort(f"OMDb: {d.get('Error')}")


def lookup(key: str, title: str, year: int | None, kind: str,
           spent: list | None = None) -> Found | object | Abort:
    """kind: "movie" or "series". Exact title (+ year) first; then a search,
    taking a result whose title matches and whose year is within one.
    spent[0] is increased by the number of API requests made (1 to 3)."""
    if not title:
        return NOT_FOUND
    params = {"t": title, "type": kind}
    if year and kind == "movie":
        params["y"] = str(year)
    d = _query(key, spent, **params)
    if isinstance(d, Abort):
        return d
    a = _answer(d)
    if isinstance(a, Abort):
        return a
    # OMDb's t= is fuzzy ("The Weight" returns "...That's the Weight of the
    # World"), so only trust it when the title and year really match.
    if isinstance(a, Found) and _matches(title, params.get("y") and year,
                                         a.title, a.year):
        return a

    # Strict search fallback: catches year differences between a release and
    # its IMDb entry, and entries that t= ranked below a fuzzy hit.
    d = _query(key, spent, s=title, type=kind)
    if isinstance(d, Abort):
        return d
    if d.get("Response") != "True":
        a = _answer(d)
        return NOT_FOUND if a is NOT_FOUND else a
    best = None
    for r in d.get("Search") or []:
        if _matches(title, year, r.get("Title", ""), r.get("Year", "")):
            best = r
            break
    if best is None:
        return NOT_FOUND
    d = _query(key, spent, i=best.get("imdbID", ""))
    if isinstance(d, Abort):
        return d
    return _answer(d)


def poster(key: str, found: Found) -> bytes | Abort | None:
    """Image bytes. The Amazon URL OMDb returns is free and ~380x562; the
    img.omdbapi.com poster API is the fallback when there is none."""
    urls = []
    if found.poster_url:
        urls.append(found.poster_url)
    if found.imdb_id:
        urls.append(IMG_API + "?" + urllib.parse.urlencode(
            {"i": found.imdb_id, "h": "900", "apikey": key}))
    for u in urls:
        try:
            data = _get(u)
        except urllib.error.HTTPError as e:
            _log.info("library: poster %s -> HTTP %s", u.split("?")[0], e.code)
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return Abort(f"network: {e}")
        except ValueError:
            continue
        if (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"
                or data[8:12] == b"WEBP") and _poster_shaped(data, u):
            return data
    return None


def _poster_shaped(data: bytes, url: str) -> bool:
    """IMDb shows a cast headshot or a still when a new title has no poster yet;
    a poster is portrait, about 2:3."""
    from PyQt6.QtGui import QImage
    img = QImage.fromData(data)
    if img.isNull() or img.width() <= 0:
        return False
    if img.height() / img.width() < 1.25:
        _log.info("library: %s is %dx%d, not a poster - skipped",
                  url.split("?")[0], img.width(), img.height())
        return False
    return True

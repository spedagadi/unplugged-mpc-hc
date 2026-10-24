"""
help_store.py — the settings guide IS the runtime help store.

docs/settings-guide.md carries one table row per setting with
(Label | Choices/range | Default | What it does); the context-help card reads
that, and `--check` (run by distrib\\build_unplugged_setup.ps1) verifies every
row the default panel can show resolves here. Editing the guide edits the help
card; a drifted guide fails packaging instead of silently lying on screen.

Heading grammar the parser relies on (the guide is written to match):
  ## <Tab> [tab] [(...)]        — tab scope; must name a GROUPS entry
  ### <Section> [(...) — ...]   — mirrors the panel's section title
  | **<Label>** [tail] | ...    — label is the FIRST bold span, matching the
                                  panel row's label (whitespace-insensitive)
Rows hidden behind the dev or non-house-curve flags need no entry; --check
uses the same visibility rule as the rail, so coverage cannot disagree.
"""

from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

_TABS = {"PLAYBACK", "SOURCE", "HDR", "ZION", "OUTPUT", "SYSTEM"}


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _head_name(text: str) -> str:
    """'Tone Mapping (delivery & gamut)' -> 'TONE MAPPING';
    'Display Target — calibrate these first' -> 'DISPLAY TARGET'."""
    s = re.split(r"\s+[(—]", text, 1)[0]
    return _collapse(s).upper()


def _tab_of(text: str) -> str | None:
    name = _head_name(text)
    for t in _TABS:
        if name == t or name.startswith(t + " "):
            return t
    return None


def _clean_label(cell: str) -> str:
    m = re.search(r"\*\*(.+?)\*\*", cell)
    if not m:
        return ""
    return _collapse(m.group(1)).strip()


class HelpStore:
    """Parsed guide: (TAB, SECTION, LABEL) -> {range, default, help}."""

    def __init__(self, md_path: Path | None = None):
        self.path = md_path or self.locate()
        self.entries: dict[tuple, dict] = {}
        self._by_label: dict[tuple, list] = {}
        if self.path and self.path.exists():
            self._parse(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def locate() -> Path | None:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            p = Path(sys._MEIPASS) / "docs" / "settings-guide.md"
            return p if p.exists() else None
        # ui -> mpvprocessor -> unplugged-ui/src -> unplugged-ui -> repo/src -> repo root
        p = Path(__file__).resolve().parents[5] / "docs" / "settings-guide.md"
        return p if p.exists() else None

    def _parse(self, md: str) -> None:
        tab = sec = None
        for line in md.splitlines():
            s = line.strip()
            if s.startswith("## ") and not s.startswith("### "):
                tab, sec = _tab_of(s[3:]), ""
                continue
            if s.startswith("### ") and tab:
                sec = _head_name(s[4:])
                continue
            if not tab or not s.startswith("|"):
                continue
            label = _clean_label(s)
            if not label or label == "Setting" or label == "Row":
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 2:
                continue
            rng = dflt = ""
            what = cells[-1]
            if len(cells) >= 4:
                rng, dflt, what = cells[1], cells[2], cells[-1]
            elif len(cells) == 3:
                dflt, what = "", cells[-1]
            key = (tab, sec, label)
            if key in self.entries:
                continue                      # first definition wins
            self.entries[key] = {"range": _collapse(rng),
                                 "default": _collapse(dflt),
                                 "help": _collapse(what)}
            self._by_label.setdefault((tab, label), []).append(key)

    def help_for(self, tab: str, section: str | None, label: str) -> dict | None:
        lab = _collapse(label)
        sec = (section or "").upper()
        rec = self.entries.get((tab, sec, lab))
        if rec:
            return rec
        rec = self.entries.get((tab, "", lab))
        if rec:
            return rec
        cands = self._by_label.get((tab, lab)) or []
        return self.entries[cands[0]] if len(cands) == 1 else None

    def coverage_check(self) -> list[str]:
        """Rows the DEFAULT rail can show that carry no help text.
        Same visibility rule as S3ShellPanel._rebuild: dev rows only when the
        INI flag is set (never by default), curve-gated rows only when at least
        one house curve reads them; PORT rows are runtime hardware."""
        try:
            from .s3shell_panel import GROUPS, CURVE_SIMPLE, build_rows
        except ImportError:
            # Run as a plain script file (the build gate): bootstrap the import.
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from mpvprocessor.ui.s3shell_panel import GROUPS, CURVE_SIMPLE, build_rows
        miss = []
        for r in build_rows():
            if r.dev or r.type == "port":
                continue
            if r.curves is not None and not (set(r.curves) & set(CURVE_SIMPLE)):
                continue
            tab = GROUPS[r.group][1]
            if self.help_for(tab, r.section, r.label) is None:
                miss.append(f"{tab} / {r.section or '-'} / {r.label}")
        return miss


def plain(s: str) -> str:
    """Inline markdown stripped entirely — for single-line surfaces (the
    card's range/default meta row) where even formatting is noise."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s or "")
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    return s.replace("`", "")


def md_to_html(s: str) -> str:
    """Guide-cell markdown -> the rich-text subset QLabel renders.
    The source is escaped FIRST, so only our own tags survive as markup:
    `code` -> accent span, **bold** -> <b>, *italic* -> <i>. The guide is
    prose authored offline; anything outside these three patterns renders
    as written — which is the point of using the md as the store."""
    s = _html.escape(s or "", quote=False)
    s = re.sub(r"`([^`]+)`",
               r'<span style="color:#FF8A4C;">\1</span>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(?=[^\s*])([^*]+?)\*", r"<i>\1</i>", s)
    return s


_ABBREV = {"e", "g", "i", "etc", "vs", "approx"}


def split_first_sentence(text: str) -> tuple[str, str]:
    """(lead, rest). The lead renders at couch size, the rest fine print.
    The break is the first period followed by whitespace whose preceding word
    is not a one-letter abbreviation (so "e.g. from" survives)."""
    for m in re.finditer(r"\.\s", text):
        before = text[:m.start()]
        word = re.split(r"[\s(]", before)[-1] if before else ""
        if word.lower().strip(".,") in _ABBREV or len(word) <= 1:
            continue
        if m.start() < 20:
            continue
        return text[:m.start() + 1].strip(), text[m.end():].strip()
    return text, ""


if __name__ == "__main__":
    if "--check" in sys.argv:
        store = HelpStore()
        if not store.path:
            print("help_store: settings-guide.md not found", file=sys.stderr)
            sys.exit(2)
        missing = store.coverage_check()
        if missing:
            print(f"settings-guide.md is missing help for {len(missing)} "
                  "visible row(s):", file=sys.stderr)
            for m in missing:
                print("  - " + m, file=sys.stderr)
            sys.exit(1)
        print(f"help coverage ok ({len(store.entries)} guide rows)")
        sys.exit(0)
    print("usage: python -m mpvprocessor.ui.help_store --check")

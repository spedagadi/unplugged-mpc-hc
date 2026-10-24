"""
help_card.py — the context-help card that opens beside the settings rail.

One card beside the settings rail, riding with the focused row: it centres on
whichever field the user is on (the chrome scrolls to keep that row visible),
so no description can land off-screen the way a bottom-anchored strip did.
Full card on focus change or value step, collapsing to a slim "label — value"
strip after a few seconds so the PICTURE stays the reference while tuning by
eye; any new focus or step brings the text back.

Text comes from the settings guide (help_store) — this widget formats, it does
not author. The guide cells are markdown, so the card renders them: meta lines
drop the markup entirely, prose shows bold/italic/code as rich text. The chip
and the current value are computed live from the panel's Row.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout

from .help_store import md_to_html, plain, split_first_sentence
from .theme import ui_font, FONT_PX_LABEL, FONT_PX_VALUE

CARD_W = 368
STRIP_MS = 4000          # full card -> strip
_BORDER = "#242428"
_TEXT = "#F2F2F2"
_MID = "#8A8A90"
_ACCENT = "#E8551F"


class HelpCard(QWidget):
    def __init__(self, store, panel, parent=None):
        super().__init__(parent)
        self._store = store
        self._panel = panel
        self._row = None                       # Row currently shown
        self._rec = None
        self.setFixedWidth(CARD_W)
        # The card lives inside the translucent chrome window, so it must not
        # paint any system background — only its own scrim (see paintEvent).
        # A stylesheet background would not render here at all: a bare QWidget
        # subclass needs WA_StyledBackground for that, and painting it directly
        # is what gives the semi-transparent dark plate the white text needs.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(14, 10, 14, 12)
        self.v.setSpacing(4)
        self.title = QLabel()
        self.title.setFont(ui_font(15, QFont.Weight.DemiBold))
        self.title.setStyleSheet(f"color: {_TEXT};")
        self.meta = QLabel()
        self.meta.setFont(ui_font(FONT_PX_LABEL))
        self.meta.setStyleSheet(f"color: {_MID};")
        self.meta.setWordWrap(True)
        self.lead = QLabel()
        self.lead.setFont(ui_font(15))
        self.lead.setStyleSheet(f"color: {_TEXT};")
        self.lead.setWordWrap(True)
        self.fine = QLabel()
        self.fine.setFont(ui_font(FONT_PX_VALUE - 1))
        self.fine.setStyleSheet(f"color: {_MID};")
        self.fine.setWordWrap(True)
        for w in (self.title, self.meta, self.lead, self.fine):
            self.v.addWidget(w)
        self.v.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._to_strip)

    def paintEvent(self, _e):
        """Semi-transparent dark plate: the video must stay visible around the
        words, but white text directly over a bright picture is unreadable —
        this scrim is what makes it render."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(_BORDER), 1))
        p.setBrush(QColor(10, 10, 12, 200))       # ~78% dark plate
        p.drawRoundedRect(r, 8, 8)

    # ------------------------------------------------------------------ slots
    def show_for(self, row) -> None:
        """panel.row_focused -> here. None (header/section/tab) clears the card."""
        if row is None:
            self._row = None
            self.hide()
            return
        self._row = row
        self._rec = self._store.help_for(
            self._panel.tab_name(row), row.section, row.label)
        self._fill(full=True)
        self.show()
        self._timer.start(STRIP_MS)

    def note_value(self, row) -> None:
        """panel.row_updated -> here while the user drags/steps: refresh and
        bring the text back — they are clearly working on this field."""
        if row is self._row:
            self._fill(full=True)
            self._timer.start(STRIP_MS)

    # ------------------------------------------------------------------ internals
    def _to_strip(self) -> None:
        self._fill(full=False)

    def _chips(self) -> str:
        r = self._row
        if r.type == "toggle":
            return "default" if r.on == r.default_on else ""
        if r.type == "cycle":
            return "default" if r.opt == r.default_opt else ""
        if r.type == "slider":
            if float(r.val) == float(r.default):
                return "default"
            if float(r.val) == float(r.max):
                return "at max"
            if float(r.min) == 0.0 and float(r.val) == 0.0:
                return "off"
        return ""

    def _fill(self, full: bool) -> None:
        r = self._row
        if r is None:
            return
        value = self._panel.value_text(r)
        if not full:
            self.title.setText(f"{r.label}   ·   {value}")
            self.meta.setText("")
            self.lead.setVisible(False)
            self.fine.setVisible(False)
            self.adjustSize()
            return
        self.lead.setVisible(True)
        self.fine.setVisible(True)
        where = r.section.title() if r.section else self._panel.tab_name(r)
        self.title.setText(f"{r.label}  ·  {where}")
        bits = []
        if self._rec:
            if self._rec["range"]:
                bits.append(plain(self._rec["range"]))
            if self._rec["default"]:
                bits.append("default " + plain(self._rec["default"]))
        chip = self._chips()
        if chip:
            bits.append(f"current: {chip}")
        self.meta.setText("  ·  ".join(bits))
        if self._rec and self._rec["help"]:
            lead, rest = split_first_sentence(self._rec["help"])
            self.lead.setTextFormat(Qt.TextFormat.RichText)
            self.fine.setTextFormat(Qt.TextFormat.RichText)
            self.lead.setText(md_to_html(lead))
            self.fine.setText(md_to_html(rest))
        else:
            self.lead.setText(value)     # no guide entry (dev tools): value only
            self.fine.setText("")
        self.setMinimumHeight(0)
        self.adjustSize()

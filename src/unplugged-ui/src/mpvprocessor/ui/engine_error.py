"""
Playback failure reporting for Media Player mode.

A file the engine cannot open used to fail silently: the library came back and
nothing said why. OpenErrorDialog tells the user in plain language, shows the
HRESULT, and lets them copy a report (also written to
~/.unplugged/logs/last-error.txt) that contains the engine's own last log lines,
so a field failure can be diagnosed from what the user sends back.

WarningToast is the non-modal counterpart for playback that works but is
degraded (no audio, system renderer, a filter taken from another install).
"""

from __future__ import annotations

import datetime
import logging
import os
import platform
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .confirm_dialog import _BTN_CANCEL, _BTN_CONFIRM, _CARD_STYLE

_log = logging.getLogger("unplugged.engine_error")

_REINSTALL = "Reinstall Unplugged (run the installer again) and try once more."

# Where "Report a problem" addresses its email.
SUPPORT_EMAIL = "fossunplugged@gmail.com"

# HRESULT -> plain-language explanation. Keys are unsigned 32-bit.
_HR_TEXT = {
    0x80040217: "Windows could not connect the filters needed to play this file. "
                "Another codec pack installed on this PC may be interfering. " + _REINSTALL,
    0x80040207: "This file could not be read. It may be damaged, incomplete, or in a "
                "format Unplugged does not support.",
    0x80040154: "A playback component of Unplugged is not registered on this PC "
                "(often after another codec pack was uninstalled). " + _REINSTALL,
    0x80070002: "The file could not be found. It may have been moved, renamed or "
                "be on a drive that is not connected.",
    0x80070003: "The folder containing this file could not be found. The drive or "
                "network share may not be connected.",
    0x80070005: "Access to the file was denied. Check that you have permission to read it.",
    0x80070020: "The file is in use by another program.",
    0x8007007E: "A playback component of Unplugged is missing. " + _REINSTALL,
    0x800700C1: "A playback component of Unplugged is damaged or the wrong type. " + _REINSTALL,
    0x80040265: "This file's format is not supported.",
    0x80040266: "This file's format is not supported.",
    0x8004022F: "This file's format is not supported.",
    0x80040241: "This file's format is not supported, or the file is damaged.",
}

_WARN_TEXT = {
    "renderer_fallback": "Unplugged's video renderer could not start - playing with the "
                         "Windows renderer. Tone mapping and picture settings are inactive.",
    "audio_none": "Audio could not be started for this file - playing without sound.",
}


def describe_hr(hr: int) -> str:
    hr &= 0xFFFFFFFF
    text = _HR_TEXT.get(hr)
    if text:
        return text
    return "The file could not be played. " + _REINSTALL + (
        " If it keeps happening, use Copy details and send the report to support.")


def describe_warning(code: str) -> str:
    if code in _WARN_TEXT:
        return _WARN_TEXT[code]
    if code.startswith("registry:"):
        name = code[len("registry:"):]
        return (f"{name} was loaded from another program's installation instead of "
                f"Unplugged's own copy. If playback misbehaves, reinstall Unplugged.")
    return f"Playback is degraded ({code})."


def build_report(url: str, hr: int, warnings: list, engine_log: str,
                 engine_dll: str = "") -> str:
    try:
        from .. import __version__ as app_version
    except Exception:   # noqa: BLE001
        app_version = "?"
    hr &= 0xFFFFFFFF
    lines = [
        "Unplugged playback error report",
        f"Time:     {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Version:  {app_version}",
        f"Engine:   {engine_dll or '?'}",
        f"OS:       {platform.platform()}",
        f"File:     {url}",
        f"Error:    0x{hr:08X}",
        f"Meaning:  {describe_hr(hr)}",
        f"Warnings: {', '.join(warnings) if warnings else '(none)'}",
        "",
        "---- engine log (most recent last) ----",
        engine_log.strip() or "(engine log not available)",
    ]
    return "\n".join(lines) + "\n"


def save_report(text: str) -> Path | None:
    try:
        d = Path(os.path.expanduser("~")) / ".unplugged" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "last-error.txt"
        p.write_text(text, encoding="utf-8")
        return p
    except Exception as e:   # noqa: BLE001 - reporting must never raise
        _log.warning("could not save error report: %s", e)
        return None


class OpenErrorDialog(QDialog):
    """Modal, styled like ConfirmDialog: what failed, why, and a copyable report."""

    def __init__(self, url: str, hr: int, report: str, saved: Path | None,
                 parent=None, report_problem=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._report = report
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setFixedWidth(560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QWidget(objectName="card")
        card.setStyleSheet(_CARD_STYLE)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        title = QLabel("Can't play this file")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(title)

        name = QLabel(os.path.basename(url) or url)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet("color: #dddddd; font-size: 13px; background: transparent;")
        layout.addWidget(name)

        msg = QLabel(describe_hr(hr))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #999999; font-size: 13px; background: transparent;")
        layout.addWidget(msg)

        detail = f"Error code 0x{hr & 0xFFFFFFFF:08X}"
        if saved:
            detail += f"\nReport saved to {saved}"
        code = QLabel(detail)
        code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code.setWordWrap(True)
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code.setStyleSheet("color: #666666; font-size: 11px; background: transparent;")
        layout.addWidget(code)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._copy_btn = QPushButton("Copy details")
        self._copy_btn.setStyleSheet(_BTN_CANCEL)
        self._copy_btn.clicked.connect(self._copy)
        row.addWidget(self._copy_btn)
        if report_problem is not None:
            rp = QPushButton("Report a problem")
            rp.setStyleSheet(_BTN_CANCEL)
            rp.clicked.connect(lambda: (self.accept(), report_problem()))
            row.addWidget(rp)
        ok = QPushButton("OK")
        ok.setStyleSheet(_BTN_CONFIRM)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addLayout(row)

        self.adjustSize()
        _center(self, parent)

    def _copy(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._report)
            self._copy_btn.setText("Copied")


class WarningToast(QWidget):
    """Non-modal notice at the top of the window; never takes focus, hides itself."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "color: #ffffff; font-size: 13px; background: rgba(14,14,14,230);"
            "border: 1.5px solid rgba(232,85,31,200); border-radius: 10px; padding: 12px 18px;")
        lay.addWidget(self._label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, text: str, msecs: int = 10000) -> None:
        self._label.setText(text)
        self.setFixedWidth(560)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            pg = parent.frameGeometry()
            self.move(pg.x() + (pg.width() - self.width()) // 2, pg.y() + 48)
        self.show()
        self.raise_()
        self._hide_timer.start(msecs)


class DiagnosticsDialog(QDialog):
    """Report a problem: build the diagnostics zip, then show it / start an email.

    The user attaches the zip themselves; mailto cannot carry attachments.
    """

    def __init__(self, engine=None, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._engine = engine
        self._zip: Path | None = None
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setFixedWidth(560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QWidget(objectName="card")
        card.setStyleSheet(_CARD_STYLE)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        title = QLabel("Report a problem")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(title)

        self._msg = QLabel(
            "Unplugged will save a diagnostics file to your Desktop with its logs, "
            "settings and a description of this PC (graphics card, displays, other "
            "codec software). It contains the names of files you played. "
            "Attach it to your email.")
        self._msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet("color: #999999; font-size: 13px; background: transparent;")
        layout.addWidget(self._msg)

        self._path_lbl = QLabel("")
        self._path_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path_lbl.setWordWrap(True)
        self._path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_lbl.setStyleSheet("color: #dddddd; font-size: 12px; background: transparent;")
        self._path_lbl.hide()
        layout.addWidget(self._path_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._close_btn = QPushButton("Cancel")
        self._close_btn.setStyleSheet(_BTN_CANCEL)
        self._close_btn.clicked.connect(self.reject)
        row.addWidget(self._close_btn)
        self._show_btn = QPushButton("Show file")
        self._show_btn.setStyleSheet(_BTN_CANCEL)
        self._show_btn.clicked.connect(self._show_file)
        self._show_btn.hide()
        row.addWidget(self._show_btn)
        self._main_btn = QPushButton("Create diagnostics file")
        self._main_btn.setStyleSheet(_BTN_CONFIRM)
        self._main_btn.setDefault(True)
        self._main_btn.clicked.connect(self._on_main)
        row.addWidget(self._main_btn)
        layout.addLayout(row)

        self.adjustSize()
        _center(self, parent)

    def _on_main(self) -> None:
        if self._zip is None:
            self._create()
        else:
            self._email()

    def _create(self) -> None:
        from ..core import diagnostics
        self._main_btn.setEnabled(False)
        self._main_btn.setText("Collecting…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            dll = getattr(self._engine, "dll_path", None) if self._engine else None
            recent = ""
            if self._engine is not None:
                try:
                    recent = self._engine.recent_log()
                except Exception:   # noqa: BLE001
                    recent = ""
            self._zip = diagnostics.collect_zip(dll, recent)
        except Exception as e:   # noqa: BLE001
            _log.error("diagnostics zip failed: %s", e)
            self._msg.setText(f"The diagnostics file could not be created: {e}")
            self._main_btn.setText("Try again")
            self._main_btn.setEnabled(True)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._msg.setText(f"Diagnostics saved. Email it to {SUPPORT_EMAIL} with a short "
                          "description of what happened and when.")
        self._path_lbl.setText(str(self._zip))
        self._path_lbl.show()
        self._show_btn.show()
        self._close_btn.setText("Close")
        self._main_btn.setText("Email support")
        self._main_btn.setEnabled(True)
        self.adjustSize()

    def _show_file(self) -> None:
        if self._zip is None:
            return
        import subprocess
        try:
            subprocess.Popen(["explorer.exe", "/select,", str(self._zip)])
        except OSError as e:
            _log.warning("could not open explorer: %s", e)

    def _email(self) -> None:
        from urllib.parse import quote
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        try:
            from .. import __version__ as ver
        except Exception:   # noqa: BLE001
            ver = "?"
        subject = f"Unplugged {ver} problem report"
        body = (f"Unplugged version: {ver}\n"
                f"Diagnostics file: {self._zip}\n"
                "(please attach the file above)\n\n"
                "What happened:\n\n"
                "What were you doing when it happened:\n")
        url = (f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}")
        if not QDesktopServices.openUrl(QUrl(url)):
            self._msg.setText(f"No email program is set up on this PC. Please email the file "
                              f"above to {SUPPORT_EMAIL}.")


def _center(dlg: QWidget, parent) -> None:
    if parent is not None:
        pg = parent.geometry()
        dlg.move(pg.x() + (pg.width() - dlg.width()) // 2,
                 pg.y() + (pg.height() - dlg.height()) // 2)
        return
    screen = QApplication.primaryScreen()
    if screen:
        sg = screen.geometry()
        dlg.move(sg.x() + (sg.width() - dlg.width()) // 2,
                 sg.y() + (sg.height() - dlg.height()) // 2)

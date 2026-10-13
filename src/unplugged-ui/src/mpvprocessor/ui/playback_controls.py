"""
PlaybackControlsPanel — icon-based two-column layout matching SettingsPanel.

Left column (80px): icon buttons for groups (DECODE, TRACKS, AUDIO, DISPLAY, SYNC)
Right area: category content page with shared help/context in RightPanel below.

Public API (unchanged):
  Signals : property_change(str, object), help_changed(str)
  Methods : update_track_list, update_audio_devices, update_hwdec_actual,
            update_property, reset_for_new_file, restore_from_config,
            emit_saved_settings
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget, QPushButton,
)

from .settings_rows import (
    _Row, _CategoryRow, _BoolRow, _FloatRow, _ActionRow, _PickerRow, _RowPage,
    _BG,
)


HWDEC_OPTIONS = [
    ("Auto-copy (recommended)",   "auto-copy"),
    ("D3D11VA-copy (Windows)",     "d3d11va-copy"),
    ("NVDEC-copy (NVIDIA)",        "nvdec-copy"),
    ("D3D11VA zero-copy",          "d3d11va"),
    ("NVDEC zero-copy",            "nvdec"),
    ("DXVA2 (legacy)",             "dxva2"),
    ("Software (CPU only)",        "no"),
    ("Auto",                       "auto"),
]

ASPECT_OPTIONS = [
    ("Source (default)", ""),
    ("16:9",   "16:9"),
    ("4:3",    "4:3"),
    ("2.35:1", "2.35:1"),
    ("2.39:1", "2.39:1"),
    ("Stretch","stretch"),
]

# Two modes — simple and clear.
# "auto" tells mpv to pass through whatever the audio device reports it supports.
AUDIO_MODES = [
    ("Decode to LPCM",
     "",
     "mpv decodes all audio → PCM. Works with any device, soundbar or headphones."),
    ("Bitstream to AVR",
     "auto",
     "Send compressed audio untouched to your receiver. "
     "The AVR decodes Dolby/DTS and shows the correct format logo."),
]

# The shipped default, by value (not by list index, which changes if the options are
# ever reordered). Must stay equal to AppConfig.audio_mode's default — the config is the
# authority on what the engine gets, this one only decides what the row shows in the
# moment before restore_from_config() runs.
DEFAULT_AUDIO_MODE_VALUE = "auto"


_CAT_HELP = {
    "Decoding":     "Hardware acceleration and deinterlacing. Auto-copy is recommended — it uses the GPU for decoding while keeping full compatibility with filters and shaders.",
    "Tracks":       "Select which video, audio and subtitle streams to play. Most files offer multiple audio languages or subtitle options.",
    "Audio Output": "Choose the output device and audio delivery mode. Use Bitstream to pass Dolby/DTS to a receiver; use LPCM Decode for headphones or simple speakers.",
    "Display":      "Aspect ratio override and playback speed. Use aspect ratio to fix wrongly-tagged files; speed is pitch-corrected so dialogue stays intelligible.",
    "Sync":         "Fix lip-sync issues by shifting audio or subtitle timing relative to the video. Positive values delay the track; negative values advance it.",
}

_HELP = {
    "HW Decode":       "Hardware-accelerated video decoding. Auto-copy uses the GPU decoder and copies frames to system RAM — compatible with all filters. Zero-copy modes are faster but may conflict with some effects.",
    "Active HW decode":"The decoder mpv is currently using for this file.",
    "Deinterlace":     "Convert interlaced video (broadcast/DVD) to progressive. Leave off for modern progressive content.",
    "Video track":     "Select which video stream to play. Most files have only one.",
    "Audio track":     "Select the audio language or commentary track.",
    "Subtitle track":  "Select subtitle language. Off disables subtitles.",
    "Device":          "Audio output device. Default uses the system default. Select a specific device to route audio to a particular soundcard or HDMI output.",
    "Audio mode":      "Decode to LPCM for maximum compatibility. Bitstream passes compressed Dolby/DTS to your receiver so it decodes natively and shows the correct format logo.",
    "Volume normalise":"Applies dynamic audio normalisation (dynaudnorm). Levels out loud and quiet passages. Useful for late-night viewing.",
    "Aspect ratio":    "Override the video's native aspect ratio. Source uses the container's ratio. Use 16:9, 4:3 etc. to correct wrongly-tagged files.",
    "Speed":           "Playback speed multiplier. 1.0 = normal. Audio pitch is corrected automatically.",
    "Audio delay":     "Shift audio forward (+) or backward (−) relative to video. Use to fix lip-sync issues.",
    "Subtitle delay":  "Shift subtitles forward (+) or backward (−) relative to video.",
    "Reset delays":    "Reset both audio and subtitle delay back to 0.",
}


_PB_ICONS = [
    ("Decoding",      "◈",  "DECODE"),
    ("Tracks",        "≋",  "TRACKS"),
    ("Audio Output",  "◉",  "AUDIO"),
    ("Display",       "▦",  "DISPLAY"),
    ("Sync",          "⊕",  "SYNC"),
]
_PB_ICON_COLORS = {
    "Decoding":     "#5B8FD0",   # blue
    "Tracks":       "#C8A030",   # gold
    "Audio Output": "#4CAF78",   # green
    "Display":      "#CC7040",   # amber
    "Sync":         "#909090",   # grey
}


class PlaybackControlsPanel(QWidget):
    """
    Emits property_change(name, value) when the user changes a setting.
    Emits help_changed(text) when a row is focused (RightPanel shows it).
    """
    property_change = pyqtSignal(str, object)
    help_changed    = pyqtSignal(str)   # connected to RightPanel._help_lbl

    def __init__(self, app_config=None, parent=None) -> None:
        super().__init__(parent)
        self._app_config = app_config

        # Label → raw-value maps (updated dynamically by update_* methods)
        self._vid_track_map: dict = {}
        self._aud_track_map: dict = {}
        self._sub_track_map: dict = {"None": False}
        self._audio_device_map: dict = {"Auto": "auto"}

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"PlaybackControlsPanel {{ background: {_BG}; }}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ── Root: horizontal split — icon column + content stack ─────────────
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left icon column (80px) ──────────────────────────────────────────
        self._icon_col = QWidget()
        self._icon_col.setFixedWidth(80)
        self._icon_col.setStyleSheet("background: rgba(0,0,0,160); border-right: 1px solid rgba(255,255,255,8);")
        icon_vl = QVBoxLayout(self._icon_col)
        icon_vl.setContentsMargins(0, 8, 0, 8)
        icon_vl.setSpacing(0)

        self._pb_cat_btns: dict[str, QWidget] = {}
        self._pb_icon_lbls: dict[str, QLabel] = {}
        self._pb_name_lbls: dict[str, QLabel] = {}

        for cat_name, icon_char, short_label in _PB_ICONS:
            icon_color = _PB_ICON_COLORS.get(cat_name, "#888")
            cont = QWidget()
            cont.setFixedSize(80, 60)
            cont.setCursor(Qt.CursorShape.PointingHandCursor)
            cont.setStyleSheet("background: transparent; border-left: 3px solid transparent;")
            inner = QVBoxLayout(cont)
            inner.setContentsMargins(4, 6, 4, 6)
            inner.setSpacing(3)
            inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl = QLabel(icon_char)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet(f"font-size: 22px; color: {icon_color}; background: transparent; border: none;")
            name_lbl = QLabel(short_label)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 9px; color: #777; letter-spacing: 0.8px; font-weight: 600; background: transparent; border: none;")
            inner.addWidget(icon_lbl)
            inner.addWidget(name_lbl)
            cont.mousePressEvent = lambda e, k=cat_name: self._select_pb_cat(k)
            icon_lbl.mousePressEvent = lambda e, k=cat_name: self._select_pb_cat(k)
            name_lbl.mousePressEvent = lambda e, k=cat_name: self._select_pb_cat(k)
            icon_vl.addWidget(cont)
            self._pb_cat_btns[cat_name] = cont
            self._pb_icon_lbls[cat_name] = icon_lbl
            self._pb_name_lbls[cat_name] = name_lbl

        icon_vl.addStretch()
        root.addWidget(self._icon_col)

        # ── Right: content stack ─────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        root.addWidget(self._stack, 1)

        self._picker_page = _RowPage()

        # Build rows and category pages
        self._build_rows()
        self._cat_pages: dict[str, _RowPage] = {}
        self._build_cat_pages()

        # Add category pages then picker to stack
        for page in self._cat_pages.values():
            self._stack.addWidget(page)
        self._stack.addWidget(self._picker_page)

        # Navigation state
        self._current_cat = list(self._cat_pages.keys())[0]
        self._in_picker = False
        self._active_picker: Optional[_PickerRow] = None

        # Select first category
        self._select_pb_cat(self._current_cat)

    # ── Row construction ──────────────────────────────────────────────

    def _build_rows(self) -> None:
        """Instantiate every row widget and connect its value signal."""

        # --- Decoding ---
        hwdec_labels = [l for l, _ in HWDEC_OPTIONS]
        self._hwdec_row = _PickerRow("HW Decode", hwdec_labels, hwdec_labels[0])
        self._hwdec_row.picked.connect(self._on_hwdec_picked)
        self._hwdec_row.activated.connect(
            lambda: self._open_picker(self._hwdec_row))

        self._hwdec_actual_row = _ActionRow("Active HW decode", "—")

        self._deint_row = _BoolRow("Deinterlace", False)
        self._deint_row.value_changed.connect(self._on_deint_changed)

        # --- Tracks ---
        self._vid_row = _PickerRow("Video track", [], "")
        self._vid_row.picked.connect(
            lambda l: self._on_track_picked("vid", l, self._vid_track_map))
        self._vid_row.activated.connect(
            lambda: self._open_picker(self._vid_row))

        self._aud_row = _PickerRow("Audio track", [], "")
        self._aud_row.picked.connect(
            lambda l: self._on_track_picked("aid", l, self._aud_track_map))
        self._aud_row.activated.connect(
            lambda: self._open_picker(self._aud_row))

        self._sub_row = _PickerRow("Subtitle track", ["None"], "None")
        self._sub_row.picked.connect(
            lambda l: self._on_track_picked("sid", l, self._sub_track_map))
        self._sub_row.activated.connect(
            lambda: self._open_picker(self._sub_row))

        # --- Audio Output ---
        self._audio_dev_row = _PickerRow("Device", ["Auto"], "Auto")
        self._audio_dev_row.picked.connect(self._on_audio_device_picked)
        self._audio_dev_row.activated.connect(
            lambda: self._open_picker(self._audio_dev_row))

        audio_mode_labels = [l for l, _, _ in AUDIO_MODES]
        # Seed from the shipped default, not from index 0. The row used to open on
        # "Decode to LPCM" for the moment before the config was applied, which showed the
        # user the opposite of what the app actually does by default.
        self._audio_mode_row = _PickerRow(
            "Audio Mode", audio_mode_labels,
            next((l for l, v, _ in AUDIO_MODES if v == DEFAULT_AUDIO_MODE_VALUE),
                 audio_mode_labels[0]))
        self._audio_mode_row.picked.connect(self._on_audio_mode_picked)
        self._audio_mode_row.activated.connect(
            lambda: self._open_picker(self._audio_mode_row))

        self._vol_norm_row = _BoolRow("Volume normalise", False)
        self._vol_norm_row.value_changed.connect(self._on_vol_norm_changed)

        # --- Display ---
        aspect_labels = [l for l, _ in ASPECT_OPTIONS]
        self._aspect_row = _PickerRow("Aspect ratio", aspect_labels, aspect_labels[0])
        self._aspect_row.picked.connect(self._on_aspect_picked)
        self._aspect_row.activated.connect(
            lambda: self._open_picker(self._aspect_row))

        self._speed_row = _FloatRow("Speed", 0.1, 4.0, 1.0, step=0.05, decimals=2)
        self._speed_row.value_changed.connect(
            lambda v: self.property_change.emit("speed", v))

        # --- Sync ---
        self._aud_delay_row = _FloatRow("Audio delay", -10.0, 10.0, 0.0,
                                        step=0.05, decimals=2)
        self._aud_delay_row.value_changed.connect(
            lambda v: self.property_change.emit("audio-delay", v))

        self._sub_delay_row = _FloatRow("Subtitle delay", -30.0, 30.0, 0.0,
                                        step=0.1, decimals=2)
        self._sub_delay_row.value_changed.connect(
            lambda v: self.property_change.emit("sub-delay", v))

        self._reset_row = _ActionRow("Reset delays", "→ 0s")
        self._reset_row.activated.connect(self._reset_delays)

    def _build_cat_pages(self) -> None:
        """Create one _RowPage per category and populate it with pre-built rows."""
        cats = [
            ("Decoding",     [self._hwdec_row, self._hwdec_actual_row,
                              self._deint_row]),
            ("Tracks",       [self._vid_row, self._aud_row, self._sub_row]),
            ("Audio Output", [self._audio_dev_row, self._audio_mode_row,
                              self._vol_norm_row]),
            ("Display",      [self._aspect_row, self._speed_row]),
            ("Sync",         [self._aud_delay_row, self._sub_delay_row,
                              self._reset_row]),
        ]
        for name, rows in cats:
            page = _RowPage()
            for row in rows:
                page.add_row(row)
            page.focus_changed.connect(self._update_pb_help)
            self._cat_pages[name] = page

    def _update_pb_help(self, row: _Row) -> None:
        """Route focused-row help to RightPanel via help_changed signal."""
        text = _HELP.get(row._label.text(), "") or _CAT_HELP.get(row._label.text(), "")
        self.help_changed.emit(
            f"<b style='color:#E8551F'>Info:</b>  {text}" if text
            else f"<span style='color:#555'>{row._label.text()}</span>"
        )

    # ── Icon category navigation ────────────────────────────────────────────

    def _select_pb_cat(self, key: str) -> None:
        """Switch content stack to the selected category page."""
        self._current_cat = key
        self._in_picker = False
        for k, cont in self._pb_cat_btns.items():
            active = (k == key)
            cont.setStyleSheet(
                "background: rgba(232,85,31,14); border-left: 3px solid #E8551F;"
                if active else
                "background: transparent; border-left: 3px solid transparent;"
            )
            icon_c = "#E8551F" if active else _PB_ICON_COLORS.get(k, "#888")
            name_c = "#E8551F" if active else "#777"
            self._pb_icon_lbls[k].setStyleSheet(
                f"font-size: 22px; color: {icon_c}; background: transparent; border: none;")
            self._pb_name_lbls[k].setStyleSheet(
                f"font-size: 9px; color: {name_c}; letter-spacing: 0.8px; "
                f"font-weight: 600; background: transparent; border: none;")
        self._stack.setCurrentWidget(self._cat_pages[key])
        self._cat_pages[key].activate()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _current_page(self) -> _RowPage:
        if self._in_picker:
            return self._picker_page
        return self._cat_pages.get(self._current_cat, self._picker_page)

    def _go_back(self) -> None:
        """Return from picker to current category page."""
        if self._in_picker:
            self._in_picker = False
            page = self._cat_pages[self._current_cat]
            self._stack.setCurrentWidget(page)
            page.activate()

    def _open_picker(self, picker_row: _PickerRow) -> None:
        """Open a full-page option list for picker_row."""
        self._active_picker = picker_row
        self._picker_page.clear()

        for opt in picker_row._options:
            is_current = (opt == picker_row._current)
            row = _ActionRow(opt, "✓" if is_current else "")
            if is_current:
                row._label.setStyleSheet(
                    "color:#E8551F; font-size:14px; font-weight:600;"
                    " background:transparent;")

            def _pick(o=opt, pr=picker_row):
                pr._current = o
                pr._show()
                pr.picked.emit(o)
                self._go_back()

            row.activated.connect(_pick)
            self._picker_page.add_row(row)
            if is_current:
                self._picker_page._focus_idx = len(self._picker_page._rows) - 1

        self._in_picker = True
        self._stack.setCurrentWidget(self._picker_page)
        self._picker_page.activate()

    # ── Keyboard ──────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key  = event.key()
        page = self._current_page()

        if key == Qt.Key.Key_Up:
            page.handle_up()
        elif key == Qt.Key.Key_Down:
            page.handle_down()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            page.handle_enter()
        elif key == Qt.Key.Key_Right:
            page.handle_right()
        elif key == Qt.Key.Key_Left:
            if self._in_picker:
                self._go_back()
            else:
                page.handle_left()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            if self._in_picker:
                self._go_back()
        else:
            super().keyPressEvent(event)

    # ── Public API — called from MainWindow to sync state ─────────────

    def update_track_list(self, tracks: list) -> None:
        """Populate track picker options from mpv's track-list property."""
        vid, aud, sub = [], [], []
        for t in (tracks or []):
            tid      = t.get("id", 0)
            lang     = t.get("lang") or ""
            title    = t.get("title") or ""
            codec    = t.get("codec") or ""
            sel      = t.get("selected", False)
            ttype    = t.get("type", "")
            w        = t.get("demux-w") or 0
            h        = t.get("demux-h") or 0
            channels = t.get("demux-channel-count") or 0
            label = _track_label(tid, lang, title, codec, w, h, channels, ttype)
            if ttype == "video":
                vid.append((label, tid, sel))
            elif ttype == "audio":
                aud.append((label, tid, sel))
            elif ttype == "sub":
                sub.append((label, tid, sel))

        self._update_track_picker(self._vid_row, vid,
                                  self._vid_track_map, "")
        self._update_track_picker(self._aud_row, aud,
                                  self._aud_track_map, "")
        self._update_track_picker(self._sub_row, sub,
                                  self._sub_track_map, "Off",
                                  none_val=False)

    def update_audio_devices(self, devices: list) -> None:
        """Populate audio device picker options."""
        self._audio_device_map.clear()
        self._audio_device_map["Auto"] = "auto"
        options = ["Auto"]
        for d in (devices or []):
            name = d.get("name", "")
            desc = d.get("description", name)[:50]
            options.append(desc)
            self._audio_device_map[desc] = name
        self._audio_dev_row._options = options
        if self._audio_dev_row._current not in options:
            self._audio_dev_row._current = options[0] if options else ""
        self._audio_dev_row._show()

    def update_hwdec_actual(self, value: str) -> None:
        self._hwdec_actual_row._value_lbl.setText(value or "software")

    def update_property(self, name: str, value) -> None:
        """Sync a row widget when mpv reports a property change."""
        if name == "hwdec":
            v = value[0] if isinstance(value, list) else str(value)
            for label, val in HWDEC_OPTIONS:
                if val == v:
                    self._hwdec_row.set_value(label)
                    break
        elif name == "hwdec-current":
            self.update_hwdec_actual(str(value) if value else "no")
        elif name == "deinterlace":
            self._deint_row.set_value(bool(value))
        elif name == "audio-device":
            label = next(
                (l for l, v in self._audio_device_map.items()
                 if v == str(value)),
                None)
            if label:
                self._audio_dev_row.set_value(label)
        elif name == "audio-spdif":
            v = str(value) if value else ""
            for label, val, _ in AUDIO_MODES:
                if val == v:
                    self._audio_mode_row.set_value(label)
                    break
        elif name == "speed":
            try:
                self._speed_row.set_value(float(value))
            except (TypeError, ValueError):
                pass
        elif name == "audio-delay":
            try:
                self._aud_delay_row.set_value(float(value))
            except (TypeError, ValueError):
                pass
        elif name == "sub-delay":
            try:
                self._sub_delay_row.set_value(float(value))
            except (TypeError, ValueError):
                pass
        elif name == "vid":
            label = next(
                (l for l, v in self._vid_track_map.items() if v == value), None)
            if label:
                self._vid_row.set_value(label)
        elif name == "aid":
            label = next(
                (l for l, v in self._aud_track_map.items() if v == value), None)
            if label:
                self._aud_row.set_value(label)
        elif name == "sid":
            label = next(
                (l for l, v in self._sub_track_map.items() if v == value), None)
            if label:
                self._sub_row.set_value(label)

    def reset_for_new_file(self) -> None:
        """Reset per-file state between files (no signals emitted)."""
        self._aud_delay_row.set_value(0.0)
        self._sub_delay_row.set_value(0.0)
        self._speed_row.set_value(1.0)
        # Clear track pickers
        self._vid_row._options = []
        self._vid_row._current = ""
        self._vid_row._show()
        self._vid_track_map.clear()
        self._aud_row._options = []
        self._aud_row._current = ""
        self._aud_row._show()
        self._aud_track_map.clear()
        self._sub_row._options = ["None"]
        self._sub_row._current = "None"
        self._sub_row._show()
        self._sub_track_map.clear()
        self._sub_track_map["None"] = False

    def restore_from_config(self) -> None:
        """Apply saved session preferences to rows (no signals emitted)."""
        if not self._app_config:
            return
        cfg = self._app_config

        # HW decode
        for label, val in HWDEC_OPTIONS:
            if val == cfg.hwdec:
                self._hwdec_row.set_value(label)
                break

        # Audio mode
        for label, val, _ in AUDIO_MODES:
            if val == cfg.audio_mode:
                self._audio_mode_row.set_value(label)
                break

        # Audio device (best-effort; device list may not be populated yet)
        dev_label = next(
            (l for l, v in self._audio_device_map.items()
             if v == cfg.audio_device),
            None)
        if dev_label:
            self._audio_dev_row.set_value(dev_label)

        # Deinterlace
        self._deint_row.set_value(cfg.deinterlace)

    def emit_saved_settings(self) -> None:
        """Emit property_change for all saved persistent settings."""
        if not self._app_config:
            return
        cfg = self._app_config
        self.property_change.emit("hwdec", [cfg.hwdec])
        self.property_change.emit("audio-spdif", cfg.audio_mode)
        self.property_change.emit("audio-device", cfg.audio_device)
        self.property_change.emit("deinterlace", cfg.deinterlace)

    # ── Internal helpers ──────────────────────────────────────────────

    def _update_track_picker(self, row: _PickerRow, tracks: list,
                              track_map: dict, none_label: str = "",
                              none_val=None) -> None:
        """Rebuild options and label→id map for a track picker row."""
        options: list = []
        track_map.clear()
        if none_label:
            options.append(none_label)
            track_map[none_label] = none_val
        selected_label = none_label
        for label, tid, sel in tracks:
            options.append(label)
            track_map[label] = tid
            if sel:
                selected_label = label
        row._options = options
        row._current = (selected_label if selected_label in options
                        else (options[0] if options else ""))
        row._show()

    def _on_hwdec_picked(self, label: str) -> None:
        hwdec_map = {l: v for l, v in HWDEC_OPTIONS}
        val = hwdec_map.get(label, "")
        if self._app_config:
            self._app_config.hwdec = val
        self.property_change.emit("hwdec", [val])

    def _on_deint_changed(self, v: bool) -> None:
        if self._app_config:
            self._app_config.deinterlace = v
        self.property_change.emit("deinterlace", v)

    def _on_vol_norm_changed(self, v: bool) -> None:
        # dynaudnorm: real-time dynamic loudness normalisation audio filter
        self.property_change.emit("af", ["dynaudnorm"] if v else [])

    def _on_audio_device_picked(self, label: str) -> None:
        val = self._audio_device_map.get(label, "auto")
        if self._app_config:
            self._app_config.audio_device = val
        self.property_change.emit("audio-device", val)

    def _on_audio_mode_picked(self, label: str) -> None:
        mode_map = {l: v for l, v, _ in AUDIO_MODES}
        val = mode_map.get(label, "")
        if self._app_config:
            self._app_config.audio_mode = val
            # Mark it as a decision. This is the only place the flag is set, and it is
            # what lets the load() migration tell "the old default was saved" apart from
            # "the user asked for LPCM" — both are the empty string.
            self._app_config.audio_mode_explicit = True
        self.property_change.emit("audio-spdif", val)

    def _on_aspect_picked(self, label: str) -> None:
        aspect_map = {l: v for l, v in ASPECT_OPTIONS}
        val = aspect_map.get(label, "")
        self.property_change.emit("video-aspect-override", val or "-1")

    def _on_track_picked(self, prop: str, label: str, track_map: dict) -> None:
        if label in track_map:
            self.property_change.emit(prop, track_map[label])

    def _reset_delays(self) -> None:
        self._aud_delay_row.set_value(0.0)
        self._sub_delay_row.set_value(0.0)
        self.property_change.emit("audio-delay", 0.0)
        self.property_change.emit("sub-delay", 0.0)


_LANG_NAMES = {
    # 3-letter ISO 639-2
    "eng": "English", "und": "", "zxx": "",
    "jpn": "Japanese", "fre": "French", "fra": "French",
    "ger": "German",   "deu": "German", "spa": "Spanish",
    "ita": "Italian",  "por": "Portuguese", "rus": "Russian",
    "chi": "Chinese",  "zho": "Chinese",    "kor": "Korean",
    "ara": "Arabic",   "hin": "Hindi",      "dut": "Dutch",
    "nld": "Dutch",    "pol": "Polish",     "swe": "Swedish",
    "nor": "Norwegian","dan": "Danish",     "fin": "Finnish",
    "tha": "Thai",     "vie": "Vietnamese", "tur": "Turkish",
    "heb": "Hebrew",   "cze": "Czech",      "ces": "Czech",
    # 2-letter ISO 639-1
    "en": "English", "ja": "Japanese", "fr": "French",
    "de": "German",  "es": "Spanish",  "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "zh": "Chinese",
    "ko": "Korean",  "ar": "Arabic",   "hi": "Hindi",
    "nl": "Dutch",   "pl": "Polish",   "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish",
    "th": "Thai",    "vi": "Vietnamese", "tr": "Turkish",
    "he": "Hebrew",  "cs": "Czech",
}

_CODEC_SHORT = {
    "hevc": "HEVC", "h264": "H.264", "avc": "H.264",
    "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
    "mpeg4": "MPEG-4", "mpeg2video": "MPEG-2",
    "ac3": "AC3", "eac3": "E-AC3", "truehd": "TrueHD",
    "dts": "DTS", "dca": "DTS",
    "aac": "AAC", "mp3": "MP3", "opus": "Opus", "flac": "FLAC",
    "vorbis": "Vorbis", "pcm_s16le": "PCM", "pcm_s24le": "PCM",
    "ass": "ASS", "subrip": "SRT", "srt": "SRT",
    "pgssub": "PGS", "dvdsub": "DVD", "hdmv_pgs_subtitle": "PGS",
}

_CH_LABELS = {1: "Mono", 2: "Stereo", 6: "5.1", 7: "6.1", 8: "7.1"}


def _track_label(tid: int, lang: str, title: str, codec: str,
                 w: int = 0, h: int = 0, channels: int = 0,
                 track_type: str = "") -> str:
    codec_s  = _CODEC_SHORT.get((codec or "").lower(), (codec or "").upper()) or ""
    lang_s   = _LANG_NAMES.get((lang or "").lower(), (lang or "").upper() if lang else "")
    if lang_s in ("UND", "ZXX", ""):
        lang_s = ""

    parts = []

    if track_type == "video":
        if codec_s:
            parts.append(codec_s)
        if h:
            parts.append(f"{h}p")
        elif title:
            parts.append(title[:24])
        if not parts:
            parts.append(f"Track {tid}")

    elif track_type == "audio":
        if lang_s:
            parts.append(lang_s)
        elif title:
            parts.append(title[:24])
        if codec_s:
            parts.append(codec_s)
        ch_s = _CH_LABELS.get(channels, f"{channels}ch" if channels > 2 else "")
        if ch_s:
            parts.append(ch_s)
        if not parts:
            parts.append(f"Track {tid}")

    else:  # subtitle — language only, no codec noise
        if lang_s:
            parts.append(lang_s)
        if title and title.lower() not in (lang_s.lower(), ""):
            parts.append(title[:24])
        if not parts:
            parts.append(f"Track {tid}")

    return "  ·  ".join(parts)

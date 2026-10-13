"""
Settings panel — two-column layout with permanent icon category selector.

Left column (84px): icon buttons for groups (SOURCE, HDR, ZION CORE, OUTPUT, SYSTEM)
Right area: group content page with section headers + shared help label at bottom

Public API (unchanged):
  Signals : profile_changed, opacity_changed, app_mode_changed, input_changed,
            wallpaper_change_requested
  Methods : set_profile(), set_hdr_active(), set_app_mode(), sync_device_combo()
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
)

from ..config.model import AppConfig, MpvProfile
from ..core.live_settings import apply_live_change, SETTING_GROUPS

_audit = logging.getLogger("unplugged.audit")

from .settings_rows import (
    _show_entry_dialog, _Row, _CategoryRow, _EnumRow, _BoolRow,
    _IntRow, _FloatRow, _ActionRow, _PickerRow, _RowPage,
    _BG, _ROW_NORMAL, _ROW_FOCUSED, _ROW_H,
    _DISPLAY_TRC, _DISPLAY_PRIM, _DISPLAY_TM, _DISPLAY_GAMUT,
    _DISPLAY_PEAK, _DISPLAY_KERN,
)


# ── Category-level help ───────────────────────────────────────────────────────
_CAT_HELP = {
    "Input Device":      "Select and name your DeckLink capture ports. Switch the active input here — changing input terminates the current capture and reconnects on the new port.",
    "Tone Mapping":      "Controls how HDR content is compressed to fit your display's brightness range. The algorithm, target peak and max boost are the primary levers for tuning HDR picture quality.",
    "Peak Detection":    "How libplacebo measures content brightness per-frame to drive tone mapping decisions. Per-frame measurement gives the most accurate result; static metadata uses the values embedded in the file.",
    "Contrast Recovery": "Recovers fine detail lost when HDR is compressed to SDR. Disabled when Zion Core is active — Construct CR takes over.",
    "Picture":           "VO equaliser: brightness, contrast, saturation, hue, sharpening. Gamma is disabled when Zion Core is active (The Oracle owns it). Saturation interacts with Spectrum Shift if non-zero.",
    "Zion Core":         "ML-powered HDR enhancement suite. The Oracle adapts the gamma curve per scene; Construct CR recovers micro-contrast; Resonance maps highlight radiance; Spectrum Shift enhances chroma with skin protection. Enabling Zion Core takes over contrast recovery automatically.",
    "Display Target":    "Describes your display to libplacebo. Target TRC and peak are the most important — set them to match your projector or TV's actual gamma and peak brightness.",
    "Gamut Mapping":     "Handles colours that fall outside your display's colour gamut. Perceptual mode compresses the whole gamut smoothly; Soft Clip only touches the most saturated outliers.",
    "Geometry":          "Zoom, pan and rotate the video output. Use zoom + pan to crop letterbox bars or adjust framing. Rotate for sideways content.",
    "Scaling":           "Filters used to resize the video to your screen. Scale (upscaling) has the most visible impact. Spline36 is a sharp, high-quality default.",
    "Dithering":         "Reduces banding when the output bit depth is lower than the source. Fruit dithering with temporal averaging is the libplacebo recommended default.",
    "Debanding":         "Removes visible banding (gradient steps) in smooth areas like skies. Increases GPU load. Off by default — enable if you see banding in the picture.",
    "Output":            "Video output driver. gpu-next (libplacebo) is the only fully-supported option for HDR tone mapping.",
    "Performance":       "Low-level buffering and threading options. Changing these requires a capture restart. The defaults are tuned for low-latency DeckLink capture.",
    "Shaders":           "GLSL post-processing shaders applied after tone mapping. KrigBilateral improves chroma quality; adaptive-sharpen adds edge enhancement.",
    "App":               "Application mode and wallpaper. Switch between Video Processor (live HDMI capture) and Media Player (local files).",
}

# ── Setting-level help ────────────────────────────────────────────────────────
_HELP = {
    # Tone mapping
    "Algorithm": "Controls how HDR content is mapped to your display's brightness range. Auto lets mpv choose (usually Spline). Spline is a good default. BT.2390 follows the HDTV standard. ST.2094-10 uses dynamic per-scene metadata (required for Dolby Vision). ST.2094-40 adds HDR10+ dynamic metadata support. Clip applies no tone-mapping (hard clip).",
    "Max boost": "Maximum brightness amplification factor for HDR highlights. 1.0 means no boost. Higher values recover more peak brightness but may clip highlights.",
    "Inverse TM":   "Enables SDR-to-HDR upconversion. Expands a standard dynamic range signal to fill the HDR display's brightness range.",
    "Visualize":    "Overlays a debug graph showing the tone mapping curve and measured peak. Useful for diagnosing how libplacebo is mapping the content — not intended for viewing.",
    # Peak detection
    "Compute peak": "How libplacebo measures content brightness. Per-frame measures each frame individually (most accurate). Auto uses static metadata when available.",
    "Percentile": "The percentile of pixels used for peak detection. 99.995 avoids clipping specular highlights.",
    "Decay rate": "How quickly the measured peak adapts to scene changes. Lower values react faster but may cause flickering on cuts.",
    "Threshold low": "Minimum scene luminance change (in dB) to trigger a tone mapping adjustment.",
    "Threshold high":  "Maximum scene luminance change (in dB) above which tone mapping adjusts immediately.",
    "Delayed detect":  "Allow libplacebo to delay peak detection by one frame for slightly more accurate results. Adds one frame of latency.",
    # Contrast recovery
    "Recovery": "Sharpening of fine detail lost during tone mapping. 0.3 is the libplacebo recommended value. Values above 0.5 may cause ringing.",
    "Smoothness": "Controls how gradually the contrast recovery is applied. Higher values are smoother but less effective.",
    # Display target
    "Target TRC": "The gamma curve libplacebo targets when tone mapping to your display. Gamma 2.4 is the cinema/projector standard (punchier than 2.2). Auto converts HDR→Gamma 2.2 and leaves SDR untouched. BT.1886 is HDTV standard but requires correct display calibration to work properly.",
    "Target prim": "The colour primaries of your display. Auto lets mpv detect via EDID. BT.709 for standard HD. BT.2020 for full wide-gamut. Display P3 for most modern projectors/TVs (~95% P3 coverage). DCI-P3 for cinema projectors (D65 white). Use auto when Windows HDR is enabled — the OS reports the correct primaries.",
    "Target peak": "Your display's maximum brightness in nits. Set this to your display's measured peak white (e.g. 100 for most projectors, 1000+ for HDR TVs).",
    "CS hint": "Whether to signal HDR metadata to the OS/display driver. Auto skips the signal when tone mapping to SDR.",
    # Gamut mapping
    "Gamut mode":  "How colours outside the display's colour gamut are handled. Auto lets mpv choose. Perceptual compresses smoothly — best for most content. Relative Colorimetric is accurate but clips. Saturation maximises vivid colours. Desaturate pulls out-of-gamut colours toward grey. Darken reduces brightness to fit gamut. Clip is a hard cut. Warn highlights out-of-gamut pixels (debug).",
    "Perc strength": "Strength of the perceptual gamut compression. Lower values preserve saturation more aggressively.",
    "Softclip knee": "Point at which soft clipping begins for out-of-gamut colours (0–1). Lower = clip earlier.",
    "Gamut expand": "Allow the display to show colours beyond its native gamut by using tone mapping in reverse.",
    # Picture
    "Brightness": "Shifts the overall luminance of the image up or down. 0 is neutral.",
    "Contrast": "Expands or compresses the tonal range. 0 is neutral.",
    "Saturation": "Increases or decreases colour intensity. 0 is neutral.",
    "Hue": "Rotates the colour wheel. 0 is neutral.",
    "Gamma": "Applies a power-law brightness correction. 0 is neutral.",
    "Sharpen": "Edge enhancement via the adaptive-sharpen shader. Positive = sharpen, negative = soften.",
    # Geometry
    "Zoom": "Scales the video. 0.0 = fill, positive = zoom in, negative = zoom out.",
    "Pan X": "Horizontal offset. Use after zooming to reframe.",
    "Pan Y": "Vertical offset. Use after zooming to reframe.",
    "Rotate": "Rotates the video 90°/180°/270°.",
    # Scaling
    "Scale": "Upscaling algorithm. Spline36 is a sharp, high-quality default.",
    "Dscale": "Downscaling algorithm. Mitchell is a standard choice that avoids ringing.",
    "Cscale": "Chroma upscaling algorithm used to reconstruct 4:2:0 chroma samples.",
    "Linear downscaling": "Downscale in linear light for more accurate brightness. Recommended.",
    "Scale blur":  "Kernel sharpness modifier for EWA Lanczos (0.9812 = ewa_lanczossharp). Leave at 0 for other kernels.",
    # Dithering
    "Dither algorithm": "Method used to reduce banding when quantising to lower bit depth. Fruit (ordered + randomised) is the libplacebo default and works well for most content.",
    "Temporal":    "Randomises the dither pattern each frame to reduce perceived banding. Recommended — the pattern changes are imperceptible at normal frame rates.",
    "Fruit size":  "Matrix size for fruit (ordered) dithering. Larger = finer pattern but more GPU memory. 6 is the libplacebo default.",
    # Debanding
    "Enabled":     "Applies a debanding filter to remove visible banding (stepped gradients) in smooth areas like skies. Increases GPU load slightly.",
    "Iterations":  "Number of debanding passes. More passes = stronger effect but higher GPU cost. 1 is usually sufficient.",
    "Threshold":   "Sensitivity of the debanding filter. Higher values remove more banding but may blur fine detail.",
    "Range":       "How far from each pixel the debanding filter samples. Larger values handle wider banding but cost more GPU.",
    "Grain":       "Adds film grain after debanding to mask residual banding. 0 = no grain.",
    # Output
    "VO":          "Video output driver. gpu-next (libplacebo) is the only fully supported option for HDR tone mapping and wide colour gamut.",
    # Performance
    "No cache":    "Disables the forward playback cache. Required for live DeckLink capture — caching live video makes no sense. Leave on for VP mode.",
    "No demuxer thread": "Runs the demuxer on the main thread rather than a background thread. Reduces latency for live capture at the cost of slight CPU overhead.",
    # Zion Core
    "Zion Core":          "Master toggle for the ML pipeline. Off = full bypass, libplacebo standard CR takes over.",
    "Oracle: Auto":       "The Oracle predicts gamma curve per-scene via XGBoost. Off = use manual value below.",
    "Oracle value":       "Manual gamma curve override (0.5–1.5, neutral=1.0). Active only when Oracle Auto is Off.",
    "Construct CR: Auto": "GPU bilateral filter for spatial micro-contrast. Off = fixed strength below.",
    "CR strength":        "Manual bilateral CR strength (0.0–0.5, default=0.30). Active when Construct CR Auto is Off.",
    "Resonance: Auto":    "Adaptive radiance spline for highlight gleam. Off = manual knee + strength below.",
    "Radiance knee":      "Breakpoint where radiance lift begins (0.4–0.9, default=0.6). Active when Resonance Auto is Off.",
    "Radiance strength":  "Strength of the highlight radiance lift (0.0–0.6, default=0.30). Active when Resonance Auto is Off.",
    "Shadow recover":     "Pre-curve 5×5 bilateral filter + ML toe-lift that un-crushes near-black detail while keeping black anchored (no fog). Auto uses the shadow model (or luminance heuristic); Manual applies fixed strength.",
    "Shadow strength":    "Denoise + toe-lift gain in shadow zones y_pq < 0.35 (0.0–0.5, default=0.20). Higher = stronger un-crush of dark gradients. Active when Shadow recover = Manual.",
    "SDR→P5 emulation":  "SDR→P5 bridge (Phase C): elevates SDR sources to a virtual DV-mastered HDR signal before grading (decode bt.1886 → scale to the virtual ceiling → PQ). Tone-mapping + ML then apply to the virtual master, giving the DV-style expansion look. OFF = pure SDR pass-through.",
    "Virtual P5 nits":   "Virtual P5 ceiling in nits (100–4000, default 1000). SDR white maps to this after the expansion. Barely visible alone (tone-map cancels the gain) — pair with Emulation strength for the visible lift.",
    "Emulation strength": "Shaped mid-lift for the SDR→P5 curve (0 = pure linear gain, 1 = strong lift that survives tone-mapping). This is the knob that makes the DV-expansion look visible.",
    "Highlight smooth":   "Post-curve 5×5 bilateral filter for specular highlight smoothing. Knee follows Oracle gamma so it only activates in near-clipped zones.",
    "Highlight strength": "Bilateral blend strength in highlight zones (0.0–0.4, default=0.15). Active when Highlight smooth = Manual.",
    "Neutral boost":      "Chroma saturation boost for neutral/low-saturation colours (1.0–1.5, default=1.20).",
    "Fire boost":         "Chroma saturation boost for highly saturated fire and neon tones (1.0–1.5, default=1.35).",
    "Spectrum knee":      "Saturation threshold where Fire Boost kicks in (0.1–0.9, default=0.55).",
    "Skin protect":       "Skin-tone hue desaturation protection (0.5–1.0, default=0.95). 1.0 = full protection.",
    # App
    "Background…": "Choose a wallpaper image shown behind the UI when no video is playing. Supports JPG and PNG.",
    # Input
    "Capture input":     "The DeckLink HDMI port to capture from. Selecting a different input terminates the current capture and reconnects on the chosen port.",
    "Configure inputs…": "Open the input configuration panel to name each DeckLink port and check signal status. Names set here appear in the capture input selector.",
    # App
    "Mode": "Switch between Video Processor (live DeckLink capture) and Media Player (local file playback).",
}

# ── Icon column styles ────────────────────────────────────────────────────────
_BTN_CAT = """
QPushButton {
    color: #555;
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 6px 2px;
    font-size: 11px;
    text-align: center;
}
QPushButton:hover { color: #aaa; background: rgba(255,255,255,6); }
"""
_BTN_CAT_ACTIVE = """
QPushButton {
    color: #E8551F;
    background: rgba(232,85,31,12);
    border: none;
    border-left: 3px solid #E8551F;
    border-radius: 0px;
    padding: 6px 2px;
    font-size: 11px;
    text-align: center;
}
"""
_SEC_STYLE = (
    "color:#E8551F; font-size:11px; font-weight:600; letter-spacing:1px; "
    "background:transparent; padding:10px 16px 4px 16px;"
)

# ── Group / category mapping ──────────────────────────────────────────────────
_GROUP_KEYS = ["source", "hdr", "zion", "output", "system"]
_GROUP_IDX  = {k: i for i, k in enumerate(_GROUP_KEYS)}
_GROUP_DISPLAY = {
    "source": "SOURCE",
    "hdr":    "HDR",
    "zion":   "ZION CORE",
    "output": "OUTPUT",
    "system": "SYSTEM",
}
_GROUP_ICONS = [
    ("source", "⬡",  "SOURCE"),
    ("hdr",    "◑",  "HDR"),
    ("zion",   "✦",  "ZION"),
    ("output", "▣",  "OUTPUT"),
    ("system", "≡",  "SYSTEM"),
]
# Distinct tint per group — visible against dark background, desaturated except when active
_ICON_COLORS = {
    "source": "#5B8FD0",   # blue — input/signal
    "hdr":    "#C8A030",   # gold — brightness/tone
    "zion":   "#C87040",   # amber — ML/Oracle
    "output": "#4CAF78",   # green — display output
    "system": "#909090",   # neutral grey — configuration
}
_GROUP_CATS = {
    "source": ["Input Device"],
    "hdr":    ["Tone Mapping", "Peak Detection", "Contrast Recovery",
               "Display Target", "Gamut Mapping"],
    "zion":   ["Zion Core"],
    "output": ["Scaling", "Dithering", "Debanding", "Shaders",
               "Picture", "Geometry", "Output"],
    "system": ["App"],
}
# Categories relegated to the ADVANCED view (hidden unless the toggle is on).
_ADV_CATS = {"Peak Detection", "Gamut Mapping", "Scaling", "Dithering",
             "Debanding", "Geometry", "Output", "Shaders"}
_CAT_BUILDER_MAP = {
    "Input Device":      "_build_input",
    "Tone Mapping":      "_build_tone_mapping",
    "Peak Detection":    "_build_peak_detection",
    "Contrast Recovery": "_build_contrast_recovery",
    "Zion Core":         "_build_zion_core",
    "Display Target":    "_build_display_target",
    "Gamut Mapping":     "_build_gamut_mapping",
    "Picture":           "_build_picture",
    "Geometry":          "_build_geometry",
    "Scaling":           "_build_scaling",
    "Dithering":         "_build_dithering",
    "Debanding":         "_build_deband",
    "Output":            "_build_output",
    "Performance":       "_build_performance",
    "Shaders":           "_build_shaders",
    "App":               "_build_app",
}

# ── Main SettingsPanel ────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    profile_changed            = pyqtSignal(str, object)
    wallpaper_change_requested = pyqtSignal()
    opacity_changed            = pyqtSignal(float)
    app_mode_changed           = pyqtSignal(str)
    input_changed              = pyqtSignal(str)
    help_changed               = pyqtSignal(str)   # emitted when a row is focused

    def __init__(self, app_config: AppConfig, profile: MpvProfile, parent=None):
        super().__init__(parent)
        self._app_config = app_config
        self._profile = deepcopy(profile)
        self._is_hdr = False
        self._emit_timers: dict = {}

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"SettingsPanel {{ background: {_BG}; }}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ── Root: horizontal split ─────────────────────────────────────────────
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left icon column ────────────────────────────────────────────────────
        # Each category is a QWidget container with two stacked QLabels
        # (icon at 20px + label at 9px) so each can have its own font size.
        self._icon_col = QWidget()
        self._icon_col.setFixedWidth(80)
        self._icon_col.setStyleSheet("background: rgba(0,0,0,160); border-right: 1px solid rgba(255,255,255,8);")
        icon_vl = QVBoxLayout(self._icon_col)
        icon_vl.setContentsMargins(0, 8, 0, 8)
        icon_vl.setSpacing(0)

        self._cat_btns: dict[str, QWidget] = {}       # QWidget containers, not QPushButton
        self._cat_icon_lbls: dict[str, QLabel] = {}
        self._cat_name_lbls: dict[str, QLabel] = {}

        for key, icon_char, label_text in _GROUP_ICONS:
            # Container — handles the left-border + background for active state
            icon_color = _ICON_COLORS.get(key, "#888")

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

            name_lbl = QLabel(label_text)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet(
                "font-size: 9px; color: #777; letter-spacing: 0.8px; font-weight: 600; "
                "background: transparent; border: none;")

            inner.addWidget(icon_lbl)
            inner.addWidget(name_lbl)

            # Click: route mouse press to _select_group
            cont.mousePressEvent = lambda e, k=key: self._select_group(k)
            # Forward child mouse events to parent container
            icon_lbl.mousePressEvent = lambda e, k=key: self._select_group(k)
            name_lbl.mousePressEvent = lambda e, k=key: self._select_group(k)

            icon_vl.addWidget(cont)
            self._cat_btns[key]      = cont
            self._cat_icon_lbls[key] = icon_lbl
            self._cat_name_lbls[key] = name_lbl

        # ── ADVANCED toggle (bottom of the icon column) ──────────────────────
        self._show_advanced = False
        adv_btn = QWidget()
        adv_btn.setFixedSize(80, 30)
        adv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        adv_btn.setStyleSheet("background: transparent;")
        self._adv_lbl = QLabel("ADVANCED")
        self._adv_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        adv_box = QVBoxLayout(adv_btn)
        adv_box.setContentsMargins(4, 0, 4, 0)
        adv_box.addWidget(self._adv_lbl)
        self._refresh_advanced_style()

        def _toggle_advanced():
            self._show_advanced = not self._show_advanced
            self._refresh_advanced_style()
            self._build_groups()   # rebuild pages with the new visibility

        adv_btn.mousePressEvent = lambda e: _toggle_advanced()
        self._adv_lbl.mousePressEvent = lambda e: _toggle_advanced()
        icon_vl.addWidget(adv_btn)

        icon_vl.addStretch()
        root.addWidget(self._icon_col)

        # ── Content stack [4] — fills remaining width ─────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        root.addWidget(self._stack, 1)

        # ── State ──────────────────────────────────────────────────────────────
        self._current_group_key: str = "hdr"
        self._active_picker: Optional[_PickerRow] = None
        self._group_pages: dict[str, _RowPage] = {}
        self._detail_page: Optional[_RowPage] = None  # target for _enum/_bool/etc.

        # Picker page sits at stack index 5 (added after the 5 group pages)
        self._picker_page = _RowPage()

        # Build group pages (indices 0–4) then add picker at index 5
        self._build_groups()
        self._stack.addWidget(self._picker_page)   # index 5

        # Start on HDR
        self._select_group("hdr")

    # ── Group building ────────────────────────────────────────────────────────

    def _refresh_advanced_style(self):
        """Style the ADVANCED toggle per state."""
        if self._show_advanced:
            self._adv_lbl.setStyleSheet(
                "font-size: 8px; letter-spacing: 1px; color: #E8551F; "
                "background: rgba(232,85,31,18); border: 1px solid #E8551F; "
                "border-radius: 6px; padding: 4px 0;")
        else:
            self._adv_lbl.setStyleSheet(
                "font-size: 8px; letter-spacing: 1px; color: #888; "
                "background: transparent; border: 1px solid #333; "
                "border-radius: 6px; padding: 4px 0;")

    def _build_groups(self):
        """Create or rebuild all five group pages."""
        for key in _GROUP_KEYS:
            if key not in self._group_pages:
                page = _RowPage()
                self._stack.addWidget(page)   # indices 0–4 in order
                self._group_pages[key] = page
                page.focus_changed.connect(self._update_help)
            self._rebuild_group_page(key, self._group_pages[key])

    def _rebuild_group_page(self, key: str, page: _RowPage):
        """Clear and repopulate a single group page."""
        page.clear()
        self._detail_page = page
        cats = _GROUP_CATS[key]
        use_headers = len(cats) > 1
        for cat_name in cats:
            if cat_name in _ADV_CATS and not self._show_advanced:
                continue   # advanced-only category — hidden in basic view
            if use_headers:
                self._add_section_header(page, cat_name)
            getattr(self, _CAT_BUILDER_MAP[cat_name])()

    def _add_section_header(self, page: _RowPage, title: str):
        """Insert a non-focusable orange section label into the page's list layout."""
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(_SEC_STYLE)
        # Insert directly before the trailing stretch; footer_slot is absent
        # after clear() so count()-1 is always the stretch position.
        page._list.insertWidget(page._list.count() - 1, lbl)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _select_group(self, key: str):
        """Switch to a group page — called by icon container clicks."""
        self._current_group_key = key
        # Update icon column: active container gets orange left-border + tinted bg;
        # inactive containers revert to transparent.
        for k, cont in self._cat_btns.items():
            active = (k == key)
            cont.setStyleSheet(
                "background: rgba(232,85,31,14); border-left: 3px solid #E8551F;"
                if active else
                "background: transparent; border-left: 3px solid transparent;"
            )
            icon_c = "#E8551F" if active else _ICON_COLORS.get(k, "#888")
            name_c = "#E8551F" if active else "#777"
            self._cat_icon_lbls[k].setStyleSheet(
                f"font-size: 22px; color: {icon_c}; background: transparent; border: none;")
            self._cat_name_lbls[k].setStyleSheet(
                f"font-size: 9px; color: {name_c}; letter-spacing: 0.8px; font-weight: 600; "
                f"background: transparent; border: none;")
        # Switch stack page
        self._stack.setCurrentIndex(_GROUP_IDX[key])
        self._group_pages[key].activate()

    def _go_back(self):
        """Return from picker page to the current group page."""
        # Commit pending input selection when returning from source picker
        if self._current_group_key == "source" and hasattr(self, "_pending_input_url"):
            url = self._pending_input_url
            del self._pending_input_url
            saved = self._app_config.active_input_url or self._profile.input.device
            if url and url != saved:
                self._app_config.active_input_url = url
                self._profile.input.device = url
                QTimer.singleShot(0, lambda u=url: self.input_changed.emit(u))
        # Return to group
        key = self._current_group_key
        self._stack.setCurrentIndex(_GROUP_IDX[key])
        self._group_pages[key].activate()

    def _open_picker(self, picker_row: "_PickerRow"):
        """Open full-page option picker for a _PickerRow."""
        self._active_picker = picker_row
        self._picker_page.clear()

        for opt in picker_row._options:
            is_current = (opt == picker_row._current)
            row = _ActionRow(opt, "✓" if is_current else "")
            if is_current:
                row._label.setStyleSheet(
                    "color:#E8551F; font-size:14px; font-weight:600; background:transparent;")
            def _pick(o=opt, pr=picker_row):
                pr._current = o
                pr._show()
                pr.picked.emit(o)
                self._go_back()
            row.activated.connect(_pick)
            self._picker_page.add_row(row)
            if is_current:
                self._picker_page._focus_idx = len(self._picker_page._rows) - 1

        self._stack.setCurrentIndex(5)
        self._picker_page.activate()

    def _update_help(self, row: _Row):
        text = _HELP.get(row._label.text(), "")
        formatted = (f"<b style='color:#E8551F'>Info:</b>  {text}" if text
                     else f"<span style='color:#555'>{row._label.text()}</span>")
        self.help_changed.emit(formatted)

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        idx = self._stack.currentIndex()

        if idx == 5:   # picker page
            page = self._picker_page
            if key == Qt.Key.Key_Up:
                page.handle_up()
            elif key == Qt.Key.Key_Down:
                page.handle_down()
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                page.handle_enter()
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self._go_back()
            else:
                super().keyPressEvent(event)
        else:   # group page (0–4)
            page = self._group_pages[self._current_group_key]
            if key == Qt.Key.Key_Up:
                page.handle_up()
            elif key == Qt.Key.Key_Down:
                page.handle_down()
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                page.handle_enter()
            elif key == Qt.Key.Key_Right:
                page.handle_right()
            elif key == Qt.Key.Key_Left:
                page.handle_left()
            else:
                super().keyPressEvent(event)

    # ── Row helpers (redirect to self._detail_page) ───────────────────────────

    def _enum(self, label: str, options, current, mutator, group_key: str,
              display_map: dict = None, advanced: bool = False) -> "_EnumRow":
        if advanced and not self._show_advanced:
            return None
        row = _EnumRow(label, list(options), str(current), display_map=display_map)
        row.value_changed.connect(lambda v, m=mutator, g=group_key: self._update(lambda p: m(p, v), g))
        self._detail_page.add_row(row)
        return row

    def _bool(self, label: str, current, mutator, group_key: str,
              advanced: bool = False) -> "_BoolRow":
        if advanced and not self._show_advanced:
            return None
        row = _BoolRow(label, bool(current))
        row.value_changed.connect(lambda v, m=mutator, g=group_key: self._update(lambda p: m(p, v), g))
        self._detail_page.add_row(row)
        return row

    def _int(self, label: str, lo, hi, current, mutator, group_key: str,
             step=1, log_scale=False, advanced: bool = False) -> "_IntRow":
        if advanced and not self._show_advanced:
            return None
        row = _IntRow(label, lo, hi, int(current), step, log_scale=log_scale)
        row.value_changed.connect(lambda v, m=mutator, g=group_key: self._update(lambda p: m(p, v), g))
        self._detail_page.add_row(row)
        return row

    def _float(self, label: str, lo, hi, current, mutator, group_key: str,
               step=0.1, decimals=2, log_scale=False, advanced: bool = False) -> "_FloatRow":
        if advanced and not self._show_advanced:
            return None
        row = _FloatRow(label, lo, hi, float(current), step, decimals, log_scale=log_scale)
        row.value_changed.connect(lambda v, m=mutator, g=group_key: self._update(lambda p: m(p, v), g))
        self._detail_page.add_row(row)
        return row

    def _action(self, label: str, sub: str, callback) -> _ActionRow:
        row = _ActionRow(label, sub)
        row.activated.connect(callback)
        self._detail_page.add_row(row)
        return row

    def _picker(self, label: str, options: List[str], current: str,
                on_pick: Callable) -> "_PickerRow":
        """A row that opens a full-page picker. on_pick(value) called on selection."""
        row = _PickerRow(label, options, current)
        row.picked.connect(on_pick)
        row.activated.connect(lambda r=row: self._open_picker(r))
        self._detail_page.add_row(row)
        return row

    # ── Category builders ─────────────────────────────────────────────────────

    def _build_input(self):
        labels = self._app_config.get_input_labels()
        current_url = self._app_config.active_input_url or self._profile.input.device
        self._pending_input_url = current_url

        if labels:
            urls  = list(labels.keys())
            names = list(labels.values())
            cur_name = labels.get(current_url, names[0] if names else "")

            def _on_pick(label_name):
                try:
                    self._pending_input_url = urls[names.index(label_name)]
                except (ValueError, IndexError):
                    pass

            self._device_row = self._picker("Capture input", names, cur_name, _on_pick)
        else:
            row = _ActionRow("Capture input", "not configured")
            self._detail_page.add_row(row)

        self._action("Configure inputs…", "", self._open_input_config)

    def _build_tone_mapping(self):
        tm = self._profile.tone_mapping
        # Complete valid --tone-mapping values per mpv options.rst
        # REMOVED: 'saturation' — that is a --gamut-mapping-mode value, not tone-mapping
        algos = ("auto", "spline", "bt.2390", "bt.2446a",
                 "st2094-40", "st2094-10",
                 "reinhard", "mobius", "hable", "gamma", "linear", "clip")
        self._enum("Algorithm",   algos, tm.algorithm,
                   lambda p, v: setattr(p.tone_mapping, "algorithm", v), "tone_mapping",
                   display_map=_DISPLAY_TM)
        self._float("Max boost",  1.0, 10.0, tm.tone_mapping_max_boost,
                    lambda p, v: setattr(p.tone_mapping, "tone_mapping_max_boost", v), "tone_mapping")
        self._bool("Inverse TM",  tm.inverse_tone_mapping,
                   lambda p, v: setattr(p.tone_mapping, "inverse_tone_mapping", v), "tone_mapping")
        self._bool("Visualize",   tm.tone_mapping_visualize,
                   lambda p, v: setattr(p.tone_mapping, "tone_mapping_visualize", v), "tone_mapping")

    def _build_peak_detection(self):
        pd = self._profile.peak_detection
        self._enum("Compute peak", ("yes", "no", "auto"), pd.hdr_compute_peak,
                   lambda p, v: setattr(p.peak_detection, "hdr_compute_peak", v), "peak_detection",
                   display_map=_DISPLAY_PEAK)
        self._float("Percentile",  90.0, 100.0, pd.hdr_peak_percentile,
                    lambda p, v: setattr(p.peak_detection, "hdr_peak_percentile", v),
                    "peak_detection", step=0.005, decimals=3)
        self._float("Decay rate",  1.0, 100.0, pd.hdr_peak_decay_rate,
                    lambda p, v: setattr(p.peak_detection, "hdr_peak_decay_rate", v),
                    "peak_detection", step=1.0, decimals=1)
        self._float("Threshold low",  0.0, 10.0, pd.hdr_scene_threshold_low,
                    lambda p, v: setattr(p.peak_detection, "hdr_scene_threshold_low", v),
                    "peak_detection", step=0.1)
        self._float("Threshold high", 0.0, 20.0, pd.hdr_scene_threshold_high,
                    lambda p, v: setattr(p.peak_detection, "hdr_scene_threshold_high", v),
                    "peak_detection", step=0.1)
        self._bool("Delayed detect", pd.allow_delayed_peak_detect,
                   lambda p, v: setattr(p.peak_detection, "allow_delayed_peak_detect", v),
                   "peak_detection")

    def _build_contrast_recovery(self):
        cr = self._profile.contrast_recovery
        zion_active = self._profile.zion_core.enabled
        if zion_active:
            self._action("Recovery", "0.0  (Zion Core active — Construct CR takes over)",
                         lambda: None)
            self._action("Smoothness", f"{cr.hdr_contrast_smoothness:.1f}  (inactive)",
                         lambda: None)
        else:
            self._float("Recovery",   0.0, 1.0, cr.hdr_contrast_recovery,
                        lambda p, v: setattr(p.contrast_recovery, "hdr_contrast_recovery", v),
                        "contrast_recovery", step=0.05)
            self._float("Smoothness", 1.0, 10.0, cr.hdr_contrast_smoothness,
                        lambda p, v: setattr(p.contrast_recovery, "hdr_contrast_smoothness", v),
                        "contrast_recovery", step=0.1)

    def _build_zion_core(self):
        zc = self._profile.zion_core
        self._bool("Zion Core", zc.enabled,
                   lambda p, v: setattr(p.zion_core, "enabled", v), "zion_core")
        P = "zion_core"
        # The Oracle
        self._bool("Oracle: Auto", zc.oracle.auto,
                   lambda p, v: setattr(p.zion_core.oracle, "auto", v), P)
        self._float("Oracle value", 0.5, 1.5, zc.oracle.value,
                    lambda p, v: setattr(p.zion_core.oracle, "value", v), P,
                    step=0.01, decimals=3)
        # Construct CR
        self._bool("Construct CR: Auto", zc.construct_cr.auto,
                   lambda p, v: setattr(p.zion_core.construct_cr, "auto", v), P)
        self._float("CR strength", 0.0, 0.5, zc.construct_cr.value,
                    lambda p, v: setattr(p.zion_core.construct_cr, "value", v), P,
                    step=0.01, decimals=3)
        # Resonance
        self._bool("Resonance: Auto", zc.resonance.auto,
                   lambda p, v: setattr(p.zion_core.resonance, "auto", v), P)
        self._float("Radiance knee", 0.4, 0.9, zc.resonance.knee,
                    lambda p, v: setattr(p.zion_core.resonance, "knee", v), P,
                    step=0.05, decimals=2, advanced=True)
        self._float("Radiance strength", 0.0, 0.6, zc.resonance.strength,
                    lambda p, v: setattr(p.zion_core.resonance, "strength", v), P,
                    step=0.01, decimals=3, advanced=True)
        self._float("Radiance shoulder", 0.7, 0.99, zc.resonance.shoulder,
                    lambda p, v: setattr(p.zion_core.resonance, "shoulder", v), P,
                    step=0.01, decimals=2, advanced=True)
        # Spectrum Shift
        ss = zc.spectrum_shift
        self._float("Neutral boost", 1.0, 1.5, ss.neutral_boost,
                    lambda p, v: setattr(p.zion_core.spectrum_shift, "neutral_boost", v), P,
                    step=0.01, decimals=2)
        self._float("Fire boost", 1.0, 1.5, ss.fire_boost,
                    lambda p, v: setattr(p.zion_core.spectrum_shift, "fire_boost", v), P,
                    step=0.01, decimals=2)
        self._float("Spectrum knee", 0.1, 0.9, ss.knee,
                    lambda p, v: setattr(p.zion_core.spectrum_shift, "knee", v), P,
                    step=0.05, decimals=2)
        self._float("Skin protect", 0.5, 1.0, ss.skin_protect,
                    lambda p, v: setattr(p.zion_core.spectrum_shift, "skin_protect", v), P,
                    step=0.01, decimals=2)
        # Shadow Bilateral
        _shadow_modes = ("off", "auto", "manual")
        self._enum("Shadow recover", _shadow_modes, zc.shadow.mode,
                   lambda p, v: setattr(p.zion_core.shadow, "mode", v), P)
        self._float("Shadow strength", 0.0, 0.5, zc.shadow.strength,
                    lambda p, v: setattr(p.zion_core.shadow, "strength", v), P,
                    step=0.01, decimals=2)
        # Highlight Bilateral
        _hi_modes = ("off", "auto", "manual")
        self._enum("Highlight smooth", _hi_modes, zc.highlight.mode,
                   lambda p, v: setattr(p.zion_core.highlight, "mode", v), P)
        self._float("Highlight strength", 0.0, 0.4, zc.highlight.strength,
                    lambda p, v: setattr(p.zion_core.highlight, "strength", v), P,
                    step=0.01, decimals=2)
        # Temporal Stability
        self._float("IIR response", 0.01, 0.50, zc.iir_alpha,
                    lambda p, v: setattr(p.zion_core, "iir_alpha", v), P,
                    step=0.01, decimals=2, advanced=True)
        self._float("Gamma deadband", 0.0, 0.10, zc.gamma_max_delta,
                    lambda p, v: setattr(p.zion_core, "gamma_max_delta", v), P,
                    step=0.005, decimals=3, advanced=True)
        self._float("Scene baseline α", 0.01, 0.20, zc.iir_slow_alpha,
                    lambda p, v: setattr(p.zion_core, "iir_slow_alpha", v), P,
                    step=0.01, decimals=2, advanced=True)
        # SDR→P5 virtual-master bridge (Phase C) — advanced
        self._bool("SDR→P5 emulation", zc.emulate_sdr,
                   lambda p, v: setattr(p.zion_core, "emulate_sdr", v), P,
                   advanced=True)
        self._float("Virtual P5 nits", 100.0, 4000.0, zc.sdr_virtual_nits,
                    lambda p, v: setattr(p.zion_core, "sdr_virtual_nits", v), P,
                    step=100, decimals=0, advanced=True)
        self._float("Emulation strength", 0.0, 1.0, zc.sdr_strength,
                    lambda p, v: setattr(p.zion_core, "sdr_strength", v), P,
                    step=0.05, decimals=2, advanced=True)

    def _build_display_target(self):
        dt = self._profile.display_target
        trcs   = ("auto", "bt.1886", "srgb", "linear",
                  "gamma1.8", "gamma2.0", "gamma2.2", "gamma2.4",
                  "gamma2.6", "gamma2.8", "prophoto",
                  "pq", "hlg", "v-log", "s-log1", "s-log2")
        # Complete valid --target-prim values per mpv options.rst
        prims  = ("auto", "bt.2020", "bt.709", "display-p3", "dci-p3",
                  "bt.601-525", "bt.601-625", "bt.470m",
                  "apple", "adobe", "prophoto", "cie1931", "v-gamut", "s-gamut")
        hints  = ("auto", "yes", "no")
        self._enum("Target TRC",    trcs,  dt.target_trc,
                   lambda p, v: setattr(p.display_target, "target_trc", v), "display_target",
                   display_map=_DISPLAY_TRC)
        self._enum("Target prim",   prims, dt.target_prim,
                   lambda p, v: setattr(p.display_target, "target_prim", v), "display_target",
                   display_map=_DISPLAY_PRIM)
        self._int("Target peak",    10, 10000, int(dt.target_peak) if dt.target_peak.isdigit() else 203,
                  lambda p, v: setattr(p.display_target, "target_peak", str(v)),
                  "display_target", step=10, log_scale=True)
        self._enum("CS hint",       hints, dt.target_colorspace_hint,
                   lambda p, v: setattr(p.display_target, "target_colorspace_hint", v), "display_target")

    def _build_gamut_mapping(self):
        gm   = self._profile.gamut_mapping
        # Complete valid --gamut-mapping-mode values per mpv options.rst
        # REMOVED: 'softclip' — does not exist in mpv
        modes = ("auto", "perceptual", "relative", "saturation",
                 "absolute", "desaturate", "linear", "darken", "clip", "warn")
        self._enum("Gamut mode",    modes, gm.mode,
                   lambda p, v: setattr(p.gamut_mapping, "mode", v), "gamut_mapping",
                   display_map=_DISPLAY_GAMUT)
        self._float("Perc strength", 0.0, 1.0, gm.perceptual_strength,
                    lambda p, v: setattr(p.gamut_mapping, "perceptual_strength", v),
                    "gamut_mapping", step=0.05)
        self._float("Softclip knee", 0.0, 1.0, gm.softclip_knee,
                    lambda p, v: setattr(p.gamut_mapping, "softclip_knee", v),
                    "gamut_mapping", step=0.05)
        self._bool("Gamut expand",   gm.gamut_expansion,
                   lambda p, v: setattr(p.gamut_mapping, "gamut_expansion", v), "gamut_mapping")

    def _build_picture(self):
        pic = self._profile.picture
        zion_active = self._profile.zion_core.enabled
        self._int("Brightness", -100, 100, pic.brightness,
                  lambda p, v: setattr(p.picture, "brightness", v), "picture", step=2)
        self._int("Contrast",   -100, 100, pic.contrast,
                  lambda p, v: setattr(p.picture, "contrast",   v), "picture", step=2)
        if zion_active and pic.saturation != 0:
            self._action("Saturation",
                         f"{pic.saturation}  (interacts with Spectrum Shift chroma boost)",
                         lambda: None)
        else:
            self._int("Saturation", -100, 100, pic.saturation,
                      lambda p, v: setattr(p.picture, "saturation", v), "picture", step=2)
        self._int("Hue",        -100, 100, pic.hue,
                  lambda p, v: setattr(p.picture, "hue",        v), "picture", step=2)
        if zion_active:
            self._action("Gamma", "0  (Zion Core active — The Oracle owns gamma)",
                         lambda: None)
        else:
            self._int("Gamma",    -100, 100, pic.gamma,
                      lambda p, v: setattr(p.picture, "gamma",  v), "picture", step=2)
        self._float("Sharpen",  -1.0, 1.0, pic.sharpen,
                    lambda p, v: setattr(p.picture, "sharpen",  v), "picture", step=0.05)

    def _build_geometry(self):
        geo = self._profile.geometry
        self._float("Zoom",    -2.0, 2.0, geo.video_zoom,
                    lambda p, v: setattr(p.geometry, "video_zoom",  v), "geometry", step=0.05)
        self._float("Pan X",   -1.0, 1.0, geo.video_pan_x,
                    lambda p, v: setattr(p.geometry, "video_pan_x", v), "geometry", step=0.02)
        self._float("Pan Y",   -1.0, 1.0, geo.video_pan_y,
                    lambda p, v: setattr(p.geometry, "video_pan_y", v), "geometry", step=0.02)
        self._int("Rotate",    0, 359, geo.video_rotate,
                  lambda p, v: setattr(p.geometry, "video_rotate", v), "geometry", step=90)

    def _build_scaling(self):
        sc = self._profile.scaling
        kernels = ("spline36", "ewa_lanczos", "ewa_lanczossharp", "mitchell",
                   "catmull_rom", "lanczos", "bicubic", "bilinear")
        self._enum("Scale",   kernels, sc.scale,
                   lambda p, v: setattr(p.scaling, "scale",  v), "scaling",
                   display_map=_DISPLAY_KERN)
        self._enum("Dscale",  kernels, sc.dscale,
                   lambda p, v: setattr(p.scaling, "dscale", v), "scaling",
                   display_map=_DISPLAY_KERN)
        self._enum("Cscale",  kernels, sc.cscale,
                   lambda p, v: setattr(p.scaling, "cscale", v), "scaling",
                   display_map=_DISPLAY_KERN)
        self._bool("Linear downscaling", sc.linear_downscaling,
                   lambda p, v: setattr(p.scaling, "linear_downscaling", v), "scaling")
        self._float("Scale blur", 0.0, 2.0, sc.scale_blur,
                    lambda p, v: setattr(p.scaling, "scale_blur", v), "scaling", step=0.05)

    def _build_dithering(self):
        d = self._profile.dithering
        algos = ("fruit", "ordered", "error-diffusion", "no")
        self._enum("Dither algorithm", algos, d.algorithm,
                   lambda p, v: setattr(p.dithering, "algorithm", v), "dithering")
        self._bool("Temporal", d.temporal,
                   lambda p, v: setattr(p.dithering, "temporal", v), "dithering")
        self._int("Fruit size", 2, 8, d.fruit_size,
                  lambda p, v: setattr(p.dithering, "fruit_size", v), "dithering")

    def _build_deband(self):
        db = self._profile.deband
        self._bool("Enabled",    db.enabled,
                   lambda p, v: setattr(p.deband, "enabled",    v), "deband")
        self._int("Iterations", 1, 16, db.iterations,
                  lambda p, v: setattr(p.deband, "iterations",  v), "deband")
        self._int("Threshold",  0, 4096, db.threshold,
                  lambda p, v: setattr(p.deband, "threshold",   v), "deband", step=8)
        self._int("Range",      1, 64, db.range,
                  lambda p, v: setattr(p.deband, "range",       v), "deband")
        self._int("Grain",      0, 4096, db.grain,
                  lambda p, v: setattr(p.deband, "grain",       v), "deband", step=8)

    def _build_output(self):
        out = self._profile.output
        vos = ("gpu-next", "gpu", "direct3d")
        self._enum("VO", vos, out.vo,
                   lambda p, v: setattr(p.output, "vo", v), "output")

    def _build_performance(self):
        pf = self._profile.performance
        self._bool("No cache",        pf.no_cache,
                   lambda p, v: setattr(p.performance, "no_cache",          v), "performance")
        self._bool("No demuxer thread", pf.no_demuxer_thread,
                   lambda p, v: setattr(p.performance, "no_demuxer_thread",  v), "performance")
        self._bool("Latency hacks",   pf.video_latency_hacks,
                   lambda p, v: setattr(p.performance, "video_latency_hacks", v), "performance")
        self._int("Cutover ceiling (ms)", 0, 1000, pf.ml_acq_cutover_ms,
                  lambda p, v: setattr(p.performance, "ml_acq_cutover_ms", v),
                  "performance", step=5)

    def _build_shaders(self):
        shaders = self._profile.shaders.shaders
        if not shaders:
            row = _ActionRow("No shaders found", "")
            self._detail_page.add_row(row)
            return
        for s in shaders:
            import os
            name = os.path.basename(s.get("path", ""))
            row = _BoolRow(name, bool(s.get("enabled", False)))
            path = s.get("path", "")
            def _on_shader(v, p=path):
                for sh in self._profile.shaders.shaders:
                    if sh.get("path") == p:
                        sh["enabled"] = v
                self._update(lambda _: None, "shaders")
            row.value_changed.connect(_on_shader)
            self._detail_page.add_row(row)

    def _build_app(self):
        modes = ("video_processor", "media_player")
        self._enum("Mode", modes, self._app_config.app_mode,
                   lambda p, v: self._on_app_mode_changed(v), "")
        self._action("Background…", "", self.wallpaper_change_requested.emit)

    # ── Core update / emit ────────────────────────────────────────────────────

    def _update(self, mutator, group_key: str):
        mutator(self._profile)
        if not group_key:
            return
        _audit.info(f"setting: group='{group_key}' preset='{self._profile.name}' changed")
        key = group_key
        if key not in self._emit_timers:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(150)
            t.timeout.connect(lambda k=key: self._flush_emit(k))
            self._emit_timers[key] = t
        self._emit_timers[key].start()

    def _flush_emit(self, group_key: str):
        try:
            self.profile_changed.emit(group_key, self._profile)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def set_profile(self, profile: MpvProfile):
        self._profile = deepcopy(profile)
        self._build_groups()
        self._select_group(self._current_group_key)

    def set_hdr_active(self, is_hdr: bool):
        self._is_hdr = is_hdr

    def set_app_mode(self, mode: str):
        pass  # mode reflected in App category

    def sync_device_combo(self):
        """Rebuild source group when device list has changed."""
        page = self._group_pages.get("source")
        if page:
            self._rebuild_group_page("source", page)
            if (self._current_group_key == "source"
                    and self._stack.currentIndex() != 5):
                page.activate()

    # ── Internal handlers ─────────────────────────────────────────────────────

    def _open_input_config(self):
        from .input_config_panel import InputConfigDialog
        dlg = InputConfigDialog(self._app_config, self)
        dlg.input_changed.connect(self._on_input_config_changed)
        dlg.exec()

    def _on_input_config_changed(self, url: str):
        self._app_config.active_input_url = url
        self._profile.input.device = url
        page = self._group_pages.get("source")
        if page:
            self._rebuild_group_page("source", page)
            if (self._current_group_key == "source"
                    and self._stack.currentIndex() != 5):
                page.activate()
        self.input_changed.emit(url)

    def _on_app_mode_changed(self, mode: str):
        self._app_config.app_mode = mode
        self.app_mode_changed.emit(mode)

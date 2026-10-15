"""
Main application window — frameless, fullscreen.

Uses MpvEngine (python-mpv / libmpv) instead of subprocess + IPC pipe.
No QThread lifecycle issues, no ctypes pipe management.

Modes:
  IDLE    — mpv not running, wallpaper or media library shown
  WATCH   — mpv playing, overlays hidden
  EDIT    — mpv playing, settings + status panels visible

Up arrow — toggles WATCH ↔ EDIT from any window (global hotkey).
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from enum import Enum, auto
from pathlib import Path
from typing import Optional

_log   = logging.getLogger("unplugged.main_window")
_audit = logging.getLogger("unplugged.audit")

from PyQt6.QtCore import Qt, QSize, QTimer, QEvent, pyqtSlot
from PyQt6.QtWidgets import QWidget, QFileDialog, QMainWindow, QMessageBox, QApplication, QLabel
from .confirm_dialog import ConfirmDialog
from ..core.calibrate import (CalibrationSession, CALIBRATE_VIDEO, CALIBRATE_CSV,
                              load_expected_table, _default_expected)

from .background_widget import BackgroundWidget
from .mpv_viewport import MpvViewport
from .settings_window import SettingsWindow
from .status_bar import StatusBar
from .control_bar import ControlBar
from .media_library_panel import MediaLibraryPanel
from .playback_bar import PlaybackBar
from .status_panel import StatusPanel
from .playback_controls import PlaybackControlsPanel
from .right_panel import RightPanel
from .acquire_overlay import AcquireOverlay
from .splash_screen import SplashScreen
from .input_selector import InputSelector
from .first_run_dialog import FirstRunDialog
from ..core.s3_engine import S3Engine as MpvEngine, EngineState   # engine layer swapped to s3engine.dll
from ..core.hotkey import GlobalHotkey
from ..core.signal_monitor import SignalMonitor, SignalState
from ..config.model import AppConfig, MpvProfile
from ..config.serializer import build_mpv_args, build_media_player_args
from ..profiles.manager import ProfileManager
from ..core.live_settings import apply_live_change, sync_all_live, ApplyMode, SETTING_GROUPS
from ..core.decklink_monitor import DeckLinkMonitor, poll_all_ports
from .input_config_panel import InputConfigDialog


_WALLPAPER_NAME = "alita-battle-angel-movie-uhdpaper.com-4K-5.jpg"


def _find_default_wallpaper() -> Path:
    """Locate the bundled default wallpaper — dev tree and frozen/packaged builds
    place it at different depths relative to this file, so try both."""
    from ..assets import asset

    candidates = [
        asset("images", _WALLPAPER_NAME),
        Path(sys.executable).parent / "_internal" / "assets" / "images" / _WALLPAPER_NAME,
        Path(sys.executable).parent / "assets" / "images" / _WALLPAPER_NAME,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


_DEFAULT_WALLPAPER = _find_default_wallpaper()

_SETTINGS_WIDTH   = 460   # 80px icon col + 380px content
_STATUS_WIDTH     = 300
_OVERLAY_OPACITY_EDIT = 1.0
_VP_MAX_RETRIES   = 10
_VP_RETRY_DELAY   = 1000   # ms

# Properties the engine observes and routes to the status panel
_STATUS_PROPS = (
    "video-params", "video-out-params", "estimated-vf-fps",
    "display-fps", "frame-drop-count", "decoder-frame-drop-count",
    "vo-delayed-frame-count",
    "tone-mapping", "hdr-compute-peak", "target-peak",
    "tone-mapping-max-boost", "hdr-contrast-recovery",
    "target-trc", "target-prim",
    "current-vo", "gamut-mapping-mode",
    "video-codec", "video-bitrate", "hwdec-current", "display-names",
    "track-list",   # for Dolby Vision profile detection
)
_PLAYBACK_CTRL_PROPS = (
    "track-list", "audio-device-list",
    "hwdec", "hwdec-current", "deinterlace",
    "audio-device", "audio-spdif",
    "speed", "audio-delay", "sub-delay",
    "vid", "aid", "sid",
)
# Properties for the playback bar
_PLAYBACK_PROPS = ("time-pos", "duration", "pause", "mute", "volume")


class AppMode(Enum):
    IDLE  = auto()
    WATCH = auto()
    EDIT  = auto()


class MainWindow(QMainWindow):
    def __init__(
        self,
        app_config: AppConfig,
        profile: MpvProfile,
        profile_manager: ProfileManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._app_config = app_config
        self._profile = profile
        self._profile_manager = profile_manager
        self._mode = AppMode.IDLE
        self._restart_needed = False
        self._panel_opacity = 0.88
        self._current_file: str = ""
        self._vp_retry_count = 0
        self._vp_acquiring = False
        self._detected_vf: Optional[str] = None
        self._detected_dv: bool = False  # True once DV confirmed via video-params
        # Signal blinked (decklink reported a lock loss) since the last confirmed
        # acquisition. Deferred recovery: re-acquire when we next get a chance
        # (lock restore or re-entering WATCH), because a brief HDMI renegotiation
        # during menu→title transitions can leave mpv playing black frames while
        # no mode-change/lock-loss restart fires (the WATCH-only guard).
        self._dl_blink_seen: bool = False
        # Delivery heartbeat for the acquisition success criterion. `recv` is the
        # renderer's cumulative framesReceived, carried on every s3_status poll.
        # Success has to mean DELIVERY, not state: `is_playing()` is only the
        # DirectShow graph being in Run state, and that stays true through a stall.
        self._recv_seen: Optional[int] = None
        self._recv_last_change_ts: float = 0.0

        # Mouse auto-hide: hide cursor after 3s in WATCH mode
        self._mouse_hide_timer = QTimer(self)
        self._mouse_hide_timer.setSingleShot(True)
        self._mouse_hide_timer.setInterval(3000)
        self._mouse_hide_timer.timeout.connect(self._hide_cursor)
        self._cursor_hidden = False
        # Set on PLAYING in media mode, cleared on a new play and on exit. The
        # engine reports "idle" both at startup and after a title ends, and the two
        # are indistinguishable in the state string alone -- so "we were playing and
        # now we are not" is the only safe trigger for exit-on-finish. Without it
        # the app would close on its first poll, before anything was ever played.
        self._media_was_playing = False
        # Set only by the automatic exit-on-finish path. closeEvent asks the user to
        # confirm an exit, which is right for a hand on the X and wrong for a title
        # that simply ended: the dialog would interrupt an unattended session, and
        # cancelling it leaves a session whose engine is already stopped -- unable to
        # play anything else, which is the exact state exit-on-finish exists to avoid.
        self._exit_without_confirm = False
        # App-level input filter — see eventFilter for why the window's own
        # mouseMoveEvent cannot carry this.
        QApplication.instance().installEventFilter(self)

        # Polls video-out-params (APL / frame peak) once per second while playing
        # _peak_poll_timer removed — video-out-params is already observed via
        # observe_property which fires safely via QueuedConnection on change.
        # Explicit polling from the Qt thread raced with the mpv event thread
        # causing access violations in _get_property.

        self._vp_retry_timer = QTimer(self)
        self._vp_retry_timer.setSingleShot(True)
        self._vp_retry_timer.timeout.connect(self._vp_retry_attempt)
        # Check-result timer — member so we can cancel pending checks before starting new one
        self._vp_check_timer = QTimer(self)
        self._vp_check_timer.setSingleShot(True)
        self._vp_check_timer.timeout.connect(self._vp_check_result)

        self._setup_window()
        self._build_layers()
        self._build_engine()
        self._wire_signals()
        self._apply_wallpaper()
        self._populate_profiles()
        self._status_panel.seed_configured_output(self._profile)
        self.showFullScreen()

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("unplugged")
        self.setMinimumSize(QSize(960, 540))
        self.setStyleSheet("QMainWindow { background: #000000; }")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def _build_layers(self) -> None:
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")
        container.setMouseTracking(True)
        self.setMouseTracking(True)
        self.setCentralWidget(container)

        self._background   = BackgroundWidget(_DEFAULT_WALLPAPER, container)
        self._viewport     = MpvViewport(container)
        self._viewport.hide()

        self._media_library = MediaLibraryPanel(self._app_config, container)
        self._media_library.hide()

        self._playback_bar = PlaybackBar(container)
        self._playback_bar.hide()

        self._status_panel = StatusPanel(container)
        self._status_panel.hide()

        # AcquireOverlay is a QDialog - parent is the main window, not container
        self._acquire_overlay = AcquireOverlay(self._app_config, self)

        # Splash screen - shown at launch, auto-dismisses after 5s
        self._splash = SplashScreen(self)

        self._status_bar   = StatusBar(container)
        self._control_bar  = ControlBar(container)

        # Input selector — shown in status bar area in VP mode
        self._input_selector = InputSelector(self._app_config, container)
        self._input_selector.hide()

        from .settings_panel import SettingsPanel
        self._settings_panel = SettingsPanel(self._app_config, self._profile, container)

        self._playback_controls = PlaybackControlsPanel(
            app_config=self._app_config, parent=container)

        # RightPanel owns tabs + mode selector — re-parents both content panels
        self._right_panel = RightPanel(
            self._settings_panel, self._playback_controls,
            app_config=self._app_config, parent=container)
        self._right_panel.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout()
        if not getattr(self, '_idle_screen_applied', False):
            self._idle_screen_applied = True
            self._apply_idle_screen()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def eventFilter(self, obj, event) -> bool:
        # WHY AN APPLICATION-LEVEL FILTER AND NOT mouseMoveEvent.
        #
        # QMainWindow.mouseMoveEvent only fires for the window's OWN area — the part not
        # covered by a child. In WATCH the viewport child covers the entire window, and a
        # child without mouse tracking receives no move events at all unless a button is
        # held. So the hide/show logic that used to live in mouseMoveEvent never ran over
        # the video: the timer started once on WATCH entry, the cursor hid after 3 s, and
        # then no amount of mouse movement could bring it back, because the events were
        # being delivered to the viewport and dropped. The auto-hide looked "broken" in
        # both directions from the user's chair — sometimes never hiding, sometimes
        # vanishing for good — depending on where the pointer happened to be.
        #
        # Watching every object's input events at the application level is the one place
        # that sees all of them, wherever in the window they land.
        t = event.type()
        if t in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                 QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress,
                 QEvent.Type.Wheel):
            self._on_user_input()
        return super().eventFilter(obj, event)

    def _on_user_input(self) -> None:
        self._show_cursor()
        if self._mode == AppMode.WATCH:
            self._mouse_hide_timer.start()

    def _show_cursor(self) -> None:
        # An application OVERRIDE cursor, not setCursor on the window. setCursor is
        # per-widget, and every child that sets its own cursor — the panels, the bars,
        # the sliders all set PointingHandCursor — defeats it: the blank never reaches
        # the pointer while it is over one of them, which is most of the screen. The
        # override cursor wins over every widget cursor, app-wide.
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False

    def _hide_cursor(self) -> None:
        if self._mode == AppMode.WATCH and not self._cursor_hidden:
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden = True


    def keyPressEvent(self, event) -> None:
        key = event.key()

        # ── Settings open/close ───────────────────────────────────────
        if key == Qt.Key.Key_Escape:
            if self._right_panel.isVisible():
                self._toggle_edit_mode()
            return
        if key == Qt.Key.Key_F1:
            self._toggle_edit_mode()
            return
        if key == Qt.Key.Key_F2:
            self._on_app_mode_changed("video_processor")
            return
        if key == Qt.Key.Key_F3:
            self._on_app_mode_changed("media_player")
            return
        if key == Qt.Key.Key_F5 and self._app_config.app_mode == "video_processor":
            self._vp_restart_capture()
            return

        # ── Playback keys (only when playing, settings closed) ────────
        playing = self._engine.is_playing()
        settings_open = self._right_panel.isVisible()

        if playing and not settings_open:
            if key == Qt.Key.Key_Space:
                self._engine.set_property("pause",
                    not self._engine.get_property("pause", False))
                return
            if key == Qt.Key.Key_Left:
                pos = self._engine.get_property("time-pos", 0) or 0
                self._engine.seek(max(0.0, float(pos) - 30.0))
                return
            if key == Qt.Key.Key_Right:
                pos = self._engine.get_property("time-pos", 0) or 0
                dur = self._engine.get_property("duration", 0) or 0
                if dur:
                    self._engine.seek(min(float(dur), float(pos) + 30.0))
                return
            if key == Qt.Key.Key_Up:
                vol = min(130, int(self._engine.get_property("volume", 100) or 100) + 5)
                self._engine.set_property("volume", vol)
                return
            if key == Qt.Key.Key_Down:
                vol = max(0, int(self._engine.get_property("volume", 100) or 100) - 5)
                self._engine.set_property("volume", vol)
                return
            if key == Qt.Key.Key_M:
                self._engine.set_property("mute",
                    not self._engine.get_property("mute", False))
                return

        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._right_panel.isVisible():
            sp_geo = self._right_panel.geometry()
            st_geo = self._status_panel.geometry()
            if (not sp_geo.contains(event.pos()) and
                    not st_geo.contains(event.pos())):
                self._toggle_edit_mode()
                return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        from .confirm_dialog import ConfirmDialog
        # The confirm dialog is a real dialog the user must click. If the cursor is
        # hidden when X is pressed it would appear with an invisible pointer.
        self._show_cursor()
        if not self._exit_without_confirm:
            if not ConfirmDialog.ask("Close Unplugged", "Are you sure you want to exit?",
                                     confirm_label="Exit", parent=self):
                event.ignore()
                return
        else:
            _audit.info("app: automatic exit (title finished) — no confirmation by design")
        _audit.info("app: window close event — shutting down")
        self._hotkey.stop()
        self._dl_monitor.stop()
        # Close the window NOW so the X responds instantly. The engine teardown
        # below is bounded (~1–10 s in s3_shutdown); running it with the window
        # already hidden turns the old "X frozen for seconds then task-kill" into
        # an immediate close. QApplication.quit() then guarantees the event loop
        # ends even if a second top-level (the chrome rail) is still up —
        # otherwise the process lingered in the background until killed
        # (observed 2026-09-23, shutdown also racing the live snapshot thread).
        event.accept()
        self.hide()
        QApplication.processEvents()
        self._engine.shutdown(for_exit=True)   # the ONLY caller allowed to arm the exit watchdog
        QApplication.quit()
        super().closeEvent(event)

    def _relayout(self) -> None:
        # ORIGINAL DESIGN (restored): the video always fills the whole window;
        # the panels are overlays on top of it and the video NEVER moves when
        # panels toggle. (The brief three-region variant moved/resized the video
        # on every mode change — wrong.)
        cw = self.centralWidget()
        if cw is None:
            return
        w, h = cw.width(), cw.height()
        if w == 0 or h == 0:
            return

        sb_h  = self._status_bar.minimumSizeHint().height() or 38
        cb_h  = self._control_bar.minimumSizeHint().height() or 52
        cb_m  = 12
        panel_top_gap = 6
        pb_h  = self._playback_bar.height() if self._playback_bar.isVisible() else 0
        panel_top = sb_h + panel_top_gap
        sp_h  = h - panel_top - pb_h - cb_h - cb_m - 4

        self._background.setGeometry(0, 0, w, h)
        self._viewport.setGeometry(0, 0, w, h)      # fixed: video never moves

        ml_w = min(900, max(600, int(w * 0.62)))
        ml_h = min(640, max(440, int(h * 0.72)))
        self._media_library.setGeometry((w - ml_w)//2, (h - ml_h)//2, ml_w, ml_h)

        if not getattr(self, "_chrome_adopted", False):
            self._status_bar.setGeometry(0, 0, w, sb_h)
        if not getattr(self, "_chrome_adopted", False):
            # Until the chrome window exists these live here; afterwards their
            # geometry belongs to that window (positioning them here would move
            # them inside it).
            self._control_bar.setGeometry(cb_m, h - cb_h - cb_m, w - cb_m*2, cb_h)
            self._playback_bar.setGeometry(cb_m, h - cb_h - cb_m - pb_h - 4,
                                            w - cb_m*2, pb_h)
            pw = min(_SETTINGS_WIDTH, w)
            sw = min(_STATUS_WIDTH, w - pw - 4)
            self._status_panel.setGeometry(0, panel_top, sw, sp_h)
        if self._input_selector.isVisible():
            iw = min(340, w - 40)
            ih = 36
            self._input_selector.setGeometry((w - iw)//2, sb_h + 4, iw, ih)

        pw = min(_SETTINGS_WIDTH, w)
        self._right_panel.setGeometry(w - pw, panel_top, pw, sp_h)

        # Overlays above the video widget (the capture path raises the viewport,
        # which otherwise covers the status bar).
        self._status_bar.raise_()
        if not getattr(self, "_chrome_adopted", False):
            self._status_panel.raise_()
            self._control_bar.raise_()
            self._playback_bar.raise_()
        if self._right_panel.isVisible():
            self._right_panel.raise_()

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------

    def _build_engine(self) -> None:
        # Set PATH so libmpv-2.dll can be found before importing mpv
        mpv_dir = str(Path(self._app_config.mpv_executable).parent)
        if mpv_dir not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = mpv_dir + os.pathsep + os.environ.get("PATH", "")

        self._engine = MpvEngine(self)
        # s3_shell settings panel, replicated 1:1 from s3_shell.cpp, INI-backed
        # and written through to the engine (KEY_MAP) live.
        from .s3shell_panel import S3ShellPanel, SettingsIni, VALUE_MAP
        # SettingsIni() with no path resolves via default_ini_path(), so the dev
        # tree and the installed build agree on one location.
        self._s3_settings = S3ShellPanel(ini=SettingsIni(), engine=self._engine)
        # Fill in any mapped row the INI has never held, so the config is
        # complete before the first push (see S3ShellPanel.seed_ini).
        self._s3_settings.seed_ini()
        self._s3_gen = None
        self._engine.s3_status.connect(self._on_s3_status)
        self._hotkey = GlobalHotkey(parent=self)
        # Alt+F4 must always work (kiosk: the shell rarely holds focus).
        # RegisterHotKey does not deliver Alt+F4 in practice — a low-level
        # keyboard hook does, and it routes to closeEvent (confirm dialog).
        try:
            from ..core.altf4_hook import AltF4Hook
            self._altf4 = AltF4Hook(parent=self)
            self._altf4.triggered.connect(self.close)
            self._altf4.start()
        except Exception as e:                 # noqa: BLE001
            _audit.warning("Alt+F4 hook failed: %s", e)

        # P0: the shell may never hold Windows focus (hotkey-driven kiosk), but
        # WM_MOUSEWHEEL goes to the FOCUSED window — so the wheel would die over
        # the panels. The LL-mouse bridge replays wheel deltas to the hovered
        # widget, focus-independent.
        # Suspended while diagnosing clicks (2026-09-15): the LL swallow+replay path
        # can silently drop Qt6 events; restored to a pure OS path until the
        # panel-level filter below shows where clicks actually go.
        # DeckLink hardware signal monitor (Windows only — no-op on Linux)
        self._dl_monitor = DeckLinkMonitor(
            device_name=self._profile.input.device,
            poll_ms=500,
            parent=self,
        )
        # Debounces transient signal-lock flicker before restarting capture
        self._dl_unlock_timer = QTimer(self)
        self._dl_unlock_timer.setSingleShot(True)
        self._dl_unlock_timer.timeout.connect(self._on_dl_unlock_confirmed)

        # Signal monitor still used for video processor mode
        self._signal_monitor = SignalMonitor(
            loss_timeout=self._app_config.signal_loss_timeout,
            restart_cooldown=self._app_config.restart_cooldown,
            max_attempts=self._app_config.max_restart_attempts,
            parent=self,
        )

    def _wire_signals(self) -> None:
        # Status bar
        self._status_bar.minimize_clicked.connect(self.showMinimized)
        self._status_bar.close_clicked.connect(self.close)

        # Control bar
        self._control_bar.restart_clicked.connect(self._on_restart_user)
        self._control_bar.stop_clicked.connect(self._on_stop_user)
        self._control_bar.settings_clicked.connect(self._toggle_edit_mode)
        self._control_bar.profile_selected.connect(self._on_profile_selected)
        self._control_bar.manage_clicked.connect(self._open_preset_manager)
        self._control_bar.mode_changed.connect(self._on_app_mode_changed)
        self._control_bar.info_clicked.connect(self._toggle_stats_osd)

        # Engine state
        self._engine.state_changed.connect(self._on_engine_state)
        self._engine.log_message.connect(self._on_engine_log)

        # Engine property changes → status panel + playback bar
        self._engine.property_changed.connect(self._status_panel.on_property)
        self._engine.zion_stats_updated.connect(self._status_panel.on_zion_stats)
        self._engine.s3_status.connect(self._status_panel.on_s3_status)
        self._status_panel.dolby_vision_detected.connect(self._on_dolby_vision_detected)
        self._status_panel.hdr_active_changed.connect(self._settings_panel.set_hdr_active)
        self._engine.property_changed.connect(self._on_property_for_playback)

        # Signal monitor (video processor mode)
        self._engine.property_changed.connect(
            lambda n, v: self._signal_monitor.on_property_changed(n, v)
            if self._app_config.app_mode == "video_processor" else None
        )
        self._signal_monitor.state_changed.connect(self._on_signal_state)
        self._signal_monitor.restart_requested.connect(self._on_restart)

        # Settings panel
        self._settings_panel.profile_changed.connect(self._on_profile_changed)
        self._settings_panel.wallpaper_change_requested.connect(self._on_change_wallpaper)
        self._settings_panel.input_changed.connect(self._on_input_changed)
        self._right_panel.opacity_changed.connect(self.set_panel_opacity)
        self._right_panel.app_mode_changed.connect(self._on_app_mode_changed)
        self._right_panel.restart_requested.connect(self._vp_restart_capture)

        # Input selector — switches capture port. Routed through the SOURCE page's handler
        # so the stop-playback warning is asked from one place; the same action reached from
        # two surfaces must not have two different safety rules.
        self._input_selector.input_changed.connect(self._on_source_port_selected)

        # The settings rail's SOURCE page — same switch, different surface. The rail
        # deliberately does nothing itself (it has no business touching the engine or the
        # INI), so both of these land in the handlers the status-bar selector already uses.
        self._s3_settings.input_selected.connect(self._on_source_port_selected)
        self._s3_settings.action_requested.connect(self._on_source_action)

        # Port enumeration for the SOURCE page. poll_all_ports() is a ctypes call into
        # decklink_monitor.dll, so it runs on this timer and never inside paintEvent.
        self._port_timer = QTimer(self)
        self._port_timer.setInterval(2500)
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start()
        QTimer.singleShot(700, self._refresh_ports)   # first paint of the tab has data

        # Playback bar → engine
        self._playback_bar.seek_requested.connect(self._on_seek)
        self._playback_bar.pause_toggled.connect(
            lambda: self._engine.set_property("pause",
                not self._engine.get_property("pause", False)))
        self._playback_bar.mute_toggled.connect(
            lambda: self._engine.set_property("mute",
                not self._engine.get_property("mute", False)))
        self._playback_bar.volume_changed.connect(
            lambda v: self._engine.set_property("volume", v))

        # Acquire overlay actions
        self._acquire_overlay.retry_requested.connect(self._start_vp_capture)
        self._acquire_overlay.input_selected.connect(self._on_input_changed)
        # Overlay "Media Player" button — no confirmation needed, user is on failure screen
        self._acquire_overlay.switch_to_media_player.connect(
            lambda: self._force_mode_change("media_player"))
        # Overlay "Exit" button. The failure dialog is modal over the whole app, so
        # it must offer a way out; close() runs the same ordered teardown as the
        # title bar (engine shutdown, config save), so there is one exit path.
        self._acquire_overlay.exit_requested.connect(self.close)

        # Playback controls → engine (track/audio-mode routed to the s3 engine;
        # everything else keeps the mpv-era set_property shim).
        self._playback_controls.property_change.connect(self._on_playback_property)

        # Engine properties → playback controls
        self._engine.property_changed.connect(self._on_property_for_playback_controls)

        # Media library
        self._media_library.play_requested.connect(self._on_play_file)
        # The library's bottom-bar button is the mode switch. _on_app_mode_changed
        # already owns the whole sequence: confirm if genuinely playing, stop and
        # shut the engine down, flip app_mode, then _start_vp_capture for the HDMI
        # feed. Reusing it keeps one definition of "switch to VP" instead of a
        # second path that drifts.
        self._media_library.switch_requested.connect(
            lambda: self._on_app_mode_changed("video_processor"))

        # Global hotkey
        self._hotkey.hotkey_pressed.connect(self._toggle_edit_mode)
        self._hotkey.start()

        # DeckLink signal monitor — fires when hardware reports signal loss/change
        self._dl_monitor.signal_locked.connect(self._on_dl_signal_locked)
        self._dl_monitor.format_changed.connect(self._on_dl_format_changed)
        self._dl_monitor.dynamic_range_changed.connect(self._on_dl_dynamic_range_changed)
        self._dl_monitor.signal_locked.connect(self._refresh_capture_status)
        self._dl_monitor.format_changed.connect(lambda _mode: self._refresh_capture_status())

        self._status_bar.update_profile(self._profile.name)
        self._status_bar.set_app_mode(self._app_config.app_mode)
        self._control_bar.set_app_mode(self._app_config.app_mode)
        self._right_panel.set_app_mode(self._app_config.app_mode)
        self._status_panel.set_app_mode(self._app_config.app_mode)

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def _set_mode(self, mode: AppMode) -> None:
        if self._mode == mode:
            return
        _audit.info(f"UI mode: {self._mode.name} -> {mode.name}")
        self._mode = mode

        if mode == AppMode.IDLE:
            self._mouse_hide_timer.stop()
            self._show_cursor()
            self._playback_bar.hide()
            self._playback_bar.reset()
            self._status_panel.hide()
            self._right_panel.hide()
            self._playback_controls.reset_for_new_file()
            self._viewport.hide()
            self._status_bar.show()
            self._control_bar.show()
            # The chrome is a separate top-level window docked over the whole frame
            # with a transparent middle -- and a transparent top-level still OWNS
            # mouse input in its transparent region. Left up, it sits over the media
            # library and eats every click meant for it, while the chrome's own
            # buttons keep working: exactly the "library visible but dead" report.
            # The chrome is a watch-mode affordance; the picker screen is not watch
            # mode, so it goes.
            self._show_chrome(False)
            self._set_overlay_opacity(_OVERLAY_OPACITY_EDIT)
            if self._app_config.app_mode == "media_player":
                self._background.show_instant()
                self._media_library.show()
                self._media_library.raise_()
            else:
                self._media_library.hide()
                self._background.show_instant()
            self._settings_panel.hide()

        elif mode == AppMode.WATCH:
            self._status_panel.hide()
            self._right_panel.hide()
            self._background.hide_instant()
            # Start mouse hide timer when entering watch mode
            self._mouse_hide_timer.start()
            self._media_library.hide()
            self._viewport.show()
            self._settings_panel.hide()
            self._playback_bar.hide()
            self._status_bar.hide()
            self._control_bar.hide()
            self.raise_()
            self.activateWindow()
            self._relayout()   # three-region layout: video expands full-width here
            self._show_chrome(False)
            # (The "blink pending on WATCH entry — re-acquiring" restart lived here.
            # Deleted 2026-09-21: it re-ran the acquisition overlay on WATCH entry when
            # a single unlocked monitor reading had set _dl_blink_seen during a disc
            # menu transition — over an engine that was healthy and delivering the whole
            # time. The UI audit showed the exact sequence: acquisition confirmed →
            # WATCH → blink pending → restart → black screen. Ingestion transitions are
            # the ENGINE's decision now (monitor → decider → executor); a one-sample
            # unlock is a fact the engine's own monitor already gates. Nothing here
            # restarts capture on a blink.)

        elif mode == AppMode.EDIT:
            self._mouse_hide_timer.stop()
            self._show_cursor()
            self._background.hide_instant()
            self._media_library.hide()
            self._viewport.show()
            # The in-window right rail is RETIRED: all interactive chrome
            # (status + settings + bars) now lives in the single chrome window.
            self._right_panel.hide()
            self._status_panel.show()
            self._settings_panel.show()
            if self._app_config.app_mode == "media_player":
                self._playback_bar.show()
            else:
                self._playback_bar.hide()
            self._status_bar.show()
            self._control_bar.show()
            self._set_overlay_opacity(_OVERLAY_OPACITY_EDIT)
            self.raise_()
            self.activateWindow()
            self._relayout()
            self._show_chrome(True)    # interactive rail window (Up)

        self._control_bar.set_edit_mode(mode == AppMode.EDIT)

    def _set_overlay_opacity(self, opacity: float) -> None:
        for w in (self._status_bar, self._control_bar):
            w.setWindowOpacity(opacity)

    def set_panel_opacity(self, opacity: float) -> None:
        self._panel_opacity = max(0.4, min(1.0, opacity))
        alpha = int(self._panel_opacity * 255)
        self._right_panel.setStyleSheet(
            f"RightPanel {{ background: rgba(10,10,12,{alpha}); }}"
        )

    @pyqtSlot()
    def _toggle_stats_osd(self) -> None:
        """Toggle mpv's built-in stats OSD (shows per-pass GPU timing).
        Triggered by the ℹ button in ControlBar.

        The stats overlay is rendered directly by mpv/libplacebo on the video
        surface and includes decode time, every libplacebo shader pass (scale,
        tone map, Zion Core hooks, etc.) with GPU ns timing, and frame graphs.
        Triggered via stats.lua's 'display-stats-toggle' binding.
        """
        _audit.info("info button: toggling stats OSD")
        try:
            self._engine.command("script-binding", "stats/display-stats-toggle")
            _audit.info("info button: script-binding sent OK")
        except Exception as e:
            _audit.warning(f"info button: script-binding failed ({e}), trying script-message-to")
            try:
                self._engine.command("script-message-to", "stats", "display-stats-toggle")
            except Exception as e2:
                _audit.warning(f"info button: both commands failed: {e2}")

    def _toggle_edit_mode(self) -> None:
        _audit.info(f"hotkey: toggle edit mode (current={self._mode.name})")
        if self._mode == AppMode.IDLE:
            # Route to the interactive rail window (was the in-window panel,
            # which is not clickable).
            self._show_chrome(
                getattr(self, "_chrome", None) is None
                or not self._chrome.isVisible())
            return
        self._set_mode(AppMode.EDIT if self._mode == AppMode.WATCH else AppMode.WATCH)

    def _apply_auto_curve_default(self, is_hdr: bool, is_dv: bool,
                                  has_meta: bool = True) -> None:
        """Per-source tone-curve DEFAULT (the user can still change it on the fly).

        DV (any profile, file or player) -> REFERENCE, i.e. Hable. Validated by the user
        across DV content: no other curve maps highlights to the target sdr nits as
        well. On PLAYER-mapped DV over HDMI the renderer's fingerprint makes Reference
        transfer instead of grade (one scalar, sdrNits/identityPeak), so the same
        default is right for both DV flavours — Hable where the signal is source-
        referred, identity where it is already display-referred.

        HDR10, with or without static metadata -> GT7 ADAPT. With metadata its adapted
        gain is sized by MaxCLL (Everest 991/220, Furiosa 909/140); without — the case
        where the card reads nothing — the peak it maps FROM falls to the guarded
        measured scene peak, which is the only peak available there.

        Taste (exposure trim, shadow detail, punch) is available on both defaults and
        is how the user offsets either; all three are exact no-ops at 0.

        SDR -> leave the curve alone.
        """
        if not is_hdr:
            return
        want = 7 if is_dv else 10   # Reference : GT7 Adapt
        row = next((r for r in self._s3_settings.rows
                    if r.key == "hdr.toneMapCurve"), None)
        if row is None:
            return
        table = VALUE_MAP.get(row.key) or []
        if want not in table:
            return
        if row.opt == table.index(want):
            return                        # already the default; don't re-push
        row.opt = table.index(want)
        self._s3_settings._rebuild()      # CURVE SETTINGS visibility tracks the curve
        self._s3_settings.update()
        self._engine.apply_settings({"hdr": {"curve": want}})
        _audit.info("auto tone-curve default: %s -> %d (hdr=%s dv=%s meta=%s)",
                    row.options[row.opt], want, is_hdr, is_dv, has_meta)

    def _on_s3_status(self, j: dict) -> None:
        """Push the INI'd settings on attach AND after every graph rebuild.

        The engine self-heals on any signal change, and each rebuild constructs
        a fresh MPCVR whose constructor re-reads its registry key — so the new
        instance does not carry what we pushed into the old one. `gen` bumps per
        build, which is the signal to re-push. (This used to be one-shot, so
        after the first rebuild the picture silently stopped following the rail.)
        """
        # Delivery heartbeat — tracked BEFORE the early return below, because the
        # state this is judged against is "playing", and "playing" is exactly the
        # state that survives a stall. Only a CHANGE of the counter means frames
        # are actually arriving; the value itself is cumulative and never resets.
        rec = j.get("render") or {}
        recv = rec.get("recv")
        if recv is not None and recv != self._recv_seen:
            self._recv_seen = recv
            self._recv_last_change_ts = time.monotonic()

        # Signal facts: the ENGINE measures the wire, the UI consumes. Pushed
        # before the early return so the status panel and the lock/format edges
        # keep working in every engine state.
        sig = j.get("signal")
        if isinstance(sig, dict):
            self._dl_monitor.update_facts(sig)

        gen = j.get("gen")
        if gen is None or j.get("state") in (None, "idle"):
            return
        if gen != getattr(self, "_s3_gen", None):
            self._s3_gen = gen
            _audit.info("engine: graph generation %s -> pushing settings", gen)
            self._s3_settings.push_all()

        # Audio rotate chips — feed every poll from the engine's audio block so the
        # active track reflects a switch (the engine is the source of truth). Only
        # when a FILE stream is loaded, so the capture path is untouched.
        aud = j.get("audio")
        media = j.get("media") or {}
        if isinstance(aud, dict) and media.get("valid"):
            tracks = aud.get("tracks") or []
            cur = next((t.get("i", 0) for t in tracks if t.get("active")), 0)
            mode = aud.get("mode", 1)
            # Feed the s3-shell rail's PLAYBACK audio rotate rows (the surface the
            # user actually uses). Only when the list/mode actually changed, so a
            # 1 Hz poll does not repaint the rail or fight a row mid-click.
            sig = (tuple((t.get("i"), t.get("name"), t.get("active")) for t in tracks), mode)
            if sig != getattr(self, "_audio_sig", None):
                self._audio_sig = sig
                self._s3_settings.set_audio_state(tracks, cur, mode)

        # Subtitle tracks — same treatment: the engine enumerates them from the splitter,
        # the rail only repaints when the list or the selection actually moved. The row used
        # to sit at ["Off"] forever because nothing fed it.
        sub = j.get("subtitle")
        if isinstance(sub, dict) and media.get("valid"):
            stracks = sub.get("tracks") or []
            scur = sub.get("current", -1)
            ssig = (tuple((t.get("i"), t.get("name"), t.get("active")) for t in stracks), scur)
            if ssig != getattr(self, "_sub_sig", None):
                self._sub_sig = ssig
                self._s3_settings.set_subtitle_state(stracks, scur)

        # Per-source tone-curve DEFAULT (file path): fires once per graph generation
        # once the media block is known. hdr and dovi arrive in the same poll, so
        # there is no race between "is it HDR" and "is it DV".
        if media.get("valid"):
            gen = j.get("gen")
            if gen != getattr(self, "_auto_curve_gen", None):
                self._auto_curve_gen = gen
                self._apply_auto_curve_default(bool(media.get("hdr")),
                                                 bool(media.get("dovi")))
        else:
            self._auto_curve_gen = None

        # Capture path: the card either reports ST.2086 or it does not, and that is
        # the whole question — GT7 when it does (metadata-sized gain), GT7 Adapt when
        # it doesn't (the Oppo case: DV keeps its mastering in the RPU, which the card
        # can't read, so the peak has to come from measurement). Fires on the lock
        # edge; resets on unlock so the next source re-applies its default.
        dl = j.get("dl") or {}
        locked = bool(dl.get("stream")) and bool((j.get("signal") or {}).get("locked"))
        if locked and not getattr(self, "_auto_curve_locked", False):
            self._auto_curve_locked = True
            eotf = int(dl.get("eotf") or 0)
            is_hdr = eotf in (2, 3)
            has_meta = bool(dl.get("hdrMeta")) or float(dl.get("maxCLL") or 0) > 1.0
            self._apply_auto_curve_default(is_hdr, False, has_meta)
        elif not locked:
            self._auto_curve_locked = False

        # The engine takes Title peak from the card's ST 2086 MaxCLL whenever the
        # signal carries one (see MpcPlayer::ApplyPendingSettings). Re-push when it
        # appears or changes, because the generation push above cannot carry it: on
        # a fresh graph the card has not read the InfoFrame yet — frame 1 returns
        # E_UNEXPECTED with zeros, the real values arrive on frame 2. MaxCLL is
        # static per title, so this fires once per disc, not once per poll.
        dl = j.get("dl") or {}
        meta = dl.get("maxCLL") if dl.get("hdrMeta") else None
        if meta != getattr(self, "_s3_hdr_meta", None):
            self._s3_hdr_meta = meta
            _audit.info("engine: card HDR meta -> %s, re-pushing settings", meta)
            self._s3_settings.push_all()

        
    def _show_chrome(self, show: bool) -> None:
        """ONE interactive chrome window (status left, settings right, transport
        bottom) shown modally over the video. In-window widgets are not
        clickable — the video renderer's window covers the client area for
        input; a modal top-level window above it is (bench-verified). Toggled
        by Up; the middle is transparent so the video shows through."""
        if getattr(self, "_chrome", None) is None:
            if not show:
                return
            self._chrome = SettingsWindow(self._app_config, self._profile,
                                          parent=self)
            self._chrome.adopt(self._status_panel, self._s3_settings,
                               [self._control_bar, self._playback_bar],
                               rail_left=min(_STATUS_WIDTH, 340),
                               rail_right=min(_SETTINGS_WIDTH, 520),
                               top=self._status_bar)
            self._chrome_adopted = True
            self._relayout()
        if show:
            self._chrome.dock(self.frameGeometry())
            self._chrome.show()
            self._chrome.raise_()
            self._chrome.activateWindow()
            # The seek bar is PRESENT but inert in VP mode (the app's own rule
            # hides it) — force it visible so the middle slot doesn't vanish.
            self._playback_bar.show()
        else:
            self._chrome.hide()

    # ------------------------------------------------------------------
    # Wallpaper
    # ------------------------------------------------------------------

    def _apply_wallpaper(self) -> None:
        wp = self._app_config.wallpaper_path
        if wp and Path(wp).exists():
            self._background.load_wallpaper(Path(wp))
        elif _DEFAULT_WALLPAPER.exists():
            self._background.load_wallpaper(_DEFAULT_WALLPAPER)
        # Defer idle screen setup to showEvent so layout is correct
        # (geometry is 0x0 before the first showEvent/relayout)

    def _apply_idle_screen(self) -> None:
        self._background.show_instant()
        self._media_library.hide()
        QTimer.singleShot(100, self._splash.show_centered)

        if self._app_config.first_run:
            # Show splash first, then first-run dialog after it dismisses
            self._splash.finished.connect(self._show_first_run)
        elif self._app_config.app_mode == "media_player":
            def _show_media_player():
                self._media_library.show()
                self._media_library.raise_()
                self._status_bar.raise_()
                self._control_bar.raise_()
            self._splash.finished.connect(_show_media_player)
        else:
            self._splash.finished.connect(self._start_vp_capture)

    def _chrome_was_visible(self) -> bool:
        """Hide the settings chrome and report whether it was up.

        The chrome is a window-modal dialog (settings_window.py:40, "required for input
        priority") parented to the main window. Qt's window-modality disables every OTHER
        window in that hierarchy — so any dialog opened while the chrome is up paints fine
        but is disabled, and every click on it lands nowhere. That is exactly how the
        first-run dialog presented: visible, inert. Anything modal that must take input
        while the chrome is open needs the chrome out of the way first.
        """
        chrome = getattr(self, "_chrome", None)
        was = bool(chrome and chrome.isVisible())
        if was:
            chrome.hide()
        return was

    def _show_first_run(self) -> None:
        """Present the first-run dialog over the app's idle background, not over whatever
        surface happens to be up.

        The dialog is a frameless card with transparent margins, so the media library stays
        visible around its rounded corners — which read as "a setup box sitting on top of
        my file list" when setup is re-run from the Source tab. The surfaces it can replace
        are put away first and restored if the user backs out, so cancelling costs them
        nothing.
        """
        was_library = self._media_library.isVisible()
        was_viewport = self._viewport.isVisible()
        if was_library or was_viewport:
            self._media_library.hide()
            self._viewport.hide()
            self._background.show_instant()
        chrome_up = self._chrome_was_visible()
        completed = [False]
        # Parentless on purpose: as a child of the main window the dialog sits inside the
        # same hierarchy the window-modal chrome disables, which is one of the two ways it
        # presented as "visible but inert". Application-modal plus no parent puts it
        # outside any disabled tree.
        dlg = FirstRunDialog(self._app_config, None)

        def _on_complete(mode: str, url: str) -> None:
            nonlocal was_library, was_viewport
            completed[0] = True
            was_library = was_viewport = False     # the choice decides what comes next
            dlg.close()
            self._on_first_run_complete(mode, url)

        def _on_done(_result) -> None:
            # Backed out (Esc/close) without completing: put back what was up, or the user
            # is left staring at a background they never asked for. The chrome comes back
            # too — it was the surface the request came from.
            if was_library:
                self._media_library.show()
                self._media_library.raise_()
            if was_viewport:
                self._viewport.show()
                self._viewport.raise_()
            if chrome_up and not completed[0]:
                self._chrome.show()
                self._chrome.raise_()
            dlg.deleteLater()

        dlg.setup_complete.connect(_on_complete)
        dlg.finished.connect(_on_done)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    @pyqtSlot(str, str)
    def _on_first_run_complete(self, mode: str, active_url: str) -> None:
        self._app_config.first_run = False
        if active_url:
            self._app_config.active_input_url = active_url
            self._profile.input.device = active_url
        prev = self._app_config.app_mode
        if mode != prev:
            # A re-run that CHANGES the mode has to actually stop what was running: the
            # engine shutdown, the acquire-overlay dismissal and the chrome updates all
            # live in _force_mode_change, and duplicating part of them here is how a
            # capture gets left running behind the library screen. It returns early when
            # the mode is unchanged, which is why the same-mode path follows.
            self._force_mode_change(mode)
            return
        # Same mode, possibly a different input: apply the choice and restart capture.
        self._app_config.app_mode = mode
        # Apply the chosen mode
        self._status_bar.set_app_mode(mode)
        self._control_bar.set_app_mode(mode)
        self._right_panel.set_app_mode(mode)
        self._status_panel.set_app_mode(mode)
        is_vp = mode == "video_processor"
        self._input_selector.setVisible(is_vp)
        if is_vp:
            self._input_selector.start_polling()
            QTimer.singleShot(200, self._start_vp_capture)
        else:
            self._media_library.show()
            self._media_library.raise_()
            self._status_bar.raise_()
            self._control_bar.raise_()
        self._relayout()

    @pyqtSlot()
    def _on_change_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Background Image", str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.webp *.bmp)",
        )
        if path and self._background.load_wallpaper(Path(path)):
            self._app_config.wallpaper_path = path

    # ------------------------------------------------------------------
    # Engine initialisation helpers
    # ------------------------------------------------------------------

    def _init_engine_with_options(self, url: str, extra_args: list[str]) -> None:
        """
        Initialise the engine (once), apply options, observe properties, play.
        """
        # PLAY-PATH BRACKETS. A hang in this function is invisible from the engine
        # log (the command never arrives) and invisible to the user (frozen UI), so
        # the only evidence that can exist is which bracket was written last. Each
        # stage logs on entry; the gap between panel.log's final line and the next
        # stage names the hang.
        _audit.info("play path: enter _init_engine_with_options")
        self._viewport.show()
        self._viewport.raise_()
        self._viewport.winId()
        wid = self._viewport.hwnd()
        _audit.info(f"play path: viewport hwnd={wid}")

        # Initialise engine once — subsequent calls are no-ops; each engine guards
        # its own re-entry internally. (The old `if not self._engine._mpv` check
        # is an mpv-ism: the S3 engine keeps _mpv as a truthy compat sentinel,
        # so the guard always skipped initialise(), s3_attach(wid) never ran, and
        # Media mode played audio into an UNBOUND renderer — no video, 2026-09-22.)
        _mp_startup: dict = {}
        for _a in extra_args:
            if _a.startswith("--log-file="):
                _mp_startup["log_file"] = _a[len("--log-file="):]
            elif _a.startswith("--msg-level="):
                _mp_startup["msg_level"] = _a[len("--msg-level="):]
        self._engine.initialise(self._app_config.mpv_executable, wid=wid,
                                startup_opts=_mp_startup or None)
        _audit.info("play path: engine initialised")

        if not self._engine._mpv:
            QMessageBox.critical(self, "Engine Error",
                "Failed to load libmpv. Check that libmpv-2.dll "
                "is in the same folder as mpv.exe.")
            return

        # Observe all needed properties
        for prop in _STATUS_PROPS + _PLAYBACK_PROPS + _PLAYBACK_CTRL_PROPS:
            self._engine.observe(prop)

        # Populate audio devices and restore saved session preferences
        devices = self._engine.get_property("audio-device-list")
        if devices:
            self._playback_controls.update_audio_devices(devices)
        self._playback_controls.restore_from_config()

        # Apply saved settings to engine after file loads
        QTimer.singleShot(800, self._playback_controls.emit_saved_settings)

        # Apply vf filter chain before playing (structural option)
        vf_arg = next((a[5:] for a in extra_args if a.startswith("--vf=")), None)
        if vf_arg:
            self._engine.set_property("vf", vf_arg)

        # Apply all other options
        self._apply_serialiser_args(extra_args)
        _audit.info(f"media_player: mpv args = {extra_args}")

        # Push profile live settings
        _audit.info("play path: syncing live settings")
        sync_all_live(self._engine, self._profile)

        _audit.info(f"play path: engine.play({url})")
        self._engine.play(url)
        _audit.info("play path: engine.play returned")
        self._acquire_overlay.dismiss()   # stale VP overlay must not persist over file playback
        # Polling is now deferred until first video-params (first real frame)
        # in MpvEngine._on_property_qt — no timer needed here.

    # Options that cannot be safely changed at runtime via set_property
    _SKIP_RUNTIME = {
        "wid", "input-ipc-server", "log-file", "msg-level", "input-conf",
        "profile",
        "no-demuxer-thread", "no-cache", "audio-buffer", "vd-lavc-threads",
        "demuxer-lavf-analyzeduration", "demuxer-lavf-probesize",
        "demuxer-lavf-o-add",
        "demuxer-max-bytes", "demuxer-max-back-bytes",
        "vf",
        "audio",
    }

    def _apply_serialiser_args(self, args: list[str]) -> None:
        """
        Parse the mpv CLI arg list and apply each option to the engine.

        Options are applied via mpv_set_option_string, NOT set_property:
        in this libmpv build every launch option (demuxer-lavf-o, vd-lavc-o,
        framedrop, video-latency-hacks, ml-acq-*) returns
        MPV_ERROR_PROPERTY_NOT_FOUND (-8) from set_property and was being
        silently dropped — the app ran with mpv's defaults, which is why the
        latency flags never took effect. The option-string route equals the CLI.
        """
        apply = []
        for arg in args:
            if not arg.startswith("--"):
                continue
            kv = arg[2:]
            if kv.startswith("libplacebo-opts-set="):
                self._engine.apply_libplacebo_opts(kv[len("libplacebo-opts-set="):])
                continue
            name = kv.partition("=")[0]
            if name in self._SKIP_RUNTIME:
                continue
            apply.append(arg)
        self._engine.apply_options(apply)

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_stop_user(self) -> None:
        """Stop playback and return to the media library (media player mode)."""
        _audit.info("user: stop playback")
        self._engine.stop()
        self._set_mode(AppMode.IDLE)
        self._media_library.show()
        self._media_library.raise_()
        self._media_library.refresh_last_played()

    @pyqtSlot()
    def _on_restart_user(self) -> None:
        """Explicit user restart (button / F5) — always does full re-acquisition in VP mode."""
        _audit.info("user: restart requested")
        self._restart_needed = False
        self._control_bar.set_restart_pending(False)
        if self._app_config.app_mode == "video_processor":
            self._vp_restart_capture()
            return
        url = self._current_file or self._profile.input.device
        self._engine.stop()
        QTimer.singleShot(200, lambda: self._engine.play(url))

    @pyqtSlot()
    def _on_restart(self) -> None:
        """Auto-restart from signal monitor.

        The monitor timed out meaning mpv's stream is stale (frozen video-pts /
        no video-params updates) for loss_timeout+cooldown — that is BROKEN
        even when the DeckLink control plane still reports signal_locked=True
        (receiver re-handshake can hold the lock line while video PTS freezes).
        Re-arming the monitor while leaving the stale stream up produced a
        silent 8-second restart loop and a permanent black viewport, so we do a
        real hardware re-acquisition (terminate libmpv + re-read signal info).
        """
        _audit.info("signal monitor: restart requested")
        if self._app_config.app_mode == "video_processor":
            self._vp_restart_capture()
            return
        url = self._current_file or self._profile.input.device
        self._engine.stop()
        QTimer.singleShot(200, lambda: self._engine.play(url))

    @pyqtSlot(str)
    def _on_play_file(self, path: str) -> None:
        _audit.info(f"user: play file  {path}")
        self._media_was_playing = False   # re-armed by the next PLAYING state
        self._current_file = path
        self._dv_switched_for = ""
        self._status_panel.set_dv_active(False)
        # Ensure audio is enabled (may be disabled from a previous VP capture session)
        if self._engine._mpv:
            try:
                self._engine._mpv["audio"] = True
            except Exception:
                pass
        self._media_library.hide()
        # Show awakening animation while the file loads (dismissed when PLAYING fires)
        self._acquire_overlay.start_acquiring(path, max_attempts=1)
        args = build_media_player_args(self._profile, "", path, wid=0)
        self._init_engine_with_options(path, args)
        self._media_library.refresh_last_played()

    # ------------------------------------------------------------------
    # Calibrate colour — HDR→SDR measurement capture
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_calibrate(self) -> None:
        """Play the 16-patch HDR clip and capture one frame per patch.

        Normal playback is untouched: this is a one-shot command. The clip plays
        through the SAME normal playback path (so we measure the exact configured
        picture). The calibrate module is imported at MODULE level (top of file):
        any frozen-app import problem then fails LOUDLY at startup instead of
        silently inside this slot, and the entry line below proves the button
        handshake reached here.
        """
        _audit.info("user: calibrate slot entered")
        try:
            self._calibrate_impl()
        except Exception as e:   # noqa: BLE001
            _audit.error("user: calibrate failed in slot — %r", e)
            if getattr(self, "_cal_overlay_lbl", None) is not None:
                self._cal_overlay_lbl.hide()
            self._media_library.show_message(f"Calibrate failed: {e}")

    def _calibrate_impl(self) -> None:
        _audit.info("user: calibrate clicked")
        if getattr(self, "_cal_session", None) is not None and self._cal_session.is_active():
            return
        if not Path(CALIBRATE_VIDEO).exists():
            QMessageBox.warning(
                self, "Calibrate colour",
                f"Patch clip missing:\n{CALIBRATE_VIDEO}\n\n"
                "Generate it with C:\\Users\\satee\\Pictures\\calibrate\\gen_patches.py "
                "and the ffmpeg encode step.")
            return
        if not ConfirmDialog.ask(
                self, "Calibrate colour",
                "Play the 16-patch HDR calibration clip (~20 s) and save rendered "
                "frames + a measurements manifest into the folder you choose?",
                "Calibrate"):
            return
        start = self._app_config.calibration_output_dir or str(Path.home())
        out_dir = QFileDialog.getExistingDirectory(
            self, "Save calibration output", start)
        if not out_dir:
            return
        self._app_config.calibration_output_dir = out_dir
        expected = load_expected_table(CALIBRATE_CSV) or _default_expected()
        # The NORMAL playback path — the session measures exactly what plays.
        self._on_play_file(CALIBRATE_VIDEO)
        session = CalibrationSession(parent=self)
        self._cal_session = session
        session.message.connect(self._cal_overlay_text)
        session.progress.connect(self._cal_overlay_progress)
        session.finished.connect(self._on_calibrate_finished)
        session.start(self._engine, CALIBRATE_VIDEO, Path(out_dir), expected,
                      profile_name=self._app_config.active_profile)
        _audit.info(f"user: calibrate started -> {out_dir}")

    def _cal_overlay(self) -> QLabel:
        """Always-on-top progress card (WATCH hides chrome, so this owns its own)."""
        if getattr(self, "_cal_overlay_lbl", None) is None:
            lbl = QLabel("Calibrating…")
            lbl.setWindowFlags(
                Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint)
            lbl.setStyleSheet(
                "background:#0e0e0e;color:#e0e0e0;border:1px solid #E8551F;"
                "font-size:16px;padding:10px 16px;border-radius:6px;")
            lbl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._cal_overlay_lbl = lbl
        return self._cal_overlay_lbl

    def _cal_overlay_text(self, text: str) -> None:
        lbl = self._cal_overlay()
        lbl.setText(f"Calibrating · {text}")
        lbl.adjustSize()
        if not lbl.isVisible():
            scr = self.screen() or QApplication.primaryScreen()
            if scr:
                geo = scr.availableGeometry()
                lbl.move(geo.right() - lbl.width() - 24, geo.top() + 24)
        lbl.show()

    @pyqtSlot(int, int)
    def _cal_overlay_progress(self, done: int, total: int) -> None:
        lbl = self._cal_overlay()
        lbl.setText(f"Calibrating {done}/{total}" if total else f"Calibrating {done}")
        lbl.adjustSize()
        if not lbl.isVisible():
            scr = self.screen() or QApplication.primaryScreen()
            if scr:
                geo = scr.availableGeometry()
                lbl.move(geo.right() - lbl.width() - 24, geo.top() + 24)
        lbl.show()

    @pyqtSlot(bool, str)
    def _on_calibrate_finished(self, ok: bool, summary: str) -> None:
        """End the session: hide the overlay, return to the library, report."""
        if getattr(self, "_cal_overlay_lbl", None) is not None:
            self._cal_overlay_lbl.hide()
        self._cal_session = None
        self._on_stop_user()
        self._media_library.show_message(f"Calibrate: {summary}")
        _audit.info(f"user: calibrate finished ok={ok} — {summary}")

    # ------------------------------------------------------------------
    # Engine state slots
    # ------------------------------------------------------------------

    @pyqtSlot(EngineState)
    def _on_engine_state(self, state: EngineState) -> None:
        _audit.info(f"engine: state -> {state.name}  (vp_acquiring={self._vp_acquiring}, mode={self._mode.name})")
        # During VP acquisition, only handle PLAYING (success) — ignore all else
        if self._vp_acquiring and state != EngineState.PLAYING:
            return
        from ..core.process_manager import ProcessState
        state_map = {
            EngineState.IDLE:    ProcessState.STOPPED,
            EngineState.READY:   ProcessState.STOPPED,
            EngineState.PLAYING: ProcessState.RUNNING,
            EngineState.PAUSED:  ProcessState.RUNNING,
            EngineState.ENDED:   ProcessState.STOPPED,
            EngineState.ERROR:   ProcessState.CRASHED,
        }
        ps = state_map.get(state, ProcessState.STOPPED)

        self._control_bar.set_running(state == EngineState.PLAYING)
        self._status_bar.update_process_state(ps)
        self._status_panel.set_process_state(ps)

        if state == EngineState.PLAYING:
            # Arms exit-on-finish: see _media_was_playing.
            if self._app_config.app_mode == "media_player":
                self._media_was_playing = True
            # The acquire overlay belongs to VP acquisition; once the engine is
            # PLAYING it is stale in ANY mode (including a leftover from a prior
            # VP session in Media mode — it would otherwise animate forever over
            # working playback). Dismiss unconditionally, before the acquiring
            # branch decides anything.
            self._acquire_overlay.dismiss()
            if self._vp_acquiring:
                # DeckLink briefly reports PLAYING before ENDED on failure.
                # Wait 600ms to confirm the signal is genuinely stable.
                QTimer.singleShot(600, self._vp_confirm_playing)
                # Keep the safety net armed as well. This transition may be the
                # only PLAYING we see, and the shot above is a single moment — if
                # the engine is settling at that instant, the check timer is the
                # only thing left that can still confirm (it now does).
                self._vp_check_timer.start(1500)
            else:
                self._acquire_overlay.dismiss()
                self._vp_retry_timer.stop(); self._vp_check_timer.stop()
                self._set_mode(AppMode.WATCH)
                if self._app_config.app_mode == "video_processor":
                    self._signal_monitor.start()

        elif state == EngineState.READY:
            pass   # Engine initialised — wait for play()

        elif state in (EngineState.ENDED, EngineState.IDLE, EngineState.ERROR):
            self._signal_monitor.stop()
            self._playback_bar.reset()

            # VP WATCH mode: ENDED/ERROR is almost always a DeckLink reconnect
            # loop (libav redirect). Silently replay without touching the mode —
            # the debounced _dl_unlock_timer handles genuine signal loss.
            # Never call is_signal_locked() here — DeckLink hardware may briefly
            # report unlocked at the exact moment of the redirect, causing a false
            # IDLE transition and wallpaper flash.
            if (state != EngineState.IDLE
                    and self._app_config.app_mode == "video_processor"
                    and not self._vp_acquiring
                    and self._mode == AppMode.WATCH
                    and self._engine._mpv is not None):
                vf = getattr(self, "_detected_vf", None)
                if vf:
                    self._engine.set_property("vf", vf)
                url = self._profile.input.device
                self._engine._video_params_seen = False
                QTimer.singleShot(200, lambda: self._engine.play(url))
                return

            # A FINISHED TITLE ENDS THE SESSION. Returning to the library after EOF
            # was the origin of three separate input-ownership bugs in a row -- the
            # renderer's native window over the Qt widgets, the chrome top-level over
            # the library, and the leftover-capture join -- each one a fight over who
            # owns the mouse on that screen. The product decision is simpler and it
            # fits the HTPC use: when the film is over, the app is over.
            #
            # Gated on _media_was_playing because the engine reports "idle" both at
            # startup and after a title ends, and the state string alone cannot tell
            # them apart. ERROR is excluded on purpose: a failed open must not kill
            # the app.
            # ENDED ONLY. The engine now reports "ended" distinctly (StateName), and
            # that is the only state that means a title finished. IDLE and LOADING
            # also occur mid-stream -- a rebuild-only re-open reports opening/idle
            # for a moment -- and treating those as end-of-title closed the app one
            # second into playback, mid-film, on 2026-10-09.
            if (self._app_config.app_mode == "media_player"
                    and self._media_was_playing
                    and state == EngineState.ENDED):
                self._media_was_playing = False
                self._exit_without_confirm = True
                _audit.info("media: title finished -> graceful exit (no confirmation)")
                self.close()
                return

            self._set_mode(AppMode.IDLE)
            if self._app_config.app_mode == "media_player":
                self._media_library.refresh_last_played()
            else:
                self._background.fade_in()

    @pyqtSlot(str, str, str)
    def _on_engine_log(self, level: str, component: str, message: str) -> None:
        if level in ("error", "fatal"):
            _log.error(f"[mpv/{component}] {message}")

    # ── SOURCE page (settings rail) ──────────────────────────────────────────

    @pyqtSlot()
    def _refresh_ports(self) -> None:
        """Enumerate DeckLink ports and hand them to the rail's SOURCE page.

        Runs on a timer, never from paint: poll_all_ports() crosses into
        decklink_monitor.dll (ctypes) and reads device state. It is documented read-only
        — safe while the capture filter holds a port — which is why the status-bar
        selector has been doing it every 2 s in VP mode all along.

        Skipped when nothing could use the answer: media-player mode with the settings
        chrome closed. The signature guard means a steady card costs one repaint, not a
        layout rebuild, every tick.
        """
        if (self._app_config.app_mode != "video_processor"
                and getattr(self, "_chrome", None) is None):
            return
        try:
            ports = poll_all_ports()
        except Exception:
            _log.exception("source: poll_all_ports failed")
            return
        active = self._app_config.active_input_url or ""
        sig = (tuple((getattr(p, "url", ""), getattr(p, "locked", False),
                      getattr(p, "dynamic_range", 0), getattr(p, "unknown", False))
                     for p in ports), active)
        if sig == getattr(self, "_ports_sig", None):
            return
        self._ports_sig = sig
        try:
            self._s3_settings.set_source_state(ports, active,
                                                self._app_config.get_input_labels())
        except Exception:
            _log.exception("source: set_source_state failed")

    def _engine_quiesce(self) -> None:
        """Stop what is playing WITHOUT taking the app down with it.

        Three places used to call engine.shutdown() here — a mode switch, a forced mode
        switch, and the Source tab's stop-playback gate. shutdown() is the app's EXIT
        routine: it releases the DLL and arms a 15 s os._exit(0) watchdog that exists so a
        closing process can never linger and hold the DeckLink. Called from a settings
        change, that watchdog is a delayed suicide: pick Media Player in first-run setup
        while a film was playing and the app vanished a quarter of a minute later, cleanly
        and with no crash to read.

        A switch needs much less. pause() takes the sound and picture off, stop_capture()
        hands the card back (empty device name is the engine's documented "capture off"),
        and the next Open()/SetDecklinkCapture() replaces whatever graph is loaded — the
        engine already tears down the old graph as the first thing it does.
        """
        self._engine.pause(True)
        self._engine.stop_capture()

    def _relaunch_for_setup(self) -> None:
        """Restart the app into the first-run wizard.

        Re-entering setup mid-session means dragging a live engine, an open settings chrome
        and possibly a playing file into a wizard that was designed to run over a splash
        screen and an idle background — and every one of those is a window that can out-rank
        or out-disable the dialog. The startup path is the one that has always worked, so
        this flags first_run, saves, spawns a detached copy of ourselves and closes. The
        new process shows splash → wizard, exactly as a genuine first launch does.
        """
        cfg = self._app_config
        cfg.first_run = True
        path = getattr(cfg, "_config_path", None)
        if path:
            cfg.save(Path(path))          # must land before the child reads it
        else:
            _audit.warning("setup: config path unknown — the relaunch will not see first_run")
        self._spawn_relaunch()
        self.close()                      # ordered teardown; shutdown(for_exit=True) inside

    def _spawn_relaunch(self) -> None:
        import subprocess

        if getattr(sys, "frozen", False):
            cmd = [sys.executable]                       # the packaged exe
            cwd = str(Path(sys.executable).parent)
        else:
            root = Path(__file__).resolve().parents[3]   # .../src/unplugged-ui
            cmd = [sys.executable, str(root / "launch.py")]
            cwd = str(root)
        _audit.info(f"setup: relaunching — {cmd} cwd={cwd}")
        # Hand the single-instance mutex back BEFORE spawning: the child checks it in its
        # first lines, and this process would otherwise hold it until teardown finishes
        # (engine shutdown alone is bounded at ~10 s), which made the child exit as a
        # "second instance" and the restart present as the app simply closing.
        from ..main import release_instance_lock
        release_instance_lock()
        # Detached so the child is not killed with our process group, and started before
        # we begin tearing down: the child's splash buys five seconds for this process to
        # release the DeckLink before the child tries to capture.
        subprocess.Popen(
            cmd, cwd=cwd, close_fds=True,
            creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                           | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
        )

    def _stop_playback_for_source(self, what: str) -> bool:
        """Warn, then actually stop, before anything on the SOURCE page replaces what is on
        screen. Returns False if the user declined (and then nothing has changed).

        The bug this closes: choosing Media Player in a re-run of first-time setup while a
        file was playing left the film running behind the library, because the mode had not
        changed and every stop lived in the mode-change path. Stopping at the ENTRY point
        means the handlers downstream can assume nothing is playing, instead of each one
        remembering to check.
        """
        if not self._engine.is_playing():
            return True
        ok = ConfirmDialog.ask(
            "Stop playback?",
            f"{what}\n\nPlayback will be stopped if you proceed.",
            confirm_label="Stop and continue",
            parent=self,
        )
        if not ok:
            _audit.info("user: declined to stop playback — nothing changed")
            return False
        # Pause and hand the card back — NOT shutdown(), which is the exit routine and
        # would schedule os._exit(0) fifteen seconds after the user changed a setting.
        _audit.info(f"user: stopping playback to proceed — {what}")
        self._engine_quiesce()
        self._vp_acquiring = False
        self._vp_retry_timer.stop()
        self._vp_check_timer.stop()
        self._acquire_overlay.dismiss()
        self._set_mode(AppMode.IDLE)
        self._background.show_instant()
        return True

    @pyqtSlot(str)
    def _on_source_port_selected(self, url: str) -> None:
        """A port row on the SOURCE page was clicked.

        In media-player mode this is also a mode change, and it goes through the same
        _on_app_mode_changed the mode buttons use — that path confirms with the user and
        shuts the engine down, which is what makes the capture restart safe. A cancelled
        confirm must not leave a file paused mid-play, so the switch is dropped when the
        mode is still media_player afterwards.
        """
        if not url:
            return
        name = self._app_config.label_for(url) or url.split("://", 1)[-1]
        if not self._stop_playback_for_source(f"Switching the input to “{name}”."):
            return
        if self._app_config.app_mode != "video_processor":
            self._on_app_mode_changed("video_processor")
            if self._app_config.app_mode != "video_processor":
                _audit.info("user: source pick cancelled at the mode confirm — staying in media player")
                return
        self._on_input_changed(url)

    @pyqtSlot(str)
    def _on_source_action(self, key: str) -> None:
        if key == "src.rescan":
            self._ports_sig = None      # force the next refresh to repaint
            self._refresh_ports()
        elif key == "src.rename":
            # Same modality trap as first-run: the chrome would leave this dialog painted
            # but disabled, so it gets the chrome to itself for the duration.
            chrome_up = self._chrome_was_visible()
            dlg = InputConfigDialog(self._app_config, parent=self)
            dlg.input_changed.connect(self._on_source_port_selected)
            dlg.exec()
            if chrome_up:
                self._chrome.show()
                self._chrome.raise_()
            self._ports_sig = None      # names may have changed
            self._refresh_ports()
        elif key == "src.setup":
            # Restart, not an in-place dialog. The wizard was designed to run over the
            # splash and an idle background; running it inside a live session is what
            # produced the painted-but-inert dialog. The warning names both costs.
            ok = ConfirmDialog.ask(
                "Run first-time setup?",
                "The app will restart and open the setup wizard.\n\n"
                "Playback will be stopped if you proceed.",
                confirm_label="Restart and set up",
                parent=self,
            )
            if ok:
                _audit.info("user: restarting into first-time setup")
                self._relaunch_for_setup()
        else:
            _audit.info(f"source: unhandled action {key}")

    @pyqtSlot(str)
    def _on_input_changed(self, url: str) -> None:
        """User selected a different input port — restart capture on new port."""
        _audit.info(f"user: input port changed -> {url}")
        self._app_config.active_input_url = url
        self._profile.input.device = url
        self._settings_panel.sync_device_combo()
        self._vp_restart_capture()

    @pyqtSlot(bool)
    def _on_dl_signal_locked(self, locked: bool) -> None:
        """DeckLink reports locked/unlocked — DISPLAY and bookkeeping only.

        The engine owns signal transitions (its monitor gates a loss past its own
        grace and the ingest decider requests Stop/Launch). This handler used to
        set _dl_blink_seen and re-run acquisition on lock restore — which fired
        over a healthy engine during disc-menu transitions and left the screen
        black (audit 2026-09-21). A single unlocked poll is not a decision.
        """
        _audit.info(f"decklink: signal_locked={locked}")
        if self._app_config.app_mode != "video_processor":
            return
        if locked:
            self._dl_unlock_timer.stop()   # a pending confirmation check is moot
            return
        if self._mode == AppMode.WATCH:
            # keep the grace window for DISPLAY purposes only (_on_dl_unlock_confirmed)
            self._dl_unlock_timer.start(1500)

    def _on_dl_unlock_confirmed(self) -> None:
        """Sustained loss confirmed past the grace window — DISPLAY it only.

        This used to stop the monitor and call _vp_restart_capture(). Neither is
        the UI's call: the engine's monitor already applies its own (longer)
        unlock grace and will emit a Stop decision, and stopping the PYTHON
        monitor here no longer closes a device (it never opened one) — it just
        makes is_signal_locked()/get_signal_info() report "nothing" for good.
        """
        if self._app_config.app_mode != "video_processor":
            return
        if self._mode != AppMode.WATCH:
            return
        if self._dl_monitor.is_signal_locked():
            return   # re-locked before the grace window elapsed
        _audit.info("decklink: unlock confirmed past grace (engine owns the teardown)")
        self._refresh_capture_status()

    @pyqtSlot(int)
    def _on_dl_format_changed(self, mode: int) -> None:
        """A format/colour-space fact changed — DISPLAY it. Do not act on it.

        These two handlers used to stop the monitor and call
        _vp_restart_capture(). That made the UI a second ingestion decider, and
        it looped: _vp_restart_capture → _start_vp_capture → monitor.start()
        resets the edge state → the next poll re-emits the same edge → restart
        again, forever, flashing the acquiring overlay over a working picture.

        Ingestion is the engine's decision now — the native monitor publishes a
        settled fact, the IngestController decides Launch/Reload/Stop and the
        ops-queue executor acts. The UI only reflects what it is told.
        """
        if self._app_config.app_mode != "video_processor":
            return
        _audit.info(f"decklink: format changed -> mode={mode:#x} (engine owns the restart)")
        self._refresh_capture_status()

    @pyqtSlot(int)
    def _on_dl_dynamic_range_changed(self, dr: int) -> None:
        """Dynamic-range/colour-space fact changed — DISPLAY it, do not act.
        See _on_dl_format_changed for why this no longer restarts anything."""
        if self._app_config.app_mode != "video_processor":
            return
        _audit.info(f"decklink: dynamic_range/colorspace changed -> dr={dr} (engine owns the restart)")
        self._refresh_capture_status()

    @pyqtSlot(SignalState)
    def _on_signal_state(self, state: SignalState) -> None:
        if self._vp_acquiring:
            return   # acquiring — don't let signal monitor flash the background
        self._status_bar.update_signal_state(state)
        if state == SignalState.ACTIVE:
            self._background.fade_out()
        elif state == SignalState.IDLE:
            self._background.fade_in()
        elif state == SignalState.NO_SIGNAL:
            # mpv's pts-based timeout can false-positive during transient
            # demuxer buffer stalls (e.g. large uncompressed 4K frames
            # backing up the packet queue) even though the hardware is
            # still receiving a valid signal. Trust the DeckLink hardware
            # lock state as authoritative in VP mode to avoid flashing the
            # wallpaper over an otherwise-live capture.
            if (self._app_config.app_mode == "video_processor"
                    and self._dl_monitor.is_signal_locked()):
                return
            self._background.fade_in()

    @pyqtSlot(str, object)
    def _on_playback_property(self, name: str, value) -> None:
        # Audio track + audio mode drive the s3 engine directly; the mpv-era
        # set_property shim is a logged no-op for these. For "aid" the value is the
        # stream id we published (audio-relative index); "audio-spdif" is "" (PCM)
        # or "auto" (Bitstream). "sid" is deferred — the graph has no subtitle
        # renderer, so selecting one would do nothing. Everything else keeps the
        # old shim (volume/mute/pause/etc.).
        if name == "aid":
            try:
                self._engine.select_audio_track(int(value))
            except (TypeError, ValueError):
                pass
        elif name == "audio-spdif":
            self._engine.set_audio_mode(1 if str(value) == "auto" else 0)
        elif name == "sid":
            pass
        else:
            self._engine.set_property(name, value)

    def _on_property_for_playback_controls(self, name: str, value) -> None:
        if name == "track-list":
            if value:
                self._playback_controls.update_track_list(value)
        elif name == "audio-device-list":
            if value:
                self._playback_controls.update_audio_devices(value)
        elif name in ("hwdec", "hwdec-current", "deinterlace",
                      "audio-device", "audio-spdif", "speed",
                      "audio-delay", "sub-delay", "vid", "aid", "sid"):
            self._playback_controls.update_property(name, value)

    @pyqtSlot(str, object)
    def _on_property_for_playback(self, name: str, value) -> None:
        if name in ("time-pos", "duration") and value is not None:
            self._pb_log_on_change(name, value)   # proof hop — see _pb_log_on_change
        if name == "time-pos":
            self._playback_bar.update_position(value)
        elif name == "duration":
            self._playback_bar.update_duration(value)
            # Deterministic panel proof — one shot per open: the exact data the
            # LIVE panel rows decode from, logged as it arrives. Any row that is
            # blank in the UI but present here is provably a status_panel label
            # bug; a missing field here means the engine didn't send it.
            if not getattr(self, "_panel_proof_logged", False):
                self._panel_proof_logged = True
                _audit.info(
                    "panel-proof: dur=%.2f params=%r fmt=%r",
                    float(value or 0),
                    dict(self._engine.get_property("video-params", {}) or {}),
                    self._engine.get_property("video-format", ""))
        elif name == "pause":
            self._playback_bar.update_pause(value)
            if value and self._app_config.app_mode == "media_player":
                self._set_mode(AppMode.EDIT)  # show controls when paused
        elif name == "mute":
            self._playback_bar.update_mute(value)
        elif name == "volume":
            self._playback_bar.update_volume(value)

    # Deterministic proof for the playback bar chain (2026-09-23): every CHANGE
    # in time-pos/duration is logged on the property bus, so one run shows the
    # whole chain — engine → property → bar — in the audit log. A flat bar with
    # these lines present means the bar's own paint is the bug; absent lines mean
    # the data never left the engine.
    _pb_trace: dict = {}

    def _pb_log_on_change(self, key: str, value) -> None:
        prev = self._pb_trace.get(key)
        cur = float(value or 0)
        if prev is None or abs(prev - cur) > 0.5:
            self._pb_trace[key] = cur
            _audit.info(f"ui: {key} <- {cur:.2f}")

    @pyqtSlot(float)
    def _on_seek(self, seconds: float) -> None:
        duration = self._engine.get_property("duration", 0) or 0
        _audit.info(f"ui: seek -> {seconds:.2f}s  (dur={duration:.2f}s)")
        self._engine.seek(seconds)

    # ------------------------------------------------------------------
    # Profile / preset slots
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_dolby_vision_detected(self, dovi_profile: int) -> None:
        _audit.info(f"content: Dolby Vision detected  profile={dovi_profile}")
        """Auto-switch tone mapping when Dolby Vision content is detected.
        Also corrects the vf filter — DeckLink reports DV as SDR so gamma=bt.1886
        is set at capture start; we upgrade to pq here once mpv confirms DV."""
        # Guard: only switch tone mapping once per file
        cur_file = self._current_file or ""
        if getattr(self, "_dv_switched_for", "") == cur_file:
            return
        self._dv_switched_for = cur_file

        self._status_panel.set_dv_active(True)

        if self._profile.tone_mapping.algorithm not in ("st2094-10", "clip"):
            self._profile.tone_mapping.algorithm = "st2094-10"
            self._profile_manager.save(self._profile)
            if self._engine.is_playing():
                from ..core.live_settings import _apply_tone_mapping
                try:
                    _apply_tone_mapping(self._engine, self._profile)
                except Exception:
                    pass
            p_label = f"P{dovi_profile}" if dovi_profile >= 0 else ""
            self._status_bar.update_profile(
                f"{self._profile.name}  (DV{p_label}→st2094-10)")

    @pyqtSlot(str, object)
    def _on_profile_changed(self, group_key: str, profile: MpvProfile) -> None:
        _audit.info(f"setting: profile '{profile.name}' group '{group_key}' changed")
        self._profile = profile
        self._status_bar.update_profile(profile.name)
        self._control_bar.set_current_profile(profile.name)
        self._profile_manager.save(profile)

        if self._engine.is_playing():
            try:
                sent = apply_live_change(group_key, self._engine, profile)
                if not sent:
                    self._restart_needed = True
                    self._control_bar.set_restart_pending(True)  # amber hint for true RESTART settings
                else:
                    # When any setting changes while paused, trigger mpv frame-step 0
                    # (or redraw) so shaders re-render the exact paused frame instantly.
                    if self._engine.get_property("pause", False):
                        self._engine.command("frame-back-step")
                        self._engine.command("frame-step")
            except Exception:
                pass
            # Tone-mapping visualize needs the full viewport — switch to WATCH
            # so libplacebo's overlay isn't clipped by the settings/status panels
            if (group_key == "tone_mapping" and
                    profile.tone_mapping.tone_mapping_visualize and
                    self._mode == AppMode.EDIT):
                self._set_mode(AppMode.WATCH)
        else:
            self._restart_needed = False

    @pyqtSlot(str)
    def _on_profile_selected(self, name: str) -> None:
        if name == self._profile.name:
            return
        _audit.info(f"user: preset selected -> '{name}'")
        profile = self._profile_manager.load(name)
        self._profile = profile
        self._status_bar.update_profile(name)
        self._settings_panel.set_profile(profile)

    def _populate_profiles(self) -> None:
        names = self._profile_manager.list_profiles()
        self._control_bar.set_profiles(names, self._profile.name)
        self._control_bar.set_app_mode(self._app_config.app_mode)

    def _on_app_mode_changed_from_overlay(self, mode: str) -> None:
        """Mode switch from overlay 'Media Player' button — no confirmation needed."""
        self._force_mode_change(mode)

    @pyqtSlot(str)
    def _on_app_mode_changed(self, mode: str) -> None:
        if mode == self._app_config.app_mode:
            return
        _audit.info(f"user: app mode change requested  {self._app_config.app_mode} -> {mode}")

        # Only confirm if engine is genuinely playing stable content
        # (not during VP acquisition which has its own escape hatch)
        if self._engine.is_playing() and not self._vp_acquiring:
            from_label = "live capture" if self._app_config.app_mode == "video_processor" else "playback"
            to_label   = "Video Processor" if mode == "video_processor" else "Media Player"
            confirmed = ConfirmDialog.ask(
                "Switch Mode?",
                f"This will stop the current {from_label}.\nSwitch to {to_label}?",
                confirm_label="Switch",
                parent=self,
            )
            if not confirmed:
                self._control_bar.set_app_mode(self._app_config.app_mode)
                self._right_panel.set_app_mode(self._app_config.app_mode)
                return
            self._engine_quiesce()

        # Cancel any in-progress VP acquisition cleanly
        if self._vp_acquiring:
            self._vp_acquiring = False
            self._vp_retry_timer.stop(); self._vp_check_timer.stop()
            self._acquire_overlay.dismiss()

        self._app_config.app_mode = mode
        self._status_bar.set_app_mode(mode)
        self._control_bar.set_app_mode(mode)
        self._right_panel.set_app_mode(mode)
        self._status_panel.set_app_mode(mode)
        is_vp = mode == "video_processor"
        self._input_selector.setVisible(is_vp)
        if is_vp:
            self._input_selector.start_polling()
        else:
            self._input_selector.stop_polling()
        self._relayout()

        if mode == "media_player":
            self._set_mode(AppMode.IDLE)
            self._background.show_instant()
            self._media_library.show()
            self._media_library.raise_()
            self._status_bar.raise_()
            self._control_bar.raise_()
        else:
            # Video Processor — auto-start capture
            self._set_mode(AppMode.IDLE)
            self._media_library.hide()
            self._background.show_instant()
            self._start_vp_capture()

    def _force_mode_change(self, mode: str) -> None:
        """Switch mode without confirmation — used when context is unambiguous."""
        if mode == self._app_config.app_mode:
            return
        if self._engine.is_playing():
            self._engine_quiesce()
        # Reuse the common body
        self._vp_acquiring = False
        self._vp_retry_timer.stop(); self._vp_check_timer.stop()
        self._acquire_overlay.dismiss()
        self._app_config.app_mode = mode
        self._status_bar.set_app_mode(mode)
        self._control_bar.set_app_mode(mode)
        self._right_panel.set_app_mode(mode)
        self._status_panel.set_app_mode(mode)
        is_vp = mode == "video_processor"
        self._input_selector.setVisible(is_vp)
        if is_vp:
            self._input_selector.start_polling()
        else:
            self._input_selector.stop_polling()
        self._relayout()
        if mode == "media_player":
            self._set_mode(AppMode.IDLE)
            self._background.show_instant()
            self._media_library.show()
            self._media_library.raise_()
            self._status_bar.raise_()
            self._control_bar.raise_()
        else:
            self._set_mode(AppMode.IDLE)
            self._media_library.hide()
            self._background.show_instant()
            self._start_vp_capture()

    # ------------------------------------------------------------------
    # Video Processor — capture acquisition with retry
    # ------------------------------------------------------------------

    def _start_vp_capture(self) -> None:
        """Reinitialise engine and begin capture acquisition."""
        from ..core.mpv_engine import _setup_libmpv_path
        _setup_libmpv_path(self._app_config.mpv_executable)

        self._vp_retry_count = 0
        self._vp_acquiring = True
        device = (self._app_config.active_input_url or self._profile.input.device)
        _audit.info(f"capture: starting acquisition  device={device}")
        self._profile.input.device = device

        self._background.show_instant()
        self._acquire_overlay.start_acquiring(device, _VP_MAX_RETRIES)
        self._detected_dv = False  # reset on each capture attempt
        self._dl_blink_seen = False  # a fresh acquisition is itself the recovery

        # S3 engine: lifecycle is internal (self-healing monitor -> ops-queue
        # executor). NEVER tear down here — the executor owns the graph; a
        # synchronous teardown while it is mid-build deadlocks the UI thread
        # (observed 2026-09-15: acquire overlay froze in s3_shutdown).
        # if self._engine._mpv: self._engine.shutdown()

        self._dl_monitor._device = self._profile.input.device
        dl_opened = self._dl_monitor.start()
        if dl_opened:
            # Read the signal snapshot exactly as the 26th (bc8b985) build did —
            # no artificial lock-wait: the retry path re-queries fresh on every
            # attempt, and mpv's own decklink open is what drives card lock-in.
            signal_info = self._dl_monitor.get_signal_info()
            if signal_info:
                vf = signal_info.build_vf_filter()
                self._detected_vf = vf if vf else ""
                _audit.info(f"capture: DeckLink signal_info={signal_info!r}  vf={self._detected_vf!r}")
            else:
                self._detected_vf = None
                _audit.info("capture: DeckLink opened but get_signal_info returned None")
        else:
            _audit.warning("capture: DeckLink monitor failed to open")
            self._detected_vf = None

        self._viewport.show()
        self._viewport.raise_()
        self._viewport.winId()
        wid = self._viewport.hwnd()
        _audit.info("capture: step — viewport ready (wid=%s)", wid)
        try:
            vp_startup = _vp_startup_opts(self._profile,
                                          signal_info=self._dl_monitor.get_signal_info()
                                          if dl_opened else None)
            _audit.info("capture: step — startup opts built: %r", vp_startup)
        except BaseException as e:
            _audit.exception("capture: _vp_startup_opts RAISED: %r", e)
            self._acquire_overlay.show_failed()
            return
        _audit.info("capture: step — entering engine.initialise")
        try:
            self._engine.initialise(self._app_config.mpv_executable, wid=wid,
                                    startup_opts=vp_startup)
            _audit.info("capture: step — engine initialised ok")
        except Exception:
            _log.exception("capture: engine initialise RAISED — acquisition aborts")
            self._acquire_overlay.show_failed()
            return

        if not self._engine._mpv:
            _audit.warning("capture: engine initialise returned no _mpv")
            self._acquire_overlay.show_failed()
            return

        for prop in _STATUS_PROPS + _PLAYBACK_PROPS:
            self._engine.observe(prop)
        _audit.info("capture: step — properties observed")

        # Seed _vf_override in status panel NOW — before mpv emits video-params —
        # so the colorspace/transfer rows show DeckLink values, not raw stream headers.
        self._refresh_capture_status()
        _audit.info("capture: step — capture status refreshed; scheduling retry")

        QTimer.singleShot(200, self._vp_retry_attempt)

    @pyqtSlot()
    def _vp_retry_attempt(self) -> None:
        self._vp_retry_count += 1
        _audit.info(f"capture: attempt {self._vp_retry_count}/{_VP_MAX_RETRIES}  url={self._profile.input.device}")
        # Reset to spinner state — hides any failure buttons from previous attempt
        self._acquire_overlay.reset_for_retry()
        self._acquire_overlay.update_attempt(self._vp_retry_count, _VP_MAX_RETRIES)

        # Re-query DeckLink hardware right before playing — signal may have
        # changed since _start_vp_capture (e.g. Apple TV SDR→HDR negotiation)
        if self._dl_monitor._opened:
            fresh = self._dl_monitor.get_signal_info()
            if fresh:
                vf = fresh.build_vf_filter()
                self._detected_vf = vf if vf else ""

        # Build startup args — always use auto-detected vf over preset HDR override
        args = build_mpv_args(self._profile, "", wid=0)
        args = [a for a in args if not a.startswith("--vf=")]
        if self._detected_vf:   # non-empty string = HDR detected, apply filter
            args.insert(0, f"--vf={self._detected_vf}")
        url = self._profile.input.device

        # Apply vf filter chain before playing (structural option — the
        # generic arg-parsing below deliberately skips "vf", so it must be
        # set explicitly or the detected HDR/SDR filter never reaches mpv)
        vf_arg = next((a[5:] for a in args if a.startswith("--vf=")), None)
        self._engine.set_property("vf", vf_arg or "")

        self._apply_serialiser_args(args)
        # --ml-acq-cutover is VO-scoped — apply via set_option_string (property
        # set would silently no-op before the VO exists).
        if self._profile.performance.ml_acq_cutover_ms > 0:
            self._engine.set_vo_option(
                "ml-acq-cutover", self._profile.performance.ml_acq_cutover_ms)
        _audit.info(f"capture: mpv args = {args}")
        self._engine.play(url)

        # Cancel any pending check from previous attempt, then schedule new one
        self._vp_check_timer.stop()
        self._vp_check_timer.start(1500)

    def _vp_acquire_succeeded(self) -> None:
        """Acquisition is over: dismiss the overlay and go to WATCH.

        Idempotent, and driven purely by "the engine is playing" — so it does not
        matter whether the PLAYING transition was observed, nor whether it arrived
        before or after _vp_acquiring was set.

        This exists because the confirmation used to live in exactly one place:
        _vp_confirm_playing, reached ONLY from the EngineState.PLAYING transition
        via a single 600 ms shot. Meanwhile the 1500 ms safety net returned early
        whenever is_playing() was true, deferring to that same handler. So when the
        transition was missed — it fired before _vp_acquiring was set, the state was
        already PLAYING from the previous attempt so no transition fired at all, or
        is_playing() was momentarily false at the 600 ms mark — nothing ever
        confirmed, and the "Attempt 1 of 10" spinner kept turning over a working
        picture. The "1 of" was the tell: attempt one had succeeded.
        """
        if not self._vp_acquiring:
            return
        _audit.info(f"capture: acquisition confirmed  device={self._profile.input.device}  vf={self._detected_vf!r}")
        self._vp_acquiring = False
        self._acquire_overlay.dismiss()
        self._vp_retry_timer.stop(); self._vp_check_timer.stop()
        self._vp_retry_count = 0
        self._set_mode(AppMode.WATCH)
        if self._app_config.app_mode == "video_processor":
            self._signal_monitor.start()
            # video-params already fired (it triggered PLAYING).
            # Seed the monitor so it transitions STARTING→ACTIVE immediately
            # rather than waiting up to loss_timeout seconds for the next event.
            vp = self._engine.get_property("video-params")
            if vp is not None:
                self._signal_monitor.on_property_changed("video-params", vp)
            # dl_monitor is already open from _start_vp_capture — do NOT
            # call start() again; it resets poll state and spuriously fires
            # dynamic_range_changed which triggers an unnecessary restart.
            self._refresh_capture_status()

    def _delivering(self) -> bool:
        """True when frames have arrived recently — the acquisition success test.

        `is_playing()` alone says only that the DirectShow graph is in Run state, and
        that stays true through a delivery stall. It is also why the SignalMonitor
        cannot see a stall: its `time-pos` heartbeat comes from
        `IMediaSeeking::GetPositions` (MpcPlayer::UpdateSnapshot), i.e. the graph's
        stream position, which the reference clock keeps advancing whether or not
        frames are being delivered.

        Requiring the frame counter to be moving is the difference between "the graph
        is running" and "a picture is arriving". The engine has its own watchdog for
        repairing a stall once it has happened; this is what stops the UI declaring
        WATCH over a picture that never arrived, which is what leaves nothing left
        able to recover it.

        The window is 3 s, deliberately: a movie->menu transition stops delivering
        for a few seconds while the source renegotiates, and a shorter window turns
        that into a failed attempt. A false failure is self-correcting here — the
        retry path re-checks, and by attempt 2 or 3 the transition is over and frames
        are moving — but it costs an overlay the user should not have to see.
        """
        return (time.monotonic() - self._recv_last_change_ts) < 3.0

    def _vp_confirm_playing(self) -> None:
        """Called 600ms after PLAYING — confirms signal is genuinely stable."""
        if not self._vp_acquiring:
            return
        # Delivery, not just state — see _delivering().
        if self._engine.is_playing() and self._delivering():
            self._vp_acquire_succeeded()
        else:
            # A single 600 ms shot is not a decision. The engine can still be
            # settling here (ENDED fires briefly on a failing DeckLink open), and
            # returning without rescheduling is what used to strand the overlay.
            # Hand it to the safety net, which now also confirms on success.
            self._vp_check_timer.start(1500)

    def _refresh_capture_status(self) -> None:
        """Push the latest DeckLink-detected signal info to the status panel.
        Called once capture is confirmed, and again whenever the hardware
        reports a lock/format change.
        Always derives vf from the current hardware read so the panel and
        what mpv is told are always in sync — never stale from a prior capture."""
        signal_info = (self._dl_monitor.get_signal_info()
                       if self._dl_monitor._opened else None)
        if signal_info is not None:
            fresh_vf = signal_info.build_vf_filter()
            if fresh_vf != self._detected_vf:
                self._detected_vf = fresh_vf
                self._engine.set_property("vf", fresh_vf or "")
        self._status_panel.update_capture_info(
            self._profile.input.device,
            signal_info,
            self._detected_vf or "",
        )

    def _vp_check_result(self) -> None:
        # Delivery, not just state — see _delivering(). A graph that is running but
        # not delivering falls through to the retry path below, which is the point:
        # declaring WATCH over a dead picture leaves nothing able to recover it.
        if self._engine.is_playing() and self._delivering():
            # Confirm here rather than returning to wait for the PLAYING transition.
            # This is the safety net: if it declines to act on the one condition that
            # means success, there is no other path left, and the overlay stays up
            # over a working picture (see _vp_acquire_succeeded).
            self._vp_acquire_succeeded()
            return
        # Still not playing — stop quietly and retry or fail
        try:
            self._engine._mpv.stop()
        except Exception:
            pass
        if self._vp_retry_count < _VP_MAX_RETRIES:
            self._vp_retry_timer.start(_VP_RETRY_DELAY)
        else:
            self._vp_acquiring = False
            self._vp_retry_timer.stop()
            self._vp_check_timer.stop()
            self._acquire_overlay.show_failed()

    def _vp_restart_capture(self) -> None:
        """Graceful restart — stop then re-acquire. Called by restart button or signal loss."""
        _audit.info("capture: restart initiated")
        self._vp_retry_timer.stop()
        self._vp_check_timer.stop()
        self._dl_monitor.stop()
        self._signal_monitor.stop()
        if self._engine.is_playing():
            self._engine.stop()
        self._set_mode(AppMode.IDLE)
        self._background.show_instant()
        QTimer.singleShot(300, self._start_vp_capture)

    @pyqtSlot()
    def _open_preset_manager(self) -> None:
        from .preset_manager_dialog import PresetManagerDialog
        dlg = PresetManagerDialog(self._profile_manager, self._profile.name, self)
        dlg.preset_activated.connect(self._on_preset_loaded)
        dlg.exec()
        self._populate_profiles()

    @pyqtSlot(object)
    def _on_preset_loaded(self, profile: MpvProfile) -> None:
        self._profile = profile
        self._status_bar.update_profile(profile.name)
        self._control_bar.set_current_profile(profile.name)
        self._settings_panel.set_profile(profile)
        self._status_panel.seed_configured_output(profile)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _decklink_raw_format(signal_info) -> int:
    """ffmpeg decklink `raw_format` index for the detected signal.

    Proven-safe mapping only — the DeckLink Quad HDMI Recorder + ffmpeg 7.0.2
    capture path is reliable with 8-bit 4:2:2 (uyvy422) and 10-bit 4:2:2 (v210).
    Selecting r210 (10-bit RGB 4:4:4) when the monitor reports RGB444 broke
    capture entirely (EnableVideoInput negotiation failed on the HTPC), so we
    deliberately DO NOT follow chroma here:
        0=auto (→ silently 8-bit, BAD)  1=8-bit YUV422 (uyvy422)
        2=10-bit YUV422 (v210)          (3/4/5 reserved — not used on this card)
    12-bit input falls back to 10-bit (no 12-bit entry in the ffmpeg 7.0.2 map).
    Chroma is reported for the LIVE panel only; RGB 4:4:4 sources are captured
    as 10-bit 4:2:2 until the Quad/ffmpeg path for r210 is proven.
    """
    if signal_info is None:
        return 2  # safe default: v210 10-bit 4:2:2
    depth = signal_info.pixel_depth or 8
    if depth >= 12:
        _log.warning("DeckLink source reports %d-bit — no 12-bit raw_format in "
                     "ffmpeg 7.0.2; capturing at 10-bit.", depth)
        depth = 10
    return 2 if depth >= 10 else 1


def _vp_startup_opts(profile, signal_info=None) -> dict:
    """
    Options that must be set at MPV() construction time for VP capture.
    libmpv ignores cache/demuxer/thread settings applied after init,
    so we pass them as kwargs to MpvEngine.initialise() → MPV(**kwargs).

    Reverted to the 2026-08-26 (bc8b985) proven-smooth VP setup. The latency
    chain added in 45cc321 (latency_mode=1, video_pts=wallclock, queue_size,
    raw_format, vd_lavc_threads, video_latency_hacks, untimed, video_sync=audio)
    coincided with UB820/DeckLink capture jitter on the HTPC. Testing this
    baseline first; `signal_info` accepted only for call-site compatibility.
    Without rtbufsize=2G the capture buffer overflows on high-bitrate HDR,
    causing mpv to emit ENDED immediately → wallpaper flash.
    python-mpv converts underscores to hyphens and booleans to yes/no.
    """
    import pathlib
    _home = pathlib.Path.home() / ".unplugged"
    _home.mkdir(exist_ok=True)

    p = profile.performance

    opts = {
        "audio": False,
        "cache": not p.no_cache,
        # NO demuxer/lavf options at construction — analyzeduration, probesize
        # and rtbufsize are applied at launch (build_mpv_args) exactly like the
        # proven-working direct command. Setting them here (esp. a large
        # rtbufsize or nonzero analyzeduration) delayed the first frame.
        "log_file": str(_home / "mpv_capture.log"),
        "d3d11_exclusive_fs": False,
    }
    if p.no_demuxer_thread:
        opts["demuxer_thread"] = False
    return opts


def _coerce(val: str):
    """Best-effort type coercion for CLI arg values."""
    if val in ("yes", "true"):
        return True
    if val in ("no", "false"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


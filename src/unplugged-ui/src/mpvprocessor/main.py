"""
Application entry point.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from .config.model import AppConfig
from .core.shader_manager import sync_shader_list
from .profiles.manager import ProfileManager
from .ui.main_window import MainWindow


def _config_dir() -> Path:
    base = Path.home() / ".unplugged"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _logs_dir() -> Path:
    d = _config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setup_logging() -> None:
    """Daily rotating log files in ~/.unplugged/logs/unplugged_YYYY-MM-DD.log.
    Retains the last 30 days. All unplugged.* loggers write here at DEBUG level."""
    import logging
    from logging.handlers import TimedRotatingFileHandler
    import datetime

    logs_dir = _logs_dir()
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_path = logs_dir / f"unplugged_{today}.log"

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Daily rotating handler — keeps 30 days
    rotating = TimedRotatingFileHandler(
        str(logs_dir / "unplugged.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    rotating.setFormatter(fmt)
    rotating.suffix = "%Y-%m-%d"

    # Also write today's named file directly (easy to share by date)
    daily = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
    daily.setFormatter(fmt)

    logger = logging.getLogger("unplugged")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(rotating)
    logger.addHandler(daily)

    # Keep legacy app.log symlink/copy for backwards compat
    legacy = _config_dir() / "app.log"
    legacy_handler = logging.FileHandler(str(legacy), mode="a", encoding="utf-8")
    legacy_handler.setFormatter(fmt)
    logger.addHandler(legacy_handler)

    _purge_old_logs(logs_dir, keep=30)


def _purge_old_logs(logs_dir: Path, keep: int) -> None:
    """Delete daily log files older than `keep` days."""
    import datetime
    cutoff = datetime.date.today().toordinal() - keep
    for f in sorted(logs_dir.glob("unplugged_*.log")):
        try:
            date_str = f.stem.replace("unplugged_", "")
            d = datetime.date.fromisoformat(date_str)
            if d.toordinal() < cutoff:
                f.unlink()
        except Exception:
            pass


def _install_exception_hook() -> None:
    """Write unhandled exceptions to a log file so crashes are diagnosable."""
    import traceback
    from pathlib import Path
    log = Path.home() / ".unplugged" / "crash.log"

    def hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.parent.mkdir(exist_ok=True)
        with open(log, "a") as f:
            import datetime
            f.write(f"\n--- {datetime.datetime.now()} ---\n{msg}")
        # Also print to stderr
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook

    # Catch exceptions thrown inside Qt slots
    from PyQt6.QtCore import pyqtSignal
    import PyQt6.QtCore as QtCore
    old_handler = QtCore.qInstallMessageHandler
    def qt_msg_handler(mode, context, message):
        if "Traceback" in message or "Error" in message:
            with open(log, "a") as f:
                import datetime
                f.write(f"\n--- Qt msg {datetime.datetime.now()} ---\n{message}\n")
    try:
        QtCore.qInstallMessageHandler(qt_msg_handler)
    except Exception:
        pass


def _setup_mpv_path() -> None:
    """Register DLL directories so ctypes can find libmpv-2.dll and its dependencies."""
    dirs: list[str] = []

    # When frozen by PyInstaller, _internal/ has all bundled DLLs
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        dirs.append(meipass)
    else:
        # Dev: resolve from AppConfig default (points to c:/Code/mpv/dist)
        from .config.model import AppConfig
        cfg = AppConfig()
        dirs.append(str(Path(cfg.mpv_executable).parent))

    current_path = os.environ.get("PATH", "")
    for d in dirs:
        if d not in current_path.split(os.pathsep):
            os.environ["PATH"] = d + os.pathsep + current_path
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(d)
            except OSError:
                pass


def main() -> None:
    # Single instance: two processes can't both own the DeckLink card nor
    # register the Up-arrow global hotkey (RegisterHotKey is process-global).
    # A stray second launch silently exits instead of fighting over both.
    import ctypes
    _kernel32 = ctypes.windll.kernel32
    _s3_mutex = _kernel32.CreateMutexW(None, False, "UnpluggedS3Instance")
    if _kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        sys.stderr.write("unplugged already running - exiting second instance\n")
        sys.exit(0)

    # TASKBAR IDENTITY. Without an explicit AppUserModelID, Windows groups this
    # process under whatever host identity it infers (a PyInstaller bootloader) and
    # shows THAT icon on the taskbar -- generic -- even though the EXE carries ours
    # (unplugged.spec icon=...). The ID is what makes the taskbar button, its icon
    # and jump-list grouping belong to this app. Must be set before any window is
    # created, hence here at process start rather than next to QApplication.
    # Stable string: changing it orphans the old grouping in the taskbar cache.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "unplugged.player.1")
    except Exception:   # noqa: BLE001 - cosmetic only; never fatal at startup
        pass

    import faulthandler
    config_dir = _config_dir()  # ensures ~/.unplugged/ exists
    _fault_log = open(str(config_dir / "segfault.log"), "a")
    faulthandler.enable(file=_fault_log, all_threads=True)

    _setup_logging()
    import logging
    import datetime
    import platform
    log = logging.getLogger("unplugged")
    log.info("=" * 72)
    log.info(f"  unplugged  —  session started  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Python   : {sys.version}")
    log.info(f"  Platform : {platform.platform()}")
    log.info(f"  CWD      : {os.getcwd()}")
    log.info(f"  Exe      : {sys.executable}")
    log.info("=" * 72)
    _setup_mpv_path()
    _install_exception_hook()
    app = QApplication(sys.argv)
    app.setApplicationName("unplugged")
    app.setOrganizationName("unplugged")

    # Window icon for every top-level this app creates (main window, chrome,
    # splash, dialogs): Qt falls back to the application icon when a window has
    # none of its own, and the taskbar/alt-tab/title-bar icon comes from the
    # window first, the AppUserModelID second. The EXE resource alone is not
    # enough on either path. Resolved through assets.py so frozen and dev runs
    # find the same file.
    try:
        from PyQt6.QtGui import QIcon
        from .assets import asset
        _icon_path = asset("brand", "ico", "unplugged.ico")
        if _icon_path.exists():
            app.setWindowIcon(QIcon(str(_icon_path)))
        else:
            log.warning("window icon missing: %s", _icon_path)
    except Exception as e:   # noqa: BLE001 - cosmetic only
        log.warning("window icon not applied: %s", e)

    # Apply global font and base stylesheet
    from .ui.theme import app_font, BASE_QSS
    app.setFont(app_font())
    app.setStyleSheet(BASE_QSS)

    config_path = config_dir / "app_config.json"

    app_config = AppConfig.load(config_path)
    app_config.profiles_dir = str(config_dir / "profiles")

    profile_manager = ProfileManager(Path(app_config.profiles_dir))
    active_profile = profile_manager.load(app_config.active_profile)

    # Sync shader list from disk on startup
    sync_shader_list(active_profile.shaders, app_config.mpv_executable)

    window = MainWindow(app_config, active_profile, profile_manager)
    # showMaximized is called inside _setup_window; don't call show() here

    exit_code = app.exec()

    app_config.save(config_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


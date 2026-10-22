# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Unplugged UI (src/unplugged-ui, inside mpc-hc).

Bundles the app plus the native pieces the S3 ingest path needs.

**The mpv stack is deliberately not bundled.** libmpv-2.dll, libplacebo,
mpv.exe and ~130 ffmpeg DLLs were well over 200 MB of the old build's 707 MB,
and the engine layer is s3engine.dll now — `main_window` aliases
`S3Engine as MpvEngine`. The only `import mpv` left is inside
`MpvEngine.initialise`, which nothing calls; it is excluded explicitly below so
it can never creep back in.

**MPCVR and the LAV filters are also not here.** They register by absolute
path, and MPCVR resolves its ML models from the directory its own `.ax` sits
in, so the Inno Setup installer places them under {app}.
"""
from pathlib import Path
import runpy
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)

block_cipher = None

_HERE = Path(SPECPATH).resolve()          # src/unplugged-ui
_SRC = _HERE / 'src'
_ASSETS = _HERE / 'assets'
_REPO = _HERE.parents[1]                  # the mpc-hc repo root
_VERSION = runpy.run_path(str(_SRC / 'mpvprocessor' / '__init__.py'))['__version__']
_VERSION_PARTS = tuple(int(part) for part in _VERSION.split('.')) + (0,)
_VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_VERSION_PARTS, prodvers=_VERSION_PARTS,
        mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0),
    ),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('FileDescription', 'Unplugged'),
            StringStruct('FileVersion', _VERSION),
            StringStruct('OriginalFilename', 'Unplugged.exe'),
            StringStruct('ProductName', 'Unplugged'),
            StringStruct('ProductVersion', _VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)

# Native DLLs that must ride inside _internal/ beside the exe.
binaries = []
_s3engine = _REPO / 'tools' / 's3engine' / 's3engine.dll'
if _s3engine.exists():
    binaries.append((str(_s3engine), '.'))
else:
    import warnings
    warnings.warn(f"{_s3engine} missing - run tools/s3engine/build_s3engine.bat", stacklevel=1)

_dl_monitor = _ASSETS / 'decklink_monitor.dll'
if _dl_monitor.exists():
    binaries.append((str(_dl_monitor), '.'))

a = Analysis(
    ['launch.py'],
    pathex=[str(_SRC)],
    binaries=binaries,
    datas=[
        (str(_SRC / 'mpvprocessor'), 'mpvprocessor'),
        # one tree, so mpvprocessor/assets.py resolves under _internal/assets/
        (str(_ASSETS), 'assets'),
    ],
    hiddenimports=[
        'mpvprocessor',
        'mpvprocessor.main',
        'mpvprocessor.assets',
        'mpvprocessor.ui.main_window',
        'mpvprocessor.ui.theme',
        'mpvprocessor.ui.settings_panel',
        'mpvprocessor.ui.playback_controls',
        'mpvprocessor.ui.status_panel',
        'mpvprocessor.ui.acquire_overlay',
        'mpvprocessor.ui.splash_screen',
        'mpvprocessor.ui.web_animation',
        'mpvprocessor.ui.media_library_panel',
        'mpvprocessor.ui.control_bar',
        'mpvprocessor.ui.status_bar',
        'mpvprocessor.ui.background_widget',
        'mpvprocessor.ui.right_panel',
        'mpvprocessor.ui.first_run_dialog',
        'mpvprocessor.ui.input_selector',
        'mpvprocessor.ui.input_config_panel',
        'mpvprocessor.ui.focus_style',
        'mpvprocessor.ui.mode_selector',
        'mpvprocessor.ui.collapsible_group',
        'mpvprocessor.ui.confirm_dialog',
        'mpvprocessor.ui.playback_bar',
        'mpvprocessor.ui.mpv_viewport',
        'mpvprocessor.ui.shader_panel',
        'mpvprocessor.ui.settings_rows',
        # the s3_shell rail + the chrome window it lives in
        'mpvprocessor.ui.s3shell_panel',
        'mpvprocessor.ui.settings_window',
        'mpvprocessor.core.s3_engine',
        'mpvprocessor.core.calibrate',
        'mpvprocessor.core.altf4_hook',
        'mpvprocessor.core.live_settings',
        'mpvprocessor.core.decklink_monitor',
        'mpvprocessor.core.hotkey',
        'mpvprocessor.core.signal_monitor',
        'mpvprocessor.core.process_manager',
        'mpvprocessor.config.model',
        'mpvprocessor.config.serializer',
        'mpvprocessor.config.conf_importer',
        'mpvprocessor.profiles.manager',
        'mpvprocessor.media.scanner',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtNetwork',
        'ctypes',
        'json',
        'pathlib',
        'dataclasses',
        'logging',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_dlls.py'],
    # 'mpv' is excluded on purpose: the bundle has no libmpv and no ffmpeg, and
    # nothing on the S3 path calls MpvEngine.initialise. See the module docstring.
    # 'email' and 'http' stay IN: urllib.request (media library posters, OMDb) needs both.
    excludes=['mpv', 'tkinter', 'unittest', 'xml', 'pydoc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# QtWebEngine ships its DevTools inspector data as .pak resources — 72 MB for the
# debug variant alone, 83 MB together. The app only ever renders the splash HTML
# in a QWebEngineView and never opens DevTools, so drop them.
_DEVTOOLS = ('qtwebengine_devtools_resources.pak',
             'qtwebengine_devtools_resources.debug.pak')
_dropped = [d for d in a.datas if str(d[0]).endswith(_DEVTOOLS)]
a.datas = [d for d in a.datas if d not in _dropped]
if _dropped:
    print(f"[spec] dropped {len(_dropped)} WebEngine DevTools resource(s)")

# `src/mpvprocessor` is bundled wholesale as data, so any native DLL sitting in
# the source tree ships inside the package. A stale core/s3engine.dll there wins
# over the freshly built one staged into _internal/ and silently downgrades the
# engine — drop every .dll/.pyd from the package tree so the staged binaries are
# the only ones that can be loaded.
_STALE = [d for d in a.datas
          if str(d[0]).startswith('mpvprocessor')
          and str(d[0]).lower().endswith(('.dll', '.pyd'))]
a.datas = [d for d in a.datas if d not in _STALE]
if _STALE:
    print(f"[spec] dropped {len(_STALE)} stale native(s) from the package tree: "
          f"{[str(d[0]) for d in _STALE]}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Unplugged',
    version=_VERSION_INFO,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_ASSETS / 'brand' / 'ico' / 'unplugged.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Unplugged',
)
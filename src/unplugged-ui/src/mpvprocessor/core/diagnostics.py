"""
Field diagnostics: what a support request needs to know about the user's PC.

* health_check()       - is the installation intact (bundled filters, engine)?
* codec_pack_report()  - how Windows would resolve .mkv/.mp4 and our filter CLSIDs,
                         and which codec packs are installed (the K-Lite failure class).
* environment_report() - GPU/driver, displays and their HDR state, bundled binary
                         versions and hashes.
* collect_zip()        - one file the user can send: logs, config, reports, dumps.

Everything here is read-only and must never raise: diagnostics that crash the app
are worse than none. Each probe catches its own failure and reports it as text.
"""

from __future__ import annotations

import ctypes
import datetime
import hashlib
import logging
import os
import platform
import sys
import zipfile
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("unplugged.diagnostics")

LAV_CLSIDS = {
    "LAV Splitter Source": "{B98D13E7-55DB-4385-A33D-09FD1BA26338}",
    "LAV Splitter":        "{171252A0-8820-4AFE-9DF8-5C92B2D66B04}",
    "LAV Video":           "{EE30215D-164F-4A92-A4EB-9D4C13390F9F}",
    "LAV Audio":           "{E8E73B6B-4CB3-44A4-BE99-4F7BCB96E491}",
}
_ASYNC_READER = "{E436EBB5-524F-11CE-9F53-0020AF0BA770}"
_MEDIATYPE_STREAM = "{e436eb83-524f-11ce-9f53-0020af0ba770}"

# The files the engine loads directly from <install>\filters. Glob patterns, so a
# LAV/ffmpeg version bump does not turn into a false "installation damaged".
REQUIRED_FILTER_FILES = (
    "LAVSplitter.ax", "LAVVideo.ax", "LAVAudio.ax", "unplugged_vr.ax",
    "LAVFilters.Dependencies.manifest", "onnxruntime.dll",
    "avcodec-lav-*.dll", "avformat-lav-*.dll", "avutil-lav-*.dll",
    "swresample-lav-*.dll", "swscale-lav-*.dll",
)
_HASHED_BINARIES = ("LAVSplitter.ax", "LAVVideo.ax", "LAVAudio.ax", "unplugged_vr.ax",
                    "DeckLinkSource.ax")

_CODEC_PACK_WORDS = ("k-lite", "lav filters", "combined community codec", "cccp",
                     "shark007", "ffdshow", "haali", "madvr", "media player classic",
                     "mpc-hc", "mpc-be", "xvid", "divx", "codec")


def app_version() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:   # noqa: BLE001
        return "?"


def install_dir() -> Path | None:
    """The installed app folder, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def logs_dir() -> Path:
    return Path.home() / ".unplugged" / "logs"


def dumps_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Unplugged" / "CrashDumps"


def _safe(fn, *a, **kw) -> str:
    try:
        return fn(*a, **kw)
    except Exception as e:   # noqa: BLE001 - a probe failure is itself a finding
        return f"  (probe failed: {type(e).__name__}: {e})\n"


# ── installation health ──────────────────────────────────────────────────────

def health_check() -> list[str]:
    """Problems with the installation, as user-readable lines. Empty = healthy.

    Only meaningful for an installed (frozen) build; a source run has no filters dir.
    """
    problems: list[str] = []
    root = install_dir()
    if root is None:
        return problems
    fdir = root / "filters"
    if not fdir.is_dir():
        return [f"the filters folder is missing ({fdir})"]
    for pattern in REQUIRED_FILTER_FILES:
        matches = sorted(fdir.glob(pattern))
        if not matches:
            problems.append(f"missing {pattern}")
            continue
        for m in matches:
            try:
                with open(m, "rb") as fh:
                    head = fh.read(2)
                if m.suffix.lower() in (".ax", ".dll") and head != b"MZ":
                    problems.append(f"damaged {m.name}")
                elif m.stat().st_size == 0:
                    problems.append(f"empty {m.name}")
            except OSError as e:
                problems.append(f"unreadable {m.name} ({e.strerror or e})")
    return problems


# ── binaries: version + hash ────────────────────────────────────────────────

def file_version(path: Path) -> str:
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return "-"
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return "-"
        p = ctypes.c_void_p()
        n = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(n)) or n.value < 52:
            return "-"
        ffi = ctypes.cast(p, ctypes.POINTER(wintypes.DWORD * 13)).contents
        ms, ls = ffi[2], ffi[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:   # noqa: BLE001
        return "-"


def _sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _describe_binary(path: Path) -> str:
    try:
        st = path.stat()
        ts = datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        return (f"  {path.name:<22} v{file_version(path):<14} {st.st_size:>10} B  "
                f"{ts}  sha256:{_sha256_short(path)}\n")
    except OSError as e:
        return f"  {path.name:<22} unreadable: {e}\n"


def _binaries_section(engine_dll: str | None) -> str:
    out = []
    if engine_dll:
        out.append(_describe_binary(Path(engine_dll)))
    root = install_dir()
    if root is not None:
        out.append(_describe_binary(Path(sys.executable)))
        for name in _HASHED_BINARIES:
            p = root / "filters" / name
            out.append(_describe_binary(p) if p.exists() else f"  {name:<22} (not present)\n")
    else:
        out.append("  (source run - no bundled filters)\n")
    return "".join(out)


# ── registry helpers ────────────────────────────────────────────────────────

def _reg_value(root, subkey: str, name: str = "", view: int = 0):
    import winreg
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_subkeys(root, subkey: str, view: int = 0) -> list[str]:
    import winreg
    out = []
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def _filter_name(clsid: str) -> str:
    import winreg
    if not clsid:
        return "-"
    name = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}")
    return f"{clsid} ({name})" if name else clsid


# ── codec packs / DirectShow resolution ─────────────────────────────────────

def codec_pack_report() -> str:
    import winreg
    out = ["Extension -> source filter (HKCR, what Windows' AddSourceFilter would use):\n"]
    for ext in (".mkv", ".mp4"):
        merged = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"Media Type\Extensions\{ext}",
                            "Source Filter")
        user = _reg_value(winreg.HKEY_CURRENT_USER,
                          rf"Software\Classes\Media Type\Extensions\{ext}", "Source Filter")
        line = f"  {ext}: {_filter_name(merged) if merged else '(none)'}"
        if user:
            line += f"  [per-user override: {user}]"
        out.append(line + "\n")

    out.append("Check-byte source overrides (non-default only):\n")
    n = 0
    base = rf"Media Type\{_MEDIATYPE_STREAM}"
    for sub in _reg_subkeys(winreg.HKEY_CLASSES_ROOT, base):
        src = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"{base}\{sub}", "Source Filter")
        if src and src.upper() != _ASYNC_READER:
            out.append(f"  {sub} -> {_filter_name(src)}\n")
            n += 1
            if n >= 40:
                out.append("  ...\n")
                break
    if n == 0:
        out.append("  (none)\n")

    out.append("LAV CLSIDs as registered on this PC (Unplugged loads its own copies directly):\n")
    for name, clsid in LAV_CLSIDS.items():
        path = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32")
        user = _reg_value(winreg.HKEY_CURRENT_USER,
                          rf"Software\Classes\CLSID\{clsid}\InprocServer32")
        line = f"  {name:<20} {path or '(not registered)'}"
        if path and not Path(os.path.expandvars(path)).exists():
            line += "  [FILE MISSING]"
        if user:
            line += f"  [per-user override: {user}]"
        out.append(line + "\n")

    out.append("Installed codec packs / players:\n")
    found = set()
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
         winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
         winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    )
    for root, key, view in roots:
        for sub in _reg_subkeys(root, key, view):
            dn = _reg_value(root, rf"{key}\{sub}", "DisplayName", view)
            if not isinstance(dn, str):
                continue
            low = dn.lower()
            if "unplugged" in low or not any(w in low for w in _CODEC_PACK_WORDS):
                continue
            dv = _reg_value(root, rf"{key}\{sub}", "DisplayVersion", view) or ""
            found.add(f"{dn} {dv}".strip())
    out += [f"  {x}\n" for x in sorted(found)] or ["  (none detected)\n"]
    return "".join(out)


def codec_pack_summary() -> str:
    """One line for the session log: is anything likely to interfere?"""
    import winreg
    parts = []
    for ext in (".mkv", ".mp4"):
        src = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"Media Type\Extensions\{ext}",
                         "Source Filter")
        parts.append(f"{ext}={'default' if not src else src}")
    lav = _reg_value(winreg.HKEY_CLASSES_ROOT,
                     rf"CLSID\{LAV_CLSIDS['LAV Splitter Source']}\InprocServer32")
    parts.append(f"LAVSplitterSource={lav or 'unregistered'}")
    return "  ".join(parts)


# ── GPU and displays ────────────────────────────────────────────────────────

def _gpu_section() -> str:
    import winreg
    cls = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    out = []
    for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, cls):
        if not sub.isdigit():
            continue
        desc = _reg_value(winreg.HKEY_LOCAL_MACHINE, rf"{cls}\{sub}", "DriverDesc")
        if not desc:
            continue
        ver = _reg_value(winreg.HKEY_LOCAL_MACHINE, rf"{cls}\{sub}", "DriverVersion") or "?"
        date = _reg_value(winreg.HKEY_LOCAL_MACHINE, rf"{cls}\{sub}", "DriverDate") or "?"
        out.append(f"  {desc}  driver {ver} ({date})\n")
    return "".join(out) or "  (no display adapters found)\n"


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _PathSource(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", ctypes.c_uint32),
                ("modeInfoIdx", ctypes.c_uint32), ("statusFlags", ctypes.c_uint32)]


class _PathTarget(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", ctypes.c_uint32),
                ("modeInfoIdx", ctypes.c_uint32), ("outputTechnology", ctypes.c_uint32),
                ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshNum", ctypes.c_uint32), ("refreshDen", ctypes.c_uint32),
                ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class _PathInfo(ctypes.Structure):
    _fields_ = [("sourceInfo", _PathSource), ("targetInfo", _PathTarget),
                ("flags", ctypes.c_uint32)]


class _ModeInfo(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32),
                ("adapterId", _LUID), ("data", ctypes.c_ubyte * 48)]


class _Header(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32),
                ("adapterId", _LUID), ("id", ctypes.c_uint32)]


class _TargetName(ctypes.Structure):
    _fields_ = [("header", _Header), ("flags", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("edidManufactureId", ctypes.c_uint16),
                ("edidProductCodeId", ctypes.c_uint16), ("connectorInstance", ctypes.c_uint32),
                ("monitorFriendlyDeviceName", ctypes.c_wchar * 64),
                ("monitorDevicePath", ctypes.c_wchar * 128)]


class _AdvColor(ctypes.Structure):
    _fields_ = [("header", _Header), ("value", ctypes.c_uint32),
                ("colorEncoding", ctypes.c_uint32), ("bitsPerColorChannel", ctypes.c_uint32)]


class _SdrWhite(ctypes.Structure):
    _fields_ = [("header", _Header), ("SDRWhiteLevel", wintypes.ULONG)]


class _SourceName(ctypes.Structure):
    _fields_ = [("header", _Header), ("viewGdiDeviceName", ctypes.c_wchar * 32)]


def _displays_section() -> str:
    u32 = ctypes.windll.user32
    QDC_ONLY_ACTIVE_PATHS = 2
    npaths, nmodes = ctypes.c_uint32(), ctypes.c_uint32()
    if u32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(npaths),
                                       ctypes.byref(nmodes)) != 0:
        return "  (display query failed)\n"
    paths = (_PathInfo * npaths.value)()
    modes = (_ModeInfo * nmodes.value)()
    if u32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(npaths), paths,
                              ctypes.byref(nmodes), modes, None) != 0:
        return "  (display query failed)\n"
    out = []
    for i in range(npaths.value):
        t = paths[i].targetInfo
        s = paths[i].sourceInfo

        name = _TargetName()
        name.header.type, name.header.size = 2, ctypes.sizeof(_TargetName)
        name.header.adapterId, name.header.id = t.adapterId, t.id
        friendly = (name.monitorFriendlyDeviceName
                    if u32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0 else "")

        src = _SourceName()
        src.header.type, src.header.size = 1, ctypes.sizeof(_SourceName)
        src.header.adapterId, src.header.id = s.adapterId, s.id
        gdi = src.viewGdiDeviceName if u32.DisplayConfigGetDeviceInfo(ctypes.byref(src)) == 0 else ""

        adv = _AdvColor()
        adv.header.type, adv.header.size = 9, ctypes.sizeof(_AdvColor)
        adv.header.adapterId, adv.header.id = t.adapterId, t.id
        if u32.DisplayConfigGetDeviceInfo(ctypes.byref(adv)) == 0:
            supported, enabled = bool(adv.value & 1), bool(adv.value & 2)
            hdr = (f"HDR {'ON' if enabled else 'off'}"
                   f"{'' if supported else ' (unsupported)'}, {adv.bitsPerColorChannel} bpc")
        else:
            hdr = "HDR unknown"

        white = _SdrWhite()
        white.header.type, white.header.size = 11, ctypes.sizeof(_SdrWhite)
        white.header.adapterId, white.header.id = t.adapterId, t.id
        sdr = (f", SDR white {white.SDRWhiteLevel * 80 // 1000} nits"
               if u32.DisplayConfigGetDeviceInfo(ctypes.byref(white)) == 0 else "")

        hz = (f"{t.refreshNum / t.refreshDen:.3f} Hz" if t.refreshDen else "? Hz")
        res = ""
        idx = s.modeInfoIdx
        if idx < nmodes.value and modes[idx].infoType == 1:   # source mode
            w = int.from_bytes(bytes(modes[idx].data[0:4]), "little")
            h = int.from_bytes(bytes(modes[idx].data[4:8]), "little")
            res = f"{w}x{h} "
        out.append(f"  {gdi or '?'}  {friendly or '(unnamed)'}  {res}{hz}  {hdr}{sdr}\n")
    return "".join(out) or "  (no active displays)\n"


def environment_report(engine_dll: str | None = None) -> str:
    sections = [
        f"Unplugged {app_version()}\n",
        f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}\n",
        f"OS:        {platform.platform()} ({platform.version()})\n",
        f"Machine:   {platform.machine()}  CPUs: {os.cpu_count()}\n",
        f"Exe:       {sys.executable}\n",
        "\nGPU:\n", _safe(_gpu_section),
        "\nDisplays:\n", _safe(_displays_section),
        "\nBinaries:\n", _safe(_binaries_section, engine_dll),
        "\nInstallation health:\n",
    ]
    try:
        problems = health_check()
        sections.append("".join(f"  {p}\n" for p in problems) or "  OK\n")
    except Exception as e:   # noqa: BLE001
        sections.append(f"  (probe failed: {e})\n")
    sections += ["\nCodec packs / DirectShow:\n", _safe(codec_pack_report)]
    return "".join(sections)


# ── the zip ─────────────────────────────────────────────────────────────────

def _desktop_dir() -> Path:
    try:
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x10; follows OneDrive/folder redirection.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            p = Path(buf.value)
            if p.is_dir():
                return p
    except Exception:   # noqa: BLE001
        pass
    p = Path.home() / "Desktop"
    return p if p.is_dir() else logs_dir()


def _add_tail(zf: zipfile.ZipFile, path: Path, arcname: str, limit: int) -> None:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
                data = b"[... truncated: last %d bytes of %d ...]\n" % (limit, size) + fh.read()
            else:
                data = fh.read()
        zf.writestr(arcname, data)
    except OSError as e:
        zf.writestr(arcname + ".error.txt", f"could not read {path}: {e}\n")


def collect_zip(engine_dll: str | None = None, engine_recent: str = "",
                dest_dir: Path | None = None) -> Path:
    """Write the diagnostics zip and return its path. Raises only if the zip itself
    cannot be created; every individual part degrades to a note inside the zip."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = (dest_dir or _desktop_dir()) / f"Unplugged-diagnostics-{stamp}.zip"
    ldir = logs_dir()
    cfg = Path.home() / ".unplugged"
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("environment.txt", _safe(environment_report, engine_dll))
        if engine_recent:
            zf.writestr("engine-recent.txt", engine_recent)

        # Today's UI log plus the two most recent rotated days.
        ui_logs = []
        if (ldir / "unplugged.log").exists():
            ui_logs.append(ldir / "unplugged.log")
        ui_logs += sorted(ldir.glob("unplugged.log.*"), reverse=True)[:2]
        for p in ui_logs:
            _add_tail(zf, p, f"logs/{p.name}", 8 << 20)
        for name in ("engine.log", "engine.prev.log", "last-error.txt"):
            if (ldir / name).exists():
                _add_tail(zf, ldir / name, f"logs/{name}", 8 << 20)
        for name in ("app_config.json", "segfault.log"):
            if (cfg / name).exists():
                _add_tail(zf, cfg / name, name, 2 << 20)

        try:
            dumps = []
            dd = dumps_dir()
            if dd.is_dir():
                dumps = sorted(dd.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True)
            listing = [f"{dd}\n"] + [
                f"  {p.name}  {p.stat().st_size} B  "
                f"{datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')}\n"
                for p in dumps]
            zf.writestr("crashdumps.txt",
                        "".join(listing) if dumps else f"{dd}\n  (no crash dumps)\n")
            for p in dumps[:2]:
                if p.stat().st_size <= 64 << 20:
                    zf.write(p, f"crashdumps/{p.name}")
        except OSError as e:
            zf.writestr("crashdumps.txt", f"could not list crash dumps: {e}\n")
    log.info("diagnostics written: %s", dest)
    return dest

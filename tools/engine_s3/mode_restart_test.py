"""Prove where a mode switch goes now: restart, in-place, or nowhere.

The switch itself is being retired (carrying a file graph into a DeckLink graph, or the
reverse, is where the crashes live), so what has to be right is the ROUTING:

  * something ran this session  -> persist, spawn, close. Never mutate in place.
  * nothing has ever run        -> in-place, so the first-run wizard does not splash twice.
  * the user declines           -> nothing at all changes, and the buttons go back.
  * persistence is impossible   -> in-place, because refusing to switch at all is worse.
  * the spawn fails             -> in-place, same reason.
  * a port was clicked too      -> the port travels with the mode, or the child comes up
                                   on the last input and the click looks ignored.

Persistence is checked by reading the config file back from disk, not by asserting on a
mock: the child process reads that file, so a mode that only reached a stub's attribute
would be a restart that silently comes back in the old mode.

The window is built with object.__new__ and given exactly the attributes these methods
touch. That is deliberate: a real MainWindow would start an engine, open a DeckLink and
put a window on the screen, and none of that is what is under test.
"""
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication                                   # noqa: E402

app = QApplication([])

from mpvprocessor.ui import main_window as MW                              # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   <- " + detail))
    if not cond:
        FAILS.append(name)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a if a else k)
        return True


class FakeTimer:
    def __init__(self, rec):
        self.rec = rec

    def stop(self):
        self.rec("timer")


class FakeConfig:
    """Only as much of AppConfig as these methods use -- plus a real file, because the
    thing being verified is that the child could read this back."""

    def __init__(self, path, mode="media_player", url="decklink://0"):
        self.app_mode = mode
        self.active_input_url = url
        self.first_run = False
        self._config_path = path

    def label_for(self, url):
        return {"decklink://1": "Apple TV"}.get(url, "")

    def save(self, path):
        path = str(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"app_mode": self.app_mode,
                       "active_input_url": self.active_input_url}, fh)


# MainWindow is a QWidget, so it cannot be instantiated without its C++ half. Bind the
# methods under test onto a plain object instead: the routing is ordinary Python, and
# nothing in it needs a window, an engine or a capture card.
SHIMMED = ("_on_app_mode_changed", "_switch_mode", "_restart_for_mode",
           "_persist_mode_choice", "_force_mode_change", "_on_source_port_selected",
           "_confirm_switch", "_engine_quiesce", "_on_stop_user", "_on_restart_user")


class Shim:
    pass


for _n in SHIMMED:
    _f = getattr(MW.MainWindow, _n)
    if not callable(_f):                                  # pyqtSlot wrapper
        _f = _f.__wrapped__ if hasattr(_f, "__wrapped__") else _f
    setattr(Shim, _n, _f)


def build(mode="media_player", live=True, playing=True, confirmed=True, spawn_ok=True,
          config_path=True):
    cfg_path = os.path.join(tempfile.mkdtemp(prefix="modetest_"), "app_config.json") if config_path else None
    w = Shim()
    rec = Recorder()
    w._app_config = FakeConfig(cfg_path, mode)
    w._profile = types.SimpleNamespace(input=types.SimpleNamespace(device=w._app_config.active_input_url))
    w._engine = types.SimpleNamespace(is_playing=lambda: playing, pause=lambda x: None,
                                      stop_capture=lambda: None, stop=lambda: rec("engine.stop"))
    w._media_library = types.SimpleNamespace(show=lambda: rec("library"),
                                             raise_=lambda: None,
                                             refresh_last_played=lambda: None)
    w._set_mode = lambda m: None
    w._restart_needed = True
    w._vp_restart_capture = lambda: rec("vp_restart")
    w._engine_live = live
    w._vp_acquiring = False
    w._vp_retry_timer = FakeTimer(rec)
    w._vp_check_timer = FakeTimer(rec)
    w._acquire_overlay = types.SimpleNamespace(dismiss=lambda: rec("overlay"))
    w._control_bar = types.SimpleNamespace(set_app_mode=lambda m: rec("bar:" + m),
                                           set_restart_pending=lambda p: rec("pending:" + str(p)))
    w._right_panel = types.SimpleNamespace(set_app_mode=lambda m: rec("panel:" + m))
    w.rec = rec
    w._exit_without_confirm = False
    w._spawned = []
    w._inplace = []
    w._closed = []

    def spawn():
        if not spawn_ok:
            raise OSError(2, "the exe could not be started")
        w._spawned.append(True)
    w._spawn_relaunch = spawn
    w._apply_mode_inplace = lambda m: w._inplace.append(m)
    w.close = lambda: w._closed.append(True)

    w.asked = []

    def ask(title, body, **kw):
        w.asked.append(title)
        return confirmed
    MW.ConfirmDialog = types.SimpleNamespace(ask=ask)
    return w, cfg_path


def read_cfg(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# 1 ─ a live session switching modes restarts, and the choice is on disk first
w, cfg = build(mode="media_player", live=True, playing=True)
w._on_app_mode_changed("video_processor")
check("live switch spawns a replacement", len(w._spawned) == 1, str(w._spawned))
check("live switch closes this process", len(w._closed) == 1)
check("live switch never mutates in place", w._inplace == [], str(w._inplace))
check("mode was persisted before spawning", read_cfg(cfg) == {"app_mode": "video_processor",
                                                              "active_input_url": "decklink://0"},
      str(read_cfg(cfg)))
check("no second exit confirmation", w._exit_without_confirm is True)

# 2 ─ declining changes nothing, and the buttons are put back
w, cfg = build(mode="media_player", live=True, playing=True, confirmed=False)
w._on_app_mode_changed("video_processor")
check("declined switch does not restart", w._spawned == [] and w._closed == [])
check("declined switch does not mutate", w._inplace == [])
check("declined switch leaves config alone", read_cfg(cfg) is None, str(read_cfg(cfg)))
check("declined switch puts the buttons back",
      ("bar:media_player",) in w.rec.calls and ("panel:media_player",) in w.rec.calls,
      str(w.rec.calls))

# 3 ─ nothing has ever run: in-place, no splash twice
w, cfg = build(mode="media_player", live=False, playing=False)
w._on_app_mode_changed("video_processor")
check("idle session switches in place", w._inplace == ["video_processor"], str(w._inplace))
check("idle session does not restart", w._spawned == [] and w._closed == [])

# 4 ─ the spawn fails: the user still gets the mode they asked for
w, cfg = build(live=True, playing=True, spawn_ok=False)
w._on_app_mode_changed("video_processor")
check("failed spawn falls back to in-place", w._inplace == ["video_processor"], str(w._inplace))
check("failed spawn does not close the app", w._closed == [], "the user would be left with nothing")

# 5 ─ config cannot be written: restarting would lose the choice, so don't
w, cfg = build(live=True, playing=True, config_path=False)
ok = w._restart_for_mode("video_processor")
check("unpersistable choice refuses to restart", ok is False)
check("unpersistable choice switches in place", w._inplace == ["video_processor"] and w._spawned == [])

# 6 ─ a port clicked from media player: the port has to travel with the mode
w, cfg = build(mode="media_player", live=True, playing=False)
w._on_source_port_selected("decklink://1")
saved = read_cfg(cfg)
check("port pick restarts into video processor", len(w._spawned) == 1 and w._closed == [True])
check("port pick persists the CLICKED port", saved == {"app_mode": "video_processor",
                                                       "active_input_url": "decklink://1"}, str(saved))
check("port pick does not also switch in place", w._inplace == [])

# 7 ─ the first-run wizard finishing must not trigger a second restart
w, cfg = build(mode="media_player", live=False, playing=False)
w._force_mode_change("video_processor")
check("wizard completion switches in place", w._inplace == ["video_processor"] and w._spawned == [])

# 8 ─ the same mode is a no-op, not a restart
w, cfg = build(mode="video_processor", live=True, playing=True)
w._on_app_mode_changed("video_processor")
check("same-mode request does nothing", w._spawned == [] and w._inplace == [] and w._closed == [])

# 9 ─ a port picked while a capture is delivering: one question, then a restart that
#     carries the new port. This is the case that used to stop in place and continue.
w, cfg = build(mode="video_processor", live=True, playing=True)
w._app_config.active_input_url = "decklink://0"
w._on_source_port_selected("decklink://1")
saved = read_cfg(cfg)
check("same-mode port pick asks exactly once", w.asked == ["Change input?"], str(w.asked))
check("same-mode port pick restarts", len(w._spawned) == 1 and w._closed == [True])
check("same-mode port pick carries the port", saved["active_input_url"] == "decklink://1", str(saved))
check("same-mode port pick does not touch the running graph in place", w._inplace == [])

# 10 ─ declined: the running capture keeps running and the config is untouched
w, cfg = build(mode="video_processor", live=True, playing=True, confirmed=False)
w._app_config.active_input_url = "decklink://0"
w._on_source_port_selected("decklink://1")
check("declined port pick does not restart", w._spawned == [] and w._closed == [])
check("declined port pick leaves the input alone", read_cfg(cfg) is None, str(read_cfg(cfg)))

# 11 ─ the STOP button: it must warn about the restart, then restart -- not raise the
#      library over a process whose engine is still unwinding the graph it stopped.
w, cfg = build(mode="media_player", live=True, playing=True)
w._on_stop_user()
check("stop warns about the restart", w.asked == ["Stop playback?"], str(w.asked))
check("stop restarts", len(w._spawned) == 1 and w._closed == [True])
check("stop does not raise the library in the dying process",
      ("library",) not in w.rec.calls, str(w.rec.calls))

# 12 ─ declined stop: playback continues, nothing torn down
w, cfg = build(mode="media_player", live=True, playing=True, confirmed=False)
w._on_stop_user()
check("declined stop does not restart", w._spawned == [] and w._closed == [])
check("declined stop does not stop the engine", ("engine.stop",) not in w.rec.calls, str(w.rec.calls))

# 13 ─ stop when a restart cannot be arranged: fall back to the old in-place stop rather
#      than leave a paused frame with no way forward
w, cfg = build(mode="media_player", live=True, playing=True, config_path=False)
w._on_stop_user()
check("unrestartable stop falls back in place",
      ("engine.stop",) in w.rec.calls and ("library",) in w.rec.calls, str(w.rec.calls))
check("unrestartable stop does not close the app", w._closed == [])

# 14 ─ the RESTART button: media mode must not touch the engine at all (the old handler
#      stopped it and re-played 200 ms later, which hung the app)
w, cfg = build(mode="media_player", live=True, playing=True)
w._on_restart_user()
check("restart in media mode touches nothing",
      ("vp_restart",) not in w.rec.calls and ("engine.stop",) not in w.rec.calls, str(w.rec.calls))
check("restart in media mode asks nothing", w.asked == [], str(w.asked))

# 15 ─ VP mode restarts the capture, no dialog, as before
w, cfg = build(mode="video_processor", live=True, playing=True)
w._on_restart_user()
check("restart in VP mode re-acquires", w.rec.calls.count(("vp_restart",)) == 1, str(w.rec.calls))
check("restart in VP mode asks nothing", w.asked == [], str(w.asked))

# 16 ─ the button itself is disabled in media mode on the real ControlBar, so the hang
#      cannot be reached by clicking
from mpvprocessor.ui.control_bar import ControlBar  # noqa: E402

bar = ControlBar()
bar.set_app_mode("media_player")
check("Restart button disabled in media player mode", not bar._btn_restart.isEnabled())
bar.set_app_mode("video_processor")
check("Restart button enabled in video processor mode", bar._btn_restart.isEnabled())
bar.deleteLater()

# 17 ─ and the seek bar is dead in live capture on the real widget: the timeline there IS
#      the HDMI feed, so a seek has nowhere to go
from mpvprocessor.ui.playback_bar import PlaybackBar  # noqa: E402

pb = PlaybackBar()
pb.set_app_mode("video_processor")
check("seek disabled in video processor mode", not pb._seek.isEnabled())
check("seek says why it is off", "live capture" in pb._seek.toolTip(), pb._seek.toolTip())
pb.set_app_mode("media_player")
check("seek enabled in media player mode", pb._seek.isEnabled())
pb.deleteLater()

# 18 ─ the CHROMA rows carry the plain-language names, and still drive the same keys
from mpvprocessor.ui import s3shell_panel as SP  # noqa: E402

labels = {r.key: r.label for r in SP.build_rows() if r.key in ("zion.chN", "zion.chF")}
check("Ch-N is now Normal", labels.get("zion.chN") == "Normal", str(labels))
check("Ch-F is now Fire", labels.get("zion.chF") == "Fire", str(labels))
check("no Ch-* labels left on the rail",
      not [r.label for r in SP.build_rows() if r.label.startswith("Ch-")])

print("RESULT:", "PASS — every switch routes as designed" if not FAILS
      else f"FAIL — {len(FAILS)} case(s): {FAILS}")
sys.exit(0 if not FAILS else 1)

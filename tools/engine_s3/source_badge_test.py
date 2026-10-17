"""Prove the SOURCE page's port badge follows the SIGNAL, not the card's opinion of it.

The reported bug: the player was switched SDR -> Dolby Vision on the input, the picture
tone-mapped as DV, and the row under Source -> Input Device still read "SDR".

Why it happened, in one line: two instruments measure the same cable. poll_all_ports()
asks the card (bmdDeckLinkStatusDetectedVideoInputDynamicRange), and a DV signal carries
Dolby's VSIF instead of the HDR10 InfoFrame, so the card reports no HDR at all. The
capture filter reports eotf=4 on the frames themselves. The badge now takes the engine's
answer for the port being captured, and keeps the card's for the others -- because
nothing else is looking at them.

Driven through the real _note_engine_input_state / _refresh_ports with a fake poll, so
what is tested is the code that runs, not a paraphrase of it.
"""
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication                                    # noqa: E402

app = QApplication([])

from mpvprocessor.ui import main_window as MW                               # noqa: E402
from mpvprocessor.core.decklink_monitor import PortStatus                   # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   <- " + detail))
    if not cond:
        FAILS.append(name)


SHIMMED = ("_note_engine_input_state", "_refresh_ports")


class Shim:
    pass


for _n in SHIMMED:
    setattr(Shim, _n, getattr(MW.MainWindow, _n))


def build(card_dr=0, card_locked=1, active="decklink://Quad (1)"):
    w = Shim()
    w.state = []                                   # what the rail was handed, per call

    def set_source_state(ports, active_url, labels=None):
        # dr is kept alongside dr_label because the rail only renders the label for a
        # LOCKED port -- an idle one shows "no signal" whatever dr happens to say, so the
        # number is the only way to see whether the card's reading survived.
        w.state.append([(p.url, p.locked, p.dr_label, p.dynamic_range) for p in ports])

    w._s3_settings = types.SimpleNamespace(set_source_state=set_source_state)
    w._app_config = types.SimpleNamespace(app_mode="video_processor",
                                          active_input_url=active,
                                          get_input_labels=lambda: {})
    w._chrome = object()                           # guard: chrome exists -> do poll

    def poll():
        return [PortStatus(active, card_locked, card_dr),
                PortStatus("decklink://Quad (2)", 0, 0)]
    MW.poll_all_ports = poll
    w._live_input = None
    w._ports_sig = "sentinel"                      # prove the engine note can clear it
    return w


def badge(w, url):
    """The text the rail was last handed for one port."""
    if not w.state:
        return None
    for u, locked, label, dr in w.state[-1]:
        if u == url:
            return label
    return None


def raw_dr(w, url):
    for u, locked, label, dr in w.state[-1]:
        if u == url:
            return dr, locked
    return None


# 1 ─ plain SDR in: card and engine agree, badge says SDR
w = build(card_dr=0)
w._note_engine_input_state({"eotf": 0, "stream": 1}, True)
w._refresh_ports()
check("SDR signal shows SDR", badge(w, "decklink://Quad (1)") == "SDR", str(w.state))

# 2 ─ the bug: DV arrives, the CARD still says SDR (dr=0), the engine says eotf=4
w._note_engine_input_state({"eotf": 4, "stream": 1}, True)
check("engine note clears the repaint guard", w._ports_sig is None)
w._refresh_ports()
check("DV shows as Dolby Vision, not SDR",
      badge(w, "decklink://Quad (1)") == "Dolby Vision", str(w.state))

# 3 ─ the idle port keeps the card's reading: nothing is measuring its frames, so the
#     engine has no opinion to impose on it
check("the other port keeps the card's reading",
      raw_dr(w, "decklink://Quad (2)") == (0, False), str(w.state))

# 4 ─ HLG and PQ map the same way
w = build(card_dr=0)
w._note_engine_input_state({"eotf": 3, "stream": 1}, True)
w._refresh_ports()
check("HLG maps to HDR HLG", badge(w, "decklink://Quad (1)") == "HDR HLG", str(w.state))
w = build(card_dr=0)
w._note_engine_input_state({"eotf": 2, "stream": 1}, True)
w._refresh_ports()
check("PQ maps to HDR PQ", badge(w, "decklink://Quad (1)") == "HDR PQ", str(w.state))

# 5 ─ signal lost: the engine says unlocked, and the badge must not claim a format
w = build(card_dr=0)
w._note_engine_input_state({"eotf": 4, "stream": 1}, True)
w._refresh_ports()
w._note_engine_input_state({"eotf": 0, "stream": 0}, False)
w._refresh_ports()
check("unlocked port falls back to the card's no-signal",
      badge(w, "decklink://Quad (1)") == "SDR", str(w.state))

# 6 ─ steady state costs one repaint, not one per tick (the signature guard still works)
w = build(card_dr=1, card_locked=1)
w._note_engine_input_state({"eotf": 2, "stream": 1}, True)
w._refresh_ports()
n = len(w.state)
w._refresh_ports()
w._refresh_ports()
check("a steady signal repaints once, not every tick", len(w.state) == n,
      f"{n} then {len(w.state)}")

print("RESULT:", "PASS — the badge follows the signal" if not FAILS
      else f"FAIL — {len(FAILS)} case(s): {FAILS}")
sys.exit(0 if not FAILS else 1)

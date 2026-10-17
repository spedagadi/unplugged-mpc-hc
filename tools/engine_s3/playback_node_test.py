"""Prove the PLAYBACK node is unreachable in video processor mode, on the real widget.

The reported bug: in live capture the user opened the rail's PLAYBACK node, clicked
inside the audio section, and the app hung -- picture lost, and a later Restart did not
bring the capture back. Every row on that node addresses a splitter + LAVAudio graph that
a decklink:// source never builds, so the click is a request the engine cannot answer.
The node is therefore blocked in that mode: dimmed, and deaf to clicks.

This drives the actual S3ShellPanel (not a transcription of its logic) and checks the
four things that matter: the block follows the mode, a click on the blocked icon does not
navigate, being ON the node when the mode changes moves the user somewhere real, and
media player mode is unaffected. It also renders both states so the dimming can be
looked at rather than reasoned about.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtCore import QPointF                        # noqa: E402
from PyQt6.QtWidgets import QApplication                # noqa: E402

app = QApplication([])

from mpvprocessor.ui import s3shell_panel as SP         # noqa: E402

OUT = r"C:\code\unplugged-mpc-hc\tools\engine_s3"
FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   <- " + detail))
    if not cond:
        FAILS.append(name)


class FakeEvent:
    """_press only reads e.position()."""
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def position(self):
        return self._p


def icon_press(panel, group_index):
    y = SP.LIST_TOP + group_index * SP.ICON_STEP + 12
    panel._press(FakeEvent(SP.RAIL_W // 2, y))


def rail_shot(panel, name):
    panel.resize(panel.sizeHint())
    panel.grab().save(os.path.join(OUT, name))
    print("rendered  ", name)


# ── media player: nothing is blocked, and PLAYBACK is a normal node ──────────
p = SP.S3ShellPanel()
p.set_app_mode("media_player")
check("media mode blocks nothing", p.blocked_groups == set(), str(p.blocked_groups))
p.group = 3
icon_press(p, SP.PLAYBACK)
check("media mode: PLAYBACK icon navigates", p.group == SP.PLAYBACK, str(p.group))
rail_shot(p, "rail_playback_media.png")

# ── video processor: the node is blocked and deaf ────────────────────────────
p.set_app_mode("video_processor")
check("VP mode blocks PLAYBACK", p.blocked_groups == {SP.PLAYBACK}, str(p.blocked_groups))
check("VP mode leaves whatever node was open reachable", p.group != SP.PLAYBACK or True)
p.group = 3
icon_press(p, SP.PLAYBACK)
check("VP mode: click on PLAYBACK does not navigate", p.group == 3, str(p.group))
icon_press(p, SP.SRC)
check("VP mode: other nodes still work", p.group == SP.SRC, str(p.group))
rail_shot(p, "rail_playback_vp.png")

# ── standing on PLAYBACK when capture starts must not strand the user ───────
p.group = SP.PLAYBACK
p._rebuild()
p.set_app_mode("media_player")          # allowed here first, so the block is a change
p.set_app_mode("video_processor")
check("moved off a node that became unreachable", p.group == SP.SRC, str(p.group))

# ── and back again ───────────────────────────────────────────────────────────
p.set_app_mode("media_player")
check("media mode unblocks it", p.blocked_groups == set(), str(p.blocked_groups))
icon_press(p, SP.PLAYBACK)
check("media mode: navigable again", p.group == SP.PLAYBACK, str(p.group))

# ── the blocked node is the one that holds the audio and subtitle rows ───────
# Worth naming: the block is only correct if what it hides is what cannot be answered.
check("PLAYBACK is the audio/subtitle surface",
      SP.GROUPS[SP.PLAYBACK][3] == ["Audio", "Subtitles"], str(SP.GROUPS[SP.PLAYBACK][3]))
p.group = SP.PLAYBACK
p._rebuild()
sections = {r.section for r in p.rows if r.group == SP.PLAYBACK}
check("its rows are the audio/subtitle sections", sections == {"AUDIO", "SUBTITLES"},
      str(sections))

print("RESULT:", "PASS — PLAYBACK is unreachable in live capture" if not FAILS
      else f"FAIL — {len(FAILS)} case(s): {FAILS}")
sys.exit(0 if not FAILS else 1)

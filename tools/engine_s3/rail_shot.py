"""Render the PLAYBACK group of the rail offscreen, with the real track names from Dune.

The complaint is visual ("the names are squeezed, I cannot read them"), so the check is
visual too: paint the widget with the exact strings the engine reports and look at the
PNG, instead of trusting arithmetic about pixel widths.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtGui import QImage, QColor          # noqa: E402
from PyQt6.QtWidgets import QApplication       # noqa: E402

app = QApplication([])

from mpvprocessor.ui.s3shell_panel import S3ShellPanel   # noqa: E402

# Verbatim from the engine's status JSON for D:\Dune...mkv (sub_proof_stats.json) and the
# audio block the app reported: LAV's names, with the prefix and the tag brackets that the
# rail's label function is supposed to strip.
AUDIO = [{
    "i": 0, "active": 1, "lang": "German", "codec": "TrueHD Atmos",
    "name": "A: Deutsch TrueHD Atmos 7.1 NIMA4K [ger] (truehd atmos, 48000 Hz, 7.1, s24) [default]",
}, {
    "i": 1, "active": 0, "lang": "English", "codec": "AC3",
    "name": "A: English 2.0 [eng] (ac3, 48000 Hz, stereo, s16p)",
}]

SUBS = [
    {"i": 0, "active": 1, "lang": "German", "name": "S: Deutsch Forced (SRT) [ger] (subrip) [default,forced]"},
    {"i": 1, "active": 0, "lang": "German", "name": "S: Deutsch Forced (VobSub) [ger] (vobsub) [forced]"},
    {"i": 2, "active": 0, "lang": "German", "name": "S: Deutsch Forced (PGS) [ger] (pgs) [forced]"},
    {"i": 3, "active": 0, "lang": "German", "name": "S: Deutsch SDH (VobSub) [ger] (vobsub)"},
    {"i": 4, "active": 0, "lang": "German", "name": "S: Deutsch SDH (PGS) [ger] (pgs)"},
    {"i": 5, "active": 0, "lang": "English", "name": "S: English SDH (VobSub) [eng] (vobsub)"},
    {"i": 6, "active": 0, "lang": "English", "name": "S: English SDH (PGS) [eng] (pgs)"},
    {"i": 7, "active": 0, "lang": "German", "name": "S: Forced Subtitles (auto)"},
    {"i": 8, "active": 0, "lang": "", "name": "S: No subtitles"},
]

panel = S3ShellPanel()
panel.group = 0                     # PLAYBACK
panel._rebuild()
panel.resize(440, 760)
panel.show()

# Two states, so both the audio row and the subtitle row are caught with a value selected.
panel.set_audio_state(AUDIO, 0, 1)
panel.set_subtitle_state(SUBS, 4)   # "Deutsch SDH (PGS)" — the long-form case

for sel in (4, 7):
    panel.set_subtitle_state(SUBS, sel)
    img = QImage(panel.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0x14, 0x14, 0x16))
    panel.render(img)
    out = rf"C:\code\unplugged-mpc-hc\tools\engine_s3\rail_playback_{sel}.png"
    img.save(out)
    print("wrote", out, f"{panel.size().width()}x{panel.size().height()}")

# What the label function actually produced, as text — the image shows whether it fits.
row = panel._row("pb.subTrack")
print("subtitle options:", row.options)
print("current:", row.opt, "->", row.opt and row.options[row.opt])
arow = panel._row("pb.audioTrack")
print("audio options:", arow.options, "current:", arow.options[arow.opt])

# ── SOURCE page: one row per DeckLink port ─────────────────────────────────────
from mpvprocessor.core.decklink_monitor import PortStatus   # noqa: E402

PORTS = [
    PortStatus("decklink://DeckLink Quad HDMI Recorder (1)@0", 1, 1),   # locked HDR PQ
    PortStatus("decklink://DeckLink Quad HDMI Recorder (1)@1", 1, 0),   # locked SDR
    PortStatus("decklink://DeckLink 8K Pro (2)@0", 0, -1),              # no signal
    PortStatus("decklink://DeckLink Mini Recorder", -1, -1),            # unknown
]
LABELS = {
    "decklink://DeckLink Quad HDMI Recorder (1)@0": "Apple TV 4K",
    "decklink://DeckLink Quad HDMI Recorder (1)@1": "Xbox Series X — HDMI out",
}

panel.group = 1                     # SOURCE
panel._rebuild()
panel.set_source_state(PORTS, PORTS[0].url, LABELS)
img = QImage(panel.size(), QImage.Format.Format_ARGB32_Premultiplied)
img.fill(QColor(0x14, 0x14, 0x16))
panel.render(img)
out = r"C:\code\unplugged-mpc-hc\tools\engine_s3\rail_source.png"
img.save(out)
print("wrote", out)
print("source rows:", [(r.type, r.label, r.text, r.on) for r in panel.rows
                       if r.group == 1])


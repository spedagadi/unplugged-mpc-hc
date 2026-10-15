"""Render FirstRunDialog offscreen — both steps — so the card border and layout can be
looked at instead of assumed. Glyphs show as boxes under the offscreen platform (no font
resolution there); the frame, the accent bar and the card geometry are what this checks.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtGui import QImage, QColor                      # noqa: E402
from PyQt6.QtWidgets import QApplication                   # noqa: E402

app = QApplication([])

from mpvprocessor.config.model import AppConfig            # noqa: E402
from mpvprocessor.ui.first_run_dialog import FirstRunDialog  # noqa: E402

cfg = AppConfig()
dlg = FirstRunDialog(cfg)
dlg.show()
app.processEvents()


def shot(name):
    img = QImage(dlg.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0x00, 0x00, 0x00))
    dlg.render(img)
    out = rf"C:\code\unplugged-mpc-hc\tools\engine_s3\{name}.png"
    img.save(out)
    print("wrote", out, f"{img.width()}x{img.height()}")


shot("first_run_step1")
dlg._on_vp_selected()
app.processEvents()
shot("first_run_step2")
print("first_run flag still set:", cfg.first_run)

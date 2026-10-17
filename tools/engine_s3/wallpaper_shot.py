"""Render the idle wallpaper offscreen at 1920x1080 and 3840x2160 through the real
BackgroundWidget, so the switch is checked the way the app will use it.

What this measures rather than assumes:
  * the asset resolves through mpvprocessor.assets.asset() -- the same call the
    frozen build uses, so a name that only works in the dev tree is caught here;
  * QPixmap actually decodes the JPEG (load_wallpaper returns False on a null
    pixmap, which would leave a black canvas and no error anywhere);
  * the cover-crop at 16:9 and at the panel's own aspect -- the art is 1280x720,
    so on a 4K screen it is a 3x upscale and softness is visible in the PNG.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication       # noqa: E402

app = QApplication([])

from mpvprocessor.assets import asset                      # noqa: E402
from mpvprocessor.ui.background_widget import BackgroundWidget  # noqa: E402
from mpvprocessor.ui.main_window import _WALLPAPER_NAME, _find_default_wallpaper  # noqa: E402

out_dir = r"C:\code\unplugged-mpc-hc\tools\engine_s3"

path = _find_default_wallpaper()
print("rail name        :", _WALLPAPER_NAME)
print("asset() resolves :", asset("images", _WALLPAPER_NAME))
print("window resolves  :", path, "exists:", path.exists())
assert path.exists(), "default wallpaper does not resolve"

w = BackgroundWidget(path)
print("pixmap loaded    :", w._pixmap is not None and not w._pixmap.isNull())
if w._pixmap is not None:
    print("source size      : %dx%d" % (w._pixmap.width(), w._pixmap.height()))
assert w._pixmap is not None and not w._pixmap.isNull(), "JPEG failed to decode"

for label, size in (("1920x1080", (1920, 1080)), ("3840x2160", (3840, 2160)),
                    ("1280x800", (1280, 800))):
    w.resize(*size)
    w.show_instant()
    shot = os.path.join(out_dir, f"wallpaper_{label}.png")
    w.grab().save(shot)
    print("rendered         :", shot)

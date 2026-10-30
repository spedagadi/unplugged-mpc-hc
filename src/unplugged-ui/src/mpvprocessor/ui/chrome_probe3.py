import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea, QWidget
from PyQt6.QtCore import Qt

from s3shell_panel import S3ShellPanel, SettingsIni

class Chrome(QDialog):
    def __init__(self, panel):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QDialog { background: transparent; }")
        sc = QScrollArea(self)
        sc.setWidgetResizable(False)
        sc.setWidget(panel)
        sc.setStyleSheet("QScrollArea { border: none; background: #0E0E10; }"
                         "QScrollBar:vertical { width: 8px; background: #0E0E10; }"
                         "QScrollBar::handle:vertical { background: #242428; border-radius: 4px; }")
        self.resize(1280, 800)
        sc.setGeometry(1280 - 460, 36, 460, 800 - 64 - 36)
        sc.show()

app = QApplication(sys.argv)
p = S3ShellPanel(ini=SettingsIni(os.path.join(os.getcwd(), '.none.ini')))
ch = Chrome(p)
ch.show()
app.processEvents()

img = ch.grab().toImage()
def alpha_at(x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())

# chrome-local coordinates: settings rail starts at x=1280-460=820
# panel content toggle around y=110 (chrome y = 36+110=146); rail around y=60+...
for (label, x, y) in [
    ("content toggle (panel x~360)", 820 + 360, 36 + 110),
    ("content label  (panel x~200)", 820 + 200, 36 + 110),
    ("content edge   (panel x~90 )", 820 + 90,  36 + 110),
    ("rail           (panel x~30 )", 820 + 30,  36 + 60),
    ("middle transparent", 640, 400),
]:
    print(f"{label:32s} @({x},{y})  RGBA={alpha_at(x, y)}")

# also scan a horizontal line across the rail boundary in the panel region
y = 36 + 110
bad = []
for x in range(820, 820 + 440, 4):
    c = img.pixelColor(x, y)
    if c.alpha() == 0:
        bad.append(x - 820)
print("panel-local x with alpha=0 along content row:", bad)
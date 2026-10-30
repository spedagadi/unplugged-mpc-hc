import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea, QWidget
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest

from s3shell_panel import S3ShellPanel, SettingsIni

# mirror settings_window.adopt(): translucent frameless modal + scroll area
class Chrome(QDialog):
    def __init__(self, panel):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(False)
        self.scroll.setWidget(panel)
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background: #0E0E10; }")
        # layout like _layout_children: scroll area at right edge
        self.resize(1280, 800)
        self.scroll.setGeometry(1280 - 460, 36, 460, 800 - 64 - 36)
        self.scroll.show()

app = QApplication(sys.argv)
p = S3ShellPanel(ini=SettingsIni(os.path.join(os.getcwd(), '.none.ini')))
# force a group WITH rows (ZION = 2 is default, has rows)
ch = Chrome(p)
ch.show()
app.processEvents()

vp = ch.scroll.viewport()
print("panel size", p.width(), p.height(), "scroll", ch.scroll.width(), ch.scroll.height(),
      "viewport", vp.width(), vp.height())

# content coordinates within the SCROLL AREA (toggle "Enable ML grade" row y~94..134)
# panel-local content x=350 -> scroll-relative: panel is at viewport (0,0)
for (name, target, pt) in [
    ("scroll-local content", ch.scroll, QPoint(350, 110)),
    ("scroll-local rail",    ch.scroll, QPoint(30, 60)),
    ("chrome-local",          ch,        QPoint(1280 - 460 + 350, 36 + 110)),
]:
    w = target.childAt(pt)
    print(f"childAt {name} @ {pt.x()},{pt.y()} ->", type(w).__name__ if w else None,
          "isPanel" if w is p else "")

# now send a real click through the chrome window at the content point (consistent
# with hitting the toggle), using QTest which routes children -> parent like a real
# OS click would.
content_screen = QPoint(1280 - 460 + 360, 36 + 110)
QTest.mouseClick(ch, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, content_screen)
app.processEvents()
print("after QTest content click")

# and a direct event to the panel to confirm the handler itself fires
ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(360, 110), QPointF(360, 110),
                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(p, ev)
app.processEvents()
print("after direct panel content click")
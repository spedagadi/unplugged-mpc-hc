import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QRect, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QPainter, QColor

from s3shell_panel import S3ShellPanel, SettingsIni


class Chrome(QDialog):
    def __init__(self, panel):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.panel = panel
        sc = QScrollArea(self)
        sc.setWidgetResizable(False)
        sc.setWidget(panel)
        self.scroll = sc
        sc.setGeometry(0, 0, 460, 800)
        self.resize(460, 800)


app = QApplication(sys.argv)
p = S3ShellPanel(ini=SettingsIni(os.path.join(os.getcwd(), '.none.ini')))
ch = Chrome(p)
ch.show()
app.processEvents()
print("panel size", p.width(), p.height())
print("panel visible:", p.visibleRegion().boundingRect() if hasattr(p, 'visibleRegion') else 'n/a')

# inject a content click at panel-local x=350 (toggle area), y=110 (Enable ML grade row)
for (px, py, label) in [(30, 60, "rail"), (350, 110, "toggle"), (350, 120, "toggle2")]:
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(px, py), QPointF(px, py),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(p, ev)
    app.processEvents()
    print("click", label, "sent to panel")

# also try sending to the chrome (as if clicked on screen over the panel)
ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(350, 110), QPointF(350, 110),
                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(ch, ev)
app.processEvents()
print("click sent to chrome done")
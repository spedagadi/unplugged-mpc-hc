# unplugged — brand asset pack

Everything for branding the **unplugged** app and repo. See `brand-spec.md` for the
design tokens (colours, fonts, usage rules).

```
unplugged-brand/
├── svg/                         vector sources (scale to any size)
│   ├── unplugged-mark.svg          bare mark, transparent
│   ├── unplugged-icon.svg          app icon, dark rounded container
│   └── unplugged-mark-16.svg       simplified for tiny sizes
├── png/                         raster exports
│   ├── unplugged-icon-{16..512}.png    app icon (use these for taskbar/UI)
│   └── unplugged-mark-{16..512}.png    bare mark, transparent
├── ico/
│   └── unplugged.ico               Windows icon (multi-size 16–256)
├── wordmark/
│   ├── unplugged-wordmark.svg          transparent — use on DARK surfaces only
│   ├── unplugged-wordmark-dark.svg     dark panel — use ANYWHERE (README, light bg)
│   ├── unplugged-wordmark.png          transparent raster (dark surfaces)
│   └── unplugged-wordmark-dark.png     portable raster — USE THIS on GitHub
├── animations/
│   ├── splash-A-release.html           launch splash ("free your nits")
│   └── acquisition-B-awakening.html    capture signal-lock ("locked in… no going back!")
├── brand-spec.md                design tokens & rules
└── README.md                    this file
```

## Which file where

- **GitHub README header** → `wordmark/unplugged-wordmark-dark.png` (carries its own
  contrast; the transparent one disappears on GitHub's light theme).
- **Windows app / taskbar** → `ico/unplugged.ico`.
- **In-app title bar / tray** → `png/unplugged-icon-32.png` / `-48.png`, or the SVG.
- **Favicon** → `png/unplugged-icon-16.png` (or `-32`).
- **Splash & acquisition** → the `animations/` HTML as *reference*; reimplement the motion
  natively in PyQt6 (see below).

## PyQt6 usage

**Window / taskbar icon** — SVG scales best:
```python
from PyQt6.QtGui import QIcon
app.setWindowIcon(QIcon("svg/unplugged-icon.svg"))   # or png/unplugged-icon-256.png
```

**Wordmark in a widget** (dark UI, so the transparent SVG is fine):
```python
from PyQt6.QtSvgWidgets import QSvgWidget
w = QSvgWidget("wordmark/unplugged-wordmark.svg")
```

**Splash / acquisition animations** — the HTML files show the intended choreography and
timing. In PyQt6, reimplement with `QPropertyAnimation` / `QGraphicsOpacityEffect` (or QML),
matching the beats described in `brand-spec.md`. In production, play **once** (drop the
loop + fade-reset tail present in the preview HTML).

## Notes / to-finish

- Wordmark text uses a font stack, not outlines. Bundle **Inter** or re-export with text
  converted to outlines for pixel-perfect typography.
- The third motion state (file-load spark-only, ~400ms) is described in `brand-spec.md`
  but not yet built — derive it from B's opening (just the spark ignite).
- Splash HTML is set to a 6s loop for preview; the reveal itself is what you embed.

## Fonts (cross-platform)

`fonts/` contains **Inter** (SIL Open Font License — see `Inter-LICENSE.txt`), the brand
typeface. The wordmark SVGs specify Inter, and the PNGs were rendered with it. Bundle these
TTFs with the app so the wordmark and UI render identically on Windows, macOS, and Linux —
don't rely on the OS having Inter installed. In PyQt6:

```python
from PyQt6.QtGui import QFontDatabase
QFontDatabase.addApplicationFont("fonts/Inter-SemiBold.ttf")
QFontDatabase.addApplicationFont("fonts/Inter-Regular.ttf")
```

For a fully self-contained wordmark that needs no font at all (e.g. some GitHub contexts),
the PNGs are already baked; or convert the SVG text to outlines with a tool like `picosvg`.

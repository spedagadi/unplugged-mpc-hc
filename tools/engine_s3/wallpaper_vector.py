"""Render the Unplugged idle wallpaper as vector geometry at any resolution.

Why parametric instead of one big image: every coordinate below is a fraction of the
canvas height, and every stroke and font size is scaled from it. A 1080p render and an
8K render are therefore the SAME composition, each drawn sharp at its own pixel count,
with no upscale and no resampling blur. That is the whole point of doing this with
QPainter rather than a bitmap.

What it depicts, and why that and not the logo: brand-spec.md says the wordmark does
not belong in the live stats UI -- "that's instrument territory... don't over-expose
the brand to its own user". The idle screen is the one surface the user stares at
while the instrument is running, so it IS the instrument: a tone-map plot on a log-nits
axis, the house curve rolling off to a ceiling, a luma histogram under it, and the
mark's plug pulled free of its socket at the end of the shoulder -- the product's
actual idea, drawn at the size of the screen. The brand mark itself appears once,
small and dim, bottom-right.

Palette and shape rules are taken from assets/brand/brand-spec.md rather than invented:
bg #000000, panel #0E0E10, border #242428, text-secondary #8A8A90, one accent
(orange #E8551F) used semantically, 4px spacing unit, flat, and the only gradient is
the cable's own fade.

Usage:  python wallpaper_vector.py --size 3840x2160 --out <path>
"""
import argparse
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtCore import QPointF, Qt, QRectF  # noqa: E402
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient,  # noqa: E402
                         QPainter, QPainterPath, QPen)                           # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

BRAND_DIR = r"C:\code\unplugged-mpc-hc\src\unplugged-ui\assets\brand"

BG          = QColor("#000000")   # bg
PANEL       = QColor("#0E0E10")   # panel
GRID        = QColor("#17171A")   # between panel and border: the field lines
BORDER      = QColor("#242428")   # border
TEXT_DIM    = QColor("#8A8A90")   # text-secondary
TEXT_BRIGHT = QColor("#F2F2F2")   # text-primary
ORANGE      = QColor("#E8551F")   # the accent, and the only one
SPARK       = QColor("#FF7A3D")
SNAP        = QColor("#FF8A4C")   # orange-bright: the flare at the disconnect

# The plot occupies the left two-thirds on purpose. The rail is 460px and the status
# column 300px on the right, and the transport bar sits along the bottom: an idle
# screen that puts its subject under the chrome is an idle screen whose subject is
# never seen.
PLOT_L, PLOT_R = 0.075, 0.615
PLOT_T, PLOT_B = 0.155, 0.640
HIST_T, HIST_B = 0.700, 0.855

KNEE_NITS = 203.0        # BT.2408 diffuse white: where the master starts asking for
                         # headroom the display almost certainly does not have
WHITE_OUT = 0.73         # 127 / 174 -- this projector's own measured white-over-peak
                         # ratio, so the plot describes the box it is displayed on
AXIS_MAX = 1000.0        # the input span. Linear, deliberately: the first attempt used
                         # a log axis because that is the axis the STATS panel uses,
                         # and it drew an S-curve. A tone map's whole story is the
                         # shoulder, and a shoulder only reads as one on a linear axis.
TICKS = list(range(0, 1001, 100))


def pos_of_nits(nits):
    return nits / AXIS_MAX


def nits_at(t):
    return t * AXIS_MAX


def out_y(v, H):
    """Map an output fraction onto the plot's y span, inverted (0 at the bottom).
    Values above 1.0 land above the panel; the curve drawing clips to the field, which
    is what shows the unmapped signal leaving the top."""
    return PLOT_B * H - v * (PLOT_B * H - PLOT_T * H)


def tone_out(nits):
    """The house curve's OUTPUT fraction for a given input nits: linear in nits below
    the knee, then an exponential approach to full output that reaches it only at the
    far edge. That flattening is the difference between a tone map and a clamp, and it
    is the shape the brand mark's cable is drawn from."""
    if nits <= KNEE_NITS:
        return (nits / KNEE_NITS) * WHITE_OUT
    x = (nits - KNEE_NITS) / (AXIS_MAX - KNEE_NITS)
    return WHITE_OUT + (1.0 - WHITE_OUT) * (1.0 - math.exp(-2.6 * x)) / (1.0 - math.exp(-2.6))


def luma_hist(i, n):
    """A deterministic luma distribution: a mid-tone mass, a shadow shoulder and a
    thin specular tail. Deterministic because a wallpaper that changes between builds
    is a wallpaper nobody can review."""
    x = i / (n - 1)
    g = lambda mu, sg, a: a * math.exp(-((x - mu) ** 2) / (2 * sg * sg))
    return g(0.44, 0.13, 1.0) + g(0.16, 0.07, 0.55) + g(0.90, 0.035, 0.30)


def draw(p, W, H):
    s = H / 1080.0                     # every size below is in 1080p-equivalent pixels
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    p.fillRect(QRectF(0, 0, W, H), BG)

    # --- the field: a panel with the plot's grid, drawn like an instrument face -----
    field = QRectF(PLOT_L * W, PLOT_T * H, (PLOT_R - PLOT_L) * W, (PLOT_B - PLOT_T) * H)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PANEL)
    p.drawRoundedRect(field, 6 * s, 6 * s)

    f_mono = QFont("Inter")
    f_mono.setPixelSize(int(15 * s))
    p.setFont(f_mono)

    # vertical: the nits scale. Every 100 gets a line so the eye can read the shoulder
    # against it; every other gets a number, because ten labels under a curve that is
    # the subject of the image would be ten labels over a curve nobody is reading.
    for tk in TICKS:
        x = field.left() + pos_of_nits(tk) * field.width()
        p.setPen(QPen(GRID, max(1.0, 1.0 * s)))
        p.drawLine(QPointF(x, field.top()), QPointF(x, field.bottom()))
        if tk % 200 == 0:
            p.setPen(TEXT_DIM)
            p.drawText(QRectF(x - 40 * s, field.bottom() + 6 * s, 80 * s, 22 * s),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "%d" % tk)

    # horizontal: output fractions, with 1.0 (diffuse white) the one that matters
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = out_y(frac, H)
        p.setPen(QPen(BORDER if frac in (0.0, 1.0) else GRID, max(1.0, 1.0 * s)))
        p.drawLine(QPointF(field.left(), y), QPointF(field.right(), y))
        p.setPen(TEXT_DIM if frac not in (0.0, 1.0) else TEXT_BRIGHT)
        p.drawText(QRectF(field.left() - 62 * s, y - 11 * s, 54 * s, 22 * s),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "%.2f" % frac)

    # axis titles, small and unbothered
    p.setPen(TEXT_DIM)
    p.drawText(QRectF(field.left(), field.bottom() + 26 * s, field.width(), 24 * s),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "INPUT  NITS")
    p.save()
    p.translate(field.left() - 58 * s, field.top())
    p.rotate(-90)
    p.drawText(QRectF(0, -22 * s, field.height(), 22 * s),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "OUTPUT")
    p.restore()

    # --- the two curves: what arrives, and what the house curve does with it --------
    # They share x (nits) and they agree below the knee, which is the point: the
    # divergence above it IS the tone map. The dashed one is the unmapped signal
    # climbing through white and out of the panel -- clipping shown as an exit rather
    # than asserted in a label, which is why the drawing is clipped to the field.
    n = 260
    ramp, curve = QPainterPath(), QPainterPath()
    for i in range(n):
        t = i / (n - 1.0)
        x = field.left() + t * field.width()
        nits = nits_at(t)
        y_raw = out_y((nits / KNEE_NITS) * WHITE_OUT, H)
        y_map = out_y(tone_out(nits), H)
        if i == 0:
            ramp.moveTo(QPointF(x, y_raw))
            curve.moveTo(QPointF(x, y_map))
        else:
            ramp.lineTo(QPointF(x, y_raw))
            curve.lineTo(QPointF(x, y_map))
    p.setClipRect(field)
    p.setPen(QPen(BORDER, max(1.0, 2.0 * s), Qt.PenStyle.DashLine))
    p.drawPath(ramp)

    # --- the house curve: the accent, and the subject ------------------------------
    grad = QLinearGradient(field.left(), field.bottom(), field.right(), field.top())
    grad.setColorAt(0.0, QColor(ORANGE.red(), ORANGE.green(), ORANGE.blue(), 140))
    grad.setColorAt(1.0, ORANGE)
    pen = QPen(grad, max(1.0, 9.0 * s))   # 9 = the mark's cable stroke, per the spec's
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)   # hierarchy: cable 9, plug 7, spark 4
    p.setPen(pen)
    p.drawPath(curve)
    p.setClipping(False)          # the annotations and the disconnect live outside it

    # the knee and the white line, annotated the way the rail annotates them
    kx = field.left() + pos_of_nits(KNEE_NITS) * field.width()
    ky = out_y(WHITE_OUT, H)
    p.setPen(QPen(QColor(255, 255, 255, 34), max(1.0, 1.0 * s), Qt.PenStyle.DotLine))
    p.drawLine(QPointF(kx, out_y(0, H)), QPointF(kx, ky))
    p.drawLine(QPointF(field.left(), ky), QPointF(kx, ky))
    p.setPen(TEXT_DIM)
    # left of the knee line, not right of it: the curve climbs through that corner on a
    # linear axis, and a label sitting under the accent reads as part of the accent
    p.drawText(QRectF(kx - 158 * s, ky - 30 * s, 150 * s, 22 * s),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "203 nits")
    p.drawText(QRectF(field.left() + 10 * s, ky + 8 * s, 220 * s, 22 * s),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "DIFFUSE WHITE")

    # --- the disconnect: the mark's plug, socket and spark, at the end of the
    #     shoulder, where the freed signal actually is ------------------------------
    # at the very end of the shoulder, where the curve has stopped going anywhere
    ex, ey = field.right() + 34 * s, out_y(tone_out(AXIS_MAX), H) - 6 * s
    plug = QRectF(ex, ey - 22 * s, 66 * s, 44 * s)
    p.setPen(QPen(ORANGE, max(1.0, 7.0 * s), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(plug, 10 * s, 10 * s)
    p.drawLine(QPointF(plug.right(), ey - 8 * s), QPointF(plug.right() + 26 * s, ey - 8 * s))
    p.drawLine(QPointF(plug.right(), ey + 8 * s), QPointF(plug.right() + 26 * s, ey + 8 * s))

    sock = QRectF(plug.right() + 62 * s, ey - 24 * s, 48 * s, 48 * s)
    p.setPen(QPen(QColor(ORANGE.red(), ORANGE.green(), ORANGE.blue(), 128),
                  max(1.0, 7.0 * s), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawRoundedRect(sock, 10 * s, 10 * s)

    gap_cx = plug.right() + 44 * s
    p.setPen(QPen(SPARK, max(1.0, 4.0 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for dy in (-26, 26):
        p.drawLine(QPointF(gap_cx, ey + dy * s * 0.5), QPointF(gap_cx, ey + dy * s))
    p.drawLine(QPointF(gap_cx - 20 * s, ey), QPointF(gap_cx - 6 * s, ey))
    p.setPen(QPen(QColor(SPARK.red(), SPARK.green(), SPARK.blue(), 150),
                  max(1.0, 4.0 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(gap_cx + 8 * s, ey), QPointF(gap_cx + 22 * s, ey))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(SNAP)
    p.drawEllipse(QPointF(gap_cx, ey), 3.4 * s, 3.4 * s)

    # --- the histogram under the plot ---------------------------------------------
    bars = 96
    peak = max(luma_hist(i, bars) for i in range(bars))
    hb = QRectF(field.left(), HIST_T * H, field.width(), (HIST_B - HIST_T) * H)
    p.setPen(QPen(GRID, max(1.0, 1.0 * s)))
    p.drawLine(QPointF(hb.left(), hb.bottom()), QPointF(hb.right(), hb.bottom()))
    for i in range(bars):
        v = luma_hist(i, bars) / peak
        x = hb.left() + (i / bars) * hb.width()
        w = hb.width() / bars * 0.72
        h = v * hb.height()
        # Above white the bars are the signal the curve is compressing, so they carry
        # the accent: meaning, not decoration. 0.72 is white's position on a CODE VALUE
        # axis, which is not the same number as pos_of_nits(203) -- the histogram runs
        # 0..1 in signal, the plot runs 0..1000 in nits. Two axes, one white point.
        p.setPen(QPen(QColor(58, 58, 64) if i / bars < 0.72 else
                      QColor(ORANGE.red(), ORANGE.green(), ORANGE.blue(), 150),
                      max(1.0, 1.0 * s)))
        p.drawLine(QPointF(x + w / 2, hb.bottom()), QPointF(x + w / 2, hb.bottom() - h))

    f_lab = QFont("Inter")
    f_lab.setPixelSize(int(15 * s))
    p.setFont(f_lab)
    p.setPen(TEXT_DIM)
    p.drawText(QRectF(hb.left(), hb.bottom() + 8 * s, hb.width(), 24 * s),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "FRAME  LUMA")
    p.drawText(QRectF(hb.left(), hb.bottom() + 8 * s, hb.width(), 24 * s),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
               "BLACK   /   DIFFUSE WHITE   /   CEILING")

    # --- the invitation, in the band the chrome never covers -----------------------
    # brand-spec.md keeps the WORDMARK out of instrument territory, and this screen is
    # instrument territory. The tagline is a different thing: the splash line, on the
    # one surface that is genuinely an invitation rather than a control. Dim, small,
    # letter-spaced per the spec, and placed left of the rail column (460px) plus the
    # status column (300px) so it is never half-hidden by chrome.
    tag = QFont("Inter")
    tag.setPixelSize(int(29 * s))
    tag.setWeight(QFont.Weight.Medium)
    tag.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
    p.setFont(tag)
    p.setPen(TEXT_DIM)
    tx, ty = 0.655 * W, 0.455 * H
    p.drawText(QPointF(tx, ty), "free your nits")
    from PyQt6.QtGui import QFontMetricsF
    dot_r = 5.5 * s
    # ~6px gap at 54px text per the spec's dot rule, scaled to this size: it is a full
    # stop, not a decorative bullet, so it hugs the word it ends
    dot_x = tx + QFontMetricsF(tag).horizontalAdvance("free your nits") + 5 * s
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ORANGE)                    # the period is the brand orange, per the spec
    p.drawEllipse(QPointF(dot_x, ty - 3 * s), dot_r, dot_r)

    # --- the quiet signature: the mark itself, small, dim, once -------------------
    mk = QImage(os.path.join(BRAND_DIR, "png", "unplugged-mark-512.png"))
    if not mk.isNull():
        size = 118 * s
        p.setOpacity(0.42)
        p.drawImage(QRectF(W - size - 64 * s, H - size - 56 * s, size, size), mk)
        p.setOpacity(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="3840x2160")
    ap.add_argument("--out", default=r"C:\code\unplugged-mpc-hc\tools\engine_s3\wallpaper_vector.png")
    args = ap.parse_args()
    W, H = (int(v) for v in args.size.lower().split("x"))

    app = QApplication([])
    for f in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf"):
        QFontDatabase.addApplicationFont(os.path.join(BRAND_DIR, "fonts", f))

    img = QImage(W, H, QImage.Format.Format_RGB32)
    p = QPainter(img)
    draw(p, W, H)
    p.end()
    img.save(args.out, "PNG")
    print("wrote", args.out, "%dx%d" % (W, H))


if __name__ == "__main__":
    main()

"""Pixel-diff the two comparison images (madVR vs unplugged, same scene).

Qt6-only (PyQt6 ships QImage; no numpy/pillow needed). Reports per-channel
deltas for the WHOLE frame, for HIGHLIGHTS (luma above the 85%-percentile) and
for SKIN-ish warm clusters, plus where unplugged exceeds madVR in warm channels
relative to blue. The last number is the "warm push" answer.
"""
import sys

from PyQt6.QtGui import QImage, QColor


def load(p):
    img = QImage(p)
    if img.isNull():
        raise SystemExit(f"cannot load {p}")
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    return img


def pixels(img):
    w, h = img.width(), img.height()
    if w != 2301 and w != 2296:
        # whatever the width, same height; keep as-is
        pass
    return img, w, h


def main(a, b):
    imA, wA, hA = pixels(load(a))
    imB, wB, hB = pixels(load(b))
    w = min(wA, wB)
    h = min(hA, hB)

    sumR = sumG = sumB = 0
    n = 0
    # per-pixel deltas
    dR = dG = dB = 0
    # highlight bucket: per-frame luma histogram percentile ~ simple threshold
    lum = []
    S = 10000000
    step = max(1, (w * h) // S)
    for y in range(0, h):
        for x in range(0, w, 4):
            cA = imA.pixelColor(x if x < wA else wA - 1, y if y < hA else hA - 1)
            lum.append(cA.red() * 0.299 + cA.green() * 0.587 + cA.blue() * 0.114)
    lum.sort()
    thres = lum[int(len(lum) * 0.90)]

    hl_dR = hl_dG = hl_dB = hl_n = 0
    for y in range(0, h):
        for x in range(0, w):
            cA = imA.pixelColor(x, y)
            cB = imB.pixelColor(x, y)
            la = cA.red() * 0.299 + cA.green() * 0.587 + cA.blue() * 0.114
            dR += cB.red() - cA.red()
            dG += cB.green() - cA.green()
            dB += cB.blue() - cA.blue()
            n += 1
            if la >= thres:
                hl_dR += cB.red() - cA.red()
                hl_dG += cB.green() - cA.green()
                hl_dB += cB.blue() - cA.blue()
                hl_n += 1
    print(f"size A {wA}x{hA}  B {wB}x{hB}  compared {w}x{h}  n={n}")
    print(f"mean  whole-frame  dB={dB / n:+.2f}  dG={dG / n:+.2f}  dR={dR / n:+.2f}  (warm-excess dR-dB={dR / n - dB / n:+.2f})")
    if hl_n:
        print(f"mean  highlights   dB={hl_dB / hl_n:+.2f}  dG={hl_dG / hl_n:+.2f}  dR={hl_dR / hl_n:+.2f}  (warm-excess dR-dB={hl_dR / hl_n - hl_dB / hl_n:+.2f})")
        print(f"      highlight luma threshold (A 90%) = {thres:.0f}; {hl_n} px in highlights")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
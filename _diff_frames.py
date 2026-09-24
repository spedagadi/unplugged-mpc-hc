"""Align + pixel-diff two screen grabs, report channel casts (yellow = (R+G)/2 - B).

Optionally scale image B to image A's size first (bicubic) so both are the SAME
frame at the SAME resolution. Reports whole-frame and highlight-region stats.
"""
import sys

from PyQt6.QtGui import QImage
from PyQt6.QtCore import Qt


def load(p):
    img = QImage(p)
    if img.isNull():
        raise SystemExit(f"cannot load {p}")
    return img.convertToFormat(QImage.Format.Format_RGB32)


def stats(img, thres=-1):
    w, h = img.width(), img.height()
    sR = sG = sB = n = 0
    hR = hG = hB = hn = 0
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            la = r * 0.299 + g * 0.587 + b * 0.114
            sR += r; sG += g; sB += b; n += 1
            if la >= thres:
                hR += r; hG += g; hB += b; hn += 1
    return (sR / n, sG / n, sB / n), (hR / hn, hG / hn, hB / hn, hn)


def main(a, b):
    imA = load(a)
    imB = load(b)
    if imB.size() != imA.size():
        imB = imB.scaled(imA.width(), imA.height(),
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        print(f"scaled B -> {imA.width()}x{imA.height()}")
    (mA, aH) = stats(imA, 200)
    (mB, bH) = stats(imB, 200)
    print(f"A {a.split(chr(92))[-1]}  mean BGR=({mA[2]:.1f},{mA[1]:.1f},{mA[0]:.1f})  yellow={((mA[1]+mA[0])/2 - mA[2]):+.1f}")
    print(f"B {b.split(chr(92))[-1]}  mean BGR=({mB[2]:.1f},{mB[1]:.1f},{mB[0]:.1f})  yellow={((mB[1]+mB[0])/2 - mB[2]):+.1f}")
    print(f"B-A whole  dB={mB[2]-mA[2]:+.2f} dG={mB[1]-mA[1]:+.2f} dR={mB[0]-mA[0]:+.2f}  yellow-Δ={((mB[1]+mB[0])/2-mB[2])-((mA[1]+mA[0])/2-mA[2]):+.2f}")
    if aH[3] and bH[3]:
        print(f"highlights(>200): A=({aH[2]:.1f},{aH[1]:.1f},{aH[0]:.1f}) [{aH[3]}px]  yellow={((aH[1]+aH[0])/2-aH[2]):+.1f}")
        print(f"                  B=({bH[2]:.1f},{bH[1]:.1f},{bH[0]:.1f}) [{bH[3]}px]  yellow={((bH[1]+bH[0])/2-bH[2]):+.1f}")
        print(f"                  B-A  dB={bH[2]-aH[2]:+.2f} dG={bH[1]-aH[1]:+.2f} dR={bH[0]-aH[0]:+.2f}  yellow-Δ={((bH[1]+bH[0])/2-bH[2])-((aH[1]+aH[0])/2-aH[2]):+.2f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
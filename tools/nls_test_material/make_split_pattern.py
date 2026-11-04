# Builds a 2.39:1 test frame for the NLS Axis comparison:
#   - a perfect circle at the centre (aspect probe)
#   - a square grid (spacing probe)
#   - vertical and horizontal ruler ticks (absolute scale probe)
# The clip is static, so a paused grab is the same frame every time.
from PIL import Image, ImageDraw, ImageFont
import subprocess, os

W, H = 1920, 804          # 2.39:1 active picture
img = Image.new("RGB", (W, H), (0, 0, 0))
d = ImageDraw.Draw(img)

# Grid: 120 px cells, dim grey so the white probes stand out.
for x in range(0, W + 1, 120):
    d.line([(x, 0), (x, H)], fill=(70, 70, 70), width=1)
for y in range(0, H + 1, 120):
    d.line([(0, y), (W, y)], fill=(70, 70, 70), width=1)

# Centre circle: radius 160 source pixels, pure white 6 px rim.
cx, cy, r = W // 2, H // 2, 160
d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=6)

# A face-proportion rectangle inside the circle (eye line + chin) so an
# anisotropic centre is visible as changed proportions, not just an ellipse.
fw, fh = 120, 170
d.rectangle([cx - fw // 2, cy - fh // 2, cx + fw // 2, cy + fh // 2],
            outline=(230, 230, 230), width=3)
d.line([(cx - fw // 2, cy - 30), (cx + fw // 2, cy - 30)], fill=(230, 230, 230), width=3)

# Rulers: 20 px ticks every 40 px, longer every 200 px.
for x in range(0, W, 40):
    t = 28 if x % 200 == 0 else 14
    d.line([(x, 0), (x, t)], fill=(200, 200, 200), width=3)
for y in range(0, H, 40):
    t = 28 if y % 200 == 0 else 14
    d.line([(0, y), (t, y)], fill=(200, 200, 200), width=3)

# Crosshair at the exact centre.
d.line([(cx - 260, cy), (cx + 260, cy)], fill=(255, 120, 60), width=2)
d.line([(cx, cy - 260), (cx, cy + 260)], fill=(255, 120, 60), width=2)

try:
    font = ImageFont.truetype("arialbd.ttf", 42)
except Exception:
    font = ImageFont.load_default()
d.text((40, H - 70), "NLS AXIS TEST  -  circle + grid + face box", fill=(255, 255, 255), font=font)

src = os.path.join(os.path.dirname(__file__), "split_probe.png")
out = os.path.join(os.path.dirname(__file__), "nls_split_probe.mp4")
img.save(src)

ffmpeg = r"C:\htpc\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
subprocess.run([ffmpeg, "-y", "-loop", "1", "-i", src, "-t", "5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", out],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(out)
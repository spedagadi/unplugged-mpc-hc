"""Bidirectional-NLS regression check.

The geometry and the warp shader are mirrored here in Python, so a sign error or
a broken shader shows up as a failed invariant instead of a wrong picture that
nobody can measure. Run it after touching NlsShader.h or the NLS block of
MpcPlayer::ResizeVideo().

    python -I tools/engine_s3/nls_math_check.py [fxc.exe]

The optional fxc argument also compiles the GENERATED shader source (the same
substitutions nls::Source() makes) for ps_4_0, so a syntax error is caught here
rather than as a silent failed injection at runtime.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHADER_H = os.path.join(HERE, "..", "..", "src", "mpchc_engine", "NlsShader.h")

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(f"{name} {detail}")
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail else ""))


# ---------------------------------------------------------------- engine model
# Mirrors MpcPlayer::ResizeVideo(): the correction k is split by share s,
# sx / sy == k (the aspect correction), sx * sy == 1 at s = 0.5 (area kept),
# each axis capped by Max distortion, the residue covered by cropping the axis
# that has slack.
def engine_model(k, s, cap=None):
    sx = k ** s
    sy = k ** (s - 1.0)
    if cap is not None:
        sx = min(max(sx, 1.0 / cap), cap)
        sy = min(max(sy, 1.0 / cap), cap)
    residue = k * sy / sx
    cx = 1.0 / residue if residue < 0.999 else 1.0
    cy = residue if residue > 1.001 else 1.0
    return sx, sy, cx, cy


def centre_anisotropy(k, sx, sy, cx, cy):
    # k: the renderer's own fill anisotropy, cx/cy: per-axis geometry zoom,
    # sx/sy: what the shader takes back out at the protected centre. 1.0 == the
    # centre is undistorted.
    return k * (cx / cy) * (sy / sx)


def old_horizontal(k, stretch, cap):
    wr = k if k < 1.0 else (k if stretch else min(k, cap))
    cs = (k / wr) if (k >= 1.0 and not stretch) else 1.0
    return wr, cs


# Mirrors NlsFillAction(): 0 none, 1 warp, 2 crop.
def fill_action(clientAR, activeAR, bandValid, mode, fillLimit, axis, split, cap):
    if mode == 3:
        return 0
    if mode == 2:
        return 2
    if mode == 1:
        return 1
    k = clientAR / activeAR
    within = (k >= 1.0) or (1.0 / k <= max(1.0, min(fillLimit, 2.0)))
    sx, sy = engine_model(k, 1.0 if axis != 2 and axis != 3 else (0.0 if axis == 2 else split),
                          None)[:2]
    worst = max(max(sx, 1.0 / sx), max(sy, 1.0 / sy))
    budget = worst > max(1.0, cap) + 1e-9
    return 1 if ((within or budget) and bandValid) else 0


def test_engine():
    scope16x9 = 1.7778 / 2.39

    # Axis = Horizontal must be exactly what shipped before the split existed.
    for k in (scope16x9, 0.98, 1.0, 1.02, 1.333, 2.0):
        for stretch in (False, True):
            wr, _cs = old_horizontal(k, stretch, 1.4)
            sx, sy, cx, _cy = engine_model(k, 1.0, None if stretch else 1.4)
            check(f"horizontal regression k={k:.4f} stretch={stretch}",
                  abs(sx - wr) < 1e-9 and abs(sy - 1.0) < 1e-12 and abs(cx - 1.0) < 1e-12,
                  f"sx={sx:.4f} old={wr:.4f}")

    # Axis = Vertical is the same correction paid on the other axis.
    k = 1.7778 / 2.35
    sx, sy, _cx, _cy = engine_model(k, 0.0)
    check("vertical-only axis", abs(sx - 1.0) < 1e-12 and abs(sy - 1.0 / k) < 1e-9,
          f"sx={sx:.4f} sy={sy:.4f} (1/k={1 / k:.4f})")

    # The operator's acceptance case: 2.35 title on 3840x2160, split 50,
    # Max distortion 110.
    sx, sy, cx, cy = engine_model(k, 0.5, 1.10)
    check("split 50 warps both axes within 10%",
          abs(sx - 1) <= 0.10 + 1e-9 and abs(sy - 1) <= 0.10 + 1e-9,
          f"sx={sx:.4f} sy={sy:.4f}")
    check("split 50 crops the slack axis", max(cx, cy) > 1.0, f"cx={cx:.4f} cy={cy:.4f}")
    check("split 50 keeps the protected centre undistorted",
          abs(centre_anisotropy(k, sx, sy, cx, cy) - 1.0) < 0.01)
    check("split 50 keeps image area at the axes", abs(sx * sy - 1.0) < 1e-9)

    # Uncapped split: no crop, centre still exact.
    sx, sy, cx, cy = engine_model(k, 0.5)
    check("uncapped split needs no crop", abs(cx - 1) < 1e-9 and abs(cy - 1) < 1e-9)
    check("uncapped split centre exact",
          abs(centre_anisotropy(k, sx, sy, cx, cy) - 1.0) < 1e-9)

    # Stretch mode must never crop.
    for k in (0.6, 0.744, 1.0, 1.5):
        _sx, _sy, cx, cy = engine_model(k, 0.5, None)
        check(f"stretch never crops k={k}", abs(cx - 1) < 1e-9 and abs(cy - 1) < 1e-9)

    # The invariance that makes the split safe: whatever the split and cap, the
    # geometry crop makes the protected centre undistorted.
    worst = 0.0
    for k in [1.7778 / a for a in (1.33, 1.5, 1.78, 2.0, 2.35, 2.76)]:
        for s in (0.0, 0.25, 0.5, 0.75, 1.0):
            for cap in (1.0, 1.05, 1.10, 1.4, 1.5):
                sx, sy, cx, cy = engine_model(k, s, cap)
                worst = max(worst, abs(centre_anisotropy(k, sx, sy, cx, cy) - 1.0))
    check("centre isotropic over split/cap grid", worst < 0.002, f"worst={worst:.5f}")

    # --- the Auto gate: no change for a traditional setup at the default cap ----
    s16 = 1.7778          # 16:9 window
    scope = 2.39
    uw = 2.76             # wider than scope
    # No change where Auto already filled (k >= 1: a picture narrower than the window).
    for name, cl, ac in [("16:9 content on a scope screen", scope, s16),
                         ("4:3 content on 16:9", s16, 4 / 3)]:
        check(f"auto fills, unchanged: {name}", fill_action(cl, ac, True, 0, 1.05, 1, 1.0, 1.4) == 1)
    # No change where Auto letterboxed (default cap above the correction).
    for name, cl, ac in [("scope on 16:9, default cap", s16, scope),
                         ("ultra-wide on a scope screen, default cap", scope, uw)]:
        check(f"auto letterboxes, unchanged: {name}",
              fill_action(cl, ac, True, 0, 1.05, 1, 1.0, 1.4) == 0)
    # The new capability: an explicit budget below the correction fills and crops.
    for name, cl, ac in [("scope on 16:9, cap 110", s16, scope),
                         ("ultra-wide on scope, cap 110", scope, uw)]:
        check(f"auto fills with an explicit budget: {name}",
              fill_action(cl, ac, True, 0, 1.05, 1, 1.0, 1.1) == 1)
    # Budget or not, a band still has to be confirmed.
    check("no band, no fill", fill_action(s16, scope, False, 0, 1.05, 1, 1.0, 1.1) == 0)
    # Stretch / Crop / Off keep their meaning.
    check("stretch always fills", fill_action(s16, scope, True, 1, 1.05, 1, 1.0, 1.4) == 1)
    check("crop mode is crop", fill_action(s16, scope, True, 2, 1.05, 1, 1.0, 1.4) == 2)
    check("off never fills", fill_action(s16, scope, True, 3, 1.05, 1, 1.0, 1.4) == 0)


# ---------------------------------------------------------------- shader model
def map_radius(r, ratio0, strength, center, curve):
    ratio = 1.0 + (ratio0 - 1.0) * min(max(strength, 0.0), 1.0)
    if abs(ratio - 1.0) <= 0.001:
        return r
    if center <= 0.0001:
        return ratio * r - (ratio - 1.0) * r ** curve
    c = min(center, 0.45)
    if r <= c:
        return r * ratio
    span = max(1.0 - c, 0.0001)
    t = min(max((r - c) / span, 0.0), 1.0)
    t2, t3, t4, t5 = t * t, t * t * t, t * t * t * t, t * t * t * t * t
    h00 = 1 - 10 * t3 + 15 * t4 - 6 * t5
    h10 = t - 6 * t3 + 8 * t4 - 3 * t5
    h01 = 10 * t3 - 15 * t4 + 6 * t5
    h11 = -4 * t3 + 7 * t4 - 3 * t5
    start = c * ratio
    edge = max(0.30, 1.0 - (ratio - 1.0) * curve)
    return h00 * start + h10 * span * ratio + h01 + h11 * span * edge


def test_shader_model():
    bad = []
    for center in (0.0, 0.2, 0.35, 0.45):
        for curve in (1.0, 1.5, 2.0, 2.9):
            for ratio in (0.5, 0.7, 0.85, 0.95, 1.0, 1.05, 1.15, 1.4):
                prev = -1.0
                for i in range(1001):
                    m = map_radius(i / 1000.0, ratio, 1.0, center, curve)
                    if m < prev - 1e-6:
                        bad.append((center, curve, ratio, i / 1000.0))
                        break
                    prev = m
                if abs(map_radius(1.0, ratio, 1.0, center, curve) - 1.0) > 1e-6:
                    bad.append((center, curve, ratio, "endpoint"))
    check("map_radius monotone, fixed endpoints", not bad, str(bad[:3]))

    check("map_radius is the identity at ratio 1",
          all(abs(map_radius(i / 100.0, 1.0, 1.0, 0.35, 2.0) - i / 100.0) < 1e-12
              for i in range(101)))

    # Half strength must stay closer to the identity than full strength.
    ok = True
    for ratio in (0.6, 0.744, 1.15, 1.4):
        for r in (0.05, 0.1, 0.3, 0.6, 0.9):
            half = map_radius(r, ratio, 0.5, 0.35, 2.0)
            full = map_radius(r, ratio, 1.0, 0.35, 2.0)
            if abs(half - r) > abs(full - r) + 1e-9:
                ok = False
    check("strength scales toward the identity", ok)


def test_shader_compiles(fxc):
    src = open(SHADER_H, encoding="utf-8").read()
    m = re.search(r'R"SHADER\((.*?)\)SHADER"', src, re.S)
    if not m:
        check("NlsShader.h contains a shader source", False)
        return
    body = m.group(1)
    subs = {
        "__AL__": "0.0", "__AT__": "0.0", "__AR__": "1.0", "__AB__": "1.0",
        "__RX__": "0.87", "__RY__": "1.15", "__STRENGTH__": "1.0",
        "__CENTER__": "0.35", "__CURVE__": "2.0",
    }
    for key, val in subs.items():
        body = body.replace(key, val)
    if "__" in re.sub(r"^\s*//.*$", "", body, flags=re.M):
        check("every shader macro substituted", False,
              str(re.findall(r"__[A-Z_]+__", body)))
    if not fxc:
        print("SKIP shader compile (no fxc given)")
        return
    with tempfile.TemporaryDirectory() as td:
        hlsl = os.path.join(td, "nls.hlsl")
        cso = os.path.join(td, "nls.cso")
        open(hlsl, "w", encoding="utf-8").write(body)
        p = subprocess.run([fxc, "/nologo", "/T", "ps_4_0", "/E", "main",
                            "/Fo", cso, hlsl],
                           capture_output=True, text=True)
        check("generated shader compiles for ps_4_0", p.returncode == 0,
              (p.stdout + p.stderr).strip()[:400])


if __name__ == "__main__":
    test_engine()
    test_shader_model()
    test_shader_compiles(sys.argv[1] if len(sys.argv) > 1 else None)
    print()
    print("FAILURES:", len(failures))
    for f in failures:
        print("  ", f)
    sys.exit(1 if failures else 0)
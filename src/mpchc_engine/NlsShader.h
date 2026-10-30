// NlsShader.h - Unplugged's own nonlinear-stretch pass.
//
// Delivered through MPCVR's existing post-scale custom-shader chain (the same
// route as PostFxShaders.h): no renderer ABI change, compiled at ps_4_0, applied
// after grading and before subtitles.
//
// Geometry is baked because the shared post-scale cbuffer has no user slots.
// The active picture is measured by the engine (renderer bar detection plus the
// destination rectangle) and baked as normalized bounds; this pass maps that
// active rectangle onto the full window along the chosen axis, so the encoded
// letterbox does not survive the warp.
#pragma once

#include <string>
#include "PostFxShaders.h"

namespace nls {

struct Params {
    float activeL = 0.0f, activeT = 0.0f, activeR = 1.0f, activeB = 1.0f;
    // The aspect correction, SPLIT across the two axes. Each axis is mapped by
    // its own factor and its own protected centre, so neither axis has to carry
    // the whole distortion. ratioX * ratioY == 1 at an even split (image area
    // kept) and ratioX / ratioY is the aspect correction itself, so
    //   (ratioX, ratioY) == (k, 1)   is exactly the old horizontal-only pass,
    //   (ratioX, ratioY) == (1, 1/k) is the vertical-only equivalent.
    // A factor of 1 on an axis is the identity map for that axis.
    float ratioX = 1.0f;      // horizontal axis correction
    float ratioY = 1.0f;      // vertical axis correction
    float strength = 1.0f;    // 0..1
    float center = 0.35f;     // protected centre fraction
    float curve = 2.0f;       // 1..2.9
};

inline std::string Source(const Params& p)
{
    std::string s = R"SHADER(
// Unplugged NLS - active picture -> full screen, protected centre.
// $MinimumShaderProfile: ps_4_0
Texture2D tex : register(t0);
SamplerState samp : register(s0);
cbuffer PS_CONSTANTS : register(b0)
{
    float px;
    float py;
    float2 wh;
    uint  counter;
    float clock;
};
#define ACTIVE_L  __AL__
#define ACTIVE_T  __AT__
#define ACTIVE_R  __AR__
#define ACTIVE_B  __AB__
#define RATIO_X   __RX__
#define RATIO_Y   __RY__
#define STRENGTH  __STRENGTH__
#define CENTER    __CENTER__
#define CURVE     __CURVE__

// The post-scale pass binds a POINT sampler at s0 (DX11VideoProcessor::
// TextureCopyRect -> m_pSamplerPoint), so a plain tex.Sample() here fetches the
// NEAREST texel. The warp moves every pixel a fraction of a texel, so on text that
// showed up as stair-stepped edges ("rugged text" in the streaming UI, chrome up or
// down - the warp runs either way). This does bilinear explicitly with four taps, so
// the result does not depend on which sampler the pass happens to bind.
float4 sampleBilinear(float2 uv)
{
    float2 texel = float2(px, py);          // cbuffer: 1/width, 1/height
    float2 pos = uv / texel - 0.5;
    float2 f = frac(pos);
    float2 base = (floor(pos) + 0.5) * texel;
    float4 c00 = tex.Sample(samp, base);
    float4 c10 = tex.Sample(samp, base + float2(texel.x, 0.0));
    float4 c01 = tex.Sample(samp, base + float2(0.0, texel.y));
    float4 c11 = tex.Sample(samp, base + texel);
    return lerp(lerp(c00, c10, f.x), lerp(c01, c11, f.x), f.y);
}

float map_radius(float r, float ratio0)
{
    float ratio = lerp(1.0, ratio0, saturate(STRENGTH));
    // RATIO > 1 stretches the outer band (window wider than the picture);
    // RATIO < 1 squeezes it (picture wider than the window). Both are the same
    // monotone map: slope RATIO at the protected centre, easing to the edge.
    if (abs(ratio - 1.0) <= 0.001) return r;
    if (CENTER <= 0.0001)
    {
        // Smooth power curve over the whole radius: no internal boundary, and
        // monotone for ratio either side of 1 (all terms stay positive) - as long
        // as the slope at r=1 is still positive: ratio - (ratio-1)*curve >= 0.
        // An uncapped ratio (Stretch mode) with a high curve would fold the
        // outermost pixels back on themselves, so the curve is bounded by that
        // rather than by the slider.
        float cv = (ratio > 1.0) ? min(CURVE, ratio / max(ratio - 1.0, 0.001))
                                 : CURVE;
        return ratio * r - (ratio - 1.0) * pow(r, cv);
    }
    // THE PROTECTED CENTRE MAY RUN ALMOST TO THE EDGE. It used to be clamped at
    // 0.45, which put the whole transition inside the middle half of the screen:
    // anything between 72 % and the edge was stretched/squeezed, and a face
    // sitting there read as elongated. Raising it confines the correction to a
    // rim, and inside the protected region the map is a uniform scale per axis -
    // i.e. no distortion at all, only zoom - so the middle of the picture stays
    // clean and the rim takes the whole redistribution.
    //
    // The limit is arithmetic, not taste: the linear segment ends at c*ratio, so
    // a squeeze (ratio < 1) is always safe, while a stretch needs c < ~1/ratio,
    // and 2/ratio - 1 keeps the ramp gentle enough for the Hermite below to stay
    // monotone. (Verified for ratio 0.5..1.5, centre 0..0.94, curve 1..2.9.)
    float cmax = (ratio > 1.0) ? max(0.0, min(0.94, 2.0 / ratio - 1.0)) : 0.94;
    float c = min(max(CENTER, 0.0), cmax);
    if (r <= c) return r * ratio;
    float span = max(1.0 - c, 0.02);
    float t = saturate((r - c) / span);
    float t2 = t * t, t3 = t2 * t, t4 = t3 * t, t5 = t4 * t;
    // QUINTIC Hermite: matches value, slope AND curvature at both ends, so the
    // mapping never changes curvature abruptly — a cubic matches only the first
    // two, and that is visible as objects "twisting" during a lateral pan.
    float h00 = 1.0 - 10.0*t3 + 15.0*t4 - 6.0*t5;
    float h10 = t - 6.0*t3 + 8.0*t4 - 3.0*t5;
    float h01 = 10.0*t3 - 15.0*t4 + 6.0*t5;
    float h11 = -4.0*t3 + 7.0*t4 - 3.0*t5;
    float startPosition = c * ratio;
    float startSlope = ratio;
    float edgeSlope = max(0.30, 1.0 - (ratio - 1.0) * CURVE);
    // A short rim ramp would otherwise ask the fixed edge slope for more than the
    // segment can give and fold back on itself. Applied only where the shape is
    // NEW (centre > 45 %) or the ratio is extreme (uncapped Stretch beyond 1.5),
    // so every existing setting keeps the curve it has today.
    if (c > 0.45 || ratio > 1.5)
        edgeSlope = min(edgeSlope, 2.0 * ((1.0 - startPosition) / span));
    return h00 * startPosition + h10 * span * startSlope +
           h01 + h11 * span * edgeSlope;
}

// Maps one axis of the picture. The radius is measured INSIDE the active rect,
// so a partial bar fill leaves the top/bottom bars black and untouched instead
// of dragging picture into them; outside the rect the coordinate passes through.
// With the full rect (0..1) this is exactly the old whole-window mapping.
float map_axis(float u, float lo, float hi, float ratio)
{
    float span = max(hi - lo, 0.0001);
    if (u < lo || u > hi) return u;
    float c = ((u - lo) / span) * 2.0 - 1.0;
    float m = map_radius(abs(c), ratio);
    return lerp(lo, hi, (c < 0.0 ? -m : m) * 0.5 + 0.5);
}

float4 main(float4 pos : SV_POSITION, float2 coord : TEXCOORD) : SV_Target
{
    // BOTH axes are mapped, each by its own factor with its own protected
    // centre, so the protected region stays a rectangle instead of a cross.
    // An axis whose factor is 1 is an exact identity (map_radius early-outs),
    // which is what makes the single-axis modes bit-for-bit what they were.
    float2 src = coord;
    src.x = map_axis(coord.x, ACTIVE_L, ACTIVE_R, RATIO_X);
    src.y = map_axis(coord.y, ACTIVE_T, ACTIVE_B, RATIO_Y);
    return sampleBilinear(src);
}
)SHADER";
    postfx::ReplaceAll(s, "__AL__", postfx::F(p.activeL));
    postfx::ReplaceAll(s, "__AT__", postfx::F(p.activeT));
    postfx::ReplaceAll(s, "__AR__", postfx::F(p.activeR));
    postfx::ReplaceAll(s, "__AB__", postfx::F(p.activeB));
    postfx::ReplaceAll(s, "__RX__", postfx::F(p.ratioX));
    postfx::ReplaceAll(s, "__RY__", postfx::F(p.ratioY));
    postfx::ReplaceAll(s, "__STRENGTH__", postfx::F(p.strength));
    postfx::ReplaceAll(s, "__CENTER__", postfx::F(p.center));
    postfx::ReplaceAll(s, "__CURVE__", postfx::F(p.curve));
    return s;
}

} // namespace nls
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
    float ratio = 1.0f;       // content/window aspect correction
    float strength = 1.0f;    // 0..1
    float center = 0.35f;     // protected centre fraction
    float curve = 2.0f;       // 1..2.9
    bool  vertical = true;
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
#define RATIO     __RATIO__
#define STRENGTH  __STRENGTH__
#define CENTER    __CENTER__
#define CURVE     __CURVE__
#define VERTICAL  __VERT__

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

float map_radius(float r)
{
    float ratio = lerp(1.0, RATIO, saturate(STRENGTH));
    // RATIO > 1 stretches the outer band (window wider than the picture);
    // RATIO < 1 squeezes it (picture wider than the window). Both are the same
    // monotone map: slope RATIO at the protected centre, easing to the edge.
    if (abs(ratio - 1.0) <= 0.001) return r;
    if (CENTER <= 0.0001)
    {
        // Smooth power curve over the whole radius: no internal boundary, and
        // monotone for ratio either side of 1 (all terms stay positive).
        return ratio * r - (ratio - 1.0) * pow(r, CURVE);
    }
    float c = min(CENTER, 0.45);
    if (r <= c) return r * ratio;
    float span = max(1.0 - c, 0.0001);
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
    return h00 * startPosition + h10 * span * startSlope +
           h01 + h11 * span * edgeSlope;
}

float4 main(float4 pos : SV_POSITION, float2 coord : TEXCOORD) : SV_Target
{
    float2 src = coord;
    if (VERTICAL > 0.5)
    {
        float c = coord.y * 2.0 - 1.0;
        float m = map_radius(abs(c));
        src.y = (c < 0.0 ? -m : m) * 0.5 + 0.5;
        src.y = lerp(ACTIVE_T, ACTIVE_B, src.y);
        src.x = lerp(ACTIVE_L, ACTIVE_R, src.x);
    }
    else
    {
        float c = coord.x * 2.0 - 1.0;
        float m = map_radius(abs(c));
        src.x = (c < 0.0 ? -m : m) * 0.5 + 0.5;
        src.x = lerp(ACTIVE_L, ACTIVE_R, src.x);
        src.y = lerp(ACTIVE_T, ACTIVE_B, src.y);
    }
    return sampleBilinear(src);
}
)SHADER";
    postfx::ReplaceAll(s, "__AL__", postfx::F(p.activeL));
    postfx::ReplaceAll(s, "__AT__", postfx::F(p.activeT));
    postfx::ReplaceAll(s, "__AR__", postfx::F(p.activeR));
    postfx::ReplaceAll(s, "__AB__", postfx::F(p.activeB));
    postfx::ReplaceAll(s, "__RATIO__", postfx::F(p.ratio));
    postfx::ReplaceAll(s, "__STRENGTH__", postfx::F(p.strength));
    postfx::ReplaceAll(s, "__CENTER__", postfx::F(p.center));
    postfx::ReplaceAll(s, "__CURVE__", postfx::F(p.curve));
    postfx::ReplaceAll(s, "__VERT__", p.vertical ? "1.0" : "0.0");
    return s;
}

} // namespace nls
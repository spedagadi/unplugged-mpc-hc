// PostFxShaders.h — Adaptive Sharpen + Deband delivered to MPCVR through its
// existing post-scale custom-shader injection (IExFilterConfig::Flt_SetBin
// "cmd_addPostScaleShader"). No renderer change: MPCVR compiles these at ps_4_0
// at runtime and runs them in the shared post-scale chain, after the tone-map +
// ML grade and before subtitles/dither — so they act on the final SDR, gamma,
// display-referred image and apply identically to SDR, HDR10->SDR and the
// Dolby-Vision path.
//
// Strength is a #define baked into the source (the shared post-scale cbuffer has
// no user-param slot), so a dial change regenerates the source and re-injects.
// The tunable numbers are inserted via unique tokens, NOT printf, because the HLSL
// bodies contain '%' (the Deband permute() modulo) which would break a format string.
//
// Shader provenance (kept intact):
//   Adaptive sharpen — (c) bacondither, BSD 2-clause, "Adaptive sharpen 2015-06-25",
//     tuned post-resize, expects full-range gamma light.
//   Debanding — SmartDeband port from MPC-HC (GPL), (c) see Authors.txt.
#pragma once

// IExFilterConfig is declared by <FilterInterfaces.h>, which MpcPlayer.cpp already
// includes; this header only builds the shader source + the injection blob and does
// not name the interface itself.

#include <string>
#include <cstdint>
#include <cstdio>
#include <cwchar>

namespace postfx {

inline void ReplaceAll(std::string& s, const std::string& from, const std::string& to)
{
    if (from.empty()) return;
    for (size_t pos = 0; (pos = s.find(from, pos)) != std::string::npos; pos += to.size())
        s.replace(pos, from.size(), to);
}

// fmt a float for an HLSL #define (always a decimal literal, no locale).
inline std::string F(float v)
{
    char b[32];
    snprintf(b, sizeof(b), "%.4f", (double)v);
    return b;
}

// ---------------------------------------------------------------------------
// cmd_addPostScaleShader blob: a sequence of { fourcc(4) | size(4) | bytes }.
// NAME -> wide shader name (size = bytes), CODE -> UTF-8 source (size = bytes).
// Mirrors CMpcVideoRenderer::Flt_SetBin's ReadShaderData exactly.
// ---------------------------------------------------------------------------
inline void AppendChunk(std::string& blob, uint32_t fourcc, const void* data, int32_t size)
{
    blob.append(reinterpret_cast<const char*>(&fourcc), 4);
    blob.append(reinterpret_cast<const char*>(&size), 4);
    blob.append(reinterpret_cast<const char*>(data), size);
}

inline std::string MakeShaderBlob(const wchar_t* name, const std::string& code)
{
    // fourcc 'NAME'/'CODE' little-endian == the 4 chars in order (matches FCC()).
    const uint32_t NAME = 0x454D414Eu; // 'N','A','M','E'
    const uint32_t CODE = 0x45444F43u; // 'C','O','D','E'
    int nameBytes = (int)(wcslen(name) * sizeof(wchar_t));
    std::string blob;
    AppendChunk(blob, NAME, name, nameBytes);
    AppendChunk(blob, CODE, code.data(), (int)code.size());
    return blob;
}

// ---------------------------------------------------------------------------
// Adaptive Sharpen (bacondither). __CH__ is the curve_height dial.
// ---------------------------------------------------------------------------
inline std::string AdaptiveSharpen(float curveHeight)
{
    std::string s = R"SHADER(
// $MinimumShaderProfile: ps_4_0
// Adaptive sharpen (c) bacondither, BSD 2-clause. Post-resize, full-range gamma.
Texture2D tex : register(t0);
SamplerState samp : register(s0);
cbuffer PS_CONSTANTS : register(b0)
{
	float  px;
	float  py;
	float2 wh;
	uint   counter;
	float  clock;
};
#define curve_height    __CH__
#define video_level_out false
#define curveslope      (curve_height*1.5)
#define D_overshoot     0.016
#define D_comp_ratio    0.250
#define L_overshoot     0.004
#define L_comp_ratio    0.167
#define max_scale_lim   10.0
float CtG(float3 RGB) { return  sqrt( (1.0/3.0)*((RGB*RGB).r + (RGB*RGB).g + (RGB*RGB).b) ); }
float4 main(float4 pos : SV_POSITION, float2 coord : TEXCOORD) : SV_Target
{
	float3 c19 = saturate( tex.Sample(samp, coord + float2(-3*px,   0)).rgb );
	float3 c21 = saturate( tex.Sample(samp, coord + float2(-2*px,  -py)).rgb );
	float3 c10 = saturate( tex.Sample(samp, coord + float2(-2*px,   0)).rgb );
	float3 c20 = saturate( tex.Sample(samp, coord + float2(-2*px,   py)).rgb );
	float3 c24 = saturate( tex.Sample(samp, coord + float2(  -px,-2*py)).rgb );
	float3 c1  = saturate( tex.Sample(samp, coord + float2(  -px,  -py)).rgb );
	float3 c4  = saturate( tex.Sample(samp, coord + float2(  -px,   0)).rgb );
	float3 c6  = saturate( tex.Sample(samp, coord + float2(  -px,   py)).rgb );
	float3 c15 = saturate( tex.Sample(samp, coord + float2(  -px, 2*py)).rgb );
	float3 c22 = saturate( tex.Sample(samp, coord + float2(   0, -3*py)).rgb );
	float3 c9  = saturate( tex.Sample(samp, coord + float2(   0, -2*py)).rgb );
	float3 c2  = saturate( tex.Sample(samp, coord + float2(   0,   -py)).rgb );
	float3 c0  = saturate( tex.Sample(samp, coord).rgb );
	float3 c7  = saturate( tex.Sample(samp, coord + float2(   0,    py)).rgb );
	float3 c12 = saturate( tex.Sample(samp, coord + float2(   0,  2*py)).rgb );
	float3 c13 = saturate( tex.Sample(samp, coord + float2(   0,  3*py)).rgb );
	float3 c23 = saturate( tex.Sample(samp, coord + float2(   px,-2*py)).rgb );
	float3 c3  = saturate( tex.Sample(samp, coord + float2(   px,  -py)).rgb );
	float3 c5  = saturate( tex.Sample(samp, coord + float2(   px,   0)).rgb );
	float3 c8  = saturate( tex.Sample(samp, coord + float2(   px,   py)).rgb );
	float3 c14 = saturate( tex.Sample(samp, coord + float2(   px, 2*py)).rgb );
	float3 c18 = saturate( tex.Sample(samp, coord + float2( 2*px,  -py)).rgb );
	float3 c11 = saturate( tex.Sample(samp, coord + float2( 2*px,   0)).rgb );
	float3 c17 = saturate( tex.Sample(samp, coord + float2( 2*px,   py)).rgb );
	float3 c16 = saturate( tex.Sample(samp, coord + float2( 3*px,   0)).rgb );
	float3 blur   = (2*(c2 + c4 + c5 + c7) + (c1 + c3 + c6 +c8) + 4*c0)/16;
	float  blur_Y = (blur.r*(1.0/3.0) + blur.g*(1.0/3.0) + blur.b*(1.0/3.0));
	float edge = length( abs(blur-c0) + abs(blur-c1) + abs(blur-c2) + abs(blur-c3)
	                   + abs(blur-c4) + abs(blur-c5) + abs(blur-c6) + abs(blur-c7) + abs(blur-c8)
	                   + 0.25*(abs(blur-c9) + abs(blur-c10) + abs(blur-c11) + abs(blur-c12)) )*(1.0/3.0);
	edge *= min((0.8+2.7*pow(2, (-7.4*blur_Y))), 3.2);
	float c0_Y = CtG(c0);
	float kernel[25] = { c0_Y,  CtG(c1), CtG(c2), CtG(c3), CtG(c4), CtG(c5), CtG(c6), CtG(c7), CtG(c8),
	                     CtG(c9), CtG(c10), CtG(c11), CtG(c12), CtG(c13), CtG(c14), CtG(c15), CtG(c16),
	                     CtG(c17), CtG(c18), CtG(c19), CtG(c20), CtG(c21), CtG(c22), CtG(c23), CtG(c24) };
	float mdiff_c0  = 0.03 + 4*( abs(kernel[0]-kernel[2]) + abs(kernel[0]-kernel[4])
	                           + abs(kernel[0]-kernel[5]) + abs(kernel[0]-kernel[7])
	                           + 0.25*(abs(kernel[0]-kernel[1]) + abs(kernel[0]-kernel[3])
	                                  +abs(kernel[0]-kernel[6]) + abs(kernel[0]-kernel[8])) );
	float mdiff_c9  = ( abs(kernel[9]-kernel[2])   + abs(kernel[9]-kernel[24])
	                  + abs(kernel[9]-kernel[23])  + abs(kernel[9]-kernel[22])
	                  + 0.5*(abs(kernel[9]-kernel[1]) + abs(kernel[9]-kernel[3])) );
	float mdiff_c10 = ( abs(kernel[10]-kernel[20]) + abs(kernel[10]-kernel[19])
	                  + abs(kernel[10]-kernel[21]) + abs(kernel[10]-kernel[4])
	                  + 0.5*(abs(kernel[10]-kernel[1]) + abs(kernel[10]-kernel[6])) );
	float mdiff_c11 = ( abs(kernel[11]-kernel[17]) + abs(kernel[11]-kernel[5])
	                  + abs(kernel[11]-kernel[18]) + abs(kernel[11]-kernel[16])
	                  + 0.5*(abs(kernel[11]-kernel[3]) + abs(kernel[11]-kernel[8])) );
	float mdiff_c12 = ( abs(kernel[12]-kernel[13]) + abs(kernel[12]-kernel[15])
	                  + abs(kernel[12]-kernel[7])  + abs(kernel[12]-kernel[14])
	                  + 0.5*(abs(kernel[12]-kernel[6]) + abs(kernel[12]-kernel[8])) );
	float4 weights  = float4( (min((mdiff_c0/mdiff_c9), 2)), (min((mdiff_c0/mdiff_c10),2)),
	                          (min((mdiff_c0/mdiff_c11),2)), (min((mdiff_c0/mdiff_c12),2)) );
	float neg_laplace = ( 0.25 * (kernel[2] + kernel[4] + kernel[5] + kernel[7])
	                      +      (kernel[1] + kernel[3] + kernel[6] + kernel[8])
	                      +      ((kernel[9]*weights.x) + (kernel[10]*weights.y)
	                      +      (kernel[11]*weights.z) + (kernel[12]*weights.w)) )
	                      /      (5 + weights.x + weights.y + weights.z + weights.w);
	float sharpen_val =  0.01 + (curve_height/(curveslope*pow(edge, 3.5) + 0.5))
	                          - (curve_height/(8192*pow((edge*2.2), 4.5) + 0.5));
	float sharpdiff = (c0_Y - neg_laplace)*(sharpen_val*0.8);
	[unroll]
	for (int i = 0; i < 2; ++i)
	{
		for (int i1 = 1+i; i1 < 25-i; ++i1)
		{
			float temp   = kernel[i1-1];
			kernel[i1-1] = min(kernel[i1-1], kernel[i1]);
			kernel[i1]   = max(temp, kernel[i1]);
		}
		for (int i2 = 23-i; i2 > i; --i2)
		{
			float temp   = kernel[i2-1];
			kernel[i2-1] = min(kernel[i2-1], kernel[i2]);
			kernel[i2]   = max(temp, kernel[i2]);
		}
	}
	float nmax = max(((kernel[23] + kernel[24])/2), c0_Y);
	float nmin = min(((kernel[0]  + kernel[1])/2),  c0_Y);
	float nmax_scale = max((1/((nmax - c0_Y) + L_overshoot)), max_scale_lim);
	float nmin_scale = max((1/((c0_Y - nmin) + D_overshoot)), max_scale_lim);
	sharpdiff = lerp( (tanh((max(sharpdiff, 0))*nmax_scale)/nmax_scale), (max(sharpdiff, 0)), L_comp_ratio )
	          + lerp( (tanh((min(sharpdiff, 0))*nmin_scale)/nmin_scale), (min(sharpdiff, 0)), D_comp_ratio );
	if (video_level_out == true) { return float4( (tex.Sample(samp, coord) + sharpdiff).rgb, 1 ); }
	return float4( (c0 + sharpdiff), 1 );
}
)SHADER";
    ReplaceAll(s, "__CH__", F(curveHeight));
    return s;
}

// ---------------------------------------------------------------------------
// Debanding (SmartDeband, MPC-HC port). Tokens: __TH__ __RA__ __IT__ __GR__.
// ---------------------------------------------------------------------------
inline std::string Deband(float threshold, float range, int iterations, float grain)
{
    std::string s = R"SHADER(
// $MinimumShaderProfile: ps_4_0
// Debanding (SmartDeband port), MPC-HC (GPL).
Texture2D tex : register(t0);
SamplerState samp : register(s0);
cbuffer PS_CONSTANTS : register(b0)
{
	float  px;
	float  py;
	float2 wh;
	uint   counter;
	float  clock;
};
#define Threshold   __TH__
#define Range       __RA__
#define Iterations  __IT__
#define Grain       __GR__
#define pixel float2(px,py)
float permute(float x) { return ((34.0 * x + 1.0) * x) % 289.0; }
float rand(float x)    { return frac(x * 0.024390243); }
float3 average(float2 coord, float range, inout float h)
{
	float dist = rand(h) * range;     h = permute(h);
	float dir  = rand(h) * 6.2831853; h = permute(h);
	float2 pt = dist * pixel;
	float2 o = float2(cos(dir), sin(dir));
	float3 ref[4];
	ref[0] = tex.Sample(samp, coord + pt * float2( o.x,  o.y)).rgb;
	ref[1] = tex.Sample(samp, coord + pt * float2(-o.y,  o.x)).rgb;
	ref[2] = tex.Sample(samp, coord + pt * float2(-o.x, -o.y)).rgb;
	ref[3] = tex.Sample(samp, coord + pt * float2( o.y, -o.x)).rgb;
	return (ref[0] + ref[1] + ref[2] + ref[3]) * 0.25;
}
float4 main(float4 pos : SV_POSITION, float2 coord : TEXCOORD) : SV_Target
{
	float h;
	float3 m = float3(coord, clock * 0.0002) + 1.0;
	h = permute(permute(permute(m.x) + m.y) + m.z);
	float3 col = tex.Sample(samp, coord).rgb;
	float3 avg; float3 diff;
	#if (Iterations == 1)
		[unroll]
	#endif
	for (int i = 1; i <= Iterations; i++) {
		avg = average(coord, i * Range, h);
		diff = abs(col - avg);
		col = lerp(avg, col, diff > Threshold * 0.00006103515625 * i);
	}
	if (Grain > 0.0) {
		float3 noise;
		noise.x = rand(h); h = permute(h);
		noise.y = rand(h); h = permute(h);
		noise.z = rand(h); h = permute(h);
		col += (Grain * 0.000122070313) * (noise - 0.5);
	}
	return float4(col, 1.0);
}
)SHADER";
    ReplaceAll(s, "__TH__", F(threshold));
    ReplaceAll(s, "__RA__", F(range));
    ReplaceAll(s, "__IT__", std::to_string(iterations));
    ReplaceAll(s, "__GR__", F(grain));
    return s;
}

} // namespace postfx

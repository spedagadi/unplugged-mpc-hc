// Player globals the MPCVR allocator-presenter reads, defined for the headless engine.
//
// In mpc-hc.exe these live in MainFrm.cpp and are mutated by the player: external
// subtitle files loaded alongside the media (g_bExternalSubtitle, and its timing
// variant), the playback rate (g_dRate), and the segment start used to offset external
// subtitle times (g_tSegmentStart). The presenter uses them only to time external
// subtitles against the video; the engine has no external-subtitle feature, so the
// honest values are the defaults: no external subtitles, rate 1.0, segment start 0.
//
// Defined here rather than compiled from MainFrm.cpp because MainFrm.cpp IS the player
// UI — thousands of lines of MFC frame, bars and dialogs that the engine must never
// depend on. If external subtitle support is ever added to the engine, these become
// real state and move next to it.
#include "MpcPlayer.h"

bool g_bExternalSubtitleTime = false;
bool g_bExternalSubtitle = false;
double g_dRate = 1.0;
REFERENCE_TIME g_tSegmentStart = 0;

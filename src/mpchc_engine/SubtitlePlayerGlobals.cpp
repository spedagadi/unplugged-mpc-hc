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
#include "../filters/renderer/VideoRenderers/RenderersSettings.h"
#include "../Subtitles/SubRendererSettings.h"

bool g_bExternalSubtitleTime = false;
bool g_bExternalSubtitle = false;
double g_dRate = 1.0;
REFERENCE_TIME g_tSegmentStart = 0;

// ── player symbols the subtitle stack references, defined here for the engine ──
//
// In mpc-hc.exe these live in AppSettings.cpp / VersionInfo.cpp / FGFilterLAV.cpp —
// files that are the player UI itself (a 204 KB settings blob, the about-box version
// string, the LAV filter-graph table). Pulling any of them into the engine would drag
// the frame window in behind it, which is the coupling ISubtitleHost exists to avoid.
// The presenter and the subpic queue only READ these, and only fields whose defaults
// are what a fresh MPC-HC install has, so default-constructed settings are the honest
// equivalent: no user overrides exist in this process to honour.

CRenderersSettings& GetRenderersSettings()
{
    static CRenderersSettings s;   // MPC-HC's own defaults; the queue reads nSize et al
    return s;
}

SubRendererSettings GetSubRendererSettings()
{
    return SubRendererSettings();
}

namespace VersionInfo
{
    // Signature matches src/mpc-hc/VersionInfo.h. The presenter logs it; the engine has
    // no about-box, so it reports what is actually running.
    CString GetVersionString()
    {
        return CString(L"Unplugged engine (internal subtitle host)");
    }
}

// LAV Video decoder CLSID, value copied verbatim from src/mpc-hc/FGFilterLAV.h:27.
// Defined here because the defining TU over there (FGFilterLAV.cpp, which includes
// initguid.h) is player code; adding initguid to a SHARED file would double-define it
// inside mpc-hc.exe. IPinHook.cpp only compares against it.
#include <initguid.h>
DEFINE_GUID(GUID_LAVVideo,
    0xEE30215D, 0x164F, 0x4A92, 0xA4, 0xEB, 0x9D, 0x4C, 0x13, 0x39, 0x0F, 0x9F);

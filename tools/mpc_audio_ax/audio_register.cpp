// Minimal COM registration for MpcAudioRenderer — a standalone .ax that
// registers ONLY the audio renderer (no mpc-hc FilterApp / Filters bag).
//
// Order matters: MFC/ATL must precede any DirectShow BaseClasses header
// (ax_pch.h is force-included by the project; it is repeated here so this
// file is also correct when opened outside the project). wxlist.h skips its
// own __POSITION when __AFX_H__ is set, so include MFC first.

#include <afxwin.h>
#include <BaseClasses/streams.h>
#include "DSUtil.h"
#include "MpcAudioRenderer.h"

const AMOVIESETUP_MEDIATYPE g_sudPinMediaTypes[] = {
    { &MEDIATYPE_Audio, &MEDIASUBTYPE_PCM },
    { &MEDIATYPE_Audio, &MEDIASUBTYPE_IEEE_FLOAT }
};

const AMOVIESETUP_PIN g_sudPins[] = {
    { (LPWSTR)L"Input", FALSE, FALSE, FALSE, FALSE, &CLSID_NULL, nullptr, (UINT)std::size(g_sudPinMediaTypes), g_sudPinMediaTypes }
};

// BaseClasses AMOVIESETUP_FILTER: clsID comes first, then strName.
const AMOVIESETUP_FILTER g_sudFilter[] = {
    { &__uuidof(CMpcAudioRenderer), (LPWSTR)MpcAudioRendererName, MERIT_UNLIKELY + 1, (UINT)std::size(g_sudPins), g_sudPins, CLSID_AudioRendererCategory }
};

CFactoryTemplate g_Templates[] = {
    { g_sudFilter[0].strName, &__uuidof(CMpcAudioRenderer), CreateInstance<CMpcAudioRenderer>, nullptr, &g_sudFilter[0] }
};
int g_cTemplates = (int)std::size(g_Templates);

STDAPI DllRegisterServer()
{
    return AMovieDllRegisterServer2(TRUE);
}

STDAPI DllUnregisterServer()
{
    return AMovieDllRegisterServer2(FALSE);
}
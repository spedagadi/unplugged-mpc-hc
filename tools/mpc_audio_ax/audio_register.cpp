// Minimal COM registration for MpcAudioRenderer — a standalone .ax that
// registers ONLY the audio renderer (no mpc-hc FilterApp / Filters bag).
#include <streams.h>
#include "../thirdparty/MpcAudioRenderer/MpcAudioRenderer.h"

const AMOVIESETUP_MEDIATYPE g_sudPinMediaTypes[] = {
	{ &MEDIATYPE_Audio, &MEDIASUBTYPE_PCM },
	{ &MEDIATYPE_Audio, &MEDIASUBTYPE_IEEE_FLOAT }
};

const AMOVIESETUP_PIN g_sudPins[] = {
	{ (LPWSTR)L"Input", FALSE, FALSE, FALSE, FALSE, &CLSID_NULL, nullptr, std::size(g_sudPinMediaTypes), g_sudPinMediaTypes }
};

const AMOVIESETUP_FILTER g_sudFilter[] = {
	{ (LPWSTR)MpcAudioRendererName, &__uuidof(CMpcAudioRenderer), MERIT_UNLIKELY + 1, std::size(g_sudPins), g_sudPins, CLSID_AudioRendererCategory }
};

CFactoryTemplate g_Templates[] = {
	{ g_sudFilter[0].strName, &__uuidof(CMpcAudioRenderer), CreateInstance<CMpcAudioRenderer>, nullptr, &g_sudFilter[0] }
};
int g_cTemplates = std::size(g_Templates);

STDAPI DllRegisterServer()
{
	return AMovieDllRegisterServer2(TRUE);
}

STDAPI DllUnregisterServer()
{
	return AMovieDllRegisterServer2(FALSE);
}
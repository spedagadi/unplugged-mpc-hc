// ax_app.cpp — minimal MFC app object for the .ax.
//
// CMpcAudioRenderer's constructor reads its (persisted) settings through
// AfxGetApp(): `CWinApp* pApp = AfxGetApp(); pApp->GetProfileInt(...)`. In
// mpc-hc that global is CFilterApp; this wrapper deliberately has no filter
// bag, so without a CWinApp AfxGetApp() returns NULL and the constructor
// crashes on the first profile read. Provide the same 1-line pattern, with
// nothing else attached.
#include <afxwin.h>

// BaseClasses' registration writes the module path with GetModuleFileNameA(g_hInst),
// and g_hInst is set ONLY in BaseClasses' own dll entry point (dllentry.cpp:319). With
// this CWinApp in the binary, MFC supplies DllMain and BaseClasses' entry never runs, so
// g_hInst stayed NULL -- GetModuleFileNameA(NULL) returns the HOST EXE, and regsvr32
// therefore registered this filter as "C:\Windows\System32\regsvr32.exe". Observed on a
// real install: regsvr32 exit 0, CLSID present with the right FriendlyName, InprocServer32
// pointing at the registrar, and CoCreateInstance failing forever (the engine then fell
// back to DirectSound and bitstream silently died). Setting the handle here is the whole
// fix; without it no CLSID, old or new, can ever register correctly.
extern HINSTANCE g_hInst;

class CMpcAxApp final : public CWinApp {
public:
    BOOL InitInstance() override {
        g_hInst = AfxGetInstanceHandle();
        return TRUE;
    }
};

CMpcAxApp theAxApp;
// ax_app.cpp — minimal MFC app object for the .ax.
//
// CMpcAudioRenderer's constructor reads its (persisted) settings through
// AfxGetApp(): `CWinApp* pApp = AfxGetApp(); pApp->GetProfileInt(...)`. In
// mpc-hc that global is CFilterApp; this wrapper deliberately has no filter
// bag, so without a CWinApp AfxGetApp() returns NULL and the constructor
// crashes on the first profile read. Provide the same 1-line pattern, with
// nothing else attached.
#include <afxwin.h>

class CMpcAxApp final : public CWinApp {
public:
    BOOL InitInstance() override { return TRUE; }
};

CMpcAxApp theAxApp;
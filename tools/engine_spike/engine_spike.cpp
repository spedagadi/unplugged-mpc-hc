// engine_spike.cpp — S0 spike: prove the "thin DShow controller" premise.
//
// Builds a DirectShow graph from a filename the way the future mpchc_engine
// will: IGraphBuilder::RenderFile -> registered filters (LAV) -> registered
// renderer (MPCVR or default). Then controls it purely through graph COM
// interfaces (play / seek / status) with no mpc-hc app code.
//
// Output: which filters got used, duration, pre/post-seek positions, results.

#include <windows.h>
#include <dshow.h>
#include <atlbase.h>
#include <string>
#include <iostream>
#include <vector>

static void PrintFilterList(IGraphBuilder* gb) {
    CComPtr<IEnumFilters> pf;
    if (SUCCEEDED(gb->EnumFilters(&pf)) && pf) {
        CComPtr<IBaseFilter> f;
        ULONG fetched = 0;
        while (SUCCEEDED(pf->Next(1, &f, &fetched)) && fetched) {
            FILTER_INFO fi = {};
            if (SUCCEEDED(f->QueryFilterInfo(&fi))) {
                std::wcout << L"  filter: " << (fi.achName[0] ? fi.achName : L"(unnamed)") << L"\n";
                if (fi.pGraph) { fi.pGraph->Release(); }
            }
            f.Release(); fetched = 0;
        }
    }
}

static HRESULT Report(HRESULT hr, const char* what) {
    std::cout << (SUCCEEDED(hr) ? "[OK] " : "[FAIL] ") << what << " hr=0x"
              << std::hex << hr << std::dec << "\n";
    return hr;
}

int wmain(int argc, wchar_t* argv[]) {
    if (argc < 2) {
        std::wcerr << L"usage: engine_spike.exe <media-file>\n";
        return 2;
    }

    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    CComPtr<IGraphBuilder> gb;
    Report(gb.CoCreateInstance(CLSID_FilterGraph), "CoCreate FilterGraph");
    if (!gb) return 1;

    Report(gb->RenderFile(argv[1], nullptr), "RenderFile");

    std::cout << "filters in graph:\n";
    PrintFilterList(gb);

    CComPtr<IMediaControl> mc;
    CComPtr<IMediaSeeking> ms;
    gb->QueryInterface(&mc);
    gb->QueryInterface(&ms);

    CComPtr<IMediaEventEx> ev;
    gb->QueryInterface(&ev);
    LONG evCode = 0;
    LONG_PTR evParam1 = 0, evParam2 = 0;

    LONGLONG dur = 0;
    if (ms) { ms->GetDuration(&dur); }
    std::cout << "duration: " << dur << " (100ns units)\n";

    Report(mc->Run(), "Run");
    Sleep(1200);

    LONGLONG pos = 0, stop = 0;
    if (ms) { ms->GetPositions(&pos, &stop); }
    std::cout << "pos after ~1.2s run: " << pos << "\n";

    if (ms && dur > 0) {
        Report(ms->SetPositions(&dur, AM_SEEKING_AbsolutePositioning,
                                &stop, AM_SEEKING_NoPositioning), "Seek to end");
    }
    Sleep(500);

    if (ev) { ev->GetEvent(&evCode, &evParam1, &evParam2, 0); }

    LONGLONG pos2 = 0, stop2 = 0;
    if (ms) { ms->GetPositions(&pos2, &stop2); }
    std::cout << "pos after seek: " << pos2 << "\n";

    mc->Stop();
    std::cout << "event code seen: " << evCode << "\n";
    std::cout << "SPIKE_COMPLETE\n";

    CoUninitialize();
    return 0;
}
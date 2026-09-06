#include <windows.h>
#include <dshow.h>
#include <cstdio>

const CLSID CLSID_MpcAudioRenderer = { 0x601d2a2b, 0x9cde, 0x40bd, { 0x86, 0x50, 0x04, 0x85, 0xe3, 0x52, 0x27, 0x27 } };

int main()
{
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    printf("before CoCreate\n"); fflush(stdout);
    IBaseFilter* f = nullptr;
    HRESULT hr = CoCreateInstance(CLSID_MpcAudioRenderer, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, (void**)&f);
    printf("CoCreate hr=0x%08X  filter=%p\n", (unsigned)hr, (void*)f); fflush(stdout);
    if (SUCCEEDED(hr) && f) {
        printf("QI IMpcAudioRendererFilter...\n"); fflush(stdout);
        IUnknown* iface = nullptr;
        const IID IID_IMpcAudioRendererFilter = { 0x495d2c66, 0xd430, 0x439b, { 0x9d, 0xee, 0x40, 0xf9, 0xb7, 0x92, 0x9b, 0xba } };
        HRESULT hrQ = f->QueryInterface(IID_IMpcAudioRendererFilter, (void**)&iface);
        printf("QI mar hr=0x%08X  iface=%p\n", (unsigned)hrQ, (void*)iface); fflush(stdout);
        if (iface) iface->Release();
        f->Release();
    }
    CoUninitialize();
    printf("done\n"); fflush(stdout);
    return 0;
}
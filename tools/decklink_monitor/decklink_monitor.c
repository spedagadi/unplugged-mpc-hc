/*
 * decklink_monitor.c
 *
 * Read-only DeckLink signal status monitor.
 * Uses IDeckLinkStatus (read-only, no exclusive device lock) so it can
 * query signal health while ffmpeg/mpv holds the capture device open.
 *
 * Exported C API (callable from Python via ctypes):
 *
 *   int  vf_dl_open(const char* device_name)
 *        Open monitoring on the named device. Returns 0 on success, -1 on error.
 *        device_name: e.g. "DeckLink Quad HDMI Recorder"
 *        Pass NULL to open the first available DeckLink device.
 *
 *   int  vf_dl_signal_locked()
 *        Returns 1 if signal is locked/present, 0 if not, -1 if not opened.
 *
 *   int  vf_dl_get_mode()
 *        Returns the current BMDDisplayMode integer (display mode hash),
 *        or 0 if no signal, -1 if not opened.
 *        Compare previous value to detect format changes.
 *
 *   int  vf_dl_get_dynamic_range()
 *        Returns detected dynamic range flags:
 *          0 = SDR
 *          1 = HDR (PQ/HLG detected)
 *         -1 = not opened / unknown
 *
 *   void vf_dl_close()
 *        Release the monitoring interface.
 *
 * Build (MSYS2 UCRT64):
 *   gcc -shared -o decklink_monitor.dll decklink_monitor.c \
 *       -I../ffmpeg-7.0.2/decklink -lole32 -loleaut32 \
 *       -D_WIN32_WINNT=0x0600 -DWIN32_LEAN_AND_MEAN \
 *       -static-libgcc -static-libstdc++
 */

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
#include <windows.h>
#include <ole2.h>
#include <stdio.h>
#include <string.h>

#include "DeckLinkAPI.h"

/* Signal info struct — defined here, used in forward decl and implementation */
typedef struct {
    int colorspace;     /* 0=Rec601 1=Rec709 2=Rec2020 */
    int dynamic_range;  /* 0=SDR    1=HDR_PQ 2=HDR_HLG */
    int pixel_depth;    /* 8 / 10 / 12 */
    int chroma;         /* 1=RGB444 0=YCbCr422 -1=unknown  (HDMI carries only these) */
    int locked;         /* 1=signal present */
} VFSignalInfo;

/* Forward declarations */
__declspec(dllexport) void vf_dl_close(void);
__declspec(dllexport) int  vf_dl_get_signal_info(VFSignalInfo* out);
__declspec(dllexport) int  vf_dl_poll_all_ports(char[][128], int*, int*, int);
__declspec(dllexport) int  vf_dl_enumerate_devices(char[][64], int*, int);
__declspec(dllexport) int  vf_dl_build_url(const char* device_name, char* out, size_t out_sz);

/* ------------------------------------------------------------------ */
/* State                                                               */
/* ------------------------------------------------------------------ */

static IDeckLink*       g_device   = NULL;
static IDeckLinkStatus* g_status   = NULL;
static int              g_opened   = 0;

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */

static int find_device(const char* name)
{
    IDeckLinkIterator* it = NULL;
    IDeckLink*         dev = NULL;
    HRESULT hr;

    /* CreateDeckLinkIteratorInstance is the COM entry point */
    hr = CoCreateInstance(&CLSID_CDeckLinkIterator, NULL,
                          CLSCTX_ALL,
                          &IID_IDeckLinkIterator,
                          (void**)&it);
    if (FAILED(hr) || !it) {
        return -1;   /* DeckLink drivers not installed */
    }

    while (it->lpVtbl->Next(it, &dev) == S_OK) {
        BSTR bname = NULL;
        dev->lpVtbl->GetDisplayName(dev, &bname);

        /* Convert BSTR to narrow string for comparison */
        char narrow[256] = {0};
        if (bname) {
            WideCharToMultiByte(CP_UTF8, 0, bname, -1,
                                narrow, sizeof(narrow)-1, NULL, NULL);
            SysFreeString(bname);
        }

        int match = (name == NULL) ||
                    (strstr(narrow, name) != NULL) ||
                    (strcmp(narrow, name) == 0);

        if (match) {
            g_device = dev;
            it->lpVtbl->Release(it);
            return 0;
        }
        dev->lpVtbl->Release(dev);
        dev = NULL;
    }

    it->lpVtbl->Release(it);
    return -2;   /* device not found */
}

/* ------------------------------------------------------------------ */
/* Exported API                                                         */
/* ------------------------------------------------------------------ */

__declspec(dllexport)
int vf_dl_open(const char* device_name)
{
    HRESULT hr;

    if (g_opened) vf_dl_close();

    hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) return -1;

    if (find_device(device_name) != 0) return -2;

    hr = g_device->lpVtbl->QueryInterface(
            g_device,
            &IID_IDeckLinkStatus,
            (void**)&g_status);
    if (FAILED(hr) || !g_status) {
        g_device->lpVtbl->Release(g_device);
        g_device = NULL;
        return -3;
    }

    g_opened = 1;
    return 0;
}

__declspec(dllexport)
int vf_dl_signal_locked()
{
    BOOL locked = FALSE;
    HRESULT hr;

    if (!g_opened || !g_status) return -1;

    hr = g_status->lpVtbl->GetFlag(
            g_status,
            bmdDeckLinkStatusVideoInputSignalLocked,
            &locked);

    if (FAILED(hr)) return -1;
    return locked ? 1 : 0;   /* 1 = locked, 0 = no signal */
}

__declspec(dllexport)
int vf_dl_get_mode()
{
    LONGLONG mode = 0;
    HRESULT hr;

    if (!g_opened || !g_status) return -1;

    hr = g_status->lpVtbl->GetInt(
            g_status,
            bmdDeckLinkStatusCurrentVideoInputMode,
            &mode);

    if (FAILED(hr)) return 0;
    return (int)mode;
}

__declspec(dllexport)
int vf_dl_get_dynamic_range()
{
    LONGLONG dr = 0;
    HRESULT hr;

    if (!g_opened || !g_status) return -1;

    hr = g_status->lpVtbl->GetInt(
            g_status,
            bmdDeckLinkStatusDetectedVideoInputDynamicRange,
            &dr);

    if (FAILED(hr)) return -1;

    /*
     * bmdDetectedVideoInputRangeSDR = 1 << 0
     * bmdDetectedVideoInputRangeHDRPQ = 1 << 1 (or similar flag)
     * Non-zero HDR flags: return 1, SDR: return 0
     */
    return (dr > 1) ? 1 : 0;
}

/*
 * vf_dl_poll_all_ports — read signal lock + dynamic range for ALL ports of ALL
 * devices simultaneously. No exclusive device lock needed.
 *
 * out_urls:    caller array of char[128] — full decklink:// URL for each port
 * out_locked:  caller int array — 1=signal locked, 0=no signal
 * out_dr:      caller int array — 0=SDR, 1=HDR_PQ, 2=HDR_HLG, -1=unknown
 * max_ports:   size of arrays
 *
 * Returns total number of ports found across all devices.
 * Opens a temporary IDeckLinkStatus on each device (no exclusive lock).
 */
__declspec(dllexport)
int vf_dl_poll_all_ports(char out_urls[][128], int* out_locked, int* out_dr, int max_ports)
{
    IDeckLinkIterator* it  = NULL;
    IDeckLink*         dev = NULL;
    HRESULT hr;
    int total = 0;

    CoInitializeEx(NULL, COINIT_MULTITHREADED);

    hr = CoCreateInstance(&CLSID_CDeckLinkIterator, NULL,
                          CLSCTX_ALL,
                          &IID_IDeckLinkIterator,
                          (void**)&it);
    if (FAILED(hr) || !it) return 0;

    while (total < max_ports && it->lpVtbl->Next(it, &dev) == S_OK) {
        /* Get display name */
        BSTR bname = NULL;
        char name_utf8[64] = {0};
        dev->lpVtbl->GetDisplayName(dev, &bname);
        if (bname) {
            WideCharToMultiByte(CP_UTF8, 0, bname, -1,
                                name_utf8, sizeof(name_utf8)-1, NULL, NULL);
            SysFreeString(bname);
        }

        /* The DeckLink iterator already yields one entry per physical port
         * (e.g. quad cards enumerate as 4 separate devices named "(1)".. "(4)"),
         * so each iterator entry maps to exactly one port here. */
        int num_ports = 1;

        /* For each port, open a temporary IDeckLinkStatus */
        for (int port = 0; port < num_ports && total < max_ports; port++) {
            /* Build URL */
            if (num_ports == 1)
                snprintf(out_urls[total], 127, "decklink://%s", name_utf8);
            else
                snprintf(out_urls[total], 127, "decklink://%s@%d", name_utf8, port);

            /* Try to get status for this port */
            /* For multi-port cards we need to open the sub-device by port index.
             * Unfortunately IDeckLinkStatus on the parent device reports the
             * currently active input port. For now we report the parent device
             * status for port 0 and mark others as unknown. */
            IDeckLinkStatus* st = NULL;
            hr = dev->lpVtbl->QueryInterface(dev,
                    &IID_IDeckLinkStatus, (void**)&st);
            if (SUCCEEDED(hr) && st) {
                BOOL locked = FALSE;
                st->lpVtbl->GetFlag(st,
                    bmdDeckLinkStatusVideoInputSignalLocked, &locked);
                out_locked[total] = (port == 0) ? (locked ? 1 : 0) : -1;

                LONGLONG dr = 0;
                hr = st->lpVtbl->GetInt(st,
                    bmdDeckLinkStatusDetectedVideoInputDynamicRange, &dr);
                if (FAILED(hr)) {
                    out_dr[total] = -1;
                } else if (dr & (LONGLONG)bmdDynamicRangeHDRStaticHLG) {
                    out_dr[total] = 2;
                } else if (dr & (LONGLONG)bmdDynamicRangeHDRStaticPQ) {
                    out_dr[total] = 1;
                } else {
                    /* DOLBY VISION. The card has no DV flag: a DV player replaces
                     * the HDR10 InfoFrame with Dolby's VSIF, so the range reads SDR
                     * and only the colours space survives. BT.2020 + SDR is not a
                     * combination consumer devices produce otherwise, so it is the
                     * DV signature (1.3.0's is_likely_dolby_vision()).
                     *
                     * It belongs HERE, not in each caller: the first-run dialog has
                     * no graph running and therefore no engine to ask, so this poll
                     * is the only instrument it has. */
                    LONGLONG cs = 0;
                    if (SUCCEEDED(st->lpVtbl->GetInt(st,
                            bmdDeckLinkStatusDetectedVideoInputColorspace, &cs)) &&
                        cs == (LONGLONG)bmdColorspaceRec2020) {
                        out_dr[total] = 3;
                    } else {
                        out_dr[total] = 0;
                    }
                }
                st->lpVtbl->Release(st);
            } else {
                out_locked[total] = -1;
                out_dr[total] = -1;
            }
            total++;
        }

        dev->lpVtbl->Release(dev);
        dev = NULL;
    }

    it->lpVtbl->Release(it);
    return total;
}

/*
 * vf_dl_enumerate_devices — list all DeckLink devices and their HDMI port count.
 *
 * out_names:  caller-allocated array of char[64] — device display names
 * out_ports:  caller-allocated int array — number of HDMI input ports per device
 * max_devs:   size of the arrays
 *
 * Returns number of devices found (0 if none / drivers not installed).
 * Each entry in out_names holds the display name (UTF-8, max 63 chars).
 * out_ports[i] is always 1 — the iterator already enumerates each physical
 * port as its own IDeckLink device (quad/duo cards appear as N devices).
 *
 * The URL to pass to ffmpeg/mpv is:
 *   decklink://<display_name>
 * For multi-port cards the individual ports are addressed as:
 *   decklink://<display_name>@<port_index>   (0-based)
 */
__declspec(dllexport)
int vf_dl_enumerate_devices(char out_names[][64], int* out_ports, int max_devs)
{
    IDeckLinkIterator* it  = NULL;
    IDeckLink*         dev = NULL;
    HRESULT hr;
    int count = 0;

    CoInitializeEx(NULL, COINIT_MULTITHREADED);

    hr = CoCreateInstance(&CLSID_CDeckLinkIterator, NULL,
                          CLSCTX_ALL,
                          &IID_IDeckLinkIterator,
                          (void**)&it);
    if (FAILED(hr) || !it) return 0;

    while (count < max_devs && it->lpVtbl->Next(it, &dev) == S_OK) {
        /* Display name */
        BSTR bname = NULL;
        dev->lpVtbl->GetDisplayName(dev, &bname);
        if (bname) {
            WideCharToMultiByte(CP_UTF8, 0, bname, -1,
                                out_names[count], 63, NULL, NULL);
            out_names[count][63] = '\0';
            SysFreeString(bname);
        } else {
            strncpy(out_names[count], "Unknown DeckLink Device", 63);
        }

        /* Each iterator entry already represents a single physical port
         * (quad/duo cards enumerate as N separate devices named "(1)".. "(N)"),
         * so there is exactly one port per device here. */
        out_ports[count] = 1;

        dev->lpVtbl->Release(dev);
        dev = NULL;
        count++;
    }

    it->lpVtbl->Release(it);
    return count;
}

/*
 * vf_dl_build_url — build the full decklink:// ingest URL for a device.
 * Contract with the engine (DeckLinkMonitor.h):
 *   int (__cdecl*)(const char* device, char* out, size_t out_sz)
 * Returns the URL length (>0 on success), 0 if the device name is empty.
 * Video-only (no_audio=1): HDMI audio is routed to the AVR externally.
 */
__declspec(dllexport)
int vf_dl_build_url(const char* device_name, char* out, size_t out_sz)
{
    int n;
    if (!out || out_sz == 0) return 0;
    if (!device_name || !device_name[0]) { out[0] = 0; return 0; }
    n = snprintf(out, out_sz,
                 "decklink://%s"
                 "?video_input=hdmi"
                 "&signal_loss_action=repeat"
                 "&no_audio=1"
                 "&raw_format=auto"
                 "&queue_size=128M"
                 "&live_frames=4",
                 device_name);
    if (n < 0 || (size_t)n >= out_sz) { out[0] = 0; return 0; }
    return n;
}

/*
 * vf_dl_get_signal_info — fills VFSignalInfo for dynamic vf filter building.
 * Returns 0 on success, -1 if not opened.
 */
__declspec(dllexport)
int vf_dl_get_signal_info(VFSignalInfo* out)
{
    LONGLONG val = 0;
    HRESULT  hr;

    if (!out) return -1;
    if (!g_opened || !g_status) return -1;

    /* Signal locked */
    {
        BOOL locked = FALSE;
        g_status->lpVtbl->GetFlag(g_status,
            bmdDeckLinkStatusVideoInputSignalLocked, &locked);
        out->locked = locked ? 1 : 0;
    }

    /* Colorspace */
    val = 0;
    hr = g_status->lpVtbl->GetInt(g_status,
        bmdDeckLinkStatusDetectedVideoInputColorspace, &val);
    if (FAILED(hr)) val = bmdColorspaceRec709;   /* safe default */
    if      (val == (LONGLONG)bmdColorspaceRec2020) out->colorspace = 2;
    else if (val == (LONGLONG)bmdColorspaceRec601)  out->colorspace = 0;
    else                                             out->colorspace = 1; /* Rec709 */

    /* Dynamic range */
    val = 0;
    hr = g_status->lpVtbl->GetInt(g_status,
        bmdDeckLinkStatusDetectedVideoInputDynamicRange, &val);
    if (FAILED(hr)) {
        out->dynamic_range = 0;   /* assume SDR on failure */
    } else if (val & (LONGLONG)bmdDynamicRangeHDRStaticHLG) {
        out->dynamic_range = 2;   /* HLG */
    } else if (val & (LONGLONG)bmdDynamicRangeHDRStaticPQ) {
        out->dynamic_range = 1;   /* PQ / HDR10 */
    } else {
        out->dynamic_range = 0;   /* SDR */
    }

    /* Pixel depth + chroma from format flags */
    val = 0;
    g_status->lpVtbl->GetInt(g_status,
        bmdDeckLinkStatusDetectedVideoInputFormatFlags, &val);
    if      (val & (LONGLONG)bmdDetectedVideoInput12BitDepth) out->pixel_depth = 12;
    else if (val & (LONGLONG)bmdDetectedVideoInput10BitDepth) out->pixel_depth = 10;
    else                                                       out->pixel_depth = 8;

    /* Chroma subsampling from the same flags (SDK 14.2 exposes only
     * YCbCr422 vs RGB444 — exactly what HDMI carries). */
    if      (val & (LONGLONG)bmdDetectedVideoInputRGB444)  out->chroma = 1;
    else if (val & (LONGLONG)bmdDetectedVideoInputYCbCr422) out->chroma = 0;
    else                                                     out->chroma = -1;

    return 0;
}

__declspec(dllexport)
void vf_dl_close()
{
    if (g_status) {
        g_status->lpVtbl->Release(g_status);
        g_status = NULL;
    }
    if (g_device) {
        g_device->lpVtbl->Release(g_device);
        g_device = NULL;
    }
    g_opened = 0;
}

/* DLL entry point */
BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved)
{
    (void)hinstDLL; (void)fdwReason; (void)lpReserved;
    return TRUE;
}

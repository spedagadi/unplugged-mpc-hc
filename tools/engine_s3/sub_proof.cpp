// sub_proof.cpp -- executable proof that embedded subtitles render through MPC-HC's
// internal path inside the engine, against the EXACT s3engine.dll the app ships.
//
// What it exercises, in order:
//   1. open a 4K HDR file                       (graph builds with the subtitle splice)
//   2. subtrack 0                               (select the embedded track)
//   3. seek into a window where the track HAS text, grab   (subtitles reach the picture)
//   4. push a rebuild-only setting              (the app does this right after every open:
//                                                it queues a re-open, i.e. a live teardown --
//                                                the sequence that crashed on first open)
//   5. grab again after the re-open, push back, grab once more
//   6. s3_shutdown                              (same teardown, final time)
// Surviving 4-6 is the point of the second half: the crash was in teardown, not in open.
//
// Pass criteria, checked by the caller against the engine log
// (%USERPROFILE%\.unplugged\logs\engine.log) for THIS run:
//   "[SUBS] subtitle pins found=N spliced=1" with N >= 1
//   "[SUBS] subpic provider attached"
//   "[TEARDOWN] 4/4 stop graph + release — done" (and each 4a..4d bracket closed)
//   no "CANNOT CREATE UNPLUGGED RENDERER", no "CRASH SELF-DIAGNOSIS"
// The frames are then looked at: text pixels in the lower third are the pixel-level proof.

#include <windows.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <atomic>

typedef int (*fn_attach)(long long);
typedef int (*fn_cmd)(const char*);
typedef int (*fn_stats)(char*, int);
typedef int (*fn_shutdown)();

static fn_attach   p_attach;
static fn_cmd      p_cmd;
static fn_stats    p_stats;
static fn_shutdown p_shutdown;

static HWND g_hwnd = 0;
static std::atomic<long long> g_lastPollMs{0};
// 0 boot, 1 playing, 2 subtrack, 3 seek, 4 grab1, 5 rebuild-push, 6 grab2,
// 7 rebuild-push-back, 8 grab3, 9 done
static std::atomic<int> g_phase{0};
static std::string g_lastState;
static long long g_lastPos = -1;
static DWORD g_t0 = 0;
static DWORD g_phaseAt = 0;

static const char* kOut1 = "C:\\code\\unplugged-mpc-hc\\tools\\engine_s3\\sub_proof1.bmp";
static const char* kOut2 = "C:\\code\\unplugged-mpc-hc\\tools\\engine_s3\\sub_proof2.bmp";
static const char* kOut3 = "C:\\code\\unplugged-mpc-hc\\tools\\engine_s3\\sub_proof3.bmp";

// JSON needs each backslash doubled on the way in: the engine's JsonField unescapes the
// value, so a single one is simply eaten and the frame lands on a mangled drive-relative
// path (measured: "GrabFrame: wrote 3840x-2160 to C:codeunplugged-mpc-hc...").
static std::string JsonEscapePath(const char* p) {
    std::string out;
    for (const char* c = p; *c; ++c) {
        if (*c == '\\') out += "\\\\";
        else out += *c;
    }
    return out;
}

// Deutsch Forced (SRT) event 5 runs 00:23:02.131 --> 00:23:06.969. Land the grab inside it.
static const long long kSeekPos = 13840000000LL;   // 23:04, 100 ns units

static std::string FieldOf(const char* j, const char* key) {
    const std::string k = std::string("\"") + key + "\":\"";
    const char* p = strstr(j, k.c_str());
    if (!p) return std::string();
    p += k.size();
    const char* e = strchr(p, '"');
    return e ? std::string(p, e - p) : std::string();
}

static long long NumberField(const char* j, const char* key) {
    const std::string k = std::string("\"") + key + "\":";
    const char* p = strstr(j, k.c_str());
    if (!p) return -1;
    p += k.size();
    long long v = 0;
    while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    return v;
}

static void Note(const char* what) {
    printf("[%7u ms] %s\n", GetTickCount() - g_t0, what);
    fflush(stdout);
}

static int Cmd(const char* json) {
    int rc = p_cmd(json);
    printf("[%7u ms] cmd %-52s rc=%d\n", GetTickCount() - g_t0, json, rc);
    fflush(stdout);
    return rc;
}

static std::string GrabCmd(const char* path) {
    return std::string("{\"a\":\"grab\",\"file\":\"") + JsonEscapePath(path) + "\"}";
}

static void PollOnce() {
    char buf[8192];
    int n = p_stats(buf, sizeof(buf));
    g_lastPollMs = GetTickCount();
    if (n <= 0) return;
    buf[n] = 0;
    // Keep the last full status JSON on disk: the subtitle track list is a UI contract
    // ("subtitle":{"current":N,"tracks":[...]}), and this is the only place the exact bytes
    // the rail receives can be inspected without running the packaged app.
    static HANDLE hStats = INVALID_HANDLE_VALUE;
    if (hStats == INVALID_HANDLE_VALUE) {
        hStats = CreateFileA("C:\\code\\unplugged-mpc-hc\\tools\\engine_s3\\sub_proof_stats.json",
                             GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    }
    if (hStats != INVALID_HANDLE_VALUE) {
        SetFilePointer(hStats, 0, nullptr, FILE_BEGIN);
        DWORD written = 0;
        WriteFile(hStats, buf, (DWORD)n, &written, nullptr);
        SetEndOfFile(hStats);
    }
    std::string st = FieldOf(buf, "state");
    if (st != g_lastState) {
        printf("[%7u ms] state: %s -> %s (pos=%lld)\n", GetTickCount() - g_t0,
               g_lastState.empty() ? "(none)" : g_lastState.c_str(), st.c_str(),
               NumberField(buf, "position"));
        fflush(stdout);
        g_lastState = st;
    }
    const long long pos = NumberField(buf, "position");
    if (pos >= 0 && (pos / 10000000LL) / 10 != ((g_lastPos < 0 ? -1 : g_lastPos) / 10000000LL) / 10) {
        printf("[%7u ms] pos = %lld.%lld s\n", GetTickCount() - g_t0, pos / 10000000LL,
               (pos / 1000000LL) % 10);
        fflush(stdout);
    }
    g_lastPos = pos;

    const DWORD now = GetTickCount();
    switch (g_phase) {
    case 0:
        if (st == "playing") { g_phase = 1; g_phaseAt = now; Note("playing"); }
        break;
    case 1:
        if (now - g_phaseAt > 1500) {
            Cmd("{\"a\":\"subtrack\",\"index\":0}");
            g_phase = 2; g_phaseAt = now;
        }
        break;
    // The A/B that tests track SWITCHING, at one fixed timestamp: 4:30.
    //   track 0 = "Deutsch Forced (SRT)"  -> has NO event at 4:30 (verified from the file:
    //                                        its events are 0:05, 3:42, 3:47, then 19:10)
    //   track 4 = "Deutsch SDH (PGS)"     -> a full subtitle track, text at 4:30
    // So frame 1 must be bare and frame 2 must carry text. Same picture, same position,
    // one variable - and the switch exercises the decoder swap (libass -> CPGSSub), which
    // is the code path that was silently clearing the provider.
    case 2:
        if (now - g_phaseAt > 500) {
            Cmd("{\"a\":\"seek\",\"pos\":2700000000}");    // 4:30
            g_phase = 3; g_phaseAt = now;
        }
        break;
    case 3:
        if (now - g_phaseAt > 2500) {
            Cmd(GrabCmd(kOut1).c_str());
            g_phase = 4; g_phaseAt = now;
        }
        break;
    // Track SWITCH, mid-playback: index 4 is "Deutsch SDH (PGS)" - a bitmap stream on a
    // different decoder (CPGSSub, not libass) reached through different code (the new
    // un-splice/re-splice, which does live pin surgery). Both the render and the teardown
    // afterwards have to survive it, so this is the phase that tests the fix rather than
    // the feature that already worked.
    case 4:
        if (now - g_phaseAt > 1000) {
            Cmd("{\"a\":\"subtrack\",\"index\":4}");
            Cmd("{\"a\":\"seek\",\"pos\":2700000000}");    // same 4:30 as frame 1
            g_phase = 12; g_phaseAt = now;
        }
        break;
    case 12:
        if (now - g_phaseAt > 4000) {
            Cmd(GrabCmd(kOut2).c_str());
            g_phase = 5; g_phaseAt = now;
        }
        break;
    // Then the rebuild the app performs on its own after every open (a rebuild-only
    // setting arrives from the rail), and a grab after it: teardown of a graph that has
    // had subtitle pin surgery is the case that crashed before.
    case 5:
        if (now - g_phaseAt > 1000) {
            Note("pushing a rebuild-only setting (the app does this after every open)");
            Cmd("{\"a\":\"set\",\"sets\":\"out.dither=false\"}");
            g_phase = 10; g_phaseAt = now;
        }
        break;
    case 10:
        if (now - g_phaseAt > 6000) {           // rebuild done; graph restarts at 0
            Cmd("{\"a\":\"subtrack\",\"index\":0}");
            Cmd("{\"a\":\"seek\",\"pos\":13840000000}");
            g_phase = 6; g_phaseAt = now;
        }
        break;
    case 6:
        if (now - g_phaseAt > 4000) {
            Cmd(GrabCmd(kOut3).c_str());
            g_phase = 8; g_phaseAt = now;
        }
        break;
    case 7:
        break;
    case 11:
        break;
    // The regression the app reported: switching to a subtitle track whose stream runs out
    // posts EC_COMPLETE on the graph, which the engine read as end-of-title - it detached
    // the renderer window and the UI fell back to the library. Track 1 is "Deutsch Forced
    // (VobSub)", the one in the failing session. Playback must survive the switch, so the
    // state has to still be "playing" here.
    case 8:
        if (now - g_phaseAt > 1000) {
            Cmd("{\"a\":\"seek\",\"pos\":200000000}");     // 20 s, as in the failing session
            Cmd("{\"a\":\"subtrack\",\"index\":1}");
            g_phase = 14; g_phaseAt = now;
        }
        break;
    case 14:
        if (now - g_phaseAt > 10000) {
            const std::string msg = (st == "playing")
                ? std::string("still playing 10 s after the short subtitle stream")
                : (std::string("STATE LOST after switch: ") + st);
            Note(msg.c_str());
            if (st != "playing") { g_phase = 20; g_phaseAt = now; break; }
            g_phase = 15; g_phaseAt = now;
        }
        break;
    // The audio switch the app reported as "stops playback and jumps to media selection":
    // it aborted the graph (EC_ERRORABORT 0x88890008). It is now queued and applied at
    // connect across a re-open that restores the position, so the test is: still playing,
    // and the position is where it was, not 0.
    case 15:
        if (now - g_phaseAt > 500) {
            Cmd("{\"a\":\"track\",\"index\":1}");
            g_phase = 16; g_phaseAt = now;
        }
        break;
    case 16:
        if (now - g_phaseAt > 12000) {
            const std::string msg = (st == "playing")
                ? std::string("still playing after the audio track switch, pos=")
                  + std::to_string(pos / 10000000LL) + "s"
                : (std::string("AUDIO SWITCH LOST STATE: ") + st);
            Note(msg.c_str());
            g_phase = (st == "playing") ? 17 : 20;
            g_phaseAt = now;
        }
        break;
    // Volume/mute ABI round trip: the engine echoes both in the status JSON, so the
    // sub_proof_stats.json dump is the proof that the slider's command reaches the engine
    // and lands — audible verification is not available to a headless harness.
    case 17:
        if (now - g_phaseAt > 500) {
            Cmd("{\"a\":\"volume\",\"percent\":40}");
            Cmd("{\"a\":\"mute\",\"on\":1}");
            g_phase = 18; g_phaseAt = now;
        }
        break;
    case 18:
        if (now - g_phaseAt > 1500) { g_phase = 9; g_phaseAt = now; }
        break;
    case 9:
        if (now - g_phaseAt > 500) {
            int rc = p_shutdown();
            printf("[%7u ms] s3_shutdown rc=%d\n", GetTickCount() - g_t0, rc);
            PostQuitMessage(0);
        }
        break;
    }
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_TIMER) { PollOnce(); return 0; }
    return DefWindowProc(h, m, w, l);
}

int main(int argc, char** argv) {
    const char* dll = "C:\\code\\unplugged-mpc-hc\\src\\unplugged-ui\\dist\\Unplugged\\_internal\\s3engine.dll";
    const char* file = (argc > 1) ? argv[1]
        : "D:\\Dune.2021.German.TrueHD.Atmos.DL.2160p.UHD.BluRay.DV.HDR.HEVC.Remux-NIMA4K.mkv";

    g_t0 = GetTickCount();
    HMODULE hm = LoadLibraryA(dll);
    if (!hm) { printf("FAIL: cannot load %s (err %lu)\n", dll, GetLastError()); return 2; }
    p_attach   = (fn_attach)GetProcAddress(hm, "s3_attach");
    p_cmd      = (fn_cmd)GetProcAddress(hm, "s3_cmd");
    p_stats    = (fn_stats)GetProcAddress(hm, "s3_stats");
    p_shutdown = (fn_shutdown)GetProcAddress(hm, "s3_shutdown");
    if (!p_attach || !p_cmd || !p_stats || !p_shutdown) { printf("FAIL: missing exports\n"); return 2; }
    Note("loaded the staged s3engine.dll");

    WNDCLASSA wc = {};
    wc.lpfnWndProc = WndProc; wc.hInstance = GetModuleHandle(0); wc.lpszClassName = "subproof";
    RegisterClassA(&wc);
    g_hwnd = CreateWindowExA(0, "subproof", "subproof", WS_OVERLAPPEDWINDOW, 0, 0, 640, 360, 0, 0, wc.hInstance, 0);
    if (!g_hwnd) { printf("FAIL: no window\n"); return 2; }

    std::thread watchdog([] {
        // Not "< 9": phases 10, 11 and 14 are the post-rebuild seeks and the end-of-title
        // wait, and a "<" test would silently drop the watchdog while they run. Phase 20 is
        // the terminal FAILURE state, which also has to stop the watch.
        while (g_phase != 9 && g_phase != 20) {
            Sleep(500);
            long long age = (long long)GetTickCount() - g_lastPollMs.load();
            if (g_lastPollMs && age > 8000) {
                printf("FAIL: poll silent for %lld ms at phase %d\n", age, (int)g_phase);
                fflush(stdout);
                ExitProcess(3);
            }
            if ((long long)GetTickCount() - g_t0 > 180000) {
                printf("FAIL: 180 s timeout at phase %d lastState=%s\n", (int)g_phase, g_lastState.c_str());
                fflush(stdout);
                ExitProcess(4);
            }
        }
    });
    watchdog.detach();

    int rc = p_attach((long long)(intptr_t)g_hwnd);
    printf("[%7u ms] s3_attach rc=%d\n", GetTickCount() - g_t0, rc);

    // Mirror the minimum the media path needs; curve 7 is the shipping default.
    Cmd("{\"a\":\"set\",\"sets\":\"hdr.convertToSdr=1;hdr.sdrNits=127;hdr.toneMapCurve=7;ml.enable=1;ml.mode=0\"}");

    std::string esc;
    for (const char* c = file; *c; ++c) {
        if (*c == '\\' || *c == '"') esc += '\\';
        esc += *c;
    }
    rc = Cmd((std::string("{\"a\":\"open\",\"url\":\"") + esc + "\"}").c_str());
    if (rc != 0) { Note("open failed"); return 2; }

    SetTimer(g_hwnd, 1, 200, nullptr);
    MSG msg;
    while (GetMessage(&msg, 0, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessage(&msg); }
    KillTimer(g_hwnd, 1);

    DWORD sz1 = 0, sz2 = 0, sz3 = 0;
    WIN32_FILE_ATTRIBUTE_DATA fad = {};
    const bool b1 = GetFileAttributesExA(kOut1, GetFileExInfoStandard, &fad) != 0;  if (b1) sz1 = fad.nFileSizeLow;
    const bool b2 = GetFileAttributesExA(kOut2, GetFileExInfoStandard, &fad) != 0;  if (b2) sz2 = fad.nFileSizeLow;
    const bool b3 = GetFileAttributesExA(kOut3, GetFileExInfoStandard, &fad) != 0;  if (b3) sz3 = fad.nFileSizeLow;
    printf("\nRESULT: phase=%d lastState=%s frames: pre-reopen=%s post-reopen1=%s post-reopen2=%s\n",
           (int)g_phase, g_lastState.c_str(), b1 ? "yes" : "NO", b2 ? "yes" : "NO", b3 ? "yes" : "NO");
    printf("        sizes: %lu %lu %lu\n", sz1, sz2, sz3);
    return (g_phase == 9 && b1 && b2 && b3 && sz1 > 100000 && sz2 > 100000 && sz3 > 100000) ? 0 : 1;
}

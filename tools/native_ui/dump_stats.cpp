// tools/native_ui/dump_stats.cpp — headless: attach+open+poll, print raw JSON blocks.
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
extern "C" {
__declspec(dllimport) int s3_attach(int64_t hwnd);
__declspec(dllimport) int s3_cmd(const char* j);
__declspec(dllimport) int s3_stats(char* buf, int cap);
__declspec(dllimport) void s3_shutdown(void);
}
static LRESULT CALLBACK WP(HWND h,UINT m,WPARAM w,LPARAM l){ return DefWindowProcW(h,m,w,l); }
int main(){
    WNDCLASSW wc={}; wc.lpfnWndProc=WP; wc.hInstance=GetModuleHandleW(nullptr); wc.lpszClassName=L"DumpHost";
    RegisterClassW(&wc);
    HWND h=CreateWindowW(wc.lpszClassName,L"d",WS_OVERLAPPED,0,0,64,64,nullptr,nullptr,wc.hInstance,nullptr);
    printf("attach rc=%d\n", s3_attach((int64_t)(intptr_t)h));
    printf("open rc=%d\n", s3_cmd("{\"a\":\"open\",\"url\":\"D:\\\\Movies\\\\Dune.2021.mkv\"}"));
    for(int i=0;i<14;++i){ Sleep(1000);
        static char buf[262144]; int n=s3_stats(buf,sizeof(buf));
        if(n<=0){ printf("tick %d stats rc=%d\n",i,n); continue; }
        printf("tick %d len=%d\n",i,n);
        const char* a=strstr(buf,"\"audio\"");
        const char* s=strstr(buf,"\"subtitle\"");
        if(a){ printf("AUDIO: %.400s\n",a); } else printf("AUDIO: ABSENT\n");
        if(s){ printf("SUB: %.300s\n",s); } else printf("SUB: ABSENT\n");
        const char* p=strstr(buf,"\"pos\""); if(p) printf("POS: %.60s\n",p);
        if(a) break;
    }
    s3_shutdown(); return 0;
}

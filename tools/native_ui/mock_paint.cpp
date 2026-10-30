// tools/native_ui/mock_paint.cpp — offline preview, TRUE 1.3.0 grammar.
// Metrics/palette copied from s3shell_panel.py (RIGHT_W=440 RAIL_W=80 ROW_H=40
// PAD=16 SECT_H=26 ICON_H=58 ICON_STEP=64 CONTROL_W=148 VALUE_W=58) and
// playback_bar.py (_SEEK_GROOVE). Renders EDIT + WATCH to PNG via GDI/GDI+.
#include <windows.h>
#include <gdiplus.h>
#include <cstdio>
#include <cstring>
using namespace Gdiplus;

static const COLORREF PANEL=RGB(14,14,16), PANEL2=RGB(35,35,39), HOT=RGB(35,35,39),
  ACTIVE_BG=RGB(30,30,32), BORDER=RGB(36,36,40), ACCENT=RGB(232,85,31),
  ACCENT2=RGB(255,138,76), TEXT=RGB(242,242,242), MID=RGB(138,138,144),
  LO=RGB(90,90,90), OFF_BG=RGB(42,42,46), TIME=RGB(204,204,204),
  GROOVE=RGB(46,46,48);
static const int RIGHT_W=440, RAIL_W=80, CAT_H=26, ROW_H=40, PAD=16,
  SECT_H=26, ICON_H=58, ICON_STEP=64, CONTROL_W=148, VALUE_W=58;

static void Fill(HDC dc, RECT r, COLORREF c){ HBRUSH b=CreateSolidBrush(c); FillRect(dc,&r,b); DeleteObject(b); }
static void Txt(HDC dc, RECT r, const wchar_t* s, COLORREF c, int px, bool bold=false,
                UINT al=DT_LEFT|DT_VCENTER|DT_SINGLELINE, const wchar_t* fam=L"Segoe UI"){
  HFONT f=CreateFont(-px,0,0,0,bold?FW_SEMIBOLD:FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,fam);
  HFONT of=(HFONT)SelectObject(dc,f); SetTextColor(dc,c); SetBkMode(dc,TRANSPARENT);
  DrawTextW(dc,s,-1,&r,al); SelectObject(dc,of); DeleteObject(f);
}
// Icon-tab column = GROUPS verbatim from s3shell_panel.py:139-146: glyph char,
// label, tint, and the glyph's optical size (GLYPH_OPTICAL: ▶=25, rest=F_ICON 30).
struct Grp{ const wchar_t* glyph; const wchar_t* label; COLORREF tint; int gpx; };
static Grp groups[]={
  {L"\x25B6",L"PLAYBACK",RGB(0x8A,0x7C,0xD8),25},   // ▶
  {L"\x2B21",L"SOURCE",  RGB(0x5B,0x8F,0xD0),30},   // ⬡
  {L"\x25D1",L"HDR",     RGB(0xC8,0xA0,0x30),30},   // ◑
  {L"\x2726",L"ZION",    RGB(0xC8,0x70,0x40),30},   // ✦
  {L"\x25A3",L"OUTPUT",  RGB(0x4C,0xAF,0x78),30},   // ▣
  {L"\x2261",L"SYSTEM",  RGB(0x90,0x90,0x90),30},   // ≡
};
// kind: 9=section header, 0=toggle, 1=slider, 2=cycle. Rows transcribed in
// order from s3shell_panel.py add(...) for group H (HDR).
struct Row{ int kind; const wchar_t* label; double f; bool on; const wchar_t* cyc; double mn,mx; const wchar_t* val; };
static Row rows[]={
  {9,L"TONE MAPPING",0,0,nullptr,0,0,L""},
  {0,L"Convert to SDR",0,true,nullptr,0,0,L""},
  {1,L"SDR display nits",0.47,false,nullptr,25,400,L"203"},
  {2,L"Tone curve",0,false,L"Unplugged",0,0,L""},
  {1,L"Exposure",0.5,false,nullptr,-1,1,L"0.00"},
  {1,L"Shadow detail",0.5,false,nullptr,-1,1,L"0.00"},
  {1,L"Contrast",0.5,false,nullptr,-1,1,L"0.00"},
  {2,L"Output gamut",0,false,L"BT.709",0,0,L""},
  {1,L"Gamut capacity (709)",0.0,false,nullptr,0,1,L"0.00"},
  {1,L"Highlight desat",0.5,false,nullptr,0,1,L"0.50"},
  {9,L"CURVE SETTINGS",0,0,nullptr,0,0,L""},
  {1,L"Title peak (nits)",0.3,false,nullptr,0,4000,L"1250"},
  {1,L"Soft knee (0=off)",0.0,false,nullptr,0,1,L"0.00"},
  {0,L"Auto exposure",0,false,nullptr,0,0,L""},
  {1,L"Highlight neutral (head)",0.9,false,nullptr,0,1,L"0.90"},
  {1,L"Chroma desat (exp)",0.3,false,nullptr,-1,3.5,L"1.00"},
  {9,L"DISPLAY TARGET",0,0,nullptr,0,0,L""},
  {2,L"Windows HDR",0,false,L"SDR",0,0,L""},
  {1,L"Static nits (max)",0.1,false,nullptr,10,10000,L"1000"},
  {1,L"Display black (nits)",0.0,false,nullptr,0,1,L"0.000"},
  {1,L"Subtitle/OSD brightness",0.8,false,nullptr,0,100,L"80"},
};
static const int NR=_countof(rows);
// Status rail rows transcribed from status_panel.py _build_rows (visible set
// for media playback), sections in file order.
struct KV{ const wchar_t* k; const wchar_t* v; bool sect; };
static KV stat[]={
  {L"VIDEO SOURCE",L"",true},
  {L"Resolution",L"3840×2160",false},
  {L"Pixel format",L"P010",false},
  {L"Colorspace",L"BT.2020",false},
  {L"Transfer (EOTF)",L"PQ (ST.2084)",false},
  {L"Source fps",L"23.976",false},
  {L"HDR format",L"HDR10",false},
  {L"Bitrate",L"45.20 Gbps",false},
  {L"MaxCLL",L"1250 nits",false},
  {L"MaxFALL",L"340 nits",false},
  {L"Mastering max",L"1000 nits",false},
  {L"Mastering min",L"0.0001 nits",false},
  {L"TONE MAPPING",L"",true},
  {L"Algorithm",L"Hable",false},
  {L"Frame peak",L"1250 nits",false},
  {L"APL (avg)",L"84 nits",false},
  {L"Target peak",L"203 nits",false},
  {L"PERFORMANCE",L"",true},
  {L"Display fps",L"23.98",false},
  {L"Dropped frames",L"0",false},
  {L"Delayed frames",L"0",false},
  {L"State",L"playing",false},
  {L"RENDER CHAIN",L"",true},
  {L"Renderer recv",L"1204",false},
  {L"Delivered",L"1204",false},
  {L"Skipped",L"0",false},
  {L"Gate dropped",L"0",false},
  {L"Queue drop",L"0",false},
  {L"Renegotiations",L"1",false},
  {L"Present lag",L"17 ms",false},
  {L"Stream time",L"00:42:11",false},
};
static const int NS=_countof(stat);

static void DrawSlider(HDC dc, int x0, int y, int right, const Row& r){
  int band_l = x0+150+4, band_r = right-PAD-VALUE_W;
  RECT band={band_l, y+ROW_H*2/5, band_r, y+ROW_H*2/5+ROW_H/5};
  Fill(dc,band,TEXT);
  int span=band_r-band_l, frac=(int)(r.f*span);
  if(frac>0){ RECT p={band_l,band.top,band_l+frac,band.bottom}; Fill(dc,p,ACCENT); }
  int cx=band_l+frac;
  RECT h={cx-6,band.top-4,cx+6,band.bottom+4}; Fill(dc,h,ACCENT2);
  wchar_t a[16],b[16]; swprintf_s(a,L"%.0f",r.mn); swprintf_s(b,L"%.0f",r.mx);
  Txt(dc,RECT{band_l,band.bottom+3,band_l+60,band.bottom+19},a,MID,11);
  Txt(dc,RECT{band_r-60,band.bottom+3,band_r,band.bottom+19},b,MID,11,false,DT_RIGHT);
  Txt(dc,RECT{right-VALUE_W,y,right-PAD,y+ROW_H},r.val,TEXT,13,false,DT_RIGHT|DT_VCENTER);
}
static void DrawEdit(HDC dc,int W,int H){
  Fill(dc,RECT{0,0,W,H},RGB(24,26,30));
  Txt(dc,RECT{W/2-140,H/2-20,W/2+140,H/2+20},L"VIDEO  (DirectX child)",RGB(70,74,80),20,false,DT_CENTER|DT_VCENTER);
  int top=40, barH=84, statW=340;
  // top strip
  Fill(dc,RECT{0,0,W,top},PANEL2);
  Txt(dc,RECT{16,0,220,top},L"UNPLUGGED",ACCENT,15,true);
  Txt(dc,RECT{W-140,0,W-16,top},L"—   ✕",MID,13,false,DT_RIGHT|DT_VCENTER);
  // left status rail
  int sx=8, sw=statW;
  Fill(dc,RECT{sx,top+4,sx+sw,H-barH-8},PANEL);
  int y=top+12;
  for(int i=0;i<NS && y<H-barH-16;++i){
    if(stat[i].sect){ Txt(dc,RECT{sx+PAD,y,sx+sw-PAD,y+SECT_H},stat[i].k,ACCENT,12,true); y+=SECT_H; }
    else { Txt(dc,RECT{sx+PAD,y,sx+sw/2+20,y+22},stat[i].k,RGB(0x66,0x66,0x66),12);
           Txt(dc,RECT{sx+sw/2+20,y,sx+sw-PAD,y+22},stat[i].v,RGB(0xE0,0xE0,0xE0),13,false,DT_RIGHT); y+=24; }
  }
  // right settings rail (width RIGHT_W, icon column RAIL_W)
  int rx=W-RIGHT_W-8;
  Fill(dc,RECT{rx,top+4,rx+RIGHT_W,H-barH-8},PANEL);
  for(int i=0;i<6;++i){
    int gt=top+4+i*ICON_STEP; bool act=(i==2);
    if(act){ Fill(dc,RECT{rx,gt,rx+RAIL_W,gt+ICON_H},ACTIVE_BG); Fill(dc,RECT{rx,gt,rx+3,gt+ICON_H},ACCENT); }
    // glyph centred in (0,top+6,RAIL_W,32) at its optical size, in the tint;
    // label centred in (0,top+38,RAIL_W,20) at F_RAIL (12 px DemiBold).
    Txt(dc,RECT{rx,gt+6,rx+RAIL_W,gt+38},groups[i].glyph,groups[i].tint,groups[i].gpx,
        true,DT_CENTER|DT_VCENTER,L"Segoe UI Symbol");
    Txt(dc,RECT{rx,gt+38,rx+RAIL_W,gt+58},groups[i].label,act?TEXT:MID,12,true,DT_CENTER|DT_VCENTER);
  }
  int cx0=rx+RAIL_W;
  Txt(dc,RECT{cx0+PAD,top+12,rx+RIGHT_W-PAD,top+12+CAT_H},
      L"Tone Mapping  ·  Curve Settings  ·  Display Target",MID,12);
  y=top+12+CAT_H;
  for(int i=0;i<NR;++i){
    const Row& r=rows[i];
    if(r.kind==9){ Txt(dc,RECT{cx0+PAD,y,cx0+PAD+18,y+SECT_H},L"▼",ACCENT,11,false,DT_LEFT|DT_VCENTER);
                   Txt(dc,RECT{cx0+PAD+18,y,rx+RIGHT_W-PAD,y+SECT_H},r.label,ACCENT,12,true,DT_LEFT|DT_VCENTER);
                   y+=SECT_H; continue; }
    Txt(dc,RECT{cx0+PAD+6,y,cx0+150-8,y+ROW_H},r.label,TEXT,12);
    int cright=rx+RIGHT_W;
    if(r.kind==0){ int w=46,h=22; RECT sw2={cright-PAD-w, y+(ROW_H-h)/2, cright-PAD, y+(ROW_H-h)/2+h};
      Fill(dc,sw2, r.on?ACCENT:OFF_BG); FrameRect(dc,&sw2,(HBRUSH)CreateSolidBrush(r.on?ACCENT2:BORDER));
      Txt(dc,sw2,r.on?L"ON":L"OFF", r.on?RGB(0,0,0):MID,11,false,DT_CENTER|DT_VCENTER); }
    else if(r.kind==1){ DrawSlider(dc,cx0,y,cright,r); }
    else { int left=cright-CONTROL_W, right=cright-PAD;
      Txt(dc,RECT{left,y,left+20,y+ROW_H},L"‹",ACCENT2,14,false,DT_LEFT|DT_VCENTER);
      Txt(dc,RECT{right-20,y,right,y+ROW_H},L"›",ACCENT2,14,false,DT_RIGHT|DT_VCENTER);
      Txt(dc,RECT{left+22,y,right-22,y+ROW_H},r.cyc,TEXT,13,false,DT_CENTER|DT_VCENTER); }
    y+=ROW_H;
  }
  // transport bar (seek-groove style)
  Fill(dc,RECT{0,H-barH,W,H},PANEL);
  const wchar_t* bl[]={L"❚❚",L"⏮",L"⏭",L"◀",L"▶"}; int x=12;
  for(int i=0;i<5;++i){ Txt(dc,RECT{x,H-barH+8,x+40,H-barH+30},bl[i],RGB(224,224,224),14,false,DT_CENTER|DT_VCENTER); x+=44; }
  RECT tr={268,H-barH+38,W-190,H-barH+42};
  Fill(dc,tr,GROOVE);
  double chaps[]={0.06,0.14,0.23,0.35,0.47,0.6,0.72,0.85};
  for(double c:chaps){ int cx2=tr.left+(int)(c*(tr.right-tr.left)); Fill(dc,RECT{cx2,tr.top-4,cx2+2,tr.bottom+4},RGB(255,255,255)); }
  int tx=tr.left+(int)(0.42*(tr.right-tr.left));
  Fill(dc,RECT{tr.left,tr.top,tx,tr.bottom},ACCENT);
  HBRUSH hb=CreateSolidBrush(RGB(255,255,255)); HBRUSH ob2=(HBRUSH)SelectObject(dc,hb);
  Ellipse(dc,tx-7,tr.top-5,tx+7,tr.bottom+5); SelectObject(dc,ob2); DeleteObject(hb);
  Txt(dc,RECT{W-185,H-barH,W-12,H},L"00:42:11 / 02:35:26",TIME,11,false,DT_RIGHT|DT_VCENTER);
}
static void DrawWatch(HDC dc,int W,int H){
  Fill(dc,RECT{0,0,W,H},RGB(24,26,30));
  Txt(dc,RECT{W/2-140,H/2-20,W/2+140,H/2+20},L"VIDEO  (clean fullscreen)",RGB(70,74,80),20,false,DT_CENTER|DT_VCENTER);
  int barH=84; Fill(dc,RECT{0,H-barH,W,H},PANEL);
  const wchar_t* bl[]={L"❚❚",L"⏮",L"⏭",L"◀",L"▶"}; int x=12;
  for(int i=0;i<5;++i){ Txt(dc,RECT{x,H-barH+8,x+40,H-barH+30},bl[i],RGB(224,224,224),14,false,DT_CENTER|DT_VCENTER); x+=44; }
  RECT tr={268,H-barH+38,W-190,H-barH+42}; Fill(dc,tr,GROOVE);
  int tx=tr.left+(int)(0.42*(tr.right-tr.left)); Fill(dc,RECT{tr.left,tr.top,tx,tr.bottom},ACCENT);
  HBRUSH hb=CreateSolidBrush(RGB(255,255,255)); HBRUSH ob=(HBRUSH)SelectObject(dc,hb);
  Ellipse(dc,tx-7,tr.top-5,tx+7,tr.bottom+5); SelectObject(dc,ob); DeleteObject(hb);
  Txt(dc,RECT{W-185,H-barH,W-12,H},L"00:42:11 / 02:35:26",TIME,11,false,DT_RIGHT|DT_VCENTER);
  Txt(dc,RECT{16,H-barH-26,520,H-barH-6},L"peek: mouse-move / bottom edge, auto-hides 3 s",MID,12);
}
static void Save(HBITMAP hb, const wchar_t* path){
  Bitmap* b=Bitmap::FromHBITMAP(hb,nullptr);
  CLSID png={0x557CF406,0x1A04,0x11D3,{0x9A,0x73,0x00,0x00,0xF8,0x1E,0xF3,0x2E}};
  b->Save(path,&png,nullptr); delete b;
}
int main(){
  GdiplusStartupInput gi; ULONG_PTR tok; GdiplusStartup(&tok,&gi,nullptr);
  int W=1920,H=1080;
  for(int m=0;m<2;++m){
    HDC mem=CreateCompatibleDC(nullptr);
    BITMAPINFO bi={}; bi.bmiHeader.biSize=sizeof(bi.bmiHeader); bi.bmiHeader.biWidth=W;
    bi.bmiHeader.biHeight=-H; bi.bmiHeader.biPlanes=1; bi.bmiHeader.biBitCount=32; bi.bmiHeader.biCompression=BI_RGB;
    void* bits; HBITMAP hb=CreateDIBSection(mem,&bi,DIB_RGB_COLORS,&bits,nullptr,0);
    HBITMAP ob=(HBITMAP)SelectObject(mem,hb); SetBkMode(mem,TRANSPARENT);
    if(m==0) DrawEdit(mem,W,H); else DrawWatch(mem,W,H);
    Save(hb, m? L"ui_mock_watch.png":L"ui_mock.png");
    SelectObject(mem,ob); DeleteObject(hb); DeleteDC(mem);
  }
  GdiplusShutdown(tok); printf("mocks written\n"); return 0;
}

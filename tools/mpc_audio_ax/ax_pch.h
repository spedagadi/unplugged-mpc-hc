// ax_pch.h — forced-include shim for the MpcAudioRenderer.ax wrapper.
//
// Every TU in this DLL gets MFC/ATL FIRST, before any DirectShow BaseClasses
// header. That ordering is load-bearing:
//   * BaseClasses/wxlist.h only defines its own __POSITION/POSITION when
//     __AFX_H__ is NOT set — with MFC first it uses ATL/MFC's POSITION and
//     the atlcoll.h redefinition (C2011) never happens.
//   * DSUtil.h includes atlcoll.h after streams.h and likewise requires
//     __AFX_H__ to already be defined.
// Also supplies <memory>/<iterator> which SimpleBuffer.h and std::size need
// when compiled without mpc-hc's app PCH.
#pragma once

#include <afxwin.h>
#include <memory>
#include <iterator>
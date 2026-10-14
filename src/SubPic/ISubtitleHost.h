/*
 * ISubtitleHost — the three things CTextPassThruFilter needs from whoever owns
 * the subtitle session.
 *
 * In mpc-hc.exe that owner is CMainFrame, and the filter held a raw CMainFrame*
 * for it. That pointer is the only reason the filter could not live in any other
 * graph builder: the headless engine (mpchc_engine) builds the same graph without
 * an MFC frame, and dragging CMainFrame into it would drag the whole player UI
 * with it. So the dependency is inverted onto this interface; CMainFrame
 * implements it by forwarding to the members it already had, and MpcPlayer
 * implements it against the allocator-presenter.
 *
 * Semantics are CMainFrame's, unchanged (MainFrm.cpp):
 *   SubLock()            the lock shared by ISubStream::SetStream / parameter edits
 *                        and the subpic queue's Render call. The queue wraps
 *                        providers in SubPicProviderWithSharedLock, so a provider
 *                        edited without it races the render thread.
 *   InvalidateSubtitle() drop cached pictures at/after rtInvalidate; the queue
 *                        re-renders from the provider on the next lookup.
 *   ReplaceSubtitle()    a provider was swapped under a live session (the pin's
 *                        AddSubStream/RemoveSubStream pair).
 */

#pragma once

#include <windows.h>

class CCritSec;          // BaseClasses
interface ISubStream;    // SubPic/ISubPic.h

struct ISubtitleHost
{
    virtual ~ISubtitleHost() {}

    virtual CCritSec* SubLock() = 0;
    virtual void InvalidateSubtitle(DWORD_PTR nSubtitleId, REFERENCE_TIME rtInvalidate) = 0;
    virtual void ReplaceSubtitle(const ISubStream* pSubStreamOld, ISubStream* pSubStreamNew) = 0;
};

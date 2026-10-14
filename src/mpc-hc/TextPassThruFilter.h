/*
 * (C) 2003-2006 Gabest
 * (C) 2006-2012 see Authors.txt
 *
 * This file is part of MPC-HC.
 *
 * MPC-HC is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * MPC-HC is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 */

#pragma once

#include "../SubPic/ISubtitleHost.h"

class CTextPassThruInputPin;

class __declspec(uuid("E2BA9B7B-B65D-4804-ACB2-89C3E55511DB"))
    CTextPassThruFilter : public CBaseFilter, public CCritSec
{
    friend class CTextPassThruInputPin;
    friend class CTextPassThruOutputPin;

    CTextPassThruInputPin* m_pInput;
    CTextPassThruOutputPin* m_pOutput;

    // Was a raw CMainFrame*. The filter only ever needs three members of its host
    // (the shared sub lock, invalidate, replace), so it now depends on that contract
    // instead of on the player's frame window — see SubPic/ISubtitleHost.h.
    ISubtitleHost* m_pHost;

public:
    CTextPassThruFilter(ISubtitleHost* pHost);
    virtual ~CTextPassThruFilter();

    DECLARE_IUNKNOWN;
    STDMETHODIMP NonDelegatingQueryInterface(REFIID riid, void** ppv);

    int GetPinCount();
    CBasePin* GetPin(int n);
};

# Subtitle support audit — 2026-11-18

Scope: embedded subtitles in Media Player mode, as shipped in 2.2.0/2.3.0.
(VP/live capture has no subtitle stream by definition.)

## Verdict

**Text subtitles are not excluded.** The pipeline accepts and decodes SRT,
ASS/SSA, WebVTT and MOV_TEXT (tx3g) in addition to PGS, VobSub and DVB. The
belief that only VobSub and PGS work is not supported by the code.

What the current evidence does **not** show is on-screen proof:

- the 26 Oct proof grabs (`tools/engine_s3/sub_proof1/2.bmp`) contain no text
  in the bottom quarter — the seek/cue timing missed the events, and the grab
  path may not composite the subtitle overlay at all;
- the 10 Nov field log (`docs/crash-2026-11-10/engine.log`) has a PGS track
  spliced but **subtitles Off** (`curSub=-1`, provider cleared), so it proves
  nothing about drawing either.

The user report ("internal subs won't show, and MPC-HC has the same outcome")
points at the **format**, not Unplugged: MPC-HC uses the same LAV Splitter and
the same MPC-HC subtitle stack. LAV silently drops formats it cannot map, so
neither player lists the track at all. The prime suspects are TTML/IMSC and
Blu-ray TEXTST (see the matrix).

## Pipeline

```
LAV Splitter (ffmpeg demux)
  -> subtitle output pin: MEDIATYPE_Text / MEDIATYPE_Subtitle + subtype
  -> CTextPassThruFilter (MPC-HC, spliced by the engine)
  -> CSubtitleInputPin::CompleteConnect -> decoder
        text   : CRenderedTextSubtitle (built-in renderer / libass)
        ASS/SSA: same, libass when active
        VobSub : CVobSubStream
        PGS    : CPGSSub
        DVB    : CDVBSub
  -> ISubStream -> ISubPicProvider
  -> MpcPlayer::ApplySubtitleProvider
  -> MPCVR CSubPicQueueImpl -> DrawSubtitles on the final SDR backbuffer
```

Key files:

| Stage | File |
| --- | --- |
| ffmpeg codec → DShow subtype | `src/thirdparty/LAVFilters/src/demuxer/Demuxers/LAVFStreamInfo.cpp:742-753` (`subtitle_format_map`) |
| Accepted media types | `src/Subtitles/SubtitleInputPin.cpp:79-86` |
| Decoder chosen at connect | `src/Subtitles/SubtitleInputPin.cpp:135-205` |
| Splice / track selection / provider | `src/mpchc_engine/MpcPlayer.cpp:2196-2212`, `5436-5462`, `5505-5677` |
| Renderer draw | `unplugged-VideoRenderer/Source/DX11VideoProcessor.cpp:7657` (`DrawSubtitles`) |
| Rail row | `tools/native_ui/native_ui.cpp:694`, populated at `10183` |

Subtitles are drawn **after** tone mapping and the Zion grade, on the final SDR
picture, so they are not tone-mapped; `hdr.osdBright` lifts the text layer.

## Format matrix

| Container / codec | LAV subtype | Engine accepts | Decoder | Status |
| --- | --- | --- | --- | --- |
| `S_TEXT/UTF8`, SRT, SUBRIP | `UTF8` | yes | RenderedTextSubtitle | **supported** |
| `S_TEXT/ASS`, SSA | `ASS` | yes | libass | **supported** |
| `S_TEXT/WEBVTT` | `WEBVTT` | yes | RenderedTextSubtitle (VTT) | **supported** |
| `tx3g` / MOV_TEXT (MP4) | `UTF8` | yes | RenderedTextSubtitle | **supported** |
| `S_HDMV/PGS` | `HDMVSUB` | yes (RLE) | CPGSSub | **supported** |
| `S_VOBSUB`, DVD in MP4/MPEG | `VOBSUB` | yes | CVobSubStream | **supported** |
| `S_DVBSUB` | `DVB_SUBTITLES` | yes (RLE) | CDVBSub | **supported** |
| Haali PGS (`NULL` + `FORMAT_SubtitleInfo`) | `NULL` | yes (RLE) | CPGSSub | **supported** |
| **TTML / IMSC** (`S_TEXT/TTML`, MP4 `txml`) | — | — | — | **not exposed by LAV** |
| **Blu-ray TEXTST** (`S_HDMV/TEXTST`) | — | — | — | **not exposed by LAV** |
| Teletext | — | — | — | **not exposed by LAV** |
| EIA-608/708 captions | — | — | — | **not handled** |
| USF | — | — | (decoder source exists) | not exposed by LAV |
| DVD subpicture as video pin (`DVD_SUBPICTURE`) | — | engine splices subtitle pins only | — | **not handled** |
| External `.srt` / `.ass` | — | — | — | **not supported** (`g_bExternalSubtitle=false`, `src/mpchc_engine/SubtitlePlayerGlobals.cpp:18`) |

LAV's `subtitle_format_map` is the gate: a codec id absent from it makes
`CreateSubtitleMediaType` return `E_FAIL`, so the track never reaches
`IAMStreamSelect` and no player sees it. `AV_CODEC_ID_TTML`,
`AV_CODEC_ID_HDMV_TEXT_SUBTITLE` and `AV_CODEC_ID_TELETEXT` are all absent.

## UI and behaviour

- Playback → **Subtitles → Track**: `Off` plus every subtitle stream the
  splitter reports, with language and format in the name.
- **Off by default.** Subtitles do not auto-select, and there is no auto-select
  for forced tracks.
- Selecting a track is **not live**: it queues a re-open of the same file at the
  current position (`SetSubtitleTrack`), then the chosen stream is enabled
  before the splice, so the decoder is built for the right track.
- One subtitle stream is spliced at a time; the list is wider than the splice.
- No font/size/position/colour controls; no subtitle delay (the presenter has
  `SetSubtitleDelay`, nothing exposes it). The audio Delay row is also inert,
  as the guide states.
- External sidecar subtitles are not supported.

## Diagnostics already in the engine

```
[SUBS] pin 0 offered: PGS cbFormat=520 dwOffset=520 lang=ger
[SUBS] subtitle pins found=1 target=0 spliced=1; initial selection=Off
[SUBS] subpic provider attached|cleared (subsOn=.. curSub=.. subs=..)
[GRAPH] pending subtitle track N applied at connect hr=0x...
[live] subs: render11=.. drew=.. lastRt=..s noQueue=..
[live] subq: depth=.. rtNow=.. cached=[..] lastHr=.. hit=.. geoHr=..
[SUBS] probe: rt=.. -> event A..B (ACTIVE now)
[SUBS] probe: rt=.. -> nothing at/after rt; first parsed=exists|NONE
```

Reading it:

- **No `offered:` line and `spliced=0`** while the rail shows only `Off` → the
  splitter exposed no subtitle stream (format not mapped by LAV).
- **`offered:` present, provider cleared with `curSub=-1`** → the user has not
  selected a track (this is the 10 Nov field log).
- **Provider attached, probe says ACTIVE, `drew=0`** → decode/render leg
  (font/libass/queue); `render11=0` would instead mean the renderer never calls
  the subtitle path.
- **Tracks listed but selection does nothing** → check
  `pending subtitle track N applied`; a second command issued during the
  re-open can deadlock (documented in `tools/engine_s3/sub_proof.cpp`).

## The report

Ask for two artifacts:

1. `ffprobe -v error -select_streams s -show_entries
   stream=index,codec_name,codec_tag_string:stream_tags=language,title,forced
   -of json "<file>"` — the definitive format list.
2. The diagnostics zip; the lines above tell which leg failed.

Decision tree:

- `codec_name` = `ttml`, `hdmv_text_subtitle`, `teletext`, `eia_608` → confirmed
  format gap; MPC-HC fails for the same reason. Not a regression; a feature gap.
- `codec_name` = `subrip`/`ass`/`hdmv_pgs_subtitle` and no track in the rail →
  investigate the splitter/engine, not the file.
- Track selectable and ACTIVE but `drew=0` → render bug; reproduce with the same
  cue and capture the log.

## Gaps and possible work (not committed)

1. **External sidecars (SRT/ASS)** — highest value per effort. The
   `SubtitleSource` filter exists in the tree but is not wired.
2. **TTML/IMSC** — needs a TTML→ASS/SRT conversion before libass; no existing
   decoder in the stack.
3. **HDMV TEXTST** — ffmpeg can demux it (`AV_CODEC_ID_HDMV_TEXT_SUBTITLE`);
   needs a decoder/segment assembler and a LAV mapping.
4. **Make unsupported streams visible** — log the codec id when LAV's
   `CreateSubtitleMediaType` fails, so a report says "TTML, unsupported" instead
   of "no subtitles".
5. **Styling and delay UI** — small; both back-ends already support them.
6. **Docs** — FEATURES says track switching is "live" (it re-opens) and implies
   styling controls exist (they do not); correct both.
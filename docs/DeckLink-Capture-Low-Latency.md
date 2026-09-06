# DeckLink capture — low-latency acquisition recipe

How to open a Blackmagic DeckLink input for minimum-latency ingest.
Taken from the proven HTPC A/B setup in `C:\Code\unplugged` (mpv + libav)
and verified against the FFmpeg 8.0 source tree this project builds
(`C:\Code\LAVFilters\ffmpeg`, `libavdevice/decklink_dec_c.c`,
`libavformat/options_table.h`).

## The option set

Pass every one of these through the **same `AVDictionary`** you hand to
`avformat_open_input()`:

```c
AVDictionary *opts = NULL;
av_dict_set(&opts, "analyzeduration", "0",        0); // no long probe before first frame
av_dict_set(&opts, "fflags",         "nobuffer", 0); // AVFMT_FLAG_NOBUFFER
av_dict_set(&opts, "rtbufsize",      "32M",      0); // bump libav's 3041280-byte default
av_dict_set(&opts, "raw_format",     "2",        0); // 10-bit YUV 4:2:2 (v210-class)
av_dict_set(&opts, "video_pts",      "wallclock",0); // wallclock PTS → frame-age diag
// (av_dict_copy order-independent; "fflags" is a flags bitmask, "nobuffer" one bit)

int ret = avformat_open_input(&fmt, url, NULL, &opts);
if (ret == 0)
    fmt->flags |= AVFMT_FLAG_NOBUFFER;   // belt-and-braces with fflags=nobuffer
```

Then, on the *first* decoder context:

```c
avctx->flags |= AV_CODEC_FLAG_LOW_DELAY;
```

## What each option does (verified against this tree)

| Option | Target | Default | Effect |
|---|---|---|---|
| `analyzeduration=0` | `max_analyze_duration` | 0 (= libav default) | Don't let the open/probe scan delay the first frame on a live, non-seekable input |
| `fflags=nobuffer` | `AVFMT_FLAG_NOBUFFER` | `AVFMT_FLAG_AUTO_BSF` | "reduce the latency introduced by optional buffering" — stops latency accumulating inside libavformat's decklink path |
| `rtbufsize=32M` | `max_picture_buffer` | 3,041,280 B (~2.9 MiB) | The capture ring. DeckLink 4K HDR is ~1 Gbps (~125 MB/s); the 2.9 MiB default overflows → the source dies immediately. 32 MiB ≈ 256 ms at that rate |
| `raw_format=2` | decklink indev | `0` = auto | Pin 10-bit YUV 4:2:2 (`yuv422p10`). Full enum below |
| `video_pts=wallclock` | decklink indev | `2` = `PTS_SRC_VIDEO` | PTS from wallclock — used as a frame-age latency *diagnostic*. Not itself a reduction |
| `AV_CODEC_FLAG_LOW_DELAY` | decoder | off | Decoder low-delay mode + drop late frames |

### decklink `raw_format` enum (`decklink_dec_c.c`)

```
0 auto  1 uyvy422  2 yuv422p10  3 argb  4 bgra  5 rgb10
```

### decklink `video_pts` enum (`decklink_common_c.h`)

```
1 PTS_SRC_AUDIO  2 PTS_SRC_VIDEO  3 PTS_SRC_REFERENCE
4 PTS_SRC_WALLCLOCK  5 PTS_SRC_ABS_WALLCLOCK
```

## Deliberately NOT set (do not regress)

- **`probesize`** — leave default (5,000,000 B). Setting it delays first frame.
- **`queue_size`** — leave default (1 GiB). The decklink capture queue absorbs
  brief app stalls without frame loss; it only becomes latency when the consumer
  is *sustained*-behind, which `nobuffer` + drop-on-late renders self-limiting.
- **`demuxer-max-bytes` / a large byte cap** — in mpv this let the demuxer run
  ~0.8 s ahead (+500 ms latency that blew the AVR lip-sync budget). No analog in
  raw libav; the caution carries over: don't add a read-ahead packet queue.
- **`analyzeduration > 0`** — any non-zero probe delay is dead latency on live input.

## Architecture-level behaviors the mpv chain also needed

These are not avflags, but the Unplugged rig needed all of them to hit its
budget. The mpc-hc capture path must be shaped the same way:

1. **Pull, don't push.** `--no-demuxer-thread`: read+decode in a single tight
   loop (`av_read_frame` → feed decoder immediately, back-directed). A producer
   thread that runs ahead of the consumer is the same as buffering.
2. **No read-ahead cache** on the live input (`--no-cache`).
3. **Drop when behind** (`--framedrop=decoder`): if the consumer lags wallclock,
   discard video frames rather than letting the queue grow.
4. **Warm-up hold / drain**: present black until the pipeline (here: Zion ML
   warm) is ready, then cut over — so acquisition start feels instant and stays
   in the A/V lip-sync budget. `--ml-acq-warm-hold` / `--ml-acq-drain` in the
   source rig; mpc-hc has its own equivalents.
5. Nothing else. In particular, the video-sync/queue-depth tricks that *look*
   latency-related (swapchain-depth, etc.) broke capture on the rig — keep the
   flag set to this minimal, proven list.
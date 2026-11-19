# Unplugged 1.2.0

A new poster library for your films and TV shows, a simpler settings panel, and Super Resolution as a single switch.

## What's new

### Poster library
- The Media Library is now a **poster grid** with **Movies**, **TV Shows** and **Folders** tabs. You can browse it with a remote (Enter to open or play, Back to go up).
- **Multiple library folders.** Add or remove folders from the library screen. Your existing media folder from 1.1.x is added automatically.
- **Stays up to date.** Each time Unplugged starts it checks your folders in the background. New files appear and removed ones disappear, and you can watch while it works. Films on a drive that's switched off or unplugged stay in the library until it comes back.
- **Uses your own artwork first:** poster files next to your films, folder art, and covers stored inside MKV/MP4 files. Kodi, Plex and Jellyfin file names are recognised.
- **Downloads missing posters** from OMDb (IMDb data) for titles with no artwork. A poster is used only when the title and year match, so you get a plain tile rather than the wrong film's poster.
- Downloaded posters are **saved next to your media** (for example `Film (2021)-poster.jpg`), so other players can use them and they survive a reinstall. If the folder is read-only they are kept only in Unplugged's own cache.

### Settings
- Clearer section headers, and every section starts **collapsed**: open one section at a time.
- The **Output** tab now shows only what most people need: Calibration LUT, scaling, Super Resolution and Save as PNG. The advanced settings are still kept and still apply.
- **Super Resolution is now an On/Off switch.** Turning it on also sets the related settings it needs, so it works without further tuning.

## Upgrading from 1.1.x
- Install over your existing version; your settings are kept.
- The first start builds the library and fetches posters, which can take a few minutes for a large collection. You can use the app meanwhile.

## Good to know
- **Privacy:** to find posters, the titles and years taken from your file names are sent to OMDb (omdbapi.com). Nothing else is sent. To turn this off, set `"library_online_art": false` in `%USERPROFILE%\.unplugged\app_config.json`.
- **Don't want posters written next to your files?** Set `"library_save_posters": false` in the same file. Posters are then kept only in Unplugged's cache.
- **Wrong or missing poster?** Put your own image next to the film as `<film file name>-poster.jpg` and press **Rescan**. Your own artwork always takes priority.
- **Deleted a downloaded poster?** It is downloaded again on the next start.
- **Super Resolution** needs an NVIDIA RTX or a recent Intel GPU, and applies to SDR, 8-bit video only. HDR and 10-bit sources play normally without it.
- **Posters per day:** downloads are limited to a daily allowance. If it runs out, the remaining posters arrive on a later start. Heavy users can add their own free OMDb key as `"omdb_api_key"` in the config file.

## Known limitations
- No "fix match" screen yet. Use the poster-file workaround above.
- TV shows get a show poster only; no individual season posters from OMDb yet.
- Very new or obscure titles may not be on OMDb and keep a plain tile.

## Download
| File | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-1.2.0.exe` | 185,974,630 bytes | `65600E1A01637F142E6D709AF95ABF5147BB30993A44353771DA770FEB65F7D3` |

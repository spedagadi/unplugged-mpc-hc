# MpcAudioRenderer silence — diagnosis and verification

Status: **DirectSound fallback and PCM downmix audibly confirmed by the user;
1.1.0 installer rebuilt with matching UI and executable versions.** The PCM fix
uses the Windows output endpoint's channel layout for LAV mixing; bitstream mode
leaves mixing disabled. The engine DLL SHA-256 is
`F3EA1B429727F918D0854DAB6F123C5AA0E71110EAB46388C370008A74CE64AE`.
The new installer still requires installed-app acceptance testing. AVR bitstream
and the private WASAPI renderer remain unvalidated.

Packaging: the UI version is defined in
`src/unplugged-ui/src/mpvprocessor/__init__.py`; `unplugged.spec` uses that value
for the executable's Windows file/product versions. Keep the package version in
`src/unplugged-ui/pyproject.toml` and `MyAppVersion` in `distrib/unplugged.iss`
aligned. Run PyInstaller before `distrib/build_unplugged_setup.ps1`; the installer
build rejects a packaged executable whose product version differs from the UI
or installer source.

The following diagnosis records the earlier investigation state.

Earlier status: **Installer regression identified; rollback installer prepared, listening
test still required.** Before the audio verification installer, the dev build repeatedly
logged `CoCreate(renderer=DSound)`. After the installer registered
MpcAudioRenderer's private CLSID, the same app instead logged
`CoCreate(renderer=MpcAudioRenderer)`; the installed app also played the test
file but was silent. Registering the unvalidated WASAPI renderer changed the
known-working fallback path. The corrected installer no longer includes or
registers MpcAudioRenderer. It removes the previous registration only if the
private CLSID still points at this product's exact installed AX path. The
current machine must run that installer as administrator (or manually
unregister the AX) before both installed and dev builds return to DirectSound.
The current shell is not elevated, so that machine-wide registration is still
present until the corrected installer is run.

The original reproduction observations are retained below for context.

---

## 1. Symptom

Media Player mode, any file (local or UNC), PCM ("Decode to LPCM") or bitstream:
video plays, **no audio at all**. Engine log shows the audio graph built and
configured successfully:

```
[AUDIO] CoCreate LAVAudio hr=0x00000000
[AUDIO] AddFilter LAVAudio hr=0x00000000 CoCreate(renderer=MpcAudioRenderer) hr=0x00000000
[AUDIO] connect splitter->decoder hrE=0x00000000 decoder->renderer hrF=0x00000000
[AUDIO] cfg enter: configured id='' len=0 name=''
[AUDIO] default render endpoint: id-len=55 name='MSI MD342CQP (NVIDIA High Definition Audio)'
[AUDIO] renderer cfg mode=bitstream device='MSI MD342CQP (NVIDIA High Definition Audio)' apply=0x00000000
```

(`mode=shared` in the PCM case; same silence.) Renaming the filter to
`MpcAudioRenderer.ax.off` makes the engine fall back to `CoCreate(renderer=DSound)`
and **audio returns**. That rename is the only known workaround.

## 2. The comparison that defines the bug

| binary | registration | device string passed | audible? |
|---|---|---|---|
| September 2026 dev build (`C:\htpc\s3_shell_htpc\bin\MpcAudioRenderer.dll`, **now deleted from disk**, was registered under MPC-BE's CLSID `601D2A2B-9CDE-40bd-8650-0485E3522727`) | correct | empty (`device=''`) | **YES** on this HTPC |
| Rebuilt 2026-10-19 from current sources (`tools\mpc_audio_ax\mpc_audio_ax.vcxproj`), private CLSID `7E3A9C24-6B18-4F5D-9A2E-8C4B7D6F1A35` | correct (after fix §4.1) | empty, then explicitly the resolved system-default endpoint id | **NO** on this HTPC and on a customer box |

Same machine and file (`D:\Dune.2021...NIMA4K.mkv`). The current log records the
`eMultimedia` default endpoint. The renderer's empty-device path instead resolves
the `eConsole` default (`AudioDevice.cpp:GetDefaultAudioDevice`); Windows permits
those roles to point at different endpoints. The two paths therefore did not
necessarily target the same device, despite both being described as "default."

## 3. Environment

- Dev HTPC: Windows 11 Pro 10.0.26200, RTX 4060, AVR + monitor endpoints; default
  render endpoint = `MSI MD342CQP (NVIDIA High Definition Audio)`.
- Customer box: Windows 11 Pro 10.0.26300, RTX 3050 **plus `Epson Projection Idd
  Device` in Error state**, K-Lite Codec Pack + MPC-BE installed (see §7).
- App: `C:\Program Files\Unplugged\Unplugged.exe` (installed) and
  `C:\code\unplugged-mpc-hc\src\unplugged-ui\dist\Unplugged\Unplugged.exe` (dev).
- Engine: `tools\s3engine\s3engine.dll` over `bin\lib\Release_x64\mpchc_engine.lib`.
- Harness: `tools\engine_s3\sub_proof.exe` — loads
  `dist\Unplugged\_internal\s3engine.dll` (the PACKAGED copy, not
  `tools\s3engine\`), opens the Dune file, plays ~25 s. **If you rebuild the engine
  you must re-run PyInstaller or the harness tests the old binary.** This cost
  three wasted diagnosis rounds.

## 4. Earlier work and validation

1. **Registration wrote `regsvr32.exe` as `InprocServer32`.** Root cause:
   `tools\mpc_audio_ax\ax_app.cpp` defines a `CWinApp`, so MFC supplies `DllMain` and
   BaseClasses' entry (which sets `g_hInst`, `dllentry.cpp:319`) never runs;
   `dllsetup.cpp:393` then calls `GetModuleFileNameA(NULL,...)` = the host exe.
   Fixed with `g_hInst = AfxGetInstanceHandle();` in `InitInstance`. Verified:
   `regsvr32 /s` exit 0 and the CLSID resolves to the real `.ax`.
2. **Private CLSID** `7E3A9C24-6B18-4F5D-9A2E-8C4B7D6F1A35` in
   `src\thirdparty\MpcAudioRenderer\MpcAudioRenderer.h` and in
   `src\mpchc_engine\MpcPlayer.cpp` (`CLSID_MpcAudioRenderer`, ~line 65). MPC-BE's
   `601D2A2B-…` left untouched on purpose.
3. **Build chain**: `tools\mpc_audio_ax\mpc_audio_ax.vcxproj` now compiles
   `src\thirdparty\AudioTools\{Mixer,AudioFilter,AudioHelper,SampleFormat,DitherInt16}.cpp`
   and `src\thirdparty\bs2b\libbs2b\src\{bs2b.c,bs2bclass.cpp}` in place of the
   nonexistent `AudioTools.lib`/`bs2b.lib`; ffmpeg headers+import libs come from
   `C:\code\LAVFilters\ffmpeg` + `C:\code\LAVFilters\bin_x64\lib`
   (`avfilter-lav.lib swresample-lav.lib avutil-lav.lib`); `bs2bconvert.c` excluded
   (it is libbs2b's CLI tool, needs libsndfile); the two `.c` files need empty
   `<ForcedIncludeFiles>` or MFC's `afx.h` fails them.
4. **Engine logging**: `[AUDIO]` lines moved from `std::cout` (invisible in a GUI
   process) to `Log()` in `MpcPlayer.cpp` `ConnectAudio`/`ApplyRendererConfig`.
   Two formatter traps cost a round each: `Log()` **silently drops any line
   containing `%zu`**, and passing `Utf8(x)` (a `std::string`) by value into its
   varargs prints object bytes — always `.c_str()`.
5. **Auto-device routing change was speculative and has been rolled back.** It
   changed the empty-device behavior based on a possible `eConsole` versus
   `eMultimedia` mismatch, without proving that this caused silence. Do not
   reintroduce that change until the renderer path has a controlled audibility
   test.

## 5. Diagnosis and remaining verification

1. **Installer registration changed the selected renderer.** Before installation,
   the dev app logged `CoCreate(renderer=DSound)` repeatedly at 13:28–13:30.
   After installing the verification build, the same dev app logged
   `CoCreate(renderer=MpcAudioRenderer)` at 13:47; the installed app launched from
   `C:\Program Files\Unplugged\Unplugged.exe` at 13:44. The installer's new
   machine-wide registration made the engine select the unvalidated WASAPI
   renderer instead of its previously working DirectSound fallback. Successful
   COM creation, pin connection, and `Apply()` do not establish that samples
   reached the speakers. The evidence strongly implicates this registration
   change; confirm by re-testing after it is removed.
2. **The installed engine log is not fresh.** The installed app's UI log records
   the 13:44 playback, but `C:\Program Files\Unplugged\s3engine.log` did not
   update, likely because the app's current-directory log is in a protected
   folder. Do not use its old contents as evidence about that run.
3. **Mute/volume fallback was checked and is not the likely cause.**
   `CMpcAudioRenderer` initializes volume to `DSBVOLUME_MAX` and balance to center;
   the `GetProfileInt` fallback values for device mode and processing flags do not
   set volume to zero. The wrapper's `CWinApp` profile is still host-specific, but
   missing preferences alone should retain those initialized defaults.
4. **WASAPI thread/message-loop assumptions remain unverified.** The event-driven
   render thread does not depend on a UI message pump, and the real app also
   reproduced the issue. Investigate only if the restored fallback is still silent.
5. **Format negotiation remains a separate renderer investigation.** If testing
   MpcAudioRenderer resumes, capture input/output `WAVEFORMATEX` and compare with
   the endpoint's mix format, then inspect queue/render progress.
6. **The September binary is gone.** Git has the tree as of `751b28429`
   (2026-09-06, "snapshot … MpcAudioRenderer.ax (as-is)"). Renderer source changes
   since that snapshot are limited to property-page and private-CLSID integration.

## 6. Reproduce

```
regsvr32 /u /s "C:\Program Files\Unplugged\filters\MpcAudioRenderer.ax"
```
Audibility needs a human or a loopback capture; there is no in-process meter.

Install the fallback-verification build as administrator. It removes the old
MpcAudioRenderer registration if and only if it resolves to the exact
`{app}\filters\MpcAudioRenderer.ax` path from the broken verification installer.
Then play the same file in both the installed app and dev app, and confirm the
engine log selects `CoCreate(renderer=DSound)`.
Audibility is the acceptance criterion; graph success alone is insufficient.
When an AVR is available, separately validate Atmos/HD-audio bitstream behavior
before shipping or enabling the WASAPI renderer.

## 7. Separate, do not confuse with this issue

- **Video blank with `hr=0x80040217` (`VFW_E_CANNOT_CONNECT`)** on the customer box
  was K-Lite Codec Pack re-registering the shared LAV CLSIDs
  (`171252A0…/EE30215D…/E8E73B6B…`) to its own copies after our install. Re-running
  our installer (or `regsvr32` of our filters, last) fixes it. Reproduced here by
  installing K-Lite. Unrelated to audio.
- The engine's `ConnectAudio` returns `S_FALSE` (treated as success) when audio
  cannot be connected, so a broken audio path never fails the open — by design,
  video-first.
- `distrib\unplugged.iss` ships five filters; MpcAudioRenderer is deliberately
  excluded until its output is validated end-to-end.

## 8. Installer state right now

The previous `Unplugged-setup-1.0.0-audio-verify.exe` included and registered
MpcAudioRenderer, and is not a working audio verification build. The corrected
`distrib\out\Unplugged-setup-1.0.0-audio-fallback-verify.exe` uses the known
DirectSound-fallback package, size 184,760,644 bytes, SHA-256
`31E666B4DC2B01537C75DEDBF25E1F3BA0E74AE44AD30644D18C000EB936463D`. It removes
the old registration only when it still points to this product's AX. The
release-named installer was not overwritten. Playback still needs a listening
test after installation.

# Unplugged 1.1.0 session handover

Date: 2026-10-19

## 1. Executive summary

This session investigated silent playback, quieter PCM playback compared with
VLC, subtitle defaults, and release packaging.

- The user confirmed that the corrected installer restored audible playback.
- The user confirmed that endpoint-aware PCM downmix fixed the perceptible
  volume difference on their stereo HDMI monitor.
- Subtitles now start Off, and subtitle media types are classified explicitly.
- A new installer was built with version 1.1.0 consistently represented in the
  UI and Windows executable metadata.
- **Release blocker:** the existing `v1.1.0` tag does not contain the subsequent
  version-metadata and packaging-check corrections. Those edits are still
  uncommitted.
- The rebuilt 1.1.0 installer still needs installed-app acceptance testing.
  No AVR was available, so Atmos/HD-audio bitstream passthrough is not validated.

## 2. Repositories and release state

| Repository | Branch | Last checked commit | Release tag |
| --- | --- | --- | --- |
| `C:\code\unplugged-mpc-hc` | `zion-s3-shell` | `8ad6a400e24c0aba87539056b9ead7276eba7c87` | `v1.1.0` |
| `C:\code\unplugged-VideoRenderer` | `zion-ml-phase0` | `8f28b94` | Existing `v1.0.0` |
| `C:\code\LAVFilters` | `master` | `e0a23179` | Existing `v1.0.0` |

The audio engine and MpcAudioRenderer sources belong to the MPC-HC repository,
not separate repositories. No new tracked source changes were identified in the
other two repositories during the release inspection. The earlier sibling
status probes were interrupted while enumerating files; do not treat that as a
complete audit of every untracked file or submodule.

At handover, local `origin/zion-s3-shell` resolves to `8ad6a400e`. Earlier push
attempts failed for authentication, but the local remote-tracking reference has
since advanced to the release commit. **This does not independently prove the
remote tag exists.** Query the live remote before changing tags or publishing.

## 3. Audio investigation and fixes

### Silence after installing the audio verification build

An earlier verification installer registered Unplugged's private
MpcAudioRenderer CLSID. That changed the engine's renderer selection from its
working DirectSound fallback to an unvalidated WASAPI renderer. Playback could
connect successfully yet remain silent.

The corrected installer:

- Does not ship or register MpcAudioRenderer.
- Uses the working DirectSound fallback when the private renderer is absent.
- Removes the previous private registration only when its registered path
  exactly matches `{app}\filters\MpcAudioRenderer.ax`.
- Logs and displays a failure if that unregister operation fails.
- Does not unregister MPC-BE's renderer or another installation's path.

Private CLSID: `{7E3A9C24-6B18-4F5D-9A2E-8C4B7D6F1A35}`.

MPC-BE's distinct CLSID remains untouched:
`{601D2A2B-9CDE-40bd-8650-0485E3522727}`.

### Low PCM volume

Before the downmix change, LAV mixing was disabled and decoded 7.1 PCM was sent
to DirectSound while the active output was a stereo HDMI monitor.

In [MpcPlayer.cpp](../src/mpchc_engine/MpcPlayer.cpp):

- `QueryAudioMixLayout` queries the Windows endpoint using
  `IAudioClient::GetMixFormat`.
- PCM mode configures LAV mixing for that endpoint's channel mask.
- Bitstream mode disables LAV mixing.
- Invalid or unavailable layouts produce a diagnostic and leave mixing
  disabled rather than silently assuming stereo.
- Logs record LAV mode/mixing state and negotiated audio format.

Verified runtime evidence:

```text
[AUDIO] PCM endpoint mix layout channels=2 mask=0x00000003
[AUDIO] LAV runtime mode=PCM ... mixing=1 layout=0x00000003
[AUDIO] negotiated output format tag=0x0003 channels=2 rate=48000 bits=32 mask=0x00000000
```

The user confirmed this fixed the volume problem.

Matching multichannel endpoint layouts is implemented, but surround hardware
was not tested. Hearing decoded sound on a monitor while Bitstream is selected
does not establish encoded Atmos passthrough to an AVR.

### MpcAudioRenderer source and binary locations

Main source tree:
[src/thirdparty/MpcAudioRenderer](../src/thirdparty/MpcAudioRenderer).

Sources/build files changed and included in the existing `v1.1.0` commit:

- [MpcAudioRenderer.h](../src/thirdparty/MpcAudioRenderer/MpcAudioRenderer.h):
  private CLSID.
- [ax_app.cpp](../tools/mpc_audio_ax/ax_app.cpp): sets BaseClasses' `g_hInst`
  from `AfxGetInstanceHandle()` so COM registration records the filter module,
  rather than the registrar executable.
- [mpc_audio_ax.vcxproj](../tools/mpc_audio_ax/mpc_audio_ax.vcxproj):
  AudioTools/bs2b compilation and matching LAV FFmpeg headers/import libraries.

Existing renderer implementation files, including `MpcAudioRenderer.cpp` and
`AudioDevice.cpp`, are also present in the tagged tree even when unchanged.

Generated binaries:

```text
src\thirdparty\MpcAudioRenderer\bin\Filters_x64\MpcAudioRenderer.ax
tools\mpc_audio_ax\x64\Release\MpcAudioRenderer.dll
```

At inspection, these were identical:

```text
SHA-256: 12125B87CC05AC9302500E37F3032A2CF0ADCB1FA219F31FF2DDD45F07D9C602
Size: 4,980,224 bytes
```

The AX is not committed or included in the current installer. The rebuilt
renderer DLL is an unstaged modification to an already-tracked binary. These
facts are intentional distinctions from the committed source fixes; do not
re-enable this renderer in a production installer without end-to-end validation.

## 4. Subtitles

- Removed startup selection of a subtitle track: the rail and renderer start
  with subtitles Off until the user selects a track.
- Explicitly classify `MEDIATYPE_Text` and `MEDIATYPE_Subtitle`.
- Investigated the Dune remux's sparse forced subtitles. The German Forced SRT
  track contained only three cues in the first ten minutes and valid UTF-8.
- VLC showed similar sparse content, so this was not evidence of a remaining
  decoder fault. Do not claim every subtitle format was comprehensively tested.

## 5. Build and validation

Native engine builds succeeded using:

```powershell
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"
cmd /c "C:\code\unplugged-mpc-hc\tools\s3engine\build_s3engine.bat"
```

The separate shell regression build failed with missing `streams.h`. This was
treated as a pre-existing build/include-path issue; it remains unresolved.
Do not describe the full regression build as passing.

Verified engine:

```text
tools\s3engine\s3engine.dll
SHA-256: F3EA1B429727F918D0854DAB6F123C5AA0E71110EAB46388C370008A74CE64AE
```

Packaging uses the existing environment:

```text
C:\code\unplugged\app\.venv\Scripts\python.exe
PyInstaller 6.22.2
```

The system Python lacked PyInstaller; use the established environment.
The latest app was built into an isolated release directory before promotion
to the normal installer input directory. The previous normal package was
preserved as `src\unplugged-ui\dist\Unplugged-pre-1.1.0`.

The gated installer script successfully ran runtime, license and source-path
checks, followed by the Inno Setup compile. Do not bypass those gates.

## 6. Version correction after the release commit

The installer declared 1.1.0, but the UI's `__version__` still declared 1.0.0.
Corrected:

- [UI version](../src/unplugged-ui/src/mpvprocessor/__init__.py): 1.1.0.
- [Package metadata](../src/unplugged-ui/pyproject.toml): 1.1.0.
- [PyInstaller spec](../src/unplugged-ui/unplugged.spec): reads the UI version
  and embeds Windows file/product version resources.
- [Installer build script](../distrib/build_unplugged_setup.ps1): rejects
  mismatched UI/installer versions or stale packaged EXE product versions.
- [Audio diagnosis](ISSUE-mpcaudiorenderer-silence.md): updated status and
  packaging instructions; historical investigation details retained.

Validation:

- Extracted `mpvprocessor` from the executable's embedded PyInstaller archive:
  `__version__ == "1.1.0"`.
- App Windows file version and product version both equal 1.1.0.
- Installer product version equals 1.1.0.
- Packaged engine SHA-256 matches the verified engine above.
- Relevant `git diff --check` passed.
- Installer completed a full gated build.
- Installed-app runtime acceptance of this final package is still pending.

## 7. Release artifacts

### Current 1.1.0 installer

```text
C:\code\unplugged-mpc-hc\distrib\out\Unplugged-setup-1.1.0.exe
Size: 184,869,185 bytes
SHA-256: E02FEC503BA4559E05963CC168142EDA81C3DCD200CE5FD4B36DD853031E1BE9
```

App:

```text
C:\code\unplugged-mpc-hc\src\unplugged-ui\dist\Unplugged\Unplugged.exe
Size: 1,992,260 bytes
SHA-256: 7F2E9A1A71E5727790DF1445BCD45C0C0F4FD5369AAB6E99E9851D70D62999F0
File/Product version: 1.1.0
```

Use this installer, not the older verification installers, for release testing.

### Earlier verification installer (superseded)

```text
distrib\out\Unplugged-setup-1.0.0-pcm-downmix-verify.exe
Size: 184,820,483 bytes
SHA-256: 7F5E2AE1D021038C728D2624C75F33867A9D0EA1DC57D54411561986560ED9B7
```

Session packaging logs:

```text
C:\Users\satee\.copilot\session-state\1f3956a7-85cf-48a6-98a4-839089e1421a\files\pyinstaller-1.1.0.log
C:\Users\satee\.copilot\session-state\1f3956a7-85cf-48a6-98a4-839089e1421a\files\installer-1.1.0.log
```

## 8. Git status and ignore cleanup

Release commit:

```text
8ad6a400e24c0aba87539056b9ead7276eba7c87
release: prepare Unplugged 1.1.0 with audio and subtitle fixes
Annotated tag: v1.1.0
```

That commit includes seven files: installer version/registration cleanup,
engine source, renderer header, renderer wrapper/build project, engine DLL, and
the original diagnosis document.

**Still uncommitted at handover:**

```text
.gitignore
distrib\build_unplugged_setup.ps1
docs\ISSUE-mpcaudiorenderer-silence.md
src\unplugged-ui\pyproject.toml
src\unplugged-ui\src\mpvprocessor\__init__.py
src\unplugged-ui\unplugged.spec
docs\HANDOVER-1.1.0-audio-release.md  (this new handover)
```

There are also unrelated/generated tracked modifications and untracked files.
Do not use an indiscriminate `git add .`, reset, clean, or discard operation.

Ignore cleanup added specific verified generated directories: UI build/dist,
root obj/output, and several component bin directories. At that inspection the
untracked count dropped from 2,398 to 239. Existing tracked build artifacts still
appear as modified because ignore rules do not apply to tracked files.

No tracked binaries were removed from the index, and no source/scripts/assets
were broadly hidden. A wider tracked-artifact cleanup requires a separate,
deliberate decision.

## 9. Next actions before publishing

1. Install the final 1.1.0 package and confirm its UI version, PCM playback,
   audible level, subtitle Off default, manual subtitle selection, and basic
   playback/seek behavior.
2. Verify the old private renderer registration is removed only when owned by
   the current install; check upgrade behavior from the affected package.
3. Review and commit the version/packaging corrections, related documentation,
   and desired ignore cleanup with explicit file paths.
4. Resolve release tag policy with the maintainer. The existing `v1.1.0` tag
   predates these corrections. Do not move or force-push it without explicit
   approval. If already published, a new patch release may be preferable.
5. Check live remote branch/tag state, then push the approved commit and tag.
6. Publish the correctly versioned installer with its checksum. Release notes
   should not claim AVR/Atmos passthrough or full regression validation.

Git executable available during this session:

```powershell
$git = 'C:\Users\satee\AppData\Local\GitHubDesktop\app-3.6.7\resources\app\git\cmd\git.exe'
& $git -C 'C:\code\unplugged-mpc-hc' ls-remote origin 'refs/heads/zion-s3-shell' 'refs/tags/v1.1.0' 'refs/tags/v1.1.0^{}'
```

Automated push/login attempts earlier failed because the agent shell could not
prompt and lacked usable credentials. Use an authenticated terminal or GitHub
Desktop; do not paste credentials into chat.

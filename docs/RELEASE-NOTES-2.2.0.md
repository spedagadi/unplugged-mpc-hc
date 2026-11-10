# Unplugged 2.2.0

2.2.0 builds on 2.1.0. A fresh install now keeps Video Processor mode and keeps
the screen awake, the display path gained an explicit transfer function and
DCI-P3 output, and the contributed DBLE compensation is integrated with its
on-screen readout. The grade no longer pumps on bright backgrounds inside a
shot, and capture renegotiation survives episode transitions.

| Download | Size | SHA-256 |
| --- | --- | --- |
| `Unplugged-setup-2.2.0.exe` | 127,094,355 bytes | `F48ED045872DB6E93801F82D9D2BDD1C040351E4BCF0AAF344210EB6BFA53FB3` |
| `UnpluggedRenderer-setup-2.2.0.exe` | 41,737,098 bytes | `30B75D1ECA8D139674FD608C7E713EEA01C8C3D86C71D742188F41591BC9C0E4` |

## First run and display sleep

- **Video Processor survives a fresh install.** When `app_config.json` is
  absent or incomplete, the app seeds a complete default instead of leaving
  the mode unset; the first-run wizard still decides what the user picked.
  A corrupt file is moved aside rather than silently discarded.
- **The screen stays awake for the whole app run.** The app holds Windows'
  display and system awake requests while it is open and releases them on
  shutdown. This fixes the field report where a live capture looked like "no
  signal" after the display had switched off.
- **Ctrl+S frame capture works from an installed app.** The intermediate BMP
  path was being built with the wrong wide-format specifier, which made it a
  relative file; it only worked when the current directory happened to be
  writable. It now uses the real `%TEMP%` path.

## Display target

- **Display transfer** (HDR tab, and Display Target in the app) now selects the
  transfer of the finished SDR picture: **Follow source**, **Gamma 2.2**,
  **Gamma 2.4**, **BT.1886**, **sRGB** or **Gamma 2.0**. Follow source keeps
  the 2.1.0 pass-through; an explicit value converts SDR too. BT.709 video is
  decoded through the BT.1886 reference and re-encoded to the target.
- **DCI-P3 (D65) output gamut**, alongside Follow source, BT.709 and BT.2020.
  The HDR tone map converts 2020→P3; the SDR final pass converts 709/2020→P3.
  The 709 gamut-capacity curve stays a 709-only control.
- A calibration LUT must be authored for the transfer and gamut it will see.

## DBLE compensation

- **The contributed DBLEFix is integrated.** In dark pictures it rolls the top
  of the range down so a projector's dynamic laser dimming (DBLE) does not push
  highlights into clipping. The roll-off runs in the configured target code,
  after the display transfer and before the calibration LUT.
- **The trigger is the measured picture**, in percent of SDR white (0.5–30,
  default 5.0). Full effect below a quarter of the trigger; none above it. It
  is measured from the finished picture, so it is independent of the ML grade
  and works with the grade Off.
- **The contributed OSD is included**: Fix, Strength, Trigger, Highlight start,
  View and Overlay rows; the selected row is marked `>`; the status line shows
  Picture / Fix / White / Scene. `Ctrl+Alt+↑/↓` selects a row,
  `Ctrl+Alt+←/→` changes it, `Ctrl+Alt+0` shows/hides the overlay, and
  `Ctrl+Alt+D` toggles the fix. The overlay is white, locked in place, and
  follows the visible video area out from under the status/settings panels.
- **View** offers Normal, Clipping test (green = fixable, red = already
  clipped, blue = actually lowered) and Split screen (unfixed left, fixed
  right). The test views change the picture; use them to inspect the fix, not
  to judge the final look. They apply only while DBLE is active, so a saved
  test view can never tint the picture with the fix switched off.

## Grade stability

- **The model's output is held while the scene is the same.** A white wall or
  a bright background no longer re-solves the grade on every switch; changes
  land on a scene cut or a genuine light change, not frame to frame.
- **The scene reference no longer jumps from the cluster or drift paths**, and
  the anchor follows the robust (lower-half) scene mean during steady shots,
  so a bright background cannot drag the character's exposure with it.

## Capture renegotiation

- **Prime Video episode transitions no longer reload the graph.** A re-lock at
  the same format is ignored; a real format change still reloads and rebaselines
  the source-format detector, so the double reload is gone.

## Standalone renderer

`UnpluggedRenderer-setup-2.2.0.exe` packages the same renderer build
(0.10.9.2637) for MPC-HC and MPC-BE. Its HDR page now carries Display transfer,
DBLE, View and OSD. See `Readme-UnpluggedRenderer.txt`.

## Upgrade

Install over 2.1.0. The media library, presets and calibration data are
preserved. Existing DBLE values are reinterpreted as Trigger picture %; the
default is 5.0. No other settings migration is required.

## Known limitations

- DBLE compensation is SDR-output only; HDR passthrough is untouched.
- DCI-P3 has no gamut-capacity curve; capacity remains BT.709-only.
- A calibration LUT is coupled to the selected Display transfer and gamut.
- Windows cannot signal an SDR BT.2020/P3 gamut flag; the display must be set
  to match manually.
- The LAV and DeckLinkSource binaries are unchanged from 2.1.0.
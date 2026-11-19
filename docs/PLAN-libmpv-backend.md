# Unplugged libmpv/libplacebo migration plan

Status: Draft v4 - three-phase delivery; detailed Phase A plan in experimental workspace.
Date: 2026-10-20

## Revised delivery order

The agreed delivery structure supersedes the milestone ordering below:

1. **Phase A:** standard mpv/libplacebo file playback in the current UI reused
   inside `unplugged_mpv`; disable Zion, adapt other tabs to functional native
   controls, and populate the live status panel with actual playback telemetry.
2. **Phase B:** add Zion and associated signature picture processing.
3. **Phase C:** add DeckLink capture and resilient live operation.

Phase A does no DeckLink implementation or hardware qualification. Keep only
disabled "Planned for Phase C (Phase 3)" UI placeholders, with no capture
services, discovery/monitoring, SDK or runtime dependency.

Detailed scope, rail behavior, status bindings and acceptance gates are in
`C:\code\unplugged_mpv\unplugged_mpv\PLAN-phase-a.md`.
The older milestones below remain background risk/reference material, not
instructions to bring capture or custom grading into Phase A.

## Execution status - initial isolation setup

- Created separate sparse worktree `C:\code\unplugged_mpv` on
  `experiment/unplugged-mpv`, based on
  `b66b6ece9d9261c18e9abd4e0fead0c8829f2353`.
  Production remains on `zion-s3-shell`; no tag was moved.
- Dedicated project: `C:\code\unplugged_mpv\unplugged_mpv`, with its own
  metadata, Python environment and non-installable `reference` snapshot.
  Phase A source launcher, private native development runtime and reused visual
  components are now implemented there; no frozen EXE/installer is produced.
- Rechecked local installer/application/engine hashes against the recorded
  1.1.0 artifacts. All 57 reference Python files match packaged loose source;
  all 50 embedded application modules also match after excluding code filenames.
- Discovered four untracked production runtime files in `media`/`profiles`.
  They are preserved with provenance in the new snapshot, but the commit alone
  is not yet a complete reproducible production baseline. No production source
  tracking or dependency metadata changes were made.
- Generated initial static inventory: 107 declared settings controls, 28 public
  engine members and five signals. Per-control mapping/semantics remain pending.
- Located native source/build trees in `C:\code\mpv` and
  `C:\code\libplacebo`. Candidate portable runtimes differ in binary hashes;
  exact source-to-binary and FFmpeg provenance still need qualification.
- Seven initial foundation tests passed without Qt/mpv. The private environment
  now has pinned dependencies and 20 tests covering native/GPU file playback,
  controls, live status, rendered LUT effects and lifecycle. The user-supplied
  4K hybrid DV/HDR MKV was also checked with temporary settings. This is not
  picture-parity, a clean production rebuild or release qualification.

## Goal and source of truth

Create a separate **unplugged_mpv application**, reusing a verified snapshot of
the current Unplugged PyQt6 UI, workflows, profile model and production fixes.
Do not integrate mpv into the deployed application's source/build path.

The current MPC-HC/S3 engine and MPCVR implementation are the behavioral and
picture-processing reference. The older `C:\code\mpv-videoprocessor` project is
implementation reference material only. Do not replace current UI files with
older versions or assume matching method names imply matching behavior.

Develop primarily on Windows, using the existing working native mpv stack as
the initial candidate. Qualify representative processing on CM3588/Ubuntu
early. Do not make Yocto adoption a prerequisite for the application port.

## Principles and boundaries

- Protect the deployed 1.1.0 maintenance line. Keeping S3 as the default in a
  mixed development tree is not sufficient isolation.
- Develop libmpv in a separate Git branch and worktree with separate build and
  runtime state. Do not add experimental imports, dependencies, backend
  selection or packaging changes to the production maintenance line.
- Launch the experimental application separately; production does not need a
  backend selector. The new application initially targets libmpv only.
- Avoid silent fallback to another backend: report initialization failures.
- Preserve UI appearance and interaction wherever supported. Clearly disable
  unsupported operations with an explanation instead of silently ignoring them.
- Reuse existing helpers and adapters before introducing new abstractions.
- Keep platform-specific capture and presentation outside picture-processing
  policy and UI code.
- Keep native dependencies isolated so FFmpeg/GPU DLLs from different engines
  cannot accidentally resolve to the wrong build.
- Do not claim rendering parity, hardware decoding, HDR output or passthrough
  solely from successful initialization or an option being accepted.
- Preserve unrelated worktree changes. Commit explicit, reviewed file sets.
- No default-backend change, production installer replacement or tag movement
  is implied by this plan.

## Production maintenance and experimental isolation

Users are already running 1.1.0. A field issue must be reproducible and fixable
without removing, disabling or understanding unfinished libmpv integration.

Before implementation:

1. Identify and preserve the exact shipped installer, application/native
   binaries, source revisions and build inputs. Earlier release work recorded
   version/packaging edits after the existing `v1.1.0` tag; do not assume that
   tag alone reproduces the deployed package. Reconcile this discrepancy
   without silently moving a published tag or discarding pending changes.
2. Establish a reviewed production maintenance baseline from the shipped
   source. Reserve it for field fixes and intentional production releases.
   The current worktree has pending changes; do not switch it, blanket-stage
   files or treat all pending work as release content.
3. Create a separate experimental branch/worktree from that verified baseline.
   Reuse the current application source there; do not fork the old UI back into
   production. Branch/worktree creation follows baseline review and approval.
4. Keep experimental Python environments, native dependencies, build/cache
   directories and package outputs separate. Do not overwrite production
   binaries or shared sibling renderer/filter build outputs.
5. Use a distinct experimental application identity, settings/profile store,
   logs and install directory. Reading production profiles must be an explicit
   copy/import, never a write-back migration. Do not change production file
   associations, shortcuts or system filter registrations.

Maintenance flow:

- Reproduce field reports against the shipped baseline and fix them on the
  production maintenance line without libmpv dependencies.
- Build and qualify production fixes using the existing production pipeline.
- Bring reviewed production fixes forward into the experimental branch as
  needed; do not merge unfinished experimental work back to obtain a hotfix.
- Keep experimental integration out of production until a separate, explicitly
  approved promotion review. Any earlier shared improvement must be extracted
  as an independently justified and tested production patch.

Isolation gate: demonstrate that the maintenance build and application run
without the experimental worktree or its environment, and that experimental
launch, failure and uninstall leave the production installation and settings
unchanged. A separate worktree alone does not isolate settings, DLL lookup or
machine-wide registrations.

### Proposed application layout and reuse model

Proposed sibling checkout/worktree (not created by this plan):

```text
C:\code\unplugged-mpc-hc\       Production maintenance; no new mpv requirements
C:\code\unplugged_mpv\         Experimental application checkout/worktree
    unplugged_mpv\            Self-contained application project
        pyproject.toml        Own dependency manifest and reproducible pins
        src\                  Reused current UI/model code and new mpv adapter
        reference\            Non-installable source snapshot during Milestone 0
        tests\                Adapter, UI and isolation checks
        native\               Pinned libmpv/libplacebo runtime and provenance
        packaging\            Own executable and installer definitions
        .venv\                Own Python environment (not committed)
        build\                Own generated outputs (not committed)
        dist\                 Own packages (not committed)
```

The experimental checkout may retain the original repository tree/history for
comparison, but its build entry point is the dedicated `unplugged_mpv` project.
It must not build, import or load from the production checkout or original
production output directories. Exact folder names can be finalized at
Milestone 0 without weakening these boundaries.

- Reuse source by taking a traceable snapshot from the verified baseline,
  recording its commit and carrying forward reviewed fixes deliberately.
- Place new integration and application-specific edits in the dedicated
  project; leave the production application tree unchanged.
- Do not share editable source through symlinks, editable installs or runtime
  path injection. Do not extract a live shared UI package during this port:
  that would couple production maintenance to experimental changes.
- Some initial source duplication is intentional. Track the upstream baseline
  and imported fixes so reuse remains reviewable rather than an untracked copy.
- Give the new application its own dependency manifest, reproducible dependency
  resolution, native-library search scope, executable, settings namespace and
  installer identity. The internal Python package need not be renamed merely
  for branding if its environment and packaged imports are isolated.
- Production must continue to build without installing new mpv dependencies.
  The new package must also work without an installed production application,
  S3/LAV/MPCVR runtime or production source checkout.

## Existing foundations

| Surface | Current evidence | Planned use |
| --- | --- | --- |
| [main_window.py](../src/unplugged-ui/src/mpvprocessor/ui/main_window.py) | Imports `S3Engine as MpvEngine`; contains platform/window handling | Reuse workflows in the separate application; change wiring there only |
| [s3_engine.py](../src/unplugged-ui/src/mpvprocessor/core/s3_engine.py) | Playback, settings, tracks, audio, LUT, screenshot and capture operations; Qt signals | Source for the adapter contract and regression expectations |
| [mpv_engine.py](../src/unplugged-ui/src/mpvprocessor/core/mpv_engine.py) | Older libmpv integration remains in the current tree | Compare with the older project's working-tree adapter before reuse |
| Older project's `app/src/mpvprocessor/core/mpv_engine.py` | DLL discovery, window embedding, events/properties, DeckLink URL translation and libplacebo options | Selectively reuse after checking threading, failure handling and lifecycle |
| Older project's `dist/VideoForge` | Portable libmpv, libplacebo and FFmpeg libraries exist | Candidate runtime; inventory and test, not proof of exact versions/build flags |
| [unplugged.spec](../src/unplugged-ui/unplugged.spec) | Explicitly excludes mpv; packages the S3 engine | Leave unchanged; use a separate experimental packaging definition |

Libplacebo is normally used through mpv's `gpu-next` renderer. The Python UI
controls libmpv, not a second independent libplacebo renderer.

## Milestone 0 - Freeze references and make the feature inventory

Deliverables:

1. Record current application/native revisions, pending source edits, reference
   binaries and representative settings. The older project has uncommitted
   changes; inspect those, not just its last commit. Reconcile the deployed
   1.1.0 source/package baseline and define the isolated maintenance and
   experimental build locations before making implementation changes.
2. Identify where the working Windows mpv/libplacebo/FFmpeg sources and custom
   patches were built. Record toolchain, configure options, dependency versions,
   hashes and relevant licenses/source-offer obligations.
3. List every engine operation and signal consumed by the current UI, including
   settings/reset/save, tracks, capture, screenshots, LUTs and statistics.
4. Build a parity matrix with one row per current user-facing control:
   current behavior, libmpv implementation, live/restart semantics, Windows
   status, CM3588 status, test and known limitations.
5. Identify the highest-risk custom picture-processing stage and evaluate
   whether libplacebo hooks can express its ordering, resources and temporal
   state. Inspect required shader/model/inference dependencies.

Gate:

- Agree the initial playback scope and parity expectations.
- Approve the production baseline and isolation layout. All subsequent
  implementation milestones apply only to the experimental worktree.
- A working portable binary can support the first prototype, but a reproducible
  native build must be established before modifying native code or distributing
  the new backend.
- Do not estimate the complete port solely from the old UI working.

## Milestone 1 - Experimental backend wiring and file playback

Depends on Milestone 0's interface inventory.

Implementation scope:

- Seed the dedicated application project from the verified current UI/model
  source and wire it to libmpv there. Preserve required engine state types
  locally; do not introduce a production backend factory or plugin framework.
- Adapt the libmpv adapter to the current method/signature/signal contract.
- Marshal callbacks to the Qt thread, preserve callback/object lifetimes and
  make shutdown/reinitialization safe. Audit the old adapter's timer callbacks
  and broad exception handling instead of copying them blindly.
- Isolate native-library loading and log backend/build identities.
- Start with Windows window embedding and file playback; retain current
  fullscreen, sizing, overlays and keyboard behavior.
- Document capabilities for unavailable controls and fail explicitly.
- Keep backend-specific configuration separate without duplicating the full
  profile model. Do not reinterpret stored values silently.

Acceptance:

- Launch the separate libmpv application; missing libmpv produces an actionable
  error and does not damage either application's configuration store.
- Open/close/reopen, play/pause, seek, EOF, stop, fullscreen, resize and exit work.
- Audio volume/mute, track selection, stereo PCM downmix, subtitles Off by
  default and manual subtitle selection match intended current behavior.
- Network/local paths and Unicode paths are exercised.
- Explicitly distinguish decoded PCM from encoded passthrough. AVR validation
  remains a hardware-dependent test, not an assumed result.
- No UI stalls, orphan callbacks, crashes or duplicate event handling during
  repeated open/stop/close cycles.
- Run production S3 separately as the behavioral reference for relevant
  regression scenarios; it is not a dependency of the new package.
- Production still builds/runs independently with no experimental dependencies,
  imports, configuration changes or package output replacement.

## Milestone 2 - Processing parity and comparison harness

Begins after Milestone 0; integrate incrementally with Milestone 1.

Tasks:

- Document the current processing order and input/output colour interpretation.
- Port a representative difficult stage first, then remaining controls by
  processing group, rather than merely forwarding similarly named options.
- Use supported mpv/libplacebo options and shader hooks where sufficient.
- If required resources/stage ordering are unavailable, make a scoped decision
  between a targeted native extension and more direct libplacebo integration.
  Do not silently approximate a signature processing feature.
- Include LUT handling, dynamic/temporal behavior and model inference where
  the reference actually uses them; HLSL is not a drop-in mpv shader.
- Capture reference material at fixed timestamps/settings and, where possible,
  comparable intermediate processing boundaries.

Comparison set:

| Area | Required evidence |
| --- | --- |
| Input | Range, matrix, transfer function, primaries and chroma siting |
| Tone/colour | Highlight/shadow treatment, gamut behavior and processing order |
| Scaling | Luma/chroma reconstruction, sharpening and artifacts |
| Output | SDR/HDR target, luminance, precision, dithering and signalling |
| Temporal | Scene changes, adaptation, flicker and dropped frames |

Gate:

- Agree numerical tolerances and visual acceptance using initial baseline
  measurements. Do not invent thresholds after seeing a favorable result.
- Exact pixel identity is not assumed across GPU backends/dithering.
- Screenshots alone are not proof of HDMI HDR signalling or display accuracy.
- Each supported control has observable verified behavior; exceptions appear
  in the parity matrix and release limitations.

## Milestone 3 - Early CM3588 feasibility spike

Run after basic file playback and one demanding processing stage, **not after
finishing every Windows feature**.

Use the user's previously working Ubuntu HDR10 experience as the functional
reference. Its exact historical revisions are unavailable, so identify a new
reproducible board baseline rather than claiming identical dependencies.

Tasks and gates:

- Run mpv/libplacebo independently, then the current application adapter.
- Establish real HEVC Main10 hardware decode and hardware GPU rendering.
- Test the intended graphics backend and select a Qt embedding strategy.
  Windows HWND embedding does not carry over automatically to Wayland.
- Compare desktop-session output with the eventual appliance presentation path.
- Measure processing/upload/synchronization costs, dropped frames and sustained
  thermal behavior at agreed resolutions and processing quality.
- 4K60 has a nominal 16.67 ms frame interval; agree workload/headroom and
  sustained-run acceptance criteria from measurements.
- Decide early whether individual features need a board-specific quality mode.
  Such modes must be explicit, not silent degradation.

This spike may run alongside the remainder of Milestone 2. Findings can change
shader/resource architecture before the full Windows port is completed.

## Milestone 4 - Live capture

Capture discovery, buffers, timestamps and audio are distinct from file playback.

### Windows / DeckLink

- Reuse proven FFmpeg/DeckLink integration selectively.
- Validate supported input modes, pixel formats, HDR metadata, signal changes,
  reconnects, buffer lifetime/queue depth and stop/restart.
- Reconcile monitoring with capture-device ownership.
- Measure end-to-end latency and synchronization; URL acceptance is not proof
  of a correct low-latency pipeline.

### CM3588 / HDMI RX

- Identify the V4L2 node and configure EDID, timings and formats explicitly.
- Qualify DMA-BUF import, strides/modifiers, fences and buffer ownership.
- Validate metadata propagation into rendering, HDMI audio and clocking.
- If mpv's ordinary capture path cannot preserve required behavior, specify a
  capture bridge/native integration instead of hiding copies or metadata loss.

Gate: measured stable capture, reconnect recovery, A/V sync and agreed latency
for the required 4K60/HDR modes. Define instrumentation and tolerances before
claiming acceptance.

## Milestone 5 - Packaging and release qualification

- Build a distinctly named experimental Windows package; preserve the existing
  production installer and renderer registration behavior. Use distinct package
  identity, install/uninstall scope, settings and output paths; verify
  side-by-side use and uninstall without affecting production.
- Verify DLL resolution on a clean machine, without MSYS2 directories on PATH.
- Include required runtimes, licenses and source offers; pin native revisions.
- Verify UI/executable/installer versions and record artifact hashes.
- On Ubuntu, package runtime dependencies and add an appliance launch mode.
  No desktop shell is needed in production, but a display server/compositor may
  still be selected if the UI/presentation architecture requires it.
- Keep development tools and desktop environment out of production deployment.
- Exercise upgrade/rollback, settings compatibility, long-run playback/capture
  and crash/error recovery on both target platforms.
- Promote any backend integration into production only after explicit approval,
  isolation/regression evidence and parity sign-off. Changing the default is a
  separate release decision, not an automatic consequence of integration.

## Validation strategy

- Adapter tests for state/property/track translation, errors and lifecycle using
  a fake libmpv boundary where useful.
- Small integration checks against actual native libraries for behavior mocks
  cannot prove.
- Manual GUI/display/audio/capture acceptance with explicit recorded results.
- Fixed image/video fixtures for processing comparisons, not arbitrary viewing.
- Separate functional, picture-quality, latency and performance results.
- Test the existing backend whenever shared UI/profile code changes.
- Do not mark hardware-specific tests passed based on Windows-only evidence.

## Decisions to resolve during iteration

1. Finalize the `unplugged_mpv` application/directory/package identity and
   baseline import procedure. Separate application launch replaces the earlier
   proposal for a backend selector in the existing application.
2. Initial Windows libplacebo backend: D3D11 or Vulkan? Inventory the working
   runtime first; compare portability and required capabilities before choosing.
3. Which current processing feature is the first hard parity gate?
4. Is ML/inference parity required for the first public experimental release?
5. Required initial file/audio/subtitle/capture format matrix.
6. Numerical/visual parity, latency and sustained performance thresholds.
7. Ubuntu Qt presentation strategy and whether production requires visible
   local controls or remote-only control.

## Immediate next iteration

Continue **Milestone 0** from the isolated foundation: review the missing-source
production-baseline gap as a separate maintenance task, resolve native runtime
provenance, map current controls/engine coupling and scope the hardest processing
parity stage. Then bound the first executable UI/adapter port in the dedicated
application. No production runtime code or packaging has been changed by setup.

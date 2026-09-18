# DFSorter v1 delivery checklist

Completion requires implementation plus verification. `specs/dfsorter-specs-clean.md` is authoritative.

## Stage 1 — Catalogue and deterministic metadata

- [x] Application-local SQLite, stable normalized source identities, live metadata, persistent projects and one ordered session.
- [x] YAML schemas, canonical aliases, dynamic field retention, and clear validation errors.
- [x] Atomic metadata parsing, reserved tokens, list replacement, free-form prefixes and preserved human text.
- [x] Structured/plain queries, triage/game/project filters, sorting, and rating-query rejection.
- [x] Undo/redo, explicit game-change clearing, independent triage/rating, and active-project Keep transitions.

## Stage 2 — Import and review

- [x] Recursive MP4 discovery, forced/nearest-ancestor game assignment, preview, rescan, and folder summaries.
- [x] Missing-file retention, transactional migration, separate confirmed removal/purge.
- [x] Six panels, dark theme, prescribed pane visibility, adjustable nonpersisted widths, and window reset.
- [x] Fixed session queues, saved position, triage counts, command history, and keyboard-led review.
- [x] H.264/AV1 playback, paused frame presentation, seek/audio controls, temporary 3× playback, and valid stored ranges.
- [x] Editing and Export open paused at the saved In point when the complete range fits the video; absent, incomplete, reversed and out-of-duration ranges start at zero. Verified with H.264/AV1 playback in both players; 19 UI tests passed.

## Stage 3 — Share and export

- [x] Whole/range H.264 MP4 Share with custom/generated names, selected fields, default destination, and collision suffixes.
- [x] Full-project validation including unknown game, undefined triage, missing fields, and unavailable kept sources.
- [x] Export preview grows with window height, including maximized/fullscreen; compact filename-option rows reserve more space for video.
- [x] Per-game filename selection, flat/rating directories, and stateless video-only output copies.
- [x] Background operations, cancellation, incomplete-copy cleanup, completed-output reporting, and source preservation.
- [x] Immediate modal progress before background work and export preparation; duplicate actions blocked, cancellation remains modal until work finishes.

## Stage 4 — First graphical touchup

- [x] Review/input separation, Space tap/hold, seek/rating shortcuts, per-run drafts, and shortcut help.
- [x] Restrained navigation, elided clip rows, compact Lucide controls, star rating, title emphasis, and conditional technical notes.
- [x] Collapsible Projects with normal/maximized defaults and per-run overrides; compact project and session actions.
- [x] Native Qt video presentation, 20 Hz coalesced scrubbing, release seek, and colored range timeline.
- [x] D3D11 hardware decoder selection verified for H.264 and AV1 on this machine; software fallback allowed.
- [x] Real whole/range sharing, mixed stereo AAC, silent sources, NVIDIA encoding and x264 fallback, cancellation cleanup, source preservation, and collision handling.
- [ ] Subjective native-video presentation, responsiveness, and mixed-audio balance acceptance with the user's capture library.

## Stage 5 — Coherent desktop design system

- [x] Authoritative color, typography, spacing and component specification; shared Qt palette/QSS and painter tokens.
- [x] Segoe UI hierarchy, compact controls, semantic verdict/error states, focused command bar and restrained application-wide styling.
- [x] Compact bordered two-line clip cards, explicit presentation roles, status dots, unavailable warnings, elision and full-text tooltips.
- [x] State-aware high-DPI Lucide icons, compact gold rating stars, cyan project indicator and 7 px cyan range timeline.
- [x] Isolated visual review across six pages, narrow/normal/maximized layouts and dialogs at 100%, 125% and 150% scaling.
- [ ] User acceptance of density, readability and clip-card grouping with the capture library.

Design verification: `uv run --no-sync pytest -q` passed 39 tests; Ruff lint/format and `git diff --check` passed. Native Windows Qt fixture startup emitted a `0x8001010d` diagnostic, but the suite completed with exit code 0. Visual fixtures can be regenerated with `uv run --no-sync python tests/visual_design.py` and `QT_SCALE_FACTOR=1`, `1.25`, or `1.5`; outputs are in `cache/verification/design`. These fixtures deliberately include invalid/missing media to exercise unavailable states; the regression suite separately tests real H.264/AV1 playback.

## Verification and deliberate limits

- [x] Rejected-original permanent deletion: grouped preview, red delete-button confirmation, file-handle identity checks, cancellation and per-file outcomes; retains catalogue references.
- [x] Unified top-right Lucide Settings with capture-folder management, project management and General placeholder.
- [ ] User acceptance of deletion review and Settings with the real capture library. Implementation verified using disposable files and isolated Qt fixtures; representative dialogs visually inspected at 100% scale.

- [x] Focused catalogue/parser/output regression suite and real Qt interaction/playback tests.
- [x] Normal/maximized window visual review with generated media.
- [ ] Manual acceptance with the user's own capture library and audio devices.
- XMP support is deferred; no sidecars are generated. Existing sidecars remain untouched.

Enabled capture folders rescan automatically on startup; manual rescan remains available and periodic polling is not included. Playback tests verify an audio stream and output controls, not subjective audio quality. No standalone installer is provided; launch through uv or `launch.bat`.

## Stage 6 — Review advancement and startup discovery

- [x] Enter focuses the command bar in review mode and submits in command-input mode; review-mode Shift+Enter separately applies a legal verdict and advances, preserving explicit Discard.
- [x] Pending commands block advancement; Keep requires a configured game and its required fields; the final clip reports Session complete.
- [x] Startup background rescan of enabled capture folders preserves existing metadata, missing-source entries and frozen Session membership.

## Stage 7 — Incremental rescanning

- [x] Transactional schema-v2 media cache; duration and capture dates restored before initial library refresh.
- [x] Unchanged rescans and reopened catalogues launch zero probes; changed/added videos launch one each. File failures expire after 24 hours; missing tools do not create reusable file failures.
- [x] Deterministic discovery and at most two concurrent probes, cancellable polling, timeout cleanup, unstable-file rejection and per-folder transaction rollback.
- [x] Background ingestion, preserved preview confirmation, immediate modal progress and Reinspect all media… in Import and Settings.
- [x] Migration/purge invalidation and preservation of metadata, project memberships, missing entries and Session ordering.
- [x] Isolated comparison on 319 real captures, without changing sources or the working catalogue.
- [ ] User acceptance of scanning responsiveness with the capture library.

2026-09-17 benchmark, seconds (one sequential run per mode):

| Mode | Traversal | Inspection/cache lookup | Database | Probes | Hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous sequential implementation | 0.067 | 20.538 | 0.127 | 319 | 0 |
| First scan | 0.119 | 9.328 | 0.159 | 319 | 0 |
| Unchanged | 0.201 | 0.074 | 0.142 | 0 | 319 |
| Reopened catalogue | 0.149 | 0.042 | 0.132 | 0 | 319 |

UI refresh measured separately: 0.083 s. Inspection timing includes scheduling,
attribute checks and cache lookup; database timing includes cache writes and ingestion.
Warm filesystem caches and machine load affect timings. Benchmark helper:
`tests/benchmark_scanning.py`, with a disposable project-local database and read-only
access to capture media. Automated coverage includes immediate modal startup/manual
progress, restart metadata, failure expiry, forced inspection, cancellation rollback,
process cleanup and the existing regression suite.

## Clip navigation and viewport stability

- [x] Editing clicks and previous/next navigation update cards and session status without rebuilding the library or reference controls. Necessary list rebuilds preserve the viewport anchor.
- [x] Editing and Export clip transitions cover only details/player controls, keeping the list and navigation usable; new details and video reveal together. Page changes retain full-page transitions.
- [x] Long-list mouse navigation, repeated selections during loading, current-clip clicks, keyboard navigation, viewport restoration, and stale reveal generations have automated regression coverage.
- [x] Generated H.264 media verifies clip switching and first-frame availability in Editing and Export. Loading/ready screenshots in `cache/verification/clip-navigation` verify cover placement; native video rendering is checked through the video sink rather than widget screenshots.
- [ ] User acceptance of scrolling and transition smoothness on the capture library.

## Editing session counters and spacing

- [x] Editing list footer shows live Kept, Rejected, Undefined and Total counts for the frozen Session, excluding clips outside it.
- [x] Empty list errors collapse; reduced list margins and a center-column command area allow the left pane to use the full height.
- [ ] User acceptance of the revised Editing layout.

## Configurable playback start

- [x] Settings → General enables a start offset before the end for clips without a valid I/O range, defaulting to 40 seconds. Both players share the persisted preference; saved In points take priority and short clips start at zero.
- [x] All 28 UI tests pass, including generated H.264/AV1 playback in both players, configurable offset, disabling, short clips, valid/invalid ranges and settings persistence. Ruff checks pass. Windows emitted a COM diagnostic during window setup; the test run completed successfully.
- [ ] User acceptance of the playback preference and starting position.

## Project selection during review

- [x] Editing player includes a bottom-right Add to project + Next button, enabled only with an active project. Ctrl+Enter invokes it in review mode; both preserve triage and drafts, advance sequentially, and stop at the end of the session.
- [x] Renamed Add selected clips to Add to project; updated shortcut hint, help and specification.
- [x] All 29 UI tests and Ruff checks pass, including active-project gating, input-mode isolation, existing Keep/Discard clips, duplicate membership, final-clip behavior and draft preservation. Windows emitted the previously observed COM diagnostic during setup; the suite completed successfully.
- [ ] User acceptance of the player button layout.

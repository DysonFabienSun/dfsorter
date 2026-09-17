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

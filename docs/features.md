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

- [x] Whole-file Share with custom/generated names, selected fields, default destination, and collision suffixes.
- [x] Full-project validation including unknown game, undefined triage, missing fields, and unavailable kept sources.
- [x] Per-game filename selection, flat/rating directories, adjacent XMP, and stateless output copies.
- [x] Background operations, cancellation, incomplete-copy cleanup, completed-output reporting, and source preservation.

## Verification and deliberate limits

- [x] Focused catalogue/parser/output regression suite and real Qt interaction/playback tests.
- [x] Normal/maximized window visual review with generated media.
- [ ] Manual acceptance with the user's own capture library and audio devices.
- [ ] Premiere-specific XMP interpretation (separate from required v1 range preservation).

Manual rescan is the implemented ingest trigger; optional polling is not included. Playback tests verify an audio stream and output controls, not subjective audio quality. No standalone installer is provided; launch through uv or `launch.bat`.

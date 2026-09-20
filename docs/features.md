# DFSorter v1 delivery checklist

## Working-title and generated-filename casing

- [x] Default lowercase generated title/filename bodies with uppercase game codes; canonical catalogue values, custom filenames, original-name fallbacks, source extensions and UI tags retain casing. Settings → General can restore stored capitalization; preference persists and refreshes visible titles without reloading playback.
- [x] Shared inline hierarchy: muted game codes, smaller regular metadata, subtle separator and bold mainline. Shared clip-card triage dots align against visible text metrics.
- [x] Seven targeted tests passed covering both output casing modes, actual copied filenames/bytes, Share encoder stems, custom names, fallback names, metadata preservation, settings persistence, immediate UI refresh and existing title/navigation behavior. Changed-file Ruff check passed. Qt emitted Windows diagnostic `0x8001010d` during test setup; tests still completed successfully.
- [x] Inspected populated, metadata-only, mainline-only, fallback and long mixed Chinese/English cards with all triage states at 100%, 125% and 150% scaling. Screenshots: `cache/verification/title-casing/scale-*.png`; isolated invalid-media fixtures exercised error-state layout without encoding video.
- [ ] User acceptance of title hierarchy and dot alignment.

## Live command field indicators and validation colors

- [x] Field indicators preview commands as typed, merging with saved fields without writing metadata. Incomplete/invalid drafts retain the longest parseable prefix; clearing restores saved indicators. Tooltips distinguish partial previews. Enter still saves.
- [x] Validation colors replace mode colors: neutral empty/unfinished tokens, blue valid drafts, amber incomplete syntax, red invalid commands, and a 1.2-second green save underline. Cyan focus remains visible. Inline hints explain validation and “Saved · Space to resume”; keyboard modes remain intact.
- [x] Five focused UI checks passed. Full regression run: 99 passed, one AV1 hold-Space timing assertion failed; both codec playback checks passed on targeted rerun together with command preview/UI tests (14 passed). Ruff passes. Inspected valid/incomplete command screenshots in `cache/verification/command-validation`.
- [ ] User acceptance of the updated colors and live indicators; exhaustive display-scale verification remains pending.

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

- [x] Review/input separation, Space tap/hold, seek shortcuts, per-run drafts, and shortcut help.
- [x] Restrained navigation, elided clip rows, compact Lucide controls, star rating, title emphasis, and conditional tags.
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

## Next undefined navigation

- [x] Editing-only Next undefined clip button above the left clip list uses the Lucide arrow-down-to-dot icon copied from the local source library. Navigation preserves verdicts and drafts, skips decided clips and never wraps.
- [x] Focused navigation and verdict-advance regressions pass (2 tests), as do Ruff checks. The previously observed Windows COM setup diagnostic did not prevent completion.
- [ ] User acceptance of button placement and appearance.

## Compact Editing controls

- [x] Session clips header balances its left label with a compact next-undefined icon on the right, shown only in Editing.
- [x] Add to project + Next uses a folder-plus icon and descriptive Ctrl+Enter tooltip, separated from range/share actions by a vertical rule. Removed the separate range text; the timeline retains saved and pending markers.
- [x] All 30 UI tests passed for the player changes; all 3 affected UI regressions passed again after the header change. Ruff checks pass.
- [ ] User acceptance of the revised header and player controls.

## Connected workspace navigation

- [x] Continuous dark navigation strip with 14 px labels, rectangular tabs and a cyan top edge on the selected tab; workspace-colored fill and bottom edge connect the active tab to the content. Projects and Settings remain right-aligned utilities.
- [x] Session clips uses 14 px semibold primary text, a transparent header and an inset matching clip-title text; the action aligns to the card's right edge.
- [x] All 30 UI regressions and Ruff checks pass. Inspected the updated Editing screenshot in cache/verification/session-counts/editing.png for alignment and tab rendering.
- [ ] User acceptance and full multi-DPI visual review of the new navigation.

## Navigation spacing correction

- [x] Removed the inherited 12 px gap above the navigation. The strip now spans the window directly beneath the menu bar; the workspace has a separate 12 px inset below it.
- [x] Inspected the regenerated Editing screenshot for the menu/strip connection and workspace spacing. Ruff checks pass.
- [ ] User acceptance of the adjusted spacing.

## Menu removal and navigation utilities

- [x] Removed the menu bar. The cog opens Settings and the remaining menu-only clip, deletion, layout and exit actions; existing page controls retain other operations.
- [x] Undo/Redo use local Lucide undo-2/redo-2 icons left of Projects, with a 16 px group gap. Ctrl+Z and Ctrl+Shift+Z operate catalogue undo/redo in review; command input retains text undo/redo. Ctrl+Q remains available.
- [x] Projects and the cog share a centered 28 px height. Inspected the regenerated Editing screenshot.
- [x] Focused checks pass for menu removal, retained actions, keyboard/button undo/redo and utility alignment. Final full UI run: 30 passed, one playback text-focus assertion failed; both playback tests passed on isolated rerun. Earlier runs also showed intermittent startup/focus failures. Ruff and diff checks pass.
- [ ] User acceptance of the simplified navigation and cog menu.

## Tags and paused command workflow

- [x] Bold bright-yellow bracketed tag prefixes appear in clip cards and Editing titles, including filename fallbacks. Metadata edits update the current card without rebuilding the list. Removed the tag textbox; retained the cog editor.
- [x] Global `tag:` commands accept one token or a quoted value, with `tag:""` clearing; search accepts the same prefix. Added `brim` as an input alias for canonical Brimstone. Share/Export filename generation remains unchanged.
- [x] Unset ratings show red empty star outlines with no background highlight; existing gold hover previews, selection and clearing remain available.
- [x] Up/Down navigates all frozen-session clips in Editing review mode, including kept/rejected clips, preserving drafts and stopping at the ends.
- [x] Paused ordinary typing enters blue command input; dull yellow indicates availability. The default-on General setting persists immediately. Successful submissions retain input focus; dull violet indicates the one-shot Space-to-resume action. Existing review shortcuts take priority, and input/focus/playback cancellation is covered.
- [x] End-of-media backward seeking resumes playback in both players; dragging previews while held and resumes on release. Real H.264/AV1 fixtures exercise completion and recovery. Ordinary paused seeking stays paused.
- [x] Full regression run: 81 passed (`uv run pytest -v -p no:faulthandler`); Ruff checks pass. An earlier native playback run stalled and was interrupted; the final complete run passed. Inspected yellow/blue/violet command-state screenshots, unrated stars and tags under `cache/verification/command-states`. Stabilized checklist height to preserve command-bar position.
- [ ] User acceptance of colors/workflow with the capture library and full multi-DPI visual review.

## General-purpose tag naming

- [x] Renamed the field, settings action, command/search prefix, checklist, helpers and documentation to `tag`. Use `tag:FAVORITE`, `tag:"needs review"`, or `tag:""` to clear. Display and all other behavior stay identical.
- [x] Schema version 4 renames the existing column on startup without changing saved values, clip IDs, other metadata, project memberships or sessions. Migration coverage includes versions 1–3, reopening, tag edits, clearing and undo/redo.
- [x] Full regression run: 84 passed; Ruff and diff checks pass.

## Capture-folder management on Home

- [x] Home owns capture folders with Add folder, Rescan and More controls. The cog retains its menu: Capture folders opens Home; Settings retains General and Projects, opening on General. Redundant Import navigation and shortcut page removed; Home remains the capture-folder entry point. Home no longer shows an inactive command bar.
- [x] More contains Pause/Resume scanning, Relink folder, Remove folder and advanced Rebuild media information. Rescan reuses valid cached inspections; rebuilding forces inspection for all enabled folders. Folder descriptions and tooltips explain scope and session behavior.
- [x] Relink validates destination/collisions and previews found/unavailable file counts. Remove uses one confirmation, backs up SQLite first, and deletes only catalogue data and references. Legacy unlinked entries remain discoverable for reviewed cleanup. Session cleanup is transactional and preserves a surviving current clip.
- [x] Nine focused checks passed in 2.69 seconds, covering Home/settings navigation, removal/cancellation/backup, retained source files, session position, disabled folders, migration collisions and scan caching. Ruff passes. Inspected the Home screenshot; no full-suite or codec playback reruns.
- [x] With DFSorter closed, backed up the live catalogue as `data/backups/catalogue-20260918-195153-534975.db` and removed exactly the eight approved SORTER-TEST entries. Catalogue: 327 → 319; session: 50 → 43; no unlinked entries remain. Verified retained clip data, registered folders and project memberships unchanged, foreign keys valid, and seven existing source files unchanged (one source was already missing). A matching `.cleanup.json` records the operation.
- [ ] User acceptance of the simplified Home layout.

## Empty-input verdict shortcut

- [x] Shift+Enter also applies the existing verdict-and-advance action from command input when the bar is completely empty. Text, including whitespace, blocks advancement; required-field validation, explicit Discard, review-mode behavior and auto-repeat protection remain intact. Successful actions enter review mode.
- [x] Two focused keyboard/session checks passed in 1.66 seconds; Ruff passes. Updated shortcut help, README and specification.

## Hold-Space feedback

- [x] Both players show a centered `>>>` on the existing transport/volume/range-controls row during hold-Space fast-forward, with a left-to-right accent highlight every 120 ms. Only the indicator’s horizontal space is retained while hidden; no extra row is added; release and existing hold cancellation stop/reset the animation.
- [x] Lightweight widget checks verified animation, centering, stable layout and stopping on release. Ruff passes; no playback-suite rerun.

## Either-order range markers and faster tooltips

- [x] In/Out can be set in either order; a valid adjustment reuses the other saved endpoint. Pending I and O display separately; incomplete/reversed/equal ranges preserve the previous saved pair.
- [x] Pending ranges block clip, panel and session changes and verdict/project advancement before metadata changes. A rejected list selection returns to the current clip. Completing the pair, Clear range or explicit metadata reset releases the block.
- [x] App-wide tooltip hover delay is 200 ms through the existing Fusion style.
- [x] Four focused checks passed in 2.41 seconds, covering both marker orders, saved-partner edits, invalid ranges, navigation guards, clearing and tooltip delay. Ruff passes; no full-suite or codec rerun.

## Command-only keyboard ratings

- [x] Removed legacy review-mode R then 1–5 rating shortcut and timer. Paused typing accepts `r4`; Enter saves. Command ratings and clickable stars remain available.
- [x] Core/UI regression suite: 79 passed. Ruff and `git diff --check` passed.

## Browse viewer and mixed-track playback

- [x] Browse tab after Home: session-free library, all triage states, independent search/game filter, newest-first default and newest/oldest header toggle.
- [x] Read-only catalogue behavior, hidden editing/project controls, guarded mutation handlers and catalogue undo/redo. Temporary I/O and custom title reset freely on clip/page exit.
- [x] Inline Share with required custom title, folder picker, whole/temporary-range choice and existing background encoding/cancellation. Saved markers and session position remain unchanged.
- [x] Application-local pinned libmpv runtime and Python binding. All players mix audio tracks live while preserving stereo channels and timing. Runtime lifecycle uses a dedicated thread to isolate Windows initialization/cleanup from Qt.
- [x] Focused Browse, keyboard, marker, clip-navigation and H.264/AV1 playback checks passed. Generated-audio checks verify mono mic mixing, stereo separation and delayed tracks; Share checks passed and Project Export retains original bytes.
- [x] Normal/maximized Browse captures inspected under simulated 100%, 125% and 150% display scaling; artifacts in `cache/verification/browse`. Display scaling changes font/control sizes independently from maximization.
- [ ] Real capture-library audio balance and performance acceptance. User indicated displayed layout looks fine; no further GUI testing requested.

Setup: `pwsh -File .\setup-playback.ps1` installs checksum-verified Windows x64 libmpv and licenses into `runtime/mpv/`. Runtime is installed on this machine; fresh checkouts require setup. No database migration or playback preview files.

Browse follow-up: each page entry selects newest matching clip and resets newest-first sorting. Delete source… confirms permanent deletion of the selected source, retaining catalogue references as unavailable. Targeted checks cover reset, cancellation, selected-source deletion, and changed-file protection.

Browse layout: enlarged working title with square red delete icon alongside; fixed-width title/folder inputs; output folder and Share mode share one row.

Browse spacing: matching 10 px gaps around the Share form; 480 px output path input and custom title spanning the folder/Share row to align right edges.

Browse consistency fix: shared Editing title typography, divider above Share form, and grid-based textbox alignment verified at two window widths.

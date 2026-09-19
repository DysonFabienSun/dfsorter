# DFSorter Specification

## 1. Introduction

DFSorter is a Python + Qt desktop application for reviewing, triaging, cataloguing, and exporting gameplay montage clips from games such as VALORANT, Escape from Tarkov, and Battlefield 6.

The application should remain minimalistic and should not behave like a video editor. Source clips are treated as immutable media units. DFSorter stores metadata about those clips in a local SQLite database and refers to the original files by path. Source clips are never renamed, moved, trimmed, transcoded, or rewritten by normal catalogue operations.

The two operations that may create video files are:

- **Share**, which creates a whole-clip or selected-range H.264 MP4 with mixed stereo AAC audio in a user-selected sharing folder.
- **Project Export**, which copies the exportable clips referenced by one project into an output directory.

Copied files are no longer managed by DFSorter after the copy completes.

The primary review workflow is keyboard-led. In the Editing panel, structured metadata is entered through a deterministic command-line-style text box, while the application still provides a conventional video player and visible representations of the metadata currently stored for the selected clip.

A **Project** is a persistent collection of references to clips in the library. It never owns or duplicates the original media.

A **Session** is a temporary-but-persisted, fixed review queue. It freezes the membership and order of clips selected for one review run while leaving the clips' metadata live and editable.

---

## 2. Naming and Normalization Conventions

- Canonical video-game references stored by DFSorter use their official names and capitalization where practical. UI casing is contextual: command hints and field indicators retain their existing presentation; working titles follow the generated-name preference. Examples include `VALORANT`, `Battlefield 6`, `Escape from Tarkov`, `Jett`, `Headhunter`, `Tour de Force`, and `Bladestorm`.
- Matching, parsing, aliases, filtering, and text sorting are case-insensitive.
- Case-insensitive matching must not destroy the canonical capitalization of stored structured metadata.
- Parsed field values have leading and trailing whitespace removed. Free-form human text such as `mainline` and `description` preserves the user's original capitalization, punctuation, and internal spacing.
- Game-specific YAML files define the canonical game name and a three-letter uppercase display code such as `VAL`, `BF6`, or `EFT`.

---

Working titles and generated Share/Project Export filename bodies default to lowercase, including structured fields and mainline. Game codes remain uppercase. Settings → General → “Lowercase working titles and generated filenames” is enabled by default; disabling it restores stored capitalization. Changes refresh visible titles immediately and apply to subsequent output operations. Stored metadata and free-form text remain unchanged. Explicit custom filenames, original-filename fallbacks, source extensions, and UI tag prefixes retain casing. Filename selection/order, sanitization and collision suffixes remain unchanged; UI ` | ` separators remain spaces in generated filenames.

## 3. Storage Conventions

All application-managed files and persistent state stay inside the DFSorter project/application directory. Do not use AppData or another per-user system directory.

A recommended layout is:

```text
dfsorter/
    app/
    configs/
        games/
    data/
        dfsorter.db
        settings.yaml
    cache/
```

Capture folders containing the actual source videos are external to this directory and are not portable with DFSorter. Their paths are stored in application state.

Game-specific names, aliases, fields, and formatting rules should be defined in YAML wherever practical rather than duplicated as hard-coded game data in Python.

Reserved engine behavior such as kill parsing, clutch parsing, ratings, sessions, source identity, and triage remains application logic rather than game YAML data.

---

## 4. SQLite Backend and Clip Identity

DFSorter uses one SQLite database file as the persistent catalogue.

Each clip has a stable internal ID used by projects, sessions, and other relationships.

The full normalized source path is the determinant of source identity. Stored paths preserve capitalization; normalization resolves an absolute path without lowercasing. Windows identity comparisons remain case-insensitive. Existing stored paths recover filesystem capitalization on upgrade where available; missing components retain their stored spelling. DFSorter does not need content hashes or lightweight file signatures. If a different video later replaces a file at exactly the same path, DFSorter treats it as the same source identity.

Path migration tools may update a clip's stored source path while preserving its stable internal ID and all metadata, project memberships, and session references.

A missing source file does **not** cause its database entry to be deleted. It remains in the catalogue in an unavailable state until the source returns, is migrated, or the user explicitly purges the catalogue entry.

Removing a capture folder requires explicit confirmation and removes its catalogue entries, cached media information, and project/session references. Save a database backup first. Original source files are never deleted. Pause scanning is the reversible alternative that retains the folder and its clips.

---

## 5. Core Clip Data

A newly ingested clip is valid even when almost all descriptive fields are unset.

Only the stable internal clip ID and source path are inherently required by the catalogue. Game assignment and user-entered metadata may initially be absent.

Core clip data includes:

- `clip_id`: stable internal identifier.
- `source_path`: current full path of the original source video.
- `game` (optional): canonical game name.
- `triage` (optional): `keep`, `discard`, or unset.
- `rating` (optional integer): 1 through 5.
- `tag` (optional string): a short free-form label for any purpose, such as `FAVORITE` or `LOW_FPS`.
- `mainline` (optional string): the primary free-form human note used in the working title, such as `clutch of the century`.
- `description` (optional string): secondary triage/editorial notes. Description is not part of the working title.
- `catalogue_modified_at`: timestamp of the most recent catalogue metadata modification.
- one optional persisted **In/Out range** for the clip.
- game-specific metadata defined by the active game configuration.

Existing catalogues automatically migrate their saved tag values to the `tag` column (schema version 4), preserving clip IDs, other metadata, sessions and project memberships.

The source video's creation/capture time should be read from the source/media metadata when needed rather than duplicated as a user-editable catalogue field.

`triage`, `rating`, and game-specific metadata are independent. Rating does not imply Keep or Discard.

Discarded clips are hidden from ordinary library/source views by default, but may be shown explicitly when the user requests them.

---

## 6. Game-Specific Metadata

### VALORANT

Typical fields include:

- `agent`: canonical agent name, for example `Killjoy` or `Jett`.
- `weapon`: one or more weapon or weapon-like equipment names, for example `Vandal`, `Phantom`, `Classic`, `Tour de Force`, `Headhunter`, `Bladestorm`, or `Showstopper`.
- `kill`: integer kill count, displayed as `3K`, `4K`, etc.
- `clutch`: integer opponent count for a 1vX situation, displayed as `1v3`, `1v4`, etc.
- `map`: canonical map name such as `Haven` or `Icebox`.

### Battlefield 6

Typical fields include:

- `kill`
- `weapon`, normally configured as a multi-value free-form field because of the larger vocabulary.

### Escape from Tarkov

Typical fields include:

- `kill`
- `weapon`, normally configured as a multi-value free-form field.
- `map`

These examples are defaults rather than a hard-coded universal schema. Game-specific fields are driven by YAML configuration.

---

## 7. Game-Specific YAML Configurations

One YAML file is stored per supported game under `configs/games/`.

Each config should define at least:

- canonical game name;
- three-letter uppercase display code;
- accepted aliases for identifying the game;
- game-specific field definitions;
- aliases/shorthand for structured field values;
- optional aliases for field prefixes;
- `display_order`;
- `required_for_export`.

An optional `command_example` string supplies the command bar's muted placeholder for that game when the input is empty. Update it when switching clips, reassigning games or reloading configurations; never insert it as command text. Unknown games or configurations without an example use a generic metadata hint.

The canonical game name is the authoritative identity. The filename should normally match it for readability but is not the sole source of truth.

### 7.1 Field Types

Game-defined fields use a deliberately small field model.

Supported ordinary field types are:

- `enum`: value must resolve to one of the configured canonical values or aliases.
- `freeform`: value is user-supplied text and does not need to exist in a predefined vocabulary.

Any ordinary field may additionally specify:

- `multiple: false` for a scalar value;
- `multiple: true` for an ordered list of values.

This is sufficient for the intended initial game schemas. Do not build a general-purpose schema language without a concrete need.

### 7.2 Reserved Engine Fields

The following concepts have application-level parsing logic:

- `kill`: written as `XK`/`Xk`, such as `4K`.
- `clutch`: written as `1vX`, such as `1v4`, when the current game declares a clutch field.
- `rating`: written as `R1` through `R5`, case-insensitive, and available for every game.

`kill` and `clutch` are reserved metadata field names. `rating` is a global clip field rather than a game-specific field.

A newly created game config should include `kill` by default in addition to the required game identity metadata.

### 7.3 Aliases and Normalization

Game and structured metadata matching are case-insensitive.

Examples:

```text
val, Val, valorant  -> VALORANT
kj                  -> Killjoy
hh                  -> Headhunter
op                  -> Operator
```

Alias keys within a game configuration must not ambiguously map to different fields or canonical values.

Canonical structured values are stored using their configured reference spelling/capitalization.

Free-form values preserve the text supplied by the user except where filesystem-safe export naming requires sanitization.

### 7.4 Free-Form Fields and Prefixes

Free-form fields are entered through an explicit field prefix.

Example:

```text
wpn:M4A1
```

Quoted values are supported:

```text
wpn:"M4A1 SOPMOD"
```

A prefixed free-form assignment consumes its value until another recognized field assignment, reserved structured token, or `--` separator begins. Repeating the same prefix may provide multiple values when the field is configured with `multiple: true`.

Field-prefix aliases may be configured for free-form fields.

### 7.5 Display Order

Each game config includes a `display_order` specifying how structured metadata is rendered in the working title.

Example:

```yaml
display_order:
  - clutch
  - kill
  - agent
  - map
  - weapon
  - mainline
```

Only present values are rendered.

The game's three-letter code is displayed as a prefix where the UI calls for it, for example:

```text
VAL_1v4 3K Killjoy Ascent Vandal clutch of the century
```

`mainline` is visually emphasized in the Editing UI. It remains ordinary text in filenames.

### 7.6 Export Requirements

Each game config may declare structured fields that must be present before a kept clip may be included in a Project Export.

Example:

```yaml
required_for_export:
  - agent
  - weapon
```

A field being optional in the catalogue does not prevent it from being required for a particular export workflow.

### 7.7 Configuration Changes and Existing Data

Removing a field from a YAML config stops that field from being shown or accepted for new input, but must not destroy values already stored for existing clips.

Re-adding a field using the same stable field key restores access to the stored values.

The exact SQLite representation of dynamic game fields is an implementation detail. The storage design must support YAML field changes without destructive schema behavior.

---

## 8. Media Playback and In/Out Markers

Initial required playback support includes MP4 clips containing H.264 or AV1 video. AV1-in-MP4 must work without requiring the user to install an unrelated codec pack manually.

The Editing player includes:

- embedded video playback;
- progress/seek bar;
- play/pause controls;
- volume slider;
- mute button;
- temporary 3x fast-forward while holding Space when a text-editing control is not consuming the key;
- visible first frame when a clip is loaded rather than an unnecessary black player surface.

Each clip may store one optional non-destructive In/Out range.

- `I` sets the In point when text input does not own the key.
- `O` sets the Out point when text input does not own the key. Set either endpoint first. For an existing saved pair, changing one endpoint reuses its saved partner when the resulting range is valid.
- The range is stored as source-relative time and shown on the player's progress display.
- Opening a clip in any panel places the paused playhead at its saved In point when `0 <= In < Out <= duration`; otherwise it starts 40 seconds before the end by default, clamped to zero for shorter clips. Settings → General allows disabling this behavior (start at zero) and configuring the offset from 1 to 86400 seconds. Preferences persist across restarts and apply on the next clip load. Apply the position as soon as media loading permits seeking.
- Pending In and Out points are shown distinctly on the timeline. Commit a pair only when both endpoints are present and In precedes Out; otherwise preserve the last valid stored range. Repeatedly setting either endpoint updates that pending point.
- An incomplete or invalid pending range blocks switching clips through list selection, previous/next controls, arrow shortcuts, Next undefined, verdict-and-advance and Add to project + Next. Block panel changes, session creation/replacement and ending the session as well, before changing verdicts, project membership or session state. Explain which endpoint needs correction and offer Clear range through the existing control. A blocked mouse selection restores the current clip selection. Completing the pair or clearing the range releases the block; explicit metadata reset also clears pending markers.
- In/Out points never trim or rewrite the source video.
- Project Export copies whole videos without exporting In/Out metadata.

---

## 9. Global UI

### 9.1 Theme

Use the application-wide dark design system in §20. A light theme is not required.

Page and clip transitions keep the native video surface hidden until the surrounding controls are prepared and the first frame is ready (or loading fails). Page changes reveal the prepared page and video together. Within Editing and Export, clip changes cover only the clip details/player area (and Editing command area); the library and navigation remain visible and usable. Reveal the new details and video together. Clip selection must not rebuild the library or unrelated controls, reset its scroll position, or restart an already selected clip. Keyboard navigation scrolls only enough to reveal its destination. Necessary library rebuilds retain surviving selections and the viewport anchor where possible. Show a quiet Loading… indicator only when the transition lasts longer than 1000 ms. Media errors and missing sources reveal the details with an error instead of leaving them covered; a preview that has not produced a frame within 15 seconds stops waiting and offers retry through Play. Stale transition callbacks must not reveal a newer page prematurely.

### 9.2 Settings and Actions

There is no menu bar. The navigation strip is the top application control row. Its right-aligned settings cog opens a menu containing Settings…, Capture folders…, Reset clip metadata…, Edit tag…, Delete rejected originals…, Reset window and panes, and Exit. Undo and Redo icon buttons sit to the left of Projects, with 4 px between them and a 16 px gap before Projects. Retain Ctrl+Z, Ctrl+Shift+Z and Ctrl+Q, with text inputs retaining native undo/redo behavior. Existing page controls provide projects, capture folders, sharing, export, configuration and playback actions. Projects and the settings cog use matching 28 px heights and are vertically centered in the strip. Undo, Redo and settings icon artwork is optically offset 1 px downward within its button.

Resetting clip metadata must never modify or delete the source video. Destructive catalogue operations retain explicit confirmation.

### 9.3 Panel Navigation

At the top of the window, provide a restrained six-destination navigation strip with connected desktop-style tabs and a cyan active top edge:

1. Home
2. Import
3. Session
4. Editing
5. Export
6. Config

The panel-navigation row and settings cog are present on every panel.

### 9.4 Pane Layout

The application uses a Premiere-inspired three-pane layout where relevant.

- The left pane defaults to roughly 30% of the normal window width.
- The right Projects pane defaults to collapsed in normal windows and expanded to roughly 25% when maximized. A visible **Projects** toggle with a folder icon controls it and is highlighted while the pane is open; manual visibility overrides are remembered separately for normal/maximized states for the current run. Export and Config always hide it. Reset Layout restores defaults.
- Both panes are manually resizable using splitters.
- Resizing/maximizing the window primarily gives additional width to the center pane.
- User-adjusted pane widths are not persisted across application restarts.

The exact content of each pane depends on the active panel.

| Panel | Left pane | Center/main area | Right pane | Command bar |
| --- | --- | --- | --- | --- |
| Home | Library reference | Capture-folder management | Projects | Hidden |
| Import | Library reference | Shortcut to capture folders on Home | Projects | Hidden |
| Session | Full library with search/filter/sort | Session creation and status | Projects | Hidden |
| Editing | Locked session queue | Video + clip metadata | Projects | Visible |
| Export | Selected project/member list | Project export controls + smaller player | Hidden | Hidden |
| Config | Library/reference view | Config placeholder/status | Hidden | Hidden |

The shared library triage filter defaults to Undefined on application startup, showing only clips without a Keep/Discard verdict. The selection stays in effect across panel changes and session creation for the current run, but is not persisted across restarts. Other triage filters remain available; frozen Editing sessions and Export membership are unaffected.

### 9.5 Left-Pane Library

The general library view supports:

- free-text search;
- structured query expressions;
- sorting;
- triage filters;
- game filters;
- project filters where relevant.

The search bar does **not** expose raw SQL.

Examples of structured queries include:

```text
game:VALORANT agent:Jett
triage:keep kill:>=4
clutch:>=3 weapon:Vandal
tag:LOW_FPS
```

Plain terms search human-facing text such as source filename, `mainline`, and `description`.

Search/filter parsing is case-insensitive and resolves canonical aliases using the current game configuration where applicable.

Ratings are deliberately **not** searchable or filterable in the initial design. Rating exists mainly as an editorial reference and optional export-grouping value.

---

## 10. Home Panel

Home owns capture-folder management. The settings cog retains its action menu: **Capture folders…** opens Home, while **Settings…** opens the General/Projects dialog (General selected initially).

Show a folder list with readable scanning state, clip/game counts, average duration, and three controls: **Add folder…**, **Rescan**, and **More…**. More contains selected-folder **Pause scanning / Resume scanning**, **Relink folder…**, and **Remove folder…** actions, followed by the advanced global **Rebuild media information…** action. Disable selected-folder actions without a valid selection. No capture-folder controls are duplicated in Settings or Import; Import links to Home. Hide the inactive command bar on Home.

Legacy clips whose folders were previously unregistered appear as an **Unlinked catalogue clips** row with a count and source-directory tooltip. Its More menu offers **Remove saved entries…**, with the same explicit confirmation and backup as folder removal. Revalidate that reviewed clips are still unlinked before removing them.

---

## 11. Import Panel

### Incremental media inspection

Startup and manual scans retain immediate cancellable modal progress. SQLite schema v2
stores inspection results by normalized path, file size and nanosecond modification
time; the path alone remains clip identity. Cached duration and capture date load before
the initial library refresh. Unchanged successful results require no ffprobe launches,
including after restart. File-specific failures retry after 24 hours or immediately
when attributes change. Missing ffprobe produces an operation warning and no reusable
failure entry. Home → More → Rebuild media information… bypasses the cache for all enabled capture folders. Ordinary Rescan discovers new files and inspects only new/changed or retry-eligible files; rebuilding forces inspection of every discovered file. Both preserve catalogue metadata and source files.

Discovery, cache access and folder ingestion run in a background coordinator. At most
two ffprobe processes run at once, with a 20-second per-file timeout and cancellable
polling that terminates and reaps active processes. Deterministic discovery order and
existing game assignments, metadata and frozen Session membership remain unchanged.
Compare size/mtime before and after inspection; discard unstable results and report
them for retry. Completed folders commit independently. Cancellation rolls back the
current folder's ingestion; completed inspections may remain cached. New folders still
require preview confirmation before registration and background ingestion.

Progress reports discovery, cache reuse, inspection, warnings and catalogue updates,
throttled during each phase. Controls remain modal until cleanup finishes; refresh views
once after applying results. Log traversal, inspection and database timings separately,
plus UI refresh time and cache/probe counts. Migration and purge invalidate affected
cache entries; missing sources retain catalogue records. Source files are never modified.
No hashing, watchers or periodic scanning is introduced. Replacements preserving both
size and mtime require explicit reinspection.

The import workflow is managed from Home and discovers source media while adding or maintaining references in the catalogue.

Capture folders are persisted across application runs.

On each application startup, automatically rescan all enabled capture folders once, after the UI is initialized, using the existing cancellable background scan. Disabled folders remain excluded. Preserve existing clip identities, metadata, missing-source entries and frozen Session membership/order. Report folder errors without preventing other folders from being scanned. With no enabled folders, do nothing. Manual Refresh/Rescan remains available; periodic polling is not required.

### 11.1 Capture-Folder Classification

DFSorter supports ShadowPlay/Instant-Replay-style roots containing game-specific subdirectories.

When recursively scanning a recorder-organized capture root:

1. walk upward from a video's immediate parent toward the capture root;
2. use the nearest ancestor whose folder name resolves to a known game using game-config aliases;
3. if no recognized ancestor exists, leave the clip's game undefined.

An explicitly forced game assignment for a capture root overrides automatic folder-name classification.

### 11.2 Capture-Folder UI

Home shows:

- configured capture folders;
- enabled/disabled state;
- clip counts;
- clip counts by recognized game;
- average clip duration where available;
- manual Rescan;
- Add Folder;
- Remove folder… under More;
- Relink folder… under More.

Adding a folder should allow a preview before confirmation, including at least the number of recognized videos per game.

When first onboarding a folder, the user may optionally force every discovered video in that folder to one game.

### 11.3 Missing Files and Folder Migration

A missing file or temporarily disconnected drive is treated as unavailable, not deleted.

Source disappearance must never automatically remove clip metadata.

Relink folder… updates source paths while retaining stable clip IDs and all metadata/project/session references; it never moves files. Before confirmation, validate the destination and source-identity collisions and show the destination, affected clip count, files found and files that will become unavailable. Invalidate affected inspection caches after relinking.

Remove folder… uses one confirmation that shows the folder, clip count, affected project/session counts and full paths in expandable details. Cancel is the default; **Remove from catalogue** is the destructive action. Save a timestamped SQLite backup under `data/backups/` first, then remove the folder, clips, inspection cache and project/session references in one transaction. Preserve the current session clip if it survives; otherwise select the next surviving clip, or the last survivor, or clear the empty session. Clear obsolete undo/redo history. Source videos are never deleted. The separate Purge button is removed.

Pause scanning retains all catalogue data and existing sessions, skips startup/manual scans, and excludes the folder from new sessions. Resume scanning restores eligibility for subsequent scans and new sessions; it does not move files or reset metadata.

---

## 12. Session Panel

All Editing-panel triage is performed within one persisted Session.

DFSorter maintains at most one Session at a time. Creating a replacement while one already exists must explicitly end/replace the existing Session. Ending a Session deletes only Session state and never changes clip metadata.

A Session freezes:

- the ordered list of clip IDs;
- the current index/progress position.

A Session does **not** snapshot clip metadata. Metadata remains live and editable.

### 12.1 Creating a Session

The Session panel shows the eligible library with normal search, filters, sorting, and selection. Clips associated with disabled capture folders cannot enter new Sessions through Selected, First N or All. Re-enabling restores eligibility. Existing frozen Sessions and project memberships remain unchanged. Clips retained after removing a folder remain eligible.

A new Session may be created from:

- the currently selected clips;
- the first `N` clips from the current filtered/sorted result;
- all clips from the current filtered/sorted result.

The resulting ordered clip-ID list is frozen when the Session is created.

By default, order follows the library's current sort. A common triage workflow is untriaged clips sorted oldest first.

Once locked, Session membership and ordering do not change because metadata or search results change.

### 12.2 Session Progress

The Session stores the current clip index across application restarts.

While Editing, the left pane shows only Session clips in the frozen order and does not expose sorting or filters. An Editing-only header above the clip list shows **Session clips** on the left and a compact icon-only **Next undefined clip** button on the right, with a downward navigation icon and an explanatory tooltip. It jumps to the next undefined clip later in frozen Session order without changing metadata or verdicts, preserving drafts. It does not wrap; if none exists ahead, it stays on the current clip and reports that fact.

The Session view should display progress and the proportions/counts of:

- Keep;
- Discard;
- Undefined.

Clip metadata in the Session list may be refreshed only at stable interaction boundaries such as explicit clip navigation or panel navigation, rather than continuously while the user is typing, to avoid distracting list movement.

---

## 13. Editing Panel

The Editing panel is disabled until a Session exists.

The Editing layout provides:

- Session queue on the left;
- player and clip information in the center;
- collapsible projects on the right, following the normal/maximized visibility rules;
- command bar at the bottom of the center pane, allowing the left clip list to use the full pane height.
- a compact footer below the Editing clip list shows Kept, Rejected, Undefined and Total counts for the frozen Session, updating immediately after verdict changes and undo/redo. Hide empty list-error messages so they reserve no vertical space.

### 13.1 Clip Display

Under the video player, show:

1. the current **working title**;
2. the original source filename/stem in smaller grey text;
3. triage state;
4. current game assignment;
5. rating as clickable stars;
6. project membership/active-project information;
7. selectable, read-only `description` text, visible only when populated.

The working title is derived from current structured metadata and `mainline` using the game's YAML `display_order`.

Example:

```text
VAL_1v4 3K Killjoy Ascent Vandal clutch of the century
```

The `mainline` portion is visually emphasized in the UI.

Use a prominent working title, muted structured metadata and source details, a compact five-star control with hover preview and a clear action, and secondary description text shown only when populated; descriptions are entered through the command bar. The tag appears only when populated, as a bold bright-yellow bracketed prefix before the game-code title in clip cards and before the Editing working title (including filename fallbacks). There is no dedicated tag textbox. Commands or **Settings cog → Edit tag…** add, change, or clear it. Escape rich text, retain title elision and full tooltips; generated Share/Export filenames do not include this UI prefix. Unset ratings show red empty star outlines with no background highlight; hover previews remain gold and selecting a rating removes the red treatment. Ratings remain optional, never zero.

Description text is secondary and is never automatically appended to the working title. There is no dedicated description editor or Save description button. Set In, Set Out, Clear range and Share icon actions sit on the right of the playback-controls row immediately beneath the video timeline. A vertical divider separates them from the icon-only Add to project + Next action, whose tooltip includes Ctrl+Enter. In/Out state is shown on the timeline without a separate range text display.

Structured field widgets may display the current stored values for direct inspection/editing, but the command line remains the primary high-throughput input mechanism.

At the end of the field checklist row, show a red danger icon and `I/O not set` whenever either range endpoint is missing, or `I/O invalid` for invalid endpoint order. Hide the indicator for a valid range while retaining its layout space. Range warnings must not open a separate error row or resize the video; retain completion guidance in the indicator tooltip and preserve pending-range navigation safeguards.

### 13.2 Command-Bar Focus and Playback Keys

Entering Editing or changing clips starts review mode with a non-text surface focused.

- Tap Space toggles playback; holding for 200 ms plays at 3× until release, restoring the previous state. While hold-Space fast-forward is active, show a bold `>>>` centered on the existing transport/volume/range-controls row beneath the timeline in both players, with an accent-colored highlight moving left to right every 120 ms. Animate only during the hold; stop and reset the animation when the hold ends. Reserve only its horizontal space when hidden; do not add a separate row or move controls vertically. Release, focus loss and clip/panel changes hide it through the existing hold cancellation. Focus loss cancels the hold.
- Left/Right seek ±5 seconds; Shift+Left/Right seek ±1 second. I/O set markers. Backspace rejects without advancing.
- Ratings use command input (`R1` through `R5`, case-insensitive) followed by Enter, or the clickable stars. There is no review-mode rating key sequence.
- `/` or Enter enters metadata input without inserting text or submitting a retained draft. Slash commands are not supported.
- Every text field consumes normal editing keys, including Space and Backspace when empty, except for the one-shot post-submit Space behavior below.
- Enter submits commands only in command-input mode and remains in input on success; invalid commands retain input focus and text. Shift+Enter never submits; it applies verdict-and-advance in review mode or command-input mode when the command bar is completely empty. Escape returns to review preserving the draft.
- Ctrl+Enter in review mode adds the current clip to the active project and advances one position in frozen Session order regardless of triage. It requires an active project, preserves triage and drafts, ignores auto-repeat, and stays on the last clip without wrapping. Existing membership is harmless. A visible icon-only **Add to project + Next** button at the bottom right of the Editing player provides the same action and is disabled without an active project. The Projects menu retains **Add to project** for the current selection (one clip in Editing, potentially multiple in other library views).
- Unmodified Up/Down in Editing review mode navigates every clip in frozen Session order, including kept/rejected clips, without wrapping. Text fields retain their normal keys. Preserve drafts and scroll only enough to reveal the destination.
- While a usable Editing video is paused, ordinary typing enters command input and inserts the triggering text once at its retained cursor. Existing review/video shortcuts take priority, including I/O, Space, arrows, Backspace, / and Enter. Other text fields, menus, dialogs and modifier-only keys are excluded. Settings → General → **Type to enter commands while video is paused** defaults on and persists immediately.
- Command colors indicate validation independently of keyboard mode: neutral when empty or typing an unfinished token, subtle blue for a valid draft, amber bottom border for incomplete syntax, red bottom border for invalid input, and a green bottom border for 1.2 seconds after saving. Retain the cyan focus outline. Defer unknown-token errors until a token is delimited or submission fails; explicit invalid values and conflicts can show immediately. A short hint explains validation and shows “Saved · Space to resume” after a successful submission while paused. In that post-submit state only, the first unmodified Space resumes normal-speed playback and enters review without inserting text; consume its repeats and release. Other non-modifier keys consume the opportunity and behave normally. Mouse interaction, focus loss, playback changes, paste and clip/panel changes cancel it. Failed commands do not arm it. This post-submit behavior is independent of the paused-typing setting.
- Unsubmitted metadata drafts are retained per clip for this run, including across panel changes; they are not persisted on restart.
- A contextual hint and `?` button/shortcut explain review/input keys and the watch, annotate, verdict, advance workflow.

Use native Qt video presentation and prefer hardware decoding, allowing logged software fallback. Coalesce drag seeks to at most 20 Hz with approximate previews; perform the final unquantized seek on release and restore playback state. Exception: after natural media completion, seeking backward resumes playback automatically; dragging previews while held and resumes on release. Apply this recovery in Editing and Export. Ordinary paused seeking remains paused; missing/failed media is not treated as completed playback. The timeline has a 7 px groove, larger hit target, colored markers, saved-range tint, and distinct pending In and Out markers. Put transport/audio/time controls directly beneath it.

### 13.3 Command Syntax

The command bar receives one complete string.

The field checklist beneath it previews saved metadata merged with the current valid command as text changes. Enter is still required to save. Empty commands show saved fields. Incomplete or invalid commands retain a preview of the longest fully parseable prefix merged with saved fields; the checklist tooltip distinguishes partial previews from complete drafts. No incomplete token contributes a value. Previewing must not modify catalogue data, history, titles or the Session list.

`tag:` is a reserved global prefix for the tag field, available without an assigned game. Use `tag:LOW_FPS` or `tag:"audio issue"`; consume one token or quoted value, preserving capitalization and trimming outer whitespace. `tag:""` clears; bare `tag:` is invalid. Conflicting repeated assignments reject the entire command. Search accepts `tag:` with exact, case-insensitive matching (empty search values remain invalid). Game configurations cannot reuse this prefix. VALORANT accepts `brim` as an input alias for canonical `Brimstone`.

General syntax:

```text
<structured metadata> [-- <mainline> [-- <description>]]
```

Example:

```text
1v4 3k killjoy ascent vandal R4 -- clutch of the century -- clean start, slow ending
```

Structured metadata parsing is case-insensitive.

The `mainline` and `description` segments preserve the user's capitalization, punctuation, quotes, and internal spacing; leading and trailing whitespace is removed. The same edge trimming applies to identified structured field values, including quoted values. Existing catalogue text is not retroactively rewritten.

The first `--` begins `mainline`.

A second `--`, if present, begins `description`.

More than two unquoted `--` separators are invalid.

Description may alternatively be edited directly in its dedicated textbox.

### 13.4 Parsing Rules

Reserved patterns:

- `1vX` -> `clutch = X`
- `XK` or `Xk` -> `kill = X`
- `R1` through `R5` -> `rating = 1..5`

All other structured tokens are resolved through the current game's YAML configuration.

The parser is deterministic and command application is atomic.

If any part of a command is invalid or ambiguous:

- no metadata from that command is applied;
- the current command text remains available for correction;
- an inline error is shown near the command bar.

A successful command behaves as a **patch**:

- fields not mentioned remain unchanged;
- for a scalar field, supplying multiple conflicting values in one command is an error;
- for a `multiple: true` field, all values supplied for that field in the command replace the previous stored list;
- repeated identical list values are deduplicated while preserving order.

Example:

```text
jett sheriff vandal
```

sets:

```text
agent = Jett
weapon = [Sheriff, Vandal]
```

If a later command contains only:

```text
phantom
```

then:

```text
weapon = [Phantom]
```

and the agent remains Jett.

### 13.5 Command History

Show the last three valid commands entered for the current clip above the command bar. Hide empty history and error rows; size the command area to visible content with compact bottom padding. Adding history expands the area upward without reserving blank space below the command bar.

This command history exists only in memory and does not persist across application restarts.

### 13.6 Submission, Triage, and Navigation

- `Enter` in command-input mode submits a valid command, remains on the current clip and stays in input mode. Enter in review mode focuses the command bar, like `/`, without submitting.
- `Shift+Enter` applies verdict-and-advance in review mode or command-input mode when the command bar is completely empty; it never submits a command. Ignore auto-repeat. Failed validation preserves input focus; a successful action enters review mode. Other text fields retain their normal editing behavior.
- If the command bar contains any text, including whitespace or a retained draft, Shift+Enter in either mode refuses advancement and prompts the user to enter input mode and press Enter to submit existing commands first.
- A successful metadata command by itself does **not** change triage.
- For a non-discarded clip, Shift+Enter requires a configured game and every field in its `required_for_export` list. Missing requirements leave verdict and position unchanged and are listed inline. A legal action changes triage to `keep`, applies the normal active-project membership rule and advances. This is metadata validation; source availability remains an export requirement.
- An explicitly discarded clip advances while preserving Discard, even with missing fields, no game or an unavailable source. The empty-command-bar requirement still applies.
- After applying the legal verdict, advance to the next clip with undefined triage later in frozen Session order, skipping Keep and Discard clips. Do not wrap. If none remains ahead, stay on the current clip and report Session complete only if no Session clips remain undefined; otherwise report that earlier clips remain undefined. Do not delete or replace the Session. Ignore key auto-repeat for advancement.
- Backspace in review mode marks the current clip `discard`; in every text field, including an empty command bar, it only edits text.
- Backspace does not automatically advance; the user may then use `Shift+Enter` or ordinary navigation to continue.
- Rating never changes triage.
- Clicking the visible triage controls may also set Keep/Discard/Undefined directly.

### 13.7 Rating

Rating is optional and available for every game.

It is entered primarily through:

```text
R1
R2
R3
R4
R5
```

The parser is case-insensitive.

The Editing panel displays the stored rating as a clickable 1-5 star control.

Rating is reference metadata only. It does not automatically Keep, Discard, or prioritize a clip and is not included in ordinary search/filter functionality.

### 13.8 Active Project Behavior

A clip may belong to multiple Projects.

At most one Project may be active at a time.

Whenever a clip transitions to `keep` from the Editing panel while a Project is active, DFSorter adds that clip to the active Project if it is not already a member.

Changing or deactivating the active Project does not remove existing memberships.

Changing a clip away from Keep does not automatically delete existing project membership; export rules determine whether the clip is actually copied.

---

## 14. Projects

Projects are stored as persistent application/database state, not as YAML files.

A Project contains:

- stable project ID;
- name;
- references to member clip IDs.

Clips may belong to any number of Projects.

At most one Project may be active at a time.

Projects may be created, renamed, activated, deactivated, and deleted.

Deleting a Project removes only the Project and its memberships. It never deletes clip catalogue entries or source videos.

The right project pane provides access to these operations and shows which Project, if any, is currently active.

Use a compact icon toolbar and project context menu; Delete remains in the context menu with confirmation. Use vendored Lucide SVGs from `resources/icons`, never runtime assets from node_modules. Clip lists use the compact bordered cards in §20.4, status dots, full-text tooltips, and no horizontal scrollbar. Session creation uses Selected / First N / All with one primary Create Session action; enable the count only for First N.

---

## 15. Share

Share is a clip-level action and is **not** part of the Export panel.

It may be invoked from the Editing panel or an appropriate Clip/File action for the currently selected clip.

Sharing:

1. selects one source clip;
2. chooses an output folder, with a persistent default share folder available in application settings;
3. chooses either:
   - a generated filename based on the working-title fields selected for that share; or
   - a user-supplied custom filename;
4. chooses the whole clip or its saved valid In/Out range, defaulting to the range when available;
5. creates an H.264 MP4 with one stereo AAC track mixing all audio tracks, or no audio if the source is silent.

Range shares decode and re-encode through the exact source-frame/audio-sample boundaries. Pending In/Out edits do not replace the saved range offered for Share; the dialog explains when it is using the saved pair. Whole H.264 shares copy the video stream without generation loss; other codecs and all range shares re-encode, preferring NVIDIA H.264 P5/CQ19 with x264 medium/CRF18 fallback. Preserve source resolution and frame timing. Share requires FFmpeg and ffprobe and supports background processing, cancellation, temporary output validation, and cleanup on failure.

Share outputs use `.mp4`. Project Export retains the source extension and original bytes.

Filesystem-invalid characters are sanitized only in the copied filename; catalogue text is not altered.

Existing destination files are never overwritten. Name collisions receive a numeric suffix.

The copied file is not added back into DFSorter and is not tracked after the copy completes.

---

## 16. Export Panel and Project Export

The Export panel is dedicated to **Project Export**.

It contains:

- selection of one Project;
- a smaller preview player;
- the Project's member list;
- export validation/errors;
- filename-format controls;
- output-directory controls;
- optional rating-based directory grouping;
- final export action.

The right project pane and command bar are hidden to give the Export panel more room.

### 16.1 Export Eligibility

For a Project Export:

- `keep` clips are candidates for export;
- `discard` clips are ignored;
- any clip with undefined triage blocks the entire export;
- any kept clip missing a field listed in that game's `required_for_export` blocks the entire export;
- any kept clip whose source file is unavailable blocks the entire export.

One invalid clip blocks the whole export.

The Export panel must clearly list every blocking clip and the reason it is invalid before the user can export.

### 16.2 Export Filenames

For each game represented in the Project, the user may choose which structured fields appear in the generated filename.

The user may independently choose whether to include:

- the game's three-letter prefix;
- clutch;
- kill;
- game-specific fields such as agent, map, or weapon;
- `mainline`.

Selected fields follow the game's YAML `display_order`.

`description` is not included in generated filenames.

The source file extension is preserved.

Output names are sanitized for the destination filesystem without changing the stored metadata.

Existing files are never overwritten. Collisions receive a numeric suffix.

### 16.3 Export Directory Layout

The default Project Export is **flat**: all exported videos are copied directly into the selected project-export directory.

DFSorter does not attempt to infer arbitrary organizational folders from game metadata in v1.

An optional **Group by Rating** export mode may instead create one subdirectory per rating value, plus an `Unrated` group for clips with no rating. The exact cosmetic folder names may be chosen consistently by the implementation.

No general-purpose "group by arbitrary field" directory builder is required in v1.

### 16.4 In/Out Ranges and Export

Project Export copies the entire source video. In/Out markers do not trim the exported file.

XMP support is deferred. Do not generate metadata sidecars or reserve sidecar filenames during Export or Share. Existing sidecars remain untouched. Saved In/Out ranges remain catalogue metadata for playback and range Share.

### 16.5 Stateless Export Semantics

Project Export is a stateless copy operation with respect to its destination.

After copying, DFSorter does not:

- synchronize exported copies;
- rename them later;
- delete them later;
- track user edits to them;
- treat them as new catalogue sources.

Re-exporting the same Project later is a new copy operation. Existing files are never overwritten and therefore receive collision suffixes as necessary.

---

## 17. Config Panel

A full graphical game-config editor is postponed.

In v1, game definitions are edited directly as YAML files under `configs/games/`.

The Config panel may remain a lightweight placeholder or status view. It should not invent a separate configuration model.

The application should validate loaded game configs and report errors clearly.

Configuration changes must never silently delete existing clip metadata.

---

## 18. Undo and Redo

Undo/redo is intentionally narrow.

Navigation Undo and Redo icons independently reflect their catalogue history stacks: available actions use slightly brighter neutral artwork (`#B8BFC9`); unavailable actions are disabled with dim gray artwork (`#59616C`). Refresh availability after edits, undo/redo, and history clearing. Preserve native text-input undo/redo.

The normal undo stack covers user metadata operations performed during the current application run, including:

- structured metadata changes;
- mainline/description edits;
- rating changes;
- triage changes;
- project membership changes where practical;
- In/Out marker changes.

Undo/redo does not need to cover:

- source-file copies;
- capture-folder deletion/purge;
- source-path migration;
- project export;
- Share;
- external YAML edits;
- other filesystem operations.

Destructive catalogue operations outside the normal undo model require explicit confirmation.

---

## 19. Safety and Non-Goals

DFSorter must not silently modify original source media.

### 19.1 Explicit deletion of rejected originals

File → Delete rejected originals is an explicit exception to source preservation. It permanently deletes original video files for all library clips whose triage is `discard`, irrespective of current filters, projects, sessions, or whether their capture folder remains enabled or registered. It bypasses the Windows Recycle Bin.

Before deletion, show a read-only preview grouped by actual parent folder, with full paths, per-folder rejected/to-delete counts, clip dates, individual sizes, folder totals and estimated overall size. Prefer cached media capture dates; label filesystem modification dates when used as fallback. Missing, linked/junction and non-regular sources are excluded with reasons. Logical file size is an estimate of space recovered.

Confirm through a red "Permanently delete originals" button in the preview, enabled when eligible files exist; no typed confirmation is required. Recheck catalogue identity, Discard status, path and file identity/size/timestamps before each deletion. On Windows, delete through a verified file handle that excludes concurrent writers and replacement; locked or changed sources are skipped. Never delete a folder or adjacent sidecar. Preserve catalogue records and project/session references as unavailable media. Cancellation stops subsequent deletions; report each success, skip, failure and cancellation. Deleted originals cannot be restored by metadata Undo. Do not run concurrently with scanning, sharing or export.

### 19.2 Unified settings

The top-right Lucide settings cog retains its action menu. Settings… opens a dialog with General and Projects tabs, with General initially selected; Capture folders… navigates to Home. General contains the configurable near-end playback start and paused-typing preferences. Project-pane controls remain available. Capture-folder management lives only on Home.

Normal review, metadata editing, session creation, project membership, search, filtering, rating, and I/O marking operate only on catalogue state.

The following are outside the initial scope unless separately specified later:

- nonlinear video editing;
- transcoding/proxy generation outside the explicitly specified Share operation;
- automatic AI/LLM classification;
- a general-purpose graphical game-schema editor;
- arbitrary-field export folder generation;
- cloud synchronization;
- multi-user support;
- source-file content hashing;
- automatic deletion of missing source entries.

---

## 20. Design System

### 20.1 Visual Direction and Ownership

Use a Premiere/Resolve-adjacent neutral dark desktop design: dense, restrained, flat, low-saturation surfaces, subtle borders, quiet sidebars, strong alignment, and a large video area. Avoid gradients, oversized controls, pill buttons, neon styling, large rounded cards, and unnecessary panel borders. Compact clip cards are an intentional exception to border-light panels.

Apply this system to all six pages, menus and application-owned dialogs. Native Windows file pickers keep operating-system styling. `src/dfsorter/theme.py` owns named tokens, typography, palette and generated QSS; custom painters, SVGs and rich text consume the same tokens. Do not scatter literal colors across widgets.

### 20.2 Color Tokens

| Role | Tokens and values |
| --- | --- |
| Backgrounds | `bg_app #1E2228`, `bg_panel #181C22`, `bg_panel_alt #15191F`, `bg_surface #252B33`, `bg_surface_hover #2D3540`, `bg_surface_pressed #343E4A`, `bg_input #12161C`, `bg_video #000000` |
| Borders | `border_subtle #2B323C`, `border_default #3A4350`, `border_strong #4B5665`, `separator #303741` |
| Text | `text_primary #E6E9ED`, `text_secondary #A9B0BA`, `text_muted #77808C`, `text_disabled #59616C`, `text_inverse #111317` |
| Interaction | `accent #41B8C7`, `accent_hover #56C9D7`, `accent_pressed #3096A4`, `accent_muted #17373D`, `accent_selection #244A53`, `accent_focus #59D2E2` |
| Success | `success #62C98D`, `success_muted #1C3A2A` |
| Warning | `warning #D9A441`, `warning_muted #3A2D16` |
| Danger | `danger #D9686A`, `danger_hover #E47D7F`, `danger_muted #3A2022` |
| Information | `info #6AA9E9` |
| Rating | `rating_filled #E8C45A`, `rating_hover #F0D16F`, `rating_empty #69717D` |
| Component colors | `command_focus #141B21`, `timeline_track #3A424D`, `timeline_progress #617080`, `scrollbar_hover #56616F`, `tooltip #11151A` |

Cyan means interaction, focus, selection, active project, playhead or I/O markers. Green means Keep or success; red means Discard, destructive operations or blocking errors. Warning amber means incomplete requirements or unavailable sources. Gold rating tokens are reserved for stars. Undefined triage uses muted gray. Always retain text or shape cues in addition to color.

### 20.3 Typography, Spacing and Dimensions

Use Segoe UI on Windows, then installed Inter, Arial and Qt's sans-serif fallback. Do not download or bundle fonts. All dimensions below are logical pixels and scale with Qt's display scaling.

| Tokens | Values |
| --- | --- |
| Font sizes xs / sm / md / base / lg / xl / xxl | 11 / 12 / 13 / 14 / 16 / 20 / 26 |
| Weights regular / medium / semibold / bold | 400 / 500 / 600 / 700 |
| Spacing 1–6 | 4 / 8 / 12 / 16 / 24 / 32 |
| Radius none / sm / md / lg | 0 / 3 / 5 / 7 |
| Control radius | 4 |
| Control compact / normal / large | 24 / 28 / 32 |
| Toolbar / navigation height | 28 / 34 |
| Icons xs / sm / md / lg / xl | 12 / 14 / 16 / 20 / 24 |

Ordinary controls and menus use 13 px regular; secondary metadata uses 12 px; card metadata uses 11 px. Editing working titles use 13 px regular metadata in `text_working_title #C7CDD5`, 13 px regular game codes and separators in `text_muted`, and 16 px bold mainline in `text_primary`. Separate metadata and mainline with ` | ` only when both are present. Retain wrapping. When no populated field contributes to the configured title display order, show the original filename followed by a smaller, secondary-colored “— Working title not set” hint. Section headings use 20 px semibold. Compact pane headings use 14 px semibold primary text. The Session clips header has a transparent background, aligns its title to clip-card text, and aligns its right action to the card edge. Avoid excessive bold text and bordered metadata boxes. Format multi-value metadata as readable comma-separated text, never Python list syntax.

Use 12 px panel padding, 4–8 px gaps within groups, 12–16 px between groups, and 24 px between large sections. Prefer 28 px ordinary controls and 24 px compact controls. Button/input radius is 4 px, panels 0–3 px. Font metrics take precedence over dimensions where necessary to avoid clipping.

### 20.4 Left-Pane Clip Cards

Use one shared delegate in all left-pane library, Session and Export views. A clip card has a 48 px body, 4 px external gap, 1 px subtle border, 3 px radius, neutral `bg_panel_alt` fill and 8 px horizontal padding. Grow only as required by font metrics.

Line one uses 12 px regular muted game codes, 12 px regular structured metadata in `text_working_title`, and 13 px bold primary mainline, with a muted ` | ` separator when both portions exist. Filename fallbacks remain 13 px. Line two is a 6 px triage dot centered against visible text using font metrics, canonical game name (or Unassigned) and Keep/Discard/Undefined at 11 px. Keep the two lines together with a 2 px gap, vertically centered in the card, rather than anchored to opposite edges. Reserve metadata width for triage and an amber Unavailable label before eliding the game name. Long titles elide; no horizontal scrollbar. Tooltips show the complete title, metadata and source path.

Hover uses `bg_surface_hover`; selection uses `accent_selection` plus a 2 px cyan left indicator. Keyboard focus uses a subtle cyan border. Preserve multi-selection outside Editing, single selection within Editing, frozen Session ordering and stable-boundary refresh behavior. Presentation data must use explicit roles, not substring matching against visible text.

### 20.5 Component Rules

- Neutral buttons use surface/hover/pressed colors and default borders. Primary actions use accent-muted fill and accent border sparingly. Destructive buttons use danger text/border with danger-muted fill. Disabled controls use panel background, subtle border and disabled text/icon colors; avoid fading whole widgets into illegibility.
- Navigation sits at the top of the application with no menu bar or outer top gap; the workspace beneath it has its own 12 px inset. Navigation uses a continuous dark strip with a bottom divider and compact rectangular text-only tabs. Labels are 14 px medium; active labels are semibold. The active tab matches the workspace background with a straight 2 px cyan top edge, subtle side borders, and no contrasting bottom border. Inactive labels use secondary text and surface hover. Projects and Settings remain right-aligned utilities.
- Inputs use input background, subtle border, primary text, muted placeholders, default hover border and focus-cyan border. The command bar uses the same idle styling and `command_focus` background when focused. No neon glow or native dotted focus rectangles. Preserve review/input focus semantics.
- Triage controls are neutral unless active: Keep uses success-muted/success; Discard uses danger-muted/danger; Undefined uses pressed-surface/strong-border/secondary-text. Selection reflects stored metadata after edits, navigation and undo/redo.
- Projects remain a secondary utility pane with secondary header text, a cyan active-project indicator and compact icon toolbar. Every icon action has a tooltip and accessible name. Delete stays separate in the context menu with confirmation.
- Use vendored Lucide SVGs: 16 px utility icons, 20 px transport icons. Default/hover/active/disabled icons use secondary/primary/accent/disabled text tokens. Render sharply at high DPI. Tooltips include actual shortcuts when applicable.
- Rating uses 18 px SVG stars with 4 px spacing, gray empty stars, gold filled stars and lighter gold hover preview. The small `x` clear action and right-click clear remain available. Rating never changes triage.
- Video is black. Retain the approved **7 px timeline groove** and larger hit area, overriding the original token sheet's 4–6 px suggestion. Use neutral track/progress, cyan playhead, focus-cyan saved I/O markers, and accent range tint at 18% opacity. Pending In and Out have distinct labels (·I and ·O). Transport/audio/time controls remain directly below.
- Scrollbars are 8 px, transparent-track, neutral-thumb with lighter hover and no arrow buttons. Splitters have a 1 px visual divider and a wider interaction region, with stronger hover color.
- Tooltips appear after a 200 ms hover delay throughout the application. They use tooltip background, default border, primary text, 6 px vertical / 8 px horizontal padding and 4 px corners. Secondary metadata recedes; populated tag prefixes use bold `#F0D16F` and remain hidden when empty. Valid commands use a subtle blue background `#172B40`; incomplete, invalid and briefly saved commands use warning, danger and success bottom borders respectively. Keyboard focus retains its cyan outline; other command backgrounds stay neutral. Unset rating uses the existing danger color for star outlines only, with no background highlight.

### 20.6 Acceptance

Verify adjacent populated cards, long and mixed Chinese/English titles, all triage states, missing sources, multi-selection, narrow panes, keyboard focus and rating hover/clear. Inspect all pages and representative dialogs at normal/maximized sizes and 100%, 125% and 150% scaling. Run existing regressions using isolated catalogues and generated media. Track completed implementation/verification separately from subjective user acceptance in `docs/features.md`.

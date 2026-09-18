# DFSorter Specification

## 1. Introduction

DFSorter is a Python + Qt desktop application for reviewing, triaging, cataloguing, and exporting gameplay montage clips from games such as VALORANT, Escape from Tarkov, and Battlefield 6.

The application should remain minimalistic and should not behave like a video editor. Source clips are treated as immutable media units. DFSorter stores metadata about those clips in a local SQLite database and refers to the original files by path. Source clips are never renamed, moved, trimmed, transcoded, or rewritten by normal catalogue operations.

The two operations that may create video files are:

- **Share**, which copies one selected source clip to a user-selected sharing folder.
- **Project Export**, which copies the exportable clips referenced by one project into an output directory.

Copied files are no longer managed by DFSorter after the copy completes.

The primary review workflow is keyboard-led. In the Editing panel, structured metadata is entered through a deterministic command-line-style text box, while the application still provides a conventional video player and visible representations of the metadata currently stored for the selected clip.

A **Project** is a persistent collection of references to clips in the library. It never owns or duplicates the original media.

A **Session** is a temporary-but-persisted, fixed review queue. It freezes the membership and order of clips selected for one review run while leaving the clips' metadata live and editable.

---

## 2. Naming and Normalization Conventions

- Canonical video-game references stored and displayed by DFSorter use their official names and capitalization where practical. Examples include `VALORANT`, `Battlefield 6`, `Escape from Tarkov`, `Jett`, `Headhunter`, `Tour de Force`, and `Bladestorm`.
- Matching, parsing, aliases, filtering, and text sorting are case-insensitive.
- Case-insensitive matching must not destroy the canonical capitalization of stored structured metadata.
- Free-form human text such as `mainline` and `description` preserves the user's original capitalization, punctuation, and spacing.
- Game-specific YAML files define the canonical game name and a three-letter uppercase display code such as `VAL`, `BF6`, or `EFT`.

---

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

The full normalized source path is the determinant of source identity. DFSorter does not need content hashes or lightweight file signatures. If a different video later replaces a file at exactly the same path, DFSorter treats it as the same source identity.

Path migration tools may update a clip's stored source path while preserving its stable internal ID and all metadata, project memberships, and session references.

A missing source file does **not** cause its database entry to be deleted. It remains in the catalogue in an unavailable state until the source returns, is migrated, or the user explicitly purges the catalogue entry.

Removing a capture folder from DFSorter does not delete source files. The user may optionally purge catalogue entries associated with that source, but this must be an explicit destructive action with confirmation.

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
- `tag` (optional string): a deliberate free-form tag such as `LOW_FPS`.
- `mainline` (optional string): the primary free-form human note used in the working title, such as `clutch of the century`.
- `description` (optional string): secondary triage/editorial notes. Description is not part of the working title.
- `catalogue_modified_at`: timestamp of the most recent catalogue metadata modification.
- one optional persisted **In/Out range** for the clip.
- game-specific metadata defined by the active game configuration.

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
- `O` sets the Out point when text input does not own the key.
- The range is stored as source-relative time and shown on the player's progress display.
- Invalid or incomplete ranges must not silently replace the last valid stored range.
- In/Out points never trim or rewrite the source video.
- Project Export may preserve the stored range through an adjacent XMP sidecar.

---

## 9. Global UI

### 9.1 Theme

Use a dark theme. A light theme is not required.

### 9.2 Menu Bar

The Windows-style menu bar contains:

- **File**: projects, capture folders, and application-level file operations.
- **Edit**: undo/redo and access to game configuration files.
- **Clip**: clip-level operations such as resetting user metadata or manually changing game assignment.
- **View**: video/playback-related controls.
- **Window**: reset the application window and pane layout to defaults.

Resetting clip metadata must never modify or delete the source video. Destructive catalogue operations require explicit confirmation.

### 9.3 Panel Navigation

Below the menu bar, provide six navigation buttons:

1. Home
2. Import
3. Session
4. Editing
5. Export
6. Config

The menu bar and panel-navigation row are present on every panel.

### 9.4 Pane Layout

The application uses a Premiere-inspired three-pane layout where relevant.

- The left pane defaults to roughly 30% of the normal window width.
- The right pane defaults to roughly 25%.
- Both panes are manually resizable using splitters.
- Resizing/maximizing the window primarily gives additional width to the center pane.
- User-adjusted pane widths are not persisted across application restarts.

The exact content of each pane depends on the active panel.

| Panel | Left pane | Center/main area | Right pane | Command bar |
| --- | --- | --- | --- | --- |
| Home | Library reference | Home shortcuts/placeholder | Projects | Visible |
| Import | Library reference | Capture folders and ingest | Projects | Hidden |
| Session | Full library with search/filter/sort | Session creation and status | Projects | Hidden |
| Editing | Locked session queue | Video + clip metadata | Projects | Visible |
| Export | Selected project/member list | Project export controls + smaller player | Hidden | Hidden |
| Config | Library/reference view | Config placeholder/status | Hidden | Hidden |

Unless otherwise stated, ordinary library views hide discarded clips by default.

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

The Home panel is intentionally a placeholder in the initial implementation.

It may contain simple navigation shortcuts such as:

- resume the active session;
- create a session;
- open Import;
- open Editing.

It should not introduce unique data models or automated behavior in v1.

---

## 11. Import Panel

Import is exclusively responsible for discovering source media and adding or maintaining references in the catalogue.

Capture folders are persisted across application runs.

The application may periodically rescan enabled capture folders for new clips. The exact automatic polling interval is not product-critical; manual Refresh/Rescan must always be available.

### 11.1 Capture-Folder Classification

DFSorter supports ShadowPlay/Instant-Replay-style roots containing game-specific subdirectories.

When recursively scanning a recorder-organized capture root:

1. walk upward from a video's immediate parent toward the capture root;
2. use the nearest ancestor whose folder name resolves to a known game using game-config aliases;
3. if no recognized ancestor exists, leave the clip's game undefined.

An explicitly forced game assignment for a capture root overrides automatic folder-name classification.

### 11.2 Capture-Folder UI

The Import panel should show:

- configured capture folders;
- enabled/disabled state;
- clip counts;
- clip counts by recognized game;
- average clip duration where available;
- manual Refresh/Rescan;
- Add Folder;
- Remove Folder;
- source migration tools.

Adding a folder should allow a preview before confirmation, including at least the number of recognized videos per game.

When first onboarding a folder, the user may optionally force every discovered video in that folder to one game.

### 11.3 Missing Files and Folder Migration

A missing file or temporarily disconnected drive is treated as unavailable, not deleted.

Source disappearance must never automatically remove clip metadata.

Capture-folder migration updates source paths while retaining stable clip IDs and all metadata/project/session references.

Removing a capture folder dereferences it from automatic scanning. An optional separate purge may remove associated catalogue entries after explicit confirmation; source videos are never deleted.

---

## 12. Session Panel

All Editing-panel triage is performed within one persisted Session.

DFSorter maintains at most one Session at a time. Creating a replacement while one already exists must explicitly end/replace the existing Session. Ending a Session deletes only Session state and never changes clip metadata.

A Session freezes:

- the ordered list of clip IDs;
- the current index/progress position.

A Session does **not** snapshot clip metadata. Metadata remains live and editable.

### 12.1 Creating a Session

The Session panel always shows the full library with normal search, filters, sorting, and selection.

A new Session may be created from:

- the currently selected clips;
- the first `N` clips from the current filtered/sorted result;
- all clips from the current filtered/sorted result.

The resulting ordered clip-ID list is frozen when the Session is created.

By default, order follows the library's current sort. A common triage workflow is untriaged clips sorted oldest first.

Once locked, Session membership and ordering do not change because metadata or search results change.

### 12.2 Session Progress

The Session stores the current clip index across application restarts.

While Editing, the left pane shows only Session clips in the frozen order and does not expose sorting or filters.

The Session view should display progress and the proportions/counts of:

- Keep;
- Discard;
- Undefined.

Clip metadata in the Session list may be refreshed only at stable interaction boundaries such as explicit clip navigation or panel navigation, rather than continuously while the user is typing, to avoid distracting list movement.

---

## 13. Editing Panel

The Editing panel is disabled until a Session exists.

All main panes are present:

- Session queue on the left;
- player and clip information in the center;
- projects on the right;
- command bar at the bottom.

### 13.1 Clip Display

Under the video player, show:

1. the current **working title**;
2. the original source filename/stem in smaller grey text;
3. triage state;
4. current game assignment;
5. rating as clickable stars;
6. project membership/active-project information;
7. a `description` text box.

The working title is derived from current structured metadata and `mainline` using the game's YAML `display_order`.

Example:

```text
VAL_1v4 3K Killjoy Ascent Vandal clutch of the century
```

The `mainline` portion is visually emphasized in the UI.

The description box is secondary and is never automatically appended to the working title.

Structured field widgets may display the current stored values for direct inspection/editing, but the command line remains the primary high-throughput input mechanism.

### 13.2 Command-Bar Focus and Playback Keys

The command bar is visible and receives focus when entering Editing or moving to a new clip.

Normal text-editing behavior takes priority while a text field contains input.

To avoid shortcut conflicts:

- when the command bar contains text, Space and Backspace edit the text normally;
- when the command bar is empty, Backspace marks the current clip `discard`;
- hold-Space fast-forward is available when a text-editing control is not consuming Space;
- I/O shortcuts are active only when a text-editing control is not consuming those keys.

### 13.3 Command Syntax

The command bar receives one complete string.

General syntax:

```text
<structured metadata> [-- <mainline> [-- <description>]]
```

Example:

```text
1v4 3k killjoy ascent vandal R4 -- clutch of the century -- clean start, slow ending
```

Structured metadata parsing is case-insensitive.

The `mainline` and `description` segments preserve the user's capitalization, punctuation, quotes, and spacing.

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

Show the last three valid commands entered for the current clip above the command bar.

This command history exists only in memory and does not persist across application restarts.

### 13.6 Submission, Triage, and Navigation

- `Enter` submits a valid command and remains on the current clip.
- `Shift+Enter` submits a valid command and then advances to the next Session clip.
- A successful metadata command by itself does **not** change triage.
- When `Shift+Enter` succeeds, the clip becomes `keep` unless it is already explicitly `discard`.
- Backspace on an empty command bar marks the current clip `discard`.
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
4. copies the whole original video.

Share never trims the clip to its In/Out range.

The source extension is preserved.

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

### 16.4 In/Out XMP Sidecars

Project Export copies the entire source video. In/Out markers do not trim the exported file.

If a clip has a valid stored In/Out range, export an adjacent `.xmp` sidecar that preserves at least:

- stable clip identity;
- source-relative In time;
- source-relative Out time.

The source video must not be rewritten in order to add this metadata.

Adobe/Premiere-specific interpretation may be validated separately; the required v1 behavior is preservation of the range in valid XMP alongside the exported copy.

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

Normal review, metadata editing, session creation, project membership, search, filtering, rating, and I/O marking operate only on catalogue state.

The following are outside the initial scope unless separately specified later:

- nonlinear video editing;
- transcoding/proxy generation;
- automatic AI/LLM classification;
- a general-purpose graphical game-schema editor;
- arbitrary-field export folder generation;
- cloud synchronization;
- multi-user support;
- source-file content hashing;
- automatic deletion of missing source entries.

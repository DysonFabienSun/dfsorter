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
- Game-specific YAML files define the canonical game name and a two- or three-character uppercase display code such as `DF`, `VAL`, or `BF6`.

---

Working titles and generated Share/Project Export filename bodies default to lowercase, including structured fields and mainline. Game codes remain uppercase. Settings → General → “Lowercase working titles and generated filenames” is enabled by default; disabling it restores stored capitalization. Changes refresh visible titles immediately and apply to subsequent output operations. Stored metadata and free-form text remain unchanged. Explicit custom filenames, original-filename fallbacks, source extensions, and UI tag prefixes retain casing. Filename selection/order, sanitization and collision suffixes remain unchanged; UI ` | ` separators remain spaces in generated filenames.

## 3. Storage Conventions

All application-managed files and persistent state stay inside the DFSorter project/application directory. Do not use AppData or another per-user system directory.

Windows distribution uses a portable release ZIP. The extracted directory contains the executable, bundled playback and media tools, resources, default game definitions, active `configs/games/`, `data/`, `cache/`, and update backups. A packaged copy requires no separately installed Python, Git, FFmpeg, or 7-Zip. Updates preserve `data/`, `configs/`, and `cache/`. At startup, game definitions merge against the previous shipped defaults kept in `data/default-games/`. Distinct local and incoming changes are combined; when both change the same setting, the local value is kept and a conflict is reported. An older install without previous default files preserves edited definitions on its first update and offers incoming copies under `configs/default-updates/`. Skipped conflicts appear in a startup dialog and in `configs/default-updates/merge-conflicts.txt`.

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

After a successful scan of an enabled capture folder, a missing source with no saved clip metadata or project membership is removed from the catalogue. Game assignment and cached media information alone do not protect it. Clips with saved metadata or project membership remain unavailable until the source returns, is migrated, or the catalogue entry is explicitly purged. A Session reference alone does not protect an otherwise empty clip.

Removing a capture folder requires explicit confirmation and removes its catalogue entries, cached media information, and project/session references. Save a database backup first. Original source files are never deleted. Pause scanning is the reversible alternative that retains the folder and its clips.

On Home, right-clicking a capture folder selects it and opens a context menu containing Pause scanning (enabled folders) or Resume scanning (paused folders), Relink folder…, and Remove folder…. Disable these actions during background operations. Empty list space and unlinked catalogue entries have no folder context menu.

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

### Helldivers 2

- `faction`: Illuminate (`squid`, `squids`), Terminids (`bugs`), or Automatons (`bots`).
- `difficulty`: numeric enum values 1 through 10, accepting the `diff` prefix.
- Global ratings remain available. Faction and difficulty are suggested review fields.
- Working titles use faction, difficulty and mainline; the engine's universal kill field is omitted from the title order.

### Wardogs

- `kill` is the only structured metadata field; global ratings remain available.
- Working titles use kill and mainline, with no suggested review fields.

These examples are defaults rather than a hard-coded universal schema. Game-specific fields are driven by YAML configuration.

---

## 7. Game-Specific YAML Configurations

One YAML file is stored per supported game under `configs/games/`.

Each config should define at least:

- canonical game name;
- two- or three-character uppercase display code;
- accepted aliases for identifying the game;
- game-specific field definitions;
- aliases/shorthand for structured field values;
- optional aliases for field prefixes;
- `display_order`;
- optional `suggested_fields`.

An optional `command_example` string supplies the command bar's muted placeholder for that game when the input is empty. Update it when switching clips, reassigning games or reloading configurations; never insert it as command text. Unknown games or configurations without an example use a generic metadata hint.

The canonical game name is the authoritative identity. The filename should normally match it for readability but is not the sole source of truth.

### 7.1 Field Types

Game-defined fields use a deliberately small field model.

Supported ordinary field types are:

- `enum`: value must resolve to one of the configured canonical values or aliases.
- `freeform`: value is user-supplied text and does not need to exist in a predefined vocabulary.

Freeform fields may also declare optional canonical `values` and value `aliases` for
commands without a field prefix. These named shortcuts do not restrict arbitrary
prefixed input; aliases must target a configured canonical value.
Canonical values and value aliases must not coincide case-insensitively with field
names, field prefixes, or global clip field names within the same game configuration.
Validate this on configuration load, reload, and Save, for both enum and freeform fields.

Any ordinary field may additionally specify:

- `multiple: false` for a scalar value;
- `multiple: true` for an ordered list of values.
- value-specific `links` that infer values for other game-defined structured fields.

Link source and target values use canonical configured values. Links may chain, but cycles are
invalid. Explicit values in the same command and existing populated target fields take precedence.
Competing links that infer different values for the same empty target reject the command atomically.
For example, VALORANT's `Headhunter` and `Tour de Force` weapon values infer `agent: Chamber`.

This is sufficient for the intended initial game schemas. Do not build a general-purpose schema language without a concrete need.

### 7.2 Reserved Engine Fields

The following concepts have application-level parsing logic:

- `kill`: written as `XK`/`Xk`, such as `4K`.
- `clutch`: written as `1vX`, such as `1v4`, when the current game declares a clutch field.
- `rating`: written as `R1` through `R5`, case-insensitive, and available for every game.

`R1` through `R6` are reserved for rating syntax. `R6` is invalid because ratings stop at five. Other `R` followed by a number tokens, such as Delta Force's `R93`, resolve as game metadata when configured; otherwise they are unknown metadata.

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

A prefixed free-form assignment consumes its value until another recognized field assignment, reserved structured token, configured enum value or alias (including a multiword phrase beginning at the next token), or `--` separator begins. A quoted free-form value remains whole even when it contains enum-like words. Repeating the same prefix may provide multiple values when the field is configured with `multiple: true`.

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

The game's display code is displayed as a prefix where the UI calls for it, for example:

```text
VAL_1v4 3K Killjoy Ascent Vandal clutch of the century
```

`mainline` is visually emphasized in the Editing UI. It remains ordinary text in filenames.

### 7.6 Suggested Fields and Export Minimum

Each game config may declare fields worth filling in during review. Missing suggestions show amber `!` markers but do not block Keep + Next or Project Export.

Example:

```yaml
suggested_fields:
  - agent
  - weapon
```

Keep + Next and Project Export require a configured game and at least one populated structured metadata field or `mainline`. Rating, tag and description do not meet this minimum. Older `required_for_export` keys are interpreted as suggestions for compatibility.

### 7.7 Configuration Changes and Existing Data

Removing a field from a YAML config stops that field from being shown or accepted for new input, but must not destroy values already stored for existing clips.

Re-adding a field using the same stable field key restores access to the stored values.

The exact SQLite representation of dynamic game fields is an implementation detail. The storage design must support YAML field changes without destructive schema behavior.

---

## 8. Media Playback and In/Out Markers

Initial required playback support includes MP4 clips containing H.264 or AV1 video. AV1-in-MP4 must work without requiring the user to install an unrelated codec pack manually.

Browse, Editing, and Export use application-local libmpv playback. All audio tracks play together by default, including microphone tracks. Mix tracks channel-wise into stereo, preserving left/right separation and relative track timing; mono contributes to both channels. Silent sources remain silent. Playback never creates derived media or changes source files. Project Export retains original bytes and separate audio tracks; Share produces mixed stereo AAC.

The embedded native video surface follows libmpv's display-corrected source dimensions and
fits within the available player region without cropping or stretching. This prevents libmpv
from adding black letterbox or pillarbox pixels around landscape, portrait, square or other
source aspect ratios. Unused player space shows the application canvas. Black pixels encoded
in the source remain part of the video and are not detected or cropped.

The Editing player includes:

- embedded video playback;
- progress/seek bar;
- play/pause controls;
- volume slider, shared across Browse, Editing and Export and persisted across application restarts; volume changes and stored values use 1% increments;
- mute button;
- temporary 3x fast-forward while holding Space when a text-editing control is not consuming the key;
- visible first frame when a clip is loaded rather than an unnecessary black player surface.

Each clip may store one optional non-destructive In/Out range.

- `I` sets the In point when text input does not own the key.
- `O` sets the Out point when text input does not own the key. Set either endpoint first. For an existing saved pair, changing one endpoint reuses its saved partner when the resulting range is valid.
- The range is stored as source-relative time and shown on the player's progress display.
- Opening a clip in any panel places the paused playhead at its saved In point when `0 <= In < Out <= duration`; otherwise it starts 40 seconds before the end by default, clamped to zero for shorter clips. Settings → General allows disabling this behavior (start at zero) and configuring the offset from 1 to 999 seconds; its visible chevron steppers adjust the value in 5-second increments. Older saved offsets above 999 seconds are clamped to 999. An optional separate mode replaces the unified controls with independent enable and offset controls for Browse, Editing and Export. Switching modes preserves each mode's values; on first use, separate values inherit the unified values. Preferences persist across restarts and apply on the next clip load. Apply the position as soon as media loading permits seeking.
- Pending In and Out points are shown distinctly on the timeline. Commit a pair only when both endpoints are present and In precedes Out; otherwise preserve the last valid stored range. Repeatedly setting either endpoint updates that pending point.
- An incomplete or invalid pending range blocks switching clips through list selection, previous/next controls, arrow shortcuts, Next pending, verdict-and-advance and Add to project + Next. Block panel changes, session creation/replacement and ending the session as well, before changing verdicts, project membership or session state. Explain which endpoint needs correction and offer Clear range through the existing control. A blocked mouse selection restores the current clip selection. Completing the pair or clearing the range releases the block; explicit metadata reset also clears pending markers.
- In/Out points never trim or rewrite the source video.
- Project Export copies whole videos without exporting In/Out metadata.

---

## 9. Global UI

### 9.1 Theme

Use the application-wide semantic design system in [UI Layout Guide](ui-layout-guide.md).
DFSorter provides System, Light and Dark appearance modes. Light is the default when no
preference has been saved. System follows the operating-system color scheme while retaining
DFSorter's own semantic palette rather than adopting unrelated native component styling.

The selected mode persists across restarts. A theme control in the top-right application
toolbar switches immediately between explicit Light and Dark modes. When the saved mode is
System, the quick toggle selects the explicit mode opposite the currently resolved system
appearance. Settings provides all three choices under Appearance.

Page and clip transitions keep the native video surface hidden until the surrounding controls are prepared and the first frame is ready (or loading fails). Page changes reveal the prepared page and video together. Within Browse and Editing, clip changes cover only the clip details/player area (and Editing command area); the library and navigation remain visible and usable. Reveal the new details and video together. Within Export, clip and Assigned / Available changes cover only the video surface while loading; project selection, readiness, titles, membership controls, library and navigation remain visible and usable. Clip selection must not rebuild the library or unrelated controls or restart an already selected clip. The first time each applicable navigation page opens, place the selected clip at the top when it is the first clip. Otherwise, show only the bottom third of the immediately preceding card above it. Successfully creating or replacing a Session re-arms this one-time placement for Editing so the first queued clip receives it; ordinary Resume Session entries preserve the Editing viewport. Later mouse selection, keyboard navigation, library rebuilds, page returns and window resizes do not reapply this prescribed placement. When cards exist beyond a visible list edge, overlay a non-interactive 16 px gradient that fades from the list background at that edge to transparent toward the content. The gradient consumes no layout space and disappears completely at the corresponding scroll boundary; do not add chevrons or borders. Necessary library rebuilds retain surviving selections and the viewport anchor where possible when no clip is selected. User-initiated library sorting and filtering select only the first visible clip and scroll to the start of the list. Show a quiet Loading… indicator only when the transition lasts longer than 1000 ms. Media errors and missing sources reveal the details with an error instead of leaving them covered; a preview that has not produced a frame within 15 seconds stops waiting and offers retry through Play. Stale transition callbacks must not reveal a newer page prematurely.

### 9.2 Settings and Actions

The settings menu also contains Check for updates… after Settings…. This manual action is available in portable releases; it checks the latest stable public GitHub Release, asks before downloading, closes the app, applies the update through a separate helper, and reopens it. Failed replacement restores the previous application files and retains the state backup. Each portable-app launch also checks once after UI initialization, without a progress dialog. The automatic check stays quiet when the copy is current or the check fails; a newer release prompts for download and installation. Development copies do not check automatically.

There is no menu bar. The navigation strip is the top application control row. Its right-aligned settings cog opens a menu containing Settings…, Capture folders…, Reset clip metadata…, Edit tag…, Delete rejected originals…, Manage unavailable clips…, Reset window and panes, and Exit. Undo and Redo icon buttons sit at the right with 4 px between them; retain Ctrl+Z, Ctrl+Shift+Z and Ctrl+Q, with text inputs retaining native undo/redo behavior. Existing page controls provide projects, capture folders, sharing, export, configuration and playback actions. Undo, Redo, Theme and Settings use matching 28 px heights and one vertical centerline with frameless styling. Retain the shared optical 1 px downward icon offset on icon-only utilities. Settings changes save immediately. While the Settings dialog is open, main-window controls ignore input, but an operating-system close request closes the dialog and shuts down the main window through its normal close handling.

Resetting clip metadata must never modify or delete the source video. Destructive catalogue operations retain explicit confirmation.

### 9.3 Panel Navigation

At the top of the window, provide a restrained six-destination navigation strip with compact desktop-style tabs and a teal active bottom indicator:

1. Home
2. Browse
3. Session
4. Editing
5. Export
6. Config

The panel-navigation row and settings cog are present on every panel except during Browse player fullscreen.

### 9.4 Pane Layout

All pages use a two-column library-and-content composition. The library starts at roughly 30% of the normal window width and remains resizable; recovered width and window growth go to the main content. Widths are retained during the run, not across restarts. Reset Layout restores a normal 1400 × 918 window and the default library width. There is no right Projects pane, hanging tab, activation UI, maximized visibility override, or Session forced-open behavior.

| Panel | Left pane | Main area | Command bar |
| --- | --- | --- | --- |
| Home | Library reference | Capture-folder management | Hidden |
| Browse | Library, search and filters | Preview, source context and Share | Hidden |
| Session | Pending candidates with search/filter/sort | Session creation and status | Hidden |
| Editing | Frozen Session queue or single clip | Video, metadata, compact project membership and review controls | Visible |
| Export | Assigned / Available, independent filters and membership actions | Project management, readiness, preview and Export setup access | Hidden |
| Config | Game list | Game-config editor and validation | Hidden |

Home, Browse and Session share a compact filter row containing **Clips**, **Games**, and **Projects** menu buttons. Each menu supports checkbox multi-selection and an all-items action. The Clips button shows the selected verdict names in menu order, or **Clips: all** / **Clips: none** for those states, and grows to fit its label. Clips defaults to Pending + Keep so discarded clips are hidden. Games includes **Uncategorized**. The Games and Projects buttons show counts of selected options, including Uncategorized in the Games count. The Projects menu offers **All clips**, including clips without project memberships, as an exclusive alternative to one or more named projects. Selecting a named project clears All clips; selecting All clips clears named project checkboxes. Selecting every named project still filters to their combined memberships. Deselecting the last selected project, or removing the last selected project from the available options, automatically restores All clips. Projects remains clickable when no projects exist and shows **All clips** selected plus a disabled **No projects** message. Other clip filters still apply. Filter selections stay in effect across panel changes for the current run but are not persisted across restarts. Export filters are independent, with separate current-run state per project and per view. Frozen Sessions and saved project memberships are never changed by filtering.

### 9.5 Left-Pane Library

The general library view supports:

- free-text search;
- structured query expressions;
- capture-time sorting, oldest or newest first;
- clip-state checkbox filters;
- game checkbox filters;
- project membership checkbox filters where relevant.

Library views support multi-selection outside Editing; Editing uses single selection. Frozen Session ordering and stable-boundary refresh follow §12.2.

Every metadata-style left-pane clip list shows `Game · R# · Capture folder` on the second line when rated and `Game · Capture folder` when unrated, with a bold theme-aware `R1`–`R5` label. Use the capture folder's final path component, or `Unlinked` for retained clips without a registered folder. Keep, Discard and Pending are represented only by the colored status dot at the left of the line. This applies to Home, Session, Editing and Export. Browse retains capture time and folder on that line. The explicit rating text remains present independently of color.

Home and Session place a compact relative capture-time label at the right of each clip row and center the verdict dot beside the two-line text block. The time updates while either pane remains open, without rebuilding or moving the list. These rows have no trailing overflow action.

The search bar does **not** expose raw SQL.

Examples of structured queries include:

```text
game:VALORANT agent:Jett
triage:keep kill:>=4
clutch:>=3 weapon:Vandal
tag:LOW_FPS
```

Plain terms search human-facing text such as source filename, `mainline`, and `description`.

Search/filter parsing is case-insensitive and resolves canonical aliases using the current game configuration where applicable. Home, Session and Browse search update on every text change. Invalid or incomplete structured expressions show the inline error while retaining the last valid result list. Plain terms match the source filename, tag, complete displayed working title (game-code prefix, structured metadata and mainline), and description. `rating:4` and `r4` match only clips rated R4. The `rating:` form also supports `=`, `>`, `<`, `>=`, and `<=` comparisons, such as `rating:>=4`; the `r4` shorthand is exact only. Rating values and comparison thresholds must be 1 through 5. Rating terms can be combined with other search terms and never match unrated clips. Missing or out-of-range values are invalid. The `r6` shorthand is invalid; `r7` and higher are ordinary search terms.

Rating remains an editorial reference and optional export-grouping value; rating searches do not change triage or clip order.

---

## 10. Home Panel

Home owns capture-folder management. The settings cog retains its action menu: **Capture folders…** opens Home, while **Settings…** opens the General/Appearance dialog (General selected initially).

Show a folder list with readable scanning state, clip/game counts, the total logical size in GB of all regular files recursively inside each capture folder, and the size in GB of newly discovered clips since application launch. Use the same since-launch baseline as the new clip counts. The controls are **Add folder…**, **Game configs…**, **Rescan**, and a text-only **More…** menu, in that order. Game configs… opens the Config panel. More contains selected-folder **Pause scanning / Resume scanning** and the advanced global **Rebuild media information…** action. **Relink folder…** and **Remove folder…** are available from the selected folder's context menu. Disable selected-folder actions without a valid selection. No capture-folder controls are duplicated in Settings. Hide the inactive command bar on Home.

Legacy clips whose folders were previously unregistered appear as an **Unlinked catalogue clips** row with a count and source-directory tooltip. Its More menu offers **Remove saved entries…**, with the same explicit confirmation and backup as folder removal. Revalidate that reviewed clips are still unlinked before removing them.

---

### 10.1 Browse Panel

Browse alone shows a cached still thumbnail before each card's title. Decode near one second, use an earlier point for subsecond clips, and fall back to the first frame if needed. Generate a 168 × 96 letterboxed still for an 84 × 48 display. Request only visible cards and about one screen around them, with at most two extraction jobs at once. Cache disposable results under `cache/thumbnails` using clip ID and source path, size and modification time; bound memory use. Missing or undecodable sources show a neutral placeholder. Source changes allow failed extraction to be retried. Stale background results must not alter a newly filtered or selected list, and extraction must not block browsing or rescanning.

Only Browse provides player fullscreen. Its transport-row Fullscreen button, F or F11 toggles fullscreen; Esc exits. Plain F does not trigger while editing text. In fullscreen, [ and ] select the previous and next visible clips without wrapping, and Up and Down move volume to the next higher or lower 5% mark; outside fullscreen, Browse Up and Down navigate clips. Hide navigation, library, status bar, below-video titles and Share form. Show the current working title in a compact, near-white top overlay. Anchor the timeline and the existing playback/range controls in a dark bottom overlay, with transport, mute and time clustered left and I/O, Edit clip, Share and Fullscreen clustered right. Fullscreen Share exits fullscreen and focuses the existing Share form. Both overlays appear on entry, mouse motion, playback toggles, progress changes and control interaction, then fade together after 2.5 seconds of inactivity even while paused. Up and Down do not reveal the overlays. Clicking the video or pressing Space toggles playback; clicks on controls perform only their own actions. Playback toggles and volume keys briefly show a large centered icon on a translucent dark circle, which fades out. Preserve the loaded clip, playback position/state and temporary range. Restore prior window geometry, normal/maximized state and pane sizes on exit; entering and leaving fullscreen reveal only the settled layout and video, without intermediate reshuffles. Leaving Browse exits fullscreen. Editing and Export have no fullscreen action.

Fullscreen Left and Right seeks show centered rewind and fast-forward icons with the same brief fade as playback feedback. While paused in fullscreen, comma and period step backward and forward by one source frame per key press, including repeated presses when held, and leave playback paused. They have no effect while playing or outside fullscreen. Fullscreen Up and Down volume feedback also shows the current percentage centered about one fifth of the way down the video. The percentage appears on a lightly translucent square and fades with the volume icon.

Browse follows Home in navigation; Home remains the startup and capture-folder page. Browse is a session-free, read-only viewer of the main library, including clips from paused capture folders. It never changes catalogue metadata, saved I/O, projects, sessions, or catalogue undo history. Startup scanning remains independent.

Browse's only catalogue-editing exception is **Edit clip…**. A pencil action sits after Clear range and before Fullscreen, is disabled without a loaded clip, and enters the transient single-clip Editing mode defined in §13.9. Browse remains read-only until that explicit transition.

Browse library cards show relative capture time (for example, "1 minute ago", "Yesterday", or "2 days ago") and capture-folder name, without clip-state text. Relative labels update while Browse remains open; the exact local capture datetime remains in the card tooltip. The shared filter row sits beneath search. Each entry into Browse resets sorting to newest capture first. Select the newest matching clip across the library unless the user manually selected another Browse clip during the current application run; restore that selection when it still matches Browse filters and is visible. If that clip is no longer visible, select the newest matching clip. Remember manual Browse selection only for the current run, independently of Editing Session selection, and scroll the selected card into view. A compact date-order icon at the right of the filter row toggles newest/oldest. Use media capture time with filesystem creation-time fallback and source-path tie-breaking. Previous/next and Up/Down follow visible order without wrapping. Sorting and filtering, including search and availability changes, select the first result. Empty results clear the player.

Show only working title and filename below the player, followed by an always-visible Share panel. Browse working titles use the same font, sizes, and rich-text styling as Editing, with a square red trash icon to the right for Delete source…. The output folder input has a fixed width of 480 px. Put output folder, its picker, and the 140 px Share mode selector on one row. Size the custom title input to that entire row so its right edge aligns with the Share selector. Separate titles from the form with a subtle horizontal divider; retain a 10 px gap before the I/O status. Use shared grid columns to align input edges. Hide editing metadata, command/session controls and Projects. Disable catalogue undo/redo and mutating settings actions in Browse; text fields retain normal undo/redo. Keep transport, seeking, volume, mute, hold-Space fast-forward and I/O shortcuts, without consuming text-field typing.

Initialize temporary I/O from saved markers. Either endpoint may be changed first, and Clear range affects only the preview. A complete range within the duration enables selected-range sharing; incomplete/invalid markers still allow whole-clip sharing. Discard temporary markers and custom title freely when leaving the clip or page, including incomplete ranges. Sorting or refreshing the same selected clip preserves them.

Inline Share contains a required custom title, output folder/picker, whole/selected-range selector, timing summary and Share action. Default to a valid selected range, otherwise whole clip. No generated-name field or game-prefix controls. Whitespace-only titles disable Share. Reuse existing Share encoding, filename sanitization, collision avoidance, destination restrictions, cancellation and cleanup; pass a snapshot of temporary markers without saving them. Remember the output folder in application settings. Missing sources are hidden by default in Home and Browse. A compact availability icon immediately left of sorting shows or hides them, persists this preference across sessions, and defaults to hidden. Successfully explicitly deleted sources remain hidden from Browse regardless of this preference. Store deletion visibility separately from clip metadata, keyed by stable clip ID. Keep hidden clips eligible for migration/relinking with all metadata and project/session references intact. Clear the deletion marker when the current source path exists again, including after relinking; failed or cancelled deletions never hide a clip. Browse also offers Delete source… for the selected clip regardless of clip state, with explicit permanent-deletion confirmation defaulting to Cancel. Reuse source identity and file-change checks; retain catalogue records and project/session references as unavailable without changing triage.

## 11. Media ingestion and scanning

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
throttled during each phase. Startup/manual scan controls remain modal until cleanup finishes; refresh views
once after applying results. Log traversal, inspection and database timings separately,
plus UI refresh time and cache/probe counts. Migration and purge invalidate affected
cache entries; missing sources with saved information retain catalogue records. Source files are never modified.
No hashing or filesystem watchers are introduced. Replacements preserving both
size and mtime require explicit reinspection.

The import workflow is managed from Home and discovers source media while adding or maintaining references in the catalogue.

Capture folders are persisted across application runs. Successful scheduled or focus-triggered scans do not post status-bar messages; failures still do.

On each application startup, automatically rescan all enabled capture folders once, after the UI is initialized, using the existing cancellable background scan. Disabled folders remain excluded. Preserve existing clip identities, metadata, protected missing-source entries and surviving Session membership/order. Report folder errors without preventing other folders from being scanned. With no enabled folders, do nothing. Manual Refresh/Rescan remains available. Additionally, request quiet incremental scans every 30 seconds and when the application regains focus. Coalesce requests and defer while another background operation or modal dialog is active; retry after it finishes. Quiet scans use the same inspection cache and enabled-folder rules without modal progress or error dialogs. Report failures in the status bar. Preserve selection, viewport anchor, playback, temporary Browse fields and surviving Session membership/order when refreshing results.

Closing the application during a background operation requests cancellation and closes the window automatically after the worker stops. When Share or Project Export jobs are queued or running, first confirm that exiting will cancel them; declining keeps the application open. Confirmed exit cancels queued jobs, waits for running jobs to clean up, then closes. Do not restart automatic scans or show scan results while closure is pending.

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
- total capture-folder size and newly discovered clip size in GB;
- manual Rescan;
- Add Folder;
- Remove folder… from the folder context menu;
- Relink folder… from the folder context menu.

After inspecting a selected folder, show a preview before confirmation with the number of videos per detected game, unclassified videos, and media inspection warnings. Explain that game names are detected from the selected folder and its subfolders. Only when the scan contains unclassified videos, show an optional assignment of those unidentified videos to one game during import. Keep recognized game assignments; later scans use nearest-ancestor classification. The preview also points to Game configs… on Home for adding more games.
The preview permits changing the selected folder with Edit folder…. A completed selection restarts inspection and the preview, including when the same folder is chosen.
When the selected folder's name resolves to a game, show a highlighted tip suggesting the parent recordings folder for including sibling game folders.

### 11.3 Missing Files and Folder Migration

A temporarily disconnected or untraversable capture folder does not trigger catalogue cleanup. Only a completed scan of an available capture folder removes missing clips without saved metadata or project membership. Scanning excludes records marked as explicitly deleted through DFSorter. Automatically detected game and media information do not count as saved metadata. The Home folder row shows a separate red per-game count of entries removed since launch; new and deleted counts are never netted.

Settings → Manage unavailable clips… opens a scrollable review of catalogue clips whose original files are missing or unreachable, grouped by each clip's immediate original parent folder. Each folder row shows Do nothing, Delete…, and Reassociate…; a second row shows clip count, verdict and game composition, known cached capture-date range, and known cached logical size with coverage. Do nothing dismisses the row for the current window only. Delete confirms the removal of only the currently unavailable records in that row, including their metadata and references, after a catalogue backup; source files are never deleted. Reassociate selects a replacement for that row's immediate folder and matches filenames directly inside it, rejecting known cached size mismatches. Preview matched, absent, and mismatched clips before applying. Apply only matched clips, preserve their metadata and project/session references, and leave unmatched paths unchanged. Register or reuse the destination for future scans without changing paths of already available clips.

Source disappearance must never automatically remove clips with saved metadata or project membership.

Relink folder… updates source paths while retaining stable clip IDs and all metadata/project/session references; it never moves files. Before confirmation, validate the destination and source-identity collisions and show the destination, affected clip count, files found and files that will become unavailable. Invalidate affected inspection caches after relinking.

Remove folder… uses one confirmation that shows the folder, clip count, affected project/session counts and full paths in expandable details. Cancel is the default; **Remove from catalogue** is the destructive action. Save a timestamped SQLite backup under `data/backups/` first, then remove the folder, clips, inspection cache and project/session references in one transaction. Preserve the current session clip if it survives; otherwise select the next surviving clip, or the last survivor, or clear the empty session. Clear obsolete undo/redo history. Source videos are never deleted. The separate Purge button is removed.

Pause scanning retains all catalogue data and existing sessions, skips startup/manual scans, and excludes the folder from new sessions. Resume scanning restores eligibility for subsequent scans and new sessions; it does not move files or reset metadata.

---

## 12. Session Panel

Above Session setup, show a library overview of the current Keep, Discard and Pending states for all retained catalogue clips. Include an aggregate All games row plus represented games and Uncategorized, ordered by total clip count descending with Uncategorized last. Each row shows total and processed counts, processed percentage, exact verdict counts, the logical size in GB of available source files represented by that row and selected period, and a stacked Keep/Discard/Pending bar using the shared semantic colors. The aggregate bar fills the available width; each game bar's length is proportional to its total clips relative to All games in the selected period, while its colors show verdict proportions within that game. Nonzero game bars remain visible at a minimum of three logical pixels. The overview is informational and does not change Session library filters.

Provide rolling capture-date filters for 7 days, 30 days, 3 months, 6 months, 1 year and All time, defaulting to All time without persistence. Use cached media creation time, then filesystem creation time for an available source. Exclude missing or unreachable source files in every period and disclose their count separately from available files without a usable capture date. All time includes available undated clips; finite ranges exclude them and disclose their count. Include available explicitly deleted, unlinked and paused-folder catalogue records. Hide zero-count game rows and show an empty-period message when needed.

Ordinary Editing-panel triage is performed within one persisted Session. The explicit single-clip Editing mode in §13.9 is the only exception and never creates, replaces, advances, or ends a Session.

DFSorter maintains at most one Session at a time. Creating a replacement while one already exists must explicitly end/replace the existing Session. Ending a Session deletes only Session state and never changes clip metadata.

A Session freezes:

- the ordered list of clip IDs;
- the current index/progress position.

A Session does **not** snapshot clip metadata. Metadata remains live and editable.

### 12.1 Creating a Session

The Session panel shows the eligible library with normal search, filters, sorting, and selection. Clips associated with disabled capture folders cannot enter new Sessions through Selected, First N or All. Re-enabling restores eligibility. Existing frozen Sessions and project memberships remain unchanged. Clips retained after removing a folder remain eligible.

A new Session contains pending clips only and may be created from:

- the currently selected clips;
- the first `N` clips from the current filtered/sorted result;
- all clips from the current filtered/sorted result.

The resulting ordered clip-ID list is frozen when the Session is created.

Selected ignores selected decided clips; First N counts pending clips before applying N; All includes all pending clips in the current filtered/sorted result. If the requested scope contains no pending clips, do not replace the active Session and report that no pending clips are available. Existing frozen Sessions retain clips after verdicts are assigned.

By default, order follows the library's current sort. A common triage workflow is untriaged clips sorted oldest first.

Once locked, Session membership and ordering do not change because metadata or search results change.

### 12.2 Session Progress

The Session stores the current clip index across application restarts.

While Editing, the left pane shows only Session clips in the frozen order and does not expose sorting or filters. An Editing-only header above the clip list shows **Session clips**, the current numeric position such as **17 / 50**, and a compact icon-only **Next pending clip** button on the right, with a downward navigation icon and an explanatory tooltip. It jumps to the next pending clip later in frozen Session order without changing metadata or verdicts, preserving drafts. It does not wrap; if none exists ahead, it stays on the current clip and reports that fact.

After the final clip in frozen Session order receives a Keep or Discard verdict, if any Session clips remain pending, the Next pending clip button shows a slowly pulsating red outline. Keep this reminder while earlier pending clips are reviewed; remove it when no clips remain pending or the final clip's verdict is cleared. The reminder does not change navigation behavior.

A completed Session remains active for review. Ending a completed Session clears it immediately without confirmation. Ending a Session with pending clips retains confirmation. After ending, open Session and select Pending in the shared Clips filter; later manual filter choices persist normally.

The Session view should display progress and the proportions/counts of:

- Keep;
- Discard;
- Pending.

Clip metadata in the Session list may be refreshed only at stable interaction boundaries such as explicit clip navigation or panel navigation, rather than continuously while the user is typing, to avoid distracting list movement.

---

## 13. Editing Panel

The Editing navigation panel is disabled until a Session exists. **Edit clip…** may still open the Editing workspace for one atomic clip without a Session.

The Editing layout provides:

- Session queue on the left;
- player and clip information in the center;
- collapsible projects on the right, following the normal/maximized visibility rules;
- command bar at the bottom of the center pane, allowing the left clip list to use the full pane height.
- a compact footer below the Editing clip list leads with decided progress `(Kept + Rejected)/Total`, followed by rejected count in parentheses, for example `38/50 (5 rejected)`. Skipped pending clips do not count as decided. While the final-clip pending reminder is active, append a middle dot and red pending text, for example `38/50 (5 rejected) · 12 still pending`. Count pending verdicts even when sources are unavailable. Update immediately after verdict changes and undo/redo. Hide empty list-error messages so they reserve no vertical space.

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

The `mainline` portion is visually emphasized in the UI. Triage selection reflects stored metadata after edits, navigation and undo/redo.

Use a prominent working title, muted structured metadata and source details, a compact five-star control with hover preview and a clear action, and secondary description text shown only when populated; descriptions are entered through the command bar. The tag appears only when populated, as a bold bright-yellow bracketed prefix, 1 px smaller than the surrounding title, before the game-code title in clip cards and before the Editing working title (including filename fallbacks). There is no dedicated tag textbox. Commands or **Settings cog → Edit tag…** add, change, or clear it. Escape rich text, retain title elision and full tooltips; generated Share/Export filenames do not include this UI prefix. Unset ratings show red empty star outlines with no background highlight; hover previews remain gold and selecting a rating removes the red treatment. Ratings remain optional, never zero.

For a `3rd` tag (case-insensitive), underline the first word of `mainline` in clip cards and the Editing working title. This is visual-only; generated filenames remain plain.

Description text is secondary and is never automatically appended to the working title. There is no dedicated description editor or Save description button. Set In, Set Out, Clear range and Share icon actions sit on the right of the playback-controls row immediately beneath the video timeline. A vertical divider separates them from the icon-only Add to project + Next action, whose tooltip includes Ctrl+Enter. In/Out state is shown on the timeline without a separate range text display.

Structured field widgets may display the current stored values for direct inspection/editing, but the command line remains the primary high-throughput input mechanism.

Immediately left of Set In and Set Out on the playback-controls row, show a red danger icon and `I/O not set` when exactly one range endpoint is set, or `I/O invalid` for invalid endpoint order. Hide the indicator when neither endpoint is set or the range is valid, while retaining its layout space. When Shift+Enter is blocked, additionally show a red command-area message identifying the missing or invalid endpoint and directing completion or Clear range; clear it once the range is valid or cleared. Retain completion guidance in the indicator tooltip and preserve pending-range navigation safeguards.

### 13.2 Command-Bar Focus and Playback Keys

Entering Editing or changing clips starts review mode with a non-text surface focused.

- Tap Space toggles playback; holding for 200 ms plays at 3× until release, restoring the previous state. While hold-Space fast-forward is active, show a bold `>>>` centered on the existing transport/volume/range-controls row beneath the timeline in both players, with an accent-colored highlight moving left to right every 120 ms. Animate only during the hold; stop and reset the animation when the hold ends. Reserve only its horizontal space when hidden; do not add a separate row or move controls vertically. Release, focus loss and clip/panel changes hide it through the existing hold cancellation. Focus loss cancels the hold.
- Left/Right seek ±5 seconds; Shift+Left/Right seek ±1 second. I/O set markers. Backspace rejects without advancing.
- Ratings use command input (`R1` through `R5`, case-insensitive) followed by Enter, or the clickable stars. There is no review-mode rating key sequence.
- `/` or Enter enters metadata input without inserting text or submitting a retained draft. Slash commands are not supported.
- Unmodified F in Editing review mode maximizes the application window if it is not already maximized. It does not toggle back to normal size. Text input and other panels retain their existing F behavior.
- Every text field consumes normal editing keys, including Space and Backspace when empty, except for the one-shot post-submit Space behavior below.
- Across all pages and application-owned dialogs, clicking outside any text box releases its keyboard focus, including clicks on labels, blank surfaces and non-focusable controls. Apply this to single-line and multiline fields, inline table editors, editable combo boxes and spin-box text inputs, including Browse custom title and output folder fields. Retain text and existing save/validation behavior, and allow the clicked control's normal action. Clicking inside the box or its child controls retains normal editing; popup menus retain their own focus. Page hotkeys become available again when no text field is focused, subject to the existing modal/popup restrictions.
- In the Editing command field, unmodified `=` inserts `-- ` at the beginning of the command (no leading space, one trailing space), or ` -- ` elsewhere at the cursor. At the end of a command with no existing `--` and no selection, trailing spaces are replaced by the separator's single leading space; an otherwise blank command has no leading space. The same expansion applies when `=` triggers the paused-video review-to-input transition. An immediate unmodified Space is suppressed once because the separator already ends in a space; subsequent spaces insert normally. An immediate Backspace (also after the suppressed Space) removes the separator, restoring one trailing space if any were replaced, otherwise none, and cancels Space suppression. Any other intervening key, cursor movement, pointer interaction or focus change cancels both opportunities.
- Enter submits commands only in command-input mode and remains in input on success; invalid commands retain input focus and text. Shift+Enter never submits; it applies verdict-and-advance in review mode or command-input mode when the command bar is completely empty. Escape returns to review preserving the draft.
- Clicking a button or empty space in Editing returns to review mode and removes focus from the command bar while preserving any unsubmitted draft. Clicking the command bar itself keeps input focus; modal dialogs and popup menus retain their own focus.
- Ctrl+Enter in review mode adds the current clip to the review destination and advances one position in frozen Session order regardless of triage. It requires a review destination, preserves triage and drafts, ignores auto-repeat, and stays on the last clip without wrapping. Existing membership is harmless. A visible icon-only **Add to project + Next** button at the bottom right of the Editing player provides the same action and is disabled without a review destination. The Projects checkbox menu edits the current clip membership; Export owns bulk membership changes.
- Unmodified Up/Down in Editing review mode navigates every clip in frozen Session order, including kept/rejected clips, without wrapping. After a successful Enter submission, Up/Down in the still-focused empty command bar performs the same navigation until new draft text is entered or focus leaves the bar. Otherwise text fields retain their normal keys. Preserve drafts and position the destination as specified in §9.1.
- While a usable Editing video is paused, ordinary typing enters command input and inserts the triggering text once at its retained cursor, applying the separator expansion above for unmodified `=`. Existing review/video shortcuts take priority, including F, I/O, Space, arrows, Backspace, / and Enter. Other text fields, menus, dialogs and modifier-only keys are excluded. Settings → General → **Type to enter commands while video is paused** defaults on and persists immediately.
- Command colors indicate validation independently of keyboard mode: neutral when empty or typing an unfinished token, subtle blue for a valid draft, amber bottom border for incomplete syntax, red bottom border for invalid input, and a green bottom border for 1.2 seconds after saving. Retain the cyan focus outline. Defer unknown-token errors until a token is delimited or submission fails; explicit invalid values and conflicts can show immediately. A short hint explains validation and shows “Saved · Space to resume” after a successful submission while paused. In that post-submit state only, the first unmodified Space resumes normal-speed playback and enters review without inserting text; consume its repeats and release. Other non-modifier keys consume the opportunity and behave normally. Mouse interaction, focus loss, playback changes, paste and clip/panel changes cancel it. Failed commands do not arm it. This post-submit behavior is independent of the paused-typing setting.
- Unsubmitted metadata drafts are retained per clip for this run, including across panel changes; they are not persisted on restart.
- A contextual hint and `?` button/shortcut explain review/input keys and the watch, annotate, verdict, advance workflow.

Use native Qt video presentation and prefer hardware decoding, allowing logged software fallback. Coalesce drag seeks to at most 20 Hz using the latest pointer position without rounding to 100 ms intervals; perform the final seek to the release position and restore playback state. Preview and release seeks use the same timestamp precision across Browse, Editing and Export. Exception: after natural media completion, seeking backward resumes playback automatically; dragging previews while held and resumes on release. Apply this recovery in Editing and Export. Ordinary paused seeking remains paused; missing/failed media is not treated as completed playback. The timeline has a 7 px groove, larger hit target, colored markers, saved-range tint, and distinct pending In and Out markers. Put transport/audio/time controls directly beneath it.

### 13.3 Command Syntax

The command bar receives one complete string.

Settings → General → Editing offers **Show ghost expansions for command aliases**, on by default and saved immediately. In the Editing command bar, exact unquoted configured enum aliases, including field-prefixed values, appear as lowercase canonical values when the caret is not touching their raw token. Alias letters matched in order within the canonical value retain the normal input color; inserted letters use muted text. If no complete ordered match exists, the whole expansion is muted. Clicking an expansion moves the caret to the nearest raw alias boundary and collapses it. The editable text, selection, clipboard, undo, draft, history, validation, and submission always use the original typed command. Freeform values and mainline or description text do not expand; recognized aliases may expand even when another token is invalid.

The field checklist beneath it previews saved metadata merged with the current valid command as text changes. Enter is still required to save. Empty commands show saved fields. Incomplete or invalid commands retain a preview of the longest fully parseable prefix merged with saved fields; checklist tooltips distinguish partial previews from complete drafts. Hovering a field shows every configured enum value with its accepted aliases, or the accepted syntax for fields without a fixed list. No incomplete token contributes a value. Previewing must not modify catalogue data, history, titles or the Session list.

The Editing field-marker row also shows a right-aligned cyan tip with an info icon. Generic tips are read from `configs/tips/default.yaml`; game-specific tips are read from separate files in that directory and apply only to the currently selected game. Tip YAML is edited directly and is separate from game command examples. Show a random eligible tip immediately on entering Editing and every 30 seconds while the pane is open. Avoid repeating tips already shown during this application run until the eligible tips are exhausted. A clip or game change leaves the displayed tip and timer unchanged; game eligibility is checked at the next rotation. Returning to Editing selects a new tip immediately. Settings → General → Editing offers **Show rotating Editing tips**, enabled by default, and a **Field markers and tips size** choice of 11, 12 or 13 px, defaulting to 12 px. Show all three size choices as adjacent buttons without a popup. Both settings save immediately; changing size does not rotate the tip.

Fields inferred by YAML links use a cyan `◇` marker while previewing. After submission they use the
normal populated marker. Command history appends smaller muted provenance such as
`(Inferred: Agent = Chamber)` only when a link actually supplied the saved value.

`tag:` is a reserved global prefix for the tag field, available without an assigned game. Use `[LOW_FPS]`, `tag:LOW_FPS` or `tag:"audio issue"`. Bracket syntax accepts one non-empty token without spaces; `[]` and brackets containing spaces are invalid. `tag:""` clears; bare `tag:` is invalid. Conflicting repeated assignments reject the entire command. For a valid tag draft, replace the generic apply hint with `[TAG] Known tag` when it matches any library clip case-insensitively, or `[TAG] New tag` otherwise. Render the bracketed tag bold in primary text; render Known tag as secondary text and New tag in the accent color. Search accepts `tag:` with exact, case-insensitive matching (empty search values remain invalid). Game configurations cannot reuse this prefix. VALORANT accepts `brim` as an input alias for canonical `Brimstone`.

In Editing, valid commands containing unregistered prefixed freeform values offer
`Enter to apply · Tab to add <value> to <game> config`. Append the offer after tag
feedback when present. Offer one value at a time in command order, only while the
command input is focused, with no selection, and the caret is outside the entire
parsed value including its boundaries. Trailing whitespace or moving to another
command segment can make a value eligible. Registered named values and aliases match
case-insensitively and receive no offer. All freeform fields participate; enum fields,
inferred values, mainline and description do not. Invalid or incomplete commands
receive no offer.

Tab starts read-only confirmation: `New <field>: <value> · Tab to finalize · Enter to
cancel`. Tab again atomically saves the named value to the current game's editable
YAML immediately and reloads recognition, without submitting the command or adding
a clip or Config undo step. After a successful save, remove only that occurrence's
field prefix and colon from the command input. Preserve its value, quotes, surrounding
text and whitespace, and adjust the caret by the removed prefix length when needed.
The edit updates the command draft and supports native text undo. Registered named
values also delimit preceding prefixed freeform values, retaining the command's
field assignments after prefix removal. Cancellation and failed saves retain the
original prefix. Preserve YAML comments and unrelated
settings; shipped defaults are unaffected. Existing structured Config history and
revert baselines retain the addition. Unsaved Config edits for that game block
registration with inline feedback. A file changed after confirmation began cannot
be overwritten. Validation or write failures keep confirmation open and show an
inline error; no partial registration is saved.

Enter or Escape during confirmation cancels registration and preserves the command.
Typing, changing selection or caret, losing input focus, application deactivation, or
changing clip, game or page also cancels confirmation. Cancelled values are suppressed
for the rest of the application run, keyed by game, field and case-insensitive value.
Other values remain eligible. Registration keys override their ordinary functions
while applicable and ignore auto-repeat; elsewhere Tab retains focus navigation.
Successful registration reveals the next eligible value. Enter still applies the
command separately. Registrations persist independently of single-clip Save/Revert.

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
- For a non-discarded clip, Shift+Enter requires a configured game and at least one populated structured metadata field or `mainline`. Missing metadata leaves verdict and position unchanged and is explained inline. A legal action changes triage to `keep`, applies the normal explicitly enabled review auto-add rule and advances. Source availability remains an export requirement.
- An explicitly discarded clip advances while preserving Discard, even with missing fields, no game or an unavailable source. The empty-command-bar requirement still applies.
- After applying the legal verdict, advance to the next clip with pending triage later in frozen Session order, skipping Keep and Discard clips. Do not wrap. If none remains ahead, stay on the current clip and report Session complete only if no Session clips remain pending; otherwise report that earlier clips remain pending. Do not delete or replace the Session. Ignore key auto-repeat for advancement.
- Backspace in review mode marks the current clip `discard`; in every text field, including an empty command bar, it only edits text.
- Backspace does not automatically advance; the user may then use `Shift+Enter` or ordinary navigation to continue.
- Immediately after Backspace rejects a clip in review mode, the next non-modifier Enter also applies verdict-and-advance once. Any other key, mouse action or clip change cancels this opportunity.
- Rating never changes triage.
- Clicking the visible triage controls may also set Keep/Discard/Pending directly. Pending clears the stored verdict.

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

The Editing panel displays the stored rating as a clickable 1-5 star control. The adjacent `x` action and right-click clear the rating. A fully valid command draft containing `R1`–`R5` previews static dull-yellow stars and temporarily replaces `x` with a disabled clock. The stars' tooltip explains rating interactions and keyboard entry; no descriptive meanings are prescribed for individual ratings.

Rating is reference metadata only. It does not automatically Keep, Discard, or prioritize a clip; rating search is supported as described in the search section.

### 13.8 Project membership and review collection

A clip may belong to multiple projects. Immediately after **Change game** on the existing verdict row, Editing provides one **Projects** menu combining current-clip membership and review collection. Left-click checkboxes change current-clip memberships, immediately in ordinary Editing and staged in atomic Editing. Right-clicking a project enables automatic collection of new Keep decisions into that project; right-clicking another project moves the single collection destination. The active project displays a Lucide cycling-arrow icon at the right of its menu row, and the Projects button has a cyan outline. Right-clicking the active project again turns Auto off and removes both indicators while retaining its destination for Add to project + Next. The Menu key on a focused project provides the same collection toggle. Tooltips explain both gestures and the current destination/Auto state. There is no separate destination selector, Auto widget or project-control row.

The review destination persists across restarts, separately from the workspace project. Auto-add starts off on every launch. Deleting the destination clears it and turns Auto off. Collection changes are disabled in atomic Editing; the membership checkboxes remain available for staging.

Auto-add applies only when Editing explicitly changes a non-Keep verdict to Keep and supplies the enabled destination to the catalogue edit. Selecting a project, editing metadata, changing memberships, or opening a Session cannot collect existing Keep clips or backfill a Session. An explicit Keep in atomic Editing may stage collection under the existing review setting. Changing away from Keep never removes membership.

**Add to project + Next** and Ctrl+Enter explicitly add to the review destination and advance one position in frozen Session order without changing verdicts or drafts. They require a destination, ignore auto-repeat, stop at the last clip, and are unavailable in atomic Editing. Project creation, rename and deletion exist exclusively in Export.

### 13.9 Atomic single-clip Editing

Clip cards on Home, Browse, Session and Export expose **Edit clip…** in the shared pointer-targeted context menu. Right-click opens the clicked clip's menu without changing selection, current row, preview or Session position, including when the clicked clip is unselected. Empty list space, Config and Editing have no clip context menu. Home clip selection is visual only: left-click retains the targeted card's selected highlight without loading or otherwise acting on the clip. Double-clicking a Home or Session clip opens that clip in Browse. Atomic Editing retains the originating panel and displays exactly one clip. Its left header reads **Single clip**; Previous, Next and Next pending are disabled; **Add to project + Next** is hidden. Any active Session and its queue/index remain unchanged.

Atomic Editing takes an immutable baseline snapshot of all editable clip fields and project memberships, then stages metadata commands, game, verdict, rating, tag, reset, In/Out range and membership Add/Remove operations in memory. Rendering, validation, title generation, markers, status, project membership and Share use that staged snapshot. Project creation, rename and deletion and permanent source deletion are unavailable. Undo/Redo reverses staged Editing actions in memory, including commands, individual I/O presses and membership changes. Native text-field undo remains available. Saving retains the staged action history for that clip; discarding drops the staged history.

Place atomic-only **Save and return to clip** and red **Revert** actions beside the working title. Save is disabled until the staged snapshot differs from its baseline and remains blocked while command text is unsubmitted or an In/Out range is incomplete or invalid. Save and Shift+Enter preserve the staged verdict, including any explicit Keep, Discard, or Pending change; neither action automatically changes triage or requires Keep/export completeness. Save verifies that the persisted clip identity, editable fields and relevant memberships still match the baseline, then writes the complete staged snapshot and memberships in one transaction, updates modification time once, and adds exactly one catalogue undo operation. A conflict keeps the draft open. A snapshot equal to its baseline performs no write. Shift+Enter in single-clip Editing invokes the same save action from review mode or an empty command bar, ignoring auto-repeat. Replace the rotating cyan tip at the bottom right with a static orange warning icon and text explaining that this is single-clip Editing and Save or Shift+Enter retains the selected verdict. Keep this notice visible even when editing tips are disabled.

Revert opens a destructive **Discard changes / Cancel** confirmation. Confirming discards the entire atomic draft and returns to the originating panel with the edited clip selected and the originating library scroll position restored; Cancel stays in Editing. Clicking another navigation tab opens the same confirmation and, when confirmed, discards the draft before opening the selected tab. Save and Shift+Enter commit and return to the originating panel with the edited clip selected, restoring its library scroll position where the resulting filtered and sorted list permits it. A confirmed navigation exit opens its selected destination. Closing DFSorter silently discards atomic state and its local submitted-command history without a catalogue write or undo entry.

Share may use the staged atomic snapshot without Save. Command text must first be submitted and the range must be complete and valid. Shared files intentionally remain after Revert or Discard. Atomic-only submitted-command history never enters normal runtime clip history. Keep entered during atomic Editing may stage addition to the review destination only when auto-add is enabled, but does not advance a Session.

## 14. Projects

Projects are persistent catalogue records with stable IDs, names, clip memberships and JSON output preferences. A clip may belong to any number of projects. Schema 9 adds an empty-object preferences column to existing projects without changing clip/project IDs, memberships, Sessions, or frozen jobs. A valid legacy `active_project` becomes `review_destination`; the legacy state is retired and automatic collection remains off. Migration and assembly perform no source-file operations.

Export owns the project selector and **More → New project / Rename / Delete**. Creation selects the new project and opens Available. The first selection of an existing project opens Assigned; later visits restore that project's current-run view, filters, selections and viewport. Every explicit Export navigation click opens Available instead when the restored view is Assigned and Assigned's default-filter count is zero. Active filters alone never trigger this fallback; manual selection of empty Assigned remains available, and atomic Editing returns preserve their originating view. Only the last workspace project persists across restarts. Missing projects show the chooser. With no project selected, creation remains available and membership/export actions are disabled. Workspace selection never changes the review destination.

Names retain nonempty-name validation. Delete requires confirmation, removes the project, memberships and preferences, and clears matching workspace/review references. Clips, source files and already-submitted jobs remain. Project management and preferences are outside membership undo.

Batch membership operations freeze the selected or matching IDs and validate all project/clip identities before writing in one transaction. Existing additions and absent removals are harmless no-ops. Any stale identity or database error rolls back the whole batch and refreshes the list with an explanation. Report actual changed/no-op counts and refresh once per batch. Verdicts and metadata never change as a side effect.

## 15. Share

Share is a clip-level action available in Browse, Editing and Export. Project Export remains a whole-original-file copy operation.

It may be invoked from Browse, Editing or Export for the currently previewed clip.

Sharing:

1. selects one source clip;
2. chooses an output folder, with a persistent default share folder available in application settings;
3. chooses either:
   - a generated filename based on the working-title fields selected for that share; or
   - a user-supplied custom filename;
4. chooses the whole clip or its saved valid In/Out range, defaulting to the range when available;
5. creates an H.264 MP4 with one stereo AAC track mixing all audio tracks, or no audio if the source is silent.

Range shares decode and re-encode through the exact source-frame/audio-sample boundaries. Pending In/Out edits do not replace the saved range offered for Share; the dialog explains when it is using the saved pair. Whole SDR H.264 shares copy the video stream without generation loss; other codecs, all range shares, and all HDR shares re-encode, preferring NVIDIA H.264 P5/CQ19 with x264 medium/CRF18 fallback. PQ and HLG sources are tone mapped to tagged BT.709 SDR for Share. Preserve source resolution and frame timing. Share requires FFmpeg and ffprobe and supports background processing, cancellation, temporary output validation, and cleanup on failure.

For a selected range starting after zero, seek at input before decoding, retaining accurate seeking and a common source-relative timestamp basis. Decode the necessary lead-in from the preceding seek point, trim at the exact selected boundaries, and preserve relative audio-track timing and silence before delayed tracks. Whole-clip processing retains its existing stream-copy/re-encoding rules.

Settings → General → Share → Output quality offers **Native resolution** (default) and **Web · 1080p**. Persist the choice immediately in `data/settings.yaml` as `share_quality` (`native` / `web_1080p`); missing or unsupported values use Native. Capture the choice when each Share is submitted in Browse, Editing or Export, so later changes do not affect queued or running jobs. Project Export remains an original-file copy.

Native retains the existing Share rules. Web always re-encodes to H.264 High profile, 8-bit YUV 4:2:0 MP4 with fast-start playback, using NVIDIA P5 VBR with x264 medium bitrate-controlled fallback. Fit the display-corrected video within 1920×1080 landscape or 1080×1920 portrait, preserving aspect ratio and orientation without cropping, stretching or upscaling; use even dimensions and square output pixels. Preserve frame timing through 60 fps, including 29.97 and 59.94. Convert 120 fps to 60 and 120000/1001 fps (approximately 119.88) to 60000/1001 (approximately 59.94); cap other rates above 60 at 60. Target 8 Mbps video through 30 fps (12 Mbps peak, 16 Mbps buffer), or 12 Mbps above 30 fps (18 Mbps peak, 24 Mbps buffer). Unknown source frame rate uses the higher bitrate tier. These are bitrate targets, not fixed output sizes. Retain 192 kbps / 48 kHz mixed stereo AAC or silence, existing HDR-to-BT.709 SDR conversion, range accuracy, cancellation and cleanup. Validate Web output dimensions, H.264 profile, pixel format and frame-rate cap as well as existing stream, color and duration checks.

Share outputs use `.mp4`. Project Export retains the source extension and original bytes.

Media inspection classifies clips tagged PQ (`smpte2084`) or HLG (`arib-std-b67`) as HDR. Library rows show a yellow HDR label after the capture-folder name, and Browse thumbnails are tone mapped to SDR. On Windows, source playback uses libmpv's `gpu-next` renderer with automatic target colorspace hints, allowing display-aware HDR output when the display path supports it. Project Export preserves the original HDR bytes.

Confirmed Shares enter the nonmodal Output Jobs queue. The initiating Share control briefly changes to the success color when submission succeeds. The job freezes the clip, selected range, filename choices, and destination at submission. Output Jobs reports encoding time progress, validation, and saving; it retains completion and errors until dismissed. Share jobs are not resumed across application restarts.

Running Share jobs show an indeterminate bar without a percentage during preparation: “Inspecting source…” during probing, “Starting encoding…” until a positive output timestamp, and “Retrying with software encoding…” during fallback startup. Positive output time restores determinate encoding progress; show “<1%” when that time rounds below 1%. Very short encodes may proceed directly to validation. Queued jobs retain their existing presentation. Validation, saving and completion retain their existing progress allocations. Cancellation remains available during preparation; indeterminate animation stops on failure or cancellation, without inventing a percentage. Project Export uses the preparation and byte-progress model in §16.5.

A clip has at most one queued, running, or cancelling Share job. Its Share controls in Browse, Editing and Export remain disabled with a spinning progress icon and an in-progress label or tooltip until the job completes, fails, or is cancelled. When the visible clip's Share completes successfully, its controls become green, show a checkmark and **Shared** label or tooltip, and remain disabled. This temporary result clears on any clip change or pane change, including a move between Browse, Editing and Export for the same clip. A failed or cancelled Share restores the ordinary controls. A new active output job automatically opens Output Jobs when no output jobs were active immediately before submission or resume. This applies to Share and Project Export, even if earlier results remain listed. Output Jobs automatically opened by a Project Export submission or resume remains open until dismissed; submitting or resuming Export also stops an existing auto-close timer. Share-only automatic openings close after four seconds unless the menu is used; manual openings remain open until dismissed. Each successful Share or Export completion turns the Output Jobs icon outline green until that icon is clicked or activated from the keyboard, even if the dropdown is already open or other jobs remain active. Automatic opening, popup dismissal and job dismissal do not acknowledge completion; later successful completions mark it green again. Only the outline uses success green; the icon and background retain their active/attention styling. Failed and cancelled jobs do not set the completion indicator. This indicator lasts only for the current application run. Output Jobs has a close control.

Filesystem-invalid characters are sanitized only in the copied filename; catalogue text is not altered.

Existing destination files are never overwritten. Name collisions receive a numeric suffix.

The copied file is not added back into DFSorter and is not tracked after the copy completes.

---

## 16. Export Panel and Project Export

Export is the project assembly and output workspace. New project…, Rename… and Delete… live in the project More menu; New project remains available without a selected project. A help icon to the right of More opens a guide covering project choice and collection through Editing auto-add or Available, candidate refinement, removal of exceptions and temporary skips, optional ranges/Share/atomic Editing, final readiness inspection, and project-wide export; it remains available without a selected project. Use the shared clip list beside the existing Export player; project controls and project-wide readiness appear above the player, and Editing-style working title, source filename and **Export…** below it. Direct selection export, dynamic memberships and saved searches remain deferred.

The top view selector contains **Assigned - <project name> (N) / Available (N)** only. Counts use each view's default filters, independent of active search, game/verdict filters, dates, readiness and availability toggles: Assigned counts all saved members, including Pending, Discard and unavailable sources; Available counts source-available Keep nonmembers, excluding temporary skips. Refresh counts with catalogue, membership and skip/history changes; tooltips explain the default-filter basis. Assigned shows the selected project's current name and refreshes after project changes or renaming; without a project, its label is Assigned (0). Available shows catalogue clips that are not saved members, including paused capture folders, independently of Session eligibility. Defaults: Keep, all games, oldest first, no date restriction, unavailable sources hidden. Without a selected project, show the catalogue in Available and disable the view selector and membership actions. There is no separate Available checkbox. Cards retain the quiet, accessible folder/text membership indicator. Available offers **Add selected (N)** and **Skip selected (N)** in a contextual footer below the list. **Add all matching (N)** lives in the list-level **Bulk actions** menu beside the result count. All matching covers the entire filtered result, including offscreen rows; counts reflect actual changes. Without a selection, hide the selected-clip actions; keep Bulk actions available when there are valid matches. Deliberately selected Pending and Discard clips may be added without altering their verdicts.

An icon-only unavailable-source toggle sits beside the view selector, using the shared eye-off / eye icons and descriptive tooltip and accessible name. Its checked state shows unavailable sources; unchecked hides them. The state is independent for each project/view, defaults off in Available and on in Assigned, and remains independent of Browse's unavailable-clips preference.

**Assigned** starts with all members, including Pending, Discard and unavailable clips. It has its own search, game/verdict filters and sorting state. From / Through date bounds are shared with Available for the same project during the current run, including partial and invalid input; other projects retain separate bounds. Readiness categories and Clear filters clear the shared bounds together with conflicting filters. Its contextual list footer contains **Remove selected (N)** only when a selection exists, with **Remove all matching (N)** in the **Bulk actions** menu. **Clear filters** sits beside search and resets readiness and conflicting filters to the complete project; show the active readiness scope nearby and retain its tooltip/accessibility text. Skip is hidden. Removal changes memberships only; all matching includes offscreen members.


**Remove all matching** in Assigned asks for confirmation when the batch would remove more than 20 members (21 or more). The dialog names the removal count and explains that metadata and original files remain unchanged. Declining or dismissing it preserves memberships, selection, preview, viewport and Undo/Redo history. Batches of 20 or fewer, Add all matching, Remove selected and history replay do not trigger this confirmation. A successful Add all matching batch switches to Assigned; a successful Remove all matching batch switches to Available, even when other members remain outside the active filters. Each switch retains the destination view's filters and shared date bounds, clears bulk selection, and uses the normal prepared-preview transition. Canceled, failed and no-change batches remain in the current view. Add selected, Remove selected and Undo/Redo do not switch views.

Temporary candidate skips are in-memory ID masks per project, applied after ordinary Available filtering and never persisted. Skip selected applies only to selected nonmembers with a project and valid filters. Hidden candidates are absent from the list, preview navigation, action counts and Add all matching. Saved members are never hidden: a skipped clip collected through Editing reappears as a member; removing it makes the mask relevant again. Skips change no verdict, metadata, membership, readiness or export manifest. Restart clears masks; project deletion clears masks and histories; catalogue cleanup prunes removed IDs. Readiness **Skipped** continues to mean Discard members. Successful Skip selected feedback reports the latest action count and the current project skip-mask total with singular/plural clip wording, for example `Skipped 1 clip · 3 clips temporarily skipped in this project until restart.` The total reflects current skip state, including Undo/Redo, rather than cumulative clicks.

Search reuses the catalogue query parser, including rating comparisons, metadata aliases, tags and free text. A **Dates** disclosure reveals the optional **From / Through** fields directly to its right on the same row, without increasing toolbar height. Start collapsed, expand when restoring active or invalid bounds, and visibly indicate active bounds while collapsed. Once opened, only the Dates toggle collapses the drawer; changing views, clearing bounds, readiness navigation and control reloads do not retract it. Collapsing never clears filtering. Optional **From / Through** capture dates accept `YYYY-M-D` or `M-D`, with one or two digits for month/day and a four-digit explicit year. Omitted years resolve to the current local calendar year; blank inputs impose no bound. Bounds are inclusive local calendar dates and use existing capture-time resolution. Invalid calendar dates, including non-leap February 29, remain errors. A complete yearless date immediately shows only its inferred year and hyphen as muted ghost text, even while typing; `3-1` shows the year before another digit extends it to `3-13`. Clicking the ghost prefix or placing the cursor at its boundary hides it; moving into the typed date restores it. Raw input, clipboard text, text undo and current-run view state retain only the entered text. Explicit years get no ghost prefix. Date ghosts always appear independently of Editing's ghost setting. Unknown dates remain visible without bounds and are excluded with either bound; disclose their excluded count. Invalid queries, malformed dates and reversed bounds keep the last valid results visible with an inline error and disable membership actions until corrected.

Export selected-clip actions default to **Add selected**, **Skip selected**, and **Remove selected**, with A/S/R identified in their tooltips. Settings → Appearance → Export offers **Nier: Automata Hotkey Labels**, off by default, to render **[A]dd selected**, **[S]kip selected**, and **[R]emove selected** instead. This application preference persists and updates Export labels immediately; other panes are unaffected. Plain A and S act in Available; plain R acts in Assigned. Route through existing enabled actions and pending-range guards; ignore repeats and reserve modified keys for existing shortcuts. Do not intercept text inputs, modal dialogs or open popups. Omit `(1)` for a single selected clip; show `(N)` for multiple selected clips.

Ctrl-click, Shift-click and Ctrl+A operate on the focused shared list. Each view contains only members or only nonmembers. Plain-click starts a new selection; Ctrl-click adds separate rows; Shift-click selects a range; Ctrl+A selects all visible rows. Current row determines preview; selected rows determine bulk actions; saved membership is independent. Preview previous/next traverses visible results without wrapping or clearing bulk selection. A context menu on a selected row preserves multi-selection; **Edit clip…** targets the pointed row. Successful Add selected, Remove selected and Skip selected reset bulk selection and select only the surviving preview; if the preview was removed, choose the next surviving row, then the previous, or clear selection and the player when no rows remain. Successful all-matching batches and Undo/Redo deselect every row and reset selection type while preserving preview and scroll where possible. Successful membership/skip actions and Clear filters return keyboard focus to the clip list before action controls are disabled or hidden, so other buttons do not acquire a focus highlight. When the preview disappears after other actions, choose the next surviving row, then the previous, or clear the player. Filter/sort changes select the first visible row and scroll to the beginning. Atomic Editing returns to the originating workspace project/view and restores surviving state. An Available / Assigned switch prepares the requested preview before replacing the list, retaining the current list and project controls while only the video surface indicates loading. An already prepared clip switches immediately. A new view, clip, project or navigation choice cancels the pending switch; stale loading callbacks cannot apply it.

Export reproduces Editing's right-aligned **Set In**, **Set Out**, **Clear range**, **Share**, vertical divider and **Edit clip…** controls beneath the timeline. I/O shortcuts and previous/next keyboard navigation route to Export; playback, seeking, volume, loading and preloading retain shared behavior. Completed valid range pairs save immediately; incomplete or invalid endpoints remain pending with Editing's warning beside the controls. Complete or clear a pending range before list navigation, project/view/page changes, filtering, affected membership/skip operations, atomic Editing entry or export submission; rejected transitions restore controls and selection. Saved range writes use an expected-range-validated transactional catalogue update of only In/Out, invalidate stale clip-edit histories, never collect or change membership, and stay outside Export Undo/Redo. Share reuses Editing's dialog/output pipeline, saved-range choice and pending-range explanation, concurrency, cancellation, spinner and completed feedback. Edit clip targets the preview and returns through existing atomic Save/Revert behavior. Project Export still copies complete original files; ranges affect preview and Share only. No schema migration is required.

A compact strip of clickable readiness counters always describes the whole project. Emphasize Ready, mute zero counts, and use semibold text, tinted fills and borders in existing warning/error colors for nonzero Pending/Blocked counts; mark the active Assigned category. Categories: **Ready** means Keep passing export validation; **Pending** means no verdict; **Blocked** means invalid Keep; **Skipped** means Discard. Clicking a category opens Assigned with that category and clears conflicting filters. **Clear filters** returns to the complete project. Show blocking reasons on affected cards and compact Pending/Blocked counts above the export dialog footer. **Edit clip…** uses atomic Editing; membership removal remains available here.

**Export…** is available whenever a project is selected, including blocked and empty projects. Its application-owned modal has Destination, Filename format and Folder organization sections, followed by a summary and Cancel / Export actions. Filename fields wrap at natural widths without a surrounding outline or scrolling. Submission requires a destination, at least one Ready member, and no Pending or Blocked members. Show a highlighted **Export unavailable** notice containing “Resolve Pending and Blocked clips before export” and nonzero blocking counts, or an empty-project explanation. Cancel discards setup changes without saving preferences or queuing jobs.

Immediately left of **Export…**, show **N ready · Estimated export: N.NN GB**. Repeat **N clips ready · Estimated size: N.NN GB** in the dialog footer, with nonzero excluded Discard counts beneath it. Both surfaces share the total current original-file size of Ready members. Use binary GB (2³⁰ = 1,073,741,824 bytes), defined in tooltips, and two decimal places. Exclude Pending, Blocked and Discard members. Selection, filters, temporary skips and In/Out ranges do not change the estimate. Refresh with project readiness/membership changes, when opening setup and before submission. An empty project shows 0.00 GB; without a project or if a Ready source size cannot be read, show an em dash and explain it in the tooltip. Place destination/submission errors immediately above the dialog summary.


The dialog opens with that project's last successfully submitted choices. Without saved choices, use the application's last export folder, current game display orders, enabled prefixes, filename Rating on and folder organization By rating. Existing project preferences without a filename-rating choice also default to on. Omit removed fields, normalize choices to current display orders, and give newly encountered games their current defaults. Title casing remains the application preference and is frozen in the submitted job.

On submission, recheck current project membership, eligibility and destination using strict manifest validation; freeze filename choices and source identities through the existing engine, and atomically record the queued job with project preferences before dispatch. A changed input snapshot or failed transaction saves neither. Preferences survive later job failure/cancellation; frozen jobs ignore subsequent project, metadata, preference and game-configuration changes. Keep the existing output concurrency, collision handling, whole-file copies, cancellation cleanup and verified Resume behavior.

### 16.1 Export Eligibility

For a Project Export:

- `keep` clips are candidates for export;
- `discard` clips are ignored;
- any clip with pending triage blocks the entire export;
- any kept clip with no structured metadata field and no `mainline` blocks the entire export;
- any kept clip whose source file is unavailable blocks the entire export.

One invalid clip prevents creating a new export job. The setup footer identifies Pending/Blocked counts and disables Export until those members are resolved or removed. Revalidate before enqueueing so stale eligibility cannot create a job; failed setup validation persists neither preferences nor jobs. Empty and Discard-only projects cannot create jobs. Execution-time source/destination failures still appear in Output Jobs, and existing frozen jobs, including previously deferred validation errors, retain their execution and Resume behavior. The workspace retains actionable readiness categories and per-card blocking reasons.


### 16.2 Export Filenames

For each configured game with Keep clips in the Project, filename options choose which structured fields appear in generated filenames. Include blocked Keep games so their options remain configurable; omit games represented only by Pending or Discard clips. The compact game selector shows the complete game name and display code, with middle elision and a full-name tooltip. A separate inset, read-only live preview shows the generated export filename from the first Keep clip for that game in catalogue order, including its original extension. Each example uses current draft field/prefix choices, title casing, sanitization and fallback naming from the export engine, updating immediately when its checkboxes change. Underline the entire included mainline portion in the preview, excluding metadata, prefixes and extensions. Preserve that semantic span through sanitization, truncation and display elision; omit underlining when mainline is absent, unchecked or replaced by filename fallback. Underlining changes presentation only. Keep game selection keyed by game identity. Show the complete filename in the preview tooltip; numeric collision suffixes remain assigned during copying. With no configured Keep-game examples, omit per-game controls and explain the absent preview while retaining the project-wide filename-rating choice.


The user may independently choose whether to include:

- the game's display-code prefix;
- clutch;
- kill;
- game-specific fields such as agent, map, or weapon;
- `mainline`.

Selected fields follow the game's YAML `display_order`.

Project Export separates filename formatting from folder organization. Under Include in filename, **Game code [CODE]** and **Rating** share the first row; remaining game fields wrap beneath them. Rating applies to all games and defaults on, remembered per project only after successful submission. When enabled, insert `r1` through `r5` immediately after the game-code prefix, followed by a space before the selected fields or original-filename fallback; for example, `VAL_r5 jett clutch.mp4`. With the prefix disabled, the rating starts the filename. Unrated clips add no token. The token follows generated-title casing (`R5` when lowercase is disabled). Live examples use the same naming logic, and submitted jobs freeze the result. By rating folder organization remains independent. Working titles and Share filenames are unchanged.

`description` is not included in generated filenames.

The generated-name Share dialog used outside Browse opens with every individual field, **All fields**, and **Game code prefix** off. **All fields** selects or clears all metadata/mainline fields and reflects checked only when every individual field is selected; the prefix remains independent. Confirmation remains disabled until a non-whitespace custom filename, at least one individual field, or an available game-code prefix is selected. Browse retains its separate required-custom-title Share panel.

The source file extension is preserved.

Output names are sanitized for the destination filesystem without changing the stored metadata.

Existing files are never overwritten. Collisions receive a numeric suffix.

### 16.3 Export Directory Layout

The default Project Export folder organization is **By rating**. **Flat** copies all exported videos directly into the selected project-export directory; saved Flat preferences remain respected.

DFSorter does not attempt to infer arbitrary organizational folders from game metadata in v1.

The Folder organization section offers an exclusive **By rating / Flat** segmented choice (By rating first and default), independent of filename-rating inclusion and stored in the existing `group_rating` preference. **By rating** may instead create subdirectories named `R1`, `R2`, `R3`, `R4` and `R5` for the corresponding rating values, plus lowercase `unrated` for clips with no rating. New exports use these names; already queued jobs retain the directory names frozen in their manifests.

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

Re-exporting the same Project later is a new copy operation. Existing files are never overwritten and therefore receive collision suffixes as necessary. A separate **Resume export** action continues an unfinished recorded job using its frozen clip list and output choices. Unfinished job records are stored in the catalogue until resumed to completion or explicitly forgotten. Each completed file records its size and SHA-256 digest; Resume verifies both before skipping it. If verification fails, Resume stops and reports the affected file for manual repair. Successfully copied files remain after cancellation or failure.

Share and Project Export appear in a top-navigation Output Jobs dropdown with per-job percentages, phase text, cancellation, and retained results. Each job has an Explorer icon that opens its destination folder. A completed Share selects its generated file in Explorer and uses a distinct file icon; Project Export opens its destination folder without selecting a file. At most two output jobs run at once, including at most one FFmpeg Share. Pending output jobs wait in submission order when a matching slot is unavailable. Automatic scanning is deferred during output jobs. A confirmed exit cancels active output jobs; unfinished and failed Project Export records are offered for Resume after restart.

Running Project Export jobs reuse Share's indeterminate preparation bar without a percentage. Show “Preparing export…”, “Checking destination…” and “Recovering previous output…” as appropriate until the first processed byte. One overall determinate bar counts bytes verified in completed outputs plus bytes copied for unfinished entries, divided by the frozen manifest's total source bytes. Show “Verifying filename” during SHA-256 verification and “Copying filename” during direct copying; both phases use the same scale without resetting. Positive progress below one whole percent displays “<1%”. Running progress is capped at 99%; 100% appears only after successful publication and persistence of the completed manifest.

Recovery verifies an output published before its manifest update once and credits its bytes once; the later completed-file pass must not hash or count it again. Byte updates are throttled to at most ten per second, with forced updates for the first positive progress, phase transitions and phase endings. Cleanup after measurable progress retains the percentage and updates the phase text. Queued and paused presentation remains unchanged. Cancellation remains available during preparation, verification and copying; failure or cancellation stops indeterminate animation without inventing a percentage. Empty or zero-byte workloads may proceed directly from preparation to completion. Progress is runtime-only: no settings, manifest schema or copy/checksum/collision safeguards change. This feedback does not promise faster disk operations.

---

## 17. Config Panel

Config edits game definitions stored directly as YAML files under `configs/games/`; it does not create a second configuration model. The left pane lists games and invalid files. Opening Config focuses Search games and selects any existing query so typing immediately starts a new search. The center editor uses Identity, Fields, and Title & review tabs, with structured rows for values, aliases, prefixes and inference links. Identity includes canonical name, code, aliases and command example. Fields cover the ordinary enum/freeform model, multiplicity and optional links. Title & review controls display order, including `mainline`, and suggested fields. New games start with `kill`; existing canonical names and field keys are stable. Existing games cannot be deleted here.

A search field above the left game list filters by displayed name, code, or YAML filename,
case-insensitively. Filtering does not switch or discard the open game draft, even when
its list item is hidden. Clearing search restores the full list.
Game rows show the current YAML file size after code and field count on the second line,
using B below 1,024 bytes and KB at or above 1,024 bytes (1 KB = 1,024 B).
On opening Config, game rows also show a cyan `(+1 named value)` or
`(+N named values)` after the size for registrations made from Editing during the
current application run. Counts accumulate per game until application close; this
notice creates no Config undo step. Retain the complete summary in the row tooltip
when the sidebar is too narrow to display it.
New weapon fields include `wpn` as a prefix alias by default.

Edits remain drafts until Save. Validate the prospective YAML and registry on every edit, including raw-YAML repair. Invalid drafts disable Save and show a red diagnostic left of Save. Leaving a dirty draft offers Save, Discard or Cancel; when invalid, Save is disabled and the dialog shows the diagnostic while Discard and Cancel remain available. Discard restores the latest saved configuration and drops the unsaved history branch while retaining saved history. Save validates the prospective registry before atomically replacing the YAML file, preserves comments and unrecognized keys where possible, reloads configurations and refreshes affected views. A file changed outside DFSorter cannot be overwritten from a stale draft. Invalid files open in a raw-YAML repair view; a valid repair returns to structured editing.

Fields exposes values and value aliases for both ordinary field types. The values row
is labelled **Enum values** for enum fields and **Named values** for freeform fields.
Freeform named values are optional shortcuts; arbitrary prefixed input remains accepted.
Switching between these types retains the value and alias rows and their contents.
An alias canonical value must match a listed value for both types. Invalid alias values
and inference link source values, target fields, or target values are red and underlined
in their respective cells, with an explanatory tooltip. Removing a canonical value
leaves dependent aliases and links visible for correction; invalid references block Save.
Duplicate values, prefix aliases, and value alias names are invalid case-insensitively;
their cells show the same error styling and block Save.
Add row inserts below the selected cell's row, or appends when no cell is selected.
Double-clicking empty table space appends a row. Both actions immediately focus and
edit the new row's first cell. Remove row is available only while a cell is selected.
Adding a row must immediately reveal the complete row vertically, both inside the table
and in the enclosing Fields scroll area. Starting cell editing or typing into an active
cell must likewise reveal its full row height on the first keystroke, including after
manual scrolling. Preserve the active cell, typed text and normal editing/navigation.
Dragging a cell reorders its entire row within that table, preserving all column values.
Each table has a search field and previous/next match arrows after its row buttons on
the same line. Search highlights every cell containing a case-insensitive substring
without filtering rows; the arrows select matches in table order and wrap at the ends.
Clicking an
already-selected cell or double-clicking an existing cell edits it; Tab commits the
current cell and moves to the next cell. Enter on the last row adds a new row and
opens its first cell for editing; Enter on earlier rows commits without adding a row.
Only one cell across the editor tables is
selected at a time. Clicking another table or outside the tables clears the previous
selection; row action buttons retain the selection so Remove row can act on it.
Fields shows a brief instruction for table entry.
Table typing marks the configuration as changed immediately. Navigation includes the
active cell's uncommitted text in the Save / Discard / Cancel prompt; Save captures it,
Discard restores the loaded configuration, and Cancel retains the draft in Config.

Removing a field or canonical enum value used by clips shows affected counts and requires confirmation. Stored clip metadata is retained, including values hidden by a removed field. Removing a field removes links targeting it. Removing a canonical value leaves dependent aliases and inference links in the draft for correction before Save. Config history is separate from clip history and restores editor drafts without writing YAML files.

---

## 18. Undo and Redo

Toolbar Undo/Redo is available in Editing, Export and Config. Each button independently
reflects the active clip, workspace project or game history; available actions use `text.secondary` and
unavailable actions use `text.disabled`. Other pages cannot invoke these histories.
Focused text inputs retain native typing undo/redo. Histories exist only for this
application run; new edits clear the active history's redo branch.

Editing uses a separate history per clip, retained across clip and panel switches.
One submitted command or button action is one step, covering structured metadata,
mainline, description, tag, game, rating, verdict, reset and project membership.
Each In or Out press is a step, including unfinished ranges. Navigation itself is
not undone, and undo never changes another clip or the current Session position.
Undoing a command restores metadata and its visible command history; its original
text returns to an empty command box. An existing draft is preserved. Redo removes
restored command text only if it has not been edited. Staged single-clip Editing uses
its own temporary history without writing catalogue changes until Save. Changes to
clip state outside its history invalidate stale actions rather than overwrite newer state.

Export retains current-run typed membership and temporary-skip Undo/Redo per project in chronological order. Each changed batch is one step; no-ops create no step. Undo/Redo verifies expected membership or skip state before applying recorded changes, preserving metadata and other projects. Saved ranges stay outside this history. Stale history is rejected without partial changes. Editing membership writes invalidate affected workspace histories; workspace membership writes invalidate affected clip-edit histories. Destructive catalogue cleanup clears affected histories and prunes masks; project deletion clears its mask and history.

Config uses a separate history per game, retained across Save and game switches.
Consecutive typing in one focused input is grouped into one step; row actions,
field changes, checkboxes and reordering are individual steps. Incomplete table
entries and YAML repair drafts are included. Save is not an undo step or a history
boundary. Undo/Redo of previously saved changes modifies only the current draft;
Save is required to update the YAML. Discard restores the saved history checkpoint.

Config Revert restores the configuration first loaded for that game during this
application run as an unsaved draft, including changes already saved this run.
For a new game its initial creation draft is the baseline. Revert is enabled only
when the current contents differ from that baseline. Pressing Revert replaces it
with a red **Confirm revert** button in the same position. Clicking it restores the
baseline as an undoable draft action. An outside click, Escape, typing or navigation
cancels confirmation and restores the ordinary Revert button. Revert never writes
YAML; applying the restored draft requires Save.

Undo/Redo does not cover filesystem operations, external YAML edits, project
creation/deletion/renaming, exports, Share, scanning or playback controls.

Destructive catalogue operations outside the normal undo model require explicit confirmation.

---

## 19. Safety and Non-Goals

DFSorter must not silently modify original source media.

### 19.1 Explicit deletion of rejected originals

File → Delete rejected originals is an explicit exception to source preservation. It permanently deletes original video files for all library clips whose triage is `discard`, irrespective of current filters, projects, sessions, or whether their capture folder remains enabled or registered. It bypasses the Windows Recycle Bin.

Before deletion, show a read-only preview grouped by actual parent folder, with full paths, per-folder rejected/to-delete counts, clip dates, individual sizes, folder totals and estimated overall size. Prefer cached media capture dates; label filesystem modification dates when used as fallback. Missing, linked/junction and non-regular sources are excluded with reasons. Logical file size is an estimate of space recovered.

Confirm through a red "Permanently delete originals" button in the preview, enabled when eligible files exist; no typed confirmation is required. Recheck catalogue identity, Discard status, path and file identity/size/timestamps before each deletion. On Windows, delete through a verified file handle that excludes concurrent writers and replacement; locked or changed sources are skipped. Never delete a folder or adjacent sidecar. Preserve catalogue records and project/session references as unavailable media. Cancellation stops subsequent deletions; report each success, skip, failure and cancellation. Deleted originals cannot be restored by metadata Undo. Do not run concurrently with scanning, sharing or export.

The bulk rejected-originals preview omits sources already recorded as explicitly deleted. Other missing rejected sources remain visible as unavailable/excluded. If a source recorded as explicitly deleted exists again, the normal marker-clearing behavior makes it eligible for later previews.

### 19.2 Unified settings

The top-right Lucide settings cog retains its action menu. Settings… opens a dialog with General and Appearance tabs in that order, with General initially selected; Capture folders… navigates to Home. General groups preferences in rounded boxes labelled with their affected panes: near-end playback applies to Browse, Editing and Export on the next clip load; paused typing applies only to Editing; title and generated-filename casing applies to Browse, Editing and Export. Avoid introductory prose between settings. Project management is available only in Export. Capture-folder management lives only on Home.

General also contains the Share group with an Output quality select box, using Appearance → Theme's ordinary noneditable QComboBox, label/buddy row and shared theme styling. The secondary description explains native quality and Web output up to 1080p and 60 fps without upscaling, with the two bitrate tiers and application to subsequent Shares. Do not add preset overrides to individual Share forms.

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

---

## 20. Design System

[UI Layout Guide](ui-layout-guide.md) is authoritative for reusable layout, typography, colors, component styling and visual interaction states. Consult it when adding or reviewing UI features. This specification retains functional behavior and explicit page-specific constraints.

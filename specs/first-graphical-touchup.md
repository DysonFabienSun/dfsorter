# Feedback

## Approved implementation decisions

- The current main specification incorporates this touchup. Its original version is archived under `specs/legacy/` and must not guide implementation.
- Superseded keyboard workflow: Enter submits only in command-input mode; Shift+Enter is review-only verdict-and-advance and requires an empty command bar. See the main specification §13.6. Empty-input Backspace only edits text. Escape retains per-clip drafts for the current run.
- R followed by 1–5 within one second rates in review mode. Space has a 200 ms tap/hold threshold.
- Projects defaults collapsed in normal windows and expanded when maximized, with separate per-run manual overrides.
- Share defaults to the saved valid range when present, even if a new In point is pending. Every Share outputs H.264 MP4 and mixes all audio tracks into stereo AAC; silent clips remain silent. Whole H.264 video is stream-copied; all trims and other codecs re-encode. Prefer NVIDIA speed with x264 fallback. Project Export remains unchanged.
- Hardware decoding is preferred and verified for supported media; software fallback remains allowed.
- Empty Tag is hidden and can be added through the Clip menu.

The original feedback below records the motivation; the decisions above resolve its ambiguities.

This will be the first visual overhaul of the application. The main functionalities are now mostly solid, and it's the application, and how it's presented, that needs work.
## Feature Changes

### Editing Pane Focus/Keyboard Behavior

**Fix focus and keyboard behavior.** Editing should have a true “review mode” and “text-input mode.” In review mode, nothing textual owns focus: Space = play/pause, arrows = seek, I/O = markers, Backspace = reject, `R1–R5` = rating. Press `/` or Enter to focus the command bar; Escape returns to review mode. While the command bar has focus, keys behave normally as text. The command bar should not however parse / or /... commands in its current state.

REVIEW MODE
Space        Play/Pause
	Hold Space       Fast Forward 3x (*was 2.5x*)
← / →        Seek ±5 s
Shift+←/→    Seek ±1 s
I / O        Set range
Backspace    Reject
R1–R5        Rate
/ or Enter   Enter metadata input
?            Show shortcut overlay

INPUT MODE
normal text editing
Enter         Submit
Shift+Enter   Submit + Keep + Next
Esc           Return to Review Mode

This would be the new keybind suite. Some features may be newly introduced.
As well, add something like `Space Play · ←/→ Seek · I/O Range · R1–5 Rate · ⌫ Reject · / Metadata · ? Shortcuts` as a context hint above the command field.

Additionally add a ? button on the Editing panel for a cheatsheet with the text as seen above. It would also include workflow recommendations (but keep it light) for giving a verdict on clips.

### Trimmed Share

Share should now offer a functionality to share either the whole clip or the selected In/Out range when a valid I/O range exists. Use exact trim with decode and reincode with ffmpeg, so that the I/O is absolutely accurate. This does not affect project export.

### Video Playback Technology

The current video playback and scrubbing is a little laggy. There are a few important things to implement:
- Make sure AV1 and other codecs are hardware decoded using my computer hardware.
- For dragging playheads around:
	- don't call `setPosition()` for every pixel/mouse-move event;
	- throttle live seeks to perhaps ~15–20 updates/sec;
	- while dragging, use approximate previews;
	- perform the accurate final seek when the mouse is released;


## UI Changes

### Right Project Pane

When the app isn't in full screen, make the right project pane by default collapsed and collapsible.

### Icons

The Lucide-static suite of icons has been downloaded and are currently in `E:\1. Workflow\1. Projects-II\2026-9-13, Project, dfsorter mk1\node_modules\lucide-static\icons`. Peruse through all of the supplied icons and create a folder under `resources/icons` with icons you would actually need. Do not directly use lucide-static icons from that folder.

The main icons to replace are text transport buttons, play/pause, mute, previous/next, set/clear range, share, project add/remove, refresh, folder operations, etc. You should also redo the star rating row in general as it having 5 buttons is very odd.

### Navigation buttons

**Turn the six huge navigation buttons into an actual tab/navigation strip.** Same location, same six destinations, but inactive tabs should mostly disappear into the background; active tab gets brighter text plus perhaps a cyan underline. Right now they look like six equally important form-submit buttons.

### Clip List (left pane)

**Redesign the clip list as rows rather than raw text.** At the moment `keep`/`undefined` appear as a second plain line and long names create a horizontal scrollbar. Give each clip a 40–50 px row: title on line one, small muted metadata/status on line two, maybe a tiny status dot. Elide long text rather than horizontally scrolling.

### Project Buttons

**Compress secondary actions.** Seven full-width Project buttons are far too prominent. `New`, `Rename`, `Activate`, `Add`, `Remove`, `Delete` can mostly become a small icon toolbar/context menu underneath the project list. Delete should not visually resemble New Project.

In general, a lot of buttons are too full-width. The Home, Import and Session pages don't need to become fancy. For example, Session could have the `50` field plus a compact segmented choice like **Selected / First N / All**, followed by one primary **Create Session** button. That reads much more clearly than five identical buttons.

### Working title format

**Use typography much more aggressively.** On Editing, the working title should be a genuine focal element. `VAL_3K Chamber Operator Headhunter quickdraw and good aim` is currently approximately the same visual importance as everything around it. Make structured metadata slightly muted and the mainline brighter/bolder. Description and tag should recede.

### Visual changes for rare trinkets

**Make rare things rare visually.** `Tag` probably doesn't deserve a permanently prominent row. It should only appear when populated.

### Timeline thickness

The current timeline bar is functional, but too thin and deserves more importance. Make it perhaps 6–8 px high with a larger invisible hit target, clearly colored In/Out markers and a tinted region between them, like 
`00:00 ────────│████████████████│──────── 01:52`
               I                           O`

Then, I would put the transport row directly beneath it:

`⏮ ▶/⏸ ⏭ 🔊 ━━━━━ 00:42 / 01:52`

That would be much nicer.

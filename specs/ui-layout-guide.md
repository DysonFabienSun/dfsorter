# DFSorter UI Layout Guide

## 1. Purpose and authority

Stable reference for adding or reviewing UI features. Covers layout, typography, colors, component appearance and visual interaction states across every page, menu and application-owned dialog. Native file pickers retain operating-system styling.

This guide owns reusable visual rules. [Main specification](dfsorter-specs-clean.md) owns feature behavior, shortcuts, data semantics and page-specific requirements. Read both before UI work. Explicit page-specific constraints are exceptions, not defaults for new pages. Resolve conflicts explicitly; do not silently redesign approved layouts.

Browse and Editing are reference compositions. Inspect current implementations and equivalent controls before changes; incidental local styling is not permission to duplicate it. [Shared theme](../src/dfsorter/theme.py) owns implementation tokens, fonts, palette and QSS; [shared widgets](../src/dfsorter/widgets.py) own icons, clip cards and rating presentation. Reuse these primitives. Changes to approved values require coordinated guide/theme updates.

Use restrained, slightly cool desktop styling in both light and dark modes: dense,
low-saturation surfaces, subtle borders, quiet sidebars, strong alignment and a large video
area. Light mode is the primary design reference; dark mode expresses the same hierarchy
rather than inverting it mechanically. Avoid gradients, oversized controls, pill buttons,
neon styling, large rounded cards, pervasive shadows and unnecessary panel borders. The
result should resemble a polished productivity/media tool, not a consumer streaming app or
web dashboard.

Keep implementation history, screenshots and verification results outside this guide. Record completed work and user acceptance separately in [feature tracking](../docs/features.md). [First graphical touchup](legacy/first-graphical-touchup.md) is archival motivation only, never implementation authority.

## 2. Visual foundations

### Semantic color model

Components request semantic roles and must not branch on the active color mode. Theme
resolution maps those roles to the selected Light or Dark palette. Reusable code must not
embed palette hex values or introduce page-specific aliases for an existing semantic role.
Small component-specific roles are allowed when a general role would obscure meaning.

Canonical roles use dotted names in documentation. Python identifiers may use an equivalent
unambiguous form such as `surface_canvas`; do not maintain a second legacy vocabulary.

#### Light palette

| Role | Value | Intended use |
| --- | --- | --- |
| `surface.canvas` | `#F3F5F7` | Window canvas behind the functional surfaces |
| `surface.workspace` | `#FFFFFF` | Primary page and working surface |
| `surface.sidebar` | `#F8F9FA` | Left/right panes and top chrome |
| `surface.panel` | `#FFFFFF` | Dialogs and important contained surfaces |
| `surface.subtle` | `#F6F8FA` | Secondary panels and neutral button fill |
| `surface.control` | `#FFFFFF` | Inputs and neutral controls |
| `surface.hover` | `#EDF1F3` | Ordinary hover state |
| `surface.pressed` | `#E4E9ED` | Pressed and neutral checked state |
| `surface.video` | `#000000` | Video surface only |
| `text.primary` | `#1F252B` | Primary content and control labels |
| `text.secondary` | `#4F5B66` | Supporting information |
| `text.muted` | `#65717C` | Tertiary hints and metadata |
| `text.disabled` | `#A3ABB3` | Disabled content |
| `text.inverse` | `#FFFFFF` | Text on a strong accent fill |
| `border.default` | `#C8D1D9` | Input and emphasized control boundaries |
| `border.subtle` | `#DEE5EA` | Separators and quiet button boundaries |
| `border.strong` | `#AEB8C1` | Emphasized neutral boundaries |
| `accent.default` | `#087F8C` | Primary action, active indicator and meaningful emphasis |
| `accent.hover` | `#066E79` | Hover on strong accent controls |
| `accent.pressed` | `#055E68` | Pressed strong accent controls |
| `accent.soft` | `#E2F2F4` | Quiet accent surface |
| `accent.softHover` | `#D4EAED` | Hover on a soft accent surface |
| `accent.selection` | `#D9EFF1` | Selected items and text selection |
| `focus` | `#087F8C` | Keyboard focus ring |
| `status.success` | `#247A4B` | Keep and success foreground |
| `status.successSoft` | `#E6F4EC` | Keep and success surface |
| `status.warning` | `#9A6700` | Missing suggestions and unavailable sources |
| `status.warningSoft` | `#FFF4D6` | Warning surface |
| `status.danger` | `#C83C43` | Discard, destructive action and blocking error |
| `status.dangerHover` | `#AD3037` | Destructive hover |
| `status.dangerSoft` | `#FBEAEC` | Destructive surface |
| `status.info` | `#316DCA` | Informational state |
| `rating.filled` | `#A66A00` | Filled rating star |
| `rating.hover` | `#C17C00` | Rating hover preview |
| `rating.empty` | `#7C8791` | Empty star for a populated rating |
| `rating.label.1–5` | `#A83245` → `#1F7044` | Bold list rating scale from low to high |
| `component.commandValid` | `#EAF2FB` | Valid command draft |
| `component.timelineTrack` | `#C7E0E3` | Pale teal timeline remainder |
| `component.timelineProgress` | `#087F8C` | Elapsed timeline section |
| `component.volumeTrack` | `#D5E7E9` | Quiet teal volume remainder |
| `component.volumeProgress` | `#3D929B` | Current volume level |
| `component.clipScrollbarTrack` | `#D5E7E9` | Left-pane clip-list scrollbar track |
| `component.clipScrollbarThumb` | `#3D929B` | Left-pane clip-list scrollbar thumb |
| `component.scrollbar` | `#CDD5DC` | Neutral scrollbar thumb |
| `component.tooltip` | `#252B33` | Tooltip surface |

#### Dark palette

| Role | Value | Intended use |
| --- | --- | --- |
| `surface.canvas` | `#181C21` | Window canvas behind the functional surfaces |
| `surface.workspace` | `#1F242B` | Primary page and working surface |
| `surface.sidebar` | `#1B2026` | Left/right panes and top chrome |
| `surface.panel` | `#1F242B` | Dialogs and important contained surfaces |
| `surface.subtle` | `#252B33` | Quiet grouped regions and alternating surfaces |
| `surface.control` | `#20262D` | Inputs and neutral controls |
| `surface.hover` | `#2A313A` | Ordinary hover state |
| `surface.pressed` | `#303842` | Pressed and neutral checked state |
| `surface.video` | `#000000` | Video surface only |
| `text.primary` | `#F1F4F6` | Primary content and control labels |
| `text.secondary` | `#BEC6CD` | Supporting information |
| `text.muted` | `#8E99A4` | Tertiary hints and metadata |
| `text.disabled` | `#626C76` | Disabled content |
| `text.inverse` | `#111317` | Text on a strong accent fill |
| `border.default` | `#39424C` | Control boundaries |
| `border.subtle` | `#2D343D` | Separators and quiet card boundaries |
| `border.strong` | `#515C67` | Emphasized neutral boundaries |
| `accent.default` | `#43B6C3` | Primary action, active indicator and meaningful emphasis |
| `accent.hover` | `#58C2CD` | Hover on strong accent controls |
| `accent.pressed` | `#32A4B1` | Pressed strong accent controls |
| `accent.soft` | `#173D43` | Quiet accent surface |
| `accent.softHover` | `#1B4850` | Hover on a soft accent surface |
| `accent.selection` | `#20515A` | Selected items and text selection |
| `focus` | `#4CC1CE` | Keyboard focus ring |
| `status.success` | `#62C98D` | Keep and success foreground |
| `status.successSoft` | `#1C3A2A` | Keep and success surface |
| `status.warning` | `#D9A441` | Missing suggestions and unavailable sources |
| `status.warningSoft` | `#3A2D16` | Warning surface |
| `status.danger` | `#EF6A70` | Discard, destructive action and blocking error |
| `status.dangerHover` | `#FF8086` | Destructive hover |
| `status.dangerSoft` | `#48252A` | Destructive surface |
| `status.info` | `#6AA9E9` | Informational state |
| `rating.filled` | `#E8C45A` | Filled rating star |
| `rating.hover` | `#F0D16F` | Rating hover preview |
| `rating.empty` | `#69717D` | Empty star for a populated rating |
| `rating.label.1–5` | `#FFA0A8` → `#79D7A0` | Bold list rating scale from low to high |
| `component.commandValid` | `#172B40` | Valid command draft |
| `component.timelineTrack` | `#23434A` | Dark teal timeline remainder |
| `component.timelineProgress` | `#43B6C3` | Elapsed timeline section |
| `component.volumeTrack` | `#29434A` | Quiet teal volume remainder |
| `component.volumeProgress` | `#3698A3` | Current volume level |
| `component.clipScrollbarTrack` | `#29434A` | Left-pane clip-list scrollbar track |
| `component.clipScrollbarThumb` | `#3698A3` | Left-pane clip-list scrollbar thumb |
| `component.scrollbar` | `#3A424D` | Neutral scrollbar thumb |
| `component.tooltip` | `#11151A` | Tooltip surface |

Both palettes additionally derive pending-rating low/high values and a scrollbar-hover value
from their adjacent semantic roles. Populated tags use the rating/gold family, not the main
accent. Working-title metadata uses `text.secondary`; it must not have a theme-specific hard-
coded color.

Teal means primary interaction, focus, selection, active project, playhead or I/O markers.
It is not the default hover color for ordinary controls. Green means Keep or success; red
means Discard, destructive operations or blocking errors. Warning amber means suggested
missing metadata or unavailable sources. Gold rating tokens are reserved for stars and tags.
Clip-list rating labels use their dedicated five-step scale. Pending triage uses muted gray.
Always retain text or shape cues in addition to color.

### Theme selection and switching

Settings contains an **Appearance** tab with **Theme: System / Light / Dark**. Light is the
default when no preference exists. The selection is saved in `data/settings.yaml` and applies
immediately to all application-owned windows, menus, dialogs, custom-painted controls, rich
text and icons.

System resolves through Qt's operating-system color-scheme API and updates while DFSorter is
running when the system scheme changes. DFSorter still uses the palettes above; System does
not delegate its component design to the platform. A sun/moon icon button appears between
Projects and Settings in the top-right toolbar. Its tooltip names the action, for example
`Switch to dark mode`. It toggles explicit Light/Dark. From System it selects the explicit
mode opposite the currently resolved appearance.

Theme changes must invalidate theme-dependent icon/pixmap caches and repaint custom delegates
and widgets. Components must never retain colors captured from the previous mode.

### Typography, spacing and dimensions

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

Ordinary controls and menus use 13 px regular; secondary metadata uses 12 px; card metadata uses 11 px. Editing working titles use 13 px regular metadata in `text.secondary`, 13 px regular game codes and separators in `text.muted`, and 16 px bold mainline in `text.primary`. Separate metadata and mainline with ` | ` only when both are present. Retain wrapping. When no populated field contributes to the configured title display order, show the original filename followed by a smaller, secondary-colored “— Working title not set” hint. Section headings use 20 px semibold. Compact pane headings use 14 px semibold primary text. The Session clips header has a transparent background, shows the numeric session position as secondary text beside its title, aligns its title to clip-card text, and aligns its right action to the card edge. Avoid excessive bold text and bordered metadata boxes. Format multi-value metadata as readable comma-separated text, never Python list syntax.

Use 12 px panel padding, 4–8 px gaps within groups, 12–16 px between groups, and 24 px between large sections. Prefer 28 px ordinary controls and 24 px compact controls. Button/input radius is 4 px; larger grouped panels may use 5–7 px. Font metrics take precedence over dimensions where necessary to avoid clipping. Empty space may remain when a screen has little content; deliberate alignment and constrained group widths should keep content from appearing stranded.

### Surface and border hierarchy

Establish grouping in this order: surface, spacing, typography, then border. In light mode,
the cool-gray canvas, faintly tinted sidebars/top chrome and white primary workspace must read
as distinct functional layers. Secondary groups use `surface.subtle`; editable controls remain
white. Do not manufacture that depth by wrapping every section in a bordered card. Use borders
for control boundaries, major pane edges, meaningful section dividers and selected/focused
state. Do not frame each label, statistic or small content group.

Shadows are limited to menus, popovers, transient overlays and modal dialogs when Qt can
render them consistently. Persistent panels and cards remain flat. Do not add decorative
animation. Any inexpensive hover or selection transition must be short and must not delay
input, theme switching or navigation.


### Controls and visual states


- Neutral buttons use the lightly tinted `surface.subtle`, neutral hover/pressed colors, a quiet `border.subtle` boundary and 5 px vertical / 9 px horizontal padding. Inputs remain `surface.control`, so buttons and editable fields do not collapse into the same stock-control treatment. Primary buttons use a filled `accent.default` surface with `text.inverse`, and are limited to the singular commit action in a local context. Secondary actions remain neutral. Ghost/icon toolbar buttons have no visible border at rest. Destructive buttons use danger text with a danger-soft surface; strong red fill is reserved for confirmation-level emphasis. Disabled controls retain the subtle neutral fill, subtle border and disabled text/icon colors; avoid fading whole widgets into illegibility.
- Navigation sits at the top of the application with no menu bar or outer top gap; the workspace beneath it has its own 12 px inset. Navigation uses a continuous `surface.panel` strip with a subtle bottom divider and compact rectangular text-only tabs. Labels are 14 px medium; active labels are semibold. Inactive tabs use secondary text, transparent backgrounds and a neutral hover surface. The active tab uses primary text and a straight 2 px `accent.default` bottom indicator; it may use an extremely subtle active surface but must not also use strong side borders or accent text. Projects, Theme and Settings remain right-aligned utilities.
- Inputs use `surface.control`, a subtle border, primary text, muted placeholders, a quiet neutral hover and an unmistakable focus treatment. Use a 2 px focus ring where QSS and geometry permit without layout movement; otherwise use an equivalently clear inset/outline treatment. The command bar uses the same idle styling and `component.commandValid` when valid. No neon glow or native dotted focus rectangles. Focus behavior follows main specs §13.2.
- Triage controls are neutral unless active: Keep uses success-muted/success; Discard uses danger-muted/danger; Pending uses pressed-surface/strong-border/secondary-text.
- Projects remain a secondary utility pane with secondary header text, a cyan active-project indicator and compact icon toolbar. Every icon action has a tooltip and accessible name. Keep destructive actions visually separate; project deletion behavior follows main specs §14.
- Use vendored Lucide SVGs: 16 px utility icons, 20 px transport icons. Default/hover/active/disabled icons use secondary/primary/accent/disabled text tokens. Render sharply at high DPI. Tooltips include actual shortcuts when applicable.
- Rating uses 18 px SVG stars with 4 px spacing, gray unfilled stars for a populated rating, gold filled stars and lighter gold hover preview. Keep small `x` clear action visually adjacent; a valid drafted rating shows a faded gold pulse and disabled clock in its place. Muted rating hints share this row; rating interactions follow main specs §13.7.
- Metadata-style clip lists show a bold `R1`–`R5` label between game and verdict, using the theme's five-step low-to-high rating-label scale. Unrated clips omit the rating segment. Browse retains capture time and folder on its second line instead.
- Video is black. Use a **7 px timeline groove** with a larger hit area, pale teal remainder and strong teal elapsed section/playhead. Use focus-cyan saved I/O markers and accent range tint at 18% opacity. Pending In and Out have distinct labels (·I and ·O). The volume slider uses an 18 px widget height, 3 px groove, 10 px handle, quiet teal remainder and medium-teal level; center it optically with the volume icon and time text. Transport/audio/time controls remain directly below.
- Scrollbars are 8 px, transparent-track, neutral-thumb with lighter hover and no arrow buttons. Splitters have a 1 px visual divider and a wider interaction region, with stronger hover color.
- Tooltips appear after a 200 ms hover delay throughout the application. They use `component.tooltip`, 12 px text, a default border, theme-appropriate tooltip text, compact 3 px horizontal padding and optical vertical padding of 0 px above / 2 px below, with 4 px corners. Secondary metadata recedes; populated tag prefixes use the theme's gold/tag role and remain hidden when empty. Valid commands use `component.commandValid`; incomplete, invalid and briefly saved commands use warning, danger and success bottom borders respectively. Keyboard focus retains its teal outline; other command backgrounds stay neutral. Unset rating uses the existing danger color for star outlines only, with no background highlight.

Every applicable interactive component has intentional rest, hover, pressed, focused,
disabled and selected states. Ordinary text targets at least WCAG AA 4.5:1 contrast, and
important focus/control indicators target 3:1 against adjacent colors. These are practical
design checks rather than a claim of formal application-wide WCAG conformance.


## 3. Application shell and side panes

### Navigation and workspace

```text
Home  Browse  Session  Editing  Export  Config   [stretch]   Undo Redo   Projects   Theme Settings
------------------------------------------------------------------------------------------------------
Left pane                  | Center: page/player and information                  | Projects
```

Navigation touches application top edge; workspace has a 12 px top, right and bottom inset and a 13 px left inset. This left gutter uses the normal workspace surface while the sidebar keeps a compact 8 px content inset. Use the continuous strip and shared tab styling described above. Utilities align vertically and use consistent 28 px square hit areas, icon size and ghost-button behavior; Projects remains a 28 px labeled control. Undo/Redo have 4 px separation, then 16 px before Projects. Theme sits between Projects and Settings with 4–8 px toolbar spacing. Retain the existing optical 1 px downward offset for navigation utility artwork. Every icon-only utility has a tooltip and accessible name. Do not imitate tabs with ordinary form buttons.

Center receives extra space as window grows. Splitters separate panes without decorative nested frames. Pane visibility, default proportions and manual overrides follow main specs §9.4; adding a feature must not invent different pane persistence.

### Left pane

Order search/filter controls, compact heading/action row where required, expanding clip list, then page-specific footer. Home and Browse place Clips, Games and Projects menu buttons in one row beneath search, followed by availability and capture-time sort icon actions at the right. Session Editing uses a Session clips heading with Next pending action. Atomic single-clip Editing replaces that heading with **Single clip**, hides Next pending and the progress footer, and shows exactly one card. Align heading and footer text exactly to card title text and actions to the card edge, not merely to outer widget bounds. Library search and filter control edges begin on this same guide. Shared heading, footer and control margins are 8 px from the sidebar surface; the left-pane layout itself has no left margin, with 8 px right / 4 px vertical margins. The sidebar retains the shared 7 px rounded corners. These are component-specific offsets, not general panel-padding replacements.

Keep lists tall; command area belongs below center, not across entire window. Hide empty error rows. Header backgrounds stay transparent. Filters and footer visibility follow page requirements.

Search is the primary filter entry. The three filter menu buttons beneath it share height,
radius, padding, border treatment and arrow placement. Menus use persistent checkboxes for
multi-selection. Do not frame the row as a separate card when the sidebar surface and spacing
already establish the group.

### Clip cards



Use one shared delegate in all left-pane library, Session and Export views. A clip row has a
48 px body, 1 px inter-row gap and 7 px horizontal padding. At rest it is transparent against
`surface.sidebar` with only a short, subtle bottom separator inset to the text edge. It must
read as a dense file/media browser row, not a stack of rounded cards. Hover receives a soft
neutral fill. Selection may use a 3 px radius because its pale accent surface is transient.
Grow only as required by font metrics.

Line one uses 12 px regular muted game codes, 12 px regular structured metadata in `text.secondary`, and 13 px bold primary mainline, with a muted ` | ` separator when both portions exist. Filename fallbacks remain 13 px. Line two is a 6 px triage dot centered against visible text using font metrics, canonical game name (or Unassigned) and Keep/Discard/Pending at 11 px. Keep the two lines together with a 2 px gap, vertically centered in the card, rather than anchored to opposite edges. Reserve metadata width for triage and an amber Unavailable label before eliding the game name. Long titles elide; no horizontal scrollbar. Tooltips show the complete title, metadata and source path.

Hover uses `surface.hover`; selection uses `accent.selection` plus a 2 px `accent.default` left indicator. The selected fill must remain soft rather than becoming a saturated teal block. Keyboard focus uses a distinct focus boundary. Presentation data must use explicit roles, not substring matching against visible text.

When additional cards exist beyond a visible list edge, overlay a non-interactive 16 px vertical gradient at that edge, fading from `surface.sidebar` to transparent toward the content. The fade sits above card content without consuming layout space and disappears completely at the corresponding start or end of the list. Do not add chevrons or borders. On the first opening of each applicable navigation page, position a selected card that is not first with only the bottom third of the immediately preceding card visible above it. Preserve the viewport on later selection and navigation changes.

Browse uses capture datetime and capture-folder name on line two instead of game/triage text; retain shared card geometry, status dot and Unavailable treatment. Content and selection behavior remain governed by main specs §§9.5, 10.1 and 12.2.

### Projects

Secondary heading, active-project accent, expanding list and compact icon toolbar. Keep common actions grouped; destructive deletion remains separate in context menu. Every icon action needs tooltip and accessible name. Preserve enabled, disabled and checked states through shared styling.

## 4. Sparse-page composition

### Home / Capture folders

Preserve Capture Folders behavior and all existing information. Each watched folder is a
compact typographic group rather than raw diagnostic-looking text. The folder path is primary;
scanning state and total clips are secondary; detected-game counts and duration statistics are
tertiary. Align labels and values consistently and use spacing before introducing containers.
A quiet surface group is acceptable when multiple folders need stronger separation, but do not
turn every statistic into a card. The explanatory sentence remains tertiary and wraps.

### Session

Compose the existing setup controls as one deliberate compact region with a comfortable
maximum width. Present the session count summary first, then Scope, its Selected / First N /
All controls and count field, followed by the primary Create Session action. Separate existing-
session actions into a subordinate group containing Resume session and End session. A single
subtle panel surface around this region is permitted. Do not stretch controls across the empty
workspace, invent dashboard content or change behavior and terminology.

Empty space is valid on both pages. Content should be anchored to shared page edges and grouped
with intentional widths so it does not appear accidentally stranded in the upper-left corner.

## 5. Video and playback controls

Reuse [Player](../src/dfsorter/playback.py) across Browse, Editing and Export. Do not build separate transport variants for equivalent actions. Browse adds a pencil **Edit clip…** action after Clear range and before its trailing fullscreen action. Both use shared icon-tool-button styling and accessible names. Fullscreen uses maximize to enter and minimize to exit, retaining the existing player and controls with surrounding UI and outer padding hidden.

```text
Video surface                                     [expands]
Timeline with playhead and I/O markers
Previous Play Next Mute Volume Time   >>>   Set In Set Out Clear [page actions]
[Status only when populated]
```

Video absorbs available height; timeline and transport remain compact. The native black video
surface uses libmpv's display-corrected aspect ratio and is centered within a
`surface.canvas` container. The surface must fit rather than crop or stretch, so player-added
letterbox/pillarbox regions become application canvas while black pixels encoded in the video
remain untouched. This behavior applies to landscape, portrait, square and unusual source
resolutions. Transport/audio/time form left group; range/page actions form right group. Both
occupy same row beneath timeline. Editing separates Share/range controls from Add to project
+ Next with subtle 1 px vertical divider, 20 px tall. Group boundaries use separators;
individual buttons do not each need dividers.

Center `>>>` in middle grid column with equal stretch on side columns. Reserve its horizontal slot while hidden; do not add indicator row or change video height. Use bold shared small font and animated accent highlights across three glyphs. Existing `QTimer` runs at 120 ms only during active hold, then stops/resets. Hold activation/cancellation and playback restoration follow main specs §13.2.

Status messages wrap when populated and collapse when empty. Keep transition/loading presentation consistent with main specs §9.1; never leave blank status row between transport and title.

## 6. Below-video information and forms

### Shared composition rules

Treat symmetry as shared edges, balanced groups and deliberate spacing, not equal width for unrelated controls. Align labels, field starts, field ends and adjacent actions through layout rows/columns. Give expanding content stretch; keep utility buttons compact. Use logical pixels and font metrics, not physical-screen measurements.

Keep title and source filename together. Working titles wrap; clip-card titles elide. Separate metadata and mainline with ` | ` only when both exist. Descriptions occupy separate wrapping row when populated; do not force them into title text. Optional tag/description content must not leave blank lines. Preserve page-specific fallback content while matching semantic font/color roles.

Use margins/spacing for gaps, never newline padding or empty labels. Use subtle horizontal divider at meaningful section boundary, such as identity → form; avoid framing every field. Do not insert manual `<br>` or paragraph breaks solely to imitate spacing. Wrap long text naturally and split distinct form groups into rows; retain explicitly specified Browse row arrangement.

### Browse reference

```text
Working title, wrapping                                          [Delete source]
Source filename
-------------------------------------------------------------------------------
Custom title   [spans output folder + picker + Share label + selector          ]
Output folder  [480 px input                       ] [picker] Share [140 px   ]
               [10 px explicit gap before I/O summary]
Range summary
Encoding hint                                                        [Share]
```

Diagram describes relationships, not character-width dimensions. In [BrowsePage](../src/dfsorter/browse.py), title action aligns top with wrapping title and uses 12 px row gap. Form uses shared `QGridLayout` columns, 6 px horizontal / 10 px vertical spacing. Custom title spans columns 1–4; folder occupies column 1, picker 2, Share label 3, selector 4. Trailing column stretches. Share label has 12 px left inset. Title input right edge equals selector right edge; never derive it from early `sizeHint()` calculations.

480 px folder width and 140 px selector width are Browse-specific requirements from main specs §10.1, not universal input widths. Preserve 10 px explicit gap before range summary in addition to layout-managed spacing. Do not silently shrink or reflow prescribed fields; report clipping that requires specification change.

Video remains the dominant visual element. Below it, the working title is primary; source/file
information and Share controls are secondary; codec and explanatory text are tertiary. The
tertiary tier must not compete with Share or Delete. Playback uses the same neutral ghost-icon
language as the rest of the application, while the seek/progress role may retain teal.

### Editing reference

```text
Working title, wrapping
Source filename
Triage / game / project status
[Keep] [Discard] [Pending] [Change game]
Rating stars [Clear] [Muted rating hints]                             [Help]
Structured metadata
[Description when populated]

Command area: intentional separation from clip information
[Recent command history when populated]
Wrapping shortcut hint
[Command input spanning center]
Command feedback
Field checklist
```

Retain bottom command area within center column and full-height left list. The command-area top margin is `8 + fontMetrics().lineSpacing()` logical pixels: intentional separation, not empty content bug. The wrapping shortcut line uses the 11 px tertiary helper role so it reads as reference rather than task content. Feedback line and checklist reserve enough height to prevent baseline jumps. Put the range warning immediately left of Set In and Set Out in the player controls row and retain its slot when valid. Do not apply empty-row collapse indiscriminately to these reserved elements.

Triage/rating groups remain compact and left aligned; help action anchors right. Description uses selectable plain text on separate row. Functional behavior and field availability follow main specs §13.

The visual order is video, playback, working title and source context, triage/game/project status,
rating, structured metadata and description, then the separated command/help region. Keyboard
hints and technical explanations remain readable but tertiary. Rating stars retain the dedicated
gold semantic family. Compact clip-list labels use their separate five-step scale and always
retain the explicit `R1`–`R5` text cue.

Atomic single-clip Editing preserves this composition. Put compact **Save** and red **Revert** actions on the working-title row, aligned to its top/right edge. Hide Add to project + Next; disable Previous/Next and catalogue Undo/Redo. Membership Add/Remove remains in the Projects pane while global project mutations are disabled.

Place new panel information in an existing row where practical. A new row can cause conspicuous vertical movement when its content appears or disappears.

### Export and Config

Preserve existing workflows and page-specific constraints. Apply the same shared surface,
typography, form alignment, button hierarchy and state styling used elsewhere. Export's final
commit action is primary; setup and utility actions remain secondary. Config remains a compact
utility page and must not grow decorative cards merely to occupy space.

## 7. Qt implementation patterns

### Shared styling and text

Use `theme.role()`, `theme.font()`, `theme.title_styles()`, `widgets.tool()` and `widgets.icon()`. Match widget font and rich-text spans together; matching only `QLabel.font()` misses embedded sizes/weights/colors. For rich user content, escape text before insertion. Set `Qt.TextFormat.PlainText` for literal descriptions/filenames and explicit `RichText` for formatted titles. Use `setWordWrap(True)` where text may grow.

Reusable appearance belongs in theme/shared component, not new local stylesheet. Existing local exceptions do not establish new defaults. Lucide source library is `node_modules/lucide-static/icons`; vendor only used SVGs into `resources/icons`, retain license, load on demand through `icon()`. Do not bundle whole library or access node_modules at runtime.

### Align through layout, not measured guesses

Illustrative pattern; `label`, `title`, `folder`, `picker` and `mode` are existing widgets:

```python
form = QGridLayout()
form.setHorizontalSpacing(6)
form.setVerticalSpacing(10)
form.addWidget(label, 0, 0)
form.addWidget(title, 0, 1, 1, 3)
form.addWidget(folder, 1, 1)
form.addWidget(picker, 1, 2)
form.addWidget(mode, 1, 3)
form.setColumnStretch(1, 1)
```

Use actual Browse grid for its additional Share label and fixed-width constraints. Set outer margins once; nested layouts should not accidentally double padding. Use `QSizePolicy` and layout stretch to express growth. Font metrics and wrapping take precedence over arbitrary fixed heights. Do not cache input widths before Qt completes layout, or repeatedly force geometry from resize handlers when shared columns suffice.

### Collapse empty content; reserve intentional slots

```python
def set_status(label, message):
    label.setText(message)
    label.setVisible(bool(message))
```

Initialize empty status labels hidden. `clear()` removes text but does not hide widget: remaining size hint/layout spacing can create blank line above title. Check nested margins, spacers and rich-text paragraph breaks when diagnosing gaps.

For `>>>`, retain hidden size inside existing transport row:

```python
policy = indicator.sizePolicy()
policy.setRetainSizeWhenHidden(True)
indicator.setSizePolicy(policy)
indicator.hide()
```

This retains both widget dimensions; existing transport row already owns vertical height, so no extra row is introduced. Apply only where stable geometry requires reserved slot, such as fast-forward indicator or range warning. Ordinary empty status and optional description rows collapse.

### Inspect final geometry and scaling

Let Qt process layout before comparing positions. Compare edges in same coordinate space using `mapTo()`; inspect rich-text formats as well as widget fonts. Use `QFontMetrics` for painted text, elision and hit-area sizing. Keep device-pixel-ratio handling inside shared icon renderer. Window resize and display scaling are separate checks; neither substitutes for other.

## 8. Feature and review checklist

- Read main specs, this guide and closest Browse/Editing counterpart before changing UI. Reuse shared components; flag unrelated inconsistencies separately.
- Compare equivalent typography, rich-text spans, colors, icon sizes, baselines and field edges. Confirm intentional exceptions remain page-specific.
- Inspect populated/empty titles, filename fallbacks, tags, descriptions, errors and unavailable sources. No accidental blank status rows or empty paragraph spacing.
- Exercise normal, hover, pressed, checked, selected, keyboard-focus and disabled states; retain text/shape cues beyond color. Check rating hover/clear and multi-selection where supported.
- Check `>>>` activation/cancellation, range warnings and command feedback without unwanted vertical jumps. Verify adjacent clip cards and narrow panes.
- Check short, long and mixed Chinese/English text; wrapping in detail panes, elision/full tooltips in cards, and visibility of bottom actions.
- Compare normal/maximized windows and 100%, 125%, 150% scaling for affected components. Inspect representative menus/dialogs when shared styling changes.
- Capture the same representative populated, empty, focused, disabled and selected states in Light and Dark. Check System mode against both operating-system appearances and verify live system changes. Theme switching must not leave stale icons, rich-text colors, custom-painted controls, menus or already-open dialogs.
- Audit contrast for ordinary text, secondary text, focus boundaries, selected items, destructive states and unavailable warnings. Do not approve a palette solely from isolated swatches; evaluate colors on their actual adjacent surfaces.
- Run smallest relevant existing checks for UI edits, using isolated catalogues/generated media where needed. Broaden only for concrete impact. Documentation-only changes need diff/link review, not runtime tests.

Existing checks include `test_browse_form_alignment_and_title_style` and `test_browse_layout` in [UI tests](../tests/test_ui.py). [Visual fixture script](../tests/visual_design.py) supplements inspection but currently omits Browse; its captures are not exhaustive acceptance. Screenshots may predate source: verify provenance before using them as reference.

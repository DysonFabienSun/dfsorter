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
| `surface.sidebar` | `#F8F9FA` | Library pane and top chrome |
| `surface.panel` | `#FFFFFF` | Dialogs and important contained surfaces |
| `surface.subtle` | `#F6F8FA` | Secondary panels and neutral button fill |
| `surface.prominentNeutral` | `#FFFFFF` | Brighter neutral fill for the leading Capture folders action |
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
| `accent.selection` | `#C9E9ED` | Selected items and text selection |
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
| `surface.sidebar` | `#1B2026` | Library pane and top chrome |
| `surface.panel` | `#1F242B` | Dialogs and important contained surfaces |
| `surface.subtle` | `#252B33` | Quiet grouped regions and alternating surfaces |
| `surface.prominentNeutral` | `#2C333B` | Brighter neutral fill for the leading Capture folders action |
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
| `accent.selection` | `#245E68` | Selected items and text selection |
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

Both palettes additionally derive pending-rating values and a scrollbar-hover value
from their adjacent semantic roles. Populated tags use the rating/gold family, not the main
accent. Working-title metadata uses `text.secondary`; it must not have a theme-specific hard-
coded color.

Teal means primary interaction, focus, selection, playhead or I/O markers.
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

General's Share group uses an **Output quality:** label and ordinary noneditable select box in the same horizontal label/buddy/control/stretch arrangement as Appearance's Theme row. Reuse its typography, padding, popup, focus and hover behavior without custom delegates, fixed selector widths or local stylesheets. Keep a wrapped shared-secondary description beneath the row and use the existing group spacing.

General playback settings use the existing grouped controls. Indent **Use separate start positions for Browse, Editing, and Export** 12 px beneath the unified start-position row, with a compact 4 px vertical gap. Separate start positions show an
outlined group with aligned Browse, Editing and Export enable and seconds controls; the unified
enable and seconds controls are hidden while that group is shown.
Use 8 px between controls within Settings groups and 12 px between groups. The playback seconds
fields are 52 px wide, with compact arrows, and fit the full `999 s` value. Use a compact
spin-box height with a 1 px top and 3 px bottom margin so each complete frame sits slightly
above its checkbox text. Shift the value text 1 px upward within the frame for even vertical
padding. Keep this styling consistent in unified and separate Browse, Editing and Export rows.

Manage unavailable clips uses a scrollable dialog with one two-line group per immediate original parent folder. Keep the full path visible or wrapped with its full value in a tooltip; align Do nothing, Delete…, and Reassociate… on that path row. Use muted secondary text for the composition, date and cached-size row. Avoid selection-only actions and per-clip checkboxes; each group action names its scope and destructive confirmation exposes affected full paths.

System resolves through Qt's operating-system color-scheme API and updates while DFSorter is
running when the system scheme changes. DFSorter still uses the palettes above; System does
not delegate its component design to the platform. A sun/moon icon button appears beside
Settings in the top-right toolbar. Its tooltip names the action, for example
`Switch to dark mode`. It toggles explicit Light/Dark. From System it selects the explicit
mode opposite the currently resolved appearance.

Theme changes must invalidate theme-dependent icon/pixmap caches and repaint custom delegates
and widgets. Components must never retain colors captured from the previous mode.

### Typography, spacing and dimensions

Use Segoe UI on Windows, then installed Inter, Arial and Qt's sans-serif fallback. For Chinese glyphs, prefer installed Microsoft YaHei UI; prefer Microsoft JhengHei UI first on Traditional Chinese Windows locales. Do not download or bundle fonts. All dimensions below are logical pixels and scale with Qt's display scaling.

| Tokens | Values |
| --- | --- |
| Font sizes xs / sm / md / base / card title / lg / xl / xxl | 11 / 12 / 13 / 14 / 14 / 16 / 20 / 26 |
| Section / pane heading font sizes | 22 / 16 |
| Weights regular / medium / semibold / bold | 400 / 500 / 600 / 700 |
| Spacing 1–6 | 4 / 8 / 12 / 16 / 24 / 32 |
| Radius none / structural / sm / md / lg | 0 / 2 / 3 / 5 / 7 |
| Control radius | 4 |
| Control compact / normal / large | 24 / 32 / 36 |
| Toolbar / navigation height | 28 / 34 |
| Icons xs / sm / md / lg / xl | 12 / 14 / 16 / 20 / 24 |

Ordinary controls and menus use 13 px regular; secondary metadata uses 12 px; card metadata uses 12 px. Editing working titles use 13 px regular metadata in `text.secondary`, 13 px regular game codes and separators in `text.muted`, and 16 px bold mainline in `text.primary`. Separate metadata and mainline with ` | ` only when both are present. Retain wrapping. When no populated field contributes to the configured title display order, show the original filename followed by a smaller, secondary-colored “— Working title not set” hint. Section headings use 22 px semibold text with a centered 24 px leading icon. Heading icons have no backing fill and use pure black in Light mode and pure white in Dark mode. Apply this shared style to Home, Session, and future section headings. Compact pane headings use 16 px semibold primary text. Raise icon-bearing heading text optically so its painted center aligns with the icon. The Session clips header uses the shared flat library toolbar surface, shows the numeric session position as secondary text beside its title, and keeps its right action near the pane edge. Avoid excessive bold text and bordered metadata boxes. Format multi-value metadata as readable comma-separated text, never Python list syntax.

Use 12 px panel padding, 4–8 px gaps within groups, 12–16 px between groups, and 24 px between large sections. Prefer 32 px ordinary actions, 36 px prominent commit actions, and 28 px icon toolbar controls. Button/input radius is 4 px; structural panels and grouped containers use at most 2 px. Avoid simultaneously visible nested rounded container contours within 16 logical pixels: remove redundant framing or square the inner container. This rule excludes ordinary controls, menus, tooltips and transient row highlights. Font metrics take precedence over dimensions where necessary to avoid clipping. Empty space may remain when a screen has little content; deliberate alignment and constrained group widths should keep content from appearing stranded.

Combo boxes use a shared list-style popup. Show every item when the list fits within the combo's visible-item limit, with no scroll arrows or clipped rows; longer lists scroll only after that limit. Give popup entries 4 px vertical and 8 px horizontal padding, including the Config field Type choices `enum` and `freeform`. Keep the closed combo at its ordinary compact control height. Use shared styling and Qt's item-based popup sizing for all combo boxes rather than fixing individual popup heights.

Indent subordinate checkboxes by 12 logical pixels relative to the parent control or row.

Checkbox label areas remain transparent so their text sits on the actual parent surface in every theme and container, including subtle and outlined groups. The indicator itself retains a visible square border when unchecked and a filled, marked square when checked. Keep the focus state without painting a separate background behind the label. Check new checkbox controls on their intended parent surface in both themes.
Keyboard focus on checkboxes strengthens the indicator border with `focus`; it never draws a rectangle around the label text. Selector popups retain the shared cyan row highlight and keyboard navigation without a native gray focus rectangle wrapped around the item text.

Informational tips in dialogs use a quiet `accent.soft` surface with a 2 px `accent.default` left edge, a 16 px Lucide info icon in `accent.default`, and wrapping ordinary body text. Keep the icon and text in one horizontal row with layout-managed padding; do not use a warning color for optional guidance. In the capture-folder preview, show this tip only when the selected folder name resolves to a known game. Its message suggests selecting the parent recordings folder to include sibling game folders, while allowing the selected game folder to be added as-is. Verify the tip in Light and Dark modes and with long paths or translated text.
Editing freeform registration offers use the existing command feedback font size
and muted color, with bold offer text and an underlined value. Confirmation keeps
the same hint styling, with an underlined value and regular surrounding text. Neither
state adds an icon, background or border. Separate feedback actions with ` · `.
Config game rows show the run's Editing registration count as `(+1 named value)` or
`(+N named values)` in `accent.default` cyan, on the same secondary metadata line
after YAML size. Use the shared secondary metadata font and preserve row alignment
and selection/hover states; elide long summaries and retain a complete tooltip.

### Add capture folder dialog

Use 16 px outer padding and a 550 px minimum width. Anchor the content to the top. Keep the
dialog height driven by its contents rather than a fixed target. Put the Folder label, a compact
noneditable path field, and Edit folder… on one row. The path field expands between the label and
button and uses a 16 px folder icon, a subtle surface, and a border. Middle-elide long paths so
the drive and final folder name remain visible; show the complete path in a tooltip and offer a
Copy full path context action. A completed folder selection restarts inspection and preview,
including when the same path is chosen. Cancelling the picker leaves the preview open.

After a 12 px gap, show the emphasized video total with a 16 px video icon, then the detected
game counts and an Unclassified count when present. Keep these original scan counts unchanged
when an import assignment is selected. Use aligned secondary labels and right-aligned semibold
values, with subtle row separators. Rows and their containing area share the dialog surface;
avoid bordered result cards and contrasting row backgrounds. Show at most six game/count rows
before the results area scrolls; allow it to grow when the dialog grows. Show a short, muted
explanation that game names come from the selected folder and its subfolders. Show inspection
warnings when present.

Only when unclassified videos exist, show one row with an Unclassified videos label and a
selector. Its first, default option is Keep unclassified; configured games follow. Selecting a
game assigns only unidentified videos from this import. Show a short muted confirmation with
the count and selected game, or state that the unidentified videos will remain unclassified.
Keep the Game configs… on Home guidance nearby. If no games are configured, leave the selector
on Keep unclassified. Hide the entire assignment group when every video is classified. Keep
the detected counts separate from the proposed assignment so their meaning does not shift.

Show the existing parent-folder tip only when the selected folder name resolves to a known game.
Its message should suggest using Edit folder… to select the parent recordings folder while
allowing the current folder to be added as-is. Use the shared quiet informational-tip styling.
Keep 4–8 px within groups and 12–16 px between groups. The footer has a subtle top divider,
12 px top padding, and right-aligned Add folder and Cancel actions with an 8 px gap. Keep the
footer visible when content needs to scroll on a small screen. Avoid shadows, gradients,
unnecessary framed blocks, and fixed heights that clip text.

For other compact read-only result forms, align the first data label with its section heading.
Use two columns: left-aligned secondary labels and right-aligned semibold values. Keep each
label/value pair in one row, with a subtle divider beneath each row. Place the rows on their
containing surface; do not offset a separate row background from the heading or leave the data
as one prose label.

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
- Navigation sits at the top of the application with no menu bar or outer top gap; the workspace beneath it has its own 12 px inset. Navigation uses a continuous `surface.panel` strip with a subtle bottom divider and compact rectangular text-only tabs. Labels are 14 px medium; active labels are semibold. Inactive tabs use secondary text, transparent backgrounds and a neutral hover surface. The active tab uses primary text and a straight 2 px `accent.default` bottom indicator; it may use an extremely subtle active surface but must not also use strong side borders or accent text. Theme and Settings remain right-aligned utilities.
- Inputs use `surface.control`, a subtle border, primary text, muted placeholders, a quiet neutral hover and an unmistakable focus treatment. Use a 2 px focus ring where QSS and geometry permit without layout movement; otherwise use an equivalently clear inset/outline treatment. The command bar uses the same idle styling and `component.commandValid` when valid. No neon glow or native dotted focus rectangles. **All text boxes on every page and in every application-owned dialog must release keyboard focus when clicking outside the box**, including labels, blank surfaces and controls that do not accept focus. This includes Browse custom title/output folder fields, command/search fields, multiline editors, inline table editors, editable combo boxes and spin-box text inputs. Retain entered text and existing save/validation behavior; the clicked control still performs its normal action. Clicking inside the field or its own child controls retains normal editing; popup menus keep their own focus. Restore applicable page shortcuts once text input loses focus. Focus behavior follows main specs §13.2.
- Optional ghost-expanded command aliases use the input's primary text color for matched typed letters and `text.muted` for decorative letters in both themes. Preserve the command bar's existing input, selection, focus, and validation styling.
- Triage controls are neutral unless active: Keep uses success-muted/success; Discard uses danger-muted/danger; Pending uses pressed-surface/strong-border/secondary-text.
- Project management uses the Export selector, New project and More menu. Editing uses compact current-clip membership and review controls. Keep destructive actions in the management menu; project deletion behavior follows main specs §14. Every icon action has a tooltip and accessible name.
- Use vendored Lucide SVGs: 16 px utility icons, 20 px transport icons. Default/hover/active/disabled icons use secondary/primary/accent/disabled text tokens. Render Lucide icons at three times each target device-pixel resolution and smoothly downsample to their specified display size by default, including at high DPI; keep device-pixel-ratio handling in the shared `icon()` helper and follow [Small icon rendering](#small-icon-rendering) for final bitmap selection and placement. Tooltips include actual shortcuts when applicable.
- Rating uses 18 px SVG stars with 4 px spacing, gray unfilled stars for a populated rating, gold filled stars and lighter gold hover preview. Keep small `x` clear action visually adjacent; a valid drafted rating shows static dull-yellow stars and a disabled clock in its place. Muted rating hints share this row; rating interactions follow main specs §13.7.
- Metadata-style clip lists show game, an optional bold `R1`–`R5` label, capture-folder name, an optional yellow HDR label and verdict in that order. Rating uses the theme's five-step low-to-high scale; unrated clips omit that segment. Reserve space for HDR before eliding long folder names in the middle. Browse retains capture time and folder on its second line, followed by the same HDR label. The full tooltip includes HDR when present. HDR thumbnails use SDR tone mapping and refreshed cache keys.
- Video is black. Use a **7 px timeline groove** with a larger hit area, pale teal remainder and strong teal elapsed section/playhead. Use focus-cyan saved I/O markers with bold I/O labels and accent range tint at 18% opacity. Pending In and Out have distinct bold labels (·I and ·O). Timeline and volume slider widget backgrounds are transparent so only their grooves, handles and markers are painted. The volume slider uses an 18 px widget height, 3 px groove, 10 px handle, quiet teal remainder and medium-teal level; center it optically with the volume icon and time text. Transport/audio/time controls remain directly below.
- Scrollbars are 8 px, transparent-track, neutral-thumb with lighter hover and no arrow buttons. Splitters have a 1 px visual divider and a wider interaction region, with stronger hover color.
- Tooltips appear after a 200 ms hover delay throughout the application. They use `component.tooltip`, 12 px text, a default border, theme-appropriate tooltip text, compact 3 px horizontal padding and optical vertical padding of 0 px above / 2 px below, with 4 px corners. Secondary metadata recedes; populated title tag prefixes use the theme's gold/tag role in bold at 1 px below the surrounding title size and remain hidden when empty. Valid commands use `component.commandValid`; incomplete, invalid and briefly saved commands use warning, danger and success bottom borders respectively. Keyboard focus retains its teal outline; other command backgrounds stay neutral. Unset rating uses the existing danger color for star outlines only, with no background highlight.
- In the command checklist, YAML-inferred fields use `◇` in `accent.default` while previewing. Recent command history renders inference provenance after the normal command in the 11 px muted helper style.
- Checklist field tooltips retain the shared tooltip styling. Show long enum value lists in compact columns, with aliases beside their canonical values and enough width to keep each value readable. Italicize alias text only; keep its parentheses upright.

Every applicable interactive component has intentional rest, hover, pressed, focused,
disabled and selected states. Ordinary text targets at least WCAG AA 4.5:1 contrast, and
important focus/control indicators target 3:1 against adjacent colors. These are practical
design checks rather than a claim of formal application-wide WCAG conformance.


## 3. Application shell and side panes

### Navigation and workspace

```text
Home  Browse  Session  Editing  Export  Config   [stretch]   Undo Redo   Output Jobs Theme Settings
------------------------------------------------------------------------------------------------------
Left pane: shared list and filters | Main content: page/player and information
```

Use two resizable columns on every page. There is no right Projects pane or hanging tab. Preserve the library width as navigation changes; recovered space and window growth go to main content. Normal and maximized windows use the same composition. Utilities use shared icon styling, tooltips and accessible names. Follow main specs §9.4 for reset and persistence behavior.

Output Jobs sits between Redo and Theme as an icon-only 26 px navigation utility with no menu arrow. Its icon and outline share a vertical center; the icon turns cyan while output jobs are active, and its tooltip gives the outstanding count. Its compact dropdown shows each job's name, phase, progress bar and Cancel, Resume or Dismiss action. Failures use danger text. A successfully submitted Share briefly uses the shared success palette on its initiating control.

Populated Output Jobs uses compact cards with a subtle surface and border. Each card shows Share and the clip's game or Export and the project name, followed by the planned Share filename or the Export clip count in secondary text. Actions align at the top right. A colored status dot, state and percentage precede the current phase and a thin full-width progress bar. An icon button to the right of the phase opens the output folder; completed Share jobs show a distinct file-search icon and select their generated file in Explorer. Project Export jobs show a folder-open icon and open the export folder without selecting a file. Running uses the accent color, completion uses success, failure uses danger, and queued or cancelled states use muted gray. Cards stack with a small gap.

The dropdown has a compact heading and a top-right Close icon. An automatic opening for Export submission or resume stays open until dismissed, and starting Export stops any existing auto-close timer. Share-only automatic openings close after four seconds unless the menu receives pointer or keyboard input; manual openings do not start this timer. Successful Share and Export completions mark the navigation icon outline with status.success until the icon is clicked or activated by keyboard. This outline takes precedence over active/attention borders, including hover and pressed states, while preserving existing icon and background colors. Keep the indicator across popup opening/dismissal and subsequent job activity; later successes mark it again. Failed/cancelled jobs retain existing attention behavior and do not set this indicator. While the current clip has a queued, running, or cancelling Share, its Browse button reads **Share in progress** with a spinning disabled icon, and icon-only Share controls show the same status in their tooltip and accessible name. After a visible Share completes successfully, the Browse button reads **Shared** with a checkmark on the right; Browse fullscreen and Editing icon controls show a green checkmark with a **Shared** tooltip. These controls use the shared success palette and stay disabled until the clip or pane changes.

### Left pane

Order search/filter controls, compact heading/action row where required, expanding clip list, then page-specific footer. Home and Browse place Clips, Games and Projects menu buttons in one row beneath search, followed by availability and capture-time sort icon actions at the right. Session Editing uses a Session clips heading with Next pending action. Atomic single-clip Editing replaces that heading with **Single clip**, hides Next pending and the progress footer, and shows exactly one card. Position the Editing header title and count at a 14 px inset; align its action to the card edge and footer text to the card title. Library controls sit on a flat toolbar surface slightly darker than the list, spanning the full pane width from its top edge without a divider; use equal 8 px top and horizontal padding, 8 px between search and filters, and aligned search/filter edges. Metadata clip rows shift their title text right to make room for the standalone verdict dot. The list body retains an 8 px right and 4 px bottom margin. Home, Browse and Session have no top margin between the toolbar and clip list; other panes retain a 4 px top margin. The sidebar uses shared 2 px structural corners. These are component-specific offsets, not general panel-padding replacements.

Keep lists tall; command area belongs below center, not across entire window. Hide empty error rows. The Editing header uses the same flat toolbar surface across the pane width, with equal visible top and left insets for its title. Center the title, numeric position, and right icon vertically; lower the position text optically by about 1 px to align its writing line with the title. Session progress text sits at the bottom left with an 8 px inset rather than aligning to clip titles. Filters and footer visibility follow page requirements.

When the final-clip pending reminder is active, outline Next pending clip in `status.danger` with a 2 px stroke inset by 1 px, the shared control radius and a smooth three-second opacity pulse from full to 25% and back. Preserve its normal icon, hover, pressed and focus styling. Append ` · N still pending` to the footer, using danger color only for the pending text and retaining the existing secondary font. Stop the animation while the button is hidden; atomic Editing has neither reminder nor footer.

Config's Existing game configs heading uses the same full-width flat toolbar surface and compact pane-heading role as Session clips, with a 14 px title inset, separated from the list by a subtle bottom divider. Put compact New game and Reload icon actions at its right edge, with accessible labels and tooltips; leave the bottom of the pane empty. The game list sits directly beneath the header on the continuous sidebar surface, flush with both side edges of the pane. The first row's painted surface meets the header edge without a top gap, and adjacent row surfaces have no vertical gap. Each row shows the canonical game name in primary text above a muted display code and total configured field count, including reserved fields. Invalid YAML uses its filename and an **Invalid configuration** secondary line. Center the two-line text block vertically with roughly 8 px of space above and below it. Follow the shared library-list treatment for a subtle selected surface spanning the list width, a 3 px cyan left accent flush with the list background's left edge, a quiet hover surface, and keyboard focus; size rows to contain all painted content without overlap.

Search is the primary filter entry. The three filter menu buttons beneath it share height,
radius, padding, border treatment and arrow placement. Menus use persistent checkboxes for
multi-selection. Allow button widths to follow their current labels. Keep the toolbar plane flat without an enclosing rounded card. Search keeps
rounded input styling with a quiet resting border, stronger hover border and accent focus ring.

### Clip cards



Use one shared delegate in all left-pane library, Session and Export views. Home, Session and Editing clip rows have a 53 px body; Export uses that same base with one additional secondary-text line for membership and blocking reasons. Browse keeps 64 px. All have a 1 px inter-row gap and 7 px horizontal padding. At rest each row is transparent against
`surface.sidebar`. Every clip view puts a short, subtle separator at the top of each row after the first, inset to the text edge. The separator belongs to that row; suppress it when that row or the preceding row is hovered or selected, so both boundaries of the highlight are clean without painting into a neighbor. Each row must
read as a dense file/media browser row, not a stack of rounded cards. Hover receives a soft
neutral fill. Browse selection may use a 3 px radius because its pale accent surface is transient; Home, Session, Editing and Export selection uses square corners.
Grow only as required by font metrics.

Home, Session, Editing and Export line one uses 13 px regular muted game codes and structured metadata, with a 14 px semibold primary mainline or filename fallback. Their second line uses 11 px for the canonical game name (or Unassigned), optional rating and capture-folder name. Browse retains 13 px regular codes and metadata, 14 px bold mainline and fallback, and 12 px details. Export matches Editing card typography, including rich-text codes, metadata, mainlines and filename fallbacks. A quiet folder icon and In project / Outside project text occupy its third line, followed by any blocking reason; retain complete text in the tooltip and accessible description. Separate structured metadata and mainline with a muted ` | ` when both exist. Do not repeat Keep, Discard or Pending as text. Keep the two lines together with a 3 px gap on Home, Session, Editing and Export, or 2 px on Browse, and center their actual rendered height in the row. On Home, Session and Editing, position the text block 1 logical px below its former optical offset and the verdict dot 2 px lower to align it with the visible capture time; keep the Home/Session time at its current offset. Export uses the same text and verdict-dot alignment as Editing. Put the 8 px verdict dot on its own at the left of the text block, with roughly 9 px between the dot edge and text; Home and Session keep a compact relative capture time right-aligned in the row with no overflow control following it. Browse keeps the dot beside line two. Reserve metadata width for the folder and an amber Unavailable label before eliding the game name. Long titles elide based on their rendered rich-text spans; no horizontal scrollbar. Tooltips show the complete title, metadata and source path.

Hover uses `surface.hover` with rounded corners on every clip row. Selection uses `accent.selection`; Home, Session, Editing and Export add a full-height 2 px `accent.default` left indicator, while Browse uses a thin cyan outline on the thumbnail without an outer left indicator. Browse hover and selection fills begin on the 8 px control guide, with the thumbnail inset another 8 px. Home, Session, Editing and Export selection and focus boundaries have square corners; Browse keeps rounded right corners. In every clip view, hover and selection fills cover the row's top separator and reach the bottom row boundary; the next row omits its separator while the preceding row is active. Both Export membership views retain accent selection. The selected fill must remain soft rather than becoming a saturated color block. Keyboard focus uses a distinct focus boundary. Presentation data must use explicit roles, not substring matching against visible text.

When additional cards exist beyond a visible list edge, overlay a non-interactive 16 px vertical gradient at that edge, fading from `surface.sidebar` to transparent toward the content. The fade sits above card content without consuming layout space and disappears completely at the corresponding start or end of the list. Do not add chevrons or borders. On the first opening of each applicable navigation page, position a selected card that is not first with only the bottom third of the immediately preceding card visible above it. Preserve the viewport on later selection and navigation changes.

Browse uses a 64 px row with an 84 × 48 px letterboxed thumbnail before the two text lines. It shows relative capture time and capture-folder name on line two instead of game/triage text and retains the shared verdict dot. Unavailable adds a separate amber warning icon beside its label. Neutral thumbnails appear while loading or when extraction fails. Content and selection behavior remain governed by main specs §§9.5, 10.1 and 12.2.

### Project controls

Export owns project management. Place the project selector, New project and More menu in one responsive row above project-wide Ready / Pending / Blocked / Skipped buttons and video. Reserve spacing after More for a shared circle-help icon button with a tooltip and accessible name; it opens the generic project assembly/export guide using the existing help-dialog styling. The left pane contains Assigned / Available with the adjacent availability icon toggle, search, game/verdict/sort controls, optional From / Through dates, followed by membership actions and the shared list. Available actions are Add selected, Skip selected and Add all matching in that order. Assigned places Remove selected, All members and Remove all matching on the same row, with Skip hidden. All members replaces Skip selected's middle position and has no separate row; retain its short label and put active-readiness context in its tooltip and accessible name. Use shared spacing, typography and catalogue-confirmation dialog styling for large matching removals. No selected project shows a clear creation/chooser message and disabled membership/export actions.

Editing places a single Projects menu after Change game on the existing verdict row. Its checkmarks control current-clip membership. Right-click enables collection into one project, shown by a right-aligned Lucide refresh-cw icon on that project row and a cyan outline on the Projects button; another right-click on the same project turns Auto off. Preserve native menu interaction and shared hover and selection colors. Draw a 16 px checkmark centered in the existing 24 px column with 4 px space on either side: the item’s left edge and a vertical divider are symmetrical across the checkmark. Offset the checkmark 2 px and the collection icon 1 px below vertical center for optical alignment with the adjacent text. Project names start 8 px after the divider. The collection icon has the same 8 px inset from the right edge, with 8 px between it and the name. Reserve these columns through item padding, without adding Qt’s checkmark gutter or widening the popup outside its item rectangles; row highlights span the full item width up to the popup border. Tooltips describe the gestures and collection state. The working-title row has no destination or Auto widgets. No new Editing rows are added.

Export places Editing's shared icon tools on the existing right-aligned transport row beneath the timeline: Set In, Set Out, Clear range, Share, a 1 × 20 px vertical divider, and pencil Edit clip…. Match Editing's icons, tooltips, dimensions and spacing. Reuse the reserved inline range-warning slot, error typography and warning icon; completed Share uses the shared success state and active Share uses the existing spinner. No extra control row is added.

Export preview titles match Editing's widget font and rich-text title roles, including filename fallback. Source filenames use plain secondary text. Membership, verdict and row selection are separate visual/accessibility states. Keep blocking reasons legible in tooltips when row text elides.

Export's From/date and Through/date pairs use a shared grid with stretching input columns, shared spacing and natural label widths; do not measure or fix input widths. Availability is controlled beside the membership-view selector; there is no checkbox row below the dates. Reuse Editing's shared ghost-input renderer for the inferred year prefix, using `text.muted` for the decorative year/hyphen and the normal primary text for entered month/day. Preserve the native text baseline, selection and clear-button alignment; reserve the clear button's space when painting ghost text. Do not add decorative leading zeros to month/day.

Put the estimated export-size label immediately left of Export… in the existing bottom action row. Right-align the row with layout stretch, vertically center the label and button, and use the shared secondary-text role and storage-size formatting (two decimal places, binary GB). Preserve shared spacing and the player's available height; do not add a separate estimate row or fixed label widths. Functional estimate scope follows main specs §16.

Export setup is an application-owned modal dialog. Use ordinary destination controls, per-game field/prefix checkboxes in a content-height outlined group and Group by Rating. Fit the prefix and all wrapped field rows on screen without scrollbars or unused space inside the outline; update its height when the selected game or available width changes. Use the shared outlined-group role and 12 px inner margins. Keep readiness counts and blocking-clip details out of this task-creation dialog; job failures belong in Output jobs. The final Export action uses the primary role; Cancel and folder selection remain secondary. Match disabled, focus and hover states across Light and Dark modes.

## 4. Sparse-page composition

### Home / Capture folders

Align the Capture folders heading with the Session overview at a 4 px top inset. Preserve Capture Folders behavior and all existing information. Each watched folder is a
compact typographic group rather than raw diagnostic-looking text. The folder path is primary;
scanning state, total clips, and folder size are secondary; detected-game counts are tertiary.
Show newly discovered clip size in the same cyan accent as new clip counts. Align labels and
values consistently and use spacing before introducing containers.
Show per-game removed-entry counts since launch in `status.danger`, separate from cyan new counts.
A quiet surface group is acceptable when multiple folders need stronger separation, but do not
turn every statistic into a card. The explanatory sentence remains tertiary and wraps.
Place Game configs… immediately after Add folder… in the capture-folder control row. Give all
four controls the same outer height and padding. Add folder… has a slightly brighter neutral
surface (`surface.prominentNeutral`), a 1 px `border.default` outline, semibold primary text,
and an `accent.default` folder-plus icon. Its hover uses a soft accent fill and cyan border;
keyboard focus uses the focus-colored border. At rest it must not resemble a selected control.
Game configs… and Rescan retain the ordinary neutral button treatment. More… is a text-only
ghost action with secondary text, a transparent resting border, and a quiet neutral hover.
Keep its menu indicator hidden and its accessible tooltip describing folder actions.

### Session

Keep Session setup as a compact, fixed-height panel below the overview with two states. An
active Session shows its position and verdict progress with End session. With no active Session,
show a clear inactive state followed by Scope, Selected / First N / All, the count field and
Create Session. The setup panel fills the center workspace without changing the clip-library
pane. Editing navigation opens the active Session at its saved position.
Give the setup heading more space above than below. In the active state, show a distinct,
square-cornered, thicker bar divided into equal segments in frozen Session order, one per
clip. Keep is green, Discard red, Pending muted gray, and an unavailable source overrides
the visible verdict with striped warning yellow. A cursor and attached processed count and
percentage mark the trailing edge of the rightmost decided clip, even if pending clips
precede it; with none decided, place the cursor at the left edge. Keep exact labeled counts
below the bar, adding a yellow Unavailable count when needed. Unavailable decided clips
still count as processed, though their verdict is hidden in the bar and verdict counts.
Keep the numeric current position in Editing only, not in this Session summary.
Render the processed label as a semibold cyan chat-bubble tag with a bottom pointer
touching the cursor and high-contrast text. Keep the body sides vertical, including at
the bar's left and right limits; shift the body within the bar at those limits while
the pointer continues to target the cursor. Paint segments flush together without
outlines or gaps.

Place the library overview above Session setup on an open workspace surface with no enclosing
boxes. A subtle 1 px horizontal divider separates the pinned setup area. Use 12 px horizontal
padding and 4 px top/bottom insets. Keep the overview heading row at the shared
4 px top inset, 4 px above the search row's 8 px toolbar inset. Allow the 22 px overview heading
its full 32 px height.
Retain 22 px section headings. Session preserves the current library width and uses the available main column; there is no forced-open project pane.
Scroll the overview vertically when its rows exceed the available height while keeping Session
setup visible at the bottom. Use visible compact segmented period controls, a 16 px full-width aggregate verdict bar and 12 px variable-length game verdict bars, exact text counts, and represented source size beneath each bar. Keep uses success green, Discard danger red and Pending
muted gray; color is never the only state indicator. The aggregate row is visually stronger
than game rows without turning individual statistics into cards.

Empty space is valid on both pages. Content should be anchored to shared page edges and grouped
with intentional widths so it does not appear accidentally stranded in the upper-left corner.

## 5. Video and playback controls

Reuse [Player](../src/dfsorter/playback.py) across Browse, Editing and Export. Do not build separate transport variants for equivalent actions. Browse adds a pencil **Edit clip…** action after Clear range and before its trailing fullscreen action. Both use shared icon-tool-button styling and accessible names. Fullscreen uses maximize to enter and minimize to exit. It retains the existing player widgets and moves timeline and controls into a bottom overlay anchored to the video edge. A compact top overlay shows the current working title near the top edge, with 8 px top and 24 px left padding. Its black background fades vertically to full transparency slightly below the title, including when the title wraps. Size its metadata and game code at 17 px, mainline at 21 px, and tag at 20 px; retain the same colors and weights as the corresponding Editing title roles. The bottom overlay is fully transparent, with no extra space above the timeline widget. Keep near-white text in both overlays. Fade both overlays in over 60 ms when revealed by playback, seeking, mouse movement or focus changes; fade them out after 1.7 seconds of inactivity, including while paused, and hide them while the application is inactive. Centered playback, seek and volume feedback uses a 112 px translucent dark circle and 52 px near-white icon, then fades out. The volume percentage uses a lightly translucent 88 px square, centered at one fifth of the video height and fading with the volume icon. Surrounding UI and outer padding remain hidden.

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
Page and clip loading covers use the workspace surface so the covered area blends with the surrounding page. Export clip loading covers only its video surface, preserving project controls, readiness, titles and library controls during Assigned / Available switches. Apply the display-corrected video geometry after the preview frame and a valid display size are ready, then warm the native surface with its visible region clipped before revealing the page. Allow at least 100 ms for each player's first native show; later clips wait two display refresh intervals. Errors and missing sources reveal without this delay.

Batch visible layout and window-state changes during transitions. Native video surfaces can remain visible while Qt widget updates are paused. For fullscreen entry and exit, use a solid black transition surface while settling window geometry, pane sizes, video and controls; reveal the destination only after its first settled paint. Do not replace live video with an SDR screen capture during the transition; it changes the appearance of HDR playback. Page and clip transitions likewise reveal prepared content together.

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
[Keep] [Discard] [Pending] [Change game] [Projects]
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

The field-checklist row includes a right-aligned cyan tip with a small info icon. Field markers, tip text and tip icon share the Settings-selected 11, 12 or 13 px size; default to 12 px. Measure the current field text's unwrapped width, let the fields use that width when available, leave a 12 px gap, and give the tip the remaining row width. Recompute the field width as its text or size changes; allow wrapping when the window is too narrow. Keep the tip on one line; elide it only when the remaining width is insufficient and show the full text on hover. The tip does not add a separate row or shift the command input.

Retain bottom command area within center column and full-height left list. The command-area top margin is `8 + fontMetrics().lineSpacing()` logical pixels: intentional separation, not empty content bug. The wrapping shortcut line uses the 11 px tertiary helper role so it reads as reference rather than task content. Keep it to the core workflow: Space Play/pause, I/O Range, Enter Metadata, Shift+Enter Verdict + next, and ? All shortcuts; atomic Editing substitutes Shift+Enter Save and return. Keys use semibold primary text and actions use muted text. Feedback line and checklist reserve enough height to prevent baseline jumps. Put the range warning immediately left of Set In and Set Out in the player controls row and retain its slot when valid. Do not apply empty-row collapse indiscriminately to these reserved elements.

Triage/rating groups remain compact and left aligned; help action anchors right. Projects follows Change game on the verdict/game row and combines membership checkboxes with right-click collection. Its active collection state uses a static cyan outline; the menu marker uses the shared Lucide cycling arrows at the right edge. Atomic Editing retains staged membership controls but disables collection changes, with the collection marker muted. Description uses selectable plain text on a separate row. Functional behavior and field availability follow main specs §13.

The visual order is video, playback, working title and source context, triage/game/project status,
rating, structured metadata and description, then the separated command/help region. Keyboard
hints and technical explanations remain readable but tertiary. Rating stars retain the dedicated
gold semantic family. Compact clip-list labels use their separate five-step scale and always
retain the explicit `R1`–`R5` text cue.

Atomic single-clip Editing preserves this composition. Put compact **Save and return to clip** and red **Revert** actions on the working-title row, aligned to its top/right edge. Replace the bottom-right cyan rotating tip with a static warning using the shared warning color and a leading warning icon. Hide Add to project + Next; disable Previous/Next; Undo/Redo applies to staged clip actions. Membership checkboxes remain available in the compact Projects menu; right-click collection changes are disabled. Global project management belongs to Export.

Editing already has enough rows, and every existing row serves a specific purpose. This applies to both Session and atomic single-clip Editing. Do not add rows for formatting, grouping, spacing or relocating controls: additional rows reduce the video player's height. Reuse the existing rows, compact spacing and inline controls while retaining their semantic purpose. New functional requirements that cannot fit the established composition require an explicit layout decision before introducing another row.

### Export and Config

Export's navigation toolbar places the **Assigned / Available** selector and an icon-only unavailable-source toggle in one row. Both view labels append a parenthesized default-filter clip count. The Assigned option appends ` - ` and the current project name before its count; elide long labels in the middle so their trailing count remains visible without widening the navigation pane, and retain the complete label in its tooltip. Let the selector fill the remaining width; use the shared compact toolbar button size and icon size, with the existing control gap and vertically aligned centers. The toggle uses eye-off when hidden and eye when shown, a transparent resting border, and a cyan outline only when checked. Retain shared hover/pressed fills and tooltip/accessibility text. Remove the former checkbox row; capture-date labels and inputs retain their aligned grid.

Preserve existing workflows and page-specific constraints. Apply the same shared surface,
typography, form alignment, button hierarchy and state styling used elsewhere. Export's final
commit action is primary; setup and utility actions remain secondary. The export setup game selector uses the shared input style and a code plus live example filename, with long labels elided in the middle and full text in the tooltip. Underline the complete mainline portion of live filename examples in both the closed selector and popup, retaining the shared font, color, baseline, hover and selection styling for all other text. Filename options place Game code prefix [CODE] on its own first row. Remaining field checkboxes pack horizontally at their natural widths in display order and wrap to additional rows as space requires, using shared 8 px spacing without fixed grid columns. Fit the options outline to its occupied rows and hide outgoing controls immediately on game changes. Config uses a game list
in the left pane and compact Identity, Fields, and Title & review tabs in the center. Its
single Save action is primary; Revert, Reload and row actions remain secondary. Keep structured
tables legible in Light and Dark without adding decorative cards merely to occupy space.
Config's Game configurations heading uses the shared 22 px section-heading row with a
24 px file-cog icon, aligned to the Home and Session workspace heading inset.
The Config game navigator places Existing game configs, New game, Reload and Search games in one flat
toolbar surface above the list. Use the shared 8 px search inset on both sides and
6 px top inset, an
8 px gap between the heading row and search, and a subtle bottom divider. Align the
search with game-row content and keep the list rows and selection styling unchanged.
Config Revert changes in place to a red Confirm revert button while confirmation is armed, using the shared danger role. Outside interaction restores its secondary appearance.
Config tables use consistent header typography regardless of column selection. Brief
wrapping notes beneath tables use the shared secondary-text role to explain command syntax.
Selection highlights only the current cell, with at most one table selection across
the editor. Empty table space and clicks outside tables clear the selection; row
action buttons retain it. Clicking a selected cell opens its editor. Double-clicking
empty table space adds a row and opens its first cell for editing. Adding a row or
starting cell editing reveals the complete row height in both the table viewport and
any enclosing scroll area. The first keystroke in an active editor restores that
visibility after manual scrolling; focus and entered text stay in the active cell.

## 7. Qt implementation patterns

### Shared styling and text

Use `theme.role()`, `theme.font()`, `theme.title_styles()`, `widgets.tool()` and `widgets.icon()`. Match widget font and rich-text spans together; matching only `QLabel.font()` misses embedded sizes/weights/colors. For rich user content, escape text before insertion. Set `Qt.TextFormat.PlainText` for literal descriptions/filenames and explicit `RichText` for formatted titles. Use `setWordWrap(True)` where text may grow.

Reusable appearance belongs in theme/shared component, not new local stylesheet. Existing local exceptions do not establish new defaults. Lucide source library is `node_modules/lucide-static/icons`; vendor only used SVGs into `resources/icons`, retain license, load on demand through `icon()`. Do not bundle whole library or access node_modules at runtime.

### Small icon rendering

Small icons, especially the 11–13 px Editing tip and notice icons, require inspection at their actual display size. Rendering a larger source improves sampling but cannot restore detail that does not fit into the final pixels. These requirements govern shared rendering and custom-painted consumers:

- Select or render the bitmap for the destination widget's current device-pixel ratio (DPR). Do not rely on an application-wide or implicit DPR when extracting a pixmap: on mixed-scale monitors it can select a bitmap for a different screen. Pass the destination DPR through the shared rendering path, keep the pixmap's DPR metadata consistent with its physical dimensions, and refresh cached consumer pixmaps when the destination screen or DPR changes. Cache selection must account for logical size, DPR, theme and icon state.
- Downsample the supersampled source to the final physical pixel dimensions for that destination. Avoid subsequent reduction or enlargement of the cached bitmap during painting. For example, a 12 logical-pixel icon at 100% needs a 12×12 physical-pixel bitmap; selecting an 18×18 bitmap for another screen and reducing it again adds filtering. Increasing the initial supersampling factor does not correct this mismatch.
- Use a reduction filter that integrates source pixel coverage, such as Qt's `QPixmap.scaled(..., SmoothTransformation)`. A `QPainter.drawPixmap()` reduction with `SmoothPixmapTransform` can undersample fine details even when the source is supersampled; the info dot and warning punctuation must survive in the final bitmap. Verify those details rather than treating the presence of a smooth-rendering flag as evidence of quality.
- Align the final bitmap origin to the destination's physical pixel grid while preserving the intended optical alignment. Centering with `(row_height - icon_size) / 2` can produce a half-pixel origin; integer logical coordinates also need checking at fractional DPR. Account for the painter's final transform. Smooth bitmap filtering at a fractional origin can spread already-antialiased edges over additional pixels. Distinguish bitmap placement from vector stroke alignment; do not apply a blanket half-pixel offset or disable antialiasing as a universal fix.
- Evaluate stroke width and internal detail at the specified size. A Lucide SVG with a 24-unit viewBox and a 2-unit stroke has a 1 logical-pixel stroke at 12 px; its circle, dot and short lines can lose contrast through antialiasing and repeated filtering. Correct DPR selection and placement before considering artwork changes. If legibility still fails, use a simpler suitable Lucide glyph or a reviewed shared optical adjustment; changes to prescribed sizes or approved styling require coordinated specification/theme updates.
- Verify the final painted widget, not only the SVG or intermediate bitmap. Inspect at 100% and, when changing scaling behavior, 125%; follow the review checklist's scaling limits. For changes to DPR handling or caching, also check screen transitions with different DPRs, using a focused simulation if necessary. Confirm that resizing into odd and even row heights does not introduce avoidable blur, and compare relevant theme and control states. Judge legibility at native size; enlarged pixel inspection is diagnostic evidence only.

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
- Compare normal/maximized windows at 100% scaling for affected components. Check 125% only when a change specifically affects display scaling; do not run 150% verification. Inspect representative menus/dialogs when shared styling changes.
- Capture the same representative populated, empty, focused, disabled and selected states in Light and Dark. Check System mode against both operating-system appearances and verify live system changes. Theme switching must not leave stale icons, rich-text colors, custom-painted controls, menus or already-open dialogs.
- Audit contrast for ordinary text, secondary text, focus boundaries, selected items, destructive states and unavailable warnings. Do not approve a palette solely from isolated swatches; evaluate colors on their actual adjacent surfaces.
- Run smallest relevant existing checks for UI edits, using isolated catalogues/generated media where needed. Broaden only for concrete impact. Documentation-only changes need diff/link review, not runtime tests.

Existing checks include `test_browse_form_alignment_and_title_style` and `test_browse_layout` in [UI tests](../tests/test_ui.py). [Visual fixture script](../tests/visual_design.py) supplements inspection and captures Browse, but its captures are not exhaustive acceptance. Screenshots may predate source: verify provenance before using them as reference.

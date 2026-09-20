# DFSorter UI Layout Guide

## 1. Purpose and authority

Stable reference for adding or reviewing UI features. Covers layout, typography, colors, component appearance and visual interaction states across every page, menu and application-owned dialog. Native file pickers retain operating-system styling.

This guide owns reusable visual rules. [Main specification](dfsorter-specs-clean.md) owns feature behavior, shortcuts, data semantics and page-specific requirements. Read both before UI work. Explicit page-specific constraints are exceptions, not defaults for new pages. Resolve conflicts explicitly; do not silently redesign approved layouts.

Browse and Editing are reference compositions. Inspect current implementations and equivalent controls before changes; incidental local styling is not permission to duplicate it. [Shared theme](../src/dfsorter/theme.py) owns implementation tokens, fonts, palette and QSS; [shared widgets](../src/dfsorter/widgets.py) own icons, clip cards and rating presentation. Reuse these primitives. Changes to approved values require coordinated guide/theme updates.

Use restrained neutral-dark desktop styling: dense, flat, low-saturation surfaces, subtle borders, quiet sidebars, strong alignment and large video area. Avoid gradients, oversized controls, pill buttons, neon styling, large rounded cards and unnecessary panel borders. Compact clip cards are intentional border exceptions.

Keep implementation history, screenshots and verification results outside this guide. Record completed work and user acceptance separately in [feature tracking](../docs/features.md). [First graphical touchup](legacy/first-graphical-touchup.md) is archival motivation only, never implementation authority.

## 2. Visual foundations

### Color tokens

| Role | Tokens and values |
| --- | --- |
| Backgrounds | `bg_app #1E2228`, `bg_panel #181C22`, `bg_panel_alt #15191F`, `bg_surface #252B33`, `bg_surface_hover #2D3540`, `bg_surface_pressed #343E4A`, `bg_input #12161C`, `bg_video #000000` |
| Borders | `border_subtle #2B323C`, `border_default #3A4350`, `border_strong #4B5665`, `separator #303741` |
| Text | `text_primary #E6E9ED`, `text_secondary #A9B0BA`, `text_working_title #C7CDD5`, `history_available #B8BFC9`, `text_muted #77808C`, `text_disabled #59616C`, `text_inverse #111317` |
| Interaction | `accent #41B8C7`, `accent_hover #56C9D7`, `accent_pressed #3096A4`, `accent_muted #17373D`, `accent_selection #244A53`, `accent_focus #59D2E2` |
| Success | `success #62C98D`, `success_muted #1C3A2A` |
| Warning | `warning #D9A441`, `warning_muted #3A2D16` |
| Danger | `danger #D9686A`, `danger_hover #E47D7F`, `danger_muted #3A2022` |
| Information | `info #6AA9E9` |
| Rating | `rating_filled #E8C45A`, `rating_hover #F0D16F`, `rating_empty #69717D` |
| Component colors | `command_focus #141B21`, `command_blue #172B40`, `tag_color #F0D16F`, `timeline_track #3A424D`, `timeline_progress #617080`, `scrollbar_hover #56616F`, `tooltip #11151A` |

Cyan means interaction, focus, selection, active project, playhead or I/O markers. Green means Keep or success; red means Discard, destructive operations or blocking errors. Warning amber means incomplete requirements or unavailable sources. Gold rating tokens are reserved for stars. Undefined triage uses muted gray. Always retain text or shape cues in addition to color.

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

Ordinary controls and menus use 13 px regular; secondary metadata uses 12 px; card metadata uses 11 px. Editing working titles use 13 px regular metadata in `text_working_title #C7CDD5`, 13 px regular game codes and separators in `text_muted`, and 16 px bold mainline in `text_primary`. Separate metadata and mainline with ` | ` only when both are present. Retain wrapping. When no populated field contributes to the configured title display order, show the original filename followed by a smaller, secondary-colored “— Working title not set” hint. Section headings use 20 px semibold. Compact pane headings use 14 px semibold primary text. The Session clips header has a transparent background, aligns its title to clip-card text, and aligns its right action to the card edge. Avoid excessive bold text and bordered metadata boxes. Format multi-value metadata as readable comma-separated text, never Python list syntax.

Use 12 px panel padding, 4–8 px gaps within groups, 12–16 px between groups, and 24 px between large sections. Prefer 28 px ordinary controls and 24 px compact controls. Button/input radius is 4 px, panels 0–3 px. Font metrics take precedence over dimensions where necessary to avoid clipping.


### Controls and visual states


- Neutral buttons use surface/hover/pressed colors and default borders. Primary actions use accent-muted fill and accent border sparingly. Destructive buttons use danger text/border with danger-muted fill. Disabled controls use panel background, subtle border and disabled text/icon colors; avoid fading whole widgets into illegibility.
- Navigation sits at the top of the application with no menu bar or outer top gap; the workspace beneath it has its own 12 px inset. Navigation uses a continuous dark strip with a bottom divider and compact rectangular text-only tabs. Labels are 14 px medium; active labels are semibold. The active tab matches the workspace background with a straight 2 px cyan top edge, subtle side borders, and no contrasting bottom border. Inactive labels use secondary text and surface hover. Projects and Settings remain right-aligned utilities.
- Inputs use input background, subtle border, primary text, muted placeholders, default hover border and focus-cyan border. The command bar uses the same idle styling and `command_focus` background when focused. No neon glow or native dotted focus rectangles. Focus behavior follows main specs §13.2.
- Triage controls are neutral unless active: Keep uses success-muted/success; Discard uses danger-muted/danger; Undefined uses pressed-surface/strong-border/secondary-text.
- Projects remain a secondary utility pane with secondary header text, a cyan active-project indicator and compact icon toolbar. Every icon action has a tooltip and accessible name. Keep destructive actions visually separate; project deletion behavior follows main specs §14.
- Use vendored Lucide SVGs: 16 px utility icons, 20 px transport icons. Default/hover/active/disabled icons use secondary/primary/accent/disabled text tokens. Render sharply at high DPI. Tooltips include actual shortcuts when applicable.
- Rating uses 18 px SVG stars with 4 px spacing, gray unfilled stars for a populated rating, gold filled stars and lighter gold hover preview. Keep small `x` clear action visually adjacent; rating interactions follow main specs §13.7.
- Video is black. Use **7 px timeline groove** with larger hit area. Use neutral track/progress, cyan playhead, focus-cyan saved I/O markers, and accent range tint at 18% opacity. Pending In and Out have distinct labels (·I and ·O). Transport/audio/time controls remain directly below.
- Scrollbars are 8 px, transparent-track, neutral-thumb with lighter hover and no arrow buttons. Splitters have a 1 px visual divider and a wider interaction region, with stronger hover color.
- Tooltips appear after a 200 ms hover delay throughout the application. They use tooltip background, default border, primary text, 6 px vertical / 8 px horizontal padding and 4 px corners. Secondary metadata recedes; populated tag prefixes use bold `#F0D16F` and remain hidden when empty. Valid commands use a subtle blue background `#172B40`; incomplete, invalid and briefly saved commands use warning, danger and success bottom borders respectively. Keyboard focus retains its cyan outline; other command backgrounds stay neutral. Unset rating uses the existing danger color for star outlines only, with no background highlight.


## 3. Application shell and side panes

### Navigation and workspace

```text
Home  Browse  Session  Editing  Export  Config   [stretch]   Undo Redo   Projects   Settings
------------------------------------------------------------------------------------------------
Left pane                  | Center: page/player and information                  | Projects
```

Navigation touches application top edge; workspace has separate 12 px inset. Use continuous strip and shared tab styling described below. Utilities align vertically; Projects and settings use 28 px height. Undo/Redo have 4 px separation, then 16 px before Projects; retain existing optical 1 px downward offset for navigation utility artwork. Do not imitate tabs with ordinary form buttons.

Center receives extra space as window grows. Splitters separate panes without decorative nested frames. Pane visibility, default proportions and manual overrides follow main specs §9.4; adding a feature must not invent different pane persistence.

### Left pane

Order search/filter controls, compact heading/action row, expanding clip list, then page-specific footer. Browse heading is Library clips with date-order action; Editing heading is Session clips with Next undefined action. Align heading text to card text and action to card edge, not merely to outer widget bounds. Shared heading margins are 13 px left / 5 px right inside existing left-pane layout; left-pane margins are 8 px horizontal / 4 px vertical. These are component-specific offsets, not general panel-padding replacements.

Keep lists tall; command area belongs below center, not across entire window. Hide empty error rows. Header backgrounds stay transparent. Filters and footer visibility follow page requirements.

### Clip cards



Use one shared delegate in all left-pane library, Session and Export views. A clip card has a 48 px body, 4 px external gap, 1 px subtle border, 3 px radius, neutral `bg_panel_alt` fill and 8 px horizontal padding. Grow only as required by font metrics.

Line one uses 12 px regular muted game codes, 12 px regular structured metadata in `text_working_title`, and 13 px bold primary mainline, with a muted ` | ` separator when both portions exist. Filename fallbacks remain 13 px. Line two is a 6 px triage dot centered against visible text using font metrics, canonical game name (or Unassigned) and Keep/Discard/Undefined at 11 px. Keep the two lines together with a 2 px gap, vertically centered in the card, rather than anchored to opposite edges. Reserve metadata width for triage and an amber Unavailable label before eliding the game name. Long titles elide; no horizontal scrollbar. Tooltips show the complete title, metadata and source path.

Hover uses `bg_surface_hover`; selection uses `accent_selection` plus a 2 px cyan left indicator. Keyboard focus uses a subtle cyan border. Presentation data must use explicit roles, not substring matching against visible text.

Browse uses capture datetime and capture-folder name on line two instead of game/triage text; retain shared card geometry, status dot and Unavailable treatment. Content and selection behavior remain governed by main specs §§9.5, 10.1 and 12.2.

### Projects

Secondary heading, active-project accent, expanding list and compact icon toolbar. Keep common actions grouped; destructive deletion remains separate in context menu. Every icon action needs tooltip and accessible name. Preserve enabled, disabled and checked states through shared styling.

## 4. Video and playback controls

Reuse [Player](../src/dfsorter/playback.py) across Browse, Editing and Export. Do not build separate transport variants for equivalent actions. Browse alone adds a trailing fullscreen icon action using shared tool-button styling: maximize to enter, minimize to exit. Fullscreen retains the existing player and controls with surrounding UI and outer padding hidden.

```text
Video surface                                     [expands]
Timeline with playhead and I/O markers
Previous Play Next Mute Volume Time   >>>   Set In Set Out Clear [page actions]
[Status only when populated]
```

Video absorbs available height; timeline and transport remain compact. Transport/audio/time form left group; range/page actions form right group. Both occupy same row beneath timeline. Editing separates Share/range controls from Add to project + Next with subtle 1 px vertical divider, 20 px tall. Group boundaries use separators; individual buttons do not each need dividers.

Center `>>>` in middle grid column with equal stretch on side columns. Reserve its horizontal slot while hidden; do not add indicator row or change video height. Use bold shared small font and animated accent highlights across three glyphs. Existing `QTimer` runs at 120 ms only during active hold, then stops/resets. Hold activation/cancellation and playback restoration follow main specs §13.2.

Status messages wrap when populated and collapse when empty. Keep transition/loading presentation consistent with main specs §9.1; never leave blank status row between transport and title.

## 5. Below-video information and forms

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

### Editing reference

```text
Working title, wrapping
Source filename
Triage / game / project status
[Keep] [Discard] [Undefined] [Change game]
Rating stars [Clear]                                                  [Help]
Structured metadata
[Description when populated]

Command area: intentional separation from clip information
[Recent command history when populated]
Wrapping shortcut hint
[Command input spanning center]
Command feedback
Field checklist                                      [Range warning slot]
```

Retain bottom command area within center column and full-height left list. Existing command-area top margin is `4 + fontMetrics().lineSpacing()` logical pixels: intentional separation, not empty content bug. Feedback line and checklist reserve enough height to prevent baseline jumps; range warning retains its slot when valid. Do not apply empty-row collapse indiscriminately to these reserved elements.

Triage/rating groups remain compact and left aligned; help action anchors right. Description uses selectable plain text on separate row. Functional behavior and field availability follow main specs §13.

## 6. Qt implementation patterns

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

## 7. Feature and review checklist

- Read main specs, this guide and closest Browse/Editing counterpart before changing UI. Reuse shared components; flag unrelated inconsistencies separately.
- Compare equivalent typography, rich-text spans, colors, icon sizes, baselines and field edges. Confirm intentional exceptions remain page-specific.
- Inspect populated/empty titles, filename fallbacks, tags, descriptions, errors and unavailable sources. No accidental blank status rows or empty paragraph spacing.
- Exercise normal, hover, pressed, checked, selected, keyboard-focus and disabled states; retain text/shape cues beyond color. Check rating hover/clear and multi-selection where supported.
- Check `>>>` activation/cancellation, range warnings and command feedback without unwanted vertical jumps. Verify adjacent clip cards and narrow panes.
- Check short, long and mixed Chinese/English text; wrapping in detail panes, elision/full tooltips in cards, and visibility of bottom actions.
- Compare normal/maximized windows and 100%, 125%, 150% scaling for affected components. Inspect representative menus/dialogs when shared styling changes.
- Run smallest relevant existing checks for UI edits, using isolated catalogues/generated media where needed. Broaden only for concrete impact. Documentation-only changes need diff/link review, not runtime tests.

Existing checks include `test_browse_form_alignment_and_title_style` and `test_browse_layout` in [UI tests](../tests/test_ui.py). [Visual fixture script](../tests/visual_design.py) supplements inspection but currently omits Browse; its captures are not exhaustive acceptance. Screenshots may predate source: verify provenance before using them as reference.

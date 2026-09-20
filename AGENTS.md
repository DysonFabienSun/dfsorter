# Agent Instructions

## Tools and Environment

- Use PowerShell 7 (`pwsh`) for shell commands.
- Use `uv` to manage Python environments and dependencies and to run Python commands.
- This machine is behind the PRC's internet firewalls. Use the `proxy_on` and `proxy_off` commands from the default PowerShell profile when accessing the broader internet. Load the profile explicitly if the shell was started without it, enable the proxy before network access, and disable it afterward in a `finally` block.

## Minimal Relevant Testing

- For each feature or edit, run only the smallest set of tests directly relevant to the changed behavior. Prefer individual test cases or narrowly selected parametrizations over entire test files or suites.
- Do not run the full suite by default, including before commits or amendments. Broaden testing only when a failure or concrete dependency impact requires it, or when the user explicitly requests it.
- Once relevant checks pass, do not repeat them unless subsequent code changes affect their results. Scope lint and other checks to changed files where supported.
- Documentation-only or instruction-only edits require diff review, not runtime tests.

## Application-Wide Style and Font Consistency

- Treat visual consistency across all pages, panes, dialogs, and control states as a requirement for every UI change. Equivalent content and controls must use the same typography and styling unless the user explicitly requests a difference or the canonical specification defines one.
- Before styling a component, inspect its existing counterpart and shared theme. Reuse typography, colors, spacing, dimensions, alignment, borders, and interaction states from `src/dfsorter/theme.py` and shared widgets rather than inventing page-specific variants.
- Match font family, size, weight, and color by semantic role. Working titles and game-code prefixes must match the Editing pane wherever they represent the same content, including rich-text spans and filename fallbacks. Check both widget fonts and embedded rich-text styles; matching only one is insufficient.
- Prefer shared style helpers and theme tokens. Avoid local stylesheets, hard-coded font sizes, or duplicated formatting rules that make equivalent components diverge. Put necessary reusable styling in the shared theme or component.
- Keep related labels, inputs, buttons, and icons aligned using shared layout rows and columns. Do not calculate fixed input widths from layout size hints before Qt has completed sizing. Preserve intentional spacing and alignment when windows resize or display scaling changes.
- Verify affected components against their counterparts, including relevant enabled, disabled, hover, selection, and empty states. Use the smallest relevant checks; distinguish window resizing from display scaling when assessing layout.
- Do not turn a focused UI task into an unsolicited application-wide redesign. Preserve existing approved styling and flag unrelated inconsistencies for separate work.

## Icon Assets

- The main Lucide icon library is `node_modules/lucide-static/icons` relative to this repository. Search it when choosing icons; available choices are not limited to the existing application assets.
- Copy only icons actually used by the application into `resources/icons`, retaining the icon license. Do not copy, bundle, or preload the entire library into the app.
- Keep runtime icon loading on demand through the existing `icon()` helper in `src/dfsorter/widgets.py`.

## Specification and Clarification

- Follow `specs/dfsorter-specs-clean.md` for all project work.
- Read and follow [UI Layout Guide](specs/ui-layout-guide.md) when adding or reviewing UI features. It owns reusable layout, typography, colors and visual states; main specs own functional behavior and page-specific constraints.
- `specs/legacy/` is archival only. Do not refer to it for implementation guidance or requirements.
- Ask the user about questions, required clarifications, or technical issues rather than silently making decisions that depart from the specification.

## Premise Checking and Technical Pushback

- Do not assume the user's diagnosis, proposed solution, or description of the current implementation is correct.
- Before implementing a non-trivial change, inspect the relevant code and verify the premise against the repository.
- If the requested behavior is already implemented, partially implemented, or available through an existing abstraction or configuration, point that out before adding another implementation.
- If the proposed direction is technically unsound, unnecessarily complex, inconsistent with the architecture, or solves the wrong problem, push back with concrete reasoning and suggest a better direction.
- Distinguish clearly between what the repository actually does, what the user believes it does, and what you recommend changing.
- Prefer evidence from code, tests, documentation, configuration, and runtime behavior over assumptions.
- Do not manufacture agreement. If evidence contradicts the user's premise, say so explicitly.
- After explaining the disagreement, follow the user's final decision unless it would violate a hard constraint or safety requirement.

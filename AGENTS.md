# Agent Instructions

## Tools and Environment

- Use PowerShell 7 (`pwsh`) for shell commands.
- Use `uv` to manage Python environments and dependencies and to run Python commands.
- This machine is behind the PRC's internet firewalls. Use the `proxy_on` and `proxy_off` commands from the default PowerShell profile when accessing the broader internet. Load the profile explicitly if the shell was started without it, enable the proxy before network access, and disable it afterward in a `finally` block.

## Specification and Clarification

- Follow `specs/dfsorter-specs-clean.md` for all project work.
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

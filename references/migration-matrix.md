# Capability Migration Matrix

This matrix prevents a migration from silently deleting user-visible behavior.
Every future redesign must update the decision and its acceptance evidence.

| Legacy capability | Decision | Safe replacement | Acceptance evidence |
| --- | --- | --- | --- |
| Copilot history review | KEEP | Bounded, redacted collector | Copilot parser tests |
| Codex history review | REPLACE | Logical-session grouping with physical cursors | Grouping and incremental tests |
| Token/cost review | REPLACE | Optional installed `ccusage` adapter; no automatic download | Adapter and missing-provider tests |
| Copilot token estimate | DEPRECATE | Report message-volume proxy and missing coverage only | No estimated cost output |
| Wiki lint | REPLACE | `ai-workspace lint` deterministic checks plus deep review | Lint fixtures and CLI test |
| Memory health | REPLACE | Guidance, skills, personal wiki, and agent-asset health | Deep-audit report template |
| Automatic asset edits | DEPRECATE | Explicit finding selection before edits | Workflow and review-log checks |
| Full user report | KEEP | Rendered in the active conversation; local report is a copy | Snapshot delivery tests |
| Remote-script installation | DEPRECATE | Manual, user-approved installation only | Adapter availability test |

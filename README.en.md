# AI Workspace Self-Improving

`ai-workspace-improver` is a conservative review skill for a managed AI
workspace. It learns from bounded, local Copilot and Codex conversation
excerpts, then combines that evidence with deterministic workspace checks to
improve skills, knowledge, agents, and shared guidance over time.

## What it does

- Collects unreviewed local Copilot and Codex JSONL history. A first review
  considers the last 90 days; later reviews are incremental. Multiple Codex
  rollout files with one session ID are one logical review session.
- Redacts common credentials and bounds every message before it reaches the
  review. Raw transcripts are never copied into the repository, wiki, reports,
  or review state.
- Audits managed assets from `workspace.toml`, not arbitrary files on the
  machine.
- Uses `ai-workspace status`, `doctor`, `apply --dry-run`, and unit tests as
  evidence for workspace findings.
- Presents small, evidence-backed changes for explicit user selection.
- Reviews each approved change after five relevant logical sessions or 30 days,
  whichever comes first; adjustments and reversions always remain user-approved.

It does not run a daemon, schedule itself, make subjective code-quality
scores, reset Git state, commit, push, or silently repair assets.

## Quick start

Ask your AI assistant for `daily review`, `self-improving`, or `AI workspace
health`. The skill runs the review workflow and presents findings before making
any change.

The collector can also be inspected directly:

```bash
python scripts/collect_chat_history.py --source all --lookback-days 90
```

Supported sources are `copilot`, `codex`, and `all`. `--mark-reviewed` advances
only physical transcript-segment cursors and should be used after the review
has been shown. The displayed count is the safer logical-session count.

## Evidence thresholds

- Skill, agent, and guidance changes require a repeated pattern in two
  independent sessions, or one direct failure with a clear preventative change.
- A knowledge candidate must be a verified and durable fact.
- A workspace repair must come from a deterministic check. Existing
  `ai-workspace` commands are preferred to new repair utilities.

## Outcome review

Every approved change records its baseline, expected outcome, observable
signal, and definition of a relevant session in the local `skill_change_log.md`.
At the review deadline it is retained, adjusted, reverted, or marked
inconclusive. The latter two are recommendations, never automatic changes.

## Privacy and local state

The following ignored files are local-only: `review_state.json`, `reviews/`,
`deferred_opportunities.md`, and `skill_change_log.md`. They contain cursors,
redacted findings, and approval history—not raw conversations.

If a transcript format or source directory is unavailable, the skill reports a
degraded source and continues with the available sources and workspace audit.

## Development

Run the collector tests with:

```bash
python -m unittest discover -s tests -v
```

The parser uses synthetic fixtures only; do not add real chat transcripts to
tests or documentation.

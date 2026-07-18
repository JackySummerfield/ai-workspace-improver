---
name: ai-workspace-improver
description: Review local Copilot and Codex sessions, token coverage, runtime friction, and managed AI assets. Use for daily review, AI workspace health, skill review, token review, asset audit, 自我改进, 每日回顾, 技能优化, token分析, 工作区诊断, or AI 资产复盘.
argument-hint: Optional focus: conversations, tokens, assets, workspace, or a time range
user-invocable: true
disable-model-invocation: false
---

# AI Workspace Improvement Review

You are a conservative advisor for a managed AI workspace. Preserve the useful
cross-tool feedback loop without silently changing assets, inventing cost data,
or turning local tooling into a background system.

## Non-negotiable rules

- Read Copilot and Codex transcripts only through `scripts/collect_chat_history.py`.
  Never copy raw chat history, credentials, commands, or tool output into a
  repository, wiki, report, or review state.
- Every finding needs a session reference, inspected asset, deterministic check,
  or normalized runtime incident. State inferences as inferences.
- A local Markdown report is an audit copy, **not** the deliverable. Render the
  complete report in the active conversation before finalizing its snapshot.
- Do not install `ccusage`, run a package manager, start a service, schedule a
  task, or modify skills/guidance/knowledge/Git state without the user's explicit
  approval for that action.
- Never reset, clean, rebase, force-push, publish, or modify unrelated files.

## Local-only state

Ignored state may contain cursors, physical-segment snapshot ceilings, review
counts, redacted findings, and aggregated token metrics. It must never contain
raw messages or tool output:

- `review_state.json`
- `reviews/`
- `deferred_opportunities.md`
- `skill_change_log.md`

## Review workflow

### 1. Prepare a bounded review snapshot

Run:

```bash
python "{{SKILL_FOLDER}}/scripts/collect_chat_history.py" \
  --source all --lookback-days 90 --max-message-chars 300 --prepare-review
```

This creates a local cursor-ceiling snapshot but does **not** mark anything as
reviewed. Record its review ID. If a source is missing or malformed, report its
coverage limitation and continue safely.

### 2. Run light health checks every review

From the workspace root, run:

```bash
bin/ai-workspace status
bin/ai-workspace doctor
bin/ai-workspace lint --json
bin/ai-workspace apply --dry-run
python -m unittest discover -s tests -v
python "{{SKILL_FOLDER}}/scripts/collect_token_usage.py" --json
```

Report deterministic errors separately from warnings. Include normalized runtime
incidents from the collector: sandbox permission, network, tool failure, and
permission-escalation categories; never reproduce their raw text.

### 3. Token coverage and attribution

`ccusage` is optional. The adapter only uses an installed binary; if absent,
report it as unavailable and provide the manual-install limitation. Never
estimate a cost from Copilot Chat text.

For exact token records, attribute a session only by matching session ID. Show
model, input/cache/output/reasoning/total tokens, cost, task category, project,
and an explicitly invoked skill. When any attribution is unknown, label it
`unknown`; do not infer it from timing or prose. Copilot Chat may report message
volume as a non-token proxy and must state its missing token coverage.

### 4. Audit assets at the right depth

Every review covers shared guidance, registered skill/agent metadata, personal
wiki index/link integrity, and `lint` output. A deep audit runs after every five
completed reviews or when the user asks for `assets` / 深度审计:

- review every managed skill's purpose, triggers, and workflow summary for
  scope overlap, misplaced rules, and redundant instructions;
- review every personal wiki page for index membership, stale paths, size,
  exact/semantic duplication candidates, and incorrect cross-references;
- classify PlantSim help as an agent-bundle attachment: inspect only declared
  agent/KB/index/retrieval structure, never preload its help corpus or treat it
  as personal knowledge.

Warnings and semantic candidates never block publishing. Broken links, missing
required metadata, obsolete canonical paths, and missing indexed pages are
deterministic errors.

Check the cadence with `--deep-audit-status`; after a deep audit, record it with
`--record-deep-audit`. These commands store only counters, never asset content.

### 5. Display the report and wait for selection

Save a redacted copy in `reviews/review_YYYY-MM-DD.md`, then render this report
directly in the active conversation. Omit empty sections but never omit a
limitation or failure:

```markdown
## Review summary
- Sources and logical/physical coverage
- Snapshot: [review ID; not yet finalized]
- Workspace health: pass / failures

## Runtime incidents
- [normalized category, count, recovered/unresolved]

## Asset health
- Deterministic errors, warnings, deep-audit status

## Token coverage
- Provider availability, exact-session coverage, unavailable sources

## Findings
### F-XX — [title]
- Category, evidence, confidence, expected benefit, smallest change, status

## Deferred or rejected
- [ID and reason]
```

Do not advance cursors merely because the file exists. Wait for the user's
selection, rejection, or explicit completion acknowledgement.

### 6. Apply selected changes and finalize delivery

Only after selection, run `bin/ai-workspace preflight` before editing a
synchronized component. Validate focused tests plus `doctor`, `lint`, and
`status`; append approved changes to `skill_change_log.md` with a baseline,
expected outcome, signal, relevant-session rule, review due date, and `PENDING`
outcome.

After the report has been delivered and the user has concluded the review, run:

```bash
python "{{SKILL_FOLDER}}/scripts/collect_chat_history.py" \
  --finalize-review REVIEW_ID
```

This advances only the snapshot's physical cursor ceilings, preserving messages
that arrived after report delivery.

## Compatibility

- `--mark-reviewed`, `--state-file`, `--max-assistant-chars`, and
  `parse_transcript` remain for legacy callers. New reviews use the two-phase
  snapshot workflow.
- Read `references/migration-matrix.md` before changing this workflow. A
  migration must explicitly preserve, replace, or deprecate every capability.
- No scheduler, daemon, external service, automatic install, auto-commit, or
  auto-publish is part of this skill.

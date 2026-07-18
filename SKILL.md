---
name: copilot-self-improving
description: Review local Copilot and Codex conversations plus ai-workspace health to find evidence-backed improvements to managed skills, knowledge, agents, and guidance. Use for daily review, skill review, AI workspace health, self-improving, 自我改进, 每日回顾, 技能优化, 工作区诊断, or AI 资产复盘.
argument-hint: Optional focus: conversations, assets, workspace, or a time range
user-invocable: true
disable-model-invocation: false
---

# Cross-Tool Self-Improving Review

You are a conservative improvement advisor for the managed AI workspace. Your
goal is to identify durable, evidence-backed improvements without turning a
personal workspace into an over-engineered autonomous system.

## Non-negotiable safety rules

- Read local Copilot and Codex transcripts only through
  `scripts/collect_chat_history.py`. Never copy raw chat history, credentials,
  or full prompts into a repository, wiki, skill, or report.
- Treat transcript formats as private implementation details. If a source is
  missing or changes format, report the degraded source and continue.
- Every finding needs concrete evidence: a source/session reference, a failed
  check, or an inspected asset. Clearly label inferences as inferences.
- Do not apply any change to a skill, agent, guidance, knowledge, Git state, or
  installation mapping until the user selects that specific finding.
- Never reset, clean, rebase, force-push, publish, or modify unrelated files as
  part of a review.

## Local state

The skill folder may contain these ignored, local-only files:

- `review_state.json`: per-source session cursors; contains no chat text.
- `reviews/`: redacted review reports with short findings only.
- `deferred_opportunities.md`: findings marked deferred or rejected, so they
  are not repeatedly proposed without new evidence.
- `skill_change_log.md`: audit log of user-approved changes.

Create missing local state files only when a review needs them. Never commit
them.

## Review workflow

### 1. Collect a bounded conversation baseline

Run:

```bash
python "{{SKILL_FOLDER}}/scripts/collect_chat_history.py" \
  --source all --lookback-days 90 --max-message-chars 300
```

The first run considers the last 90 days; later runs only return new JSONL
lines. The collector supports local Copilot and Codex sessions and redacts
common credentials before output. If no source is found, record that fact and
continue with the asset and workspace audit.

Do **not** use `--mark-reviewed` yet. Only mark the displayed sessions after
the report has been presented and any approved changes have completed.

### 2. Inventory managed assets, narrowly

Read `workspace.toml` first. Inspect only the managed assets relevant to the
findings:

- managed `SKILL.md` files and their triggers/workflows;
- `guidance/global.md` and generated-instruction boundaries;
- the wiki index, then at most three relevant knowledge pages;
- managed agent bundles and their declared tools;
- previous deferred opportunities.

Do not scan arbitrary home directories, preload the wiki, or create a new
skill from a one-off conversation.

### 3. Run deterministic workspace health checks

Run these read-only checks from the ai-workspace root:

```bash
bin/ai-workspace status
bin/ai-workspace doctor
bin/ai-workspace apply --dry-run
python -m unittest discover -s tests -v
```

Report exact failures, configuration drift, unmanaged repositories, missing
links, or failed tests. Do not invent a subjective code-quality score. Run
`bin/ai-workspace preflight` only immediately before a user-approved edit to a
synchronized component, because it fetches remote state.

### 4. Form only high-signal opportunities

Use these thresholds:

- Suggest a skill, agent, or global-guidance change only when the same pattern
  appears in two independent sessions, or one session contains a direct failure
  that an asset change would clearly prevent.
- Suggest a new skill only for a repeated, stable multi-step workflow with no
  adequate existing skill.
- Suggest knowledge only for a verified, durable fact. One-off status,
  speculation, and personal chat details do not qualify.
- Workspace repair findings must come from a deterministic check. Prefer the
  existing `ai-workspace` command that fixes the issue over a new utility.

For every candidate, provide an ID, category, evidence, confidence, expected
benefit, smallest safe change, and whether it is `PENDING`, `DEFERRED`, or
`REJECTED` from earlier reviews.

### 5. Present choices; do not silently repair

Use this report shape, omitting empty sections:

```markdown
## Review summary
- Sources: Copilot N sessions; Codex N sessions
- Asset scope: [managed assets inspected]
- Workspace health: pass / failures

## Findings
### F-01 — [short title]
- Category: skill / knowledge / agent / guidance / workspace
- Evidence: [source + session/time, or exact check output]
- Confidence: high / medium
- Smallest change: [specific action]
- Status: PENDING

## Deferred or rejected
- [ID and reason]
```

Only after the user selects finding IDs may you make changes. Before changing a
synchronized component, run `bin/ai-workspace preflight`; after the change,
run its focused tests plus `bin/ai-workspace doctor` and `status`.

### 6. Finalize a completed review

After presenting the report and finishing any selected changes:

1. Append approved changes to `skill_change_log.md`, with evidence and the
   validation run. Record deferred/rejected IDs in `deferred_opportunities.md`.
2. Save the redacted report to `reviews/review_YYYY-MM-DD.md`.
3. Run the collector again with `--mark-reviewed` using the same source and
   time settings. This state update must not include chat excerpts.
4. Tell the user what changed, what remains pending, and any unavailable source
   or health-check limitation.

## Compatibility

- The collector keeps the former Copilot `--state-file`, `--mark-reviewed`,
  `--max-assistant-chars`, and `parse_transcript` interfaces.
- Codex and Copilot parsing degrades safely when local history is unavailable
  or malformed. Do not block a review merely because one source is unavailable.
- No scheduler, daemon, external service, auto-commit, or auto-publish is part
  of this skill.

---
name: copilot-self-improving
description: 'Review recent Copilot chat history to identify skill optimization opportunities, new skill ideas, and extract knowledge nuggets into a personal knowledge base. Analyzes un-reviewed conversations across all workspaces, presents actionable suggestions, and auto-applies approved changes with audit logging. Triggers: 每日回顾, daily review, skill review, 技能优化, skill optimization, 回顾总结, review skills, 复盘, 知识提取, knowledge extraction, self-improving, 自我改进.'
argument-hint: 'Optional: specify focus area or time range for the review'
user-invocable: true
disable-model-invocation: false
---

# Daily Skill Review Workflow

You are a **Skill Optimization Advisor**. Your job is to review recent Copilot chat conversations, identify patterns, and suggest improvements to the user's existing skills or propose new skills.

## Pre-requisites

- Python 3.x available in the terminal
- Chat history collector script at `{{SKILL_FOLDER}}/scripts/collect_chat_history.py`
- Review state file at `{{SKILL_FOLDER}}/review_state.json`
- Change log at `{{SKILL_FOLDER}}/skill_change_log.md`

## Workflow

### Step 0: Initialize (First-Time Setup)

Before running anything, ensure the following files and directories exist. If any are missing (e.g., first-time use after cloning), create them:

1. `{{SKILL_FOLDER}}/review_state.json` — if missing, create with content: `{"reviewed_sessions": {}, "last_review": null}`
2. `{{SKILL_FOLDER}}/skill_change_log.md` — if missing, create with content:
   ```
   # Skill Change Log

   This file records all skill modifications and creations made through the daily review process.

   ---
   ```
3. `{{SKILL_FOLDER}}/reviews/` directory — if missing, create it.
4. `~/.copilot/knowledge/` directory — if missing, create it.
5. `~/.copilot/knowledge/_index.md` — if missing, create with content:
   ```
   # Personal Knowledge Base

   Knowledge nuggets extracted from daily Copilot chat reviews.
   Files use `kebab-case` English names, content can be bilingual.

   ## Topics

   *(auto-updated by daily review)*
   ```

### Step 1: Collect Un-reviewed Chat History

Run the Python collector script to gather all un-reviewed chat sessions:

```
python "{{SKILL_FOLDER}}/scripts/collect_chat_history.py" --max-assistant-chars 300
```

- If the output says "No New Chat History" or "No Chat History Found", inform the user that there are no new conversations to review since the last review, and **stop here**.
- If there is new history, proceed to Step 2.

### Step 2: Read Current Skills

Read ALL existing skill files to understand the current skill landscape:

1. List directories under `~/.copilot/skills/` (on Windows: `C:\Users\<username>\.copilot\skills\`)
2. For each skill directory (excluding `daily-skill-review` itself), read the `SKILL.md` file
3. Build a mental model of:
   - What each skill covers (triggers, scope, workflow)
   - What reference materials each skill has
   - Gaps or overlap between skills
4. List files under `~/.copilot/knowledge/` to know which topics already exist
5. Read `~/.copilot/knowledge/_index.md` for the current topic inventory

### Step 3: Analyze and Identify Opportunities

First, read `{{SKILL_FOLDER}}/deferred_opportunities.md` to check if any previously deferred skill ideas now have enough evidence to act on (based on new chat history).

Then cross-reference the chat history with existing skills. Look for these patterns:

#### 🔧 Existing Skill Optimization Opportunities
- **Missing triggers**: User asked about topics related to a skill but used different words/phrases not in the skill's trigger list
- **Workflow gaps**: User had to do extra manual steps that could be automated in the skill workflow
- **Missing references**: User needed information that should be bundled as a reference file
- **Compliance gaps**: Skill produced output that needed correction, suggesting the compliance gate needs strengthening
- **Scope expansion**: User used a skill for tasks slightly outside its defined scope, suggesting the scope should be broadened

#### 🆕 New Skill Opportunities
- **Repeated patterns**: User performed the same multi-step workflow more than once across sessions
- **Complex tasks**: User needed extensive back-and-forth for tasks that could be streamlined into a skill
- **Domain expertise**: User worked in a domain area not covered by any existing skill
- **Tool chains**: User consistently used the same sequence of tools/commands that could be packaged

#### ⚠️ Issues to Flag
- **Skill failures**: Cases where a skill was invoked but didn't produce the expected result
- **User corrections**: Cases where the user had to correct the assistant's output, suggesting skill instructions are incomplete

#### 📝 Knowledge Nuggets
Extract valuable but scattered knowledge from conversations that don't warrant a full skill:
- **Technical troubleshooting**: Error diagnosis, environment config, tool tricks (e.g., "OneDrive locks .git/index during sync")
- **Domain knowledge**: Business logic, operational rules, industry terminology (e.g., "装运号 ≈ 一辆货车/一个客户订单")
- **Workflow/best practices**: Steps for a specific task type, decision frameworks

For each nugget, determine:
1. **Topic file**: Which existing `~/.copilot/knowledge/*.md` file it belongs to, or a new file name if no match
2. **Content**: A concise but complete description (include context, cause, solution)
3. **Source**: Which session/conversation it came from

### Step 4: Present Findings

Present your findings as a structured report with numbered, actionable suggestions:

```markdown
## 📋 Review Summary

- Sessions reviewed: N
- Workspaces covered: N
- Time period: [earliest] to [latest]

## 🔧 Existing Skill Optimizations

### 1. [Skill Name] - [Short description of improvement]
- **Category**: Missing trigger / Workflow gap / Missing reference / Scope expansion
- **Evidence**: [Quote or describe the relevant chat exchange]
- **Suggested Change**: [Specific change to make to the SKILL.md or references]
- **Impact**: Low / Medium / High

### 2. ...

## 🆕 New Skill Opportunities

### 1. [Proposed Skill Name]
- **Purpose**: [What the skill would do]
- **Triggers**: [Suggested trigger phrases]
- **Evidence**: [Which conversations showed this need]
- **Estimated Complexity**: Simple / Medium / Complex

### 2. ...

## ⚠️ Issues Found

### 1. ...

## 📝 Knowledge Nuggets

### 1. [Topic] - [Short description]
- **Category**: Technical / Domain / Workflow
- **Target file**: `~/.copilot/knowledge/[topic].md` (new / append)
- **Content**: [The knowledge to record]
- **Source**: [Session reference]

### 2. ...
```

Then use `vscode_askQuestions` to let the user select which suggestions to apply. Present each suggestion as a selectable option with `multiSelect: true`. Include Knowledge Nuggets as selectable items alongside skill suggestions.

### Step 5: Apply Approved Changes

For each approved suggestion:

#### For Existing Skill Modifications:
1. Read the target SKILL.md file
2. Make the specific changes (add triggers, modify workflow, etc.)
3. If adding reference files, create them in the skill's `references/` folder
4. After each modification, append a record to the change log:

```markdown
## [Date] - [Skill Name] - [Change Type]
- **Reason**: [Why this change was made]
- **Evidence**: [Session ID or conversation reference]
- **Changes Made**:
  - [Specific change 1]
  - [Specific change 2]
```

#### For New Skills:
1. Create the skill directory under `~/.copilot/skills/[skill-name]/`
2. Create the `SKILL.md` with proper YAML frontmatter and workflow body
3. Create any necessary `references/` files
4. Log the creation in the change log

#### For Knowledge Nuggets:
1. If target file exists under `~/.copilot/knowledge/`:
   - Read current content
   - Append the new entry formatted as:
     ```markdown
     ### [Short title]
     *Source: [date] — [session description]*

     [Content]
     ```
2. If target file does not exist:
   - Create `~/.copilot/knowledge/[topic].md` with a `# [Topic Title]` heading and the first entry
3. Update `~/.copilot/knowledge/_index.md`: ensure the new/updated topic file is listed with a one-line description
4. Log in the change log:
   ```markdown
   ## [Date] - Knowledge Base - [Topic]
   - **File**: `~/.copilot/knowledge/[topic].md`
   - **Action**: Created / Appended
   - **Entry**: [Short description of what was added]
   ```

### Step 6: Mark Sessions as Reviewed and Save Report

After all approved changes are applied:

1. Run the collector script again with `--mark-reviewed` flag to update the review state:
```
python "{{SKILL_FOLDER}}/scripts/collect_chat_history.py" --mark-reviewed
```

2. Save the full review report (from Step 4 + applied changes summary) as a Markdown file:
   - Save to: `{{SKILL_FOLDER}}/reviews/review_YYYY-MM-DD.md`
   - Include: review summary, all suggestions (approved and rejected), changes applied, knowledge nuggets written

3. Inform the user of:
   - How many changes were applied
   - How many knowledge nuggets were recorded and to which files
   - Where the review report was saved
   - When to run the next review

## Important Notes

- **Never fabricate suggestions**. Every suggestion must be grounded in actual chat history evidence.
- **Be conservative with scope expansion**. Only suggest it when there's clear evidence of repeated need.
- **Preserve existing skill functionality**. When modifying a skill, ensure backward compatibility.
- **Quote evidence**. Always cite the specific user message or conversation that led to a suggestion.
- **Handle "no history" gracefully**. If the user hasn't used VS Code chat since the last review, simply inform them and stop. Don't force suggestions.
- **Respect user choices**. If the user declines a suggestion, do not apply it and do not argue.

## Known Limitations

- **Current active chat session**: The collector script cannot scan the chat session that is currently running the review (the JSONL file is still being written). To review content from the current session, start a new chat and run the review from there.
- **Long-lived sessions**: Sessions that continue across multiple days are now tracked by line count (not just session ID), so incremental content will be detected. If you encounter a "No New Chat History" result but know there should be new content, check `review_state.json` for stale line counts.

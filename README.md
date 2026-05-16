# copilot-self-improving

A Copilot Skill that reviews recent chat history across all VS Code workspaces, identifies skill optimization opportunities, proposes new skills, and extracts knowledge nuggets into a personal knowledge base. Auto-applies approved changes with audit logging.

## Features

- Scans all VS Code workspace chat transcripts (JSONL format)
- Session-based deduplication — only processes un-reviewed conversations
- Cross-references chat patterns against existing skills
- Extracts reusable knowledge nuggets into `~/.copilot/knowledge/` (by topic)
- Tracks deferred skill opportunities across reviews
- Presents actionable suggestions with evidence from actual conversations
- Auto-modifies skills and knowledge base after user confirmation
- Maintains a change audit log and dated review reports

## Usage

In VS Code Copilot Chat, use any of these trigger phrases:

- `每日回顾` / `daily review` / `skill review` / `技能优化` / `回顾总结` / `复盘` / `知识提取` / `self-improving` / `自我改进`

## Requirements

- Python >= 3.10
- VS Code with GitHub Copilot Chat extension

## File Structure

```
copilot-self-improving/
├── SKILL.md                              # Skill definition and workflow
├── review_state.json                     # Tracks reviewed session IDs
├── skill_change_log.md                   # Audit log of all skill modifications
├── deferred_opportunities.md             # Skill ideas waiting for more evidence
├── references/
├── scripts/
│   └── collect_chat_history.py           # Python script to collect chat history
└── reviews/
    └── review_YYYY-MM-DD.md             # Generated review reports
```

## Related

- `~/.copilot/knowledge/` — Personal knowledge base (auto-populated by this skill)

## License

MIT — see [LICENSE](LICENSE).

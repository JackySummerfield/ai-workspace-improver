# Skill Creation Conventions

Standards for creating new skills through the `ai-workspace-improver` workflow. These conventions ensure quality, portability, and safety for any skill published to a public repository.

## Content Safety

### Absolute Prohibitions

The following must NEVER appear in any file committed to a public skill repo:

- Employer / client / partner company names
- Company-specific tool names that reveal employer identity
- Internal project names or codenames
- Employee names, email addresses, employee IDs
- File paths containing real usernames (e.g., `C:\Users\jane.doe\...`)
- Internal URLs (intranet, SharePoint, corporate APIs)
- Real dates tied to work activities (use placeholder dates like `2026-01-15`)

### Writing Generic Examples

| Avoid (reveals identity) | Use instead (generic) |
|--------------------------|----------------------|
| A real skill name from your workplace | `api-docs-helper`, `test-runner` |
| Company-prefixed filenames (`acme-env.md`) | `dev-environment.md` |
| Vendor-specific tools as sole cause | "Corporate SSL inspection" (not a specific vendor name) |
| Real work dates (`2026-06-24`) | Placeholder dates (`2026-01-15`) |
| Company jargon / acronyms | Industry-standard terminology |

### Self-Check Before Commit

1. Search staged files for company name patterns: `git diff --cached | grep -i "company_name"`
2. Verify all example skill/file names are generic
3. Confirm dates are placeholders, not real activity dates
4. Check file paths don't contain real usernames

## SKILL.md Structure

Follow the [Agent Skills specification](https://agentskills.io/):

### Required YAML Frontmatter

```yaml
---
name: skill-name          # lowercase, hyphens only, matches directory name, max 64 chars
description: '...'        # what it does + when to use it, max 1024 chars
argument-hint: '...'      # hint for slash command input (optional)
user-invocable: true      # appears in / menu (default: true)
disable-model-invocation: false  # agent can auto-load (default: false)
---
```

### Required Body Sections

1. **Role statement** — one sentence defining what the agent does
2. **Pre-requisites** — tools, files, environment needed
3. **Workflow** — numbered steps with clear entry/exit conditions
4. **Important Notes** — constraints, edge cases, known limitations

### Referencing Resources

- Use relative Markdown links: `[template](./references/template.md)`
- Only referenced files get loaded into context — unreferenced files are invisible
- Keep resource files in a `references/` subdirectory

## README Structure

Follow [Best-README-Template](https://github.com/othneildrew/Best-README-Template):

### Required Sections

| Section | Content |
|---------|---------|
| Title + badges | Name, VS Code version, language, license |
| About | One-paragraph purpose statement |
| Getting Started | Prerequisites, clone command, first-run instructions |
| Usage | Trigger phrases and expected behavior |
| Workflow Overview | Mermaid diagram or numbered step summary |

### Optional Sections

- **Output Examples** — in collapsible `<details>` blocks
- **Roadmap** — planned improvements
- **Contributing** — if accepting PRs
- **Acknowledgments** — references and inspiration

### Style Rules

- Bilingual OK (separate Chinese + English README files)
- Examples show the pattern, not exhaustive cases
- Long output samples go in collapsible sections

## Versioning

- [SemVer](https://semver.org/): MAJOR.MINOR.PATCH
- Git tags with `v` prefix: `v1.2.0`
- CHANGELOG.md per [Keep a Changelog](https://keepachangelog.com/)

## License

- Default: MIT for utility tools / Skills
- Include `LICENSE` file in repo root

## Git Hygiene

- `.gitignore` must exclude: `review_state.json`, `reviews/`, personal config, `*.bak`, `__pycache__/`, `node_modules/`
- Commit messages: imperative mood, 50-char subject line
- No binary files unless essential

# Claude Code Skills

A collection of reusable [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills for production development workflows. Each skill captures battle-tested patterns, architectural decisions, and solutions to real-world problems encountered during development.

## What Are Skills?

Skills are structured instructions that Claude Code can autonomously discover and use. They provide:

- **Reusable patterns** — Architecture and code patterns that work across projects
- **Gotcha prevention** — Known issues and their fixes, so you don't repeat mistakes
- **Step-by-step guides** — Implementation procedures from setup to verification
- **Template files** — Ready-to-use code templates for common components

## Available Skills

| Skill | Description |
|-------|-------------|
| [api-platform](./api-platform/) | API key management, auto-generated API docs with interactive "Try It" panels, dual auth (JWT + API key), and Swagger decorator patterns for NestJS + React |

## Installation

### Personal Skills (all projects)

```bash
# Clone into your Claude Code skills directory
cd ~/.claude/skills
git clone https://github.com/celinadevassist/claude-skills.git temp
cp -r temp/api-platform ./api-platform
rm -rf temp

# Or symlink the entire repo
git clone https://github.com/celinadevassist/claude-skills.git
```

### Project Skills (team-shared)

```bash
# Clone into your project's .claude/skills directory
cd your-project/.claude/skills
git clone https://github.com/celinadevassist/claude-skills.git temp
cp -r temp/api-platform ./api-platform
rm -rf temp
git add .claude/skills/api-platform
git commit -m "Add api-platform skill"
```

## Skill Structure

Each skill follows this structure:

```
skill-name/
├── SKILL.md                  # Main skill file (required)
├── docs/                     # Extended documentation
│   └── TROUBLESHOOTING.md
└── resources/
    └── templates/            # Code templates
        ├── backend/
        └── frontend/
```

## Creating New Skills

Use the `skill-builder` skill or follow this template:

```markdown
---
name: "My Skill Name"
description: "What it does. When to use it."
---

# My Skill Name

## What This Skill Does
[Description]

## Quick Start
[Basic usage]

## Patterns & Architecture
[Key patterns]

## Critical Fixes & Gotchas
[Known issues and solutions]

## Verification Checklist
[How to verify it works]
```

## Tech Stack

Skills in this collection are primarily built for:

- **Backend**: NestJS, MongoDB/Mongoose, Passport.js
- **Frontend**: React, Mantine UI, Vite
- **Auth**: JWT + API Key dual authentication
- **Docs**: Swagger/OpenAPI auto-generation

## Contributing

1. Create a new directory under the repo root
2. Add a `SKILL.md` with proper YAML frontmatter
3. Include templates in `resources/templates/`
4. Add troubleshooting in `docs/TROUBLESHOOTING.md`
5. Update this README's skills table

## License

MIT

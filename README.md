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
| [bulk-db-audit](./bulk-db-audit/) | Audit MongoDB/Mongoose operations for performance anti-patterns; detects loops with individual DB calls that should use `bulkWrite`, `insertMany`, `updateMany`, or `$in` queries |
| [deployment-setup](./deployment-setup/) | Build a Setup Guide page and Docker deployment infrastructure for NestJS + React monolith projects: Dockerfile, GitHub Actions CI/CD, Portainer stack config, NPM proxy setup |
| [i18n-bilingual-rtl](./i18n-bilingual-rtl/) | English + Arabic bilingual support with full RTL, Tailwind logical properties, Cairo + Inter font pairing, Arabic-safe PDF/Excel exports, and lint rules that block hardcoded strings and physical CSS |
| [logging-setup](./logging-setup/) | Production-grade structured logging for NestJS: JSON file-based logs with rotation, error serialization, and exception filters with full stack traces |
| [monolith-setup](./monolith-setup/) | Convert separate NestJS backend + React frontend into a single monolithic deployment where the backend serves the SPA from `public/` with proper React Router fallback |
| [nestjs-throttle](./nestjs-throttle/) | Production-ready rate limiting for NestJS monoliths (ServeStaticModule + API): prevents 429 errors on page refresh while still protecting auth endpoints |
| [project-metadata-refiner](./project-metadata-refiner/) | AI-driven audit of project identity — cross-references package.json, README, deployed og: tags, and git history to produce a `.project-meta.json` side-car with refined name, description, keywords, full SEO/OpenGraph metadata, and README intro |
| [project-skill-advisor](./project-skill-advisor/) | Recommends which skills in this repo to apply to a given project, in dependency-correct order. Cross-references the project against [`skills-graph.yml`](./skills-graph.yml); emits a `.project-skills.json` side-car with three buckets (recommendations / alreadyApplied / notRecommended) for Mission Control's apply drawer to consume |
| [pwa-setup](./pwa-setup/) | Configure a Vite + React + NestJS monolith as an installable PWA: manifest, icon set, `vite-plugin-pwa` shell-cache, Android install banner, iOS install instruction sheet |
| [skill-graph-position-inferrer](./skill-graph-position-inferrer/) | Given a newly-added skill, infers its correct entry for [`skills-graph.yml`](./skills-graph.yml) — type, category, level, depends_on, description — by reading the SKILL.md, comparing against calibration peers, and scanning for explicit prerequisite signals. Outputs a copy-paste-ready YAML block with per-field confidence |

## Adding a new skill

1. `npx skill-builder` (or hand-write `SKILL.md`) to create the new skill folder.
2. Run the [`skill-graph-position-inferrer`](./skill-graph-position-inferrer/) skill in Claude Code — it proposes the YAML entry for `skills-graph.yml`.
3. Review the proposal, edit if needed, paste into `skills-graph.yml`.
4. `git commit` — [`scripts/lint-skills-graph.py`](./scripts/lint-skills-graph.py) runs in CI ([workflow](./.github/workflows/lint-skills-graph.yml)) and fails the build if the skill exists on disk but is missing from the graph, has bad deps, has a cycle, or breaks any other contract.

The lint catches the case where you skipped step 2 or 3. The inferrer makes step 2 cheap.

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

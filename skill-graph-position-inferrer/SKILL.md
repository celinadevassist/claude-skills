---
name: "Skill Graph Position Inferrer"
description: "Given a newly-added skill in this repo, infers the correct entry for skills-graph.yml — type, category, level, depends_on, description_short — by reading the new SKILL.md, comparing against existing skills in the same category, and scanning the body for explicit prerequisite references. Outputs a copy-paste-ready YAML block plus per-field reasoning with confidence levels. Run after `skill-builder` creates a new SKILL.md, before committing it to the repo. Closes the gap between 'skill exists' and 'skill exists in the dependency graph'."
---

# Skill Graph Position Inferrer

## What This Skill Does

You just added `claude-skills/<new-slug>/SKILL.md`. The skill is real — but until it's also in `skills-graph.yml`, the `project-skill-advisor` won't recommend it, the Mission Control graph view won't show it, and the canonical apply order ignores it.

This skill closes that gap. Given a new skill's slug, it:

1. Reads the new `SKILL.md` (front-to-back).
2. Loads the current `skills-graph.yml` to understand the existing ontology.
3. Picks 2–3 existing skills as **calibration peers** (closest category fits).
4. Infers **type / category / level / depends_on / description_short** by scanning the new skill's content for concrete signals.
5. Emits a copy-paste-ready YAML block, plus a one-sentence justification per field with `confidence: high|medium|low`.

You review, edit if needed, paste into `skills-graph.yml`, commit. The lint script (`scripts/lint-skills-graph.py`) will then verify on next push.

## When to Use

- Right after `skill-builder` creates a new SKILL.md, before the first commit.
- When importing an external skill into this repo and you need to slot it correctly.
- When refactoring an existing skill and its dependencies change.

## When NOT to Use

- The skill is purely informational / a reference list with no procedure — those don't really fit the graph; just add a stub `level: null, type: audit, depends_on: []`.
- Renaming an existing skill — that's a `git mv` + edit-the-existing-entry job, not a fresh inference.

---

## Input

Pass the new skill's slug as the single argument. The skill assumes:

- The new `SKILL.md` exists at `/home/sammy/claude-skills/<slug>/SKILL.md`.
- `skills-graph.yml` exists at `/home/sammy/claude-skills/skills-graph.yml`.
- The user wants advice, not auto-edits — never mutate `skills-graph.yml` directly.

---

## Output Format

A single markdown block, ready to paste back to the user:

```text
## Proposed entry for skills-graph.yml

  <slug>:
    type: setup
    category: ui
    level: 2
    depends_on: [monolith-setup, mantine-theme-discipline]
    description_short: "Inline rich-text editor for admin tools using Mantine + Tiptap"

## Reasoning

- type:         setup        | confidence: high   | The skill modifies the project (creates components, edits app.module.ts).
- category:     ui           | confidence: high   | All content is frontend; reuses `<Drawer>`, `<Textarea>`, Tiptap.
- level:        2            | confidence: medium | Lowest available level given deps on monolith-setup (L0) and mantine-theme-discipline (L2). Could float to L3 if user prefers grouping with `spotlight-cmdk`.
- depends_on:   monolith-setup, mantine-theme-discipline | confidence: high
                | Explicit references in body: `ServeStaticModule` (line 47) → monolith;
                |                              `theme tokens for editor toolbar` (line 81) → theme-discipline.
- description:  one line from the skill's What This Skill Does opener, trimmed to <100 chars.

## Calibration peers consulted
- mantine-theme-discipline (same category, similar size)
- spotlight-cmdk (same level, similar UI-sugar pattern)

## Manual review checklist before pasting
- [ ] Re-read depends_on — anything implicit I missed?
- [ ] Confirm level — could it actually go a row lower?
- [ ] description_short is under 100 chars, no marketing fluff.
```

---

## Investigation Procedure

### Step 1 — Read the new skill end-to-end

```bash
cat /home/sammy/claude-skills/<slug>/SKILL.md
```

Note the frontmatter `description` (becomes a candidate for `description_short`) and skim the whole body. Look for:

- Imperative verbs early: "creates", "adds", "modifies" → **setup**; "audits", "reviews", "scans" → **audit**.
- Names of NestJS modules, React components, frontend libraries → **category signal**.
- Quoted file paths, `@nestjs/*` imports, `mantine/*` imports → **dependency signals**.
- The "Pairs Well With" section, if present — explicit dependency hints.

### Step 2 — Load the current graph

```bash
cat /home/sammy/claude-skills/skills-graph.yml
```

You need the full set of existing slugs (so you can validate `depends_on` against real skills, not invent edges to skills that don't exist) and the category list.

### Step 3 — Pick calibration peers

For each candidate category, pick the existing skill that's the closest sibling. Read that peer's body summary. Two things matter:

- **Does the new skill assume the peer is in place?** If yes, that's a `depends_on` candidate.
- **Is the peer's level a good ceiling/floor?** If the peer is L2 and the new skill is logically downstream of it, the new skill should be ≥ L2.

Read just enough of each peer — usually the first 30 lines + the "Pairs Well With" section. Don't burn context on full reads.

### Step 4 — Infer each field

Apply this rubric. **Be conservative with confidence — the user reviews before pasting.**

#### `type`

- **setup** — skill creates files, modifies code, adds dependencies, edits package.json. Has an "Implementation" or "Step N" section.
- **audit** — skill reads the project and reports findings. Emits a side-car or report. Doesn't change source unless the user opts in.
- **generative** — skill creates new artifacts from prompts (rare in this repo).

Confidence: usually **high** — the skill's verbs are explicit.

#### `category`

Pick from the categories defined in `skills-graph.yml` (currently: `foundation`, `auth`, `data`, `ui`, `audit`, `ops`).

| Category signals | Examples |
|---|---|
| `foundation` | "monolith", "logging", "throttle", "server setup", "module structure" |
| `auth` | "JWT", "user", "role", "API key", "audit trail", "session" |
| `data` | "Mongoose", "schema", "query", "migration" (no current member here yet) |
| `ui` | "Mantine", "React", "component", "theme", "i18n", "PWA", "Spotlight" |
| `audit` | "scan", "detect", "warn", "report", "side-car" |
| `ops` | "Dockerfile", "GitHub Actions", "Portainer", "deploy", "setup page" |

Confidence: **high** if a single category dominates; **medium** if the skill spans two (e.g., a feature with both backend and frontend pieces — pick the larger half).

#### `level`

Levels reflect *real* prerequisite ordering, not aesthetic grouping. Compute as:

```
level = max(level of each entry in depends_on) + 1
```

Special cases:
- `type: audit` → `level: null` (audits run anytime, independent of stack state).
- No `depends_on` → `level: 0`.
- Skill explicitly says "run last" / "after everything is in place" → push to L4 or L5 even if deps are lower.

Confidence: **high** when deps are unambiguous; **medium** when the skill could float between adjacent levels.

#### `depends_on`

Scan the body for these signals:

| Signal in the new SKILL.md | Likely dep |
|---|---|
| `ServeStaticModule`, "serves the SPA", "backend/public/" | `monolith-setup` |
| `winston`, `pino`, "/logs/*.log", "structured logging" | `logging-setup` |
| `JWT`, `AuthContext`, `ProtectedRoute`, "admin-seed", "bcrypt" | `jwt-auth-admin-seeded` |
| `AuditService`, "audit trail", "attributed by user" | `audit-log` |
| `api_keys`, "X-API-Key", "dual auth", Swagger | `api-platform` |
| `theme tokens`, "no hardcoded shades", `useMantineTheme` | `mantine-theme-discipline` |
| `@mantine/spotlight`, "Cmd-K", "command palette" | `spotlight-cmdk` |
| `i18next`, `:lang` route prefix, "RTL", "Arabic" | `i18n-bilingual-rtl` |
| `manifest.webmanifest`, `vite-plugin-pwa`, "installable" | `pwa-setup` |
| `/setup` page, "DB check", "live checks" | `setup-guide-page` |
| `Dockerfile`, GHA workflow, Portainer | `deployment-setup` |

Two rules:
- **Only include explicit signals.** Don't add a dep just because "it's usually nice to have logging first" — that's an opinion, not a prerequisite.
- **Cross-check every proposed slug against the real graph.** If you'd add `depends_on: [users-module]` but `users-module` isn't a skill in the graph, omit it.

Confidence: **high** for each dep you can cite a line number for; **medium** when it's implied; never include a **low**-confidence dep — leave it out and surface it as a manual-review note instead.

#### `description_short`

- One sentence, <100 chars, ends without a period (matches existing style).
- No marketing fluff ("powerful", "modern", "best-in-class").
- Lead with the noun: "Cmd-K command palette …", not "Add a Cmd-K command palette …".
- If the frontmatter `description` is too long, trim to the gist. Don't paraphrase if a clean shorter form already exists in the skill's "What This Skill Does" opener.

Confidence: **high** — short text is easy to get right.

### Step 5 — Self-check before emitting

Run through this list before showing the user the YAML block:

- [ ] All `depends_on` slugs exist in `skills-graph.yml`.
- [ ] `level` is consistent with `max(level of deps) + 1` (or null for audit).
- [ ] No cycle: none of the deps transitively depend on the new skill.
- [ ] `category` is one of the declared categories.
- [ ] `description_short` is under 100 chars.
- [ ] Confidence for each field is reported honestly. If a field is `low`, explicitly call out what would change the answer.

### Step 6 — Emit the output block

Use the exact format from "Output Format" above. Do NOT auto-edit `skills-graph.yml` — the user pastes and commits. The lint script catches mistakes on push.

---

## Edge Cases

- **Audit skills** — set `type: audit, level: null, depends_on: []`. Audits can target any project state and are run on demand.
- **Skill that touches both backend and frontend** — pick the category of the larger commit (usually backend = `auth`/`foundation`/`data`; frontend = `ui`). If genuinely 50/50, prefer `ui` (audience reads it as user-facing).
- **Skill that references a non-existent skill in its "Pairs Well With"** — that peer isn't a dep, it's a recommendation. Don't add to `depends_on`.
- **First skill in a new category** — propose adding the category to the `categories:` block too. Flag clearly in the output ("⚠️ proposed new category: `data` — confirm before adding").
- **Skill that should run before everything else** (e.g., a new foundation primitive) — `level: 0`. Don't try to wedge it in below the existing foundation skills; just declare it a peer.

---

## What This Skill Won't Do

- **Won't auto-edit `skills-graph.yml`.** Always proposes; never mutates.
- **Won't infer business value or priority.** That's the `project-skill-advisor`'s job, per-project.
- **Won't infer dependencies the new skill *should have but doesn't mention*.** It only reports what's in the SKILL.md, plus structural facts from the graph. If the user knows there's an implicit dep, they edit the proposal before pasting.

---

## Pairs Well With

- **`skill-builder`** — creates the SKILL.md. Run this immediately after.
- **`scripts/lint-skills-graph.py`** — the CI safety net that fails the build if a SKILL.md exists with no graph entry. Catches the case where you skip this skill entirely.

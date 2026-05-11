---
name: "Project Skill Advisor"
description: "Recommends which skills from this repo to apply to a given project, in dependency-correct order. Investigates the project's structure (NestJS modules, React routes, deps, existing patterns), cross-references against skills-graph.yml, runs per-skill 'already applied' heuristics, and writes a .project-skills.json side-car with three buckets: recommendations (level-sorted, depends-checked), alreadyApplied (with evidence), and notRecommended (with reason). Output is non-destructive — the side-car is the input for an Apply UI (Mission Control's drawer) or a manual run from /terminal. Use when starting a new project, onboarding an existing one to the standard pattern, or auditing a portfolio to see what's missing where."
---

# Project Skill Advisor

## What This Skill Does

Investigates a target project, evaluates it against every skill in this repo (via `skills-graph.yml`), and emits one side-car file at `<project-root>/.project-skills.json` containing:

- **`recommendations`** — skills the project should adopt, sorted topologically (dependencies first), each annotated with `level`, `depends_on`, `priority`, `reason`, and `estimated_effort`.
- **`alreadyApplied`** — skills the heuristics detect as already in place, each with `evidence` (the file/dep/code pattern that proved it).
- **`notRecommended`** — skills explicitly *not* suggested, each with a `reason` (project type mismatch, scope creep, etc.).

The side-car is **non-destructive** — it doesn't run any skill, doesn't touch project files. The apply step is a separate action (Mission Control's drawer button, or a manual `claude --allow-dangerously-skip-permissions` invocation per skill in `/terminal`).

## When to Use

- **Onboarding a new project** to the standard pattern (skill stack).
- **Auditing an existing project** to see what's missing.
- **Portfolio review** — run across N projects to spot gaps.
- After a significant feature addition that may have unlocked new skills (e.g., you just added user accounts → `audit-log` now applies).

## When NOT to Use

- Greenfield project that's still under 200 lines — wait until structure stabilizes.
- One-off scripts, CLIs, pure libraries — most skills target NestJS+React monoliths.
- Projects on a different stack (Next.js, Django, Rails) — the heuristics assume NestJS+Vite+Mantine.

---

## The Side-Car Schema

Single file at `<project-root>/.project-skills.json`:

```jsonc
{
  "$generatedBy": "project-skill-advisor",
  "$generatedAt": "2026-05-11T12:00:00.000Z",
  "$version": 1,

  "$sources": {
    "projectPath":      "/abs/path/to/project",
    "skillsCatalogPath": "/home/sammy/claude-skills",
    "skillsGraphPath":   "/home/sammy/claude-skills/skills-graph.yml",
    "skillsGraphVersion": 1,
    "skillsEvaluated":   14
  },

  "$findings": {
    "projectType":      "NestJS+React internal admin tool",
    "stack":            ["nestjs", "react", "vite", "mantine", "mongodb"],
    "audience":         "internal team (admin-seeded, no public signup)",
    "existingPatterns": ["JWT httpOnly cookies", "JSON file logging via winston", "Mantine 8 with light theme"],
    "pageCount":        12,
    "controllerCount":  18,
    "deployStatus":     "deployed at mission-control.46.62.210.62.sslip.io via Caddy + systemd"
  },

  "recommendations": [
    {
      "skill": "audit-log",
      "level": 2,
      "category": "auth",
      "depends_on": ["jwt-auth-admin-seeded", "logging-setup"],
      "depends_satisfied": true,
      "priority": "high",
      "reason": "12 mutation endpoints (POST /users, PATCH /projects, DELETE /audit-rules…) but no `audit_logs` collection or AuditService — every admin action currently flies un-attributed.",
      "estimated_effort": "30 min Claude session",
      "applyHint": "Adds AuditService (@Global, fire-and-forget) + admin-only /audit page with filters + payload-redaction for secrets."
    },
    {
      "skill": "spotlight-cmdk",
      "level": 3,
      "category": "ui",
      "depends_on": ["mantine-theme-discipline"],
      "depends_satisfied": true,
      "priority": "medium",
      "reason": "12 pages in src/pages — past the 5-page threshold where Cmd-K starts paying off.",
      "estimated_effort": "20 min Claude session"
    }
  ],

  "alreadyApplied": [
    {
      "skill": "monolith-setup",
      "evidence": "backend/public/ contains built frontend; ServeStaticModule registered in app.module.ts:42; React Router fallback to index.html in main.ts:67"
    },
    {
      "skill": "jwt-auth-admin-seeded",
      "evidence": "src/auth/strategies/jwt.strategy.ts uses process.env.JWT_SECRET; scripts/seed-admin.ts exists; AuthContext + ProtectedRoute in frontend/src/services/auth/"
    },
    {
      "skill": "mantine-theme-discipline",
      "evidence": "frontend/src/utils/theme.ts uses only theme tokens; grep for hardcoded hex outside theme.ts returned 0 matches"
    }
  ],

  "notRecommended": [
    {
      "skill": "i18n-bilingual-rtl",
      "reason": "Project is single-language English-only — no Arabic requirement signaled by the codebase or README. Adding bilingual is scope creep."
    },
    {
      "skill": "api-platform",
      "reason": "Pure internal tool with no external integration use-case in the README or commit log. JWT cookie auth is sufficient for the admin UI; API keys would be unused infrastructure."
    }
  ]
}
```

Every section is optional — omit when there's nothing to put in it. Don't emit an empty `recommendations` array as a signal of "no work to do"; if all skills are applied, write a one-line note in `$findings.deployStatus` instead.

---

## Investigation Procedure

Six ordered steps. Step 3 (already-applied heuristics) is the heart of the skill — get it wrong and you'll either re-apply skills that are already in place (corruption) or skip skills the user actually needs (gaps).

### Step 1 — Load the graph

```bash
# Read the source-of-truth file from the skills repo
cat /home/sammy/claude-skills/skills-graph.yml | head -20

# Parse it and topologically sort the skill list (Python or yaml-aware tool).
# The order matters: recommendations are emitted in topo order so a downstream
# UI can present "you must do A before B" correctly.
```

If `skills-graph.yml` isn't readable, abort with a clear error pointing at it. Do not invent dependencies.

### Step 2 — Inventory the target project

```bash
cd "$TARGET_PROJECT"

# What kind of project is this?
ls -la backend/ frontend/ src/ 2>/dev/null | head
cat package.json 2>/dev/null
cat backend/package.json frontend/package.json 2>/dev/null | head -40

# How big?
find src backend/src frontend/src -name "*.ts" -o -name "*.tsx" 2>/dev/null | wc -l
find frontend/src/pages -maxdepth 2 -name "*.tsx" 2>/dev/null | wc -l

# What's deployed where?
cat README.md 2>/dev/null | head -20
git log -20 --format='%s' 2>/dev/null

# Side-car already exists?
[ -f .project-skills.json ] && echo "(prior run exists)" && head -30 .project-skills.json
```

Record findings into `$findings` — stack array, page count, controller count, audience inference, deploy status.

### Step 3 — Per-skill detection heuristics

For each skill in the graph, run the `detect_applied` heuristic from the table below. Classify into one of three buckets:

- **APPLIED** → goes into `alreadyApplied[]` with evidence
- **APPLICABLE_AND_NOT_APPLIED** → goes into `recommendations[]` with reason
- **NOT_APPLICABLE** → goes into `notRecommended[]` with reason (project doesn't fit the skill)

### Step 4 — Dependency check

For each entry in `recommendations[]`, set `depends_satisfied`:

- `true` if every entry in `depends_on` is in `alreadyApplied[]` or higher in `recommendations[]` (will be applied first)
- `false` otherwise — but DO NOT remove from recommendations. Surface the missing dep in `reason`.

This lets the UI flag "you selected B but its dep A isn't selected" without the skill making that decision unilaterally.

### Step 5 — Priority assignment

For each recommendation, assign one of: `high | medium | low`:

- **high** — skill plugs a security/correctness gap or is a prerequisite for another high-priority skill. Example: `audit-log` on an admin tool, `jwt-auth-admin-seeded` on a project with empty `src/auth/`.
- **medium** — skill is valuable but the project works without it. Example: `spotlight-cmdk` on a project with enough pages to justify, `mantine-theme-discipline` if the project currently has dark-mode bugs.
- **low** — quality-of-life upgrade. Example: `setup-guide-page` is nice but not blocking. `pwa-setup` on a desktop-first tool.

### Step 6 — Write the side-car

Topologically sort `recommendations[]` so dependencies come first. Write to `<project-root>/.project-skills.json` with 2-space indent. If a prior `.project-skills.json` exists, **preserve any `$userNotes` block** the user added by hand.

---

## Per-Skill Detection Heuristics

The most important part of this skill. Each row is the contract: how to detect "already applied", what signals justify recommending it, what disqualifies it.

| Skill | Detect as applied if … | Recommend if … | Skip if … |
|---|---|---|---|
| `monolith-setup` | `backend/public/` populated AND `ServeStaticModule` registered AND React Router fallback present | Separate `backend/` + `frontend/` dirs, both with package.json, no single-port serving yet | Pure backend / pure frontend / Next.js / non-NestJS |
| `logging-setup` | `src/logger/` directory exists OR `winston`/`pino`/`@nestjs/common Logger` instances writing to `/logs/*.log` with rotation | NestJS backend with bare `console.log` and no log files in `/logs/` | Not NestJS, or already logs to a service (Datadog, etc.) |
| `nestjs-throttle` | `@nestjs/throttler` in deps AND `ThrottlerModule.forRoot` in `app.module.ts` AND skip-rule for static assets present | `monolith-setup` applied, throttler dep missing, public auth/API routes exposed | Internal-network only, or behind a rate-limiting proxy |
| `jwt-auth-admin-seeded` | `src/auth/` with JWT strategy AND `scripts/seed-admin*` AND frontend `AuthContext`+`ProtectedRoute` | Project has user-facing endpoints OR admin UI but no `src/auth/` directory | No user concept (pure compute service), or already uses session cookies + CSRF instead |
| `audit-log` | `AuditService` exists AND `audit_logs` collection in a Mongoose schema AND `/audit` route in frontend | `jwt-auth-admin-seeded` applied AND ≥3 mutation endpoints (POST/PATCH/DELETE controllers) | Read-only app, or non-mutating ETL service |
| `api-platform` | `api_keys` collection AND dual-auth guard accepts both JWT and `X-API-Key` | External integration mentioned in README/commits OR project meant for programmatic access | Pure internal tool with no programmatic-access use case |
| `mantine-theme-discipline` | `frontend/src/utils/theme*` uses ONLY `theme.colors.<name>[idx]` style tokens AND no hardcoded hex outside theme file AND no `bg="gray.0"`-style fixed shades | Mantine in deps AND grep finds hardcoded hex / fixed-shade props (`bg="white"`, `c="gray.6"`, etc.) | Not Mantine, or already clean |
| `spotlight-cmdk` | `@mantine/spotlight` in deps AND a `<Spotlight />` component mounted in app shell | `mantine-theme-discipline` satisfied AND `frontend/src/pages/` has ≥5 top-level pages | <5 pages, or not Mantine |
| `i18n-bilingual-rtl` | `i18next` + `react-i18next` in deps AND `:lang` route prefix in controllers AND `dir="rtl"` styling present | README/commits explicitly mention Arabic, MENA, or RTL — OR project has Arabic content data | English-only project (default assumption); never recommend unprompted |
| `pwa-setup` | `frontend/public/manifest.webmanifest` exists AND `vite-plugin-pwa` in deps AND maskable icons present | React+Vite frontend AND mobile-relevant (touch UI, drawer-heavy, capture flows) AND no manifest yet | Desktop-only admin console where no one would install it |
| `setup-guide-page` | `/setup` route exists in frontend AND backend `/api/setup/checks` controller exists | Admin tool with DB + proxy + systemd dependencies AND `jwt-auth-admin-seeded` applied | Not an admin tool, or pre-existing onboarding flow |
| `deployment-setup` | `Dockerfile` + `.github/workflows/docker-build-push.yml` + production `docker-compose.yml` all exist | Project not yet deployed OR no CI/CD configured | Already has working production deploy, even if non-standard |
| `bulk-db-audit` | (audit skill, always available — never "applied") | Mongoose project AND grep finds `for ... await Model.findOne` / `await Model.create` loops in controllers/services | Not Mongoose |
| `project-metadata-refiner` | (audit skill, always available) | `package.json.name` is generic (e.g. `vite-project`) OR `description` empty/stale OR `.project-meta.json` missing | Already-perfect metadata (rare) |

### How to write a heuristic correctly

- **Be conservative.** When in doubt, mark as APPLIED. Re-applying a skill is more destructive than skipping one — the user can always run the skill manually.
- **Cite specific evidence.** "Has Mongoose" is too vague. "`@nestjs/mongoose` in `backend/package.json:dependencies`, 14 `*.schema.ts` files in `backend/src/`" is good.
- **Don't infer intent.** "Project probably needs i18n because the user lives in the MENA region" is wrong. Only signal what the codebase actually shows.

---

## Output Verification

Before writing the side-car, confirm:

- Every recommendation's `depends_on` array contains only known skills (cross-check against the graph).
- `recommendations` array is in topological order — verify no entry depends on a later entry.
- Every recommendation has a non-empty `reason` (a string with concrete evidence, not "this is generally good").
- Every entry in `notRecommended` has a non-empty `reason`.
- No skill appears in more than one of `recommendations` / `alreadyApplied` / `notRecommended`.
- JSON parses cleanly (`jq . .project-skills.json`).

---

## Applying the Side-Car

The skill stops at writing the side-car. The apply step happens elsewhere:

- **Mission Control's drawer** — opens the side-car, presents recommendations with checkboxes. Clicking "Apply N skills" composes ONE Claude prompt that runs each selected skill in topo order, committing + pushing after each.
- **Manual from /terminal** — open Claude Code in the project root, invoke each skill via the Skill tool one at a time, commit between.

For the Mission Control prompt template (when applying multiple skills in one Claude session):

```text
Apply these N skills to the project at <projectPath>, in dependency-correct order.
For each skill:

  1. Invoke it using the Skill tool: <slug>
  2. Follow its procedure end-to-end.
  3. Run `git status --short` to confirm what changed.
  4. Stage + commit: `git add -A && git commit -m "feat: apply skill <slug>"`.
  5. Push: `git push`.
  6. Move to the next skill.

Skills (already in topo order):
  1. <slug-1> — reason: <reason-1>
  2. <slug-2> — reason: <reason-2>
  …

If any skill fails midway, STOP and report. Do not continue to the next one
with a broken state. Don't skip a skill silently.
```

---

## Edge Cases

- **Project has no `.project-skills.json` yet** — first run; emit fresh side-car.
- **Side-car exists, project state has changed** — re-run; preserve `$userNotes`, overwrite everything else.
- **A skill in the graph has no SKILL.md file in the repo** — log a `WARN:` in `$findings.warnings[]`, still include in evaluation (the heuristic may still work from the slug alone).
- **Project is itself this repo (`claude-skills`)** — short-circuit: emit a side-car with empty `recommendations` and a note that meta-application doesn't make sense.
- **`depends_on` chain unsatisfied** — recommend the dependent skill anyway, set `depends_satisfied: false`, and explicitly list the missing prereq in `reason`. The UI's job to decide whether to auto-add or warn.

---

## Pairs Well With

- **`project-metadata-refiner`** — run that one first so the project's name + description + README are sane; the skill advisor uses those to infer project type. Their side-cars are independent.
- **Any skill in the catalog** — this skill exists to point at them.

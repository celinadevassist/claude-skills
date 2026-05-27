---
name: "Skill Verification Runner"
description: "Executes nextActions[] from .project-skills.json and stamps verified/verifiedAt/verificationOutput on every alreadyApplied entry. The runtime half of advisor v2 — without it every project's skillVerification dimension in .project-readiness.json stays at 0/15. Use after applying skills, after refreshing the advisor side-car, as a pre-merge gate, or as a scheduled portfolio-health check."
---

# Skill Verification Runner

## What This Skill Does

Reads a project's `.project-skills.json`, walks every entry in `alreadyApplied[]` that has a `nextActions[]` list, executes each non-`Manual:` action as a shell command, and stamps three fields on the entry:

- **`verified: true`** — every auto check passed
- **`verified: false`** — at least one auto check failed
- **`verified: null`** — only `Manual:` actions exist; nothing to auto-verify

Plus `verifiedAt` (ISO timestamp) and `verificationOutput` (one-line summary).

The runner is the **runtime half** of the advisor v2 schema: the advisor writes `nextActions[]`, the runner executes them. They are intentionally split so the read-only audit (advisor) never has side effects, and the side-effectful execution (runner) is opt-in.

This skill ships a reference implementation at [`scripts/run-skill-verification.py`](../scripts/run-skill-verification.py). The SKILL.md defines the contract; the script is the canonical executor.

## When to Use

- **Right after applying skills** to a fresh project — confirms each skill landed cleanly before moving on.
- **After re-running `project-skill-advisor`** (e.g. to upgrade a side-car to v2) — populates the `verified` field for the first time.
- **As a pre-merge gate** — fail the build if any applied skill regressed.
- **As a portfolio-wide health check** — cron the runner across every project nightly; flip Mission Control tile colors based on `verified: false` results.
- **Before computing readiness** — running this immediately before `project-readiness-report` is what lifts the `skillVerification` dimension above 0/15.

## When NOT to Use

- The project's `.project-skills.json` is still v1 (no `nextActions[]` field) — re-run `project-skill-advisor` first.
- The project's services aren't running locally — many `nextActions` `curl localhost:NNNN` style commands will fail. Either start the app or skip with `--dry-run` first to preview.
- You're auditing a project without write access — use `--no-write` to see what *would* be stamped without persisting.

---

## Contract

### Inputs

A `.project-skills.json` matching the advisor v2 schema (see `project-skill-advisor/SKILL.md`). Specifically, the runner reads:

- `alreadyApplied[].skill` — for labeling
- `alreadyApplied[].nextActions[]` — array of shell commands (or `Manual:` prose)

### Outputs

For every entry in `alreadyApplied[]` that has at least one `nextActions[]` entry, the runner sets:

```jsonc
{
  "skill": "pwa-setup",
  "evidence": "...",
  "nextActions": [...],

  "verified":           true,                              // NEW
  "verifiedAt":         "2026-05-27T20:50:00.000Z",        // NEW
  "verificationOutput": "all 2 auto-check(s) passed"       // NEW
}
```

If a prior run set these fields, the runner **overwrites them** (verification is point-in-time). Every other field is preserved verbatim.

### What the runner NEVER does

- Modify `recommendations[]`, `notRecommended[]`, `catalogGaps[]`, `$findings`, `$sources`.
- Add new entries to `alreadyApplied[]`.
- Change `evidence`, `appliedVersion`, `catalogVersion`, `outdated`, `nextActions[]`.
- Commit or push.
- Send notifications.

The runner is **stamping-only** — it observes and records, never decides or restructures. The advisor owns structure; the runner owns observation.

---

## How to Run

### Basic — verify everything in a project

```bash
python3 /home/sammy/claude-skills/scripts/run-skill-verification.py /home/sammy/my-project
```

### Dry-run — see commands without executing

```bash
python3 .../run-skill-verification.py /home/sammy/my-project --dry-run
```

Useful first time on a project to confirm command shapes are sane before letting them touch the system.

### One skill at a time

```bash
python3 .../run-skill-verification.py /home/sammy/my-project --only pwa-setup
```

Updates only that entry; everything else is preserved verbatim.

### Slow project (e.g. `npm run build` in a nextAction)

```bash
python3 .../run-skill-verification.py /home/sammy/my-project --timeout 120
```

Per-command timeout (default: 30s). Each `nextAction` gets its own clock.

### Preview-only (stamp would-be values, don't write)

```bash
python3 .../run-skill-verification.py /home/sammy/my-project --no-write
```

Runs commands, prints what verified/verifiedAt/output WOULD be, but doesn't touch the side-car.

---

## Sample Output

```text
Skill Verification Runner — expense-tracking-app
  side-car:  /home/sammy/expense-tracking-app/.project-skills.json
  cwd:       /home/sammy/expense-tracking-app
  timeout:   30s per command

  monolith-setup:
    PASS curl -sI http://localhost:3044/ | head -1
    PASS curl -sI http://localhost:3044/api/health

  logging-setup:
    PASS ls -la logs/*.log
    FAIL tail -1 logs/application.log | jq .
         exit 4: jq: error (at <stdin>:1): Cannot iterate over null

  pwa-setup:
    PASS curl -sI http://localhost:3044/manifest.json | head -1

  spotlight-cmdk:
    (manual-only — verified: null)

Summary
  PASS  verified=true:   11
  FAIL  verified=false:   1
  MAN   verified=null:    1   (manual-only / nothing to auto-run)
  SKIP  no field:         0   (no nextActions in side-car)

Wrote /home/sammy/expense-tracking-app/.project-skills.json
```

---

## How `nextActions[]` Should Be Written

The runner is only as good as the actions the advisor put in. Per the advisor's `nextActions[]` rules:

- Each action ≤ 100 characters, single line, copy-pasteable into a terminal.
- Inline comments with `# expect: ...` are encouraged — the runner **strips them before exec** (they're documentation, not assertion).
- `Manual:` prefix → not executable; runner counts but doesn't run them.
- Prefer real commands over prose. If prose is unavoidable, use `Manual: ...`.

### Examples that work well

```text
"curl -sI http://localhost:3044/api/health   # expect 200 + JSON"
"cd frontend && npm run lint:colors"
"ls -la logs/*.log"
"tail -1 logs/application.log | jq ."
"Manual: open /setup as admin and confirm all live checks pass"
```

### Examples that DON'T work well

```text
"check that the manifest is reachable"                     ← prose, not a command
"npm run build && deploy.sh"                               ← runs full deploy on every gate
"DROP TABLE refresh_tokens; -- only kidding, don't run"    ← obviously
```

---

## Safety

The runner executes whatever's in `nextActions[]` via `bash -c` with shell expansion enabled. This is intentional — many real verification commands are pipelines (`for i in $(seq...); do curl...; done | sort | uniq -c`).

Mitigations:

- **The user explicitly invokes the runner.** It is not invoked automatically by any other skill.
- **`nextActions[]` is author-controlled, not user-input.** The advisor writes them based on each skill's Verification Checklist; they aren't sourced from untrusted callers.
- **Per-command timeout** (default 30s) prevents runaway hangs.
- **cwd is pinned to the project root**, not `/` — accidental relative-path damage is contained.
- **Dry-run mode** (`--dry-run`) shows every command before any execution.

What the runner deliberately does NOT do:

- It does **not** sandbox commands. A `nextAction` that runs `rm -rf` would happily do so.
- It does **not** filter or sanitize commands. The author's intent is trusted.
- It does **not** request elevated privileges. Commands run as the invoking user.

Run on machines you trust, against side-cars you trust. Treat unfamiliar side-cars the same way you'd treat an untrusted shell script.

---

## Edge Cases

| Situation | Behavior |
|---|---|
| `alreadyApplied[]` is empty | Prints a NOTE, exits 0 — no work to do |
| Entry has no `nextActions[]` (v1 side-car) | Skipped with a `—` marker; `verified` not touched |
| All `nextActions[]` are `Manual:` | `verified: null`, output: `"unknown — N manual action(s) only, no auto-checks"` |
| One of N auto-actions fails | `verified: false`, output mentions the FIRST failure (so the summary is one-line) |
| Command times out | Counts as a failure; output: `"timed out after Ns"` |
| Side-car is invalid JSON | Exit 1, never modifies the file |
| `--only X` for a skill not in `alreadyApplied[]` | Exit 1 with error message |
| Re-running on an already-verified entry | Overwrites verified/verifiedAt/output — verification is point-in-time, not historical |

---

## Pairs Well With

- **`project-skill-advisor`** — produces `nextActions[]` for this runner to execute. Run the advisor first; run the runner after.
- **`project-readiness-report`** — consumes the `verified` field this runner writes. Run the runner before re-scoring readiness, or the verification dim stays at 0/15.
- **CI integration** — wire the runner into a GH Actions workflow on every push; fail the build on `verified: false` to catch regressions early.

This skill is the **third leg** of the audit triangle: advisor (intent) → runner (verification) → readiness-report (synthesis). Skip the runner and the readiness score is missing the "is it actually healthy?" signal.

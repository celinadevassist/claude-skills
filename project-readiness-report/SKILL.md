---
name: "Project Readiness Report"
description: "Rolls up the three project side-cars (.project-meta.json from project-metadata-refiner, .project-skills.json from project-skill-advisor, .project-technical-prd.json from project-technical-analyzer) into a single 0-100 readiness score plus a tile-friendly summary and a prioritized punch-list. Use after the three input audits have run, when you need one number per project for a portfolio dashboard (Mission Control tiles), a 'is this shippable?' gate before a public launch, or a periodic portfolio-health sweep."
---

# Project Readiness Report

## What This Skill Does

Reads the three project side-cars produced by the other audit skills and emits exactly one new file at `<project-root>/.project-readiness.json` containing:

- **`score`** — a single integer 0-100 capturing project shipping-readiness.
- **`tier`** — one of `ship-ready` / `ship-with-caveats` / `needs-work` / `foundational-gaps`.
- **`headline`** — one sentence that names the single biggest blocker (or the single biggest win, if score ≥ 80).
- **`breakdown`** — the 5 weighted dimensions that produced the score.
- **`punchList`** — a top-10 prioritized list of concrete next actions, drawn from the inputs.
- **`trend`** — score delta vs. the previous run (if a prior `.project-readiness.json` exists).

The side-car is **read-only of the three inputs** — it never modifies `.project-meta.json`, `.project-skills.json`, or `.project-technical-prd.json`. It also never applies any skill; it only reports.

## When to Use

- **Portfolio tile** — Mission Control shows one number per project; this skill computes that number.
- **Pre-launch gate** — before a project goes public, run this and require `score ≥ 80`.
- **Periodic sweep** — run weekly across the whole portfolio; sort projects by score ascending to find the most-neglected.
- **After a big change** — re-run after a metadata refresh, a batch skill-apply, or an infra checklist update to see the score move.

## When NOT to Use

- The three input side-cars don't exist yet — run those audits first. If any input is missing, this skill emits a side-car with `score: null` and a `WAITING:` entry in `punchList[]` rather than guessing.
- One-off scripts, pure libraries, projects under 200 lines — readiness scoring isn't meaningful at that scale.
- As a substitute for the input audits — this skill aggregates; it doesn't replace `project-metadata-refiner` etc.

---

## The Side-Car Schema

Single file at `<project-root>/.project-readiness.json`:

```jsonc
{
  "$generatedBy": "project-readiness-report",
  "$generatedAt": "2026-05-27T18:30:00.000Z",
  "$version": 1,

  "$sources": {
    "projectMetaPath":      "/abs/path/.project-meta.json",
    "projectMetaFound":     true,
    "projectSkillsPath":    "/abs/path/.project-skills.json",
    "projectSkillsFound":   true,
    "projectTechPrdPath":   "/abs/path/.project-technical-prd.json",
    "projectTechPrdFound":  true,
    "priorReadinessPath":   "/abs/path/.project-readiness.json",
    "priorReadinessFound":  true
  },

  "score":    78,
  "tier":     "ship-with-caveats",
  "headline": "One required infra dimension (cd) is incomplete and 2 applied skills are outdated — fix those and the project clears 85.",

  "breakdown": {
    "metadataHealth":    { "score": 18, "max": 20, "note": "1 RECOMMEND open; 0 MISSING/STALE/INCONSISTENT" },
    "skillAdoption":     { "score": 38, "max": 40, "note": "13 applied / 0 recommended; all high-priority recs satisfied" },
    "skillVerification": { "score": 12, "max": 15, "note": "11 verified-clean / 1 verified-broken / 1 unknown" },
    "skillDrift":        { "score":  8, "max": 10, "note": "2 of 13 applied skills are outdated (pwa-setup v1 vs v2, mantine-theme-discipline v1 vs v2)" },
    "infraCompleteness": { "score":  2, "max": 15, "note": "6 of 7 infra dimensions complete; 'cd' missing" }
  },

  "punchList": [
    { "rank": 1, "category": "infra",         "action": "Wire push-to-deploy CD: extend .github/workflows/docker-build-push.yml to trigger Watchtower pull",                     "pointsIfDone": 13 },
    { "rank": 2, "category": "drift",         "action": "Re-apply pwa-setup (v1 → v2 adds shortcuts + share_target manifest entries)",                                            "pointsIfDone":  4 },
    { "rank": 3, "category": "drift",         "action": "Re-apply mantine-theme-discipline (v1 → v2 tightens hex detection for nested style props)",                              "pointsIfDone":  4 },
    { "rank": 4, "category": "verification",  "action": "Re-run nextActions on logging-setup (last gate: 'log file 0 bytes after 1h — exception filter not firing')",            "pointsIfDone":  3 },
    { "rank": 5, "category": "verification",  "action": "Run nextActions on spotlight-cmdk (never gated yet)",                                                                    "pointsIfDone":  1 },
    { "rank": 6, "category": "metadata",      "action": "Address RECOMMEND: design a real og-banner — current is the auto-generated placeholder",                                 "pointsIfDone":  2 }
  ],

  "trend": {
    "priorScore":   71,
    "delta":        7,
    "direction":    "improving",
    "priorRunAt":   "2026-05-20T11:14:00.000Z"
  }
}
```

Schema notes:

- `score` is always an integer 0-100, never floating-point. Round half-up.
- `score: null` is permitted when one or more input side-cars are missing; in that case `tier: "incomplete"` and `punchList[]` starts with `WAITING:` entries naming each missing input.
- `breakdown.<dim>.score` + `.max` lets the UI render dimensions as progress bars without recomputing the math.
- `punchList[].pointsIfDone` is the rank-1 hint Mission Control uses to sort actions by "biggest score lift per task done".

---

## Scoring Model

Total = sum of 5 weighted dimensions = 100 max.

### Dimension 1 — Metadata Health (20 pts)

Reads `.project-meta.json.diagnostics[]`:

```
metadataHealth = 20 - sum_of_open_diagnostics_with_penalty
  where each open diagnostic costs:
    MISSING:      -4
    STALE:        -3
    INCONSISTENT: -3
    RECOMMEND:    -1
    TODO:         -1
    WARN:         -1
    BREAKING:     -2
    RESOLVED:      0   (resolved diagnostics don't subtract)
```

Floor at 0; never negative. Cap at 20.

### Dimension 2 — Skill Adoption (40 pts)

Reads `.project-skills.json.recommendations[]` + `.alreadyApplied[]`:

```
applied  = len(alreadyApplied)
pending  = len(recommendations)
total    = applied + pending

if total == 0:
  skillAdoption = 40   (no skills apply to this project; full credit)
else:
  baseRatio       = applied / total                      # 0.0 - 1.0
  highPriorityRec = count(recommendations where priority == "high")
  highPriorityPenalty = min(highPriorityRec * 3, 10)     # cap at 10
  skillAdoption   = round(baseRatio * 40 - highPriorityPenalty)
```

Floor at 0. The high-priority penalty is what makes "10 low-priority recs pending" worth more than "1 high-priority rec pending".

### Dimension 3 — Skill Verification (15 pts)

Reads the `verified` field on each `alreadyApplied[]` entry:

```
verifiedClean   = count(alreadyApplied where verified == true)
verifiedBroken  = count(alreadyApplied where verified == false)
unknown         = count(alreadyApplied where verified field absent)
total           = verifiedClean + verifiedBroken + unknown

if total == 0:
  skillVerification = 15
else:
  cleanRatio       = verifiedClean / total
  brokenPenalty    = min(verifiedBroken * 3, 10)
  skillVerification = round(cleanRatio * 15 - brokenPenalty)
```

Floor at 0. A verified-broken skill is worse than an unknown one — at least unknown might pass.

### Dimension 4 — Skill Drift (10 pts)

Reads the `outdated` field on each `alreadyApplied[]` entry:

```
applied  = len(alreadyApplied)
outdated = count(alreadyApplied where outdated == true)

if applied == 0:
  skillDrift = 10
else:
  skillDrift = round((applied - outdated) / applied * 10)
```

### Dimension 5 — Infra Completeness (15 pts)

Reads `.project-technical-prd.json.infraChecklist`:

```
totalDims      = 7  # host, domain, storage, database, docker, ci, cd (fixed by analyzer)
completeDims   = count(infraChecklist where status in {"complete", "verified"})

infraCompleteness = round(completeDims / totalDims * 15)
```

### Tier mapping

```
score 80-100 → "ship-ready"
score 60-79  → "ship-with-caveats"
score 40-59  → "needs-work"
score  0-39  → "foundational-gaps"
score null   → "incomplete"  (one or more inputs missing)
```

---

## Synthesis Procedure

Six steps, in order. Steps 1-3 gather; steps 4-5 compute; step 6 writes.

### Step 1 — Locate the three inputs

```bash
[ -f "$PROJECT/.project-meta.json"          ] && echo "meta found"
[ -f "$PROJECT/.project-skills.json"        ] && echo "skills found"
[ -f "$PROJECT/.project-technical-prd.json" ] && echo "tech-prd found"
```

If any are missing, mark `$sources.<name>Found: false`, skip the corresponding dimension (treat as 0 contributed), and add a `WAITING:` entry to `punchList[]` with `pointsIfDone` equal to the dimension's max (so the UI shows "run this audit for up to N more points").

Never invent diagnostics or scores for a missing input.

### Step 2 — Parse and extract relevant fields

```bash
jq '.diagnostics'        .project-meta.json          # for Dimension 1
jq '.recommendations, .alreadyApplied' .project-skills.json   # for Dimensions 2-4
jq '.infraChecklist'     .project-technical-prd.json # for Dimension 5
```

Use `jq` (or equivalent) — do not regex-parse JSON.

### Step 3 — Load the prior readiness report (if any)

```bash
[ -f "$PROJECT/.project-readiness.json" ] && jq '.score, .$generatedAt' .project-readiness.json
```

This is what powers the `trend` block. If no prior exists, omit `trend` entirely (don't write `trend: null`).

### Step 4 — Compute each dimension

Apply the formulas in "Scoring Model" exactly. Round half-up. Floor at 0.

### Step 5 — Compose the punchList

Walk the inputs in this order and emit one punchList entry per actionable item:

1. **Infra gaps** (highest `pointsIfDone` per item — usually) — one entry per `infraChecklist` dimension with status != complete.
2. **Drift** — one entry per `alreadyApplied` with `outdated: true`.
3. **Broken verifications** — one entry per `alreadyApplied` with `verified: false`.
4. **Unknown verifications** — one entry per `alreadyApplied` with `verified` field absent.
5. **High-priority recommendations** — one entry per `recommendations[]` with `priority: "high"`.
6. **Metadata diagnostics** — one entry per open MISSING/STALE/INCONSISTENT (skip RECOMMEND/TODO unless score ≥ 80, when polish matters).
7. **Medium/low recommendations** — only if `punchList[]` < 10 entries so far.

Sort the final list by `pointsIfDone` descending. Re-number `rank` after sort. Cap at 10 entries; if more exist, add an 11th entry `{rank: 11, category: "..", action: "...and N more — see input side-cars", pointsIfDone: 0}`.

### Step 6 — Compose headline + write side-car

The `headline` is one sentence, ≤ 140 chars:

- For `score >= 80`: name the strongest dimension as the takeaway. `"All applied skills verified clean and 7/7 infra dimensions complete — ship-ready."`
- For `score 40-79`: name the single biggest deficit. `"One required infra dimension (cd) is incomplete and 2 applied skills are outdated — fix those and the project clears 85."`
- For `score < 40`: name the most foundational gap. `"4 high-priority skills not yet applied (jwt-auth-admin-seeded, logging-setup, ...) — address before any public exposure."`
- For `score == null`: `"Run <missing audits> first — readiness can't be scored without those inputs."`

Write `.project-readiness.json` with 2-space indent. Preserve any `$userNotes` block from a prior side-car.

---

## Output Verification

Before declaring done, confirm:

- `score` is an integer 0-100 OR explicitly `null`; never a float, never out of range.
- `tier` matches the score (use the tier-mapping table — no off-by-one).
- Sum of `breakdown.<dim>.score` equals `score` exactly (integer arithmetic, no rounding drift).
- Every `breakdown.<dim>.score` ≤ `breakdown.<dim>.max`; never negative.
- `punchList[]` has between 1 and 11 entries (10 + the overflow marker).
- `punchList[]` is sorted by `pointsIfDone` descending; ranks 1..N are contiguous.
- Every input flagged `Found: false` has a corresponding `WAITING:` entry in `punchList[]`.
- `trend` block is either fully populated or omitted entirely (never partial).
- JSON parses cleanly (`jq . .project-readiness.json`).

---

## Edge Cases

- **First run on a project** — no prior `.project-readiness.json`; omit `trend` entirely.
- **All three inputs missing** — `score: null`, `tier: "incomplete"`, `punchList[]` has 3 `WAITING:` entries (one per missing input).
- **`recommendations[]` empty AND `alreadyApplied[]` empty** — project doesn't fit the catalog at all; Dimension 2 gets full credit (40), but headline notes `"No catalog skills apply to this project type — readiness is metadata + infra only."`
- **Score equals the previous score** — emit `trend.delta: 0, direction: "stable"`.
- **`infraChecklist` has fewer than 7 dimensions** (older analyzer output) — log `WARN:` in headline, scale `totalDims` to what's present; flag in `punchList`.
- **`$userNotes` block in prior side-car** — preserve verbatim. Users use this for "ignore this dimension for now" notes; the skill must not overwrite them.

---

## Pairs Well With

- **`project-metadata-refiner`** — produces input #1. Run first.
- **`project-skill-advisor`** — produces input #2. Run after metadata-refiner so it can read the polished name/description.
- **`project-technical-analyzer`** — produces input #3. Independent; can run anytime.
- **Mission Control's portfolio view** — consumes `.project-readiness.json` as the single source of truth for the per-project tile score, color, and "what to do next" hint.

This skill is the **last** audit to run in any portfolio sweep — it aggregates everything else.

---
name: "Project Technical Analyzer"
description: "Turns a project's business PRD into a technical PRD plus a machine-readable infra checklist. Reads the business PRD(s) in prds/ and the design files in designs/, inspects the codebase, then writes prds/technical-prd.md (recommended stack, architecture, data model, feature breakdown, key decisions, risks) and a .project-technical-prd.json side-car whose infraChecklist covers 7 fixed dimensions (host, domain, storage, database, docker, ci, cd) that the Mission Control provisioning phase consumes. Non-destructive: preserves any $userNotes block on re-run. Use after a project is scaffolded with a business PRD, to produce the technical plan before building or provisioning."
---

# Project Technical Analyzer

## What This Skill Does

Given a project that already has a **business PRD** in `prds/` (e.g. dropped in by the
Mission Control New Project wizard), this skill produces two artifacts:

1. **`prds/technical-prd.md`** — a human-readable technical PRD.
2. **`.project-technical-prd.json`** — a machine-readable side-car consumed by Mission
   Control's Technical Analysis UI and the (future) provisioning phase.

It does NOT recommend skills — that is the job of `project-skill-advisor`. Run that
separately (or after this) to refresh `.project-skills.json`.

## When to Use

- Right after a project is scaffolded with a business PRD and (optionally) design mockups.
- Before building or provisioning, to turn "what & why" into "how".

## The Side-Car Schema

Write `<project-root>/.project-technical-prd.json` with 2-space indent:

```json
{
  "$generatedBy": "project-technical-analyzer",
  "$generatedAt": "<ISO timestamp>",
  "$version": 1,
  "$sources": {
    "businessPrdPaths": ["prds/<file>.md"],
    "designPaths": ["designs/<file>"],
    "technicalPrdPath": "prds/technical-prd.md",
    "codebaseScanned": true
  },
  "$findings": {
    "summary": "<one-paragraph technical summary of what to build and how>",
    "stack": ["<tech>", "..."],
    "keyDecisions": ["<decision>", "..."]
  },
  "infraChecklist": [
    { "dimension": "host",     "recommendation": "<this-server|remote>",   "detail": "<...>", "rationale": "<...>", "confidence": "<high|medium|low>" },
    { "dimension": "domain",   "recommendation": "<sslip|real>",           "detail": "<...>", "rationale": "<...>", "confidence": "<...>" },
    { "dimension": "storage",  "recommendation": "<local|volume|bucket>",  "detail": "<...>", "rationale": "<...>", "confidence": "<...>" },
    { "dimension": "database", "recommendation": "<local|atlas|none>",     "detail": "<...>", "rationale": "<...>", "confidence": "<...>" },
    { "dimension": "docker",   "recommendation": "<none|compose>",         "detail": "<...>", "rationale": "<...>", "confidence": "<...>" },
    { "dimension": "ci",       "recommendation": "<actions|none>",         "detail": "<...>", "rationale": "<...>", "confidence": "<...>" },
    { "dimension": "cd",       "recommendation": "<actions-ssh|watchtower|portainer-api|none>", "detail": "<...>", "rationale": "<...>", "confidence": "<...>" }
  ]
}
```

The 7 `dimension` values are FIXED and must all be present, in this order.

## Investigation Procedure

### Step 1 — Read the inputs
Read every `prds/*.md` EXCEPT `prds/technical-prd.md` (those are the business PRD(s)). List
the filenames in `designs/` (open the HTML/text ones; for images just note the names).

### Step 2 — Inventory the codebase
Check `package.json` (root/backend/frontend), existing stack, structure — enough to know
what (if anything) is already built.

### Step 3 — Write `prds/technical-prd.md`
Sections: Overview, Recommended stack, Architecture, Data model sketch, Feature → component
breakdown, Key technical decisions, Risks / open questions, and an "Infrastructure" section
that explains each of the 7 checklist dimensions in prose.

### Step 4 — Write `.project-technical-prd.json`
Fill `$findings.summary/stack/keyDecisions` and all 7 `infraChecklist` items. Pick concrete
recommendations; use `confidence` honestly. For a low-traffic internal tool on this host,
sensible defaults are: host=this-server, domain=sslip, storage=local, database=local,
docker=none, ci=actions, cd=actions-ssh.

### Step 5 — Preserve user notes
If `.project-technical-prd.json` already exists, preserve any top-level `$userNotes` block.

## Output Verification
- `prds/technical-prd.md` exists and is non-trivial.
- `.project-technical-prd.json` parses as JSON and has all 7 `infraChecklist` dimensions.

## Pairs Well With
- `project-skill-advisor` (skills) — run after this.
- The Mission Control "Technical analysis" section renders this side-car.

---
name: "Project Metadata Refiner"
description: "AI-driven audit of project identity. Cross-references package.json, README, deployed og: meta tags, and git history to produce a .project-meta.json side-car with refined name, description, keywords, full SEO/OpenGraph metadata, and README intro suggestions. Output is structured, non-destructive (writes one side-car file only), and ready for manual or scripted merge into package.json + README.md + index.html. Use when a project's name/description has drifted from what it actually does, before a public release, or when auditing an internal portfolio of projects."
---

# Project Metadata Refiner

## What This Skill Does

Investigates a project from four sources — codebase, docs, deployed site, and git history — then writes a single side-car file at `<project-root>/.project-meta.json` containing refined values for:

- **`package.json`** — `name`, `description`, `keywords`, `homepage`, `repository`, `license`, `author`
- **`README.md` top section** — H1 title, italic tagline, "what this is" intro paragraph
- **`index.html` meta tags** — `<title>`, `<meta description>`, full Open Graph (`og:title`, `og:description`, `og:image`, `og:url`, `og:type`, `og:site_name`), Twitter Card (`twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`)
- **Diagnostics list** — concrete inconsistencies the audit found (missing keywords, stale og:image URL, name/manifest mismatch, license file present but pkg `license` field empty, etc.)

The side-car is **non-destructive** — it does **not** edit `package.json`, `README.md`, or `index.html` directly. The user (or a follow-up step) merges values from the side-car into the real files. This makes the skill safe to run repeatedly and across many projects in a portfolio without overwriting hand-tuned text.

## When to Use

- Project name in `package.json` is auto-generated (e.g. `vite-project`, `nest-app`, `frontend`) and doesn't describe the business.
- Description field is empty, generic ("My new project"), or out of date with what the codebase actually does now.
- Preparing for public release / open-source / portfolio listing — you need consistent SEO and shareable links.
- Auditing a portfolio: run across N projects, review side-cars, batch-merge the obvious wins.
- After a pivot — feature set has moved but README/meta still describes the original product.
- Building a "Projects" landing page that scrapes `package.json` (like Mission Control's `/projects`) and wants the cards to read well.

## When NOT to Use

- The project is private, internal, never deployed publicly, and never referenced by name elsewhere — metadata churn is wasted effort.
- The project has hand-tuned, recently-written marketing copy — running this risks suggesting weaker text from old git context. Read the diagnostics, skip the suggestions.
- Pure libraries with no homepage and no UI — there's no og: tags or HTML to refine; just use the simpler `package.json`-only audit (call this skill with `--scope package` if the variant exists).

---

## The Side-Car Schema

The skill writes exactly one file: `<project-root>/.project-meta.json`. Schema:

```jsonc
{
  "$generatedBy": "project-metadata-refiner",
  "$generatedAt": "2026-05-12T14:30:00.000Z",
  "$version": 1,

  "$sources": {
    "packageJsonPath": "/abs/path/package.json",
    "readmePath": "/abs/path/README.md",
    "indexHtmlPath": "/abs/path/frontend/index.html",
    "homepageUrl": "https://example.com",
    "homepageFetched": true,
    "gitCommitsScanned": 50,
    "ogTagsFound": ["og:title", "og:description", "og:image"]
  },

  "$findings": {
    "currentName": "vite-project",
    "currentDescription": "",
    "inferredPurpose": "Headless CMS for restaurant menus with multi-tenant Stripe billing",
    "primaryAudience": "small-restaurant operators",
    "stack": ["nestjs", "react", "vite", "mongodb", "stripe"]
  },

  "package": {
    "name": "menukit-cms",
    "description": "Headless CMS for restaurant menus with multi-tenant Stripe billing and bilingual (en/ar) storefronts.",
    "keywords": ["restaurant-menu", "cms", "stripe", "multi-tenant", "bilingual", "nestjs", "react"],
    "homepage": "https://menukit.io",
    "repository": { "type": "git", "url": "https://github.com/celinadevassist/menukit" },
    "license": "UNLICENSED",
    "author": "Celina Devassist <hello@celina.dev>"
  },

  "readme": {
    "title": "MenuKit CMS",
    "tagline": "Headless menu management + storefront for independent restaurants.",
    "intro": "MenuKit is a multi-tenant CMS that lets restaurant operators manage menus in English and Arabic, push them to a hosted storefront, and bill customers through Stripe — all from a single dashboard. Built on NestJS, React, and MongoDB."
  },

  "html": {
    "title": "MenuKit — Restaurant Menu CMS & Storefront",
    "metaDescription": "Manage your restaurant's menu in English & Arabic, host a fast public storefront, and accept payments with Stripe. Multi-tenant CMS for independent operators.",
    "og": {
      "title": "MenuKit — Restaurant Menu CMS",
      "description": "Headless CMS + storefront + Stripe billing for independent restaurants.",
      "image": "https://menukit.io/og-banner.png",
      "url": "https://menukit.io",
      "type": "website",
      "siteName": "MenuKit"
    },
    "twitter": {
      "card": "summary_large_image",
      "title": "MenuKit — Restaurant Menu CMS",
      "description": "Headless CMS + storefront + Stripe billing for independent restaurants.",
      "image": "https://menukit.io/og-banner.png"
    }
  },

  "diagnostics": [
    "MISSING: package.json has no `keywords` array",
    "MISSING: package.json `description` is empty",
    "MISSING: no <meta property=\"og:image\"> in frontend/index.html",
    "STALE: README still says 'starter template for Vite + React'",
    "INCONSISTENT: package.json.name='vite-project' but manifest.webmanifest.short_name='MenuKit'",
    "RECOMMEND: og:image should be 1200x630 PNG — current is missing entirely"
  ]
}
```

Every top-level key is **optional but should be present when applicable**. If a project has no `index.html`, omit the `html` block entirely (don't write empty strings). If git scan was skipped, omit `gitCommitsScanned`.

---

## Investigation Procedure

Run these steps in order. Each step gathers evidence; the final step writes the side-car. Do not skip steps — every source disambiguates the others.

### Step 1 — Read what's already there

```bash
# Current package.json (full file — license, scripts, deps all carry signal)
cat package.json 2>/dev/null

# Top-level docs
cat README.md README.MD readme.md 2>/dev/null | head -200
ls docs/ 2>/dev/null | head

# License file (decides the package.json.license suggestion)
ls LICENSE LICENSE.md COPYING 2>/dev/null

# Manifest (for PWAs — name/short_name must match suggestions)
cat **/manifest.webmanifest **/manifest.json 2>/dev/null | head -30
```

Record current `name`, `version`, `description`, `keywords`, `homepage`, `repository`, `license`, `author` in `$findings.currentName` and `$findings.currentDescription`. These become the "before" half of every suggestion.

### Step 2 — Infer purpose from the codebase

Don't trust docs — read the code:

```bash
# Dependency signals (most accurate single source of truth)
jq '.dependencies, .devDependencies | keys' package.json 2>/dev/null

# Backend signals — what does the API actually serve?
find src backend/src -type d -maxdepth 3 2>/dev/null
grep -r "@Controller(" src backend/src 2>/dev/null | head -20

# Schemas / models — what nouns does the system care about?
find . -name "*.schema.ts" -o -name "*.entity.ts" -o -name "*.model.ts" 2>/dev/null | head -20

# Routes (frontend) — what pages exist?
grep -rE "<Route |path:" src frontend/src 2>/dev/null | grep -v node_modules | head -20

# Environment shape — secrets reveal integrations
grep -E "^[A-Z_]+=" .env.example .env.template 2>/dev/null | sed 's/=.*//'
```

Synthesize one sentence: "This project is a `<noun>` that does `<verb>` for `<audience>` using `<key tech>`." Put it in `$findings.inferredPurpose`. This sentence is the seed for every refined description below.

### Step 3 — Read git history for theme drift

```bash
# Last 50 commit subjects — recent themes often expose what the project has become
git log -50 --format='%s' 2>/dev/null

# Project age + breadth
git log --reverse --format='%aI %s' 2>/dev/null | head -3
git log -1 --format='%aI %s' 2>/dev/null
```

If recent commits cluster around topics not mentioned in the current `description`, that's drift — flag it in `diagnostics`. Example: description says "starter template" but last 30 commits are all about Stripe and tenant isolation → drift.

### Step 4 — Fetch the deployed site (if there is one)

Pick the homepage URL in this order: `package.json.homepage` → `package.json.repository.url` (only if it's a project page, not a repo) → CNAME files in `public/` or `frontend/public/` → `manifest.webmanifest.start_url` → ask the user.

```bash
# Read HTML, extract head only — full page is wasteful
curl -sL --max-time 8 "$HOMEPAGE_URL" | head -200
```

From the returned HTML, capture (record in `$sources.ogTagsFound`):

- `<title>`
- `<meta name="description" content="...">`
- `<meta property="og:title|og:description|og:image|og:url|og:type|og:site_name" content="...">`
- `<meta name="twitter:card|twitter:title|twitter:description|twitter:image" content="...">`

If the fetch fails (404, DNS, timeout), set `$sources.homepageFetched: false` and continue — don't block the rest of the audit. Add a diagnostic: `"WARN: homepage <url> unreachable — og: suggestions inferred from codebase only"`.

### Step 5 — Read the current `index.html`

```bash
cat frontend/index.html public/index.html backend/public/index.html 2>/dev/null | head -50
```

Compare what's *in the file* with what's *served live* (from Step 4). Differences usually mean a stale deploy or a build that strips meta. Either is a diagnostic.

### Step 6 — Synthesize and write the side-car

Apply the **field quality rules** (next section) to produce each value. Write the side-car as JSON (not JSONC — the `$`-prefixed keys are valid JSON, the `//` comments above are documentation only) to `<project-root>/.project-meta.json` using 2-space indent.

If `.project-meta.json` already exists, **read it first** — preserve any `$userNotes` or `$keep` blocks the user added by hand. Only overwrite the AI-generated sections.

---

## Field Quality Rules

These are the standards every suggested value must meet. If you can't meet the rule, leave the field out and add a diagnostic.

### `package.name`

- Kebab-case, ASCII, no leading numbers.
- Scoped (`@org/name`) only if the project is published to a registry under an org.
- Describes **what** not **how**: `restaurant-menu-cms` ✅, `react-vite-app` ❌.
- Max 40 chars (npm limit is 214, but readable matters).
- If renaming an existing project: add diagnostic `"BREAKING: name change from <old> to <new> requires updating dependents"`.

### `package.description`

- 50–160 characters (SEO sweet spot; truncates cleanly in card UIs).
- One sentence, ends with `.`.
- Leads with the noun, then the verb, then the audience: `"Headless CMS for restaurant menus with multi-tenant Stripe billing and bilingual storefronts."`
- No marketing fluff: no "best", "fastest", "powerful", "modern", "next-generation".
- No version numbers ("v2 of..." rots fast).
- No leading "A" or "The".

### `package.keywords`

- 3–10 entries. Fewer is fine; more dilutes.
- Lowercase, kebab-case or single word.
- Mix: 2-3 domain words (`restaurant`, `cms`, `multi-tenant`), 2-3 tech words (`nestjs`, `react`, `mongodb`), 1-2 distinguishing features (`bilingual`, `stripe`).
- No duplicates of `name` parts.
- No generic stuff (`web`, `app`, `javascript`, `typescript` — they match everything).

### `package.homepage` / `repository`

- `homepage` is the **public-facing site**, not the repo. If no public site, omit.
- `repository.url` must be `https://`, not `git@` SSH (npm convention).
- If both repo + homepage exist and differ, that's correct — don't conflate them.

### `package.license`

- If `LICENSE` file exists, parse the first line and map to SPDX (`MIT`, `Apache-2.0`, `GPL-3.0`, `UNLICENSED`).
- If no license file, suggest `"UNLICENSED"` and add diagnostic `"RECOMMEND: add a LICENSE file — license field is missing"`.
- Never guess `MIT` just because it's common.

### `readme.title`

- Brand case (`MenuKit CMS`, not `menukit-cms`).
- 1–4 words.
- Matches `package.name` semantically but reads naturally.

### `readme.tagline`

- Italic line under the H1.
- 50–80 chars.
- States the **for-whom** + **what**: "Headless menu management + storefront for independent restaurants."

### `readme.intro`

- 2–3 sentences (≈ 300 chars total).
- Answers in order: What is it? Who is it for? What's the stack?
- No code blocks, no badges — those come after.

### `html.title` (page `<title>`)

- 50–60 chars (Google truncates ~60).
- Format: `Brand — What it is` or `What it is | Brand`. Em-dash beats pipe for readability.
- Includes one keyword the audience would search for.

### `html.metaDescription`

- 150–160 chars (Google truncates ~160).
- Rephrases `package.description` for a public audience (less jargon, more outcome).
- Active voice, present tense.

### `html.og.image` / `html.twitter.image`

- Absolute URL (not `/og.png` — relative paths break when shared).
- 1200×630 PNG or JPG, ≤ 5 MB (per Facebook spec).
- If the project doesn't have one yet, suggest `https://<homepage>/og-banner.png` and add diagnostic `"TODO: create og-banner.png — 1200x630, branded"`.

### `html.og.type`

- `website` for SPAs and landing pages.
- `article` for blog posts (not relevant here).

### `html.twitter.card`

- Always `summary_large_image` if `twitter:image` is set. Otherwise `summary`.

---

## Diagnostics — What to Flag

Use these prefixes consistently so the diagnostics list filters cleanly later:

| Prefix | Meaning | Example |
|--------|---------|---------|
| `MISSING:` | Field is absent and should exist | `MISSING: package.json has no keywords` |
| `STALE:` | Field exists but is wrong/outdated | `STALE: description still says "starter template"` |
| `INCONSISTENT:` | Two sources disagree | `INCONSISTENT: pkg.name='foo' but manifest.short_name='Bar'` |
| `RECOMMEND:` | Not a defect, but a meaningful upgrade | `RECOMMEND: og:image dimensions should be 1200x630` |
| `BREAKING:` | Applying this suggestion has downstream cost | `BREAKING: name change from foo-app to foo-cms breaks npm consumers` |
| `WARN:` | Audit ran into a soft failure | `WARN: homepage <url> unreachable — used codebase fallback` |
| `TODO:` | Requires a creative/manual asset, not text | `TODO: create og-banner.png — 1200x630, branded` |

---

## Applying the Side-Car (Manual)

The skill stops at writing `.project-meta.json`. To merge, follow this checklist by hand or in a follow-up automation pass:

1. **`package.json`** — open it, copy each `package.*` field from the side-car. Don't blindly overwrite `name` if the project is published to a registry under the old name (check `BREAKING:` diagnostics first).
2. **`README.md`** — replace the top three lines (H1, italic tagline, intro paragraph). Leave the rest untouched.
3. **`frontend/index.html`** (or wherever the SPA shell lives) — replace `<title>` and the meta tags inside `<head>`. Order conventionally: `<title>` → description → og:* → twitter:*.
4. **`manifest.webmanifest`** (if PWA) — sync `name` and `short_name` to match the new brand.
5. **Re-deploy** — og: tags only take effect after the next build of the static shell, since they're rendered server-side.
6. **Verify** with Facebook Sharing Debugger and Twitter Card Validator after deploy. (They cache aggressively — use their "Scrape Again" buttons.)
7. **Delete the side-car** after merging — it's a working file, not a source of truth: `rm .project-meta.json`. Or commit it as a historical record under `.docs/metadata-audit/<date>.json` if you want a trail.

---

## Edge Cases

- **Monorepo** — run per-package. Each `package.json` gets its own side-car at the package root. Don't try to make one side-car cover a workspace.
- **No `index.html`** — pure library or CLI. Omit the `html` block entirely; don't fabricate og: tags.
- **No homepage** — fetch fails. Set `$sources.homepageFetched: false` and rely on codebase + README only.
- **Internal-only project** — still useful for the `package.name` + `description` polish for tools like Mission Control's `/projects` page. Skip og: tags; add diagnostic `"NOTE: skipped og: tags — project has no public homepage"`.
- **Conflicting README and og: tags** — the deployed og: tags often reflect the *most recent intent*; the README is often stale. Bias suggestions toward og: when they conflict, but flag the conflict in diagnostics.
- **Project with a generated description** (e.g. starts with `"My new …"` or `"A "`) — treat as empty for inference purposes.

---

## Output Verification

Before declaring done, verify:

- `.project-meta.json` parses as valid JSON (`jq . .project-meta.json`).
- Every top-level field with values uses real values, not placeholders (no `"TODO"`, `"..."`, `"<your name>"`).
- Character counts on `description`, `metaDescription`, `title` are within the rules above.
- Diagnostics list is non-empty (every project has at least *something* worth flagging — if it's empty, you didn't look hard enough).
- The inferred purpose sentence in `$findings.inferredPurpose` makes sense to a stranger.

---

## Pairs Well With

- **`mantine-theme-discipline`** — once metadata is polished, theme discipline polishes the UI shell that hosts it.
- **`pwa-setup`** — manifest fields (`name`, `short_name`, `description`) should match the side-car's package + html suggestions exactly.
- **`deployment-setup`** — re-deploy after merging so og: tags actually ship.

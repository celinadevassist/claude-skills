---
name: "Project Metadata Refiner"
description: "AI-driven audit of project identity. Cross-references package.json, README, deployed og: meta tags, and git history to produce a .project-meta.json side-car with refined name, description, keywords, full SEO/OpenGraph metadata, and README intro suggestions. Then runs a Technical Completeness Pass that auto-fills missing technical assets (og:image placeholder, root README, LICENSE, missing pkg fields, og:/twitter: meta tags) using the side-car as the source of truth — so the project becomes structurally correct without touching hand-tuned business copy. Use when a project's name/description has drifted from what it actually does, before a public release, or when auditing an internal portfolio of projects."
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
  "$ogBannerVersion": 2,    // cache-bust counter for og:image?v=N — bump on every banner re-render
  "$ogBannerMode": "ai-bg", // "pure-svg" (default) | "ai-bg" (opt-in via OPENAI_API_KEY)

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

## Step 7 — Technical Completeness Pass (Auto-Fill)

After the side-car is written, run an idempotent pass that resolves every `MISSING:` diagnostic the side-car *can* fix mechanically. The goal: make the project **structurally correct** — every link previews, every required asset exists, every package.json field is non-empty — using the side-car as the source of truth. The user can re-run the audit later and only the business copy will need tuning; the scaffolding is already in place.

**Principle: technical completeness, then business polish.** Auto-fill is for stuff a machine can decide. Business copy (the actual wording of `description`, `tagline`, `intro`) goes through human review via the side-car. Auto-fill *uses* the side-car's wording — it does not invent new wording.

### What auto-fill resolves (each gated by "only if missing")

| Diagnostic the side-car flagged | Auto-fill action | Source of truth |
|---|---|---|
| `MISSING: no og-banner.png` | Write SVG source to `frontend/public/og-banner.svg` using the **rich template** (icon + wordmark + tagline pill + domain-appropriate right-column preview card — see "Rich og-banner" section below). Render to `frontend/public/og-banner.png` (1200×630) via `rsvg-convert`. Bump `$ogBannerVersion` in the side-car and update `og:image` / `twitter:image` URLs to include `?v=N`. Both files commit — SVG is the editable source. | `readme.title` + `readme.tagline` + manifest theme_color + `$findings.inferredPurpose` (for the right-column preview content) |
| `MISSING: no logo / favicon` | If neither `favicon.svg`, `logo.svg`, nor `logo.png` exists in `frontend/public/` (or project root for non-frontend projects), write a placeholder `logo.svg`: rounded square in manifest theme_color, white project initials (first 2 letters of `readme.title`), 256×256 viewBox. Use until a real logo is designed. | `readme.title` initials + manifest theme_color |
| `MISSING: no <meta og:*> / twitter:*` in `index.html` | Inject the full og:/twitter: block from the side-car into `<head>` after the existing `<meta name="description">` | `html.og.*` + `html.twitter.*` |
| `MISSING: no README.md at project root` | Write a real root README: H1, italic tagline, intro paragraph, `## Documentation` pointer to `docs/`, auto-gen marker at bottom | `readme.title` + `readme.tagline` + `readme.intro` |
| `MISSING: no LICENSE file` | Drop `UNLICENSED\n\nAll rights reserved.\n` — the conservative default for private projects. Never guess MIT/Apache. | side-car `package.license` |
| `MISSING: no description in <pkg>` | Set `description` in that package.json to side-car `package.description` | `package.description` |
| `MISSING: no <field> in <pkg>` (license, author, repository, homepage) | Backfill each from side-car `package.*` | `package.*` |

### What auto-fill does NOT touch

- **`package.name`** — renaming has downstream consequences (CI, systemd, Docker tags, npm consumers). Leave the `STALE:` diagnostic in place; manual review.
- **Existing `description` text** that's just *stale* (not missing). Auto-fill won't rephrase prose; that's business-copy territory.
- **`<meta name="description">`** if it already exists, even when stale. Same reason.
- **Real `LICENSE` file** if one exists, even if `package.license` field is empty — backfill the field from the file, not the other way around.
- **Real `README.md`** if one exists. The side-car's `readme` block is for the *missing* case only.
- **`og:image`** if one already exists in `index.html`, even if the file behind it 404s. Flag the 404 as a separate diagnostic.

### Rich og-banner — implementation (SVG source + PNG render)  [v2]

Always write **both** files. The SVG is the editable source; the PNG is what Facebook/Twitter/Slack/WhatsApp scrape (they don't fetch SVG). The SVG also doubles as a re-render target — change the text, re-run `rsvg-convert`, ship.

**Why rich, not flat.** Chat-app preview heuristics (WhatsApp, Telegram, iMessage) downgrade flat-text-on-gradient banners to a SMALL left-thumbnail card and reserve the big post-style preview for banners with visual richness (icon + data preview + structured layout). A gradient + wordmark + tagline gets you the small thumbnail. Adding a brand-icon + tagline-pill + right-column data-preview-card flips it to the rich preview every time. This is non-negotiable — banners shipped without a right-column preview will keep getting downgraded.

The template below is the canonical layout. The right column ("preview card") is **domain-appropriate** — pick what to render based on the project's purpose:

| Project type | Preview card shows |
|---|---|
| Finance / expense | Expense rows with multi-currency amounts + USD total |
| CMS / menu / e-commerce | Items with prices + total |
| Knowledge / notes / wiki | Card stack with note titles + tags |
| Dashboard / admin / portfolio | Stat cards with numbers + sparkline bar |
| Task tracker / kanban | Task rows with status pills + count |
| Chat / messaging | Message bubbles with sender names |
| Analytics | KPI tiles with deltas |
| Generic / unknown | Feature list with check icons |

Pick the closest match; invent specific row contents that match the project's actual domain vocabulary (read `$findings.inferredPurpose` and the project's controllers/routes for hints). Do NOT use lorem-ipsum.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="<THEME_COLOR>"/>
      <stop offset="100%" stop-color="<THEME_COLOR_DARK_40>"/>
    </linearGradient>
    <linearGradient id="cardBg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.98"/>
      <stop offset="100%" stop-color="#f3f6fa" stop-opacity="0.96"/>
    </linearGradient>
    <filter id="cardShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="14"/>
      <feOffset dx="0" dy="10" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Background gradient -->
  <rect width="1200" height="630" fill="url(#bg)"/>

  <!-- Subtle dot grid (texture — prevents flat appearance) -->
  <g fill="#ffffff" opacity="0.06">
    <circle cx="140" cy="80"  r="3"/><circle cx="240" cy="130" r="2"/>
    <circle cx="80"  cy="220" r="4"/><circle cx="340" cy="60"  r="2"/>
    <circle cx="180" cy="500" r="3"/><circle cx="40"  cy="450" r="2"/>
    <circle cx="290" cy="580" r="3"/><circle cx="650" cy="50"  r="2"/>
    <circle cx="1130" cy="560" r="3"/><circle cx="1150" cy="60" r="2"/>
    <circle cx="980" cy="20" r="2"/><circle cx="1060" cy="600" r="3"/>
  </g>

  <!-- ============== LEFT COLUMN ============== -->

  <!-- App icon: rounded square with a single glyph picked per domain
       ($ for finance, M for menu, ✓ for tasks, ★ for ratings, etc.) -->
  <rect x="80" y="120" rx="22" ry="22" width="100" height="100" fill="#ffffff"/>
  <text x="130" y="200" font-family="system-ui,-apple-system,sans-serif"
        font-size="68" font-weight="800" fill="<THEME_COLOR>"
        text-anchor="middle"><BRAND_GLYPH></text>

  <!-- Wordmark — split across two lines if > ~12 chars total. Verbatim
       project name from readme.title; do NOT abbreviate. -->
  <text x="80" y="320" font-family="system-ui,-apple-system,sans-serif"
        font-size="82" font-weight="800" fill="#ffffff" letter-spacing="-2"><TITLE_LINE_1></text>
  <text x="80" y="404" font-family="system-ui,-apple-system,sans-serif"
        font-size="82" font-weight="800" fill="#ffffff" letter-spacing="-2"><TITLE_LINE_2></text>

  <!-- Tagline pill — keep SHORT (≤ 40 chars) so it doesn't run under
       the right-column card at x=720. Distill readme.tagline. -->
  <rect x="80" y="438" width="560" height="48" rx="24" ry="24"
        fill="#ffffff" opacity="0.14"/>
  <text x="106" y="470" font-family="system-ui,-apple-system,sans-serif"
        font-size="22" font-weight="600" fill="#ffffff" opacity="0.95"><TAGLINE_SHORT></text>

  <!-- Domain line -->
  <text x="80" y="570" font-family="system-ui,-apple-system,sans-serif"
        font-size="22" font-weight="500" fill="#ffffff" opacity="0.6"><HOMEPAGE_DOMAIN></text>

  <!-- ============== RIGHT COLUMN: domain-appropriate preview card ============== -->
  <!-- Renders at x=720, width=400, height=450. Adapt the contents per
       project type — see table above. The 4-row + footer-total layout is
       reusable across nearly every domain; just swap the labels + values. -->

  <g transform="translate(720, 100)" filter="url(#cardShadow)">
    <rect x="0" y="0" width="400" height="450" rx="40" ry="40" fill="url(#cardBg)"/>

    <!-- Header row -->
    <text x="42" y="56" font-family="system-ui,-apple-system,sans-serif"
          font-size="18" font-weight="700" fill="<THEME_COLOR_DARK_40>"><CARD_TITLE></text>
    <text x="358" y="56" font-family="system-ui,-apple-system,sans-serif"
          font-size="13" font-weight="500" fill="#7a8a99" text-anchor="end"><CARD_SUBTITLE></text>
    <line x1="42" y1="78" x2="358" y2="78" stroke="#e0e6ec" stroke-width="1"/>

    <!-- 4 data rows (icon-chip + primary + secondary + right-aligned value).
         y values: 116, 168, 220, 272 -->
    <g font-family="system-ui,-apple-system,sans-serif">
      <!-- Row 1 -->
      <circle cx="60" cy="116" r="15" fill="#dbeafe"/>
      <text x="60" y="121" font-size="14" font-weight="700" fill="<THEME_COLOR>" text-anchor="middle"><ROW1_GLYPH></text>
      <text x="88" y="112" font-size="14" font-weight="600" fill="<THEME_COLOR_DARK_40>"><ROW1_PRIMARY></text>
      <text x="88" y="130" font-size="11" fill="#7a8a99"><ROW1_SECONDARY></text>
      <text x="358" y="118" font-size="15" font-weight="700" fill="<THEME_COLOR_DARK_40>" text-anchor="end"><ROW1_VALUE></text>
      <!-- Rows 2-4 follow the same pattern with y=168/220/272 and
           varying chip colors (#fef3c7 amber, #dcfce7 mint, #fce7f3 pink) -->
    </g>

    <!-- Footer: aggregate label + value + progress bar -->
    <line x1="42" y1="324" x2="358" y2="324" stroke="#e0e6ec" stroke-width="1"/>
    <text x="42" y="358" font-size="13" font-weight="500" fill="#7a8a99"><FOOTER_LABEL></text>
    <text x="358" y="358" font-size="22" font-weight="800" fill="<THEME_COLOR>" text-anchor="end"><FOOTER_VALUE></text>

    <text x="42" y="390" font-size="11" font-weight="500" fill="#7a8a99"><PROGRESS_LABEL></text>
    <rect x="42" y="402" width="316" height="8" rx="4" ry="4" fill="#e0e6ec"/>
    <rect x="42" y="402" width="<PROGRESS_FILL_WIDTH>" height="8" rx="4" ry="4" fill="<THEME_COLOR>"/>
  </g>
</svg>
```

Save the SVG at `frontend/public/og-banner.svg` and render the PNG:

```bash
rsvg-convert -w 1200 -h 630 -f png \
  -o frontend/public/og-banner.png frontend/public/og-banner.svg
```

Verify the PNG (`stat -c%s` ≥ 50000 bytes — rich banners typically render 80-120 KB). If under 50 KB, the right-column preview likely failed to render — recheck the SVG. If `rsvg-convert` is missing, ship the SVG only and convert the diagnostic from `MISSING:` to `WARN: rsvg-convert not installed — SVG written, PNG not rendered. Install librsvg2-bin to fix.`

### Cache-bust versioning (CRITICAL — applies to every og:image / twitter:image URL)

Chat-app crawlers (WhatsApp, Telegram, iMessage, Slack, Discord, Facebook) cache `og:image` scrapes **aggressively**, keyed on the FULL URL including query string. A new banner at the same URL will NOT show up in previously-cached chats — those keep displaying the old image (often the small-thumbnail downgrade from a flat-text era) forever.

The fix is mandatory: every `og:image` and `twitter:image` URL **must** carry a `?v=N` query parameter. On every re-render of `og-banner.png`, INCREMENT N.

The refiner persists this counter in the side-car field `$ogBannerVersion: N` (sibling of `$version`, at the top level of `.project-meta.json`). Behavior:

- **First write** of og-banner: `$ogBannerVersion: 1` → URLs end `?v=1`
- **Re-render** (tagline edit, brand color change, new layout): bump to `?v=2`, `?v=3`, …
- The refiner reads the old `$ogBannerVersion`, increments by 1
- The side-car's `html.og.image` and `html.twitter.image` always include the current `?v=N`
- When the refiner re-runs the og:/twitter: injection step, it overwrites the old `?v=N` with the new one inside `index.html` — chat-app crawlers see a "new URL" and re-fetch

**Edge case — `$ogBannerVersion` missing from a prior side-car:** start at `?v=2` (NOT `?v=1`) to deliberately invalidate any previously-cached unversioned scrape. Most legacy projects fall here.

**Edge case — banner content didn't change but a re-run still happens:** still bump the version. The cost of an unnecessary re-fetch is zero; the cost of a stale cached preview is real.

The file `og-banner.png` itself stays at the same path — the bump lives only in the URL inside `index.html`. No need to rename the file on disk.

### AI-bg mode (optional, opt-in via `OPENAI_API_KEY`)  [v3]

The pure-SVG rich template is reliable, free, and offline-buildable. It's the default. But hand-drawn schematic mockups have a "computer art" feel — when the project budget allows ~$0.04 per project for AI image generation, the banner can go from "schematic but rich" to "magazine-cover striking".

This skill ships an **optional two-layer mode**: AI generates the BACKGROUND, SVG overlays the text. Two layers because image models reliably misspell text and can't pixel-match brand colors — keeping text in SVG gives you both visual richness AND legibility/brand-precision.

**Activation:** if `OPENAI_API_KEY` is set in the environment when the refiner runs, AI-bg mode kicks in. If absent, fall back to pure-SVG (current default behavior — no regression).

**What changes:**

1. **Background generation** — the refiner calls `scripts/generate-og-bg.py` (ships with this repo, stdlib-only Python) with the project's `theme_color`, `inferredPurpose`, and one of 7 category-keyed prompt templates (finance / dashboard / ecommerce / knowledge / cms / tasks / generic). The script POSTs to OpenAI's Images API (`gpt-image-1` by default; `dall-e-3` via `OG_AI_IMAGE_MODEL=dall-e-3`), downloads the resulting PNG to `frontend/public/og-banner-bg.png` (~2 MB, 1536×1024). Takes ~40 s.

2. **Composite SVG** — `og-banner.svg` uses `<image href="og-banner-bg.png" preserveAspectRatio="xMidYMid slice">` for the background (center-crops the 1536×1024 source to the 1200×630 canvas with no distortion). A left-side dark `<linearGradient>` scrim ensures the text overlay is legible regardless of what the AI painted on the left. The icon + wordmark + tagline pill + domain line sit on top — same SVG elements as the pure-SVG mode, just on a richer canvas. The right-column data-card is OMITTED in AI-bg mode (the AI usually paints its own visual content there).

```svg
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 1200 630" width="1200" height="630">
  <defs>
    <linearGradient id="scrim" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"   stop-color="#0b0d2e" stop-opacity="0.85"/>
      <stop offset="50%"  stop-color="#0b0d2e" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#0b0d2e" stop-opacity="0.00"/>
    </linearGradient>
  </defs>

  <image href="og-banner-bg.png" xlink:href="og-banner-bg.png"
         x="0" y="0" width="1200" height="630"
         preserveAspectRatio="xMidYMid slice"/>

  <rect width="1200" height="630" fill="url(#scrim)"/>

  <!-- icon, wordmark, tagline pill, domain — same elements as pure-SVG mode -->
  <rect x="80" y="120" rx="22" ry="22" width="100" height="100" fill="#ffffff"/>
  <text x="130" y="200" font-size="68" font-weight="800" fill="<THEME_COLOR>"
        font-family="system-ui,-apple-system,sans-serif" text-anchor="middle"><BRAND_GLYPH></text>

  <text x="80" y="320" font-size="82" font-weight="800" fill="#ffffff"
        font-family="system-ui,-apple-system,sans-serif" letter-spacing="-2"><TITLE_LINE_1></text>
  <text x="80" y="404" font-size="82" font-weight="800" fill="#ffffff"
        font-family="system-ui,-apple-system,sans-serif" letter-spacing="-2"><TITLE_LINE_2></text>

  <rect x="80" y="438" width="560" height="48" rx="24" ry="24" fill="#ffffff" opacity="0.18"/>
  <text x="106" y="470" font-size="22" font-weight="600" fill="#ffffff"
        font-family="system-ui,-apple-system,sans-serif"><TAGLINE_SHORT></text>

  <text x="80" y="570" font-size="22" font-weight="500" fill="#ffffff" opacity="0.7"
        font-family="system-ui,-apple-system,sans-serif"><HOMEPAGE_DOMAIN></text>
</svg>
```

3. **Render** as before: `rsvg-convert -w 1200 -h 630 -f png -o og-banner.png og-banner.svg`.

4. **Side-car** stamps `$ogBannerMode: "ai-bg"` (vs. `"pure-svg"` for the default). The advisor's `nextActions[]` for project-metadata-refiner gains one line: `Manual: review og-banner.png — AI-generated, re-roll prompt if quality is off`.

**Commit policy.** Commit BOTH files to the project repo:
- `frontend/public/og-banner-bg.png` (2 MB AI source — committed so the build is reproducible without re-paying the API call on every CI build)
- `frontend/public/og-banner.png` (final composite — what chat-app crawlers fetch)

Trade-off accepted: +2 MB per project repo, saved $0.04 per CI build × N builds/year + immunity to API outages.

**Re-generation cadence.** Re-run the AI generation only when:
- The project's domain/purpose changes meaningfully (`$findings.inferredPurpose` drifts)
- The brand color changes
- The user explicitly wants to re-roll for aesthetic reasons

Don't auto-regenerate on every refiner re-run — that's $0.04 per audit pass × N audits, with no observable improvement.

**Prompt library** (in `scripts/generate-og-bg.py`):

| Category | Visual metaphor |
|---|---|
| `finance` | Floating receipts, coin discs, currency symbol shapes in negative space |
| `dashboard` | Floating UI cards, soft progress arcs, light grid lines, gentle data flow lines |
| `ecommerce` | Floating storefront cards, shopping bag silhouettes, soft tag shapes |
| `knowledge` | Floating index cards in a soft stack, gentle connection lines, glowing nodes |
| `cms` | Stacked document silhouettes, soft layout grids, gentle layering |
| `tasks` | Floating checklist cards, soft progress indicators, gentle priority swatches |
| `generic` | Floating geometric shapes, soft layered cards, gentle data flow lines, subtle dots |

Every prompt ends with `"Composition leaves the left half OPEN and DARKER for text overlay"` so the scrim has clear real estate.

**Model selection.** `gpt-image-1` is the default (faster, returns b64 inline — no second-hop download). `dall-e-3` is supported as a fallback via `OG_AI_IMAGE_MODEL=dall-e-3` env var (returns URL, slightly older training but sometimes more "design-y").

**Failure handling.** If `OPENAI_API_KEY` is set but the API call fails (rate limit, outage, invalid model, payment issue), the refiner FALLS BACK to pure-SVG mode automatically and adds a `WARN:` diagnostic. The user can re-run with the same key once the API issue resolves; the diagnostic resolves on re-run.

### Placeholder logo.svg — implementation

Only write if no logo exists (`favicon.svg`, `logo.svg`, `logo.png` all missing in `frontend/public/` or project root). A real logo always beats a placeholder, so don't overwrite.

The placeholder is a rounded square with the project's initials. Take the first 1–2 capital letters from `readme.title` (e.g. `"CartFlow"` → `"C"`, `"MenuKit CMS"` → `"MK"`):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect width="256" height="256" rx="48" fill="<THEME_COLOR>"/>
  <text x="128" y="128" font-family="system-ui, -apple-system, sans-serif"
        font-size="140" font-weight="800" fill="#ffffff"
        text-anchor="middle" dominant-baseline="central"
        letter-spacing="-4"><INITIALS></text>
  <!-- PLACEHOLDER — replace with real logo. -->
</svg>
```

Save to `frontend/public/logo.svg` (or project root for non-frontend projects). Do **not** rasterize to PNG by default — the SVG renders natively in `<img>` and is sharper at every size. If the PWA manifest needs PNG icons too, defer to the `pwa-setup` skill rather than duplicating that pipeline here.

The SVG-only output is intentional: most modern places that consume a "logo" (favicon, hero image, README badge, GitHub social preview) accept SVG. Until the user designs a real one, the initials-on-theme-color square is a clean, professional-looking stand-in.

### og:/twitter: meta-tag injection — implementation

Find the existing `<meta name="description" ...>` line in `index.html` and inject the og:/twitter: block immediately after it. Order conventionally: og:title → og:description → og:type → og:url → og:site_name → og:image → og:image:width → og:image:height → twitter:card → twitter:title → twitter:description → twitter:image.

Wrap with HTML comment markers so a re-run can detect and replace the block instead of duplicating:

```html
<!-- BEGIN project-metadata-refiner: og:/twitter: -->
<meta property="og:title" content="..." />
<meta property="og:image" content="https://example.com/og-banner.png?v=2" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
...
<meta name="twitter:image" content="https://example.com/og-banner.png?v=2" />
<!-- END project-metadata-refiner -->
```

**`?v=N` is mandatory** — read the current `$ogBannerVersion` from the side-car (default to 2 if missing — see Cache-bust versioning section above), and append the same `?v=N` to BOTH `og:image` and `twitter:image`. When the refiner re-runs and the version was bumped, overwriting the block here is what propagates the new URL to chat-app crawlers.

### Root README.md — implementation

Write a real markdown file. The format is opinionated and consistent across projects so portfolio scrapers (Mission Control, GitHub) get something usable:

```markdown
# <readme.title>

*<readme.tagline>*

<readme.intro>

## Documentation

See [`docs/`](./docs/) for full architecture, feature guides, deployment, and release notes.

---

<sub>This README was scaffolded by `project-metadata-refiner` on <ISO date>. Edit freely — the auto-fill marker can be deleted once you've reviewed it.</sub>
```

### Idempotency

Every auto-fill step must:
- **Check before writing** — if the target file or field already has a non-empty value, skip and leave the diagnostic.
- **Mark its own output** — HTML comment markers, README footer line, or a `// AUTO-FILLED by project-metadata-refiner` comment in JSON (where format allows).
- **Update the side-car diagnostics** — demote `MISSING:` to `RESOLVED:` so a re-run sees what's done.

A second invocation of the skill against the same project should produce zero new file writes and the same side-car (modulo `$generatedAt`).

### After auto-fill — what's left for the human

The user re-reads the side-car. The remaining diagnostics are now exclusively:
- `STALE:` — wording that exists but is wrong. Needs human judgment.
- `INCONSISTENT:` — usually points at a brand drift; the user decides the canonical spelling.
- `RECOMMEND:` — judgment calls (renaming packages, adding a root package.json).
- `BREAKING:` — needs an impact review before applying.
- `TODO:` — purely creative tasks (replace placeholder og-banner with a real designed one).

Most projects go from ~15 diagnostics → ~5 after auto-fill. The remaining five are exactly where human attention is worth spending.

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
- **Always include `?v=N` cache-bust** (where N is `$ogBannerVersion` from the side-car). Chat-app crawlers cache aggressively by URL — without the version query, a redesigned banner stays invisible in previously-shared chats forever.
- If the project doesn't have one yet, suggest `https://<homepage>/og-banner.png?v=1` and add diagnostic `"TODO: create og-banner.png — 1200x630, rich layout (icon + wordmark + tagline pill + right-column preview card per the v2 template)"`.
- Generated banners follow the **rich layout** template (Rich og-banner section). Flat-text-on-gradient banners get downgraded to small-thumbnail previews by WhatsApp/Telegram/iMessage — never ship those.

### `html.og.type`

- `website` for SPAs and landing pages.
- `article` for blog posts (not relevant here).

### `html.twitter.card`

- Always `summary_large_image` if `twitter:image` is set. Otherwise `summary`.

---

## Diagnostics — What to Flag

**Every entry in `diagnostics` must be actionable.** Diagnostics drive badge counts in portfolio tools (Mission Control's `/projects` card, GitHub Action gates, etc.) — if it's not something the user can *do*, it doesn't belong in this array.

Use these prefixes consistently so the list filters cleanly later:

| Prefix | Meaning | Example |
|--------|---------|---------|
| `MISSING:` | Field is absent and should exist | `MISSING: package.json has no keywords` |
| `STALE:` | Field exists but is wrong/outdated | `STALE: description still says "starter template"` |
| `INCONSISTENT:` | Two sources disagree | `INCONSISTENT: pkg.name='foo' but manifest.short_name='Bar'` |
| `RECOMMEND:` | Not a defect, but a meaningful upgrade | `RECOMMEND: og:image dimensions should be 1200x630` |
| `BREAKING:` | Applying this suggestion has downstream cost | `BREAKING: name change from foo-app to foo-cms breaks npm consumers` |
| `WARN:` | Audit ran into a soft failure | `WARN: homepage <url> unreachable — used codebase fallback` |
| `TODO:` | Requires a creative/manual asset, not text | `TODO: create og-banner.png — 1200x630, branded` |
| `RESOLVED:` | An earlier diagnostic that's now fixed (set when re-running on a project that already applied prior suggestions). The `RESOLVED:` prefix may carry a parenthetical qualifier like `RESOLVED (this run):` or `RESOLVED (since prior audit):` — both forms are valid. | `RESOLVED: package.json now has name='cartflow'` |

### What does NOT belong in `diagnostics`

- **Pure observations / context.** If you find yourself writing "the project is internal", "the stack is bilingual", "the repo has no public homepage" — that's context. It belongs in `$findings.brandDrift` or `$findings.inferredPurpose`, not in `diagnostics`.
- **`NOTE:`-prefixed entries are forbidden.** They were emitted ad-hoc by earlier audit runs and silently inflated badge counts. If the observation is worth recording, put it in `$findings`; if it's not, drop it.
- **Things that are true forever about the project's nature.** "Project is private", "repo uses master not main", "stack includes Stripe" — these are facts, not work. The diagnostic list tracks deltas between current and desired state, not the project's identity.

A clean diagnostics list lets the badge count map 1:1 to "items still on the user's plate". If your audit produces a diagnostic the user can't act on, rewrite it so they can, or move it to `$findings`.

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

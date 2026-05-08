---
name: "Mantine Theme Discipline"
description: "Stop pages from breaking in dark mode by enforcing theme tokens over hardcoded colors. Use when adding pages to a Mantine + light/dark project, code-reviewing UI changes, or auditing an existing app for theme violations before shipping dark mode."
---

# Mantine Theme Discipline

## What This Skill Does

Enforces a single rule across a Mantine codebase:

> **Never name a color or shade outside `theme.ts`.** All visual surfaces, borders, and accents must use Mantine's auto-flipping CSS variables so dark mode looks deliberate, not broken.

This is a discipline skill, not a setup skill. It's enforced by code review + a 3-line grep gate, applied per-PR.

## When to Use

- You enabled `defaultColorScheme="auto"` (or `"dark"`) in `MantineProvider` and a page suddenly looks wrong in the other mode.
- You're code-reviewing a PR that touched `style={{...}}`, `bg="..."`, `c="..."`, or any new CSS file.
- You're auditing an existing app before declaring dark-mode support shipped.
- A junior engineer just asked "what color should I use here?"

## When NOT to Use

- Tailwind-based projects — they have their own theming model (different rules apply).
- A pure-light or pure-dark single-mode app (the breakage doesn't surface, but the rule is still cheaper to follow than to retrofit later).
- Marketing/landing pages with intentional brand color blocks (one-off art direction is fine — annotate with a comment).

---

## The Three Forbidden Patterns

These all *render* in light mode, but break (low contrast, wrong tone, or jarring) in dark mode.

### ❌ Pattern 1: Hardcoded hex codes outside `theme.ts`

```tsx
// BAD
<Card bg="#0e1116">…</Card>
<div style={{ color: '#1d4ed8' }}>…</div>
<Paper style={{ borderColor: '#e5e7eb' }}>…</Paper>
```

**Why it breaks:** Pinned to one mode regardless of `useMantineColorScheme()`.

### ❌ Pattern 2: Fixed-shade Mantine color tokens for surfaces

```tsx
// BAD
<Card bg="gray.0">…</Card>          // light gray pinned — invisible in dark mode
<Alert bg="red.0" c="red.7">…</Alert>  // shade 0 is barely there in dark mode
<Paper bg="blue.1" />                // pinned tint, doesn't flip
```

**Why it breaks:** Mantine color tokens like `gray.0`, `red.7`, `blue.1` are *literal shades* on a 0–9 scale. They don't auto-flip between light and dark. Shade 0 (lightest) in dark mode = barely visible against a dark surface; shade 7 (darkest) on a light card = readable, but the same `c="red.7"` text on a dark card is unreadable.

### ❌ Pattern 3: Pinned-shade CSS vars

```tsx
// BAD
<Box style={{ background: 'var(--mantine-color-gray-0)' }}>
<Icon color="var(--mantine-color-red-6)" />
<Box style={{ borderColor: 'var(--mantine-color-gray-2)' }}>
```

**Why it breaks:** `--mantine-color-{name}-{0..9}` are the same pinned shades — wrapping them in `var()` doesn't change that they're a single shade locked to one mode.

---

## The Allowed Replacements

Mantine 7+ exposes a small set of **auto-flipping** CSS variables. These are the ONLY color values you should reach for in components.

### For surfaces (backgrounds)

| Use case | Token | Light mode | Dark mode |
|---|---|---|---|
| Page body bg | `var(--mantine-color-body)` | white | near-black |
| Default card / surface | `var(--mantine-color-default)` | white | dark.6 |
| Alert / status tint (red, green, etc.) | `var(--mantine-color-{name}-light)` | very light tint | dark muted tint |
| Hover state on tint | `var(--mantine-color-{name}-light-hover)` | slightly darker tint | slightly lighter tint |
| Brand-accented surface | `var(--mantine-color-{primary}-light)` | (e.g. indigo light) | (indigo dark) |

### For text and icons

| Use case | Token |
|---|---|
| Body text | `var(--mantine-color-text)` (default) — Mantine handles automatically |
| Dimmed text | `c="dimmed"` — the right way |
| Status text on its matching `*-light` bg | `var(--mantine-color-{name}-light-color)` |
| Icon matching brand | `color="var(--mantine-color-{primary}-filled)"` |

### For borders

| Use case | Token |
|---|---|
| Default card border | `var(--mantine-color-default-border)` |
| Active/selected border | `var(--mantine-color-{name}-filled)` |

### Translation table

```diff
- bg="gray.0"
+ bg="var(--mantine-color-default)"

- bg="red.0"
+ bg="var(--mantine-color-red-light)"

- c="red.7"     (next to red.0 bg)
+ c="var(--mantine-color-red-light-color)"

- color="var(--mantine-color-green-6)"      (icon)
+ color="var(--mantine-color-green-light-color)"

- borderColor: '1px solid var(--mantine-color-gray-2)'
+ borderColor: '1px solid var(--mantine-color-default-border)'

- background: 'var(--mantine-color-blue-0)'   (selected card)
+ background: 'var(--mantine-color-indigo-light)'   (uses your primary)

- borderColor: 'var(--mantine-color-blue-5)'   (selected border)
+ borderColor: 'var(--mantine-color-indigo-filled)'

- background: 'var(--mantine-color-gray-0)'   (login page)
+ background: 'var(--mantine-color-body)'
```

---

## The Two Legitimate Exceptions

These *are* allowed to break the rule, and should each carry a short comment explaining why.

### Exception 1: The theme palette itself (`theme.ts`)

```ts
const indigo: MantineColorsTuple = [
  '#eef2ff', '#e0e7ff', /* … */
];
```

This is *the* place hex codes live. Define palettes here, register them in `createTheme`, and reference them by name everywhere else.

### Exception 2: Intentionally always-dark surfaces (terminals, code editors, video players)

A terminal pane is dark in light mode too — that's a UX convention, not a theme bug. Make the intent explicit:

```tsx
// Terminal is intentionally always-dark — by terminal UX convention,
// regardless of the surrounding app theme. Background lives on the
// xterm container, not the outer Card, so the page chrome still
// respects the user's color scheme.
<Card withBorder>
  <div style={{ background: '#0e1116' }}>
    {/* xterm renders here */}
  </div>
</Card>
```

The outer `Card` flips with the theme; only the inner viewport stays dark.

---

## The Pre-Merge Audit (3 greps)

Run these from the frontend root before merging any PR with UI changes:

```bash
# 1. Hex codes outside theme.ts and intentional exceptions
grep -rEn "#[0-9a-fA-F]{6}" --include="*.tsx" --include="*.ts" src/ \
  | grep -vE "theme\.ts|BrandMark|Terminal\.tsx"

# 2. Fixed-shade Mantine color props (bg="gray.0", c="red.7", etc.)
grep -rEn "[cb]g?=['\"](gray|dark|red|blue|green|yellow|orange|cyan|teal|violet|indigo)\.[0-9]" \
  --include="*.tsx" --include="*.ts" src/

# 3. Pinned-shade Mantine CSS variables
grep -rEn "var\(--mantine-color-(red|blue|green|gray|yellow|orange|cyan|teal|violet|indigo)-[0-9]\)" \
  --include="*.tsx" --include="*.ts" src/
```

**Expected output for all three: empty.** Anything that prints needs review:
- It's a real violation — fix using the translation table above.
- It's an intentional exception — add a one-line comment explaining why and adjust the grep to exclude that file.

Wire these into your `lint` script so CI fails on regressions:

```json
{
  "scripts": {
    "lint:colors": "scripts/check-theme.sh",
    "lint": "eslint . --ext ts,tsx && npm run lint:colors"
  }
}
```

`scripts/check-theme.sh` should run the three greps above and `exit 1` if any produce output.

---

## How to Verify Manually

After fixing all violations:

1. Open every page logged in.
2. Toggle the theme (`<IconSun>/<IconMoon>` button in the AppShell header).
3. Look for: white blocks on dark mode, low-contrast text, borders that disappear, status tints (red/green/blue) that look gray or saturated.
4. Bonus: open Chrome DevTools → Rendering tab → Emulate CSS prefers-color-scheme to test before logging in.

If a page looks identical in both modes, that's wrong — Mantine vars should produce visibly different (but balanced) chrome.

---

## Common Symptoms This Skill Fixes

| Symptom | Likely cause |
|---|---|
| "The error alert is invisible in dark mode" | `bg="red.0"` (use `var(--mantine-color-red-light)`) |
| "The login page is white in dark mode" | `background: 'var(--mantine-color-gray-0)'` (use `var(--mantine-color-body)`) |
| "Modal content card is too bright in dark mode" | `bg="gray.0"` (use `var(--mantine-color-default)`) |
| "Status icons (✓/✗) look duller in dark mode" | `var(--mantine-color-green-6)` (use `var(--mantine-color-green-light-color)`) |
| "Card borders disappear in dark mode" | `borderColor: 'var(--mantine-color-gray-2)'` (use `var(--mantine-color-default-border)`) |
| "Selected card highlight color is wrong shade" | `bg="blue.0"` (use the project's `primary-light`, e.g. `var(--mantine-color-indigo-light)`) |

---

## Why This Skill Exists

This was extracted from a real audit of Mission Control v0.4. After enabling `defaultColorScheme="auto"`, six pages had visible breakage:
- Audit log error card was a tiny pale-pink rectangle on a dark page
- PRD preview tab was a bright white block
- Setup checklist icons were the wrong green/red shade
- Project card borders disappeared
- Login page was a white wash in dark mode

All six were fixable with the translation table above in under 10 minutes — but they each represented bugs that would have shipped to users had they not been caught. The 3-grep gate prevents the next batch of equivalent regressions.

---

## Tradeoffs This Skill Bakes In

- **Strict over expressive.** You lose the convenience of typing `c="red.7"` for "a slightly darker red." In exchange you gain dark-mode reliability without per-page reasoning.
- **Three rules, not five.** Mantine has dozens of CSS vars; this skill only sanctions the auto-flipping subset. Smaller set = faster review, fewer edge cases.
- **Greps, not lint plugins.** A 3-line grep is cheaper to maintain than a custom ESLint rule. Re-evaluate if/when @mantine ships an official lint plugin.

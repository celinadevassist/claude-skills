---
name: "Responsive Layout Discipline"
description: "Prevent admin pages from breaking on mobile by enforcing Mantine breakpoint discipline — responsive Grid/SimpleGrid spans, visibleFrom/hiddenFrom for header chips, ScrollArea for terminals + wide tables, no fixed pixel widths. Use when adding pages to a Mantine + React project, code-reviewing UI changes that introduce Grid/Group/Flex layouts, or auditing an existing admin tool before declaring mobile support shipped."
---

# Responsive Layout Discipline

## What This Skill Does

Enforces a single rule across a Mantine + React codebase:

> **Every page must render usably from 360px wide.** Layouts collapse to one column on mobile, header chips hide instead of overflow, wide content (terminals, tables, code blocks) lives inside a `ScrollArea`, and no element pins itself to a fixed pixel width.

This is a discipline skill, not a setup skill. It pairs with `mantine-theme-discipline` (which handles colors); together they're a 3-grep gate that runs per-PR.

## When to Use

- You're adding a new page to a Mantine + React admin tool that's expected to work on a phone.
- You're code-reviewing a PR that introduced `<Grid>`, `<SimpleGrid>`, `<Group>`, `<Flex>`, or `<Table>`.
- A user reported "page X is broken on mobile" — the cause is almost always one of the four patterns below.
- You're auditing an existing app before declaring mobile-installable support shipped (PWA on the home screen with a broken layout is worse than no PWA).

## When NOT to Use

- Pure-desktop tools where mobile isn't a target (price-trading dashboards, dense data-grid CRMs) — the rule is still cheap to follow, but the audit gate isn't worth wiring in.
- Tailwind / shadcn projects — they have their own breakpoint primitives (`sm:`, `md:`, `lg:`); a different skill applies.
- Marketing pages built with a CMS — those usually ship their own responsive system.

---

## The Four Forbidden Patterns

All of these *render* on a 1440px laptop. All of them break (overflow, horizontal scroll, hidden content, illegible) at 390px.

### ❌ Pattern 1: Fixed pixel widths

```tsx
// BAD
<TextInput w={400} />
<Card style={{ width: 600 }}>…</Card>
<Container size={1200}>…</Container>     // pinned, can't shrink
<div style={{ minWidth: 800 }}>…</div>
```

**Why it breaks:** Element refuses to shrink below the fixed width. On a 390px phone, the page acquires a horizontal scrollbar — the worst possible mobile UX.

### ❌ Pattern 2: Single-shape Grid / SimpleGrid

```tsx
// BAD
<Grid>
  <Grid.Col span={6}>{left}</Grid.Col>     // 50% at every viewport
  <Grid.Col span={6}>{right}</Grid.Col>
</Grid>

<SimpleGrid cols={4}>…</SimpleGrid>        // 4 columns at every viewport
```

**Why it breaks:** A two-column layout on a 390px viewport gives you two 175px columns — each barely wide enough for a button. Content is technically visible but unusable.

### ❌ Pattern 3: Non-collapsing Group / Flex rows

```tsx
// BAD
<Group>
  <TextInput placeholder="Search" />
  <Select data={categories} />
  <DatePickerInput />
  <Button>Apply</Button>
</Group>

<Flex direction="row" gap="md">
  {/* 4 cards side-by-side, no wrap */}
</Flex>
```

**Why it breaks:** `Group` defaults to `wrap="nowrap"` *if* `style` overrides it; even when it does wrap, child widths often don't shrink, so the row overflows the viewport.

### ❌ Pattern 4: Wide content with no horizontal-scroll wrapper

```tsx
// BAD
<Card>
  <Table>
    <Table.Thead>
      <Table.Tr>
        {/* 8 columns of data */}
      </Table.Tr>
    </Table.Thead>
    …
  </Table>
</Card>

<Card>
  <div ref={terminalRef} style={{ height: 500 }} />   {/* xterm */}
</Card>

<Card>
  <Code block>{multilineSnippet}</Code>
</Card>
```

**Why it breaks:** Tables, terminals, and `<Code block>` enforce their natural width on the parent. Without a `ScrollArea`, the entire page acquires a horizontal scrollbar to accommodate them.

---

## The Allowed Replacements

Mantine 7+ ships everything needed. Reach for these — and only these — when laying out a page.

### For widths

| Bad | Good | Why |
|---|---|---|
| `w={400}` | `maw={400}` (max-width) | Caps at 400 on desktop, shrinks freely on mobile |
| `style={{ width: 600 }}` | `style={{ maxWidth: 600, width: '100%' }}` | Same idea, raw CSS |
| `<Container size={1200}>` | `<Container size="lg">` | Mantine sizes (`xs`/`sm`/`md`/`lg`/`xl`) already include responsive caps |
| `<div style={{ minWidth: 800 }}>` | Wrap in `<ScrollArea>` | The container scrolls instead of the page |

### For Grid / SimpleGrid

| Bad | Good |
|---|---|
| `<Grid.Col span={6}>` | `<Grid.Col span={{ base: 12, sm: 6 }}>` |
| `<Grid.Col span={4}>` | `<Grid.Col span={{ base: 12, sm: 6, md: 4 }}>` |
| `<Grid.Col span={3}>` | `<Grid.Col span={{ base: 12, xs: 6, md: 3 }}>` |
| `<SimpleGrid cols={4}>` | `<SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>` |
| `<SimpleGrid cols={2}>` | `<SimpleGrid cols={{ base: 1, sm: 2 }}>` |

Rule of thumb: at `base` (the default <576px), almost everything is `12` (full row) or `1` (single column).

### For Group / Flex / header bars

| Bad | Good |
|---|---|
| `<Group>{filters}</Group>` | `<Group wrap="wrap">{filters}</Group>` (or `<Stack hiddenFrom="sm">` + `<Group visibleFrom="sm">`) |
| `<Flex direction="row">` | `<Flex direction={{ base: 'column', sm: 'row' }}>` |
| Header chips visible on phone | Wrap each chip in `<Box visibleFrom="sm">`, replace with a `Burger`/`Drawer` on mobile |
| Sidebar nav rendered everywhere | `AppShell.Navbar` with `breakpoint="sm"` + `collapsed={{ mobile: !opened }}` |

### For wide content

| Bad | Good |
|---|---|
| Bare `<Table>` | `<ScrollArea><Table>…</Table></ScrollArea>` |
| Bare xterm container | `<ScrollArea type="auto" scrollbars="x"><div ref={termRef}/></ScrollArea>` (and let xterm's `FitAddon` recompute) |
| Bare `<Code block>` | `<ScrollArea><Code block>…</Code></ScrollArea>` |
| Bare `<Tabs>` with many tabs | `<Tabs><ScrollArea scrollbars="x"><Tabs.List>…</Tabs.List></ScrollArea></Tabs>` |

### Translation diff

```diff
- <Grid.Col span={6}>
+ <Grid.Col span={{ base: 12, sm: 6 }}>

- <SimpleGrid cols={4} spacing="md">
+ <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md">

- <Group>
-   <TextInput placeholder="Search" />
-   <Select data={items} />
-   <Button>Filter</Button>
- </Group>
+ <Group wrap="wrap">
+   <TextInput placeholder="Search" style={{ flex: '1 1 200px' }} />
+   <Select data={items} style={{ flex: '1 1 160px' }} />
+   <Button>Filter</Button>
+ </Group>

- <Card>
-   <Table>…</Table>
- </Card>
+ <Card>
+   <ScrollArea>
+     <Table miw={720}>…</Table>
+   </ScrollArea>
+ </Card>

- <Card style={{ width: 600 }}>
+ <Card maw={600}>      {/* shrinks freely below 600px */}

- <Group>{breadcrumbs}{title}{cmdKChip}{userMenu}</Group>
+ <Group justify="space-between">
+   <Group visibleFrom="sm">{breadcrumbs}{title}</Group>
+   <Title hiddenFrom="sm">{title}</Title>
+   <Group>
+     <Box visibleFrom="md">{cmdKChip}</Box>
+     {userMenu}
+   </Group>
+ </Group>
```

---

## The Two Legitimate Exceptions

These *are* allowed to break the rule, with a one-line comment.

### Exception 1: Intentionally desktop-only screens

```tsx
// This dense data grid is desktop-only by product decision — mobile users
// are redirected to /mobile-summary instead. Documented in PRD §3.2.
<Container size="xl" miw={1200}>
  <BigDataGrid />
</Container>
```

If the *whole page* is desktop-only, add a server-side or route-level redirect for `useMediaQuery('(max-width: 768px)')` so phones don't load it at all.

### Exception 2: Print or PDF-export views

```tsx
// PDF-export preview — rendered at fixed A4 width (210mm ≈ 794px) so the
// browser-printed output matches the downloaded PDF byte-for-byte.
<div style={{ width: 794 }} className="print-target">…</div>
```

These are rendered offscreen for `html2pdf` / Puppeteer; users never see them on a phone.

---

## The Pre-Merge Audit (4 greps)

Run from the frontend root before merging any PR with UI changes:

```bash
# 1. Fixed numeric width / minWidth in props or styles
grep -rEn "(\\b(w|miw|minWidth)=\\{[0-9]+\\})|(width:\\s*['\"]?[0-9]+(px)?\\b)|(minWidth:\\s*['\"]?[0-9]+(px)?\\b)" \
  --include="*.tsx" --include="*.ts" src/ \
  | grep -vE "// print|// pdf|print-target|desktop-only"

# 2. Grid.Col / SimpleGrid cols with a bare number (no breakpoints)
grep -rEn "(<Grid\\.Col[^>]*span=\\{[0-9]+\\})|(<SimpleGrid[^>]*cols=\\{[0-9]+\\})" \
  --include="*.tsx" src/

# 3. <Table> / xterm / <Code block> not wrapped in ScrollArea (heuristic)
grep -rln "<Table\\b\\|xterm\\|<Code\\b.*block" --include="*.tsx" src/ \
  | xargs -I{} sh -c 'grep -L "ScrollArea" {} && echo "  ↑ missing ScrollArea wrapper"'

# 4. Header-bar children with no visibleFrom/hiddenFrom (manual review)
grep -rEn "AppShell\\.Header|<Group[^>]*justify=" --include="*.tsx" src/ \
  | head -20
# ↑ visual check: every child in a header bar should be inside <Box visibleFrom>
#   or <Box hiddenFrom>, or live in a <Drawer>/<Menu> below `sm`.
```

**Expected output for greps 1–2: empty.** Anything that prints is either a violation (fix using the translation table) or an intentional exception (annotate with a comment that the grep excludes).

Wire greps 1 and 2 into `scripts/check-responsive.sh` and into `npm run lint`:

```json
{
  "scripts": {
    "lint:responsive": "scripts/check-responsive.sh",
    "lint": "eslint . --ext ts,tsx && npm run lint:colors && npm run lint:responsive"
  }
}
```

---

## How to Verify Manually

After fixing all violations:

1. Open Chrome DevTools → Toggle device toolbar → pick "iPhone 12 Pro" (390 × 844) and "iPad Air" (820 × 1180).
2. Walk every authenticated page. No horizontal scrollbar on the page body is the bar.
3. Tap every header chip / icon. Anything not reachable through the Burger menu or a Drawer on mobile is a regression.
4. For pages with a `<Table>` or terminal: confirm the *content* scrolls horizontally inside its card, not the page.
5. Rotate to landscape (390 × 844 → 844 × 390). The layout should reflow, not stay locked.

If a page renders identically on a 1440px laptop and a 390px phone, that's wrong — `base`-breakpoint overrides should produce visibly different chrome.

---

## Common Symptoms This Skill Fixes

| Symptom | Likely cause |
|---|---|
| "The whole page scrolls sideways on my phone" | A child with fixed `w={N}` (use `maw={N}`) |
| "The terminal page is unusable on mobile" | xterm container not wrapped in `ScrollArea` |
| "The filter row hides the rightmost button on mobile" | `<Group>` without `wrap="wrap"` |
| "The dashboard cards are tiny columns on a phone" | `<SimpleGrid cols={4}>` (use `{{ base: 1, sm: 2, md: 4 }}`) |
| "The breadcrumbs and Cmd-K chip overflow on mobile" | Header bar without `visibleFrom`/`hiddenFrom` on chips |
| "The data table renders but I can't see columns 5–8" | `<Table>` without horizontal `ScrollArea` |
| "AppShell sidebar covers the page on mobile" | `AppShell.Navbar` without `breakpoint="sm"` + `collapsed={{ mobile }}` |

---

## Why This Skill Exists

This was extracted from a real audit of Mission Control v0.5. After enabling the PWA install banner so the dashboard could run on a phone, the `/terminal` page was unusable: the xterm viewport pinned the page to 800px wide, the page acquired a horizontal scrollbar at the document level, and the header tabs row overflowed off the right edge. The right-nav adapted (because `AppShell.Navbar` ships breakpoints out of the box), but everything inside the page assumed desktop.

All of it was fixable with the translation table above in under 20 minutes — `<ScrollArea>` around the xterm, `<Group wrap="wrap">` on the filter row, `visibleFrom="sm"` on the breadcrumb chips. But each was a bug that would have shipped to phone users had they not been caught. The 4-grep gate prevents the next batch of equivalent regressions.

---

## Tradeoffs This Skill Bakes In

- **Mobile-first is a constraint, not a default.** You lose the convenience of `<Grid.Col span={6}>` for a two-column page. In exchange you gain a phone that works.
- **Tables/terminals always get a ScrollArea wrapper.** Slightly heavier DOM. The win is that the wrap is mechanical: future authors don't have to remember it case-by-case.
- **`visibleFrom`/`hiddenFrom` instead of CSS media queries.** Less powerful than custom queries, but cheap to grep for and reason about. If you need finer control, that's a one-off justification per file.
- **Greps, not lint plugins.** A 4-line audit script is cheaper to maintain than a custom ESLint rule. Re-evaluate if/when `@mantine` ships an official responsive-discipline lint plugin.

---

## Pairs Well With

- **`mantine-theme-discipline`** — colors. Together they form the front-line discipline pair: theme tokens + responsive tokens. Both surface as 3–4 line grep gates that ship to CI.
- **`pwa-setup`** — once the app is installable on a phone, this skill stops being optional.
- **`spotlight-cmdk`** — the Cmd-K chip is the canonical "header element that needs `visibleFrom="sm"`"; mention this skill in any spotlight-cmdk apply step.

---
name: "PWA Desktop-Site Guard"
description: "Immunize an installed PWA against Chrome Android's 'Desktop site' checkbox: detect the spoofed ~980px viewport in standalone mode and simulate mobile via html zoom + a centralized useIsMobile() hook. Use when an installed PWA renders the desktop layout on a phone, when retrofitting existing Vite+React+Mantine PWAs against this failure mode, or after pwa-setup on any new mobile-first app."
---

# PWA Desktop-Site Guard

## What This Skill Does

Chrome on Android remembers the ⋮ → "Desktop site" checkbox **per domain**, and an
installed PWA (WebAPK) inherits it. When it's on, Chrome:

- spoofs a desktop user agent (and client hints — the server cannot detect it),
- **ignores the viewport meta tag**, so the layout viewport becomes ~980px+,
- which makes every width-based breakpoint read "desktop" on a phone.

**There is no site-side opt-out** — no meta tag, header, or manifest field restores
viewport handling. This skill retrofits the app to detect the condition inside the
installed (standalone) app only and simulate mobile:

1. `desktopSiteGuard.js` — detection + CSS `zoom` on `<html>` so content lays out at
   true device width, sets `data-force-mobile`, ships a `?vpdebug` overlay.
2. `useIsMobile()` — drop-in wrapper for width-based `useMediaQuery` mobile checks
   that forces `true` in guard mode.
3. Migration of every width-based breakpoint the CSS media-query engine would get
   wrong (this is where all the real work and all the gotchas live — see Step 3).
4. A dismissible banner pointing at the durable fix (unchecking the checkbox).

Browser tabs keep Chrome's normal Desktop-site behavior — only the standalone app
is corrected. That separation is the point: the user's browser choice is respected;
the installed app never breaks because of it.

## When to Use

- An installed PWA shows the desktop layout / tiny text on a phone and the cause is
  the "Desktop site" checkbox (verify: uncheck it in a Chrome tab → app recovers).
- Retrofitting any existing `pwa-setup`-shaped app (Vite + React + Mantine + NestJS
  monolith) against this failure mode before users hit it.
- Right after `pwa-setup` on a new mobile-first project.

## When NOT to Use

- The app isn't installable / never runs standalone — a browser tab with Desktop
  site checked is the user's explicit choice; leave it alone.
- iOS-only problems — Safari's "Request Desktop Website" is a different mechanism
  and the guard deliberately won't fire there (detection requires standalone +
  Android-style viewport anomaly).
- The layout bug reproduces with Desktop site OFF — that's an ordinary responsive
  bug; use `responsive-layout-discipline`.

---

## How It Works (mechanism, read before editing)

With the viewport meta ignored, the layout viewport is ~980px on a ~384px screen.
CSS `zoom = innerWidth / deviceWidth` (~2.5–2.9) on `<html>` makes descendants lay
out at true device width AND render crisp at full resolution. But:

- `window.innerWidth` and CSS media queries **still report the fake width** — so
  every width-based mobile check must be routed through JS (`useIsMobile`) or
  mirrored under `html[data-force-mobile]`.
- Detection signals Chrome does NOT spoof (as of Chrome ~151): `screen.width`,
  `maxTouchPoints`, `pointer: coarse`, `display-mode: standalone`,
  `visualViewport.scale` (<0.75 when the viewport meta is being ignored).
  What Chrome spoofs varies by version — that's what the `?vpdebug` overlay is for.
- False-positive guards are load-bearing: `standalone` only (browser tabs exempt),
  `screenWidth < 1024` (touchscreen laptops with browser zoom would otherwise get
  zoomed ~8x), `innerWidth >= 800` (a correctly-viewported phone never reports that).
  Fail direction is deliberate: if a future Chrome spoofs more signals, the guard
  silently doesn't fire and the original bug stays visible — it never wrecks a
  real desktop.

## Step-by-Step Retrofit

### Step 1: Drop in the three files

`frontend/src/pwa/desktopSiteGuard.js` — copy verbatim from the reference
implementation: [resources/desktopSiteGuard.js](resources/desktopSiteGuard.js)
(source of truth: `idea-keep` repo, same path).

`frontend/src/hooks/useIsMobile.js`:

```js
import { useMediaQuery } from '@mantine/hooks';
import { isForcedMobile } from '../pwa/desktopSiteGuard';

export function useIsMobile(query) {
  const queryMatches = useMediaQuery(query);
  return isForcedMobile() || queryMatches;
}
```

Re-export it from `hooks/index.js`. Then in `main.jsx`, **before first render**:

```js
import { initDesktopSiteGuard } from './pwa/desktopSiteGuard';
initDesktopSiteGuard();
```

`frontend/src/pwa/DesktopSiteNotice.jsx` — dismissible banner, mounted once near
the app root (next to InstallBanner): [resources/DesktopSiteNotice.jsx](resources/DesktopSiteNotice.jsx).

### Step 2: Find every width-based mobile decision

```bash
grep -rn "useMediaQuery(" frontend/src --include="*.jsx" | grep -v import   # JS checks
grep -rn "window.innerWidth" frontend/src --include="*.jsx"                 # raw checks
grep -rn "@media" frontend/src --include="*.css"                            # CSS modules
grep -rn -E "={{[^}]*base:" frontend/src --include="*.jsx"                  # Mantine responsive object props
grep -rn "hiddenFrom|visibleFrom" frontend/src --include="*.jsx"            # Mantine visibility props
```

### Step 3: Migrate each class of hit

| Pattern found | Replacement |
|---|---|
| `useMediaQuery('(max-width: …)')` used as isMobile | `useIsMobile('(max-width: …)')` — keep each file's breakpoint, don't unify |
| `window.innerWidth <= N` | `isForcedMobile() \|\| window.innerWidth <= N` |
| CSS-module `@media (max-width: …)` blocks | Mirror the rules under `:global(html[data-force-mobile]) .localClass { … }` |
| `p={{ base: 'xs', sm: 'md' }}`, `cols={{ base: 1, sm: 3 }}`, `span={{ base: 12, md: 6 }}`, AppShell `padding={{ … }}` | `p={isForcedMobile() ? 'xs' : { base: 'xs', sm: 'md' }}` — forced mode gets the base value, normal browsing keeps the responsive object untouched |
| `hiddenFrom` / `visibleFrom` | Replace with conditional render on the page's `isMobile` |

**The Mantine responsive object props are the trap.** They compile to CSS media
queries, so after the JS migration everything *looks* mobile except padding and
grid columns — the app quietly gets desktop `md` spacing and multi-column grids.
The global AppShell `padding={{ base: 4, sm: 'md' }}` is the single biggest
offender; audit `DashboardLayout` first.

### Step 4: Verify on a real phone

1. Deploy. Fully close and reopen the installed app **twice** (service-worker
   update cycle) before judging anything.
2. Enable Desktop site for the domain in Chrome, relaunch the installed app →
   mobile layout + yellow banner.
3. To read the detection signals: open `https://<domain>/?vpdebug` in a Chrome tab
   once — the overlay persists via localStorage and appears **inside the installed
   app** too (the app launches at `start_url`, so a query param alone can't reach
   it). `?vpdebug=off` clears it.
4. Exercise pointer-math features specifically — @dnd-kit drag-and-drop, canvases,
   drawing surfaces. CSS `zoom` is standardized (Chrome 128+) and coordinates are
   consistent, but these are the components that break if anything is off.
5. Confirm a Chrome **tab** with Desktop site checked still renders desktop —
   the guard must not fire outside standalone.

## Already-Applied Heuristic

```bash
test -f frontend/src/pwa/desktopSiteGuard.js && grep -rq "useIsMobile" frontend/src/hooks/ \
  && echo "applied" || echo "not applied"
# Partial application check — object props migrated?
grep -rn -E "={{[^}]*base:" frontend/src --include="*.jsx" | grep -v isForcedMobile
# (any output = Step 3 incomplete)
```

## Critical Gotchas

1. **No site-side opt-out exists.** Don't burn time on meta tags, headers, or UA
   sniffing on the server — client hints are spoofed too. Simulation is the ceiling.
2. **Mantine's `color="yellow"` light-variant Alert is translucent** — a fixed
   banner over the AppShell header shows the header bleeding through. Paint the
   banner opaque (`background: '#fff3bf'`).
3. **`window.innerWidth` changes after zoom is applied.** Never treat it as stable
   across the guard's lifetime; compute the zoom target from `screen.width` (falls
   back to `visualViewport.width * scale`, clamped 320–480).
4. **The service worker masks your deploy.** Every "it still doesn't work" report
   during iteration: first check which bundle hash the phone is actually running
   (two full relaunches after each pull).
5. **Keep the banner.** Silent simulation makes future layout oddities mysterious;
   the banner explains the mode and points at the durable fix. Dismissal is
   per-session by design.

## Pairs Well With

- `pwa-setup` — prerequisite; this skill guards what that one builds.
- `responsive-layout-discipline` — a codebase that follows it (JS-driven
  breakpoints, no scattered CSS width queries) migrates in minutes; one that
  doesn't takes an afternoon.

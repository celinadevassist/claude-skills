---
name: "PWA Setup"
description: "Configure a Vite + React + NestJS monolith as an installable Progressive Web App with manifest, icon set, service-worker shell caching, Android install banner, and iOS install instruction sheet. Use when building a mobile-first app that must install to the home screen, work after a single online load, and survive App Store-free distribution."
---

# PWA Setup

## What This Skill Does

Turns a `monolith-setup`-shaped project (NestJS serving a Vite/React SPA) into an installable PWA:

- Web App Manifest with the right icon set (192/512 + maskable variants).
- HTML head meta tags for iOS, Android, and Windows tiles.
- `vite-plugin-pwa` configured with **`CacheFirst` for the app shell** and **`NetworkOnly` for `/api/*`** (the app must always hit the live backend for data).
- A custom Android install banner triggered by `beforeinstallprompt`.
- A platform-aware iOS install instruction sheet (iOS does not fire `beforeinstallprompt`, so users must add to Home Screen manually).
- HTTPS enforcement reminders — camera, push, and service worker all require HTTPS.

## When to Use

- Building any mobile-first app that should live on the home screen.
- The PRD says "PWA only, no native apps".
- The app needs camera, push notifications, or service worker — all of which require HTTPS + a registered SW.
- Replacing a "just add a manifest.json" half-PWA with a real, audit-passing install experience.

## When NOT to Use

- Backend-only services (no UI).
- Internal admin tools that won't run on phones.
- If the app must work fully offline with a write queue — that's beyond this skill (PRD-level decision; this skill is "always-online with shell-cache for fast launch").

---

## Architecture

```
frontend/
├── public/
│   ├── manifest.json              ← Web App Manifest
│   ├── icons/
│   │   ├── icon-192.png           ← any-purpose
│   │   ├── icon-512.png           ← any-purpose
│   │   ├── icon-192-maskable.png  ← maskable (Android adaptive icon)
│   │   └── icon-512-maskable.png
│   └── browserconfig.xml          ← Microsoft tiles (optional but cheap)
├── src/
│   ├── pwa/
│   │   ├── usePwaInstall.ts       ← captures beforeinstallprompt
│   │   ├── InstallBanner.tsx      ← Android: "Install" CTA
│   │   └── IosInstallSheet.tsx    ← iOS: "Tap Share → Add to Home Screen"
│   └── main.tsx                   ← register service worker
├── index.html                     ← <link rel="manifest"> + meta tags
└── vite.config.ts                 ← VitePWA plugin
```

**Caching strategy (PRD-aligned default):**
- App shell (HTML, JS, CSS, fonts, icons) → `CacheFirst`. Loads instantly on every launch, even on flaky cellular.
- API responses (`/api/*`) → `NetworkOnly`. Never cache business data — stale times, prices, or wristband states would be dangerous.
- Images that come from the API → `NetworkOnly` (or `StaleWhileRevalidate` only if explicitly safe per PRD).

---

## Step-by-Step Setup

### Step 1: Install vite-plugin-pwa

```bash
cd frontend
npm install -D vite-plugin-pwa workbox-window
```

### Step 2: Configure VitePWA in `vite.config.ts`

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',          // updates SW silently when a new build is deployed
      injectRegister: 'auto',
      includeAssets: ['favicon.svg', 'icons/*.png', 'browserconfig.xml'],
      manifest: false,                     // we ship our own manifest.json under /public
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: '/index.html',   // SPA route requests fall back to index
        navigateFallbackDenylist: [/^\/api\//, /^\/health/],
        runtimeCaching: [
          {
            // App shell + assets — fast launch
            urlPattern: ({ request }) =>
              request.destination === 'document' ||
              request.destination === 'script' ||
              request.destination === 'style' ||
              request.destination === 'font',
            handler: 'CacheFirst',
            options: {
              cacheName: 'app-shell',
              expiration: { maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
          {
            // API — always hit the network, never cache business data
            urlPattern: /\/api\/.*/,
            handler: 'NetworkOnly',
          },
        ],
      },
      devOptions: {
        enabled: false,                    // keep SW off in dev — it confuses HMR
      },
    }),
  ],
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api':         { target: 'http://localhost:3041', changeOrigin: true },
      '/swagger-json':{ target: 'http://localhost:3041', changeOrigin: true },
    },
  },
});
```

**Why `manifest: false` + a hand-written manifest:** the plugin's manifest generator is fine for trivial apps, but for production you want full control over `categories`, `shortcuts`, language, and `purpose: "any maskable"` icon variants. Ship `frontend/public/manifest.json` directly.

### Step 3: Web App Manifest (`frontend/public/manifest.json`)

```json
{
  "name": "Your App Full Name",
  "short_name": "AppName",
  "description": "One-sentence pitch — appears in Android install dialog.",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait-primary",
  "theme_color": "#2563EB",
  "background_color": "#FFFFFF",
  "lang": "en",
  "categories": ["productivity", "business"],
  "icons": [
    { "src": "/icons/icon-192.png",          "type": "image/png", "sizes": "192x192", "purpose": "any" },
    { "src": "/icons/icon-512.png",          "type": "image/png", "sizes": "512x512", "purpose": "any" },
    { "src": "/icons/icon-192-maskable.png", "type": "image/png", "sizes": "192x192", "purpose": "maskable" },
    { "src": "/icons/icon-512-maskable.png", "type": "image/png", "sizes": "512x512", "purpose": "maskable" }
  ]
}
```

**Icon rules** (gotchas — get them wrong and the install fails or the icon looks bad):
- 192 + 512 PNG **both required**. 192 is the home screen icon, 512 is the splash + Play Store-style display.
- `purpose: "maskable"` variants need a safe-area: keep all meaningful pixels inside a center circle of ~80% diameter. Test in [maskable.app](https://maskable.app/editor).
- If you don't ship maskable, Android may crop your transparent edges into a white square — looks broken.
- Prefer PNG over SVG for icons (Android is fine with SVG, iOS is not).

### Step 4: HTML head tags (`frontend/index.html`)

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>Your App</title>

  <!-- Manifest + theme -->
  <link rel="manifest" href="/manifest.json" />
  <meta name="theme-color" content="#2563EB" />

  <!-- iOS -->
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="default" />
  <meta name="apple-mobile-web-app-title" content="AppName" />
  <link rel="apple-touch-icon" sizes="192x192" href="/icons/icon-192.png" />

  <!-- Microsoft tile (cheap, optional) -->
  <meta name="msapplication-config" content="/browserconfig.xml" />
  <meta name="msapplication-TileColor" content="#2563EB" />

  <!-- Splash background until app paints -->
  <meta name="background-color" content="#FFFFFF" />
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

`viewport-fit=cover` is required for safe-area-aware bottom tab bars on iPhones with a home indicator.

### Step 5: Capture `beforeinstallprompt` (Android)

```ts
// frontend/src/pwa/usePwaInstall.ts
import { useEffect, useState, useCallback } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export function usePwaInstall() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(
    typeof window !== 'undefined' && window.matchMedia('(display-mode: standalone)').matches,
  );

  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();                     // stop the default mini-infobar
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setDeferred(null);
    };
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const promptInstall = useCallback(async () => {
    if (!deferred) return null;
    await deferred.prompt();
    const choice = await deferred.userChoice;
    setDeferred(null);
    return choice.outcome;                    // 'accepted' | 'dismissed'
  }, [deferred]);

  return {
    canInstall: !!deferred && !installed,
    installed,
    promptInstall,
    isIos: typeof window !== 'undefined' && /iphone|ipad|ipod/i.test(window.navigator.userAgent),
  };
}
```

### Step 6: Android install banner (`InstallBanner.tsx`)

```tsx
import { usePwaInstall } from './usePwaInstall';

export function InstallBanner() {
  const { canInstall, isIos, promptInstall } = usePwaInstall();
  if (isIos || !canInstall) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 flex items-center gap-3 bg-blue-600 px-4 py-3 text-white shadow-lg">
      <span className="flex-1 text-sm">Install this app for faster access and full-screen mode.</span>
      <button
        onClick={promptInstall}
        className="rounded-md bg-white px-3 py-1 text-sm font-medium text-blue-700"
      >
        Install
      </button>
    </div>
  );
}
```

### Step 7: iOS install instruction sheet (`IosInstallSheet.tsx`)

iOS Safari does **not** fire `beforeinstallprompt`. The only way to install is `Share → Add to Home Screen`. Show users a one-time instruction sheet.

```tsx
import { useEffect, useState } from 'react';
import { usePwaInstall } from './usePwaInstall';

const DISMISS_KEY = 'pwa-ios-sheet-dismissed';

export function IosInstallSheet() {
  const { isIos, installed } = usePwaInstall();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isIos || installed) return;
    if (localStorage.getItem(DISMISS_KEY)) return;
    // Show after the user has spent ~10s in the app — don't ambush on first paint.
    const t = window.setTimeout(() => setOpen(true), 10_000);
    return () => window.clearTimeout(t);
  }, [isIos, installed]);

  if (!open) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, '1');
    setOpen(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40">
      <div className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-xl">
        <h2 className="text-lg font-semibold">Install this app</h2>
        <ol className="mt-3 space-y-2 text-sm text-gray-700">
          <li>1. Tap the <strong>Share</strong> icon in Safari's toolbar.</li>
          <li>2. Scroll and tap <strong>Add to Home Screen</strong>.</li>
          <li>3. Tap <strong>Add</strong> in the top-right.</li>
        </ol>
        <button onClick={dismiss} className="mt-4 w-full rounded-md bg-gray-900 py-2 text-white">
          Got it
        </button>
      </div>
    </div>
  );
}
```

Mount both components in your root layout. They render to nothing on platforms where they're not relevant.

### Step 7b: Mantine variant (recommended for projects using @mantine/core)

If your project uses Mantine instead of Tailwind, swap the components above for these. They use Mantine theme tokens so they auto-flip in dark mode (see `mantine-theme-discipline`).

**`InstallBanner.tsx` (Mantine)**

```tsx
import { Button, Group, Paper, Text } from '@mantine/core';
import { IconDownload, IconX } from '@tabler/icons-react';
import { useState } from 'react';
import { usePwaInstall } from './usePwaInstall';

const DISMISS_KEY = 'pwa.banner.dismissed';

export function InstallBanner() {
  const { canInstall, isIos, promptInstall } = usePwaInstall();
  const [dismissed, setDismissed] = useState(
    typeof window !== 'undefined' && Boolean(localStorage.getItem(DISMISS_KEY)),
  );
  if (isIos || !canInstall || dismissed) return null;

  const dismiss = () => { localStorage.setItem(DISMISS_KEY, '1'); setDismissed(true); };

  return (
    <Paper pos="fixed" bottom={16} right={16} p="md" radius="md" shadow="md" withBorder
           style={{ zIndex: 1000, maxWidth: 360 }}>
      <Group justify="space-between" wrap="nowrap" mb="xs">
        <Text fw={600} size="sm">Install this app</Text>
        <Button variant="subtle" color="gray" size="compact-xs" onClick={dismiss}>
          <IconX size={14} />
        </Button>
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        Add to your home screen for one-tap access and full-screen mode.
      </Text>
      <Button size="xs" leftSection={<IconDownload size={14} />}
              onClick={async () => {
                const outcome = await promptInstall();
                if (outcome === 'dismissed') dismiss();
              }}>
        Install
      </Button>
    </Paper>
  );
}
```

**`IosInstallSheet.tsx` (Mantine)**

```tsx
import { Button, List, Modal, Stack, Text } from '@mantine/core';
import { IconShare } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { usePwaInstall } from './usePwaInstall';

const DISMISS_KEY = 'pwa.ios.dismissed';

export function IosInstallSheet() {
  const { isIos, installed } = usePwaInstall();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isIos || installed) return;
    if (localStorage.getItem(DISMISS_KEY)) return;
    const t = window.setTimeout(() => setOpen(true), 10_000);
    return () => window.clearTimeout(t);
  }, [isIos, installed]);

  const dismiss = () => { localStorage.setItem(DISMISS_KEY, '1'); setOpen(false); };
  if (!isIos || installed) return null;

  return (
    <Modal opened={open} onClose={dismiss} title="Install this app" centered size="sm">
      <Stack gap="md">
        <Text size="sm" c="dimmed">Add this app to your home screen for one-tap access.</Text>
        <List spacing="xs" size="sm">
          <List.Item icon={<IconShare size={16} />}>
            Tap the <strong>Share</strong> icon in Safari's toolbar
          </List.Item>
          <List.Item>Scroll and tap <strong>Add to Home Screen</strong></List.Item>
          <List.Item>Tap <strong>Add</strong> in the top-right</List.Item>
        </List>
        <Button onClick={dismiss}>Got it</Button>
      </Stack>
    </Modal>
  );
}
```

**`UpdatePrompt.tsx` — service-worker registration with a Mantine notification**

Replaces Step 8's bare `registerSW` with a user-visible "new version available" toast that includes a Reload button.

```tsx
import { useEffect } from 'react';
import { notifications } from '@mantine/notifications';
import { Button } from '@mantine/core';
import { registerSW } from 'virtual:pwa-register';

export function PwaRegistration() {
  useEffect(() => {
    const updateSW = registerSW({
      onNeedRefresh() {
        notifications.show({
          id: 'pwa-update',
          title: 'New version available',
          message: <Button size="xs" mt={4} onClick={() => updateSW(true)}>Reload</Button>,
          color: 'blue', autoClose: false, withCloseButton: true,
        });
      },
      onOfflineReady() {
        notifications.show({
          title: 'Offline-ready',
          message: 'The app shell is cached and will load instantly even on slow connections.',
          color: 'green',
        });
      },
    });
  }, []);
  return null;
}
```

Mount `<PwaRegistration />` once near `<MantineProvider>` in `main.tsx`.

### Step 7c: Generate the icon set from a single SVG (rsvg-convert)

Maintaining 5 separate PNG files by hand is fragile. Keep one **source SVG** for the "any-purpose" icon and one for the maskable variant; generate every PNG size on demand:

**`frontend/public/icons/source-any.svg`** — full bleed, can have rounded corners, can have edge content
**`frontend/public/icons/source-maskable.svg`** — keep all meaningful pixels in the central 80% (Android crops the rest)

Then run:

```bash
cd frontend/public/icons
rsvg-convert -w 192 -h 192 source-any.svg       -o icon-192.png
rsvg-convert -w 512 -h 512 source-any.svg       -o icon-512.png
rsvg-convert -w 192 -h 192 source-maskable.svg  -o icon-192-maskable.png
rsvg-convert -w 512 -h 512 source-maskable.svg  -o icon-512-maskable.png
rsvg-convert -w 180 -h 180 source-any.svg       -o apple-touch-icon.png
rsvg-convert -w 32  -h 32  source-any.svg       -o ../favicon-32.png
rsvg-convert -w 16  -h 16  source-any.svg       -o ../favicon-16.png
```

`rsvg-convert` ships with `librsvg2-bin` on Debian/Ubuntu (`apt install librsvg2-bin`). Cross-platform alternatives: `sharp` (Node), `convert` (ImageMagick).

When real branding lands later, swap the two SVGs and rerun — every downstream icon updates automatically.

### Step 8: Service worker registration

`vite-plugin-pwa` with `injectRegister: 'auto'` injects a `<script>` that registers the SW automatically. If you need to react to "new version available," use `workbox-window`:

```ts
// frontend/src/main.tsx
import { registerSW } from 'virtual:pwa-register';

registerSW({
  onNeedRefresh() {
    // Show a "new version available — reload" toast
  },
  onOfflineReady() {
    // Show "ready to work without network for the cached shell"
  },
});
```

### Step 9: HTTPS is mandatory

Service workers, the install prompt, the camera (`getUserMedia`), and Web Push **all require HTTPS** (or `http://localhost` for dev). With NPM + sslip.io wildcard cert, this is already the case in production. In dev, use `localhost` rather than the LAN IP, or set up Caddy/NPM dev entry with SSL (see `monolith-setup` Step 8).

---

## Verification Checklist

Run before declaring this skill complete:

```bash
# 1. Manifest is reachable
curl -s https://APPNAME.IP.sslip.io/manifest.json | head -5

# 2. Icons return 200, not 404
for icon in icon-192.png icon-512.png icon-192-maskable.png icon-512-maskable.png; do
  echo -n "$icon: "
  curl -sI "https://APPNAME.IP.sslip.io/icons/$icon" | head -1
done

# 3. Service worker is registered
curl -sI https://APPNAME.IP.sslip.io/sw.js | head -1

# 4. Lighthouse PWA audit (Chrome DevTools → Lighthouse → Progressive Web App)
#    Expect: Installable, PWA optimized, fast and reliable.
```

**Manual install test (REQUIRED — one each):**
- [ ] Real Android (Chrome): install banner appears, tap → app installs to home screen, launches in standalone (no browser chrome).
- [ ] Real iPhone (Safari): instruction sheet appears, follow steps, app installs to home screen, launches in standalone.
- [ ] Open the installed app with airplane mode on — the **shell loads instantly** (white screen would be a fail). API requests fail gracefully with the app's normal "no internet" UX.
- [ ] Bump the SPA version, rebuild, redeploy; on next launch the SW updates silently.

---

## Critical Gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Install banner never appears | Site not served over HTTPS, or manifest is missing required fields, or SW not registered | Check Lighthouse PWA audit; it lists every missing requirement explicitly. |
| App installs but icon looks pixelated on Android | Only 192 icon shipped, no 512 | Ship both. 512 is used for splash + larger displays. |
| Icon corners get clipped to a square on Android | No maskable variant | Ship `purpose: "maskable"` icons with safe-area padding. |
| iOS app installs but launches with browser chrome | Missing `apple-mobile-web-app-capable` meta | Add `<meta name="apple-mobile-web-app-capable" content="yes" />`. |
| Bottom tab bar overlaps iPhone home indicator | Missing `viewport-fit=cover` | Add to viewport meta + use Tailwind's `pb-[env(safe-area-inset-bottom)]` (or shadcn's safe-area utility) on the tab bar. |
| Stale frontend served to installed users after redeploy | `CacheFirst` shell + a SW that doesn't auto-update | Use `registerType: 'autoUpdate'`. Confirmed working in `vite-plugin-pwa` v0.17+. |
| `beforeinstallprompt` never fires in Chrome | The PWA criteria aren't met (e.g. no SW, no manifest, no HTTPS), or the user already dismissed it earlier | Check chrome://flags is default; check Lighthouse; clear site data and retry. |
| API responses cached forever in installed app | A `runtimeCaching` rule that catches `/api/*` with `CacheFirst` or `StaleWhileRevalidate` | Force `/api/*` to `NetworkOnly` (see Step 2). |
| Camera prompt fails silently in installed PWA | Service worker hijacking `getUserMedia` somehow, or no HTTPS | Confirm site is HTTPS; camera in PWAs requires HTTPS. |
| Service worker active in dev, breaks HMR | `devOptions.enabled: true` | Keep `devOptions.enabled: false` (default in this skill). Test PWA on the deployed dev URL, not local Vite. |

---

## Tradeoffs This Skill Bakes In

- **`autoUpdate` over user-confirmed updates.** Silent SW updates are friendlier; downside is the user might see a UI inconsistency for ~1 reload. If your app is stateful enough that mid-session updates would corrupt state, switch to `prompt` and force a reload.
- **`NetworkOnly` for `/api/*`.** Zero offline data path. If the app must keep working offline (e.g. order taking with a sync queue), this skill is not enough — the PRD must explicitly call for an offline action queue, and the implementation lives in a separate skill.
- **Manual manifest, not generated.** More control, but you must remember to update icon paths and `theme_color` in two places (manifest + index.html meta).

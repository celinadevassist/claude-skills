---
name: "Spotlight (⌘K)"
description: "Add a Cmd-K / Ctrl-K command palette for navigation, role-aware actions, and quick search across a Mantine + React Router app. Use when an admin tool has 5+ pages and keyboard nav would beat menu-clicking."
---

# Spotlight (⌘K)

## What This Skill Does

Wires up `@mantine/spotlight` with a **role-aware action registry** so users can ⌘K to any page, ⌘P to do the same (familiar to VS Code users), or click a search chip in the header. Actions filter by user role automatically — admin-only routes don't appear for members.

Two files + a one-line mount + one nav chip. ~120 lines total.

## When to Use

- Internal tools with 5+ pages where users move around frequently.
- Apps with admin/member role separation — spotlight makes "what can this user do" trivially explorable.
- Anywhere you'd otherwise build a sidebar tree of routes.

## When NOT to Use

- Single-page apps or apps with ≤3 routes (the menu IS the spotlight).
- End-user-facing apps where ⌘K isn't part of the audience's mental model.
- Mobile-first apps where the keyboard shortcut is invisible to users.

---

## Implementation (4 steps)

### Step 1: Install

```bash
npm install --save @mantine/spotlight
# Match your @mantine/core version exactly to avoid peer dep conflicts.
```

### Step 2: Create the action registry — `src/components/Spotlight.tsx`

```tsx
import { Spotlight, SpotlightActionData, spotlight } from '@mantine/spotlight';
import '@mantine/spotlight/styles.css';
import {
  IconHome, IconLogout, IconSearch,
  IconShield, IconUsers, /* + your route icons */
} from '@tabler/icons-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../services/auth/AuthContext';

export function AppSpotlight() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const isAdmin = user?.role === 'admin';

  const actions: SpotlightActionData[] = [
    {
      id: 'go-dashboard',
      label: 'Dashboard',
      description: 'Go to home',
      keywords: ['home', 'overview'],
      onClick: () => navigate('/'),
      leftSection: <IconHome size={18} />,
    },
    // … one action per route. Add `keywords` for non-obvious matches.

    ...(isAdmin
      ? [
          {
            id: 'go-users',
            label: 'Users',
            description: 'Manage team accounts (admin only)',
            keywords: ['team', 'admin', 'members'],
            onClick: () => navigate('/users'),
            leftSection: <IconUsers size={18} />,
          },
          {
            id: 'go-audit',
            label: 'Audit Log',
            description: 'Every mutation, attributed (admin only)',
            keywords: ['log', 'security', 'history'],
            onClick: () => navigate('/audit'),
            leftSection: <IconShield size={18} />,
          },
        ]
      : []),

    {
      id: 'logout',
      label: 'Sign out',
      description: user?.email,
      keywords: ['logout', 'signout', 'exit'],
      onClick: async () => {
        await logout();
        navigate('/login');
      },
      leftSection: <IconLogout size={18} />,
    },
  ];

  return (
    <Spotlight
      actions={actions}
      shortcut={['mod + K', 'mod + P']}
      nothingFound="Nothing found"
      highlightQuery
      searchProps={{
        leftSection: <IconSearch size={18} />,
        placeholder: 'Search modules and actions…',
      }}
    />
  );
}

export function openSpotlight() {
  spotlight.open();
}
```

**Pattern notes:**
- `id` must be unique and stable — `go-{route}` or `{verb}-{noun}` works well.
- `keywords` are the secret sauce. Add synonyms users might type ("logout" → matches "Sign out").
- Spread admin-only actions inside `...(isAdmin ? [{…}] : [])` — clean and the role check happens at render time.
- `mod + K` resolves to ⌘ on Mac, Ctrl elsewhere. Two shortcuts (K + P) covers both VS Code and Linear muscle memory.

### Step 3: Mount once at the route root — `src/App.tsx`

```tsx
import { AppSpotlight } from './components/Spotlight';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/*" element={
        <ProtectedRoute>
          <AppSpotlight />          {/* ← mount inside ProtectedRoute so it has user context */}
          <AppShell>
            <Routes>{/* … */}</Routes>
          </AppShell>
        </ProtectedRoute>
      } />
    </Routes>
  );
}
```

**Why inside `ProtectedRoute`:** Spotlight needs `useAuth()` to know the user's role. Mounting outside throws.

### Step 4: Add a search chip + kbd hint to the header — `src/components/AppShell.tsx`

```tsx
import { Kbd, UnstyledButton, Text } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { openSpotlight } from './Spotlight';

// inside the header row:
<UnstyledButton
  onClick={() => openSpotlight()}
  p="6px 10px"
  style={{
    borderRadius: 6,
    border: '1px solid var(--mantine-color-default-border)',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13,
  }}
>
  <IconSearch size={14} />
  <Text size="xs" c="dimmed">Search</Text>
  <Kbd size="xs">⌘K</Kbd>
</UnstyledButton>
```

The chip discoverably teaches the shortcut on first sight. After a day of use, most users hit ⌘K directly and never click the chip again — but new joiners always know it's there.

**Border:** `var(--mantine-color-default-border)` auto-flips with the theme — matches the `mantine-theme-discipline` skill.

---

## Verification Checklist

- [ ] ⌘K (or Ctrl+K) opens the palette from any page.
- [ ] ⌘P opens the same palette (familiar to VS Code users).
- [ ] Typing matches `label`, `description`, AND `keywords`.
- [ ] Switching to a member account hides admin-only actions.
- [ ] Esc closes the palette.
- [ ] Header chip is keyboard-focusable (tab + enter opens spotlight).

---

## Common Mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Palette opens but list is empty | `actions` array is `[]` | Make sure each route has an entry; spread the admin-only group conditionally. |
| `useAuth must be used inside provider` | Spotlight mounted outside `ProtectedRoute` / `AuthProvider` | Move it inside the protected tree. |
| Same action fires twice on Enter | Two actions share an `id` | Make every `id` unique. |
| ⌘K conflicts with browser bookmark | Browser has higher priority on some pages | Use `mod + P` as the secondary, never override browser shortcuts that users rely on (Cmd+S, Cmd+R, etc.). |
| Action labels disappear in dark mode | Hardcoded `c="gray.7"` in custom actions | Apply `mantine-theme-discipline` — use `c="dimmed"` instead. |

---

## Tradeoffs

- **Static action list, not dynamic.** This skill teaches the simple route-registry pattern. For "search across all PRDs / projects / users in the database" you'd want a dynamic Spotlight that fetches results — that's a separate, larger skill.
- **All actions registered up-front.** Big apps (50+ pages) might want to lazy-register per-section actions. Cross that bridge when you reach it; the simple registry covers 95% of cases.
- **No persistence of recent actions.** Mantine Spotlight doesn't track history out of the box. If you want "recently used" at the top, sort `actions` from a localStorage-backed counter — but it's rarely worth the complexity.

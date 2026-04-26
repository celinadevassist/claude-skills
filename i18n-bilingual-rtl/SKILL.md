---
name: "i18n Bilingual RTL"
description: "Configure react-i18next for English + Arabic with full RTL support: Tailwind logical properties, Cairo + Inter font pairing, dir-toggle on language change, Arabic pluralization, locale-aware number/date formatting, and Arabic-safe PDF + Excel export. Use when the project requires bilingual UI with RTL from day one (retrofitting RTL into a finished app is expensive — about 15% per screen if added later)."
---

# i18n Bilingual RTL

## What This Skill Does

Bakes English + Arabic (RTL) bilingual support into a Vite/React + NestJS monolith **from day one**, so every screen built afterward is RTL-correct without rework:

- `react-i18next` setup with the right namespace strategy and language detection.
- `dir="rtl"` toggle on the HTML root that flips the entire layout via Tailwind logical properties.
- Cairo (Arabic) + Inter (Latin) font pairing in one font-family rule — browsers fall through per-character automatically.
- Arabic pluralization via i18next's `count` interpolation (Arabic has 6 forms: zero, one, two, few, many, other).
- Locale-aware number/date formatting, with `ar-EG-u-nu-latn` as the sensible Egyptian-app default (Western digits in Arabic UI).
- Arabic PDF rendering — the real gotcha — handled via `pdfkit-rtl` or `pdf-lib` with Cairo font embedded.
- Excel exports respect RTL via `worksheet.views = [{ rightToLeft: true }]`.
- Lint rules that **fail the build** when a developer adds a hardcoded English string or a physical CSS property (`ml-*`, `mr-*`, `left-*`, `right-*`).
- Translator handoff workflow (en.json is the source of truth → translator → ar.json → CI parity check).

## When to Use

- Any project where Arabic is a v1 (or guaranteed v1.x) requirement.
- Any project where the user base is bilingual and the app needs to be installable in either language.
- Greenfield projects — adding RTL later costs roughly 15% per existing screen and a full design pass; adding it day one is essentially free.

## When NOT to Use

- English-only product where Arabic is a "maybe someday" — the lint rules and font pairing add real complexity, only worth paying once the requirement is real.
- Projects already shipping with hardcoded `ml-*` / `mr-*` everywhere — you need a different skill (an RTL retrofit is a project, not a setup).

---

## Architecture

```
frontend/
├── src/
│   ├── i18n/
│   │   ├── index.ts              ← init react-i18next
│   │   ├── en.json               ← source of truth (developer writes here)
│   │   └── ar.json               ← translator fills (CI checks parity)
│   ├── hooks/
│   │   └── useDirection.ts       ← syncs <html dir> with active language
│   └── main.tsx                  ← imports ./i18n
├── tailwind.config.ts            ← tailwindcss-rtl plugin
├── eslint.config.js              ← i18next/no-literal-string + custom rule for ml-*/mr-*
└── index.html                    ← <html lang="en"> default

backend/src/
├── users/schemas/user.schema.ts             ← preferredLanguage: 'en'|'ar'
├── config/schemas/system-config.schema.ts   ← defaultLanguage: 'en'|'ar'
└── reports/pdf/
    ├── fonts/Cairo-Regular.ttf              ← bundled, NOT loaded from CDN
    ├── fonts/Cairo-Bold.ttf
    └── pdf-builder.ts                        ← pdfkit-rtl OR pdf-lib
```

---

## Step-by-Step Setup

### Step 1: Install dependencies

```bash
cd frontend
npm install react-i18next i18next i18next-browser-languagedetector
npm install -D tailwindcss-rtl eslint-plugin-i18next
```

```bash
cd backend
# pdfkit-rtl is the simplest path; pdf-lib is the fallback if you hit shaping bugs
npm install pdfkit-rtl
# fonts get committed under src/reports/pdf/fonts/
```

### Step 2: react-i18next init (`frontend/src/i18n/index.ts`)

```ts
import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';
import en from './en.json';
import ar from './ar.json';

export const SUPPORTED_LANGUAGES = ['en', 'ar'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ar: { translation: ar },
    },
    fallbackLng: 'en',
    supportedLngs: SUPPORTED_LANGUAGES,
    interpolation: { escapeValue: false },   // React already escapes
    detection: {
      // 1. user's saved preference, 2. <html lang>, 3. fallback
      order: ['localStorage', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'lang',
    },
    react: { useSuspense: false },
  });

export default i18n;
```

Import once in `main.tsx`:

```ts
import './i18n';
```

### Step 3: Direction toggle (`frontend/src/hooks/useDirection.ts`)

```ts
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export function useDirection() {
  const { i18n } = useTranslation();
  useEffect(() => {
    const dir = i18n.language === 'ar' ? 'rtl' : 'ltr';
    document.documentElement.setAttribute('dir', dir);
    document.documentElement.setAttribute('lang', i18n.language);
  }, [i18n.language]);
}
```

Mount once at the top of your app shell:

```tsx
function AppShell() {
  useDirection();
  return /* ... */;
}
```

### Step 4: Tailwind RTL plugin (`tailwind.config.ts`)

```ts
import type { Config } from 'tailwindcss';
import rtl from 'tailwindcss-rtl';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Inter for Latin glyphs, Cairo for Arabic glyphs.
        // Browsers fall through per-character automatically — one rule, both languages.
        sans: ['Inter', 'Cairo', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [rtl],
} satisfies Config;
```

**Bundle the fonts locally** (offline-friendly, privacy, speed):

```css
/* frontend/src/index.css */
@font-face {
  font-family: 'Inter';
  src: url('/fonts/Inter-Variable.woff2') format('woff2-variations');
  font-weight: 100 900;
  font-display: swap;
}
@font-face {
  font-family: 'Cairo';
  src: url('/fonts/Cairo-Variable.woff2') format('woff2-variations');
  font-weight: 200 1000;
  font-display: swap;
}
```

### Step 5: Logical-properties-only lint rule (`eslint.config.js`)

```js
import i18next from 'eslint-plugin-i18next';

export default [
  // ... your existing config
  {
    plugins: { i18next },
    rules: {
      // Forbid hardcoded English strings in JSX — every visible string must flow through t().
      'i18next/no-literal-string': ['error', {
        markupOnly: true,
        ignoreAttribute: ['data-testid', 'className', 'href', 'src', 'id', 'role', 'type', 'name'],
      }],
      // Forbid physical Tailwind properties (`ml-*`, `mr-*`, `left-*`, `right-*`) — use logical props.
      'no-restricted-syntax': ['error', {
        selector: 'Literal[value=/\\b(?:ml-|mr-|pl-|pr-|left-|right-|text-left|text-right)\\b/]',
        message: 'Use logical Tailwind classes (ms-/me-/ps-/pe-/start-/end-/text-start/text-end) for RTL safety.',
      }],
    },
  },
];
```

After this lands, **the build fails on hardcoded strings and physical CSS** — the only sustainable way to keep i18n + RTL clean.

### Step 6: en.json structure

Use **flat keys per screen**, not deeply nested namespaces. Translators work in JSON editors and hate deep trees.

```json
{
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.confirm": "Confirm",

  "auth.login.title": "Sign in",
  "auth.login.username": "Username",
  "auth.login.password": "Password",
  "auth.login.submit": "Sign in",

  "cashier.home.newVisit": "New visit",
  "cashier.home.queueCount_zero": "No visits in queue",
  "cashier.home.queueCount_one": "{{count}} visit in queue",
  "cashier.home.queueCount_other": "{{count}} visits in queue",

  "operator.scan.signOut": "Sign out",
  "operator.scan.skip": "Skip"
}
```

Arabic plurals work automatically when you write `key_zero`, `key_one`, `key_two`, `key_few`, `key_many`, `key_other` — `react-i18next` picks the right one from `Intl.PluralRules`.

### Step 7: Number, date, and currency formatting

Always go through `Intl`, never string-concatenate.

```ts
import { useTranslation } from 'react-i18next';

export function useFormat() {
  const { i18n } = useTranslation();

  // Egyptian-app convention: Western digits even in Arabic UI.
  // To switch to Arabic-Indic digits, drop the `-u-nu-latn` suffix.
  const numberLocale = i18n.language === 'ar' ? 'ar-EG-u-nu-latn' : 'en-US';

  return {
    formatNumber: (n: number) => new Intl.NumberFormat(numberLocale).format(n),
    formatMoney: (piastres: number) =>
      `${new Intl.NumberFormat(numberLocale, { minimumFractionDigits: 0 }).format(piastres / 100)} LE`,
    formatDate: (d: Date | string, opts?: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat(numberLocale, { timeZone: 'Africa/Cairo', ...opts }).format(new Date(d)),
  };
}
```

### Step 8: Inputs that must stay LTR

Phone numbers, codes, and numeric inputs read backwards in RTL containers if you don't pin them:

```tsx
<input type="tel" dir="ltr" inputMode="numeric" />
```

For mid-text numbers (e.g. a phone embedded in an Arabic sentence), wrap in `<bdi>`:

```tsx
<p>{t('contact.line', { phone: <bdi>{phone}</bdi> })}</p>
```

### Step 9: Backend data model fields

```ts
// User schema
preferredLanguage: { type: String, enum: ['en', 'ar'], default: 'en' }

// SystemConfig schema (single doc)
defaultLanguage: { type: String, enum: ['en', 'ar'], default: 'en' }
```

Login response sends `installationLanguage` so the SPA can render the login screen in the right language before any user is authenticated.

```ts
POST /auth/login → { ..., installationTimezone, installationLanguage }
```

### Step 10: Public unauthenticated language endpoint

The login screen has no user yet, so it can't read `User.preferredLanguage`. Expose a tiny public endpoint:

```ts
GET /api/config/public  →  { installationLanguage, installationName, installationTimezone }
```

Frontend reads it on cold start to pick the right login-screen language and direction.

### Step 11: Arabic in PDFs (the gotcha)

`pdfkit` does not handle Arabic shaping or RTL out of the box. Two paths:

**Path A — `pdfkit-rtl` (simplest):**

```ts
import PDFDocument from 'pdfkit-rtl';
import fs from 'fs';

const doc = new PDFDocument({ size: 'A4' });
doc.registerFont('Cairo', './src/reports/pdf/fonts/Cairo-Regular.ttf');
doc.registerFont('Cairo-Bold', './src/reports/pdf/fonts/Cairo-Bold.ttf');

doc.font('Cairo').fontSize(14).text('فاتورة', { align: 'right' });
```

**Path B — `pdf-lib` (fallback when `pdfkit-rtl` shaping breaks):**

`pdf-lib` requires you to use a fontkit + Arabic-shaping helper, but its output is more reliable for complex Arabic ligatures. Switch when you hit a real bug, not preemptively.

**Either path** — embed the Cairo TTF in the backend image. Do not rely on Google Fonts at runtime.

**Smoke test in milestone 5 (mobile shell), not milestone 17 (reports):** render one trivial PDF with `"Hello"` and `"مرحبا"` side-by-side and visually verify Arabic glyphs are joined correctly (not separated letters in reverse order). Catching this early saves a week.

### Step 12: Excel exports

```ts
import ExcelJS from 'exceljs';

const wb = new ExcelJS.Workbook();
const ws = wb.addWorksheet('Visits');
if (userLanguage === 'ar') {
  ws.views = [{ rightToLeft: true }];
}
// Column headers in user's UI language at export time
ws.columns = [{ header: t('reports.columns.date'), key: 'date' }, /* ... */];
```

Excel respects the user's locale for digit display by itself — don't override.

### Step 13: Translator workflow

- During development, every `t('key')` is added to `en.json` immediately. `ar.json` mirrors the keys with empty strings (or English fallbacks).
- **CI parity check** fails the build if `en.json` and `ar.json` diverge in keys:

```bash
# scripts/check-i18n-parity.mjs
import en from '../frontend/src/i18n/en.json' assert { type: 'json' };
import ar from '../frontend/src/i18n/ar.json' assert { type: 'json' };
const enKeys = Object.keys(en).sort();
const arKeys = Object.keys(ar).sort();
const missing = enKeys.filter(k => !arKeys.includes(k));
const extra = arKeys.filter(k => !enKeys.includes(k));
if (missing.length || extra.length) {
  console.error('i18n parity error.');
  if (missing.length) console.error('Missing in ar.json:', missing);
  if (extra.length)   console.error('Extra in ar.json:',   extra);
  process.exit(1);
}
```

- **Near launch**, hand `en.json` to a professional translator (Lokalise, Crowdin, or a Cairo-based agency). Don't machine-translate before review — bad Arabic in a UI is worse than English-only.
- After launch, every new key follows the same pattern: developer writes English, translator fills Arabic before the next release.

### Step 14: What stays English (intentional)

- Audit log entries (machine data; UI translates field labels at display time).
- Telegram developer alerts (vendor reads them; technical jargon stays English).
- Admin-entered free text (visitor type names, extra charge names, child names) — stored as-typed, no per-language values. If admin types `Minion` it stays `Minion`. If they type `مينيون` it stays `مينيون`. Single value, not a translation pair.
- Voice/audio cues (non-linguistic).

---

## Verification Checklist

```bash
# 1. i18n parity
node scripts/check-i18n-parity.mjs && echo "OK: keys match"

# 2. No hardcoded JSX strings
npx eslint 'src/**/*.{ts,tsx}' --rule 'i18next/no-literal-string: error' --quiet

# 3. No physical Tailwind classes
grep -rE '\b(?:ml-|mr-|pl-|pr-|left-|right-|text-left|text-right)' src/ | grep -v 'ms-\|me-\|ps-\|pe-\|start-\|end-' \
  && echo "FAIL: physical CSS found" || echo "OK: only logical CSS"
```

**Manual smoke tests:**
- [ ] Toggle language to Arabic — entire layout flips RTL, including nav, drawers, tab bars, modals, and table headers.
- [ ] A directional icon (back arrow, chevron) is visually correct in both directions (use `rtl:rotate-180` or pick symmetric icons like `ChevronLeft`).
- [ ] An Arabic-language PDF renders with **joined ligatures** (not separated letters in reverse order). Open it in a native Arabic reader (an Egyptian colleague's phone is the gold standard).
- [ ] Phone-number inputs stay LTR even in Arabic UI.
- [ ] Number `1234.5` renders as `1,234.5` in English and `1,234.5` in Arabic with `-u-nu-latn` (or `١٬٢٣٤٫٥` if you opt into Arabic-Indic digits).
- [ ] Login screen renders in the installation's default language **before** the user logs in.
- [ ] Excel export with `rightToLeft: true` opens correctly in Arabic Excel and English Excel.

---

## Critical Gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Layout flips half-correctly — some elements still left-aligned | Hardcoded `ml-*` / `text-left` slipped past lint | Run the grep verification; convert to `ms-*` / `text-start`. |
| Arabic letters render separated, in visual order (e.g. `ا ب ج` instead of `ابج`) | PDF generator doesn't shape Arabic | Switch from raw `pdfkit` to `pdfkit-rtl`, or to `pdf-lib` with Arabic-shaping helper. |
| Arabic font shows as "Times New Roman" or boxes | Font not embedded in PDF | `doc.registerFont('Cairo', '...')` and `doc.font('Cairo')` before drawing Arabic. |
| Arabic UI mixes Latin and Arabic digits inconsistently | Some places use `Intl`, others use raw `.toString()` | Always use `Intl.NumberFormat(numberLocale, ...)`. Audit grep for `.toString()` and `String(` near numeric values. |
| New keys break Arabic build at runtime | `ar.json` missing keys; `react-i18next` falls back to English silently | The CI parity check catches this. Make it a required check. |
| Phone number reads `8901-234-567` instead of `567-234-8901` | Phone input inherits RTL from container | `<input type="tel" dir="ltr" />`. |
| `<bdi>` not respected in some browsers | Older Safari | Wrap in a span with `unicode-bidi: isolate; direction: ltr;` as fallback. |
| Translator sends back keys with broken `{{count}}` placeholders | Translators sometimes localize the placeholder name | Document that `{{count}}`, `{{name}}`, etc. must remain literal English; ideally use a translation platform that locks placeholders. |
| Arabic Excel headers show LTR despite `rightToLeft: true` | View applied per worksheet, not per column | Verify `worksheet.views = [{ rightToLeft: true }]` is set before adding rows. |
| Camera/scanner overlay text reads wrong direction | Component built with physical CSS | Same fix as the lint rule — convert to logical properties. |

---

## Tradeoffs This Skill Bakes In

- **English source of truth, Arabic catches up.** Developers move fast in English; translator catches up before each release. Alternative — translator working alongside development — slows everyone and produces stale Arabic. This skill optimizes for shipping.
- **Western digits in Arabic UI by default (`ar-EG-u-nu-latn`).** Matches modern Egyptian app convention. If the first customer wants Arabic-Indic digits, change one constant. Pre-asking "which digit system" delays shipping.
- **Lint-enforced over convention-enforced.** Code review catches missed strings inconsistently; ESLint catches them every time. The startup cost of writing the rules pays back in the first two screens.
- **Per-language admin content is out of scope.** A visitor type name is a single string. Multi-language admin content is a much bigger feature (localized name field, fallback rules, admin UX) — defer until a customer pays for it.
- **Bundled fonts, not Google CDN.** Loads slower on first paint, but works offline (PWA), respects user privacy, and survives Google CDN outages.

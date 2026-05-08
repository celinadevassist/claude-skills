---
name: "Setup Guide Page"
description: "Add an in-app /setup page with backend live-checks (DB, proxy, systemd, env vars, disk) and a frontend accordion of copy-able reference snippets (env template, systemd unit, proxy entry, deploy script, log paths). Use when onboarding a new admin to a NestJS+React monolith — they hit /setup and see exactly what's healthy and what's missing, with copy-paste fixes for everything."
---

# Setup Guide Page

## What This Skill Does

Two artifacts that together replace the "where are the docs?" question for any new admin or rehydrated server:

1. **`GET /api/setup`** — backend endpoint (admin-only) that runs **live system checks** and returns boolean+detail for each.
2. **`/setup` page** — frontend that renders those checks at the top (✅/❌ with diagnostic detail) and an Accordion below with **copy-able reference snippets** for every operational artifact (env vars, systemd unit, proxy entry, deploy script, smoke-test curls, log file map).

The page becomes the single source of truth for "how do I deploy / debug / rehydrate this app." Onboarding a new admin: send them the URL, done.

## When to Use

- Any internal tool that's deployed to your own infrastructure (NestJS+React monolith, with systemd / Docker / a reverse proxy).
- After completing initial deploy — capture the recipe while it's fresh.
- When onboarding a teammate to admin a project they didn't build.

## When NOT to Use

- SaaS products deployed to managed platforms (Vercel, Railway, Heroku) — those have their own setup wizards.
- Public-facing websites — there's no "admin" audience for this page.
- Single-developer prototypes where the dev = the deployer.

---

## Implementation

### Step 1: Backend — `src/setup/setup.service.ts`

```ts
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectModel, InjectConnection } from '@nestjs/mongoose';
import { execFile } from 'child_process';
import { promises as fs } from 'fs';
import { Connection, Model } from 'mongoose';
import { promisify } from 'util';
import { User, UserDocument } from '../auth/schemas/user.schema';

const execFileAsync = promisify(execFile);

const REQUIRED_ENV = [
  'NODE_ENV', 'PORT', 'MONGO_URI',
  'JWT_ACCESS_SECRET', 'JWT_REFRESH_SECRET',
  'FRONTEND_URL', 'ADMIN_EMAIL', 'ADMIN_PASSWORD',
];
const OPTIONAL_ENV: string[] = []; // project-specific extras

export interface CheckResult { ok: boolean; detail?: string; }
export interface SetupInfo {
  nodeVersion: string;
  pid: number;
  uptimeSeconds: number;
  port: number;
  mongo: CheckResult;
  envPresence: Record<string, boolean>;
  optionalEnvPresence: Record<string, boolean>;
  proxy: CheckResult;            // Caddyfile / nginx config
  systemdUnit: CheckResult;
  adminCount: CheckResult;
  logsDir: CheckResult;
}

@Injectable()
export class SetupService {
  constructor(
    private readonly config: ConfigService,
    @InjectModel(User.name) private readonly userModel: Model<UserDocument>,
    @InjectConnection() private readonly connection: Connection,
  ) {}

  async info(): Promise<SetupInfo> {
    const [mongo, proxy, systemdUnit, adminCount, logsDir] = await Promise.all([
      this.checkMongo(),
      this.checkProxy(),
      this.checkSystemd(),
      this.checkAdmins(),
      this.checkLogsDir(),
    ]);
    return {
      nodeVersion: process.version,
      pid: process.pid,
      uptimeSeconds: Math.round(process.uptime()),
      port: Number(this.config.get('PORT', 3000)),
      mongo, proxy, systemdUnit, adminCount, logsDir,
      envPresence: Object.fromEntries(REQUIRED_ENV.map(k => [k, !!process.env[k]])),
      optionalEnvPresence: Object.fromEntries(OPTIONAL_ENV.map(k => [k, !!process.env[k]])),
    };
  }

  private async checkMongo(): Promise<CheckResult> {
    const states: Record<number, string> = { 0: 'disconnected', 1: 'connected', 2: 'connecting', 3: 'disconnecting' };
    return { ok: this.connection.readyState === 1, detail: states[this.connection.readyState] };
  }

  private async checkProxy(): Promise<CheckResult> {
    // Adapt to your proxy. Example for Caddy:
    const path = process.env.CADDYFILE_PATH || '/etc/caddy/Caddyfile';
    try {
      const raw = await fs.readFile(path, 'utf-8');
      const hasOurApp = /YOUR-APP-NAME[\s.-].*\{/i.test(raw);
      const blocks = raw.split('\n').filter(l => /^[a-z0-9._-]+\s*\{/.test(l)).length;
      return { ok: hasOurApp, detail: hasOurApp ? `${blocks} domains; entry detected` : `Caddyfile read but no entry for this app` };
    } catch (err) {
      return { ok: false, detail: `Cannot read ${path}: ${(err as Error).message}` };
    }
  }

  private async checkSystemd(): Promise<CheckResult> {
    const unit = process.env.SYSTEMD_UNIT || 'YOUR-APP.service';
    try {
      const { stdout } = await execFileAsync('systemctl',
        ['show', unit, '--property=LoadState,ActiveState,UnitFileState'],
        { timeout: 3000 });
      const props: Record<string, string> = {};
      stdout.split('\n').forEach(l => { const i = l.indexOf('='); if (i > 0) props[l.slice(0, i)] = l.slice(i + 1); });
      const ok = props.LoadState === 'loaded' && props.ActiveState === 'active' && props.UnitFileState === 'enabled';
      return { ok, detail: `loaded=${props.LoadState} active=${props.ActiveState} unitFileState=${props.UnitFileState}` };
    } catch (err) {
      return { ok: false, detail: (err as Error).message };
    }
  }

  private async checkAdmins(): Promise<CheckResult> {
    const count = await this.userModel.countDocuments({ role: 'admin', active: true }).exec();
    return { ok: count > 0, detail: count === 0 ? 'No active admin — run `npm run seed:admin`' : `${count} active admin${count === 1 ? '' : 's'}` };
  }

  private async checkLogsDir(): Promise<CheckResult> {
    try {
      const stat = await fs.stat('logs');
      return { ok: stat.isDirectory(), detail: stat.isDirectory() ? 'logs/ exists' : 'logs/ exists but is not a directory' };
    } catch {
      return { ok: false, detail: 'logs/ directory does not exist' };
    }
  }
}
```

**Pattern:** every check returns `{ ok, detail }`. The detail is what makes the page useful when something's wrong — instead of just a red ❌, you see "Cannot read /etc/caddy/Caddyfile: ENOENT".

### Step 2: Backend — `src/setup/setup.controller.ts` + module

```ts
@Controller('setup')
@UseGuards(JwtAuthGuard, RolesGuard)
@Roles('admin')
export class SetupController {
  constructor(private readonly setup: SetupService) {}
  @Get() info() { return this.setup.info(); }
}
```

```ts
@Module({
  imports: [MongooseModule.forFeature([{ name: User.name, schema: UserSchema }])],
  controllers: [SetupController],
  providers: [SetupService],
})
export class SetupModule {}
```

Then add `SetupModule` to `app.module.ts`.

### Step 3: Frontend — typed API client

```ts
// src/services/api/setup.ts
import api from './base';
export interface CheckResult { ok: boolean; detail?: string; }
export interface SetupInfo { /* same shape as backend */ }
export const setupApi = {
  info: () => api.get<SetupInfo>('/api/setup').then(r => r.data),
};
```

### Step 4: Frontend — `/setup` page

Top: live-checks card. Below: accordion of copy-able snippets.

```tsx
// src/pages/Setup.tsx
import { Accordion, Badge, Button, Card, Code, CopyButton, Group, Loader,
  ScrollArea, Stack, Text, Title } from '@mantine/core';
import { IconCheck, IconCircleCheck, IconCircleX, IconCopy, IconRefresh,
  IconX } from '@tabler/icons-react';

export function SetupPage() {
  const [info, setInfo] = useState<SetupInfo | null>(null);
  /* useEffect to load info, refresh button */

  return (
    <Stack gap="md" maw={1100}>
      <Group justify="space-between" align="flex-end">
        <Stack gap={2}>
          <Title order={2}>Setup Guide</Title>
          <Text c="dimmed" size="sm">Everything a new admin needs to deploy or rehydrate.</Text>
        </Stack>
        <Button variant="light" leftSection={<IconRefresh size={16} />} onClick={load}>
          Refresh checks
        </Button>
      </Group>

      <Card withBorder radius="md" p="md">
        <Group justify="space-between" mb="sm">
          <Text fw={700}>Live system checks</Text>
          <Group gap="xs">
            <Badge size="xs" variant="light" color="gray">Node {info.nodeVersion}</Badge>
            <Badge size="xs" variant="light" color="gray">PID {info.pid}</Badge>
            <Badge size="xs" variant="light" color="gray">up {Math.floor(info.uptimeSeconds/60)}m</Badge>
          </Group>
        </Group>
        <Stack gap={6}>
          <Check title="MongoDB connection" result={info.mongo} />
          <Check title="Reverse proxy" result={info.proxy} />
          <Check title="systemd unit" result={info.systemdUnit} />
          <Check title="Active admin account" result={info.adminCount} />
          <Check title="logs/ directory" result={info.logsDir} />
          <EnvCheck label="Required env vars" presence={info.envPresence} />
        </Stack>
      </Card>

      <Accordion variant="contained" multiple>
        <Accordion.Item value="env">
          <Accordion.Control><Text fw={600}>1. Environment variables</Text></Accordion.Control>
          <Accordion.Panel><Snippet content={ENV_TEMPLATE} filename=".env" /></Accordion.Panel>
        </Accordion.Item>
        {/* repeat per section: seed admin, systemd unit, proxy entry, deploy script, health curls, log paths */}
      </Accordion>
    </Stack>
  );
}

function Check({ title, result }: { title: string; result: CheckResult }) {
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      {result.ok
        ? <IconCircleCheck size={18} color="var(--mantine-color-green-light-color)" />
        : <IconCircleX size={18} color="var(--mantine-color-red-light-color)" />}
      <Stack gap={0}>
        <Text size="sm" fw={500}>{title}</Text>
        {result.detail && <Text size="xs" c={result.ok ? 'dimmed' : 'red'}>{result.detail}</Text>}
      </Stack>
    </Group>
  );
}

function Snippet({ content, filename }: { content: string; filename?: string }) {
  return (
    <Card withBorder p="sm" radius="md" bg="var(--mantine-color-default)">
      <Group justify="space-between" mb={6}>
        {filename && <Text size="xs" c="dimmed" ff="monospace">{filename}</Text>}
        <CopyButton value={content}>
          {({ copied, copy }) => (
            <Button size="compact-xs" variant="subtle" onClick={copy}
              leftSection={copied ? <IconCheck size={12} /> : <IconCopy size={12} />} ml="auto">
              {copied ? 'Copied' : 'Copy'}
            </Button>
          )}
        </CopyButton>
      </Group>
      <ScrollArea>
        <Code block style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {content}
        </Code>
      </ScrollArea>
    </Card>
  );
}
```

**Theme note:** Icon colors use `green-light-color` / `red-light-color` (auto-flip). Snippet bg uses `var(--mantine-color-default)`. See `mantine-theme-discipline`.

---

## The 7 Reference Sections (template)

These are the headings to put inside the Accordion. Each one has 1–2 copy-able snippets. Adjust per stack.

1. **Environment variables** — full `.env` template with `<openssl rand -hex 64>` placeholders for secrets and a comment explaining each var.
2. **Seed the initial admin** — `cd backend && npm install && npm run seed:admin`.
3. **systemd unit** — full unit file + the install commands (`sudo cp ... && sudo systemctl daemon-reload && sudo systemctl enable --now`).
4. **Reverse proxy entries** — prod + dev domain snippets + `caddy reload` (or `nginx -s reload`).
5. **Deploy script** — `bash scripts/deploy.sh` with a one-liner explaining what it does.
6. **Health check + smoke test** — curl /health, curl /api/auth/login, curl public URL.
7. **Where the logs live** — table of paths: application.log, error.log, debug.log, audit-log file, systemd journal, mongo collections.

---

## Verification Checklist

- [ ] Visit `/setup` as admin, see all checks ✅ green.
- [ ] Visit as a `member` → 403 Forbidden (admin-only).
- [ ] Stop MongoDB, refresh `/setup`, see ❌ on the Mongo check with detail "disconnected".
- [ ] Disable systemd unit, refresh, see ❌ on systemd check.
- [ ] Copy buttons on every snippet actually copy to clipboard.
- [ ] Page works in dark mode (icons readable, snippet cards have correct contrast).

---

## Tradeoffs

- **Static snippets, not dynamic.** The reference snippets are hardcoded strings in `Setup.tsx`. They're maintained alongside the code. If the systemd unit changes, you update the snippet too. Tradeoff: simple. Alternative: serve snippets from the backend so they always match files on disk — overkill for most projects.
- **Admin-only.** Members can't see the setup info. Reasonable — the snippets contain server paths, env names, and operational secrets-in-template. If you want a public health page, add a separate `/status` route.
- **Live checks but no fix-it actions.** The page tells you what's broken; it doesn't restart services for you. That's the curated-commands skill's job — pair them.

---
name: "Audit Log"
description: "Add an append-only audit trail to a NestJS+Mongo project: every mutation, action, command, or login attributed by user, with payload redaction for secrets. Includes an admin-only filterable UI with pagination and a drawer for full payload inspection. Use when an internal tool has admins making changes that need to be traceable."
---

# Audit Log

## What This Skill Does

Adds two things to a NestJS + React + Mongoose stack:

1. **Backend `AuditService`** — a global, fire-and-forget logger that writes to an append-only `audit_logs` Mongo collection. Sensitive keys (`password`, `token`, `secret`, etc.) are auto-redacted from payloads. Admin-only `GET /api/audit` lists entries with filters (action name, search, date range, user) and pagination.

2. **Frontend `/audit` page** (admin only) — table view with filter dropdown, search, pagination, and a side drawer showing the full payload JSON for any entry.

Combined, they make every meaningful action attributable to a user with a timestamp + IP + payload snapshot, queryable from the UI.

## When to Use

- Any internal tool where admins create/modify/delete things and you need a "who did this?" trail.
- Compliance-adjacent projects (anything with PII, payments, customer data).
- Apps with a Commands or Terminal feature — pair this skill with those for full attribution.
- Debugging "why did X change?" — without an audit log you're stuck reading git history of database state.

## When NOT to Use

- Read-only / static sites.
- Single-user apps where attribution is meaningless.
- Stateless services with no concept of mutating actions.

---

## The Service Pattern

The audit service is **global** (`@Global()` module) and **fire-and-forget**: callers don't await, errors are swallowed (logged as warnings), so audit failures never break user-facing requests.

```ts
// Anywhere a controller has access to the service:
this.audit.log({
  userId: actor.sub,
  userEmail: actor.email,
  userRole: actor.role,
  action: 'user.create',
  target: createdEmail,
  ip: clientIp(req),
  status: 200,
  payload: { role: dto.role, displayName: dto.displayName },
});
// returns void; never throws
```

**Action naming convention:** `domain.verb` — `user.create`, `prd.update`, `command.run`, `terminal.connect`, `auth.login`. This makes the action filter dropdown self-organizing.

---

## Implementation

### Step 1: Schema — `src/audit/schemas/audit-log.schema.ts`

```ts
import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document, Types } from 'mongoose';

@Schema({ timestamps: { createdAt: 'ts', updatedAt: false }, collection: 'audit_logs' })
export class AuditLog extends Document {
  @Prop({ type: Types.ObjectId, ref: 'User', index: true })
  userId?: Types.ObjectId;

  @Prop() userEmail?: string;
  @Prop() userRole?: string;

  @Prop({ required: true, index: true })
  action!: string;

  @Prop() target?: string;
  @Prop() ip?: string;
  @Prop() userAgent?: string;
  @Prop({ type: Number }) status?: number;
  @Prop({ type: Object }) payload?: Record<string, unknown>;
  @Prop({ type: String }) error?: string;

  @Prop({ type: Date, default: Date.now, index: true })
  ts!: Date;
}

export const AuditLogSchema = SchemaFactory.createForClass(AuditLog);
AuditLogSchema.index({ ts: -1 });
AuditLogSchema.index({ userId: 1, ts: -1 });
```

**Indexes matter.** `ts: -1` for the default "newest first" sort, `userId+ts` for "all entries by user X". Without these, the audit page gets slow as soon as you have thousands of entries.

### Step 2: Service — `src/audit/audit.service.ts`

```ts
import { Injectable, Logger } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { FilterQuery, Model, Types } from 'mongoose';
import { AuditLog } from './schemas/audit-log.schema';

const SENSITIVE_KEYS = new Set([
  'password', 'passwordhash', 'refreshtoken', 'accesstoken',
  'jwtsecret', 'secret', 'authorization',
]);

export interface AuditEntry {
  userId?: string; userEmail?: string; userRole?: string;
  action: string; target?: string; ip?: string; userAgent?: string;
  status?: number; payload?: Record<string, unknown>; error?: string;
}

@Injectable()
export class AuditService {
  private readonly logger = new Logger(AuditService.name);
  constructor(@InjectModel(AuditLog.name) private readonly model: Model<AuditLog>) {}

  /** Fire-and-forget. Never throws into the caller. */
  log(entry: AuditEntry): void {
    void this.model
      .create({
        userId: entry.userId ? new Types.ObjectId(entry.userId) : undefined,
        userEmail: entry.userEmail,
        userRole: entry.userRole,
        action: entry.action,
        target: entry.target,
        ip: entry.ip,
        userAgent: entry.userAgent?.slice(0, 200),
        status: entry.status,
        payload: redactPayload(entry.payload),
        error: entry.error?.slice(0, 1000),
      })
      .catch(err =>
        this.logger.warn(`Audit log write failed: ${(err as Error).message}`),
      );
  }

  async list(query: { userId?: string; action?: string; from?: Date; to?: Date; search?: string; limit?: number; skip?: number }) {
    const filter: FilterQuery<AuditLog> = {};
    if (query.userId && Types.ObjectId.isValid(query.userId)) filter.userId = new Types.ObjectId(query.userId);
    if (query.action) filter.action = query.action;
    if (query.from || query.to) {
      filter.ts = {};
      if (query.from) (filter.ts as { $gte?: Date }).$gte = query.from;
      if (query.to) (filter.ts as { $lte?: Date }).$lte = query.to;
    }
    if (query.search) {
      const re = new RegExp(escapeRegex(query.search), 'i');
      filter.$or = [{ action: re }, { target: re }, { userEmail: re }, { error: re }];
    }
    const limit = Math.min(Math.max(query.limit ?? 100, 1), 500);
    const skip = Math.max(query.skip ?? 0, 0);
    const [items, total] = await Promise.all([
      this.model.find(filter).sort({ ts: -1 }).skip(skip).limit(limit).lean().exec(),
      this.model.countDocuments(filter).exec(),
    ]);
    return { items, total, limit, skip };
  }

  async distinctActions(): Promise<string[]> {
    return ((await this.model.distinct('action').exec()) as string[]).sort();
  }
}

function redactPayload(p?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!p || typeof p !== 'object') return p;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(p)) {
    if (SENSITIVE_KEYS.has(k.toLowerCase())) out[k] = '[redacted]';
    else if (v && typeof v === 'object' && !Array.isArray(v))
      out[k] = redactPayload(v as Record<string, unknown>);
    else out[k] = v;
  }
  return out;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
```

**Why fire-and-forget:** if Mongo is briefly down or the audit collection has an issue, the user-facing request still succeeds. The audit miss is logged to console as a warning. This is a deliberate tradeoff — if your compliance regime requires *guaranteed* audit, switch to `await` and wrap callers in try/catch.

### Step 3: Controller — `src/audit/audit.controller.ts`

```ts
@Controller('audit')
@UseGuards(JwtAuthGuard, RolesGuard)
@Roles('admin')
export class AuditController {
  constructor(private readonly audit: AuditService) {}

  @Get()
  list(
    @Query('userId') userId?: string,
    @Query('action') action?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('search') search?: string,
    @Query('limit') limit?: string,
    @Query('skip') skip?: string,
  ) {
    return this.audit.list({
      userId, action, search,
      from: from ? new Date(from) : undefined,
      to: to ? new Date(to) : undefined,
      limit: limit ? Number(limit) : undefined,
      skip: skip ? Number(skip) : undefined,
    });
  }

  @Get('actions')
  actions() { return this.audit.distinctActions(); }
}
```

### Step 4: Module — `src/audit/audit.module.ts`

```ts
import { Global, Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { AuditController } from './audit.controller';
import { AuditService } from './audit.service';
import { AuditLog, AuditLogSchema } from './schemas/audit-log.schema';

@Global()
@Module({
  imports: [MongooseModule.forFeature([{ name: AuditLog.name, schema: AuditLogSchema }])],
  controllers: [AuditController],
  providers: [AuditService],
  exports: [AuditService],
})
export class AuditModule {}
```

`@Global()` means any other module can inject `AuditService` without re-importing. Critical — every controller that mutates state will use it.

### Step 5: Wire into app.module.ts

```ts
@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    MongooseModule.forRoot(/*...*/),
    AuditModule,                    // ← add
    // ... your domain modules
  ],
})
export class AppModule {}
```

### Step 6: Calling it from your controllers

Pattern: controllers know request context (user + IP), services don't. So services do their work, controllers call audit.

```ts
@Controller('users')
@UseGuards(JwtAuthGuard)
export class UsersController {
  constructor(
    private readonly users: UsersService,
    private readonly audit: AuditService,
  ) {}

  @Post()
  @UseGuards(RolesGuard) @Roles('admin')
  async create(@Body() dto: CreateUserDto, @CurrentUser() user: JwtPayload, @Req() req: Request) {
    const created = await this.users.create(dto);
    this.audit.log({
      userId: user.sub, userEmail: user.email, userRole: user.role,
      action: 'user.create',
      target: created.email,
      ip: clientIp(req),
      payload: { role: dto.role, displayName: dto.displayName },
      // password is auto-redacted by SENSITIVE_KEYS
    });
    return created;
  }
}
```

**Helper:**
```ts
function clientIp(req: Request): string | undefined {
  const fwd = req.headers['x-forwarded-for'];
  if (typeof fwd === 'string') return fwd.split(',')[0].trim();
  if (Array.isArray(fwd)) return fwd[0];
  return req.socket.remoteAddress ?? undefined;
}
```

---

## Frontend

### API client — `src/services/api/audit.ts`

```ts
export interface AuditEntry { _id: string; userEmail?: string; userRole?: string; action: string; target?: string; ip?: string; status?: number; payload?: Record<string, unknown>; error?: string; ts: string; }
export interface AuditPage { items: AuditEntry[]; total: number; limit: number; skip: number; }
export const auditApi = {
  list: (q: AuditQuery = {}) => api.get<AuditPage>('/api/audit', { params: q }).then(r => r.data),
  actions: () => api.get<string[]>('/api/audit/actions').then(r => r.data),
};
```

### Page — `/audit` (admin only)

Three pieces: filter row (search + action select + refresh), paginated table, side drawer with payload JSON.

Theme tokens for status badges:
- 2xx → `green` light variant
- 4xx → `yellow`
- 5xx → `red`
- Action prefix → color (e.g. `user.*` violet, `auth.*` orange, `terminal.*` red)

Use `var(--mantine-color-X-light-color)` for icons (auto-flips per `mantine-theme-discipline`).

---

## Verification Checklist

- [ ] After creating a user, an `audit_logs` entry appears within 100ms.
- [ ] Body containing `password: 'foo'` shows `password: '[redacted]'` in the payload column.
- [ ] Filter dropdown lists every distinct action used.
- [ ] Pagination works past 50/100/200 entries.
- [ ] Member account hitting `/audit` gets 403.
- [ ] Stopping Mongo briefly does NOT 500 the user-facing requests (audit silently drops).
- [ ] `audit_logs` collection has indexes on `ts`, `userId+ts`, and `action`.

---

## Pairs Well With

- **Curated commands** — every `command.run` writes an audit entry with exit code + duration.
- **Browser SSH terminal** — `terminal.connect` / `terminal.disconnect` with session metadata; per-keystroke output goes to a separate file (too noisy for Mongo).
- **Users admin page** — every user CRUD writes a `user.create` / `user.update` / `user.deactivate` entry with the diff.
- **JWT auth** — `auth.login` / `auth.refresh` / `auth.logout` (redact the refresh token).

---

## Tradeoffs

- **Fire-and-forget over guaranteed.** Silent failures are tolerable for ops audit, not for compliance-grade audit. Switch to `await` if you need it.
- **Mongo, not append-only file.** Mongo gives you query/filter/index for free. Tradeoff: a malicious admin with DB access could delete entries. Mitigate with per-collection access rules + offsite log shipping if required.
- **Redaction by key name only.** `password` is caught; "creditcard" buried in nested data isn't. Add to `SENSITIVE_KEYS` per project. Don't try to detect by value heuristics — too noisy.
- **No retention policy.** Entries accumulate forever. Add a cron later if cardinality becomes a problem (10M+ entries; for most internal tools, never).

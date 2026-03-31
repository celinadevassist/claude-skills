---
name: "NestJS Throttle Guard"
description: "Set up production-ready rate limiting for NestJS monolith projects (ServeStaticModule + API). Prevents 429 errors on page refresh while still protecting auth endpoints. Use when adding rate limiting, fixing throttle-related 429 errors, or setting up a new NestJS project with both static serving and API routes."
---

# NestJS Throttle Guard

## What This Skill Does

Sets up a custom `ThrottlerGuard` for NestJS monolith apps that serve both a frontend SPA (via `ServeStaticModule`) and API routes. Solves common 429 errors caused by incorrect throttle scope.

## When to Use

- Setting up rate limiting on a new NestJS project
- Getting 429 errors on page refresh or navigation
- Monolith apps where backend serves frontend static files
- Projects behind a reverse proxy (Caddy, nginx)

## Prerequisites

- NestJS backend with `@nestjs/throttler` installed
- `ServeStaticModule` serving frontend from `public/` folder
- API routes prefixed with `/api`

---

## Common Pitfalls (Why This Skill Exists)

### Pitfall 1: Static assets get throttled

When `ThrottlerGuard` is registered as `APP_GUARD`, it applies to ALL requests — including static file requests for JS, CSS, images, fonts. A single page refresh can fire 20-40 static asset requests simultaneously, easily exceeding even generous rate limits.

**Fix:** Skip throttling for non-`/api` routes.

### Pitfall 2: `req.user` is undefined in the throttler

Global guards (`APP_GUARD`) execute BEFORE controller-level guards. If your auth guard (`JwtOrApiKeyGuard`, `AuthGuard('jwt')`) is applied at the controller level, `req.user` is **not populated** when the throttler runs. Checking `req.user` will always be falsy, causing every authenticated request to be throttled.

**Fix:** Check the `Authorization: Bearer` header directly from `req.headers` instead of `req.user`.

### Pitfall 3: Proxy IP tracking

Behind Caddy/nginx, `req.ip` is always `127.0.0.1`. All users share one throttle bucket and hit limits instantly.

**Fix:** Extract real IP from `x-forwarded-for` or `x-real-ip` headers.

---

## Implementation

### Step 1: Install throttler

```bash
npm install @nestjs/throttler
```

### Step 2: Create the guard

Copy template from `resources/templates/custom-throttler.guard.ts` to `src/guards/throttle.guard.ts`.

The guard has three skip conditions:
1. **Non-API requests** — static assets bypass throttling entirely
2. **Bearer token present** — authenticated frontend users bypass throttling (checked via header, not `req.user`)
3. **Everything else** — unauthenticated and API key requests are throttled (brute-force protection)

### Step 3: Configure ThrottlerModule in app.module.ts

```typescript
import { ThrottlerModule } from '@nestjs/throttler';
import { APP_GUARD } from '@nestjs/core';
import { CustomThrottlerGuard } from './guards/throttle.guard';

@Module({
  imports: [
    ThrottlerModule.forRoot([
      {
        name: 'short',
        ttl: 1000,     // 1 second
        limit: 30,     // 30 req/sec — handles page refresh burst
      },
      {
        name: 'medium',
        ttl: 60000,    // 1 minute
        limit: 300,    // 300 req/min
      },
      {
        name: 'long',
        ttl: 3600000,  // 1 hour
        limit: 5000,   // 5000 req/hour
      },
    ]),
    // ... other modules
  ],
  providers: [
    {
      provide: APP_GUARD,
      useClass: CustomThrottlerGuard,
    },
  ],
})
export class AppModule {}
```

### Step 4: Per-endpoint overrides for sensitive routes

Auth endpoints should have stricter limits:

```typescript
import { Throttle } from '@nestjs/throttler';
import { CustomThrottlerGuard } from '../guards/throttle.guard';

@Controller('auth')
@UseGuards(CustomThrottlerGuard)
export class AuthController {
  @Post('signin')
  @Throttle({ default: { ttl: 60000, limit: 5 } })   // 5 req/min
  async signin() { ... }

  @Post('signup')
  @Throttle({ default: { ttl: 3600000, limit: 3 } })  // 3 req/hour
  async signup() { ... }

  @Post('forgot-password')
  @Throttle({ default: { ttl: 3600000, limit: 3 } })  // 3 req/hour
  async forgotPassword() { ... }
}
```

### Step 5: Public endpoints (no auth)

For public endpoints that accept user input (reviews, contact forms):

```typescript
@UseGuards(CustomThrottlerGuard)
@Throttle({ default: { limit: 5, ttl: 60000 } })  // 5 req/min
@Post('submit')
async submitReview() { ... }
```

---

## Verification

After setup, verify with:

```bash
# Should NOT return 429 (static assets skip throttling)
curl -s -o /dev/null -w "%{http_code}" https://your-app.example.com/

# Should NOT return 429 with valid JWT (authenticated skip)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer YOUR_JWT" https://your-app.example.com/api/en/orders

# Should return 429 after exceeding limit (unauthenticated)
for i in $(seq 1 35); do curl -s -o /dev/null -w "%{http_code}\n" https://your-app.example.com/api/en/public-endpoint; done
```

## Guard Execution Order Reference

```
Request → Global Guards (APP_GUARD) → Controller Guards → Route Guards → Handler
              ↑                            ↑
    CustomThrottlerGuard          JwtOrApiKeyGuard
    (req.user = undefined!)       (populates req.user)
```

This is why the throttler MUST check headers, not `req.user`.

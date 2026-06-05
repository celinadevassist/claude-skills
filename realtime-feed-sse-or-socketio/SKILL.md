---
name: "Realtime Feed (SSE or Socket.IO)"
description: "Add real-time server→client (and optionally bidirectional) push to a NestJS + React monolith. Replaces 'click Refresh' with a live LIVE-chip ticker — events, log tails, presence, notifications, anything. Use when adding a live feed of any kind: events streams, build/deploy log tails, persona-online indicators, collaborative cursors, dashboard tickers, or any time a Refresh button is a smell. Includes a decision tree for SSE vs Socket.IO so you pick the right transport — defaults to SSE."
---

# Realtime Feed (SSE or Socket.IO)

## What This Skill Does

Wires real-time server→client push into a NestJS + React monolith end-to-end. Two transports covered, with a decision tree so you pick the right one:

- **SSE** — strictly one-way push of structured JSON. Zero new dependencies. Auto-reconnect. ~80% of "live feed" UIs are this.
- **Socket.IO** — bidirectional, native rooms, polling fallback. Use when SSE genuinely isn't enough.

The skill produces:
- A `StreamService` (RxJS Subject bus) on the backend
- A `@Sse()` endpoint (or `@WebSocketGateway`) with JWT auth + tenancy filtering
- A small JWT-strategy patch so `EventSource` can authenticate (no Authorization header support in the browser API)
- A React `useEffect` hook that opens the stream, dedupes, caps memory, and surfaces a `● LIVE` chip in the panel header

Field-tested in production on the Pulsar project (`feat(analytics): live event ticker via SSE`).

## Prerequisites

- NestJS + React monolith (the [monolith-setup](../monolith-setup/SKILL.md) shape)
- JWT auth ([jwt-auth-admin-seeded](../jwt-auth-admin-seeded/SKILL.md))
- A reverse proxy that allows long-lived HTTP connections (Caddy default = fine; Nginx needs `proxy_read_timeout`; Cloudflare needs WebSockets enabled in the zone for Socket.IO)

---

## Decision Tree (read this first)

```
Does the feature need messages from CLIENT to SERVER too?
       (e.g. chat, collaborative editing, "join this room", typing indicators)
                       │
        ┌──────────────┴──────────────┐
       no                             yes
        │                              │
        ▼                              ▼
   Use SSE              Are explicit room semantics required server-side?
   (this skill,            (e.g. broadcast.to('order-42').emit(...))
    Part A)                     │
                  ┌─────────────┴─────────────┐
                 no                           yes
                  │                            │
                  ▼                            ▼
            Use SSE                   Use Socket.IO
            (still simpler)           (this skill, Part B)
```

### Why default to SSE

| | SSE | Socket.IO |
|---|---|---|
| New backend deps | 0 (`@Sse()` is built into NestJS) | 3 (`@nestjs/websockets`, `@nestjs/platform-socket.io`, `socket.io`) |
| New frontend deps | 0 (`EventSource` is browser-native) | 1 (`socket.io-client`) |
| Auto-reconnect | built into EventSource | built into client lib |
| Debugging | one hanging GET visible in DevTools Network tab | needs Socket.IO inspector |
| Reverse-proxy config | none — just long-lived HTTP | websocket upgrade headers, sometimes a 504 timeout bump |
| Bidirectional | ❌ one-way (filter server-side) | ✅ |
| Native rooms / broadcast | ❌ (use RxJS pipe filters) | ✅ |
| Transport fallback | N/A (HTTP) | polling fallback for restrictive networks |

**Rule of thumb**: default to SSE. Reach for Socket.IO only when you actually need bidirectionality or rooms — *not* "in case we need them later." Migrating SSE→Socket.IO later is mechanical (the StreamService Subject stays; only the controller adapter changes).

---

## Part A: SSE Path (the default)

### Step 1 — Stream Service (the bus)

Create `backend/src/<module>/<entity>-stream.service.ts`:

```typescript
import { Injectable } from '@nestjs/common';
import { Subject, Observable, filter, map } from 'rxjs';

/**
 * In-process event bus. Multiple subscribers (different operator
 * browser tabs on the same tenant) all fan out from one Subject.
 * Payload mirrors what the REST list endpoint returns so the
 * frontend can prepend straight into state — no round-trip refetch.
 */
export interface StreamedEvent {
  id: string;
  tenantId: string;       // accountId / pixelId / userId — your tenancy key
  // ... the rest of the row shape the frontend already knows
  createdAt: Date;
}

@Injectable()
export class EntityStreamService {
  private readonly subject = new Subject<StreamedEvent>();

  publish(ev: StreamedEvent): void {
    this.subject.next(ev);
  }

  /** Filter server-side so the SSE wire only carries authorized rows. */
  streamFor(tenantId: string): Observable<StreamedEvent> {
    return this.subject.asObservable().pipe(
      filter((ev) => ev.tenantId === tenantId),
      // Re-map into a plain object so RxJS doesn't accidentally pass
      // a hydrated Mongoose doc through to the SSE serializer.
      map((ev) => ({ ...ev })),
    );
  }
}
```

Register in the module's `providers` and `exports`:

```typescript
@Module({
  providers: [..., EntityStreamService],
  exports: [..., EntityStreamService],
})
```

### Step 2 — Publish on persist

Wherever you create the entity, inject the stream service and call `publish(...)` after the write:

```typescript
const doc = await this.model.create(data);

// Fan out to SSE subscribers. Wrapped in try/catch so a publish
// failure CANNOT poison the write path — the row is already saved.
try {
  this.stream.publish({
    id: String(doc._id),
    tenantId: data.tenantId,
    // ...same shape your REST list endpoint returns
    createdAt: doc.createdAt ?? new Date(),
  });
} catch (err) {
  this.logger.warn(`stream publish failed: ${String(err)}`);
}
```

### Step 3 — JWT strategy: accept `?token=` for SSE auth

Browser `EventSource` **cannot** set the `Authorization` header (HTML spec limitation). Add a query-param fallback to your JWT strategy:

```typescript
// backend/src/auth/jwt.strategy.ts
import { ExtractJwt, Strategy } from 'passport-jwt';

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(config: ConfigService) {
    super({
      jwtFromRequest: ExtractJwt.fromExtractors([
        ExtractJwt.fromAuthHeaderAsBearerToken(),          // every existing API call
        ExtractJwt.fromUrlQueryParameter('token'),         // SSE-only fallback
      ]),
      secretOrKey: config.getOrThrow<string>('JWT_ACCESS_SECRET'),
      ignoreExpiration: false,
    });
  }
  // ...validate unchanged
}
```

Existing bearer-header callers keep working unchanged. The query-param path only matters for `@Sse()` endpoints because no other route uses `?token=`.

### Step 4 — Controller `@Sse()` endpoint

```typescript
import { Sse, UseGuards, Param, NotFoundException } from '@nestjs/common';
import { Observable, from, merge, interval, map } from 'rxjs';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import { CurrentTenantId } from '../common/tenant/current-tenant.decorator';
import { EntityStreamService } from './entity-stream.service';

@Sse('entities/:id/stream')
@UseGuards(JwtAuthGuard)
async streamEntity(
  @CurrentTenantId() tenantId: string,
  @Param('id') entityId: string,
): Promise<Observable<{ data: string }>> {
  // Verify ownership BEFORE opening the stream — otherwise an
  // authenticated user could subscribe to another tenant's stream.
  const owned = await this.entityModel
    .exists({ _id: entityId, tenantId })
    .exec();
  if (!owned) throw new NotFoundException('Entity not found');

  const live$ = this.stream.streamFor(tenantId).pipe(
    map((ev) => ({ data: JSON.stringify(ev) })),
  );
  // Heartbeat every 25s — keeps Caddy/Nginx/Cloudflare from killing
  // the idle connection. Critical, not optional.
  const heartbeat$ = interval(25_000).pipe(
    map(() => ({ data: JSON.stringify({ heartbeat: Date.now() }) })),
  );
  // Hello frame so the client knows the connection is live before
  // any real event lands.
  const hello$ = from([{ data: JSON.stringify({ hello: true, entityId }) }]);

  return merge(hello$, live$, heartbeat$);
}
```

### Step 5 — Frontend `useEffect`

```tsx
import { useEffect, useState } from 'react';
import { getAccessToken } from '../services/api/base';

const [events, setEvents] = useState<Row[]>([]);
const [streamConnected, setStreamConnected] = useState(false);
const [lastStreamedAt, setLastStreamedAt] = useState<number | null>(null);

useEffect(() => {
  if (!selectedEntity) return;
  const token = getAccessToken();
  if (!token) return;
  const url = `/api/entities/${selectedEntity.id}/stream?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  es.onopen = () => setStreamConnected(true);
  es.onerror = () => setStreamConnected(false);
  es.onmessage = (msg) => {
    try {
      const parsed = JSON.parse(msg.data) as Row & { heartbeat?: number; hello?: boolean };
      if (parsed.heartbeat || parsed.hello) return;
      setLastStreamedAt(Date.now());
      setEvents((prev) => {
        // Dedup by stable id — initial REST fetch + first stream
        // pushes can overlap and we don't want doubles.
        if (parsed.id && prev.some((e) => e.id === parsed.id)) return prev;
        const next = [parsed, ...prev];
        // Cap memory growth on long-lived dashboards.
        return next.length > 200 ? next.slice(0, 200) : next;
      });
    } catch { /* malformed frame — skip */ }
  };
  return () => { es.close(); setStreamConnected(false); };
}, [selectedEntity]);
```

### Step 6 — UI: LIVE chip + freshness counter

```tsx
<span style={{
  display: 'inline-flex', alignItems: 'center', gap: 6,
  fontFamily: 'monospace', fontSize: 10, fontWeight: 600,
  letterSpacing: '0.08em', textTransform: 'uppercase',
  color: streamConnected ? 'var(--signal-2)' : 'var(--text-4)',
}}>
  <span style={{
    width: 6, height: 6, borderRadius: '50%',
    background: streamConnected ? 'var(--signal)' : 'var(--text-4)',
    animation: streamConnected ? 'pulse 1.6s ease-in-out infinite' : 'none',
  }} />
  {streamConnected ? 'LIVE' : 'OFFLINE'}
</span>
```

Panel subtitle as freshness check:

```tsx
subtitle={
  streamConnected
    ? lastStreamedAt
      ? `Live · last event ${Math.round((Date.now() - lastStreamedAt) / 1000)}s ago`
      : 'Live · waiting for first event'
    : 'Last 100 events · click any row to expand full payload'
}
```

---

## Part B: Socket.IO Path (when SSE isn't enough)

### Step 1 — Install

```bash
cd backend && npm i @nestjs/websockets @nestjs/platform-socket.io socket.io
cd ../frontend && npm i socket.io-client
```

### Step 2 — Bootstrap the platform adapter

```typescript
// backend/src/main.ts
import { IoAdapter } from '@nestjs/platform-socket.io';
// ...
app.useWebSocketAdapter(new IoAdapter(app));
```

### Step 3 — Gateway with JWT-on-handshake auth

```typescript
import {
  WebSocketGateway, WebSocketServer,
  OnGatewayConnection, OnGatewayDisconnect, SubscribeMessage, MessageBody,
} from '@nestjs/websockets';
import { Server, Socket } from 'socket.io';
import { Injectable, Logger } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';

@Injectable()
@WebSocketGateway({ cors: { origin: true, credentials: true } })
export class EntityGateway implements OnGatewayConnection, OnGatewayDisconnect {
  @WebSocketServer() server!: Server;
  private readonly logger = new Logger(EntityGateway.name);

  constructor(private readonly jwt: JwtService) {}

  async handleConnection(client: Socket) {
    try {
      const token = (client.handshake.auth?.token as string) ||
                    (client.handshake.query?.token as string);
      const payload = await this.jwt.verifyAsync(token);
      client.data.tenantId = payload.accountId; // attach for later checks
    } catch {
      client.disconnect(true); // bad token → close immediately
    }
  }

  handleDisconnect(client: Socket) {
    this.logger.debug(`disconnect ${client.id}`);
  }

  @SubscribeMessage('subscribe-entity')
  async onSubscribe(client: Socket, @MessageBody() entityId: string) {
    const tenantId = client.data.tenantId;
    // Verify the entity belongs to this tenant before joining the room
    const owned = await this.entityModel.exists({ _id: entityId, tenantId });
    if (!owned) return { error: 'not found' };
    client.join(`entity:${entityId}`);
    return { joined: true };
  }

  /** Called from the service after persist. */
  emitEvent(entityId: string, payload: unknown) {
    this.server.to(`entity:${entityId}`).emit('event', payload);
  }
}
```

### Step 4 — Frontend client

```tsx
import { io, Socket } from 'socket.io-client';
import { getAccessToken } from '../services/api/base';

useEffect(() => {
  if (!selectedEntity) return;
  const socket: Socket = io('/', { auth: { token: getAccessToken() } });
  socket.on('connect', () => {
    socket.emit('subscribe-entity', selectedEntity.id, (ack) => {
      if (ack?.joined) setStreamConnected(true);
    });
  });
  socket.on('event', (payload: Row) => {
    setLastStreamedAt(Date.now());
    setEvents((prev) => prev.some((e) => e.id === payload.id) ? prev : [payload, ...prev].slice(0, 200));
  });
  socket.on('disconnect', () => setStreamConnected(false));
  return () => { socket.disconnect(); };
}, [selectedEntity]);
```

### Step 5 — Reverse-proxy upgrade headers

**Caddy** — works natively, no config change needed.

**Nginx** — add to the location block:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400s;
```

**Cloudflare** — toggle *Network → WebSockets → On* in the zone settings.

---

## Gotchas

- **SSE + Caddy idle timeout**: idle connections die after 60s by default. The 25s heartbeat keeps them alive. Do not skip it.
- **EventSource auth header**: `EventSource` cannot set `Authorization` per HTML spec. Use `?token=` and the JWT-strategy fallback above. Don't try other workarounds.
- **SSE memory growth**: cap the frontend array (`.slice(0, 200)`). A dashboard left open overnight can accumulate thousands of rows otherwise.
- **SSE / Socket.IO dedup**: the initial REST fetch and the first stream pushes will overlap. Always dedup by a stable id (`event._id`, `event.eventId`, whatever the row uses).
- **Tenancy is the controller's job, not the service's**: the StreamService Subject is shared across all tenants in the process. The `@Sse()` controller filters via `streamFor(tenantId)` and verifies ownership before opening. **Never** expose the Subject directly.
- **Multi-pod horizontal scale**: the in-process RxJS Subject fans out within **one pod only**. If you scale the backend horizontally, swap the Subject for Redis pub/sub (via `@nestjs/microservices` or just `ioredis`). Single-pod deployments (Hetzner monolith, single-systemd-unit boxes) need no change.
- **PII leakage via stream**: the stream emits whatever you pass to `publish(...)`. Strip raw PII server-side before publishing — once it's on the wire, anyone with the JWT for that tenant sees it. Hash emails, redact tokens.
- **Socket.IO + Cloudflare**: enable WebSockets in the zone (Network → WebSockets → On). Without this it falls back to polling, which works but is ~5× the latency.
- **Socket.IO + load balancer sticky sessions**: if you have multiple pods AND a load balancer, enable sticky sessions OR use the Redis adapter. Otherwise clients bounce between pods and miss events.

---

## Validation checklist

After install, verify:

- [ ] Open the relevant cockpit page, see green `● LIVE` chip in the panel header
- [ ] DevTools Network tab shows one hanging GET to `/api/.../stream` (SSE) or one WebSocket frame (Socket.IO)
- [ ] Trigger an event from another tab/curl → it appears in the live feed within 1-2 seconds
- [ ] Close the tab → backend logs a clean disconnect (no error stack)
- [ ] Reload the cockpit → stream reconnects automatically, dedup prevents duplicate rows from the REST initial fetch
- [ ] Try to subscribe to a tenant you don't own → 404 (SSE) or `{ error: 'not found' }` (Socket.IO), connection closed
- [ ] Leave the cockpit open for 5+ minutes idle → connection stays alive (heartbeat working)

---

## Reference implementation

The Pulsar project ships this exact pattern in production:

- `backend/src/events/events-stream.service.ts` — the Subject bus
- `backend/src/events/events.controller.ts` `@Sse('pixels/:id/events/stream')` — the controller
- `backend/src/auth/jwt.strategy.ts` — the `fromUrlQueryParameter('token')` fallback
- `backend/src/events/ingestion.service.ts` — the `try/catch` publish wrap after `eventModel.create`
- `frontend/src/pages/analytics/Analytics.tsx` — the `useEffect` + LIVE chip + dedup + memory cap

Commit: `ca95b9a` (`feat(analytics): live event ticker via Server-Sent Events`).

---

## Related skills

- [jwt-auth-admin-seeded](../jwt-auth-admin-seeded/SKILL.md) — the JWT strategy this skill patches
- [monolith-setup](../monolith-setup/SKILL.md) — the NestJS + React shape this skill assumes
- [single-host-systemd-deploy](../single-host-systemd-deploy/SKILL.md) — Caddy auto-HTTPS handles SSE natively
- [hetzner-monolith-deploy](../hetzner-monolith-deploy/SKILL.md) — Docker/Caddy combo, same SSE behavior
- [logging-setup](../logging-setup/SKILL.md) — useful for logging disconnect events from the gateway

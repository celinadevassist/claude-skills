---
name: "Monolith Setup"
description: "Convert separate NestJS backend + React frontend projects into a single monolithic deployment where the backend serves the frontend SPA. Use when setting up a new project, converting a split frontend/backend into a monolith, or configuring Docker for a NestJS+React app that serves from one port."
---

# Monolith Setup

## What This Skill Does

Configures a NestJS backend to serve a React (Vite) frontend as a single deployable unit. One container, one port, one process. The backend serves the built frontend from a `public/` folder and handles SPA routing fallback for React Router.

## When to Use

- Setting up a new NestJS + React project from scratch
- Converting an existing split frontend/backend into a monolith
- Fixing "Cannot GET /route" errors when refreshing a React SPA served by NestJS
- Setting up Docker for a NestJS + React project

## Architecture

```
Project Root
├── backend/                 → NestJS API
│   ├── src/
│   │   ├── app.module.ts   → ServeStaticModule config
│   │   └── main.ts         → SPA fallback middleware
│   └── public/             → Frontend build output (created at build time)
├── frontend/                → React (Vite) app
│   ├── src/
│   ├── vite.config.js      → Dev proxy + build output config
│   └── .env.development    → Dev API URL
└── Dockerfile              → Multi-stage build
```

**How it works:**
1. Frontend builds to `dist/` (or optionally to `backend/public/`)
2. Dockerfile copies frontend `dist/` into backend `public/`
3. NestJS `ServeStaticModule` serves static files from `public/`
4. SPA fallback middleware returns `index.html` for all non-API, non-file routes
5. Single port serves both API (`/api/*`) and frontend (everything else)

---

## Step-by-Step Setup

### Step 1: Install ServeStaticModule in Backend

```bash
cd backend
npm install @nestjs/serve-static
```

### Step 2: Configure app.module.ts

Add `ServeStaticModule` to serve the frontend from `public/`:

```typescript
import { ServeStaticModule } from '@nestjs/serve-static';
import { join } from 'path';

@Module({
  imports: [
    // ... other modules

    // Serve frontend SPA from public folder
    ServeStaticModule.forRoot({
      rootPath: join(__dirname, '..', '..', 'public'),
      exclude: ['/api'],
    }),
  ],
})
export class AppModule {}
```

**Key points:**
- `rootPath` points to `backend/public/` (two levels up from `dist/src/`)
- `exclude: ['/api']` ensures API routes are handled by NestJS controllers, not static file serving
- The `public/` folder is populated at build time (by Dockerfile or manual copy)

### Step 3: Add SPA Fallback in main.ts

After all middleware and before `app.listen()`, add the SPA fallback. This is critical for React Router — without it, refreshing `/dashboard` returns 404.

```typescript
import { join } from 'path';
import { existsSync, readFileSync } from 'fs';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, {
    bodyParser: false,  // If using custom body parser
    // ...
  });

  app.setGlobalPrefix('api');

  // ... all other middleware (CORS, body parser, guards, etc.)

  // SPA fallback: serve index.html for non-API routes (React Router support)
  const expressApp = app.getHttpAdapter().getInstance();
  const indexPath = join(__dirname, '..', '..', 'public', 'index.html');
  if (existsSync(indexPath)) {
    const indexHtml = readFileSync(indexPath, 'utf-8');
    expressApp.use((req: any, res: any, next: any) => {
      // Skip non-GET requests and API routes
      if (req.method !== 'GET' || req.url.startsWith('/api/')) {
        return next();
      }
      // Static file request (has extension) — let ServeStatic handle it
      if (req.url.includes('.')) {
        const filePath = join(__dirname, '..', '..', 'public', req.url.split('?')[0]);
        if (existsSync(filePath)) {
          return next();
        }
        return res.status(404).json({ statusCode: 404, message: 'File not found' });
      }
      // SPA route — serve index.html
      res.type('html').send(indexHtml);
    });
  }

  const port = process.env.PORT || 3041;
  await app.listen(port);
}
bootstrap();
```

**Why read index.html once into memory:**
- Avoids disk I/O on every request
- The `if (existsSync(indexPath))` check means dev mode (no public/ folder) works fine — the fallback simply doesn't activate

**Why this order matters:**
1. API routes are registered first by NestJS
2. `ServeStaticModule` handles static files (JS, CSS, images)
3. SPA fallback catches remaining GET requests and returns `index.html`
4. React Router on the client then handles the actual route

### Step 4: Configure Vite for Development

In `frontend/vite.config.js`, set up the dev proxy so frontend dev server forwards `/api/*` to the backend:

```javascript
export default defineConfig({
  // ... plugins, etc.
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:3041',
        changeOrigin: true,
      },
      '/swagger-json': {
        target: 'http://localhost:3041',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },
  },
});
```

**Dev workflow:**
- Frontend runs on port 3000 (Vite dev server with HMR)
- Backend runs on port 3041
- Vite proxies `/api/*` to backend — no CORS issues in dev
- In production, both are served from port 3041

### Step 5: Configure Frontend API Base URL

The frontend API service should use a relative or configurable base URL:

```javascript
// frontend/src/services/api/base.js
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_BASE_URL || '';

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
});

export default api;
```

**Environment files:**

```bash
# frontend/.env.development
VITE_API_BASE_URL=    # Empty — Vite proxy handles it

# frontend/.env.production
VITE_API_BASE_URL=    # Empty — same origin in monolith
```

When `VITE_API_BASE_URL` is empty, axios uses the current origin — which is the backend itself in production.

### Step 6: Dockerfile (Multi-Stage Build)

```dockerfile
# Stage 1: Build Frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ .
RUN npm run build

# Stage 2: Build Backend
FROM node:18-alpine AS backend-builder
RUN apk add --no-cache python3 make g++
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --legacy-peer-deps
COPY backend/ .

# Copy frontend build output into backend's public folder
COPY --from=frontend-builder /app/frontend/dist ./public

RUN npm run build

# Stage 3: Production
FROM node:18-alpine
RUN apk add --no-cache dumb-init curl
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001

WORKDIR /app
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --production --legacy-peer-deps

# Copy built backend (includes public/ with frontend)
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/dist ./dist
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/public ./public

# Copy templates if they exist
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/src/templates ./templates

# Create writable directories
RUN mkdir -p /app/logs /app/uploads /app/data && chown -R nodejs:nodejs /app/logs /app/uploads /app/data

USER nodejs
EXPOSE 3041

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD curl -f http://localhost:3041/health || exit 1

ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "dist/src/main"]
```

**Key decisions:**
- **`--legacy-peer-deps`** — Required if using Mantine 8 + React 19 (peer dep conflicts)
- **`python3 make g++`** — Needed for native modules like bcrypt in backend build
- **Non-root user** — Security: runs as `nodejs:1001`
- **`dumb-init`** — Proper PID 1 signal handling for graceful shutdown
- **`curl`** — Required for Docker health checks
- **Stage 2 copies frontend dist into backend's public/** — This is the monolith link

### Step 7: .dockerignore

```
node_modules
.git
.github
*.md
.env
.env.*
logs
uploads
data
dist
.DS_Store
*.log
```

### Step 7b: Scan for Project-Specific Environment Variables

Before creating the docker-compose.yml or setup page, scan the backend for all env vars it actually uses:

```bash
# Find all process.env references in the backend
grep -rn 'process\.env\.' backend/src --include="*.ts" | grep -oP 'process\.env\.\K[A-Z_]+' | sort -u
```

This gives you the complete list of env vars to include in:
1. The `docker-compose.yml` environment section
2. The setup page's environment variables template and reference table
3. The `.env.production.example` file

Common project-specific vars to look for:
- **Payment gateways**: `STRIPE_*`, `ZIINA_*`, `PAYPAL_*`
- **AI services**: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- **Cloud storage**: `AWS_*`, `S3_*`
- **Third-party APIs**: `TWILIO_*`, `SENDGRID_*`
- **App-specific**: `MAX_CONTENT_CHARS`, `BATCH_SIZE`, etc.

Do NOT use a generic template — always customize env vars per project.

---

## Step 8: Development Mode with HMR (REQUIRED)

Every project needs a dev environment where frontend changes are visible instantly without rebuilding. This step sets up Vite dev server with HMR behind a Caddy reverse proxy.

### 8a. Configure Vite HMR for remote access

Update `frontend/vite.config.js` server section with HMR settings for your sslip.io domain:

```javascript
server: {
  port: 3001,          // Use a unique port per project (3000=ems, 3001=cartflow, etc.)
  host: '0.0.0.0',
  hmr: {
    host: 'APPNAME-dev.IP.sslip.io',  // Your dev domain
    protocol: 'wss',                    // WebSocket over HTTPS (Caddy handles SSL)
    clientPort: 443,                    // Caddy's HTTPS port
    overlay: true,
  },
  proxy: {
    '/api': {
      target: 'http://localhost:BACKEND_PORT',  // e.g. 3041, 3042
      changeOrigin: true,
    },
    '/swagger-json': {
      target: 'http://localhost:BACKEND_PORT',
      changeOrigin: true,
    },
  },
},
```

**Key settings:**
- `host: '0.0.0.0'` — listen on all interfaces (required for remote access)
- `hmr.protocol: 'wss'` — WebSocket Secure, because Caddy terminates SSL
- `hmr.clientPort: 443` — browser connects to Caddy on 443, which proxies to Vite
- `hmr.host` — must match the exact domain you'll access in the browser

### 8b. Add Caddy dev entry

Add a dev domain to `/etc/caddy/Caddyfile` that proxies to the Vite dev server:

```
APPNAME-dev.IP.sslip.io {
    reverse_proxy localhost:VITE_PORT
}
```

Then reload Caddy:
```bash
sudo caddy reload --config /etc/caddy/Caddyfile
```

### 8c. Start the Vite dev server

```bash
cd frontend
nohup npm exec vite -- --host 0.0.0.0 --port VITE_PORT > /tmp/vite-APPNAME-dev.log 2>&1 &
```

### 8d. Verify HMR works

1. Open `https://APPNAME-dev.IP.sslip.io/` in browser
2. Edit any React component
3. Changes should appear instantly without page refresh

### Port Allocation Convention

| Project | Backend Port | Vite Dev Port | Production Domain | Dev Domain |
|---------|-------------|---------------|-------------------|------------|
| ems     | 3041        | 3000          | ems.IP.sslip.io   | ems-dev.IP.sslip.io |
| cartflow| 3042        | 3001          | cartflow.IP.sslip.io | cartflow-dev.IP.sslip.io |
| idea-keep| 3043       | 3002          | idea-keep.IP.sslip.io | idea-keep-dev.IP.sslip.io |
| (next)  | 3044        | 3003          | ...                | ...-dev.IP.sslip.io |

---

## Development vs Production

| Aspect | Development | Production (Docker) |
|--------|-------------|---------------------|
| Frontend | Vite dev server with HMR | Served by NestJS from `public/` |
| Backend | NestJS (backend port) | NestJS (same port) |
| API calls | Vite proxy → backend | Same origin (monolith) |
| HMR | Yes — instant updates | No (static files) |
| Ports exposed | Vite port + backend port | Backend port only |
| public/ folder | Empty/doesn't exist | Contains frontend build |
| Access URL | `APPNAME-dev.IP.sslip.io` | `APPNAME.IP.sslip.io` |
| Caddy config | `reverse_proxy localhost:VITE_PORT` | Serves from `dist/` or proxies to backend |

---

## Checklist

### Backend
- [ ] `@nestjs/serve-static` installed
- [ ] `ServeStaticModule.forRoot()` in `app.module.ts` with `exclude: ['/api']`
- [ ] SPA fallback middleware in `main.ts` (after all other middleware, before `app.listen`)
- [ ] `app.setGlobalPrefix('api')` — all API routes under `/api`
- [ ] Health check endpoint exists at `/health` (outside `/api` prefix for Docker)

### Frontend
- [ ] Vite proxy configured for `/api` → backend port
- [ ] `VITE_API_BASE_URL` empty or omitted in production
- [ ] Build output goes to `dist/` (default)
- [ ] API service uses relative URLs (no hardcoded `localhost`)

### Docker
- [ ] Stage 1 builds frontend
- [ ] Stage 2 builds backend AND copies frontend `dist/` to `public/`
- [ ] Stage 3 copies both `dist/` (backend) and `public/` (frontend)
- [ ] Health check configured
- [ ] Runs as non-root user
- [ ] Single port exposed

### Verification
- [ ] `docker build -t app .` succeeds
- [ ] `curl http://localhost:3041/health` returns OK
- [ ] `curl http://localhost:3041/api/en/some-endpoint` returns API data
- [ ] `curl http://localhost:3041/` returns HTML (index.html)
- [ ] `curl http://localhost:3041/dashboard` returns HTML (SPA fallback)
- [ ] `curl http://localhost:3041/nonexistent.js` returns 404 (not index.html)

---

## Post-Setup Cleanup (REQUIRED)

After the monolith is working and verified, **ask the user** about cleaning up the old setup. Do not skip this step.

### Prompt the user with these questions:

1. **Old GitHub repos:** "The frontend and backend are now in a single repo. Do you want to delete or archive the old separate repos (e.g. `org/app-frontend`, `org/app-backend`)?"

2. **Old deployments:** "The app now runs from a single container/port. Do you want to remove the old separate deployments?"
   - Old Docker containers (separate frontend container, separate backend container)
   - Old Portainer stacks for the split setup
   - Old reverse proxy entries (e.g. separate Caddy/Nginx entries for `api.app.com` and `app.com`)

3. **Old CI/CD pipelines:** "Do you have separate GitHub Actions workflows for the old frontend/backend repos that should be removed?"

4. **DNS / proxy entries:** "Any old DNS records or proxy rules pointing to the separate frontend/backend ports that should be updated or removed?"

5. **Dev server processes:** "Any old dev server processes still running (e.g. Vite on port 3000 + backend on port 3041 as separate services) that should be stopped?"

### Why this matters:
- Leftover containers waste server resources
- Old repos cause confusion about which is the source of truth
- Stale proxy entries can intercept traffic meant for the new monolith
- Old CI/CD workflows may still trigger and push outdated images

---

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Cannot GET /dashboard" on refresh | Missing SPA fallback | Add the `expressApp.use()` middleware in `main.ts` |
| API returns HTML instead of JSON | `ServeStaticModule` catching `/api` routes | Add `exclude: ['/api']` to ServeStaticModule config |
| Frontend shows blank page in Docker | `public/` folder empty | Check Dockerfile copies `frontend/dist` → `backend/public` |
| CORS errors in dev | Frontend not using proxy | Add `/api` proxy in `vite.config.js` server section |
| Static assets 404 in production | Wrong `rootPath` in ServeStaticModule | Verify `join(__dirname, '..', '..', 'public')` matches your dist structure |
| Health check fails | `/health` route behind `/api` prefix | Health controller must be registered WITHOUT the global `/api` prefix. Use `@Controller()` not `@Controller('health')`. Docker health check should hit `/health` directly. |

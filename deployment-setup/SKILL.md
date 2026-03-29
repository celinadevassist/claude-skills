---
name: "Deployment Setup Builder"
description: "Build a Setup Guide page and Docker deployment infrastructure for NestJS + React monolith projects. Creates Dockerfile, GitHub Actions CI/CD, Portainer stack config, NPM proxy setup, and an in-app setup instructions page. Use when deploying a new project, adding Docker support, creating deployment docs, or setting up CI/CD pipelines."
---

# Deployment Setup Builder

## What This Skill Does

Creates the complete deployment infrastructure for a NestJS + React monolith project:

1. **Dockerfile** — Multi-stage build (frontend → backend → production)
2. **GitHub Actions** — Auto-build and push Docker image to GHCR on every push to master
3. **Docker Compose** — Portainer-ready stack with health checks, volumes, and proxy network
4. **Setup Guide Page** — In-app React page with copy-paste instructions for deployment
5. **.dockerignore** — Optimized build context

## Prerequisites

- NestJS backend + React frontend in a monorepo (`backend/` + `frontend/`)
- GitHub repository
- Portainer for container management
- Nginx Proxy Manager for reverse proxy + SSL
- MongoDB Atlas (or any MongoDB)

---

## Architecture

```
Project Root
├── backend/           → NestJS API (serves frontend from public/)
├── frontend/          → React app (builds to backend/public/)
├── Dockerfile         → Multi-stage Docker build
├── .dockerignore      → Exclude node_modules, logs, etc.
└── .github/
    └── workflows/
        └── docker-build-push.yml  → CI/CD pipeline
```

### Docker Multi-Stage Build Pattern

```
Stage 1: frontend-builder
  → npm install + npm run build (produces dist/)

Stage 2: backend-builder
  → npm install + copy frontend dist to public/ + npm run build

Stage 3: production
  → node:20-alpine + production deps only + copy dist + public
  → Runs as non-root user (nodejs:1001)
  → Health check via curl
  → Entry: dumb-init → node dist/src/main
```

**Why this pattern:**
- Frontend builds first, output copied into backend's `public/` folder
- Backend serves the SPA via NestJS ServeStaticModule
- Single container, single port (3041)
- Production stage has only runtime deps (~300MB vs ~1.2GB dev)
- `dumb-init` handles signal forwarding for graceful shutdown

---

## Dockerfile Template

```dockerfile
# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ .
RUN npm run build

# Stage 2: Build Backend
FROM node:20-alpine AS backend-builder
RUN apk add --no-cache python3 make g++
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --legacy-peer-deps
COPY backend/ .
COPY --from=frontend-builder /app/frontend/dist ./public
RUN npm run build

# Stage 3: Production
FROM node:20-alpine
RUN apk add --no-cache dumb-init curl
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
WORKDIR /app
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --production --legacy-peer-deps
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/dist ./dist
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/public ./public
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/src/templates ./templates
RUN mkdir -p /app/logs /app/uploads /app/data && chown -R nodejs:nodejs /app/logs /app/uploads /app/data
USER nodejs
EXPOSE 3041
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "dist/src/main"]
```

### Key Decisions

- **`--legacy-peer-deps`** — Required for Mantine 8 + React 19 peer dep conflicts
- **`python3 make g++`** — Needed for bcrypt native compilation in backend build stage
- **Non-root user** — Security: runs as `nodejs:1001`
- **`dumb-init`** — Proper PID 1 signal handling for Docker
- **`curl`** — Required for Docker health checks

---

## GitHub Actions Workflow

```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [ master, main ]
  pull_request:
    branches: [ master, main ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v3

    - name: Log in to GitHub Container Registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Extract metadata
      id: meta
      uses: docker/metadata-action@v5
      with:
        images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
        tags: |
          type=ref,event=branch
          type=sha,prefix={{branch}}-
          type=raw,value=latest,enable={{is_default_branch}}

    - name: Build and push Docker image
      uses: docker/build-push-action@v5
      with:
        context: .
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
        cache-from: type=gha
        cache-to: type=gha,mode=max
        platforms: linux/amd64
```

### What This Does
- Triggers on every push to master/main
- Builds the Docker image using the multi-stage Dockerfile
- Tags as: `latest`, `master`, `master-<sha>`
- Pushes to `ghcr.io/<org>/<repo>:latest`
- Uses GitHub Actions cache for faster builds (~2 min vs ~5 min)
- No secrets needed — uses built-in `GITHUB_TOKEN`

---

## Docker Compose (Portainer Stack)

The compose file below is a **template**. When applying to a new project, you MUST customize:

1. **`image`** — replace `ghcr.io/ORG/REPO:latest` with the actual GHCR image path (e.g. `ghcr.io/celinadevassist/ems:latest`)
2. **`container_name`** — use the project's short name (e.g. `ems`, `cartflow`, `idea-keep`)
3. **`PORT`** — assign a unique port per project (3041, 3042, 3043, etc.)
4. **Environment variables** — add project-specific vars (payment gateways, AI keys, S3, etc.) based on what the backend actually uses. Check the backend's `.env.production.example` or `config.manager.ts` for the full list.
5. **Volume names** — prefix with the project name (e.g. `ems_app_data`, `cartflow_app_logs`)
6. **Health check path** — use `/health` (outside the `/api` prefix) to match the monolith pattern

```yaml
version: '3.8'

services:
  app:
    image: ghcr.io/ORG/REPO:latest
    container_name: APP_NAME
    ports:
      - '${PORT:-3041}:${PORT:-3041}'
    environment:
      # Application
      NODE_ENV: production
      PORT: '${PORT:-3041}'
      APP_NAME: '${APP_NAME}'
      APP_URL: '${APP_URL}'
      FRONTEND_URL: '${FRONTEND_URL}'
      MAX_REQUEST_SIZE: '${MAX_REQUEST_SIZE:-50mb}'

      # Database
      DB_URI: '${DB_URI}'

      # JWT Authentication
      JWT_SECRET: '${JWT_SECRET}'
      JWT_EXPIRATION: '${JWT_EXPIRATION:-14d}'

      # Email Configuration
      EMAIL_PROVIDER: '${EMAIL_PROVIDER:-smtp}'
      EMAIL_FROM: '${EMAIL_FROM}'
      EMAIL_FROM_NAME: '${EMAIL_FROM_NAME}'
      SMTP_HOST: '${SMTP_HOST}'
      SMTP_PORT: '${SMTP_PORT:-465}'
      SMTP_SECURE: '${SMTP_SECURE:-true}'
      SMTP_USER: '${SMTP_USER}'
      SMTP_PASSWORD: '${SMTP_PASSWORD}'
      EMAIL_VERIFICATION_URL: '${EMAIL_VERIFICATION_URL}'
      PASSWORD_RESET_URL: '${PASSWORD_RESET_URL}'

      # Add project-specific vars below (payment, AI, S3, etc.)
    restart: unless-stopped
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:${PORT:-3041}/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - proxy-network
    volumes:
      - 'app_data:/app/data'
      - 'app_logs:/app/logs'
      - 'app_uploads:/app/uploads'

networks:
  proxy-network:
    external: true

volumes:
  app_data:
    driver: local
  app_logs:
    driver: local
  app_uploads:
    driver: local
```

### Variables to Set in Portainer

**Core variables (every project):**

| Variable | Description | Required |
|----------|-------------|----------|
| `DB_URI` | MongoDB Atlas connection string | Yes |
| `JWT_SECRET` | JWT signing key (min 32 chars). Generate: `openssl rand -hex 32` | Yes |
| `APP_URL` | Public URL (e.g. `https://app.yourdomain.com`) | Yes |
| `FRONTEND_URL` | CORS allowed origins. Comma-separated for multiple domains | Yes |
| `EMAIL_FROM` | Default sender email | Yes |
| `EMAIL_FROM_NAME` | Default sender display name | Yes |
| `APP_NAME` | Application display name | No |
| `PORT` | App port (default: 3041). Use unique port per project | No |
| `JWT_EXPIRATION` | Token expiry (default: 14d) | No |
| `MAX_REQUEST_SIZE` | Max body size (default: 50mb) | No |
| `EMAIL_PROVIDER` | `smtp` or `mailrelay` (default: smtp) | No |
| `SMTP_HOST` | SMTP server hostname | If using SMTP |
| `SMTP_PORT` | SMTP port (default: 465) | No |
| `SMTP_SECURE` | Use TLS (default: true) | No |
| `SMTP_USER` | SMTP username | If using SMTP |
| `SMTP_PASSWORD` | SMTP password | If using SMTP |
| `EMAIL_VERIFICATION_URL` | Email verification link URL | No |
| `PASSWORD_RESET_URL` | Password reset link URL | No |

**Project-specific variables (add as needed):**

Check the backend source for additional env vars. Common ones include:
- Payment gateways (Ziina, Stripe, etc.)
- AI services (OpenAI, etc.)
- Cloud storage (AWS S3, etc.)
- Third-party APIs

Always scan `backend/src/config.manager.ts` or `backend/.env.production.example` for the full list when applying this skill to a new project.

---

## Portainer Stack Deployment

There are two recommended methods for deploying stacks in Portainer. Choose the one that fits your workflow:

### Method 1: Repository (Recommended — Auto-Updates)

This method pulls the `docker-compose.yml` directly from your GitHub repo. When you update the compose file in git, you can re-pull in Portainer with one click.

1. **Stacks → Add Stack → Repository**
2. Fill in:
   - **Name:** Your app name (e.g. `ems`, `cartflow`)
   - **Repository URL:** `https://github.com/ORG/REPO`
   - **Repository reference:** `refs/heads/master` (or `refs/heads/main`)
   - **Compose path:** `docker-compose.yml` (or `docker-compose.prod.yml` if separate)
   - **Authentication:** ON (for private repos)
     - **Username:** Your GitHub username
     - **Personal Access Token:** GitHub PAT with `repo` scope
3. **Environment variables:** Add all required variables (DB_URI, JWT_SECRET, etc.) in the Environment Variables section below the form
4. Click **Deploy the stack**

**To update after changes:**
- Go to the stack in Portainer → click **Pull and redeploy**
- This fetches the latest compose file from the repo and the latest image

**Advantages:**
- Compose file is version-controlled in git
- One-click re-pull when compose changes
- No manual copy-paste of YAML
- Team members can see what's deployed by reading the repo

### Method 2: Web Editor (Quick & Manual)

Copy-paste the docker-compose.yml directly into Portainer. Good for quick deploys or when you want full manual control.

1. **Stacks → Add Stack → Web Editor**
2. **Name:** Your app name
3. **Paste** the full docker-compose.yml content into the editor
4. **Environment variables:** Add all required variables below
5. Click **Deploy the stack**

**To update after changes:**
- Edit the compose content directly in Portainer's editor
- Or delete and recreate the stack

---

## Portainer Registry Setup (GHCR)

Before Portainer can pull your Docker image, add GitHub Container Registry:

1. **Settings → Registries → Add Registry → Custom Registry**
2. Fill in:
   - **Name:** GitHub Container Registry
   - **URL:** `ghcr.io`
   - **Authentication:** ON
   - **Username:** Your GitHub username
   - **Password:** GitHub Personal Access Token

3. **Create PAT:** github.com/settings/tokens → Generate new token (classic)
   - Scope: `read:packages` (required for pulling images)
   - Scope: `repo` (also needed if using Repository deploy method with private repos)
   - Copy token → paste as Password in Portainer

---

## Nginx Proxy Manager Setup

1. **Proxy Hosts → Add Proxy Host**
2. Fill in:
   - **Domain Names:** `app.yourdomain.com`
   - **Scheme:** `http`
   - **Forward Hostname:** Container name (e.g. `app-name`)
   - **Forward Port:** `3041`
3. **SSL tab:**
   - Request new SSL certificate
   - Force SSL: ON
   - HTTP/2 Support: ON

**Important:** Both the app container and NPM must be on the same Docker network (`proxy-network`).

---

## Health Check Endpoint

Every project should have a simple health endpoint:

```typescript
@Controller()
@ApiTags('Health')
export class HealthController {
  @Get('/health')
  @ApiOperation({ summary: 'Health check' })
  @ApiResponse({ status: 200, description: 'Service is healthy' })
  getHealthCheck() {
    return {
      status: 'ok',
      service: 'APP_NAME API',
      timestamp: new Date().toISOString(),
    };
  }
}
```

The Docker health check and monitoring tools depend on this.

---

## .dockerignore

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

---

## In-App Setup Guide Page

Create a React page at `src/pages/Settings/Setup/index.jsx` that contains:

1. **Registry setup** — Table with GHCR fields + PAT creation steps
2. **Deploy Method: Repository** — Step-by-step for Stacks → Add Stack → Repository with fields: repo URL, reference, compose path, authentication, env vars
3. **Deploy Method: Web Editor** — Alternative: copy-paste docker-compose.yml into Portainer editor
4. **Docker Compose** — Full stack file with copy button (for Web Editor method)
5. **Environment Variables** — Template with copy button
6. **Variable Reference** — Table explaining each variable
7. **NPM Proxy** — Domain, scheme, hostname, port, SSL settings
8. **Verify** — Checklist (visit domain, check /health, create account, test API keys)
9. **Update** — "Pull and redeploy" in Portainer (works for both methods)
10. **Troubleshooting** — Table of common issues and solutions

### Design Pattern
- Use raw HTML/CSS with `setup-` prefixed class names (not Mantine)
- Dark code blocks with copy buttons (same pattern as API docs)
- Numbered step circles
- Warning/info note boxes
- Responsive layout

### Route Setup
1. Add lazy component: `export const LazySetup = lazy(() => import("../pages/Settings/Setup"))`
2. Add route: `<Route path="setup" element={<LazySetup />} />`
3. Add to settings menu with `FaServer` icon

---

## Verification Checklist

### Docker Build
- [ ] `docker build -t app .` succeeds locally
- [ ] Multi-stage produces image under 400MB
- [ ] Container starts and responds on port 3041
- [ ] Health check passes: `curl http://localhost:3041/health`
- [ ] Non-root user: container runs as `nodejs:1001`

### GitHub Actions
- [ ] Workflow triggers on push to master
- [ ] Image pushes to `ghcr.io/<org>/<repo>:latest`
- [ ] Build completes in under 3 minutes (with cache)

### Portainer
- [ ] GHCR registry added with valid PAT
- [ ] Stack deploys successfully
- [ ] Container health check shows "healthy"
- [ ] Environment variables are set correctly

### Nginx Proxy Manager
- [ ] Domain resolves to server IP
- [ ] Proxy host forwards to container
- [ ] SSL certificate issued and active
- [ ] Force SSL enabled

### Application
- [ ] Login page loads at domain
- [ ] API responds at `/health`
- [ ] Can create account and log in
- [ ] API key authentication works

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Container exits immediately | Check `DB_URI` — MongoDB must be reachable. Check container logs. |
| Health check fails | Ensure port 3041 exposed and healthcheck URL is `/health` |
| CORS errors | Set `FRONTEND_URL` to exact domain with `https://` |
| API key auth 401 | CORS must allow `X-API-Key` header (built-in) |
| Can't connect to MongoDB | Whitelist server IP in MongoDB Atlas Network Access |
| SSL not working | Ensure NPM can reach ports 80/443 and domain resolves correctly |
| Image pull fails | Check GHCR registry credentials in Portainer. PAT needs `read:packages` scope. |
| 502 Bad Gateway | Container is down — check logs in Portainer and redeploy |
| Redux `payload` error | Clear browser localStorage (`persist:root`) — stale cache from old build |

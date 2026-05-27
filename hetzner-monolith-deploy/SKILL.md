---
name: hetzner-monolith-deploy
description: End-to-end production deploy of a NestJS + React + Postgres + Prisma monolith to a single Hetzner ARM server, with Caddy auto-HTTPS, push-to-deploy via GitHub Actions multi-arch builds + Watchtower, Prisma migrations on container start, nightly backups to local disk + Backblaze B2, and SMTP via MXroute. Use when standing up a new project from the same blueprint as Follow-Up Expenses; complements monolith-setup (app shape), pwa-setup (PWA), and deployment-setup (Portainer alternative).
---

# Hetzner Monolith Deploy

## What This Skill Does

Takes a NestJS-backend + React-frontend (Vite/Mantine) + Postgres + Prisma monolith from `git push` to a live HTTPS URL on a **single small Hetzner ARM server** with **zero-click auto-deploy**, then keeps it backed up and observable.

The full picture, in one diagram:

```
  developer machine                        GitHub                       GHCR                Hetzner cax11 (your server)
  ─────────────────                        ──────                       ────                ──────────────────────────────
  git push origin main      ───▶   Actions: build (amd64 + arm64    ▶  multi-arch        ┌─────────────────────────────────┐
                                    matrix, native runners)            manifest @latest  │ Watchtower (60s poll)            │
                                    + merge digests                                      │   pulls ──▶ recreates expenses-app│
                                                                                         │                                  │
                                                                                         │ expenses-app  (Nest + SPA)       │
                                                                                         │   docker-entrypoint.sh:          │
                                                                                         │     prisma migrate deploy        │
                                                                                         │     node dist/main.js            │
                                                                                         │                                  │
                                                                                         │ Caddy ◀── HTTPS (auto LE cert)   │
                                                                                         │   reverse_proxy app:<PORT>       │
                                                                                         │                                  │
                                                                                         │ Postgres 16  (data on volume)    │
                                                                                         │                                  │
                                                                                         │ Backup cron 03:15:               │
                                                                                         │   pg_dump + uploads tar          │
                                                                                         │   ──▶ local 14d                  │
                                                                                         │   ──▶ rclone B2 30d              │
                                                                                         └─────────────────────────────────┘
```

End-to-end from `git push` to live: **~5–6 minutes** (build ~3 min, Watchtower poll ≤ 60 s, recreate + migrate + healthcheck ~30 s).

## When to Use

- Standing up a new internal tool, side project, or small SaaS where ONE small server is enough (the cax11 handles dozens of concurrent users comfortably).
- The app fits the same shape: NestJS API + React SPA served as a monolith (backend serves the built SPA from `public/`).
- You want push-to-deploy without paying for Vercel/Render/Fly etc.
- You want full ownership: Postgres on your disk, your domain, your backups in your B2 bucket.

## When NOT to Use

- Pure backend service (no SPA) → still works but `caddy` + the SPA serving is overkill; trim those.
- App needs horizontal scaling (>1 instance behind a load balancer) → this pattern is intentionally single-box. Move to k8s / managed Postgres before you outgrow it.
- App needs ports 25/465 outbound (Hetzner blocks these) → SMTP must be 587 STARTTLS, or proxy through a relay.
- You don't have a real domain and don't want Let's Encrypt rate-limit pain → sslip.io works but the LE shared-domain limit (250k/week) will sometimes deny issuance.

---

## PRE-FLIGHT — what to ask the user for

> **HARD GATE.** Before doing **any** provisioning, server SSH, code generation, or DNS work, post the full checklist below to the user (BOTH the where-to-get column AND the why column) and **wait until they have provided all 4 MUST-HAVE items.** Do not call any Hetzner API, do not create any files on a target server, do not write any GitHub Actions workflow until the 4 MUST-HAVEs are in hand. CAN-ADD-LATER items don't block — proceed without them and wire them up when they arrive.

### MUST-HAVE (4 items)

| # | Item | Where they get it | Why |
|---|---|---|---|
| 1 | **Hetzner Cloud API token** (read+write on the project) | Hetzner Console → Project → Security → API Tokens → "Generate API token" | Lets you create the server + volume + firewall via the API |
| 2 | **GitHub repo URL** + a **PAT with `read:packages` + `repo` scope** (classic token) | github.com/settings/tokens | Repo to push to; PAT lets the server pull the private image from GHCR |
| 3 | **A domain you control** + **DNS access** (e.g. `app.theirdomain.com`) | Their registrar (Namecheap/Cloudflare/etc.) | Point an A-record at the server IP; Caddy gets a real LE cert |
| 4 | **Server-size confirmation** (default `cax11` = 2 vCPU/4 GB ARM, fsn1, ~€5.49/mo) | Just confirm or override | Sets cost + capacity. `cax21` (4 vCPU/8 GB ~€11) for heavier loads. Note: `cax**` are only in fsn1/nbg1 |

With these four, you can stand up the box, deploy the app, get HTTPS, set up the CI/CD loop, and hand back a working URL in ~25 min.

### CAN-ADD-LATER (4 items)

| # | Item | Without it | When you'd want it |
|---|---|---|---|
| 5 | **SMTP credentials** + DNS for SPF/DKIM | Verification emails log the link to docker logs instead of sending. Users can be verified manually | Before opening public signup |
| 6 | **Off-site backup bucket** (Backblaze B2 / S3 / DO Spaces — name + bucket-scoped API key) | Nightly local backups still run (14-day retention) | Add anytime — gives 30-day off-site redundancy |
| 7 | **Branding** — display name, theme color, logo, og-banner.png (1200×630) | Sensible placeholders auto-generated | Before any public marketing/share |
| 8 | **VAPID keys** (or generate via `npx web-push generate-vapid-keys`) | Web push disabled, everything else works | Only if push notifications are wanted |

### What you (the agent) generate — no input needed

- Fresh SSH keypair (`~/.ssh/<project>_prod`) + add public key to the `deploy` user.
- `JWT_ACCESS_SECRET` + `JWT_REFRESH_SECRET` (each `openssl rand -hex 64`).
- Initial admin password (strong, printed once to user's screen).
- All Compose / Caddyfile / backup.sh / Actions workflow files.

---

## Architecture (the actual building blocks)

### Server
- **Hetzner cax11 ARM** (2 vCPU / 4 GB / ARM64). Provisioned in `fsn1` or `nbg1` (the only regions cax** is offered in).
- **DB volume** — separate 10 GB Hetzner block, mounted at `/mnt/db`. Holds `pgdata/` and `uploads/` (receipts). Survives server destroy/recreate.
- **Non-root `deploy` user** with `sudo` + `docker` group; **root SSH disabled**, key-only.
- **Firewall** — 22/80/443 only.

### Stack (Docker Compose at `/opt/expenses/`, project repo's `deploy/` is the source of truth)

| Container | Image | Role |
|---|---|---|
| `<project>-postgres` | `postgres:16-alpine` | Data on `/mnt/db/pgdata` |
| `<project>-app` | `ghcr.io/<owner>/<repo>:latest` (multi-arch) | NestJS API + serves built SPA from `public/`. Listens on `:${PORT}` **inside the Docker network only** (no host port published). Healthcheck → `/health` |
| `<project>-caddy` | `caddy:2-alpine` | Reverse-proxies the public domain → `app:${PORT}`, automatic LE certs |
| `<project>-watchtower` | `containrrr/watchtower` | Polls GHCR every 60 s with `--label-enable`; pulls + recreates only labelled containers |

The app and proxy share a network. Postgres is internal-only. Uploads are bind-mounted from `/mnt/db/uploads` so receipt images survive image rebuilds.

### CI/CD (every `git push origin main`)

1. **`build` matrix job** in `.github/workflows/docker-build-push.yml`:
   - `amd64` leg on `ubuntu-latest`
   - `arm64` leg on **native `ubuntu-24.04-arm` runner** (NOT QEMU emulation — much faster)
   - Each builds + pushes by **digest** to GHCR
2. **`merge` job** runs `docker buildx imagetools create` to assemble a single multi-arch manifest tagged `:latest`.
3. **Watchtower** notices the new digest within ≤ 60 s, pulls, recreates `<project>-app`.
4. The container's **`docker-entrypoint.sh`** runs `npx prisma migrate deploy` first, then `node dist/main.js`. So every push → migrations applied → live, with no manual steps.

### Secrets

- All runtime secrets in **`/opt/expenses/.env`** — chmod 600, never committed, **never baked into the image** (would leak via GHCR layers).
- Compose maps them via `${VAR}` substitution into the app container's env.
- Standard contents: `POSTGRES_USER/PASSWORD/DB`, `DATABASE_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `JWT_ACCESS_TTL`, `JWT_REFRESH_TTL`, `ALLOW_SIGNUP`, `APP_URL`, `FRONTEND_URL`, `SMTP_HOST/PORT/SECURE/USER/PASSWORD`, `EMAIL_FROM`, `VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY` (if push).

### GHCR auth on the server

For Watchtower to pull a **private** image, do `docker login ghcr.io` on the server as the user Watchtower runs as (root or the deploy user — see compose). The PAT (item #2 above) goes in `~/.docker/config.json` for that user. Watchtower reads it automatically. Re-run `docker login` if the PAT is ever rotated.

### Backups

- Cron under `deploy` at **03:15 daily** runs `/opt/expenses/backup.sh`.
- Produces `expenses-<ts>.sql.gz` (pg_dump, gzip) + `uploads-<ts>.tar.gz`.
- Keeps newest 14 of each locally at `/opt/expenses/backups/`.
- Pushes off-site via `rclone` to **Backblaze B2** at `b2:<your-bucket>/<hostname>/`, prunes `--min-age 30d`.
- Exits non-zero only if the **DB dump** failed (uploads best-effort).

### SMTP

Use **port 587 STARTTLS** (`SMTP_SECURE=false`). Hetzner **blocks outbound 25 and 465**, so the "recommended" secure-true configs that providers print will hang for ~2 min. MXroute on `taylor.mxrouting.net:587` was the reference that worked. The mailer should have connection/socket timeouts (10/20s) so a blocked port falls back to logging rather than hanging registration.

---

## Step-by-step (in order)

### 0. PRE-FLIGHT GATE — collect the 4 MUST-HAVEs

Re-read the PRE-FLIGHT section above. Post the full MUST-HAVE table to the user (item + where-to-get + why), and **wait for all 4 answers** before Step 1. Confirm back to the user what you received and what's missing. Only proceed once these are in hand:

- [ ] Hetzner Cloud API token (read+write)
- [ ] GitHub repo URL + PAT (`read:packages` + `repo`)
- [ ] Domain + DNS access (or explicit OK to use `<name>.<ip>.sslip.io`)
- [ ] Server-size choice (default `cax11`)

Also ask (CAN-ADD-LATER; non-blocking — list as "optional now, wire later"):
- SMTP creds + EMAIL_FROM
- Off-site backup bucket (B2/S3/DO Spaces) + scoped key
- Branding (display name, theme color, logo, 1200×630 og-banner)
- VAPID keys (or "I'll generate them when push is wanted")

If the user replies with only some of the 4 MUST-HAVEs, ask once for the rest. Do not start provisioning with partial info.

### 1. Provision the Hetzner server + volume

```bash
# Replace placeholders. Region must be fsn1 or nbg1 for cax**.
TOKEN=<HETZNER_API_TOKEN>
NAME=<project-name>

# Create the server (gets a random root password; we'll disable root login next step)
curl -sX POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://api.hetzner.cloud/v1/servers \
  -d "{\"name\":\"$NAME\",\"server_type\":\"cax11\",\"image\":\"ubuntu-24.04\",\"location\":\"fsn1\"}" \
  | tee /tmp/server.json

SERVER_ID=$(jq -r .server.id /tmp/server.json)
SERVER_IP=$(jq -r .server.public_net.ipv4.ip /tmp/server.json)

# Create the volume (10 GB) and attach it
curl -sX POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://api.hetzner.cloud/v1/volumes \
  -d "{\"name\":\"$NAME-db\",\"size\":10,\"server\":$SERVER_ID,\"format\":\"ext4\",\"location\":\"fsn1\"}"
```

ROTATE the API token immediately after — it's been in your shell history.

### 2. Bootstrap the `deploy` user + harden SSH

```bash
# Generate a fresh keypair LOCALLY
ssh-keygen -t ed25519 -f ~/.ssh/${NAME}_prod -N "" -C "${NAME}-deploy"

# SSH in as root with the server's initial password (Hetzner emailed it)
ssh root@$SERVER_IP "bash -s" <<EOF
set -e
useradd -m -s /bin/bash deploy
usermod -aG sudo deploy
echo 'deploy ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/deploy
mkdir -p /home/deploy/.ssh
echo '$(cat ~/.ssh/${NAME}_prod.pub)' >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd
EOF

# Confirm key-only deploy access works
ssh -i ~/.ssh/${NAME}_prod deploy@$SERVER_IP 'whoami && groups'
```

Hetzner Cloud Firewall: keep 22/80/443 inbound only.

### 3. Install Docker, Compose, rclone, mount the volume

```bash
ssh -i ~/.ssh/${NAME}_prod deploy@$SERVER_IP 'sudo bash -s' <<'EOF'
set -e
apt-get update && apt-get install -y ca-certificates curl gnupg rclone jq postgresql-client
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker deploy

# Mount the attached Hetzner volume at /mnt/db (id from step 1)
VOL_DEV=$(ls -1 /dev/disk/by-id/scsi-0HC_Volume_* | head -1)
mkdir -p /mnt/db
echo "$VOL_DEV /mnt/db ext4 defaults,nofail 0 0" >> /etc/fstab
mount /mnt/db
mkdir -p /mnt/db/pgdata /mnt/db/uploads /opt/expenses /opt/expenses/backups
chown -R deploy:deploy /opt/expenses
chown 70:70 /mnt/db/pgdata     # postgres user inside postgres:alpine
chown 1001:1001 /mnt/db/uploads # nodejs user inside the app image (matches Dockerfile)
EOF
```

### 4. Drop the stack onto the server

Create `/opt/expenses/.env` (chmod 600) with all secrets:

```ini
# /opt/expenses/.env
PORT=3044
NODE_ENV=production
POSTGRES_USER=followup
POSTGRES_PASSWORD=<openssl rand -hex 24>
POSTGRES_DB=followup
DATABASE_URL=postgresql://followup:<same-pw>@postgres:5432/followup?schema=public

JWT_ACCESS_SECRET=<openssl rand -hex 64>
JWT_REFRESH_SECRET=<openssl rand -hex 64>
JWT_ACCESS_TTL=15m
JWT_REFRESH_TTL=7d

ALLOW_SIGNUP=false
APP_URL=https://<your-domain>
FRONTEND_URL=https://<your-domain>

ADMIN_EMAIL=<admin@yourdomain>
ADMIN_PASSWORD=<strong-pass-printed-once>

# SMTP (port 587 — Hetzner blocks 25/465)
SMTP_HOST=
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM="<App Name> <no-reply@yourdomain>"

# Push notifications (optional)
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:<admin@yourdomain>
```

Drop `/opt/expenses/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: <project>-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - /mnt/db/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      retries: 5

  app:
    image: ghcr.io/<owner>/<repo>:latest
    container_name: <project>-app
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PORT: ${PORT:-3044}
      NODE_ENV: production
      DATABASE_URL: ${DATABASE_URL}
      JWT_ACCESS_SECRET: ${JWT_ACCESS_SECRET}
      JWT_REFRESH_SECRET: ${JWT_REFRESH_SECRET}
      JWT_ACCESS_TTL: ${JWT_ACCESS_TTL:-15m}
      JWT_REFRESH_TTL: ${JWT_REFRESH_TTL:-7d}
      ALLOW_SIGNUP: ${ALLOW_SIGNUP:-false}
      APP_URL: ${APP_URL}
      FRONTEND_URL: ${FRONTEND_URL}
      ADMIN_EMAIL: ${ADMIN_EMAIL}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_SECURE: ${SMTP_SECURE}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      EMAIL_FROM: ${EMAIL_FROM}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_SUBJECT: ${VAPID_SUBJECT}
    volumes:
      - /mnt/db/uploads:/app/uploads
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  caddy:
    image: caddy:2-alpine
    container_name: <project>-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

  watchtower:
    image: containrrr/watchtower
    container_name: <project>-watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /root/.docker/config.json:/config.json:ro
    environment:
      DOCKER_API_VERSION: '1.44'   # Docker 29 requires this
    command: --interval 60 --cleanup --label-enable

volumes:
  caddy_data:
  caddy_config:
```

Drop `/opt/expenses/Caddyfile`:

```caddy
<your-domain> {
    encode zstd gzip
    reverse_proxy <project>-app:{$PORT:3044}
}
```

### 5. GitHub Actions workflow (in the repo's `.github/workflows/docker-build-push.yml`)

```yaml
name: Build and Push Docker Image
on:
  push:
    branches: [main]
permissions:
  contents: read
  packages: write
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - platform: linux/amd64
            runner: ubuntu-latest
            arch: amd64
          - platform: linux/arm64
            runner: ubuntu-24.04-arm   # native ARM runner — no QEMU emulation
            arch: arm64
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@v5
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: build
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: ${{ matrix.platform }}
          outputs: type=image,name=ghcr.io/${{ github.repository }},push-by-digest=true,name-canonical=true,push=true
          cache-from: type=gha,scope=${{ matrix.arch }}
          cache-to: type=gha,mode=max,scope=${{ matrix.arch }}
      - run: |
          mkdir -p /tmp/digests
          echo "${{ steps.build.outputs.digest }}" > /tmp/digests/${{ matrix.arch }}
      - uses: actions/upload-artifact@v4
        with: { name: digests-${{ matrix.arch }}, path: /tmp/digests/* }

  merge:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { path: /tmp/digests, pattern: digests-* }
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - run: |
          cd /tmp/digests
          docker buildx imagetools create \
            -t ghcr.io/${{ github.repository }}:latest \
            $(for f in */*; do echo "ghcr.io/${{ github.repository }}@$(cat $f)"; done)
      - run: docker buildx imagetools inspect ghcr.io/${{ github.repository }}:latest
```

Dockerfile (multi-stage; the entrypoint runs `prisma migrate deploy` on start):

```dockerfile
# Stage 1: frontend build
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ .
RUN npm run build

# Stage 2: backend build (+ prisma client)
FROM node:20-alpine AS backend-builder
RUN apk add --no-cache python3 make g++   # for bcrypt native build
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --legacy-peer-deps
COPY backend/ .
COPY --from=frontend-builder /app/frontend/dist ./public
RUN npx prisma generate && npm run build

# Stage 3: production
FROM node:20-alpine
RUN apk add --no-cache dumb-init curl
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
WORKDIR /app
COPY backend/package*.json ./
RUN npm cache clean --force && npm install --omit=dev --legacy-peer-deps
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/dist ./dist
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/public ./public
COPY --from=backend-builder --chown=nodejs:nodejs /app/backend/prisma ./prisma
# Regenerate client against prod node_modules
RUN npx prisma generate
RUN mkdir -p /app/logs /app/uploads && chown -R nodejs:nodejs /app/logs /app/uploads
COPY --chown=nodejs:nodejs backend/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh
USER nodejs
EXPOSE 3044
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f "http://localhost:${PORT:-3044}/health" || exit 1
ENTRYPOINT ["dumb-init", "--", "./docker-entrypoint.sh"]
```

Entrypoint `backend/docker-entrypoint.sh`:

```bash
#!/usr/bin/env sh
set -e
echo "[entrypoint] Applying database migrations (prisma migrate deploy)..."
npx prisma migrate deploy
echo "[entrypoint] Starting Nest..."
exec node dist/main.js
```

### 6. GHCR auth on the server

```bash
ssh -i ~/.ssh/${NAME}_prod deploy@$SERVER_IP
# As root so Watchtower (root) can read it. For deploy user too, repeat as deploy.
sudo bash -c 'docker login ghcr.io -u <github-user> --password-stdin' <<< "$GH_PAT"
```

Verify `/root/.docker/config.json` exists with the GHCR auth blob.

### 7. First deploy + verify

```bash
ssh -i ~/.ssh/${NAME}_prod deploy@$SERVER_IP
cd /opt/expenses
docker compose pull
docker compose up -d
docker compose logs -f app          # watch the entrypoint run migrations
curl -s -w "\n%{http_code}\n" https://<your-domain>/health     # expect 200
```

DNS: point `<your-domain>` A-record → server IP. First Caddy access triggers LE cert issuance (~30 s).

### 8. SMTP wiring (when ready)

Fill `SMTP_*` and `EMAIL_FROM` in `/opt/expenses/.env`, then:

```bash
cd /opt/expenses && docker compose up -d app   # recreates with the new env
# Verify the handshake without sending a real email:
docker exec -e NODE_PATH=/app/node_modules <project>-app node -e "
const nm=require('nodemailer');
const t=nm.createTransport({host:process.env.SMTP_HOST,port:+process.env.SMTP_PORT,secure:process.env.SMTP_SECURE==='true',auth:{user:process.env.SMTP_USER,pass:process.env.SMTP_PASSWORD},connectionTimeout:10000});
t.verify().then(()=>console.log('SMTP OK')).catch(e=>console.log('FAIL:',e.message));"
```

DNS housekeeping for deliverability: set SPF (`v=spf1 include:<provider-spf> ~all`), DKIM (provider gives the record), DMARC (`v=DMARC1; p=none; rua=mailto:<inbox>`).

### 9. Off-site backups (when ready)

Drop `/opt/expenses/backup.sh` (mark executable):

```bash
#!/usr/bin/env bash
# Nightly backup. DB pg_dump + receipt uploads → local 14d + B2 30d.
set -uo pipefail
APP_DIR=/opt/expenses
DIR="$APP_DIR/backups"
UPLOADS=/mnt/db/uploads
KEEP=14
REMOTE="b2:<your-bucket>"   # leave empty to disable off-site
OFFSITE_KEEP_DAYS=30
mkdir -p "$DIR"
log() { echo "$(date -Is) $*" >> "$DIR/backup.log"; }
PG_USER=$(grep -E '^POSTGRES_USER=' "$APP_DIR/.env" | cut -d= -f2-)
PG_DB=$(grep -E '^POSTGRES_DB=' "$APP_DIR/.env" | cut -d= -f2-)
TS=$(date +%Y%m%d-%H%M%S)
DB_OUT="$DIR/<project>-$TS.sql.gz"
UP_OUT="$DIR/uploads-$TS.tar.gz"
db_ok=0
if docker exec <project>-postgres pg_dump -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner --no-privileges | gzip > "$DB_OUT"; then
  log "OK   db       $DB_OUT ($(du -h "$DB_OUT" | cut -f1))"; db_ok=1
else
  rm -f "$DB_OUT"; log "FAIL pg_dump failed"
fi
if [ -d "$UPLOADS" ] && [ -n "$(ls -A "$UPLOADS" 2>/dev/null)" ]; then
  tar -czf "$UP_OUT" -C "$UPLOADS" . 2>>"$DIR/backup.log" \
    && log "OK   uploads  $UP_OUT ($(du -h "$UP_OUT" | cut -f1))" \
    || { rm -f "$UP_OUT"; log "WARN uploads archive failed"; }
fi
ls -1t "$DIR"/<project>-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$DIR"/uploads-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
if [ -n "$REMOTE" ] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$DIR" "$REMOTE/$(hostname)/" --include "*-$TS.*" 2>>"$DIR/backup.log" \
    && { rclone delete --min-age "${OFFSITE_KEEP_DAYS}d" "$REMOTE/$(hostname)/" 2>>"$DIR/backup.log" || true; \
         log "OK   off-site -> $REMOTE/$(hostname)/"; } \
    || log "WARN off-site upload failed (local backup is fine)"
fi
[ "$db_ok" = 1 ] || exit 1
```

Configure rclone for B2 (one-time):

```bash
rclone config   # add a "b2" remote with account + bucket-scoped app key
crontab -e      # add: 15 3 * * * /opt/expenses/backup.sh
```

---

## Common operations

```bash
# Deploy a code change — just push:
git push origin main    # CI builds → GHCR → Watchtower deploys ≤ 6 min

# Change an env var without rebuilding the image:
ssh deploy@$IP "cd /opt/expenses && nano .env && docker compose up -d app"

# Force a redeploy right now (don't wait for Watchtower):
ssh deploy@$IP "cd /opt/expenses && docker compose pull app && docker compose up -d app"

# Tail logs / health
docker logs -f <project>-app
docker logs --since 30m <project>-app | grep -i error
curl -s -o /dev/null -w '%{http_code}\n' https://<domain>/health

# Run a one-off Prisma command
docker exec <project>-app npx prisma migrate status
docker exec <project>-app npx prisma studio   # if you bind a port

# Restore DB from local backup
zcat /opt/expenses/backups/<project>-<ts>.sql.gz | docker exec -i <project>-postgres psql -U $PG_USER -d $PG_DB

# Restore receipts
tar -xzf /opt/expenses/backups/uploads-<ts>.tar.gz -C /mnt/db/uploads

# Restore from off-site
rclone copy b2:<bucket>/<hostname>/<project>-<ts>.sql.gz /tmp/ && zcat /tmp/<project>-<ts>.sql.gz | ...

# Manually trigger backup
ssh deploy@$IP "/opt/expenses/backup.sh && tail -5 /opt/expenses/backups/backup.log"
```

---

## Tradeoffs & gotchas

- **Hetzner blocks SMTP 25/465 outbound.** Use 587 STARTTLS (`SMTP_SECURE=false`). The mailer **must** set `connectionTimeout`/`socketTimeout` (~10/20 s) or registration hangs ~2 min on a blocked port.
- **Docker 29 + Watchtower** → set `DOCKER_API_VERSION: '1.44'` in the watchtower service, or it can't talk to the socket.
- **Migrations destructive defaults.** `prisma migrate dev` auto-generated migrations for enum→text conversions are DESTRUCTIVE (DROP + ADD column = data loss). Hand-write `ALTER TABLE ... ALTER COLUMN ... TYPE TEXT USING ...::text` + the matching seed `INSERT`s in the same `migration.sql`.
- **Frontend build gotchas.** `tsc -b` enforces `noUnusedLocals` which `tsc --noEmit` doesn't catch. ALWAYS run `cd frontend && npm run build` (not just `tsc --noEmit`) before pushing or the Docker build fails on an unused import.
- **`sslip.io` + Let's Encrypt rate-limit.** The shared `sslip.io` domain hits the LE 250k/week ceiling sometimes. For prod, use a real domain.
- **Single-box pattern.** No HA. The cax11 is plenty for tens of concurrent users and thousands of accounts; bcrypt cost 12 caps auth at ~7/sec on 2 cores. Drop bcrypt to cost 10 for ~30/sec headroom, or scale up to cax21.
- **Vendors + Items aren't cascade-deleted by Expense delete.** When testing on real accounts, clean those up explicitly or they linger in autocomplete / "Recent vendors".
- **SQL `LIKE` underscore is a wildcard.** Escape with `LIKE '\_\_%' ESCAPE '\'` when matching literal `__test_` prefixes.

---

## Companion skills

- **`monolith-setup`** — the app architecture (NestJS serving the SPA from `public/` via `ServeStaticModule`). Run that first to scaffold; this skill deploys what it produces.
- **`deployment-setup`** — older Portainer-based deploy pattern. Use this skill instead unless the team standardises on Portainer.
- **`pwa-setup`** — manifest + service worker + install prompts. Independent of this skill.
- **`jwt-auth-admin-seeded`** — JWT cookie auth + initial admin seeding. Independent.
- **`nestjs-throttle`** — global rate-limit guard. Independent.
- **`setup-guide-page`** — in-app `/setup` page that shows live health checks. Pair with this skill once deployed.

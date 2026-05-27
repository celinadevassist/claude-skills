---
name: single-host-systemd-deploy
description: Deploy a NestJS + React monolith onto a shared Linux host (multiple sibling projects on one box) without Docker — systemd units for prod + dev, Caddy reverse-proxy with auto-HTTPS, sslip.io subdomain (or any custom domain), a `scripts/deploy.sh` that builds frontend → backend/public → backend → restarts the unit → health-checks, and GitHub Actions CD over SSH. Use when adding a project to an existing shared box that already runs Caddy + a handful of siblings (the mission-control / ems / cartflow / idea-keep pattern). Sibling deploy skills — pick **hetzner-monolith-deploy** to stand up a NEW dedicated Docker server, **deployment-setup** when the host runs Portainer + Nginx-Proxy-Manager.
---

# Single-Host Systemd Deploy

## What This Skill Does

Adds a new NestJS + React monolith to a **shared Linux host** that already runs Caddy and one or more sibling projects, **without Docker**. You get:

- **systemd units** for prod and dev (auto-restart, journal logging, env from `backend/.env`).
- **Caddy reverse-proxy block** routing a `<slug>.<host-ip>.sslip.io` subdomain (and/or a custom domain) to the prod port, with **automatic HTTPS**.
- **`scripts/deploy.sh`** — one command that builds the frontend, copies `dist/` into `backend/public/`, builds the backend, restarts the systemd unit, and health-checks.
- **GitHub Actions** workflow that SSHes to the host and runs `deploy.sh` on push to `main`.

```
   git push main ─▶ GitHub Actions (actions/ssh)
                              │
                              ▼
                  ssh <host> "cd /home/sammy/<slug> && ./scripts/deploy.sh"
                              │
                              ▼
   npm run build (frontend)  →  cp dist/* backend/public/
   npm run build (backend)
   sudo systemctl restart <slug>.service
   curl -fs localhost:<port>/health  → OK
                              │
                              ▼
       https://<slug>.<host-ip>.sslip.io/   (or your custom domain)
```

Same shared host can carry **10+ projects** (today this box runs mission-control / ems / cartflow / idea-keep / playground-wristband / expense-tracking-app / pulsar — each with its own prod + dev unit on its own port pair).

## When to Use This Skill — pick one of three siblings

| You're deploying to… | Use |
|---|---|
| A **shared box** that already runs Caddy + several sibling projects, no Docker | **this skill** (`single-host-systemd-deploy`) |
| A **new dedicated server** on Hetzner/DO (Docker + Watchtower + B2 backups) | `hetzner-monolith-deploy` |
| An **existing Portainer + Nginx-Proxy-Manager** host | `deployment-setup` |

Pick this one when: the host already exists, you don't want Docker overhead per app, sslip.io is fine for the URL (or you have your own DNS), and the box is one you control via SSH.

## Prerequisites — host-level (assumed in place once)

These are set up **once per host**, not per project:

1. **Linux box, public IP, SSH access** (port 22, your SSH key in `~/.ssh/authorized_keys`).
2. **Node.js** installed at `/usr/bin/node` (use whatever version your projects need; nvm-managed paths break systemd — use a system Node).
3. **Caddy** installed, running as a systemd service, with `/etc/caddy/Caddyfile` writable by root and `systemctl reload caddy` available.
4. **A non-root user** for the apps (we use `sammy`); its home dir holds all the project folders (`/home/sammy/<slug>/`).
5. **Sudoers entry** for that user so the deploy script can restart the unit without a password — e.g. `sammy ALL=(root) NOPASSWD: /bin/systemctl restart *.service, /bin/systemctl reload caddy, /usr/sbin/caddy validate*`.
6. **(Optional) DNS A record** if you want a custom domain (`<slug>.yourdomain.com → <host-ip>`); otherwise sslip.io works with no DNS config (`<slug>.<host-ip>.sslip.io` auto-resolves to `<host-ip>`).

If any of those are missing, set them up first — the rest of this skill assumes them.

## Port Allocation Convention

Each project gets **two ports**: one for prod, one for dev. The host's current allocation:

| Port | Project | Env |
|------|---------|-----|
| 3000 | ems | dev |
| 3001 | cartflow | dev |
| 3003 | playground-wristband | dev |
| 3041 | ems | prod |
| 3042 | cartflow | prod |
| 3043 | idea-keep | prod |
| 3044 | expenses-tracker | prod |
| 3045 | pulsar | prod |
| 3047 | mission-control | prod |
| 3048 | mission-control | dev |
| 3050 | idea-keep | dev |

Loose rule: **prod in the 3040s, dev in the 3000s or 3050+**. Pick the next free pair when adding a project. Check with `ss -tln | awk '$4 ~ /:30[0-9][0-9]$/{print $4}' | sort -u`.

## What You Create Per Project

Four artifacts, all small:

1. `<project>/scripts/deploy.sh` — the build + restart script.
2. `/etc/systemd/system/<slug>.service` — production unit.
3. `/etc/systemd/system/<slug>-dev.service` — dev unit (optional but recommended).
4. A block in `/etc/caddy/Caddyfile` — public URL.
5. `.github/workflows/deploy.yml` — GitHub Actions CD.

---

## Step 1: `scripts/deploy.sh`

Drop this in the project as `scripts/deploy.sh` (`chmod +x scripts/deploy.sh`):

```bash
#!/usr/bin/env bash
# Build frontend, copy into backend/public, build backend, restart systemd, health-check.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

SLUG="<slug>"                    # e.g. mission-control
PORT="<prod-port>"               # e.g. 3047
HOST_URL="https://${SLUG}.<host-ip>.sslip.io/"

echo "==> Building frontend..."
(cd frontend && npm run build)

echo "==> Copying frontend/dist -> backend/public..."
rm -rf "$ROOT/backend/public"
mkdir -p "$ROOT/backend/public"
cp -r "$ROOT/frontend/dist/." "$ROOT/backend/public/"

echo "==> Building backend..."
(cd backend && npm run build)

echo "==> Restarting ${SLUG}.service..."
sudo -n systemctl restart "${SLUG}.service"
sleep 3

echo "==> Health check..."
curl -fs "http://localhost:${PORT}/health" > /dev/null && echo "OK" || { echo "FAIL"; exit 1; }

echo "==> Deployed: ${HOST_URL}"
```

**Why this shape:**
- `set -euo pipefail` — fail fast on any error.
- Builds frontend **first**, then copies its `dist/` into `backend/public/` (the monolith pattern from `monolith-setup`: backend serves the SPA via `ServeStaticModule`).
- `sudo -n` — non-interactive sudo. The sudoers entry from prerequisites makes this work without a password.
- Health-check curls the local port (not the public URL — faster, no DNS/TLS in the loop).

> **A `/health` endpoint is required.** Add a `GET /health` route to the NestJS backend returning `{ status: 'ok' }` — it's used by both the deploy script and any uptime monitor.

---

## Step 2: systemd unit — production

Create `/etc/systemd/system/<slug>.service` (write as root):

```ini
[Unit]
Description=<Project Name> Backend (NestJS monolith)
After=network.target

[Service]
Type=simple
User=sammy
WorkingDirectory=/home/sammy/<slug>/backend
EnvironmentFile=/home/sammy/<slug>/backend/.env
Environment=NODE_ENV=production
Environment=PORT=<prod-port>
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/node /home/sammy/<slug>/backend/dist/main
Restart=always
RestartSec=5
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now <slug>.service
systemctl status <slug>.service
```

**Key details:**
- `EnvironmentFile=` points at `backend/.env` — *never* commit that file.
- `Environment=PATH=...` is **required**. Without it, child processes (e.g. `npm`, `gh`, system commands the app shells out to) won't find binaries.
- `LimitNOFILE=65535` — bumps the FD ceiling so a busy server (sockets, watchers) doesn't hit the default 1024.
- `StandardOutput=journal` — all logs go to `journalctl -u <slug>.service`. No log files to rotate.
- **Do NOT** include `After=docker.service` or `Requires=docker.service` unless this app actually depends on Docker (e.g. running its DB in Docker). Existing units on this host inherited those lines from an early template and they're vestigial.

### Optional: a host-level env drop-in

If several projects share a host-only secret (e.g. a `GH_TOKEN` for `gh repo create`), put it in `/etc/<host-secret>.conf` (mode 600, root-owned) and add a systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/<slug>.service.d
sudo tee /etc/systemd/system/<slug>.service.d/gh-token.conf <<'EOF'
[Service]
EnvironmentFile=/etc/mission-control-gh.conf
EOF
sudo systemctl daemon-reload && sudo systemctl restart <slug>.service
```

This keeps host-level secrets out of every project's `.env`.

---

## Step 3: systemd unit — dev (recommended)

A dev unit gives you a permanently-live, auto-restarting dev URL (`<slug>-dev.<host-ip>.sslip.io`) handy for testing without disturbing prod.

Create `/etc/systemd/system/<slug>-dev.service`:

```ini
[Unit]
Description=<Project Name> Backend (development, watch mode)
After=network.target

[Service]
Type=simple
User=sammy
WorkingDirectory=/home/sammy/<slug>/backend
EnvironmentFile=/home/sammy/<slug>/backend/.env
Environment=NODE_ENV=development
Environment=PORT=<dev-port>
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/env PORT=<dev-port> /usr/bin/npm run start:dev
Restart=always
RestartSec=5
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Differences from prod: `NODE_ENV=development`, different port, and `ExecStart` runs `npm run start:dev` (Nest watch mode) instead of the built bundle. Both units share the same `backend/.env`.

> Dev builds usually mean **no built frontend**. If you also want a dev SPA, run `npm run dev` in `frontend/` from a tmux session, or just leave the dev port as backend-only (`/api/*`) and use the prod sslip URL for the UI when you need it.

---

## Step 4: Caddy reverse-proxy block

Append to `/etc/caddy/Caddyfile`:

```caddyfile
<slug>.<host-ip>.sslip.io {
    reverse_proxy localhost:<prod-port>
}

<slug>-dev.<host-ip>.sslip.io {
    reverse_proxy localhost:<dev-port>
}
```

Then validate + reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**Caddy gives you HTTPS for free** — it sees the public hostname and provisions a Let's Encrypt cert on first request. `sslip.io` resolves any `<anything>.<ip>.sslip.io` to `<ip>` with no DNS configuration, so the URL works the moment Caddy reloads.

### Variants you'll probably hit

**A. Custom domain alongside sslip:**
```caddyfile
<slug>.yourdomain.com {
    reverse_proxy localhost:<prod-port>
}
```
(Plus an A record for `<slug>.yourdomain.com → <host-ip>`.)

**B. Local cert (no public DNS, internal-only):**
```caddyfile
<slug>.<host-ip>.sslip.io {
    tls internal
    reverse_proxy localhost:<prod-port>
}
```

**C. Long-lived requests (server-sent events, websockets, long polls):**
```caddyfile
<slug>.<host-ip>.sslip.io {
    reverse_proxy localhost:<prod-port> {
        transport http {
            read_timeout 300s
            write_timeout 300s
        }
    }
}
```

**D. Backend-routed + static SPA fallback (when the backend returns 404, serve the SPA shell):**
```caddyfile
<slug>.<host-ip>.sslip.io {
    reverse_proxy localhost:<prod-port> {
        @backend_404 status 404
        handle_response @backend_404 {
            root * /home/sammy/<slug>/frontend/dist
            try_files {path} /index.html
            file_server
        }
    }
}
```
(Cartflow uses this so deep links work even if the API ever 404s a path.)

**E. Basic auth on a sensitive endpoint:**
```caddyfile
terminal.<host-ip>.sslip.io {
    basic_auth { admin <bcrypt-hash> }
    reverse_proxy localhost:7681
}
```
Generate the hash with `caddy hash-password`.

---

## Step 5: GitHub Actions CD (actions-ssh)

`.github/workflows/deploy.yml`:

```yaml
name: Deploy to host

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: SSH and deploy
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key:      ${{ secrets.DEPLOY_SSH_KEY }}
          port:     22
          script: |
            set -euo pipefail
            cd /home/sammy/<slug>
            git fetch --prune origin main
            git reset --hard origin/main
            (cd frontend && npm ci --no-audit --no-fund)
            (cd backend  && npm ci --no-audit --no-fund)
            ./scripts/deploy.sh
```

Repo secrets you set:
- `DEPLOY_HOST` — host IP or hostname.
- `DEPLOY_USER` — `sammy` (or whatever).
- `DEPLOY_SSH_KEY` — the **private** key matching `~/.ssh/authorized_keys` on the host. Generate a deploy-only keypair (`ssh-keygen -t ed25519 -f deploy_key -N ''`), commit the public half to `authorized_keys`, paste the private half as the secret.

Why `npm ci` in CI and not in `deploy.sh`: `deploy.sh` runs interactively too (you'll occasionally deploy by hand over SSH), and `npm install` is more forgiving in that mode. The CI step does the strict `npm ci` once, then calls the shared script.

---

## How a deploy actually flows

1. You push to `main`.
2. GitHub Actions SSHes in, does `git reset --hard origin/main`, `npm ci` both halves.
3. It calls `scripts/deploy.sh`.
4. The script builds the frontend (`vite build`), wipes `backend/public/`, copies the new `dist/` in.
5. It builds the backend (`nest build`).
6. It restarts the systemd unit. systemd starts `node dist/main`, which reads `backend/.env` and listens on `PORT`.
7. The script curls `http://localhost:<port>/health`. Pass = deploy done; fail = non-zero exit, CI goes red.
8. Caddy keeps proxying `<slug>.<host-ip>.sslip.io:443 → localhost:<port>` with its existing cert. No Caddy restart needed unless you changed the Caddyfile.

The whole thing usually takes 30–90 seconds depending on bundle size.

---

## Operational cookbook

**Tail logs:**
```bash
journalctl -u <slug>.service -f
journalctl -u <slug>.service --since "10 min ago"
```

**Restart / status:**
```bash
sudo systemctl restart <slug>.service
systemctl status <slug>.service
```

**Edit env, then restart:**
```bash
nano /home/sammy/<slug>/backend/.env
sudo systemctl restart <slug>.service
```

**Find a free port pair:**
```bash
ss -tln | awk '$4 ~ /:30[0-9][0-9]$/{print $4}' | sort -u
```

**Validate Caddyfile before reloading (don't skip — a syntax error kills *every* site):**
```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

**Roll back to the previous commit:**
```bash
ssh <host> 'cd /home/sammy/<slug> && git reset --hard HEAD~1 && ./scripts/deploy.sh'
```

---

## Anti-patterns / common bugs

- **Building the frontend without copying `dist/` into `backend/public/`.** Backend serves an empty SPA and you'll spend 30 minutes wondering why the page is blank. The deploy script handles this; if you build by hand, don't skip the copy.
- **Same port for prod and dev** — the second unit silently fails to bind and restarts in a loop. Check `journalctl` if a unit won't stay up.
- **No `Environment=PATH=...` in the unit.** The app starts, but the moment it shells out (e.g. to `git`, `gh`, `mongodump`) it gets ENOENT. systemd's default `PATH` is empty.
- **Forgetting `sudo caddy validate` before `reload`.** A typo in any Caddy block crashes the reload and every site on the box goes down. Validate first.
- **Putting secrets in the systemd unit's `Environment=` lines** instead of `EnvironmentFile=`. Systemd unit content is world-readable. `EnvironmentFile=` reads from a 600-permissioned file owned by the service user.
- **Inheriting `After=docker.service` from an old template.** If this app doesn't use Docker, drop those lines — they create a phantom dependency that can delay boot.

---

## Companion skills

- **`monolith-setup`** — the app architecture this skill assumes (NestJS serves the SPA from `backend/public/` via `ServeStaticModule`). Run first to scaffold.
- **`hetzner-monolith-deploy`** — sibling deploy skill, **new dedicated server** scenario (Docker + Watchtower + B2 backups).
- **`deployment-setup`** — sibling deploy skill, **existing Portainer + NPM** host scenario.
- **`logging-setup`** — adds structured JSON logs alongside the journal output; helpful once `journalctl` per service grows noisy.
- **`setup-guide-page`** — an in-app `/setup` page with live health checks for env / disk / proxy / systemd — pair after the first deploy.
- **`pwa-setup`** — once the app is live, optionally make it installable; orthogonal to this skill.

---
name: "CloudPanel Site Add"
description: "Add a WordPress / WooCommerce site to an existing multi-tenant CloudPanel host on Hetzner. One repeatable run per site, idempotent, with optional Hostinger-migration mode that sets up an sslip.io alias + LE cert + wp-config overrides for pre-DNS Migrate Guru access. Use when onboarding a new tenant to cloudpanel-1 (or any CloudPanel 6.x host), whether greenfield or migrating from Hostinger. Auto-picks MySQL native vs MariaDB-Docker sidecar based on source DB collation."
---

# CloudPanel Site Add

## What This Skill Does

Adds one WordPress / WooCommerce tenant to an existing CloudPanel host in a single repeatable run:

1. Pre-flights the host (CloudPanel healthy, free port for the DB sidecar, no name collisions).
2. Creates the site (Linux user + nginx vhost + PHP-FPM pool + WordPress files).
3. Creates the database — **MySQL native** (CloudPanel's `:3306`) **or** a per-site **MariaDB 11.4 Docker sidecar** on `127.0.0.1:330X` when the source uses Hostinger's `utf8mb3_uca1400_*` collations.
4. (Migration mode only) Adds a `<slug>.<dashed-ip>.sslip.io` alias to the nginx vhost, issues a real Let's Encrypt cert for it via certbot, and injects temporary `WP_HOME` / `WP_SITEURL` overrides in `wp-config.php` so Migrate Guru and you can reach the destination over HTTPS before DNS is flipped.
5. Verifies everything (HTTP 200, valid cert, DB `SELECT 1`, PHP-FPM pool active, ownership), then prints a single parseable **OUTPUTS** block for piping into [`cloudflare-dns-setup`](../cloudflare-dns-setup/) and [`wp-migrate-guru-import`](../wp-migrate-guru-import/).

The site-user and DB passwords are **generated, printed once, and never stored** in any agent memory file. Save them to your vault when the run prints them.

## When to Use

- Onboarding a brand-new WP/WooCommerce site to **cloudpanel-1** (`178.105.177.37`) or any other multi-tenant CloudPanel 6.x host.
- Migrating a site from **Hostinger** to that host — the migration mode handles the DNS chicken-and-egg.
- Re-running after an aborted previous attempt — the skill is **idempotent** and will skip steps whose outputs already exist.

## When NOT to Use

- Brand-new server (no CloudPanel installed) → run `hetzner-cloudpanel-provision` first.
- Non-WordPress PHP app → use `clpctl site:add:php --vhostTemplate=Generic` directly; this skill assumes WP layout.
- Static site / Node app → use `clpctl site:add:static` or `clpctl site:add:nodejs`.

## Prerequisites

- SSH root access to a Hetzner host running **CloudPanel 6.x** with **MySQL 8.4** native (default install).
- **Docker** installed on the host (only needed when `db_engine=mariadb-docker`; check with `docker --version`).
- **certbot** installed (only needed in migration mode; `apt install -y certbot` if missing).
- A `~/.ssh/<key>` that can reach `root@<host_ip>` — every command in this skill assumes `root` and runs over SSH.
- The host has at least **~2 GB free disk** and (for `mariadb-docker`) **~250 MB free RAM** per sidecar container.

---

## Inputs (collect once before Step 1)

| Var | Example | Notes |
|---|---|---|
| `HOST_IP` | `178.105.177.37` | The CloudPanel server's public IPv4 |
| `DOMAIN` | `madomarche.com` | Bare apex, no scheme, no `www.` |
| `SITE_USER` | `madomarche` | **Lowercase, no dots**, ≤ 32 chars. Used as Linux user, nginx pool, and DB user. |
| `PHP_VERSION` | `8.3` | One of CloudPanel's installed PHP versions (`ls /etc/php/`). Default `8.3` covers current WooCommerce. |
| `DB_ENGINE` | `mysql` \| `mariadb-docker` | See decision rule below. |
| `MARIADB_PORT` | `3307` | Only for `mariadb-docker`. First free port ≥ 3307; the skill auto-picks if unset. |
| `MODE` | `greenfield` \| `migration` | `migration` enables the sslip.io alias + LE cert + wp-config overrides. |

### Picking `DB_ENGINE`

| Source | Pick |
|---|---|
| Greenfield (no source DB) | `mysql` |
| Source on **Hostinger** with `SHOW VARIABLES LIKE 'version'` returning **MariaDB ≥ 10.10** | `mariadb-docker` |
| Source on Hostinger with **MySQL** (rare) | `mysql` |
| Unsure | Default to `mariadb-docker` if migrating from Hostinger — costs ~250 MB RAM but avoids the `utf8mb3_uca1400_ai_ci` failure mode documented in [[hostinger-mariadb-collation]] |

---

## Step 1 — Pre-flight (idempotency gates)

Run on the host (replace `${...}` with values from the table above):

```bash
ssh root@${HOST_IP} bash <<'CHECK'
set -e
# CloudPanel healthy?
clpctl --version | grep -q CloudPanel || { echo "FAIL: clpctl missing"; exit 1; }
# PHP version installed?
[ -d "/etc/php/${PHP_VERSION}" ] || { echo "FAIL: PHP ${PHP_VERSION} not installed"; exit 1; }
# Site user already exists? (=> site already created — skill will skip create steps)
id "${SITE_USER}" 2>/dev/null && echo "EXISTING site user — will be idempotent" || echo "NEW site"
# Docker available if needed?
if [ "${DB_ENGINE}" = "mariadb-docker" ]; then
  docker --version | grep -q Docker || { echo "FAIL: docker missing for mariadb-docker"; exit 1; }
fi
# Free RAM > 250 MB?
free -m | awk 'NR==2 {if ($7 < 250) {print "WARN: <250MB free RAM"; exit 0}}'
CHECK
```

For `mariadb-docker`, auto-pick the next free port if `MARIADB_PORT` not set:

```bash
ssh root@${HOST_IP} 'for p in 3307 3308 3309 3310 3311; do ss -ltn "sport = :$p" | grep -q LISTEN || { echo $p; break; }; done'
```

## Step 2 — Create the CloudPanel site

`clpctl site:add:php` is idempotent-by-collision (returns non-zero "site exists" — caught and skipped):

```bash
SITE_USER_PW=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)

ssh root@${HOST_IP} "clpctl site:add:php \
  --domainName='${DOMAIN}' \
  --phpVersion='${PHP_VERSION}' \
  --vhostTemplate='WordPress' \
  --siteUser='${SITE_USER}' \
  --siteUserPassword='${SITE_USER_PW}'" || \
  ssh root@${HOST_IP} "id ${SITE_USER}" >/dev/null  # confirm pre-existing
```

CloudPanel creates `/home/${SITE_USER}/htdocs/${DOMAIN}/`, the nginx vhost (`/etc/nginx/sites-enabled/${DOMAIN}.conf`), and the PHP-FPM pool. `vhostTemplate=WordPress` applies WP-friendly rewrites; if your CloudPanel version lacks it (older 6.x), fall back to `--vhostTemplate=Generic`.

Download WordPress core files if not already present (via wp-cli as the site user):

```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=/home/${SITE_USER}/htdocs/${DOMAIN} \
  core download --skip-content --force"
```

`--skip-content` skips default themes/plugins (Migrate Guru will overwrite them anyway in migration mode; for greenfield, drop the flag).

## Step 3 — Create the database

### 3a. MySQL native (`DB_ENGINE=mysql`)

```bash
DB_NAME="${SITE_USER}_db"
DB_USER="${SITE_USER}"
DB_PW=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)

ssh root@${HOST_IP} "clpctl db:add \
  --domainName='${DOMAIN}' \
  --databaseName='${DB_NAME}' \
  --databaseUserName='${DB_USER}' \
  --databaseUserPassword='${DB_PW}'" || \
  ssh root@${HOST_IP} "mysql -e \"SHOW DATABASES\" | grep -q ${DB_NAME}"

DB_HOST="127.0.0.1"
DB_PORT="3306"
```

### 3b. MariaDB-Docker sidecar (`DB_ENGINE=mariadb-docker`)

Per [[hostinger-mariadb-collation]] — one container per migrated tenant, bound to `127.0.0.1:${MARIADB_PORT}` only:

```bash
DB_NAME="${SITE_USER}"
DB_USER="${SITE_USER}"
DB_PW=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
ROOT_PW=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)

# Idempotent: if container exists, skip create
ssh root@${HOST_IP} "docker ps -a --format '{{.Names}}' | grep -q '^mariadb-${SITE_USER}$'" || \
ssh root@${HOST_IP} "docker run -d \
  --name mariadb-${SITE_USER} \
  --restart unless-stopped \
  -p 127.0.0.1:${MARIADB_PORT}:3306 \
  -v mariadb-${SITE_USER}-data:/var/lib/mysql \
  -e MARIADB_ROOT_PASSWORD='${ROOT_PW}' \
  -e MARIADB_DATABASE='${DB_NAME}' \
  -e MARIADB_USER='${DB_USER}' \
  -e MARIADB_PASSWORD='${DB_PW}' \
  -e MARIADB_CHARACTER_SET_SERVER=utf8mb4 \
  -e MARIADB_COLLATION_SERVER=utf8mb4_unicode_ci \
  mariadb:11.4 \
  --max_allowed_packet=256M \
  --innodb_buffer_pool_size=512M"

# Wait for readiness
for i in $(seq 1 30); do
  ssh root@${HOST_IP} "docker exec mariadb-${SITE_USER} mariadb-admin ping -p${ROOT_PW} 2>/dev/null" && break
  sleep 2
done

DB_HOST="127.0.0.1"
DB_PORT="${MARIADB_PORT}"
```

Document the sidecar in the host's `/root/SERVER_NOTES.md` (one-line per tenant) so future ops know about it — see the `madomarche-migration` memory for the convention.

## Step 4 — Wire `wp-config.php`

Only if WP files were freshly downloaded in Step 2 (skip on idempotent re-run):

```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=/home/${SITE_USER}/htdocs/${DOMAIN} \
  config create \
  --dbname='${DB_NAME}' \
  --dbuser='${DB_USER}' \
  --dbpass='${DB_PW}' \
  --dbhost='${DB_HOST}:${DB_PORT}' \
  --skip-check \
  --extra-php <<PHP
define('WP_DEBUG', false);
define('DISALLOW_FILE_EDIT', true);
PHP"
```

The `${DB_HOST}:${DB_PORT}` form works in WP for both MySQL on `:3306` and the MariaDB sidecar on `:${MARIADB_PORT}`.

## Step 5 — Migration mode extras (skip if `MODE=greenfield`)

### 5a. Append sslip.io alias to nginx server_name

CloudPanel's UI may not expose Domain Aliases in 6.x; edit the vhost directly. Idempotent: `grep` first.

```bash
SSLIP="${SITE_USER}.$(echo ${HOST_IP} | tr . -).sslip.io"
VHOST="/etc/nginx/sites-enabled/${DOMAIN}.conf"

ssh root@${HOST_IP} "
  grep -q '${SSLIP}' '${VHOST}' || \
  sed -i 's/server_name ${DOMAIN} www[0-9]*\.${DOMAIN};/server_name ${DOMAIN} www.${DOMAIN} ${SSLIP};/g' '${VHOST}'
  nginx -t && systemctl reload nginx
"
```

### 5b. Issue a Let's Encrypt cert for the sslip.io and install it on the site

```bash
ssh root@${HOST_IP} "
  certbot certonly --webroot \
    -w /home/${SITE_USER}/htdocs/${DOMAIN} \
    -d '${SSLIP}' \
    --non-interactive --agree-tos --register-unsafely-without-email \
    --preferred-challenges http-01
  LE=/etc/letsencrypt/live/${SSLIP}
  clpctl lets-encrypt:install:certificate \
    --domainName='${DOMAIN}' \
    --privateKey=\$LE/privkey.pem \
    --certificate=\$LE/cert.pem \
    --certificateChain=\$LE/chain.pem
"
```

### 5c. Inject temporary `WP_HOME` / `WP_SITEURL` overrides in wp-config.php

The marker `MIGRATION_TEMP_OVERRIDE` lets `wp-post-migration-fixup` find and strip the block later.

```bash
WPCONF="/home/${SITE_USER}/htdocs/${DOMAIN}/wp-config.php"

ssh root@${HOST_IP} "
  grep -q MIGRATION_TEMP_OVERRIDE '${WPCONF}' || \
  python3 -c \"
import re
p='${WPCONF}'
s=open(p).read()
inj='''
// MIGRATION_TEMP_OVERRIDE - remove after DNS cutover (see wp-post-migration-fixup)
define('WP_HOME',    'https://${SSLIP}');
define('WP_SITEURL', 'https://${SSLIP}');
'''
open(p,'w').write(re.sub(r'(<\\?php\\s*\\n)', r'\\1'+inj+'\\n', s, count=1))
\"
  chown ${SITE_USER}:${SITE_USER} '${WPCONF}'
  chmod 640 '${WPCONF}'
"
```

## Step 6 — Verification

Each check is independent. A skipped subset is OK if you know the cause (e.g. greenfield won't have the sslip.io cert).

```bash
# DB reachable + auth works (matches both MySQL and MariaDB sidecar)
ssh root@${HOST_IP} "mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} -e 'SELECT 1' >/dev/null && echo 'DB OK'"

# PHP-FPM pool active for site user
ssh root@${HOST_IP} "systemctl is-active php${PHP_VERSION}-fpm | grep -q active && echo 'FPM OK'"

# File ownership + perms (dirs 750, files 640)
ssh root@${HOST_IP} "find /home/${SITE_USER}/htdocs/${DOMAIN} -maxdepth 1 -not -uid \$(id -u ${SITE_USER}) | head -1 | xargs -r echo 'OWNERSHIP WRONG:'"

# HTTPS reachable + cert valid (sslip.io URL in migration mode, real domain in greenfield-with-DNS)
TEST_URL=$([ "${MODE}" = migration ] && echo "https://${SSLIP}/" || echo "https://${DOMAIN}/")
curl -sk -o /dev/null -m 15 -w "HTTPS %{http_code} ssl_verify=%{ssl_verify_result}\n" "${TEST_URL}"
```

## Step 7 — Print OUTPUTS block

Print this exact block at the end so the next skill in the chain can `grep -A 10 OUTPUTS_BEGIN` to parse it:

```
OUTPUTS_BEGIN
DOMAIN=madomarche.com
HOST_IP=178.105.177.37
SITE_USER=madomarche
DOCROOT=/home/madomarche/htdocs/madomarche.com
PHP_VERSION=8.3
DB_ENGINE=mariadb-docker
DB_HOST=127.0.0.1
DB_PORT=3307
DB_NAME=madomarche
DB_USER=madomarche
SSLIP_URL=https://madomarche.178-105-177-37.sslip.io     # migration mode only
MODE=migration
OUTPUTS_END

CREDENTIALS_BEGIN  -- shown ONCE, save to your vault now
SITE_USER_PASSWORD=<the openssl rand value>
DB_USER_PASSWORD=<the openssl rand value>
MARIADB_ROOT_PASSWORD=<the openssl rand value>      # mariadb-docker only
CREDENTIALS_END
```

The credential block must NEVER be written to a memory file. If the user closes the terminal without saving, regenerate them via `clpctl user:reset:password`, `clpctl db:add ... --databaseUserPassword=...` (re-create), or `docker exec mariadb-... mariadb -uroot -p... -e "ALTER USER ..."`.

---

## Idempotency contract

The skill MUST be safe to re-run after partial failure. Each step's guard:

| Step | Idempotency check |
|---|---|
| 2 (site create) | `id ${SITE_USER}` → if exists, skip `clpctl site:add:php` |
| 2 (WP download) | `[ -f /home/${SITE_USER}/htdocs/${DOMAIN}/wp-load.php ]` → if exists, skip |
| 3a (MySQL DB) | `mysql -e "SHOW DATABASES" \| grep -q ${DB_NAME}` |
| 3b (MariaDB container) | `docker ps -a --format '{{.Names}}' \| grep -q "^mariadb-${SITE_USER}$"` |
| 4 (wp-config) | `[ -f wp-config.php ]` → if exists, skip `wp config create` |
| 5a (nginx alias) | `grep -q "${SSLIP}" "${VHOST}"` |
| 5b (LE cert) | `[ -d /etc/letsencrypt/live/${SSLIP} ]` |
| 5c (wp-config override) | `grep -q MIGRATION_TEMP_OVERRIDE wp-config.php` |

A re-run prints `SKIP` for each guarded step. The OUTPUTS block at the end is **always** printed (using current state, not freshly generated values).

---

## Common pitfalls (from real cloudpanel-1 migrations)

- **`Could not open input file: /home/clp/htdocs/app/files/bin/clpctl`** — install of CloudPanel was interrupted. Re-run `bash /root/install.sh` to finish.
- **`server_type=cax31 → error during placement`** at provision time — ARM stock is out. Fall back to CPX32 x86 and run this skill identically; CloudPanel doesn't care about CPU arch.
- **Hostinger source has duplicated theme files** (e.g. WoodMart's 9 coexisting `class XYZ` files). nginx + PHP-FPM fatals on the second `class` declaration where LiteSpeed tolerated it. Enable `WP_DEBUG_LOG` and dedupe via `wp-content/debug.log` — see [[madomarche-migration]] for the WoodMart case.
- **MariaDB sidecar `mariadb-admin ping` hangs** when `MARIADB_ROOT_PASSWORD` is too short or contains shell-special chars. Use the `openssl rand -base64 32 | tr -d '/+=' | cut -c1-32` form above.
- **certbot HTTP-01 returns 301 to HTTPS** during validation — this is FINE; Let's Encrypt follows redirects and skips cert validation during the challenge fetch, even when the destination cert is self-signed.
- **`ssl_stapling ignored, issuer certificate not found`** warning after first cert install — cosmetic; CloudPanel ships the chain on the next renewal cycle. Or copy `chain.pem` next to `cert.pem` and reload nginx.

---

## Outputs (consumed by paired skills)

```
{
  "domain": "<DOMAIN>",
  "host_ip": "<HOST_IP>",
  "site_user": "<SITE_USER>",
  "docroot": "/home/<SITE_USER>/htdocs/<DOMAIN>",
  "php_version": "<PHP_VERSION>",
  "db": { "engine": "<DB_ENGINE>", "host": "<DB_HOST>", "port": <DB_PORT>, "name": "<DB_NAME>", "user": "<DB_USER>" },
  "sslip_url": "<https://...sslip.io>",         // migration mode only
  "mode": "greenfield" | "migration"
}
```

## Pairs Well With

- **[`cloudflare-dns-setup`](../cloudflare-dns-setup/)** — next step. Reads `DOMAIN` + `HOST_IP` from the OUTPUTS block; sets up the zone, A/CNAME, MX/SPF/DKIM/DMARC, CAA for Let's Encrypt, and prints the nameservers to set at the registrar.
- **[`wp-migrate-guru-import`](../wp-migrate-guru-import/)** *(migration only)* — uses the `SSLIP_URL` as the destination Migrate Guru can reach over HTTPS while real DNS still points to the source host.
- **[`wp-post-migration-fixup`](../wp-post-migration-fixup/)** *(migration only)* — runs once DNS is live: `wp search-replace SSLIP_URL DOMAIN`, removes the `MIGRATION_TEMP_OVERRIDE` block, reissues a real LE cert for `${DOMAIN}` + `www.${DOMAIN}`, smoke-tests the live site.
- **[`nightly-backup-wp-cron`](../nightly-backup-wp-cron/)** — installs `/usr/local/bin/${SITE_USER}-backup.sh` + cron entry, DB dump (auto-detects MySQL vs `docker exec mariadb-<site>`) + files tarball, 7-day rotation.
- **[`hostinger-mariadb-sidecar`](../hostinger-mariadb-sidecar/)** — the dedicated skill for the MariaDB-Docker pattern this skill embeds inline. Use it standalone if you need to add a MariaDB sidecar to an already-existing site (not creating a new one).
- **[`uptime-kuma-add-monitor`](../uptime-kuma-add-monitor/)** — registers an HTTP + cert-expiry monitor on the shared Uptime Kuma instance for the new domain.

## References

### Sidecar reference files (loaded on demand)

- [`references/clpctl-cheatsheet.md`](./references/clpctl-cheatsheet.md) — every CloudPanel CLI command this skill uses, plus the adjacent ones (`db:show:master-credentials`, `user:add`, `vhost-template:view`, etc.), with idempotency notes and exit-code semantics.
- [`references/wp-cli-cheatsheet.md`](./references/wp-cli-cheatsheet.md) — WP-CLI invocation patterns including the `sudo -u ${SITE_USER} -i wp --path=...` wrapper, the WooCommerce-safe `search-replace --precise --skip-columns=guid` recipe, and the WP_DEBUG_LOG troubleshooting flow.
- [`references/troubleshooting.md`](./references/troubleshooting.md) — extended pitfalls beyond the SKILL.md quick-list (MariaDB sidecar hangs, Migrate Guru "partial but reachable" failures, the WoodMart 9-class-files case, plugin auto-update during migration).

Open the relevant one when you hit that subject — they stay out of context until you ask for them.

### Memory notes (background knowledge in the operator's vault)

- [[cloudpanel-1-multi-tenant-host]] — the actual host this skill targets
- [[hostinger-mariadb-collation]] — full rationale for the MariaDB-Docker pattern + alternative fixes
- [[hetzner-smtp-port-blocked]] — outbound 25/465 blocked, use 587+STARTTLS; relevant after migration when WP transactional mail fails
- [[madomarche-migration]] — first production run of this skill (madomarche.com + armadorn.com on cloudpanel-1, 2026-05-31)

### External

- CloudPanel CLI reference: https://www.cloudpanel.io/docs/v2/cli/
- WP-CLI handbook: https://make.wordpress.org/cli/handbook/

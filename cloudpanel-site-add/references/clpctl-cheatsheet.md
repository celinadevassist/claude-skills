# clpctl Cheatsheet

Sidecar reference for the CloudPanel CLI commands the `cloudpanel-site-add` skill uses, plus the adjacent ones you'll reach for during operations. Loaded on demand — open this when you need a specific command syntax or behaviour clarification.

CloudPanel CLI version this targets: **6.x** (verified against 6.0.8). Older 2.x may differ.

---

## Quick orientation

`clpctl` is a single binary at `/usr/bin/clpctl` (shim) → `/home/clp/htdocs/app/files/bin/clpctl` (the real Symfony app). Run as **root**. There's no per-user shell, no daemon — it's a one-shot command that talks to MySQL + writes to `/etc/nginx/sites-enabled/`.

List all commands: `clpctl` (no args). The interesting groups are `site`, `db`, `lets-encrypt`, `user`, `vhost-templates`.

```bash
# Health probe (use as the pre-flight check in any skill that touches CloudPanel)
clpctl --version              # → "CloudPanel CLI 6.0.8 (env: prod, debug: false) ..."
```

---

## site: — creating + deleting sites

CloudPanel has no `site:add:wordpress` in 6.x — WordPress sites are PHP sites with a specific vhost template. The web UI's "Create a WordPress Site" wizard wraps `site:add:php` + WP-CLI download internally.

```bash
# Add a PHP site (WordPress is just PHP under the hood)
clpctl site:add:php \
  --domainName='example.com' \
  --phpVersion='8.3' \
  --vhostTemplate='WordPress' \
  --siteUser='example' \
  --siteUserPassword='<strong-pw>'
```

**Args:**
- `--domainName` — bare apex (`example.com`, not `www.example.com`, not `https://...`)
- `--phpVersion` — must be installed; check `ls /etc/php/` (typical: `7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5`)
- `--vhostTemplate` — see `clpctl vhost-templates:list`. Useful values:
  - `WordPress` — WP-aware rewrites + LiteSpeed/Cache friendly (preferred for WP)
  - `Generic` — vanilla PHP, no special rewrites
  - `Laravel 11/12`, `Magento 2`, `Drupal 10/11`, `Joomla 6`, `Nextcloud 32`, `Moodle 5`, etc.
- `--siteUser` — lowercase, no dots, ≤32 chars; becomes the Linux user and FPM pool name
- `--siteUserPassword` — used for SSH/SFTP under that user. Generated, printed once, never stored.

**What it creates:**
- Linux user `${SITE_USER}` (UID auto-assigned)
- `/home/${SITE_USER}/htdocs/${DOMAIN}/` (docroot)
- `/home/${SITE_USER}/logs/` (nginx + PHP-FPM logs)
- nginx vhost: `/etc/nginx/sites-enabled/${DOMAIN}.conf`
- PHP-FPM pool: `/etc/php/${PHP_VERSION}/fpm/pool.d/${SITE_USER}.conf`
- Self-signed cert at `/etc/nginx/ssl-certificates/${DOMAIN}.{crt,key}` until LE is issued

**Idempotency:** `clpctl site:add:php` exits non-zero if the site exists. Detect by `id ${SITE_USER}` BEFORE calling.

```bash
clpctl site:delete --domainName='example.com'
```

Removes everything: nginx vhost, Linux user, home dir, PHP-FPM pool, and the per-site DB if it exists. **Destructive — no confirmation prompt.**

---

## db: — databases (MySQL native only)

CloudPanel manages CloudPanel's **own** MySQL 8.4 instance on `:3306`. For the MariaDB-Docker sidecar pattern, see `references/mariadb-sidecar.md` (not this file) — those DBs are NOT visible to `clpctl db:*`.

```bash
clpctl db:show:master-credentials
# Prints root user + password for the MySQL master account
# WRITE THIS DOWN ONCE — re-reading prints to stdout in plaintext

clpctl db:add \
  --domainName='example.com' \
  --databaseName='example_db' \
  --databaseUserName='example' \
  --databaseUserPassword='<strong-pw>'
# Creates the DB + a user with ALL privs on it; links to the site for UI display

clpctl db:export --databaseName='example_db' --file=/tmp/dump.sql.gz
clpctl db:import --databaseName='example_db' --file=/tmp/dump.sql.gz
clpctl db:delete --databaseName='example_db'
```

**Idempotency:** Catch by `mysql -e "SHOW DATABASES" | grep -q ${DB_NAME}` before `db:add`.

---

## lets-encrypt: — TLS certificates

```bash
clpctl lets-encrypt:install:certificate \
  --domainName='example.com' \
  --subjectAlternativeName='www.example.com,api.example.com'
```

**Critical behaviour:** the cert is issued for `domainName` + all SANs. **EVERY name must resolve to this server's public IP** at issuance time, or LE's HTTP-01 challenge fails and the whole command rolls back. There's no `--ignore-failing-domains` flag.

This is why the `cloudpanel-site-add` skill uses `certbot certonly --webroot` directly for the sslip.io migration cert — certbot lets you issue for a single domain that DOES resolve, and we install it as the site cert via `clpctl site:install:certificate` (below).

**For a real-DNS cert after cutover:** the live DNS at the new server's IP makes LE happy, and `clpctl lets-encrypt:install:certificate` works as advertised.

```bash
clpctl site:install:certificate \
  --domainName='example.com' \
  --privateKey=/etc/letsencrypt/live/<le-domain>/privkey.pem \
  --certificate=/etc/letsencrypt/live/<le-domain>/cert.pem \
  --certificateChain=/etc/letsencrypt/live/<le-domain>/chain.pem
```

Use this to install a cert issued OUTSIDE clpctl (certbot, manual, etc.). Replaces the site's current cert atomically; reloads nginx automatically.

---

## user: — CloudPanel admin users (not site users!)

These are the people who can log into `https://<host>:8443`. Distinct from `site:add:php`'s `--siteUser` (those are Linux/SFTP users with no CloudPanel UI access).

```bash
clpctl user:list

clpctl user:add \
  --userName='jane.doe' \
  --email='jane@company.com' \
  --firstName='Jane' --lastName='Doe' \
  --password='<strong-pw>' \
  --role='admin' \
  --sites='example.com,api.example.com' \
  --timezone='UTC' \
  --status='1'

clpctl user:reset:password --userName='jane.doe' --password='<new-pw>'
clpctl user:disable:mfa     --userName='jane.doe'
clpctl user:delete          --userName='jane.doe'
```

**Roles:** `admin` (full) | `user` (scoped to `--sites` list).

---

## vhost-templates: — what's available

```bash
clpctl vhost-templates:list
# Includes: WordPress, Generic, Laravel 11/12, Magento 2, Drupal 10/11,
#           Joomla 6, Nextcloud 32, OwnCloud 12, Moodle 5, CodeIgniter 4,
#           CakePHP 5, Contao 4, Laminas, Matomo 5, Mautic 6, Neos 9, ...

clpctl vhost-template:view --name='WordPress'
# Prints the actual nginx config snippet that gets dropped into the site vhost

clpctl vhost-template:add  --name='Custom App' --file=/tmp/template.tpl
clpctl vhost-template:delete --name='Custom App'
```

**Editing a system template** (e.g. WordPress) requires saving the modified version under a new name — system templates are read-only. Custom templates land in `/home/clp/var/app-data/vhost-templates/user/`.

---

## cloudpanel: — panel itself

```bash
clpctl cloudpanel:enable:basic-auth  --userName='john.doe' --password='<pw>'
clpctl cloudpanel:disable:basic-auth
clpctl cloudpanel:set:release-channel --channel='test'
# channel: stable (default) | test (pre-release builds)
```

Basic-auth wraps the panel URL (`https://<host>:8443`) with an HTTP-auth layer BEFORE the login form. Useful for shared CloudPanel hosts when you want a second gate.

---

## cloudflare: — IP list refresh

```bash
clpctl cloudflare:update:ips
# Pulls the current Cloudflare IP ranges and updates nginx's real-IP module
# so the X-Forwarded-For from CF proxied (orange-cloud) requests resolves correctly.
```

Only matters when you flip a site to orange-cloud. See `[[cloudflare-proxy-preference]]` for why cloudpanel-1 sites stay grey.

---

## Output format gotcha

Most `clpctl` commands print human-prose ("Site has been created.", "Certificate installation was successful.") on success. **Failures dump a Symfony JSON exception** with the message, stack info, level, channel, datetime. Detect failures by either:

```bash
# Exit code (most reliable)
clpctl site:add:php ... ; if [ $? -ne 0 ]; then echo FAILED; fi

# Or grep the JSON in stderr → stdout merge
clpctl site:add:php ... 2>&1 | grep -q '"level":500' && echo FAILED
```

There's no `--json` flag for clean machine-readable success output — Symfony decided humans get plaintext, errors get JSON, end of story. Plan around it.

---

## Common syntax errors

| Symptom | Cause | Fix |
|---|---|---|
| `Could not open input file: /home/clp/htdocs/app/files/bin/clpctl` | CloudPanel install interrupted (deb postinst didn't finish) | Re-run `bash /root/install.sh` |
| `Command "site:list" is not defined` | 6.x removed `site:list` | Use `ls /home/*/htdocs/` or `ls /etc/nginx/sites-enabled/` |
| `The collation utf8mb3_uca1400_ai_ci is not supported` | Importing a Hostinger dump into MySQL 8 | See `[[hostinger-mariadb-collation]]` — switch to mariadb-docker sidecar |
| `Domain name is already in use` from `site:add:php` | Site exists from a previous run | Idempotency check: `id ${SITE_USER}` before calling |
| `Vhost template "WordPress" not found` | Older 6.x | Fall back to `--vhostTemplate=Generic`, install WP via wp-cli |

---

## See also

- [WP-CLI Cheatsheet](./wp-cli-cheatsheet.md) — the WordPress-side companion (`wp config create`, `wp search-replace`, etc.)
- [Troubleshooting](./troubleshooting.md) — beyond the SKILL.md's quick-list
- CloudPanel official CLI docs: https://www.cloudpanel.io/docs/v2/cli/

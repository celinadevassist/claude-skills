# Troubleshooting

Extended troubleshooting beyond the SKILL.md's quick "Common pitfalls" list. Each entry: **symptom**, **root cause**, **fix** with verifiable commands.

---

## CloudPanel / clpctl

### "Could not open input file: /home/clp/htdocs/app/files/bin/clpctl"

**Symptom:** `clpctl` prints that error and exits, even though the shim at `/usr/bin/clpctl` is present.

**Cause:** the CloudPanel deb install was interrupted (the postinst step that drops the real app under `/home/clp/htdocs/app/` didn't complete). Common when `/root/install.sh` was killed or the server ran out of memory mid-install.

**Fix:**
```bash
ls -la /home/clp/htdocs/app/files/bin/   # should contain clpctl as executable
[ ! -f /home/clp/htdocs/app/files/bin/clpctl ] && bash /root/install.sh   # idempotent — resumes
clpctl --version   # verify after re-run
```

If `/root/install.sh` is gone, re-fetch: `curl -sS https://installer.cloudpanel.io/ce/v2/install.sh -o /root/install.sh`.

---

### `vhostTemplate "WordPress" not found`

**Symptom:** `clpctl site:add:php --vhostTemplate=WordPress` fails despite WordPress being a documented option.

**Cause:** older CloudPanel 6.x ships only the system templates listed in `clpctl vhost-templates:list`; WordPress lands later. Or the template was deleted by someone.

**Fix:** verify with `clpctl vhost-templates:list | grep WordPress`. If absent:
- Option A: Use `--vhostTemplate=Generic` and run wp-cli to install WordPress. The Generic template handles WP fine; you lose only some Cache plugin auto-tuning.
- Option B: Import the WordPress template from a working CloudPanel:
  ```bash
  scp /etc/nginx/sites-enabled/<existing-wp-site>.conf root@<other-host>:/tmp/  # NO — wrong file
  # Templates live under /home/clp/htdocs/app/files/Web/templates/. Copy the WordPress.tpl:
  scp /home/clp/htdocs/app/files/Web/templates/WordPress.tpl root@<this-host>:/tmp/
  ssh <this-host> "clpctl vhost-template:add --name='WordPress' --file=/tmp/WordPress.tpl"
  ```

---

### `clpctl` exits 0 but nginx isn't reloaded after a vhost edit

**Symptom:** you edit `/etc/nginx/sites-enabled/<domain>.conf` by hand and reload via `systemctl reload nginx`, but the site behaves as if the edit didn't take.

**Cause:** CloudPanel re-renders the vhost from its DB on certain operations (cert install, PHP version change, vhostTemplate switch), overwriting your manual edits. The render is silent.

**Fix:** keep manual edits idempotent (add-only, grep-guarded). After any `clpctl site:*` or `clpctl lets-encrypt:*` call, re-apply your aliases:

```bash
ssh root@$IP "
  VHOST=/etc/nginx/sites-enabled/${DOMAIN}.conf
  grep -q '${SSLIP}' \$VHOST || sed -i 's/server_name ${DOMAIN};/server_name ${DOMAIN} ${SSLIP};/' \$VHOST
  nginx -t && systemctl reload nginx
"
```

For permanent custom routes, save them as a custom vhost template (`clpctl vhost-template:add`) so CloudPanel uses them on every render.

---

## MariaDB sidecar (Docker)

### `docker run` succeeds but `mariadb-admin ping` hangs forever

**Symptom:** the container is `Up` per `docker ps`, but `docker exec ... mariadb-admin ping -p<root_pw>` never returns.

**Causes & fixes:**

1. **Root password contains shell-special characters** — `!`, `$`, backticks. They got interpolated by the local shell, the container received a different password than expected.
   - Fix: generate with `openssl rand -base64 32 | tr -d '/+=' | cut -c1-32` (the skill's recipe) — only `[A-Za-z0-9]`.

2. **Volume permissions wrong** — `/var/lib/mysql` inside the container owned by `root` instead of `mysql` (uid 999 in mariadb:11.4).
   - Fix: `docker run` with a fresh named volume (not a bind mount) — `-v mariadb-<site>-data:/var/lib/mysql`. Docker creates it with the right perms automatically. If using bind mount, `chown 999:999 /path/to/data` on the host.

3. **MaxConn exhausted** — the first connection succeeded, then the script forks and the 2nd hangs because the container is single-process-init and the entrypoint hasn't finished bootstrapping.
   - Fix: wait for `Ready for connections` in `docker logs mariadb-<site>` before any client. The skill's wait loop catches this; if you're doing it by hand, add `sleep 10` after `docker run`.

---

### Site can't connect to MariaDB sidecar — "MySQL server has gone away"

**Symptom:** WP loads its first request but throws "MySQL server has gone away" on every subsequent one.

**Cause:** WP keeps connections open across requests; the sidecar's `wait_timeout` (default 28800s — 8h) is fine, but `max_allowed_packet` defaults to 16MB. WooCommerce easily sends > 16MB orders (product images attached as base64 in transient meta), connection drops mid-write.

**Fix:** the skill sets `--max_allowed_packet=256M` on `docker run`. Verify:

```bash
docker exec mariadb-${SITE_USER} mariadb -uroot -p${ROOT_PW} -e "SHOW VARIABLES LIKE 'max_allowed_packet'"
# Should print 268435456 (256M)
```

If you need to change it after the fact: stop the container, edit the env, restart. Or `docker exec ... mariadb -e "SET GLOBAL max_allowed_packet=268435456"` (lost on restart).

---

### Backup script's `docker exec ... mariadb-dump` returns 0 but the dump is empty

**Symptom:** `/var/backups/${SITE_USER}/db-*.sql.gz` is ~20 bytes (just the gzip header).

**Cause:** mariadb-dump prints errors to stderr; we piped stdout to `gzip` and silently swallowed the empty result. Common reason: dump ran before the container was ready, so the user auth failed.

**Fix:** validate inside the backup script:

```bash
DUMP=$(docker exec mariadb-${SITE_USER} mariadb-dump -u${DB_USER} -p${DB_PW} ${DB_NAME})
if [ -z "$DUMP" ] || [ "$(echo "$DUMP" | head -c 100)" = "" ]; then
  echo "FAIL: empty dump"; exit 1
fi
echo "$DUMP" | gzip > "$DBFILE"
```

The hardened `nightly-backup-wp-cron` skill ships this check by default.

---

## Migration mode

### Migrate Guru shows "Migration completed" but the site is partial / blank

**Symptom:** the destination admin loads, but pages 404, products missing, theme broken.

**Cause:** Migrate Guru aborts on the first table-level error (most commonly the collation mismatch from `[[hostinger-mariadb-collation]]`) but the green "completed" badge fires on the manifest write, not on actual table-by-table success. Their dashboard hides partial-success state behind a "View Details" expander.

**Fix:**

1. Check the actual destination state — count tables vs expected:
   ```bash
   sudo -u ${SITE_USER} -i wp --path=/path db tables 'wp_*' | wc -l
   # Compare to source: ~30 for vanilla WP, 80-150 for WC + WC extensions
   ```
2. If short, drop the destination DB, recreate it (`clpctl db:delete && clpctl db:add` OR `docker exec mariadb-... mariadb -e "DROP DATABASE; CREATE DATABASE"`), and re-import.
3. If the source uses `utf8mb3_uca1400_*` collations, switch the destination engine BEFORE the next import attempt — see `[[hostinger-mariadb-collation]]`.

**Don't trust the "View" link Migrate Guru shows** — it loads the site through their proxy with cached HTML from before the migration, so it often shows the OLD site looking fine even when the new one is broken.

---

### Site loads but every page redirects to the source domain

**Symptom:** browser hits `https://${SSLIP}/`, gets a 301 redirect to `https://${DOMAIN}/` (which still points at Hostinger).

**Cause:** the WP_HOME / WP_SITEURL overrides in wp-config.php weren't picked up. Either:
- The MIGRATION_TEMP_OVERRIDE block landed AFTER another `define('WP_HOME', ...)` line (PHP uses the FIRST define()), so the second one is silently a noop.
- A caching plugin (LiteSpeed, WP Super Cache) cached the redirect from a previous load.

**Fix:**
```bash
# Verify both constants resolve to sslip.io at WP runtime
sudo -u ${SITE_USER} -i wp --path=/path eval 'echo WP_HOME . "\n" . WP_SITEURL;'
# Should print https://<sslip> twice

# If wrong: re-inject overrides at top of wp-config.php (after <?php), and:
sudo -u ${SITE_USER} -i wp --path=/path cache flush
sudo -u ${SITE_USER} -i wp --path=/path litespeed-purge all  # if LiteSpeed plugin present
```

---

### Live site (after DNS cutover) shows "Error establishing a database connection"

**Symptom:** post-cutover, the new server is reachable, cert is valid, but every page shows the DB error.

**Causes:**

1. **Wrong DB_HOST in wp-config.php after switching from MariaDB sidecar to native MySQL** (or vice versa) — the migration cleanup didn't update the port.
   - Fix: `sudo -u ... wp config get DB_HOST` and compare against the actual listening port.

2. **MariaDB container restarted but bound to a different host port** because we used `-p :3306` (random) instead of `-p 127.0.0.1:3307:3306`.
   - Fix: always use the explicit port form in docker run.

3. **Native MySQL ran out of connections** (default `max_connections=151`) under bot traffic.
   - Fix: `mysql -e "SHOW STATUS LIKE 'Threads_connected'"` to confirm. Raise `max_connections` in `/etc/mysql/mysql.conf.d/cloudpanel.cnf` and restart MySQL.

---

## Theme / plugin migration gotchas

### Fatal error: "Cannot redeclare class X" after migration

**Symptom:** WP-CLI works (it doesn't load theme/plugins), but every browser request returns a blank page or PHP fatal in the error log.

**Cause:** the Hostinger source had silent file duplication — multiple copies of a plugin's PHP files (old + new versions) coexisting under `wp-content/plugins/<plugin>/includes/`. LiteSpeed's OPcache tolerated it because the autoloader cached the first include and skipped the rest. nginx + PHP-FPM 8.x on the new host doesn't, and the second `class WhateverX { ... }` fatals.

**The WoodMart case (madomarche migration):**
```
wp-content/themes/woodmart/inc/integrations/woocommerce/class-product-options.php
wp-content/themes/woodmart/inc/integrations/woocommerce/class-product-options.php.bak
wp-content/themes/woodmart/inc/integrations/woocommerce/class-product-options-old.php
... 9 files in total, all declaring the same class
```

**Fix:**
```bash
# 1. Enable debug logging (see wp-cli-cheatsheet.md → debug-log)
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG_LOG true --raw

# 2. Reproduce the error — visit any page in the browser

# 3. Read the log; find the "Cannot redeclare class X" line + the file paths
tail -200 /path/wp-content/debug.log

# 4. Find ALL files containing that class declaration:
grep -rn "^class WhateverX\b" /path/wp-content/themes/<theme>/

# 5. Keep the file referenced from the theme's main loader (look for include/require lines)
grep -rn "include.*class-whatever-x" /path/wp-content/themes/<theme>/

# 6. Delete the orphans (keep ONE)
rm /path/wp-content/themes/<theme>/inc/...-old.php
rm /path/wp-content/themes/<theme>/inc/...-options.php.bak
```

This is destructive — back up the orphan files first if uncertain:
```bash
mkdir -p /root/migration-cleanup/<theme>/
mv /path/wp-content/themes/<theme>/inc/...-old.php /root/migration-cleanup/<theme>/
```

---

### Plugin auto-update kicked in during migration, broke everything

**Symptom:** Migrate Guru completed clean, but minutes later the site is broken. WP admin shows "Plugin X was automatically updated to 5.2.0."

**Cause:** WordPress 5.5+ auto-updates security releases by default. If the source plugin was on 5.1.3 and 5.2.0 was published yesterday, the destination's first cron tick auto-updates it. If 5.2.0 has a regression incompatible with the theme, you find out the hard way.

**Fix:** disable auto-update during the migration window:

```bash
sudo -u ${SITE_USER} -i wp --path=/path config set AUTOMATIC_UPDATER_DISABLED true --raw
sudo -u ${SITE_USER} -i wp --path=/path config set WP_AUTO_UPDATE_CORE false --raw
```

Re-enable after the site is stable.

---

## See also

- [clpctl Cheatsheet](./clpctl-cheatsheet.md)
- [WP-CLI Cheatsheet](./wp-cli-cheatsheet.md)
- The "Common pitfalls" section in [SKILL.md](../SKILL.md) — quicker-hit list
- `[[madomarche-migration]]` — the first real run, where most of these lessons came from
- `[[hostinger-mariadb-collation]]` — the deep dive on the collation issue
- `[[hetzner-smtp-port-blocked]]` — separate but adjacent gotcha

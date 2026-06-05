# WP-CLI Cheatsheet

Sidecar reference for the WP-CLI commands the `cloudpanel-site-add` skill uses, plus the adjacent ones you'll reach for during a migration or post-cutover fixup. Loaded on demand.

WP-CLI version this targets: **2.10+** (CloudPanel ships 2.10+; pin with `wp cli check-update`).

---

## The one rule: always run as the site user

WP-CLI honours file ownership — running it as `root` writes files owned by `root` and breaks PHP-FPM (which runs as the site user) the next time WP tries to update an option that touches the filesystem.

The right wrapper, used in every command below:

```bash
sudo -u ${SITE_USER} -i wp --path=/home/${SITE_USER}/htdocs/${DOMAIN} <subcommand>
```

`-u ${SITE_USER}` → become the site user. `-i` → load that user's login env (PATH, HOME). `--path=...` → tell WP-CLI where wp-config.php lives (you're not `cd`'d into it).

**Skip the wrapper for read-only checks** (e.g. `wp option get`) if you're in a hurry — root-owned reads work. But never for writes.

---

## Install / scaffold (greenfield)

```bash
# Download core files (no themes/plugins). Use --force if re-running.
sudo -u ${SITE_USER} -i wp --path=/path core download --skip-content [--force]

# Generate wp-config.php (DB creds + salts)
sudo -u ${SITE_USER} -i wp --path=/path config create \
  --dbname='example_db' \
  --dbuser='example' \
  --dbpass='<pw>' \
  --dbhost='127.0.0.1:3306' \
  --skip-check \
  --extra-php <<PHP
define('WP_DEBUG', false);
define('DISALLOW_FILE_EDIT', true);
PHP

# Install WP (this writes the initial admin user — overwritten by Migrate Guru in migration mode)
sudo -u ${SITE_USER} -i wp --path=/path core install \
  --url='https://example.com' \
  --title='Example' \
  --admin_user='admin-temp' \
  --admin_password='<pw>' \
  --admin_email='admin@example.com' \
  --skip-email
```

**Notes:**
- `--dbhost='127.0.0.1:3306'` form covers both the native MySQL and the MariaDB sidecar (just change the port).
- `--skip-check` lets `wp config create` proceed even if the DB isn't reachable yet — useful when wp-cli runs before the MariaDB container is ready.
- `--skip-email` on install skips the "WordPress is set up!" mail to `--admin_email`. Almost always wanted; you can send mail later once SMTP is wired.
- `--skip-content` on core download skips Twenty* themes + Akismet/Hello plugins. Migrate Guru overwrites everything anyway in migration mode.

---

## Config inspection / edits

```bash
sudo -u ${SITE_USER} -i wp --path=/path config list                # → table of constants
sudo -u ${SITE_USER} -i wp --path=/path config get WP_DEBUG        # → "false"
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG true --raw   # --raw = unquoted (booleans, numbers)
sudo -u ${SITE_USER} -i wp --path=/path config delete WP_DEBUG
sudo -u ${SITE_USER} -i wp --path=/path config shuffle-salts       # regenerate the 8 SECRET_KEY/SALT constants
```

The MIGRATION_TEMP_OVERRIDE block uses `config set` for WP_HOME / WP_SITEURL — but for the marker comment, we inject via Python+regex because wp-cli has no "add comment" command.

---

## Options (the wp_options table)

```bash
sudo -u ${SITE_USER} -i wp --path=/path option get siteurl         # → "https://example.com"
sudo -u ${SITE_USER} -i wp --path=/path option get home
sudo -u ${SITE_USER} -i wp --path=/path option update siteurl 'https://example.com'
sudo -u ${SITE_USER} -i wp --path=/path option list --search='*url*' --fields=option_name,option_value
```

**Subtle:** `WP_HOME` / `WP_SITEURL` defined in wp-config.php OVERRIDE the `home` / `siteurl` options in the DB. The skill uses this to keep the DB at `madomarche.com` while WP runtime points at the sslip.io URL — so when the migration is done, just removing the wp-config block reverts WP to the DB values, no DB write needed.

---

## Search-replace (the WooCommerce serialized-data safe one)

```bash
sudo -u ${SITE_USER} -i wp --path=/path search-replace \
  'https://old-host.example' 'https://new-host.example' \
  --skip-columns=guid \
  --report-changed-only \
  --precise           # optional: PHP-side replace instead of SQL REPLACE() — slower but handles serialized strings

# Always dry-run first
sudo -u ${SITE_USER} -i wp --path=/path search-replace 'OLD' 'NEW' --dry-run
```

**Flags that matter:**
- `--skip-columns=guid` — GUID is the original post URL at create-time. RSS readers use it as a unique ID. Changing it would re-trigger every subscriber's "new post" notification. ALWAYS skip.
- `--report-changed-only` — readable output, hides 0-replacement tables
- `--precise` — for WooCommerce, this is the safe default. The fast path uses SQL `REPLACE()` which corrupts serialized PHP strings whose stored byte length is now wrong. `--precise` runs the replace in PHP land where `serialize()` recomputes lengths. ~3-5× slower; use it.
- `--dry-run` — print the table-by-table count without touching anything

**Don't forget the bare-hostname pass:** plugins (especially Yoast SEO, WPRocket) store URLs without scheme. After replacing `https://OLD` → `https://NEW`, also replace `OLD` → `NEW`:

```bash
sudo -u ${SITE_USER} -i wp --path=/path search-replace \
  'old-host.example' 'new-host.example' \
  --skip-columns=guid --report-changed-only --precise
```

This is the line that caught 499 extra replacements in the madomarche migration after the URL-with-scheme pass caught the first 1830.

---

## User management

```bash
sudo -u ${SITE_USER} -i wp --path=/path user list --fields=ID,user_login,user_email,roles
sudo -u ${SITE_USER} -i wp --path=/path user list --role=administrator --field=user_login
sudo -u ${SITE_USER} -i wp --path=/path user update <id|login> --user_pass='<new-pw>'
sudo -u ${SITE_USER} -i wp --path=/path user create john john@example.com --role=editor
sudo -u ${SITE_USER} -i wp --path=/path user delete <id> --reassign=1
```

**Reset the admin password mid-migration** (used by `cloudpanel-site-add` to print a single-use admin login for Migrate Guru install):

```bash
ADMIN=$(sudo -u ${SITE_USER} -i wp --path=/path user list --role=administrator --field=user_login | head -1)
NEWPW=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
sudo -u ${SITE_USER} -i wp --path=/path user update "$ADMIN" --user_pass="$NEWPW"
echo "use ONCE: $ADMIN / $NEWPW"
```

---

## DB export / import (faster than `mysqldump` for WP-only)

```bash
sudo -u ${SITE_USER} -i wp --path=/path db export -                   # to stdout → pipe to gzip
sudo -u ${SITE_USER} -i wp --path=/path db export /tmp/dump.sql       # to file

# Filter only WP tables (skip wp_*_log, custom plugin tables)
sudo -u ${SITE_USER} -i wp --path=/path db export - --tables=$(sudo -u ${SITE_USER} -i wp --path=/path db tables 'wp_*' --format=csv)

# Import
sudo -u ${SITE_USER} -i wp --path=/path db import /tmp/dump.sql

# Other DB helpers
sudo -u ${SITE_USER} -i wp --path=/path db check
sudo -u ${SITE_USER} -i wp --path=/path db optimize
sudo -u ${SITE_USER} -i wp --path=/path db size --tables --human-readable
```

The backup script in `nightly-backup-wp-cron` uses `wp db export -` → `gzip` for the smallest dump (~9.5MB for madomarche).

---

## Cache management

```bash
sudo -u ${SITE_USER} -i wp --path=/path cache flush         # object cache (Redis/Memcached if installed)
sudo -u ${SITE_USER} -i wp --path=/path rewrite flush       # re-write .htaccess + pretty-permalink rules

# Plugin-specific cache flushes (these only work if the plugin is active)
sudo -u ${SITE_USER} -i wp --path=/path litespeed-purge all
sudo -u ${SITE_USER} -i wp --path=/path w3-total-cache flush all
sudo -u ${SITE_USER} -i wp --path=/path wp-rocket clean --post_id=all
```

Always flush after a migration: stale caches will serve pages with the old URL until purged.

---

## Plugins / themes

```bash
sudo -u ${SITE_USER} -i wp --path=/path plugin list
sudo -u ${SITE_USER} -i wp --path=/path plugin install woocommerce --activate
sudo -u ${SITE_USER} -i wp --path=/path plugin update --all
sudo -u ${SITE_USER} -i wp --path=/path plugin deactivate <slug>
sudo -u ${SITE_USER} -i wp --path=/path plugin delete <slug>

sudo -u ${SITE_USER} -i wp --path=/path theme list
sudo -u ${SITE_USER} -i wp --path=/path theme activate <slug>
```

For Migrate Guru: install via the WP admin UI, not `wp plugin install migrate-guru` — the latter doesn't pre-create the BlogVault account link that the plugin needs to register a destination.

---

## Migration-mode flow (post-cutover summary)

Used by `wp-post-migration-fixup` after DNS flips:

```bash
SITE=/home/madomarche/htdocs/madomarche.com
OLD="https://madomarche.178-105-177-37.sslip.io"
NEW="https://madomarche.com"
USER=madomarche

# 1. Search-replace (both URL-with-scheme AND bare-hostname passes)
sudo -u ${USER} -i wp --path="${SITE}" search-replace "${OLD}" "${NEW}" --skip-columns=guid --report-changed-only --precise
sudo -u ${USER} -i wp --path="${SITE}" search-replace "${OLD#https://}" "${NEW#https://}" --skip-columns=guid --report-changed-only --precise

# 2. Flush caches
sudo -u ${USER} -i wp --path="${SITE}" cache flush
sudo -u ${USER} -i wp --path="${SITE}" rewrite flush

# 3. Verify the live values
sudo -u ${USER} -i wp --path="${SITE}" option get siteurl  # should be https://madomarche.com
sudo -u ${USER} -i wp --path="${SITE}" option get home     # should be https://madomarche.com
```

---

## Debug-log troubleshooting

When migration brought over silent duplicates (e.g. WoodMart's 9 coexisting `class XYZ` files — see `[[madomarche-migration]]`), enable debug logging:

```bash
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG true --raw
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG_LOG true --raw
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG_DISPLAY false --raw

# Reproduce the request, then read:
tail -200 /path/wp-content/debug.log

# Restore quiet mode
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG false --raw
sudo -u ${SITE_USER} -i wp --path=/path config set WP_DEBUG_LOG false --raw
```

---

## See also

- [clpctl Cheatsheet](./clpctl-cheatsheet.md) — the CloudPanel-side companion
- [Troubleshooting](./troubleshooting.md) — extended pitfalls
- WP-CLI handbook: https://make.wordpress.org/cli/handbook/

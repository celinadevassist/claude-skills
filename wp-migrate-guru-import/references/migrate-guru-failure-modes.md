# Migrate Guru Failure Modes

Focused troubleshooting reference for the destination-side of a Migrate Guru migration to a CloudPanel host. Each failure mode follows the same shape: **Symptom → Root cause → Detection → Recovery**. Recovery always ends with a re-runnable state, never a half-fixed one.

Open this file the moment the SQL watcher in `SKILL.md` Step 4 plateaus, or any verification in Step 6 fails.

---

## 1. Collation mismatch (MariaDB uca1400 → MySQL 8.4)

**Symptom.** MySQL error log on the destination shows, within the first 1-2 minutes of import:

```
[ERROR] [MY-013140] [Server] Unknown collation: 'utf8mb3_uca1400_ai_ci'
[ERROR] [MY-013140] [Server] Unknown collation: 'utf8mb4_uca1400_ai_ci'
```

The Migrate Guru source-side dashboard typically shows a red error banner like *"Error while creating the table wp_woodmart_wishlist_products. The collation utf8mb3_uca1400_ai_ci is not supported by the destination."* but the wording varies by Migrate Guru version.

**Root cause.** Hostinger's shared WordPress hosting runs MariaDB ≥10.10, which introduced UCA 14.0.0 collations (`*_uca1400_*`). MySQL 8.x — including the MySQL 8.4 that ships native with CloudPanel — does NOT support them and rejects `CREATE TABLE` statements that reference them. See [[hostinger-mariadb-collation]] for the full picture.

**Detection.**
```bash
ssh root@${HOST_IP} 'tail -100 /var/log/mysql/error.log | grep -i uca1400'
```
A single hit is conclusive — Migrate Guru aborts on the first failure.

**Recovery.** Three options, in preference order for cloudpanel-1:

1. **Re-create destination with `DB_ENGINE=mariadb-docker`** (cleanest, used for armadorn). Abort the current migration on the source side, then re-run `cloudpanel-site-add` with `MODE=migration DB_ENGINE=mariadb-docker`. The site keeps its sslip URL + LE cert; only the DB layer swaps to a MariaDB 11.4 sidecar on `127.0.0.1:3307` (or next free port). Then restart from this skill's Step 1.
2. **Convert source DB to utf8mb4 in Hostinger phpMyAdmin** (touches the live source). Run the `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_520_ci` recipe from [[hostinger-mariadb-collation]] on every base table. Total ~3-10 min on a typical WC store; tables lock individually.
3. **Switch tool to All-in-One WP Migration** — auto-translates unknown collations to `utf8mb4_general_ci` on import. Free version has a 512 MB upload limit; bigger files via the `wp-content/ai1wm-backups/` SFTP-copy workaround.

After recovery, drop the destination DB first to avoid stale half-imported tables:
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} db reset --yes"
```

---

## 2. Partial-but-reachable

**Symptom.** Migrate Guru source-side dashboard shows green **"Migration complete"** with a checkmark. You visit `https://${SSLIP_URL}/` and the site loads — maybe the homepage even looks right. But:
- The SQL watcher in Step 4 showed table count well below the source.
- wp-admin shows "table doesn't exist" notices when you visit specific plugin pages.
- A specific product / page / order returns 404 even though it exists on source.
- WC Status → System Status shows missing tables (`wp_actionscheduler_*`, `wp_wc_orders`, etc).

**Root cause.** Migrate Guru fires "complete" on **manifest write**, not on per-table verification. A network blip during the file copy or DB-write phase can leave the migration at 80-95% complete with no error surfaced to either side. The cloud broker (BlogVault) thinks it pushed everything; the destination silently never received the last batch.

**Detection.** Always run SKILL.md Step 6 verification. Specifically, compare:
```bash
# Destination
ssh root@${HOST_IP} "mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} \
  -e \"SHOW TABLES LIKE 'wp\\_%'\" -sN | wc -l"

# Ask operator for source count via Hostinger phpMyAdmin:
#   USE <source_db>; SHOW TABLES LIKE 'wp\_%';   -- and count
```

If destination count < source count, you have a partial. Even a 1-table gap is enough — that 1 table is probably a critical WC subsystem.

**Recovery.** Don't try to patch the missing tables individually. Drop and re-import — Migrate Guru is idempotent on re-import (truncates destination tables before re-writing), but reset the destination's `wp-content/uploads/` first to avoid orphaned media bloat:

```bash
ssh root@${HOST_IP} bash <<RESET
rm -rf ${SITE}/wp-content/uploads/*
sudo -u ${SITE_USER} -i wp --path=${SITE} db reset --yes
RESET
```

Then on the destination wp-admin → Migrate Guru → **Generate New Migration Key**, paste the new key on the source side (see failure mode #5 for why the old key won't work), and restart the migration.

---

## 3. WoodMart-style duplicate class files (PHP fatal on first page load)

**Symptom.** Migration completes, Step 6 verification looks clean on DB counts. You visit the destination homepage and get a **blank white page**, or HTTP 500 from nginx, or a "There has been a critical error on this website" notice. Same on wp-admin in some cases. The source site on Hostinger (LiteSpeed) loaded the same page fine.

**Root cause.** Hostinger's LiteSpeed PHP-FPM is more lenient about violating PHP class-redeclaration rules than stock nginx + PHP-FPM. Theme/plugin folders that accumulated **multiple copies of the same `class X { ... }` file** over years of partial updates load cleanly on LiteSpeed (which picks one and ignores the rest via opcache quirks) but fatal on nginx FPM on the second `class X` declaration.

The canonical case from [[madomarche-migration]]: the WoodMart theme on madomarche.com had **9 coexisting copies** of the same class file in `wp-content/themes/woodmart/inc/` from years of WP-admin uploads-overwriting-not-replacing. LiteSpeed tolerated it; nginx FPM fatalled the first time anyone visited the front page.

**Detection.** Enable debug logging BEFORE doing anything else — the first 500 will write the fatal that tells you which file is at fault:

```bash
ssh root@${HOST_IP} bash <<DEBUG
sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG true --raw
sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG_LOG true --raw
sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG_DISPLAY false --raw
DEBUG

# Trigger a request
curl -sk -o /dev/null "https://${SSLIP_URL}/"

# Read the fatal
ssh root@${HOST_IP} "tail -50 ${SITE}/wp-content/debug.log"
```

A typical fatal looks like:

```
PHP Fatal error:  Cannot declare class WOODMART_Theme_Setup, because the name is already in use in /home/madomarche/htdocs/madomarche.com/wp-content/themes/woodmart/inc/class-theme-setup-old-copy.php on line 8
```

The path tells you the duplicate; the original is usually in the canonical theme structure (referenced from the theme's `functions.php` / `autoload.php`).

**Recovery.** Locate the duplicates of the class file the fatal mentions:

```bash
ssh root@${HOST_IP} "find ${SITE}/wp-content/themes/<theme>/ -name '*.php' -exec grep -l 'class WOODMART_Theme_Setup' {} \;"
```

Keep the one referenced from the canonical autoloader (`grep -r "require.*class-theme-setup" ${SITE}/wp-content/themes/<theme>/` will show which file the theme expects). Delete the rest — but BACKUP first:

```bash
ssh root@${HOST_IP} "mkdir -p /root/dedup-backup-$(date -u +%Y%m%d) && \
  mv ${SITE}/wp-content/themes/woodmart/inc/class-theme-setup-old-copy.php /root/dedup-backup-$(date -u +%Y%m%d)/"
```

Re-test, repeat for each new fatal that surfaces, until the homepage loads. Then **turn debug logging off** — leaving WP_DEBUG on in production leaks paths in some plugin error messages:

```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG false --raw"
```

---

## 4. Plugin auto-update during migration window

**Symptom.** Migration completes cleanly. Site loads fine for the first 30-60 min. Then suddenly a specific page / feature breaks ("Add to cart" stops working, layout shifts, checkout 500s). Coincides with the destination's first WP cron tick after import.

**Root cause.** WordPress 5.5+ auto-updates security/minor releases of core AND plugins (`auto_update_plugins` site option). If a plugin was at version `X.Y.Z` on the source, and `X.Y.Z+1` shipped between source backup and destination first cron — and that release has a theme-incompatible regression — the destination upgrades and breaks. Source site is unaffected because its DNS still points to Hostinger.

**Detection.**
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} plugin list --update=available"
# After the suspected auto-update event:
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} plugin list --field=name,version,update"
```

Compare against source-side plugin versions to confirm.

**Mitigation (preventive — do BEFORE operator clicks Validate on source).**
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} config set AUTOMATIC_UPDATER_DISABLED true --raw"
```

**Recovery (after auto-update break).** Roll the offending plugin back to the source version:
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} plugin install <plugin-slug> --version=<source-version> --force"
```

Then disable auto-updates (the mitigation block above) so it doesn't happen again on the next cron tick.

---

## 5. Source-side "key already used"

**Symptom.** On the Hostinger source wp-admin → Migrate Guru → after pasting the migration key from destination, **Validate** button returns an error like *"This migration key has already been used. Please generate a new one."*

**Root cause.** Each migration key from BlogVault's cloud is single-use. If the operator clicked Validate once, the migration started/failed/cancelled, and they're now retrying — the source plugin (or the cloud broker) marked the key as consumed.

**Detection.** Self-evident from the error message.

**Recovery.** On the **destination** wp-admin → Migrate Guru:
1. Look for a "Generate New Migration Key" or "Reset" or "Cancel and Start Over" button (wording varies by plugin version).
2. Click it. The plugin re-registers with BlogVault's cloud and shows a new key.
3. Copy the new key.
4. On the source side, paste the new key and click Validate again.

If no such button exists on the destination side (older Migrate Guru versions), reset the plugin's stored state by deactivating + reactivating:

```bash
ssh root@${HOST_IP} bash <<RESET
sudo -u ${SITE_USER} -i wp --path=${SITE} plugin deactivate migrate-guru
sudo -u ${SITE_USER} -i wp --path=${SITE} option delete migrateguru_options
sudo -u ${SITE_USER} -i wp --path=${SITE} option delete bvplugin_options
sudo -u ${SITE_USER} -i wp --path=${SITE} plugin activate migrate-guru
RESET
```

Then refresh the destination wp-admin Migrate Guru page; it'll re-register and show a fresh key.

---

## 6. Migrate Guru cloud rate-limit / queue stalled

**Symptom.** The SQL watcher in SKILL.md Step 4 shows table count plateaued at some non-zero value for >10 min. No errors in MySQL error log. Source-side dashboard shows a spinner ("Migration in progress...") that hasn't advanced its percentage for the same window. Destination wp-content/uploads/ isn't growing either.

**Root cause.** BlogVault's cloud broker queues migrations and rate-limits per-account on the free / lower-tier plans. Long migrations from large WooCommerce stores can get stuck in queue behind other users' migrations, especially during US business hours.

**Detection.**
1. Check Migrate Guru service status: https://status.blogvault.net — look for any active incident.
2. From the destination, watch the inbound TCP connections from BlogVault's IP range:
   ```bash
   ssh root@${HOST_IP} "ss -tn 'state established' | grep -E ':(80|443)' | head"
   ```
   During an active transfer there should be 1-3 connections from BlogVault's egress IPs (varies). If zero, the cloud broker isn't pushing.
3. Check the source-side Migrate Guru log (Hostinger wp-admin → Migrate Guru → check for a "View Log" link).

**Recovery.** Patience first — if status page shows a known incident, wait it out (typically <30 min). If after 30 min there's no incident and no progress:
1. Cancel the migration on the source side.
2. Wait 5 min (lets the cloud broker release the queued slot).
3. Generate a new migration key on the destination (see failure mode #5).
4. Restart the migration.

If a paid Migrate Guru tier is in use, contact BlogVault support with the migration ID — they can manually unstick queued jobs.

---

## 7. Destination wp-admin shows 404 (renamed login URL)

**Symptom.** After import completes, the operator visits `https://${SSLIP_URL}/wp-admin/` and gets a 404 page (not a redirect, not a login form). `https://${SSLIP_URL}/wp-login.php` also returns 404.

**Root cause.** The source site had a security plugin that **renamed** the WordPress login URL. Common offenders: **WPS Hide Login** (the typical case on madomarche), iThemes Security ("Hide Backend" feature), WordFence ("Login Security" → "Hide login URL"), All In One WP Security. The plugin stores the custom slug in `wp_options` and serves a 404 to anyone hitting the default `/wp-login.php` or `/wp-admin/`. After migration, the destination has the same renamed URL — but you don't know what it is.

**Detection.** Query `wp_options` for the renamed slug:

```bash
# WPS Hide Login stores it as 'whl_page'
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} option get whl_page"

# iThemes Security stores it under 'itsec-storage' → JSON → 'hide-backend.slug'
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} option get itsec-storage --format=json | python3 -m json.tool | grep -A2 hide-backend"

# WordFence stores it as 'whWAFAdminURL' (varies; grep for *login*)
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} db query \"SELECT option_name, option_value FROM wp_options WHERE option_name LIKE '%login%' OR option_name LIKE '%hide%' OR option_name LIKE '%backend%' LIMIT 20\""
```

The custom slug surfaces under one of those. Login URL becomes `https://${SSLIP_URL}/<slug>` (no `/wp-admin/`, no `/wp-login.php`).

**Recovery options.**

1. **Use the renamed URL** (preferred — preserves source security posture):
   `https://${SSLIP_URL}/<slug>` — log in, then proceed.

2. **Temporarily disable the security plugin** if you can't find the slug:
   ```bash
   ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} plugin deactivate wps-hide-login"
   # Now /wp-admin/ works again. Re-activate after you're done:
   ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} plugin activate wps-hide-login"
   ```

3. **Reset the slug to a known value** (if you'll keep the plugin active):
   ```bash
   ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} option update whl_page 'secure-portal-$(openssl rand -hex 4)'"
   ```
   Then log in at the new slug.

Communicate the URL to whoever is taking over operations — losing it after `wp-post-migration-fixup` switches the site to the real domain is a real way to lock yourself out of production.

---

## Cross-reference

- [[madomarche-migration]] — first production runs that surfaced #1, #2, #3, #7.
- [[hostinger-mariadb-collation]] — deep dive on #1, with all three recovery paths.
- [[hetzner-smtp-port-blocked]] — adjacent post-migration gotcha (not a Migrate Guru failure; appears after the site goes live and WP transactional mail hangs 60s).

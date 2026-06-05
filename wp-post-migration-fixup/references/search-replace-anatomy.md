# `wp search-replace` Anatomy

Sidecar reference for the `wp-post-migration-fixup` skill. Explains why every flag matters, what blows up if you skip one, and how to recover from a botched run. Loaded on demand.

WP-CLI version this targets: **2.10+**.

---

## The canonical safe invocation

```bash
sudo -u ${SITE_USER} -i wp --path=${SITE} search-replace 'OLD' 'NEW' \
  --skip-columns=guid \
  --report-changed-only \
  --precise \
  --dry-run    # remove for the real run
```

Each flag earns its place. Drop any one and something will hurt — eventually, silently, in production.

---

## `--skip-columns=guid` — the RSS notification storm

The `guid` column in `wp_posts` is the original post URL at creation time. **It is not used for routing.** WordPress matches posts by ID; `guid` is metadata for one purpose only: it's the unique identifier RSS readers use to deduplicate items in a feed.

If you update `guid` during search-replace:

- Every RSS reader subscribed to the site sees every post as "new" (different GUID → new item).
- Every push-notification service that reads the feed re-fires.
- The site's email-on-new-post plugin re-emails every subscriber every post in the archive.
- Feedly, Inoreader, etc. blow up with thousands of "new" items.

This has happened in the wild on large blogs migrating between hosts. The fix afterwards is to manually restore `guid` from a pre-migration backup — there's no clean way to "tell RSS readers oops, these aren't really new". The right answer is to never touch it: `--skip-columns=guid`, always.

---

## `--precise` — the WooCommerce-killer flag

WP-CLI's default search-replace uses MySQL's native `REPLACE()` function — a single SQL statement per table, fast and efficient. For plain text it works perfectly.

For **serialized PHP data** it corrupts the database.

PHP's `serialize()` format encodes the byte length of every string:

```
a:1:{s:7:"siteurl";s:42:"https://madomarche.178-105-177-37.sslip.io";}
```

That `s:42:` is the byte length of the value that follows. When you replace `https://madomarche.178-105-177-37.sslip.io` (42 bytes) with `https://madomarche.com` (22 bytes), SQL `REPLACE()` rewrites the string but leaves the `s:42:` prefix untouched:

```
a:1:{s:7:"siteurl";s:42:"https://madomarche.com";}
```

PHP's `unserialize()` reads the prefix, expects 42 bytes, gets 22 bytes plus a closing `"}`, throws a notice, and returns `false`. WordPress receives `false` from `get_option()` and silently uses the default — usually `''` or `[]`. The site doesn't error; it just behaves wrong.

**WooCommerce stores serialized data EVERYWHERE:**

- `wp_options` → tax rates, shipping zones, payment-gateway settings (most of WC config is one big serialized array per gateway)
- `wp_postmeta` → product attributes, variation pricing, custom fields
- `wp_usermeta` → cart contents (for logged-in users), saved addresses, capabilities
- `wp_termmeta` → product category settings, brand metadata

**`--precise` runs the replace in PHP land** — it pulls each row, `unserialize()`s, walks the data structure, replaces matching strings, `serialize()`s back with correct length prefixes, writes back. ~3-5× slower than the SQL path. **Always use it for WC sites**, and there's no real reason not to use it generally.

### What corruption looks like in practice

- Checkout breaks — payment gateway "not configured" because its serialized settings unserialize to `false`.
- Shipping options vanish — zones array is empty.
- Cart totals come out as `0.00` — tax rates lost.
- Admin user lists show no roles — `wp_capabilities` unserialize-fails.
- Yoast SEO settings reset to defaults — its single `wpseo_*` serialized blob is gone.

### What corruption looks like at the SQL layer

Direct check after a botched run:

```sql
SELECT option_name FROM wp_options
WHERE option_value LIKE 's:%' AND option_value NOT LIKE 's:[0-9]%:"%";';
-- Or, more useful: try to unserialize and see what fails
```

Or via wp-cli:

```bash
$WP option get woocommerce_default_country
# If this returns nothing on a site that previously had a value: corruption
```

---

## `--report-changed-only` — readability, not correctness

Without this flag, search-replace prints one row per table even if zero replacements happened — a ~80-row table for any non-trivial site, mostly noise.

With it, only tables that actually changed appear. Easier to verify "did Yoast's table change in pass 2?" or "why is `wp_options` showing 68 PHP-serialized replacements when I expected 12?".

Doesn't affect correctness. Drop it if you want machine-readable output to grep, but for human consumption keep it on.

---

## The two-pass URL pattern

Plugins / themes don't agree on whether to store URLs with or without scheme. Pass 1 catches scheme-prefixed; pass 2 catches the bare hostname.

### Pass 1: URL with scheme

```bash
$WP search-replace 'https://madomarche.178-105-177-37.sslip.io' 'https://madomarche.com' \
  --skip-columns=guid --report-changed-only --precise
```

Catches the "canonical" stores:
- `wp_options.siteurl` / `wp_options.home`
- WooCommerce checkout / cart / shop URLs
- Plugin license-key registration URLs
- Embedded `<a href>` and `<img src>` in post_content
- REST API root URLs cached in transients

Madomarche real number: **1830 replacements**.

### Pass 2: bare hostname

```bash
$WP search-replace 'madomarche.178-105-177-37.sslip.io' 'madomarche.com' \
  --skip-columns=guid --report-changed-only --precise
```

Catches the scheme-less stores:
- Yoast SEO canonical/sitemap settings (`wpseo_titles`, `wpseo_internallinks`)
- WP Rocket CDN host (`wp_rocket_settings.cdn_cnames`)
- Custom theme "site URL" options often stored as hostname only
- Hard-coded `<link rel="canonical" href="//hostname/...">` in `post_content` (note the protocol-relative form)
- Third-party tracking pixel hostnames

Madomarche real number: **499 additional replacements** on top of pass 1. Pass 2 is not optional.

### What about `http://` (no s)?

If the source site was ever served over plain HTTP, run a third pass:

```bash
$WP search-replace 'http://madomarche.178-105-177-37.sslip.io' 'https://madomarche.com'
```

For sslip-era destinations this is almost never needed (sslip-era is HTTPS-only by skill design). For Hostinger sources that mixed HTTP and HTTPS over their lifetime, it's needed. Check with:

```bash
$WP db query "SELECT COUNT(*) FROM wp_options WHERE option_value LIKE '%http://${SSLIP_URL}%'"
```

---

## The dry-run gate — always

```bash
$WP search-replace 'OLD' 'NEW' --skip-columns=guid --report-changed-only --precise --dry-run
```

Prints the per-table count without writing. Use it to:

- Sanity-check the source string is actually in the DB. If `--dry-run` shows 0 replacements across all tables, your source string is wrong (typically: forgot the dashed IP in the sslip hostname, or wrong scheme).
- Catch surprise tables — if `wp_woocommerce_log` shows 50,000 replacements, somebody has been logging full URLs at debug level and you're about to bloat your wp-cli output to ~100MB.
- Verify expected magnitudes before the real run. The madomarche pass-1 dry-run reported 1830; if it had reported 18, somebody had screwed up the source string.

If the dry-run looks right, drop `--dry-run` and re-run the same command.

---

## WooCommerce-specific tables to watch

`--precise` handles all of these correctly. `--report-changed-only` keeps the output focused. They show up in the report because WC uses URLs heavily.

| Table | What's stored | Why URLs are there |
|---|---|---|
| `wp_wc_orders` (HPOS) | Order rows | Order URLs in custom-data columns; rare but present |
| `wp_wc_order_addresses` | Billing/shipping addresses | Some payment gateways store callback URLs per-address |
| `wp_woocommerce_order_items` | Line items per order | Refund URLs, product-page URLs |
| `wp_woocommerce_order_itemmeta` | Line-item metadata | Variation thumbnail URLs, download URLs for digital products |
| `wp_woocommerce_payment_tokens` | Saved payment methods | Gateway notification URLs |
| `wp_woocommerce_sessions` | Cart sessions | Full serialized cart state — biggest source of URL hits |
| `wp_actionscheduler_*` | Async job queue | Job arguments often include URLs |

HPOS (High-Performance Order Storage) sites store orders in `wp_wc_orders` instead of `wp_posts`. `search-replace` handles both. Legacy sites pre-HPOS store orders as `wp_posts` rows with `post_type='shop_order'` — those get caught by the standard `wp_posts` pass.

---

## Recovery from a botched search-replace

If you ran without `--precise` and serialized data is now corrupt, **do not try to fix it in place**. Restore from backup.

### Step 1: Confirm corruption

```bash
# Try to load an option known to be serialized
$WP option get woocommerce_default_country
# If empty on a site that previously had a value → corruption confirmed

# Or check for unserialize failures in the error log
tail -200 /home/${SITE_USER}/htdocs/${DOMAIN}/wp-content/debug.log | grep -i unserialize
```

### Step 2: Restore the DB from `nightly-backup-wp-cron`

```bash
ls -lh /var/backups/${SITE_USER}/  # find the most recent dump from BEFORE the bad run
zcat /var/backups/${SITE_USER}/${SITE_USER}-db-<date>.sql.gz | $WP db import -
```

If you don't have a `nightly-backup-wp-cron` dump from before the bad run, check for:
- `cloudpanel-site-add` migration-mode pre-cutover snapshot (usually saved to `/var/backups/migration/`)
- Hostinger source DB export from `wp-migrate-guru-import` (kept by Migrate Guru on BlogVault)
- ZFS / LVM snapshots if the host has them

If none of those exist, the only recovery is to re-run `wp-migrate-guru-import` from the source — which means the source has to still be reachable (it is, if DNS just flipped and you haven't decommissioned).

### Step 3: Redo with correct flags

```bash
$WP search-replace 'https://OLD' 'https://NEW' --skip-columns=guid --report-changed-only --precise
$WP search-replace 'OLD' 'NEW' --skip-columns=guid --report-changed-only --precise
```

### Step 4: Smoke-test the recovery

```bash
$WP option get siteurl                    # right URL
$WP option get woocommerce_default_country # non-empty for WC sites
$WP eval 'var_dump(get_option("woocommerce_general_settings"));' # serialized data unserialises cleanly
```

---

## When NOT to use `wp search-replace`

- **For files on disk** — search-replace only touches the DB. URLs hard-coded in `wp-content/themes/<theme>/header.php`, `functions.php`, `style.css`, or in custom plugin PHP need a separate `grep -r` + `sed -i` pass. After the DB pass, sweep:
  ```bash
  grep -rE "${SSLIP_URL}" /home/${SITE_USER}/htdocs/${DOMAIN}/wp-content/
  ```
- **For uploaded media URLs in `wp_posts.guid`** — `--skip-columns=guid` skips them by design. Media URLs in `post_content` get caught (they're in `post_content`, not `guid`).
- **For email-history tables** logged by transactional-mail plugins — historical record, don't rewrite. Most are out of WP's table prefix anyway; check before running.

---

## See also

- [WP-CLI Cheatsheet](../../cloudpanel-site-add/references/wp-cli-cheatsheet.md) — the broader wp-cli reference this skill builds on
- WP-CLI search-replace docs: https://developer.wordpress.org/cli/commands/search-replace/
- PHP serialize format reference: https://www.phpinternalsbook.com/php5/classes_objects/serialization.html (the canonical reference for *why* SQL `REPLACE()` corrupts serialized data)

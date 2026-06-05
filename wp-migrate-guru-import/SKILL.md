---
name: "WP Migrate Guru Import"
description: "Drive the destination side of a Migrate Guru migration from a source WordPress site (typically Hostinger) to a destination on a CloudPanel host (typically cloudpanel-1). Verifies destination state, coaches the operator through the source/destination migration-key handoff, watches the destination DB for progress, detects known failure modes (Hostinger MariaDB collation mismatch, partial-but-reachable, plugin/theme PHP fatals, security-plugin renamed login URL), and runs post-import verification. Use immediately after `cloudpanel-site-add` (mode=migration) finishes, before `wp-post-migration-fixup` and DNS cutover."
---

# WP Migrate Guru Import

## What This Skill Does

Drives the **destination-side** of a Migrate Guru migration from a source WordPress site (typically on **Hostinger**) to a destination running on a **CloudPanel host** (typically `cloudpanel-1`). The destination must already exist — created by [`cloudpanel-site-add`](../cloudpanel-site-add/) in `mode=migration`, which gave it an sslip.io alias + LE cert + temporary `WP_HOME` / `WP_SITEURL` overrides in `wp-config.php`.

The **source side** (Migrate Guru on Hostinger) is driven by the user from their browser — this skill does NOT automate the source side. What this skill DOES:

1. **Pre-flight** the destination is in the right state (sslip alias reachable, valid LE cert, WP installed, overrides present).
2. **Reset destination admin password** to a fresh one-time value the user saves once, so they can log in to install the Migrate Guru plugin.
3. **Coach the operator** through the migration-key handoff between source and destination plugins.
4. **Watch the destination DB** for progress (table count, product count) in a non-blocking loop.
5. **Detect known failure modes early** — collation mismatch (MariaDB uca1400 → MySQL 8.4), "partial-but-reachable", plugin/theme PHP fatals after import, security-plugin renamed login URL.
6. **Post-import verification** — table count vs source, post count, `siteurl` / `home` options sanity, stray source-domain URLs.

This skill is intentionally **light on automation**. Migrate Guru's modern flow (2025+) uses a peer-to-peer migration-key exchange between source + destination plugins, brokered by BlogVault's cloud. There is no public API to drive it from outside the wp-admin UI. The value here is making sure **both sides are configured correctly so the migration succeeds first try** — and catching the handful of failure modes that have wasted real hours on past runs (see [[madomarche-migration]]).

## When to Use

- The destination was just created by `cloudpanel-site-add --mode=migration`, and the OUTPUTS block printed an `SSLIP_URL`.
- Migrating from Hostinger to cloudpanel-1 (or any CloudPanel 6.x host) where DNS still points to the source.
- Re-importing after a previous failed attempt — Migrate Guru is idempotent on re-import (truncates destination DB tables before re-writing), but this skill's Step 1 pre-flight catches the state issues that caused the first failure.

## When NOT to Use

- Destination created without `mode=migration` (no sslip alias, no wp-config overrides). Re-run `cloudpanel-site-add` first.
- Both source and destination are on the same DNS — at that point you can just use `wp db export` / `wp db import` + `wp search-replace`. Migrate Guru's value is the source-pushes-to-destination-via-its-cloud model that works before DNS is flipped.
- Source is NOT a working WordPress site (the plugin needs wp-admin access to install).
- Source DB engine is **MariaDB ≥10.10 with `utf8mb3_uca1400_*` collations AND destination DB is MySQL 8.x** — Migrate Guru will fail mid-import. Re-create the destination with `DB_ENGINE=mariadb-docker` via `cloudpanel-site-add` first. See [[hostinger-mariadb-collation]] + [`references/migrate-guru-failure-modes.md`](./references/migrate-guru-failure-modes.md).

## Prerequisites

- SSH root access to the CloudPanel host (`ssh -i ~/.ssh/<key> root@${HOST_IP}`).
- Browser access to BOTH the source Hostinger wp-admin AND the destination wp-admin at the sslip.io URL.
- `cloudpanel-site-add` already ran in `migration` mode and printed an OUTPUTS block — you'll feed those values in as inputs below.
- Source-side Migrate Guru plugin **not yet installed** (or installed but the migration key from a previous attempt is unused; see "key already used" pitfall).
- A password vault open in another tab — the destination admin password reset in Step 2 is printed **once** and never stored.

---

## Inputs (collect from `cloudpanel-site-add` OUTPUTS block)

| Var | Example | Notes |
|---|---|---|
| `HOST_IP` | `178.105.177.37` | cloudpanel-1 IP |
| `SITE_USER` | `madomarche` | From `cloudpanel-site-add` OUTPUTS |
| `DOMAIN` | `madomarche.com` | The eventual real domain |
| `SSLIP_URL` | `madomarche.178-105-177-37.sslip.io` | sslip alias from `cloudpanel-site-add`, no scheme |
| `SITE` | `/home/madomarche/htdocs/madomarche.com` | Docroot, from OUTPUTS |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PW` | from OUTPUTS + saved password | Used by the SQL progress watcher |
| `SOURCE_DOMAIN` | `madomarche.com` | Usually same as `DOMAIN` since DNS still points to source — used for stray-URL sanity check |

---

## Step 1 — Pre-flight on destination

Verify the state expected after `cloudpanel-site-add --mode=migration` ran. All checks must pass before you tell the operator to start the source side — otherwise Migrate Guru will write data into a misconfigured destination and you'll have to drop and retry.

```bash
ssh root@${HOST_IP} bash <<CHECK
set -e
echo "1. docroot exists:"
[ -d ${SITE} ] && echo "  OK ${SITE}" || { echo "  FAIL — re-run cloudpanel-site-add"; exit 1; }

echo "2. wp-config has MIGRATION_TEMP_OVERRIDE marker:"
grep -q MIGRATION_TEMP_OVERRIDE ${SITE}/wp-config.php && echo "  OK" || \
  { echo "  FAIL — destination not in migration mode; re-run cloudpanel-site-add with mode=migration"; exit 1; }

echo "3. wp-admin reachable via sslip URL:"
curl -sk -o /dev/null -m 15 -w "  HTTP %{http_code} ssl_verify=%{ssl_verify_result}\n" \
  "https://${SSLIP_URL}/wp-admin/"
# Expect 200 or 302 (login redirect). Anything else means the alias or cert is broken.

echo "4. WP_HOME / WP_SITEURL are the sslip URL (proves overrides are active):"
sudo -u ${SITE_USER} -i wp --path=${SITE} eval \
  'echo WP_HOME, " | ", WP_SITEURL, "\n";'
# Both fields should print "https://${SSLIP_URL}".

echo "5. DB reachable + auth works:"
mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} -e 'SELECT 1' >/dev/null \
  && echo "  OK" || { echo "  FAIL — check creds from cloudpanel-site-add OUTPUTS"; exit 1; }
CHECK
```

If check 2 fails (no `MIGRATION_TEMP_OVERRIDE` marker), wp-admin will redirect to the **real** domain — which still points at the source Hostinger box. You'll log in to the wrong site and never realize it until the migration writes nothing. Always re-run `cloudpanel-site-add` with `MODE=migration` rather than hand-patching wp-config.

## Step 2 — Reset destination admin password (single-use, printed once)

The destination WP currently has whatever admin creds were entered at the CloudPanel "Create WordPress Site" step. Most operators don't remember them. Reset to a fresh one-time password the operator saves once — Migrate Guru will overwrite the `wp_users` table during import, so this credential dies after the import anyway.

```bash
ssh root@${HOST_IP} bash <<RESET
set -e
NEWPW=\$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
ADMIN=\$(sudo -u ${SITE_USER} -i wp --path=${SITE} user list --role=administrator --field=user_login | head -1)
sudo -u ${SITE_USER} -i wp --path=${SITE} user update "\$ADMIN" --user_pass="\$NEWPW" >/dev/null
echo
echo "=== USE ONCE — overwritten by Migrate Guru when migration completes ==="
echo "  URL:  https://${SSLIP_URL}/wp-admin/"
echo "  User: \$ADMIN"
echo "  Pass: \$NEWPW"
echo "=== Save this to your vault NOW. It will not be printed again. ==="
RESET
```

The password is `openssl rand -base64 18 | cut -c1-20` — 20 URL-safe chars, ~118 bits of entropy. Never written to a memory file.

## Step 3 — Coach the operator through the migration-key handoff

This is the part the skill **cannot** automate. Print the exact instructions in order. The screens have stayed stable through Migrate Guru's 2024-2026 UI; if your version differs, adapt by intent.

**On the DESTINATION (the sslip.io wp-admin you just got creds for):**

1. Log in at `https://${SSLIP_URL}/wp-admin/` with the user/pass from Step 2.
2. Go to **Plugins → Add New** → search **"Migrate Guru"** → **Install Now** → **Activate**.
3. Click the new **Migrate Guru** menu item on the left sidebar.
4. The plugin registers this destination with BlogVault's cloud and displays a **Migration Key** — a long alphanumeric string. Click the **Copy** button next to it.
5. Leave this tab open.

**On the SOURCE (the Hostinger wp-admin):**

1. Log in to the source wp-admin (still on the real domain, since DNS still points to Hostinger).
2. **Plugins → Add New** → **"Migrate Guru"** → **Install** → **Activate**, if not already installed.
3. **Migrate Guru** sidebar item → click **Migrate Site**.
4. Choose **"Custom Host"** (or similar — wording varies; pick the option that asks for a destination URL, NOT a hosting-provider preset like "WP Engine" or "Pantheon").
5. Enter destination URL: `https://${SSLIP_URL}` (paste exactly, including `https://`).
6. Click **Validate Migration Key** (or **Next**) → on the next screen paste the migration key from Step 4 of the destination side.
7. Click **Validate**. If validation fails see the "key already used" pitfall in [`references/migrate-guru-failure-modes.md`](./references/migrate-guru-failure-modes.md).
8. On the next screen click **Migrate** to start.

**Expected duration:** 30 min – 4 h depending on store size. Migrate Guru's progress bar is a rough estimate; the SQL watcher in Step 4 is the real source of truth.

## Step 4 — Watch the destination DB for progress (non-blocking)

Migrate Guru writes the destination DB table-by-table, then copies files. Watch the DB in a separate terminal so you spot a stall early. Loop until table count plateaus and equals the source-side estimate.

```bash
# One-line watcher: prints table count + product count every 30s
ssh root@${HOST_IP} bash <<'WATCH'
while true; do
  TS=$(date -u +%H:%M:%S)
  TC=$(mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} \
    -e "SHOW TABLES LIKE 'wp\\_%'" -sN 2>/dev/null | wc -l)
  PC=$(mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} \
    -e "SELECT COUNT(*) FROM wp_posts WHERE post_type='product' AND post_status='publish'" \
    -sN 2>/dev/null || echo 'n/a')
  echo "${TS}  tables=${TC}  published_products=${PC}"
  sleep 30
done
WATCH
```

**Reading the watcher:**
- Tables ramp from `0` toward the source count (typical: 30-50 for plain WP, 80-150 for WooCommerce, 150+ for WC + bookings/membership/multilingual plugins).
- `published_products` stays at `n/a` (no `wp_posts` table yet) until ~halfway through, then jumps from `0` to the source product count in one tick (Migrate Guru bulk-inserts).
- A plateau lasting >5 min with NO further table growth almost always means an error — check [`references/migrate-guru-failure-modes.md`](./references/migrate-guru-failure-modes.md) and start tailing the MySQL error log:
  ```bash
  ssh root@${HOST_IP} 'tail -F /var/log/mysql/error.log' &
  ```

When the count stabilizes and matches the source-side Migrate Guru dashboard's "tables migrated" number, the DB phase is done. File copy continues in the background (uploads tarball arrives, gets extracted into `wp-content/uploads/`).

## Step 5 — Detect known failure modes early

Three failures account for ~95% of bad runs on cloudpanel-1. Detect them while the migration is still going so you abort early instead of after a 4-hour completed-but-broken import.

### 5a. Collation mismatch (MariaDB uca1400 → MySQL 8.4)

**Symptom in MySQL error log:** `Unknown collation: 'utf8mb3_uca1400_ai_ci'` (the exact collation name varies; `uca1400` is the signature). The error appears within the first few `CREATE TABLE` statements.

**Detection:**
```bash
ssh root@${HOST_IP} 'tail -100 /var/log/mysql/error.log | grep -i uca1400'
```

**Recovery:** Abort the migration (close the source tab; Migrate Guru cancels server-side after timeout). Re-run `cloudpanel-site-add` with `DB_ENGINE=mariadb-docker` to swap the destination DB to a MariaDB sidecar, then restart from this skill's Step 1. See [[hostinger-mariadb-collation]] for the full rationale.

### 5b. Partial-but-reachable

**Symptom:** Migrate Guru's source-side dashboard shows green "Migration complete" but the SQL watcher in Step 4 shows a table count well below the source count. Or the wp-admin loads but some plugins are missing options / show "table doesn't exist" notices.

**Why:** Migrate Guru's dashboard fires "complete" on manifest write, not on table-by-table success. Network blips during the file copy phase can leave the DB at 80% imported with no error surfaced.

**Detection:** Always run Step 6 verification — never trust the dashboard alone.

**Recovery:** Drop and re-import (re-import is idempotent; truncates destination tables first), but reset destination uploads first to avoid orphaned media:
```bash
ssh root@${HOST_IP} "rm -rf ${SITE}/wp-content/uploads/* && sudo -u ${SITE_USER} -i wp --path=${SITE} db reset --yes"
```

### 5c. Plugin/theme PHP fatals after import (nginx + PHP-FPM strict-mode)

**Symptom:** Migration completes, you visit the destination front page, get a blank white screen or HTTP 500. wp-admin may also 500. Source on Hostinger (LiteSpeed) ran fine; destination doesn't.

**Why:** Hostinger's LiteSpeed PHP-FPM is more lenient with duplicate `class` declarations and other PHP-strict-mode violations than nginx + PHP-FPM stock. The classic case from [[madomarche-migration]] is the **WoodMart theme on madomarche.com** which had **9 coexisting copies** of the same class file from years of partial updates — LiteSpeed picked one and ignored the rest, nginx FPM fatals on the second `class X` redeclaration.

**Detection:** Enable debug logging on the destination (do this BEFORE you start trying to fix things — the first reload writes the fatal that tells you which file):
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG true --raw && \
  sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG_LOG true --raw && \
  sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG_DISPLAY false --raw"
curl -sk -o /dev/null "https://${SSLIP_URL}/"
ssh root@${HOST_IP} "tail -50 ${SITE}/wp-content/debug.log"
```

**Recovery:** Depends on the specific fatal. For the WoodMart 9-class-files case: dedupe in `wp-content/themes/woodmart/inc/` keeping only the canonical files referenced from the theme's `autoload.php`. After fix, **turn debug logging off** before going live:
```bash
ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} config set WP_DEBUG false --raw"
```

## Step 6 — Post-import verification

Each check is independent. The full block is required — a passing dashboard + a passing wp-admin login do NOT prove the migration succeeded.

```bash
ssh root@${HOST_IP} bash <<VERIFY
set -e
echo "1. Destination table count:"
TC=\$(mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} \
  -e "SHOW TABLES LIKE 'wp\\_%'" -sN | wc -l)
echo "   tables=\$TC  (compare against source — ask operator for source count)"

echo "2. Destination product count:"
PC=\$(mysql -u${DB_USER} -p${DB_PW} -h${DB_HOST} -P${DB_PORT} ${DB_NAME} \
  -e "SELECT COUNT(*) FROM wp_posts WHERE post_type='product' AND post_status='publish'" -sN)
echo "   published_products=\$PC  (compare against source)"

echo "3. siteurl / home options (must equal sslip URL — proves URL rewrite worked):"
sudo -u ${SITE_USER} -i wp --path=${SITE} option get siteurl
sudo -u ${SITE_USER} -i wp --path=${SITE} option get home

echo "4. No stray source-domain URLs left in wp_options:"
sudo -u ${SITE_USER} -i wp --path=${SITE} option list --search='*hostinger*' --fields=option_name,option_value
sudo -u ${SITE_USER} -i wp --path=${SITE} option list --search='*hstgr*' --fields=option_name,option_value

echo "5. Test page loads with no PHP errors:"
curl -sk -o /dev/null -m 20 -w "   HTTP %{http_code}  size=%{size_download}\n" \
  "https://${SSLIP_URL}/"
tail -20 ${SITE}/wp-content/debug.log 2>/dev/null | grep -i fatal && \
  echo "   FATALS PRESENT — see Step 5c" || echo "   no PHP fatals in debug.log"
VERIFY
```

If anything in the verification fails, see the failure-mode-specific recovery in [`references/migrate-guru-failure-modes.md`](./references/migrate-guru-failure-modes.md). Don't proceed to `wp-post-migration-fixup` (which flips URLs to the real domain) until verification is clean — fixing URL state mid-broken-migration is much harder than fixing the migration first.

## Step 7 — Print OUTPUTS block

```
OUTPUTS_BEGIN
DOMAIN=madomarche.com
HOST_IP=178.105.177.37
SITE_USER=madomarche
SSLIP_URL=https://madomarche.178-105-177-37.sslip.io
MIGRATION_STATUS=complete|partial|failed
TABLE_COUNT_DEST=137
TABLE_COUNT_SOURCE_REPORTED=137
PRODUCT_COUNT_DEST=1226
PRODUCT_COUNT_SOURCE_REPORTED=1226
DEBUG_LOG_ENABLED=false
OUTPUTS_END
```

`MIGRATION_STATUS=complete` means Step 6's verification passed end-to-end. `partial` means the migration ran but Step 6 caught discrepancies — `wp-post-migration-fixup` should NOT run yet. `failed` means abort and re-import.

---

## Idempotency contract

Steps 2-5 are user-driven (we can't make the operator click less). Steps 1 + 6 are scriptable and must be safe to re-run.

| Step | Idempotency check |
|---|---|
| 1 (pre-flight) | Read-only; always safe to re-run |
| 2 (admin password reset) | Generates a fresh password each run — **not** idempotent by design. Operator must save the printed value before re-running |
| 3 (handoff coaching) | Pure documentation; no state change |
| 4 (DB watcher) | Read-only loop; Ctrl-C to stop |
| 5 (failure detection) | Read-only |
| 6 (verification) | Read-only |

A re-import after a failed first try is the **operator's** action via the source-side Migrate Guru UI. From this skill's perspective, just re-run Step 1 → Step 6 on the new attempt.

---

## Common pitfalls (real, from madomarche/armadorn runs on cloudpanel-1)

- **wp-admin reachable via sslip only if `WP_HOME`/`WP_SITEURL` overrides are present.** If `cloudpanel-site-add` was run without `mode=migration`, those overrides aren't there — wp-admin redirects to the real domain (which goes to source Hostinger). You'll think you're logged in to the destination but you're not. Pre-flight check 4 catches this; never skip it.

- **Migrate Guru's "Migration complete" badge is unreliable.** It fires on manifest write, not table-by-table success. ALWAYS verify via SQL table count + product count vs source. See "partial-but-reachable" in `references/migrate-guru-failure-modes.md`.

- **Plugin auto-update during migration window.** WordPress 5.5+ auto-updates security releases by default. If a source plugin was on `X.Y.Z` and `X.Y.Z+1` shipped yesterday with a theme-incompatible regression, the destination's first cron tick after import will auto-update and break the site. Mitigate by setting `define('AUTOMATIC_UPDATER_DISABLED', true);` in destination `wp-config.php` BEFORE the operator clicks "Validate" on the source:
  ```bash
  ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} config set AUTOMATIC_UPDATER_DISABLED true --raw"
  ```
  Re-enable after the dust settles (or leave disabled and update manually — recommended for production stores).

- **Hostinger's `wp-content/uploads` can have HUGE caches.** A store that looks like 2 GB in Hostinger admin might be 8 GB with all cached image variants (`-300x300.jpg`, `-768x768.jpg`, `-scaled.jpg`, `-1024x1024.webp`, etc). Migrate Guru transfers everything; ETA mismatches operator expectations. Forewarn before kicking off.

- **Source-side "key already used".** If the operator clicked Validate, the migration failed/cancelled, and they're retrying — the source plugin remembers the consumed key and refuses. Fix: on destination wp-admin, in Migrate Guru → click "Generate New Migration Key" (or "Reset"), copy the new key, paste on source. See `references/migrate-guru-failure-modes.md`.

- **Destination wp-admin shows 404 after import.** Hostinger sites with security plugins (WPS Hide Login, iThemes Security, WordFence) rename `/wp-login.php` to e.g. `/secure-portal-9482/`. After import, the destination has the same renamed URL but you don't know what it is. Lookup:
  ```bash
  ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} option get whl_page"          # WPS Hide Login
  ssh root@${HOST_IP} "sudo -u ${SITE_USER} -i wp --path=${SITE} db query \"SELECT option_name, option_value FROM wp_options WHERE option_name LIKE '%login%'\""
  ```
  The renamed URL is in `wp_options` somewhere — grep for it.

---

## Pairs Well With

- **[`cloudpanel-site-add`](../cloudpanel-site-add/)** *(mode=migration)* — REQUIRED prereq; provides the sslip URL, wp-config overrides, and LE cert that make the destination reachable before DNS cutover.
- **[`wp-post-migration-fixup`](../wp-post-migration-fixup/)** — runs AFTER DNS cutover; flips sslip URLs → real domain in DB via `wp search-replace`, removes the `MIGRATION_TEMP_OVERRIDE` block from `wp-config.php`, issues a real LE cert for `${DOMAIN}` + `www.${DOMAIN}`, smoke-tests the live site.
- **[`cloudflare-dns-setup`](../cloudflare-dns-setup/)** — runs in PARALLEL with this skill (DNS prep happens while the migration runs); switches NS to Cloudflare and preps records for the cutover that `wp-post-migration-fixup` will trigger.
- **[`wp-bot-hardening`](../wp-bot-hardening/)** — run after `wp-post-migration-fixup` finishes. Bot crawlers will find the new IP fast; hardening before that happens prevents the first PHP-FPM swap-peak event.

## References

### Sidecar reference files (loaded on demand)

- [`references/migrate-guru-failure-modes.md`](./references/migrate-guru-failure-modes.md) — focused troubleshooting reference. For each known failure mode: symptom (exact text where possible), root cause, detection commands, recovery steps. Covers collation mismatch, partial-but-reachable, WoodMart-style duplicate class files (with the 9-files anecdote from madomarche), plugin auto-update breakage, source-side "key already used", Migrate Guru cloud rate-limit / queue stall, and destination wp-admin 404 from renamed login URL.

### Memory notes

- [[madomarche-migration]] — first production run of this skill (madomarche.com + armadorn.com on cloudpanel-1, 2026-05-31). Has the WoodMart 9-class-files war story.
- [[hostinger-mariadb-collation]] — full rationale for the MariaDB-Docker pattern + alternative source-side conversion path.
- [[cloudpanel-1-multi-tenant-host]] — the host this skill targets; per-site authoritative reference is `/root/SERVER_NOTES.md` on the box.

### External

- Migrate Guru by BlogVault: https://migrateguru.com — official docs (mostly source-side oriented; this skill fills in the destination-side gaps)
- WP-CLI handbook: https://make.wordpress.org/cli/handbook/
- Migrate Guru status / queue: https://status.blogvault.net (check if the cloud-broker side is the bottleneck before assuming the migration is stuck)

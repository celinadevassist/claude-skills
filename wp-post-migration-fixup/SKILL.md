---
name: "WP Post-Migration Fixup"
description: "The 'after DNS cutover' sweep for a WordPress / WooCommerce migration. Flips sslip.io URLs to the real domain via a WooCommerce-safe two-pass `wp search-replace`, strips the `MIGRATION_TEMP_OVERRIDE` block from wp-config.php, reissues a real Let's Encrypt cert for apex + www, flushes caches, and smoke-tests HTTPS / cert chain / no-sslip-leftovers / email DNS / optional transactional mail. Idempotent. Use once `dig $DOMAIN @1.1.1.1` returns the new origin IP — i.e. nameservers are switched to Cloudflare AND A records point to the new host."

---

# WP Post-Migration Fixup

## What This Skill Does

The final post-cutover sweep that turns a "migrated site reachable via sslip.io" into a "live site at the real domain, fully cut over":

1. **Pre-flights DNS** — verifies `$DOMAIN` actually resolves to the new origin (cutover happened) and that the destination still carries the `MIGRATION_TEMP_OVERRIDE` block (pre-cutover state matches what `cloudpanel-site-add` produced).
2. **Strips `MIGRATION_TEMP_OVERRIDE`** from `wp-config.php` — the `WP_HOME` / `WP_SITEURL` defines injected during migration mode are removed so WP reads the DB values again.
3. **Runs `wp search-replace` in two passes** — first the URL with scheme (`https://$SSLIP_URL` → `https://$DOMAIN`), then the bare hostname (`$SSLIP_URL` → `$DOMAIN`) to catch Yoast/WPRocket/theme-option references that store hostnames without scheme. Uses `--precise --skip-columns=guid --report-changed-only` — WooCommerce-safe, RSS-safe, readable output.
4. **Flushes caches + permalinks** — `wp cache flush`, `wp rewrite flush`, plus LiteSpeed / WP-Rocket plugin-specific purges if installed.
5. **Issues a real Let's Encrypt cert** for `$DOMAIN` + `www.$DOMAIN` via `clpctl lets-encrypt:install:certificate` — replaces the sslip-only cert that was installed during migration. Works post-cutover because both names now resolve to our origin so LE's HTTP-01 challenge succeeds.
6. **Smoke-tests** — HTTPS 200, www → apex 301, cert chain valid and covers both names, no `sslip.io` leftovers in the rendered HTML, MX/SPF/DKIM still resolve, optional security-plugin-aware wp-admin reachability.
7. **(Optional) Sends a test transactional email** through WP's mail subsystem and asks the operator to verify SPF/DKIM/DMARC PASS at the recipient (sanity check on email after DNS changes).
8. Prints a single parseable **OUTPUTS** block with the cutover summary (search-replace count, cert expiry, HTTPS status, sslip leftover count, email DNS health).

On the cloudpanel-1 production run (madomarche.com, 2026-05-31) this swept **2329 replacements** across the DB (1830 URL-with-scheme + 499 bare-hostname), reissued a clean LE cert, and confirmed zero sslip leftovers in the live HTML. See [[madomarche-migration]].

## When to Use

- **DNS has flipped to the new origin** — `dig $DOMAIN @1.1.1.1` returns the new host's IP. This is the entry condition; nothing in this skill works before that.
- **The destination was previously set up by `cloudpanel-site-add` in `mode=migration`** and still carries the `MIGRATION_TEMP_OVERRIDE` block in `wp-config.php`.
- **`wp-migrate-guru-import` finished** and the destination renders correctly via the sslip.io URL.
- **Re-running after a partial run** — every step is idempotent. Strip is a no-op if the block is gone; search-replace returns "0 replacements" naturally if already done; LE issue is skipped if the cert exists and is valid for more than 7 days.

## When NOT to Use

- **DNS has not flipped yet** — abort. Cert issue will fail (LE can't validate), search-replace will succeed but the site will be unreachable at the new URL anyway. Use `cloudflare-dns-setup` first.
- **No `MIGRATION_TEMP_OVERRIDE` marker** in `wp-config.php` — either this site wasn't set up by `cloudpanel-site-add` in migration mode, or a previous fixup run already completed. In the first case, this skill's assumptions don't hold; in the second, the DB is already at the real domain and there's nothing to do. Check `wp option get siteurl` before forcing anything.
- **Greenfield site (no migration involved)** — the DB never held an sslip URL, so search-replace is meaningless. The LE cert is issued by `cloudpanel-site-add` directly in greenfield mode.

## Prerequisites

- SSH root access to the destination host. Every command runs over SSH (`ssh -i ~/.ssh/<key> root@${HOST_IP}`).
- `wp-cli` available for the site user (CloudPanel ships `/usr/bin/wp` by default).
- `clpctl` (CloudPanel CLI) on the host for the LE step.
- Backups: `cloudpanel-site-add`'s nightly cron should be live before running this (`nightly-backup-wp-cron`). If not, take a manual `wp db export` first — the search-replace step is the single highest-risk operation in the chain.

---

## Inputs (from `cloudpanel-site-add` OUTPUTS)

| Var | Example | Source |
|---|---|---|
| `HOST_IP` | `178.105.177.37` | from `cloudpanel-site-add` OUTPUTS |
| `SITE_USER` | `madomarche` | from `cloudpanel-site-add` OUTPUTS |
| `DOMAIN` | `madomarche.com` | the real domain (bare apex, no scheme) |
| `SSLIP_URL` | `madomarche.178-105-177-37.sslip.io` | bare hostname (no scheme), from `cloudpanel-site-add` OUTPUTS. If yours was printed with `https://` prefix, strip it. |
| `VERIFY_EMAIL` | `you@gmail.com` | optional, for the Step 9 test mail |

Derived in the skill: `SITE=/home/${SITE_USER}/htdocs/${DOMAIN}`, `WP="sudo -u ${SITE_USER} -i wp --path=${SITE}"`.

---

## Step 1 — Pre-flight (the DNS gate)

The single hard prerequisite is that `$DOMAIN` resolves to `$HOST_IP` from a public resolver. If it doesn't, abort loudly.

```bash
ACTUAL_IP=$(dig +short ${DOMAIN} @1.1.1.1 | head -1)
if [ "${ACTUAL_IP}" != "${HOST_IP}" ]; then
  echo "ABORT: ${DOMAIN} resolves to ${ACTUAL_IP}, expected ${HOST_IP}"
  echo "DNS hasn't propagated yet OR the A record wasn't flipped at Cloudflare."
  echo "Check the Cloudflare DNS panel and wait — TTL on the sslip-era record could be up to 1 hour."
  exit 1
fi

# Cross-check from a second resolver in case 1.1.1.1 is cached
dig +short ${DOMAIN} @8.8.8.8 | head -1
dig +short www.${DOMAIN} @1.1.1.1 | head -1

# Verify destination still has the migration overrides (proves pre-cutover state matches)
ssh root@${HOST_IP} "grep -q MIGRATION_TEMP_OVERRIDE /home/${SITE_USER}/htdocs/${DOMAIN}/wp-config.php" \
  || { echo "WARN: no MIGRATION_TEMP_OVERRIDE marker — site may have already been fixed up. Check 'wp option get siteurl'."; }
```

## Step 2 — Strip wp-config overrides

Idempotent: if the marker is gone, `sed` is a no-op. Backup is taken every time.

```bash
ssh root@${HOST_IP} bash <<STRIP
set -e
TS=\$(date -u +%Y%m%d-%H%M%S)
WPC=/home/${SITE_USER}/htdocs/${DOMAIN}/wp-config.php
if grep -q MIGRATION_TEMP_OVERRIDE "\$WPC"; then
  cp "\$WPC" "\${WPC}.bak.postmig.\$TS"
  sed -i "/MIGRATION_TEMP_OVERRIDE/,/WP_SITEURL.*sslip.io/d" "\$WPC"
  chown ${SITE_USER}:${SITE_USER} "\$WPC"
  chmod 640 "\$WPC"
  echo "STRIPPED: MIGRATION_TEMP_OVERRIDE block from \$WPC (backup \${WPC}.bak.postmig.\$TS)"
else
  echo "SKIP: no MIGRATION_TEMP_OVERRIDE in \$WPC"
fi
STRIP
```

The `sed -i "/MIGRATION_TEMP_OVERRIDE/,/WP_SITEURL.*sslip.io/d"` deletes from the marker comment through the `WP_SITEURL` line — exactly the block `cloudpanel-site-add` injected. If you customized that block, adjust the second pattern accordingly.

## Step 3 — `wp search-replace`, pass 1 (URL with scheme)

This is the workhorse. **Always dry-run first** for a sanity check on the source string; see [`references/search-replace-anatomy.md`](./references/search-replace-anatomy.md) for the flag rationale.

```bash
WP="sudo -u ${SITE_USER} -i wp --path=/home/${SITE_USER}/htdocs/${DOMAIN}"

# Sanity-check the source string actually appears in the DB
ssh root@${HOST_IP} "$WP db query \"SELECT option_value FROM wp_options WHERE option_name='siteurl'\""

# Dry-run first — this prints the per-table count without writing
ssh root@${HOST_IP} "$WP search-replace 'https://${SSLIP_URL}' 'https://${DOMAIN}' \
  --skip-columns=guid --report-changed-only --precise --dry-run"

# If counts look right, run for real:
ssh root@${HOST_IP} "$WP search-replace 'https://${SSLIP_URL}' 'https://${DOMAIN}' \
  --skip-columns=guid --report-changed-only --precise"
```

Real run on madomarche: **1830 replacements** across `wp_options` (68 PHP-serialized), `wp_postmeta` (787 PHP), `wp_posts post_content` (841 SQL), `wp_posts post_excerpt` (28 SQL), `wp_termmeta` (10 PHP), `wp_usermeta` (96 PHP).

## Step 4 — `wp search-replace`, pass 2 (bare hostname)

Plugins / themes sometimes store the hostname without scheme — Yoast SEO's canonical/sitemap settings, WP Rocket's CDN host, custom theme options. A second pass catches those.

```bash
ssh root@${HOST_IP} "$WP search-replace '${SSLIP_URL}' '${DOMAIN}' \
  --skip-columns=guid --report-changed-only --precise"
```

Real run on madomarche: **499 additional replacements**. Total across both passes: **2329**.

## Step 5 — Flush caches + permalinks

```bash
ssh root@${HOST_IP} "$WP cache flush"
ssh root@${HOST_IP} "$WP rewrite flush"
# LiteSpeed if installed (no-op if not)
ssh root@${HOST_IP} "$WP litespeed-purge all 2>/dev/null || true"
# WP Rocket if installed
ssh root@${HOST_IP} "$WP wp-rocket clean --post_id=all 2>/dev/null || true"
```

Stale caches will serve pages with the old sslip URL until purged. Always flush after search-replace.

## Step 6 — Verify DB looks correct

```bash
ssh root@${HOST_IP} "$WP option get siteurl"   # MUST be https://${DOMAIN}
ssh root@${HOST_IP} "$WP option get home"      # MUST be https://${DOMAIN}
```

If either still shows the sslip URL after a successful search-replace, you have a `WP_HOME` / `WP_SITEURL` define somewhere else in wp-config.php — Step 2's sed pattern missed something. Inspect `wp-config.php` manually.

## Step 7 — Issue real LE cert for apex + www

Pre-cutover this would have failed (LE's HTTP-01 challenge couldn't reach the new origin). Post-cutover it works because both names resolve to us.

```bash
ssh root@${HOST_IP} "clpctl lets-encrypt:install:certificate \
  --domainName=${DOMAIN} \
  --subjectAlternativeName=www.${DOMAIN}"

# clpctl usually reloads nginx itself, but verify:
ssh root@${HOST_IP} "nginx -t && systemctl reload nginx"
```

Idempotency: skip if `/etc/letsencrypt/live/${DOMAIN}` exists and the cert is valid for more than 7 days.

```bash
ssh root@${HOST_IP} "
  if [ -d /etc/letsencrypt/live/${DOMAIN} ]; then
    EXP=\$(openssl x509 -enddate -noout -in /etc/letsencrypt/live/${DOMAIN}/cert.pem | cut -d= -f2)
    DAYS=\$(( ( \$(date -d \"\$EXP\" +%s) - \$(date +%s) ) / 86400 ))
    [ \$DAYS -gt 7 ] && echo 'SKIP: cert valid for '\$DAYS' more days' && exit 0
  fi
"
```

## Step 8 — Smoke tests (each must pass)

```bash
ssh root@${HOST_IP} bash <<VERIFY
set -e
echo "1. Cert details (CN, SAN, issuer, dates):"
echo | openssl s_client -servername ${DOMAIN} -connect ${HOST_IP}:443 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName -issuer -dates

echo
echo "2. HTTPS reachability + cert chain valid:"
curl -sk -o /dev/null -m 15 -w "  https://${DOMAIN}:      HTTP %{http_code}  ssl_verify=%{ssl_verify_result}  (expect 200, 0)\n" "https://${DOMAIN}/"
curl -sk -o /dev/null -m 15 -w "  https://www.${DOMAIN}:  HTTP %{http_code}                                    (expect 301)\n" "https://www.${DOMAIN}/"
curl -sIL -m 15 -w "  Final URL: %{url_effective}\n" "http://${DOMAIN}/" 2>/dev/null | grep -E "^HTTP|^  Final"

echo
echo "3. No sslip.io leftover in rendered HTML (MUST be 0):"
curl -s -m 15 "https://${DOMAIN}/" | grep -c "sslip\.io" || true

echo
echo "4. Email DNS resolves (MX, SPF, DKIM):"
dig +short mx ${DOMAIN} @1.1.1.1
dig +short txt ${DOMAIN} @1.1.1.1 | grep -E '(spf|v=spf)' || echo "  WARN: no SPF record"
dig +short txt x._domainkey.${DOMAIN} @1.1.1.1 | head -c 80 || echo "  WARN: no DKIM x._domainkey record"
VERIFY
```

### Optional: security-plugin-aware wp-admin check

A `/wp-admin/ → 404` post-cutover is often a security plugin hiding admin under a custom slug stored in wp_options. The site is fine; you just need the renamed URL.

```bash
ssh root@${HOST_IP} "$WP option get whl_page 2>/dev/null || true"          # WPS Hide Login
ssh root@${HOST_IP} "$WP option get itsec_login_url 2>/dev/null || true"   # iThemes Security Pro
```

## Step 9 — (Optional) Send a test transactional email

Only run if SMTP is configured (WP Mail SMTP plugin or similar). Confirms post-DNS mail flow.

```bash
ssh root@${HOST_IP} "$WP wp-mail-smtp-test --to=${VERIFY_EMAIL} 2>/dev/null" || \
ssh root@${HOST_IP} "$WP eval \"wp_mail('${VERIFY_EMAIL}', 'Migration test for ${DOMAIN}', 'If you see this with SPF/DKIM/DMARC PASS in Gmail \\\"Show original\\\", post-migration email is healthy.');\""
```

Operator-side verification: open the message in Gmail → "Show original" → SPF, DKIM, DMARC should all read PASS. If DKIM is `none`, the DKIM TXT record at the DNS layer is missing or wrong — fix that via `cloudflare-dns-setup` before declaring done.

## Step 10 — Print OUTPUTS block

Print this exact block so downstream skills (or a human reviewer) can `grep -A 10 OUTPUTS_BEGIN` to parse it:

```
OUTPUTS_BEGIN
DOMAIN=madomarche.com
ORIGIN_IP=178.105.177.37
SEARCH_REPLACE_COUNT=2329
CERT_VALID_UNTIL=2026-08-29
HTTPS_STATUS=200
WWW_REDIRECT=301
SSLIP_LEFTOVER_COUNT=0
EMAIL_DNS_OK=true
OUTPUTS_END
```

`SEARCH_REPLACE_COUNT` is the sum of pass 1 + pass 2 (from `--report-changed-only` output). `CERT_VALID_UNTIL` from `openssl x509 -enddate`. `SSLIP_LEFTOVER_COUNT` from the Step 8 grep — anything non-zero is a bug to investigate before declaring done.

---

## Idempotency contract

| Step | Skip-guard | Reversal |
|---|---|---|
| 2 (strip overrides) | `! grep -q MIGRATION_TEMP_OVERRIDE wp-config.php` | Restore from `wp-config.php.bak.postmig.<ts>` |
| 3-4 (search-replace) | Not strictly idempotent — re-runs naturally return "0 replacements" | Restore DB from `nightly-backup-wp-cron` dump, retry with correct flags. See `references/search-replace-anatomy.md` |
| 5 (cache flushes) | No-op safe; nothing to skip | N/A |
| 7 (LE cert) | `[ -d /etc/letsencrypt/live/${DOMAIN} ] && cert valid for >7 days` | `certbot delete --cert-name ${DOMAIN}` then re-run |
| 8 (smoke tests) | Read-only; always runs | N/A |

A clean re-run after success prints `SKIP:` for steps 2 and 7, runs search-replace and gets "0 replacements" on every table, flushes caches (harmless), and re-asserts the smoke tests. Total runtime ~30 seconds.

---

## Common pitfalls (from the madomarche cutover, 2026-05-31)

- **`Could not retrieve a valid certificate` from clpctl lets-encrypt** — DNS hasn't propagated yet at the LE validator's resolver. The Step 1 dig check passed against `1.1.1.1`, but LE uses its own resolver pool. Wait 5 minutes and retry; cross-check with `dig ${DOMAIN} @8.8.8.8` and `dig ${DOMAIN} @9.9.9.9` to see what other resolvers see.

- **`wp search-replace` finds 0 hits in any table** — almost always the wrong source string. The most common cause: source DB has `https://madomarche.178-105-177-37.sslip.io` (with the IP dashed in) but you passed `https://madomarche.sslip.io` (without IP). Inspect the actual stored value first:
  ```bash
  $WP db query "SELECT option_value FROM wp_options WHERE option_name='siteurl'"
  ```
  Use that exact string as the source.

- **WooCommerce checkout breaks after search-replace** — usually because `--precise` wasn't used. SQL `REPLACE()` doesn't update the length prefix on serialized PHP strings, so any `s:42:"https://old..."` becomes `s:42:"https://new..."` even when the new value is 38 chars — PHP refuses to unserialize and silently drops the option. Re-run with `--precise`. If damage was already done, restore the DB from the `nightly-backup-wp-cron` dump and redo with correct flags. See `references/search-replace-anatomy.md` for the full mechanics.

- **`/wp-admin/` returns 404 post-cutover** — usually a security plugin (WPS Hide Login, iThemes Security Pro, Solid Security) hides admin under a custom slug stored in `wp_options`. The renamed URL works fine; just not `/wp-admin/`. Find the slug via `wp option get whl_page` (WPS Hide Login) or `wp option get itsec_login_url` (iThemes / Solid). Document the new login URL in the site's `/root/SERVER_NOTES.md` entry.

- **`sslip.io` leftover count > 0 in Step 8** — check what's left:
  ```bash
  curl -s "https://${DOMAIN}/" | grep -oE '[a-z0-9.-]*sslip\.io[^"]*' | sort -u
  ```
  Usual suspects: inline JSON-LD schema generated by Yoast (run pass 2 again — the bare-hostname pass may have missed a namespace), hard-coded URLs in theme `header.php` / `footer.php` (search-replace doesn't touch PHP files; grep + manual edit), or transients holding old URLs (`wp transient delete --all`).

- **`Final URL` from `curl -L http://${DOMAIN}/` is the sslip URL** — `WP_HOME` / `WP_SITEURL` still pointing at sslip, either via leftover wp-config block or DB. Re-run Step 2's strip, then Step 6's verify.

- **MX / SPF / DKIM disappeared after Cloudflare migration** — when `cloudflare-dns-setup` imported zones from the old DNS host, it may have skipped TXT records or set the wrong DKIM selector. Compare against the old zone export; common selectors are `default._domainkey`, `mail._domainkey`, `x._domainkey` (MXroute uses `x` by default). Re-add missing records at Cloudflare and re-test.

- **Test email arrives but SPF=fail / DKIM=fail** — the mail provider's sending IP isn't in your SPF, OR the DKIM TXT at DNS doesn't match the signing key the mail provider uses. For MXroute: `dig txt x._domainkey.${DOMAIN}` should match the value MXroute showed in its panel. See [[hetzner-smtp-port-blocked]] for related Hetzner SMTP gotchas.

---

## Outputs (consumed by paired skills / dashboards)

```
{
  "domain": "<DOMAIN>",
  "origin_ip": "<HOST_IP>",
  "search_replace_count": <int>,
  "cert_valid_until": "<YYYY-MM-DD>",
  "https_status": 200,
  "www_redirect": 301,
  "sslip_leftover_count": 0,
  "email_dns_ok": true
}
```

## Pairs Well With

- **[`cloudpanel-site-add`](../cloudpanel-site-add/)** *(REQUIRED prereq, mode=migration)* — produced the destination site, the sslip alias, the LE cert for sslip, and the `MIGRATION_TEMP_OVERRIDE` block this skill removes. The OUTPUTS block from `cloudpanel-site-add` feeds `HOST_IP` / `SITE_USER` / `SSLIP_URL` into this skill.
- **[`wp-migrate-guru-import`](../wp-migrate-guru-import/)** *(REQUIRED prereq)* — moved the DB + files from source to destination. Until that's done, the DB doesn't have any sslip URLs to flip.
- **[`cloudflare-dns-setup`](../cloudflare-dns-setup/)** *(REQUIRED prereq)* — the NS switch + A record flip is the trigger for running this skill. The Step 1 `dig` gate fails until DNS propagation finishes.
- **[`wp-bot-hardening`](../wp-bot-hardening/)** *(runs AFTER this)* — post-deploy hardening (bot UA block + xmlrpc deny + real wp-cron). Once the site is live at the real domain and bot crawls start arriving in earnest, hardening becomes urgent.
- **[`nightly-backup-wp-cron`](../nightly-backup-wp-cron/)** *(runs AFTER this)* — lock in nightly backups with the new domain in path names. If backups were already running with the sslip naming, update the cron entry path.

## References

### Sidecar reference files (loaded on demand)

- [`references/search-replace-anatomy.md`](./references/search-replace-anatomy.md) — why every flag matters: `--skip-columns=guid` (RSS notification storm), `--precise` (SQL REPLACE corrupts serialized PHP), `--report-changed-only` (readability), WooCommerce-specific tables that hold URLs, the two-pass URL+bare-hostname pattern, the dry-run gate, and the recovery procedure from a botched search-replace.

### Memory notes

- [[madomarche-migration]] — the production cutover this skill codifies (madomarche.com on cloudpanel-1, 2026-05-31). Has the actual 1830 + 499 = 2329 replacement counts and the WoodMart silent-duplication aftermath.
- [[cloudpanel-1-multi-tenant-host]] — the host this skill targets; read `/root/SERVER_NOTES.md` on the box before changing anything.
- [[hetzner-smtp-port-blocked]] — relevant if Step 9's test mail hangs exactly 60 seconds (Hetzner blocks outbound 25 / 465).

### External

- WP-CLI search-replace docs: https://developer.wordpress.org/cli/commands/search-replace/
- Let's Encrypt rate limits: https://letsencrypt.org/docs/rate-limits/ (relevant if you've re-issued the cert too many times during testing — limit is 5 per week per identical SAN set)
- Gmail "Show original" header reference (for SPF / DKIM / DMARC verification): https://support.google.com/mail/answer/29436

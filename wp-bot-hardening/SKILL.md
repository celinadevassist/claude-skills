---
name: "WP Bot Hardening"
description: "Block scraper / AI-training / SEO crawlers at nginx, deny /xmlrpc.php, and replace WP-cron-via-HTTP with real Linux cron — for a WordPress / WooCommerce site behind nginx + PHP-FPM (default: a CloudPanel host like cloudpanel-1). Idempotent, fully reversible, ~30 seconds per site. Use when a WC store complaints of intermittent slowness or 'becomes heavy', when PHP-FPM peak memory is far above its idle baseline, when nginx access logs show MJ12bot / PetalBot / Bytespider / Amazonbot / SemrushBot / AhrefsBot / GPTBot / ClaudeBot / meta-externalagent dominating last-hour traffic, or when onboarding a new site to a multi-tenant CloudPanel host as the post-deploy hardening step."
---

# WP Bot Hardening

## What This Skill Does

Applies three production-tested mitigations to a WordPress / WooCommerce site behind nginx + PHP-FPM:

1. **Bot user-agent block at nginx** — drops requests from ~25 known scraper / AI-training / SEO crawlers with a single `if ($http_user_agent ~* "...")` block injected after the apex `server_name`. Real search engines (Googlebot, Bingbot, Applebot, DuckDuckBot, Twitterbot, FacebookExternalHit) are intentionally kept.
2. **`/xmlrpc.php → 403` at nginx** — closes the classic pingback-amplification + brute-force vector. Already shipped in some CloudPanel WordPress vhost templates; the skill checks before adding.
3. **`DISABLE_WP_CRON` + real cron** — replaces WordPress's on-every-pageview cron with a per-site `/etc/cron.d/wp-cron-sites` entry that runs `wp cron event run --due-now --quiet` every 5 minutes as the site's Linux user.

All three changes are marker-commented (`# ===== HARDENING_BLOCK v1 (managed) =====`, `# ===== XMLRPC_DENY v1 (managed) =====`, `// ===== WP_CRON_DISABLED v1 (managed) =====`) so re-runs are no-ops and the changes are easy to find / revert. Vhost backups land next to the originals as `*.bak.harden.<UTC-ts>`.

On the cloudpanel-1 production run (2026-06-05) this deflected **~79% of bot hits at nginx** in the first 5-minute window — verified by live access-log tail. See [[madomarche-migration]].

## When to Use

- **WooCommerce store reports "site becomes heavy" or intermittent slowness** with no obvious cause in WC code or recent deploys. Bot crawl bursts are the #1 cause on small ARM/x86 boxes.
- **`free -h` shows swap > 0** on a 4–8 GB server that was idle a few hours ago — PHP-FPM children got swapped during a bot burst. Hardening prevents the next one.
- **Access logs show >100 requests/hour** from any single bot UA in the blocklist below.
- **Right after `cloudpanel-site-add` finishes** a new tenant — pair these two skills as the standard onboarding chain.
- **Re-running on the same host** when a new site has been added since the last hardening pass. Idempotent: existing sites are skipped, new ones get the full treatment.

## When NOT to Use

- Site is **behind Cloudflare orange-cloud** (proxied) — bot mitigation already happens at the CF edge via Bot Fight Mode. Applying this at origin too is harmless but redundant. For cloudpanel-1 specifically, sites are grey-cloud (per [[cloudflare-proxy-preference]]) so origin-level hardening IS needed.
- Site **legitimately depends on `/xmlrpc.php`** (very rare in 2026: old Jetpack < 4.0, certain Movable Type ping-back setups, some IFTTT recipes). Verify before applying.
- **Non-CloudPanel nginx** with a radically different vhost layout — the skill's injection logic targets CloudPanel's standard vhost template (3 server blocks: www→non-www redirect on 80/443, main HTTPS, internal 8080). Other layouts may need the injection point adapted manually. See [`references/cloudpanel-vhost-anatomy.md`](./references/cloudpanel-vhost-anatomy.md).

## Prerequisites

- SSH root access to the host. Every command in this skill assumes `root` and runs over SSH (`ssh -i ~/.ssh/<key> root@${HOST_IP}`).
- **nginx** (any version) serving WordPress.
- **wp-cli** in `$PATH` for the site user (CloudPanel ships `/usr/bin/wp` by default).
- **cron** (systemd `cron.service`) active. Verify: `systemctl is-active cron`.
- Backup of the vhost files and `wp-config.php` is taken automatically by the skill; if you want extra paranoia, run `cloudpanel-site-add`'s nightly backup script before applying.

---

## Inputs (collect once before Step 1)

| Var | Example | Notes |
|---|---|---|
| `HOST_IP` | `178.105.177.37` | The CloudPanel server's public IPv4 |
| `SITES` | `[(madomarche, madomarche.com), (armadorn, armadorn.com)]` | List of `(site_user, domain)` tuples. If omitted, the skill auto-discovers from `ls /etc/nginx/sites-enabled/*.com.conf` and asks for confirmation before touching each one. |
| `DRY_RUN` | `0` \| `1` | When `1`, prints the planned diff for each site without writing anything. Default `0`. |

**Discovery default** when `SITES` is unset:

```bash
ssh root@${HOST_IP} '
for vhost in /etc/nginx/sites-enabled/*.com.conf; do
  domain=$(basename "$vhost" .conf)
  user=$(stat -c %U "/home/$(echo $domain | cut -d. -f1)/htdocs/$domain" 2>/dev/null)
  [ -n "$user" ] && echo "$user $domain"
done'
```

---

## Step 1 — Pre-flight (idempotency gates)

For each site, classify what work is needed. **No writes** in this step.

```bash
ssh root@${HOST_IP} bash <<CHECK
set -e
VHOST=/etc/nginx/sites-enabled/${DOMAIN}.conf
WPC=/home/${SITE_USER}/htdocs/${DOMAIN}/wp-config.php
echo "Site: ${SITE_USER} / ${DOMAIN}"
echo "  vhost:        \$([ -f \$VHOST ] && echo OK || echo MISSING)"
echo "  wp-config:    \$([ -f \$WPC ] && echo OK || echo MISSING)"
echo "  hardening:    \$(grep -q 'HARDENING_BLOCK v1' \$VHOST && echo PRESENT || echo TODO)"
echo "  xmlrpc deny:  \$(grep -qE 'location\s*=\s*/xmlrpc\.php' \$VHOST && echo PRESENT || echo TODO)"
echo "  wp-cron off:  \$(grep -qE \"define\\s*\\(\\s*'DISABLE_WP_CRON'\" \$WPC && echo PRESENT || echo TODO)"
echo "  cron entry:   \$(grep -q \"madomarche\" /etc/cron.d/wp-cron-sites 2>/dev/null && echo PRESENT || echo TODO)"
CHECK
```

Anything reading `PRESENT` is skipped in its respective step below. `MISSING` aborts (the site doesn't exist on this host — wrong inputs).

If `DRY_RUN=1`, stop here and print what each remaining step **would** change.

## Step 2 — Bot user-agent block (the biggest single win)

Inject into the **main HTTPS server block** of each vhost, right after the apex `server_name` line. The marker comment makes the block trivially greppable + reversible.

```bash
ssh root@${HOST_IP} bash <<'INJECT'
set -euo pipefail
TS=$(date -u +%Y%m%d-%H%M%S)
HARDENING='  # ===== HARDENING_BLOCK v1 (managed) =====
  # Blocks scraper / AI-training / SEO crawlers with no commercial value to this store.
  # KEEPS Googlebot, Bingbot, Applebot (without -Extended), DuckDuckBot, Twitterbot, FacebookExternalHit.
  # If a desired bot ends up here, remove its token from the regex below.
  if ($http_user_agent ~* "(MJ12bot|PetalBot|Bytespider|Amazonbot|SemrushBot|AhrefsBot|GPTBot|ClaudeBot|Claude-User|anthropic-ai|CCBot|DataForSeoBot|DotBot|MauiBot|BLEXBot|ZoominfoBot|meta-externalagent|Applebot-Extended|PerplexityBot|YandexBot|SeznamBot|Sogou|MegaIndex|serpstatbot|360Spider|YisouSpider|Bytedance)") {
    return 403;
  }
  # ===== /HARDENING_BLOCK v1 ====='

VHOST=/etc/nginx/sites-enabled/${DOMAIN}.conf
if grep -q 'HARDENING_BLOCK v1' "$VHOST"; then
  echo "SKIP: hardening already in $VHOST"
else
  cp "$VHOST" "${VHOST}.bak.harden.${TS}"
  # Match the apex server_name line, NOT the www-only redirect block on line ~12
  awk -v block="$HARDENING" -v dom="${DOMAIN}" '
    { print }
    !done && $0 ~ ("^  server_name "dom)"( |;)" { print block; done=1 }
  ' "$VHOST" > "${VHOST}.tmp" && mv "${VHOST}.tmp" "$VHOST"
  echo "INJECTED: hardening into $VHOST (backup ${VHOST}.bak.harden.${TS})"
fi
INJECT
```

**See [`references/bot-ua-catalog.md`](./references/bot-ua-catalog.md)** for the full per-bot rationale (who runs each crawler, why it's blocked, whether to revisit if the store expands to a market where one of these matters).

## Step 3 — `/xmlrpc.php → 403`

Some CloudPanel WordPress templates already ship this. Check first; only add if missing.

```bash
ssh root@${HOST_IP} bash <<'XMLRPC'
set -euo pipefail
VHOST=/etc/nginx/sites-enabled/${DOMAIN}.conf
if grep -qE '^\s*location\s*=\s*/xmlrpc\.php' "$VHOST"; then
  echo "SKIP: xmlrpc deny already in $VHOST"
else
  awk '
    /^  location ~ \/\.well-known \{/ && !inserted {
      print "  # ===== XMLRPC_DENY v1 (managed) ====="
      print "  location = /xmlrpc.php {"
      print "    deny all;"
      print "    access_log off;"
      print "    log_not_found off;"
      print "  }"
      print "  # ===== /XMLRPC_DENY v1 ====="
      print ""
      inserted=1
    }
    { print }
  ' "$VHOST" > "${VHOST}.tmp" && mv "${VHOST}.tmp" "$VHOST"
  echo "INJECTED: xmlrpc deny into $VHOST"
fi
XMLRPC
```

Insertion anchor is the `location ~ /.well-known {` line because every CloudPanel WP vhost has it — see [`references/cloudpanel-vhost-anatomy.md`](./references/cloudpanel-vhost-anatomy.md) for why.

## Step 4 — `DISABLE_WP_CRON` + real cron

### 4a. wp-config.php

```bash
ssh root@${HOST_IP} bash <<'WPCRON'
set -euo pipefail
TS=$(date -u +%Y%m%d-%H%M%S)
WPC=/home/${SITE_USER}/htdocs/${DOMAIN}/wp-config.php
if grep -qE "define\s*\(\s*'DISABLE_WP_CRON'" "$WPC"; then
  echo "SKIP: DISABLE_WP_CRON already in $WPC"
else
  cp "$WPC" "${WPC}.bak.crondisable.${TS}"
  awk '
    /That.s all, stop editing/ && !inserted {
      print "// ===== WP_CRON_DISABLED v1 (managed) — real cron via /etc/cron.d/wp-cron-sites ====="
      print "define( '\''DISABLE_WP_CRON'\'', true );"
      print ""
      inserted=1
    }
    { print }
  ' "$WPC" > "${WPC}.tmp" && mv "${WPC}.tmp" "$WPC"
  chown ${SITE_USER}:${SITE_USER} "$WPC"
  chmod 640 "$WPC"
  echo "INJECTED: DISABLE_WP_CRON into $WPC (backup ${WPC}.bak.crondisable.${TS})"
fi
WPCRON
```

### 4b. /etc/cron.d/wp-cron-sites (rewritten atomically every run)

The cron file is the **source of truth** for which sites get real cron — re-running the skill regenerates it from the current `SITES` list. New sites are added; removed sites are dropped.

```bash
ssh root@${HOST_IP} bash <<CRON
set -e
WP=\$(command -v wp || echo /usr/local/bin/wp)
cat > /etc/cron.d/wp-cron-sites <<EOF
# Real WordPress cron for cloudpanel-1 tenants — replaces wp-cron.php-on-every-pageview.
# Each site runs as its own Linux user so file ownership stays correct.
# Managed by wp-bot-hardening skill (re-run regenerates this file from current SITES).
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

$(for tuple in "\${SITES[@]}"; do
  user="\${tuple%% *}"; domain="\${tuple##* }"
  echo "*/5 * * * * \$user \$WP --path=/home/\$user/htdocs/\$domain cron event run --due-now --quiet >/dev/null 2>&1"
done)
EOF
chmod 644 /etc/cron.d/wp-cron-sites
echo "WROTE: /etc/cron.d/wp-cron-sites"
cat /etc/cron.d/wp-cron-sites
CRON
```

## Step 5 — Verification (must all pass before declaring success)

```bash
ssh root@${HOST_IP} bash <<'VERIFY'
set -e
echo "1. nginx config syntax:"
nginx -t 2>&1 | tail -2
echo
echo "2. Reload nginx:"
systemctl reload nginx && echo "  OK"
echo
echo "3. cron service active:"
systemctl is-active cron
echo
echo "4. Per-site curl smoke test:"
for tuple in "${SITES[@]}"; do
  user="${tuple%% *}"; D="${tuple##* }"
  echo "  --- $D ---"
  curl -sk -o /dev/null -m 10 -w "    Chrome:      HTTP %{http_code}  (expect 200)\n" \
    -A "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130 Safari/537.36" "https://$D/"
  curl -sk -o /dev/null -m 10 -w "    MJ12bot:     HTTP %{http_code}  (expect 403)\n" \
    -A "Mozilla/5.0 (compatible; MJ12bot/v1.4.8; http://mj12bot.com/)" "https://$D/"
  curl -sk -o /dev/null -m 10 -w "    Googlebot:   HTTP %{http_code}  (expect 200 — MUST NOT 403)\n" \
    -A "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" "https://$D/"
  curl -sk -o /dev/null -m 10 -w "    xmlrpc.php:  HTTP %{http_code}  (expect 403)\n" "https://$D/xmlrpc.php"
  echo "    DISABLE_WP_CRON: $(sudo -u $user -i wp --path=/home/$user/htdocs/$D eval 'echo defined("DISABLE_WP_CRON") && DISABLE_WP_CRON ? "DISABLED" : "still enabled (BAD)";' 2>/dev/null)"
  echo "    wp cron run:     $(sudo -u $user -i wp --path=/home/$user/htdocs/$D cron event run --due-now 2>&1 | tail -1)"
done
VERIFY
```

If Chrome returns anything but 200, or Googlebot returns 403, **roll back** (see Idempotency contract → reversal).

### Post-apply live proof (30-second tail)

Show the user that the rules are firing on real traffic, not just synthetic curls:

```bash
ssh root@${HOST_IP} bash -c '
timeout 30 tail -F /home/*/logs/nginx/access.log 2>/dev/null | \
  awk "/MJ12bot|PetalBot|Bytespider|Amazonbot|SemrushBot|AhrefsBot|GPTBot|ClaudeBot|meta-externalagent/ \
       { printf \"  %s %s %s\n\", \$9, gensub(/.*(MJ12bot|PetalBot|Bytespider|Amazonbot|SemrushBot|AhrefsBot|GPTBot|ClaudeBot|meta-externalagent).*/, \"\\\\1\", \"g\"), \$7 }" | head -20'
```

On the cloudpanel-1 production run this caught a real MJ12bot burst hammering 30+ WC faceted-filter URLs (`?min_price=&orderby=&stock_status=&shop_view=`) — all `403`, none reaching PHP.

---

## Idempotency contract

| Step | Skip-guard | Reversal |
|---|---|---|
| 2 (bot UA block) | `grep -q 'HARDENING_BLOCK v1' $VHOST` | Restore from `${VHOST}.bak.harden.<ts>` or `sed -i '/HARDENING_BLOCK v1/,/\/HARDENING_BLOCK v1/d' $VHOST` + `systemctl reload nginx` |
| 3 (xmlrpc deny) | `grep -qE 'location\s*=\s*/xmlrpc\.php' $VHOST` | Delete the `XMLRPC_DENY v1` block (same sed pattern) + reload |
| 4a (DISABLE_WP_CRON) | `grep -qE "define\s*\(\s*'DISABLE_WP_CRON'" $WPC` | Restore from `${WPC}.bak.crondisable.<ts>` or remove the marker block |
| 4b (cron file) | none — atomic rewrite every run | `rm /etc/cron.d/wp-cron-sites` |

A re-run with no new sites and all markers already present prints `SKIP:` for every step and rewrites only the cron file (atomic, byte-identical content if `SITES` unchanged).

---

## Common pitfalls

- **CloudPanel re-renders vhost files on cert reissue / PHP-version change / vhostTemplate switch.** When this happens, the HARDENING_BLOCK and XMLRPC_DENY markers are wiped — the wp-config and cron entries survive. **Run this skill again** to restore the nginx side. Monthly health check:
  ```bash
  ssh root@${HOST_IP} "
    missing=\$(for v in /etc/nginx/sites-enabled/*.com.conf; do
      grep -L 'HARDENING_BLOCK v1' \$v
    done)
    [ -n \"\$missing\" ] && echo 'WIPED — re-run wp-bot-hardening for:' && echo \"\$missing\"
  "
  ```
  Wire this into `uptime-kuma-add-monitor` as a script monitor that fires monthly. The marker is gone within seconds of a panel re-render, but Uptime Kuma checking monthly catches it before a serious bot burst hits.

- **Googlebot must not be in the blocklist regex.** Real search bots bring buyers. The regex above uses exact tokens (`Applebot-Extended` specifically, NOT bare `Applebot`) — be careful editing. Test every change with the verification curl block before reloading nginx.

- **`grep -qE "define\s*\(\s*'DISABLE_WP_CRON'"` matches both `true` AND `false` definitions.** If a site already has `define('DISABLE_WP_CRON', false);` for some reason, the skill skips — but cron-via-HTTP is still active. Always check the actual value in pre-flight (`wp eval 'echo DISABLE_WP_CRON;'`) and fix manually.

- **Bot UAs evolve.** Every 6 months, re-run the access-log analysis from the SKILL preamble of [[madomarche-migration]] and check the top-15 UAs for new junk crawlers. Add new tokens to the regex, increment the marker to `v2`, re-deploy.

- **The cron entries use `wp --path=...` not `cd && wp`.** wp-cli's `--path` flag is the only way to get correct CWD without leaking environment. `cd` in cron is a common bug source (depends on user shell, doesn't fail loudly).

- **If wp-cli isn't `/usr/bin/wp`** (some CloudPanel installs put it under `/usr/local/bin/wp` or none at all), the `command -v wp || echo /usr/local/bin/wp` fallback in Step 4b may write a dead path. Verify with `ssh root@${HOST_IP} 'which wp'` before running.

---

## Pairs Well With

- **[`cloudpanel-site-add`](../cloudpanel-site-add/)** — run THIS skill immediately after that one finishes. The OUTPUTS block from `cloudpanel-site-add` (`DOMAIN`, `SITE_USER`) feeds directly into this skill's `SITES` input.
- **[`nightly-backup-wp-cron`](../nightly-backup-wp-cron/)** *(planned)* — independent but related: both are post-deploy hardening. Order doesn't matter; run both.
- **[`uptime-kuma-add-monitor`](../uptime-kuma-add-monitor/)** *(planned)* — host the monthly `HARDENING_BLOCK v1` marker-presence check there as a script monitor.

## References

### Sidecar reference files (loaded on demand)

- [`references/bot-ua-catalog.md`](./references/bot-ua-catalog.md) — every UA in the blocklist with who runs it, why it's blocked (commercial value: none / AI training / SEO competitor scraper), the bot's official page, and a decision tree for when to revisit (e.g. if expanding to the CN market, you'd unblock Yisou/Sogou/360 and PetalBot).
- [`references/cloudpanel-vhost-anatomy.md`](./references/cloudpanel-vhost-anatomy.md) — the structure of CloudPanel's WordPress vhost (3 server blocks: www-redirect, main HTTPS, internal `:8080`), exact safe injection anchors, and what survives a CloudPanel re-render vs what doesn't.

### Memory notes

- [[madomarche-migration]] — first production run of this skill (madomarche.com + armadorn.com on cloudpanel-1, 2026-06-05). Has the live before/after numbers and the bot-traffic analysis that motivated this skill.
- [[cloudpanel-1-multi-tenant-host]] — the host this skill targets.
- [[cloudflare-proxy-preference]] — why cloudpanel-1 sites stay grey-cloud (and therefore why origin-level hardening is needed instead of relying on CF Bot Fight Mode).

### External

- nginx `map` vs `if` debate: https://nginx.org/en/docs/http/ngx_http_rewrite_module.html#if — using `if` inside a server block (not location) for UA matching is one of the explicitly safe `if` uses per the maintainers
- WP-CLI cron docs: https://developer.wordpress.org/cli/commands/cron/
- robots.txt spec (for the "well-behaved bots will respect it anyway" defense): https://www.rfc-editor.org/rfc/rfc9309.html

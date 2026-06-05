# CloudPanel WordPress Vhost Anatomy

Sidecar reference for `wp-bot-hardening`. Documents the structure of a CloudPanel 6.x WordPress vhost file at `/etc/nginx/sites-enabled/<domain>.conf`, the safe injection anchors used by the skill's awk patterns, and which edits survive a CloudPanel re-render vs which don't.

Open this file when:
- Adapting the skill to a non-CloudPanel nginx (different vhost layout)
- Debugging an injection that landed in the wrong server block
- Investigating why a marker disappeared (CloudPanel may have re-rendered the vhost)

---

## The three server blocks

Every CloudPanel WP vhost has the same skeleton — three `server { }` blocks. Knowing which is which is the difference between hardening that works and hardening that lands inside an 8080 internal block where it never sees public traffic.

### Block 1 — `www.<domain>` redirect (lines ~1–15)

```
server {
  listen 80;
  listen [::]:80;
  listen 443 quic;
  listen 443 ssl;
  listen [::]:443 quic;
  listen [::]:443 ssl;

  http2 on;
  http3 on;

  server_name www.<domain>;
  return 301 $scheme://<domain>$request_uri;
}
```

- Sole purpose: redirect `www.<domain>` → `<domain>`.
- Injecting hardening here is **useless** — it never serves a real page, just `301`s.
- **DO NOT match `server_name www.<domain>;` as the injection anchor.** It's the wrong block.

### Block 2 — Main HTTPS server (lines ~16–107) — **inject here**

```
server {
  listen 80;
  listen [::]:80;
  listen 443 quic;
  listen 443 ssl;
  listen [::]:443 quic;
  listen [::]:443 ssl;

  { various ssl_*, add_header, root, index directives }

  server_name <domain> www1.<domain>;          ← match THIS line, exact ^"  server_name <domain> "
  
  # >>>>>> INJECT HARDENING_BLOCK HERE <<<<<<

  location ~ /.well-known {
    auth_basic off;
    allow all;
  }
  
  # >>>>>> XMLRPC_DENY goes ABOVE this line (anchor: /.well-known) <<<<<<

  location ~/\.git {
    deny all;
  }

  location = /xmlrpc.php {        ← MAY OR MAY NOT exist depending on template version
    deny all;
  }

  location ~/(wp-admin/|wp-login.php) { ... }
  location / { ... try_files ... fastcgi_pass ... }
  location ~* ^.+\.(css|js|...) { ... cache headers ... }
}
```

- **This is where everything goes.** Bot UA block, xmlrpc deny, anything else.
- The `server_name` line is **deterministic** in CloudPanel templates: apex first, then `www1.<domain>` (CloudPanel's odd default for the canonical secondary). The awk anchor in SKILL.md `^  server_name <domain>` matches the START of this line, which only appears in Block 2.
- Some older CloudPanel templates use `www.<domain>` instead of `www1.<domain>` as the secondary — the regex still matches because we anchor on the apex.

### Block 3 — Internal `:8080` (lines ~108–end)

```
server {
  listen 8080;
  listen [::]:8080;
  
  server_name <domain> www1.<domain>;   ← same server_name! Could fool a naive anchor

  { ssl_*, root, index }

  location ~ \.php$ {
    try_files $uri =404;
    fastcgi_pass 127.0.0.1:900X;
    ...
  }
}
```

- Used internally by CloudPanel for certain operations (status checks, internal proxy hops, the file manager). Not exposed publicly.
- **server_name is identical to Block 2.** This is why the awk anchor in SKILL.md uses `done=1` after first match — it only injects into the FIRST match, which is Block 2 because file order matches line order.
- If you ever need to inject into Block 3 separately (rare), use `listen 8080` as part of the anchor:
  ```awk
  /listen 8080/ { in_8080=1 }
  in_8080 && /server_name/ && !done { print; print "  # ..."; done=1; next }
  ```

---

## Injection anchors used by the skill

| Step | Anchor regex | Why it works | Risk |
|---|---|---|---|
| 2 (bot UA block) | `^  server_name <domain>( \|;)` | Apex domain at start-of-line; matches Block 2 (and Block 3 if `done=1` flag wasn't there). awk `!done` gates to first match only. | If two sites' vhosts somehow combined, could double-inject. Doesn't happen — each domain has its own vhost file. |
| 3 (xmlrpc deny) | `^  location ~ /\.well-known \{` | First location in Block 2; always present (CloudPanel needs it for LE renewals). Injecting BEFORE it puts xmlrpc deny early in the request-routing chain. | If a future CloudPanel version drops `.well-known` (won't happen — LE depends on it), the anchor fails and inject is a no-op. |
| 4a (wp-config edit) | `That.s all, stop editing` | The canonical WP marker, present in EVERY wp-config.php since WP 2.0. | If a custom wp-config skeleton dropped it (rare), the skill falls back to appending at EOF. |

---

## What survives a CloudPanel re-render — and what doesn't

CloudPanel re-renders vhost files from a template + per-site database row on these operations:
- `clpctl lets-encrypt:install:certificate ...` (cert install or auto-renewal)
- `clpctl site:install:certificate ...` (manual cert install)
- Changing PHP version via UI or `clpctl`
- Changing the vhost template (`Generic` ↔ `WordPress` etc.)
- Site-level config edits in the panel UI ("Additional Configuration" textarea, PHP settings, etc.)

| Edit | Lives in | Survives re-render? |
|---|---|---|
| HARDENING_BLOCK v1 (bot UA) | nginx vhost (`/etc/nginx/sites-enabled/<d>.conf`) | ❌ Wiped |
| XMLRPC_DENY v1 | nginx vhost | ❌ Wiped |
| DISABLE_WP_CRON | wp-config.php (`/home/<u>/htdocs/<d>/wp-config.php`) | ✅ Survives (CloudPanel never touches wp-config) |
| `/etc/cron.d/wp-cron-sites` | systemd cron dir | ✅ Survives |
| Backup tarballs in `/var/backups/<site>/` | host filesystem | ✅ Survives |
| Backups of vhost in `<vhost>.bak.harden.<ts>` | host filesystem | ✅ Survives (sit next to vhost; restore by `cp` after a re-render wipes the live file) |

**The asymmetry matters.** If you only check "did the cron entry survive?" you'll think the skill held — but the actual hot-path mitigation (the nginx UA block) is silently gone. **Use the marker grep, not the cron file, as the canary:**

```bash
ssh root@${HOST_IP} "
  for v in /etc/nginx/sites-enabled/*.com.conf; do
    grep -L 'HARDENING_BLOCK v1' \$v
  done
"
```

Empty output = healthy. Any vhost listed = wiped, re-run the skill.

---

## "CloudPanel-native" alternative: vhost templates

For a setup that **truly** survives re-renders, the only safe path is to make the bot-block part of the **vhost template itself** instead of injecting into the rendered file:

```bash
# Pull the current WordPress template
ssh root@${HOST_IP} 'clpctl vhost-template:view --name=WordPress' > /tmp/wp-template.tpl

# Edit /tmp/wp-template.tpl — add the HARDENING_BLOCK in the main server block

# Re-import under a new name (system templates are read-only)
scp /tmp/wp-template.tpl root@${HOST_IP}:/tmp/wp-hardened.tpl
ssh root@${HOST_IP} 'clpctl vhost-template:add --name="WordPress (hardened)" --file=/tmp/wp-hardened.tpl'

# Switch the site to it via UI: Site → Settings → Vhost → Template = WordPress (hardened)
```

After that, every CloudPanel re-render uses your hardened template — markers can't be wiped because they're built into the source.

Tradeoff: the template form is harder to iterate on. Use injection (the SKILL.md default) for ongoing tuning; promote to a template once the regex is stable.

---

## Adapting to non-CloudPanel nginx setups

The SKILL.md injection logic assumes the CloudPanel template. For a hand-rolled nginx config, the broad pattern is:

1. **Find the main HTTPS server block.** In hand-rolled configs there's usually only ONE — easier than CloudPanel's three.
2. **Anchor on `server_name`.** Same approach, simpler matching.
3. **Verify the `.well-known/acme-challenge` location exists.** If not, the xmlrpc anchor breaks — pick a different anchor like `^\s*root ` (the root directive is always near the top of the server block).

A minimal portable injection block (good for Caddy → nginx migrations, Plesk, manual setups):

```awk
# Match the first server_name line in any HTTPS block (port 443)
in_https && /server_name/ && !done {
  print
  print "  # ===== HARDENING_BLOCK v1 (managed) ====="
  print "  if ($http_user_agent ~* \"...\") { return 403; }"
  print "  # ===== /HARDENING_BLOCK v1 ====="
  done=1
  next
}
/listen 443/ { in_https=1 }
{ print }
```

The CloudPanel-specific version in SKILL.md is more conservative because we know the template — for other setups, prefer the broader awk above.

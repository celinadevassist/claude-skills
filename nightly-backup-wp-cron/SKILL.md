---
name: "Nightly Backup WP Cron"
description: "Install per-site nightly WordPress backups on a CloudPanel host — DB dump + files tarball, 7-day local retention, atomic cron file regeneration as the source of truth for which sites are backed up. Handles both MySQL native and MariaDB-Docker sidecar engines transparently via wp-cli. Idempotent: re-run after adding/removing sites and the cron schedule self-heals. Use immediately after `cloudpanel-site-add` finishes a new tenant, or as a one-shot pass to backfill backups across every existing site on a multi-tenant host (e.g. cloudpanel-1)."
---

# Nightly Backup WP Cron

## What This Skill Does

Installs per-site nightly backups on a multi-tenant CloudPanel host. For each WordPress / WooCommerce site:

1. Drops a backup script at `/usr/local/bin/<site_user>-backup.sh` that does a `wp db export | gzip` of the database and a `tar -czf` of the WP files (with the obvious bloat directories excluded).
2. Atomically regenerates `/etc/cron.d/sites-backup` — a single shared cron file listing every backed-up site at staggered nightly times. **This file is the source of truth**: removing a site from the input list and re-running the skill removes its cron line.
3. Stores backups at `/var/backups/<site_user>/` with **7-day local retention** (separate `db-*.sql.gz` and `files-*.tar.gz` files, pruned via `find -mtime +7 -delete`).
4. Runs each script once synchronously to verify it works *now* — so a broken wp-cli path, unreadable wp-config, or DB-auth issue fails loud instead of silently at 03:00 UTC.

The script is **engine-agnostic**: `wp db export` reads `wp-config.php` to figure out the DB connection. CloudPanel's native MySQL on `:3306` and per-site MariaDB-Docker sidecars on `127.0.0.1:330X` both work without any branching — wp-cli's MySQL client connects natively to either. No `docker exec` needed.

On the cloudpanel-1 production run (2026-05-31) this set up backups for `madomarche` (MySQL native, ~8 MB DB + 11 MB files) and `armadorn` (MariaDB sidecar, ~6 MB DB + 2.4 GB files) — see [[madomarche-migration]].

## When to Use

- **Right after `cloudpanel-site-add` finishes** a new tenant — pair these two as the standard onboarding chain.
- **Backfilling backups** across an existing multi-tenant host that was set up without them.
- **After removing a site** from the host — re-run with the new `SITES` list to drop the orphaned cron line.
- **After moving a site to a different DB engine** (MySQL → MariaDB-Docker or vice-versa) — re-run; the script content is engine-agnostic so it just keeps working.

## When NOT to Use

- **Single-tenant box with one site** where you'd rather use a hosted backup product (UpdraftPlus to S3, BackWPup to B2, etc.) — that's fine, but those run *inside* PHP and miss things like wp-config and the nginx vhost. This skill is the belt-and-braces lower-level layer.
- **Site uses an external managed DB** (RDS, PlanetScale, etc.) where `wp db export` would try to dump over the network — works, but think about egress cost and lock duration before scheduling nightly.
- **You need off-site copies right now.** This skill only does local retention. See "NOT included" below and the planned `offsite-backup-sync` skill.

## Prerequisites

- SSH root access to the CloudPanel host. Every command in this skill assumes `root` and runs over SSH (`ssh -i ~/.ssh/<key> root@${HOST_IP}`).
- **wp-cli** in `$PATH` for each site user (CloudPanel ships `/usr/bin/wp` by default; verify with `ssh root@${HOST_IP} 'which wp'`).
- **cron** (systemd `cron.service`) active. Verify: `systemctl is-active cron`.
- At least **~3 GB free disk** for `/var/backups` per site for typical WC stores; the skill checks and warns.
- The DB sidecars (if any) are already running — `cloudpanel-site-add` sets that up.

---

## Inputs (collect once before Step 1)

| Var | Example | Notes |
|---|---|---|
| `HOST_IP` | `178.105.177.37` | The CloudPanel server's public IPv4 |
| `SITES` | `[(madomarche, madomarche.com), (armadorn, armadorn.com)]` | List of `(site_user, domain)` tuples. If omitted, auto-discover from `ls /etc/nginx/sites-enabled/*.com.conf` (same logic as `wp-bot-hardening`). |
| `RETENTION_DAYS` | `7` | How many daily snapshots to keep. Default `7`. |
| `BACKUP_ROOT` | `/var/backups` | Where per-site directories live. Default `/var/backups`. |
| `CRON_HOUR_START` | `3` | First backup runs at `${CRON_HOUR_START}:00 UTC`, subsequent sites staggered every 30 min. Default `3`. |

**Discovery default** when `SITES` is unset (same auto-discovery as `wp-bot-hardening`):

```bash
ssh root@${HOST_IP} '
for vhost in /etc/nginx/sites-enabled/*.com.conf; do
  domain=$(basename "$vhost" .conf)
  user=$(stat -c %U "/home/$(echo $domain | cut -d. -f1)/htdocs/$domain" 2>/dev/null)
  [ -n "$user" ] && echo "$user $domain"
done'
```

---

## Step 1 — Pre-flight per site

For each `(site_user, domain)` tuple, classify what's needed. **No writes** in this step.

```bash
ssh root@${HOST_IP} bash <<CHECK
set -e
SITE=/home/${SITE_USER}/htdocs/${DOMAIN}
DEST=${BACKUP_ROOT}/${SITE_USER}
echo "Site: ${SITE_USER} / ${DOMAIN}"
echo "  docroot:    \$([ -d \$SITE ] && echo OK || { echo MISSING; exit 1; })"
echo "  wp-cli:     \$(sudo -u ${SITE_USER} -i wp --path=\$SITE core version 2>/dev/null || echo BROKEN)"
echo "  dest dir:   \$([ -d \$DEST ] && echo EXISTS || echo NEW)"
echo "  site size:  \$(du -sh \$SITE 2>/dev/null | cut -f1)"
echo "  disk free:  \$(df -h ${BACKUP_ROOT} | awk 'NR==2{print \$4}')"
CHECK
```

Estimate disk need: `site_size * 1.5 * RETENTION_DAYS` (DB dump is typically tiny vs files; the 1.5× covers compression headroom + the day-of-run double-buffer). If estimated need exceeds free space, **abort** — don't half-install backups that will fill the disk on day 4.

`wp-cli BROKEN` aborts: the script can't dump the DB without it. Fix wp-cli first (usually a wp-config perms issue or a missing PHP extension), then re-run.

## Step 2 — Drop the per-site backup script

Generated from a single template per site, substituting `<site_user>` and `<domain>`. Always overwrite — the script content is fully determined by `(site_user, domain, BACKUP_ROOT, RETENTION_DAYS)` so re-renders are byte-identical no-ops.

```bash
ssh root@${HOST_IP} "cat > /usr/local/bin/${SITE_USER}-backup.sh <<'BACKUP'
#!/bin/bash
# Nightly ${SITE_USER} backup — DB dump + site files tarball, ${RETENTION_DAYS}-day retention.
# Managed by nightly-backup-wp-cron skill. Re-run regenerates this file.
# Tolerates tar warnings (live cache files changed during read).
set -uo pipefail
SITE=/home/${SITE_USER}/htdocs/${DOMAIN}
DEST=${BACKUP_ROOT}/${SITE_USER}
STAMP=\$(date -u +%Y-%m-%d)
LOG=\$DEST/backup.log
mkdir -p \"\$DEST\"
exec > >(tee -a \"\$LOG\") 2>&1
echo \"===== \$(date -u) | starting backup =====\"

# 1) DB dump
DBFILE=\$DEST/db-\${STAMP}.sql.gz
if sudo -u ${SITE_USER} -i wp --path=\"\$SITE\" db export - 2>/dev/null | gzip > \"\$DBFILE\"; then
  SIZE=\$(stat -c%s \"\$DBFILE\" 2>/dev/null || echo 0)
  if [ \"\$SIZE\" -lt 1024 ]; then
    echo \"  db FAIL: dump suspiciously small (\$SIZE bytes) — aborting\"; exit 1
  fi
  echo \"  db OK: \$DBFILE (\$(du -h \"\$DBFILE\" | cut -f1))\"
else
  echo \"  db FAIL — aborting\"; exit 1
fi

# 2) Files tarball — exclude obvious bloat (caches + plugin backup dumps + log files)
FFILE=\$DEST/files-\${STAMP}.tar.gz
tar --warning=no-file-changed --warning=no-file-removed \\
    --exclude='wp-content/cache' \\
    --exclude='wp-content/uploads/cache' \\
    --exclude='wp-content/litespeed' \\
    --exclude='wp-content/wflogs' \\
    --exclude='wp-content/backups' \\
    --exclude='wp-content/ai1wm-backups' \\
    --exclude='wp-content/updraft' \\
    --exclude='*.log' \\
    -czf \"\$FFILE\" -C /home/${SITE_USER}/htdocs ${DOMAIN} 2>>\"\$LOG\"
RC=\$?
if [ -s \"\$FFILE\" ] && { [ \$RC -eq 0 ] || [ \$RC -eq 1 ]; }; then
  echo \"  files OK: \$FFILE (\$(du -h \"\$FFILE\" | cut -f1)) tar_rc=\$RC\"
else
  echo \"  files FAIL (rc=\$RC, file size \$(stat -c%s \"\$FFILE\" 2>/dev/null || echo 0))\"; exit 1
fi

# 3) Prune older than ${RETENTION_DAYS} days
find \"\$DEST\" -name 'db-*.sql.gz'    -mtime +${RETENTION_DAYS} -delete
find \"\$DEST\" -name 'files-*.tar.gz' -mtime +${RETENTION_DAYS} -delete
echo \"  retained: \$(ls \$DEST/db-*.sql.gz 2>/dev/null | wc -l) DB / \$(ls \$DEST/files-*.tar.gz 2>/dev/null | wc -l) files backups, total \$(du -sh \$DEST | cut -f1)\"
echo \"===== done \$(date -u) =====\"
BACKUP
chmod 755 /usr/local/bin/${SITE_USER}-backup.sh
mkdir -p ${BACKUP_ROOT}/${SITE_USER}
chmod 750 ${BACKUP_ROOT}/${SITE_USER}
echo 'WROTE: /usr/local/bin/${SITE_USER}-backup.sh'
"
```

**Why `set -uo pipefail` instead of `set -euo pipefail`?** `set -e` makes any non-zero exit fatal — but `tar` returns 1 when a file changes during read, which is **guaranteed** on a live WordPress site (LiteSpeed cache, session files, plugin temp dirs all churn during the tarball). Without explicit handling, every nightly backup would fail on the file step. The script checks `tar_rc in {0, 1}` explicitly and treats both as success.

**Why dump-size validation?** `wp db export` can return exit code 0 while writing 0 bytes — typically when wp-cli can't find wp-config (wrong `--path`), can't read it (perms), or the DB host is unreachable. A < 1 KB dump means something is wrong; abort before the prune step deletes yesterday's good backup.

## Step 3 — Atomically regenerate `/etc/cron.d/sites-backup`

This file is the **source of truth** for which sites get backed up. Re-running the skill regenerates it from the current `SITES` list — added sites get a cron line, removed sites lose theirs.

Stagger backups every 30 min from `${CRON_HOUR_START}:00 UTC`. Up to 6 sites fit comfortably in one nightly window; for more, drop the stagger to 15 min or push `CRON_HOUR_START` earlier.

```bash
ssh root@${HOST_IP} bash <<CRON
set -e
{
  echo '# /etc/cron.d/sites-backup'
  echo '# Managed by nightly-backup-wp-cron skill. Re-run regenerates this from current SITES list.'
  echo 'SHELL=/bin/bash'
  echo 'PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin'
  echo ''
  echo '# Format: <min> <hour> * * * <site_user> /usr/local/bin/<site_user>-backup.sh > /dev/null 2>&1'
  i=0
  for tuple in "\${SITES[@]}"; do
    user="\${tuple%% *}"
    minute=\$(( (i % 2) * 30 ))
    hour=\$(( ${CRON_HOUR_START} + (i / 2) ))
    printf '%-2d %d * * * %-12s /usr/local/bin/%s-backup.sh > /dev/null 2>&1\n' "\$minute" "\$hour" "\$user" "\$user"
    i=\$((i+1))
  done
} > /etc/cron.d/sites-backup
chmod 644 /etc/cron.d/sites-backup
echo 'WROTE: /etc/cron.d/sites-backup'
cat /etc/cron.d/sites-backup
CRON
```

Example output for `SITES=[(madomarche, ...), (armadorn, ...)]` with `CRON_HOUR_START=3`:

```cron
# /etc/cron.d/sites-backup
# Managed by nightly-backup-wp-cron skill. Re-run regenerates this from current SITES list.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Format: <min> <hour> * * * <site_user> /usr/local/bin/<site_user>-backup.sh > /dev/null 2>&1
0  3 * * * madomarche   /usr/local/bin/madomarche-backup.sh > /dev/null 2>&1
30 3 * * * armadorn     /usr/local/bin/armadorn-backup.sh > /dev/null 2>&1
```

cron picks up `/etc/cron.d/*` changes within a minute — no service reload needed.

## Step 4 — Run each backup once now to verify

Synchronously fire each script and capture its exit code. This catches "wp-cli silently broken", "site user can't read wp-config", "disk filled mid-tarball", etc. **right now** instead of at 03:00 UTC tonight when nobody's watching.

```bash
ssh root@${HOST_IP} bash <<VERIFY
set -e
for tuple in "\${SITES[@]}"; do
  user="\${tuple%% *}"
  echo "===== \$user ====="
  /usr/local/bin/\${user}-backup.sh
  echo "  exit code: \$?"
done
echo
echo "Backup tree:"
find ${BACKUP_ROOT} -maxdepth 2 -name '*.gz' -printf '%p (%s bytes)\n' | sort
VERIFY
```

If any script exits non-zero, **stop**. Read `/var/backups/<site_user>/backup.log` for the failure detail. Don't proceed to the OUTPUTS block — the schedule is in place but the run is broken.

## Step 5 — Print OUTPUTS block

```
OUTPUTS_BEGIN
HOST_IP=178.105.177.37
SITES_BACKED_UP=2
SITES=madomarche:8.2MB+11MB, armadorn:6.1MB+2.4GB
BACKUP_ROOT=/var/backups
CRON_FILE=/etc/cron.d/sites-backup
RETENTION_DAYS=7
NEXT_RUN_UTC=2026-06-06 03:00
OUTPUTS_END
```

`SITES=` lists each site's most-recent `db-size+files-size` (from the Step 4 verification run). Use this as a sanity baseline — a 2.4 GB files tarball becoming 30 GB next week is the bloat-from-plugin-backups symptom (see Common pitfalls).

---

## Idempotency contract

| Step | Skip-guard | Behavior |
|---|---|---|
| 2 (per-site script) | none — always overwrite | Script content is deterministic per `(site_user, domain, BACKUP_ROOT, RETENTION_DAYS)`, so re-renders are byte-identical no-ops. Single source of truth. |
| 3 (cron file) | none — always overwrite | Same logic. Removing a site from `SITES` and re-running removes its line. |
| 4 (verification run) | none — always run | Verifies live state; cheap on first day, slightly redundant on re-runs but catches drift (e.g. wp-cli broken since last run). |

A re-run with the same `SITES` list overwrites every managed file to byte-identical content, regenerates the cron file, runs each backup once, and emits the OUTPUTS block. No flags to remember; no partial-failure states to recover from manually.

**Reversal:** to fully remove backups for a site:

```bash
# Drop from SITES and re-run the skill (cron line goes away).
# Optionally also:
ssh root@${HOST_IP} "rm /usr/local/bin/<site_user>-backup.sh; rm -rf ${BACKUP_ROOT}/<site_user>"
```

To remove backups *entirely* from the host: pass `SITES=[]` and re-run — the cron file ends up with no schedule lines. Then `rm /etc/cron.d/sites-backup /usr/local/bin/*-backup.sh; rm -rf ${BACKUP_ROOT}`.

---

## Common pitfalls (from real cloudpanel-1 deployment)

- **`set -e` + tar's "file changed as we read it" warning** = silent failure every night. tar exits 1 on warnings, and on a live WordPress site at least one cache / session / log file will change mid-tarball. The script uses `set -uo pipefail` (no `-e`) and checks `tar_rc in {0, 1}` explicitly. Don't "fix" this back to `set -euo pipefail` — that was the bug.

- **`wp db export` returns 0 with empty stdout.** Common causes: wrong `--path`, site user can't read `wp-config.php` (e.g. mode 600 root-owned after a manual edit), DB host unreachable from the site user's environment. The script validates `dump_size > 1024 bytes` and aborts otherwise — without this guard, the prune step would happily delete yesterday's good backup and leave you with 7 days of empty `db-*.sql.gz` files.

- **Files tarball bloats disk.** A 2 GB WooCommerce store with 5 years of UpdraftPlus / All-in-One-Migration / BackWPup plugin backups in `wp-content/{backups,ai1wm-backups,updraft}/` becomes a 30 GB tarball × 7 days = 210 GB. The script excludes those paths plus `wp-content/{cache,uploads/cache,litespeed,wflogs}` and `*.log`. The user's own UpdraftPlus retention is their concern — duplicating it in *our* tarball is wasteful.

- **Stagger collisions on small servers.** Four+ sites all dumping at 03:00 = MySQL connection pool exhaustion + IOPS storm on the underlying disk. 30-min stagger handles up to ~6 sites/night comfortably on a CPX32-class box. For more, drop to 15 min, or split across two windows (some at 03:xx, some at 04:xx).

- **MariaDB-Docker sidecar "just works" without `docker exec`.** wp-cli reads `wp-config.php`, sees `DB_HOST=127.0.0.1:3307`, opens a native MySQL protocol connection to the host-bound port, and dumps. No `docker exec`, no container-aware logic needed in the script. This is the single biggest reason the script can be engine-agnostic.

- **`find ... | xargs rm` instead of `find ... -delete`.** The xargs form trips over filenames with spaces, newlines, or hyphens at the start (interpreted as flags). `find -delete` is atomic-per-file and handles any filename. Always use it for prune steps.

- **CloudPanel doesn't backup wp-config.php specially.** wp-config.php IS inside the docroot tarball — so the files tarball restore brings it back. But if you want to restore a site to a *different* user / host, you'll need to edit `DB_USER` / `DB_PASSWORD` / `DB_HOST` post-restore. See `references/backup-restore-runbook.md`.

- **cron's `MAILTO` defaults to root.** When a backup script writes to stderr (which the verification step *does*, via `tee`), cron tries to mail root. On a CloudPanel box without postfix/sendmail configured, this generates `/var/spool/mail` errors. The cron line ends in `> /dev/null 2>&1` to suppress this — the backup script's own `tee -a $LOG` handles real logging.

---

## NOT included (separate skill)

- **Off-site sync.** Backups land in `/var/backups` on the same disk as the sites. If the server is destroyed, so are the backups. The cloudpanel-1 memory notes this as an open TODO. A future **`offsite-backup-sync`** skill will rclone `/var/backups` to Backblaze B2 / S3 / a second host. Until then, treat this skill as belt-only — you still need braces.

- **Encryption at rest.** Backups are gzipped plaintext SQL + tar. If the host is compromised, so are the backups. For PII-heavy stores, layer `age` / `gpg` encryption before off-siting. Out of scope here.

- **Database point-in-time recovery.** Daily logical dumps give you ≤ 24 h RPO. For sub-day RPO, you need MySQL binlog shipping or a managed DB with PITR — both are beyond a CloudPanel single-host setup.

## Pairs Well With

- **[`cloudpanel-site-add`](../cloudpanel-site-add/)** — required prerequisite. Creates the sites this skill backs up. The OUTPUTS block from `cloudpanel-site-add` (`DOMAIN`, `SITE_USER`) feeds directly into this skill's `SITES` input.
- **[`wp-bot-hardening`](../wp-bot-hardening/)** — independent; both are post-deploy hardening. Order doesn't matter; run both. Together they form the full "site is live and protected" baseline.
- **[`cloudflare-dns-setup`](../cloudflare-dns-setup/)** / **[`wp-migrate-guru-import`](../wp-migrate-guru-import/)** / **[`wp-post-migration-fixup`](../wp-post-migration-fixup/)** — independent; backups can be set up before or after these. Best to set up backups *before* migration so you have a known-good snapshot of the freshly-imported state.
- **[`offsite-backup-sync`](../offsite-backup-sync/)** *(planned)* — rclone-based off-site mirror of `/var/backups` to B2 / S3.
- **[`uptime-kuma-add-monitor`](../uptime-kuma-add-monitor/)** *(planned)* — register a script monitor that checks `find /var/backups -name 'db-*.sql.gz' -mtime -2 | wc -l == ${#SITES[@]}` so a silently-broken nightly is detected within 48 h.

## References

### Sidecar reference files (loaded on demand)

- [`references/backup-restore-runbook.md`](./references/backup-restore-runbook.md) — how to test a backup is valid before you need it, full DB + files restore commands, partial restore (just uploads, just one table), off-site backup options (B2 / S3 / rclone sketch), and disaster-recovery rebuild of a destroyed cloudpanel-1 from snapshot + latest backups.

### Memory notes

- [[madomarche-migration]] — first production run of this skill (madomarche.com + armadorn.com on cloudpanel-1, 2026-05-31). Has the live `/etc/cron.d/sites-backup` and `/var/backups/*/` paths.
- [[cloudpanel-1-multi-tenant-host]] — the host this skill targets.

### External

- WP-CLI `db export` docs: https://developer.wordpress.org/cli/commands/db/export/
- GNU tar warning controls: https://www.gnu.org/software/tar/manual/html_node/warnings.html
- cron.d file format: `man 5 crontab` (the `<user>` field at position 6 is what makes `/etc/cron.d/*` different from per-user crontabs)

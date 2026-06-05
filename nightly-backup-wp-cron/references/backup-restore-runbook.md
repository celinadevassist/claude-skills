# Backup Restore Runbook

Companion to `nightly-backup-wp-cron`. Covers verifying a backup *before* you need it, full and partial restores, off-site mirror options, and full disaster-recovery rebuild of a CloudPanel host.

Throughout: replace `<site>` with the site_user (`madomarche`, `armadorn`, etc.) and `<date>` with the `YYYY-MM-DD` UTC stamp in the backup filename.

---

## 1. Test that a backup is valid (do this monthly)

A backup you've never restored from is a backup you don't have. Run this on the first of every month for a randomly-picked site — takes about 2 minutes.

### 1a. DB dump quick-eyeball

```bash
ssh root@<host_ip> "
  zcat /var/backups/<site>/db-<date>.sql.gz | head -20
  echo '---'
  zcat /var/backups/<site>/db-<date>.sql.gz | grep -c '^CREATE TABLE'
"
```

Expect:
- Header includes `-- WordPress Database Backup` or `-- MySQL dump` or `-- MariaDB dump`.
- Table count matches roughly what you'd expect (~12 WP core + N plugins; WC adds ~20). If `0`, the dump is empty — see Common pitfalls in the main skill.

### 1b. Files tarball quick-eyeball

```bash
ssh root@<host_ip> "
  tar -tzf /var/backups/<site>/files-<date>.tar.gz | head -20
  echo '---'
  tar -tzf /var/backups/<site>/files-<date>.tar.gz | wc -l
  echo '---'
  # Should NOT include the excluded paths:
  tar -tzf /var/backups/<site>/files-<date>.tar.gz | grep -E '(wp-content/cache|wp-content/litespeed|wp-content/backups)' | head -5
"
```

Expect:
- First entries are the domain dir (`<domain>/`, `<domain>/wp-admin/`, ...).
- File count in the thousands-to-low-millions for a typical WC store.
- Zero matches for the excluded paths grep (proves the excludes fired).

### 1c. Cold-test restore to /tmp (no live impact)

The strongest test: actually extract both and import the DB to a throwaway DB, then `wp core verify-checksums`.

```bash
ssh root@<host_ip> bash <<'COLDTEST'
TMP=/tmp/restore-test-$$
mkdir -p $TMP
cd $TMP
tar -xzf /var/backups/<site>/files-<date>.tar.gz
zcat /var/backups/<site>/db-<date>.sql.gz > db.sql
echo "Files extracted: $(find . -type f | wc -l)"
echo "DB SQL size: $(stat -c%s db.sql) bytes"
# Optional: actually import to a temp DB and check
# mysql -e "CREATE DATABASE restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
# mysql restore_test < db.sql
# mysql restore_test -e "SHOW TABLES" | wc -l
# mysql -e "DROP DATABASE restore_test"
rm -rf $TMP
COLDTEST
```

---

## 2. Restore the database

### 2a. Full restore (overwrites current DB completely)

```bash
ssh root@<host_ip> "
  zcat /var/backups/<site>/db-<date>.sql.gz | \
    sudo -u <site> -i wp --path=/home/<site>/htdocs/<domain> db import -
"
```

`wp db import -` reads from stdin and uses the credentials in `wp-config.php` — engine-agnostic, same as the dump side. **It DROPS and re-CREATEs every table in the dump** (the dump includes `DROP TABLE IF EXISTS` per table), so the current DB content is gone after this completes.

### 2b. Restore just one table

```bash
ssh root@<host_ip> "
  zcat /var/backups/<site>/db-<date>.sql.gz | \
    awk '/^-- Table structure for table .wp_postmeta./,/^-- Table structure for table /' | \
    sudo -u <site> -i wp --path=/home/<site>/htdocs/<domain> db query
"
```

The `awk` range pulls just the named table's DDL + INSERTs out of the dump. Replace `wp_postmeta` with whatever you want. **The DROP TABLE inside the snippet wipes the live table before re-loading** — no data merging, this is a full table replace.

### 2c. Dry-run / inspect before importing

```bash
# What changed between current and backup?
ssh root@<host_ip> "
  CUR=\$(mktemp)
  sudo -u <site> -i wp --path=/home/<site>/htdocs/<domain> db export - 2>/dev/null > \$CUR
  diff <(zcat /var/backups/<site>/db-<date>.sql.gz | grep '^INSERT' | sort) \
       <(grep '^INSERT' \$CUR | sort) | head -100
  rm \$CUR
"
```

Useful when something feels wrong but you're not sure restoring is the right call.

---

## 3. Restore the files

### 3a. Full restore (overwrites the docroot)

```bash
ssh root@<host_ip> "
  cd /home/<site>/htdocs
  # Optionally move the live docroot aside first:
  # mv <domain> <domain>.broken.$(date -u +%Y%m%d-%H%M%S)
  tar -xzf /var/backups/<site>/files-<date>.tar.gz
  chown -R <site>:<site> <domain>
"
```

**Overwrite behavior:** `tar -xzf` writes over existing files of the same name but does **not** delete files that exist in the docroot but aren't in the tarball. If you want a true "wipe and restore", use the `mv ... .broken.<ts>` line first.

**Ownership reset:** root extracted the tarball, so every file is now owned by root. The `chown -R` line restores correct ownership — without it, PHP-FPM (running as `<site>`) can't read its own files and you get 500s.

### 3b. Restore just `wp-content/uploads/`

Common case: someone deleted a product image directory in the WP admin.

```bash
ssh root@<host_ip> "
  cd /home/<site>/htdocs
  tar -xzf /var/backups/<site>/files-<date>.tar.gz \
    <domain>/wp-content/uploads/2024/03/
  chown -R <site>:<site> <domain>/wp-content/uploads/2024/03/
"
```

The path inside the tarball starts with `<domain>/`, so the extract path matches what's already in the docroot — no `--strip-components` needed.

### 3c. Restore just one file

```bash
ssh root@<host_ip> "
  tar -xzf /var/backups/<site>/files-<date>.tar.gz \
    -O <domain>/wp-config.php > /tmp/wp-config-from-backup.php
"
```

`-O` extracts to stdout instead of disk — safe for inspecting without touching anything live. Then diff against the current file and decide.

---

## 4. Common restore gotchas

- **File ownership reset to root.** Tar preserves the original uid/gid only if extracted by root *and* the original uids match. On a different host, they probably don't. Always `chown -R <site>:<site> <domain>` after a tar restore.
- **wp-config.php IS in the tarball.** Restoring overwrites the current wp-config — including DB credentials. If you restored to a different host or after a DB password rotation, edit `DB_USER` / `DB_PASSWORD` / `DB_HOST` post-restore or the site will throw "Error establishing a database connection".
- **Object cache / OPcache.** After a restore, `systemctl reload php<X.Y>-fpm` to flush OPcache. If the site uses Redis object cache, `wp cache flush` as the site user.
- **Search-replace for URL changes.** If restoring to a different domain, run `wp search-replace 'https://old.example.com' 'https://new.example.com' --precise --skip-columns=guid` after both DB + files are in place. See `wp-post-migration-fixup` for the full recipe.
- **Excluded paths come back empty.** `wp-content/cache`, `wp-content/litespeed`, etc. weren't in the tarball — they'll be empty after restore. WordPress / LiteSpeed / W3TC regenerate them on first page load; no manual intervention needed.
- **Plugin license re-activation.** Some commercial plugins phone home with the site URL — restoring to a different host triggers a re-activation prompt. Have license keys ready.

---

## 5. Off-site backup sketch (planned skill — manual recipe meanwhile)

Until `offsite-backup-sync` exists, this is the manual quick-start. Pick one provider and one sync tool.

### 5a. rclone to Backblaze B2 (cheapest)

```bash
# On the host, one-time:
apt install -y rclone
rclone config  # interactive: pick "b2", paste application key + key ID, pick endpoint
# Test:
rclone lsd b2:<bucket-name>

# Add to /etc/cron.d/sites-backup-offsite (after the local backup cron lines, offset by 90 min):
30 4 * * * root rclone sync /var/backups b2:<bucket-name>/cloudpanel-1 --transfers 4 --checksum --log-file /var/log/rclone-offsite.log
```

B2 cost as of 2026: $0.006/GB-month storage, $0.01/GB egress (download). 50 GB total backups = ~$0.30/mo. Restore egress is the bigger cost — don't store 1 TB of backups for a 5 GB site.

### 5b. AWS S3 with lifecycle to Glacier

Same shape, replace `b2` with `s3:` in rclone config (or use `aws s3 sync`). Add a lifecycle rule on the bucket: "transition to S3 Glacier Deep Archive after 30 days". Cheaper than B2 for cold storage, more expensive for hot. **Use S3 if you already have AWS infra**; B2 if this is the only thing.

### 5c. Encryption before upload

```bash
# In the per-site backup script, BEFORE the upload (sketch — not yet in the skill):
age -r age1<recipient-pubkey> \
  -o "${FFILE}.age" \
  "$FFILE" && rm "$FFILE"
```

`age` is single-binary, no key infrastructure, sufficient for "we don't want the backup provider reading our DB". Store the recipient *private* key in a password manager — losing it means losing the backups.

---

## 6. Disaster recovery: rebuild from scratch

Scenario: cloudpanel-1 is destroyed (disk failure, accidental `rm -rf`, Hetzner data-center fire). You have:
- The most recent off-site backup of `/var/backups`.
- The `cloudpanel-1-clean-20260531` snapshot (hardened CloudPanel + zero site data) per [[madomarche-migration]].
- The credentials in your password vault.

### Order of operations

1. **Spin up a new Hetzner box from the snapshot.** New IP — note it.
2. **Restore `/var/backups`** from off-site:
   ```bash
   rclone sync b2:<bucket-name>/cloudpanel-1 /var/backups
   ```
3. **For each site, in any order:**
   1. Run `cloudpanel-site-add` with the original `SITE_USER` and `DOMAIN`. This recreates the Linux user, nginx vhost, PHP-FPM pool, DB user, and (for MariaDB-Docker sites) the sidecar container. DB starts empty.
   2. Restore the DB from the most recent dump (section 2a).
   3. Restore the files (section 3a, including the `mv .broken` step — the docroot has only the empty WP scaffold from `cloudpanel-site-add` Step 2).
   4. `chown -R <site>:<site> /home/<site>/htdocs/<domain>`.
   5. Smoke-test with curl on the sslip.io URL (or real domain once DNS catches up).
4. **Re-run `wp-bot-hardening`** across all restored sites (the snapshot is hardened at the OS level, but the per-site vhost markers and wp-config edits need re-applying because we just got new vhosts from `cloudpanel-site-add`).
5. **Re-run `nightly-backup-wp-cron`** to re-install the per-site backup scripts and cron file.
6. **Update DNS** at Cloudflare to point each domain's A record at the new IP. Real LE certs reissue automatically on the next certbot renewal (or force with `certbot renew --force-renewal`).

Total RTO from off-site backup + snapshot: **~2 hours for a 2-site host**, dominated by DNS propagation. Without the snapshot, add ~1 hour for the CloudPanel install + hardening.

### What the snapshot does NOT contain

- Site data (intentionally; that's what `/var/backups` is for).
- Off-site backup credentials (rclone config) — re-create from the password vault.
- Per-site sidecar container data (the MariaDB-Docker container exists in the snapshot but with empty DB). The DB restore in step 3.ii populates it.

### Practice this once a quarter

Spin up a `cax11` (€4/mo) from the snapshot, restore one site to it, smoke-test, destroy. **You'll find a broken link in the runbook within 2 quarters** — that's the point. Don't wait for a real disaster to discover that the off-site bucket's API key expired six months ago.

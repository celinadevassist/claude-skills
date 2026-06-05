---
name: "Cloudflare DNS Setup"
description: "Add a domain to Cloudflare as a new zone, point it at a new origin, preserve email DNS (MX/SPF/DKIM/DMARC) verbatim from the previous host, and hand back the assigned nameservers for the user to set at the registrar. Two modes: greenfield (no prior DNS) and migrate-from-existing (auto-import via Cloudflare's scan endpoint, then audit and clean before NS switch). Defaults to grey-cloud (DNS-only, no proxy) per the cloudpanel-1 preference for real client IPs. Idempotent — re-run on a half-completed zone is safe. Use when onboarding a new cloudpanel-1 tenant after `cloudpanel-site-add` finishes, when standing up DNS for a brand-new domain, or when migrating a live domain from Hostinger / dns-parking.com / any other DNS host without breaking email."
---

# Cloudflare DNS Setup

## What This Skill Does

Adds one domain to Cloudflare in a single repeatable run:

1. Pre-flights the API token (verifies it's active and has the right scopes).
2. Creates the zone (`type=full`), or picks up the existing zone ID if it's already there.
3. **(migrate mode only)** Triggers Cloudflare's DNS auto-import (`POST /zones/{id}/dns_records/scan`) — reads from the CURRENT nameservers at the old provider and clones records into the new zone.
4. Audits the imported records and cleans the noise (old-origin A/AAAA, dead CDN CNAMEs, Hostinger's `_da-verify-*` TXTs) — KEEPS email DNS (MX/SPF/DKIM/DMARC) byte-for-byte.
5. Adds the new-origin pointers: `A @ → ${ORIGIN_IP}` and `CNAME www → @`, both **grey-cloud** (`proxied: false`) per [[cloudflare-proxy-preference]].
6. Optionally trims CAA records to only the cert authority you actually use (default: keep all; safer for first-time migrations).
7. Prints the **two Cloudflare-assigned nameservers** for the user to set at the registrar (Cloudflare can't do this part; the registrar UI is manual).
8. Polls `zones/{id}.status` every 60 s until `active`.
9. Verifies authoritative DNS with a public resolver (`dig @1.1.1.1`).
10. Prints a single parseable **OUTPUTS** block for piping into the next skill in the chain.

The API token is **read from the caller's environment (`$CF_TOKEN`) and never stored** in any memory file or output.

## When to Use

- **Right after `cloudpanel-site-add` finishes** a new tenant on cloudpanel-1 (`178.105.177.37`) or any other origin host. The OUTPUTS block from that skill provides `DOMAIN` + `HOST_IP` (which becomes this skill's `ORIGIN_IP`).
- **Migrating a live site's DNS** from Hostinger (`dns-parking.com` NS), GoDaddy, Namecheap basic DNS, or any other provider — use `MODE=migrate-from-existing` so MX / SPF / DKIM / DMARC are auto-imported, audited, and only THEN does the user switch nameservers at the registrar.
- **Greenfield**: a brand-new domain with no DNS anywhere yet — use `MODE=greenfield`, set up the apex + www, hand back the NS.
- **Re-running** after an aborted previous attempt — the skill is idempotent; existing zone is reused, existing records are NOT duplicated.

## When NOT to Use

- **The user wants Cloudflare orange-cloud / proxy mode.** This skill defaults to grey because cloudpanel-1 sites want real client IPs in nginx logs ([[cloudflare-proxy-preference]]). If proxy is genuinely desired, set `proxied: true` in the record JSON below and disable the "preserve real IP" assumption — but read that memory note first to confirm the user actually wants it.
- **Registrar-locked DNS** (some country-code TLDs require DNS to stay at the registrar — `.de`, certain `.it` setups). Cloudflare's `type=full` zone won't activate; use `type=partial` (CNAME setup) instead, which is out of scope for this skill.
- **DNSSEC is already enabled at the old provider with the registrar trust anchor set.** The NS switch will break resolution until DNSSEC is disabled at the registrar OR re-keyed in Cloudflare. Disable DNSSEC at the old provider 24h before running this skill.

## Prerequisites

- A **Cloudflare account** with room for one more zone (free plan: 1000 zones).
- A **scoped API token** with `Zone:Edit` + `Zone Settings:Edit` + `DNS:Edit`. `Account:Read` is **NOT** required when creating a zone without specifying an account ID (Cloudflare infers from the token's scope). Export as `CF_TOKEN` — never paste inline.
- `curl`, `jq`, and `dig` on the operator's machine.
- The **new origin IP** is already serving the site (e.g. via `cloudpanel-site-add`'s sslip.io alias) so you can verify `dig +short ${DOMAIN}` after activation.
- Access to the **registrar's UI** for the manual NS switch in Step 6.

---

## Inputs (collect once before Step 1)

| Var | Example | Notes |
|---|---|---|
| `CF_TOKEN` | env var | Cloudflare API token. NEVER store in memory. `export CF_TOKEN=...` |
| `DOMAIN` | `madomarche.com` | Bare apex, no scheme, no `www.` |
| `ORIGIN_IP` | `178.105.177.37` | New origin IPv4 (cloudpanel-1 in the production case) |
| `MODE` | `greenfield` \| `migrate-from-existing` | Migrate mode triggers the scan import + audit |
| `KEEP_GOOGLE_VERIFY` | `true` (default) | Keep `google-site-verification` TXTs when imported |
| `CAA_POLICY` | `keep-all` (default) \| `lets-encrypt-only` | `lets-encrypt-only` trims CAA to just `0 issue "letsencrypt.org"` + `0 issuewild "letsencrypt.org"` |
| `OLD_ORIGIN_IPS` | `147.79.x.x,92.112.x.x` | (migrate only) Comma-separated IPs the old A/AAAA records point to — anything matching is deleted in the audit |

---

## Step 1 — Pre-flight: verify token

```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify | jq .
# Expect: { "success": true, "result": { "status": "active", ... } }
```

If `status` is not `active`, abort. Common causes:
- Token expired (Cloudflare tokens can have a TTL set at creation)
- Token revoked from the user's dashboard
- Pasted the wrong token (an Account-level token won't pass zone-scoped checks later — verify scopes in the dashboard)

The token's actual scopes aren't exposed via the API, so this skill's later calls double as scope checks (e.g. zone create fails with `9109` if `Zone:Edit` is missing).

## Step 2 — Create the zone (or reuse if it exists)

Idempotent: if the zone already exists in the account, capture its ID and skip create.

```bash
# Check first
EXISTING=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=${DOMAIN}" | jq -r '.result[0].id // empty')

if [ -n "$EXISTING" ]; then
  ZONE_ID="$EXISTING"
  echo "SKIP: zone ${DOMAIN} already exists, id=${ZONE_ID}"
  NAMESERVERS=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}" | jq -r '.result.name_servers | join(",")')
else
  RESP=$(curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
    https://api.cloudflare.com/client/v4/zones \
    -d "{\"name\":\"${DOMAIN}\",\"type\":\"full\"}")
  ZONE_ID=$(echo "$RESP" | jq -r '.result.id')
  NAMESERVERS=$(echo "$RESP" | jq -r '.result.name_servers | join(",")')
  echo "CREATED: zone ${DOMAIN}, id=${ZONE_ID}"
fi

echo "ZONE_ID=${ZONE_ID}"
echo "NAMESERVERS=${NAMESERVERS}"
```

The `name_servers` array is the pair Cloudflare assigned (e.g. `ariadne.ns.cloudflare.com`, `charles.ns.cloudflare.com`) — these go to the registrar in Step 6.

## Step 3 — Trigger DNS auto-import (migrate mode only)

Skip if `MODE=greenfield`.

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/scan" | jq .
# { "result": { "total_records_parsed": 14, "added": 14 }, "success": true }
```

What the scan does: Cloudflare queries the **current authoritative nameservers** for `${DOMAIN}` (still the old provider at this point) and clones every A, AAAA, CNAME, MX, TXT, SRV, CAA record it can find. It does NOT delete anything you already added to the new zone.

Re-running the scan on a zone where it already ran returns error `81058` ("scan already performed"). That's the idempotency guard — safe to ignore.

## Step 4 — Audit and clean imported records

List all records in the zone:

```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?per_page=100" \
  | jq '.result[] | {id, type, name, content, proxied}'
```

For each record, classify and act:

| Record matches | Action | Why |
|---|---|---|
| `A` or `AAAA` at apex or `www`, content in `OLD_ORIGIN_IPS` | DELETE | Old origin — we'll replace with single A → new origin in Step 5 |
| `A` or `AAAA` at apex pointing at `${ORIGIN_IP}` already | KEEP | Pre-existing correct record (idempotent re-run) |
| `CNAME www → *.hstgr.net` (Hostinger CDN) or any other dead CDN host | DELETE | Will be replaced by `CNAME www → @` in Step 5 |
| `A ftp.${DOMAIN} → old IP` | DELETE | No SFTP-on-FTP needed; we use port 22 |
| `TXT _da-verify-* "domain-verified"` | DELETE | Hostinger control-panel verification, useless after leaving |
| `MX ${DOMAIN}` | **KEEP UNCHANGED** | Mail routing — single character drop breaks all inbound mail |
| `TXT ${DOMAIN}` containing `v=spf1` | **KEEP UNCHANGED** | SPF — breaks outbound mail authentication if altered |
| `TXT _dmarc.${DOMAIN}` containing `v=DMARC1` | **KEEP UNCHANGED** | DMARC policy |
| `TXT *._domainkey.${DOMAIN}` containing `v=DKIM1` | **KEEP UNCHANGED — verify byte-for-byte** | DKIM signing key. A single character drop sends all outbound mail to spam. Diff the imported value against the source's `dig TXT *._domainkey.${DOMAIN} @${OLD_NS}` output before trusting it. |
| `TXT ${DOMAIN}` containing `google-site-verification=` | KEEP if `KEEP_GOOGLE_VERIFY=true` else DELETE | Search Console ownership proof |
| `CAA` records | See Step 4a below | |

### Step 4a — CAA policy

`CAA_POLICY=keep-all` (default): leave whatever was imported. Safest for first-time migrations.

`CAA_POLICY=lets-encrypt-only`: delete all imported CAA, then add the two below. **Only do this if you're 100% sure no other CA issues certs for any subdomain on this zone** — otherwise next cert renewal will fail with a CAA rejection.

```bash
# Delete existing CAA
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?type=CAA&per_page=100" \
  | jq -r '.result[].id' | while read id; do
  curl -s -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${id}"
done

# Add LE-only
for FLAGS_TAG in '0,issue' '0,issuewild'; do
  FLAGS="${FLAGS_TAG%,*}"; TAG="${FLAGS_TAG#*,}"
  curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
    -d "{\"type\":\"CAA\",\"name\":\"${DOMAIN}\",\"data\":{\"flags\":${FLAGS},\"tag\":\"${TAG}\",\"value\":\"letsencrypt.org\"},\"ttl\":1}"
done
```

The `0 issue "letsencrypt.org"` record **must be present** if Let's Encrypt certs are being issued anywhere on this zone (which they are, via `cloudpanel-site-add`). If you delete it without re-adding, all future LE renewals fail.

### Generic delete pattern (used throughout Step 4)

```bash
curl -s -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}"
```

## Step 5 — Add origin pointers (grey cloud)

Both records use `proxied: false` per [[cloudflare-proxy-preference]]. Use `ttl: 1` for Cloudflare's "auto" (300 s when grey, 1 s when proxied).

```bash
# A @ → new origin
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d "{
    \"type\":\"A\",
    \"name\":\"${DOMAIN}\",
    \"content\":\"${ORIGIN_IP}\",
    \"ttl\":1,
    \"proxied\":false,
    \"comment\":\"origin (grey: DNS only; flip to orange later if desired)\"
  }"

# CNAME www → apex
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d "{
    \"type\":\"CNAME\",
    \"name\":\"www.${DOMAIN}\",
    \"content\":\"${DOMAIN}\",
    \"ttl\":1,
    \"proxied\":false
  }"
```

Idempotency: if either record already exists with the correct content, Cloudflare returns error `81057` ("record already exists"). Skip silently. If it exists with WRONG content (e.g. old apex A from the scan that wasn't caught in Step 4), update with `PUT /zones/{id}/dns_records/{record_id}` instead.

```bash
# Update example (for stale apex A)
curl -s -X PUT -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}" \
  -d "{\"type\":\"A\",\"name\":\"${DOMAIN}\",\"content\":\"${ORIGIN_IP}\",\"ttl\":1,\"proxied\":false}"
```

## Step 6 — Output the nameserver pair for the registrar

Cloudflare cannot push NS records to the registrar — the user has to do this in the registrar's web UI (Namecheap, GoDaddy, etc.). Print the pair clearly so they can copy-paste:

```
======================================================================
ACTION REQUIRED — set these nameservers at your domain registrar:

  ${NAMESERVERS%,*}
  ${NAMESERVERS#*,}

Common registrars:
  - Namecheap:  Domain List → Manage → Nameservers → "Custom DNS"
  - GoDaddy:    My Products → DNS → Nameservers → "I'll use my own"
  - Cloudflare Registrar (if registered here): already done automatically

Activation takes 15 min - 4 h after the registrar saves. The polling
loop in Step 7 will wait for it.
======================================================================
```

**Critical timing rule:** do NOT switch nameservers until ALL records (especially MX, SPF, DKIM, DMARC) are present in the Cloudflare zone. The window between "NS pointing at CF" and "MX records added to CF" = email broken. Step 4 + Step 5 must complete BEFORE telling the user to switch.

## Step 7 — Poll for activation

```bash
echo "Waiting for Cloudflare zone ${DOMAIN} to activate..."
while true; do
  STATUS=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}" | jq -r .result.status)
  echo "  $(date -u +%H:%M:%S) status=${STATUS}"
  [ "$STATUS" = "active" ] && break
  [ "$STATUS" = "deactivated" ] && { echo "FAIL: zone deactivated by Cloudflare"; exit 1; }
  sleep 60
done
echo "ACTIVE."
```

Typical activation time:
- Registrar with low TTL on old NS records: 15-30 min
- Registrar with default 24h TTL: 1-4 h
- Stuck > 8 h: re-check the NS pair at the registrar matches `${NAMESERVERS}` exactly (case-insensitive, no trailing dot)

## Step 8 — Verify with a public resolver

Confirm authoritative DNS is now Cloudflare AND the apex resolves to the new origin. Use `@1.1.1.1` to bypass local resolver caches.

```bash
echo "NS check:"
dig +short ns "${DOMAIN}" @1.1.1.1
# Expect: ariadne.ns.cloudflare.com / charles.ns.cloudflare.com (or your assigned pair)

echo "Apex A check:"
dig +short "${DOMAIN}" @1.1.1.1
# Expect: ${ORIGIN_IP}

echo "www CNAME check:"
dig +short "www.${DOMAIN}" @1.1.1.1
# Expect: ${DOMAIN}. then ${ORIGIN_IP}

echo "MX check (must still resolve to mail provider, not the old DNS host):"
dig +short mx "${DOMAIN}" @1.1.1.1
# Expect: whatever MXroute / Google Workspace / etc. used before
```

If apex returns the OLD origin IP: a stale A record survived Step 4's audit. Re-list records and delete the extras.

If MX returns nothing: SPF/DKIM/DMARC are also probably missing — email is broken. Re-check the scan output and re-add MX from the source's `dig MX ${DOMAIN} @${OLD_NS}` BEFORE the user notices.

## Step 9 — Print OUTPUTS block

```
OUTPUTS_BEGIN
DOMAIN=madomarche.com
ZONE_ID=6daefcb3ee96f5cb489a0a1aa1bd473a
NAMESERVERS=ariadne.ns.cloudflare.com,charles.ns.cloudflare.com
ORIGIN_IP=178.105.177.37
PROXIED=false
STATUS=active
MODE=migrate-from-existing
CAA_POLICY=keep-all
OUTPUTS_END
```

`STATUS` will be `pending` if the user hasn't switched NS yet (skip the polling loop on caller request). The next skill in the chain (`wp-migrate-guru-import` or `wp-post-migration-fixup`) can decide whether to proceed based on `STATUS`.

---

## Idempotency contract

The skill MUST be safe to re-run after partial failure. Each step's guard:

| Step | Idempotency check |
|---|---|
| 1 (token verify) | Always runs — cheap, no side effect |
| 2 (zone create) | `GET /zones?name=${DOMAIN}` → if `result[0].id` exists, reuse |
| 3 (scan) | Returns `81058` "scan already performed" on second call → safe to ignore |
| 4 (audit/delete) | Delete is keyed on RECORD_ID from a live list — re-run finds nothing to delete |
| 4a (CAA trim) | Same — list + delete + re-add is atomic per record |
| 5 (apex A) | `81057` "record already exists" on duplicate → check content, `PUT` if wrong else skip |
| 5 (www CNAME) | Same as apex |
| 7 (poll) | No-op if already `active` |
| 8 (dig verify) | Read-only |

A re-run on a fully-completed zone prints `SKIP:` for every write step and re-prints the OUTPUTS block from current state.

---

## Common pitfalls (from the real cloudpanel-1 runs, 2026-05-31)

- **The scan import returned multiple apex A records** (Hostinger CDN's load-balanced set — 4 IPs in `147.79.x.x`/`92.112.x.x`). Step 4 must loop through ALL of them and delete each, not just the first. Verify with `dig +short ${DOMAIN} @1.1.1.1` after the audit — should be ONE IP, not 4.
- **IPv6 (AAAA) records imported for the old origin** (`2a02:4780:...`). Delete unless the new server has IPv6 set up too (cloudpanel-1 does NOT serve over IPv6 by default — leaving AAAA records intact causes `ECONNREFUSED` for IPv6-preferring clients).
- **CAA records from the old provider include CAs you don't use** (`comodoca`, `sectigo`, `digicert`). They don't HURT (LE issuance still works as long as `letsencrypt.org` is among them), but they're noise. `CAA_POLICY=lets-encrypt-only` cleans them.
- **DKIM TXT records show as one long string in Cloudflare's UI** but get chunked at 255-byte boundaries on DNS lookup. That's normal — DON'T manually break the value with quotes. The chunking happens at the protocol layer (RFC 7208 §3.3).
- **Don't switch nameservers until ALL records are at Cloudflare.** The window between "NS pointing at CF" and "MX records added to CF" = email broken. Steps 4 + 5 MUST be complete before Step 6's banner is shown.
- **Cloudflare assigns a different NS pair per zone** — don't hardcode `ariadne/charles`. Always read from `result.name_servers` in the create response (or the existing-zone GET).
- **`type=full` zone vs `type=partial`**: `partial` is CNAME-setup (the user keeps DNS at the old provider and just proxies via CF). This skill assumes `full` — the user is moving authority to Cloudflare. Don't conflate them.
- **The registrar's NS-change UI sometimes has a TTL field separate from the records.** Some registrars (Namecheap) cache the OLD NS for the OLD TTL even after the user saves. If activation takes > 4 h, ask the user to confirm the registrar SAVED (not just edited) the NS change.
- **DNSSEC at the old provider** breaks resolution mid-switch. If `dig +short DS ${DOMAIN} @1.1.1.1` returns anything before this skill runs, the user MUST disable DNSSEC at the OLD provider and wait for the DS records to expire from the parent zone (TTL of the .com/.net/etc. zone — usually 1 hour) before this skill's Step 7 will succeed.

---

## Pairs Well With

- **[`cloudpanel-site-add`](../cloudpanel-site-add/)** — runs BEFORE this. Its OUTPUTS block provides `DOMAIN` + `HOST_IP` (= this skill's `ORIGIN_IP`).
- **[`wp-migrate-guru-import`](../wp-migrate-guru-import/)** — runs AFTER Cloudflare zone is `active`. The Migrate Guru push uses the sslip.io URL from `cloudpanel-site-add` while the real domain's NS may still be mid-switch. Order: cloudpanel-site-add → cloudflare-dns-setup → wp-migrate-guru-import → (NS switch flips traffic) → wp-post-migration-fixup.
- **[`wp-post-migration-fixup`](../wp-post-migration-fixup/)** — runs AFTER A records flip and DNS propagates. Strips the sslip.io overrides from wp-config, runs `wp search-replace`, reissues LE cert for the real domain.
- **[`wp-bot-hardening`](../wp-bot-hardening/)** — independent of DNS, but should be applied to the new origin BEFORE high traffic hits the new IP. Grey-cloud means bots hit nginx directly — origin hardening matters.

## References

### Sidecar reference files (loaded on demand)

- [`references/cloudflare-api-cheatsheet.md`](./references/cloudflare-api-cheatsheet.md) — token scope minimums, every Cloudflare endpoint this skill uses with exact request/response shape, the scan endpoint's quirks, the full error-code list (1004, 9103, 81057, 81058, 9109, etc.) with what triggers each and how to recover, pagination + rate-limit notes.

### Memory notes

- [[madomarche-migration]] — first production run of this skill (madomarche.com + armadorn.com on cloudpanel-1, 2026-05-31). Has the NS pair Cloudflare actually assigned (ariadne / charles) and the full audit decisions from the live import.
- [[cloudflare-proxy-preference]] — why this skill defaults to grey-cloud (`proxied: false`) on cloudpanel-1 sites. Read before suggesting orange-cloud as an "upgrade".
- [[cloudpanel-1-multi-tenant-host]] — the target origin pattern; provides `ORIGIN_IP=178.105.177.37`.

### External

- Cloudflare API reference: https://developers.cloudflare.com/api/
- DNS record types reference: https://developers.cloudflare.com/dns/manage-dns-records/reference/dns-record-types/
- Scan endpoint docs: https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/#import-dns-records
- CAA record explainer: https://letsencrypt.org/docs/caa/
- DKIM chunking (RFC 7208 §3.3): https://datatracker.ietf.org/doc/html/rfc7208#section-3.3

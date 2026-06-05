# Cloudflare API Cheatsheet

Every endpoint the `cloudflare-dns-setup` skill uses, plus the adjacent ones you reach for when something breaks. All examples assume `CF_TOKEN` is exported. Base URL is `https://api.cloudflare.com/client/v4`.

## Token scopes

The skill needs a **User API Token** (not a Global API Key) with these scopes:

| Scope | Resource | What it unlocks |
|---|---|---|
| `Zone:Edit` | Specific Zone OR All Zones | Create new zone, update settings |
| `Zone Settings:Edit` | Specific Zone | Change SSL mode, security level, etc. (not used heavily by this skill, but required by some implicit Cloudflare reads) |
| `DNS:Edit` | Specific Zone OR All Zones | List, create, update, delete DNS records |

`Account:Read` is **NOT** required when creating a zone without specifying `account.id` — Cloudflare infers from the token's scope. If you DO want to specify the account (multi-account tokens), add `Account:Read`.

Token TTL is optional at creation. For migration ops, a 24h-TTL token is the safe default — long enough for the multi-step flow, short enough to not linger.

**Verify a token:**
```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify
# { "result": { "id": "...", "status": "active" }, "success": true }
```

`status: "disabled"` = token revoked. `status: "expired"` = TTL elapsed. Both require creating a new one — there's no API to re-enable.

## Zones

### Create a zone

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  https://api.cloudflare.com/client/v4/zones \
  -d '{"name":"example.com","type":"full"}'
```

Returns:
```json
{
  "result": {
    "id": "6daefcb3ee96f5cb489a0a1aa1bd473a",
    "name": "example.com",
    "status": "pending",
    "name_servers": ["ariadne.ns.cloudflare.com", "charles.ns.cloudflare.com"],
    "type": "full"
  },
  "success": true
}
```

`type` values: `full` (Cloudflare is authoritative — most common), `partial` (CNAME setup — keep DNS at old provider). This skill uses `full` exclusively.

### Get a zone (status, NS pair)

```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  https://api.cloudflare.com/client/v4/zones/${ZONE_ID}
```

`result.status` values: `pending` (NS not yet switched at registrar), `active` (Cloudflare is now authoritative), `deactivated` (manually disabled), `read only` (account suspended).

### Find zone by name (idempotency check)

```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=example.com" \
  | jq -r '.result[0].id'
```

Returns empty string if no zone exists with that exact name. Cloudflare matches the FULL name — `example.com` and `www.example.com` are different.

### Delete a zone

```bash
curl -s -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
  https://api.cloudflare.com/client/v4/zones/${ZONE_ID}
```

Frees the zone slot. Records inside are also deleted. Idempotent: deleting an already-deleted zone returns `1001`.

## DNS records

### List records

```bash
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?per_page=100"
```

**Filters** (query params):
- `type=A` — only one type
- `name=www.example.com` — exact name match
- `content=1.2.3.4` — exact content match
- `proxied=true` — only proxied records

**Pagination**: `per_page` max is `100`. For zones with > 100 records, use `page=2`. Result envelope includes `result_info.{count, total_count, total_pages}`. Cloudflare DOES set `Link` headers but the per-page param is simpler.

### Create a record

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d '{
    "type": "A",
    "name": "example.com",
    "content": "1.2.3.4",
    "ttl": 1,
    "proxied": false,
    "comment": "origin (grey)"
  }'
```

**Field reference (the ones that bite):**
- `name`: FULL name. For apex use the bare domain (`example.com`), not `@`. For subdomains use FQDN (`www.example.com`).
- `content`: A → IPv4, AAAA → IPv6, CNAME → target FQDN (with or without trailing dot), TXT → the raw string (Cloudflare handles quoting), MX → mail server FQDN.
- `ttl`: `1` means "auto" (Cloudflare chooses — 300s grey, 1s when proxied). Or any value 60-86400.
- `proxied`: `true` = orange cloud (CF terminates TLS, hides origin), `false` = grey cloud (DNS only). **This skill defaults to `false`.**
- `priority`: required for MX records only (lower = higher priority — usually 10).
- `comment`: free text, visible in dashboard, max 100 chars.

### MX record

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d '{
    "type": "MX",
    "name": "example.com",
    "content": "mail.mxrouteserver.com",
    "priority": 10,
    "ttl": 1
  }'
```

### TXT record (SPF, DKIM, DMARC, verification)

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d '{
    "type": "TXT",
    "name": "example.com",
    "content": "v=spf1 include:_spf.mxrouteserver.com -all",
    "ttl": 1
  }'
```

For DKIM (long string), pass the value RAW — don't chunk it manually. Cloudflare handles the 255-byte chunking at the protocol layer.

### CAA record

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -d '{
    "type": "CAA",
    "name": "example.com",
    "data": { "flags": 0, "tag": "issue", "value": "letsencrypt.org" },
    "ttl": 1
  }'
```

Note the `data` object instead of `content`. `tag` is `issue` (issuance allowed) or `issuewild` (wildcard issuance allowed) or `iodef` (reporting email). `flags` is almost always `0`; `128` means "critical" (reject if CA doesn't understand).

### Update a record

```bash
curl -s -X PUT -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}" \
  -d '{
    "type": "A",
    "name": "example.com",
    "content": "5.6.7.8",
    "ttl": 1,
    "proxied": false
  }'
```

`PUT` replaces ALL fields — you must send the complete record. `PATCH` is also supported and only updates the fields sent (preferable for partial updates).

### Delete a record

```bash
curl -s -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}"
```

## DNS scan (auto-import)

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" \
  https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/scan
```

Returns:
```json
{
  "result": {
    "total_records_parsed": 14,
    "added": 14
  },
  "success": true
}
```

**What it does:** Cloudflare queries the CURRENT authoritative nameservers for the zone (still the old provider at this point — Cloudflare looks them up via the parent TLD's NS, NOT from your account) and clones every standard record it finds: A, AAAA, CNAME, MX, TXT, SRV, CAA, NS-at-subdomain.

**What it does NOT import:**
- The apex NS records (Cloudflare provides those itself)
- SOA (auto-generated by Cloudflare)
- DNSSEC keys (must be re-keyed in Cloudflare)
- Records on subdomains that have their own NS delegation that the scanner can't follow

**Quirks:**
- The scan can only be run ONCE per zone. Second call returns `81058`.
- If the old DNS provider has rate-limited Cloudflare's scanner IPs (rare), some records silently won't import. Cross-check against `dig AXFR @${OLD_NS}` if you can, or `dig ANY` if AXFR is denied.
- Records with TTL = 1 at the source come in as `ttl: 1` (auto). Higher TTLs are preserved literally.

## Common error codes

| Code | Message (excerpt) | Triggered by | Recovery |
|---|---|---|---|
| `1001` | Invalid request | Malformed JSON, missing required field | Validate payload against the endpoint docs |
| `1004` | DNS Validation Error | Invalid zone name format (uppercase, leading dot, special chars) | Bare lowercase apex only |
| `1097` | Zone is already paused | Trying to pause an already-paused zone | Idempotency win — safe to ignore |
| `81004` | DNS record with that name and type already exists | Two records of same `(type, name)` where Cloudflare requires unique | Either delete the existing record first, or `PUT` to update it |
| `81057` | This record already exists | Exact duplicate (same type, name, content) | Skip silently — already present |
| `81058` | DNS records have already been scanned | Calling `dns_records/scan` twice on the same zone | Skip silently — initial import already done |
| `9103` | Unknown X-Auth-Key or X-Auth-Email | Using legacy auth headers instead of `Bearer` token | Use `Authorization: Bearer $CF_TOKEN` — never the old `X-Auth-Key` / `X-Auth-Email` pair |
| `9109` | Invalid access token | Token expired, revoked, or wrong scope for endpoint | Verify with `/user/tokens/verify`; check scopes in dashboard |
| `10000` | Authentication error | Token missing entirely from request | Check `Authorization` header was sent |
| `6003` | Invalid request headers | `Content-Type: application/json` missing on POST/PUT | Always set `Content-Type: application/json` for write methods |

Error envelope shape:
```json
{
  "success": false,
  "errors": [{ "code": 81057, "message": "An A record with that name and content already exists" }],
  "messages": [],
  "result": null
}
```

Always check `success` (not just HTTP status — Cloudflare returns 200 with `success: false` for soft errors).

## Rate limits

Per token:
- **1,200 requests per 5 minutes** across all endpoints
- Burst tolerance: ~50 req/sec for short bursts

Per zone:
- **200 requests per 5 minutes** for zone-scoped operations

If you exceed: HTTP 429 with `Retry-After` header (seconds). The skill's record-by-record audit + delete pattern on a 100-record zone is well within limits (~250 req total).

For bulk import of many zones (not this skill's use case), use `dns_records/import` with a BIND zone file payload — single request, no per-record cost.

## Pagination details

Endpoints that return arrays:
- `?per_page=100` — max 100, default 20
- `?page=2` — 1-indexed
- `&order=type` — sort by field
- `&direction=asc|desc`

Response envelope:
```json
{
  "result": [...],
  "result_info": {
    "page": 1,
    "per_page": 100,
    "count": 100,
    "total_count": 247,
    "total_pages": 3
  }
}
```

`Link` headers (`Link: <...?page=2>; rel="next"`) are also set per RFC 5988 — use whichever your client handles better.

## Adjacent endpoints (not used by this skill, but you'll reach for them)

```bash
# Pause/unpause Cloudflare for a zone (DNS-only, no other features)
PATCH /zones/${ZONE_ID}  -d '{"paused": true}'

# Purge cache (relevant only if proxied: true)
POST /zones/${ZONE_ID}/purge_cache  -d '{"purge_everything": true}'

# SSL mode (Flexible / Full / Full Strict / Off)
PATCH /zones/${ZONE_ID}/settings/ssl  -d '{"value": "full"}'

# Always Use HTTPS (auto-redirect 80 → 443 at the edge — proxied only)
PATCH /zones/${ZONE_ID}/settings/always_use_https  -d '{"value": "on"}'

# Universal SSL pack (status, regen)
GET  /zones/${ZONE_ID}/ssl/universal/settings
PATCH /zones/${ZONE_ID}/ssl/universal/settings  -d '{"enabled": true}'

# DNSSEC (if you want to enable it in Cloudflare AFTER NS switch)
PATCH /zones/${ZONE_ID}/dnssec  -d '{"status": "active"}'
```

## See also

- Full API explorer (try-it-now UI): https://developers.cloudflare.com/api/
- DNS record type semantics: https://developers.cloudflare.com/dns/manage-dns-records/reference/dns-record-types/
- Scan endpoint reference: https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/#import-dns-records
- Cloudflare error code list: https://developers.cloudflare.com/fundamentals/api/reference/errors/

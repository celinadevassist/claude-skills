---
name: "SLT Payment Hub Integration"
description: "Integrate SmartLabTec's Payment Hub (payment-hub.smartlabtec.com) — one API in front of multiple gateways (PayTabs, Paymob, Ziina, …) with hosted checkout, signed redirects, signed webhooks, refunds, and Egyptian SMS pay-links. Use when adding payments to any project via the hub instead of integrating a gateway directly, when verifying hub redirects/webhooks, or when debugging amounts, signatures, or idempotency against it."
---

# SLT Payment Hub Integration

## What This Skill Does

Encodes the integration contract for the in-house **SLT Payment Hub** at
`https://payment-hub.smartlabtec.com` — the docs at `/docs/` distilled into the
parts that matter, plus every trap that bites in practice. The hub fronts
several gateways behind one API, so a project integrates once and gateways can
be switched per company without code changes.

Verified live 2026-09-28: base URL answers, `/api/v1/gateways` returns 401
without credentials (auth required, endpoint exists).

## The Contract

**Auth** — every request carries both headers. Credentials come from the hub
dashboard (Companies → your company → Generate credential); the token is shown
once. Several credentials can be active at once → zero-downtime rotation.

```
X-Merchant-Id: mid_…
Authorization: Bearer slt_sk_…
Content-Type: application/json
```

**Discover gateways first** — `GET /api/v1/gateways` returns the company's
enabled gateways, each with its currencies, and the default used when
`gateway` is omitted. Requesting a disabled gateway is a 400 that names the
allowed ones. Check this before assuming a currency/market is supported.

**Create a payment** — `POST /api/v1/payments`:

```jsonc
// Header: Idempotency-Key: <your order id>
{
  "amount": 145000,            // MINOR UNITS — integer piasters/fils/cents
  "currency": "EGP",
  "orderId": "ORD-10944",      // echoed everywhere, incl. redirect + webhooks
  "gateway": "paytabs",        // optional
  "description": "Order ORD-10944",
  "customer": { "name": "…", "email": "…", "phone": "…" },
  "language": "ar",            // ar (default) | en — SMS/email wording
  "sendSms": true,             // pay-link SMS, Egyptian mobiles only
  "returnUrl": "https://…",    // optional, overrides the company backward link
  "metadata": { }
}
```

201 → `{ payment_id, status: "pending", checkout_url, … }`. Redirect the
customer to `checkout_url`. A 400 "Could not create a checkout session" is
retried **with the same Idempotency-Key** to get a fresh attempt — the key
scopes to the payment, not the attempt.

**Status (the only source of truth)** — `GET /api/v1/payments/:payment_id` →
`pending | paid | failed | expired | refunded`. Terminal states never change.
`expired` = 24 h pending → create a **new** payment; never retry the old one.
Always confirm status here before fulfilling — never trust the redirect alone.

**Customer return (signed redirect)** — customer lands on the company
"Backward link" (or per-payment `returnUrl`) with
`?payment_id&order_id&status&ts&sig` where
`sig = HMAC-SHA256(webhook_secret, payment_id + "." + order_id + "." + status + "." + ts)`.
Verify with timing-safe compare, reject stale `ts` (older than a few minutes),
**then still GET the payment** — redirects can be replayed; the API cannot.

**Webhooks** — POSTed to the company webhook URL, retried 6× with backoff.
Header `X-SLT-Signature: t=<unix>,v1=<hex>` where
`v1 = HMAC-SHA256(webhook_secret, t + "." + raw_body)`. Events:
`payment.paid`, `payment.failed`, `payment.expired`,
`payment.partially_refunded`, `payment.refunded`. Answer 2xx fast, do the work
async, and key idempotency on `payment_id + event` — duplicates happen.

**Refunds** — `POST /api/v1/payments/:id/refunds` with `Idempotency-Key`;
omit `amount` to refund the remainder. Only `paid` payments refund; sum never
exceeds the total; partial refunds keep status `paid` and grow
`refunded_amount`.

**SMS** — `POST /api/v1/sms` `{ mobile, message }`, 202 → poll
`GET /api/v1/sms/:id`. **Egyptian mobiles only** (010/011/012/015); anything
else is a 400. `sendSms:true` on a payment texts `{base}/pay/<payment_id>`,
which 302s to checkout while pending and to the return page after.

**Limits** — 429 at 120 req/min per credential per endpoint; honour
`Retry-After`. 401 = bad credential or suspended company. 404 = not your
payment.

## The Traps (each one has bitten or will)

1. **Minor units.** The hub takes integer piasters/fils/cents. App code that
   stores decimal EGP (e.g. CartFlow's `sellingPrice: 4898.6`) must convert
   with `Math.round(amount * 100)` — `4898.6 * 100` is `489859.99999…` in
   floats, so the `Math.round` is not optional. A non-integer amount is a 400.
2. **Two signatures, two formats, one secret.** Redirect and webhook are both
   HMAC-SHA256 with the **webhook secret** (dashboard → Reveal — NOT the API
   token), but the payloads differ: redirect signs the dot-joined query
   fields; webhooks sign `t + "." + raw_body`.
3. **Raw body or nothing.** Webhook verification needs the exact bytes
   received. In NestJS/Express, JSON body-parsing destroys them — keep a raw
   body (e.g. `express.json({ verify: (req,_res,buf)=>{req.rawBody=buf} })`,
   or CartFlow-style: `main.ts` already preserves raw body for `/webhooks/*`,
   so mount the handler under that prefix). Never re-serialize the parsed
   object to verify.
4. **Redirect ≠ paid.** Fulfil only after `GET /payments/:id` says `paid`.
5. **Idempotency-Key is per-payment, deliberately reused on retry** after a
   gateway session failure — a *new* key makes a *new* payment (double-charge
   risk); the *same* key gets a fresh checkout attempt.
6. **A safety-net poller is still required.** Customers pay and close the tab;
   webhooks can lag. Poll recent pending payments every few minutes (CartFlow:
   `sweepPendingPayments` cron) and reconcile.
7. **Credentials live server-side only** — in DB settings or root-owned
   `/etc/*.env`, never in code or frontend. Rotate via multiple active
   credentials.

## Company Settings (the dashboard form)

- **Logo URL** — https PNG shown in customer emails (SVG may not render in
  mail clients).
- **Backward link** — the *default* customer return page; a per-payment
  `returnUrl` overrides it, so pass the locale- and order-specific URL on each
  payment and keep this as the clean fallback.
- **Webhook URL** — must reach the instance that owns payment processing for
  the store (where the order-confirmation logic and sweeps run), under a
  raw-body-preserving route.

## CartFlow-Specific Notes (first consumer — IMPLEMENTED 2026-09-28)

- Shared client: `backend/src/shared/payment/slt/slt-hub.client.ts` —
  `SltHubClient` (create/get payment, gateways) + `toMinorUnits()` +
  `verifySltWebhookSignature()` / `verifySltRedirectSignature()` (timing-safe,
  stale-ts rejection). Unit-tested in `slt-hub.client.spec.ts` (16 tests incl.
  the 4898.6 float trap and re-serialized-body negative).
- Storefront adapter: `SltHubGateway` in
  `backend/src/storefront/payment-gateways.ts` (`id: 'slt'`), factory branch
  needs `payments.slt.merchantId + secretKey`. Idempotency-Key = orderNumber;
  `returnUrl` = per-order successUrl; `language` from `/ar/` in the URL;
  `sendSms` from `payments.slt.sendSms`. `refunded` verifies as `'paid'`,
  `cancelPayment` is a no-op (24 h link expiry).
- Webhook: `POST /api/webhooks/slt`
  (`backend/src/storefront/webhook.controller.ts`) — raw-body verified
  against the owning store's `payments.slt.webhookSecret` AND the platform
  `SLT_WEBHOOK_SECRET`; every failure is the same 401 (no oracle). A verified
  store event reconciles through `confirmPayment` (which re-GETs the hub —
  webhooks never confirm directly).
- Dashboard: Storefront → Payments — 'SLT Payment Hub' market option (all
  three markets) + credentials card (Merchant ID / Secret key / Webhook
  secret / SMS toggle) + connection test. Whitelist lives in FOUR places when
  adding a gateway: `store/dto.update.ts` (types + Joi), `store/service.ts`
  merge, `storefront/notify.controller.ts` mask + test list,
  `StorefrontService.GATEWAY_CURRENCIES`.
- Platform client (CartFlow's own hub company, for subscription billing):
  `backend/src/shared/payment/slt/slt-hub.service.ts` reads
  `SLT_MERCHANT_ID` / `SLT_SECRET_KEY` / `SLT_WEBHOOK_SECRET` from
  `backend/.env`; warns at boot when unset. Subscriptions still charge via
  Ziina until explicitly switched.
- ARMADORN company values: logo
  `https://wp.armadorn.com/wp-content/uploads/2025/12/cropped-Logo_Only-scaled-1.png`,
  backward link `https://armadorn.com/pay/return`, webhook
  `https://cartflow.46.62.210.62.sslip.io/api/webhooks/slt` (the box running
  the storefront payment sweeps; the smartlabtec prod dashboard does not).
- CartFlow company values (platform billing): logo
  `https://cartflow.smartlabtec.com/icons/icon-512.png`, backward link
  `https://cartflow.smartlabtec.com/payment/success`, webhook
  `https://cartflow.smartlabtec.com/api/webhooks/slt` (prod owns
  subscriptions; route 404s there until the next docker pull deploy).
- Markets: ARMADORN sells EGP/AED/SAR — confirm via `GET /api/v1/gateways`
  that the hub company has a gateway enabled for each currency before removing
  the direct Ziina integration (Ziina covers AED/SAR/USD today).

## Go-Live Checklist (from the docs, kept verbatim in spirit)

1. `merchant_id`, token, webhook secret in server-side secrets.
2. Stable `Idempotency-Key` (your order id) on payment creation.
3. Verify redirect signature AND confirm via GET before fulfilment.
4. Verify `X-SLT-Signature` on the raw body; handlers idempotent.
5. `GET /api/v1/gateways` to confirm enabled gateways + currencies.

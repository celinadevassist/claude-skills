# Bot User-Agent Catalog

Sidecar reference for `wp-bot-hardening`. Every UA in the blocklist regex is documented here with: who operates it, what it's harvesting, why it's blocked for a typical WC store, the official page (for tone-checking against "good citizen" bots later), and a re-visit signal.

Open this file when:
- Adding/removing a UA from the regex in SKILL.md Step 2
- A user reports legitimate traffic was blocked (find the UA in their report, look it up here, decide)
- Pre-deploy review of the skill on a store in a market the current list doesn't cover (e.g. CN, RU)

The blocklist regex (from SKILL.md):
```
(MJ12bot|PetalBot|Bytespider|Amazonbot|SemrushBot|AhrefsBot|GPTBot|ClaudeBot|Claude-User|anthropic-ai|CCBot|DataForSeoBot|DotBot|MauiBot|BLEXBot|ZoominfoBot|meta-externalagent|Applebot-Extended|PerplexityBot|YandexBot|SeznamBot|Sogou|MegaIndex|serpstatbot|360Spider|YisouSpider|Bytedance)
```

Intentionally NOT blocked (real search / social): `Googlebot`, `Bingbot`, `Applebot` (without `-Extended`), `DuckDuckBot`, `Twitterbot`, `facebookexternalhit`.

---

## AI training crawlers (block by default)

These crawlers exist to scrape content into LLM training corpora. Zero search-traffic value back to the store.

| Token | Operator | What it does | Re-visit signal |
|---|---|---|---|
| `GPTBot` | OpenAI | Scrapes for ChatGPT training. [openai.com/gptbot](https://platform.openai.com/docs/gptbot) | Only unblock if you've explicitly opted IN to be indexed in OpenAI search / ChatGPT shopping cards |
| `ClaudeBot` | Anthropic | Scrapes for Claude training. [Anthropic crawler docs](https://docs.anthropic.com/en/docs/agents-and-tools/web-fetch-tool) | Same as above for Claude |
| `Claude-User` | Anthropic | Claude's web-fetch (real-time per-query, not training). Lower volume than ClaudeBot. | Block unless the store WANTS to be cited in Claude's responses |
| `anthropic-ai` | Anthropic | Alternative spelling some clients send | Same as ClaudeBot |
| `CCBot` | Common Crawl | Massive open corpus crawler; underlies many LLM training sets. [commoncrawl.org](https://commoncrawl.org/ccbot) | Block — even "open data" downstream uses are AI training |
| `Bytespider` | ByteDance (TikTok) | AI training for Doubao / Volc Engine. Notoriously aggressive — single sessions of 1000+ req/min reported. [bytespider docs](https://www.bytespider.cn/) | Block unless TikTok shop integration is being added |
| `Amazonbot` | Amazon | Powers Alexa/AI features per Amazon. Behaviour suggests training-corpus building. | Block — your store won't see Alexa-driven traffic regardless |
| `meta-externalagent` | Meta | Meta AI training crawler (introduced 2024). Distinct from `facebookexternalhit` (which IS allowed — it's the OG link preview crawler). | Block. Note: `facebookexternalhit` stays allowed — that's what makes WhatsApp / Messenger link previews work |
| `Applebot-Extended` | Apple | Apple's training-only variant of Applebot. Plain `Applebot` (which powers Siri / Spotlight / Safari Suggestions) is allowed. | Keep blocked — `Applebot-Extended` only matters for Apple Intelligence training |
| `PerplexityBot` | Perplexity AI | Perplexity's answer-engine crawler. Sends some referral traffic but disproportionate load. | Re-visit if Perplexity meaningfully ranks shopping queries in your market |

---

## SEO competitor scrapers (block by default)

These crawl your site so OTHER businesses can query competitive intelligence about your prices, products, link graph, etc. Your store doesn't subscribe to any of them, so they extract value without returning any.

| Token | Operator | What competitors query |
|---|---|---|
| `SemrushBot` | Semrush | Backlink graph, keyword positions, ad copy |
| `AhrefsBot` | Ahrefs | Same as Semrush, different DB |
| `MJ12bot` | Majestic | "Trust Flow" / "Citation Flow" link intelligence. Among the most aggressive in our cloudpanel-1 data (207 req/hr peak) |
| `DotBot` | Moz | Domain Authority crawler |
| `BLEXBot` | WebMeUp | Similar competitive backlink DB |
| `MauiBot` | Unknown / unattributed | No official page. Frequently seen in WP attack logs — block |
| `DataForSeoBot` | DataForSEO | SaaS API that resells SEO data; very high crawl rate when subscribers query "tell me everything about <competitor>" |
| `ZoominfoBot` | Zoominfo | B2B contact / firmographic harvesting. No retail-store value |
| `serpstatbot` | Serpstat | Same category as Semrush/Ahrefs |
| `MegaIndex` | MegaIndex.ru | Russian SEO platform crawler |

**Re-visit signal:** if YOUR business subscribes to one of these (e.g. you pay Ahrefs and want them to crawl YOUR site to feed YOUR own dashboards), remove that token from the regex.

---

## Regional crawlers (block by default — only matter for specific markets)

These are mainstream search engines for specific regions. **Unblock if your store targets that market.**

| Token | Operator | Market | Unblock if |
|---|---|---|---|
| `YandexBot` | Yandex | Russia / CIS | Selling to RU/CIS customers — Yandex is the dominant search engine there |
| `Bytedance` (generic) | ByteDance | China | TikTok shop integration. Note: also catches Bytespider — split into separate regex entries if you want one without the other |
| `Sogou` | Sogou (Tencent) | China | Selling to CN; ~5% search share |
| `360Spider` | Qihoo 360 | China | Selling to CN; ~10% search share |
| `YisouSpider` | UC Browser (Alibaba) | China mobile | Selling to CN — UC has significant CN mobile presence |
| `PetalBot` | Huawei | China + Huawei device ecosystem | Selling to CN OR markets where Huawei device share is high (some MENA regions) |
| `SeznamBot` | Seznam.cz | Czech Republic | Selling to CZ — Seznam is the local default search there |

For cloudpanel-1 (smartlabtec — EG market): all of these stay blocked. madomarche.com gets ~88 PetalBot req/hr with zero conversions from CN traffic — pure waste.

---

## How to add a new UA to the blocklist

1. Identify the UA from access logs (typically over-represented in a recent slow-down):
   ```bash
   ssh root@${HOST_IP} "awk -F'\"' '{print \$6}' /home/${SITE_USER}/logs/nginx/access.log | sort | uniq -c | sort -rn | head -30"
   ```
2. Look up who runs it (Google the UA string verbatim, find the operator's bot info page).
3. Decide using the matrix above (AI training / SEO scraper / regional / good citizen / unknown).
4. Add the UA token to the regex in SKILL.md Step 2.
5. **Increment the marker** from `HARDENING_BLOCK v1` to `v2` so existing deployments re-apply.
6. Add an entry to this catalog with the rationale.
7. Re-run the skill on every host that has the marker.

---

## How to UNBLOCK a UA when you change markets

E.g. madomarche.com expands to KSA + UAE where users predominantly browse via Huawei devices:

1. Edit SKILL.md Step 2 — remove `PetalBot` from the regex.
2. Bump marker to `v2`.
3. Re-run the skill. Existing `v1` blocks get replaced with `v2` (which omits PetalBot).
4. Verify with `curl -A "Mozilla/5.0 (Linux; Android) ... PetalBot ..." https://madomarche.com/` → expect 200.
5. Update this catalog with a "✅ UNBLOCKED 2026-09-15 — KSA expansion" note next to PetalBot.

---

## Test UAs for the verification step

Real-world UA strings to use in curl verification. These match the regex tokens exactly.

```bash
# Should 403:
-A "Mozilla/5.0 (compatible; MJ12bot/v1.4.8; http://mj12bot.com/)"
-A "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.0; +https://openai.com/gptbot)"
-A "Mozilla/5.0 (Linux; Android 7.0;) AppleWebKit/537.36 ... PetalBot;+https://webmaster.petalsearch.com/site/petalbot)"
-A "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)"
-A "Bytespider"   # short form, still matches the regex

# Should 200 (allowlisted real bots):
-A "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
-A "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
-A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15 Applebot/0.1"
-A "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
```

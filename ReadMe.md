> October 17 update: product photo uploads/crops/frame selection, safe editor saves, item archive, expanded recorded expenses, private recovery/cleanup and CI acceptance checks. See [release readiness](docs/READINESS.md) and [current validation](docs/VALIDATION.md). Live eBay/Google checks still require seller credentials.

# SnapSell — prepare once, sell on your marketplaces

SnapSell turns an inventory video into reviewed resale listings, researches asking prices, and prepares materials for **eBay, Facebook Marketplace and Craigslist**. Buyers and payments stay on those marketplaces.

## Current workflow

1. **Inventory:** upload real goods in an English-narrated video, or enter an item manually. AMD vision creates private drafts across 26 categories and Other. Local Whisper transcribes English speech.
2. **Review & research:** confirm observed facts. Unknown models can be researched from the photo. Source-backed candidate models remain unconfirmed until the seller compares them. Numeric price recommendations require sufficient matching evidence.
3. **Channels:** choose an item and marketplace. SnapSell prepares a suitable title, description, available asking price and real photo. Copy the text or download a ZIP listing kit. A supported market-median recommendation is prefilled when the seller has not already set a price; insufficient evidence leaves the price blank.
4. **Post externally:** publish a configured eBay offer through the connector, or open the marketplace form and post manually in the seller's account. Record the actual published item URL in SnapSell. Downloading a kit never marks an item published.
5. **Reply desk:** paste a buyer's marketplace question, review a fact-based response and copy it back. Replies are drafts; marketplace inboxes are not synchronized and SnapSell does not send messages.
6. **Deals:** add pickup intervals and meeting places, book a reviewed item for a named buyer, record buyer agreement, reschedule/cancel and confirm pickup or a no-show. Private in-app reminders and manual calendar exports are available. See [pickup organization](docs/DEALS.ru.md).
7. **Results:** record a completed external sale with the actual fee and acquisition cost. Contribution is sale price minus recorded fee and acquisition cost. Other recorded copies are flagged for removal. Connected eBay copies are withdrawn through the API; the seller removes other marketplace copies and confirms removal.

## Integration status

| Destination | Working now | Direct publication |
|---|---|---|
| eBay | Listing ZIP, seller OAuth, Inventory API publish/update/status/withdraw, existing SKU linking | Sandbox by default; developer keys and seller authorization required |
| Facebook Marketplace | Listing ZIP, copyable text/photo, link tracking and reply drafts | Manual posting in the seller's account |
| Craigslist | Listing ZIP, copyable text/photo, link tracking and reply drafts | Manual posting in the seller's selected city |

The eBay connector implements single-unit FIXED_PRICE listings on EBAY_US. Configure it using [the free Sandbox setup guide](docs/EBAY_SETUP.ru.md). Live publication has not been verified without developer keys and seller authorization. eBay publication requires seller OAuth authorization, the correct leaf category and aspects, a supported condition, public photo URLs, inventory location and business policy IDs. The exported JSON identifies missing fields; it is **not** a complete live-publish request. [Official eBay publishing requirements](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html).

Craigslist bulk posting is access-controlled and intended for approved high-volume accounts in specific paid categories; this prototype uses manual posting. [Official bulk interface](https://www.craigslist.org/about/bulk_posting_interface). Facebook's seller flow is used for manual transfer. [Facebook selling help](https://www.facebook.com/help/550954179351183/).

Manual listing statuses and financial sale completion are **seller-reported**. Connected eBay offers are checked through the API every two minutes while app.py runs. An eBay sold unit blocks relisting but does not fabricate payment or fee data. Local revisions are marked for synchronization; use Update on eBay after reviewing them. Connected eBay copies queued for removal are withdrawn through the API; other platforms require manual removal. No external posting, payment or message is performed by downloading or copying materials.

## One-click launch on Windows

After the initial setup, double-click **Start SnapSell.cmd** in the project folder. It checks the installed dependencies, starts the local API and website, and opens <http://127.0.0.1:3000>. The first launch builds the production website; later launches reuse it until frontend source files change. Python and Node helper processes run without separate windows. No packages are downloaded and no billing is enabled by the launcher.

Keep the launcher window open and use **Ctrl+C** there to stop servers it started. If SnapSell was already running, the launcher reuses it and leaves those existing processes alone. Logs are in `private/backend.log`, `private/frontend.log` and `private/build.log`.

To check installation without starting servers:

```powershell
& ".\Start SnapSell.cmd" --check
```

Node.js is detected from PATH, the installed Codex runtime, or the standard Windows installation. `SNAPSELL_NODE` can point to a different Node.js executable. Standard ports 3000/5000 match the configured Google OAuth callback. Initial dependency installation is described below; the two-terminal development workflow also remains available.

See [the full session change report](docs/SESSION_CHANGES.ru.md) for implemented features, validation and remaining limits.

## Local setup

Tested with Python 3.11 and Node.js 22+; pnpm is required.

```powershell
Copy-Item .env.example .env
# Set AMD_API_KEY and optionally SELLER_PASSWORD in .env.
python -m venv .venv
.venv/Scripts/python -m pip install -r snapsell-backend/requirements.txt
pnpm --dir snapsell-frontend install --frozen-lockfile
.venv/Scripts/python snapsell-backend/speech.py
```

Speech setup downloads a pinned, checksum-verified model (~75 MB), cached in `data/models/tiny.en`. Audio transcription runs locally on CPU. AMD performs vision, product identity lookup, research planning, buyer-intent classification and evidence summaries. Available models are discovered at runtime; the API key stays on the server.

Run in two terminals from the repository root:

```powershell
.venv/Scripts/python snapsell-backend/app.py
```

```powershell
pnpm --dir snapsell-frontend dev
```

Open [SnapSell](http://127.0.0.1:3000). `LOCAL_ACCESS=true` enables local quick entry with `snapsell-local`. Network deployments require `LOCAL_ACCESS=false`, a strong `SELLER_PASSWORD`, HTTPS and `COOKIE_SECURE=true`. Persist the data directory and run one backend process; interrupted jobs can be retried.

## Price decisions

The system starts without fabricated inventory, offers or buyer activity. Prices come from retrievable merchant evidence, not generated numbers. Web valuation requires at least three distinct matching product pages from two merchants. Variant/tracking links do not manufacture independent observations. Merchant-balanced recency weights, a MAD outlier check and weighted quartiles produce asking-price positions constrained by recorded cost, fee estimate and seller minimum. Asking prices do not prove completed sales.

Without sufficient real seven-day outcomes, sale probability and expected-return forecasts remain unavailable. See [price research](docs/PRICE_RESEARCH.md) and [validation](docs/VALIDATION.md).

## Checks and provenance

```powershell
.venv/Scripts/python -m pip install pytest
.venv/Scripts/python -m pytest snapsell-backend/tests -q
pnpm --dir snapsell-frontend typecheck
pnpm --dir snapsell-frontend build
```

Tests use an isolated database. Source derives from [CollinQ/sbhacks2025](https://github.com/CollinQ/sbhacks2025), preserved with its MIT license under `upstream/`. SQLite provides a persistent single-seller runtime. AMD Token Factory is an experimental development service; deployment for production customers needs an appropriate supported inference endpoint.

The repository's earlier CHESHIRE concept is preserved in [docs/CHESHIRE_CONCEPT.md](docs/CHESHIRE_CONCEPT.md).

Price research now offers US/USD, Kazakhstan/KZT, Japan/JPY and China/CNY selectors, separate similar-product references, source-backed delivery comparisons and opt-in daily refresh. Foreign estimates never overwrite USD inventory accounting. Optional eBay Browse research and explicit seven-day outcome collection are documented in [price research](docs/PRICE_RESEARCH.md). Regional live coverage and credentialed Browse calls have not been established by the isolated tests.

Google Calendar can be connected from Deals: primary-calendar availability checks, automatic pickup event creation and updates, durable retries, and popup reminders. Configure a Web OAuth client and authorize your account using [the Google Calendar guide](docs/GOOGLE_CALENDAR.ru.md). External-calendar edits do not update local meetings. The local Google account was connected and live availability reads plus temporary event creation, rescheduling and cancellation were verified; this does not establish eBay publication or production Google OAuth verification.

The repository's earlier CHESHIRE concept is preserved in [docs/CHESHIRE_CONCEPT.md](docs/CHESHIRE_CONCEPT.md).

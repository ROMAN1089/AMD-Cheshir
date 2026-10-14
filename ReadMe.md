# SnapSell — prepare once, sell on your marketplaces

SnapSell turns an inventory video into reviewed resale listings, researches asking prices, and prepares materials for **eBay, Facebook Marketplace and Craigslist**. Buyers and payments stay on those marketplaces.

## Current workflow

1. **Inventory:** upload real goods in an English-narrated video, or enter an item manually. AMD vision creates private drafts across 26 categories and Other. Local Whisper transcribes English speech.
2. **Review & research:** confirm observed facts. Unknown models can be researched from the photo. Source-backed candidate models remain unconfirmed until the seller compares them. Numeric price recommendations require sufficient matching evidence.
3. **Channels:** choose an item and marketplace. SnapSell prepares a suitable title, description, available asking price and real photo. Copy the text or download a ZIP listing kit. A supported market-median recommendation is prefilled when the seller has not already set a price; insufficient evidence leaves the price blank.
4. **Post externally:** open the marketplace form and post in the seller's account. Record the actual published item URL in SnapSell. Downloading a kit never marks an item published.
5. **Reply desk:** paste a buyer's marketplace question, review a fact-based response and copy it back. Replies are drafts; marketplace inboxes are not synchronized and SnapSell does not send messages.
6. **Results:** record a completed external sale with the actual fee and acquisition cost. Contribution is sale price minus recorded fee and acquisition cost. Other recorded copies are flagged for removal; the seller confirms removal after ending them on the marketplace.

## Integration status

| Destination | Working now | Direct publication |
|---|---|---|
| eBay | Listing ZIP, text/photo transfer, Inventory/Offer JSON draft, external-link tracking | Seller API not connected |
| Facebook Marketplace | Listing ZIP, copyable text/photo, link tracking and reply drafts | Manual posting in the seller's account |
| Craigslist | Listing ZIP, copyable text/photo, link tracking and reply drafts | Manual posting in the seller's selected city |

eBay direct publication requires seller OAuth authorization, the correct leaf category and aspects, a supported condition, public photo URLs, inventory location and business policy IDs. The exported JSON identifies missing fields; it is **not** a complete live-publish request. [Official eBay publishing requirements](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html).

Craigslist bulk posting is access-controlled and intended for approved high-volume accounts in specific paid categories; this prototype uses manual posting. [Official bulk interface](https://www.craigslist.org/about/bulk_posting_interface). Facebook's seller flow is used for manual transfer. [Facebook selling help](https://www.facebook.com/help/550954179351183/).

External listing statuses and completed sales are explicitly **seller-reported**, not API-verified or synchronized. No external posting, payment or message is performed by downloading or copying materials.

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

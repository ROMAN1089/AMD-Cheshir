# SnapSell

An English-language US resale workspace: video → reviewed inventory → source-backed asking prices → storefront → buyer questions and offers → seller-confirmed sales.

## Start locally

Requires Python 3.11+, Node.js 22.12+ and pnpm. `ffmpeg` is supplied by the Python package; no system installation is needed.

From this directory in PowerShell:

```powershell
Copy-Item .env.example .env
# Set AMD_API_KEY and SELLER_PASSWORD inside .env. Never commit this file.
python -m venv .venv
.venv/Scripts/python -m pip install -r snapsell-backend/requirements.txt
pnpm --dir snapsell-frontend install --frozen-lockfile
.venv/Scripts/python snapsell-backend/speech.py
```

The speech setup downloads a pinned, checksum-verified English model (~75 MB). It runs on CPU. Model files are cached in `data/models/tiny.en`; `ASR_MODEL_PATH` can point to an existing compatible model. Without the model, video extraction still works and clearly asks the seller to supply spoken facts manually.

Start the backend in one terminal and frontend in another:

```powershell
.venv/Scripts/python snapsell-backend/app.py
```

```powershell
pnpm --dir snapsell-frontend dev
```

Open [SnapSell](http://127.0.0.1:3000). With `LOCAL_ACCESS=true`, the local quick-entry password is `snapsell-local`. For a network deployment, set `LOCAL_ACCESS=false`, a strong `SELLER_PASSWORD`, `COOKIE_SECURE=true` behind HTTPS, and configure the frontend backend address before building. The local quick-entry button is then disabled. Use a persistent data directory and a single backend process; the job queue is in-process, and interrupted jobs can be retried.

## Use real inventory

1. Upload an MP4, MOV, WebM or M4V, up to 180 seconds and 250 MB. Show real items one at a time: furniture, clothing, shoes, books, tools, toys, electronics, appliances or any other goods. Show readable labels and narrate included parts and known condition in English. Extraction supports up to 30 products per capture, with `Other` retaining products outside the named taxonomy. Game scenes, advertisements and pictures of products are not physical inventory.
2. Review each draft. Confirm category-relevant details and enter acquisition cost, selling fee, minimum price and asking price. Clothing exposes size/material/color; furniture exposes dimensions/material; books expose author/ISBN/edition; electronics keep their own fields. Unknown facts remain unknown. Drafts are private until explicitly published.
3. Choose **Identify & find matches** when the model is unknown. AMD recognizes the common product type from the photo and searches source-backed possible models. Compare a candidate and confirm **This matches my item** before its identity can support a valuation. Once an exact model is saved, price research starts automatically. Inspect prices and source evidence under **Pricing evidence**. Three independent product pages from at least two merchants are needed for a numeric recommendation.
4. Open **View store** to ask buyer questions and submit an offer. The seller controls whether a completed deal is recorded. The service does not collect payment or automatically book meetings.
5. Insights use recorded buyer events and completed deals. Contribution deducts recorded cost and fees, with the sale's economics frozen at completion. No fabricated views, revenue or sales forecasts are added.

## AMD and numeric decisions

AMD Token Factory performs multimodal inventory extraction, photo identification, candidate-model lookup, search planning, adaptive search refinement, buyer-intent classification and a bounded evidence summary. Available models are discovered from `/models`; Qwen3.8-Flash-Next is the preferred vision model after direct comparison on an ambiguous record-player capture. Explicit model overrides are supported. The API key stays on the server. Speech uses local Whisper because the event gateway currently rejects the audio input format.

Prices come from retrievable merchant evidence, not model-generated numbers. Merchant-balanced recency weights, a MAD outlier check and weighted quartiles produce asking-price positions. Fee-adjusted break-even and seller minimum constrain every recommendation. Used inventory and refurbished retail are separate condition classes. A refurbished retail reference does not become a private used-item valuation.

Without at least 120 fully labeled real seven-day outcomes, sale probability and expected-return forecasts are unavailable. The existing forecast feature schema is limited to laptops and monitors; other categories use observed market comparisons without inheriting that model. An observed price is not evidence that an item sold or that a price change will improve revenue. See [price research details](docs/PRICE_RESEARCH.md).

## Validation

```powershell
.venv/Scripts/python -m pip install pytest
.venv/Scripts/python -m pytest snapsell-backend/tests -q
pnpm --dir snapsell-frontend typecheck
pnpm --dir snapsell-frontend build
```

Backend tests use a separate temporary database and do not call paid inference or add demo inventory. Live verification should also use a separate `DATA_DIR` so diagnostic offers and sales never enter the seller's workspace.

## Origin and limits

Based on [CollinQ/sbhacks2025](https://github.com/CollinQ/sbhacks2025), preserved with its MIT license under `upstream/`. The runtime extends the original Flask/video approach with a new commerce workflow and English frontend. SQLite provides persistent single-store storage; this is not yet a multi-tenant marketplace. There is no external marketplace publishing integration or payment processing. Token Factory is an experimental event service for development and trials; use an appropriate supported endpoint before serving production customers.

The repository's earlier CHESHIRE concept is preserved in [docs/CHESHIRE_CONCEPT.md](docs/CHESHIRE_CONCEPT.md).

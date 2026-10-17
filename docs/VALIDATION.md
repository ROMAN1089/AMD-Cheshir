# Current AMD optimization validation — October 17, 2026

- Backend: 300 isolated behavioral tests. New coverage checks concurrent request capacity, shared pacing/cooldown, non-retryable authentication, model modalities, one-hop vision fallback, non-reasoning mode, intent cache key isolation, changed product facts, explicit battery-topic protection, accounting for invalid model output, observed connectivity, lossless duplicate-frame selection, safe saved-frame reuse and idempotent seller recovery from failed captures.
- Frontend production build and TypeScript validation passed locally. Chromium acceptance coverage now also includes the AMD compute dashboard without falsely reporting connectivity when no key exists. Read the corresponding GitHub Actions run for remote execution status.
- Live intent/cache and visual-model diagnostics, including failures, are documented in [AMD_PIPELINE.md](AMD_PIPELINE.md). No overall end-to-end vision speedup or new real-market forecasting accuracy is claimed.
- Existing 280-test release results below are historical. External eBay/Google account requirements remain unchanged.

---

# Current validation — October 17, 2026

- Backend: 280 isolated behavioral tests, including photo decode/crop/export, unowned source rejection, archive guards, complete manual-to-marketplace-kit-to-recorded-sale workflow, actual expense accounting, repeated-sale rejection, consistent backup/restore and protected cleanup. Fixture prices exist only in disposable test databases.
- Notification receiver: five worker tests. Production frontend build includes TypeScript checking.
- Live AMD: authenticated connectivity call returned HTTP 200 using DeepSeek-V4-Flash on this installation. No seller item was changed by this check.
- Local browser review: actual existing item opens the photo editor, saved video frames and crop controls. The real inventory is retained. Mobile dialog stacking and Escape protection were corrected after review.
- Browser acceptance tests and GitHub Actions are now included. Their execution status must be checked separately; adding tests is not evidence that a remote CI run passed.
- The current eBay Sandbox settings are missing client_id/client_secret/runame; Google is missing client_id/client_secret. Neither seller account is connected. No real marketplace publication, payment or Google event was executed in this pass.

Current release scope, recovery instructions and remaining external checks: [READINESS.md](READINESS.md).

---

## Historical October 14 baseline (not the current release test count)

# Validation — October 14, 2026

## Completed checks

- Backend: 64 isolated tests passed. Coverage includes unknown-model lookup, candidate/valuation separation, explicit model confirmation, media path safety, marketplace listing kits, supported price prefilling, seller-price preservation, ZIP output, destination/item-link validation, completed external sales, repeat-sale protection, copy-removal confirmation and replies that do not create fake buyer events.
- Frontend: TypeScript check and production build passed. Browser review confirmed the category selector, inventory category filter and category-relevant specification fields.
- English speech: the installed, checksum-verified local Whisper model accurately transcribed a diagnostic recording containing “Dell Latitude 5420”, “16 gigabytes”, “256 gigabyte”, included charger and an untested battery. Four seconds of silence produced no text.
- Live video: a real 54,112,118-byte MOV from the public upstream repository passed upload, decoding, English speech recognition and AMD MiMo-V2.6-Flash extraction in 37 seconds. Five private drafts were created: office chair (Furniture), energy drink can (Other), backpack (Accessory), cap (Clothing) and MacBook Pro (Laptop). Exact model identifiers remained unknown where they could not be established. This run used a separate validation database, not the seller's inventory.
- General commerce: an extracted furniture draft was reviewed and published in that isolated database, received a buyer offer and completed exactly once. Recorded revenue and fee-adjusted contribution matched the explicit diagnostic inputs. A repeated completion was rejected. No real payment or external marketplace action occurred.
- Streaming upload: a 12 MiB multipart request reached Flask through the frontend route and was correctly rejected as invalid media. No inventory or upload job was created by this diagnostic request. The real MOV above independently confirmed valid large-file ingestion.
- Existing seller upload: the saved Minecraft screen recording was reprocessed with AMD and local speech. Processing completed with zero products, correctly avoiding fictitious physical inventory from game objects.
- A subsequent seller upload completed with two observed product drafts in Electronics and Other. Unverified function, brand and model were flagged for review.
- Final automatic price-research check: 25 pages checked in 73 seconds; two current asking prices accepted from two independent merchants. The three-page threshold was not met, so no numeric recommendation or sale-speed forecast was published.
- Photo identification with Qwen3.8-Flash-Next correctly recognized the ambiguous suitcase record player and disassembled hard-drive components. The live unknown-model workflow renamed the unconfirmed draft to Portable Suitcase Record Player, classified it as Audio and discovered a source-backed Crosley resale candidate. The candidate remains explicitly unconfirmed, with no offer value or item valuation invented.
- Live Facebook Marketplace kit download contained listing JSON, title, description, posting guide and the actual 84,810-byte product photo. Download did not create a posted external listing or fabricate a price when no supported estimate existed.

## Limits of these checks

The current UI centers on external marketplace preparation. Listing-kit download is not publication. eBay Seller API authorization has not been connected; Facebook Marketplace and Craigslist use manual posting. External listing states and sales are seller-reported. Historical local-store checks above document earlier validation, not the current seller flow.

The five-item capture validates multiple product categories, not recognition accuracy for every product or every recording. Poor lighting, unreadable labels and similar-looking objects still require seller review. These checks do not establish measured conversion uplift or market demand.

Live web verification has accepted actual current asking prices from independent US merchants. Search coverage varies, and some repeated runs find fewer usable pages. Automatic valuation remains unavailable unless the evidence threshold is satisfied. Neither a successful crawl nor a generated description proves that a transaction occurred.

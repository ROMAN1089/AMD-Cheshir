# Live price research

The application starts with an empty inventory, no seeded comparables, no fabricated buyer activity and no synthetic forecast fallback.

Saving an item with an exact model (or extracting one from a video) automatically queues research. Open the listing or **Research & AMD** to inspect progress, accepted observations and rejected pages. A manual re-run can include up to five direct product URLs.

## Evidence pipeline

1. AMD Token Factory plans queries using the saved product identity and capacity configuration.
2. DDGS discovers public product pages across search engines. Search snippets are discovery only: their numbers are never imported as prices.
3. The fetcher respects robots exclusions, validates public HTTPS addresses, pins DNS results for TLS connections, checks certificates and revalidates redirects. It does not sign in, solve challenges, bypass access controls or execute website scripts.
4. Product/Offer structured data or explicit primary-product OpenGraph metadata must establish the exact model and recorded processor/RAM/storage, USD price, pre-owned condition and current availability. The documented Shopify Product Ajax API can resolve available variants, with explicit page currency, original minor-unit prices and product/variant evidence preserved. Aggregate ranges, unresolved variants, unavailable offers, accessories, broken products and unconfirmed currency are rejected. Conflicting merchant metadata remains visible.
5. Each observation retains the source URL, retrieval time, source condition, availability, relevant structured evidence and a hash of the fetched page. It expires from the estimate after seven days or when the saved product identity changes.
6. If the first pass has too few independent merchants, AMD refines searches using rejection reasons. Source budgets are shared across queries so targeted searches are not crowded out. Accepted offers appear while remaining sources are checked.
7. At least three distinct product pages from two merchants are required for a web market estimate. Multiple cosmetic grades on one page cannot satisfy that threshold. Merchant-balanced recency weights, an outlier filter and weighted quartiles produce the observed asking-price band. There are no invented numerical condition adjustments.

## What “verified” means

The system has checked that a public source advertises that offer at that price. It has not verified that the seller is trustworthy, that someone bought it, or that shipping/taxes are included. Used and refurbished inventory are separated. Cosmetic grades may differ and remain visible in the evidence.

The public-web connector does **not** label an asking price as a completed sale. Confirmed transaction data needs an authorized transaction source or another independently verifiable record. An arbitrary imported CSV marked `sold` is not enough.

There is no guarantee of coverage of every website. Robots exclusions, blocked requests, missing structured prices, out-of-stock products and search limits are reported rather than silently substituted with estimates. An empty research result produces no price recommendation.

## Demand forecasts

No sales probability is displayed until at least 120 observed, fully labeled seven-day outcomes with both classes are available. Web asking prices alone cannot establish demand, sale speed or profit uplift. Without outcome history, the three price choices are market quartile positions, not forecasts.

## Dependencies and sources

- [DDGS](https://github.com/deedy5/ddgs), MIT: search discovery.
- [Schema.org Offer](https://schema.org/Offer): price, currency, condition and availability evidence.
- [Shopify Product Ajax API](https://shopify.dev/docs/api/ajax/reference/product): public variant availability and minor-unit prices.
- [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html): a possible future authorized active-listings connector; active listings do not prove completed transactions.
- [AMD model APIs](https://amd-aim.github.io/radeon-cloud-docs/guides/model-apis/): query planning and bounded evidence synthesis.


## Four research markets (October 15, 2026)

Research starts on US/USD. The research panel can select Kazakhstan/KZT,
Japan/JPY or China/CNY. Jobs, accepted observations, rejection reasons and
refresh schedules are separate by market and exact/similar matching mode.
No exchange-rate conversion is performed. The existing inventory, channel kits
and accounting remain USD; foreign research estimates cannot set their prices.
A Japanese or Chinese market option is not a connection to Mercari, Taobao or JD.

Regional web offers require the selected currency and a national source domain
(.kz, .jp or .cn), or a source Offer explicitly establishing eligibleRegion.
Generic foreign-currency pages do not establish the country by currency alone.
Blocked pages, robots exclusions and missing evidence remain rejected. Coverage
of all four markets has not been established by live end-to-end validation.

Brand matching is mandatory when a brand is recorded; model identifiers,
generation and recorded capacity constraints are checked. Unicode normalization
supports Cyrillic and Japanese/Chinese product text alongside Latin model codes.
This is still a conservative rule-based matcher, not a guaranteed recognizer.

Similar-product research is available without an exact model when product type,
descriptive title and recorded attributes match source evidence. It produces a
separate reference band, never automatic exact-model strategies or forecasts.
An unknown item in Other must first be categorized. Sparse results remain empty.

Each product page counts once; variants and tracking URLs do not inflate the
sample. Outliers are displayed as excluded, and the independent-page/seller
threshold is checked again after filtering. eBay Browse seller identities can
establish different sellers on the same platform. Asking-price evidence is not
mixed with completed transaction prices. Current research fingerprints include
brand and category; old snapshots are invalidated when facts change.

## Delivery, taxes and scope

The default comparison uses item asking prices. A separate item-plus-delivery
comparison accepts only explicit shipping amounts in the same currency for the
selected destination country. It is a reference, not a suggested item price.
Unknown shipping is not assumed to be zero. Taxes remain unverified and are not
invented. Shipping rules with postal-code or regional restrictions are skipped
because this version does not collect the buyer's precise address.

## Optional eBay Browse source

Set EBAY_BROWSE_ENABLED=true and separate Production EBAY_BROWSE_CLIENT_ID and
EBAY_BROWSE_CLIENT_SECRET. The connector obtains an application access token and
uses read-only Browse search/getItem requests. Production API access depends on
eBay permissions; without credentials this source is disabled. Seller OAuth
Inventory API authorization does not substitute for Browse application tokens.
Only available, fixed-price US offers with USD prices, seller identity and
matching product evidence are admitted. API observations retain a response hash
and their evidence. No live Browse credentials were available for validation.

OLX's official API cannot read other sellers' adverts, so it cannot supply a
market-wide price catalog. No paid scraper or access-control bypass is installed.

## Daily refresh

Daily refresh is opt-in in the research panel. Its switch persists immediately, so it can also be disabled without starting another search.
It uses the configured search/inference quotas. The app.py worker queues due
subscriptions every minute, at most once per day per subscription. Sold items
are skipped. A market refresh replaces only that market/matching mode's snapshots;
a successful run with zero observations removes previous snapshots in that scope.

## Captured seven-day outcomes

For reviewed, active US/USD Laptop/Monitor inventory with an exact-model baseline,
Start observation freezes the price ratio and other model features for seven days.
A seller-confirmed completed sale within the window writes a labeled history row
atomically with the sale. An unsold outcome requires explicit seller confirmation
after the entire window; silence is never labeled unsold automatically. Changes
to price, facts or availability invalidate the observation. Sandbox listings are
excluded. Captured outcomes retain seller-reported provenance and are not
independently audited transaction data. An outcome window is not a public sold
price connector. Late-recorded transactions can be missing from the eligible cohort.

Forecasts require 120 eligible US/USD outcomes, both classes in every chronological
train/calibration/test split and held-out Brier performance better than the
constant baseline. Imported labels must be binary and their timestamps cannot
be future or timezone-free. These checks validate shape and model performance;
they do not prove the truth of an imported CSV or causal demand effects. Models
are not extrapolated to foreign markets or other product categories.

Official references:

- [eBay Browse API](https://developer.ebay.com/develop/api/buy/browse_api)
- [OLX FAQ: other users' ads](https://developer.olx.kz/articles/faq)
- [Shipping evidence](https://schema.org/OfferShippingDetails)
- [Shopify Product Ajax](https://shopify.dev/docs/api/ajax/reference/product)

Regional CSV comparables may specify market and currency (US/USD, KZ/KZT, JP/JPY, CN/CNY); omitted columns retain legacy US/USD defaults. Currency mismatch and unknown exact-model keys are rejected. Imports remain seller-provided observations, not source-verified prices. Repeated identical history rows are deduplicated so reimport cannot manufacture additional training outcomes.

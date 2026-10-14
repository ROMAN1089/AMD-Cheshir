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

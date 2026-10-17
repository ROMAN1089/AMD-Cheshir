# eBay price research

The US price source uses Production Browse API application credentials, not seller
OAuth. RuName and seller authorization are required for listing management, not Browse.
Production listing writes remain disabled.

## Evidence checks

- Search by saved model, brand and recorded CPU/RAM/storage, with a shorter model
  query as a fallback. Search at most 30 unique detailed offers across both queries.
- Read the official getItem response. A search snippet alone is not price evidence.
- Require exact model/recorded attribute matching, current in-stock availability,
  US item location, a positive USD price and a fixed-price buying option.
- Exclude ended listings, new/open-box inventory, accessories and multi-unit lots.
  Browse's live `lotSize: 0` means no lot; it must not reject normal listings.
- Keep working/faulty and used/refurbished comparisons separate. Reject mismatched
  specifications. A failure to fetch one listing does not discard other offers.
- Preserve source condition IDs, item ID, availability, observed time and evidence
  hash. Keep only the variation selector in a canonical listing URL.
- Delivery is separate and accepted only for a source-stated single-unit US
  estimate. Missing delivery is never assumed to be zero. Taxes remain unknown.
- The numeric engine requires at least three independent pages and two sellers,
  excludes robust outliers and weights each seller equally before weighted
  quartiles. Missing unit-specific facts produce preliminary confidence.
- These are current asking prices, not completed sales or evidence of sale speed.
  Neither the LLM nor estimatedSoldQuantity supplies a sale-price forecast.

## Live verification, 2026-10-17

Read-only diagnostic for Dell UltraSharp U2720Q: 9 detailed offers checked, 5 model
matches from 5 distinct sellers, 4 different-model titles rejected. Matching item
asking prices were USD 159.99, 299.00, 450.00, 627.89, 185.00. No source-stated US
delivery estimates were accepted. This is a diagnostic snapshot, not an appraisal
of any seller-owned unit. These offers were not saved to the owner workspace.

## Current deployment blocker

The configured Cloudflare notification inbox returns HTTP 503. Its corresponding
RSA private key is also absent from this checkout. The persisted research path
therefore remains paused by its existing notification synchronization check.
An application token and a successful Browse search do not mean this path works.

The deployment owner needs to restore the existing Pages/Worker service, its D1
`DB` binding and inbox schema, and provide the matching private key at
`private/ebay-notifications.pem`. Do not generate a replacement key while old
encrypted messages are queued. Verify the key matches the deployed PUBLIC_KEY_JWK,
process pending signed notifications and then run research through the app.
See `deploy/ebay-notifications/README.ru.md` for the deployment procedure.

Targeted coverage includes lot-zero semantics, invalid/auction/expired/foreign
offers, separate shipping, parts rejection, deduplication, request limits,
single-listing failures and the notification guard. All fixtures use temporary
databases, never the owner's prices or credentials.

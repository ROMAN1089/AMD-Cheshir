# SnapSell readiness — 2026-10-17

Scope: a single-seller, English, US/USD resale application. Other-market research is kept as an optional reference; local inventory accounting remains USD. This release does not introduce multi-tenant public hosting or promise marketplace messaging automation.

## Completed in this pass

- Real JPG/PNG/WebP uploads for existing manual and video drafts, cover selection, saved video-frame selection, reversible photo-list removal and crop copies. Up to 12 photos; 12 MB and 24-megapixel limits. EXIF metadata is removed by decoding/re-encoding. Listing ZIPs contain the real photo collection.
- Open editors save only changed fields. A newer backend price survives saving an unrelated description. Explicit price selection saves unrelated pending edits first. Unsaved edits are protected on dialog close, Escape and browser navigation. Dialogs cover mobile navigation.
- Every source receives a unit-attribute audit. Explicit battery-health and repair-history conflicts exclude an offer. Missing battery/repair/additional-question facts are disclosed; source ranges remain preliminary and receive no invented numerical adjustment. Editing product identity invalidates the old assessment label while retaining the seller's asking price.
- Reversible inventory archive with guards against active marketplace copies, detected sales and scheduled pickups. Archived products do not count toward active asking inventory or receive scheduled research. Product history and images remain.
- External sale accounting records shipping, packaging, repairs, taxes, labor and refunds as well as acquisition cost and marketplace fees. Legacy sales retain their original recorded economics. Unrecorded costs and future costs remain unknown; this is recorded contribution, not an audited profit statement.
- Private consistent SQLite snapshots include saved media, upload originals, session encryption key, encrypted integration tokens, private integration material and configured environment files. Downloaded model caches are excluded. Startup creates a daily snapshot when needed. Recovery verifies SHA-256 checksums and SQLite integrity, restores only to a NEW folder and adjusts upload paths.
- Storage maintenance previews removable files. Cleanup first creates a verified recovery archive, then removes only original finished/failed uploads and unused media. Product photos and active-job files are retained; cleaned uploads clearly require re-upload before retry.
- GitHub validation workflow runs backend tests, production frontend build, notification-worker tests and isolated Chromium browser acceptance tests. Browser tests use a disposable database and disable inference/marketplace research; they never post actual listings.

## Reproducing recovery

Run `python scripts/backup.py` using the application Python environment. Archives are stored in `private/backups/` and contain credentials; keep them private.

Verify with `python scripts/backup.py --verify ARCHIVE.zip`.

Restore with `python scripts/backup.py --restore ARCHIVE.zip --to NEW_RECOVERY_DIRECTORY`. Point DATA_DIR to NEW_RECOVERY_DIRECTORY/data. Review recovered config files before copying them into the application root. Restored `.session-secret` and encrypted tokens must be used together. Recovery is intentionally never an in-place overwrite of a live installation.

## External verification still required

- eBay Sandbox: the current installation lacks Client ID, Client Secret and RuName. No seller is authorized. The user explicitly chose to finish everything possible without an account. Real create/read/update/withdraw, timeout reconciliation and remote photo acceptance cannot be claimed from mocked API tests.
- Google Calendar: the current installation lacks the OAuth client configuration and seller consent. Live free/busy, booking, move/cancel and revoked-consent checks need that account. Saved local meetings and ICS export remain independent of Google.
- Facebook/Craigslist use manual listing transfer and reply copying. No inbox connection, payment processor, fulfillment, returns or dispute synchronization is claimed.
- Internet coverage depends on accessible current source offers. Empty results, unavailable sources or unmatched physical-unit facts do not prove a sale value. Real demand forecasting still requires sufficient observed outcomes and its existing held-out validation gate.
- CI browser tests are supplied separately from the local browser review. Read the actual Actions result before treating the CI execution as passed.

## Local verification

See VALIDATION.md for current test results and the distinction between local deterministic tests, live AMD calls, local browser checks and unperformed external account operations. No diagnostic listings, fake sales or fixture prices are inserted into the actual workspace.

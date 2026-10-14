# Validation — October 14, 2026

## Completed checks

- Backend: 51 isolated tests passed. Coverage additionally confirms that unknown-model lookup is accepted, candidate offers remain separate from item valuation, a forged candidate cannot be applied, seller confirmation is required, photo lookup cannot read outside the media directory and recognition preserves edited descriptions.
- Frontend: TypeScript check and production build passed. Browser review confirmed the category selector, inventory category filter and category-relevant specification fields.
- English speech: the installed, checksum-verified local Whisper model accurately transcribed a diagnostic recording containing “Dell Latitude 5420”, “16 gigabytes”, “256 gigabyte”, included charger and an untested battery. Four seconds of silence produced no text.
- Live video: a real 54,112,118-byte MOV from the public upstream repository passed upload, decoding, English speech recognition and AMD MiMo-V2.6-Flash extraction in 37 seconds. Five private drafts were created: office chair (Furniture), energy drink can (Other), backpack (Accessory), cap (Clothing) and MacBook Pro (Laptop). Exact model identifiers remained unknown where they could not be established. This run used a separate validation database, not the seller's inventory.
- General commerce: an extracted furniture draft was reviewed and published in that isolated database, received a buyer offer and completed exactly once. Recorded revenue and fee-adjusted contribution matched the explicit diagnostic inputs. A repeated completion was rejected. No real payment or external marketplace action occurred.
- Streaming upload: a 12 MiB multipart request reached Flask through the frontend route and was correctly rejected as invalid media. No inventory or upload job was created by this diagnostic request. The real MOV above independently confirmed valid large-file ingestion.
- Existing seller upload: the saved Minecraft screen recording was reprocessed with AMD and local speech. Processing completed with zero products, correctly avoiding fictitious physical inventory from game objects.
- A subsequent seller upload completed with two observed product drafts in Electronics and Other. Unverified function, brand and model were flagged for review.
- Final automatic price-research check: 25 pages checked in 73 seconds; two current asking prices accepted from two independent merchants. The three-page threshold was not met, so no numeric recommendation or sale-speed forecast was published.
- Photo identification with Qwen3.8-Flash-Next correctly recognized the ambiguous suitcase record player and disassembled hard-drive components. The live unknown-model workflow renamed the unconfirmed draft to Portable Suitcase Record Player, classified it as Audio and discovered a source-backed Crosley resale candidate. The candidate remains explicitly unconfirmed, with no offer value or item valuation invented.

## Limits of these checks

The five-item capture validates multiple product categories, not recognition accuracy for every product or every recording. Poor lighting, unreadable labels and similar-looking objects still require seller review. These checks do not establish measured conversion uplift or market demand.

Live web verification has accepted actual current asking prices from independent US merchants. Search coverage varies, and some repeated runs find fewer usable pages. Automatic valuation remains unavailable unless the evidence threshold is satisfied. Neither a successful crawl nor a generated description proves that a transaction occurred.

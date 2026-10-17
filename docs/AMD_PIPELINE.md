# AMD execution and measured optimization

This is an AMD Token Factory application, not a claim that the seller's Windows computer contains an AMD GPU. Shared model inference runs at AMD; frame preparation, English faster-whisper CPU int8 transcription, SQLite and the numeric price engine run locally.

## Routing and scheduling

- Detailed vision prefers Qwen3.8-Flash-Next, with one compatible DeepSeek-V4.1-Flash fallback on timeout or 500/502/503. Explicit diagnostic model overrides never silently switch models. Actual models are recorded. HTTP 429 does not trigger model hopping because the quota belongs to the whole team.
- Ordinary chat/research reasoning prefers DeepSeek-V4-Flash. Short buyer-intent classification prefers MiniCPM5-2B, with a 256-token output ceiling. An explicit `AMD_INTENT_MODEL` can override it. Model IDs are checked against the live catalog; advertised input modalities are respected.
- Supported DeepSeek/MiMo models and Qwen3.8-Flash-Next use non-reasoning mode for these structured extraction tasks. Qwen3.8-27B retains its supported low-effort setting.
- At most two AMD requests are in flight, with at most one vision request. Starts are spaced by 3.2 seconds, below the documented shared 20 RPM gateway ceiling. A shared 429 cooldown honors Retry-After. The other computers on the team still consume the same quota.
- The scheduler lock protects start times, not the entire GPU response. A long vision call therefore does not itself monopolize all local inference capacity. Per-thread HTTP sessions reuse connections.
- Short intent work has an eight-second local queue/pacing budget and a bounded remaining read timeout; it falls back to recorded facts on busy/quota/network errors. Connection establishment can add overhead, so this is not an eight-second end-to-end SLA. Vision uses a 60-second read timeout and a single model fallback. HTTP read timeouts are not a hard total workflow deadline.

## Work removed rather than renamed

- Exact-model search starts from the saved identity/specifications. AMD refinement remains available when matching independent offers are insufficient. Similar-product query planning can still use AMD.
- Source limitations are generated from checked fields rather than sending the entire offer list to another model for decorative synthesis. No model supplies an accepted numeric price.
- Validated intent labels are cached in process for 15 minutes, bounded to 256 entries. The key binds the endpoint/API-key identity, actual model, prompt version and redacted question. No question text, price, inventory fact, negotiation decision or reply is stored in this cache. Every reply reads the item's current facts. Invalid classifications never enter the cache.
- The local keyword classifier protects explicit topics, so a small model cannot silently discard a clear battery or accessories question. Unreviewed/unavailable products do not spend a classification request at all.
- Intake frame decoding is reused by the worker. Image encoding decodes originals once across compression attempts. Only byte-identical repeated frames are omitted from inference; first/middle/last temporal anchors and every distinct selected view remain. All original sampled frames remain available for seller review.
- Numbered contact sheets were investigated but did not establish a reliable improvement on the current endpoint; they are NOT the default shipped input. Detailed individual frames are retained.

## Observations on October 17, 2026

These were isolated diagnostic runs, not sales records or a representative accuracy benchmark:

- Six English intent prompts were run once through MiniCPM5-2B and once through DeepSeek-V4-Flash. Both returned the exact expected label sets for all six. Either model also showed a long latency outlier; this does not establish general small-model speed superiority.
- A later combined question exposed a missed battery label in the small model. The prompt was tightened, explicit-topic protection was added and the follow-up returned both battery and included labels. Deterministic regression coverage protects the missed-topic case independently of live model behavior.
- Repeating one identical classification took 16 ms locally after a first call taking 4,234 ms including model discovery/pacing. The repeat made zero additional inference calls. This demonstrates reuse, not an isolated GPU speedup or a promise for different questions.
- A deliberate 12-identical-frame diagnostic retained three temporal anchors. Image-content JSON shrank from 582,384 to 145,596 bytes (75%). Real moving footage may have no identical frames and no such reduction. The diagnostic was never inserted into the seller's inventory.
- On one original frame, DeepSeek-V4.1-Flash recognized the portable record player and hard-drive components. MiniCPM-V-4.7-1B returned an overly generic device label and was not enabled as the default vision model.
- Complete live video extractions during this session encountered shared-endpoint timeouts and HTTP 500 responses. A later single-frame probe succeeded slowly. Full end-to-end video latency/quality improvement is therefore NOT claimed. Lower image size and contact sheets did not establish a reliable fix for provider availability.

## Product behavior during an outage

Original frames and local transcription remain saved. A seller can select a frame and create a clearly seller-entered draft without claiming AI recognition succeeded. The operation is idempotent, does not invent a model/price/working state, and does not change a failed AI job to completed. Completed captures also support adding a missed item. A capture with seller-added drafts cannot be retried into duplicate inventory.

The Research & AMD screen reports observed calls, reported tokens, cache reuses, workload medians and video stages. A configured key is distinct from a verified call for the current key. Diagnostics use temporary databases; no fake offers, sales, buyer activity or evaluation metrics are seeded into the working workspace.

Shared-endpoint availability is an external dependency. For a competition demo, verify the chosen models shortly before presenting and keep the saved-frame recovery route available. This is not evidence of a production SLA or measured revenue uplift.

# 0011: fulfillment follows captured intent and evidenced catalog offers

- Status: accepted target; cross-provider fulfillment and intent snapshots are planned
- Decided: 2026-10-03
- Scope: request policy, identity, collections, files and asset provenance

## Decision

Capture intent at enqueue: origin media/collection, identity policy, provider and
engine pins, quality/audio type, required codec/video constraints, assets,
metadata/organization policy, duplicate behavior and fallback permissions.
Defaults affect new requests. Retry retains the original intent unless explicitly
changed; Auto uses current readiness within that intent. Settings orders are
preferences; a per-operation selection pins its dimension. A provider pin still
allows Auto engine routing. Per-job Allow fallback explicitly relaxes a pin.
Same-provider execution recovery follows [ADR 0010](0010-provider-engine-runtime-boundary.md).

Three independent cross-provider policies default off:

- Choose the best available provider before execution.
- Recover failed fulfillment through another provider.
- Upgrade an existing Waves-owned Version through another provider.

Only high-confidence matches, ready providers and preserved constraints qualify.
Initial selection does not authorize replacement. Explicit provider disable or
sign-out never triggers substitution. Record every provider/engine change in
attempt history and concise notifications.

A catalog offer is a small comparison value: namespaced provider/catalog
identity, origin relationship, match evidence, capabilities, ownership/presence,
readiness and delivery evidence. It is not a universal persisted catalog.
Track matching uses ISRC with consistent artist/title, precise duration,
explicitness and version/remaster facts. Default recording equivalence can span
releases; stricter release/Edition matching is configurable. ISRC alone does not
prove the same master. Album matching combines UPC, release/Edition facts and
ordered track-list evidence; UPC alone is insufficient.

Resolution distinguishes high-confidence automatic eligibility, user-confirmed,
ambiguous and unresolved candidates. Contradictions block automatic selection.
Users may explicitly choose fuzzy/ambiguous candidates; confirmation does not
grant future automatic eligibility. Explain missing facts and competing
candidates. Identity confidence never substitutes for file verification.

Bound lookups to enabled capable providers and requested context. Isolate source
errors and stale results. Timestamp/cache evidence and invalidate it for relevant
identity, account/storefront, runtime/version or request-constraint changes.
Quality evidence and ranking belong to [ADR 0001](0001-one-quality-model.md).

Albums default to Whole release: one confidently matched Edition and ordered
track list from one provider. Engine recovery may finish remaining tracks.
Explicit Hybrid resolves the source-defined recordings across providers without
silently adding/removing bonus tracks or changing order. Unresolved entries stay
visible. A strict album failing after partial delivery holds for explicit retry,
conversion to Hybrid for unfinished entries, or restart on another matched
provider with replacement confirmation. Keep verified files until replacements
verify; partial albums are incomplete.

Playlists resolve source entries individually, preserving order and repeats.
Mixed-provider fulfillment is explicit. Resolved entries may proceed with an
incomplete result; an all-entries-must-resolve preflight is optional. Output is
files/local playlists, without provider account playlist writes. Artist
fulfillment takes an explicit bounded set of source releases and album policies,
reports missing releases and never substitutes another provider's entire catalog.
Apple artist-download requires implementation and qualification before exposure.

Descriptive metadata and organization default to origin, with a configurable
fulfillment policy. Fill missing facts only from consistent matches. Technical
codec/quality, actual catalog IDs and delivery provenance describe the delivered
file. Ownership remains per provider and Version; an equivalent Library file
does not establish ownership of every matching offer.

Bulk skips equivalent files satisfying the request. One batch policy chooses
Keep existing (default), Replace Waves-owned or Keep both. Automatic replacement
requires trustworthy Waves ownership and a verified improvement of the same
recording/audio type. Protect uncertain ownership and externally modified files.
Keeping a below-minimum file reports retained/skipped, not fulfilled. Keep both
uses readable provider/quality/type suffixes and collision counters. Shared path
templates gain optional provider/quality/audio-type tokens; mixed collections
retain source order and organization.

Artwork defaults to the original release; lyrics correspond to the delivered
recording. Explicit asset-source overrides are available. Cross-provider
enrichment is a separate off-by-default policy restricted to eligible offers;
timing conflicts block automatic attachment. Prefer rich original-language
timing, preserve raw timed lyrics and export configured formats. Optional
translations/pronunciation accompany original content. Preserve valid embed/
sidecar combinations, LRCLIB preferences, provider overrides and stored values;
raw TTML remains sidecar-only.

Missing optional assets completes with a warning by default. Require selected
extras holds completion until delivery. Standalone asset requests require the
asset; requested variants are never silently substituted.

## Why

A saved default can change while a collection waits in the queue. Capturing
intent preserves what the user asked for across retries and fallback. Catalog
evidence enables useful comparison without turning a weak match into an
unexplained substitution. Distinct selection, recovery and replacement policies
keep consent specific to the operation.

## Alternatives considered

- Always using the source provider prevents the approved offer comparison.
- One automatic-switch setting conflates initial selection with replacement.
- Universal fuzzy deduplication would silently merge different recordings.
- Treating equivalent Library presence as provider ownership invents provenance.

## Consequences

- Existing namespaced IDs, legacy bare-TIDAL reads, per-Version ownership and
  migration protections remain compatible. No new universal ID is required.
- Collection progress/attempt history must preserve source entry identity and
  verified finished work through recovery.
- The Chooser follows [ADR 0012](0012-composable-provider-surfaces.md); failures,
  substitutions and incomplete results follow [ADR 0013](0013-redacted-event-lifecycle.md).

# 0001: one quality model, per-provider mapping

- Status: accepted
- Decided: 2026-09-03 (issue #24, from the Apple Music provider spec §4.3, §9.2)
- Supersedes: the tidalapi `Quality` type as the app's shared quality vocabulary
- Amended: 2026-10-03; delivery evidence/ranking is accepted target, planned for offer routing

## Decision

Waves' audio quality is the Waves-owned four-rung ladder
`LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS` (`waves.constants.QualityTier`,
ranked 0..3 by `TIER_RANK`/`quality_rank`). Every shared path — the queue's
pinned quality, the ownership rank scale, session quality apply, the
per-provider settings — speaks the ladder (tier strings at the JSON/QML
edges); no engine quality type appears on a shared path. Each provider maps
its engine's codecs onto the rungs at its own boundary (TIDAL's map:
`config.tidal_quality_for_tier`). Audio type (stereo/Atmos) stays orthogonal:
never a rung (`providers.base.AudioType`).

The `quality_audio` setting split into `tidal_quality_audio` /
`apple_quality_audio`, serialized as the ladder's tier strings. One migration
carries the legacy value onto `tidal_quality_audio`; the legacy field is a
never-serialized carrier, so the migration is one-time by construction.

Keep catalog-advertised, manifest/probed, selected and verified delivered facts
separate. A service maximum is never an item's exact available quality. Enrich
tiers with codec/profile, sample rate, bit depth, bitrate and video facts where
known. Metadata/manifest probes are lazy and bounded to enabled ready providers
when Download With or opt-in routing needs them; timestamp/cache evidence and
show unknown/stale/checking states. Actual media diagnostics remain explicit.

Best available is the initial configurable mode within the selected audio
family. Lower lossless resolution can be accepted visibly; lossless-to-lossy or
stereo/Atmos changes require confirmation. Minimum required enforces the
requested tier/exact constraints. Auto never silently changes mix/codec family.

Filter by audio type and minimum constraints before ranking. Demonstrated
availability outranks theoretical ceilings. Comparable lossless offers rank bit
depth then sample rate; equal-resolution FLAC/ALAC are equivalent unless a codec
is required. Compare lossy bitrate only across comparable codecs/profiles. Video
ranks demonstrated resolution within selected codec/HDR/frame-rate constraints;
HDR is explicit. Provider priority breaks ties; retain origin absent an override
or evidence of improvement. Resolution does not prove better mastering.

Matching and request policy are owned by
[ADR 0011](0011-captured-fulfillment-intent.md), not quality rank.

## Why

tidalapi is the TIDAL engine's library, not the app's vocabulary: a second
provider must not inherit TIDAL's enum, and "which fidelity did we ask for"
must mean the same thing in the queue drawer, the ownership gate and the
settings store. The fold (`tier_from_word`) accepts every spelling a
config, a wire value or a UI word can carry, so old rows and hand-edited
configs keep working.

## Consequences

- Unknown or corrupt quality values rank -1 (below every real rung) and write
  nothing to sessions; they never crash a caller and never rank as LOW.
- The engine's internal use of tidalapi `Quality` (download.py) is codec
  vocabulary, not a shared path.
- Provider quality values retain their serialization and migration. Their
  placement follows [ADR 0012](0012-composable-provider-surfaces.md); a historical
  dropdown position is not a permanent product constraint.
- A delivery's verified codec/quality is not its identity confidence and does
  not replace the mandatory Apple integrity gate.

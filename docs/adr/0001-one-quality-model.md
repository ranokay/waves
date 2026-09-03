# 0001: one quality model, per-provider mapping

- Status: accepted
- Decided: 2026-09-03 (issue #24, from the Apple Music provider spec §4.3, §9.2)
- Supersedes: the tidalapi `Quality` type as the app's shared quality vocabulary

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
- The settings page's TIDAL dropdown keeps its wording and position; Apple's
  section (with `apple_quality_audio` surfaced) lands with the providers'
  settings area (issue #11).

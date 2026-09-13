# 0003: migration completion lives in a sidecar, recorded after the save

- Status: accepted
- Decided: 2026-09-13 (issue #128, audit item 15 / E12)
- Scope: the one-time steps in `waves/config.py`'s `_migrate_settings`

## Decision

A run-once settings migration runs only when neither its in-file marker nor a
sidecar beside settings.json (`settings-migrations.json`) says it already ran.
The sidecar lists step names; unknown names are carried through. It is written
only after the migrated settings are safely on disk: `Settings.__init__` runs
the steps with `record=False`, saves, and records only on a successful save.

Two kinds of step are deliberate exceptions:

- **The quality split is not in the sidecar.** Its carrier (`quality_audio`)
  is never serialized by the current model, so a carrier can only be present
  in a file a pre-split release wrote, and that file has no
  `tidal_quality_audio` for the fold to overwrite. Folding a reappearing
  carrier is the recovery of that setting, so it happens unconditionally.
- **Steps whose carrier is absent and whose destination already carries the
  post-migration default** still get recorded when their in-file marker says
  they ran, so an existing install seeds the sidecar on its first launch.

## Why

The in-file markers are fields an older release does not know, and that
release rewrites settings.json from its own model on every launch: a
downgrade strips them. On re-upgrade the step then replays over choices the
user made since — ReplayGain forced back on, per-provider lyrics/art mirrors
overwritten from stale shared values, a tuned rate-limit pace reset, the
retired Atmos carrier moving the default-audio dropdown back to "both". A
sidecar the older release never touches survives the round trip, and a
per-step name means adding a future migration cannot resurrect an old one.

Recording after the save closes the matching hole: a migration that lives
only in memory (the settings file was locked) must not be marked done, or the
next launch would skip it forever even though nothing was persisted.

## Consequences

- Adding a migration means appending its name to `_MIGRATION_STEPS` and
  guarding its work by that name.
- A sidecar from a newer build is preserved name-for-name across a code
  downgrade.
- A failed sidecar write only costs a repeat of an already-applied step's
  guards, never a crash; the in-file markers still cover installations that
  carry them.
- The sidecar is per config directory, beside settings.json, so sandboxed
  profiles and tests never touch a real install's state.

# 0006: first-run onboarding is one cancellable surface, answered once

- Status: accepted
- Decided: 2026-09-16 (issue #213, the onboarding spec; implemented across #215, #218, #219)
- Scope: the first-run welcome surface, its provider paths, the "Finish setup" chip, and the one key that remembers the answer

## Decision

First run opens **one welcome surface** built from the provider
descriptors: one card per provider, each stating what it enables, plus a
Skip. Every path out of it is cancellable and lands in a usable app.

- **TIDAL** is chosen into **inline sign-in steps on the same surface**: no
  full-window overlay, no automatic browser open, and Cancel/Escape returns
  to the cards with nothing kept. A completed sign-in answers the first run
  and lands on Search with the field focused.
- **Apple** is enabled by the choice (search and previews work immediately,
  before any setup) and the existing in-place wizard opens in Settings; its
  **SKIP FOR NOW** defers the remaining steps without undoing the choice.
- **Skip** answers the first run and leaves a dismissible **"Finish setup"**
  chip in the header while no provider can download yet. Settings →
  Providers → "Set up providers" re-opens the same surface as a normal page.

Persistence is **two keys** in the QML `Settings` store (category `setup`):
`firstRunAnswered` and the chip's `setupChipDismissed`. The legacy picker
bit is migrated by a **one-time shim inside that store**
(`migrateOnboarding()`): it seeds `firstRunAnswered` from the old
`providerPickerDone` and clears it. Everything else about the surface —
which mode it is on, whether a login URL arrived — is session state that
cancel discards.

## Why

- The audit's F-11 was a latching full-window login panel: starting a
  sign-in became a session-long commitment. Inline, cancellable steps make
  starting nothing of the sort.
- The persistence lives where the flag is read. The Python migration sidecar
  (ADR 0003) covers `settings.json` only and cannot migrate QML settings, so
  a shim in the QML store is the honest mechanism; a second state store
  would have meant two owners for one answer.
- An existing install must not be onboarded again: the shim seeds from the
  bit every prior release wrote, and the chip only appears while no
  provider can download yet.

## Alternatives considered

- **A Python-owned onboarding model persisted in `settings.json`**: would
  inherit the sidecar migration, but puts UI routing state in the engine's
  store and gives the same flag two homes (the surface reads it in QML).
- **A modal wizard that must be completed** (finish setup or quit): rejected
  in the design interview — Skip must land in a usable app, and every
  provider path must be escapable.
- **Auto-enabling a provider on Skip**: rejected (spec S9.2e); enabling is
  an explicit click, so a skip cannot surprise the user with catalog calls.
- **A second inline wizard for Apple**: rejected in favour of reusing the
  existing in-place wizard, so there is one place that owns setup actions.

## Consequences

- A future migration of these two QML keys needs the same shim treatment;
  the Python sidecar will not see them.
- The first run is answered at most once per install; re-entering the
  surface is always an explicit request (the chip, Settings, or an empty
  state's call to action).
- Onboarding behaviour is testable as a state machine on the rendered QML:
  fresh, either provider, cancel from each panel, skip, restart and the
  shim's one-time seed all run in the offscreen scenarios.
- The setup chip's test is "can any provider download yet", read from the
  live provider state (the session flag and the Apple light), so it retires
  itself the moment one can.

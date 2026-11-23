# 0006: first-run onboarding is one cancellable surface, answered once

- Status: accepted
- Decided: 2026-09-16 (issue #213, the onboarding spec; implemented across #215, #218, #219)
- Scope: first-run provider choice, answered-once persistence and requested setup
- Amended: 2026-10-03; Apple catalog-first and Providers entry points are accepted target, planned

## Decision

First run opens **one welcome surface** built from the provider
descriptors: one card per provider, each stating what it enables, plus a
Skip. Every path out of it is cancellable and lands in a usable app.

- **TIDAL** is chosen into **inline sign-in steps on the same surface**: no
  full-window overlay, no automatic browser open, and Cancel/Escape returns
  to the cards with nothing kept. A completed sign-in answers the first run
  and lands on Search with the field focused.
- **Apple** is enabled by the choice (search and previews work immediately,
  before download setup). Download setup is separate, on request or first need;
  choosing Apple does not automatically provision or open a download wizard.
  Recommended hides engine choice initially; specific engines are available
  under Advanced setup.
- **Skip** answers first run and activates/provisions nothing. Resume setup
  explicitly from Providers/Settings or a relevant empty state. Show catalog-ready
  separately from download-ready; unused optional setup is neutral.

Header setup presentation follows [ADR 0012](0012-composable-provider-surfaces.md),
replacing the mandatory Finish setup chip. Requested provisioning follows the
[Apple spec](../apple-music-provider-spec.md#2-one-time-setup-managed-and-user-supplied).

Existing persistence is **two keys** in the QML `Settings` store (category `setup`):
`firstRunAnswered` and the chip's `setupChipDismissed`. The legacy picker
bit is migrated by a **one-time shim inside that store**
(`migrateOnboarding()`): it seeds `firstRunAnswered` from the old
`providerPickerDone` and clears it. Everything else about the surface —
which mode it is on, whether a login URL arrived — is session state that
cancel discards.
Preserve the answered-once flag and migration when changing presentation; a
retired chip's stored dismissal must not re-onboard an existing install.

## Why

- A latching full-window login panel made starting a sign-in a session-long
  commitment. Inline, cancellable steps make starting nothing of the sort.
- The persistence lives where the flag is read. The Python migration sidecar
  (ADR 0003) covers `settings.json` only and cannot migrate QML settings, so
  a shim in the QML store is the honest mechanism; a second state store
  would have meant two owners for one answer.
- An existing install must not be onboarded again: the shim seeds from the
  bit prior releases wrote, independently of changes to setup presentation.

## Alternatives considered

- **A Python-owned onboarding model persisted in `settings.json`**: would
  inherit the sidecar migration, but puts UI routing state in the engine's
  store and gives the same flag two homes (the surface reads it in QML).
- **A modal wizard that must be completed** (finish setup or quit): rejected
  in the design interview — Skip must land in a usable app, and every
  provider path must be escapable.
- **Auto-enabling a provider on Skip**: rejected (spec S9.2e); enabling is
  an explicit click, so a skip cannot surprise the user with catalog calls.
- **Automatically opening Apple download setup on provider choice**: superseded
  by catalog-first activation and separately requested setup; a usable catalog
  does not require committing to an external runtime.

## Consequences

- A future migration of these two QML keys needs the same shim treatment;
  the Python sidecar will not see them.
- The first run is answered at most once per install; re-entering the
  surface is always an explicit request (Providers, Settings, or an empty
  state's call to action).
- Onboarding behaviour is testable as a state machine on the rendered QML:
  fresh, either provider, cancel from each panel, skip, restart and the
  shim's one-time seed all run in the offscreen scenarios.
- Providers readiness replaces the mandatory chip's download-only gate.
  Catalog access and requested download readiness are independently observable.

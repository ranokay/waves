# 0008: provider surfaces render from descriptors and capabilities

- Status: accepted
- Decided: 2026-09-16 (issue #213, the onboarding spec; the contract in #214, applied by #215–#223)
- Scope: every surface that lists providers or asks what a provider can do
- Amended: 2026-10-03; status/Browse presentation is superseded by ADR 0012

## Decision

A provider describes itself **once**, in a descriptor composed next to its
implementation (`ProviderDescriptor`: id, name, mark, one honest capability
line, its card's own action words, the Settings fields its card owns, and the
shape of live status it carries). What a provider _can do_ is its
`Capability` set, and its chooser metadata (the option ladder a download can
ask for) sits on the provider beside them. The bridge composes `status` and
`actions` at read time (the probes are the bridge's), and Apple's wizard steps are
bridge-built live data, so the descriptor stays static identity. Surfaces
render from the seam's metadata, and the bridge composes the live state on
top:

- welcome cards, Settings provider entries and one Providers attention surface;
- combined Browse's provider-owned sections and relevant setup/empty states;
- My Music's saved-shelf sources and their labels;
- the per-provider Settings sections and each provider's Chooser option
  ladder.

QML renders the list the bridge answers with and never branches on a
provider's identity. No capability is invented: a FAVORITES-less provider
contributes no account-saved shelf. Disabled providers appear in a separate
setup area rather than the enabled readiness list. Live data stays bridge-owned
because the probes are the bridge's to run; the descriptor is static identity
only.

[ADR 0012](0012-composable-provider-surfaces.md) owns the accepted status,
multi-provider Browse and other surface layouts; they are planned. This
supersedes per-provider header marks and hiding every disabled setup opportunity,
without changing static registration or the descriptor/live-state boundary.
Operation-specific readiness follows
[ADR 0010](0010-provider-engine-runtime-boundary.md).

## Why

- Hardcoded provider identities make every new provider require another
  tab, first-run branch and empty state across the bridge and QML.
- A descriptor next to the provider keeps the copy and the fields under
  review with the code they describe; a central registry would drift.
- The existing tests make the baseline promise falsifiable: a fake provider registered
  after the surfaces were written renders a card, a header mark and a saved
  section, and dispatches its actions with **zero QML edits**.

## Alternatives considered

- **Per-provider QML components and per-provider bridge branches**: rejected
  — it is the status quo the spec removes, and it makes every surface's test
  matrix grow with each provider.
- **A central provider registry/config file**: rejected — provider-specific
  copy and field lists would live away from the provider that owns them.
- **Dynamic plugin discovery**: not adopted; static registration is sufficient
  for the accepted target and keeps the seam simple.
- **Descriptor carrying live status**: rejected — the probes (a session, a
  runtime) are the bridge's, and a frozen descriptor cannot answer a live
  question; the bridge composes status at read time.

## Consequences

- Adding a provider is: implement the seam, return a descriptor, declare
  capabilities, register it where the providers are wired.
- Surfaces express absence honestly: no live readiness invented for disabled
  providers, no shelf for unsupported operations and no fabricated Browse feed.
  Setup opportunities are separate presentation, not a capability claim.
- The descriptor contract is versioned by its tests (both real providers plus
  a fake third); a new descriptor field must be rendered or explicitly
  answer-only.
- Live-status surfaces re-read on the flips that move them (a session, the
  Apple light) rather than caching a descriptor's snapshot.

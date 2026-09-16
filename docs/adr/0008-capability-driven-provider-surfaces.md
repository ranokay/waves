# 0008: provider surfaces render from descriptors and capabilities

- Status: accepted
- Decided: 2026-09-16 (issue #213, the onboarding spec; the contract in #214, applied by #215–#223)
- Scope: every surface that lists providers or asks what a provider can do

## Decision

A provider describes itself **once**, in a descriptor composed next to its
implementation (`ProviderDescriptor`: id, name, mark, one honest capability
line, its card's own action words, the Settings fields its card owns, and the
shape of live status it carries). What a provider _can do_ is its
`Capability` set. Surfaces render from those two, and the bridge composes the
live state (a session, a setup light) on top:

- the welcome cards, the Settings provider cards and the header's
  per-provider marks;
- Browse's availability (a browse-capable provider exists; hidden when none
  does; its session decides page vs sign-in call to action);
- My Music's saved-shelf sources and their labels;
- the per-provider Settings sections and each provider's Chooser option
  ladder.

QML renders the list the bridge answers with and never branches on a
provider's identity: the answer is empty/absent when a provider has nothing
to offer (a switched-off setup provider contributes no status; a
FAVORITES-less provider contributes no shelf). Live data stays bridge-owned
because the probes are the bridge's to run; the descriptor is static identity
only.

The migration is staged. Surfaces the audit found TIDAL-shaped — the
Chooser's enable gate, the search group header — move as their remediation
tickets land; the rule above is the destination and the bar for every new
surface.

## Why

- The audit's F-10 measured the cost of the alternative: every new provider
  meant another hardcoded tab, another first-run branch and another
  one-provider empty state, spread across the bridge and QML.
- A descriptor next to the provider keeps the copy and the fields under
  review with the code they describe; a central registry would drift.
- The paper tests make the promise falsifiable: a fake provider registered
  after the surfaces were written renders a card, a header mark and a saved
  section, and dispatches its actions with **zero QML edits**.

## Alternatives considered

- **Per-provider QML components and per-provider bridge branches**: rejected
  — it is the status quo the spec removes, and it makes every surface's test
  matrix grow with each provider.
- **A central provider registry/config file**: rejected — provider-specific
  copy and field lists would live away from the provider that owns them.
- **Dynamic plugin discovery**: rejected for v1 — two providers do not need
  it, and the descriptor seam is the part that must stay stable; discovery
  can land behind it later without changing a surface.
- **Descriptor carrying live status**: rejected — the probes (a session, a
  runtime) are the bridge's, and a frozen descriptor cannot answer a live
  question; the bridge composes status at read time.

## Consequences

- Adding a provider is: implement the seam, return a descriptor, declare
  capabilities, register it where the providers are wired.
- Surfaces must express absence honestly: no status row for a provider with
  no status, no shelf for a provider that cannot fill one, no Browse tab
  when nothing declares it.
- The descriptor contract is versioned by its tests (both real providers plus
  a fake third); a new descriptor field must be rendered or explicitly
  answer-only.
- Live-status surfaces re-read on the flips that move them (a session, the
  Apple light) rather than caching a descriptor's snapshot.

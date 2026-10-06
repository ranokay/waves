# 0012: shared surfaces compose capable providers and configurable sections

- Status: accepted target; redesigned surfaces and Settings are planned
- Decided: 2026-10-03
- Scope: Search, Browse, My Music, Chooser, Providers, queue and Settings
- Supersedes: ADR 0007's fixed layout/order/empty-state rules and ADR 0008's header/Browse presentation
- Amended: 2026-10-06; Chooser offer comparison implemented, other surface redesigns remain planned

## Decision

Keep Waves' dark CRT identity and useful provider-specific capabilities. Shared
screens render neutral descriptor/capability/live-state presentations, without
provider-identity branches or one screen per provider. A service contributes
only implemented and qualified operations
([ADR 0008](0008-capability-driven-provider-surfaces.md)).

Search defaults to All Providers, with configurable filters and remember-last.
Publish successful providers progressively without disturbing focus/selection;
retain useful stale results and isolate failed sources. Merge high-confidence
equivalents into one item exposing offers; uncertain items stay separate.
Available-provider icons are compact and accessible. Quality detail lives in
Download With; matching eligibility belongs to [ADR 0011](0011-captured-fulfillment-intent.md).

Browse combines provider-owned sections with source filters. Preserve editorial
order and provenance within each section; sections can reorder, hide and
collapse. Only validated Browse capabilities contribute. Actual fetch/drill/page
routing becomes neutral without inventing Apple feeds or removing TIDAL content.

My Music defaults to an All home with source filters for Library and available
account-saved providers, and vertically composable shelves. Library is initially
first; section order, visibility and collapse are configurable. Preserve local
Saved (Waves files, the initial Library view), All files (the scan), and provider
account-saved semantics. Compact setup prompts replace empty horizontal regions.
The surviving Library/provenance rules are in [ADR 0007](0007-my-music-information-architecture.md).

Download With remains the split-button's anchored Chooser. Stacked offer rows
show confidence, evidence, availability, ownership and readiness. The selected
offer expands delivery/asset options and relevant engine detail. Provider changes
preserve compatible explicit choices and explain/confirm incompatible changes.
Unpinned options use shared/provider defaults. Main Download uses saved policies,
origin by default. Preview stays independent, preserving valid service differences.
Use the existing intentional lyrics/art icons with labels in menus/Chooser;
compact toolbar icons carry tooltips, accessible names and keyboard access.

The Chooser keeps one guarded request snapshot. Compatible explicit options
survive provider changes; incompatible changes are proposed and confirmed before
the old choices are replaced. Engine pins include their provider owner. Separate
provider/engine fallback controls relax only that dimension within saved policies.
Unresolved alternatives explain missing evidence. Origin identity survives enqueue
independently of fulfillment identity; automatic execution/recovery is a separate
consumer. The bridge contract and current owners are documented in
[BRIDGE.md](../../waves/desktop/BRIDGE.md).

One Providers button replaces header marks, with a compact attention count.
Enabled providers expose catalog/account/download readiness, relevant engines
and setup/reconnect actions. Disabled providers have a separate setup area and
relevant empty-state opportunities. Mask account identity or use an alias; fuller
details belong in Settings. Missing unused optional setup produces no unhealthy
badge. Readiness is defined in [ADR 0010](0010-provider-engine-runtime-boundary.md).

Queue rows retain compact provider identity and expandable engine/attempt
history. Fallback explains what changed and why without engine badges on every
catalog row. A configurable neutral activity line shows work or Idle; account
status belongs in Providers, feedback in notifications. Remove duplicate
TIDAL-only global sign-in chrome while keeping provider-specific account views.

Settings has General, Providers, Downloads, Library, Lyrics & Artwork, Interface,
Notifications, Advanced and Diagnostics. Shared behavior appears once; accounts,
provider download overrides, engines and runtime belong under the provider.
Reuse one schema and the staged edit/Apply/Cancel lifecycle. Preserve existing
stored values and [ADR 0003](0003-migration-sidecar.md) downgrade safeguards.

- Normal settings expose provider priorities/per-operation defaults, Auto
  policies, engine preferences, delivery constraints, metadata/duplicate/assets,
  source defaults, remember-last, section order/visibility, density, motion/art
  effects, notifications and activity visibility. On-screen rearrangement writes
  the same persisted settings.
- Advanced groups endpoints, retry limits, timeouts, health polling, pacing and
  parallelism by owner. Provider-specific pacing moves here; shared video
  preferences belong in Downloads. Preserve legacy values.
- Diagnostics owns explicit media/status probes, temporary detailed capture and
  redacted export. Mandatory privacy and integrity cannot be disabled.

Onboarding's answered-once/cancel/skip/catalog-first contract belongs to
[ADR 0006](0006-onboarding-state-machine.md). Notification presentation and
retention belong to [ADR 0013](0013-redacted-event-lifecycle.md).

## Why

Fixed provider groups, header dots and wide account regions scale with provider
count instead of user needs. Composable sections and one status entry preserve
provenance without requiring a new screen design for every service. Ownership
of settings is clearer when shared rules appear once and execution details stay
with their provider.

## Alternatives considered

- Fixed Library-first layout and per-provider header dots do not scale.
- Provider-specific screen copies duplicate shared behavior and accessibility.
- Removing legitimate service differences to create symmetry loses capabilities.
- Exposing all tuning controls together makes normal setup harder to understand.

## Consequences

- This replaces target layout rules, not a claim that the current QML implements
  them. Migrate views in cohesive slices and retain existing state/values.
- Offscreen/process tests prove state and composed lifecycle. Native bundle runs
  own font/chrome/hover/DPI/menu claims, including window sizes/aspects,
  keyboard/focus/popover/tooltips, long names, many providers and partial/offline/
  fallback states. Keep their evidence in the owning issue/PR.
- Future providers implement/register the seam without redesigning core screens;
  no imaginary provider or generic global manager is required.

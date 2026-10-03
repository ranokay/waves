# 0010: engines execute beneath providers through explicit runtime boundaries

- Status: accepted target; multiple-engine routing and qualification are planned
- Decided: 2026-10-03
- Scope: provider execution, readiness, runtime lifecycle and capability release gates

## Decision

A Provider owns its service, account and catalog. Its descriptor and declared
capabilities remain static; live readiness is composed separately
([ADR 0008](0008-capability-driven-provider-surfaces.md)). Shared application
entry points remain provider catalog methods and download adapters. Engines
execute beneath their provider, without creating multiple Apple providers or
dynamic plugin discovery.

An engine exposes stable identity, supported operations and delivery constraints,
effective readiness, compatible versions, execution/cancellation and classified
failures. Engine protocols and dependencies stay in the provider domain. Shared
QML consumes neutral bridge presentations; provider/engine code never imports Qt.
Apple starts with the existing gamdl adapter and one qualified lite/Temari
adapter. A third client requires demonstrated additional benefit. Neither a
README feature list nor existing integration makes an engine Recommended.

Runtime identifies a built-in client, Waves-managed external resource or
user-managed endpoint. Engines may share a runtime/account failure boundary;
changing clients against the same failed wrapper is not independent recovery.
One active Apple account/storefront is the logical context, but engine sessions
are not interchangeable. Verify consistency, or require confirmation before
admitting an unverifiable account to automatic routing. Explicit account or
storefront changes invalidate affected evidence.

Readiness separates enabled state, catalog access, authentication, runtime
connectivity, protocol compatibility and requested operation/delivery capability.
Reachability does not prove entitlement or decryption. Cookies-only operations
can be ready while wrapper-dependent operations are unavailable. Missing unused
optional setup is neutral; requesting it gives an actionable setup state.
Background probes are bounded status/metadata checks. A media/decryption
diagnostic is an explicit user action.

Normal preferences provide Auto/Recommended and engine order, with justified
operation-specific preferences. Request pins and cross-provider policies are
owned by [ADR 0011](0011-captured-fulfillment-intent.md). Same-provider engine
fallback defaults on for Auto requests, preserving the same catalog item and
delivery constraints:

| Failure                                           | Recovery                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Engine/runtime-local connection or worker failure | Bounded recovery, then a ready compatible engine                                      |
| Authentication expiry or 2FA                      | Hold for account action; do not cycle engines                                         |
| Rate limit                                        | Honor backoff; switch only for a demonstrated engine-local limit                      |
| Delivery unavailable in an engine                 | Another engine may meet the same constraints                                          |
| Confirmed provider-level item refusal             | Terminal for that provider; separate cross-provider policy applies                    |
| Integrity failure                                 | Quarantine; bounded recovery or independent-engine fallback; verify every replacement |
| Protocol incompatibility                          | Mark engine unavailable; a compatible ready alternative may serve the request         |
| Uncertain account or rate-limit scope             | Conservative hold/backoff                                                             |

Attempts are bounded, visible and cancellable. Cancel applies to the logical job
and all attempts. Late or cancelled attempts cannot publish success or commit
output. Reuse verified finished entries; resume partial bytes only when identity,
manifest and range semantics are compatible, otherwise restart the unfinished
attempt. Preserve mandatory pre-placement Apple verification.

Deliberate engine Stop holds pinned jobs; Auto jobs may use another ready engine
under their policy. Waves never automatically restarts an intentionally stopped
runtime. Disconnect a user-managed endpoint without terminating the user's
service. Provider disable/sign-out is the distinct stop boundary in
[ADR 0002](0002-disabled-provider-stops-its-queue.md). Runtime update/distribution
requirements live in the [Apple spec](../apple-music-provider-spec.md#10-packaging-and-distribution-constraints).

Each new capability releases across all eight builds together: macOS Intel and
Apple silicon, both macOS 12 legacy variants, Linux x64/arm64 and Windows
x64/arm64. Qualify host client, guest/runtime, packaged behavior, account/session
and delivered media separately. Builds or emulation alone do not establish
native parity. Expand the common validated capability set in stages. Apple
Browse, account-saved, artist-download and video surfaces remain planned until
implemented and qualified. Candidate qualification and release evidence belong
in their issues/releases, not this decision record.

## Why

Service identity is stable while execution methods differ. A subordinate engine
seam permits useful operation routing without spreading implementation identity
through screens. Explicit shared failure boundaries prevent futile fallback,
and separate readiness facts avoid treating a reachable wrapper as a working
download account.

## Alternatives considered

- One Apple provider per engine duplicates catalog/account identity and UI.
- A single permanent engine winner prevents routing demonstrated capability
  differences; a general orchestration/plugin framework adds unused machinery.
- Platform-specific capability releases violate the accepted parity requirement.

## Consequences

- The current gamdl route remains the comparison baseline. Managed defaults and
  secondary adapters require whole-stack distribution/security eligibility and
  live qualification; this ADR grants no qualification result.
- Execution ownership must cover attempt completion, cancellation, session
  changes and staged placement, while retaining existing thread/generation rules.
- Failure classification belongs to the operation owner. Presentation and
  redaction follow [ADR 0013](0013-redacted-event-lifecycle.md).

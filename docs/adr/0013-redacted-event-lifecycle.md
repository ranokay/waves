# 0013: structured events are redacted before presentation and retention

- Status: accepted; structured event boundary implemented; notification center planned
- Decided: 2026-10-03
- Scope: application events, actionable notifications, history and diagnostics

## Decision

Use a small typed event/error contract: stable code, severity/domain, safe title/
summary, optional expanded context/diagnostics, provider/engine/job/media
references, retryability, lifecycle/dedup key and allowlisted actions. Subsystem
owners classify failures; exceptions are diagnostic input, never default UI copy.
Keep the Qt boundary in desktop composition without a global subsystem manager.

The event contract is Qt-free. Desktop composition owns queued delivery and the
active action index. Owners provide applicability guards, checked on the GUI
thread at delivery and again at action dispatch. Terminal lifecycle updates
remove recovery actions. Persistent history, toast timing and notification
preferences remain planned notification-center behavior.

Catalog owners pair failures with successful results using the same operation
key and provider generation. Merely starting work, completing a different
request or signing in through a different credential path does not resolve the
original issue. Wrapper sign-in keeps fixed user-facing error copy and redacted
diagnostics, and resolves its own event only after sign-in completes.

Redact before display, storage and copy, including credentials, tokens, cookies,
private paths and sensitive arbitrary values. Safe structured context does not
authorize raw exception/URL/request dumps. Details explain the likely cause,
attempted recovery and useful actions such as Retry, Reconnect or Open Settings.
Normal copy uses plain language; Advanced can reveal redacted protocol/trace
detail. Copy diagnostics stays redacted. Report issue opens a reviewable prefilled
draft; the user submits it.

Repeated connectivity/runtime events update one notice by lifecycle/dedup key.
Group nearby completions into one logical job/batch notice; one concise fallback
notice per job carries track/attempt detail underneath. Completion toasts can be
disabled without losing actionable errors or owning job/provider state.

Success/info lasts four seconds, warnings eight seconds. Actionable errors remain
until dismissed or resolved. Pause dismissal on hover or keyboard focus, never
steal focus, show at most three notices and retain overflow in the center.
Respect keyboard navigation, screen readers and reduced motion.

The persistent center initially retains up to 200 resolved events or seven days,
whichever expires first; these limits are configurable. Active issues remain
discoverable through their owning provider/job until resolved or dismissed.
Owner state and event lifecycle must agree when recovery succeeds, a job ends,
an account changes or an action is no longer applicable.

## Why

Strings emitted independently by subsystems lose identity, recovery context and
privacy guarantees. A small shared contract can deduplicate a recurring outage,
keep default feedback concise and make expanded actions useful without becoming
an enterprise logging framework. Redacting only at copy time would already have
leaked sensitive values through the UI or persistent history.

## Alternatives considered

- Raw exception toasts expose implementation details and sensitive values.
- Transient-only errors disappear before the user can take action.
- A toast per track/attempt overwhelms collection feedback.
- Automatically submitting reports bypasses the user's review of diagnostics.

## Consequences

- Queue, provider, runtime, connectivity, integrity, update, library and config
  owners emit classified events. Existing log privacy remains mandatory.
- Event schema/redaction/lifecycle tests own data guarantees; QML tests own
  timeout, focus, expansion and accessibility behavior. A center is a bounded
  product history, not a second log store.
- Surface placement follows [ADR 0012](0012-composable-provider-surfaces.md);
  fallback classification follows [ADR 0010](0010-provider-engine-runtime-boundary.md).

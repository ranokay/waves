# 0002: disabling a provider stops its queue

- Status: accepted
- Decided: 2026-09-13 (issue #126, audit item 14 / J5, J8)
- Scope: the provider enable switches (today only Apple Music's `apple_enabled`)

## Decision

Turning a provider off stops that provider's queued and running downloads.
The rows are not dropped: they settle in the queue's Stopped section carrying
the reason ("Apple Music was disabled"), so RETRY / RETRY ALL re-queues them
after the provider is switched back on. Work belonging to other providers,
and work of other providers held for the download folder to return, is
untouched; the disabled provider's own held replays are dropped with its
rows. The save's status line reports how many rows stopped.

## Why

The switch reads as "stop using this provider". Leaving its downloads
running behind a search group and badges that have already vanished is the
misleading state the audit recorded (J3, J5): the interface says the provider
is gone while bytes keep coming. Stopping is also the honest sequel to
sign-out, which clears the credentials those queued jobs would need.

Keeping the rows in Stopped (the STOP button's own shape) preserves
everything the user asked for: nothing is lost, and one click restores it.
The alternative — leave the work running and mark the rows as continuing —
keeps the contradiction, and a queued job can run for a long time.

## Alternatives considered

- **Mark, keep running.** Rejected: the provider reads as gone while its
  fetches continue, and the rows outlive the account they were queued under.
- **Ask at disable time (stop or keep).** Rejected: an extra decision on a
  switch flip; RETRY ALL already covers the user who disabled by mistake.
- **Stop only queued rows, let the running one finish.** Rejected for
  consistency: the running item is the one whose progress the user is
  watching, and a half-album that stops with a recoverable row is less
  confusing than a provider that ends work some time after being turned off.
  (RETRY resumes at the skipped tracks, so the already-landed files stay.)

## Consequences

- A running item stops mid-run; its partial files remain, and RETRY skips
  what already landed.
- The Stopped rows carry a reason now; the drawer shows a stopped row's
  reason instead of a bare "Stopped".
- Process STOP still stops every provider, and still clears the presentation
  reasons it supersedes; only the provider-scoped stop writes one.

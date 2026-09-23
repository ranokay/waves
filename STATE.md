# Waves state

Audited revision: a2a13cd (2026-09-21). The full snapshot is [AUDIT.md](AUDIT.md).
It never changes; GitHub issues own current status.

## Kickoff

Run this to see the frontier, oldest round first:

    gh issue list --repo ranokay/waves --search 'is:open label:ready-for-agent no:assignee sort:created-asc'

Claim the first issue whose blocked-by edges are closed, then follow
docs/agents/implementation-workflow.md: branch off develop, focused tests,
`mise run check`, `mise run test-strict`, OpenCodeReview, `/code-review`, PR to
develop, squash merge, close the issue, delete the branch.

If the list is empty, run triage on AUDIT.md and file only the next priority's
work (the audit's issue filing protocol).

## Human decisions

Nothing here blocks the filed issues. Still open for its priority round:
tooling policy (cua-driver scope, graph freshness, global AGENTS.md cleanup,
TOOL-02, TOOL-03, TOOL-05).

## Review corrections

- Approve the ARCH-01 and ARCH-03 ownership designs early and land the ARCH-02
  compatibility guard before any extraction. Run the queue pilot after the
  priority 1 correctness fixes; priority 5 in the audit is too late for the
  design work.
- The ADR and evidence deletion is settled: the files are restored and the
  guards are green. Trim stale docs through normal triage.

## Ledger

Do not create PROGRESS.md or any other status file. Issues, pull requests and
CI runs record progress; this file only points at the frontier.

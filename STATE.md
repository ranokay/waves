# Waves state

Audited revision: a2a13cd (2026-09-21). The full snapshot is [AUDIT.md](AUDIT.md).
It never changes; GitHub issues own current status.

## Kickoff

Run this to see the frontier:

    gh issue list --repo ranokay/waves --search 'is:open label:ready-for-agent no:assignee'

Claim the first issue whose blocked-by edges are closed, then follow
docs/agents/implementation-workflow.md: branch off develop, focused tests,
`mise run check`, `mise run test-strict`, OpenCodeReview, `/code-review`, PR to
develop, squash merge, close the issue, delete the branch.

The tracker has no ready-for-agent issues yet, so run triage on AUDIT.md first
and file only priority 0 and priority 1 work (the audit's issue filing
protocol).

## Human decisions

Settle these during triage. The audit's open questions carry the detail.

1. Release publisher: upstream iamprivacy/Waves, or this fork. Decide this
   first; choosing upstream turns most BUILD findings into documentation
   instead of work. (BUILD-02, BUILD-04)
2. Windows legs: dispatch only=windows-x64,windows-arm64 on the current
   recipe, or ship a six-leg release. (BUILD-01)
3. Wrapper image: publish a replacement tag from the current pipeline, or
   record a legal exception for 0.2.3. (DEP-01)
4. Python 3.14: drop the classifier, or take Nuitka 4.x and its AGPL build
   tool license. (DEP-03)
5. Tooling policy: cua-driver scope, graph freshness, global AGENTS.md
   cleanup. (TOOL-02, TOOL-03, TOOL-05)

## Review corrections

- Approve the ARCH-01 and ARCH-03 ownership designs early and land the ARCH-02
  compatibility guard before any extraction. Run the queue pilot after the
  priority 1 correctness fixes. Priority 5 is too late for the design work.
- The ADR and evidence deletion is settled: the files were restored on
  2026-09-23 and the guards are green. Trim stale docs (for example
  docs/research/provider-seam-analysis.md) through normal triage.
- Triage should also file one package-wide dead-code sweep. The audit does
  not carry this item.

## Ledger

Do not create PROGRESS.md or any other status file. Issues, pull requests and
CI runs record progress; this file only points at the frontier.

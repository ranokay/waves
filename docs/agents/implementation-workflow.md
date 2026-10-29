# Implementation workflow

How an agent turns an issue into merged code in this repo. `/implement` reads this; the fork topology is the reason the rules look the way they do.

## Branch topology

This repo is a fork: `upstream` is the parent project, `origin` is the fork.

- **`main` mirrors upstream.** It takes fast-forwards from upstream and nothing else. No direct commits, no PRs.
- **`develop` is this fork's integration branch.** Every PR lands here, and only here. PRs base on `develop`, never `main`.
- **One branch per issue**, cut from up-to-date `develop`, named `<type>/issue-<n>-<slug>` (for example `feat/issue-23-generic-tag-family`; the type is the work's own: `feat`, `fix`, `spec`).

The branch guard is commit-only. A conflicted upstream synchronization merge concludes with `HK_SKIP_STEPS=no-commit-to-branch git commit`.

## The loop

1. **Pre-flight.** Run `/sync-upstream` and settle every reconcile verdict before starting. Upstream changes are judged against our implementations and our open and closed issues and PRs before new work begins.
2. **Choose the gate class.** Use the matrix below. It decides the tests and review the change needs.
3. **Implement.** Add the focused tests for what you touch. A bug fix adds a test that fails on the base revision and passes at the head. If no safe deterministic regression exists, state the limitation in the PR.
4. **Format, then check.** Run `mise run fmt`, review its diff, then `mise run check`. `check` and commit hooks are read-only.
5. **Review.** Get the reviewer count below. Every finding is fixed or explicitly refuted, with the disposition in the PR.
6. **Gate.** Run the class's gate once on the final SHA. A code correction after the gate reruns the class gate. A prose-only correction may record the delta instead.
7. **Open the PR.** Base it on `develop`, link the issue with `Closes #<n>`, and follow `.github/pull_request_template.md`.
8. **Merge.** Use the verification path below. A finding that arrives after merge becomes a separate corrective PR; it never rewrites merged history.
9. **Close out.** The PR's `Closes #<n>` auto-closes the issue. Tick its box in the parent map; `mise run frontier` reports drift.
10. **Clean up.** Delete the issue branch and any worktree this run created. Leave branches and worktrees that other sessions own.

## Gate matrix

This section owns the gate policy. Other docs link here instead of repeating it.

| Change class      | Examples                                                                                   | Before the PR                                                       |
| ----------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| Prose             | Docs, comments, docstrings without code                                                    | `mise run check`, plus the packaging guard when one covers the file |
| Isolated logic    | Pure domain rules with no UI, process, persistence or provider surface                     | `mise run check`, `mise run test-fast`, and focused tests           |
| Full gate         | UI, public contracts, persistence, providers, downloads, dependencies, or uncertain impact | `mise run check` and `mise run test-strict` on the final SHA        |
| Release or native | Build, packaging, signing, updater, wrapper, platform claims                               | Full gate plus the build, native or live evidence the claim needs   |

Dependency changes are full-gate. A docs or config policy cleanup is prose class unless it changes runtime behavior.

## Review

This section owns the reviewer count.

- **One independent reviewer** for every substantive code change, including isolated logic. The review covers standards, the issue requirements (the spec), and correctness as one checklist.
- **Two independent reviewers** for data loss, security, authentication and updater changes. The second review targets the named risk.
- **No independent code reviewer** for prose or docs and config policy cleanup. Supervisor or maintainer review is enough.
- Automated CodeQL and SonarCloud remain advisory security and quality scans. They are not reviewers.
- Do not request CodeRabbit routinely. A high-risk change may use one additional reviewer, bot or human, when the named risk justifies it.
- The shared `/code-review` skill starts two subagents for Standards and Spec. It has no correctness agent. Waves uses one reviewer with all three topics; invoking the shared two-agent review as the gate would spend two reviewers and does not match this policy.
- A behavior-changing correction after review gets a focused re-review of the delta. A prose or formatting correction does not.

## Merge verification

The full-gate and light paths are deliberately different. Do not fabricate a receipt or use the full-gate tool for a light change.

**Full gate.** Collect a `mise run check` receipt and a `mise run test-strict` receipt on the same head, plus one review receipt with standards, spec and correctness complete and no unresolved findings. Use the existing `merge_preflight.py` only with those receipts. It hardcodes both gate commands and all three review topics.

**Light path.** For prose and isolated-logic changes, record the `mise run check` exit, the `test-fast` and focused-test exits where they apply, and the reviewer where the change is substantive code. Verify the PR head, base, mergeability and check rollup with `gh pr view --json headRefOid,baseRefName,mergeable,mergeStateStatus,statusCheckRollup`, then merge with `gh pr merge --squash --match-head-commit <head>`. Do not create a strict receipt and do not call `merge_preflight.py`.

A docs or config policy cleanup uses the light path with supervisor review. It does not claim independent code review.

## Waiting on long commands

A command that runs for minutes (`mise run test-strict`, a build) starts once in the background, and the harness reports its exit. Do other work or wait for that report.

## Evidence and session state

Keep implementation evidence in the owning issue or PR: findings, screenshots, benchmark results, investigation notes and completion reports. Record exact commands, the tested head, exits and counts. No raw logs and no linked logs.

Session state and handoffs live in the agent's private context, not the checkout. Do not create routine `.scratch` artifacts. Promote only current rules, contracts or supported workflows into maintained documentation.

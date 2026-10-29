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

| Change class      | Examples                                                                                   | Before the PR                                                     |
| ----------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| Prose             | Docs, comments, docstrings without code                                                    | `mise run check` plus the prose checks below                      |
| Isolated logic    | Pure domain rules with no UI, process, persistence or provider surface                     | `mise run check`, `mise run test-fast`, and focused tests         |
| Full gate         | UI, public contracts, persistence, providers, downloads, dependencies, or uncertain impact | `mise run check` and `mise run test-strict` on the final SHA      |
| Release or native | Build, packaging, signing, updater, wrapper, platform claims                               | Full gate plus the build, native or live evidence the claim needs |

Prose checks: run the packaging guard when one covers the file; run the source-pin test when it reads the edited function or file (for example the wipe guards in `tests/ui/test_factory_reset.py` and the source assertions in `tests/downloads/test_login_token_persist_listener.py`); run the applicable doctest command when the edit adds or edits `>>>`. The normal suite tasks do not collect doctests.

Dependency changes are full-gate. The light exception covers documentation and the removal of a non-executable obsolete tool's metadata or schema, including its schema-only guard test. Executable CI, build, test-collection, gate or security configuration is full-gate, even when it looks like cleanup. Uncertain impact is full-gate.

## Review

This section owns the reviewer count.

- **One independent reviewer** for every substantive code change, including isolated logic. The review covers standards, the issue requirements (the spec), and correctness as one checklist.
- **Two independent reviewers** for data loss, security, authentication and updater changes. The second review targets the named risk, and the PR body names that reviewer and the risk. The full-gate helper validates the three review topics, not the reviewer count.
- **No independent code reviewer** for prose or docs and config policy cleanup. Supervisor or maintainer review is enough.
- Automated CodeQL and SonarCloud remain advisory security and quality scans. They are not reviewers.
- Do not request CodeRabbit routinely. A high-risk change may use one additional reviewer, bot or human, when the named risk justifies it.
- The shared `/code-review` skill starts two subagents for Standards and Spec. It has no correctness agent. Waves uses one reviewer with all three topics; invoking the shared two-agent review as the gate would spend two reviewers and does not match this policy.
- A behavior-changing correction after review gets a focused re-review of the delta. A prose or formatting correction does not.

## Merge verification

Both paths verify the live PR before merging. The head must equal the reviewed and tested head, the base must be `develop`, the PR must be open and not a draft, GitHub must report acceptable mergeability, and every posted review or scan finding must have a written fix, refutation or disposition. A failed advisory check needs a written disposition. A pending, skipped or empty review is recorded as incomplete, never claimed as coverage. Do not request routine bot reviews and do not wait for a bot quota.

The full-gate and light paths are deliberately different. Do not fabricate a receipt or use the full-gate tool for a light change.

**Full gate.** Collect a `mise run check` receipt and a `mise run test-strict` receipt on the same head, plus one review receipt with standards, spec and correctness complete and no unresolved findings. Use the existing `merge_preflight.py` only with those receipts. It hardcodes both gate commands and all three review topics, and it checks the live PR head, base and mergeability. For a high-risk change, the PR body names the second reviewer and the named risk; the helper does not validate that count.

**Light path.** For prose and isolated-logic changes, record the `mise run check` exit, the `test-fast` and focused-test exits where they apply, and the reviewer where the change is substantive code. Verify with `gh pr view <pr> --repo ranokay/waves --json state,isDraft,baseRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup`. Require `OPEN`, `isDraft: false`, base `develop`, head equal to the reviewed and tested head, `mergeable: MERGEABLE`, and `mergeStateStatus` in `CLEAN`, `UNSTABLE` or `HAS_HOOKS`. Then merge with `gh pr merge <pr> --repo ranokay/waves --squash --match-head-commit <head>`. Do not create a strict receipt and do not call `merge_preflight.py`.

A docs or config policy cleanup uses the light path with supervisor review. It does not claim independent code review.

## Waiting on long commands

A command that runs for minutes (`mise run test-strict`, a build) starts once in the background, and the harness reports its exit. Do other work or wait for that report.

## Evidence and session state

Keep implementation evidence in the owning issue or PR: findings, screenshots, benchmark results, investigation notes and completion reports. Record exact commands, the tested head, exits and counts. No raw logs and no linked logs.

Session state and handoffs live in the agent's private context, not the checkout. Do not create routine `.scratch` artifacts. Promote only current rules, contracts or supported workflows into maintained documentation.

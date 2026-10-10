# Implementation workflow

How an agent turns an issue into merged code in this repo. `/implement` reads this; the fork topology is the reason the rules look the way they do.

## Branch topology

This repo is a fork: `upstream` is the parent project, `origin` is the fork.

- **`main` mirrors upstream.** It takes fast-forwards from upstream and nothing else — no direct commits, no PRs.
- **`develop` is this fork's integration branch.** Every PR lands here, and only here. PRs base on `develop`, never `main`.
- **One branch per issue**, cut from up-to-date `develop`, named `<type>/issue-<n>-<slug>` (e.g. `feat/issue-23-generic-tag-family`; the type is the work's own — `feat`, `fix`, `spec`).

The branch guard is commit-only. A conflicted upstream synchronization merge
concludes with `HK_SKIP_STEPS=no-commit-to-branch git commit`; use hk's step
skip variable for that authorised exception.

## The loop

1. **Pre-flight**: run `/sync-upstream` and settle every reconcile verdict before starting — upstream changes are judged against our implementations and our open/closed issues and PRs before any new work begins.
2. **Implement** with the focused tests for what you touch. The strict group is the final gate, not a per-edit ritual: it runs once, on the frozen SHA, after the reviews (see Test scope).
3. **`mise run fmt`, then `mise run check`**, so the reviewers read the text that ships. `check` and commit hooks are read-only; formatting failures require an explicit `fmt` and review of its diff.
4. **`/code-review`** against `develop`, with the issue as the spec. Its three axes are the review gate: standards ([coding standards](../../CODING_STANDARDS.md), which bind the per-path house rules), spec, and correctness (the defect classes in the standards' Correctness section). Every finding fixed or explicitly refuted, dispositions recorded in the commit/PR. A non-trivial fix delta gets its own `/code-review`, and each correction commit runs `mise run test-fast` first: the fast group carries the cheap guards (Qt markers, BRIDGE rows, doc pins) that must not cost a reviewer round. No strict run happens between review rounds.
5. **Local gate on the frozen SHA**: `mise run check` plus `mise run test-strict`, the merge gate in `DEVELOPER.md`'s test-group table (it excludes the live account tests, which never run in CI, and it runs alone). A fix commit after this run invalidates the tested SHA, so this is the last write before the PR.
6. **PR → `develop`**, body linking the issue (`Closes #<n>`, which closes it on merge: `develop` is the default branch). Then comment `@coderabbitai review` on the PR, because CodeRabbit reviews only when asked. Read the checks and bot reviews before the merge; none of them gates it. CodeQL and SonarCloud scan every PR automatically; the test suite runs only through the local gate or a manual `master.yml` dispatch. A failed check is a finding like any review finding, fixed or refuted in the PR body before the merge. CodeRabbit, Codex, Greptile and every other review bot are advisory, and each bot finding gets the same disposition. When a bot is out of quota, skips, fails or has not answered by the merge, the PR body records that and the delivery continues. Only a completed review counts as bot review coverage; a green bot check does not. A fix after the PR opens goes back through step 4's review rule and step 5's gate on the new head; a prose-only fix may record the delta instead (see Test scope). The merge stands on the local gate (`mise run check`: lock drift, qmllint, ty, ruff lint + format, prettier and deptry; the strict test group; the review above), and the PR body says so, with the tested SHA. A finding that arrives after merge becomes a separate corrective PR that never rewrites the merged history and goes through the same gate.
7. **Squash-merge** into `develop`.
8. **Close out the issue**: the PR body's `Closes #<n>` auto-closes it on the squash. Close explicitly (`gh issue close <n>` with a one-line delivery note) only when the auto-close did not fire. Tick the issue's box in its parent map's checklist; `mise run frontier` reports any box that disagrees with the tracker.
9. **Clean up the branch.** GitHub deletes the remote head branch when the PR merges (the repository's automatic head-branch deletion); delete it by hand only if it survived. Locally, delete the issue branch and any worktree this run created, and leave branches and worktrees that other sessions own. One issue per run — the next issue waits for its own ask.

## Test scope

The strict group is the merge gate, not a per-edit ritual. What an edit needs before it moves on:

- **Prose**: docs, comments, and docstrings with no `>>>` example. `mise run check` covers the file, and the suite proves nothing about a comment. One exception: `tests/packaging/` guards read GLOSSARY.md, the ADRs, the provider spec, the CHANGELOG, CONTRIBUTING, README, the wrapper-image runbook, the CI workflows and the OCR/packaging configuration, so a change to one of those runs its guard file.
- **A comment or docstring inside a function a test reads as source**: the `inspect.getsource` guards, for example the wipe guards in `tests/ui/test_factory_reset.py` and the source assertions in `tests/downloads/test_login_token_persist_listener.py`. Run that test file, plus `mise run check`.
- **Code**: run the focused test files while iterating, then `mise run test-strict` once on the final SHA. `>>>` examples in `waves/` are not collected by any task, so run them explicitly (e.g. `uv run pytest --doctest-modules waves/metadata/camelot.py`) if you touch them.

The tested SHA named in the PR body holds while that SHA is the head. If a later commit is prose-only, fold the fix in before the gate run, or record the delta in the body: `strict green at <sha>; the commits since are prose-only`.

## Waiting on long commands

A command that runs for minutes (`mise run test-strict`, a build) starts once
in the background (the Bash tool's `run_in_background`), and the harness
reports its exit. Do other work or wait for that report; each `sleep` and
`tail` peek costs a call and its context.

## UI verification ladder

Each layer owns its claims. Use the cheapest layer that can observe the
behavior; do not repeat a lower-layer claim with pixel automation.

- **Unit and contract (pytest, no Qt)**: data rules, gates, quality matrix,
  stores, tag writes. Every push, fast.
- **Offscreen QML scenario**: widget state, geometry, bindings, queue/search
  state machines. `mise run test-qml`, `test-strict`.
- **Real-process boot**: composed launch, settings round-trip, library scan,
  quit flush. `test-strict`.
- **Pixel and native automation (cua-driver)**: real hover, native window
  chrome, DPI scaling, real fonts, modal dialogs, OS menu actions. Opt-in
  built-bundle smoke only, bounded with postconditions, each run naming the
  native-only claim it proves; attach the recording
  or screenshots to the issue, PR or release record. Do not re-verify with
  screenshots behavior the QML and process layers already cover.

## Gate evidence

The PR body follows `.github/pull_request_template.md`: a compact gate
record (the exact gate commands, the frozen SHA they ran on, exit
statuses, and result counts) plus the reviews and their dispositions. No
raw logs, no linked logs: counts and exits are the whole record.
Screenshots and recordings are evidence
only for native claims the offscreen layers cannot prove.

Keep implementation evidence in the owning issue or PR: audit findings,
screenshots, benchmark results, investigation notes and completion reports.
Temporary plans, session state and handoff prompts live under `.scratch/`
(gitignored) while work is active. A handoff for the next session is
`.scratch/handoff-<issue>.md`, and the prompt that starts that session names
it. Promote only current rules, contracts or supported workflows into
maintained project documentation.

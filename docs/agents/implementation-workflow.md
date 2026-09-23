# Implementation workflow

How an agent turns an issue into merged code in this repo. `/implement` reads this; the fork topology is the reason the rules look the way they do.

## Branch topology

This repo is a fork: `upstream` is the parent project, `origin` is the fork.

- **`main` mirrors upstream.** It takes fast-forwards from upstream and nothing else — no direct commits, no PRs.
- **`develop` is this fork's integration branch.** Every PR lands here, and only here. PRs base on `develop`, never `main`.
- **One branch per issue**, cut from up-to-date `develop`, named `<type>/issue-<n>-<slug>` (e.g. `feat/issue-23-generic-tag-family`; the type is the work's own — `feat`, `fix`, `spec`).

## The loop

1. **Pre-flight**: run `/sync-upstream` and settle every reconcile verdict before starting — upstream changes are judged against our implementations and our open/closed issues and PRs before any new work begins.
2. **Implement** with the focused tests for what you touch. The strict group is the final gate, not a per-edit ritual: it runs once, on the frozen SHA, after the reviews (see Test scope).
3. **`mise run check`** to settle formatting and lint, so the reviewers read the text that ships.
4. **OpenCodeReview** (`ocr_review`, or `ocr review` on the CLI) on the branch diff with the issue text as background. `.opencodereview/rule.json` carries the house rules and keeps QML/Markdown in scope (its `include` list bypasses the default extension filter). Every finding fixed or explicitly refuted, dispositions recorded in the commit/PR.
5. **`/code-review`** findings fixed or explicitly refuted — the two axes (standards + spec) stay the gate, and they cover what OCR's filters drop. A non-trivial fix delta gets its own `/code-review`; no suite runs between review rounds.
6. **Local gate on the frozen SHA**: `mise run check` plus `mise run test-strict`, the merge gate in `DEVELOPER.md`'s test-group table (it excludes the live account tests, which never run in CI, and it runs alone). A fix commit after this run invalidates the tested SHA, so this is the last write before the PR.
7. **PR → `develop`**, body linking the issue (`Closes #<n>`, which closes it on merge: `develop` is the default branch). Checks are read, not awaited: no workflow of ours gates a PR, the checks that do run on these PRs are CodeQL and SonarCloud, and neither bot review is coverage (CodeRabbit skips repos under 10 stars; Copilot's automatic request came back quota-blocked on #398). The merge stands on the local gate — `mise run check` (lock drift, qmllint, ty, ruff lint + format, prettier and deptry) plus the strict test group and the two reviews above — and the PR body says so, with the tested SHA.
8. **Squash-merge** into `develop`.
9. **Check the issue closed**: the PR body's `Closes #<n>` auto-closes it on the squash, now that `develop` is the default branch. Close explicitly (`gh issue close <n>` with a one-line delivery note) only when the auto-close did not fire.
10. **Delete the branch** locally and on the remote. One issue per run — the next issue waits for its own ask.

## Test scope

The strict group is the merge gate, not a per-edit ritual. What an edit needs before it moves on:

- **Prose**: docs, comments, and docstrings with no `>>>` example. `mise run check` covers the file, and the suite proves nothing about a comment. One exception: `tests/packaging/` guards read CONTEXT.md, the ADRs and the platform, CI and OCR docs, so a change to one of those runs its guard file.
- **A comment or docstring inside a function a test reads as source**: the `inspect.getsource` guards, for example the wipe guards in `tests/ui/test_factory_reset.py` and the source assertions in `tests/downloads/test_login_token_persist_listener.py`. Run that test file, plus `mise run check`.
- **Code, or a `>>>` example in a docstring**: every test task passes `--doctest-modules`. The focused test files while iterating, then `mise run test-strict` once on the final SHA.

The tested SHA named in the PR body holds while that SHA is the head. If a later commit is prose-only, fold the fix in before the gate run, or record the delta in the body: `strict green at <sha>; the commits since are prose-only`.

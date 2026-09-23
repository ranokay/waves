# Implementation workflow

How an agent turns an issue into merged code in this repo. `/implement` reads this; the fork topology is the reason the rules look the way they do.

## Branch topology

This repo is a fork: `upstream` is the parent project, `origin` is the fork.

- **`main` mirrors upstream.** It takes fast-forwards from upstream and nothing else — no direct commits, no PRs.
- **`develop` is this fork's integration branch.** Every PR lands here, and only here. PRs base on `develop`, never `main`.
- **One branch per issue**, cut from up-to-date `develop`, named `<type>/issue-<n>-<slug>` (e.g. `feat/issue-23-generic-tag-family`; the type is the work's own — `feat`, `fix`, `spec`).

## The loop

1. **Pre-flight**: run `/sync-upstream` and settle every reconcile verdict before starting — upstream changes are judged against our implementations and our open/closed issues and PRs before any new work begins.
2. **Implement** with the strict group green (the merge gate in `DEVELOPER.md`'s test-group table; it excludes the live account tests, which never run in CI, and it runs alone).
3. **OpenCodeReview** (`ocr_review`, or `ocr review` on the CLI) on the branch diff with the issue text as background. `.opencodereview/rule.json` carries the house rules and keeps QML/Markdown in scope (its `include` list bypasses the default extension filter). Every finding fixed or explicitly refuted, dispositions recorded in the commit/PR.
4. **`/code-review`** findings fixed or explicitly refuted — the two axes (standards + spec) stay the gate, and they cover what OCR's filters drop.
5. **PR → `develop`**, body linking the issue (`Closes #<n>`, which closes it on merge: `develop` is the default branch). Checks are read, not awaited: no workflow of ours gates a PR, the checks that do run on these PRs are CodeQL and SonarCloud, and neither bot review is coverage (CodeRabbit skips repos under 10 stars; Copilot's automatic request came back quota-blocked on #398). The merge stands on the local gate — `mise run check` (lock drift, qmllint, ty, ruff lint + format, prettier and deptry) plus the strict test group and the two reviews above — and the PR body says so, with the tested SHA.
6. **Squash-merge** into `develop`.
7. **Check the issue closed**: the PR body's `Closes #<n>` auto-closes it on the squash, now that `develop` is the default branch. Close explicitly (`gh issue close <n>` with a one-line delivery note) only when the auto-close did not fire.
8. **Delete the branch** locally and on the remote. One issue per run — the next issue waits for its own ask.

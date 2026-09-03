# Implementation workflow

How an agent turns an issue into merged code in this repo. `/implement` reads this; the fork topology is the reason the rules look the way they do.

## Branch topology

This repo is a fork: `upstream` is the parent project, `origin` is the fork.

- **`main` mirrors upstream.** It takes fast-forwards from upstream and nothing else — no direct commits, no PRs.
- **`develop` is this fork's integration branch.** Every PR lands here, and only here. PRs base on `develop`, never `main`.
- **One branch per issue**, cut from up-to-date `develop`, named `<type>/issue-<n>-<slug>` (e.g. `feat/issue-23-generic-tag-family`; the type is the work's own — `feat`, `fix`, `spec`).

## The loop

1. **Pre-flight**: run `/sync-upstream` and settle every reconcile verdict before starting — upstream changes are judged against our implementations and our open/closed issues and PRs before any new work begins.
2. **Implement** with the full suite green.
3. **`/code-review`** findings fixed or explicitly refuted.
4. **PR → `develop`**, body linking the issue (`Closes #<n>` for the record). Wait for CI and the review bots (**coderabbitai**, **codex**); fix every finding, push, repeat until the reviews are clean.
5. **Squash-merge** into `develop`.
6. **Close the issue explicitly** (`gh issue close <n>` with a one-line delivery note): a squash into `develop` never auto-closes it, because `develop` is not the default branch.
7. **Delete the branch** locally and on the remote. One issue per run — the next issue waits for its own ask.

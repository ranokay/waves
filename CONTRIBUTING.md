# Contributing to `Waves`

Contributions are welcome, and they are greatly appreciated!
Every little bit helps, and credit will always be given.

You can contribute in many ways:

# Types of Contributions

## Report Bugs

Report bugs at https://github.com/ranokay/waves/issues

If you are reporting a bug, please include:

- Your operating system name and version.
- Any details about your local setup that might be helpful in troubleshooting.
- Detailed steps to reproduce the bug.

## Fix Bugs

Look through the GitHub issues for bugs.
Anything tagged with "bug" and "help wanted" is open to whoever wants to implement a fix for it.

## Implement Features

Look through the GitHub issues for features.
Anything tagged with "enhancement" and "help wanted" is open to whoever wants to implement it.

## Write Documentation

Waves could always use more documentation, whether as part of the official docs, in docstrings, or even on the web in blog posts, articles, and such.

## Submit Feedback

The best way to send feedback is to file an issue at https://github.com/ranokay/waves/issues.

If you are proposing a new feature:

- Explain in detail how it would work.
- Keep the scope as narrow as possible, to make it easier to implement.
- Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

# Get Started!

Ready to contribute? Here's how to set up `Waves` for local development.
Please note this documentation assumes you already have `mise` (which brings `uv` and the pinned Python) and `Git` installed and ready to go.

1. Fork the `Waves` repo on GitHub.

2. Clone your fork locally:

```bash
cd <directory_in_which_repo_should_be_created>
git clone git@github.com:YOUR_NAME/Waves.git
```

3. Now we need to install the environment. Navigate into the directory

```bash
cd Waves
```

Then install the environment with:

```bash
mise run install
```

`mise` reads `mise.toml`, which pins Python, uv, hk, Node and Prettier. The
task creates the locked uv environment and installs repository-local hk hooks
through mise. Install mise from <https://mise.jdx.dev>, then run `mise install`
and `mise run install`.

Installation saves recognised generated hooks as `*.before-hk`. It refuses
foreign hooks, symlinked hooks or hook directories, and a configured `core.hooksPath`; coordinate
with their owner before changing them. It never changes global hook settings.

4. Create a branch for local development:

```bash
git switch develop
git switch -c name-of-your-bugfix-or-feature
```

This fork integrates into `develop`; `main` mirrors upstream and takes no
PRs. Follow [the implementation workflow](docs/agents/implementation-workflow.md)
for issue branches and synchronization. Locate the feature's code and tests
in [the domain map](docs/architecture.md).

5. Don't forget to add test cases for your added functionality to the `tests` directory.

6. When you're done making changes, check that your changes pass the formatting tests.

```bash
mise run check
```

7. Before raising a pull request, run the merge gate — the strict group,
   everything but the live account tests:

```bash
mise run test-strict
```

The merge stands on that local run: there is no per-push test gate —
`master.yml` is manual-only (`workflow_dispatch`). The checks a PR does show
come from automatic scanners (CodeQL, SonarCloud) and review bots. None of them
runs the tests or gates the merge. Record the gate in
the PR body with the tested short SHA (the strict result, run alone, plus
`mise run check` and the `/code-review` run). Record exact commands, the tested SHA, exit statuses, result counts and review
dispositions, as in [the PR template](.github/pull_request_template.md).
The manual workflow covers the same group across Python 3.12, 3.13 and
3.14. To run another version locally, re-sync the venv onto it
first (uv keeps the existing interpreter otherwise):
`uv sync --locked --all-extras --python 3.14 && mise run test-strict`.

8. Commit your changes and push your branch to GitHub:

```bash
git add path/to/changed-file.py path/to/new-file.py
git commit -m "fix(domain): describe the corrected behavior" -- path/to/changed-file.py path/to/new-file.py
git push origin name-of-your-bugfix-or-feature
```

9. Submit a pull request through the GitHub website.

The full branch, check, review, and merge loop lives in
`docs/agents/implementation-workflow.md` — follow it; the steps above are
its contributor-facing minimum.

# Pull Request Guidelines

Before you submit a pull request, check that it meets these guidelines:

1. Include focused behavior tests for changed functionality; prose-only changes
   need the checks described in the implementation workflow.

2. If the pull request adds functionality, the docs should be updated.
   Put your new functionality into a function with a docstring, and add the feature to the "What Waves can do" section in `README.md`.

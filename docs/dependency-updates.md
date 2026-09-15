# Dependency and engine updates

Waves pins several things that do not move through `poetry.lock`: the Apple
engine (gamdl/yt-dlp), the wrapper image and its digest, the N_m3u8DL-RE
binaries, the blessed APK with its guest libraries, FFmpeg from managed
sources, and Qt. This page is the playbook for moving any of them.

## The Apple stack moves bottom-up

gamdl → wrapper image → app pins → tests and docs. Nothing later in that
chain moves until the earlier link is published:

1. **gamdl** talks to Apple's catalog and APIs.
2. **The wrapper image** does the playback key exchange and ALAC decryption
   (`wrapper-image.md`).
3. **The app pins** (`WRAPPER_V2_IMAGE_DIGEST`, `N_m3u8DL-RE`, the APK
   version) point at exact artifacts.

A bump is done when the opt-in live suite passes, not when the mocked suite
is green:

```bash
WAVES_ACCOUNT_TESTS=1 .venv/bin/python -m pytest -q tests/account
```

Run the cookies tier always, and the wrapper tier when a container runtime
is available. Without the gate the suite is skipped at collection, so it
never leaks into the default run or CI.

## What is already automated

| Mechanism                                | What it covers                                                                                                                                                                                                                                                   |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wrapper-upstream-check` (Mondays 09:00) | Opens one deduped issue when `glomatico/wrapper-v2` moves past `.github/wrapper-upstream.sha`. Never builds or publishes.                                                                                                                                        |
| Pin-drift tests                          | Fail when the image tag, digest, APK pin, guest-lib pin and runbook drift (`test_wrapper_image_pins.py`), when gamdl drops a member the engine calls (`test_pinned_client_contract.py`), or when the files on this page lose their shape (`test_ci_hygiene.py`). |
| Dependabot (`.github/dependabot.yml`)    | Weekly grouped PRs for `poetry.lock` and GitHub Actions, targeting `develop`. Ignores the deliberate pins below.                                                                                                                                                 |
| The in-app updater                       | Ships app and engine bumps to users through normal releases; no side channel (spec §10.4).                                                                                                                                                                       |
| The release build cache                  | Carries Nuitka's build tree between runs so a routine release relinks instead of recompiling every module.                                                                                                                                                       |

## The update table

| Artifact         | Pinned in                                                            | Cadence                                     | Procedure                                                                                                          |
| ---------------- | -------------------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| gamdl            | `pyproject.toml` (`~3.8.5`, patch-only on purpose)                   | When Apple breaks, or a monthly glance      | Branch off `develop`, open the constraint to the needed minor and relock, then gate on tests + live suite (below). |
| yt-dlp           | Floored to gamdl's own floor; the lockfile holds the version         | Only with a gamdl bump                      | `poetry lock` after the gamdl change; never bump it alone.                                                         |
| Wrapper image    | `WRAPPER_V2_IMAGE` + `WRAPPER_V2_IMAGE_DIGEST`                       | On the watcher's issue, or when ALAC breaks | Dispatch `wrapper-image` with the new upstream SHA, then move tag + digest + runbook in one commit (below).        |
| APK / guest libs | `APK_PINNED_VERSION`, runbook, private asset                         | Only with an image rebuild                  | The image build re-pins libs from the blessed APK; the app never manages them.                                     |
| N_m3u8DL-RE      | `waves/providers/apple/runtime.py` version, asset and SHA-256 tables | When a needed fix lands                     | Re-pin asset names and hashes together in one commit; the pin test enforces coverage; a live fetch confirms.       |
| FFmpeg           | The FFmpeg manager's sources (martin-riedl, BtbN)                    | On breakage                                 | Bump the manager's parser/pin when a source changes shape; smoke-test a managed install.                           |
| Qt / PySide6     | `pyproject.toml`, locked                                             | Deliberately, per release                   | Re-check the macOS floor, the 6.9.3 legacy overlay and the QML suite (below).                                      |
| Everything else  | `poetry.lock`                                                        | Weekly via Dependabot, or on advisories     | Review the grouped PR: `poetry update <pkg>`, `make check`, full suite.                                            |

### gamdl

```bash
git checkout develop && git checkout -b chore/bump-gamdl
poetry add 'gamdl@~3.9'          # edits pyproject.toml and poetry.lock
poetry run pytest                # the pinned-client contract fails first on surface changes
WAVES_ACCOUNT_TESTS=1 .venv/bin/python -m pytest -q tests/account
```

The contract test names the members the engine calls; an intentional surface
change updates that list in the same PR. A bump that changes packaging (new
Qt plugin, new bundled client) also builds one leg and runs
`tools/inspect_bundle.py` before shipping.

### The wrapper image

1. The weekly watcher opens an issue with a compare link; decide, then
   dispatch the workflow with the new upstream ref (a SHA, not a branch):

   ```bash
   gh workflow run wrapper-image.yml --repo ranokay/waves \
     -f wrapper_ref=<upstream-sha> -f image_tag=<new-tag>
   ```

2. The workflow builds `linux/arm64` from upstream source plus the blessed
   APK, smoke-tests `/health` and the decrypt port, and pushes a **new tag**.
3. Move `WRAPPER_V2_IMAGE`, `WRAPPER_V2_IMAGE_DIGEST` and the runbook table
   to the new tag and its publish digest in one commit; the packaging tests
   fail if they drift. Never retag: the app refuses a pull whose digest does
   not match the pin.
4. Confirm with a live wrapper-tier fetch before closing the issue.

### Qt / PySide6

The locked PySide6 has a real macOS 15 floor, and CI's legacy legs overlay
6.9.3 for macOS 12 through 14. Any bump re-runs the macOS version-floor
assertions and the QML suite, and verifies the legacy overlay wheels still
honor their macOS 12 tag. Treat a Qt bump like a release, not a chore.

## Reviewing a Dependabot PR

- The test workflow is manual-only, so the PR shows no checks: run
  `make check` and the full suite locally (or dispatch `master.yml`) before
  merging.
- `poetry.lock` is what users get. If the grouped PR touches something with
  a platform floor or a live-service surface, review it as an engine bump.
- The ignored names (gamdl, yt-dlp, Nuitka, PySide6) are deliberate;
  Dependabot will not propose them. Their bumps use the sections above.

## The Nuitka build cache

A clean release build compiles roughly 1,780 generated C modules for about
an hour; yt-dlp's lazily generated extractor module alone took thirty
minutes locally. Nuitka keeps `dist/waves.build` between invocations: scons
skips C compilation for modules whose generated C is unchanged (content
signatures), and Nuitka's bytecode cache lives in the same tree.

The `build` job restores that tree plus Nuitka's own download cache with
`actions/cache`, keyed `nuitka-v1-<leg>-<poetry.lock hash>`. The
restore-key fallback warms the first build after a dependency bump, with
unchanged modules still skipping. Legs are keyed separately because the
legacy macOS flavors overlay different Qt bindings. ccache is deliberately
not cached: scons already covers it, and a second multi-gigabyte cache would
crowd the repository's 10 GB budget. The first run on a cold cache still
pays the full compile; later releases mostly relink. GitHub evicts caches
unused for seven days, and the `v1` prefix allows a full invalidation if the
build layout ever changes.

## Escalation: match the symptom to the link

| Symptom                                              | Move                                                                        |
| ---------------------------------------------------- | --------------------------------------------------------------------------- |
| Catalog, search or sign-in errors                    | gamdl first, then a live cookies-tier run                                   |
| Download key or ALAC failures, wrapper health errors | Wrapper image                                                               |
| 403/404 fetching the downloader binary               | Re-pin N_m3u8DL-RE assets and hashes                                        |
| Managed FFmpeg install or resolve failures           | FFmpeg manager source parser                                                |
| A release that drags for an hour                     | Check the Nuitka cache restored; a missing lockfile hash means a cold build |

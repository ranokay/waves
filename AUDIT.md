# Waves production-readiness audit

Audit of `develop` at `a2a13cd`, 2026-09-21. Eight parallel audits plus a
coordinating pass. 106 open findings: 2 P0, 21 P1, 42 P2, 41 P3. Two
intentional worktree conditions and two resolved tooling records are documented
outside that count.

## How to use this file

This file is a dated evidence snapshot, not a live backlog.

- Triage session: read Baseline evidence, Execution priorities, Issue filing
  protocol and Open questions. Create issues only for the next deliverable
  work. Once filed, the issue is authoritative for scope and status.
- Implementing agent: start from a `ready-for-agent` GitHub issue. Use its
  source finding IDs to locate the supporting audit evidence, then verify the
  current source before editing.
- Human: resolve only the decisions marked `needs human: yes`. Release
  readiness records what was proven at the audited revision, not a deadline.
- `STATE.md`, if created, is a short kickoff pointer to the tracker and the next
  unblocked work. Do not create `PROGRESS.md`; issues, PRs, commits and CI runs
  already record progress.

## What was audited, and how

Depth was risk-weighted. Every tracked file in scope appears in an inventory
table in the area sections (about 1,000 rows).

| area                                       | depth           | approach                                                                 |
| ------------------------------------------ | --------------- | ------------------------------------------------------------------------ |
| `waves/` shipped package (58.7k lines)     | line-level      | eight agents, one slice each, file:line evidence per claim               |
| `tools/`, `packaging/`, `.github/`, config | line-level      | read plus real command output (`gh`, `git`, `du`)                        |
| `tests/` (107.8k lines, 411 files)         | deep sampled    | scripted passes for markers, hollow tests, coverage gaps; bodies sampled |
| dependencies and external engines          | primary sources | PyPI JSON, OSV, wheel metadata, workflow files                           |
| docs and agent tooling                     | line-level      | every file, verdict per file                                             |
| icons, fonts, binary assets                | inventory only  | counted and listed, not reviewed                                         |
| OS state, external services                | excluded        | outside the repo                                                         |

The coordinator independently re-verified the original P0 candidates, the
baseline numbers below, the CI run facts and the git state. P2 and P3 findings
were not individually re-verified by the coordinator; each carries a confidence
field and file:line evidence. Implementation still starts by checking the cited
source because this snapshot does not update as the repository changes.

## Audit conditions, not findings

The worktree intentionally omitted nine ADRs and four evidence files so the
audit would not rely on them. Those files still exist at `a2a13cd`; their local
deletion is not a defect in that revision and is not a P0. The deletion makes
six repository tests fail because tests and live references still expect the
files. Do not restore or commit the deletions automatically. If the deletions
become a product change, update or remove their tests and references in the
same issue so the resulting repository has one coherent documentation policy.

## Baseline evidence (measured 2026-09-21)

Measured in the worktree at `a2a13cd` plus the 13 intentional uncommitted
deletions described above.

| check                                    | result                                                                                                                                                                                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `uv lock --check`                        | clean, 75 packages                                                                                                                                                                                                                         |
| `mise run test-fast`                     | 6 failed, 4319 passed, 6 skipped, 181 deselected in 30 s                                                                                                                                                                                   |
| the six failures                         | `test_repository_docs.py` (2), `test_acceptance_evidence.py` (3), `test_platform_claims.py` (1). All six expect intentionally omitted files. This worktree cannot pass the gate until the deletion policy and those guards are reconciled. |
| `git status`                             | 13 intentional tracked deletions: `docs/adr/0001` ... `0009`, `docs/evidence/{README,bundle-inspection,platform-builds,wrapper-image-inspection}.md`                                                                                       |
| `gh secret list -R ranokay/waves`        | two secrets (`APK_URL`, `APK_AUTH_HEADER`). No `WAVES_SIGNING_KEY`.                                                                                                                                                                        |
| `git ls-remote --tags origin`            | empty. No tag and no Release has ever existed on the fork.                                                                                                                                                                                 |
| release run `35588929771` (2026-09-21)   | both regular macOS legs green. `create-release`, `sign-manifest`, `update-homebrew-tap` skipped (dispatch without `release_tag`).                                                                                                          |
| full-matrix run `35019374456` (pre-mise) | `windows-x64` and `windows-arm64` failed. macOS regular plus legacy and Linux x64/arm64 succeeded. Signing skipped.                                                                                                                        |
| last `master.yml` run                    | 2026-09-15, before the uv+mise migration (`3879bdf`, 2026-09-18). The current test workflow has never run.                                                                                                                                 |
| code-review-graph                        | was stale at `7710316`; rebuilt at `a2a13cd` during this audit. Embeddings still 0, so semantic search falls back to keyword.                                                                                                              |
| local residue                            | `dist/` 1.1 GB, `.venv` 1.3 GB, `.code-review-graph` 144 MB (HYG-01)                                                                                                                                                                       |

## Executive summary

The shipped code is in better shape than the release path around it. The gates
are thorough and the suite is honest about many of its limits. Confirmed
correctness, privacy and accessibility defects deserve attention before broad
decomposition work. File size identifies maintenance risk, but does not by
itself prove the proposed module boundary.

The two P0s:

1. BUILD-02: `WAVES_SIGNING_KEY` does not exist on the fork and the updater is
   fail-closed. The fork cannot publish a signed release as configured. This is
   conditional on the fork owning publication.
2. DEP-01: the pinned wrapper image `0.2.3` predates the pipeline's notice and
   label fix. Publishing it needs a fixed image or an explicit legal exception.

BUILD-01 is an unresolved release gate, not a proven build failure. The last
Windows failures predate the current `lazy_extractors` exclusion, and no
post-fix Windows run exists. Revalidate the legs before deciding whether they
ship or remain parked.

Cross-cutting themes:

- The release path has never run end to end. There is no fork tag or signing
  key, several legs are unproven under the current recipe, and Flatpak sits
  outside the signed manifest.
- Docs are test inputs. If the intentional deletions are retained,
  `test_repository_docs.py`, `test_platform_claims.py`, live links and
  `test_acceptance_evidence.py` must change in the same deliverable.
- Structure debt is concentrated. `backend.py` is 21,810 lines with a
  519-method bridge; `Main.qml` is 11,345 lines with 338 functions. The audit
  supplies an exact seam map for both.
- Accessibility is the largest UX gap. Save, cancel, retry, filters and update
  actions are pointer-only; 82 `Accessible.*` uses cover 8 of 80 QML files.
- Evidence. Pytest test IDs, assertion failures and CI artifacts are the
  machine-checkable record. Screenshots and native UI recordings are useful
  only for claims that offscreen QML and process tests cannot prove.
- Legal and supply chain. Wrapper notices (DEP-01), pywidevine GPL exposure
  (DEP-02), no bundled third-party notices (DEP-09).

## Release readiness matrix

| leg                                      | last proven build                                            | current recipe | status              |
| ---------------------------------------- | ------------------------------------------------------------ | -------------- | ------------------- |
| macOS intel                              | run `35588929771`, 2026-09-21                                | yes            | builds              |
| macOS apple-silicon                      | run `35588929771`, 2026-09-21                                | yes            | builds              |
| macOS intel `_legacy` (floor 12)         | run `35019374456`, 2026-09-15, poetry recipe                 | never          | unproven            |
| macOS apple-silicon `_legacy` (floor 12) | run `35019374456`, poetry recipe                             | never          | unproven            |
| Linux x64 (zip + AppImage)               | run `35019374456`, poetry recipe                             | never          | unproven            |
| Linux arm64 (zip + AppImage)             | run `35019374456`, poetry recipe                             | never          | unproven            |
| Windows x64                              | never (failed `lazy_extractors`, no run since the exclusion) | never          | parked and unproven |
| Windows arm64                            | never (same)                                                 | never          | parked and unproven |
| Flatpak                                  | workflow exists, not in the signed manifest                  | unknown        | BUILD-08            |
| signed manifest and Release              | never executed (no tag, no key)                              | no             | BUILD-02            |

## Execution priorities

This audit asks for production-grade work, not a release deadline. Do not make a
large refactor the entry fee for contained fixes. GitHub issue dependencies,
not this table, determine the live frontier.

| priority | goal                                                 | representative findings                                                                                      | exit criteria                                                                                                            |
| -------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| 0        | resolve irreversible or external decisions           | BUILD-02, DEP-01 with DEP-08, BUILD-01, DEP-02, DEP-03 and the intentional docs deletion policy              | each decision has an owner and an issue, or a recorded rejection with rationale                                          |
| 1        | prevent wrong files, lost state and privacy failures | DL-01, DL-02, DL-03, SHELL-01, LIB-01, CFG-01, RED-01                                                        | focused regression test proves each original failure; relevant strict group is green                                     |
| 2        | fix user-facing correctness and accessibility        | UX-01 to UX-07, META-01, DL-04, SHELL-04, TEST-02                                                            | keyboard and screen-reader paths work; user-visible outcomes have behavior tests                                         |
| 3        | prove build, dependency and release paths            | BUILD-01 to BUILD-09, TEST-09, TEST-10, DEP-01 to DEP-09                                                     | supported platform set, signing owner and artifact verification agree in executable config and user docs                 |
| 4        | remove test, docs and DX friction                    | TEST-01 to TEST-08, TEST-11, DOC-01 and DOC-04 to DOC-08, HYG-01, HYG-02, DX-01 to DX-05, TOOL-02 to TOOL-05 | repository tasks and claims are truthful; generated evidence stays in CI unless it is durable release or legal evidence  |
| 5        | design and pilot structural changes                  | ARCH-01 to ARCH-03, PRV-01 to PRV-04, QML-01 to QML-03                                                       | an approved design identifies ownership and dependency reduction; one pilot proves the seam before a series is scheduled |
| 6        | cleanup                                              | remaining P3 findings                                                                                        | each is implemented, grouped into a coherent deliverable, or rejected with a reason                                      |

Every issue runs the smallest relevant test while being developed, then follows
`docs/agents/implementation-workflow.md`. Do not commit generated run state just
to prove a test passed. Link CI runs and attach transient logs or screenshots to
the issue or PR. Commit evidence only when it is a durable release, legal or
manual-verification record that cannot be reproduced from code and CI.

## Skills and tools

Choose skills by the issue, not by a fixed wave. Use `diagnosing-bugs` before a
bug fix, `tdd` for behavior changes, `codebase-design` before architectural
work, `research` for current external facts, `wizard` for human-only secret or
account steps, and `blast-radius` plus `code-review` before merge. Start code
exploration with code-review-graph, verify in source, and run OpenCodeReview as
required by the repository workflow.

## UI verification ladder

Each layer owns its claims. Use the cheapest layer that can observe the
behavior; do not repeat a lower-layer claim with pixel automation.

| layer                               | owns                                                                                      | runs                                                                                                   |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| unit and contract (pytest, no Qt)   | data rules, gates, quality matrix, stores, tag writes                                     | every push, fast                                                                                       |
| offscreen QML scenario              | widget state, geometry, bindings, queue/search state machines                             | `mise run test-qml`, `test-strict`                                                                     |
| real-process boot                   | composed launch, settings round-trip, library scan, quit flush                            | `test-strict`                                                                                          |
| cua-driver pixel and `verify_state` | real hover, native window chrome, DPI scaling, real fonts, modal dialogs, OS menu actions | opt-in built-bundle smoke only; attach the recording or screenshots to the issue, PR or release record |

Pytest test IDs, assertion messages and CI output are enough for offscreen QML
scenarios. TEST-11 improves their diagnostics without introducing a checked-in
run database or a per-feature manifest.

## Issue filing protocol

- Create one issue per independently deliverable change. Group overlapping
  findings when one change owns them, for example HYG-01 with the clean portion
  removed from DX-05. Split a finding only when its parts can ship and verify
  independently.
- Pin every command with `--repo ranokay/waves` or `GH_REPO=ranokay/waves`.
- Create with the existing `needs-triage` label. Add category labels only when
  they already exist. Triage then replaces it with `ready-for-agent` or
  `ready-for-human`; do not assume `audit`, area or severity labels exist.
- The issue body names source finding IDs, current evidence, exact scope,
  acceptance criteria and required verification. Do not copy a finding block
  verbatim when the issue groups, narrows or supersedes it. Once filed, the
  issue owns current scope and status; this audit remains unchanged.
- Encode only `blocked by` edges using GitHub native dependencies. `Related to`
  is not a blocking edge. Verify the graph is acyclic before filing it.
- Follow the complete loop in `docs/agents/implementation-workflow.md`:
  `/sync-upstream`, one issue branch from `develop`, focused tests, `mise run
check`, `mise run test-strict`, OpenCodeReview, `/code-review`, PR to
  `develop`, squash merge, explicit issue closure and branch deletion.
- File only the next priority's deliverables. Do not preload the tracker with
  every P2 and P3 observation.

## STATE.md protocol

If a kickoff file is useful, keep `STATE.md` short. It contains the audited
revision, a link to this audit, the umbrella issue or tracker query, unresolved
human decisions, and the command that lists unassigned `ready-for-agent`
issues. It does not repeat finding bodies or progress. A new session reads it,
queries GitHub, claims the first unblocked issue, and follows the repository
workflow. Do not create `PROGRESS.md`.

## Open questions (human decisions)

| #   | question                                                               | recommendation                                                                                                                                                   | finding            |
| --- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| 1   | Windows: revalidate the parked legs or ship six?                       | dispatch `only=windows-x64,windows-arm64` at the candidate SHA before deciding; the `lazy_extractors` exclusion has never run                                    | BUILD-01, TEST-09  |
| 2   | Who owns the signed release, fork or upstream?                         | choose one publisher before configuring secrets or updater endpoints; rehearse in the other repository only if artifacts cannot be confused with public releases | BUILD-02, BUILD-04 |
| 3   | Wrapper image: publish now or sign an exception?                       | publish; the fix is in the pipeline and the APK secret exists                                                                                                    | DEP-01             |
| 4   | Python 3.14 claim: drop or upgrade first?                              | drop the claim until the pinned toolchain and CI prove it; do not take a major compiler and license change only to preserve a classifier                         | DEP-03             |
| 5   | Agent tooling policy: cua-driver per repo, graph freshness?            | keep cua-driver for opt-in built-bundle smoke only; keep routine UI verification in QML tests; rebuild or verify the graph before trusting it                    | TOOL-02, TOOL-03   |
| 6   | Do the intentional ADR and evidence deletions become a product change? | decide after the audit; if yes, remove or replace live references and guards in the same deliverable instead of restoring the files by default                   | audit condition    |

## Provenance and limits

- Area sections were written by eight agents. The coordinator re-verified the
  original P0 candidates, baseline commands, CI run facts, secret list, git
  state and graph rebuild. Everything else carries its own evidence and
  confidence.
- This file is a snapshot at `a2a13cd`. It does not change when a finding lands.
  GitHub issues own implementation status after triage; `STATE.md` only points
  at the live frontier.
- `AUDIT.md` is currently untracked and is not ignored by `.gitignore`. Add it
  normally if it should be durable; otherwise a future checkout cannot use it.
- No repository file was modified during the audit except this one.

---

## Shell and bridge audit

Verdict, three lines:

1. `backend.py` is a 21,810-line module whose `WavesBridge` class (line 3902) carries 519 methods; the existing `LibraryMixin` shows that extraction is possible, while the shared-state census below shows that file moves alone will not create clear ownership.
2. Update install verification is fail-closed and heavily tested, but nothing exercises the baked `UPDATE_PUBLIC_KEY` against the CI signing secret; a key/secret mismatch ships an updater that refuses every install, and no test or CI step can catch it before release.
3. `factoryReset` latches its persistence freeze for prefs and page caches but not for `settings.json` or `token.json`, so a pending settings write or concurrent sign-in finalization can recreate state after the "reset application" wipe, against the promise the dialog makes.

## Inventory

| path                               | lines | purpose (8 words max)                             | depth   | verdict                      |
| ---------------------------------- | ----- | ------------------------------------------------- | ------- | ---------------------------- |
| `waves/desktop/backend.py`         | 21810 | QML bridge: queue, downloads, providers, settings | deep    | refactor (ARCH-01)           |
| `waves/desktop/bridge_library.py`  | 2590  | Library scan/presence mixin                       | deep    | keep                         |
| `waves/desktop/bridge_surfaces.py` | 728   | Provider surface composition, module helpers      | deep    | keep                         |
| `waves/desktop/app.py`             | 732   | Entry point, boot pacing, TLS/art cache           | deep    | finding (SHELL-05, SHELL-08) |
| `waves/desktop/updater.py`         | 2107  | Self-update verify/stage/swap/resume              | deep    | keep (SHELL-02)              |
| `waves/desktop/diagnostics.py`     | 677   | Redacted logging, watchdog, export bundle         | deep    | finding (SHELL-04, SHELL-07) |
| `waves/desktop/ffmpeg_manager.py`  | 631   | Managed ffmpeg install, checksum, smoke test      | sampled | finding (SHELL-03)           |
| `waves/desktop/library_proc.py`    | 386   | Scanner child process lifecycle                   | sampled | keep                         |
| `waves/desktop/devlog.py`          | 146   | Dev timing log, off by default                    | sampled | keep                         |
| `waves/desktop/session.py`         | 136   | WavesTidal cached-token survival                  | sampled | keep                         |
| `waves/desktop/signing.py`         | 102   | Ed25519 verify and manifest parse                 | deep    | finding (SHELL-02)           |
| `waves/desktop/worker.py`          | 46    | QRunnable wrapper that logs failures              | deep    | keep                         |
| `waves/desktop/proc.py`            | 46    | Windows no-console child spawn flags              | deep    | keep                         |
| `waves/desktop/__init__.py`        | 14    | `__version__ = "0.1.30"`                          | deep    | keep                         |
| `waves/desktop/__main__.py`        | 12    | `python -m waves.desktop` launcher                | deep    | keep                         |
| `waves/desktop/README.md`          | 100   | UI module layout notes                            | sampled | keep                         |
| `waves/desktop/BRIDGE.md`          | 384   | Signal/slot map for QML                           | deep    | finding (SHELL-06)           |
| `waves.py`                         | 170   | Nuitka entry point plus build recipe              | deep    | keep                         |
| `waves/__init__.py`                | 196   | Version/repo metadata helpers                     | sampled | keep                         |

## ARCH seam map (`backend.py`)

Census: 21,810 lines. Module level before the bridge holds 8 classes and 164
`def`/constant bindings. `class WavesBridge(LibraryMixin, QObject)` at 3902
spans to EOF (`backend.py:154` import): 17,909 lines, 519 methods, plus a
~920-line `__init__` (4183-5103). `__init__` owns every attribute, following
the rule `bridge_library.py:14-22` states for the mixin it already extracted:
state is created in `WavesBridge.__init__`, behaviour lives in the mixin.

### Domain grouping

Ranges are contiguous blocks of that group's own methods. No other group's
`def` sits inside a listed block. Blocks were derived from `def` lines, so a
move is: start at the first listed method's `def` line, include any decorator
lines directly above it (`@Slot`, `@Property`), end at the line before the
next foreign method's `def` line, and trim any trailing decorator or blank
lines that belong to that foreign method. Verify with
`rg -n '^    (@Slot|@Property)' waves/desktop/backend.py` around each cut.

| #   | domain (proposed module)                                               | methods | blocks                                                                                                                                                                                  |
| --- | ---------------------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | preview + video (`bridge_preview.py`)                                  | 19      | 15693-15953, 15976-16435, 20645-20698                                                                                                                                                   |
| 2   | standalone lyrics/art (`bridge_standalone.py`)                         | 11      | 17502-17640, 17663-17747, 17799-17976                                                                                                                                                   |
| 3   | session/provider surfaces (`bridge_session.py`)                        | 27      | 5179-5250, 5345-5400, 5545-5964, 5991-6092                                                                                                                                              |
| 4   | catalog reads + row vocab (`bridge_catalog.py`)                        | 67      | 5401-5544, 6093-6564, 6592-6656, 6685-7881, 9731-9803, 12358-12755                                                                                                                      |
| 5   | browse/home/tile art (`bridge_browse.py`)                              | 29      | 7882-9182                                                                                                                                                                               |
| 6   | queue state machine (`bridge_queue.py`)                                | 46      | 9183-9507, 10337-10530, 11302-11349, 11384-11668, 18822-19217                                                                                                                           |
| 7   | chooser + quality (`bridge_chooser.py`)                                | 40      | 9508-9717, 9825-10336, 20726-20745                                                                                                                                                      |
| 8   | ownership cluster (`bridge_ownership.py`)                              | 23      | 10642-11301                                                                                                                                                                             |
| 9   | folder gate + recovery (`bridge_folders.py`)                           | 26      | 12810-13464, 15954-15975                                                                                                                                                                |
| 10  | download jobs + merge (`bridge_download.py`)                           | 55      | 10531-10641, 11350-11383, 12756-12809, 13465-14189, 14278-14289, 14298-14320, 14650-14657, 14743-14746, 14789-14849, 14907-15692, 16436-17501, 17977-18165                              |
| 11  | Apple runtime + jobs (`bridge_apple.py`)                               | 105     | 5965-5990, 6565-6591, 6657-6684, 9718-9730, 9804-9824, 14190-14277, 14290-14297, 14321-14649, 14658-14742, 14747-14788, 14850-14906, 17641-17662, 17748-17798, 19235-19856, 20746-21377 |
| 12  | settings/prefs/window/update/ffmpeg/diagnostics (`bridge_settings.py`) | 54      | 5105-5178, 5251-5344, 11738-11968, 12077-12357, 18480-18821, 19218-19234, 19857-20644, 20699-20725, 21378-21810                                                                         |
| 13  | boot/migrations/stop/shutdown (`bridge_lifecycle.py`)                  | 16      | 11669-11737, 11969-12076, 18166-18479                                                                                                                                                   |
| -   | `__init__` + wiring (stays in `backend.py`)                            | 1       | 3902-5103                                                                                                                                                                               |

Counts sum to 518 plus `__init__` (519 total).
Groups are already file-ordered, which is why the split is mechanical: the
module was written domain by domain.

### The three seams that unlock the rest

1. Queue delta protocol. `_queue`/`_queue_index`/`_qdirty_*`/`_qflush_posted`/
   `_queue_emit_suspended`/`_queue_lock` (4686-4721, 4858) plus
   `_emit_queue` (9389), `_flush_queue_changes` (9406), `_queue_batch` (9364),
   `_trim_queue_history` (9183). Only entry points for other groups:
   `_set_queue_status` (10454), `_set_queue_progress` (10477), `_enqueue`
   (10337), `_remove_rows_where` (9231), `_queue_resync` (9355). Once
   `bridge_queue.py` owns these, groups 1, 2, 9, 10, 11 stop reading queue
   internals and the queue module lands before any consumer moves.
2. The one-job runtime. `_JobSpec` (3141), `_ProgressSignals` (1279),
   `_TrackedDownload` (1478), and the per-qid registries `_job_specs`,
   `_job_objs`, `_job_aborts`, `_job_signals`, `_job_tracks`, `_job_dls`,
   `_pending_qids`, `_running_qid`, `_pct_last` (4726-4761). `_start_job`
   (14940, ~410 lines) is the only constructor of `_ProgressSignals` (14963)
   and only GUI-thread caller (`_pump_queue`, 14907). This is the interface
   that needs design, not a pure move.
3. Live media-object cache. `_objs`/`_objs_lock`/`_objs_max` (4501-4517),
   `_remember` (5389), `_MAX_OBJS_PER_BUCKET` (817), and the eviction recovery
   hop `_mediaRefetched` (4668-4674, `_refetch_for_download` 16436). 40+ call
   sites across groups 3-8 and 10. Needs a small `MediaObjectCache` with one
   eviction policy and a refetch callback, or the extracted mixins inherit the
   same 4500-line `__init__` dependency they were supposed to shed.

### Shared state that would fight the split

| state                                                                                                                                    | created at       | read/written by (groups) |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------------------ |
| `_objs`, `_objs_lock`, `_objs_max`                                                                                                       | 4501, 4517, 4509 | 3, 4, 5, 7, 8, 10, 11    |
| `_queue`, `_queue_index`, `_qdirty_*`, `_queue_lock`                                                                                     | 4686-4721        | 6, 9, 10, 11, 13         |
| `_job_specs/_job_objs/_job_aborts/_job_signals/_job_tracks/_job_dls/_pending_qids`                                                       | 4726-4761        | 6, 10, 11, 13            |
| `_artist_groups`/`_artist_lock`, `_folder_groups`/`_folder_lock`, `_stranded_once`                                                       | 4372-4383, 4850  | 6, 10, 13                |
| `_merge_plans`, `_redownload_overrides`, `_library_claim_overrides`                                                                      | 4835-4847        | 6, 9, 10                 |
| `_pending_downloads`, `_pending_lock`, `_recovery_poll`                                                                                  | 4700-4778        | 6, 9, 10, 13             |
| `_lib_cache`, `_search_cache`, `_browse_root_cache`, `_browse_pages`, `_artist_cache`, `_page_cache_lock`                                | 4524-4641        | 3, 4, 5, 11              |
| `_own_cache`, `_own_pool`, `_own_pending`, `_ownership`                                                                                  | 4886-4919        | 6, 7, 8, 11, 13          |
| `settings`, `_waves_prefs`, `_ffmpeg_flag_prefs`, `_ffmpeg_user_path`, `_settings_save_lock`, `_config_writer`                           | 4196-4480        | 2, 3, 7, 10, 11, 12      |
| `threadpool`, `_scan_pool`, `dl_pool`                                                                                                    | 4319-4349        | every group              |
| `providers`, `_provider_signout_flows`, `_provider_status_probes`, `_provider_search_gates`, `_provider_verb_flows`, `_tracked_sessions` | 4233-4300        | 3, 4, 5, 7, 11, 12       |
| `_factory_reset`, `_prefs_unsavable`, `_ffmpeg_install_inflight`, `_app_update_inflight`, `_running_qid`, `_paused`                      | scattered        | 6, 10, 12, 13            |

### Candidate extraction order

This is design input, not an approved implementation series. Validate ownership
and dependency reduction with one pilot before scheduling the remaining
modules. A move that leaves broad access to `WavesBridge.__init__` state has
reduced file size, not coupling.

| PR  | slice                                                | class                                                                                                                     |
| --- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | queue (6)                                            | design ownership and freeze `_emit_queue`/`_flush_queue_changes` as the delta interface before moving consumers           |
| 2   | preview (1)                                          | mechanical after queue ownership                                                                                          |
| 3   | standalone (2)                                       | mechanical after queue ownership                                                                                          |
| 4   | session/provider (3)                                 | mechanical; `_remember` moves here, keep a `backend._remember` alias                                                      |
| 5   | catalog (4)                                          | mechanical                                                                                                                |
| 6   | browse (5)                                           | mechanical                                                                                                                |
| 7   | chooser (7)                                          | mechanical                                                                                                                |
| 8   | ownership (8)                                        | mechanical                                                                                                                |
| 9   | folders (9)                                          | mechanical after queue ownership                                                                                          |
| 10  | download jobs (10)                                   | interface design: one-job runtime object; `_ProgressSignals`/`_TrackedDownload`/`_JobSpec` stay importable from `backend` |
| 11  | Apple (11)                                           | interface design: `_apple_*` state ownership, runtime manager injection                                                   |
| 12  | settings/prefs/window/update/ffmpeg/diagnostics (12) | mechanical, largest shared-state surface                                                                                  |
| 13  | lifecycle/stop/shutdown (13)                         | mechanical                                                                                                                |

For a mechanical pilot, move method bodies without behavior, signature or
public import changes. Test observable behavior and public compatibility. Do
not add source-text guards that pin methods to a file; TEST-05 documents why
those guards obstruct behavior-preserving refactors.

Per-PR test gate: `mise run test-strict` (`mise.toml:41-43`; `pytest
--doctest-modules -rs --require-qml -m "not account" tests`) plus `mise run
check` (`mise.toml:15-17`). `tests/ui/test_qml_bridge_slots.py` is the slot
reachability guard, `tests/ui/test_gui_thread_and_lock_hygiene.py` the
threading guard; both read `WavesBridge`, so they must stay green unmodified.

## Findings

### ARCH-01 - backend.py concentrates unrelated behavior and shared state

- severity: P1
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `backend.py` 21810 lines; `WavesBridge` 3902-21810, 519 methods; `__init__` 4183-5103. `bridge_library.py:708` already extracts one behavior family as `LibraryMixin`; `backend.py:154` imports it. Seam map and shared-state census above.
- why it matters: every bridge PR pays conflict and review cost on one file, while shared mutable state makes naive extraction likely to preserve the same coupling across more files.
- proposed change: run a codebase-design pass over the queue, job-runtime and media-cache seams. Pilot one contained family and measure whether it reduces state access, import coupling and patch-surface risk. Schedule a series only after the pilot proves the boundary.
- acceptance criteria:
  - [ ] an approved design names the state owner and allowed dependencies for the pilot.
  - [ ] the pilot imports without a cycle and preserves every public bridge name it moves.
  - [ ] behavior and public compatibility tests fail on a broken extraction; no test asserts only the source file containing a method.
  - [ ] the pilot demonstrates less shared-state access or a smaller public patch surface, not only fewer lines in `backend.py`.
- evidence required to close: approved design, pilot diff, dependency comparison and green relevant tests plus `mise run test-strict`.
- blocked by: none.
- effort: L after a successful pilot.
- needs human: yes (approve the ownership design and any multi-issue series).

### ARCH-02 - the patch/import surface is load-bearing and unguarded

- severity: P2
- confidence: confirmed
- area: dx
- tags: [refactor] [tests]
- evidence: tests patch module globals in `waves.desktop.backend`: `_image`, `_quality_label`, `_primary_artist_name`, `_track_count`, `_offers_both`, `_atmos_only`, `_has_atmos`, `_fmt_duration`, `_IS_MACOS`, `_preview_http`, `_preview_seg_registered`, `_headless_platform`, `_all_playlist_items`, `format_path_media`, `name_builder_title` (`rg -o 'setattr\(backend..., "X"' tests`). Tests import these names from `backend`: `_MergeRec`, `_TrackedDownload`, `_align_edition`, `_as_member_of`, `_build_merge_plan`, `_collapse_album_editions`, `_collection_incomplete_reason`, `_copy_is_current`, `_delivers_atmos`, `_edition_base_key`, `_explicit_sides`, `_merge_rec_title`, `_norm_track_title`, `_split_explicit_editions`, `_strip_edition_quals`, `atmos_file_template`, `_FACTORY_WIPE_SUBDIRS`, `_FACTORY_WIPE_LOG_PATTERNS`. `app.py:32` imports `_ART_CACHE_DIR`. `bridge_surfaces.py:12-16` states the discipline: helpers are imported back by name so `backend._name` and monkeypatch targets stay alive.
- why it matters: a mixin in a new module binds its own globals, so a patch on `backend._image` silently stops taking effect once the calling method moves and the suite can go vacuous without failing.
- proposed change: before the ARCH-01 pilot, add a compatibility test for public imports and monkeypatch targets actually used by tests or shipped code. Prefer behavioral proof that a patch still reaches the moved method; use identity assertions only where behavior cannot expose the contract.
- acceptance criteria:
  - [ ] frozen-name list committed; test fails when a name is removed or shadowed.
  - [ ] every split PR runs the guard unmodified.
- evidence required to close: the new test, and a demonstration failure from deleting one alias.
- blocked by: none. Related to ARCH-01.
- effort: S.
- needs human: no.

### ARCH-03 - the job runtime is the one interface that must be designed

- severity: P2
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `_ProgressSignals` constructed only at `backend.py:14963` inside `_start_job` (GUI-thread only per `_pump_queue` 14907-14911); `_TrackedDownload` 1478; `_JobSpec` 3141; registries 4726-4761; `_finish_job` 14184; `_release_job_signals` 13465; `_jobFinished` queued hop 4729.
- why it matters: `_start_job` builds 11 collaborators and is the only place with QObject affinity rules; a naive move puts `_ProgressSignals` construction in a module with no documented GUI-thread contract and re-opens the freeze class of bugs.
- proposed change: design and pilot a job-runtime owner with an explicit GUI-thread construction contract. The listed `start`, `finish`, `abort` and `signals` operations are candidate boundaries, not a fixed interface; choose the smallest surface that removes direct registry access from consumers.
- acceptance criteria:
  - [ ] `JobRuntime` unit-tested without a bridge; affinity rule asserted by a test that constructs it off the GUI thread and expects a refusal, or documented and pinned by `test_gui_thread_and_lock_hygiene.py`.
  - [ ] `_start_job` shrinks to a builder call; no behaviour change in `tests/downloads/` and `tests/ui/test_queue*`.
- evidence required to close: new module plus green test-strict.
- blocked by: ARCH-01 design approval.
- effort: M.
- needs human: yes (approve the runtime ownership contract).

### SHELL-01 - factory reset can be silently undone by a late writer

- severity: P1
- confidence: likely
- area: security
- tags: [privacy]
- evidence: `factoryReset` latches `self._factory_reset = True` at `backend.py:21719` and wipes, but the gate is only read by `_save_waves_prefs` (11952), `_save_page_cache` (5808) and tile art (9132). `_submit_settings_write` (18469-18479) and `_save_settings` (18417) have no gate. `shutdown` (18321) flushes `_config_writer` first (18334-18336) and runs on `aboutToQuit` (`app.py:677`), after the wipe; a write submitted before the reset that is still queued lands after `settings.json` was deleted. In-flight downloads are only aborted inside `shutdown`, so a worker can refresh and persist TIDAL tokens (via `config.BaseConfig.save`/`token.json`, `waves/config.py:123-171`) between the wipe and quit.
- why it matters: the dialog promises the next launch starts like a brand-new install; a resurrected `settings.json` or `token.json` keeps the old account and preferences alive after a privacy wipe.
- proposed change: in `factoryReset`, before deleting anything: set the latch, set `_event_abort`, bump generations and abort job events (reuse `stopAll` internals), then `self._config_writer.flush()`, then wipe, then unlink the token path again after the drain. Add the same `_factory_reset` early return to `_submit_settings_write`. Token gating touches `waves/config.py` (library agent) or is handled by the post-drain unlink.
- acceptance criteria:
  - [ ] a test proves a settings write submitted before the reset does not recreate `settings.json` after flush.
  - [ ] a test proves a `Tidal.save()` after the reset cannot recreate `token.json`.
  - [ ] `tests/ui/test_factory_reset.py` keeps its wipe assertions green.
- evidence required to close: two new test names in `tests/ui/test_factory_reset.py` or `tests/downloads/test_factory_reset_wipes_diagnostics.py` plus green test-strict.
- blocked by: none. The issue may include `waves/config.py` if token gating is the chosen fix.
- effort: S.
- needs human: no.

### SHELL-02 - the baked update key is never exercised against the CI secret

- severity: P1
- confidence: unverified
- area: security
- tags: [packaging]
- evidence: `signing.py:34` embeds a 32-byte key; comment at 26-33 still says "BLANK until go-live" (stale). Install verifies fail-closed (`updater.py:797-825`). The only test touching the baked key decodes it and checks length and foreign-signature rejection (`tests/providers/tidal/test_signing.py:54-61`); all round-trip tests monkeypatch the key (`tests/support/updater_fakes.py:32`, `tests/ui/test_updater_integration.py:47`). CI only greps for a non-empty literal (`.github/workflows/release-or-test-build.yml:115-116`). No check compares the baked key to the key that signs `SHA256SUMS.sig`.
- why it matters: a key/secret mismatch ships an updater that refuses every update with "signature invalid" (fail-closed), and no in-repo test can see it; the first signal would be users on the previous release being unable to update.
- proposed change: in the `sign-manifest` job, after signing, verify the signature against the key compiled into the tree: run a two-line Python check importing `waves.desktop.signing` and asserting `verify(manifest_bytes, sig, UPDATE_PUBLIC_KEY)`. Fails the release before publish on mismatch.
- acceptance criteria:
  - [ ] a release (dispatch) run fails when `WAVES_SIGNING_KEY` does not match `UPDATE_PUBLIC_KEY`.
  - [ ] the same job verifies the just-signed manifest before the release goes live.
- evidence required to close: CI run URL from a deliberately mismatched dry run.
- blocked by: BUILD-02 publishing-owner decision.
- effort: S.
- needs human: yes (confirm the secret in the fork's Actions matches the baked key, and who holds it).
- suggested owner: build agent, with this section as the case.

### SHELL-03 - ffmpeg macOS signature check is advisory; docs claim verification

- severity: P2
- confidence: confirmed
- area: security
- tags: [docs]
- evidence: `_macos_verify` logs a warning and `return`s when `codesign --verify` fails (`ffmpeg_manager.py:520-545`); promotion then depends only on `_probe_version` running the staged binary (429-442). Module docstring says the macOS builds are "published signed + notarized, and on macOS we _verify_ that signature (codesign --verify) before trusting the download" (16-21); `install` docstring says "signature-verified, and smoke-tested _before_ it is swapped in" (356-362). `tests/packaging/test_ffmpeg_install_rollback.py:178` pins the fail-open path deliberately.
- why it matters: the shipped trust claim is stronger than the behaviour. On Windows and Linux there is no authenticity check at all, which the module's own trust note admits; the macOS wording implies a gate that does not exist.
- proposed change: either make a failed `codesign --verify` fatal (refuse to promote, keep the existing binary) or reword both docstrings to "advisory: signature is recorded, promotion is gated on checksum plus smoke test". Decide fail-open vs fail-closed once.
- acceptance criteria:
  - [ ] docstrings and the test name agree with the chosen policy.
  - [ ] if fail-closed, a test proves a bad-signature download leaves the previous binary in place.
- evidence required to close: the chosen policy in the test and docstring diff.
- depends on / blocks: none.
- effort: S.
- needs human: yes (pick fail-open or fail-closed for managed installation).
- suggested owner: shell.

### SHELL-04 - logTail can block the GUI thread for up to 2s per poll

- severity: P2
- confidence: confirmed
- area: perf
- tags: [ux]
- evidence: `_flush_disk_log` waits up to `timeout=2.0` (`diagnostics.py:573-585`); `diagnostics.log_tail` calls it with no timeout (395-411); `WavesBridge.logTail` (12328-12341) is called from `qml/LogsDrawer.qml:49` on a 1000ms timer (`LogsDrawer.qml:88`). The docstring claims the tail "can never stall the GUI thread that polls it" (`test_logs_console.py:1-7`). `test_logs_console.py` covers byte/line caps only.
- why it matters: with verbose diagnostics on and a busy log producer (per-track download lines), every poll can hold the event loop while the queue never empties, which is the stall class the console exists to diagnose.
- proposed change: pass a short deadline (`flush_disk_log(timeout=0.05)`) from `log_tail`, and add a test whose fake handler's queue never empties, asserting `log_tail` returns inside a bound.
- acceptance criteria:
  - [ ] `log_tail` returns within 100ms when the writer is wedged.
  - [ ] console still shows just-written lines (existing tests green).
- evidence required to close: new test name in `tests/ui/test_logs_console.py`.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### SHELL-05 - `os._exit` skips atexit, and the QML-failure path never shuts down

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: standalone launch ends with `os._exit(rc)` (`app.py:717-727`), so `atexit` handlers never run: `atexit.register(_watchdog.stop)` (`diagnostics.py:371`) and `atexit.register(_stop_disk_listener)` (`diagnostics.py:466`) are skipped. `shutdown` covers the watchdog (18335) and flushes the writer, but records logged after that flush and still in the disk queue are dropped. The QML-load failure path returns 1 at `app.py:680-683` without calling `bridge.shutdown()`, leaving pools and the scanner child alive into interpreter teardown.
- why it matters: crash-log fidelity at exit is a support tool for production diagnostics; losing the last records is minor but silent, and the failure path is the one where a clean teardown matters most.
- proposed change: call `diagnostics._stop_disk_listener()` (or a public `diagnostics.close()`) in `app.py` immediately before `os._exit`, and call `bridge.shutdown()` on the QML-load failure path.
- acceptance criteria:
  - [ ] a line logged after `shutdown()` in a cold boot test still reaches `waves_dev.log`.
  - [ ] `test_cold_process_boot.py` exits 0 unchanged.
- evidence required to close: new assertion in a cold-process test.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### SHELL-06 - BRIDGE.md drift and a stale pool contract

- severity: P3
- confidence: confirmed
- area: docs
- tags: [obsolete]
- evidence: signal census from `backend.py` against `BRIDGE.md`: public signals declared but undocumented: `skipExistingChanged`, `qualityOverridesChanged`, `targetTierChanged`, `qualityChoiceChanged`, `appleWrapperAuthChanged`, `appUpdatePending`. `BRIDGE.md:376-384` requires a row per new signal; only the retired `recentlyAdded` pair is pinned (`tests/ui/test_dead_pair_and_qml_gating_guards.py:15`). `WavesBridge` docstring says `dl_pool` is "sized by the concurrency setting" (`backend.py:3934`) while it is fixed at one thread (`4349`) and deliberately not resized (`21622`).
- why it matters: BRIDGE.md is the seam map other agents read; drift makes the QML contract unreliable.
- proposed change: add the six rows, fix the `dl_pool` sentence, and add a census assertion to `tests/ui/test_qml_bridge_slots.py` that every public `Signal` declared in `backend.py` and `bridge_library.py` appears in `BRIDGE.md`.
- acceptance criteria:
  - [ ] census test fails on a new undocumented public signal; passes today after the rows are added.
- evidence required to close: the test plus the doc diff.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### SHELL-07 - freeze watchdog is off on every default install, stale 6s comment

- severity: P3
- confidence: confirmed
- area: dx
- tags: [docs]
- evidence: watchdog starts only through `diagnostics.set_verbose` (`diagnostics.py:499-517`); the pref defaults false (`backend.py:11844`) and is applied at construction (`5102`); `test_freeze_watchdog_quit.py` therefore exercises an opt-in mode. Comment block at `diagnostics.py:73-90` reasons about "a 6s dump wait" while `_WATCHDOG_DUMP_SEC = _WATCHDOG_STALL_TARGET_SEC + _WATCHDOG_TICK_MS/1000` is 4.5s (`78-85`).
- why it matters: a GUI freeze on a release build produces no stack and no freeze record, so a hang report has nothing to read; the stale number misleads the next debugger.
- proposed change: fix the comment; decide whether the watchdog (stack-only, no user content) should be always on at a higher threshold, e.g. 15s, with only the dump enabled.
- acceptance criteria:
  - [ ] comment matches the constants.
  - [ ] if always-on is chosen, a cold boot test proves the dump fires once on a synthetic 20s block and that non-verbose disk level stays WARNING.
- evidence required to close: comment diff and, if changed, the test.
- depends on / blocks: none.
- effort: S.
- needs human: yes (privacy trade-off of an always-on stack dump).

### SHELL-08 - test-only quit knob is a production env backdoor

- severity: P3
- confidence: confirmed
- area: dx
- tags: []
- evidence: `_install_test_quit` reads `WAVES_QUIT_AFTER_BOOT_MS` and quits the app after that delay for any launch (`app.py:585-596`, called at 715). Used by `tests/ui/test_cold_process_boot.py:11-12`.
- why it matters: anyone with the variable exported (a copied CI snippet, a wrapper script) gets an app that closes itself with no message; support cost with no upside.
- proposed change: gate the seam on a second marker (`WAVES_TEST_SEAM=1`) or on `--quit-after-boot-ms` in `sys.argv`, and update the cold-boot test's env.
- acceptance criteria:
  - [ ] setting only `WAVES_QUIT_AFTER_BOOT_MS` no longer quits a normal launch.
  - [ ] the cold boot test still exits 0.
- evidence required to close: updated test plus a manual launch check.
- depends on / blocks: none.
- effort: S.
- needs human: no.

## Claims checked

| claim                                                                                 | source                               | verdict                    | evidence                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------- | ------------------------------------ | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cross-thread signals are delivered on the GUI thread; QML handlers never see a race   | `BRIDGE.md:6-8`                      | true for the audited paths | `_emit_queue` branches on `main_thread()` (`backend.py:9389-9403`); worker-only signals use queued connections (`4721`, `4729`, `4679`); `_emit_from_worker` covers teardown (`18583-18597`)                        |
| `dl_pool` is sized by the concurrency setting                                         | `backend.py:3934`                    | false                      | fixed at 1 (`4349`), explicitly not resized (`21622`)                                                                                                                                                               |
| Update payload hashes are trusted only after the signed manifest verifies             | `updater.py:789-825`                 | true                       | signature check 804, version check 812-818, asset-in-manifest 822, checksum 824-827; `test_updater.py:1200-1306`                                                                                                    |
| Downgrade to an older signed release is refused                                       | `updater.py:808-818`                 | true                       | `test_updater.py:1276`, `test_install_missing_version_line_refused` 1292                                                                                                                                            |
| Factory wipe can only delete Waves' own files and contains no recursive delete        | `backend.py:21703-21714`             | true                       | allowlists 649-800; `test_factory_reset.py:314` asserts no recursive delete; symlink cases 296, 390                                                                                                                 |
| Factory reset makes the next launch start like a brand-new install                    | `backend.py:21697-21706`             | false under concurrency    | SHELL-01                                                                                                                                                                                                            |
| The log tail "can never stall the GUI thread that polls it"                           | `test_logs_console.py:1-7`           | false for the flush wait   | SHELL-04                                                                                                                                                                                                            |
| ffmpeg macOS binary is signature-verified before it is trusted                        | `ffmpeg_manager.py:16-21`, `356-362` | false in effect            | advisory only (`520-545`), fail-open pinned by `test_ffmpeg_install_rollback.py:178`                                                                                                                                |
| Nothing stops a second copy of Waves; nothing may assume one                          | `test_two_copies_of_waves.py:1-20`   | true                       | per-write temp staging (`waves/config.py:91-171`), ownership schema self-heal (test 140), ffmpeg in-flight guard plus `mkstemp` staging (`ffmpeg_manager.py:387-399`), update `_StagingLock` (`updater.py:458-511`) |
| Watchdog cannot fabricate a freeze on quit; `shutdown` stops it before draining pools | `test_freeze_watchdog_quit.py:1-14`  | true                       | `shutdown` stops it at 18335 before drains at 18381-18387                                                                                                                                                           |
| Queue mutations from workers cross only via coalesced deltas on the GUI thread        | `backend.py:3917-3936`               | true                       | `_emit_queue` 9389, `_flush_queue_changes` 9406, batch context 9364; `tests/ui/test_queue_delta_protocol.py`, `test_queue_delta_mirror.py`                                                                          |
| Every `waves.<name>` QML calls is a real meta-object slot                             | `test_qml_bridge_slots.py:1-10`      | true (slot direction only) | the test walks QML refs; no reverse census exists (SHELL-06)                                                                                                                                                        |
| `UPDATE_PUBLIC_KEY` is blank until go-live                                            | `signing.py:26-33`                   | false, key is set          | `signing.py:34`                                                                                                                                                                                                     |

## Top 3

1. SHELL-01: fence factory reset against late settings and token writers before relying on the privacy promise.
2. SHELL-02: verify the baked update key against the CI signing secret as a release gate; it is the one failure that breaks updates for the installed base and cannot be seen from the repository alone.
3. ARCH-01: design and pilot one ownership seam before scheduling a large split.

## Release blockers

None confirmed as P0. Closest is SHELL-02, which is unverifiable here (needs the fork's `WAVES_SIGNING_KEY`); if the secret and the baked key do not match, it becomes P0 (every self-update refuses).

## Open questions

1. Should the update signing key be verified end-to-end in CI before publish? Default: yes, add the verify step to `sign-manifest` (owner: build agent).
2. Fail-open or fail-closed for an unverifiable macOS ffmpeg signature? Default: fail-closed for the managed install, keep the user's existing binary.
3. Should the freeze watchdog be always on (stack-only) at a higher threshold? Default: yes at 15s, disk level unchanged.
4. Should the release add a single-instance guard? Default: no; keep the current mitigations and document the second-copy behaviour in `README.md`.
5. Which bridge seam should be the pilot? Default: queue state, because it already has a delta protocol and clear external entry points.
6. Should extracted behavior continue reading bridge-owned state? Default: no. Approve an owner and narrow operations first; otherwise defer the move.

---

## Downloads / providers / metadata audit

The TIDAL byte pipeline is the most defensive code in the release: staged merges,
fsynced cross-filesystem swaps, item-id-keyed skip gates, version gates for
dual-download, and failure isolation per item. The Apple pipeline is the newer
risk: its file-skip is identity-blind, its placement overwrites unconditionally,
and its tag writes can be permanently skipped. The Provider seam is a real ABC
for provider calls, but the download engine is still tidalapi-shaped, and the
row-dict schema is convention plus tests, never a runtime contract.

## Inventory

| path                                 | lines | purpose (8 words max)                                 | depth   | verdict |
| ------------------------------------ | ----- | ----------------------------------------------------- | ------- | ------- |
| waves/download.py                    | 4983  | TIDAL segment pipeline, staging, tagging, collections | deep    | finding |
| waves/model/**init**.py              | 0     | empty package marker                                  | sampled | keep    |
| waves/model/cfg.py                   | 673   | settings dataclass, provider_setting, tag flags       | deep    | keep    |
| waves/model/downloader.py            | 24    | DownloadSegmentResult, TrackStreamInfo dataclasses    | deep    | keep    |
| waves/model/gui_data.py              | 53    | GUI signal dataclasses; imports PySide6 when present  | deep    | finding |
| waves/model/meta.py                  | 14    | release/project dataclasses                           | sampled | keep    |
| waves/providers/**init**.py          | 70    | lazy provider re-exports                              | deep    | keep    |
| waves/providers/base.py              | 724   | Provider ABC, row-dict schema, StreamInfo, adapter    | deep    | finding |
| waves/providers/tidal.py             | 816   | TIDAL provider; imports engine helpers privately      | deep    | finding |
| waves/providers/tidal_client.py      | 275   | tidalapi session/query helpers, media instantiation   | sampled | keep    |
| waves/providers/tidal_folders.py     | 323   | playlist folder tree, per-segment sanitizing          | sampled | keep    |
| waves/providers/tidal_manifest.py    | 84    | DASH segment-count arithmetic                         | deep    | finding |
| waves/providers/apple/**init**.py    | 14    | Apple package re-exports                              | sampled | keep    |
| waves/providers/apple/engine.py      | 928   | gamdl fetch/decrypt, verification, probes             | deep    | keep    |
| waves/providers/apple/files.py       | 351   | Apple paths, tags, sidecars, atomic placement         | deep    | finding |
| waves/providers/apple/integrity.py   | 406   | verify decisions, quarantine paths/dates              | deep    | keep    |
| waves/providers/apple/provider.py    | 1593  | Apple catalog, stream resolution, TTML                | deep    | keep    |
| waves/providers/apple/runner.py      | 2731  | Apple job orchestration, retries, settlement          | deep    | finding |
| waves/providers/apple/runtime.py     | 1072  | N_m3u8DL-RE provisioning, wrapper image pin           | deep    | keep    |
| waves/providers/apple/supervision.py | 890   | sidecar container lifecycle, throttling               | deep    | keep    |
| waves/metadata/**init**.py           | 7     | metadata package doc                                  | sampled | keep    |
| waves/metadata/camelot.py            | 395   | key/scale to Camelot conversion                       | sampled | keep    |
| waves/metadata/lyrics.py             | 203   | LRCLIB lookup, sidecar precedence choices             | deep    | keep    |
| waves/metadata/matching.py           | 1315  | presence matching, editions, rollups                  | sampled | keep    |
| waves/metadata/mb_arbiter.py         | 386   | MusicBrainz arbitration with sqlite cache             | sampled | keep    |
| waves/metadata/naming.py             | 101   | tidalapi objects to artist/title names                | deep    | keep    |
| waves/metadata/tags.py               | 804   | mutagen tag writer/reader, id and version tags        | deep    | finding |
| waves/metadata/ttml_lyrics.py        | 191   | TTML to LRC/text conversion                           | deep    | keep    |
| waves/poolgauge.py                   | 83    | Qt-free executor saturation gauge                     | deep    | keep    |
| waves/progress.py                    | 112   | headless progress task table                          | deep    | keep    |
| waves/playlists.py                   | 287   | per-directory m3u writer, atomic swap                 | deep    | keep    |

## Findings

### DL-01 - DASH under-generated URL list lands truncated audio as success

- severity: P1
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/providers/tidal_manifest.py:36-84` computes the required DASH
  segment count and returns a negative number when `tidalapi` emitted too few
  URLs (`:78-82` warns "audio may be truncated"); `waves/providers/tidal.py:660`
  passes that value into `StreamInfo.tail_spurious`;
  `waves/download.py:898-902` reads only `n_tail_spurious > 0` as harmless and
  treats a negative exactly like `None`/`0` for every URL that _does_
  download; `waves/download.py:1043-1051` derives success from the generated
  URLs only, so all-URLs-success + short list = `(True, file)` and the item is
  written, tagged, moved and reported done. Test
  `tests/packaging/test_manifest_tail.py:84-95` pins the `-1` helper answer
  only; no test asserts a pipeline verdict for it.
- why it matters: A track whose manifest has two or more repeated `<S r>` blocks
  yields a file missing its last segment while every surface reports success.
  This is the exact "silently truncated file" class DL-01's sibling logic
  (`n_tail_spurious == 0`) was built to prevent, and it survives because the
  negative signal is computed and then ignored.
- proposed change: Fail the item when the provider proved the URL list short.
  In `Download._download` (download.py:1022) classify
  `stream_info.tail_spurious is not None and stream_info.tail_spurious < 0` as a
  fetch failure before the segment fan-out, log the provider's warning, and
  return `(False, path)`; leave every other `tail_spurious` behavior byte-
  identical.
- acceptance criteria:
  - [ ] A unit test feeds `n_tail_spurious=-1` with all segments succeeding and
        asserts the item fails and no file is written.
  - [ ] A test with `n_tail_spurious=-1` and the last segment failing also
        fails (no behavior change).
  - [ ] `tail_spurious` `None`, `0` and `>0` behavior is unchanged.
- evidence required to close: new test names in `tests/downloads/` plus
  `mise run test-strict` green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### DL-02 - Apple file skip ignores item id, silently skipping other tracks

- severity: P1
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/providers/apple/runner.py:1783-1784` raises `_AppleSkipped`
  when `data.skip_existing and exact.exists() and occupant_is_version(exact,
version_hint)`; `occupant_is_version` (`waves/metadata/tags.py:323-344`)
  reads only the on-disk Version tag/codec and never the item id. The TIDAL
  engine's equivalent gate checks identity through
  `_existing_same_item_at` (`waves/download.py:1925-1936`: occupant id, owned
  ids, numbered variants). `pick_destination` (`waves/providers/apple/files.py:135-154`)
  numbers on disk collisions but is never reached once the skip fires. The skip
  fires whenever the ownership store has no current record
  (`runner.py:1370-1371` returns `None` on a broken/missing record), e.g. a
  fresh ownership DB pointed at an existing library.
- why it matters: Two distinct tracks whose template renders one relative path
  (same artist/title, blank-album playlist template, two releases of one song)
  collide; the second one is reported skipped/done and never fetched. This is
  the collision TIDAL spent `_numbered_variant_holding` and the name ledger on.
- proposed change: Before `_AppleSkipped`, read the occupant's item id
  (`read_item_id`/generic tag) and compare against this track's id; skip only
  when the id is absent or belongs to this track (the TIDAL rule), else fall
  through to `pick_destination` so the colliding track lands at a numbered
  name.
- acceptance criteria:
  - [ ] A test places a tagged file for a DIFFERENT Apple track at the rendered
        path with `skip_existing` on; asserts the new track fetches and lands
        at the numbered variant.
  - [ ] A test with the same track's id still skips without fetching.
  - [ ] An untagged occupant still skips (historical safety).
- evidence required to close: tests in `tests/downloads/` or
  `tests/providers/apple/` named for identity-aware skip; strict suite green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### DL-03 - Apple placement overwrites an occupant without identity check

- severity: P2
- confidence: confirmed
- area: bug
- tags: [windows]
- evidence: `waves/providers/apple/files.py:703-720` (`place_file`) writes
  `dest.name.part-<uuid>` then `os.replace(tmp, dest)` unconditionally, and
  `runner.py:1873` calls it after a `dest` resolved earlier by
  `pick_destination` (`runner.py:1786` or `:1862`). TIDAL's equivalent move
  refuses an occupied destination it cannot prove is its own
  (`waves/download.py:3701-3725`, `occupant_is_own` callback at `:3120-3131`).
  Nothing re-checks the name between pick and place; the fetch window is
  seconds to minutes.
- why it matters: A same-named file created in that window (another app, a
  sync tool, a Finder copy) is silently replaced, and the item is reported
  done. TIDAL treats exactly this as "leaving the download out of the library"
  rather than losing the file.
- proposed change: Make Apple's place path refuse an occupied destination
  unless it can prove ownership (id + Version via the same readers the skip
  uses), stepping aside to a numbered name or failing the item with the TIDAL
  wording. `force`/`owned_path` keeps its overwrite right.
- acceptance criteria:
  - [ ] A test creates a foreign same-named file between destination pick and
        place; asserts it is not overwritten and the item either numbers or
        fails loudly.
  - [ ] A forced re-download still overwrites the owned path in place.
- evidence required to close: test name + strict suite green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### DL-04 - Apple tag failure is invisible and permanently unretried

- severity: P2
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/providers/apple/runner.py:2070-2082` calls
  `tag_apple_file(...)` and only `logger.debug`s a False return; the track
  then emits `status: done` with quality (`:2544-2551`) and ownership is
  recorded upstream. The next run skips the file (`runner.py:1783`), so the
  untagged file is never re-tagged. TIDAL has the same shape:
  `waves/download.py:3207-3213` discards `_result_metadata`.
- why it matters: A file that lands but cannot be tagged (locked by a scanner,
  transient EACCES, a container mutagen cannot parse) is recorded as owned and
  skipped forever; the user sees a done row and a library entry with no tags.
  Tag write is the last non-atomic step before the done event.
- proposed change: Surface the failure: when the tag write returns False, emit
  the done event with a non-fatal reason (or a `tagged: false` field) so the
  row can say "saved, tags failed", and do not let the ownership record alone
  justify a silent skip on the next run unless the file reads as tagged.
- acceptance criteria:
  - [ ] A test forces `tag_apple_file` False and asserts the done event
        carries the failure (or the row reason), not just a debug log.
  - [ ] Re-running over the untagged file retries tagging.
- evidence required to close: test names, strict suite green.
- depends on / blocks: none.
- effort: M.
- needs human: no.

### DL-05 - `event_abort` is Optional by constructor, dereferenced unguarded

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/download.py:468` defaults `event_abort` to `None` and
  `:542` stores it; the hot paths call `self.event_abort.is_set()` with no
  guard (`:910`, `:914`, `:1122`, `:1160`, `:1302`, `:1319`, `:4612`), while
  `:1641`/`:1656` deliberately guard `is not None` and the pacing helper
  tolerates `None` (`:1656-1659`). Tests must set
  the attribute by hand to exercise `item()`
  (`tests/downloads/test_zero_byte_destination.py:38`); the backend always
  passes the bridge's event (`waves/desktop/backend.py:5339`).
- why it matters: The constructor advertises an optional argument and half the
  class honors it; any new caller (a worker, a test harness, a future headless
  path) that omits it crashes with `AttributeError` only once a download
  starts, mid-job, where the failure is least diagnosable. The mixed contract
  also hides which methods are safe to call without an abort event.
- proposed change: Pick one: default the attribute to a shared, never-set
  `Event()` on the class (matching `_pace_holds`'s stand-in pattern) so
  every call site is safe, or make the parameter required. Keep the `is not
None` guards harmless either way.
- acceptance criteria:
  - [ ] A test constructs `Download` without `event_abort` and runs a
        one-item download; it fails for the intended reason, never
        `AttributeError`.
  - [ ] Grep shows no unguarded `self.event_abort.` on a path reachable
        before assignment.
- evidence required to close: test name, strict suite green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### PRV-01 - Row-dict schema is documented convention, not runtime contract

- severity: P2
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: The schema lives in a docstring (`waves/providers/base.py:24-98`)
  with the warning that rows are never partial-keyed because a QML ListModel
  freezes roles on the first row (`:33-34`); the neutral default for the row
  renderer returns an empty dict (`base.py:694-700`), which callers treat as
  "cannot render" rather than an error. The only enforcement is exact-dict
  equality in per-provider tests (e.g.
  `tests/providers/apple/test_apple_provider_search.py:97-168`); no runtime
  code validates keys, and QML never sees an error for a missing role.
- why it matters: A provider-side rename or omission (an Apple catalog field
  that disappears, a new provider's row) degrades to empty UI roles and
  silently wrong badges rather than a visible failure. The release ships two
  providers plus a documented third-provider path; that path has no guardrail.
- proposed change: Add one `validate_row(kind, row)` (required keys per kind,
  values type-checked) in `waves.providers.base` and call it at the bridge's
  row-ingest points, raising in tests/CI and logging once per kind at runtime.
  Behavior freeze: no row content changes.
- acceptance criteria:
  - [ ] A deliberately key-dropped row fails validation with the missing key
        named.
  - [ ] Apple and TIDAL rows pass unchanged.
  - [ ] The validator is not imported by `waves.download` (no engine coupling).
- evidence required to close: validator tests, strict suite green.
- depends on / blocks: none.
- effort: M.
- needs human: no.

### PRV-02 - Engine half of the seam is tidalapi-shaped; Apple bypasses it

- severity: P2
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `waves/providers/base.py:8-12` states the seam is "one fused
  interface that TIDAL and Apple Music both implement" and `:283-288` admits
  `StreamInfo.local_file` exists because a provider's whole-file delivery
  cannot ride the pipeline. The engine still imports tidalapi types at module
  scope (`waves/download.py:33-40`) and branches on them
  (`isinstance(media, Track)` / `Video` at `:2626-2670`), calls
  `media.get_stream()` inside `_get_track_stream_info` (`:2796`), and reads
  `media.audio_modes` for the Atmos decision (`:2768-2772`). Apple's real
  pipeline is a separate 2731-line runner (`waves/providers/apple/runner.py`)
  wired as a bridge-side `DownloadAdapter.job_runner` (`base.py:361-377`).
- why it matters: "Second provider behind the same seam" holds for search,
  catalog and stream resolution, but any provider that is not tidalapi-shaped
  (or Amazon, Qobuz) must reimplement the entire download pipeline. The seam's
  claimed extensibility is part of the provider architecture contract.
- proposed change: Freeze behavior and split the engine's provider-neutral core
  (path claiming, staging/swap, sidecar moves, collection fan-out, m3u) from
  the TIDAL fetch/tag specifics, so `runner.py` and `download.py` share one
  pipeline. Scoped first step: move `Track | Video` typing behind the seam
  (a `MediaKind` on `StreamInfo` plus the provider's `local_file`/`urls`
  contract) without changing any behavior.
- acceptance criteria:
  - [ ] `Download` performs no `isinstance(..., Track)` branch; media kind
        comes from the provider answer.
  - [ ] Apple and TIDAL integration tests unchanged and green.
  - [ ] No file layout, tag, or m3u byte changes (golden tests).
- evidence required to close: diff plus strict suite green.
- depends on / blocks: none.
- effort: L.
- needs human: yes (whether to fund the refactor pre- or post-release).

### PRV-03 - Providers import engine-private helpers and the library scanner

- severity: P3
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `waves/providers/tidal.py:31` imports
  `_artist_ids, _tidal_refuses_asset, _waves_item_id` from `waves.download`;
  `waves/providers/apple/runner.py:42` imports
  `waves.library.ownership` at module scope and `:816` imports
  `waves.library.index` lazily for quarantine scan exclusion. The base module
  promises it is "deliberately import-light ... without dragging anyone else
  along" (`base.py:4-6`).
- why it matters: The provider package cannot be imported without the engine,
  and the direction of the private-helper import is engine->provider in some
  places and provider->engine in others, exactly the cycle the lazy
  `waves/providers/__init__.py:6-11` dance exists to dodge. A third provider
  author has no public helper to reuse.
- proposed change: Promote the three helpers to a neutral module
  (`waves/metadata/naming.py` or a new `waves/providers/neutral.py`) and have
  both the engine and TIDAL import them there; keep the library imports lazy
  and document the allowed direction (providers -> base + metadata only).
- acceptance criteria:
  - [ ] `rg 'from waves.download import' waves/providers/` is empty.
  - [ ] TIDAL behavior tests unchanged.
- evidence required to close: grep output plus strict suite green.
- blocked by: PRV-02 design decision.
- effort: S.
- needs human: no.

### PRV-04 - Engine import chain pulls PySide6 when installed

- severity: P3
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `waves/model/gui_data.py:4-24` imports `PySide6.QtCore` at module
  scope behind `except ModuleNotFoundError` and defines `ProgressBars`; the
  engine imports it at `waves/download.py:76` and annotates on it (`:453`,
  `:465`). `waves/poolgauge.py:17-18` documents the intent ("the download
  engine imports this and must stay importable without PySide6"). The guard
  catches only `ModuleNotFoundError`, not the `ImportError`/`OSError` a broken
  Qt shared library raises.
- why it matters: The engine package is no longer UI-free in practice: any
  process importing `waves.download` loads QtCore whenever PySide6 is present,
  and a partially broken PySide6 install can break the engine import entirely.
  It also makes a headless consumer of the engine pay Qt startup.
- proposed change: Move the neutral progress-signal shape (a Protocol or a
  plain dataclass) into `waves/model/downloader.py`; have
  `waves/model/gui_data.py` build the Qt-backed `ProgressBars` from it. The
  engine imports only the neutral module.
- acceptance criteria:
  - [ ] `waves.download` imports cleanly with PySide6 removed from
        `sys.modules` and PySide6 absent from disk.
  - [ ] A test asserts `PySide6` not in `vars(waves.download)`.
- evidence required to close: test name, strict suite green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### META-01 - Apple files are tagged with a zero disc total

- severity: P2
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/providers/apple/files.py:322` passes `totaldisc=0` for
  every Apple tag write; MP4 writes `disk = [[discnumber, 0]]`
  (`waves/metadata/tags.py:718`) and FLAC writes `DISCTOTAL = "0"`
  (`tags.py:601`), which the empty-tag sweep keeps because `"0"` is non-empty
  (`tags.py:782-803`). The same writer deliberately omits an unknown
  TRACKTOTAL (`tags.py:596-599`), and the MP4 unknown track total is pinned as
  intentional (`tests/metadata/test_tag_truths.py:87-91`). TIDAL passes
  `album_facts.get("num_volumes") or 1` (`waves/download.py:4180`), so this
  is Apple-only.
- why it matters: Every Apple file (M4A and converted FLAC) tells tag readers
  "disc 1 of 0" / DISCTOTAL=0, a false statement visible in any tag editor and
  a contradiction of the writer's own unknown-total rule.
- proposed change: Stop inventing a disc total: write the MP4 `disk` pair
  only when a real total is known (or omit the total), and drop FLAC
  `DISCTOTAL` when it is 0, mirroring TRACKTOTAL. Route the choice through
  the existing `Metadata` contract so both providers agree.
- acceptance criteria:
  - [ ] Apple M4A with no volume count carries no `disk` atom (or a pair
        without 0); FLAC carries no `DISCTOTAL`.
  - [ ] A real multi-volume album still writes the true total on both.
- evidence required to close: tag tests in `tests/metadata/`, strict suite
  green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

### META-02 - MP3 lyrics are written as a single 0 ms SYLT frame

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/metadata/tags.py:655-658` writes
  `SYLT(text=[(self.lyrics, 0)])` where `self.lyrics` is the synced LRC text
  (including its `[mm:ss.xx]` timestamps, `waves/download.py:4103-4104`). A
  timed-lyrics-capable reader therefore gets one frame at 0:00 containing the
  raw LRC markup, not per-line timing; USLT carries the unsynced text
  (`:659`). FLAC/MP4 write the same LRC text into a text field
  (`:604`, `:721`), which is the defensible shape.
- why it matters: MP3 output (TIDAL LOW, the only MP3 container the engine
  writes) gets a malformed-on-purpose sync frame while the sidecar .lrc is
  correct. Players that prefer SYLT show nothing or all lyrics at once, and
  the tagged file disagrees with the sidecar.
- proposed change: Only write SYLT when real per-line timing is available; for
  LRC-derived text write it to USLT/USLT-equivalent and leave SYLT unset.
  If SYLT is kept, parse the LRC into (text, ms) tuples first.
- acceptance criteria:
  - [ ] An MP3 tagged from synced LRC has no single-frame SYLT (or has one
        entry per lyric line with parsed timestamps).
  - [ ] USLT still carries unsynced text.
- evidence required to close: tag test, strict suite green.
- depends on / blocks: none.
- effort: S.
- needs human: no.

## Claims checked

- `docs/apple-music-provider-spec.md` "ffmpeg decode-to-null, always-on, never
  a setting": true on the main path. `decode_check` runs inside the engine
  (`engine.py:165-193`, `_verify_delivery` `:217-244`) and again in the runner
  (`runner.py:740-785`). Caveat: when a delivery carries a verified probe the
  runner trusts it (`runner.py:760-762`), and when no ffprobe exists the codec
  family check is skipped (`runner.py:767-768`) leaving only ffmpeg's decode.
- "Integrity failures retry automatically (2, 1 for outbreak-era)": true.
  `integrity_retries` (`integrity.py:384-397`) and the retry loop
  (`runner.py:1965-2036`); test `tests/downloads/test_apple_integrity_gate.py:639-643`
  asserts the numbers, `:789-819` asserts outbreak uses 2 fetches total.
- "Persistent failures land in Quarantine plus the skip-list": true;
  `runner.py:1994-2009` (quarantine_file + skiplist_add) and
  `integrity.py:194-208` (per-name numbering); tests
  `test_apple_integrity_gate.py:698-722` assert a kept file and the per-version
  skip-list.
- "Staging lives on another filesystem ... copy beside the target and rename":
  Apple side true (`files.py:703-720`). TIDAL side true: `_stage_and_swap`
  (`download.py:3775-3825`) fsyncs before rename; test
  `tests/downloads/test_stage_swap_durability.py:21-37` asserts the fsync.
- "Segment loop runs exactly once" (`tests/downloads/test_download_segment_loop.py:1-14`):
  true; `_download_segments` derives success from per-segment results
  (`download.py:854-938`); tests assert termination and the tail matrix.
- "The row-dict schema IS the catalog contract" (`base.py:381-387`): only
  half-true. It is documented (`base.py:24-98`) and pinned per provider by
  exact-dict tests (`tests/providers/apple/test_apple_provider_search.py:97`);
  no runtime validation exists (see PRV-01).
- "gamdl/N_m3u8DL-RE are pinned and the called members are checked": true
  locally. `tests/providers/apple/test_pinned_client_contract.py:20-56` checks
  the private members the engine calls, including
  `AppleMusicInterface._get_song_media` (`engine.py:255`). Structural only;
  it cannot catch a behavior change inside gamdl.
- "Wrapper image digest pin refuses a mutated registry copy"
  (`runtime.py:56-62`): partly true. A reported digest that differs raises
  (`runtime.py:897-902`); an unreportable digest is accepted and recorded
  `digest_ok: None` (`:912-913`), pinned by
  `tests/providers/apple/test_apple_runtime_wizard.py:1425-1437`. Fail-open is
  deliberate; noted as an Open question.
- "The package must stay UI-free": false in practice. No Qt import exists in
  `waves/download.py`, `waves/providers/`, or `waves/metadata/`, but
  `waves/model/gui_data.py:4-24` imports PySide6 into the engine import chain
  via `download.py:76` (PRV-04).
- "Windows legs parked" (ADR 0009, `docs/platform-enablement-review.md:114-116`):
  the CI leg definitions exist (`release-or-test-build.yml:57-58`) and the park
  is documented, but my subtree carries untested Windows paths:
  `os.name == "nt"` case folding (`integrity.py:62`), `.exe`/`ffprobe.exe`
  (`engine.py:159`, `runtime.py:157-158`), `chmod` on install
  (`runtime.py:819`),
  and the Docker `-v C:\...:/data` volume spelling
  (`supervision.py:450-460`). No audit claim can be made for those.
- "Quarantine is scan-excluded": true for the default and custom roots
  (`runner.py:813-821` registering, `integrity.py:139-191` sidecar of known
  roots); test `test_apple_integrity_gate.py:646-658`.
- "Ownership stays honest on quarantine: nothing is owned that isn't on disk"
  (`runner.py:954-955`): true in the runner; quarantine records bytes
  (`record_quarantine` `:960-981`) and does not call the ownership add path.

## Top 3

1. DL-01: DASH under-generation is detected and then ignored; a truncated file
   is reported done.
2. DL-02: Apple's file skip is identity-blind; a distinct colliding track is
   silently skipped.
3. DL-03 plus META-01: Apple replaces an occupant without proof and writes a
   knowingly false disc total; both are small, contained fixes in the newest
   pipeline.

## Release blockers

None at P0. DL-01 and DL-02 are P1 production-correctness work.

## Open questions

1. DL-01 fix shape: fail the item vs re-derive the URL list from the manifest.
   Recommended default: fail the item (the provider already proved the list
   short; re-derivation duplicates tidalapi's job).
2. Apple skip identity (DL-02): match TIDAL's id-aware skip exactly, or keep a
   "never delete/never overwrite" conservative skip for untagged files?
   Recommended default: id-aware, untagged still skips.
3. Windows legs (ADR 0009): re-examine the park now, or mark provider Windows
   support explicitly unverified for this release? Recommended default:
   re-enable the legs behind the documented exclusion recipe; if that fails,
   state the provider paths are untested on Windows in release notes.
4. Apple `totaldisc` (META-01): omit the disc pair entirely vs write the
   track/disc number without a total. Recommended default: omit the total, keep
   the number.
5. Wrapper image digest fail-open (`runtime.py:897-913`): keep tolerating an
   unreportable digest, or refuse when the runtime cannot report one?
   Recommended default: keep (already pinned by tests), surface `digest_ok`
   in diagnostics.
6. Quarantine growth: `apple_quarantine_keep` defaults on with no cap.
   Recommended default: keep default, document manual cleanup; a size cap is a
   post-release decision.

---

## Library, config, paths, redaction audit

Verdict: the sqlite index is carefully built and heavily tested; no silent-corruption bug was found in the scan itself.
Release-relevant defects: the ownership store keeps read handles open past `close()` (Windows factory reset leaves the database behind), a library root of `/` silently disables scanning, and corrupt-config recovery can die before any window exists.
Paths, constants and SMB recovery are otherwise solid; the redaction net has one demonstrable blind spot.

## Inventory

| path                        | lines | purpose (8 words max)                                 | depth   | verdict |
| --------------------------- | ----- | ----------------------------------------------------- | ------- | ------- |
| waves/library/index.py      | 3225  | sqlite album/folder cache, incremental resumable scan | deep    | finding |
| waves/library/ownership.py  | 972   | downloaded-copy record, live on-disk ownership        | deep    | finding |
| waves/library/worker.py     | 280   | scanner child process, JSON line protocol             | deep    | keep    |
| waves/library/smb_relist.py | 399   | fresh-mount relist of broken SMB listing              | deep    | finding |
| waves/library/netmount.py   | 206   | statfs origin, NetFS remount                          | deep    | keep    |
| waves/library/recover.py    | 101   | orchestrate untrusted-listing recovery                | deep    | finding |
| waves/library/**init**.py   | 6     | package marker, module re-exports                     | sampled | keep    |
| waves/config.py             | 932   | settings/token load-save, migrations, Tidal session   | deep    | finding |
| waves/paths.py              | 1756  | templates, sanitization, path budgets, uniquify       | deep    | finding |
| waves/constants.py          | 321   | tiers, provider names, template constants             | sampled | keep    |
| waves/errors.py             | 20    | download exception types                              | sampled | keep    |
| waves/ids.py                | 45    | namespaced id spelling                                | sampled | keep    |
| waves/redaction.py          | 226   | log scrubbing, runtime secret registration            | deep    | finding |

## Findings

### LIB-01 - OwnershipStore.close leaves other threads' read handles open

- severity: P1
- confidence: confirmed
- area: bug
- tags: [windows]
- evidence: `waves/library/ownership.py:361` creates `self._readers = local()` (a per-thread reader connection, `ownership.py:528-540`), but `close()` (`ownership.py:963-972`) closes only `self._conn` and the calling thread's reader. The scan cache hit this exact bug and fixed it with a weakref registry plus a full-collection close: `waves/library/index.py:838-847`, `index.py:2572-2582`, `index.py:3201-3225`, covered by `tests/library/test_library_index.py:2229` (`test_close_takes_every_thread_s_read_connection_not_just_its_own`). Ownership has no equivalent test (`rg -n "reader|close" tests/library/test_ownership_store.py` finds none). `factoryReset` closes the store then unlinks the named files: `waves/desktop/backend.py:21722-21725`, wipe list at `backend.py:671-673`, silent `os.remove` suppression at `backend.py:21751-21753`. Reader connections are live on `_own_pool` and download-worker threads (`backend.py:4898-4904`), which are not drained before that unlink.
- why it matters: on Windows an open sqlite handle refuses deletion, so the factory reset that promises to erase "the ownership store" leaves `ownership.sqlite3`, `-wal` and `-shm` on disk, holding every downloaded path. macOS/Linux unlink succeeds, so CI without Windows will not see it.
- proposed change: give `OwnershipStore` the same `_reader_refs` weakref set `LibraryIndex` has; `_read` registers each new connection, and `close()` closes every collected one before dropping this thread's. No behavior change to the read path.
- acceptance criteria:
  - [ ] a parked second thread that ran `ownership_of` has its connection closed by `close()`, verifiable by `sqlite3.ProgrammingError` on reuse
  - [ ] `close()` empties the registry
  - [ ] a factory-reset test asserts the three named ownership files are gone
- evidence required to close: new test mirroring `tests/library/test_library_index.py:2229` in `tests/library/test_ownership_store.py`, plus a factoryReset test run on a Windows CI leg showing the files absent.
- depends on / blocks: none
- effort: S
- needs human: no

### LIB-02 - A library root of "/" is silently turned into no library

- severity: P2
- confidence: confirmed
- area: bug
- tags: [windows]
- evidence: `waves/library/index.py:1139` (`refresh`), `index.py:1578` (`probe_folders`) and `index.py:2979` (`poll_containers_changed`) all do `root = os.path.expanduser(str(root or "")).rstrip(os.sep)`. On POSIX `"/".rstrip("/")` is `""`, and `_probe_root("")` returns `SCAN_UNSET` (`index.py:1075-1076`), so the scan returns immediately at `index.py:1157-1160`, the poll returns None, and probes refuse. Verified directly: `rstrip("/") -> ''`, `probe_root("") -> 'unset'`. `cache_file_for_root` also maps that empty key to the shared legacy `library.sqlite3` name (`index.py:417-425`). On Windows `"D:\\".rstrip("\\")` becomes `"D:"`, and `ntpath.join("D:", "Music") == "D:Music"` (verified), so the walk records drive-relative folder paths. The root is user-selectable through a native `FolderDialog` (`waves/desktop/qml/SettingsPage.qml:1320-1325`), which allows picking a volume root.
- why it matters: a user who points the library at a volume root gets badges that never light up, with `SCAN_UNSET` read as "no folder configured", and on Windows a cache full of drive-relative paths. `tests/library/test_library_index.py:188` covers the empty-string root, not `/`.
- proposed change: normalize with a helper that keeps a bare separator (`norm = expanduser(root); trimmed = norm.rstrip(os.sep); root = trimmed or norm`), and use it at the three sites. Keep `root_comparison_key` as is.
- acceptance criteria:
  - [ ] `refresh("/")` on a POSIX tmp-path monkeypatch of `_probe_root` reaches the walk, not `SCAN_UNSET`
  - [ ] `refresh("D:\\")` on Windows stores paths under `D:\\...`, not `D:...` (or the code explicitly refuses a bare drive root with a status)
  - [ ] the new test fails against the pre-fix lines
- evidence required to close: new test in `tests/library/test_library_index.py` named for the bare-separator root; Windows leg if available.
- depends on / blocks: none
- effort: S
- needs human: yes (whether a bare volume root is allowed or refused with a message)

### CFG-01 - Corrupt-config recovery can abort startup

- severity: P2
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/config.py:193-213`: the `except` calls `os.path.exists(path_bak)`, `os.remove(path_bak)` and `shutil.move(path, path_bak)` outside any guard. Only the later write-back `self.save(...)` is wrapped (`config.py:223-229`). A corrupt `settings.json` plus an unwritable config dir (or an existing `settings.json.bak` that cannot be removed) raises `OSError`/`IsADirectoryError` out of `Settings.__init__`, which runs inside the bridge constructor before QML loads (`waves/desktop/backend.py:5107-5121` documents that an exception there means no window; the corrupt case is described as self-healing at `config.py:217-229`).
- why it matters: the recovery path exists so a damaged config cannot brick the app; it currently can, in exactly the environment (locked/AV-held files on Windows) the atomic-write code already accounts for at `config.py:83-105`.
- proposed change: wrap the backup move in `try/except OSError` and fall through to the default model when the move fails (keep the file in place, log at WARNING). Do not change the JSONDecodeError branch order.
- acceptance criteria:
  - [ ] a `read()` over decodable-but-invalid JSON with `shutil.move` raising still returns False and leaves `data` at defaults
  - [ ] a `read()` with an unremovable `.bak` still constructs
- evidence required to close: new test in `tests/settings/` monkeypatching `shutil.move` to raise `PermissionError`.
- depends on / blocks: none
- effort: S
- needs human: no

### RED-01 - Cookie/Set-Cookie headers are only half redacted

- severity: P2
- confidence: confirmed
- area: security
- tags: []
- evidence: `_KV_SECRET`'s value class `[^\s'\"&;,]+` stops at the first `;` (`waves/redaction.py:74-82`). Running the real scrubber: `Cookie: session=abc123def456; csrftoken=SECRETSECRET; _ga=GA1.2.3` becomes `Cookie: ‹redacted›; csrftoken=SECRETSECRET; _ga=GA1.2.3`; `Set-Cookie: a=1; b=2` becomes `Set-Cookie: ‹redacted›; b=2`. No current INFO+ log site is known to emit cookie headers (root logger is INFO and third-party loggers inherit it: `waves/desktop/diagnostics.py:437-444`), so this is latent, not an observed leak.
- why it matters: the module's stated design is over-redaction, and the disk log plus the export bundle are attached to public issues (`redaction.py:1-12`). Any future or wrapper-side line that prints a cookie header (or an `http.client`/`urllib3` DEBUG line once verbosity changes) publishes every pair after the first.
- proposed change: after the `_KV_SECRET` pass, add one pattern for a labelled cookie header that replaces everything to end of line: `(?i)\b(set-cookie|cookie)\s*:\s*[^\r\n]+` -> `\1: ‹redacted›`. Keep the existing pattern for labelled keys.
- acceptance criteria:
  - [ ] a multi-pair Cookie and Set-Cookie header scrub to a single placeholder
  - [ ] `track: Secret Song` and other prose are unchanged
  - [ ] idempotence holds (re-scrubbing the result is a no-op)
- evidence required to close: new cases in the redaction test module (search `tests/` for the existing scrub coverage) asserting the exact strings above.
- depends on / blocks: none
- effort: S
- needs human: no

### LIB-03 - worker.py's "parent only reads the cache" invariant is false

- severity: P3
- confidence: confirmed
- area: docs
- tags: [refactor]
- evidence: `waves/library/worker.py:11-14` states the app process "only ever READS the cache ... this process is the one writer". `LibraryIndex.__init__` writes on every open: `UPDATE albums SET raw_count = track_count` (`index.py:913`), `UPDATE dirs SET mtime = 0` (`index.py:1018-1030`), `_meta_set` (`index.py:1031`, `index.py:1054`), and the `@eaDir` prune with `DELETE FROM dirs/albums/tracks` (`index.py:1042-1053`). Every `_open_library_index` therefore opens the same sqlite file for writing (`waves/desktop/backend.py:5105-5135`), and on a root respelling it opens the SAME file as the still-running child (same root key, `index.py:418-425`) before cancelling the worker (`waves/desktop/bridge_library.py:787-794`).
- why it matters: the single-writer claim is what callers reason from when deciding how the child and parent may share the file. Today SQLite WAL and the default busy timeout absorb the overlap, so the practical risk is low, but the invariant is not enforceable and a future long child transaction would surface as a busy error in a launch path the app cannot repair.
- proposed change: either correct the docstring to "the child is the only bulk writer; the parent runs schema/open migrations", or gate the write statements behind a "only when a marker is missing / only when not scanning" check and make the constructor read-only once the schema is current. Behavior-freeze: no change to what a scan writes.
- acceptance criteria:
  - [ ] the chosen wording/behavior is asserted by a test: a second read-only open of a current cache performs zero writes (e.g. assert no `meta` change and unchanged mtime), or the docstring is corrected
  - [ ] no scan-path behavior change
- evidence required to close: test or doc diff; cite the exact lines changed.
- depends on / blocks: none
- effort: M (behavior option) / S (doc option)
- needs human: yes (which direction)

### LIB-04 - playlist_duration tokens never resolve and stay literal in paths

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `waves/paths.py:882-886` handles `playlist_duration_seconds` / `playlist_duration_minutes` under `isinstance(media, Album)`, so a playlist never matches. `format_str_media` returns the token name when no formatter matches (`paths.py:600-634`), and `format_path_media` only substitutes when the result differs from the token (`paths.py:499-513`), so `{playlist_duration_minutes}` survives verbatim into the file name. The settings token list offers only track/album durations (`waves/desktop/backend.py:945-948`), so this is reachable only by a hand-typed template token.
- why it matters: a user who adds the token to the playlist template gets a literal brace token in every playlist file name and no error. It is a two-line fix before release.
- proposed change: narrow the branches to `Playlist | UserPlaylist` (drop the Album checks) and add the tokens to the settings list if they are meant to be public; otherwise delete the branches so the token renders as an unknown token the help page does not list.
- acceptance criteria:
  - [ ] a playlist template containing `{playlist_duration_minutes}` renders the duration, or the token is removed from `format_str_media` and documented as unsupported
- evidence required to close: unit test over `format_path_media` with a `Playlist`.
- depends on / blocks: none
- effort: S
- needs human: yes (keep or delete the token)

### LIB-05 - sweep_stale unmounts a live second instance's private mount

- severity: P3
- confidence: likely
- area: bug
- tags: [concurrency]
- evidence: private mount points are named by pid (`waves/library/smb_relist.py:280-292`), but `sweep_stale` unmounts every directory under `relist-mounts` without checking whether that pid is alive (`smb_relist.py:308-332`), and `recover_untrusted` calls it before every relist (`waves/library/recover.py:60-65`). Two instances are an explicitly contemplated shape in this codebase (`waves/config.py:146-154`). If the peer's mount is unmounted mid-read, `_read_dir_names` returns the empty mount point, `_accept` accepts it when the index holds no children for that target (`smb_relist.py:252-277`), and `recover_untrusted` can then record `note_listing_reconciled(True)` on a library that is still incomplete (`recover.py:88-94`; `listing_holds_all` is `all(...)` over an empty name list, `index.py:1488-1502`).
- why it matters: `last_listing_reconciled` is the difference between a Settings warning and a note, so a stale `True` hides a genuinely incomplete library. The trigger needs two instances plus timing, hence likely rather than confirmed.
- proposed change: have `sweep_stale` skip mount points whose embedded pid is a live process (same-user check sufficient: pid parse plus `os.kill(pid, 0)`), and only sweep dead pids and the base. Behavior freeze elsewhere.
- acceptance criteria:
  - [ ] a leftover pid directory is swept when its pid is absent
  - [ ] a pid-named mount point owned by a live process is left mounted
- evidence required to close: unit test with an injected `os.kill`/liveness probe.
- depends on / blocks: none
- effort: S
- needs human: no

### LIB-06 - Recovery probes cost one network stat per parent per name

- severity: P3
- confidence: confirmed
- area: perf
- tags: [perf]
- evidence: `recover_untrusted` flattens every recovered name into one list (`waves/library/recover.py:68-76`) and hands it to `probe_folders`, whose loops are `for parent in parents: for name in wanted: for spelling in candidates(name)` with an `os.stat` per iteration (`waves/library/index.py:1626-1660`). `parents` is every folder flagged unreliable (`index.py:1590`, `unreliable_dirs`), and the whole call holds `_scan_busy` (`index.py:1582`), so live badge probes return None for its duration.
- why it matters: on a big broken share (hundreds of flagged artists, hundreds of recovered names) this is tens of thousands of round trips inside the scan lock, extending the very stall the recovery exists to shorten. Correctness is unaffected.
- proposed change: pass the per-parent name mapping through instead of the flattened list, so each name is stat'd only under the parent it was recovered from (`recovered: {target: [names]}` is already that shape at `recover.py:61-65`). Behavior freeze: the same folders are found.
- acceptance criteria:
  - [ ] a name recovered from parent A is not stat'd under parent B
  - [ ] the existing recovery tests (`tests/library/test_smb_relist.py:340`, `:408`) still pass
- evidence required to close: a counting-stat test asserting the per-parent call count.
- depends on / blocks: none
- effort: S
- needs human: no

### CFG-02 - save()'s unchanged-skip can never fire

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `BaseConfig.save` compares `config_to_compare` (the raw file text) with `self.data.to_json()` (`waves/config.py:123-130`). `to_json()` emits single-line JSON (verified), while `write_serialized` writes with `indent=4` (`config.py:144-162`), so the two are never equal for a file this app wrote. Verified end to end: after `save()` wrote an indented file, `read()` on that unchanged file still invoked `os.replace` exactly once. This makes `read()`'s "write-back on change of code" (`config.py:217-229`) a full rewrite of settings.json and token.json on every launch, including the fsync.
- why it matters: every launch rewrites and re-syncs both files, and on a downgrade it re-serializes the model over a newer file each launch rather than only when something changed. No data is lost by the rewrite itself, but the skip the code documents is dead and the extra write is the sort of thing that grows into a real problem when someone relies on the comparison.
- proposed change: compare parsed structures, not text: `if config_to_compare is not None and self._canonical(config_to_compare) == self._canonical(data_json): return`, where `_canonical` is `json.dumps(json.loads(x), sort_keys=True)` inside a `ValueError` guard. Behavior freeze: identical decisions except the intended skip.
- acceptance criteria:
  - [ ] an unchanged re-read performs zero `os.replace`
  - [ ] a changed model still writes
- evidence required to close: test in `tests/settings/test_config_atomic_write.py` counting `os.replace` across an unchanged `read()`.
- depends on / blocks: none
- effort: S
- needs human: no

### CFG-03 - Factory reset leaves the migration sidecar behind

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `_MIGRATIONS_SIDECAR_NAME = "settings-migrations.json"` (`waves/config.py:249`) is written through a fixed temp name with no fsync (`config.py:286-294`), and it is absent from the factory wipe allowlists (`waves/desktop/backend.py:649-687`) and their log patterns (`backend.py:693-710`). A crash between the write and the replace strands `settings-migrations.json.tmp`, which no wipe pattern matches either.
- why it matters: the wipe claims to erase Waves' own config files; this Waves-owned file survives, and a stranded `.tmp` survives every future reset. Low impact on behavior (the next launch's defaults make the recorded steps no-ops) but it is a listed safety property that is not met.
- proposed change: add both names to `_FACTORY_WIPE_FILES`, and stage the sidecar through `tempfile.mkstemp` like every other config writer.
- acceptance criteria:
  - [ ] the factory wipe removes `settings-migrations.json` and a `settings-migrations.json.tmp`
  - [ ] the sidecar write leaves no fixed-name sibling
- evidence required to close: extend `tests/downloads/test_factory_reset_wipes_diagnostics.py` (or the settings wipe test) with both names.
- depends on / blocks: none
- effort: S
- needs human: no

### RED-02 - config.py prints bypass the redacting handlers

- severity: P3
- confidence: confirmed
- area: security
- tags: []
- evidence: `waves/config.py:210-213` prints the full backup path (which contains the username on macOS and Windows) to stdout; `config.py:816-885` print session state, and `config.py:894-911` call a caller-supplied `fn_print`. Log scrubbing is installed only on logging handlers (`waves/desktop/diagnostics.py:442-462`), so `print` output never passes through `waves.redaction`. A from-source run or a launcher that captures stdout publishes those lines unscrubbed.
- why it matters: the redactor exists to keep usernames, home paths and hosts out of anything a user attaches to an issue; the corrupt-config message is exactly what a user pastes when settings will not load.
- proposed change: route the corrupt-config message through `logger.warning` (the path there is already scrubbed by the handlers) and leave the interactive `fn_print` calls alone (they are a CLI login flow, not persisted).
- acceptance criteria:
  - [ ] the corrupt-config path emits no stdout line containing the config path
- evidence required to close: test that `read()` over a corrupted file logs at WARNING and prints nothing.
- depends on / blocks: none
- effort: S
- needs human: no

### LIB-07 - folder_names_under sorts an unindexed full table

- severity: P3
- confidence: confirmed
- area: perf
- tags: [perf]
- evidence: `waves/library/ownership.py:852` reads `SELECT path FROM downloads WHERE path IS NOT NULL ORDER BY recorded_at DESC` with no index on `recorded_at`, then filters in Python. The only index is `idx_downloads_track` (`ownership.py:384`). The one caller runs on a worker once per session (`waves/desktop/bridge_library.py:2340-2376`), on a store that keeps one row per (track, path) forever.
- why it matters: on a large library with years of downloads this is a full scan plus sort of the ownership table at every launch, on the session's most contended start-up. Cost only, no wrong answers.
- proposed change: add `CREATE INDEX IF NOT EXISTS idx_downloads_recorded ON downloads(recorded_at DESC)` in the constructor's schema block, or bound the query with `LIMIT` before the prefix filter and accept a slightly different seed order. Index first is the smaller change.
- acceptance criteria:
  - [ ] the query plan uses the new index (assert via `EXPLAIN QUERY PLAN` in a test)
- evidence required to close: test asserting the plan string contains the index name.
- depends on / blocks: none
- effort: S
- needs human: no

### LIB-08 - resource_path is dead

- severity: P3
- confidence: confirmed
- area: dx
- tags: [obsolete]
- evidence: `waves/paths.py:1723-1735`; `rg -n "\bresource_path\b" waves/ tests/` returns no call site outside the definition. (`path_file_numbered_candidate` and `url_to_filename` do have callers; `path_home` is used at `paths.py:175`.)
- why it matters: dead PyInstaller-era helper (`sys._MEIPASS`) in the module the Windows limbs must be reasoned about; it invites a wrong assumption about how resources resolve in the frozen build.
- proposed change: delete `resource_path`. Behavior freeze.
- acceptance criteria:
  - [ ] no references remain; `mise run check` clean
- evidence required to close: grep output in the PR description.
- depends on / blocks: none
- effort: S
- needs human: no

## Claims checked

| claim                                                                   | source                                     | true?                                                     | evidence                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the app process only ever READS the scan cache                          | `waves/library/worker.py:11-14`            | false                                                     | `LibraryIndex.__init__` writes on every open (`waves/library/index.py:913`, `index.py:1018-1054`)                                                                                                                                                                                                                             |
| ownership is never asserted from a row alone; the disk is re-checked    | `waves/library/ownership.py:5-13`          | true                                                      | `_best_surviving` gates on `_nonempty_file` before answering (`ownership.py:290-329`, `ownership.py:46-51`)                                                                                                                                                                                                                   |
| a physically truncated listing is detected and recovered                | `waves/library/smb_relist.py:1-45`         | true (mechanism), untested against real SMB in this audit | repeat detection `index.py:2055-2118`, fresh-mount verify `smb_relist.py:208-277`, recovery wiring `recover.py:48-100`                                                                                                                                                                                                        |
| macOS-only modules degrade to no-ops elsewhere                          | `netmount.py:17-19`, `smb_relist.py:39-41` | true                                                      | `netmount.py:80-81`, `netmount.py:188-189`, `smb_relist.py:87-90`, `smb_relist.py:363-364`                                                                                                                                                                                                                                    |
| an empty or offline library never wipes the cache                       | `index.py:1106-1107`                       | true                                                      | device-id ghost guard `index.py:1238-1248`, two-strike gap `index.py:1353-1383`; tests `test_library_index.py:1050`, `:1074`, `:1106`                                                                                                                                                                                         |
| `close()` releases every connection the cache handed out                | `index.py:3201-3225`                       | true for `LibraryIndex`                                   | `test_library_index.py:2229`                                                                                                                                                                                                                                                                                                  |
| the same for `OwnershipStore`                                           | `ownership.py:963-972`                     | false                                                     | LIB-01                                                                                                                                                                                                                                                                                                                        |
| `save()` skips the write when the config is unchanged                   | `config.py:126-130`                        | false                                                     | CFG-02                                                                                                                                                                                                                                                                                                                        |
| paths sanitize against Windows rules on every platform                  | `paths.py:324-327`                         | true for name components, false for `path_file_sanitize`  | `sanitize_name_component` uses pathvalidate's universal default (`paths.py:347`); `path_file_sanitize` passes `platform="auto"` (`paths.py:1229`, `:1243`, `:1253`), so on macOS it applies macOS rules only. Windows reserved names are handled by the universal pass (verified: `CON` -> `CON_`, `CON.flac` -> `CON_.flac`) |
| a broken listing only costs one mount per share per recovery            | `smb_relist.py:358-362`                    | true                                                      | grouping `smb_relist.py:372-383`; test `test_smb_relist.py:291`                                                                                                                                                                                                                                                               |
| the scanner child is killed on cancel and a superseded job returns None | `library_proc.py:251-258`                  | true                                                      | `backend.py` callers; test `test_library_worker.py:129`                                                                                                                                                                                                                                                                       |
| the parent's crash count is not burned by an intentional cancel         | `library_proc.py:82-87`                    | true                                                      | `library_proc.py:348-356`; test `test_library_worker.py:224`                                                                                                                                                                                                                                                                  |
| the factory reset only deletes allowlisted Waves files                  | `backend.py:528-534`                       | true by construction, incomplete by omission              | LIB-01 and CFG-03 are the two omissions found                                                                                                                                                                                                                                                                                 |

## Top 3

1. LIB-01: `OwnershipStore.close()` leaves other threads' read connections open, so the Windows factory reset does not remove `ownership.sqlite3` (P1, confirmed). The fix and its test already exist for `LibraryIndex`; the ownership store was never given the same treatment.
2. LIB-02: a library root of `/` (macOS volume root) or `D:\` (Windows) is mangled by `rstrip(os.sep)`; POSIX silently reports `SCAN_UNSET`, Windows records drive-relative folder paths (P2, confirmed).
3. CFG-01: corrupt-config recovery can raise `OSError` out of the bridge constructor on an unwritable config dir, so the app dies before a window exists instead of self-healing (P2, confirmed).

## Release blockers

- LIB-01 (P1): the Windows factory reset's promise is falsified while the database file survives.

## Open questions

1. Windows ship decision: LIB-01 and LIB-02 both have Windows-only halves. Recommendation: fix both before re-examining the park; neither needs a Windows machine (both are unit-testable with path fakes), only a Windows CI leg to prove the delete.
2. LIB-03 direction: correct the docstring or make the parent's cache opens read-only once the schema is current? Recommendation: correct the docstring now (S), open a follow-up for read-only opens.
3. LIB-04: keep `playlist_duration_*` tokens (fix and document them) or delete the dead branches? Recommendation: delete; the settings token list does not offer them.
4. CFG-02: is the launch-time rewrite of `token.json` acceptable? Recommendation: fix the comparison; a token file rewritten per launch is a needless window for a file lock to block startup.
5. LIB-05: is multi-instance support real for the SMB recovery path? Recommendation: add the liveness skip regardless; it is five lines and removes the only known path to a false `listing_reconciled`.
6. Apple credential registration: the Apple provider's `credential_facts()` returns `{}` (`waves/providers/apple/provider.py:608-609`), so the Apple side registers no token/cookie secrets. Recommendation: out of this section's ownership, but the redaction owner should decide whether Apple credentials need registration before release; no Apple log site emitting them was found.

---

## QML audit

80 QML files + 2 JS files, 36,090 lines, all flat in `waves/desktop/qml/`; 60% of the lines sit in 5 files (Main 11,345; SettingsPage 5,790; DownloadButton 1,965; QueueDrawer 1,334; LibSourceGroup 1,160).
The visual layer is consistent and heavily commented, but keyboard and screen-reader users cannot commit settings, act on queue rows, install updates, or pick a provider in the Chooser.
The dominant release risk is change cost, not visible breakage: an 11k-line Main.qml serving a 175-member untyped `host` API to 42 components, with 44 files carrying private copies of the palette.

## Inventory

| path                                  | lines | purpose (8 words max)                       | depth   | verdict  |
| ------------------------------------- | ----- | ------------------------------------------- | ------- | -------- |
| AlbumBlock.qml                        | 628   | album row with inline track expansion       | deep    | keep     |
| AlbumPresencePill.qml                 | 58    | album library-presence pill, scan-resolved  | sampled | keep     |
| Art.qml                               | 568   | shared square cover box, hover FX           | sampled | keep     |
| ArtCard.qml                           | 634   | art-first Browse card, hero variant         | sampled | refactor |
| ArtistBadges.qml                      | 263   | artist library-rollup badge strip           | sampled | keep     |
| ArtistLinks.qml                       | 87    | clickable comma-separated artist names      | deep    | keep     |
| ArtistSearchCard.qml                  | 120   | shared artist search-result card            | sampled | keep     |
| BackToTop.qml                         | 287   | scroll edge fades and back-to-top badge     | sampled | keep     |
| BigVideoThumb.qml                     | 188   | large 16:9 video result thumbnail           | sampled | keep     |
| BrowseCard.qml                        | 414   | console-style framed Browse card            | sampled | refactor |
| BrowseScroll.qml                      | 121   | shared Browse scroll pane, keep-alive       | deep    | keep     |
| BrowseSection.qml                     | 448   | one Browse content section renderer         | sampled | refactor |
| BrowseTile.qml                        | 477   | genre/mood/decade mosaic tile               | sampled | keep     |
| CardCaption.qml                       | 86    | card caption line: title, artists, meta     | deep    | keep     |
| Check.qml                             | 34    | small square checkbox, dumb                 | deep    | finding  |
| DecodeController.qml                  | 119   | matrix-decrypt paste driver for TextField   | deep    | keep     |
| DecryptText.qml                       | 51    | glyph-decrypting word for queue status      | deep    | keep     |
| DotBar.qml                            | 63    | DotMatrix copy for Settings scan bar        | deep    | delete   |
| DotMatrix.qml                         | 263   | LED dot-matrix progress grid                | deep    | keep     |
| DownIcon.qml                          | 328   | outlined terminal download icon states      | sampled | keep     |
| DownloadButton.qml                    | 1965  | download control plus Chooser popover       | deep    | refactor |
| ExpandChevron.qml                     | 81    | rotating chevron indicator                  | deep    | keep     |
| ExplicitMark.qml                      | 25    | explicit-content mono mark                  | deep    | keep     |
| FfmpegManager.qml                     | 79    | headless FFmpeg state holder                | deep    | keep     |
| FolderBadge.qml                       | 77    | folder Download-all count badge             | deep    | keep     |
| FolderTile.qml                        | 42    | playlist-folder glyph tile                  | sampled | keep     |
| GateAction.qml                        | 100   | shared full-width popup action              | deep    | keep     |
| GateCard.qml                          | 126   | tap-card option with title and chip         | deep    | keep     |
| HeartGib.js                           | 75    | settings footer pixel-heart easter egg      | sampled | keep     |
| HoverSwell.qml                        | 87    | hover outline swell effect                  | sampled | keep     |
| Ico.qml                               | 57    | Phosphor vector icon, no font dependency    | deep    | keep     |
| LedBar.qml                            | 126   | LED progress pill with label                | deep    | keep     |
| LibChip.qml                           | 51    | My Music strip chip                         | sampled | keep     |
| LibLibrarySection.qml                 | 397   | Library section: scan rows and empty states | deep    | finding  |
| LibList.qml                           | 82    | virtualised My Music list                   | sampled | keep     |
| LibPlaylistRow.qml                    | 127   | My Music playlist or folder row             | sampled | keep     |
| LibSourceGroup.qml                    | 1160  | one provider saved-shelf source group       | sampled | refactor |
| LibraryTag.qml                        | 144   | in-library presence pill                    | deep    | keep     |
| LibraryVerdict.qml                    | 84    | per-card library verdict                    | deep    | keep     |
| LogsDrawer.qml                        | 266   | realtime dev-log console drawer             | deep    | finding  |
| Main.qml                              | 11345 | app shell, pages, controllers, gates        | sampled | refactor |
| MosaicCell.qml                        | 63    | tile mosaic quadrant crossfade              | deep    | keep     |
| NavCrumbTrail.qml                     | 259   | app-wide breadcrumb pills                   | sampled | keep     |
| NavTab.qml                            | 376   | CRT-tube nav tab                            | deep    | keep     |
| NewTag.qml                            | 102   | recent-release mint dot mark                | deep    | keep     |
| OdoDigit.qml                          | 89    | odometer digit for folder badge             | deep    | keep     |
| PasteGlyph.qml                        | 127   | decrypt-fill clipboard glyph                | deep    | keep     |
| PlayBadge.qml                         | 73    | video play affordance strip                 | sampled | keep     |
| PlaylistBlock.qml                     | 514   | playlist row with inline expansion          | sampled | keep     |
| PopMeter.qml                          | 55    | two-row LED popularity meter                | deep    | keep     |
| PreviewArt.qml                        | 729   | artwork-as-play-button track preview        | sampled | keep     |
| PreviewBar.qml                        | 241   | full-width preview control bar              | sampled | keep     |
| ProviderBadge.qml                     | 37    | provider logo chip over artwork             | deep    | keep     |
| QualPick.qml                          | 442   | quality badge with tier menu                | sampled | keep     |
| QualPickRow.qml                       | 150   | one tier row of QualPick menu               | deep    | keep     |
| QualTag.qml                           | 172   | quality tier badge                          | deep    | keep     |
| QueueDrawer.qml                       | 1334  | sectioned download queue drawer             | deep    | finding  |
| QueueStack.qml                        | 43    | queued three-bar glyph                      | deep    | keep     |
| RemoteText.qml                        | 38    | PlainText-safe Text, never instantiated     | deep    | delete   |
| RetryMark.qml                         | 64    | vector retry arcs, icon only                | deep    | finding  |
| RiseIn.qml                            | 64    | Browse shelf entrance rise                  | deep    | keep     |
| RollSwap.qml                          | 145   | hover pill idle-to-live roll                | sampled | keep     |
| SearchProviderGroup.qml               | 773   | one provider search result group            | sampled | refactor |
| SearchSectionMore.qml                 | 23    | SHOW ALL toggle for search sections         | deep    | keep     |
| SectionHeader.qml                     | 118   | list section header with actions            | sampled | keep     |
| SettingsPage.qml                      | 5790  | schema-driven settings page                 | sampled | finding  |
| ShelfEdgeFades.qml                    | 89    | horizontal shelf edge fades                 | deep    | keep     |
| ShelfWheelRedirect.qml                | 31    | vertical wheel redirect for shelves         | deep    | keep     |
| ShowAllLabel.qml                      | 61    | SHOW ALL/SHOW LESS label control            | deep    | finding  |
| SnakeField.qml                        | 178   | snake circling loading label                | sampled | keep     |
| SpecBtn.qml                           | 133   | hugging outlined dialog action button       | deep    | keep     |
| StandalonePair.qml                    | 45    | standalone lyrics and art actions           | sampled | keep     |
| StatusLight.js                        | 14    | provider status-light colour vocabulary     | deep    | keep     |
| TrackPresencePill.qml                 | 46    | track twin of album presence pill           | deep    | keep     |
| TrackPreview.qml                      | 232   | compact ascii preview toggle for rows       | deep    | keep     |
| TrackRow.qml                          | 354   | full track row, search and artist           | sampled | keep     |
| VideoCell.qml                         | 150   | art-first 16:9 video result cell            | sampled | keep     |
| VideoThumb.qml                        | 63    | small square video thumbnail                | deep    | keep     |
| WaveMark.qml                          | 346   | ASCII ocean-wave logo                       | sampled | keep     |
| WelcomeBanner.qml                     | 276   | welcome banner with WaveMark parallax       | sampled | keep     |
| WelcomePicker.qml                     | 373   | first-run provider welcome and sign-in      | deep    | finding  |
| WireHint.qml                          | 145   | page loading hint surface                   | deep    | keep     |
| assets/providers/apple-music-dark.png | -     | Apple Music provider mark, dark             | sampled | keep     |
| assets/providers/apple-music.png      | -     | Apple Music provider mark                   | sampled | keep     |
| assets/providers/tidal-dark.png       | -     | TIDAL provider mark, dark                   | sampled | keep     |
| assets/providers/tidal.png            | -     | TIDAL provider mark                         | sampled | keep     |
| assets/wave_loop.mp4                  | -     | 8.9 MB looping background water video       | sampled | finding  |
| PHOSPHOR-LICENSE.txt                  | 31    | Phosphor icons MIT licence                  | sampled | keep     |
| icons/icon.icns                       | -     | macOS app icon                              | sampled | keep     |
| icons/icon.ico                        | -     | Windows app icon, multi-frame               | sampled | keep     |
| icons/icon16.png                      | -     | 16px app icon                               | sampled | keep     |
| icons/icon32.png                      | -     | 32px app icon                               | sampled | keep     |
| icons/icon48.png                      | -     | 48px app icon                               | sampled | keep     |
| icons/icon64.png                      | -     | 64px app icon                               | sampled | keep     |
| icons/icon256.png                     | -     | 256px app icon                              | sampled | keep     |
| icons/icon512.png                     | -     | 512px app icon                              | sampled | keep     |
| fonts/JetBrainsMono-Regular.ttf       | -     | bundled mono regular                        | sampled | keep     |
| fonts/JetBrainsMono-Bold.ttf          | -     | bundled mono bold                           | sampled | keep     |
| fonts/OFL.txt                         | -     | JetBrains Mono OFL licence                  | sampled | keep     |

File-count note: the brief says 80 QML/JS files; the tree holds 80 `.qml` plus 2 `.js` (82), 36,090 lines.

## Findings

### UX-01 - Settings save, update actions and gate choices are pointer-only

- severity: P1
- confidence: confirmed
- area: ux
- tags: [accessibility]
- evidence: `SettingsPage.qml:1373-1388` (CANCEL `Text` + `MouseArea`, no `Accessible`, no `Keys`, no `activeFocusOnTab`) and `SettingsPage.qml:1395-1422` (SAVE CHANGES identical); the page has exactly two accessible controls (`SettingsPage.qml:3495-3505` generic switch, `SettingsPage.qml:4001-4002` Apple skip). Update toast actions are the same shape: `Main.qml:10072-10116` (`utAct`, `MouseArea.onClicked` installs/restarts) with no name or tab stop, `Main.qml:10106-10158`. Video player controls: `Main.qml:4167-4230` quality picker, close and seek are MouseAreas; only Space (play/pause) and Esc exist as `Shortcut`s (`Main.qml:4003-4019`). Settings fields are focusable (SText wraps `TextField`, `SettingsPage.qml:1186-1206`), so the page is half reachable: a keyboard user can edit values and never apply them. 82 `Accessible.*` uses across 8 of 80 QML files; 208 `MouseArea` elements.
- why it matters: a keyboard-only or screen-reader user cannot save settings, cannot restart into an update, and cannot seek a video. The rest of the app is deliberately keyboard-workable (queue button, nav tabs, chooser rows all carry metadata), so this is an inconsistent hole on the two pages that commit state.
- proposed change: add one shared primitive (`qml/primitives/TapAction.qml`) that wraps the existing Text+MouseArea pattern and carries `activeFocusOnTab`, `Accessible.role/name/onPressAction` and Return/Enter/Space, then use it for SAVE CHANGES, CANCEL, the update-toast primary/secondary, and gate buttons. No behaviour change to the pointer path.
- acceptance criteria: [ ] SAVE CHANGES and CANCEL are Tab-reachable inside Settings and activate on Return/Space; [ ] update toast INSTALL/VIEW/RESTART/LATER/✕ are Tab-reachable and activate; [ ] each carries a non-empty `Accessible.name`; [ ] pointer behaviour, layout and copy unchanged.
- evidence required to close: an extended `tests/ui/test_accessibility_tree_qml.py` scenario that Tabs to SAVE CHANGES, asserts its name and `activeFocusOnTab`, and applies an edit; `mise run test-strict` green.
- depends on / blocks: none
- effort: M
- needs human: no

### UX-02 - Queue row actions, SHOW ALL, filter chips and log filters have no keyboard path

- severity: P1
- confidence: confirmed
- area: ux
- tags: [accessibility]
- evidence: `QueueDrawer.qml` has zero `Keys.`/`activeFocusOnTab`/`Accessible.`; per-row retry is `RetryMark` + MouseArea (`QueueDrawer.qml:695-706`), per-row cancel/remove is `Ico` + MouseArea (`QueueDrawer.qml:709-722`), row expansion is hover/DragArea only (`QueueDrawer.qml:476-488`). `ShowAllLabel.qml:48-60` is Text+MouseArea, and it is the only way to expand a capped search/artist section. Search type chips are Text+MouseArea (`Main.qml:6736-6776`). Logs level and FOLLOW chips are Text+MouseArea (`LogsDrawer.qml:126-162`, `164-190`). `Check.qml:26-32` emits `toggled` with no role; gate checkbox rows are pointer-only (`Main.qml:10850-10863`).
- why it matters: retrying one failed download, cancelling one row, expanding SHOW ALL and filtering log levels are all mouse-only. The accessibility scenario documents coverage of section-level CLEAR/RETRY ALL and the drawer close, which makes the row-level gap look covered when it is not.
- proposed change: adopt the UX-01 primitive for these controls; for queue rows add focus and Return/Delete handling mirroring `DownloadButton` (`DownloadButton.qml:213-234` is the existing model to copy, with `Keys.onDeletePressed` cancelling a queued row).
- acceptance criteria: [ ] Tab reaches a queue row, its retry mark and its cancel/remove control; Return retries, Delete cancels; [ ] each has `Accessible.name` naming the row; [ ] SHOW ALL, type chips, log chips and gate checkboxes are Tab-reachable with names and Space/Return activation.
- evidence required to close: extended accessibility scenario asserting the above on a seeded queue; `mise run test-strict` green.
- blocked by: UX-01 shared keyboard-control pattern.
- effort: M
- needs human: no

### UX-03 - Chooser provider tiles look selectable but are inert; CONTEXT.md says the user picks provider there

- severity: P1
- confidence: confirmed
- area: ux
- tags: [docs]
- evidence: `DownloadButton.qml:1325-1330` renders one tile per enabled provider with a `MouseArea { anchors.fill: parent; enabled: false; cursorShape: Qt.PointingHandCursor }`. No `chooserPickProvider` exists anywhere (`rg "chooserPick" DownloadButton.qml` returns `chooserPickTier`/`chooserPickAudio` only). The bridge docstring says the tiles are a segment display (`waves/desktop/backend.py:10026-10028`, `"providers": _chooser_provider_tiles(self, provider_id)`). CONTEXT.md: "Chooser: The per-download control where the user picks provider, audio quality, audio type, and lyrics/art options".
- why it matters: with both providers enabled, the Chooser draws a two-tile provider selector where the unselected tile cannot be chosen and is not even in the tab order or accessibility tree. The control advertises a choice that does not exist, and the domain doc claims it does.
- proposed change: either (a) make the tiles selectable and route the pick to the row's provider (needs a bridge slot; out of qml scope), or (b) render the provider as a static single chip (`ProviderBadge` plus name) and remove the unselected tiles, and correct CONTEXT.md. Recommend (b) for this release.
- acceptance criteria: [ ] no control in the Chooser shows a pointing-hand cursor without acting; [ ] the provider section states one provider, or picks; [ ] CONTEXT.md and code agree on one behaviour.
- evidence required to close: screenshot or QML source showing a single static provider line; `rg "enabled: false" DownloadButton.qml` empty; CONTEXT.md updated.
- blocked by: a bridge slot only if provider selection is the chosen behavior.
- effort: S
- needs human: yes (which behaviour ships: provider pick or static label)

### UX-04 - Type filter chips vanish for Apple-only (TIDAL signed-out) searches

- severity: P1
- confidence: confirmed
- area: ux
- tags: []
- evidence: `Main.qml:6736`: `visible: root.signedIn && root.hasResults && ...`; `signedIn` is TIDAL only (`Main.qml:19`, `waves.loggedIn`). Search itself is provider-neutral (`Main.qml:611`, `searchAvailable: signedIn || appleEnabled || searchEnabled()`), and the empty state is deliberately provider-neutral (`Main.qml:7665-7672`). Chip filtering itself works for Apple groups (`SearchProviderGroup.qml:168-170`, `2295`), and the Apple test drives `root.filterType` directly (`tests/ui/test_apple_only_search_qml.py:168-174`).
- why it matters: an Apple-only user with results gets no way to filter artists/albums/tracks/videos from the UI, so the type vocabulary exists and is unreachable for exactly the provider that is being shipped as the second Provider.
- proposed change: change the chip row's gate to the same `root.searchAvailable` used by the search field, or to `hasResults` alone.
- acceptance criteria: [ ] with TIDAL signed out and Apple enabled, a search shows the type chips; [ ] clicking each chip filters both providers' groups; [ ] TIDAL-only behaviour unchanged.
- evidence required to close: new scenario or extension of `tests/ui/test_apple_only_search_qml.py` asserting chip visibility `visible === true` and a filter click; `mise run test-strict` green.
- depends on / blocks: none
- effort: S
- needs human: no

### UX-05 - Sort direction control is unlabeled, keyboard-dead, and live when sorting is Relevance

- severity: P2
- confidence: confirmed
- area: ux
- tags: [accessibility]
- evidence: `Main.qml:6707-6724`: a 44px square whose only label is "↑"/"↓" in a `Text`, with a `MouseArea.onClicked` that flips `root.sortAsc` and persists `search_sort_asc`. At Relevance the arrow is dimmed to `root.textDim` (`Main.qml:6711`) but the click still fires, and `searchOrdered` reverses the API relevance order when `sortAsc` is true (`Main.qml:9075`). No `Accessible`, no `activeFocusOnTab`, no tooltip.
- why it matters: the dimmed state reads as disabled while the control mutates a persisted preference that also applies to Date/Name/Popularity later. A reader hears only "↑".
- proposed change: disable the control when `sortBox.currentIndex === 0` (and say why in a tooltip), give it `Accessible.name` ("Sort ascending/descending") and a tab stop, and stop persisting `sortAsc` on a relevance-only flip.
- acceptance criteria: [ ] control is inert and visually disabled at Relevance; [ ] Tab reaches it and Space/Return flips; [ ] accessible name reflects current direction; [ ] no `search_sort_asc` write while Relevance is selected.
- evidence required to close: source scan plus a scenario asserting `enabled === false` at index 0 and a persisted pref unchanged after a click.
- depends on / blocks: none
- effort: S
- needs human: no

### UX-06 - "Could not read your music folder" has no retry control

- severity: P2
- confidence: confirmed
- area: ux
- tags: []
- evidence: `LibLibrarySection.qml:187-206` (`statusText` returns "Could not read your music folder", `statusHint` returns "Reopen My Music to try again"), rendered by two static `Text`s at `LibLibrarySection.qml:336-362` with no button. The section reloads only on `librarySourceChanged` (`Main.qml:108-116`).
- why it matters: the only offered recovery is a manual navigation workaround, and the failure is not actionable at the point it is stated. Same shape for "Scanning your music folder…" (no progress or cancel) although `waves.libraryScanStatus` exists.
- proposed change: add a RETRY action to the `libFilesEmpty` branch calling the same reload path as `onLibrarySourceChanged` (`libSection.reset()` + refresh), and show the bridge's scan progress on the scanning line if a percentage is available.
- acceptance criteria: [ ] with the library folder unreadable, My Music shows a RETRY that re-runs the scan and clears the error when the folder returns; [ ] the hint no longer asks the user to reopen the page.
- evidence required to close: scenario seeding `unreadable` scan status then asserting the button exists and calls the reload slot.
- depends on / blocks: none
- effort: S
- needs human: no

### UX-07 - Bulk STOP/CLEAR discard queued and failed work with no confirm or undo

- severity: P3
- confidence: confirmed
- area: ux
- tags: []
- evidence: `QueueDrawer.qml:93-104` STOP calls `waves.stopAll()`; per-section CLEAR at `QueueDrawer.qml:214-224` calls `clearFinished`/`clearFailed`/`clearStopped`/`clearQueued` in one click, styled danger for the three destructive ones. No confirmation and no undo anywhere in the drawer. The exit path by contrast confirms (`Main.qml:10740-10870`).
- why it matters: one misclick on a section header discards a whole queue, including rows a user may still want; the app already has the confirmation vocabulary for comparable loss.
- proposed change: reuse the exit-gate confirmation for CLEAR on queued/stopped (or require a second click on the same header within a few seconds). Completed may stay one-click.
- acceptance criteria: [ ] CLEAR on queued/stopped/failed requires a confirm step; [ ] Completed CLEAR stays one click; [ ] STOP keeps one-click (it is the panic control) but says what will be lost.
- evidence required to close: scenario asserting the confirm gate appears and the queue survives a dismissed confirm.
- depends on / blocks: none
- effort: S
- needs human: yes (whether STOP also confirms)

### QML-01 - Main.qml concentrates unrelated UI behavior in one scope

- severity: P1
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `Main.qml` 11,345 lines / 468,734 bytes; `wc -l` ranks it first of 80 QML files and 31% of all QML lines. Named regions: property/controller head `1-1108`; preview/video/peek engines and models `1109-4700`; queue model and ledger `4700-6100`; header `6136-6854` (`consoleHeader`, includes search tier `6403-6854`); Browse panes `6855-7758`; search results `7607-7758`; artist page `7759-8217`; settings/library mounts `8218-8358`; status bar `8359-9010`; gates/overlays `9118-10879`; boot sequence `10880-11345`. 338 functions and 465 top-level definitions in one scope.
- why it matters: every UI change collides in one file and one scope. There is no seam to test a surface in isolation, no way to review a Browse change without reading the queue model, and the plaintext guard treats Main.qml as the one TIDAL render surface, so its growth is also the security surface's growth.
- proposed change: use the region map as design input. Pilot one low-coupling surface, such as boot sequence or one gate, after declaring its inputs and outputs. Keep `objectName`s and visible behavior stable, but do not standardize new components on the existing 175-member untyped `host` surface.
- acceptance criteria: [ ] an approved pilot identifies its explicit inputs, outputs and test owner; [ ] no new engine warnings; [ ] existing behavior and accessibility scenarios stay green; [ ] the pilot reduces access to Main.qml state rather than only moving lines.
- evidence required to close: approved design, pilot diff, dependency comparison, focused QML scenarios and `mise run test-strict`.
- blocked by: none.
- related: coordinate the pilot with QML-02.
- effort: L
- needs human: yes (approve a multi-PR refactor before release, or defer to post-release)

### QML-02 - 42 components depend on an untyped 175-member host object

- severity: P1
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: 42 files declare `required property var host`; components reference 175 distinct `host.*` members (`rg -o "host\.[a-zA-Z_]+" *.qml | sort -u | wc -l`); `Main.qml` defines 465 top-level `function`/`property` members. There is no interface file, no `qmldir`, no singleton; typos fail only at load (the reason `host` is `required`).
- why it matters: the host surface is the real API of every component and is invisible to any reader or tool. Renaming or removing a host method requires grepping 42 files, and each component's true dependencies are only discoverable by reading its whole body.
- proposed change: use a generated consumer report as temporary design evidence, not a new source of truth. For the QML-01 pilot, replace `required property var host` with the smallest explicit properties, signals or narrow feature object that the component needs. Standardize a grouped host object only after two consumers need the same boundary.
- acceptance criteria: [ ] the pilot's dependencies are explicit and checked by QML loading; [ ] no generated contract table is committed as a second API definition; [ ] a second migration reuses a narrow feature object only when the same boundary is real.
- evidence required to close: pilot and second-consumer diffs plus focused QML scenarios and `mise run test-strict`.
- blocked by: QML-01 pilot selection.
- effort: L
- needs human: yes (approve the typed ownership boundary)

### QML-03 - Palette literals are copied into 44 files with a "keep in step" comment

- severity: P2
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: 44 QML files contain the literal `"#3dff6e"` as a local `readonly property color accent`; the convention is stated in-file, e.g. `Check.qml:4-5`, `RetryMark.qml:8`, `DotMatrix.qml:6-7` ("keep them in step if the palette changes"). No singleton exists; `Main.qml:156-200` holds the canonical palette. `tests/ui/test_qml_color_literals.py` exists to police literals, so a change is already twice-enforced.
- why it matters: a palette change is a 44-file edit, and nothing fails when one file is missed (the test checks the literal vocabulary, not that all files agree with Main.qml).
- proposed change: add `qml/primitives/Palette.qml` as a QML singleton (`pragma Singleton` + a `qmldir`), have each file import it and bind `accent: Palette.accent`, and delete the local copies. Behaviour-freeze: same values, no visual change. If the singleton cannot be proven safely, defer the change rather than creating a checked-in generator and a second representation.
- acceptance criteria: [ ] one source of truth for each palette token; [ ] no QML file contains a raw palette hex outside the singleton and the audited richtext spots; [ ] rendering unchanged.
- evidence required to close: `rg -l '"#3dff6e"' waves/desktop/qml` returns the singleton only; `mise run check` and `test-strict` green.
- depends on / blocks: none
- effort: M
- needs human: no

### QML-04 - RemoteText.qml is dead code with zero instantiations

- severity: P3
- confidence: confirmed
- area: dx
- tags: [obsolete]
- evidence: `rg -n "RemoteText" --glob '!*.pyc' .` outside `qml/RemoteText.qml` and the guard test returns nothing; no instantiation in any QML or Python file. Meanwhile remote strings use bare `Text` + `textFormat: Text.PlainText` (343 occurrences across the tree; 87 in Main.qml). Its own header (`RemoteText.qml:24-26`) says "Reach for RemoteText for new remote strings", and `tests/ui/test_qml_plaintext_guard.py:22-28` describes it as "the ergonomic shared default".
- why it matters: the documented safe default is not used anywhere, so the doc and the test describe a practice the code does not follow. A new contributor will follow the comment and introduce the first RemoteText instance, which is untested against any real caller.
- proposed change: either adopt it for the dynamic remote bindings in Main.qml and the components the guard marks remote, or delete the file and its dedicated test and let the structural PlainText rule stand alone. Recommend delete unless adoption is part of the PlainText cleanup.
- acceptance criteria: [ ] either RemoteText has at least one production instantiation and the guard still passes, or the file and its test are gone and the guard's structural tests still cover the files it listed.
- evidence required to close: `rg "RemoteText" waves/desktop/qml` result; `mise run test-strict` green.
- depends on / blocks: none
- effort: S
- needs human: yes (keep as the future default, or delete)

### QML-05 - DotBar.qml duplicates DotMatrix.qml

- severity: P3
- confidence: confirmed
- area: architecture
- tags: [refactor]
- evidence: `DotBar.qml:3-6` says it is "Main.qml's inline DotMatrix, as a standalone file", with the same grid maths (`DotBar.qml:17-25` vs `DotMatrix.qml:11-25`) and its own 20 Hz clock (`DotBar.qml:28-35`). Its only consumer is `SettingsPage.qml:4492`. `DotMatrix.qml` has 8 consumers and the shared host clock.
- why it matters: two copies of the download progress visual can drift, and the Settings scan bar is the one surface users compare against the download button.
- proposed change: use `DotMatrix` in SettingsPage with `rows: 4`, `dot: 3`, `gap: 2`, `maxCols: 0` and a local pulse feed (DotMatrix requires `ledPulse`/`shimmerPhase`/`queueEdgeHeld`; pass static values plus a local `pulse` timer if the breathe is wanted), then delete DotBar and update the guard's file list.
- acceptance criteria: [ ] Settings scan bar renders identically to the download matrix at the same percentage; [ ] DotBar.qml removed from the tree and from `TIDAL_DATA_FILES`.
- evidence required to close: side-by-side screenshots at 30%/100% plus `rg "DotBar"` empty; `test-strict` green.
- depends on / blocks: none
- effort: S
- needs human: no

### QML-06 - Minimum window 880x560 exceeds the logical screen on small high-DPI Windows displays

- severity: P2
- confidence: likely
- area: ux
- tags: [windows]
- evidence: `Main.qml:32-33`: `minimumWidth: Math.max(880, Math.ceil(headerRow.implicitWidth) + 44)`, `minimumHeight: 560`. The bridge clamps a restored frame to live screens (`waves/desktop/backend.py:12198-12221`) but cannot shrink below Qt's minimum. At 150% scaling a 1366x768 panel is 910x512 logical, so the 560px minimum is taller than the usable screen; at 175% (common default on 1366x768 and 1600x900 laptops) the logical width is 780, below the 880 minimum.
- why it matters: on Windows laptops at common scaling factors the app cannot fit the screen: the bottom bar or the right edge is off-display, with no way to shrink it. This matters whenever Windows support is enabled.
- proposed change: derive the minimums from the current screen's available geometry (`Screen.width`/`Screen.height` of the window's screen, times 0.9) with the current numbers as the floor cap, or add a compact mode below 900x600 logical. At minimum, lower `minimumHeight` toward the header plus one status row (about 420) and let the panes scroll.
- acceptance criteria: [ ] at 1366x768 with 150% scaling the whole window, including the status bar, is on screen; [ ] at 1280x800 with 125% scaling the default 1040x780 frame is clamped to fit; [ ] nothing accumulates a scrollbar in the reduced frame.
- evidence required to close: a Windows screenshot or `Screen.width/height` readback at 150% scaling with the window frame reported by `list_windows`.
- depends on / blocks: none
- effort: M
- needs human: yes (which layout degrades first at small logical sizes)

### QML-07 - The plaintext guard's file list misses 9 of 82 files

- severity: P3
- confidence: confirmed
- area: security
- tags: [tests]
- evidence: `tests/ui/test_qml_plaintext_guard.py:132-206` lists 73 files; the tree has 80 QML + 2 JS. Missing: `DotBar.qml`, `ExpandChevron.qml`, `FfmpegManager.qml`, `Ico.qml`, `LedBar.qml`, `RemoteText.qml`, `WireHint.qml`, `HeartGib.js`, `StatusLight.js`. I read all seven missing QML files: `WireHint.qml:107-108` and `LedBar.qml:115-118` already pin `textFormat: Text.PlainText`; `DotBar`, `ExpandChevron`, `FfmpegManager` and `Ico` hold no `Text` element at all, so the gap is currently inert. The file list is manual, and the test comment says "add any NEW bare remote-bearing component property to this list" (`test_qml_plaintext_guard.py:280-286`).
- why it matters: the guard is the only control on the zero-click beacon path, and it is fail-open for new files: a new component that renders a remote string and is not added to `TIDAL_DATA_FILES` is never scanned. Six of the nine missing files are shared primitives likely to gain text.
- proposed change: replace the hand list with "every `.qml` in the directory", and classify remote markers by file plus a small `LOCAL_ONLY_FILES` exception list (the current design already has that exception mechanism).
- acceptance criteria: [ ] adding a new `.qml` with a dynamic remote `text:` binding fails the guard without any list edit; [ ] existing allowlist behaviour and the deliberate-richtext anchors unchanged.
- evidence required to close: a temporary fixture file that fails the guard, plus `test-strict` green after removal.
- depends on / blocks: none
- effort: S
- needs human: no

### QML-08 - Test coverage is name-based for 76 files and load-based for almost none

- severity: P2
- confidence: confirmed
- area: tests
- tags: [tests]
- evidence: every `.qml` name is referenced somewhere in `tests/` except `DotBar.qml`, `ExpandChevron.qml`, `FfmpegManager.qml`, `LedBar.qml` (`rg` over `tests/**/*.py`). Only 13 test files resolve paths through `QML_DIR`, and only 24 distinct component files are ever loaded by path; the single whole-tree load is `tests/ui/test_qml_loads.py:43-125` (`Main.qml`, asserting 0 warnings). `tests/ui/test_qml_plaintext_guard.py` and `test_qml_color_literals.py` read files as text rather than loading them.
- why it matters: a component can stop loading (typo, bad import, renamed id) without any test failing as long as Main.qml still instantiates it, and four components have no test at all. This is a coverage map, not a test-code review; the tests agent owns the fix.
- proposed change: add a directory-wide load smoke test that instantiates each `.qml` in a minimal harness (or at least fails on a parse error), and add the four unreferenced files to it. Extend the `test_qml_loads` warning assertion to the full tree if the harness can carry it.
- acceptance criteria: [ ] a test enumerates `QML_DIR/*.qml` and loads each; [ ] a deliberate syntax error in any single component fails that test; [ ] the four unreferenced files are covered.
- evidence required to close: the new test name plus a red/green check with one injected syntax error; `mise run test-strict` green.
- depends on / blocks: none
- effort: M
- needs human: no

### QML-09 - Background video's visible binding is overwritten by its error handler

- severity: P3
- confidence: confirmed
- area: bug
- tags: []
- evidence: `Main.qml:1417` declares `visible: motionOn`; `Main.qml:1443` assigns `onErrorOccurred: visible = false`, which destroys the binding. The toggle path only survives because `onMotionBgChanged` imperatively re-writes `bgWave.visible = bgWave.motionOn` (`Main.qml:1462-1468`).
- why it matters: a media error permanently severs the declarative binding; any future read or binding on `bgWave.visible` sees a stale value, and the fallback works only through the side channel that exists today.
- proposed change: add a `property bool decodeFailed: false` set by `onErrorOccurred`, and make the visibility binding `motionOn && !decodeFailed`; clear `decodeFailed` on source change. No behaviour change to the current error path.
- acceptance criteria: [ ] error path hides the video and the motion toggle still restores it; [ ] no imperative write to a bound property remains for `bgWave.visible`.
- evidence required to close: scenario triggering `onErrorOccurred` then toggling the pref and asserting visibility; `test-strict` green.
- depends on / blocks: none
- effort: S
- needs human: no

### QML-10 - File-backed manifest strings feed StyledText spots

- severity: P3
- confidence: confirmed
- area: security
- tags: []
- evidence: the four ffmpeg attribution elements render `page.ff.status.source`, `source_url`, `source_license` with `textFormat: Text.StyledText` (`SettingsPage.qml:1772-1782`, `1990-2000`, `Main.qml:9865-9872`). Those values come from the on-disk install manifest (`waves/desktop/ffmpeg_manager.py:270-282` reads `self._manifest()`), which is written by the app but readable and writable by anything with local file access.
- why it matters: any HTML in that file is parsed and, for `<img src>`, fetched when the label paints; the guard classifies these spots local-only, which is true for the app's writable path but not for the file's contents. Low threat model, cheap fix.
- proposed change: render the manifest-derived text through RemoteText or `textFormat: Text.PlainText`, and keep StyledText only for the anchor markup the QML itself composes, escaping the interpolated values.
- acceptance criteria: [ ] no StyledText spot interpolates a value read from disk; [ ] attribution links still open the same URLs.
- evidence required to close: source scan of the four spots plus the guard's allowlist updated; `test-strict` green.
- depends on / blocks: none
- effort: S
- needs human: no

## Claims checked

| claim                                                                                                                | source                                                      | verdict                                | evidence                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "Chooser: the per-download control where the user picks provider, audio quality, audio type, and lyrics/art options" | CONTEXT.md                                                  | false for provider                     | `DownloadButton.qml:1325-1330` inert tiles; no `chooserPickProvider` in QML or Python                                                                                                                                |
| "RemoteText is the ergonomic shared default for new remote strings"                                                  | `RemoteText.qml:24-26`, `test_qml_plaintext_guard.py:22-28` | false in practice                      | zero instantiations repo-wide; 343 `Text.PlainText` pins instead                                                                                                                                                     |
| "DotBar is Main.qml's inline DotMatrix as a standalone file"                                                         | `DotBar.qml:3-6`                                            | true                                   | `DotMatrix.qml` exists as the shared version with 8 consumers; DotBar has one (`SettingsPage.qml:4492`)                                                                                                              |
| Plaintext guard "ZERO false negatives by design"                                                                     | `test_qml_plaintext_guard.py:15-30`                         | conditionally true                     | structural rule is remote-marker + dynamic-`text:` based, but only within a hand-maintained 73-file list (`test_qml_plaintext_guard.py:132-206`); 9 files unscanned (QML-07)                                         |
| Main.qml loads with zero engine warnings                                                                             | `tests/ui/test_qml_loads.py:121-125`                        | unverified                             | no test runs permitted in this audit; would be confirmed by `mise run test-strict -k qml_loads`                                                                                                                      |
| Accessibility scenario covers the primary controls                                                                   | `tests/ui/test_accessibility_tree_qml.py:1-25`              | true as scoped, incomplete in coverage | it names nav tabs, QUEUE button, one DownloadButton, drawer PAUSE/RESUME/STOP/close, section CLEAR/RETRY ALL, search field, Chooser rows; it does not cover SAVE CHANGES, queue row actions, chips, gates (UX-01/02) |
| Palette copies must be kept "in step"                                                                                | `Check.qml:4-5`, `RetryMark.qml:8`, `DotMatrix.qml:6-7`     | true, 44 files                         | `rg -l '"#3dff6e"'` = 44; no singleton                                                                                                                                                                               |
| The tree has 80 QML/JS files                                                                                         | audit brief                                                 | false                                  | 80 `.qml` + 2 `.js` = 82, 36,090 lines                                                                                                                                                                               |
| Motion background falls back safely on decode failure                                                                | `Main.qml:1443`                                             | true by side channel                   | error hides the video; toggle restored imperatively (`Main.qml:1462-1468`); binding itself is destroyed (QML-09)                                                                                                     |

## Top 3

1. UX-01/UX-02: keyboard and screen-reader users cannot save Settings, restart for an update, retry/cancel a queue row, expand SHOW ALL, or use the video controls. 82 `Accessible.*` uses in 8 of 80 files against 208 MouseAreas.
2. UX-03/UX-04: the Chooser's provider tiles are inert while CONTEXT.md says the user picks provider there, and Apple-only search loses the type filter chips.
3. QML-01/QML-02: 11,345-line Main.qml plus a 175-member untyped `host` API across 42 files. This is the change-risk ceiling for every other finding in this area.

## Release blockers

None (no P0).

## Open questions

1. Chooser provider selection: ship the static single-provider label (recommended, S) or add a bridge slot for provider choice? Owner: shell + docs.
2. Which Main.qml surface should prove an explicit dependency seam? Recommended default: one gate or the boot sequence. Do not schedule the wider split until that pilot reduces coupling.
3. Should `STOP` also confirm, or stay the one-click panic control? Recommended default: stay one-click, confirm only per-section CLEAR.
4. Should RemoteText be adopted or deleted? Recommended default: delete now; re-add with the PlainText cleanup if ever needed.
5. `assets/wave_loop.mp4` is 8.9 MB inside the QML tree; does the packaging leg need it re-encoded or excluded from an unused-asset copy? Owner: build agent (out of scope here, flagged).
6. Windows small-screen behaviour (QML-06): is a compact layout acceptable, or should minimums simply shrink? Recommended default: derive minimums from the current screen and keep layout unchanged.

---

## Build, CI and release audit

Verdict: the build recipe is deliberate and evidenced; the release path is not.
The eight-leg matrix includes two parked Windows legs whose current recipe has
not been revalidated, the release key is absent from this fork, and no tag or Release has ever been published from
`ranokay/waves`, so tag-to-Release has never executed. Hygiene (`mise clean`) is
missing while the local tree carries ~1.3 GB of removed-able caches.

## Inventory

| path                                         | lines               | purpose                                       | depth   | verdict                   |
| -------------------------------------------- | ------------------- | --------------------------------------------- | ------- | ------------------------- |
| tools/build_waves.sh                         | 160                 | One Nuitka recipe, flags, trim, inspect       | deep    | keep                      |
| tools/trim_qt_bundle.sh                      | 196                 | Remove unused Qt/QML modules from bundle      | deep    | keep (gap: BUILD-07)      |
| tools/prune_static_qml_plugins.py            | 84                  | Prune static-only QML plugins from build venv | deep    | refactor (BUILD-11)       |
| tools/select_build_legs.py                   | 45                  | Matrix leg selection for `only` filter        | deep    | keep                      |
| tools/sign_manifest.py                       | 42                  | Sign SHA256SUMS with CI key                   | deep    | keep                      |
| tools/waves_release_keygen.py                | 33                  | Generate Ed25519 release keypair              | deep    | keep                      |
| tools/inspect_bundle.py                      | 241                 | Forbidden-material and native-module gate     | deep    | keep                      |
| tools/launch_probe.py                        | 118                 | Manual render-loop gap probe                  | sampled | keep                      |
| tools/bundle_size_report.sh                  | 59                  | Stable per-build size table                   | deep    | keep                      |
| tools/build_appimage.sh                      | 65                  | Pinned appimagetool AppImage packaging        | deep    | keep                      |
| tools/lint_qml.sh                            | 41                  | qmllint gate                                  | sampled | keep                      |
| tools/format_qml.sh                          | 27                  | qmlformat wrapper                             | sampled | keep                      |
| tools/sync_star_history.sh                   | 72                  | Copy star chart from public repo              | sampled | keep (stale ref BUILD-12) |
| tools/appimage/AppRun                        | 6                   | AppImage entry point                          | deep    | keep                      |
| tools/appimage/waves.desktop                 | 8                   | AppImage desktop entry                        | deep    | keep                      |
| tools/wrapper-image/NOTICE + 3 licenses      | 283                 | Notices copied into wrapper image             | sampled | keep                      |
| .github/workflows/release-or-test-build.yml  | 642                 | Tag to signed published Release               | deep    | refactor (BUILD-01/02)    |
| .github/workflows/build-legs.json            | 60                  | Eight leg definitions                         | deep    | refactor (BUILD-01)       |
| .github/workflows/flatpak-build.yml          | 118                 | Flatpak bundle build and attach               | deep    | keep (gap BUILD-08)       |
| .github/workflows/master.yml                 | 55                  | Manual check + tests                          | deep    | finding (BUILD-05)        |
| .github/workflows/star-history.yml           | 34                  | Daily chart on public repo                    | sampled | keep                      |
| .github/workflows/wrapper-image.yml          | 289                 | Publish pinned wrapper image                  | sampled | keep (BUILD-09)           |
| .github/workflows/wrapper-upstream-check.yml | 78                  | Weekly upstream watch                         | sampled | keep                      |
| .github/actions/setup-env/action.yml         | 68                  | mise/uv setup with retry                      | deep    | keep                      |
| .github/dependabot.yml                       | 37                  | Weekly grouped bumps to develop               | deep    | keep                      |
| .github/wrapper-upstream.sha                 | 8                   | Pinned upstream wrapper SHA                   | sampled | keep                      |
| .github/FUNDING.yml                          | 1                   | Donation link                                 | sampled | keep                      |
| .github/ISSUE_TEMPLATE/\*.yml (4)            | 166                 | Issue forms                                   | sampled | keep (BUILD-14)           |
| packaging/flatpak/org.getwaves.Waves.yml     | 55                  | Flatpak manifest                              | deep    | keep                      |
| packaging/flatpak/README.md + 3 glue files   | 84                  | Build docs, desktop, metainfo, entry          | sampled | keep                      |
| mise.toml                                    | 67                  | Tools and task surface                        | deep    | finding (HYG-01)          |
| .gitignore                                   | 210                 | Ignore rules                                  | deep    | find (HYG-02)             |
| .gitattributes                               | absent              | not present                                   | n/a     | finding (HYG-02)          |
| pyproject.toml (build/packaging only)        | build backend, pins | deep                                          | keep    |
| assets/ plus star-history/ (10 files)        | 5168 KB             | README art, star chart                        | sampled | keep                      |
| dist/                                        | untracked, 1.1 GB   | local build trees                             | shallow | finding (HYG-02)          |

## Findings

### BUILD-01 - Windows legs sit in the release matrix and block signing

- severity: P1
- confidence: confirmed release-gate contradiction; current Windows build result unverified
- area: packaging
- tags: [windows] [ci]
- evidence: `.github/workflows/build-legs.json:45-58` defines both Windows legs; `.github/workflows/release-or-test-build.yml:224-225` iterates the selected legs and `:97-101` selects all eight for a blank `only`, which a release requires (`:142-146` refuses `only` + `release_tag`). `sign-manifest` needs the whole build (`:461`), so one failed leg skips it, and signing is what flips the draft live (`:543-558`). Last recorded attempts: runs `34928310777`, `34929398611`, `35019374456` all failed on `lazy_extractors` (`gh run view ... --json jobs`; `docs/evidence/platform-builds.md` at HEAD lines 44, plus `docs/platform-enablement-review.md:146-151` "Windows artifacts stay unpublished"; `:171` "revalidate then"). The `--nofollow-import-to` exclusion landed but no Windows run exists after it (`git show a2a13cd --stat` shows no Windows evidence; `gh run list -w release-or-test-build` newest Windows leg is 2026-09-15). `tests/packaging/test_ci_hygiene.py:193-197` requires both Windows legs to stay in the table, so the park and the matrix contradict each other.
- why it matters: a `v*` tag selects Windows despite the documented park. The post-exclusion result is unknown, so the tag could either prove the fix or spend hours before blocking signing.
- proposed change: dispatch `only=windows-x64,windows-arm64` on the candidate commit. If green, keep eight release legs and update the support claims. If red and Windows remains parked, make the existing build-leg configuration the executable source for release selection and have tests plus user docs derive their claims from it; do not add a second platform-status file.
- acceptance criteria: either (a) a Windows dispatch run at the RC SHA is green end to end including smoke-launch and floor steps, or (b) `select_build_legs.py` returns six legs for a blank release selection and a test pins that, and README/ADR 0009 stay truthful.
- evidence required to close: run URL with both Windows legs `success`, or a `mise run test-strict` run for the selector change plus the six-leg artifact set on the next dispatch.
- blocked by: none. Blocks publication until the supported-platform set is decided. Related to BUILD-03. needs human: yes, choose revalidate vs ship six.
- effort: M

### BUILD-02 - The release cannot be signed on this fork: WAVES_SIGNING_KEY absent

- severity: P0
- confidence: confirmed
- area: security
- tags: [release]
- evidence: `gh secret list --repo ranokay/waves` returns only `APK_AUTH_HEADER` and `APK_URL` (checked 2026-09-21); `gh api repos/ranokay/waves/actions/secrets` reports `total_count: 2`; the one environment (`copilot`) is unused by the workflow. `release-or-test-build.yml:487-496` hard-fails when the secret is blank. `gh release list --repo ranokay/waves` returns nothing and `git ls-remote --tags origin` is empty: no tag has ever been pushed and the create-release/sign/publish jobs have never run on the fork.
- why it matters: by design the updater refuses unsigned releases, so a tag push fails at signing and the draft is never published. `WAVES_SIGNING_KEY` also cannot be invented: the matching public key is baked into `waves/desktop/signing.py:34`.
- proposed change: add the release key as a fork secret (or publish from upstream, where the secret exists and the same public key is embedded: `iamprivacy/Waves` `waves/waves_ui/signing.py:32`). Decide which repository owns publication before tagging.
- acceptance criteria: `gh secret list` shows `WAVES_SIGNING_KEY`; one end-to-end tag (or dispatch with `release_tag`) produces a live Release carrying `SHA256SUMS` + `SHA256SUMS.sig`.
- evidence required to close: Release URL with the two manifest assets and a `sign-manifest` job URL.
- blocked by: publishing-owner decision. Blocks publication from the fork. needs human: yes, install the secret or move publishing upstream.
- effort: S

### BUILD-03 - Legacy macOS legs have never been built; their first run is the release

- severity: P1
- confidence: confirmed
- area: packaging
- tags: [macos]
- evidence: `docs/evidence/platform-builds.md` (HEAD lines 29-33): "Legacy floor-12 legs ... did not run here"; newest macOS evidence is the four regular legs only (`gh run view 35588929771`, filter `only=macos-intel,macos-apple-silicon`). The legacy recipe is `uv pip install --force-reinstall --no-deps pyside6==6.9.3 ... && WAVES_MACOS_MIN=12.0 bash tools/build_waves.sh` (`build-legs.json:22,29`), and the workflow's floor assertion (`release-or-test-build.yml:332-365`) has never been exercised at 12.0.
- why it matters: a first-time failure on either legacy leg fails `sign-manifest` (BUILD-01 mechanism) after the other six legs have burned their minutes.
- proposed change: dispatch `only=macos-intel_legacy,macos-apple-silicon_legacy` on the RC SHA (the documented substring rule also runs the regular twins) and record the run id in `docs/evidence/platform-builds.md`.
- acceptance criteria: both legacy jobs green with `Info.plist LSMinimumSystemVersion 12.0` and a healthy smoke-launch; Mach-O scan reports no file above 12.0.
- evidence required to close: run URL and the two artifact names.
- depends on / blocks: none. needs human: no (one dispatch).
- effort: S

### BUILD-04 - Fork builds self-update against upstream, not the fork

- severity: P1
- confidence: confirmed
- area: architecture
- tags: [release]
- evidence: `waves/desktop/updater.py:75` `REPO = "iamprivacy/Waves"`; the release guard only checks the string is non-empty (`release-or-test-build.yml:113-114`). Upstream already has a live `v0.1.30` with every asset name this workflow emits (`gh release view v0.1.30 --repo iamprivacy/Waves`) and the same embedded public key (fork `signing.py:34` equals upstream `waves/waves_ui/signing.py:32`). No Release exists on the fork (BUILD-02).
- why it matters: if `ranokay/waves` publishes, the shipped binaries resolve updates from `iamprivacy/Waves` and will offer upstream bundles (no Apple engine) while never seeing the fork's own release. The fork cannot test its own update path.
- proposed change: decide the publishing repo. Default: publish upstream (REPO stays), cut the fork's tag only as an artifact/rehearsal run. If the fork must publish, point `REPO` at the fork for the RC and revert before upstream merge, or disable the update check in RC builds.
- acceptance criteria: the RC's in-app update check resolves the Release it was installed from, or the RC is explicitly documented as non-updating.
- evidence required to close: a recorded update-check log naming the release tag and a verified `SHA256SUMS.sig`.
- blocked by: BUILD-02 publishing-owner decision. needs human: yes.
- effort: S

### BUILD-05 - The current test workflow has never run in CI

- severity: P1
- confidence: confirmed
- area: tests
- tags: [ci]
- evidence: `.github/workflows/master.yml:7-8` is `workflow_dispatch` only; the newest `master` run (`34928309207`, 2026-09-15) executed the pre-migration workflow (`git show b67bc72:.github/workflows/master.yml` line 33 `tox:`), while the uv/mise rewrite landed at `3879bdf` on 2026-09-18 (`git log -1 --format=%ci 3879bdf`). `mise run check`/`test-strict` jobs have never executed. Branch protection has no required checks (`gh api repos/ranokay/waves/branches/develop/protection`: `"contexts": []`), so nothing else substitutes.
- why it matters: the current automated test evidence is local; the CI path that runs the merge gate is unproven, including the Python 3.12/3.13/3.14 matrix.
- proposed change: dispatch `master` on the RC commit and record the run id in `docs/evidence/platform-builds.md`; do not add a per-push trigger (the repo's documented policy is manual-only, `test_ci_hygiene.py:290-308`).
- acceptance criteria: one green `master` run at the RC SHA with quality + all three Python versions.
- evidence required to close: run URL.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-06 - "Code scanning AI findings" is red on every PR from a bot error

- severity: P2
- confidence: confirmed
- area: dx
- tags: [ci]
- evidence: runs `35565083297` (#377), `35569806594` (#378), `35574360738` (#379), `35594427738`/`35596093844` (#380) all `failure` in 36-39 s. `gh run view 35596093844 --log` shows the failing step "Processing Request (Linux)" ending in `CAPIError: 400 The requested model is not supported` from GitHub's Autofind agent; no code finding is produced. #374-#376 passed the same check with the same diff shape. The check is not required (`contexts: []`), so PR #380 merged anyway.
- why it matters: a permanent red X on every PR trains reviewers to ignore a security-adjacent check, and the "AI findings" name reads as a real finding in the audit trail.
- proposed change: turn off Autofind in the GHAS code-scanning default setup (or pin the agent to a supported model) so the check reflects code, and record the reason in the issue tracker.
- acceptance criteria: the next PR's "Code scanning AI findings" run concludes success or does not start.
- evidence required to close: run list showing the check green or absent.
- depends on / blocks: none. needs human: yes, repo/org setting.
- effort: S

### BUILD-07 - Trim safety rests on a 15-second idle launch

- severity: P2
- confidence: confirmed
- area: packaging
- tags: [tests]
- evidence: `tools/trim_qt_bundle.sh:39-72` deletes QML modules, Controls styles and PySide bindings by deny-list; the only execution check is the offscreen smoke-launch (`release-or-test-build.yml:282-319`), which polls the process for 15 s with no interaction, plus `inspect_bundle.py` (native modules/signature) called from `build_waves.sh:156-159`. No test relates the QML import closure to the deny-lists: `grep -rn "QML_MODULES\|MODULE_TOKENS" tests/` finds nothing. Today's closure is 8 modules (QtQuick, QtQuick.Layouts, QtQuick.Controls.Basic, QtQuick.Shapes, QtQuick.Effects, QtQuick.Dialogs, QtMultimedia, QtCore), none denied, but a lazily loaded page importing a trimmed module would fail only in the field.
- why it matters: QML pages created by Loader are not loaded during the smoke window; a trimmed module used by one page ships broken.
- proposed change: add `tests/packaging/test_qml_trim_closure.py`: parse every `import` in `waves/desktop/qml/**` (and any `Loader.source`/`createComponent` targets), map each module root against the arrays in `trim_qt_bundle.sh`, and fail when an imported module is denied or a kept module is trimmed.
- acceptance criteria: the test fails when `QtQuick3D` is added to a QML file or when `QtQuick.Layouts` is added to `QML_MODULES`; passes on the current tree.
- evidence required to close: test name and a mutation check in the PR body.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-08 - Flatpak bundles are attached outside the signed manifest

- severity: P2
- confidence: confirmed
- area: packaging
- tags: [linux]
- evidence: `flatpak-build.yml:108-118` uploads `dist/waves_linux-*.flatpak` with `gh release upload` and no `.sha256` sidecar. `sign-manifest` gathers only `sha256-*` artifacts from its own run (`release-or-test-build.yml:469-474`), and a separate workflow's artifacts are not visible to it, so the manifest can never cover Flatpak. The flatpak workflow has never run on the fork (`gh run list -w flatpak-build` empty). Runtime pin `org.getwaves.Waves.yml:8` `26.08` exists on Flathub for x86_64 (verified against `dl.flathub.org/repo/summary`; aarch64 unverified).
- why it matters: the .flatpak is a release asset with no published checksum and no signature coverage, while every other asset has both.
- proposed change: until Flatpak joins the signed manifest, document it as outside that trust path. Then move the build into the release matrix or publish a `.sha256` sidecar covered by a signed manifest.
- acceptance criteria: README states the exception, or `SHA256SUMS` on a release lists the flatpak files.
- evidence required to close: README diff or a Release asset list.
- depends on / blocks: none. needs human: yes, scope decision.
- effort: S

### BUILD-09 - Third-party actions are not SHA-pinned in write-capable workflows

- severity: P2
- confidence: confirmed
- area: security
- tags: [supply-chain]
- evidence: `grep -rhn "uses:" .github/workflows` shows `docker/setup-qemu-action@v4`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/build-push-action@v7` by moving tag in `wrapper-image.yml` (`permissions: packages: write`, lines 47-49), while `jdx/mise-action` and `softprops/action-gh-release` are SHA-pinned. `gh api repos/ranokay/waves/actions/permissions` returns `"sha_pinning_required": false`. `actions/*` also use major tags in the release workflow (`contents: write`, secrets).
- why it matters: the release and wrapper-image pipelines hold signing keys and package-write tokens; a moved third-party tag is a direct path into published artifacts.
- proposed change: pin all third-party actions to full SHAs (Dependabot already watches the `github-actions` ecosystem, `.github/dependabot.yml:29-37`), or enable SHA-pinning enforcement in repo settings.
- acceptance criteria: no `uses:` in `.github/**` references a mutable tag; the release workflow still runs green on a dispatch.
- evidence required to close: grep output plus one green dispatch.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-10 - Every workflow edit colds the Nuitka cache on all legs

- severity: P3
- confidence: confirmed
- area: perf
- tags: [ci]
- evidence: cache key at `release-or-test-build.yml:249-259` hashes `release-or-test-build.yml` and `build-legs.json` alongside the real inputs. Measured: intel cold 39-41 min vs warm 24 min; `docs/evidence/platform-builds.md` records the second cold run at `d36ecb3` purely because the workflow file changed between dispatches.
- why it matters: comment-only workflow edits between RC and release recompile every leg, adding ~hours across eight legs for no object change.
- proposed change: key on build inputs only (`tools/build_waves.sh`, `tools/trim_qt_bundle.sh`, `build-legs.json`, `mise.toml`, `pyproject.toml`, `uv.lock`) and drop the workflow file itself; keep the same per-leg salt.
- acceptance criteria: a comment-only workflow change still restores the exact cache key, proven by a dispatch log line `Cache restored from key`.
- evidence required to close: two dispatch logs, one before and one after a comment-only edit.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-11 - prune_static_qml_plugins mutates the developer venv permanently

- severity: P3
- confidence: likely
- area: dx
- tags: [qt]
- evidence: `tools/build_waves.sh:115-121` runs `tools/prune_static_qml_plugins.py` with the venv interpreter on every build; `prune_static_qml_plugins.py:74-77` `shutil.rmtree`s matching directories inside the installed PySide6 tree. uv tracks installed distributions, not deleted files, so a later `uv sync --locked` is expected not to restore them (unverified; `uv` behavior was not run).
- why it matters: a local build can leave the shared dev venv without a QML module, and a later source run or QML test then fails for a reason unrelated to the app.
- proposed change: prune into a copy or stage the removal so it is reversible, or print an explicit warning plus the reinstall command (`uv sync --reinstall-package pyside6`), and note it in DEVELOPER.md.
- acceptance criteria: after a build, the project's qml tests still pass, and the script's output tells a developer how to restore the tree.
- evidence required to close: run the build, then the restore command, and show the module path returns.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-12 - Dangling references to RELEASING.md and release.sh

- severity: P3
- confidence: confirmed
- area: docs
- tags: [obsolete]
- evidence: `release-or-test-build.yml:161` calls the dispatch path "the documented fallback (RELEASING.md)"; no RELEASING.md exists (`git ls-files | grep -i releas` empty). `tools/sync_star_history.sh:12-13` says "release.sh publishes the tree of a ref"; no `release.sh` is tracked.
- why it matters: the release fallback is documented nowhere, so the person cutting the first release has to reconstruct it from workflow comments.
- proposed change: add a short RELEASING.md or fix both comments to point at the real procedure (dispatch with `release_tag`, guards, `only` refusal).
- acceptance criteria: every doc reference resolves; `rg "RELEASING|release\.sh"` returns only existing files.
- evidence required to close: link check or grep output.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-13 - Issue templates bypass the triage vocabulary

- severity: P3
- confidence: confirmed
- area: dx
- tags: [process]
- evidence: `.github/ISSUE_TEMPLATE/bug.yml:3` applies `labels: ["bug"]`, `feature.yml:3` `["enhancement"]`, `help.yml:4` `["help wanted"]`; the triage label set on the repo includes `needs-triage` (`gh label list --repo ranokay/waves`), but no template applies it.
- why it matters: new issues enter the tracker without the triage state the workflow expects, so the `needs-triage` queue misses them.
- proposed change: add `needs-triage` to each template's labels (keeping the category label).
- acceptance criteria: a test or manual check shows new issues carry `needs-triage`.
- evidence required to close: label list on a test issue.
- depends on / blocks: none. needs human: no.
- effort: S

### BUILD-14 - Local build matrix is undocumented; OrbStack covers Linux only

- severity: P3
- confidence: likely
- area: dx
- tags: [windows] [macos]
- evidence: `DEVELOPER.md:123-127` documents `mise run build` for the host platform only; no task builds or runs another platform. Nuitka does not cross-compile, it compiles with the running interpreter and Qt, so an apple-silicon host cannot produce the x86_64 macOS bundle and no macOS host can produce the Linux or Windows bundles. `build-legs.json:22,29` runs the legacy flavor only because it reinstalls a different PySide6 inside the same runner. OrbStack runs Linux containers and VMs on macOS and has no Windows guest toolchain. Task feasibility inside a container is unverified.
- why it matters: production artifacts need build smoke tests on every supported leg, and the only path today is a CI dispatch of 40 minutes to 6 hours per iteration. Contributors on macOS edit the Linux packaging scripts (`tools/build_appimage.sh`, `packaging/flatpak/`) with no local way to run them.
- proposed change: document the supported local build matrix in `DEVELOPER.md` (CI is the artifact truth; Linux x64 build and packaging smoke can run in an OrbStack container using the same `tools/build_waves.sh` and `tools/build_appimage.sh`; Windows and macOS intel stay CI-only). Optionally add an opt-in `mise run build-linux-container`. Do not add local Windows or Intel-mac builds.
- acceptance criteria: [ ] `DEVELOPER.md` names which legs can be built locally and which cannot, with the reason; [ ] either `mise run build-linux-container` produces `dist/waves_linux-x64.zip` plus an AppImage on an apple-silicon host inside the container, or the task is rejected with the reason recorded in the audit follow-up.
- evidence required to close: task transcript including `file` output for the produced ELF artifacts, plus the `DEVELOPER.md` diff.
- depends on / blocks: none. needs human: no.
- effort: S

### HYG-01 - `mise clean` is missing

- severity: P2
- confidence: confirmed
- area: dx
- tags: [hygiene]
- evidence: `mise.toml` has 10 tasks (lines 12-67) and no clean task; `rg "mise clean|mise run clean"` finds no reference. Measured repository-local residue: `dist/` 1.1 GB (`waves.build` 935 MB + `waves.app` 239 MB), `.venv` 1.3 GB, `.pytest_cache` 992 KB, `.ruff_cache` 3.2 MB and `.code-review-graph` 144 MB.
- why it matters: the RC workflow (build, test, repeat) leaves multiple GB per checkout, and the repo has no supported way to reclaim them.
- proposed change: add one repository-local `mise run clean` task that explicitly removes generated build output and caches: `dist/`, `build-dir/`, `flatpak-repo/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.code-review-graph/`, `*.qmlc` and `*.jsc`. Never use `git clean`; it would remove the deliberately local `packaging/aur/` and `packaging/winget/` directories. Do not delete `.venv` or global caches.
- acceptance criteria: `mise run clean` leaves `git status --porcelain` byte-for-byte unchanged, preserves local distribution-channel files, removes the listed generated paths, and is idempotent. A focused task test or sandbox transcript proves the behavior; the full gate remains subject to the intentional documentation-deletion policy.
- evidence required to close: before/after status and `du -sh` transcript plus the focused clean-task verification.
- depends on / blocks: none. needs human: no.
- effort: S

### HYG-02 - No `.gitattributes`; caches self-ignore instead of being listed

- severity: P3
- confidence: confirmed
- area: dx
- tags: [hygiene] [windows]
- evidence: `git ls-files .gitattributes` is empty; the repo has none. `.editorconfig` sets `end_of_line = lf` for editors only. `.ruff_cache/` and `.pytest_cache/` do not appear in `git status` because each carries its own `.gitignore` (`ls -la .ruff_cache/.gitignore`, `.pytest_cache/.gitignore`), so the root `.gitignore:54` lists only pytest. `.code-review-graph/` was appended at `.gitignore:209-210`. No `core.autocrlf` setting is shipped, and only bash on the Windows legs executes the checked-out scripts (`release-or-test-build.yml:226,261`).
- why it matters: a Windows checkout with `autocrlf=true` delivers CRLF to `bash tools/build_waves.sh`, `select_build_legs.py` and the shell heredocs. The Windows legs have never built, so this class of failure has never been observed (unverified, not a confirmed cause).
- proposed change: add a minimal `.gitattributes`: `* text=auto`, `*.sh text eol=lf`, `*.py text eol=lf`, `*.yml text eol=lf`, `*.json text eol=lf`, plus binary marks for `*.png`, `*.gif`, `*.icns`, `*.ico`, `*.AppImage`; add `.ruff_cache/` and `.mypy_cache/` to `.gitignore` for editors that do not read the inner files.
- acceptance criteria: `git check-attr -a tools/build_waves.sh` reports `eol=lf`; a Windows leg dispatch still builds (or the finding is closed as merged on the strength of the attribute).
- evidence required to close: `git check-attr` output; the existing Windows revalidation run covers the rest.
- blocked by: BUILD-01 platform decision. needs human: no.
- effort: S

## Claims checked

| Claim                                                                               | Verdict                           | Evidence                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A tag push builds every leg and publishes a signed Release                          | false today                       | No tags/Releases on the fork (`git ls-remote --tags origin`, `gh release list`); BUILD-01/02                                                                                                                                                                       |
| Blank `only` selects all eight legs; naming a legacy leg also runs its regular twin | true                              | `tools/select_build_legs.py:24-28`; pinned by `test_ci_hygiene.py:151-161`                                                                                                                                                                                         |
| Legacy macOS floor 12.0 is declared and statically asserted                         | true (never executed)             | `build-legs.json:22,29`, `build_waves.sh:33,147`, `release-or-test-build.yml:332-365`; legacy legs never ran (BUILD-03)                                                                                                                                            |
| Updater asset selection is consistent with CI naming                                | true                              | legacy token partition and sidecar pairing at `waves/desktop/updater.py:411-441`; `_MACOS_LEGACY_BELOW = 15` (`:103`) matches the regular floor; workflow emits matching names (`release-or-test-build.yml:409-414`) and attaches `SHA256SUMS`/`.sig` (`:556-558`) |
| AppImage toolchain is pinned by version and hash                                    | true                              | `build_appimage.sh:24-33`; both `appimagetool` 1.9.1 URLs return 200 and the downloaded SHA-256s equal the pins (`ed4ce8...4eb0`, `f0837e...9158`)                                                                                                                 |
| PyCryptodome natives are required, bundled and never trimmed                        | true                              | `build_waves.sh:79-98`, `inspect_bundle.py:68-81`, trim note `trim_qt_bundle.sh:159-169`, test `test_ci_hygiene.py:260-287`                                                                                                                                        |
| Flatpak runtime `26.08` exists                                                      | true for x86_64; arm64 unverified | `dl.flathub.org/repo/summary` lists `org.freedesktop.Platform/x86_64/26.08`; the flow itself never ran (BUILD-08)                                                                                                                                                  |
| The README states Windows is parked                                                 | true                              | `README.md:148,157`; ADR 0009 (HEAD) and `test_platform_claims.py:24-45`; contradicted by the live release matrix (BUILD-01)                                                                                                                                       |
| Linux evidence in `docs/evidence/platform-builds.md`                                | leg-level true, run-level caveat  | run `34928310777` linux-x64 job success 1h53m but the overall run is `cancelled` (concurrency), and the instant-success macOS jobs were step-skipped, as the file's reading note says                                                                              |
| `mise run test-strict` is the merge gate                                            | task exists; no CI gate           | `mise.toml:49-51`; branch protection has no required checks (`contexts: []`)                                                                                                                                                                                       |
| Docs evidence committed at #379/#380                                                | currently broken in this worktree | `git status` shows `docs/adr/*` and `docs/evidence/*` deleted (unstaged); `test_platform_claims.py` and `test_acceptance_evidence.py` fail against the working tree until restored                                                                                 |

## Top 3

1. BUILD-01: Windows legs are selected for publication despite being documented as parked; the current recipe has not been revalidated.
2. BUILD-02: `WAVES_SIGNING_KEY` is absent on the fork and no tag/Release has ever been cut here; the release path is untested end to end.
3. BUILD-03: the legacy macOS legs have never run and would first execute during the release.

## Release blockers

P0:

- BUILD-02 (no signing key on the fork; release path never executed).

Publication gate:

- BUILD-01 must be resolved by a post-exclusion Windows run or an executable six-leg publication policy.

## Open questions

1. Which repository publishes releases, `ranokay/waves` or `iamprivacy/Waves`? Default: choose the repository the updater already targets, and use the other only for clearly non-public rehearsal artifacts (BUILD-02/04).
2. Windows: revalidate the exclusion recipe now, or cut the RC with six legs? Default: dispatch `only=windows-x64,windows-arm64` first; ship six only if it fails and update README/ADR 0009/tests together.
3. Who installs `WAVES_SIGNING_KEY` (and optionally `TAP_PUSH_TOKEN`) on the fork, and is the existing key reused or rotated? Default: reuse the existing upstream key.
4. Build the legacy macOS legs before tagging? Default: yes, one dispatch.
5. Is the Flatpak bundle in scope for the signed release manifest? Default: out of scope until it joins the same signed asset pipeline, with the exception documented (BUILD-08).
6. `docs/adr/` and `docs/evidence/` are intentionally deleted in the shared worktree and the guards fail without them. Default: settle the documentation policy and update guards plus references as one deliverable; do not restore them incidentally.

---

## Tests and test harness audit

- 411 files, 107,775 lines, 396 test modules, 3,825 test functions; the suite is deliberate and unusually well documented, and most tests state the user-visible sequence they prevent.
- The gaps are in enforcement, not intent: the marker guard misses real Qt tests (TEST-01), one shipped Apple integrity branch has positive-only coverage (TEST-02), and 28 bridge slots plus 13 signals are named by no test (TEST-03).
- The offscreen harness cannot observe hover, paint, DPI or native chrome, and 107 files lean on fixed real-time waits; no CI leg runs the suite on macOS or Windows (TEST-04, TEST-10).

## Inventory

Depth: `deep` = read in full or near-full for this audit; `sampled` = docstring, test names and representative bodies read. Purpose is the first docstring line, cut to 8 words. Verdict `finding` means the file is cited in Findings.

Directory summary:

| dir               | files |  lines | notes                                       |
| ----------------- | ----: | -----: | ------------------------------------------- |
| tests/conftest.py |     1 |    204 | sandbox, markers, require-qml gate          |
| tests/account     |     1 |    209 | live-only, never in CI, 4 tests             |
| tests/downloads   |    58 | 14,256 | largest domain group                        |
| tests/library     |    38 | 16,584 | includes the 2,291-line library index suite |
| tests/metadata    |    36 |  8,700 | tag/path/naming rules                       |
| tests/packaging   |    23 |  4,958 | doc/CI/manifest claims guards               |
| tests/providers   |    27 | 12,010 | seam tests plus Apple runtime               |
| tests/settings    |    27 |  4,944 | settings persistence and schema             |
| tests/support     |    14 |  1,621 | shared doubles and the QML harness          |
| tests/ui          |   186 | 44,289 | QML scenarios plus bridge units             |

All rows, sorted by path:

| path                                                           | lines | purpose                                                                       | depth   | verdict |
| -------------------------------------------------------------- | ----: | ----------------------------------------------------------------------------- | ------- | ------- |
| pyproject.toml (pytest config only, lines 133-142)             |    10 | testpaths plus the six marker declarations                                    | deep    | finding |
| tests/account/test_live_account.py                             |   209 | Opt-in live account checks                                                    | sampled | keep    |
| tests/conftest.py                                              |   204 | Shared test doubles for the WavesBridge unit tests                            | deep    | finding |
| tests/downloads/test_apple_flac_matrix.py                      |   702 | FLAC format matrix: lossless stereo lands FLAC, the                           | sampled | keep    |
| tests/downloads/test_apple_integrity_gate.py                   |  1655 | Integrity gate: verify, retry, quarantine, skip-list (spec §6)                | deep    | finding |
| tests/downloads/test_apple_job_runner.py                       |  2020 | Apple job runner: queue entry, gates, delivery, events                        | deep    | keep    |
| tests/downloads/test_apple_runner_hooks.py                     |   184 | The Apple runner's neutral seam: one job through                              | sampled | keep    |
| tests/downloads/test_apple_standalone_fallback.py              |   109 | Standalone Apple destinations render through the shared path                  | sampled | keep    |
| tests/downloads/test_atmos_session_swap.py                     |   237 | The Atmos session swap must actually engage the                               | sampled | keep    |
| tests/downloads/test_breadcrumb_dump_limiter.py                |    50 | One breadcrumb trail per dump window across both                              | sampled | keep    |
| tests/downloads/test_collection_download_edges.py              |   241 | Four edge behaviours of a collection download                                 | sampled | keep    |
| tests/downloads/test_collection_download_loop.py               |   129 | The collection-download loop must terminate                                   | sampled | keep    |
| tests/downloads/test_collection_outcome.py                     |    73 | What a finished collection download reports as its                            | sampled | keep    |
| tests/downloads/test_degraded_delivery_verdict.py              |    85 | The degraded verdict is measured against the quality                          | sampled | keep    |
| tests/downloads/test_download_base_containment.py              |   108 | A formatted media path can never escape the                                   | sampled | keep    |
| tests/downloads/test_download_cancellation.py                  |   107 | (no docstring)                                                                | sampled | keep    |
| tests/downloads/test_download_delay_setting.py                 |   272 | The "Download delay" setting actually reaches the engine                      | deep    | finding |
| tests/downloads/test_download_error_redaction.py               |    63 | The text a failed download's OSError puts on                                  | sampled | keep    |
| tests/downloads/test_download_failure_paths.py                 |   239 | Failure paths in the segment downloader, the metadata                         | sampled | keep    |
| tests/downloads/test_download_false_done.py                    |   158 | A silent stream failure must not read as                                      | sampled | keep    |
| tests/downloads/test_download_file_operations.py               |   275 | (no docstring)                                                                | sampled | keep    |
| tests/downloads/test_download_gate_liveness.py                 |   264 | Reachability-gate liveness + held-download replay + makedirs retry            | sampled | keep    |
| tests/downloads/test_download_path_and_staging_limits.py       |   162 | Staging names and path fitting around a download                              | sampled | keep    |
| tests/downloads/test_download_queue_serial.py                  |    85 | The download queue runs ONE item at a                                         | deep    | finding |
| tests/downloads/test_download_segment_loop.py                  |   180 | The segment-download loop must terminate                                      | sampled | keep    |
| tests/downloads/test_download_start_readout.py                 |   173 | A download announces 0% before it announces running                           | sampled | keep    |
| tests/downloads/test_dual_download.py                          |   274 | Dual-download: Atmos alongside stereo                                         | sampled | finding |
| tests/downloads/test_dual_version_rollup_and_force.py          |   221 | Dual Version rows share one media id in                                       | sampled | keep    |
| tests/downloads/test_encrypted_stream_refused.py               |    99 | Encrypted streams are refused, never written out as                           | sampled | keep    |
| tests/downloads/test_factory_reset_strays.py                   |    69 | What a factory reset must take out of                                         | sampled | keep    |
| tests/downloads/test_factory_reset_wipes_diagnostics.py        |    62 | Factory reset wiping exported diagnostic bundles                              | sampled | keep    |
| tests/downloads/test_hls_playlist_fetch.py                     |    86 | HLS playlists must never be fetched by m3u8's                                 | sampled | keep    |
| tests/downloads/test_login_token_persist_listener.py           |    78 | How the redactor hears about session credentials                              | sampled | keep    |
| tests/downloads/test_long_playlist_failure_isolation.py        |   665 | A long playlist must not fail as a                                            | sampled | keep    |
| tests/downloads/test_merge_failure_handling.py                 |    65 | Merging when the target file will not open                                    | sampled | keep    |
| tests/downloads/test_merge_plan_lifecycle.py                   |   100 | When a stashed best-of-both merge plan survives and                           | sampled | keep    |
| tests/downloads/test_page_cache_save_integrity.py              |    66 | Page-cache saves that race a library cache mutating                           | sampled | keep    |
| tests/downloads/test_path_budget_and_staging_spelling.py       |   278 | Path-length budget and existing-spelling behaviour of the naming              | sampled | keep    |
| tests/downloads/test_path_suffix_budget.py                     |    76 | The path budget behind the unique suffix                                      | sampled | keep    |
| tests/downloads/test_playlist_full_albums.py                   |   410 | The playlist page's "Download full albums" queues each                        | sampled | keep    |
| tests/downloads/test_preparing_state.py                        |   125 | A click that is parked behind a prerequisite                                  | deep    | finding |
| tests/downloads/test_queue_clear_aborts_hold.py                |   309 | The queue's clear, remove and stop slots withdraw                             | sampled | keep    |
| tests/downloads/test_redownload_force.py                       |   205 | REDOWNLOAD and the upgrade verdict: when an owned                             | sampled | keep    |
| tests/downloads/test_refetch_group_unstick.py                  |   107 | A failed re-fetch must not strand a discography                               | sampled | keep    |
| tests/downloads/test_rollup_verdict.py                         |   230 | The one verdict behind the DOWNLOADED / IN                                    | sampled | keep    |
| tests/downloads/test_segment_pool_shared.py                    |    94 | One segment executor per download job, sized to                               | sampled | keep    |
| tests/downloads/test_shared_http.py                            |   102 | The segment-download HTTP session is process-wide (Download.\_shared_http)    | sampled | keep    |
| tests/downloads/test_signout_and_rollup_recovery.py            |   270 | Sign-out clears the spinner a superseded search worker                        | sampled | keep    |
| tests/downloads/test_stage_swap_durability.py                  |    78 | Durability and zero-byte gates around the stage-and-swap copy                 | sampled | keep    |
| tests/downloads/test_staging_name_budget.py                    |    47 | Staging names that fit beside a destination that                              | sampled | keep    |
| tests/downloads/test_startup_store_resilience.py               |   128 | Startup resilience of the config write-backs and the                          | sampled | keep    |
| tests/downloads/test_stop_during_the_reachability_gate.py      |   161 | STOP sticks even when it lands while the                                      | sampled | keep    |
| tests/downloads/test_symlink_to_track_safety.py                |   182 | Symlink-to-track mode must obey the same file-safety rules                    | sampled | keep    |
| tests/downloads/test_twin_late_skip.py                         |   184 | A playlist entry listed twice lands one file                                  | deep    | finding |
| tests/downloads/test_twin_late_skip_and_pause_gate.py          |   697 | Two in-flight twins, the late skip, and the                                   | deep    | finding |
| tests/downloads/test_unavailable_not_failed.py                 |   262 | A track TIDAL refuses to stream is skipped                                    | sampled | keep    |
| tests/downloads/test_unchanged_batch_query.py                  |   118 | The warm scan's unchanged-verdict pass costs one query                        | sampled | keep    |
| tests/downloads/test_version_aware_skip.py                     |   293 | Version-aware skip and ownership                                              | sampled | keep    |
| tests/downloads/test_windows_stem_trim.py                      |    54 | Stem trimming on Windows counts in the units                                  | sampled | keep    |
| tests/downloads/test_worker_latch_and_logout.py                |   345 | Busy-latch discipline in the browse/search workers, and sign-out              | sampled | keep    |
| tests/downloads/test_zero_byte_destination.py                  |   145 | A truncated leftover must not eat a track's                                   | sampled | keep    |
| tests/library/test_apple_quarantine_actions.py                 |   231 | Quarantine actions on a failed row: reveal and                                | sampled | keep    |
| tests/library/test_atmos_is_its_own_row.py                     |   194 | A Dolby Atmos release is its own row                                          | sampled | keep    |
| tests/library/test_atmos_never_overwritten.py                  |   232 | A Dolby Atmos file is never replaced by                                       | sampled | keep    |
| tests/library/test_atmos_only_and_duplicate_names.py           |   332 | Atmos-only tracks and colliding filenames                                     | sampled | keep    |
| tests/library/test_atmos_only_downloads_anyway.py              |   205 | An Atmos-only track downloads whatever the Atmos setting                      | sampled | keep    |
| tests/library/test_atmos_ownership_scale.py                    |   425 | A Dolby Atmos copy is judged on the                                           | sampled | keep    |
| tests/library/test_duplicate_playlist_entry_claim.py           |   114 | A playlist may list the same track twice                                      | sampled | keep    |
| tests/library/test_duplicate_track_delivered_snapshot.py       |   115 | A collection may list the same track twice                                    | sampled | keep    |
| tests/library/test_legacy_layout_preserved.py                  |   103 | An existing library keeps its folder and file                                 | sampled | keep    |
| tests/library/test_legacy_source_id_own_copy.py                |   257 | A merged track re-saved over a copy an                                        | sampled | keep    |
| tests/library/test_library_bridge.py                           |  1442 | Glue tests for the bridge's local-library scan family                         | sampled | keep    |
| tests/library/test_library_claim_gate.py                       |   204 | The library scan's bulk claim gate only fires                                 | sampled | keep    |
| tests/library/test_library_files_bridge.py                     |   311 | The Library section's bridge data (ADR 0007)                                  | sampled | keep    |
| tests/library/test_library_index.py                            |  2291 | Tests for the local music-library scanner (waves/library/index.py)            | deep    | finding |
| tests/library/test_library_item_id_scan.py                     |   412 | The scan carries each file's Waves item id                                    | sampled | keep    |
| tests/library/test_library_listing_truncation.py               |   728 | A directory listing the scanner cannot trust, and                             | sampled | keep    |
| tests/library/test_library_presence_match.py                   |  1613 | Unit tests for the album-presence matching core (waves.metadata.matching)     | sampled | keep    |
| tests/library/test_library_probe_fallback.py                   |   498 | The bridge's probe by name behind a badge                                     | sampled | keep    |
| tests/library/test_library_save_rescan.py                      |   174 | SAVE CHANGES starts a library scan only when                                  | sampled | keep    |
| tests/library/test_library_watch_classify.py                   |   110 | The local-vs-network classification behind the library file-watcher           | sampled | keep    |
| tests/library/test_library_worker.py                           |   389 | The library scanner process: its protocol, and the                            | sampled | keep    |
| tests/library/test_listed_date.py                              |   271 | A reissue shows the day it was really                                         | sampled | keep    |
| tests/library/test_mb_arbiter.py                               |   375 | Unit tests for the MusicBrainz arbiter (waves.metadata.mb_arbiter)            | sampled | keep    |
| tests/library/test_mb_overlay.py                               |   170 | The MusicBrainz arbitration OVERLAY: how a stored verdict                     | sampled | keep    |
| tests/library/test_ownership_bridge.py                         |   837 | Tests for the ownership recording wiring in the                               | sampled | keep    |
| tests/library/test_ownership_ceiling.py                        |   463 | The ownership gate converges at each track's achievable                       | sampled | keep    |
| tests/library/test_ownership_namespaces.py                     |   182 | Ownership rows are namespaced (§4.2 of the provider                           | sampled | keep    |
| tests/library/test_ownership_store.py                          |   297 | Tests for the download-ownership store (waves/library/ownership.py)           | sampled | keep    |
| tests/library/test_ownership_two_folders.py                    |   120 | Waves only ever looks for a downloaded copy                                   | sampled | keep    |
| tests/library/test_presence_memo.py                            |    95 | The badge slots answer repeat asks from a                                     | sampled | keep    |
| tests/library/test_restart_upgrade_baseline.py                 |   203 | Restart and upgrade from a released baseline                                  | sampled | keep    |
| tests/library/test_scan_provider_badges.py                     |   926 | Provider-aware library scan and badges                                        | sampled | keep    |
| tests/library/test_scan_publish_throttle.py                    |   100 | Mid-scan badge publishes are throttled; the rollup is                         | sampled | keep    |
| tests/library/test_share_remount.py                            |   366 | A network share macOS quietly ejected gets mounted                            | sampled | keep    |
| tests/library/test_sibling_scan_completeness.py                |   394 | A failed artist lookup must never be reported                                 | sampled | keep    |
| tests/library/test_smb_efficiency.py                           |   227 | Network-mount efficiency behavior of the download write path                  | sampled | keep    |
| tests/library/test_smb_relist.py                               |   537 | Recovering the folders an SMB mount refuses to                                | sampled | keep    |
| tests/library/test_stop_keeps_rows_and_stops_scans.py          |   641 | STOP ends a discography scan in flight, keeps                                 | sampled | keep    |
| tests/metadata/test_album_artist.py                            |   162 | The opt-in 'Clean album-artist tag' setting, at its                           | sampled | keep    |
| tests/metadata/test_apple_double_cleanup.py                    |   178 | AppleDouble (.\_\*) hygiene: strip xattrs after moves, keep                   | sampled | keep    |
| tests/metadata/test_apple_files.py                             |   355 | Apple file layout: template paths, collision names, tags                      | sampled | keep    |
| tests/metadata/test_artist_id_tag.py                           |   245 | A file carries the ids of the artists                                         | sampled | keep    |
| tests/metadata/test_default_template_keeps_legacy_folder.py    |   292 | A library built before 0.1.17 keeps its album                                 | sampled | keep    |
| tests/metadata/test_delisted_album_naming.py                   |   162 | Naming a song whose album TIDAL will not                                      | sampled | keep    |
| tests/metadata/test_dot_folder_keeps_its_name.py               |   115 | An album named "." gets a folder, and                                         | sampled | keep    |
| tests/metadata/test_edition_collapse.py                        |   219 | Unit tests for the opt-in "most complete edition                              | sampled | keep    |
| tests/metadata/test_edition_explicit_split.py                  |   489 | A clean cut and its explicit twin never                                       | sampled | keep    |
| tests/metadata/test_edition_merge.py                           |   729 | Unit tests for the 'best of both worlds'                                      | sampled | keep    |
| tests/metadata/test_edition_merge_gate.py                      |   107 | The setting-to-behaviour path for the 'best of both'                          | sampled | keep    |
| tests/metadata/test_emptied_title_keeps_its_folder.py          |   148 | A title made only of illegal characters still                                 | sampled | keep    |
| tests/metadata/test_filename_byte_length.py                    |   212 | 255 is a byte limit on real filesystems                                       | sampled | keep    |
| tests/metadata/test_filename_torture.py                        |   297 | A nasty-name battery over the four functions every                            | sampled | keep    |
| tests/metadata/test_generic_tag_family.py                      |   320 | Every new download answers "which item is this?"                              | sampled | keep    |
| tests/metadata/test_helper_camelot.py                          |   359 | Tests for Camelot wheel notation conversions                                  | sampled | keep    |
| tests/metadata/test_illegal_char_spacing.py                    |   113 | Stripping an illegal character must not leave its                             | sampled | keep    |
| tests/metadata/test_illegal_map_defaults_offer.py              |   324 | Recommended stand-ins: offered on the settings page, never                    | sampled | keep    |
| tests/metadata/test_illegal_replacement_map.py                 |   317 | Per-character stand-ins: one rejected character, one replacement              | sampled | keep    |
| tests/metadata/test_illegal_replacement_setting.py             |   225 | The illegal-character stand-in setting is safe and strictly                   | sampled | keep    |
| tests/metadata/test_lyrics_lrclib.py                           |   164 | LRCLIB lyrics lookup (waves/metadata/lyrics.py)                               | sampled | keep    |
| tests/metadata/test_lyrics_precedence.py                       |   460 | Source precedence + standalone actions (spec section 9.1)                     | sampled | keep    |
| tests/metadata/test_lyrics_sidecar_overwrite.py                |   118 | A hand-timed .lrc beside a track is the                                       | sampled | keep    |
| tests/metadata/test_merge_destination_sanitized.py             |   271 | A merge member owned in a folder the                                          | sampled | keep    |
| tests/metadata/test_merge_member_destination_drift.py          |   215 | A merge member is gated against the folder                                    | sampled | keep    |
| tests/metadata/test_merge_writes_album_playlist.py             |   452 | A best-of-both merge leaves the album's .m3u8 behind                          | sampled | keep    |
| tests/metadata/test_name_comparison_edges.py                   |   170 | Two names that are one file to the                                            | sampled | keep    |
| tests/metadata/test_overwrite_mode_collisions.py               |   435 | Colliding tracks stay distinct even when the run                              | sampled | keep    |
| tests/metadata/test_path_folder_candidates.py                  |    65 | The spellings an artist folder may have on                                    | sampled | keep    |
| tests/metadata/test_path_traversal.py                          |    55 | Remote-controlled media names must not escape the download                    | sampled | keep    |
| tests/metadata/test_provider_path_segment.py                   |   191 | Provider-separated download paths                                             | sampled | keep    |
| tests/metadata/test_replay_gain.py                             |   109 | ReplayGain tag writing: default-on, sentinel guard, and spec                  | sampled | keep    |
| tests/metadata/test_sidecar_ordering.py                        |   139 | The cover and the lyrics follow the audio                                     | sampled | keep    |
| tests/metadata/test_staging_path_length.py                     |    99 | The whole staging path is capped, not just                                    | sampled | keep    |
| tests/metadata/test_tag_truths.py                              |   291 | Tags may not claim what the download does                                     | sampled | keep    |
| tests/metadata/test_windows_path_length.py                     |    98 | The platform's path cap is checked on the                                     | sampled | keep    |
| tests/packaging/test_acceptance_evidence.py                    |    97 | The R-05 acceptance evidence resolves and stays secret-free                   | deep    | finding |
| tests/packaging/test_app_icon.py                               |    67 | Guards for the packaged app icon                                              | sampled | keep    |
| tests/packaging/test_bundle_inspection.py                      |   239 | The bundle inspector that enforces spec §10.1                                 | sampled | keep    |
| tests/packaging/test_caches_and_paging_guards.py               |   667 | Cache and paging guards for the bridge's library                              | sampled | keep    |
| tests/packaging/test_changelog_format.py                       |   105 | CHANGELOG.md format guard                                                     | deep    | finding |
| tests/packaging/test_ci_dependency_retry.py                    |    44 | The CI dependency install must retry                                          | sampled | keep    |
| tests/packaging/test_ci_hygiene.py                             |   308 | The update hygiene stays wired: Dependabot targets develop                    | deep    | finding |
| tests/packaging/test_ffmpeg_install_rollback.py                |   303 | Rollback and version-probe tests for the Waves FFmpeg                         | sampled | keep    |
| tests/packaging/test_ffmpeg_manager.py                         |   506 | Unit tests for the Waves in-app FFmpeg manager                                | sampled | keep    |
| tests/packaging/test_flatpak_manifest.py                       |    89 | The Flatpak channel stays minimal and wired                                   | sampled | keep    |
| tests/packaging/test_manifest_tail.py                          |   126 | A DASH track must not lose its genuinely                                      | sampled | keep    |
| tests/packaging/test_ocr_review_rules.py                       |    59 | OpenCodeReview's project rules keep QML and Markdown in                       | sampled | keep    |
| tests/packaging/test_package_version.py                        |    35 | The packaging metadata version must match the version                         | sampled | keep    |
| tests/packaging/test_platform_claims.py                        |    45 | The README's platform claims match what ships while                           | deep    | finding |
| tests/packaging/test_provider_spec_amendments.py               |    53 | The provider spec names the decisions that superseded                         | sampled | keep    |
| tests/packaging/test_qt_tests_carry_the_marker.py              |   196 | Every test that drives Qt or spawns a                                         | deep    | finding |
| tests/packaging/test_release_star_history.py                   |   222 | A release must not blank the star-history chart                               | sampled | keep    |
| tests/packaging/test_repository_docs.py                        |   195 | The repository's decision records and glossary stay complete                  | deep    | finding |
| tests/packaging/test_stale_refetch_and_settings_refresh.py     |   512 | Stale re-fetch and settings-refresh guards                                    | sampled | keep    |
| tests/packaging/test_updater_asset_selection.py                |   268 | The self-updater's asset selection + extraction                               | sampled | keep    |
| tests/packaging/test_updater_backup_keep.py                    |   620 | The self-updater and the bundle size report                                   | sampled | keep    |
| tests/packaging/test_updater_tree_swap.py                      |    51 | Updater tree swap confirming the executable before it                         | sampled | keep    |
| tests/packaging/test_wrapper_image_pins.py                     |   151 | The wrapper-image pipeline stays pinned to the app                            | sampled | keep    |
| tests/providers/apple/test_apple_alac_wrapper.py               |   487 | ALAC delivery via wrapper-v2 (spec §1, §4.3, §6)                              | sampled | keep    |
| tests/providers/apple/test_apple_catalog_backend.py            |   536 | (no docstring)                                                                | sampled | keep    |
| tests/providers/apple/test_apple_catalog_pages.py              |   495 | (no docstring)                                                                | sampled | keep    |
| tests/providers/apple/test_apple_download_seam.py              |   292 | Apple download seam: tier words, Atmos choice, facts                          | sampled | keep    |
| tests/providers/apple/test_apple_fetch_reuse.py                |   649 | E11 reuse: one verified probe, one gamdl stack                                | sampled | keep    |
| tests/providers/apple/test_apple_probe_responsive.py           |   104 | A slow Apple probe never freezes the window                                   | sampled | keep    |
| tests/providers/apple/test_apple_provider_disable.py           |   203 | Disabling Apple Music stops its work and leaves                               | sampled | keep    |
| tests/providers/apple/test_apple_provider_search.py            |   189 | (no docstring)                                                                | sampled | keep    |
| tests/providers/apple/test_apple_runtime_wizard.py             |  1952 | Managed runtime + setup wizard (spec section 2                                | sampled | keep    |
| tests/providers/apple/test_apple_setup_guidance.py             |   221 | Apple setup guidance                                                          | sampled | keep    |
| tests/providers/apple/test_apple_supervision.py                |   783 | Session supervision + pacing (spec §3)                                        | sampled | keep    |
| tests/providers/apple/test_pinned_client_contract.py           |    64 | The pinned clients the engine calls, checked without                          | sampled | keep    |
| tests/providers/test_bridge_catalog_seam.py                    |   889 | The bridge's catalog reads route through the Provider                         | sampled | keep    |
| tests/providers/test_bridge_session_seam.py                    |   783 | The Provider seam is the only road                                            | sampled | keep    |
| tests/providers/test_my_music_shelves.py                       |   363 | My Music's saved-shelf sources: labels, categories and the                    | sampled | keep    |
| tests/providers/test_provider_chooser_metadata.py              |   503 | The Chooser's answers come from provider metadata, not                        | sampled | keep    |
| tests/providers/test_provider_download_seam.py                 |   866 | The download pipeline routed through the Provider seam                        | sampled | keep    |
| tests/providers/test_provider_lights.py                        |   120 | The header's per-provider lights and Browse's availability                    | sampled | keep    |
| tests/providers/test_provider_logos.py                         |   221 | Official provider logos live in qml/assets/providers/ and are                 | sampled | keep    |
| tests/providers/test_provider_seam.py                          |  1348 | The Provider seam's TIDAL side, pinned to independent                         | sampled | keep    |
| tests/providers/test_welcome_provider_cards.py                 |    81 | The welcome surface's provider cards carry copy and                           | sampled | keep    |
| tests/providers/tidal/test_cached_login_resilience.py          |   230 | The cached-sign-in launch login (`WavesTidal.login_token`)                    | sampled | keep    |
| tests/providers/tidal/test_login_paste_privacy.py              |    91 | A mis-pasted sign-in field must never reach the                               | sampled | keep    |
| tests/providers/tidal/test_session_login.py                    |   256 | The cached-token launch login (`_try_token_login`)                            | sampled | keep    |
| tests/providers/tidal/test_signin_records_saved_credentials.py |   152 | A completed sign-in is recorded as saved, so                                  | sampled | keep    |
| tests/providers/tidal/test_signing.py                          |    67 | Unit tests for the release-signing primitives (pure crypto                    | sampled | keep    |
| tests/providers/tidal/test_signout_stops_the_queue.py          |    65 | Signing out ends the downloads first, on the                                  | sampled | keep    |
| tests/settings/test_atomic_json_writers.py                     |   123 | The app's own JSON files are written whole                                    | sampled | keep    |
| tests/settings/test_best_quality_defaults.py                   |    50 | Best quality out of the box                                                   | sampled | keep    |
| tests/settings/test_both_mode_collapses_the_losing_side.py     |   312 | With "both" asked for, the clean side is                                      | sampled | keep    |
| tests/settings/test_config_atomic_write.py                     |    55 | BaseConfig.save atomic write (crash-safe config files)                        | sampled | keep    |
| tests/settings/test_config_path.py                             |   163 | Platform-native config location + one-shot legacy migration                   | sampled | keep    |
| tests/settings/test_config_sandbox.py                          |    45 | The suite never reads or writes the config                                    | sampled | keep    |
| tests/settings/test_config_save_lock.py                        |    83 | A locked settings file on Windows must never                                  | sampled | keep    |
| tests/settings/test_config_write_async.py                      |   133 | Config saves leave the GUI thread; snapshots win                              | sampled | keep    |
| tests/settings/test_confirm_category_download_toggle.py        |    92 | The bulk-download confirm must be switchable back ON                          | sampled | keep    |
| tests/settings/test_default_audio_type.py                      |   111 | The Chooser one-click audio default                                           | sampled | keep    |
| tests/settings/test_lyrics_art_matrix.py                       |   241 | Lyrics & art matrix (spec section 9.1)                                        | sampled | keep    |
| tests/settings/test_per_provider_lyrics_art.py                 |   275 | Per-provider lyrics/artwork + one tag template                                | sampled | keep    |
| tests/settings/test_providers_settings_area.py                 |   701 | The two-axis Providers area and the Apple Music                               | sampled | keep    |
| tests/settings/test_quality_change_live.py                     |    90 | A saved audio-quality change must reach the tidal                             | sampled | keep    |
| tests/settings/test_quality_override.py                        |   395 | A per-item quality choice reaches the job it                                  | deep    | finding |
| tests/settings/test_quality_pinned_per_job.py                  |   420 | A download finishes at the quality it was                                     | sampled | keep    |
| tests/settings/test_search_surface_prefs.py                    |    97 | The search page's provider-keyed surface prefs                                | sampled | keep    |
| tests/settings/test_settings_cancel_stays_put.py               |    73 | CANCEL on the settings page discards edits without                            | sampled | keep    |
| tests/settings/test_settings_diagnostics_card.py               |    94 | Exporting a diagnostic report must not rewrite the                            | sampled | keep    |
| tests/settings/test_settings_field_defaults.py                 |   108 | Per-field "Restore default" data (Settings, string fields)                    | sampled | keep    |
| tests/settings/test_settings_help_text.py                      |    64 | Settings help text keeps its commas                                           | sampled | keep    |
| tests/settings/test_settings_migration_sidecar.py              |   169 | One-time settings migrations survive a downgrade and a                        | sampled | keep    |
| tests/settings/test_settings_place_memory.py                   |    48 | Settings remembers its shape: sections collapsed by default                   | sampled | keep    |
| tests/settings/test_settings_restore_default_binding.py        |    91 | Restore default must RE-BIND the field, never overwrite                       | sampled | keep    |
| tests/settings/test_settings_save_guard.py                     |   404 | Every settings save must undo the transient ffmpeg                            | sampled | keep    |
| tests/settings/test_update_check_failures.py                   |   142 | The legacy engine entry points' update-check behaviour                        | sampled | keep    |
| tests/settings/test_waves_quality_tiers.py                     |   365 | The Waves quality enum and per-provider quality settings                      | sampled | keep    |
| tests/support/**init**.py                                      |     8 | Shared test machinery: repository paths, process runners and                  | sampled | keep    |
| tests/support/audio_fixtures.py                                |    40 | Generated audio fixtures for the tag, path and                                | sampled | keep    |
| tests/support/browse_fakes.py                                  |   113 | Tidalapi-shaped fakes for the Browse item-page builders                       | sampled | keep    |
| tests/support/discography_fakes.py                             |   142 | Artist-discography download stand-ins shared by the discography tests         | sampled | keep    |
| tests/support/dispatch_stub.py                                 |   223 | Arm a partial WavesBridge stand-in with the queue                             | sampled | keep    |
| tests/support/library_fakes.py                                 |   240 | Library-bridge stand-ins shared by the library scan tests                     | sampled | keep    |
| tests/support/offline.py                                       |    35 | Keep offscreen Main.qml scenarios off the live TIDAL                          | sampled | keep    |
| tests/support/paths.py                                         |    15 | Repository paths, resolved from this file's own location                      | deep    | keep    |
| tests/support/provider_fakes.py                                |    96 | Provider stand-ins shared by the provider and bridge                          | sampled | keep    |
| tests/support/qml.py                                           |   346 | Offscreen QML scenario runner for the subprocess-based UI                     | deep    | finding |
| tests/support/qml_probe.py                                     |    37 | JS handed to QML scenarios that need to                                       | deep    | keep    |
| tests/support/search_fakes.py                                  |   197 | A bare stand-in for the bridge's search pipeline                              | sampled | keep    |
| tests/support/settings_fakes.py                                |    74 | Settings-schema stand-ins shared by the settings and provider                 | sampled | keep    |
| tests/support/updater_fakes.py                                 |    55 | Updater stand-ins shared by the updater test modules                          | sampled | keep    |
| tests/ui/test_accessibility_tree_qml.py                        |   612 | The accessibility tree of the primary controls                                | sampled | keep    |
| tests/ui/test_account_journey.py                               |   631 | The account-switch journey, end to end, offline                               | sampled | keep    |
| tests/ui/test_album_collapse_returns_the_view.py               |   281 | Collapsing an expanded album row brings the page                              | sampled | keep    |
| tests/ui/test_album_tracks_hover_prefetch.py                   |   146 | An album row's tracks are fetched on hover                                    | sampled | keep    |
| tests/ui/test_apple_only_search_qml.py                         |   356 | The search row is live with Apple enabled                                     | sampled | keep    |
| tests/ui/test_apple_quarantine_row_qml.py                      |   145 | The failed Apple row's quarantine actions work, and                           | sampled | keep    |
| tests/ui/test_apple_search_groups_qml.py                       |   189 | (no docstring)                                                                | sampled | keep    |
| tests/ui/test_apple_setup_journey_qml.py                       |   375 | The Apple setup path from the welcome card                                    | sampled | keep    |
| tests/ui/test_art_cache_immutable.py                           |    86 | A held cover is fresh, whatever the CDN's                                     | sampled | finding |
| tests/ui/test_art_hero_underlay.py                             |   323 | The item page hero paints the clicked card's                                  | sampled | keep    |
| tests/ui/test_artist_download_gate_qml.py                      |   197 | The artist surfaces offer a discography control only                          | sampled | keep    |
| tests/ui/test_artist_hover_prefetch.py                         |   199 | A pointer resting on an artist card has                                       | sampled | keep    |
| tests/ui/test_artist_page_hides_subset_editions.py             |   343 | An artist page hides the editions the discography                             | sampled | keep    |
| tests/ui/test_artist_releases.py                               |   158 | Unit tests for the discography 'Featured' vs 'Appears                         | sampled | keep    |
| tests/ui/test_artist_videos_download_all.py                    |   197 | The VIDEOS section's download-all queues the videos, and                      | sampled | keep    |
| tests/ui/test_ax_toggle_actions_qml.py                         |   303 | AX press and toggle reach the switches and                                    | sampled | keep    |
| tests/ui/test_back_navigation_filter.py                        |   164 | Back navigation input: the macOS swipe filter and                             | sampled | keep    |
| tests/ui/test_boot_fade_landing_park.py                        |   155 | The wordmark fade must not share its frames                                   | sampled | keep    |
| tests/ui/test_boot_handover_gate.py                            |   311 | The launch sequence must cover the Browse landing's                           | sampled | keep    |
| tests/ui/test_boot_input_shield.py                             |   121 | The launch screen is inert: nothing under it                                  | sampled | keep    |
| tests/ui/test_boot_library_scan_process.py                     |   133 | The launch library sweep runs in the scanner                                  | sampled | keep    |
| tests/ui/test_boot_paced_incubation.py                         |    94 | The boot-paced incubation controller can never leave incubation               | sampled | keep    |
| tests/ui/test_boot_quiet_window.py                             |   214 | Nothing new may run on the interpreter during                                 | sampled | keep    |
| tests/ui/test_boot_reveal_prewarm.py                           |   169 | The interface is painted before the launch zoom                               | sampled | keep    |
| tests/ui/test_boot_scroll_dressing_hidden.py                   |   110 | The launch screen is clean water: no scroll                                   | sampled | keep    |
| tests/ui/test_boot_shield_cursor_release.py                    |   190 | The boot shield must release the cursor the                                   | sampled | keep    |
| tests/ui/test_boot_version_drain_order.py                      |   148 | The launch handover plays its two beats in                                    | deep    | keep    |
| tests/ui/test_breadcrumb_navigation.py                         |   256 | App-wide breadcrumb trail: section scoping, trim-on-revisit, crumb jumps      | sampled | keep    |
| tests/ui/test_bridge_boot_isolated.py                          |   109 | A real bridge boots from isolated settings with                               | sampled | keep    |
| tests/ui/test_bridge_queue_and_cache_guards.py                 |   534 | Hermetic tests for the WavesBridge (backend.py) guards                        | sampled | keep    |
| tests/ui/test_browse_back_scroll.py                            |   243 | Back to Browse lands on your scroll position                                  | sampled | keep    |
| tests/ui/test_browse_card_dressing.py                          |   154 | A browse card carries its library verdict, and                                | sampled | keep    |
| tests/ui/test_browse_card_library_state.py                     |   232 | A browse card has to say what your                                            | sampled | keep    |
| tests/ui/test_browse_card_line_fits.py                         |   285 | The console card's bottom control line holds both                             | sampled | keep    |
| tests/ui/test_browse_card_openable.py                          |   594 | A browse card's cursor agrees with its click                                  | sampled | keep    |
| tests/ui/test_browse_category_resolve.py                       |   117 | Browse category resolve: a failure must never be                              | sampled | keep    |
| tests/ui/test_browse_console_wayfinding.py                     |   172 | The console-style Browse landing must reach the playlists-only                | sampled | keep    |
| tests/ui/test_browse_home_feed.py                              |   261 | Browse landing: the V2 home feed's personalized shelves                       | sampled | keep    |
| tests/ui/test_browse_item_prefetch.py                          |   413 | The item page (playlist / mix / album)                                        | sampled | keep    |
| tests/ui/test_browse_pool_hygiene.py                           |   362 | Thread hygiene in the browse region: pools that                               | sampled | keep    |
| tests/ui/test_browse_row_window.py                             |   207 | Track shelves on the Browse landing must actually                             | sampled | keep    |
| tests/ui/test_browse_strip_fits_the_card.py                    |   250 | The hover strip on a browse card stays                                        | sampled | keep    |
| tests/ui/test_card_progress_outline.py                         |   203 | A Browse card's running download bar keeps the                                | sampled | keep    |
| tests/ui/test_category_cache_freshness.py                      |    84 | A resolved Browse category must not be trusted                                | sampled | keep    |
| tests/ui/test_chooser_split_button.py                          |   578 | Chooser split button + popover (spec section 7.2)                             | sampled | keep    |
| tests/ui/test_cold_process_boot.py                             |   125 | A cold app launch boots, persists and rehydrates                              | deep    | keep    |
| tests/ui/test_cover_art_cache.py                               |   105 | One album, one cover fetch: the per-job art                                   | sampled | keep    |
| tests/ui/test_crash_log_scrubbed.py                            |   101 | crash.log must be scrubbed like every other log                               | sampled | keep    |
| tests/ui/test_dead_pair_and_qml_gating_guards.py               |    51 | Source guards against a dead bridge pair and                                  | deep    | finding |
| tests/ui/test_devlog_privacy_default.py                        |   191 | Tests for devlog's privacy-safe default                                       | deep    | keep    |
| tests/ui/test_diagnostics_content_marking.py                   |   176 | User content that is logged must be marked                                    | sampled | keep    |
| tests/ui/test_diagnostics_disk_thread.py                       |    99 | The on-disk log is written by its own                                         | sampled | keep    |
| tests/ui/test_diagnostics_occupancy.py                         |    79 | Guards for the verbose event-loop occupancy probe (diagnostics                | sampled | keep    |
| tests/ui/test_diagnostics_redactor.py                          |   217 | Zero-leakage tests for the diagnostics redactor                               | sampled | keep    |
| tests/ui/test_discography_atmos_off.py                         |   163 | With the Atmos setting off, a discography sweep                               | sampled | keep    |
| tests/ui/test_discography_video_source.py                      |   219 | 'Download discography' includes music videos when their source                | sampled | keep    |
| tests/ui/test_dual_version_queue_scenario.py                   |   208 | The dual-version queue stays honest per version                               | sampled | keep    |
| tests/ui/test_exit_warning_gate.py                             |   105 | The exit-while-downloading warning (exitGate)                                 | sampled | keep    |
| tests/ui/test_expand_spots_die_with_their_page.py              |    59 | A remembered scroll spot never outlives the page                              | sampled | keep    |
| tests/ui/test_factory_reset.py                                 |   408 | Advanced-settings reset actions                                               | sampled | finding |
| tests/ui/test_folder_back_navigation.py                        |   134 | Reopening an already-keyed browse page still records history                  | sampled | keep    |
| tests/ui/test_folder_badge_and_crumb_labels.py                 |   248 | Folder badge, odometer and breadcrumb labels, driven through                  | sampled | keep    |
| tests/ui/test_folder_gate_probe.py                             |    78 | Download-folder reachability gate (\_probe_folder_verdict): a set folder is   | sampled | keep    |
| tests/ui/test_folder_path_migration.py                         |    55 | The one-time format_playlist upgrade that added {folder_path}                 | sampled | keep    |
| tests/ui/test_folder_path_standins.py                          |    51 | A TIDAL playlist folder's name follows the stand-ins                          | sampled | keep    |
| tests/ui/test_folder_recovery.py                               |   284 | Unreachable-folder recovery watch: the app notices a returned                 | sampled | keep    |
| tests/ui/test_folder_rollup.py                                 |   329 | Folder "download all" rollup: track-weighted aggregate under the              | sampled | keep    |
| tests/ui/test_folder_tree_freshness.py                         |   146 | The cached folder tree must stay authoritative, and                           | sampled | keep    |
| tests/ui/test_folder_tree_warm.py                              |   224 | Nothing may silently give up because the folder                               | sampled | keep    |
| tests/ui/test_forward_history_account_switch.py                |   220 | An account switch must drop navForwardHistory too, not                        | sampled | keep    |
| tests/ui/test_freeze_watchdog_quit.py                          |   185 | The freeze watchdog must not invent a freeze                                  | deep    | keep    |
| tests/ui/test_gates_sit_above_drawers.py                       |   132 | Full-screen gates sit in the window's overlay layer                           | sampled | keep    |
| tests/ui/test_group_progress.py                                |   110 | The album/playlist roll-up bar folds in-flight track fractions                | sampled | keep    |
| tests/ui/test_gui_thread_and_lock_hygiene.py                   |   145 | Network work must not run on the GUI                                          | sampled | keep    |
| tests/ui/test_held_download_release.py                         |   568 | The bridge's half of the held-download path                                   | sampled | keep    |
| tests/ui/test_hover_prefetch_scenario.py                       |   521 | A pointer resting on a playlist card has                                      | sampled | keep    |
| tests/ui/test_hover_prefs.py                                   |   102 | The three hover escape hatches (Settings > Advanced)                          | sampled | keep    |
| tests/ui/test_hover_swell_fade.py                              |   146 | HoverSwell must fade IN fast and OUT slow                                     | sampled | keep    |
| tests/ui/test_lazy_metadata.py                                 |    87 | Importing `waves` must not pay for packaging metadata                         | sampled | keep    |
| tests/ui/test_library_downloaded_state.py                      |   493 | An album the library scan says you fully                                      | sampled | keep    |
| tests/ui/test_library_presence_surfaces.py                     |   444 | Every surface that shows a download state has                                 | sampled | keep    |
| tests/ui/test_library_section_qml.py                           |   387 | The Library section renders the files on disk                                 | sampled | keep    |
| tests/ui/test_library_track_claim.py                           |   359 | A track row's download button has to answer                                   | sampled | keep    |
| tests/ui/test_logs_console.py                                  |   126 | Realtime logs console: tail helper plus the copy/tail                         | sampled | keep    |
| tests/ui/test_logs_console_qml.py                              |   291 | Realtime logs console: bottom-bar button, live tail, filter                   | deep    | keep    |
| tests/ui/test_motion_video_cache.py                            |   100 | The ambient wave loop plays from a local                                      | sampled | keep    |
| tests/ui/test_move_errno_breadcrumb.py                         |    70 | The rename fast path leaves a breadcrumb when                                 | sampled | keep    |
| tests/ui/test_my_music_second_source_qml.py                    |   215 | A second saved-shelf source renders with zero QML                             | sampled | keep    |
| tests/ui/test_my_tidal_features.py                             |   231 | Unit coverage for the My Tidal / download-folder                              | sampled | keep    |
| tests/ui/test_nav_seq_and_history_guards.py                    |   159 | Navigation bookkeeping must react to NAVIGATIONS, not to                      | sampled | keep    |
| tests/ui/test_new_release_mark.py                              |   715 | A release wears NEW for its first fortnight                                   | sampled | keep    |
| tests/ui/test_offscreen_qt_is_usable.py                        |    80 | The canary for every offscreen QML gate in                                    | sampled | keep    |
| tests/ui/test_onboarding_state_qml.py                          |   452 | First-run welcome, the inline TIDAL sign-in, Skip, the                        | sampled | keep    |
| tests/ui/test_page_reuse_caches.py                             |   229 | Unit coverage for the session/page caches that stop                           | sampled | keep    |
| tests/ui/test_pasted_link_routing.py                           |    45 | A pasted catalog link routes to open_url; a                                   | sampled | keep    |
| tests/ui/test_playlist_folder_qml.py                           |   204 | Playlist-folder drill-in: the QML state machine end to                        | sampled | keep    |
| tests/ui/test_playlist_folders.py                              |   219 | Folder tree sweep + {folder_path} handling (waves/providers/tidal_folders.py) | sampled | keep    |
| tests/ui/test_playlist_full_pagination.py                      |   117 | A playlist's tracks page to the end, not                                      | sampled | keep    |
| tests/ui/test_playlist_m3u_order.py                            |   248 | The m3u8 lists a playlist's tracks in the                                     | sampled | keep    |
| tests/ui/test_playlist_m3u_write.py                            |   133 | The playlist m3u is the one file written                                      | sampled | keep    |
| tests/ui/test_playlist_scope_only_what_landed.py               |   248 | The m3u writer may only write where this                                      | sampled | keep    |
| tests/ui/test_playlist_selection_and_reset.py                  |   271 | Playlist rows select per ROW, and a new                                       | sampled | keep    |
| tests/ui/test_presence_call_budget.py                          |   351 | Building a page of search rows asks the                                       | sampled | keep    |
| tests/ui/test_preview_fetch.py                                 |   314 | Preview loading: parallel HLS segment fetch + up-front                        | sampled | keep    |
| tests/ui/test_progress_carved_percent.py                       |   355 | The download button's progress bar fills the whole                            | sampled | keep    |
| tests/ui/test_progress_jump_ramp.py                            |   155 | A download bar that jumps forward fills to                                    | sampled | keep    |
| tests/ui/test_progress_matrix_stable_width.py                  |   323 | A running download's dot matrix must not shed                                 | sampled | keep    |
| tests/ui/test_progress_pad_cells.py                            |   236 | The download face's opening percent is visible: pad                           | sampled | keep    |
| tests/ui/test_progress_shim.py                                 |   122 | Pin the waves.progress shim to the rich bookkeeping                           | sampled | keep    |
| tests/ui/test_progress_throttle.py                             |    62 | The broadcast-progress rate gate (WavesBridge)                                | sampled | keep    |
| tests/ui/test_provider_badge_qml.py                            |   178 | Provider badges on drill headers, descriptor-driven                           | sampled | keep    |
| tests/ui/test_provider_descriptor_card_qml.py                  |   166 | A provider the page has never heard of                                        | sampled | keep    |
| tests/ui/test_provider_status_dots_qml.py                      |   250 | Per-provider header lights, Browse availability, no header sign-out           | sampled | keep    |
| tests/ui/test_qml_art_cache_keys.py                            |   175 | The warm cover-art pool must ask for covers                                   | sampled | keep    |
| tests/ui/test_qml_bridge_slots.py                              |    97 | Every `waves.<name>` the QML calls really is reachable                        | sampled | keep    |
| tests/ui/test_qml_color_literals.py                            |    78 | QML colour literals must not be 9 characters                                  | sampled | keep    |
| tests/ui/test_qml_loads.py                                     |   130 | The QML actually parses, and a QML error                                      | sampled | keep    |
| tests/ui/test_qml_mask_shapes_stay_hidden.py                   |    52 | An item used only as a mask SHAPE                                             | sampled | keep    |
| tests/ui/test_qml_plaintext_guard.py                           |   809 | A zero-click image-beacon must never re-appear in the                         | sampled | keep    |
| tests/ui/test_qml_runner_classification.py                     |   200 | The QML scenario runner: success, positive dependency skips                   | sampled | keep    |
| tests/ui/test_qml_scenarios_are_sandboxed.py                   |    49 | An offscreen scenario must never run against the                              | deep    | keep    |
| tests/ui/test_quality_pick_qml.py                              |   535 | The quality badge's tier menu, on the real                                    | deep    | keep    |
| tests/ui/test_queue_delta_mirror.py                            |   178 | QML's queue model mirrors the bridge through the                              | sampled | keep    |
| tests/ui/test_queue_delta_protocol.py                          |   357 | The queue tells QML what changed, and builds                                  | sampled | keep    |
| tests/ui/test_queue_drawer_close_button.py                     |   198 | The queue drawer carries its own way out                                      | sampled | keep    |
| tests/ui/test_queue_drawer_resize.py                           |   243 | The queue drawer is dragged wider by its                                      | sampled | keep    |
| tests/ui/test_queue_expected_tier.py                           |   321 | The queue predicts a tier honestly: the request                               | sampled | keep    |
| tests/ui/test_queue_failed_section.py                          |   192 | Failed queue rows get their own section, above                                | deep    | keep    |
| tests/ui/test_queue_failure_reason_qml.py                      |   135 | The failed row's reason reaches the drawer, not                               | sampled | keep    |
| tests/ui/test_queue_finalize_word.py                           |   246 | The queue ledger's FINISHING word: finalize-progress plumbing                 | sampled | keep    |
| tests/ui/test_queue_in_library_row.py                          |   204 | An IN LIBRARY ledger row keeps its quality                                    | sampled | keep    |
| tests/ui/test_queue_index.py                                   |   287 | The qid index stays a faithful mirror of                                      | sampled | keep    |
| tests/ui/test_queue_ledger_cap.py                              |   215 | An expanded queue row builds a bounded number                                 | deep    | keep    |
| tests/ui/test_queue_owned_marks_can_be_unsaid.py               |   296 | A queued row can take back "you already                                       | sampled | finding |
| tests/ui/test_queue_owned_prediction.py                        |   443 | A queued row's ledger says which tracks you                                   | sampled | keep    |
| tests/ui/test_queue_playlist_expands.py                        |   235 | A downloading playlist (or mix) row expands to                                | sampled | keep    |
| tests/ui/test_queue_repeated_track_state.py                    |   153 | A track that appears twice in a collection                                    | sampled | keep    |
| tests/ui/test_queue_row_index.py                               |   210 | A queue progress tick finds its own row                                       | sampled | keep    |
| tests/ui/test_queue_row_pins_the_library_skip.py               |   388 | A queue row keeps the "skip songs already                                     | sampled | keep    |
| tests/ui/test_queue_row_progress_density.py                    |   202 | A running queue row's progress bar is the                                     | sampled | keep    |
| tests/ui/test_queue_row_quality.py                             |   269 | A queue row states a quality, and states                                      | sampled | keep    |
| tests/ui/test_queue_row_state_is_not_resurrected.py            |   160 | Per-row state may not outlive, or come back                                   | sampled | keep    |
| tests/ui/test_queue_section_pulse.py                           |   258 | The queue's section headers pulse the number that                             | sampled | keep    |
| tests/ui/test_queue_single_row_has_nothing_to_expand.py        |   285 | The queue's one-item releases answer a hover but                              | sampled | keep    |
| tests/ui/test_queue_track_repeater_stability.py                |    99 | The queue drawer's per-track Repeater must not rebuild                        | sampled | keep    |
| tests/ui/test_queue_unavailable_word.py                        |   194 | A delisted track reads UNAVAILABLE in the queue                               | sampled | keep    |
| tests/ui/test_queue_withdrawal_rollup.py                       |   785 | Withdrawn queue rows settle their rollups, and stranded                       | sampled | keep    |
| tests/ui/test_search_artists_show_all_empty.py                 |   222 | The ARTISTS SHOW ALL / SHOW LESS label                                        | sampled | keep    |
| tests/ui/test_search_paste_autosearch.py                       |   236 | The paste glyph searches what it pastes; a                                    | sampled | keep    |
| tests/ui/test_search_playlist_block.py                         |   251 | Search playlist rows behave like album rows                                   | sampled | keep    |
| tests/ui/test_search_provider_collapse_qml.py                  |   246 | Collapsible provider groups in Search                                         | sampled | keep    |
| tests/ui/test_search_query_collapse_qml.py                     |   161 | The search field sends the words it shows                                     | sampled | keep    |
| tests/ui/test_search_query_hygiene.py                          |    75 | A pasted title with a line break never                                        | sampled | keep    |
| tests/ui/test_search_refresh_in_place.py                       |   235 | A search refresh swaps the rows in place                                      | sampled | keep    |
| tests/ui/test_search_results_surface_steal.py                  |   132 | Late search results must not steal the active                                 | sampled | keep    |
| tests/ui/test_search_scroll_reset.py                           |   232 | A NEW search always lands at the top                                          | sampled | keep    |
| tests/ui/test_search_sort_pref.py                              |    40 | The search sort control is remembered across launches                         | sampled | keep    |
| tests/ui/test_search_stale_revalidate.py                       |   167 | A search the app has answered before paints                                   | sampled | keep    |
| tests/ui/test_search_tab_artist_restore.py                     |   278 | The Search tab restores ONE artist, not two                                   | sampled | keep    |
| tests/ui/test_search_third_provider_qml.py                     |   374 | A third provider's search group renders with zero                             | sampled | keep    |
| tests/ui/test_search_top_hit_payload.py                        |   156 | The search payload carries TIDAL's top hit, and                               | sampled | keep    |
| tests/ui/test_search_top_result.py                             |   281 | A specific search answers at the top of                                       | sampled | keep    |
| tests/ui/test_setup_ctas_qml.py                                |   389 | Every empty state a provider could fill offers                                | sampled | keep    |
| tests/ui/test_startup_provider_picker_qml.py                   |   158 | Startup provider picker                                                       | sampled | keep    |
| tests/ui/test_startup_self_heal.py                             |   214 | Three things at the edges of starting up                                      | sampled | keep    |
| tests/ui/test_terms_gate.py                                    |   181 | The first-run terms gate                                                      | sampled | keep    |
| tests/ui/test_tidal_signin_reachable_qml.py                    |   406 | TIDAL sign-in stays reachable without any latched overlay                     | sampled | keep    |
| tests/ui/test_track_progress_join.py                           |   197 | Each queue row follows its OWN track's progress                               | sampled | keep    |
| tests/ui/test_track_row_hover_stable.py                        |   181 | Track-row hover stability: hover must never reflow the                        | sampled | keep    |
| tests/ui/test_transient_failures_not_cached.py                 |   558 | Rollup stranding and transient failures cached as authoritative               | sampled | keep    |
| tests/ui/test_two_copies_of_waves.py                           |   263 | Nothing stops a second copy of Waves running                                  | sampled | keep    |
| tests/ui/test_update_check_teardown.py                         |   125 | The update-check worker must survive outliving the bridge                     | sampled | keep    |
| tests/ui/test_update_optin_prompt.py                           |   157 | The one-time update opt-in prompt (updateOptInGate)                           | sampled | keep    |
| tests/ui/test_update_toast_staged.py                           |   160 | The update toast never names a version the                                    | sampled | keep    |
| tests/ui/test_updater.py                                       |  1669 | Unit tests for the in-app self-updater (no network                            | sampled | keep    |
| tests/ui/test_updater_integration.py                           |   157 | End-to-end integration test for the self-updater: no GitHub                   | sampled | keep    |
| tests/ui/test_video_card_date_no_overlap.py                    |   164 | A video card's release date must never run                                    | sampled | keep    |
| tests/ui/test_video_grid_hover_dwell.py                        |   154 | A pointer resting on a video result actually                                  | sampled | keep    |
| tests/ui/test_video_grid_whole_rows.py                         |    52 | The mixed search view's video grid shows whole                                | sampled | keep    |
| tests/ui/test_video_metadata.py                                |   225 | Downloaded music videos carry real metadata                                   | sampled | keep    |
| tests/ui/test_video_owned_plate_agrees.py                      |   228 | A video cell's owned plate agrees with its                                    | sampled | keep    |
| tests/ui/test_video_path_template.py                           |   113 | The default video path: Videos/<artist>/[year] <title>                        | sampled | keep    |
| tests/ui/test_video_peek.py                                    |    64 | The hover peek's stream picker favours instant start                          | sampled | keep    |
| tests/ui/test_video_results_fields.py                          |   139 | The video payload carries what the results grid                               | sampled | keep    |
| tests/ui/test_welcome_signin_decode_gaps.py                    |   322 | The welcome inline sign-in must never submit a                                | sampled | keep    |
| tests/ui/test_window_geometry.py                               |   426 | Tests for window-geometry persistence in the bridge                           | sampled | keep    |

## Findings

### TEST-01 - 4 Qt-driving files escape the marker guard

- severity: P2
- confidence: confirmed
- area: tests
- tags: [refactor]
- evidence: `tests/packaging/test_qt_tests_carry_the_marker.py:28` limits `_QT_TYPES` to 5 names (QCoreApplication, QGuiApplication, QQmlApplicationEngine, QQmlEngine, QQuickWindow), so the guard cannot see other Qt constructors. Confirmed escapes, each with no `qml`/`integration` marker and no `pytest.importorskip` at module scope: `tests/downloads/test_download_queue_serial.py:58-80` builds a real `QThreadPool`/`QRunnable`; `tests/ui/test_factory_reset.py:343-347` builds `QNetworkCacheMetaData`/`QNetworkDiskCache` (reached from tests at lines 361, 374, 390); `tests/ui/test_art_cache_immutable.py:17-46` is unmarked despite module-scope Qt imports behind `importorskip`; `tests/ui/test_queue_owned_marks_can_be_unsaid.py:97` calls `importorskip("PySide6")` inside a helper. I ran the guard's own check function in-process (`test_every_qt_or_process_test_declares_its_marker`) and it reports zero offenders. `DEVELOPER.md:139` sells `mise run test-fast` as the no-Qt group; the standard tasks force `--all-extras` (the `gui` extra, `pyproject.toml:55`), but a contributor synced without extras gets errors, not skips. Separately, `tests/downloads/test_dual_download.py:232-245` runs real ffmpeg with an inline skip and no `ffmpeg` marker, so `mise run test-ffmpeg` (`-m ffmpeg`) never selects it.
- why it matters: the suite's stated rule is "a test that spawns an interpreter or constructs Qt itself is qml or integration, never unmarked" (`test_qt_tests_carry_the_marker.py:11-13`). The rule is not enforced for any Qt type outside the 5-name list, and `--require-qml`'s static half cannot see these tests.
- proposed change: make `_constructs_qt` accept any call whose leaf name matches `Q[A-Z]\w+` and whose module resolves to PySide6 (or, simpler and good enough, extend `_QT_TYPES` with the Qt types the tree really uses and treat `pytest.importorskip("PySide6")` as a drives-Qt signal). Then add `pytestmark = pytest.mark.qml` to the 4 in-process files (or an `importorskip` for the two that already use it) and the `ffmpeg` marker to `test_file_mode_reader_prefers_the_tag_over_the_codec`.
- acceptance criteria: [ ] the guard fails on the current tree with the 4 files listed; [ ] after marking, the guard passes; [ ] on a venv without PySide6, `uv run pytest -q -m "not qml" tests/downloads/test_download_queue_serial.py tests/ui/test_factory_reset.py` reports skips, not errors.
- evidence required to close: red then green output of the guard test, plus the no-Qt run output.
- depends on / blocks: none
- effort: S
- needs human: no

### TEST-02 - Wrapper-tier codec rejection has no negative test

- severity: P1
- confidence: confirmed
- area: tests
- tags: [coverage]
- evidence: `waves/providers/apple/runner.py:723-737` raises `AppleIntegrityError` for a stereo delivery whose codec is not aac/alac. The only `verify_staged(..., expect_atmos=False)` calls are `tests/downloads/test_apple_integrity_gate.py:966` (probe returns alac, must not raise) and `:694` (probe returns aac, so the codec check passes and the failure comes from decode). `rg "_require_codec_family" tests` returns nothing. The Atmos negative exists (`:1106-1116`, ac3 with `expect_atmos=True`). Deleting the stereo `elif` branch at `runner.py:736-737` keeps the suite green.
- why it matters: the docstring at `runner.py:747-748` states the shipped contract ("the codec must be the asked family (stereo: AAC or ALAC)"). A regression that accepts any container for stereo downloads would ship quarantine-free.
- proposed change: add one test beside the Atmos negative: probe returns `ec3` (or `mp3`) with `expect_atmos=False`, assert `pytest.raises(AppleIntegrityError)` and that the message names the served codec.
- acceptance criteria: [ ] new test fails when `runner.py:736-737` is removed; [ ] passes on current code.
- evidence required to close: test id plus the mutation result.
- depends on / blocks: none
- effort: S
- needs human: no

### TEST-03 - 28 bridge slots and 13 signals are named by no test

- severity: P2
- confidence: confirmed
- area: tests
- tags: [coverage]
- evidence: static scan of `waves/desktop/backend.py` (21,810 lines, 156 `@Slot` functions, 97 signals) against all 107,775 test lines. Slots with zero name matches: `loadHome:7785`, `providerSignInSteps:9762`, `_own_announce_arm:10776`, `ownershipGeneration:10831`, `collectionOwnershipMany:11170`, `bootIncubationBusy:11990`, `_emit_diagnostics_exported:12318`, `revealDiagnostics:12322`, `bypassFfmpegGate:13391`, `retryDownloadFolder:13415`, `playVideo:16096`, `peekVideo:16172`, `ffmpegStatus:18499`, `checkFfmpegUpdate:18505`, `cancelFfmpeg:18566`, `removeFfmpeg:18570`, `resumePendingUpdate:18623`, `startupFfmpegUpdateCheck:18693`, `cancelAppUpdate:18799`, `restartForUpdate:18803`, `openReleasesPage:18816`, `copyShareUrl:19177`, `appleRuntimeStatus:19573`, `removeAppleRuntime:19641`, `resetSettingsDefaults:21677`, `uiLog:21802`, plus `_ProgressSignals._on_pct:1309` and `_on_track_event:1313` (internal). Signals with zero matches: `_ProgressSignals.item_name:1292`, `busyChanged:3943`, `homeLoaded:3964`, `motionBgChanged:4010`, `diagnosticsExported:4014`, `videoPeekReady:4101`, `appleRuntimeProgress:4122`, `setupRequested:4130`, `ffmpegUpdateChecked:4142`; four more (`downloadFolderMissing:4070`, `downloadFolderDefault:4071`, `videoReady:4097`, `appUpdatePending:4147`) are named only in QML. 24 of the slots are invoked from `waves/desktop/qml/` (`uiLog` has 7 call sites), so the QML harness can reach them by luck of a click, but no test asserts them.
- why it matters: production depends on the ffmpeg manager and app update flows, and their bridge wiring (`checkFfmpegUpdate`, `cancelFfmpeg`, `removeFfmpeg`, `resumePendingUpdate`, `cancelAppUpdate`, `restartForUpdate`) is named nowhere. `tests/packaging/test_ffmpeg_manager.py` and `tests/ui/test_updater.py` test the manager modules, not the slots that call them.
- proposed change: bind the real methods onto the existing stub pattern (`tests/conftest.py` `_Signal`/`_InlinePool`) and add one behavioral test per slot in the QML-reachable group; for the internal ones, assert the emission contract. Do not build a new harness.
- acceptance criteria: [ ] each of the 28 slots has at least one test whose failure mode is behavioral, listed in a comment above the test; [ ] the static scan reports zero unnamed slots; [ ] no test asserts only `inspect.getsource` text for these.
- evidence required to close: new test ids plus a rerun of the static scan.
- depends on / blocks: none
- effort: L (split by group: ffmpeg/update, catalog/home, video, settings)
- needs human: no

### TEST-04 - The QML harness is wall-clock bound and cannot observe hover, paint or native chrome

- severity: P2
- confidence: confirmed
- area: tests
- tags: [refactor]
- evidence: `tests/support/qml.py:132-141` runs each scenario as a subprocess with `QT_QPA_PLATFORM=offscreen`; `:302-305` implements `settle(ms)` as a real-time `QEventLoop` wait. 836 `settle(`/`time.sleep(`/`QTest.qWait(` call sites across 107 files; the longest single waits are 5000 ms (`tests/ui/test_logs_console_qml.py:231`), 3000 ms x4 (`tests/ui/test_boot_handover_gate.py:132,169,244,283`), 1800 ms (`tests/ui/test_progress_pad_cells.py:131`), 1400/1100 ms (`tests/ui/test_progress_jump_ramp.py:111,124`). 15 tests assert elapsed-time bounds; the tightest are `tests/library/test_library_index.py:272` (`< 0.5` with "serial would be >= 0.8s") and `:299` (`< 0.6`). `tests/ui/test_boot_version_drain_order.py:45-46,138-139` samples an animation every 25 ms and asserts the ordering gap is <= 300 ms. `tests/ui/test_art_cache_immutable.py:68` sleeps 1.3 s to age a cache entry. `tests/ui/test_queue_ledger_cap.py:22-27` records that the hover peek ceiling "cannot be driven headlessly". `tests/support/qml.py:182-199` works around a control that arms only on a second press with a double click.
- why it matters: `DEVELOPER.md:130-132` already asks the machine be idle while QML runs; the gates run on shared runners (`master.yml:33-37`), where 25 ms sampling and a 300 ms bound are load-sensitive. Nothing in the suite detects real painting, real hover, DPI scaling or native window chrome, which is the largest remaining native UI verification gap.
- proposed change: add `support/qml.wait_until(predicate, timeout_ms=3000, interval_ms=25)` and convert animation/state assertions to poll a predicate instead of sleeping a guessed duration; keep `settle` only where the point is to let a scheduled timer fire, with a one-line reason. Widen elapsed-time bounds to at least 3x the measured value or move them behind a `perf` marker excluded from `test-strict`.
- acceptance criteria: [ ] no animation test asserts a wall-clock delta without polling a state predicate; [ ] the 15 elapsed-bound assertions have a 3x margin or a `perf` marker; [ ] `wait_until` has a unit test that fails when the timeout is exceeded.
- evidence required to close: diff of the converted tests, plus `mise run test-qml` timings before and after.
- blocked by: none.
- related: TEST-11 diagnostics.
- effort: L
- needs human: no

### TEST-05 - Source-spelling pins are counted as behavior coverage

- severity: P3
- confidence: confirmed
- area: tests
- tags: [refactor]
- evidence: 40 `inspect.getsource` sites in `tests/`. 69 test functions have only source/doc-text assertions (heuristic: every `assert` names a source variable or reads a file). Clearest cases where the assertion pins a literal spelling rather than behavior: `tests/downloads/test_download_queue_serial.py:31-39` (regex over `self.dl_pool = QtCore.QThreadPool()` ... `setMaxThreadCount(1)`), `:42-46` (`src.count("dl_pool.setMaxThreadCount") == 1`), `:49-55` (literal `"max_workers=self.settings.data.downloads_concurrent_max"`), `tests/downloads/test_preparing_state.py:97-102` (`src.count('"preparing")') == 5`), `tests/ui/test_dead_pair_and_qml_gating_guards.py:31-32` (literal `'format_path_media(template, vid, pad, **kw) + ".mp4"'`) and `:49-51` (`"visible ?" in line`), `tests/settings/test_quality_override.py:283-296` (`inspect.getsource(...)` substring checks), `tests/metadata/test_illegal_replacement_map.py:290-315` (QML/backend text regexes).
- why it matters: these fail on behavior-preserving refactors and can pass while the behavior is broken elsewhere in the same expression. They inflate the apparent coverage of the slots and QML surfaces they name.
- proposed change: keep the genuinely fail-closed ones (`test_dead_recently_added_pair_removed` is an obsolete-API guard; `test_every_engine_dispatch_forwards_the_delay` is backed by 6 behavioral tests at `test_download_delay_setting.py:183-243`), convert the rest to behavior tests where a seam exists, and rename the retained pins `test_wiring_*` so they are not reported as behavior coverage. State the policy in `DEVELOPER.md`.
- acceptance criteria: [ ] every retained source pin has a comment naming the behavior it fences and why no behavioral seam exists; [ ] the 8 cited tests are either converted or renamed; [ ] no source pin is the only test for a user-facing feature.
- evidence required to close: renamed/converted test ids.
- depends on / blocks: none
- effort: M
- needs human: no

### TEST-06 - Claims guards pass vacuously in five places

- severity: P2
- confidence: confirmed
- area: tests
- tags: [docs]
- evidence:
  - `tests/packaging/test_platform_claims.py:38` forbids the exact string `"on Windows and Linux run"`; re-wording it to `"on Windows and Linux, run"` satisfies the guard while still presenting a parked platform as runnable. Line 32 only requires `"parked"` anywhere in the README, not in the Windows paragraph.
  - `tests/packaging/test_acceptance_evidence.py:62` accepts any 40-hex string as "its producing revision", not the revision of the artifact. `:93-97` scans only top-level `docs/evidence/*.md` with 8 substrings, so a secret in a subdirectory, a `.json`/`.txt` artifact, or a pattern not listed (`ASIA`, JWT `eyJ`, `xoxb-`) passes.
  - `tests/packaging/test_repository_docs.py:183` finds thread ids anywhere in the file, not only in table rows; a prose mention counts. `:52-55` checks the 5 ADR markers exist somewhere in the file, so an ADR can contradict itself and pass.
  - `tests/packaging/test_changelog_format.py:71-86` never resets `in_release`, exempts any continuation line starting with `<`, `#` or `-`, and leaves the preamble unguarded; a wrapped bullet can pass by starting the continuation with `<`.
  - `tests/packaging/test_ci_hygiene.py:175-186,189-257` spawn bash and assert `shutil.which("bash")`; there is no `integration` or `platform` marker on those tests, so the marker taxonomy in `test_qt_tests_carry_the_marker.py:11-13` is not applied to process-spawning tests that do not use `sys.executable` or `__file__`.
- why it matters: these are the guards that let reviews stop re-checking doc claims. A vacuous pass on the platform badge, evidence revisions or the disposition table is a false green on published claims.
- proposed change: make each check structural, not substring. Platform: parse the Windows paragraph of the README and assert no run/download instruction there. Evidence: require `revision: <sha>` and `artifact: <name>` in a YAML/JSON header of each artifact and compare the sha to the artifact's own commit; extend the secret scan to `**/*` under `docs/evidence/`. Dispositions: parse only table rows for ids (already done for `rows`) and assert each id appears exactly once across the file. Changelog: reset `in_release` per release section and only exempt fenced code. Marker taxonomy: include `subprocess.run([bash, ...])` in `_CHILD_PROCESS_CALLS`.
- acceptance criteria: [ ] each cited guard has a negative test (mutate the doc, expect the guard to fail); [ ] the platform reword `"on Windows and Linux, run"` fails the guard; [ ] a fabricated `revision: 1234...` that does not match the artifact fails the evidence guard; [ ] a secret in `docs/evidence/notes.md` subdir or a `.json` file fails the scan.
- evidence required to close: the 4 negative tests, red before the fix and green after.
- blocked by: TEST-09 platform-claim design.
- effort: M
- needs human: no

### TEST-07 - The `--require-qml` session-end net cannot fire for missing Qt

- severity: P3
- confidence: confirmed
- area: tests
- tags: [obsolete]
- evidence: `tests/conftest.py:125-131` raises `pytest.UsageError` in `pytest_configure` when `--require-qml` is set and PySide6 is missing, so the session never reaches `pytest_sessionfinish` (`:163-186`). The net's docstring (`:176-181` of `tests/packaging/test_qt_tests_carry_the_marker.py`) claims it "fails a strict run when an UNMARKED test skipped for missing Qt", and its test (`:171-196`) monkeypatches the condition to prove the mechanism only. I found no path where the parent has PySide6, a child does, and a test skips with a PySide6 reason.
- why it matters: dead enforcement reads as live enforcement in review. The static guard (TEST-01) is the only load-bearing half.
- proposed change: either delete `_UNMARKED_QT_SKIPS`, `pytest_runtest_logreport`, the sessionfinish branch and the test, or narrow the docstring to "reachable only for skips that name PySide6 while Qt is present" and keep it as defense in depth. Deletion is simpler.
- acceptance criteria: [ ] `conftest.py` and the guard test agree on what is reachable; [ ] `mise run test-strict` still fails when `--require-qml` meets a missing PySide6 (UsageError).
- evidence required to close: the chosen diff plus a run showing UsageError.
- blocked by: TEST-01 marker-guard correction.
- effort: S
- needs human: no

### TEST-08 - `--doctest-modules` is inert and markers are not strict

- severity: P3
- confidence: confirmed
- area: tests
- tags: [dx]
- evidence: `pyproject.toml:134` sets `testpaths = ["tests"]`; every task passes `--doctest-modules` (`mise.toml:33,37,41,45,49,53`) but the test paths never include `waves/`. There are 0 doctest lines in `tests/` and 27 in `waves/metadata/camelot.py` only. `pyproject.toml:135-142` declares markers but sets no `addopts`, no `--strict-markers`, no `--strict-config`, no `xfail_strict`, and no `filterwarnings = error`.
- why it matters: the flag reads as coverage of the shipped package's examples and collects nothing; a typo in a marker name (`pytest.mark.qmll`) is a warning, not an error, so the test runs in the wrong group silently.
- proposed change: add `addopts = ["--strict-markers", "--strict-config"]` and `xfail_strict = true` to `[tool.pytest.ini_options]`; either drop `--doctest-modules` from the tasks or add one task that runs `pytest --doctest-modules waves` and pins camelot's examples.
- acceptance criteria: [ ] a marker typo fails collection; [ ] `mise run check` or a new task actually executes the 27 camelot doctest lines, or the flag is gone from all tasks.
- evidence required to close: the config diff plus a collection run with a deliberately typo'd marker.
- depends on / blocks: none
- effort: S
- needs human: no

### TEST-09 - The suite hard-enforces the Windows park, and re-entry has no test path

- severity: P1
- confidence: confirmed
- area: tests
- tags: [windows] [docs]
- evidence: `tests/packaging/test_platform_claims.py:24-38` fails if the README badge contains "Windows", if "parked" disappears, or if the run instructions mention Windows; `tests/packaging/test_provider_spec_amendments.py:38` requires the spec to point at ADR 0009. Meanwhile `.github/workflows/build-legs.json` carries `windows-x64` and `windows-arm64` legs and `tests/packaging/test_ci_hygiene.py:189-197` asserts both build with `--low-memory`. The BRIEF says the park must be re-examined, not accepted; whoever un-parks must edit 2 test files (`test_platform_claims.py` and `test_provider_spec_amendments.py`) plus the README and the ADR reference, and nothing in the suite tells them what to change.
- why it matters: enabling Windows requires coordinated test edits, and the re-entry acceptance is defined only in ADR 0009 prose.
- proposed change: make `.github/workflows/build-legs.json` own whether a leg is selected for publication, because release selection already reads it. Have `test_platform_claims.py` compare README support claims with that configuration. Add a Windows `mise run test-fast` job when Windows is enabled. Do not add a parallel status file under `docs/`.
- acceptance criteria: [ ] one executable configuration controls release-leg selection; [ ] changing Windows between parked and enabled plus updating README requires no test-source edit; [ ] an enabled Windows test job runs `mise run test-fast`.
- evidence required to close: build-leg diff, claim-guard test and a green Windows run when enabled.
- blocked by: TEST-10 and the BUILD-01 platform decision.
- effort: M
- needs human: yes (decide the supported-platform set)

### TEST-10 - No CI leg runs the suite on macOS or Windows

- severity: P1
- confidence: confirmed
- area: tests
- tags: [windows] [dx]
- evidence: `.github/workflows/master.yml:7-8` is `workflow_dispatch` only and runs `mise run test-strict` on `ubuntu-24.04` for Python 3.12/3.13/3.14 (`:33-55`). `.github/workflows/release-or-test-build.yml` has no test step: the 8 build legs run bundle smoke-launch (`:282-287`, `:369-374`) but never the suite. The Linux workflow collects the 6 `platform`-marked tests, but host-specific branches such as macOS share remount and Windows cleanup do not execute on their target systems.
- why it matters: a release that ships macOS or Windows artifacts has no test-suite run on those host families. Path-length, case-insensitive-filesystem, native cleanup and Qt-version failures are exactly what those jobs would catch.
- proposed change: add `mise run test-strict` (or `test-fast` plus the qml group) to the build legs before packaging, or add one test job per OS family. If runner minutes are the constraint, at minimum run `mise run test-fast` on macOS and Windows and gate the release on it.
- acceptance criteria: [ ] a CI run on `macos-14` and `windows-2022` executes the suite; [ ] the run is green or the failing tests are linked as issues.
- evidence required to close: CI run URLs per OS.
- depends on / blocks: none
- effort: M
- needs human: yes (CI budget and runner choice)

### TEST-11 - QML scenario failures do not identify named checkpoints

- severity: P3
- confidence: confirmed
- area: tests
- tags: [refactor]
- evidence: `support/qml.run_scenario` returns only the child's stdout tail (`tests/support/qml.py:202-241`); parent QML tests are often one-line subprocess calls (`tests/ui/test_queue_ledger_cap.py:55-61`). Pytest records the parent test ID and child assertion failure, but long scenarios can be hard to diagnose when several checkpoints share generic messages.
- why it matters: a failing scenario can require rerunning or reading the whole child to identify the failed state. This is a diagnostics problem, not a missing evidence database.
- proposed change: give important child assertions descriptive messages or small named checkpoint helpers so the existing pytest failure identifies the behavior. Keep CI logs and artifacts in CI. Do not add per-run JSON, a checked-in latest-run pointer or a feature manifest.
- acceptance criteria: [ ] representative multi-checkpoint scenarios report the failed checkpoint in their existing pytest output; [ ] removing a behavior assertion still changes the test source reviewed in the PR; [ ] no generated run state is committed.
- evidence required to close: red-then-green output from representative scenario failures.
- blocked by: none.
- related: TEST-04 harness timing.
- effort: S
- needs human: no

### TEST-12 - Duplicate test names and scaffolding around the twin late-skip guard

- severity: P3
- confidence: confirmed
- area: tests
- tags: [refactor]
- evidence: `tests/downloads/test_twin_late_skip.py` (184 lines, 6 tests) and `tests/downloads/test_twin_late_skip_and_pause_gate.py` (697 lines, 18 tests) each define `_make_download`, `_track` and their own guard-spy runner (`test_twin_late_skip.py:68-92` vs `test_twin_late_skip_and_pause_gate.py:95-130`). The forced-redownload scenario is covered in both (`test_twin_late_skip.py:127-141`, `test_twin_late_skip_and_pause_gate.py:266-280`) against different mechanisms (tag id vs written-name ledger). Four test names are also identical across `tests/downloads/test_playlist_full_albums.py:356-388` and `tests/library/test_stop_keeps_rows_and_stops_scans.py:566-621`; `pytest -k` on those names selects both files.
- why it matters: two copies of the guard scaffolding drift apart, and identical names make targeted selection ambiguous in a suite this large.
- proposed change: move the shared doubles into `tests/support/` and rename one side of each duplicate pair for the entry point it drives (for example `..._for_a_playlist` / `..._for_a_discography`).
- acceptance criteria: [ ] no two test functions share a name across files; [ ] the shared `_make_download` lives in one place; [ ] both guard mechanisms keep at least one test each.
- evidence required to close: a rerun of the duplicate-name scan.
- depends on / blocks: none
- effort: S
- needs human: no

## Claims checked

| Claim                                                    | Source                                                                                               | Verdict                                      | Evidence                                                                                                                                                                                                                                                                                                                                                                     |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mise run test-strict` is the merge gate                 | BRIEF, `mise.toml:49-51`                                                                             | true, with caveats                           | Runs `--require-qml -m "not account"` over `tests`; only CI invocation is `master.yml:54-55`, manual-only (`master.yml:7-8`) and Linux-only. No macOS/Windows leg (TEST-10).                                                                                                                                                                                                 |
| Markers are declared and used as documented              | `pyproject.toml:135-142`                                                                             | true                                         | 3,825 test functions: 112 qml, 60 ffmpeg, 13 slow, 6 integration, 6 platform, 4 account, 3,639 unmarked.                                                                                                                                                                                                                                                                     |
| `slow` always sits beside `qml`                          | `pyproject.toml:140`                                                                                 | true                                         | All 13 slow functions also carry qml (12 qml+slow, 1 qml+slow+integration).                                                                                                                                                                                                                                                                                                  |
| `--require-qml` fails instead of skipping on missing Qt  | `DEVELOPER.md:146-147`                                                                               | true, but the session-end net is unreachable | `tests/conftest.py:125-131` raises UsageError at configure; the sessionfinish net (`:163-186`) cannot fire for missing Qt (TEST-07).                                                                                                                                                                                                                                         |
| The marker guard keeps unmarked Qt/process tests visible | `test_qt_tests_carry_the_marker.py:11-17`                                                            | false                                        | Guard passes today while 4 Qt-driving files carry no marker (TEST-01).                                                                                                                                                                                                                                                                                                       |
| The fast group needs no Qt                               | `DEVELOPER.md:139`                                                                                   | false on a venv without the `gui` extra      | The group selects by marker only; the unmarked Qt tests error rather than skip (TEST-01).                                                                                                                                                                                                                                                                                    |
| Every test runs against a throwaway config home          | `tests/conftest.py:38-57` docstring                                                                  | true                                         | `XDG_CONFIG_HOME` is set at conftest import, before any module import; `tests/ui/test_qml_scenarios_are_sandboxed.py:29-49` scans for scenarios that build a bridge without their own sandbox. The live account suite restores the real profile only under its own fixture (`tests/account/test_live_account.py:34-57`).                                                     |
| The composed launch is covered outside the QML harness   | `tests/support/qml.py:254-260` docstring                                                             | true                                         | `tests/ui/test_cold_process_boot.py:45-54,83` runs the real `waves.py` entry point twice under an isolated config; `tests/ui/test_bridge_boot_isolated.py` covers the real bridge.                                                                                                                                                                                           |
| Acceptance evidence cites resolving suites               | `tests/packaging/test_acceptance_evidence.py:76-90`                                                  | partly                                       | All 6 cited files exist, but only by filename; no test id or verdict is pinned (TEST-11).                                                                                                                                                                                                                                                                                    |
| Package version matches app version                      | `tests/packaging/test_package_version.py`                                                            | true                                         | `pyproject.toml` 0.1.30 and `waves/desktop/__init__.py:14` `__version__ = "0.1.30"`.                                                                                                                                                                                                                                                                                         |
| The 98 disposition threads are covered exactly once      | `tests/packaging/test_repository_docs.py:76-186`                                                     | true today                                   | 98 unique ids in the test tuple; 98 occurrences in `docs/review-thread-dispositions.md`; the id scan is not cell-scoped (TEST-06).                                                                                                                                                                                                                                           |
| Windows builds are parked in the docs                    | `tests/packaging/test_platform_claims.py:24-38`                                                      | true and enforced                            | The suite fails on README un-parking; `build-legs.json` still carries both Windows legs (TEST-09).                                                                                                                                                                                                                                                                           |
| Group case counts in `DEVELOPER.md:137-144`              | `DEVELOPER.md:139-144`                                                                               | unverified                                   | 3,825 test functions plus 96 `parametrize` decorators is the static floor; only a collection run can confirm 4,194/91/4,354/56/4.                                                                                                                                                                                                                                            |
| ADR and evidence artifacts exist on disk                 | `tests/packaging/test_repository_docs.py:45-48`, `tests/packaging/test_acceptance_evidence.py:53-57` | false in this checkout                       | 13 tracked files are deleted in the worktree (9 under `docs/adr/`, 4 under `docs/evidence/`, `git status --porcelain`), both directories now empty with mtimes 19:19/19:29, before this audit session. `test_repository_docs.py` would fail its `assert files` and `test_acceptance_evidence.py` its `is_file()` checks. Not an edit by this agent; outside tests ownership. |
| `--doctest-modules` exercises shipped examples           | `mise.toml:33-53`                                                                                    | false                                        | 0 doctests under `tests/`; 27 doctest lines exist only in `waves/metadata/camelot.py` and `testpaths = ["tests"]` (`pyproject.toml:134`) never collects them (TEST-08).                                                                                                                                                                                                      |

## Top 3

1. TEST-10: the suite runs on no macOS or Windows CI leg while most configured artifacts target those platforms. The only test workflow is manual and Linux-only. This is the largest unverified platform surface.
2. TEST-02: the wrapper-tier codec-family rejection is a shipped integrity contract with positive-only coverage. Deleting the stereo branch at `waves/providers/apple/runner.py:736-737` leaves the suite green.
3. TEST-03: 28 bridge slots and 13 signals, including the entire ffmpeg-manager and app-update wiring, are named by no test. Those are user-facing production flows.

## Release blockers

None in this area. TEST-02, TEST-09 and TEST-10 are P1 production-readiness work.

## Open questions

1. Windows disposition: keep parked or enable the two legs? Recommended default: run the current recipe, then let `build-legs.json` and the README reflect the result.
2. CI budget for macOS and Windows test runs: full `test-strict`, `test-fast`, or the QML group only? Recommended default: `test-fast` on `macos-14` and `windows-2022` for release branches, keep `test-strict` on Linux. Confirm minutes are approved.
3. Source-pin policy: convert or rename? Recommended default: rename retained pins to `test_wiring_*` and document them as non-behavior coverage, convert only the 8 cited cases where a behavioral seam exists (TEST-05).
4. Live account suite: which production-readiness milestone requires a manual run? Recommended default: run it before publishing an artifact, and link the transcript or CI-style log from the release issue rather than creating another progress document.
5. Pixel automation scope: which claims need cua-driver? Recommended default: a small built-bundle smoke covering only real hover, window geometry, DPI and native dialogs. Attach recordings or screenshots to the relevant issue or release; everything else stays offscreen (TEST-04, TEST-11).
6. Does `mise run test` (no `--require-qml`) stay documented as the whole suite? Recommended default: keep it, because every task runs `--all-extras` and Qt is present, but label it non-strict next to `test-strict` in `DEVELOPER.md`.
7. Working-tree state: 13 tracked docs files (`docs/adr/0001-0009`, `docs/evidence/*`) are intentionally deleted in the checkout, so two claims guards fail. Recommended default: make a separate product decision about the documentation policy; never restore or commit the deletions as incidental test cleanup.

---

## Dependencies and external engines audit

The locked Python set is current and clean: all 21 direct deps resolve to the latest PyPI release except the two deliberately older exact pins (PySide6 6.11.1, Nuitka 2.8.4), `uv lock --check` passes, `deptry .` is clean, and no OSV advisory matches any resolved version. The risk is not the lock; it is what the lock does not cover: the pinned wrapper image still predates its own license-notice fix, a GPLv3 Widevine CDM enters the bundle through gamdl, and two artifacts outside `uv.lock` (legacy Qt 6.9.3 fixed at build time, managed FFmpeg resolved at install time). Fix the image pin before calling this release production.

`tidal-ng-dl` / `tidal-dl-ng` is not a dependency or engine in this repository.
The only matches are compatibility comments about an old installed application.
Waves' TIDAL integration uses `tidalapi` plus `waves/download.py`; no
`tidal-ng-dl` code or artifact is bundled, so there is no dependency surface to
audit beyond those migration comments.

## Inventory

| path                                                                 | lines | purpose                                          | depth   | verdict                  |
| -------------------------------------------------------------------- | ----- | ------------------------------------------------ | ------- | ------------------------ |
| `pyproject.toml` (deps lines 20-74)                                  | 368   | direct runtime/dev ranges, pins, policy comments | deep    | finding                  |
| `uv.lock`                                                            | 1199  | 75-package locked resolution, hashes, URLs       | deep    | keep                     |
| `docs/dependency-updates.md`                                         | 135   | engine/pin bump runbook and update table         | deep    | keep (update per DEP-11) |
| `docs/wrapper-image.md`                                              | 155   | image publish runbook, pin lockstep              | deep    | keep                     |
| `docs/wrapper-image-license-review.md`                               | 83    | image license inventory and accepted risk        | deep    | keep                     |
| `tools/wrapper-image/NOTICE`                                         | 28    | image third-party notices                        | deep    | keep                     |
| `tools/wrapper-image/{Apache-2.0,BSD-2-Clause,BSD-3-Clause}.txt`     | 255   | license texts copied into the image              | sampled | keep                     |
| `.github/workflows/wrapper-image.yml`                                | 289   | image publish pipeline (dispatch-only)           | deep    | finding                  |
| `.github/wrapper-upstream.sha`                                       | 8     | upstream wrapper-v2 SHA the live image came from | deep    | keep                     |
| `.github/dependabot.yml`                                             | 37    | weekly grouped updates, four deliberate ignores  | sampled | keep                     |
| `waves/providers/apple/runtime.py` (pin block 50-116 + pull 880-955) | 1072  | wrapper tag/digest, libs, N_m3u8DL-RE, APK pins  | deep    | keep                     |
| `waves/desktop/ffmpeg_manager.py` (shell-owned, engine cross-ref)    | 631   | runtime FFmpeg provisioning                      | deep    | finding (DEP-07)         |
| `.github/workflows/build-legs.json` (legacy commands 19-29)          | -     | macOS legacy Qt overlay                          | deep    | finding (DEP-04)         |

## Direct dependency matrix

Resolved versions from `uv.lock`; latest, licenses and release dates from `https://pypi.org/pypi/<pkg>/json` (fetched 2026-09-21); maintenance from `https://api.github.com/repos/<repo>`; vulnerabilities from `https://api.osv.dev/v1/query` with the resolved version (fetched 2026-09-21).

| name                  | declared                | resolved  | latest    | maintenance                           | vulns | license                                       | role                                            | verdict                          |
| --------------------- | ----------------------- | --------- | --------- | ------------------------------------- | ----- | --------------------------------------------- | ----------------------------------------------- | -------------------------------- |
| requests              | >=2.34.2,<3             | 2.34.2    | 2.34.2    | 2026-05-14; push 2026-09-07, 239 open | clean | Apache-2.0                                    | HTTP for TIDAL, runtime, updater                | keep                             |
| mutagen               | >=1.47.0,<2             | 1.48.1    | 1.48.1    | 2026-06-25; push 2026-08-20, 124 open | clean | GPL-2.0-or-later                              | tag read/write                                  | keep (notice obligation, DEP-09) |
| dataclasses-json      | >=0.6.7,<0.7            | 0.6.7     | 0.6.7     | 2024-06-09; push 2026-05-05, 164 open | clean | MIT                                           | config (de)serialization (`waves/model/cfg.py`) | watch, keep for release          |
| pathvalidate          | >=3.3.1,<4              | 3.3.1     | 3.3.1     | 2025-06-15; push 2026-05-10, 9 open   | clean | MIT                                           | filenames/paths                                 | keep                             |
| m3u8                  | >=6.0.0,<7              | 6.0.0     | 6.0.0     | 2024-08-07; push 2025-01-31, 45 open  | clean | MIT                                           | HLS parsing (`waves/download.py:26`)            | keep (shared with gamdl)         |
| gamdl                 | >=3.8.5,<3.9            | 3.8.5     | 3.8.5     | 2026-08-03; 27 open                   | clean | MIT                                           | Apple engine                                    | keep (bump policy)               |
| tidalapi              | >=0.8.10,<0.9           | 0.8.11    | 0.8.11    | 2026-01-19; push 2026-08-14, 21 open  | clean | LGPL-3.0-or-later                             | TIDAL client                                    | keep (notice obligation, DEP-09) |
| python-ffmpeg         | >=2.0.12,<3             | 2.0.12    | 2.0.12    | 2024-04-15; push 2026-09-03, 18 open  | clean | MIT                                           | subprocess wrapper around the managed binary    | watch, keep                      |
| yt-dlp                | >=2025.10.22 (no upper) | 2026.8.19 | 2026.8.19 | 2026-08-19; 2662 open                 | clean | Unlicense                                     | direct-URL downloader (`engine.py:212`)         | keep, constrain policy (DEP-05)  |
| pycryptodome          | >=3.23.0,<4             | 3.23.0    | 3.23.0    | 2025-05-17; push 2026-07-18, 97 open  | clean | BSD + Public Domain                           | Ed25519 signing (`waves/desktop/signing.py:23`) | keep, 3.14 gap (DEP-03)          |
| certifi               | >=2026.4.22             | 2026.7.22 | 2026.7.22 | 2026-07-22; 4 open                    | clean | MPL-2.0                                       | CA bundle (`waves/download.py:24`)              | keep                             |
| urllib3               | >=2.7.0,<3              | 2.8.0     | 2.8.0     | 2026-09-15; 244 open                  | clean | MIT                                           | TLS context (`waves/download.py:41`)            | keep                             |
| pyside6 (extra `gui`) | ==6.11.1                | 6.11.1    | 6.11.2    | 2026-08-18; Qt project                | clean | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | GUI toolkit                                     | keep (floor pin)                 |
| pytest                | >=9.0.1,<10             | 9.1.1     | 9.1.1     | 2026-06-19; active, 825 open          | clean | MIT                                           | tests                                           | keep                             |
| deptry                | >=0.25.1,<0.26          | 0.25.1    | 0.25.1    | 2026-03-18; push 2026-09-21, 69 open  | clean | MIT                                           | dependency hygiene gate                         | keep                             |
| pre-commit            | >=4.5.0,<5              | 4.6.2     | 4.6.2     | 2026-08-10; 26 open                   | clean | MIT                                           | hook runner                                     | keep                             |
| ruff                  | ==0.16.8                | 0.16.8    | 0.16.8    | 2026-09-16; 2191 open                 | clean | MIT                                           | lint/format                                     | keep (hook parity pin)           |
| pyupgrade             | >=3.21.2,<4             | 3.21.2    | 3.21.2    | 2025-11-19; push 2026-09-04, 23 open  | clean | MIT                                           | syntax modernization                            | keep                             |
| pillow                | >=12.0.0,<13            | 12.3.0    | 12.3.0    | 2026-07-01; 135 open                  | clean | MIT-CMU                                       | none in scanned code (DEP-10)                   | drop the dev pin or document     |
| nuitka                | ==2.8.4                 | 2.8.4     | 4.2.1     | 2.8.4: 2025-10-21; 222 open           | clean | Apache-2.0 (2.8.4); 4.x is AGPL-3.0-only      | release compiler                                | keep exact (3.14 gap, DEP-03)    |
| ty                    | ==0.0.82                | 0.0.82    | 0.0.82    | 2026-09-17; 917 open                  | clean | MIT (classifier; PyPI field empty)            | type gate                                       | keep                             |

Notable transitive additions pulled by gamdl 3.8.5 (`uv.lock`): `pywidevine` 1.9.0 (GPL-3.0-only, DEP-02), `protobuf`, `pyyaml`, `httpx`, `structlog`, `pywidevine -> pymp4`. `gamdl`'s closure is 31 packages, `tidalapi`'s 12; `yt-dlp` itself has no runtime deps.

### Replace or drop

- `dataclasses-json` 0.6.7: last release 2024-06-09, 164 open issues, but the repo is alive. Load-bearing for config (de)serialization with legacy-key handling (`waves/model/cfg.py:3,15,302-316`). Replacing with plain `dataclasses`/dicts is a medium refactor with real config-migration risk. Keep; schedule a review, not a prerequisite rewrite.
- `m3u8` 6.0.0: last release 2024-08-07, repo quiet since 2025-01. It is also gamdl's pinned HLS dependency, so dropping it from Waves does not remove it from the bundle. Keep.
- `python-ffmpeg` 2.0.12: last PyPI release 2024-04-15, repo pushed 2026-09-03 (unreleased fixes). It is a thin wrapper used at five call sites (`waves/download.py:4777-4944`, `runner.py:671`); replacing it with raw `subprocess` is churn without user-visible gain. Keep and watch for a release.
- `pycryptodome` and `nuitka` 2.8.4: not abandoned, but both constrain the Python 3.14 claim (DEP-03). Nuitka's next major is AGPL-3.0-only, a licensing change to decide, not an automatic bump.
- No direct dependency is a drop candidate. `pillow` is the only inert declaration (DEP-10).

### Lockfile and runtime-fetch exposure (answers the "yank" question)

- `uv.lock` (v1/revision 3) pins 75 packages with per-file URLs and SHA-256 hashes; longest dependency chain is 5 (`waves -> gamdl -> httpx-retries -> httpx -> anyio -> idna`). A yanked-but-present PyPI release still installs from the lock. If a file is deleted, a fresh `uv sync --locked` fails; nothing vendors wheels and no alternate index is configured. Sdist-only entries that require a source build: `construct`, `pyaes`, `ratelimit`, `nuitka`, `waves` itself (graph script over `uv.lock`, 2026-09-21). `setup-env/action.yml:36-67` retries PySide6's ~165 MB wheels three times and clears the uv cache between attempts, so a transient PyPI failure is handled; a permanent disappearance is not.
- Fetched at runtime, outside the lock: the wrapper image (pinned tag + digest, digest verified after pull, `runtime.py:892-913`), N_m3u8DL-RE (pinned version + inline SHA-256 table, `runtime.py:69-106`), and the managed FFmpeg (resolved to the latest upstream build each time, checksum from the same origin, `ffmpeg_manager.py:154-202,406-412`). yt-dlp and gamdl do not self-update; they arrive only through the lock.

## Findings

### DEP-01 - Pinned wrapper 0.2.3 ships without required notices

- severity: P0
- confidence: confirmed
- area: dependency / security
- tags: [obsolete]
- evidence: `waves/providers/apple/runtime.py:61-62` pins `ghcr.io/ranokay/waves-wrapper-v2:0.2.3` + digest; `docs/wrapper-image.md:20-24` states post-2026-09-15 images carry `/licenses` and provenance labels while "the currently published `0.2.3` predates them; the next publish carries them"; `docs/wrapper-image-license-review.md:35-57` records the AOSP notice and label fixes as pipeline-only; `.github/workflows/wrapper-image.yml:191-206` is the fix (COPY into `/licenses`), which the live tag does not contain.
- why it matters: Waves is the publisher of the public image end users pull. Apache-2.0/BSD attribution is a redistribution condition, and the pinned artifact does not carry it; the release ships the pre-fix bytes.
- proposed change: publish a new tag from the current pipeline (notices + OCI labels), then move `WRAPPER_V2_IMAGE`/`WRAPPER_V2_IMAGE_DIGEST` in `runtime.py` and the runbook/front-page digest in one commit per the lockstep table (`docs/wrapper-image.md:112-135`). Alternative: record an explicit release exception in the license review and README. Do not retag 0.2.3.
- acceptance criteria: publication path: [ ] new tag != `0.2.3` published from a recorded upstream SHA; [ ] `runtime.py:61-62` and `docs/wrapper-image.md:5` name the new tag and digest in the same commit; [ ] a local `docker pull` + `docker run --rm <image> ls /licenses` shows NOTICE, Apache-2.0, BSD-2-Clause, BSD-3-Clause; [ ] `pytest tests/packaging/test_wrapper_image_pins.py` passes. Exception path: [ ] the named human owner records the legal decision, affected artifact and expiry/revisit condition; [ ] user-facing release material states that the pinned image predates the notice fix; [ ] no text claims `/licenses` exists in `0.2.3`.
- evidence required to close: publication path: pin diff plus publish URL or pull transcript listing `/licenses/*`. Exception path: link to the recorded decision and the release-material diff.
- blocked by: the human choice to publish the fixed image or accept an exception.
- conditional sequencing: if publication is chosen, group DEP-08's workflow guard into the same deliverable before pushing the replacement tag.
- impact: blocks production publication. Related to DEP-07.
- effort: S
- needs human: yes (publish the image; or sign the exception)

### DEP-02 - pywidevine (GPL-3.0-only, Widevine CDM) rides gamdl into the bundle

- severity: P2
- confidence: likely
- area: dependency / security
- tags: [windows]
- evidence: `gamdl` 3.8.5 wheel `METADATA` (fetched from PyPI) has `Requires-Dist: pywidevine>=1.8.0`; `uv.lock` resolves `pywidevine` 1.9.0; the wheel's `gamdl/interface/base.py` does `from pywidevine import PSSH, Cdm, Device` and imports `pywidevine.license_protocol_pb2`; Waves imports that module at `waves/providers/apple/engine.py:294` and `tests/providers/apple/test_pinned_client_contract.py:24`; `rg pywidevine tools/ .github/` finds no `--nofollow-import-to` or bundle exclusion; `tools/inspect_bundle.py` does not list it.
- why it matters: a Widevine CDM/DRM library is compiled into an app whose Apple tier uses FairPlay through the wrapper, not Widevine. The wrapper license review covers Apple's `.so` files and never mentions pywidevine; the dependency brings GPL-3.0-only code and `protobuf` into the artifact.
- proposed change: decide explicitly. Option A (smallest change): add pywidevine to the wrapper-image-style license inventory and `inspect_bundle.py`'s expected module list so its presence is deliberate. Option B: if gamdl can be imported without `gamdl.interface.base`'s pywidevine import path, exclude it via `--nofollow-import-to=pywidevine` and prove the engine still imports; otherwise keep Option A.
- acceptance criteria: [ ] `inspect_bundle.py` names pywidevine and protobuf as expected-or-absent with a documented decision; [ ] a built bundle's inspection output matches; [ ] license review mentions the CDM.
- evidence required to close: `tools/inspect_bundle.py dist/...` output plus the recorded decision.
- depends on / blocks: none.
- effort: M
- needs human: yes (legal review of bundling a Widevine CDM)

### DEP-03 - Python 3.14 is claimed but the pinned toolchain stops at 3.13

- severity: P2
- confidence: confirmed
- area: packaging / dependency
- tags: [docs]
- evidence: `pyproject.toml:16-20` classifies 3.14 and allows `<3.15`; `mise.toml:9` pins Python 3.13; PyPI for `nuitka/2.8.4` lists classifiers only through 3.13 while `nuitka/4.2.1` adds 3.14 (and changes license to AGPL-3.0-only); `pycryptodome/3.23.0` publishes no `cp314` wheels (PyPI file list), so 3.14 installs build it from sdist; the only 3.14 leg is `master.yml:33-37`, which is `workflow_dispatch`-only (`master.yml:6-8`) and not in the release path.
- why it matters: the project advertises installability on 3.14 that neither the compiler nor a native dependency supports and no release gate exercises. The packaged app builds on 3.13 only.
- proposed change: either drop `3.14` from `classifiers` for this release (keep `<3.15`), or make 3.14 real by bumping to Nuitka 4.x (accept the AGPL build-tool license change) and running the 3.14 leg in the release workflow.
- acceptance criteria: [ ] classifiers match tested versions, or a green 3.14 run URL exists in the release workflow; [ ] `uv sync` on 3.14 either succeeds or is documented as unsupported.
- evidence required to close: pyproject diff, or CI run URL for a 3.14 leg.
- depends on / blocks: none.
- effort: S
- needs human: yes (whether to take Nuitka 4.x's AGPL)

### DEP-04 - Legacy macOS builds install Qt 6.9.3 outside the lock

- severity: P2
- confidence: confirmed
- area: dependency / packaging
- tags: [packaging]
- evidence: `.github/workflows/build-legs.json:22,29` run `uv pip install --force-reinstall --no-deps pyside6==6.9.3 pyside6-addons==6.9.3 pyside6-essentials==6.9.3 shiboken6==6.9.3` after `setup-env` ran `uv sync --locked` (`.github/actions/setup-env/action.yml:43-55`); `uv.lock` holds 6.11.1; Dependabot ignores `pyside6` (`.github/dependabot.yml:27`); no test asserts the 6.9.3 overlay (grep of `tests/` for `pyside6==`/6.9.3 is empty).
- why it matters: two shipped macOS assets (`*_legacy.zip`) embed a Qt version absent from the lock and from every pin-drift test. A future edit to `build-legs.json` could change the legacy runtime silently.
- proposed change: add a packaging test that parses `build-legs.json`, extracts every `pyside6==` pin in `cmd_build`, and asserts the legacy set is exactly the four packages at the documented version with `macos_floor` 12.0.
- acceptance criteria: [ ] new test fails if a legacy `cmd_build` loses or changes the overlay; [ ] test passes at HEAD.
- evidence required to close: test name and a local run output.
- depends on / blocks: none.
- effort: S
- needs human: yes (confirm test-only enforcement is enough vs a lockfile-encoded extra)

### DEP-05 - yt-dlp's "never bump alone" invariant is unenforced

- severity: P2
- confidence: confirmed
- area: dependency
- tags: []
- evidence: `pyproject.toml:33` declares `yt-dlp>=2025.10.22` with no upper bound (comment `pyproject.toml:31-32`); `docs/dependency-updates.md:45` says "Only with a gamdl bump; never bump it alone"; `uv.lock` holds 2026.8.19; `tools/build_waves.sh:66` excludes `yt_dlp.extractor.lazy_extractors` by name; `tests/packaging/test_ci_hygiene.py:206-219` only asserts the flag string, and `tests/providers/apple/test_pinned_client_contract.py` checks gamdl's surface, not yt-dlp's.
- why it matters: any `uv lock --upgrade` or grouped Dependabot lock refresh can move yt-dlp (no upper bound, only a docs rule), and a release could then ship an unvalidated yt-dlp or a missing `lazy_extractors` module with no failing test until the Windows/macOS build or live fetch.
- proposed change: add one test: the declared yt-dlp floor equals the `Requires-Dist` floor of the installed gamdl; the pinned `yt_dlp.extractor.lazy_extractors` module exists in the locked yt-dlp. Both are local and fast.
- acceptance criteria: [ ] test fails if pyproject's floor drifts from gamdl's; [ ] test fails if the locked yt-dlp drops the nofollow module.
- evidence required to close: test name, run output at HEAD.
- depends on / blocks: none.
- effort: S
- needs human: no

### DEP-06 - yt-dlp security fixes are blocked by the gamdl-only cadence

- severity: P3
- confidence: confirmed
- area: dependency / security
- tags: [docs]
- evidence: `docs/dependency-updates.md:45` gives yt-dlp cadence as "Only with a gamdl bump"; OSV (`api.osv.dev`, 2026-09-21) lists at least 8 historical yt-dlp advisories (e.g. GHSA-3ch3-jhc6-5r8x, GHSA-f7j3-774f-rfhj, GHSA-79w7-vh3h-8g4j); the resolved 2026.8.19 has none.
- why it matters: if a yt-dlp advisory lands between gamdl releases, the documented process forbids the only fix. yt-dlp ships in-process and parses untrusted manifests, so it is the highest-churn attack surface in the lock.
- proposed change: add one line to the runbook: a security advisory is a valid standalone bump reason; run the same gates (`mise run check`, full suite, live account suite) and note the advisory ID in the PR.
- acceptance criteria: [ ] runbook names the standalone security exception; [ ] `docs/dependency-updates.md` update table's yt-dlp row links it.
- evidence required to close: docs diff.
- blocked by: DEP-05 policy enforcement.
- effort: S
- needs human: no

### DEP-07 - Managed FFmpeg is resolved to "latest" at install time

- severity: P2
- confidence: confirmed
- area: dependency / security
- tags: [security]
- evidence: `waves/desktop/ffmpeg_manager.py:63-64` (`ffmpeg.martin-riedl.de`, `BtbN/FFmpeg-Builds`), `:154-202` resolves the newest build, `:377-378` installs on demand, `:406-412` verifies a checksum fetched from the same origin and the code itself states this is a corruption check, not proof of authenticity; no version constant exists anywhere in the file or in `docs/dependency-updates.md:49`.
- why it matters: every install downloads a different set of upstream bytes and executes them. A compromised mirror or GitHub release yields arbitrary code on user machines; there is no Waves-side pin to review in a diff. This is an accepted design risk, but it is not recorded as one anywhere in `docs/`.
- proposed change: decide and record. Minimum: add a "managed FFmpeg" row to `docs/dependency-updates.md` with the accepted same-origin-checksum posture and a review date. Stronger: pin the martin-riedl epoch version the app ships with (BtbN daily builds stay floating) and test the parser against it.
- acceptance criteria: [ ] a doc states the accepted posture or the version pin; [ ] any pin is asserted by a test in `tests/packaging/test_ffmpeg_manager.py`.
- evidence required to close: docs diff or test name.
- depends on / blocks: none.
- effort: S
- needs human: yes (accept vs pin)

### DEP-08 - wrapper-image workflow can republish the live tag, and defaults to `main`

- severity: P3
- confidence: confirmed
- area: dx / dependency
- tags: [packaging]
- evidence: `.github/workflows/wrapper-image.yml:26-34` defaults `wrapper_ref: main` and `image_tag: 0.2.3`; `:214` pushes `$IMAGE:$TAG` unconditionally; there is no pre-push existence check in the job; `docs/wrapper-image.md:129-134` says "Never retag a published tag in place". The pin test (`tests/packaging/test_wrapper_image_pins.py:44-51`) forces the default tag to equal the runtime pin, which is currently the published 0.2.3.
- why it matters: a maintainer dispatching with defaults overwrites the tag the app's digest pin references; every client that pulls before the next app update gets bytes the app then refuses (`runtime.py:898-901`), and the documented provenance of `0.2.3` is destroyed.
- proposed change: before build, fail if `docker buildx imagetools inspect $IMAGE:$TAG` resolves, unless an explicit `allow_overwrite=true` input is set; require a full SHA for `wrapper_ref` (reject `main` with an error).
- acceptance criteria: [ ] a dispatch with an existing tag fails without the override input; [ ] `wrapper_ref` other than a 40-hex SHA fails.
- evidence required to close: workflow diff plus a run URL showing the guard.
- blocked by: none.
- impact: blocks DEP-01 publication of a replacement tag, but not DEP-01's legal-exception path.
- effort: S
- needs human: no

### DEP-09 - No third-party license notices ship with the app bundle

- severity: P2
- confidence: likely
- area: dependency / docs
- tags: [packaging]
- evidence: `rg -rn "LGPL|THIRD_PARTY|third.party" tools/ packaging/ docs/ .github/` matches nothing outside the wrapper-image files; `tools/build_waves.sh` has no notice step; `tools/trim_qt_bundle.sh` trims Qt without adding notices; the only notice pipeline is `.github/workflows/wrapper-image.yml:191-206`. Bundled deps include PySide6 (LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only), tidalapi (LGPL-3.0-or-later), mutagen (GPL-2.0-or-later), pywidevine (GPL-3.0-only, DEP-02).
- why it matters: LGPL-3.0 §4 combined-work distribution requires notices and a relinking path; GPL-family code requires source/notice preservation. The app is AGPL (source published), but the notices are not in the artifact, and Qt's shared libraries are trimmed by `trim_qt_bundle.sh`.
- proposed change: ship a `THIRD_PARTY_NOTICES` (and the license texts) beside the app in each bundle, generated from the lock's metadata plus Qt's texts; add it to `inspect_bundle.py`'s expected list. Keep the LGPL libraries as separate shared libraries (do not static-link Qt) if a relinking claim is to be made; confirm with legal.
- acceptance criteria: [ ] each built bundle contains THIRD_PARTY_NOTICES and license texts; [ ] inspection fails when absent.
- evidence required to close: bundle listing plus inspection test.
- blocked by: DEP-02 bundling decision.
- effort: M
- needs human: yes (legal sign-off on LGPL compliance model)

### DEP-10 - pillow is declared dev but has no importer

- severity: P3
- confidence: confirmed
- area: dependency
- tags: [obsolete]
- evidence: `pyproject.toml:66` declares `pillow>=12.0.0,<13`; `rg "from PIL|import PIL"` across `waves/`, `tools/`, `tests/` finds nothing; the icon test parses the `.ico` with `struct` (`tests/packaging/test_app_icon.py:12,22-30`); `.venv/bin/deptry .` reports "Success! No dependency issues found." while scanning 67 files; `tests/` is in deptry's default exclude list (`deptry --help`), and every unimported dev entry (pytest, ruff, nuitka, pillow) passes the gate, so deptry does not catch this declaration.
- why it matters: is declared for no visible reason; it is already in the lock as gamdl's transitive dependency, so the dev entry changes nothing except implying a build use that does not exist.
- proposed change: remove the pillow dev entry, or add a comment naming its purpose (for example a deliberate floor on gamdl's transitive Pillow for advisories). Behavior-freeze: no code change.
- acceptance criteria: [ ] pyproject no longer declares pillow as dev, or the entry carries a purpose comment; [ ] `uv lock --check` and `deptry .` pass.
- evidence required to close: pyproject diff and gate output.
- depends on / blocks: none.
- effort: S
- needs human: no

### DEP-11 - docs/dependency-updates.md omits three tracked surfaces

- severity: P3
- confidence: confirmed
- area: docs
- tags: [docs]
- evidence: the update table (`docs/dependency-updates.md:42-52`) has no Python-version row, no legacy-macOS Qt overlay row (`build-legs.json:22,29`), and no pywidevine/CDM row (DEP-02); it is otherwise accurate: gamdl `>=3.8.5,<3.9` matches `pyproject.toml:28`; yt-dlp's floor matches gamdl's wheel METADATA; Dependabot's ignores match `.github/dependabot.yml:24-27`; the pin-drift and CI-hygiene tests it names exist (`tests/packaging/test_wrapper_image_pins.py`, `tests/packaging/test_ci_hygiene.py:57`).
- why it matters: the runbook is the only place a human learns the non-lock moves; the three missing rows are exactly the ones that silently rot (3.14 support claim, legacy Qt, CDM presence).
- proposed change: add a "Python version support" row, a "legacy macOS Qt overlay" row pointing at `build-legs.json`, and a pywidevine line under gamdl; no deletions. Verdict for the file: keep with these edits.
- acceptance criteria: [ ] three rows present with the pinned values; [ ] existing rows unchanged.
- evidence required to close: docs diff.
- blocked by: DEP-02, DEP-03 and DEP-04 decisions.
- effort: S
- needs human: no

## Claims checked

| claim                                                                   | source                                                                                  | verdict                                                                                                                                                                |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| yt-dlp floor equals gamdl's own requirement                             | `pyproject.toml:31-33` comment                                                          | true: gamdl 3.8.5 wheel METADATA has `Requires-Dist: yt-dlp>=2025.10.22`, exact match                                                                                  |
| gamdl is pinned to 3.8.x                                                | `pyproject.toml:28`, `docs/dependency-updates.md:44`                                    | true: `>=3.8.5,<3.9`; 3.8.5 is current                                                                                                                                 |
| python-ffmpeg and the ffmpeg binary are separate                        | `pyproject.toml:30`, `waves/download.py:4777`                                           | true: `python-ffmpeg` has no runtime deps on PyPI; app calls `FFmpeg(executable=self.settings.data.path_binary_ffmpeg)` and provisions the binary via `ffmpeg_manager` |
| wrapper tag/digest agree across code, runbook, workflow defaults        | `runtime.py:61-62`, `docs/wrapper-image.md:5`, `.github/workflows/wrapper-image.yml:34` | true: all `0.2.3` / `sha256:1aac…be15`; tests at `test_wrapper_image_pins.py:44-51,96-98`                                                                              |
| APK pin agrees across code, workflow and runbook                        | `runtime.py:109`, `wrapper-image.yml:39,44`, `docs/wrapper-image.md:59,121`             | true: `3.6.0-beta` build `1109` everywhere                                                                                                                             |
| the app refuses a pull whose digest differs from the pin                | `docs/wrapper-image-license-review.md:58-67`                                            | true when the runtime reports a digest (`runtime.py:898-901`); runtimes that report none record `digest_ok: None` and are tolerated (`runtime.py:906-913`)             |
| pin-drift tests cover image tag, digest, APK and runbook                | `docs/dependency-updates.md:35`                                                         | true (`test_wrapper_image_pins.py`); they compare constants and docs, not the registry bytes                                                                           |
| Dependabot ignores gamdl/yt-dlp/Nuitka/PySide6 and the test enforces it | `docs/dependency-updates.md:100-101`                                                    | true: `.github/dependabot.yml:24-27`, `tests/packaging/test_ci_hygiene.py:57`                                                                                          |
| `uv.lock` is current with pyproject                                     | `docs/dependency-updates.md:52`                                                         | true: `uv lock --check` exit 0, 75 packages                                                                                                                            |
| no unused/undeclared direct dep                                         | repo gate `mise run check` (deptry step)                                                | true at HEAD: `.venv/bin/deptry .` = "Success! No dependency issues found." (67 files; `tests/` excluded by deptry default)                                            |
| no advisory touches the locked set                                      | OSV API query per package/version, 2026-09-21                                           | true for all 21 direct deps at resolved versions                                                                                                                       |
| Python 3.14 works                                                       | `pyproject.toml:16-18` classifiers                                                      | false as packaged: pinned Nuitka 2.8.4 classifies ≤3.13, pycryptodome 3.23.0 has no cp314 wheels; only a manual CI leg would test it (`master.yml:6-8,33-37`)          |
| the shipped image carries third-party notices                           | `docs/wrapper-image.md:20-24`                                                           | false for the pinned `0.2.3` (pre-fix), by the doc's own words (DEP-01)                                                                                                |
| wrapper image digest was verified against the published image           | `docs/wrapper-image-license-review.md:6-10`                                             | unverified here: requires a `docker pull` + `docker image inspect`; the review records a 2026-09-15 local pull at 328 MB matching the digest                           |

## Top 3

1. DEP-01: the pinned wrapper image `0.2.3` lacks the `/licenses` notices and provenance labels its own review says are required; the release ships the pre-fix bytes.
2. DEP-02: pywidevine 1.9.0 (GPL-3.0-only Widevine CDM) enters the compiled bundle through `gamdl.interface.base` with no license review and no bundle inspection entry.
3. DEP-04: the two legacy macOS assets embed Qt 6.9.3 installed outside `uv.lock`, with no test tying the overlay to the leg definition.

## Release blockers

- DEP-01 (P0): publish a post-2026-09-15 wrapper image and move the tag/digest pins in one commit, or record an explicit release exception. If publication is chosen, DEP-08 joins this priority-0 deliverable; the remaining P2/P3 dependency work can follow normal prioritization.

## Open questions

1. Publish a fixed wrapper image before the release, or ship `0.2.3` with a recorded exception? Recommended default: publish; the pipeline change already exists.
2. Is a Widevine CDM acceptable inside the app, or must it be excluded? Recommended default: document its presence first (fast, definite), decide exclusion separately.
3. Drop the Python 3.14 classifier for this release, or take Nuitka 4.x's AGPL to support it? Recommended default: drop the classifier now.
4. Accept floating managed-FFmpeg resolution, or pin one martin-riedl epoch? Recommended default: accept and document, revisit on the first break.
5. When to review the stagnant-but-stable three (`dataclasses-json`, `m3u8`, `python-ffmpeg`)? Recommended default: one dated maintenance issue, not a prerequisite refactor.
6. Add bundle-wide third-party notices now or defer? Recommended default: add in the same packaging change that touches the bundle next, tracked as its own issue.

---

## Docs, DX and agent tooling audit

Area verdict: the docs tree is large and mostly current. The intentional ADR
and evidence deletions expose guards and live references that must be removed or
repointed if that cleanup is kept. The README contradicts the Windows park in
two places, and the DX task surface has no doctor, clean or fmt task. The global
opencode config loads a large agent toolset whose fit for a Python/Qt/QML repo
is mixed; two tooling repairs were completed during the audit.

Scope note: everything below is read-only. The `docs/adr` and `docs/evidence`
deletions were intentional audit conditions. They are recorded after the open
findings, not counted as defects in `a2a13cd`.

## Inventory

`| path | lines | audience | purpose | depth | verdict | specific fixes |`

| path                                                    | lines | audience              | purpose                                               | depth   | verdict         | specific fixes                                                                                                                                                                                         |
| ------------------------------------------------------- | ----: | --------------------- | ----------------------------------------------------- | ------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `README.md`                                             |   279 | users, contributors   | landing, install, feature list, privacy, license      | deep    | rewrite         | fix Windows claims (28, 45, 102); drop "What's new" (74-103) as duplicated changelog; point the star-history and release links at the fork                                                             |
| `DEVELOPER.md`                                          |   218 | contributors          | architecture, threading, test groups, gates           | deep    | trim            | remove the snapshot case counts (137-143); dedupe config-dir list against `CONTEXT.md`/README; automate the stale-install recovery (175-180) into a task                                               |
| `CONTRIBUTING.md`                                       |   133 | external contributors | contribution flow                                     | deep    | rewrite         | repoint issues/PRs at `ranokay/waves` (12, 36); the branch/PR/check steps (78-122) duplicate `docs/agents/implementation-workflow.md`; "add the feature to the list in README" (132-133) names no list |
| `CONTEXT.md`                                            |    67 | agents, contributors  | domain glossary                                       | deep    | keep            | add missing terms (see DOC-05); keep it glossary-only                                                                                                                                                  |
| `CHANGELOG.md`                                          |   915 | users                 | release notes, per-release format                     | sampled | keep            | format is test-enforced (`tests/packaging/test_changelog_format.py`); no action                                                                                                                        |
| `AGENTS.md`                                             |    66 | agents                | entry point, graph-tool guidance                      | deep    | keep            | its `docs/adr/` pointer (19) dies with the deletion proposal                                                                                                                                           |
| `docs/apple-music-provider-spec.md`                     |   332 | implementers          | Apple provider spec                                   | deep    | refactor        | APK-supply step is stale (see DOC-06); otherwise the reference the provider was built from                                                                                                             |
| `docs/platform-enablement-review.md`                    |   187 | maintainers           | Windows/Linux enablement record                       | deep    | refactor        | revalidation due today (see DOC-07); evidence rows duplicate `docs/evidence/platform-builds.md`                                                                                                        |
| `docs/review-thread-dispositions.md`                    |   171 | maintainers, agents   | 98 P1/P2 review-thread verdicts                       | sampled | keep            | load-bearing: `tests/packaging/test_repository_docs.py:180` pins all 98 ids; update citations as lines drift                                                                                           |
| `docs/wrapper-image.md`                                 |   155 | maintainers           | wrapper image runbook                                 | sampled | keep            | digest matches `runtime.py`; no action                                                                                                                                                                 |
| `docs/wrapper-image-license-review.md`                  |    83 | maintainers, legal    | license and accepted-risk record                      | sampled | keep            | replace the dead audit transcript cite (10) with `docs/evidence/wrapper-image-inspection.md`                                                                                                           |
| `docs/agents/domain.md`                                 |    51 | agents                | where domain docs live                                | deep    | trim            | the CONTEXT-MAP and multi-context scaffolding (20-38) does not describe this repo; keep the ADR-conflict rule                                                                                          |
| `docs/agents/implementation-workflow.md`                |    22 | agents                | merge loop, branch topology                           | deep    | keep            | canonical workflow; CONTRIBUTING should point here instead of restating it                                                                                                                             |
| `docs/agents/issue-tracker.md`                          |    45 | agents                | gh conventions, fork pin                              | deep    | keep            | no action                                                                                                                                                                                              |
| `docs/agents/triage-labels.md`                          |    15 | agents                | label vocabulary map                                  | deep    | keep            | no action                                                                                                                                                                                              |
| `docs/research/alac-verification.md`                    |    59 | implementers          | ALAC source corruption, why the integrity gate exists | sampled | keep            | cited by `tests/downloads/test_apple_integrity_gate.py:60`                                                                                                                                             |
| `docs/research/apple-catalog-surface.md`                |   132 | implementers          | Apple catalog API facts                               | sampled | keep            | still the catalog reference; no action                                                                                                                                                                 |
| `docs/research/gamdl-eval.md`                           |    83 | implementers          | chosen engine evaluation                              | sampled | keep            | add a one-line "decision: adopted, see spec §1" header                                                                                                                                                 |
| `docs/research/zhaarey-eval.md`                         |    76 | implementers          | rejected engine (no license)                          | sampled | keep            | the license disproof is the reason it was not vendored; keep                                                                                                                                           |
| `docs/research/worldobs-eval.md`                        |    85 | implementers          | wrapper lineage evaluation                            | sampled | keep            | superseded by the wrapper-v2 decision; add status header                                                                                                                                               |
| `docs/research/provider-seam-analysis.md`               |   311 | implementers          | pre-refactor seam inventory                           | sampled | delete          | cites `waves/waves_ui/backend.py` and commit `d4c0a87`; the seam shipped, the inventory is stale                                                                                                       |
| `.opencodereview/rule.json`                             |    30 | OCR bot               | house rules, include list                             | deep    | keep            | rule 1 depends on `docs/adr/` existing                                                                                                                                                                 |
| `.pre-commit-config.yaml`                               |    73 | contributors          | hooks                                                 | deep    | refactor        | duplicate `pre-commit/pre-commit-hooks` block (7-20 and 47-52); see DX-05                                                                                                                              |
| `docs/adr/*.md` (9, intentionally deleted locally)      |   556 | agents, contributors  | decision records                                      | deep    | policy decision | tests and live references must change if deletion is kept                                                                                                                                              |
| `docs/evidence/*.md` (4, intentionally deleted locally) |   116 | maintainers           | acceptance evidence + index                           | deep    | policy decision | keep only durable evidence; update guards if deletion is kept                                                                                                                                          |

`docs/dependency-updates.md` is owned by the deps agent and not audited here.

## Findings

### DOC-01 - README claims Windows support while saying the builds are parked

- severity: P1
- confidence: confirmed
- area: docs
- tags: [windows]
- evidence: `README.md:28` ("native desktop app for macOS, Windows, and Linux (Intel/AMD and Apple-silicon/ARM)") and `README.md:45` ("Run native on macOS, Windows, and Linux") versus `README.md:148` ("**Windows builds are parked** ... no Windows asset ships") and `README.md:13`, whose platform badge reads `platforms-macOS · Linux`. The park is real: `.github/workflows/build-legs.json` defines the two Windows legs, `docs/evidence/platform-builds.md` records every Windows run as failed, and `docs/adr/0009-windows-builds-parked.md` (HEAD) states no all-platform release can be cut while parked. `README.md:102` also sells "Silent background work on Windows" as shipped.
- why it matters: the README is the product storefront and simultaneously promises and disclaims Windows. A reviewer or user reads the first two claims as shipped support.
- proposed change: make the platform claim conditional in both places, e.g. "runs natively on macOS and Linux; Windows builds are parked (see the Install note)". Move the Windows-only bullet (`README.md:102`) under the Install park note. Do not delete the Windows asset rows: `README.md:148` already labels them as future assets, and the release workflow still defines those names.
- acceptance criteria: [ ] no README sentence asserts Windows support without the park qualifier; [ ] `rg -n "Windows" README.md` shows every hit either inside the park note or explicitly future-tense; [ ] the badge, line 13, matches the platform sentence.
- evidence required to close: `rg -n "Windows" README.md` output in the PR.
- blocked by: none. If the ADR deletion is kept, replace the park-note link in the same deliverable.
- effort: S
- needs human: no

### Intentional documentation deletions

The nine ADRs and four evidence files exist in `a2a13cd` but were removed from
the audit worktree on purpose. The current deletion fails repository guards and
breaks live references in `README.md`, the Apple provider spec, wrapper license
review, `AGENTS.md`, `docs/agents/domain.md` and OpenCodeReview rules. This is a
policy decision, not an open audit finding. If the deletion is kept, create one
issue to relocate any durable rationale or legal/release evidence, remove stale
references, and update the guards. If it is rejected, restore the files. Do not
create separate restoration issues or treat restoration as automatic.

### DOC-04 - README "What's new" is a second changelog and duplicates the feature list

- severity: P1
- confidence: confirmed
- area: docs
- evidence: `README.md:74-103` ("What's new in Waves") duplicates the capability bullets at `README.md:32-45` (search, preview, queue, library scan, ffmpeg, updates) and carries no version anchor at all. The actual deltas for the coming release live in `CHANGELOG.md:25-39` (Flatpak, Providers area), which the README install section separately describes as shipped (`README.md:170-176`). Line 96 is version-relative with no version ("This covers music saved from this version onward").
- why it matters: two documents own release history, so one is always stale, and the README's present-tense "new" claims go incorrect at the next cut. `CONTEXT.md` and the CHANGELOG already exist to carry the two distinct jobs (feature semantics, release history).
- proposed change: delete the "What's new in Waves" section; point users at the Releases page/`CHANGELOG.md`. If a highlights section is wanted, keep it to the current release's three to five bullets and source it from the same text the CHANGELOG uses. Keep the deep feature documentation in `README`'s "What Waves can do" only.
- acceptance criteria: [ ] `README.md` has one features section; [ ] no README sentence claims a feature is "new" without naming the release; [ ] Flatpak is described in README only as install instructions.
- evidence required to close: `rg -n "What's new" README.md` returns nothing.
- depends on / blocks: none.
- effort: M (the section is 30 dense lines)
- needs human: yes (how much feature prose to retain)

### DOC-05 - CONTEXT.md is missing four terms the code and UI use consistently

- severity: P2
- confidence: confirmed
- area: docs
- evidence: defined terms pin at `tests/packaging/test_repository_docs.py:40,66-69` (Onboarding, My Music, Saved vs Library). Used consistently but undefined in `CONTEXT.md`: **Capability** (`waves/providers/base.py:116 class Capability(StrEnum)`, `:544`), **Edition** (`waves/library/index.py:2447,2769,2824`; the Settings switch "Show every edition on artist pages", `README.md:87`), **Held** (`waves/desktop/backend.py:3142` "held until its turn comes", `:4074-4079` held downloads resumed on remount), **Twin** (`waves/metadata/matching.py:1075 twin_key`, `:1095 meets_twin`). `Shelf` appears 23 files but is already covered inside the My Music definition; no separate entry needed.
- why it matters: the repo's own agent rules (`AGENTS.md`, `.opencodereview/rule.json:27` rule 2) tell authors to use the glossary's vocabulary; four load-bearing concepts have none, so issues and reviews drift to synonyms (capability set, release, pending, duplicate).
- proposed change: add four entries with an `_Avoid_` line each, in the existing style: Capability (avoid "feature flag", "permission"), Edition (avoid "version", "release", "variant"), Held (avoid "pending", "paused", "waiting"), Twin (avoid "duplicate", "match", "copy"). Note in Held that it is queue state distinct from Stopped.
- acceptance criteria: [ ] four terms defined; [ ] every existing term keeps `_Avoid_`; [ ] the guard test stays green.
- evidence required to close: diff of `CONTEXT.md` plus `mise run test-strict` on `tests/packaging/test_repository_docs.py`.
- depends on / blocks: none.
- effort: S
- needs human: no

### DOC-06 - Apple spec still specifies the APK-supply step that was removed

- severity: P2
- confidence: confirmed
- area: docs
- evidence: `docs/apple-music-provider-spec.md:249` describes the wizard as "managed runtime provisioning → Apple ID login + 2FA → **APK supply**", and `:259` states "The Apple Music APK is user-supplied ... The wizard guides the user to source the pinned version ... verifies it by SHA-256, and scripts the `.apkm` extraction". The code and later decisions reversed this: `waves/providers/apple/runtime.py:7-8` ("The image carries the guest libraries, so no APK is provisioned or supplied at runtime"), ADR 0005, and `README.md:44` ("a cookies export unlocks AAC 256 and Atmos downloads"). The spec does carry amendment notes at `:258` and `:261` for §10, but `§9.2 item 3` (`:249`) and `§10 item 2` (`:259`) still read as live instructions.
- why it matters: the spec is named as the implementation input in `docs/agents`-adjacent docs and is the first place an agent looks. A wizard step that no longer exists reads as a missing feature, not a removed one.
- proposed change: amend `§9.2 item 3` to the current wizard shape (runtime provisioning → Apple ID login + 2FA; cookies tier always offered), and mark `§10 item 2` superseded in place with `ADR 0005` (the file already uses that pattern). Do not rewrite the decision history; annotate it.
- acceptance criteria: [ ] neither line presents APK supply as a current step; [ ] each change carries the `Amended by`/`Superseded` marker the file already uses; [ ] `rg -n "APK supply" docs/apple-music-provider-spec.md` returns only annotated history.
- evidence required to close: diff plus the rg output.
- depends on / blocks: none.
- effort: S
- needs human: no

### DOC-07 - Windows park review duplicates evidence and its revalidation trigger is today

- severity: P2
- confidence: confirmed / likely (the re-run itself is unverified)
- area: docs
- tags: [windows]
- evidence: `docs/platform-enablement-review.md:45-68` repeats the CI rows that `docs/evidence/platform-builds.md` owns, including the same run ids and conclusions, with a pointer to the evidence file at `:78`. The doc's own gap 5 (`:164-171`) says Windows arm64 runners migrate to Visual Studio 2026 "on 2026-09-21, which may change the compiler's behavior; revalidate then" - today's date is 2026-09-21 and no post-exclusion Windows run exists in `docs/evidence/platform-builds.md` or the review. `tools/build_waves.sh:66` still appends `--nofollow-import-to=yt_dlp.extractor.lazy_extractors`, so the recipe is live, and the park reasoning (MSVC dies on that generated module) is otherwise confirmed by the four failed runs.
- why it matters: the release cannot be cut on an all-platform release trigger while the park holds (ADR 0009), so "revalidate now" is the critical path, not a note.
- proposed change: keep the review's analysis sections; replace the CI tables with a one-line pointer to `docs/evidence/platform-builds.md`. Dispatch the two Windows legs on the exclusion recipe (with the VS 2026 image) and append the outcome to the evidence file, then either lift the park in ADR 0009 or record the new failure.
- acceptance criteria: [ ] no CI table duplicated between the two files; [ ] the evidence file gains a post-exclusion row for each Windows leg; [ ] ADR 0009 status updated to reflect the result.
- evidence required to close: two GitHub Actions run URLs in `docs/evidence/platform-builds.md`.
- blocked by: BUILD-01 platform decision and a post-exclusion Windows run.
- effort: M
- needs human: yes (dispatch the Windows runs; only a human can spend the CI minutes)

### DOC-08 - CONTRIBUTING sends external contributors to the upstream tracker

- severity: P2
- confidence: confirmed
- area: docs
- evidence: `CONTRIBUTING.md:12` and `:36` direct issue reports to `https://github.com/iamprivacy/Waves/issues` (upstream), while `docs/agents/issue-tracker.md:14` says this fork's issues live on `ranokay/waves` and every `gh` call must be pinned there because unpinned calls "silently target the wrong repository". `CONTRIBUTING.md:100-114` restates the branch/check/test-strict loop that `docs/agents/implementation-workflow.md:19-40` already owns, and `:132-133` tells contributors to "add the feature to the list in `README.md`", a list that does not exist (README has "What Waves can do", not a changelog list).
- why it matters: outside contributors will file issues on the parent repo, where this fork's agents do not look; the duplicated workflow text can drift from the canonical doc.
- proposed change: repoint both issue URLs to `ranokay/waves/issues`; replace steps 5-10 with a link to `docs/agents/implementation-workflow.md` plus the contributor-facing minimum (branch, `mise run check`, `mise run test-strict`); drop the README-list instruction or name the real section.
- acceptance criteria: [ ] `rg -n "iamprivacy/Waves/issues" CONTRIBUTING.md` returns nothing; [ ] CONTRIBUTING's workflow section is a pointer, not a parallel copy; [ ] no instruction names a nonexistent README list.
- evidence required to close: diff.
- depends on / blocks: none.
- effort: S
- needs human: no

### DX-01 - mise run check writes to the tree; there is no format-only task

- severity: P2
- confidence: confirmed
- area: dx
- evidence: `mise.toml:16-19` defines `check` as lock drift + `pre-commit run -a` + deptry. The hooks it runs mutate files: `ruff format` (`.pre-commit-config.yaml:32-37`, entry `uv run ... ruff format`), `prettier` (`:39-45`, formats Markdown), and `qmlformat` (`:54-60`, `tools/format_qml.sh` runs `qmlformat -i`). A developer running the documented static gate gets a failed run and a modified working tree with no task that says "format my changes". CI (`master.yml:31` `mise run check`) depends on this failing when files are unformatted.
- why it matters: "check" that writes is a footgun before every commit, and the repo has no `fmt` alias for the three formatters it actually uses.
- proposed change: add `mise run fmt` (ruff format + qmlformat + prettier, i.e. the mutating hooks) and keep `check` read-only by running the same hooks with a fail-diff mode, or document on the task that it will rewrite files and must be re-run. Minimal version: rename nothing, add the `fmt` task and one line to `DEVELOPER.md`.
- acceptance criteria: [ ] `mise run fmt` exists and formats Python, QML and Markdown; [ ] a dirty unformatted tree fails `mise run check` without being silently rewritten, or the task description says it rewrites; [ ] DEVELOPER.md names both tasks.
- evidence required to close: `mise run fmt` then `mise run check` output in the PR.
- depends on / blocks: none.
- effort: S
- needs human: no

### DX-02 - No doctor task for the documented stale-install failure

- severity: P2
- confidence: confirmed
- area: dx
- evidence: `DEVELOPER.md:175-180` documents the exact recovery for a stale editable install (`uv pip uninstall tidaler`, then `mise run install`) and the confusing symptom (the app opens against `Waves-dev` and looks signed out). `mise.toml` has no `doctor` task; the only entry points are install/check/test/app/build.
- why it matters: this is the first failure a contributor hits after the package rename, and the fix is manual and easy to miss. An agent hitting it will not know to look in DEVELOPER.
- proposed change: add `mise run doctor` that prints Python/uv/mise versions, verifies the `waves` distribution is installed and `tidaler` is not, checks `uv lock --check`, the pre-commit hook install and a QML import smoke (`pyshell` not needed), and names the fix for each failure.
- acceptance criteria: [ ] task exists and exits nonzero on a stale install; [ ] it detects an uninstalled pre-commit hook; [ ] DEVELOPER.md's recovery paragraph points at it.
- evidence required to close: `mise run doctor` output in both states.
- depends on / blocks: none.
- effort: S
- needs human: no

### DX-03 - Evidence capture has no task, and docs/evidence asks for reproducibility

- severity: P2
- confidence: confirmed
- area: dx
- evidence: the deleted `docs/evidence/bundle-inspection.md` names a repeatable bundle-inspection command, while CI and release workflows already own run logs and artifacts. The repository has no single task for the durable manual checks that cannot be reconstructed later, such as inspecting a published wrapper image.
- why it matters: durable legal or release facts need a repeatable capture path, but generated test and build logs should remain in CI rather than be copied into the repository.
- proposed change: after the documentation-policy decision, add a narrowly scoped task only for retained durable evidence, such as bundle inspection and wrapper image provenance. Print output to stdout or an explicit destination; do not generate progress scaffolding or latest-run files.
- acceptance criteria: [ ] each retained durable evidence file names a repeatable command and producing revision; [ ] ordinary test/build evidence remains linked from CI; [ ] the task does not rewrite unrelated docs.
- evidence required to close: task output and the updated guard for whichever evidence policy is chosen.
- blocked by: intentional documentation-deletion policy.
- effort: M
- needs human: no

### DX-04 - mise run star-history cannot run in this clone

- severity: P2
- confidence: confirmed
- area: dx
- evidence: `mise.toml:65-67` defines `star-history` as `bash tools/sync_star_history.sh`. The script requires a git remote named `public` (`tools/sync_star_history.sh` `PUBLIC_REMOTE="public"`, then `git remote get-url "$PUBLIC_REMOTE" || error 'remote public is not configured'`). `git remote -v` in this checkout lists only `origin` (ranokay/waves) and `upstream` (iamprivacy/Waves). Also `.github/workflows/star-history.yml:27` guards `if: github.repository == 'iamprivacy/Waves'`, so the chart can never be generated on this fork. The README's star-history block (`README.md:206-211`) therefore drifts, and the task that supposedly fixes it always exits 1.
- why it matters: a documented mise task that cannot run is worse than no task; the README carries a chart this repo cannot refresh.
- proposed change: either add the missing remote convention (`git remote add public <url>` in the script's error text or the task description) or make the task accept an upstream remote name and default it to `upstream` when `public` is absent. Also state in `tools/sync_star_history.sh` that the chart is upstream's.
- acceptance criteria: [ ] `mise run star-history` succeeds in this clone after `git remote add public ...`, or the task/script names the exact command to add it; [ ] the README star block is either refreshed or labelled as upstream's chart.
- evidence required to close: a successful `mise run star-history` run in the PR.
- depends on / blocks: none.
- effort: S
- needs human: no

### DX-05 - Duplicate hooks, qmllint run twice, and no clean or account task

- severity: P3
- confidence: confirmed
- area: dx
- evidence: `.pre-commit-config.yaml` declares `pre-commit/pre-commit-hooks` twice (lines 7-20 and 47-52), repeating `check-yaml` and `end-of-file-fixer` with different excludes, so each file is checked twice and the LICENSE exclusion (`:52`) is defeated by the first block (`:17-20` does not exclude LICENSE). `mise run check` depends on `lint-qml` (`mise.toml:18`) and then runs `pre-commit run -a` (`:19`), whose `qmllint` hook (`:61-65`) lints the whole tree again. There is also no task for the live account group, which `DEVELOPER.md:144` documents as a raw `WAVES_ACCOUNT_TESTS=1 uv run ...` command while every other group has a wrapper. HYG-01 owns `mise run clean`.
- why it matters: small, repeated friction on the path every contributor and agent takes; the duplicated hooks also mean two different exclude policies run against one file, which is a silent behavior difference from the documented one.
- proposed change: delete the second `pre-commit-hooks` block or merge its excludes into the first; in `check`, either drop the `lint-qml` dependency or run qmllint only through pre-commit; add `mise run test-account`.
- acceptance criteria: [ ] each hook id appears once; [ ] a full `mise run check` invokes qmllint once; [ ] `mise run test-account` mirrors DEVELOPER's command.
- evidence required to close: `pre-commit run -a -v` output plus `mise tasks`.
- depends on / blocks: none.
- effort: S
- needs human: no

### TOOL-02 - cua-driver should be limited to native built-bundle claims

- severity: P2
- confidence: likely
- area: dx
- evidence: `~/.config/opencode/opencode.json` enables the `cua-driver` MCP (huge tool surface: AX snapshots, pixel clicks, window frames, recorder). This repo's UI is PySide6/Qt Quick; its own rules require QML assertions through `objectName` plus `visible === true` in a subprocess scenario (`.opencodereview/rule.json:12` rule 5, rule 22 rule 2) and `mise run test-qml` is the supported path (`mise.toml:41-43`). cua-driver's AX walk on Qt Quick returns generic roles, and its own description warns that transport success is not proof of UI effect, so it would spend seconds per call to produce weaker evidence than the QML scenarios.
- why it matters: every enabled MCP tool costs context and invites an agent to verify UI by screenshot instead of the repo's tests.
- proposed change: keep routine UI verification in offscreen QML and real-process tests. Use cua-driver only for a bounded built-bundle smoke whose claims require native rendering or OS integration: real hover, window chrome and geometry, DPI, fonts, modal dialogs and menu actions. Do not use pixel automation as evidence for data or state rules already covered below the native layer.
- acceptance criteria: [ ] the documented verification ladder assigns routine behavior to QML/process tests; [ ] any cua-driver smoke names the native-only claim and verifies a postcondition; [ ] no screenshot substitutes for a behavioral assertion available in the test harness.
- evidence required to close: one bounded smoke definition and an attached run for a built artifact.
- depends on / blocks: none.
- effort: S
- needs human: yes (whether to keep the tool globally enabled)

### TOOL-03 - Graph freshness is unguarded and semantic embeddings are absent

- severity: P2
- confidence: confirmed
- status: the plugin load failure was fixed under TOOL-06 and the graph was manually rebuilt at the audited revision. Embeddings are still 0, so semantic search falls back to keyword. A normal-session edit has not yet proved the repaired auto-update hook.
- area: dx
- evidence: `AGENTS.md:23-27` tells agents to start with code-review-graph tools and `:62` says "The graph auto-updates on file changes (via hooks)". At audit start, `list_graph_stats_tool` reported `built_at_sha: 7710316...`, `head_sha: a2a13cd...`, `head_matches_build: false` and zero embedded nodes. TOOL-06 repaired the plugin load, and the coordinator rebuilt the graph manually so `head_matches_build` became true. No subsequent edit was observed to prove the hook, and semantic search still falls back to keyword matching.
- why it matters: an agent can spend its first search against stale data or assume keyword fallback is semantic search. The repository correctly says source wins, so the failure is survivable but wastes time and can narrow exploration incorrectly.
- proposed change: verify the repaired hook with one normal-session edit. If it does not refresh, add a `mise run graph` task and tell agents to rebuild whenever `head_matches_build` is false. State that semantic search uses keyword fallback until embeddings are intentionally generated; do not require embeddings if keyword and graph queries are sufficient.
- acceptance criteria: [ ] a normal session with a file edit ends with `head_matches_build` true, or `AGENTS.md` names the working rebuild command; [ ] graph context exposes whether the current head matches; [ ] docs do not imply embeddings exist when they do not.
- evidence required to close: graph stats before and after a normal editing session, plus any task or instruction diff.
- blocked by: none; the plugin load repair is recorded below. needs human: no.
- effort: S

### TOOL-04 - caveman and rtk can silently alter the evidence the merge gate rests on

- severity: P3
- confidence: likely
- area: dx
- evidence: caveman is enabled both as an MCP server (`opencode.json` `"mcp": {"caveman": ... enabled: true}`) and a plugin (`~/.config/opencode/plugins/caveman-native.js`); its own tool description states the compression is "Lossy (S4)". rtk is on PATH (`/opt/homebrew/bin/rtk`) and `~/.config/opencode/plugins/rtk.ts` rewrites shell commands to `rtk` when present. This repo's merge evidence is exact command output (`mise run test-strict`, PR bodies record the run), and `test-strict` prints counts and failure lists.
- why it matters: a lossy-compressed test log or a rewritten command can change what an agent reports as the gate result, which is the one thing the workflow says must be exact (`docs/agents/implementation-workflow.md:33-36`).
- proposed change: keep both for exploration but exclude the gate commands from rewriting, or disable them in a repo-level config for waves. At minimum, require the raw `mise run test-strict` output (uncompressed) in the PR body.
- acceptance criteria: [ ] a documented rule that gate evidence is pasted raw; [ ] the exact command `mise run test-strict` is what ran in the recorded PR.
- evidence required to close: one PR body with unmodified output and the command line.
- depends on / blocks: none.
- effort: S
- needs human: yes (acceptable to relax global token-saving)

### TOOL-05 - Global AGENTS.md carries repo-misfiring rules and no repo precedence note

- severity: P3
- confidence: confirmed
- area: dx
- evidence: `~/.config/opencode/AGENTS.md` (in the session system prompt) contains: a SonarQube MCP section instructing calls to `analyze_file_list`, `toggle_automatic_analysis` and `search_my_sonarqube_projects`, while `opencode.json`'s `mcp` map has no SonarQube entry; a TypeScript stack preference list (Convex, Tailwind, React, Vite, pnpm, Zustand, TanStack, Clerk) for a repo whose only UI is PySide6/QML; "Never commit changes unless the user explicitly asks" against the repo's `/implement` loop, which commits and opens a PR as its normal shape (`docs/agents/implementation-workflow.md:19-40`); and "Do not spawn subagents" against the repo's `/code-review`, which runs two parallel review subagents. `~/.config/opencode/cli.json` also sets `"session": {"permissions": "autoaccept"}`.
- why it matters: the repo AGENTS.md is the correct entry point, but an agent that has not read it can act on the global defaults; the dead SonarQube section in particular is pure noise that may trigger nonexistent-tool calls.
- proposed change: on the global file, delete the SonarQube section or mark it "only when the sonarqube MCP is configured"; scope the TS stack paragraph to TS projects; add one line that repo workflows (commit/PR loop, subagents for review) override the defaults, which the file's own preamble already intends. For this repo, put the precedence in `AGENTS.md` explicitly, and consider ask-mode permissions for a repo with `dist/` artifacts. Keep context7 and the OCR plugin: both map to the repo's own rules (library docs; OpenCodeReview is step 3 of the workflow).
- acceptance criteria: [ ] no instruction references an unconfigured MCP server; [ ] repo AGENTS.md states that the implementation workflow's commit/PR loop is the sanctioned exception to "never commit without being asked"; [ ] the TS paragraph is scoped or removed.
- evidence required to close: diff of the two AGENTS.md files.
- depends on / blocks: none.
- effort: S
- needs human: yes (global policy)

### Resolved tooling records

#### TOOL-01 - Superpowers loads once after the config fix

Resolved 2026-09-21. The configuration now has one `plugin` key, one load per
plugin ID, and exposes the Superpowers skills in a new session. `opencode debug
config` and `opencode plugin list` supplied the verification. Keep this as
historical evidence, not an open issue, and do not reintroduce a plural
`plugins` key.

#### TOOL-06 - Four local plugins load under opencode v2.0.12

- status: resolved 2026-09-21; verification below
- evidence: at session start 2026-09-21T17:24:49Z the startup log showed ERROR `failed to load plugin` for `plugins/crg-plugin.ts`, `plugins/caveman-native.js`, `plugins/ponytail.ts` and `plugin/unpeel-notify.js`, each `must default export an object with server()`. All four exported only `{ id, async setup(ctx) }`, the host API shape. Fix: each gained a native `server` implementation while keeping `setup` for the OpenChamber host, the same dual pattern `rtk.ts` and `open-code-review.ts` already used. Verification: `bun -e "import(...)"` reports `server=function` for all four; a private-server run (`opencode run --standalone --print-logs --log-level error`) logs `loading plugin` for all six file plugins and zero `failed to load plugin` lines (run `d58abf35`, 2026-09-21T17:34Z). Backups sit in `~/.config/opencode/plugin-backups/pre-v2-migration-20260921/`. The migrated handlers read event payloads as `data ?? properties`, because this runtime emits `data` while the published SDK types name `properties`.
- why it matters: the graph auto-updater, ponytail injection, caveman session context and unpeel notifications were silently dead while every listing showed them installed.
- acceptance criteria: [x] zero "failed to load plugin" lines at startup; [x] all six file plugins load. Normal-session graph freshness is not part of this load repair; TOOL-03 owns that separate check.
- evidence: startup log excerpt and plugin import checks captured during the audit.

## Claims checked

- **README macOS floors (12 vs 15)**: true. `.github/workflows/build-legs.json` sets `macos_floor` `15.0` for the four regular macOS legs and `12.0` for `macos-intel_legacy` / `macos-apple-silicon_legacy`, matching `README.md:138`.
- **README "eight legs"**: true. `build-legs.json` has exactly 8 entries (`macos-intel`, `macos-apple-silicon`, both `_legacy`, `linux-x64`, `linux-arm64`, `windows-x64`, `windows-arm64`), matching `docs/platform-enablement-review.md:14-15`.
- **README Python 3.12/3.13/3.14**: true. `pyproject.toml:20 requires-python = ">=3.12,<3.15"`; `.github/workflows/master.yml:37` matrix `["3.12","3.13","3.14"]`.
- **README signed SHA256SUMS**: true. `.github/workflows/release-or-test-build.yml:475-492` builds `SHA256SUMS` and signs it with `tools/sign_manifest.py`.
- **README Homebrew tap**: true. `.github/workflows/release-or-test-build.yml:576 TAP_REPO: iamprivacy/homebrew-waves` and the cask-bump job; `brew tap iamprivacy/waves` resolves to that tap.
- **README "Homebrew and the in-app updater pick the right one"**: true. `waves/desktop/updater.py:100-110,390-428` selects the legacy flavor below macOS 15.
- **README Windows park**: true as of HEAD (no Windows asset; all Windows runs in `docs/evidence/platform-builds.md` failed), but contradicted twice by the README itself (DOC-01).
- **"docs/evidence is guarded"**: false after deletion. `tests/packaging/test_acceptance_evidence.py:54` reads the deleted `docs/evidence/README.md`.
- **"docs/adr is guarded"**: false after deletion. `tests/packaging/test_repository_docs.py:46-47` requires files, `:58-62` requires the three slugs.
- **CHANGELOG format rules are enforced**: true. `tests/packaging/test_changelog_format.py` exists and asserts the documented format.
- **Star-history sync works**: false in this clone. `git remote -v` has no `public`; `tools/sync_star_history.sh` exits with "remote 'public' is not configured".
- **Windows park reasoning still holds**: confirmed. `tools/build_waves.sh:66` still excludes `yt_dlp.extractor.lazy_extractors`, and no post-exclusion Windows run appears in `docs/evidence/platform-builds.md`; the review's own revalidation date is today (`docs/platform-enablement-review.md:170`).
- **Spec APK step**: false against code. `docs/apple-music-provider-spec.md:249,259` vs `waves/providers/apple/runtime.py:7-8` (DOC-06).
- **Review-thread dispositions are load-bearing, not a changelog**: true. `tests/packaging/test_repository_docs.py:180` pins all 98 thread ids exactly once each with a verdict and a current-path citation.
- **CONTEXT.md vocabulary**: four terms used by code/UI are absent (DOC-05).

## Top 3

1. Decide the intentional ADR/evidence deletion policy and update its guards,
   references and retained rationale as one deliverable.
2. DOC-01: the README both claims and disclaims Windows support, and the park
   note points at an intentionally deleted ADR.
3. TOOL-03: graph freshness after a normal edit is unproven, and semantic
   search currently falls back to keywords because embeddings were not
   generated.

## Release blockers

None in this area. The intentional documentation deletions make the current
worktree gate red and require a policy decision before unrelated work can use
that worktree as its test baseline. BUILD-01 owns the separate Windows release
selection contradiction.

## Open questions

1. Keep the intentional ADR/evidence deletion, or restore the files?
   Recommended default: decide which rationale and legal/release evidence is
   durable, relocate only that content, then update guards and references in
   the same deliverable.
2. Should the three engine evaluations (`gamdl-eval`, `zhaarey-eval`,
   `worldobs-eval`) stay on `develop` when the spec links to their
   `research/*` branches? Recommended default: keep `alac-verification.md` on
   `develop` (a test cites it), add a one-line "superseded by the spec"
   header to the other three, delete `provider-seam-analysis.md` as stale
   (it cites pre-rename paths).
3. Which platforms must the next GitHub Release support? Recommended default:
   re-run both Windows legs on the exclusion recipe first; if they still fail,
   make release selection and user-facing support claims agree on macOS+Linux.
4. Should `README.md` keep any "new in this release" section? Recommended
   default: no; link the Releases page and keep the feature documentation in
   "What Waves can do" only.
5. Global tooling policy for this repo: keep cua-driver available only for
   native built-bundle smoke; keep caveman and rtk for exploration but preserve
   raw gate output; keep context7, OCR and code-review-graph after freshness
   verification.
6. Fixture regeneration: `docs/apple-music-provider-spec.md:164` names
   known-bad albums as QA fixtures, but no committed fixture or regeneration
   task exists (grep for those titles in `tests/` finds only the ALAC research
   citation). Recommended default: decide whether those fixtures are synthetic
   (then say so in the spec) or real files (then add a `mise run fixtures`
   task with provenance and licensing notes). Not verified further: testing
   fixtures were outside this audit's reads.

---

## Appendix: finding index

| ID       | Severity | Title                                                                                               |
| -------- | -------- | --------------------------------------------------------------------------------------------------- |
| BUILD-02 | P0       | The release cannot be signed on this fork: WAVES_SIGNING_KEY absent                                 |
| DEP-01   | P0       | Pinned wrapper 0.2.3 ships without required notices                                                 |
| ARCH-01  | P1       | backend.py concentrates unrelated behavior and shared state                                         |
| BUILD-01 | P1       | Windows legs sit in the release matrix and block signing                                            |
| BUILD-03 | P1       | Legacy macOS legs have never been built; their first run is the release                             |
| BUILD-04 | P1       | Fork builds self-update against upstream, not the fork                                              |
| BUILD-05 | P1       | The current test workflow has never run in CI                                                       |
| DL-01    | P1       | DASH under-generated URL list lands truncated audio as success                                      |
| DL-02    | P1       | Apple file skip ignores item id, silently skipping other tracks                                     |
| DOC-01   | P1       | README claims Windows support while saying the builds are parked                                    |
| DOC-04   | P1       | README "What's new" is a second changelog and duplicates the feature list                           |
| LIB-01   | P1       | OwnershipStore.close leaves other threads' read handles open                                        |
| QML-01   | P1       | Main.qml concentrates unrelated UI behavior in one scope                                            |
| QML-02   | P1       | 42 components depend on an untyped 175-member host object                                           |
| SHELL-01 | P1       | factory reset can be silently undone by a late writer                                               |
| SHELL-02 | P1       | the baked update key is never exercised against the CI secret                                       |
| TEST-02  | P1       | Wrapper-tier codec rejection has no negative test                                                   |
| TEST-09  | P1       | The suite hard-enforces the Windows park, and re-entry has no test path                             |
| TEST-10  | P1       | No CI leg runs the suite on macOS or Windows                                                        |
| UX-01    | P1       | Settings save, update actions and gate choices are pointer-only                                     |
| UX-02    | P1       | Queue row actions, SHOW ALL, filter chips and log filters have no keyboard path                     |
| UX-03    | P1       | Chooser provider tiles look selectable but are inert; CONTEXT.md says the user picks provider there |
| UX-04    | P1       | Type filter chips vanish for Apple-only (TIDAL signed-out) searches                                 |
| ARCH-02  | P2       | the patch/import surface is load-bearing and unguarded                                              |
| ARCH-03  | P2       | the job runtime is the one interface that must be designed                                          |
| BUILD-06 | P2       | "Code scanning AI findings" is red on every PR from a bot error                                     |
| BUILD-07 | P2       | Trim safety rests on a 15-second idle launch                                                        |
| BUILD-08 | P2       | Flatpak bundles are attached outside the signed manifest                                            |
| BUILD-09 | P2       | Third-party actions are not SHA-pinned in write-capable workflows                                   |
| CFG-01   | P2       | Corrupt-config recovery can abort startup                                                           |
| DEP-02   | P2       | pywidevine (GPL-3.0-only, Widevine CDM) rides gamdl into the bundle                                 |
| DEP-03   | P2       | Python 3.14 is claimed but the pinned toolchain stops at 3.13                                       |
| DEP-04   | P2       | Legacy macOS builds install Qt 6.9.3 outside the lock                                               |
| DEP-05   | P2       | yt-dlp's "never bump alone" invariant is unenforced                                                 |
| DEP-07   | P2       | Managed FFmpeg is resolved to "latest" at install time                                              |
| DEP-09   | P2       | No third-party license notices ship with the app bundle                                             |
| DL-03    | P2       | Apple placement overwrites an occupant without identity check                                       |
| DL-04    | P2       | Apple tag failure is invisible and permanently unretried                                            |
| DOC-05   | P2       | CONTEXT.md is missing four terms the code and UI use consistently                                   |
| DOC-06   | P2       | Apple spec still specifies the APK-supply step that was removed                                     |
| DOC-07   | P2       | Windows park review duplicates evidence and its revalidation trigger is today                       |
| DOC-08   | P2       | CONTRIBUTING sends external contributors to the upstream tracker                                    |
| DX-01    | P2       | mise run check writes to the tree; there is no format-only task                                     |
| DX-02    | P2       | No doctor task for the documented stale-install failure                                             |
| DX-03    | P2       | Evidence capture has no task, and docs/evidence asks for reproducibility                            |
| DX-04    | P2       | mise run star-history cannot run in this clone                                                      |
| HYG-01   | P2       | `mise clean` is missing                                                                             |
| LIB-02   | P2       | A library root of "/" is silently turned into no library                                            |
| META-01  | P2       | Apple files are tagged with a zero disc total                                                       |
| PRV-01   | P2       | Row-dict schema is documented convention, not runtime contract                                      |
| PRV-02   | P2       | Engine half of the seam is tidalapi-shaped; Apple bypasses it                                       |
| QML-03   | P2       | Palette literals are copied into 44 files with a "keep in step" comment                             |
| QML-06   | P2       | Minimum window 880x560 exceeds the logical screen on small high-DPI Windows displays                |
| QML-08   | P2       | Test coverage is name-based for 76 files and load-based for almost none                             |
| RED-01   | P2       | Cookie/Set-Cookie headers are only half redacted                                                    |
| SHELL-03 | P2       | ffmpeg macOS signature check is advisory; docs claim verification                                   |
| SHELL-04 | P2       | logTail can block the GUI thread for up to 2s per poll                                              |
| TEST-01  | P2       | 4 Qt-driving files escape the marker guard                                                          |
| TEST-03  | P2       | 28 bridge slots and 13 signals are named by no test                                                 |
| TEST-04  | P2       | The QML harness is wall-clock bound and cannot observe hover, paint or native chrome                |
| TEST-06  | P2       | Claims guards pass vacuously in five places                                                         |
| TOOL-02  | P2       | cua-driver should be limited to native built-bundle claims                                          |
| TOOL-03  | P2       | Graph freshness is unguarded and semantic embeddings are absent                                     |
| UX-05    | P2       | Sort direction control is unlabeled, keyboard-dead, and live when sorting is Relevance              |
| UX-06    | P2       | "Could not read your music folder" has no retry control                                             |
| BUILD-10 | P3       | Every workflow edit colds the Nuitka cache on all legs                                              |
| BUILD-11 | P3       | prune_static_qml_plugins mutates the developer venv permanently                                     |
| BUILD-12 | P3       | Dangling references to RELEASING.md and release.sh                                                  |
| BUILD-13 | P3       | Issue templates bypass the triage vocabulary                                                        |
| BUILD-14 | P3       | Local build matrix is undocumented; OrbStack covers Linux only                                      |
| CFG-02   | P3       | save()'s unchanged-skip can never fire                                                              |
| CFG-03   | P3       | Factory reset leaves the migration sidecar behind                                                   |
| DEP-06   | P3       | yt-dlp security fixes are blocked by the gamdl-only cadence                                         |
| DEP-08   | P3       | wrapper-image workflow can republish the live tag, and defaults to `main`                           |
| DEP-10   | P3       | pillow is declared dev but has no importer                                                          |
| DEP-11   | P3       | docs/dependency-updates.md omits three tracked surfaces                                             |
| DL-05    | P3       | `event_abort` is Optional by constructor, dereferenced unguarded                                    |
| DX-05    | P3       | Duplicate hooks, qmllint run twice, and no clean or account task                                    |
| HYG-02   | P3       | No `.gitattributes`; caches self-ignore instead of being listed                                     |
| LIB-03   | P3       | worker.py's "parent only reads the cache" invariant is false                                        |
| LIB-04   | P3       | playlist_duration tokens never resolve and stay literal in paths                                    |
| LIB-05   | P3       | sweep_stale unmounts a live second instance's private mount                                         |
| LIB-06   | P3       | Recovery probes cost one network stat per parent per name                                           |
| LIB-07   | P3       | folder_names_under sorts an unindexed full table                                                    |
| LIB-08   | P3       | resource_path is dead                                                                               |
| META-02  | P3       | MP3 lyrics are written as a single 0 ms SYLT frame                                                  |
| PRV-03   | P3       | Providers import engine-private helpers and the library scanner                                     |
| PRV-04   | P3       | Engine import chain pulls PySide6 when installed                                                    |
| QML-04   | P3       | RemoteText.qml is dead code with zero instantiations                                                |
| QML-05   | P3       | DotBar.qml duplicates DotMatrix.qml                                                                 |
| QML-07   | P3       | The plaintext guard's file list misses 9 of 82 files                                                |
| QML-09   | P3       | Background video's visible binding is overwritten by its error handler                              |
| QML-10   | P3       | File-backed manifest strings feed StyledText spots                                                  |
| RED-02   | P3       | config.py prints bypass the redacting handlers                                                      |
| SHELL-05 | P3       | `os._exit` skips atexit, and the QML-failure path never shuts down                                  |
| SHELL-06 | P3       | BRIDGE.md drift and a stale pool contract                                                           |
| SHELL-07 | P3       | freeze watchdog is off on every default install, stale 6s comment                                   |
| SHELL-08 | P3       | test-only quit knob is a production env backdoor                                                    |
| TEST-05  | P3       | Source-spelling pins are counted as behavior coverage                                               |
| TEST-07  | P3       | The `--require-qml` session-end net cannot fire for missing Qt                                      |
| TEST-08  | P3       | `--doctest-modules` is inert and markers are not strict                                             |
| TEST-11  | P3       | QML scenario failures do not identify named checkpoints                                             |
| TEST-12  | P3       | Duplicate test names and scaffolding around the twin late-skip guard                                |
| TOOL-04  | P3       | caveman and rtk can silently alter the evidence the merge gate rests on                             |
| TOOL-05  | P3       | Global AGENTS.md carries repo-misfiring rules and no repo precedence note                           |
| UX-07    | P3       | Bulk STOP/CLEAR discard queued and failed work with no confirm or undo                              |

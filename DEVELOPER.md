# Developer guide

A short orientation for anyone who wants to read or change the Waves code.
Ten minutes here saves an afternoon of reverse-engineering.

## Finding code

Start with [the architecture and domain map](docs/architecture.md). It links
Python owners, QML components, tests and domain rules for each feature. The
[glossary](CONTEXT.md) defines the language; [ADRs](docs/adr/) explain decisions.

`waves/desktop/backend.py` composes the single `WavesBridge` context object.
`qml/Main.qml` composes the window and routing. Domain modules own the
extracted behavior; `qml/domains/` contains their UI. Shared controls live in
`qml/components/`, low-level controls and Palette in `qml/primitives/`.
Search, browse, catalog and playback coordination still live in the bridge;
the map names those sections explicitly.

The engine/UI seam is a hard boundary: `waves/library/`, `waves/metadata/`,
`waves/providers/` and the download engine never import `waves/desktop/`.
Provider implementations translate SDK objects behind the Provider contract;
QML receives plain payloads and IDs. One process, one window, one bridge
object, plus a child process for library scanning.

User-facing state lives in its own `Waves` folder (`~/.config/Waves` on
Linux, `~/Library/Application Support/Waves` on macOS, `%APPDATA%\Waves` on
Windows; see `__config_dirname__` in `waves/__init__.py`).

## Threading model

- The **GUI thread** runs Qt's event loop, all QML, and every signal
  handler. Bridge state (`_objs`, caches) is only mutated here; `_queue`
  rows are also touched by download workers under `_queue_lock`, and QML
  hears about it through the coalesced GUI-thread flush
  (`_flush_queue_changes`).
- **`threadpool`** runs short blocking work: login, search, album tracks,
  artist pages, browse pages.
- **`dl_pool`** runs the one download job in flight (queue items are
  serial; track-level parallelism lives inside the engine's per-collection
  executor, sized by the "concurrent downloads" setting). Rows behind it
  wait as lightweight specs until `_pump_queue` builds their job, so a
  backlog of any size holds no Workers, no Download objects and no relays.

The pattern for anything slow, used by every slot in `backend.py`:

```python
@Slot(str)
def doThing(self, arg: str) -> None:  # called from QML
    def work():
        result = something_blocking(arg)  # worker thread
        self.thingLoaded.emit(result)  # Qt queues this to the GUI thread

    self.threadpool.start(Worker(work))
```

Signals emitted from a worker are delivered on the GUI thread automatically
(queued connection), so handlers can commit results there. Worker callbacks must not mutate
GUI-owned state directly; queue rows have their own lock as described above.

## Where state lives

| State                                                     | Owner                                                                    | Why                                                |
| --------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------- |
| View routing, filters, scroll positions, preview UI state | `Main.qml` root properties                                               | UI transients; die with the window                 |
| Download queue, live tidalapi objects, page caches        | `WavesBridge` (see its class docstring)                                  | Must survive view switches and feed multiple views |
| User preferences                                          | engine `Settings` (`settings.json`) plus `waves.json` for GUI-only prefs | Persisted across runs                              |
| Login token                                               | engine `Tidal` (`token.json`)                                            | Owned by the engine                                |

## Adding a feature

For an album-card action:

1. Find catalog ownership in [the domain map](docs/architecture.md). Put the
   provider operation on its Provider implementation, or a pure catalog rule
   beside its owner. A bridge slot coordinates the current session/cache and
   dispatches blocking work through `Worker`.
2. Keep `@Slot`/`Signal` declarations on the bridge context object. Document
   new payloads in [BRIDGE.md](waves/desktop/BRIDGE.md); preserve GUI-thread
   state mutation and stale-result generation checks.
3. Add the action to `qml/domains/catalog/ArtCard.qml`. Route results through
   Main's `Connections` where they change shared window state. Reuse the
   relevant domain control or a shared primitive, and set dynamic Text to
   `Text.PlainText`.
4. Add behavior tests in `tests/catalog/`, including provider-contract tests
   in `tests/providers/` if that surface changes. Use the existing subprocess
   QML harness for rendered behavior, then the final strict gate.

Extract a cohesive state owner when a feature needs one; avoid appending pure
rules to the bridge or adding a forwarding module for a single call.

## Testing and verification

```bash
mise run test                         # default suite, excludes live accounts
mise run app                          # run the app from source
mise run build                        # Nuitka build -> dist/waves.app
```

`mise run build` compiles for the current host only (Nuitka emits
host-native binaries, no cross-compilation). The full 8-leg matrix in
`.github/workflows/build-legs.json` is CI-only: macOS Intel + Apple
silicon, their `_legacy` twins (PySide6 6.9.3 overlay, macOS floor 12.0),
Linux x64 + arm64, Windows x64 + arm64. A container/OrbStack Linux host
can build the Linux leg matching its arch, not the macOS/Windows legs.

The release workflow smoke-launches all macOS bundles and the Linux/Windows
x64 bundles offscreen; Linux/Windows arm64 artifacts are built without a
launch. `master.yml` runs the strict suite (`mise run test-strict`) on Linux for Python 3.12–3.14
and fast-domain tests on macOS and Windows. These checks do not verify live
accounts or container behavior on each platform. The wrapper image is
`linux/arm64`; x86_64 hosts require emulation, whose full-tier behavior needs
separate live verification.

`tools/build_waves.sh` excludes yt-dlp's generated `lazy_extractors` module:
MSVC cannot compile its generated C on hosted Windows runners, and it adds
substantial build time elsewhere. yt-dlp falls back to the eager extractor
list; gamdl uses direct stream URLs. Windows also uses Nuitka's low-memory
mode. Inspect each built bundle with:

```bash
uv run --locked --all-extras python tools/inspect_bundle.py dist/waves.app
```

The build task runs this inspector automatically after trimming and signing.
Use the emitted bundle path on Linux or Windows. Record build/launch results
and benchmark measurements in the owning issue or PR.

`tools/prune_static_qml_plugins.py` deletes static-only QML plugin
directories inside the build venv's PySide6 tree before Nuitka walks it.
Restore with `uv sync --reinstall-package pyside6`.

### Dock entry on macOS

A from-source run (`mise run app`) shows no Waves tile in the macOS Dock when a
terminal or editor launches it. The venv's `python` ships no app bundle, so
LaunchServices attributes the process to the app that launched it rather than
giving it a branded tile of its own. Launched detached (for instance
`launchctl submit`) a tile does appear, but named after the interpreter
(`python3.13`) rather than Waves. No in-process call brands it — on macOS 27
with Qt 6.11 the activation policy is already `Regular`, `TransformProcessType`
returns `paramErr`, and `NSProcessInfo.processName` adds no tile. A branded
entry (the Waves name and icon) is a property of the packaged bundle:
`mise run build` writes `dist/waves.app`, whose Info.plist carries
`CFBundleName`/`CFBundleIconFile`.

### Test groups

The suite splits into groups with their own commands. Do not run groups
concurrently, and keep the machine idle while one runs: the QML scenarios are
timing-sensitive under load. The budgets are local targets on macOS arm64, offscreen Qt. Use the run
summary for current counts; they change as coverage grows.

| Group                                                           | Command                                    | Target            |
| --------------------------------------------------------------- | ------------------------------------------ | ----------------- |
| fast (excludes qml, ffmpeg, slow, integration, account markers) | `mise run test-fast`                       | < 1 min           |
| quick QML (excludes slow and integration scenarios)             | `mise run test-qml`                        | < 5 min           |
| default (all but live accounts)                                 | `mise run test` or `mise run test-default` | < 10 min          |
| strict (default plus required Qt)                               | `mise run test-strict`                     | < 10 min          |
| FFmpeg                                                          | `mise run test-ffmpeg`                     | < 1 min           |
| live accounts (opt-in credentials, never CI)                    | `mise run test-account`                    | service-dependent |

`--require-qml` turns a missing Qt into a failure instead of a silent skip of
the whole QML half. The `slow` marker names the heaviest QML boots (each case
at least 8 s) and always sits beside `qml`, so `qml and not slow` covers the
GUI surface without them. `integration` tests (nested runners, process
boundaries) have no quick group of their own; run them through strict.
`mise run test-fast`, `mise run test-qml`, `mise run test-default`,
`mise run test-strict` and `mise run test-ffmpeg` wrap the first five groups;
the live account group has its own wrapper (`mise run test-account`) and never runs in CI. Every test and
check task runs the command through `uv run --locked --all-extras`, so the
lockfile is the environment and drift fails the run.

`mise run check` (also `mise run lint`) carries the static gates. It runs the format hooks
(ruff format, prettier, qmlformat), so it rewrites unformatted files instead
of only failing: run `mise run format` first on a dirty tree, or re-run check
until it is clean.

- `mise run format` (also `fmt`) — format Python, QML and the remaining
  text with ruff, qmlformat and prettier. `lint` is an alias for the comprehensive
  `check` gate and can also rewrite files through the format hooks.
- `mise run lint-qml` — qmllint over `waves/desktop/qml` for direct use, also wired as a
  pre-commit hook for changed QML. `mise run check` reaches that same hook through its
  `pre-commit run -a` (once, over the whole tree), so there is no separate lint pass.
  Errors fail; the thousands of existing
  `[unqualified]` warnings are counted, not printed (they would bury errors).
- `mise run format-qml` — qmlformat over `waves/desktop/qml`, styled by the
  root `.qmlformat.ini` (the style is pinned there, not taken from Qt's
  defaults). Also a pre-commit hook for changed QML: a commit that reformats
  fails the hook, so re-stage the files and commit again. Pass file paths to
  format just those.
- `mise run typecheck` — ty (Astral's type checker, pinned while in beta) over
  the shipped package (`waves/`); tests and tools are outside the gate. The
  dynamic-seam categories (attribute access, argument types, mixin Signal
  descriptors) and the inherited engine's shape are downgraded to warnings
  only inside the files the `pyproject.toml` overrides name; every other
  module is held at the error level, so a new diagnostic in hand-written code
  fails the gate. Warnings do not fail (ty's own default-warn rules included);
  the seam warnings that remain are that accepted baseline. Re-check each
  override reason when a seam, a stub, or the inherited engine moves.

Updating a checkout across the package rename (`tidaler/` to `waves/`)? Run
`mise run doctor` first — it detects the stale state — then
`uv pip uninstall tidaler`, then `mise run install` (or
`uv sync --all-extras`). A stale editable install keeps `import tidaler`
resolving against dead code, and without the `waves` distribution installed
the app treats the run as a dev environment and opens against the separate
`Waves-dev` config folder, which looks like being signed out.

The QML plain-text guard test fails if any dynamic `Text` in Main.qml or the
components split out of it can render rich text (remote strings must
never inject markup).

The launch water (the wave video behind the launch screen) shares the GUI
thread with the interface, and the GUI thread waits for the interpreter lock
whenever any Python runs, so a job dispatched before `bootRevealed` competes
with the picture for every frame it holds the lock. Two things keep it
smooth: `tests/ui/test_boot_quiet_window.py` allowlists every job that may run
before the reveal (a new boot job fails the test until it is added with its
reason), and `tools/launch_probe.py` measures a real launch with Qt's own
render-loop log, no Python on the measured path, and prints a verdict:

```bash
uv run --locked --all-extras python tools/launch_probe.py   # 12 s, gaps over 45 ms
```

Run it twice (the first launch after a build is colder) before and after
anything that touches the boot path. The library walk itself runs in a child
process (`waves/library/worker.py`, started by `waves/desktop/library/scan_process.py`)
for the same reason: off the GUI thread was never enough, off the interpreter
is what the picture needs.

`tests/conftest.py` points `XDG_CONFIG_HOME` at a throwaway directory at
import time, before any test module loads, so the whole suite (subprocess
scenarios included) resolves its config out of a sandbox. Never resolve a path
from `path_config_base()` in a test without that sandbox: a `WavesBridge`
writes `waves.json` in `__init__`, so an unsandboxed test overwrites the real
settings of whoever runs the suite. Patching a loader to return defaults is not
enough while the writer still knows the real path.

### Source pins are wiring, not behavior coverage

A retained source pin kept as wiring — a test that asserts on source or QML
text (`inspect.getsource`, or reading a source/QML file to assert on its text)
instead of driving the behavior — is named `test_wiring_*` and carries a
comment naming the fenced behavior plus why no behavioral seam exists
(usually: driving the real call site needs the full bridge session or an
offscreen render). Absence guards, whose point is that something stays gone,
cite the reason no behavioral test exists instead. Prefer a behavioral test
wherever a seam exists; retain a wiring pin only where none does. Wiring pins
are never the only test for a user-facing feature: the behavior they fence is
proved by a behavioral test the comment cites, except absence guards with no
behavior to prove.

## Releases and the publication model

Releases are published from the upstream repository,
[`iamprivacy/Waves`](https://github.com/iamprivacy/Waves/releases). It holds the
signing key (`WAVES_SIGNING_KEY`) and the release line. This fork is a
development line. It publishes no releases and cannot sign one. The
`UPDATE_PUBLIC_KEY` in `waves/desktop/updates/signing.py` is upstream's public key, and
the private half is not in this repository.

The in-app updater resolves updates from upstream (`REPO` in
`waves/desktop/updates/updater.py`), so a fork build can be replaced in place by an
upstream release. The Apple Music engine is fork-only and is not in that
release. The release workflow (`.github/workflows/release-or-test-build.yml`)
is rehearsal-only here. Dispatch it with a blank `release_tag` to build the
unsigned artifacts; the `vX.Y.Z` tag and `release_tag` paths belong to
upstream.

## More detail

- [Architecture](docs/architecture.md): ownership, dependency direction and naming.
- [Documentation index](docs/README.md): domain rules and provider contracts.
- `waves/desktop/README.md`: desktop directory entry points.
- `waves/desktop/BRIDGE.md`: reference for every bridge signal and slot
  pattern.
- `WavesBridge`'s class docstring in `backend.py`: the state model.

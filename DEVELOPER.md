# Developer guide

A short orientation for anyone who wants to read or change the Waves code.
Ten minutes here saves an afternoon of reverse-engineering.

## Architecture at a glance

```
┌─────────────────────────────  Waves (GUI)  ─────────────────────────────┐
│                                                                         │
│  qml/Main.qml ── the main window (views, routing, state, object tree)   │
│  qml/*.qml ── every component, split out beside it: ArtCard, TrackRow,  │
│               LibSourceGroup, DownloadButton, NavTab, the drawers, the  │
│               player surfaces)                                          │
│  qml/SettingsPage.qml ── schema-driven settings editor                  │
│        │                                    ▲                           │
│        │ calls slots on `waves`             │ signals (queued,          │
│        ▼ (context property)                 │ GUI-thread delivery)      │
│  backend.py ── WavesBridge(QObject): every slot QML can call,           │
│        │       every signal QML listens to (the library half lives      │
│        │       in the bridge_library.py mixin)                          │
│        │                                                                │
│        ├── threadpool (QThreadPool): search, artist pages, metadata     │
│        └── dl_pool   (QThreadPool, 1 thread): the ONE download job in   │
│                                     flight; queued rows wait as specs   │
└────────┼────────────────────────────────────────────────────────────────┘
         ▼ imports, unchanged
   waves engine ──── Settings, Tidal (auth/session), Download
                     (streaming, FLAC extraction, tagging)
                     providers/ ── the Provider seam: TIDAL and Apple catalog
                     reads plug in here; each provider's engine stays behind it
```

One process, one window, one bridge object. QML never talks to TIDAL and
Python never builds UI.

## Package layout and the engine/UI seam

Waves began as a fork of Tidaler and now maintains its own engine: the
download engine modules at the top of the `waves` package descend from the
upstream code (with many fixes of our own), and everything UI-specific lives
in `waves/desktop/`. The engine/UI split is a hard seam: engine modules stay
close to their inherited shape and UI-owned behavior lands in
`waves/desktop/` subclasses and helpers, which keeps the engine easy to audit.

```
waves/
  config.py  constants.py  ids.py      # settings/session, shared primitives
  paths.py  errors.py  redaction.py    # naming rules, error types, log scrubbing
  download.py  progress.py  poolgauge.py  playlists.py  # the inherited engine
  library/                             # scan, index, worker, ownership, share mounts
  metadata/                            # tags, matching, MusicBrainz, lyrics, camelot
  providers/                           # the Provider seam: base, tidal*, apple/
  model/                               # persisted data models
  desktop/                             # the Qt/QML layer, see desktop/README.md
    icons/  fonts/  qml/
```

User-facing state lives in its own `Waves` folder, independent of the package
name (`~/.config/Waves` on Linux, `~/Library/Application Support/Waves` on
macOS, `%APPDATA%\Waves` on Windows; see `__config_dirname__` in
`waves/__init__.py`).

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
(queued connection), which is why the bridge never needs locks around
QML-facing state.

## Where state lives

| State                                                     | Owner                                                                    | Why                                                |
| --------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------- |
| View routing, filters, scroll positions, preview UI state | `Main.qml` root properties                                               | UI transients; die with the window                 |
| Download queue, live tidalapi objects, page caches        | `WavesBridge` (see its class docstring)                                  | Must survive view switches and feed multiple views |
| User preferences                                          | engine `Settings` (`settings.json`) plus `waves.json` for GUI-only prefs | Persisted across runs                              |
| Login token                                               | engine `Tidal` (`token.json`)                                            | Owned by the engine                                |

## Worked example: adding a feature end to end

Say you want a "share link" action on album cards:

1. **Bridge slot** (`backend.py`): add `@Slot(str)` `def shareAlbum(self,
album_id)`, look the album up in `self._objs["album"]`, do the work on
   `self.threadpool` via `Worker`, emit a new signal with the result.
2. **Signal**: declare it near the other signals with a comment saying what
   it carries and when it fires (see `BRIDGE.md` in `waves/desktop/`).
3. **QML**: add a `function onShareAlbum(...)` handler inside Main.qml's
   `Connections { target: waves }` block, and call `waves.shareAlbum(id)`
   from the card's control line.
4. **Conventions**: reuse the shared components (ArtistLinks, DotMatrix,
   button spec constants on the root item) so the new surface matches the
   rest of the app, and keep any dynamic `Text` as `Text.PlainText` (a test
   enforces this).

## Testing and verification

```bash
mise run test                         # unit tests, incl. the QML guards
mise run app                          # run the app from source
mise run build                        # Nuitka build -> dist/waves.app
```

### Test groups

The suite splits into groups with their own commands. Do not run groups
concurrently, and keep the machine idle while one runs: the QML scenarios are
timing-sensitive under load. Counts and runtimes below are as of 2026-09-17
(macOS arm64, offscreen Qt); the budget is the limit the group must stay
within on this host.

| Group                                                  | Command                 |  Cases |                   Budget (measured) |
| ------------------------------------------------------ | ----------------------- | -----: | ----------------------------------: |
| fast (no Qt, ffmpeg, slow, integration or account)     | `mise run test-fast`    | ~4,194 |                      < 1 min (37 s) |
| quick QML (the heaviest boots skipped)                 | `mise run test-qml`     |    ~91 |                < 5 min (4 min 12 s) |
| default (all but the live account tests)               | `mise run test-default` | ~4,354 |               < 10 min (6 min 48 s) |
| strict (the merge gate; default plus `--require-qml`)  | `mise run test-strict`  | ~4,354 | < 10 min (6 min 51 s to 9 min 21 s) |
| ffmpeg (assumes ffmpeg on PATH; `-rs` shows the skips) | `mise run test-ffmpeg`  |    ~56 |                      < 1 min (11 s) |
| live account (never in CI; needs credentials)          | `mise run test-account` |      4 |                                 n/a |

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

`mise run check` also carries the static gates. It runs the format hooks
(ruff format, prettier, qmlformat), so it rewrites unformatted files instead
of only failing: run `mise run fmt` first on a dirty tree, or re-run check
until it is clean.

- `mise run fmt` — the three formatters check runs (ruff format, qmlformat,
  prettier) with nothing else attached.
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
  descriptors) and the inherited engine's shape are warnings, with the reasons
  in `pyproject.toml`; error-level diagnostics elsewhere fail the gate,
  warnings do not (ty's own default-warn rules included). The remaining
  warnings are accepted as the permanent shape; re-check each reason when a
  seam, a stub, or the inherited engine moves.

Updating a checkout across the package rename (`tidaler/` to `waves/`)? Run
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
smooth: `tests/test_boot_quiet_window.py` allowlists every job that may run
before the reveal (a new boot job fails the test until it is added with its
reason), and `tools/launch_probe.py` measures a real launch with Qt's own
render-loop log, no Python on the measured path, and prints a verdict:

```bash
uv run --locked --all-extras python tools/launch_probe.py   # 12 s, gaps over 45 ms
```

Run it twice (the first launch after a build is colder) before and after
anything that touches the boot path. The library walk itself runs in a child
process (`waves/library/worker.py`, started by `waves/desktop/library_proc.py`)
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
`UPDATE_PUBLIC_KEY` in `waves/desktop/signing.py` is upstream's public key, and
the private half is not in this repository.

The in-app updater resolves updates from upstream (`REPO` in
`waves/desktop/updater.py`), so a fork build can be replaced in place by an
upstream release. The Apple Music engine is fork-only and is not in that
release. The release workflow (`.github/workflows/release-or-test-build.yml`)
is rehearsal-only here. Dispatch it with a blank `release_tag` to build the
unsigned artifacts; the `vX.Y.Z` tag and `release_tag` paths belong to
upstream.

## More detail

- `waves/desktop/README.md`: layout, key concepts, architecture notes.
- `waves/desktop/BRIDGE.md`: reference for every bridge signal and slot
  pattern.
- `WavesBridge`'s class docstring in `backend.py`: the state model.

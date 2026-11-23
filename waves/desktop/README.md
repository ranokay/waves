# Desktop package

Run from the repository root with `mise run app`. Setup and validation are in
[DEVELOPER.md](../../DEVELOPER.md); find each feature's Python, QML and tests
in [the architecture map](../../docs/architecture.md).

| Path                                               | Responsibility                                                            |
| -------------------------------------------------- | ------------------------------------------------------------------------- |
| `app.py`, `__main__.py`                            | Process/window startup, resources, shutdown                               |
| `backend.py`                                       | `WavesBridge` context object, lifecycle and remaining domain coordination |
| `session.py`                                       | Tracked provider sessions                                                 |
| `library/`                                         | Library bridge family and scanner child-process controller                |
| `queue/`                                           | Queue transitions/publication, per-job runtime and Qt progress carriers   |
| `settings/`                                        | Field vocabulary, schema construction, atomic/coalesced persistence       |
| `providers/`                                       | Provider card/status presentation used by settings and live surfaces      |
| `diagnostics/`                                     | Breadcrumbs, crash/export and optional timing logs                        |
| `updates/`                                         | Signed self-update verification, staging and rollback                     |
| `ffmpeg/`                                          | Managed FFmpeg provisioning                                               |
| `runtime_paths.py`, `proc.py`, `worker.py`         | Shared launch/process/thread mechanisms                                   |
| `bridge_surfaces.py`                               | Remaining cross-surface payload helpers; no backend import                |
| `qml/Main.qml`                                     | Window, routing, signal handlers and shared UI state                      |
| `qml/domains/`                                     | Feature components, including SettingsPage and drawers                    |
| `qml/components/`, `qml/primitives/`, `qml/shell/` | Shared composites, low-level controls/design tokens, navigation/branding  |
| `icons/`, `fonts/`, `qml/assets/`                  | Bundled runtime assets and licenses                                       |
| [BRIDGE.md](BRIDGE.md)                             | Qt boundary and signal/slot contracts                                     |

The library/download/metadata/provider engines live below this package and
never import it. Keep blocking work off the GUI thread; keep relays, timers
and QML-facing state on it. See the bridge class docstring for remaining state
ownership, and the developer guide for dispatch and validation conventions.

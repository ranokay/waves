# Architecture and domain ownership

Use this map to find a feature's implementation, UI, tests and rules. Start
with [domain guidance](agents/domain.md) for vocabulary and decisions, and
[CODING_STANDARDS.md](../CODING_STANDARDS.md) for coding conventions. Read
[DEVELOPER.md](../DEVELOPER.md) for setup and commands. The
[documentation index](README.md) points to specifications and ADRs.

## Runtime boundaries

```mermaid
flowchart TD
    UI[QML window and domain components] --> Bridge[WavesBridge composition and Qt boundary]
    Bridge --> Desktop[Desktop domain coordination]
    Bridge --> Engine[Download engine]
    Desktop --> Providers[Provider contracts and implementations]
    Engine --> Providers
    Desktop --> Library[Library and ownership]
    Engine --> Metadata[Metadata and tagging]
    Library --> Metadata
    Providers --> Infra[Identity, HTTP, paths, integrity, redaction]
    Metadata --> Infra
    Library --> Infra
```

- QML calls the `waves` context object's slots and consumes plain payloads
  through Qt signals. SDK objects remain in Python. The bridge reference is
  [BRIDGE.md](../waves/desktop/BRIDGE.md).
- `desktop/backend.py` constructs sessions, pools, timers, relays and domain
  state. `QueueMixin` and `LibraryMixin` operate on that state; they never
  import the backend. `JobRuntime` owns per-job registries by composition.
- Settings schema construction and provider presentation take explicit
  values/callbacks. They have no bridge or Qt imports. Schema reads are
  per-call snapshots; apply/save lifecycle remains bridge-owned.
- The engine, providers, library and metadata never import `desktop` or Qt.
  Provider-neutral operations use `providers/base.py`; SDK exceptions,
  catalog mapping and download adapters belong to the provider. The
  inherited TIDAL engine still has TIDAL-specific resolution; it is not a
  universal engine, and Apple uses its own adapter.
- Infrastructure modules have specific contracts: `ids.py` for identity,
  `http.py` for pooled sessions, `file_integrity.py` for streaming SHA-256,
  `redaction.py` for privacy, and `events.py` for typed redacted application events. Do not borrow another domain's private
  helpers for these operations.

This map names the current implementation, including subordinate engine contracts,
captured queued intent and the notification-center consumer of
[structured redacted events](adr/0013-redacted-event-lifecycle.md). Remaining
accepted extensions follow:
[Provider → Engine → Runtime](adr/0010-provider-engine-runtime-boundary.md),
[captured fulfillment intent and catalog offers](adr/0011-captured-fulfillment-intent.md),
and [composable surfaces/Settings](adr/0012-composable-provider-surfaces.md).
Add those
contracts within their existing provider, download, metadata and desktop owners;
do not infer new implemented folders or a global manager from the target design.
Capability release requires packaged/native, account/runtime and delivered-media
qualification, not merely building this dependency graph.

Product contracts and coherent UI slices are upstream candidates. This fork's
CI/graph/branch workflow and image publishing remain independent; an upstream
integration does not require the fork image. Maintained docs own contracts;
research, benchmarks and delivery evidence belong in issues/PRs and releases.

## Find a feature

Python owner paths below are relative to `waves/`; test paths are relative to
the repository root. The QML column is relative to `waves/desktop/qml/`. A
backend method family is listed
where coordination remains central; a directory does not imply that all its
behavior has been extracted.

| Domain                                    | Python owners / entry points                                                                                                                                                                                                                                                                                                                       | QML under `waves/desktop/qml/`                          | Tests / durable rules                                                               |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Search and pasted links                   | `desktop/backend.py`: `search`, progressive publication and link resolution; `providers/search_merge.py` folds provider groups into unified sections; provider catalog methods                                                                                                                                                                     | `domains/search/`; results/routing in `Main.qml`        | `tests/search/`, `tests/providers/`; provider spec and ADR-0008                     |
| Browse / discovery                        | backend browse/page/cache families; provider browse methods                                                                                                                                                                                                                                                                                        | `domains/browse/`; page composition in Main             | `tests/browse/`; ADR-0008                                                           |
| Artists, albums, playlists, mixes, videos | backend catalog/page/edition families; `providers/tidal.py`, `providers/apple/provider.py`; shared title/edition vocabulary in `metadata/title_identity.py`, presence rules in `metadata/matching.py`; catalog identity in `metadata/catalog_identity.py`, provider-owned `catalog_identity` adapters, and `desktop/providers/catalog_identity.py` | `domains/catalog/`; video overlay in Main               | `tests/catalog/`, `tests/metadata/`, `tests/providers/`                             |
| Preview / playback                        | backend preview resolve/probe families, one shared player in Main                                                                                                                                                                                                                                                                                  | `domains/playback/`                                     | `tests/playback/`; BRIDGE preview contract                                          |
| Download execution / Chooser              | `download.py`, `model/downloader.py`, `progress.py`, `poolgauge.py`, `playlists.py`; Apple `providers/apple/runner.py`, its downloader guard `child_guard.py` and temp folders `workdirs.py`; backend job construction and Chooser slots                                                                                                           | `domains/downloads/`, reused by catalog and queue       | `tests/downloads/`, `tests/providers/`; ADR-0001/0002, provider spec                |
| Queue                                     | `desktop/queue/bridge.py` row transitions/publication, `runtime.py` job registries, `progress.py` Qt progress carriers; backend pump/refetch/scheduling                                                                                                                                                                                            | `domains/queue/`                                        | `tests/queue/`; BRIDGE queue and threading contracts                                |
| Library / ownership / My Music            | `library/index.py`, `ownership.py`, recovery/mount helpers and `worker.py`; `desktop/library/bridge.py` presence/scans/files, `scan_process.py` child lifecycle; backend saved shelves/folders                                                                                                                                                     | `domains/library/`                                      | `tests/library/`, provider saved-shelf tests; ADR-0003/0007                         |
| Providers / authentication / session      | `providers/base.py`; `tidal.py`, `tidal_client.py`, `tidal_folders.py`, `tidal_manifest.py`, `tidal_refusals.py`; `apple/`; `desktop/session.py`; backend session lifecycle; `desktop/providers/presentation.py` payload builders                                                                                                                  | `domains/providers/`; provider settings in SettingsPage | `tests/providers/` with `tidal/` and `apple/`; provider spec and ADR-0004/0006/0008 |
| Settings / preferences                    | `model/cfg.py` persisted fields, `model/download_policy.py` rules and immutable intent, `config.py` loading/migration/session; `desktop/settings/schema.py` labels/defaults/schema/coercion registries, `persistence.py` atomic/coalesced writers; backend apply/side effects                                                                      | `domains/settings/`                                     | `tests/settings/`; ADR-0001 and provider spec                                       |
| Diagnostics                               | `events.py` typed events, `desktop/diagnostics/events.py` queued delivery/actions, `desktop/diagnostics/notifications.py` retained notification history, `desktop/diagnostics/export.py` breadcrumb/crash/export, `devlog.py` opt-in timing, `redaction.py` shared privacy                                                                         | `domains/diagnostics/`                                  | `tests/diagnostics/`                                                                |
| Updates                                   | `desktop/updates/updater.py`, `signing.py`; `desktop/runtime_paths.py` shared frozen/source launch identity                                                                                                                                                                                                                                        | settings and shell restart surfaces                     | `tests/updates/`, signing tools and packaging guards                                |
| FFmpeg provisioning                       | `desktop/ffmpeg/manager.py`; engine FFmpeg use stays beside the download behavior                                                                                                                                                                                                                                                                  | `domains/ffmpeg/`                                       | `tests/ffmpeg/`, `tests/downloads/`                                                 |
| Metadata / tagging                        | `metadata/tags.py`, `matching.py`, `naming.py`, lyrics/TTML, MusicBrainz arbiter, Camelot; path templates in `paths.py`                                                                                                                                                                                                                            | Settings and catalog consumers                          | `tests/metadata/`, relevant library/download tests                                  |
| Application shell / shared UI             | `desktop/app.py`, `__main__.py`, `worker.py`, `proc.py`; backend window/preferences integration                                                                                                                                                                                                                                                    | `Main.qml`, `shell/`, `components/`, `primitives/`      | `tests/ui/`; DEVELOPER threading/boot rules                                         |
| Distribution / tooling                    | `tools/`, `packaging/`, `mise.toml`, `.github/`                                                                                                                                                                                                                                                                                                    | resources included recursively                          | `tests/packaging/`; platform/distribution ADRs and evidence                         |

## Directory rules

```text
waves/
  library/                    scan, files, ownership, recovery, child worker
  metadata/                   tags, matching, naming, lyrics
  providers/                  contract + TIDAL modules + apple/ adapter
  model/                      engine/configuration data contracts
  desktop/
    backend.py                context object and remaining coordination
    app.py, session.py        process/window and tracked session lifecycle
    library/                  bridge family and scan process controller
    queue/                    bridge family, runtime and progress carriers
    settings/                 schema vocabulary and persistence
    providers/                presentation shared by settings/live surfaces
    diagnostics/, updates/, ffmpeg/
    qml/
      Main.qml                window/routing/composition entry point
      domains/                search, browse, catalog, playback, downloads,
                              queue, library, providers, settings,
                              diagnostics, ffmpeg
      shell/                  navigation and window branding
      components/             reusable composite UI concepts
      primitives/             low-level controls, Icon, Palette, qmldir
      assets/                 root-relative runtime assets
    icons/, fonts/            packaged assets with licenses
tests/
  <domain>/                   behavior tests and domain-specific fakes
  providers/{tidal,apple}/    provider-specific contracts
  ui/                         shell and shared QML behavior
  packaging/                  build/CI/resource contracts
  support/                    shared Qt, offline, paths and audio harnesses
  account/                    opt-in live-account checks
```

A domain-only component belongs in its domain. Shared composites use
`components/`; low-level controls use `primitives/`. Domain components may
compose other domain controls with explicit relative imports (for example a
catalog row's download button). Primitives and shared components must not
import domains. Dialogs stay with the domain whose decision they implement;
there is no generic global dialog folder. Main composes domains, shell and
shared UI, and remains responsible for shared window state.

Resolve resources relative to their owning file. `ProviderLogo` resolves
descriptor logo paths from the QML root, so moving a consumer cannot change
their meaning. The build recipes include the entire QML tree.

## Public contracts

Catalog offer evidence and comparison live in `providers/catalog_offers.py`,
provider adapters in `providers/tidal_offers.py` and `providers/apple/catalog_offers.py`,
and lazy guarded collection/cache in `desktop/providers/catalog_offers.py`.
The Chooser receives neutral payloads through the bridge's `requestCatalogOffers`
and `catalogOffersLoaded` contract; source maxima remain static requirements.
Search groups fold into the page's unified sections in `providers/search_merge.py`;
the bridge publishes one `searchResults` display payload per provider arrival,
and `dropSearchSource` refolds the displayed page when a provider leaves.

- A payload's `id` is its primary media identity; `album_id` or `artist_id`
  names a relation. `provider_id` names a provider; `qid` is the established
  integer queue-job key. Media IDs are namespaced strings; legacy bare IDs
  read as TIDAL. Identity/source-stream IDs remain distinct during merges.
- Existing mixins share bridge state and private coordination methods
  intentionally. Their remaining coupling is documented in their module
  docstrings. These methods are not general APIs for new domains.
  `bridge_surfaces.py` retains legacy payload helpers and backend monkeypatch
  targets until each call site can move coherently.

## Working and validation

For code exploration and impact analysis, follow [the graph workflow](agents/code-review-graph.md).
For commands, markers, and execution constraints, read [the developer guide](../DEVELOPER.md#testing-and-verification).
For issue delivery and review gates, follow [the implementation workflow](agents/implementation-workflow.md).

Wheel inspection and strict offscreen/process tests prove source/resource
wiring; native bundle signatures and live-service behavior need their own
evidence.

Main and the bridge still coordinate several domains. Extract only a stable
state owner or independently testable rule, preserving Qt affinity,
generation guards and lifecycle sequencing. Do not split them into arbitrary
file sections or add forwarding interfaces to make the diagram look tidier.

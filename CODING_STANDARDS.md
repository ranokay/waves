# Coding standards

Read when writing or reviewing Waves code. These conventions supplement the
global standards and take precedence where they differ.

## Naming

- Python modules, functions, and properties use `snake_case`; classes use
  `PascalCase`; constants use `UPPER_SNAKE_CASE`. Name files for their owner
  and operation, such as `settings/schema.py` or `library/scan_process.py`.
  Place code under its domain rather than generic shared, helper, or manager folders.
- Qt slots, signals, and properties retain `camelCase` because QML consumes
  that ABI. Internal Python helpers use `snake_case`.
- QML component files use `PascalCase`; IDs, functions, and properties use
  `camelCase`. Use concept names such as `QualityPicker`, `MusicList`, or
  `ActionButton`. Keep QML file names unique across directories.
- Use album, track, or video for a specific catalog kind. Use `media` for
  code accepting several kinds.

## Contracts and compatibility

- Use [domain guidance](docs/agents/domain.md) for glossary terms and relevant
  ADRs. Use [the architecture map](docs/architecture.md) for ownership,
  dependency direction, and media identity contracts.
- Import public helpers from the domain that owns the contract. Underscored
  names are implementation details. Existing bridge mixins share private
  coordination intentionally; their exception is documented in the architecture map.
- For public desktop slots, signals, or payload changes, read and update
  [BRIDGE.md](waves/desktop/BRIDGE.md).
- Preserve serialized settings and payload keys during internal cleanup.
- Moves must update source imports, QML imports and assets, test harnesses,
  resource recipes, dynamic module names, CI and tool imports, and documentation.
- The per-path house rules in [`.opencodereview/rule.json`](.opencodereview/rule.json)
  (QML, bridge Python, tests, Markdown, BRIDGE.md, the architecture map) bind
  every review, whichever tool runs it.

## Correctness

The correctness review hunts these defect classes. Each finding names a
concrete failure: the state or input, and the wrong result it produces.

- **Provider identity travels with the data.** When a change lets a path
  serve more than one provider, every key, cache, pending map, preference key,
  rollup and paging guard built from a path, title or bare ID carries the
  owning provider. TIDAL-specific type checks, defaults and fallbacks inside
  that path move behind the provider seam.
- **Stale work never publishes.** A worker re-checks every provider token it
  read from at emit time, not only at start. Revoking or signing out a
  provider clears its state from every combined surface it contributed to.
- **Derived UI state follows its inputs.** Every input that changes a plan or
  layout (resize, source filter, sort, refresh, expand or collapse, Back
  restore) re-runs it, after the state it reads is restored. Counters and
  caches keyed to delegates reset when those delegates are destroyed or replaced.
- **Failure reads as failure.** A run whose every read failed reports an
  error, not an empty success, and a partial index or result stays marked partial.

## Tests

- Name behavior tests `test_<behavior>.py`. Keep basenames unique across the
  suite because pytest's current import mode requires them.
- Put fixtures beside their domain. Only widely used harnesses belong in
  `tests/support/`.
- Before choosing markers, source-wiring guards, test groups, or validation
  commands, read [the developer guide](DEVELOPER.md#testing-and-verification).
  It owns test execution requirements and the source-pin policy.
- For issue delivery, follow [the implementation workflow](docs/agents/implementation-workflow.md)
  for review order, test scope, and frozen-SHA evidence.

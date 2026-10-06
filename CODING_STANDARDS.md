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

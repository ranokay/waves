# Testing and evidence

This document owns test design and the evidence each layer provides. The gate matrix lives in [the implementation workflow](implementation-workflow.md#gate-matrix); commands and test groups live in [the developer guide](../../DEVELOPER.md#testing-and-verification).

## Choose the lowest layer that proves the claim

Use the cheapest layer that can observe the behavior. Move up only when the lower layer cannot show the claim, and say what the higher layer adds.

| Layer             | Runs                              | Proves                                                                               | Does not prove                                |
| ----------------- | --------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------- |
| Unit and contract | `pytest` without Qt               | Data rules, gates, quality matrix, stores, tag writes, provider and bridge contracts | Rendered UI, a real process, live services    |
| Offscreen QML     | `mise run test-qml`               | Widget state, bindings, geometry, focus, queue and search state machines             | Native fonts, window chrome, DPI, OS menus    |
| Real-process boot | `mise run test-strict`            | Composed launch, settings round-trip, library scan, quit flush                       | Native chrome or live account behavior        |
| Native automation | `cua-driver`, opt-in built bundle | Real hover, native dialogs, fonts, scaling, OS menu actions                          | Provider correctness or other platforms       |
| Live account      | `mise run test-account`           | Account sessions, catalog access and deliveries on the tested account                | Other accounts, platforms or service versions |

A skipped, blocked or pending case is a gap. Do not report it as passing.

## Use real seams and external-boundary fakes

Tests enter Waves through seams the product already has:

- The provider contract in `waves/providers/base.py`.
- Bridge slots, signals and payloads, with `tests/support/bridge_stub.py` and the provider fakes.
- The QML `host` contract and the offscreen scenario harness.
- Real process and filesystem boundaries where the claim crosses them.

Fake an external boundary when a real service would make the test nondeterministic or unsafe. Use the real local implementation where practical: real temp files, real SQLite stores, real QML, real subprocesses. Do not rewrite existing engine-boundary mocks for their own sake.

## Write behavior, not structure

Assert what the layer exposes to its consumer: a bridge signal or payload, a provider contract result, visible QML state, a file on disk, a process exit. A test should fail when the user-visible behavior changes, not when a helper is renamed.

- Name tests for the behavior.
- Give each test a simple expected outcome. Keep product rules in product code; helpers may arrange, wait and measure.
- QML scenarios select the visible instance, wait on the state they assert, and name their checkpoints. Interactive controls they drive expose a stable `objectName`. Synthetic clicks re-measure the target after layout, park scroll dressing and reset onboarding flags at scenario start. They do not sleep where a settle helper exists.
- The non-account suite never touches a real account, network or user library. `tests/conftest.py` sandboxes the config; live work uses the account marker.
- A source pin is wiring, not behavior coverage. See the source-pin section below.

## Source pins are wiring, not behavior coverage

A retained source pin asserts on source or QML text through `inspect.getsource` or by reading a source or QML file. Name it `test_wiring_*`, cite the behavioral test that proves the fenced behavior, and explain why no behavioral seam exists. The usual reason is that driving the real call site needs the full bridge session or an offscreen render.

An absence guard says why there is no behavior to drive. Prefer a behavioral test wherever a seam exists, and retain a wiring pin only where none does. A wiring pin is never the only test for a user-facing feature: a behavioral test proves the fenced behavior, except for absence guards with no behavior to prove.

## Prove a bug with a failing test

The default is test-first: add a test that fails on the base revision, then fix the bug and watch it pass. Record the red and green heads in the PR.

If a safe deterministic regression cannot be written, say why in the PR and describe the manual or live evidence used instead. Do not present a source comparison or a mock as a runtime reproduction.

## Use property and mutation checks where they add signal

Use a property test when a pure rule has an invariant that is hard to enumerate. Use a manual mutation check when a guard protects data loss, security or authentication: remove the guard, watch the test fail, restore it.

Do not add a property or mutation service for the whole suite. A focused test for the named invariant is enough.

## Services and browsers

Current Waves claims do not need Testcontainers or Playwright. There is no containerized service dependency in the default suite, and the interface is Qt, not a browser. The Apple runtime is a live qualification target, not a unit fixture.

A future claim that needs a real container service or a real browser would justify a focused integration test with that dependency. Do not add one speculatively.

## Record the evidence

The PR body follows `.github/pull_request_template.md`: change class, tests added, red and green proof, gate commands with exits and counts, reviewer count, and qualification gaps. Screenshots and recordings are evidence only for native claims lower layers cannot show.

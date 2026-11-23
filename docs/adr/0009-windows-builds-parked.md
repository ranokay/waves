# 0009: Windows bundle builds are parked until the engine compiles under MSVC

- Status: superseded (2026-09-23; see Supersession)
- Decided: 2026-09-21 (issue #227; build evidence and the corrected platform claims are recorded in issue #205)
- Scope: whether this fork publishes Windows artifacts

## Supersession

Both Windows legs went green on the exclusion recipe on 2026-09-23
(`windows-x64` built and smoke-launched offscreen, `windows-arm64` built
without a launch by design), so the park was lifted: the release matrix
keeps all eight legs and the README presents the Windows assets as
downloadable. The decision and its reasoning below stand as the record of
the park while it held; the dispatch, run ids and build proof are in
PR #406, and the Windows test job and live verification stay owed as
separate work (see Consequences).

The accepted new-capability parity gate is
[ADR 0010](0010-provider-engine-runtime-boundary.md). It requires packaged native,
account/runtime and delivered-media qualification across all eight builds;
this historical build recovery does not satisfy those results.

## Decision

No Windows asset ships from this fork until a Windows leg builds and
smoke-launches on the recipe that excludes yt-dlp's generated
`lazy_extractors` module. The release workflow keeps defining the
`waves_windows-x64` / `waves_windows-arm64` asset names, but while the park
holds, no release may present Windows rows as downloadable — and the
workflow's all-platform release guard means no all-platform release can be
cut at all until re-entry (or until that guard learns a park exception,
which is follow-up work, not this decision).

## Why

- Both Windows legs genuinely failed on hosted runners, on one module:
  x64 with a `cl` stack overflow and arm64 with heap exhaustion, both on
  yt-dlp's generated `lazy_extractors`. Serial compilation (`--low-memory`,
  shipped) removed the parallelism pressure but not the module; every other
  module compiled.
- The cause is the fork's bundled Apple engine: gamdl pulls in yt-dlp's full
  extractor set, so Nuitka compiles the generated extractor table where
  upstream's tree — no providers package, no gamdl entry — built both
  Windows legs on the same workflow without the engine.
- The supporting runs proved the failure and nothing else: Linux built on
  both arches while the macOS legs in those runs finished "success" with
  their build steps skipped by the `only` filter — job conclusions, not
  builds. A stated park is honest; a Windows zip that cannot be built would
  be worse.

## Alternatives considered

- **Exclude `yt_dlp.extractor.lazy_extractors` via `--nofollow-import-to` —
  adopted in the recipe (#245).** yt-dlp falls back to its eager extractor
  list (verified in the source tree and a compiled probe); gamdl only ever
  hands yt-dlp direct stream URLs, so the extractor machinery is never
  touched. The Windows re-run is recorded in Supersession.
- **Drop the Apple engine from the Windows bundle (an ADR 0004 amendment)**:
  rejected for now — it splits the product into two apps by platform.
- **A larger runner**: the x64 failure is `cl`'s own stack, so memory alone
  may not remove it; not pursued without evidence.
- **Cross-building under QEMU**: unproven for Nuitka plus MSVC; not pursued.

## Consequences

- The README marks the Windows rows parked and the platform badge covers
  only shippable platforms until re-entry (met on 2026-09-23; see
  Supersession).
- Re-entry needs all three, in order: (1) a tracked run with both Windows
  legs green on the exclusion recipe (x64 build plus smoke-launch, arm64
  build, arm64 launch still by design); (2) the README table and badge
  updated to present the Windows assets as downloadable; (3) this record
  amended to superseded, pointing at the revalidation run (PR #406).
- A green bundle is not a tested platform: the Windows fast-domain test job
  and the live account/container verification stay owed separately
  (#244 for CI, #250 for the human run).
- Windows arm64 runners migrate to Visual Studio 2026 on 2026-09-21, which
  may change the compiler's behavior; revalidate after the migration.

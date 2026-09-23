# 0009: Windows bundle builds are parked until the engine compiles under MSVC

- Status: superseded (2026-09-23) — both Windows legs went green on the exclusion recipe; see Supersession
- Decided: 2026-09-21 (issue #227, audit remediation R-03; evidence in `docs/platform-enablement-review.md`; the #205 closing overclaim is corrected by that issue's follow-up comment, not by editing history)
- Scope: whether this fork publishes Windows artifacts

## Supersession

Run [35836125855](https://github.com/ranokay/waves/actions/runs/35836125855)
(2026-09-23, head `cbf4827315f5e6b8ac2bc5dffa5b75270b33d38e`) dispatched
`only=windows-x64,windows-arm64` on the exclusion recipe and both legs went
green: `windows-2022` built and smoke-launched offscreen (healthy, ~1h36m),
`windows-11-arm` built (no launch by design, ~1h44m), both artifacts
uploaded. The park is lifted: the release matrix keeps all eight legs, the
README presents the Windows assets as downloadable, and the platform-claim
tests pin this state. The decision and its reasoning below stand as the
record of the park while it held; the Windows test job and the live
verification stay owed as separate work (see Consequences).

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

- Both Windows legs genuinely fail on hosted runners, on one module:
  x64 dies with `cl` stack overflow (`0xC00000FD`) and arm64 with `C1002`
  heap exhaustion, both on yt-dlp's generated `lazy_extractors` (186k lines
  of generated C). Serial compilation (`--low-memory`, shipped) removed the
  parallelism pressure but not the module; every other module — all 1,751
  individual extractors and the second-largest generated file — compiles.
- The cause is the fork's bundled Apple engine: gamdl pulls in yt-dlp's full
  extractor set, so Nuitka compiles ~1,700 extra C modules. Upstream's tree
  has no providers package and no gamdl entry, and its v0.1.29 release built
  both Windows legs in ~14 minutes (run `34766640853`) — the same workflow
  without the engine.
- The retained runs prove the failure and nothing else: Linux x64 built and
  smoke-launched (run `34928310777`), Linux arm64 built (run `34929398611`,
  no launch by design), while every macOS leg in those runs finished
  "success" with its build steps skipped by the `only` filter — job
  conclusions, not builds. A stated park is honest; a Windows zip that
  cannot be built would be worse.

## Alternatives considered

- **Exclude `yt_dlp.extractor.lazy_extractors` via `--nofollow-import-to` —
  adopted in the recipe (#245).** yt-dlp falls back to its eager extractor
  list (all 1,751 classes verified, source tree and compiled probe); gamdl
  only ever hands yt-dlp direct stream URLs, so the extractor machinery is
  never touched. The Windows legs have not been re-run since, so
  revalidation is still owed.
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
  amended to superseded with the run ids.
- A green bundle is not a tested platform: the Windows fast-domain test job
  and the live account/container verification stay owed separately
  (#244 for CI, #250 for the human run).
- Windows arm64 runners migrate to Visual Studio 2026 on 2026-09-21, which
  may change the compiler's behavior; revalidate after the migration.

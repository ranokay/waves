# 0004: open-source client libraries ship; Apple-derived engine material is provisioned

- Status: accepted
- Decided: 2026-09-14, ratified 2026-09-15 (issue #200)
- Scope: spec §10.1 ("Nothing Apple-engine ships inside Waves' own package")
- Amended: 2026-10-03; whole-stack eligibility applies to additional clients

## Decision

The signed bundle carries no Apple-derived or proprietary material: no APK,
no wrapper image, no guest/session libraries and no N_m3u8DL-RE binary. Those
are provisioned at setup through the managed-runtime flow, and
`tools/inspect_bundle.py` fails a build whose bundle contains any of them.

The bundle does ship the open-source client libraries it depends on — gamdl,
yt-dlp and their cleared dependencies — as ordinary runtime dependencies. For §10.1,
"Apple-engine artifacts" means the Apple-derived or proprietary pieces and the
separately provisioned executables, not a general-purpose open-source client.

Additional clients qualify for bundling only after reviewing the complete
dependency stack, platform artifacts and notices for distribution eligibility.
An engine's headline license does not clear its dependencies, downloaded wheels
or embedded assets. External execution is not a blanket exception to this gate.
Candidate qualification belongs to
[ADR 0010](0010-provider-engine-runtime-boundary.md); no new candidate is approved
for bundling by this amendment.

## Why

- The redistribution exposure §10.1 exists to avoid is the APK-derived guest
  material and the wrapper image; the ratified image-publishing decision
  (#76/#80/#82) already moved those out of Waves into a source-built image.
- §10.4 treats gamdl as a pinned dependency whose bumps ride Waves' normal
  update channel, which presumes it ships with the app.
- Provisioning a Python dependency tree at runtime would need a wheel
  manifest, platform artifacts, a checksum/trust chain and a sys.path loader.
  The cookies tier deliberately needs no runtime at all; making it download
  one would weaken that tier, not strengthen it.
- The existing client boundary avoids Apple-derived bundle material; each new
  stack still needs its own distribution review. ADR 0005 records the fork's
  image posture, not universal eligibility for clients or dependencies.

## Alternatives considered

The strict reading provisions gamdl/yt-dlp as a downloaded, checksum-pinned
wheelhouse loaded from the managed-runtime area. It was considered and **not
adopted** (ratified 2026-09-15): it would make the cookies tier, which needs
no runtime today, depend on a provisioned Python environment with ABI-matched
compiled wheels, and it buys only a stricter reading of §10.1. The option
stays reachable: `tools/inspect_bundle.py --strict-clients` makes the client
report a failure, and the wheelhouse design would be a new implementation
item if that reading is ever adopted.

## Consequences

- `tools/build_waves.sh` (task `build`) runs `tools/inspect_bundle.py` after trimming and signing,
  so every local and CI matrix build fails on forbidden material.
- The client report is informational by default; `--strict-clients` flips it
  to a failure for the strict reading.
- `--require-developer-id` fails an ad-hoc or Apple Development signature, for
  a release pipeline that signs and notarizes.
- The classification is name-based; a content audit belongs to the
  wrapper-image distribution review (ADR 0005, issue #203).
- Building this locally needs `--disable-cache=ccache` because Nuitka's
  downloaded x86_64 ccache cannot run `xcrun` on Apple silicon with this
  Command Line Tools install.

## Conditions

- Every release's bundle inspection keeps confirming the provisioned pieces
  are absent.
- A contrary distribution finding can reopen this decision. The accepted fork
  image risk in ADR 0005 does not clear another stack's dependency licenses.

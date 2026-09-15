# 0004: open-source client libraries ship; Apple-derived engine material is provisioned

- Status: proposed — needs the spec owner's ratification (audit item 23 / S12)
- Decided: 2026-09-14 (issue #200, audit item 23 / S12)
- Scope: spec §10.1 ("Nothing Apple-engine ships inside Waves' own package")

## Decision

The signed bundle carries no Apple-derived or proprietary material: no APK,
no wrapper image, no guest/session libraries and no N_m3u8DL-RE binary. Those
are provisioned at setup through the managed-runtime flow, and
`tools/inspect_bundle.py` fails a build whose bundle contains any of them.

The bundle does ship the open-source client libraries it depends on — gamdl,
yt-dlp and their dependencies — as ordinary runtime dependencies. For §10.1,
"Apple-engine artifacts" means the Apple-derived or proprietary pieces and the
separately provisioned executables, not a general-purpose open-source client.

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
- gamdl is MIT-licensed and contains no Apple code; item 24's distribution
  review is where licensing can overrule this decision.

## Alternatives considered

The strict reading provisions gamdl/yt-dlp as a downloaded, checksum-pinned
wheelhouse loaded from the managed-runtime area. It is spec-faithful but is a
new distribution and trust pipeline of its own; if the spec owner prefers it,
`tools/inspect_bundle.py --strict-clients` makes the client report a failure
and a new implementation item carries the wheelhouse design.

## Consequences

- `make gui-waves` runs `tools/inspect_bundle.py` after trimming and signing,
  so every local and CI matrix build fails on forbidden material.
- The client report is informational by default; `--strict-clients` flips it
  to a failure for the strict reading.
- `--require-developer-id` fails an ad-hoc or Apple Development signature, for
  a release pipeline that signs and notarizes.
- The classification is name-based; a content audit belongs to item 24's
  distribution review.
- Building this locally needs `--disable-cache=ccache` because Nuitka's
  downloaded x86_64 ccache cannot run `xcrun` on Apple silicon with this
  Command Line Tools install.

## Conditions

- Every release's bundle inspection keeps confirming the provisioned pieces
  are absent.
- Item 24's license review can reopen this decision; a contrary finding wins.

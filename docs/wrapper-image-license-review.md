# Wrapper image license and distribution review

- Status: complete; the decision is recorded in `docs/adr/0005-wrapper-image-distribution.md`
- Scope: `ghcr.io/ranokay/waves-wrapper-v2:0.2.3`, its build inputs, and what
  the project publishes through it
- Method: static review of the pinned source and workflow, plus a local pull
  of the published image (digest
  `sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15`,
  328 MB, matching the runbook's documented digest) and a contents inspection
  (transcript: `docs/audits/apple-music-2026-09-11/evidence/wrapper-image-inspection-2026-09-15.md`)

This is an engineering inventory and risk record, not legal advice. Apple's
terms and applicable law govern the Apple components; a lawyer's review was
not performed and cannot be replaced by this page.

## What the image contains

| Component                                                                                   | Source                                                                                       | License                                                                          |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Debian 13 base                                                                              | Docker library image                                                                         | Debian/DFSG; the base's own 17 common license texts are present                  |
| `wrapper`, `wrapperd`                                                                       | `glomatico/wrapper-v2` @ `100e0a86…` (Unlicense)                                             | Unlicense                                                                        |
| ~90 AOSP system libraries (`linker64`, bionic, stagefright, skia, …)                        | committed in wrapper-v2's `vendor/android-system/arm64-v8a/`                                 | Apache-2.0 / BSD (AOSP)                                                          |
| **18 Apple libraries** (`libCoreFP.so`, `libandroidappmusic.so`, `libCoreFoundation.so`, …) | extracted from Apple's `com.apple.android.music` 3.6.0-beta, build 1109, at image build time | **proprietary; no license from Apple authorizing redistribution was identified** |

Upstream wrapper-v2's own vendor README describes the tree as self-contained
"except for the non-redistributable Apple libraries". The published GHCR
package is public, so the image distributes those Apple binaries to anyone
who pulls it.

## Findings

1. **Public redistribution of proprietary Apple libraries.** The central
   exposure. The maintainer accepted it explicitly (ADR 0005) rather than
   leaving it a caveat.
2. **AOSP notices were missing from the image.** Apache-2.0 and BSD require
   attribution/license retention. Fixed in the publish pipeline on
   2026-09-15: a single build now appends `COPY` lines to upstream's
   Dockerfile and ships `NOTICE`, `Apache-2.0`, `BSD-3-Clause` and
   `BSD-2-Clause` under `/licenses` (`tools/wrapper-image/`). The currently
   published `0.2.3` predates this; the next publish carries it. No retag
   happens — republishes take a new tag per the runbook.
3. **No image provenance labels.** Fixed in the same pipeline change: OCI
   title, source, revision (the exact wrapper-v2 commit), licenses and
   description labels are set through the build action. The current `0.2.3`
   predates them.
4. **The pinned digest was documented but unenforced in the app.** Fixed:
   `AppleRuntimeManager` resolves the pulled image's repo digest (preferring
   the pin when the runtime reports several) after `docker pull`; a digest
   differing from `WRAPPER_V2_IMAGE_DIGEST` refuses the image, and the receipt
   records the digest and whether it matched. Runtimes that cannot report a
   digest record none and are tolerated; a receipt that recorded a mismatch
   never counts as pulled. A packaging test keeps the constant and the
   runbook's documented digest in lockstep. This is a pull-time check: it
   catches a registry serving different bytes than the pin, not a local image
   mutated afterwards by someone with Docker access.

## Decision

Recorded in ADR 0005: keep the public image, accept the Apple-libraries risk,
and carry the notice, label and digest fixes above. ADR 0004's license review
of the bundled clients closes with no change.

## Residual risk

- The Apple libraries remain in a public artifact by decision; the source-only
  alternative is the documented path back if the posture changes.
- Image bytes are not reproducible bit-for-bit (timestamps); provenance is the
  Actions publish summary, the `revision` label, and the digest of the
  published manifest the app now checks.
- The wrapper image's tag, digest, APK pin and guest-lib pins ride one lockstep
  table in `docs/wrapper-image.md`.

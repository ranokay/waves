# Wrapper image license and distribution review

The maintained inventory and distribution constraints for the public wrapper
image pinned in [the runbook](wrapper-image.md). The accepted distribution
posture is recorded in [ADR 0005](adr/0005-wrapper-image-distribution.md).

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

## Distribution requirements

- The image contains proprietary Apple libraries. No license from Apple
  authorizing redistribution was identified; ADR 0005 records the
  maintainer's accepted risk. The image must not be described as entirely
  open source.
- The publish pipeline ships `NOTICE`, `Apache-2.0`, `BSD-3-Clause` and
  `BSD-2-Clause` under `/licenses`, using the maintained files in
  `tools/wrapper-image/`. The Debian base supplies its own common licenses.
  AOSP notices carry per-file copyright attribution; the generic BSD texts
  retain their provenance pointers and must not contain unfilled templates.
- OCI title, source, revision, licenses and description labels identify the
  wrapper source used to build each image. Every changed image uses a new tag.
- `AppleRuntimeManager` compares the pulled repo digest with
  `WRAPPER_V2_IMAGE_DIGEST` and refuses a mismatch. Runtimes that cannot report
  a digest are tolerated; a receipt with a recorded mismatch is never ready.
  This is a pull-time check, not detection of later local image mutation.
- The bundle's open-source clients remain covered by ADR 0004 and the
  generated third-party notices; the proprietary libraries stay in the
  separately provisioned image.

## Residual risk

- The Apple libraries remain in a public artifact by decision; the source-only
  alternative is the documented path back if the posture changes.
- Image bytes are not reproducible bit-for-bit (timestamps); provenance is the
  Actions publish summary, the `revision` label, and the digest of the
  published manifest the app now checks.
- The wrapper image's tag, digest, APK pin and guest-lib pins ride one lockstep
  table in `docs/wrapper-image.md`.

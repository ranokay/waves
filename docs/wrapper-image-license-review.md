# Wrapper image license and distribution review

- Status: decided 2026-09-15 (item 24, issues #203 / #80-#82 lineage)
- Scope: `ghcr.io/ranokay/waves-wrapper-v2:0.2.3`, its build inputs, and what
  the project publishes through it
- Method: static review of the pinned source and workflow, plus a local pull
  of the published image (digest `sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15`,
  328 MB, matching the runbook's documented digest) and a contents inspection

This is an engineering inventory and risk record, not legal advice. Apple's
terms and applicable law govern the Apple components; a lawyer's review was
not performed and cannot be replaced by this page.

## What the image contains

| Component                                                                                   | Source                                                                                       | License                                                         |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Debian 13 base                                                                              | Docker library image                                                                         | Debian/DFSG; the base's own 17 common license texts are present |
| `wrapper`, `wrapperd`                                                                       | `glomatico/wrapper-v2` @ `100e0a86…` (Unlicense)                                             | Unlicense                                                       |
| ~90 AOSP system libraries (`linker64`, bionic, stagefright, skia, …)                        | committed in wrapper-v2's `vendor/android-system/arm64-v8a/`                                 | Apache-2.0 / BSD (AOSP)                                         |
| **18 Apple libraries** (`libCoreFP.so`, `libandroidappmusic.so`, `libCoreFoundation.so`, …) | extracted from Apple's `com.apple.android.music` 3.6.0-beta, build 1109, at image build time | **proprietary; no license granted to Waves**                    |

Upstream wrapper-v2's own vendor README describes the tree as self-contained
"except for the non-redistributable Apple libraries". The published GHCR
package is public, so the image distributes those Apple binaries to anyone
who pulls it.

## Findings

1. **Public redistribution of proprietary Apple libraries.** The central
   exposure. No license from Apple authorizes it. The maintainer's decision
   (below) accepts the risk explicitly rather than leaving it a caveat.
2. **AOSP notices were missing from the image.** Apache-2.0 and BSD require
   attribution/license retention. Fixed: the publish workflow now copies the
   Debian base's `Apache-2.0` and `BSD` texts into `/licenses` together with a
   committed `NOTICE` (`tools/wrapper-image/NOTICE`) naming every component.
3. **No image provenance labels.** The image had no OCI labels. Fixed: the
   publish workflow now labels title, source, revision (the exact wrapper-v2
   commit), licenses and description.
4. **The pinned digest was documented but unenforced in the app.** The
   runtime receipt checked only the tag. Fixed: `AppleRuntimeManager` now
   resolves the pulled image's repo digest after `docker pull`; a digest that
   differs from `WRAPPER_V2_IMAGE_DIGEST` refuses the image, and the receipt
   records the digest and whether it matched. Runtimes that cannot report a
   digest (some podman setups) record none and are allowed; a mismatch never
   is. A packaging test keeps the constant and the runbook's documented
   digest in lockstep.

## Decision

**Keep the public image and accept the Apple-libraries risk, with the
compliance fixes above.** Reasons recorded with the decision:

- The image is what makes one-click setup possible; the alternatives below
  trade meaningful user friction for a risk the maintainer knowingly accepts
  for a personal fork.
- Everything that _can_ be made compliant now is: AOSP texts and NOTICE
  ship, provenance labels are set, and the app verifies the published digest.
- The risk and its scope are disclosed in `docs/wrapper-image.md`, in the
  image itself (`/licenses/NOTICE`), and here.

**Alternatives not taken**

- _Private image plus per-user grants_: removes anonymous redistribution but
  requires every user to authenticate to GHCR and be granted access — the
  runbook already calls this a one-click-setup killer.
- _Source-only image with user-supplied libraries mounted at runtime_: no
  redistribution at all, but re-introduces APK supply and extraction (the
  audit's S13 work) and puts the guest libs on every user's disk.
- _Local image build per user_: maximum friction; the pinned public image was
  chosen precisely to avoid it.

## Residual risk and follow-ups

- The Apple libraries remain in a public artifact by decision; if the
  project's distribution posture changes, the source-only variant is the
  documented path back.
- Image bytes are not reproducible bit-for-bit (timestamps); provenance is
  the Actions publish summary, the `revision` label, and the digest of the
  published manifest that the app now checks.
- The wrapper image's guest-lib pins and the APK pin ride the same lockstep
  table in `docs/wrapper-image.md`.

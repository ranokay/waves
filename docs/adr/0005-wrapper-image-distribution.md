# 0005: the wrapper image stays public, with notices, labels and digest checks

- Status: accepted
- Decided: 2026-09-15 (issue #203; the bundled clients are ADR 0004)
- Scope: this fork's wrapper image; independent managed/user-supplied product paths
- Amended: 2026-10-03; user-supplied assets and image-independent upstream integration are accepted target, planned

## Decision

This fork keeps publishing `ghcr.io/ranokay/waves-wrapper-v2` publicly and
knowingly accepts that the image contains Apple's proprietary libraries —
they are what makes ALAC decryption possible, and upstream's own vendor
README calls them non-redistributable. Everything that can be made compliant
is:

- the publish pipeline ships AOSP license texts and a NOTICE under `/licenses`
  (appended to the single upstream build; no retagging) and sets OCI
  source/revision/licenses labels;
- the app verifies the pulled image's digest against `WRAPPER_V2_IMAGE_DIGEST`
  at pull time and records it in the runtime receipt, refusing a mismatch.

The product supports both verified fork-managed assets and user-supplied Apple
assets/existing endpoints. Provisioning, provenance/pins and isolated private
session state remain required; installing host tools is a separate explicit
action. Proprietary assets remain outside the signed app
([ADR 0004](0004-apple-engine-bundling.md)). An upstream contribution must work
independently of this image and need not adopt this fork's distribution policy.
User-managed services receive compatibility guidance rather than automatic
modification. Asset update policy lives in the [Apple spec](../apple-music-provider-spec.md#10-packaging-and-distribution-constraints).

The inventory, findings and residual risk are in
`docs/wrapper-image-license-review.md`. This ADR is the decision record; it
does not replace legal advice.

## Why

- The public image is what makes one-click setup possible; private access or
  user-built images trade real friction for a risk the maintainer accepts.
- The redistribution exposure cannot be removed without removing the guest
  libraries from the artifact entirely (the source-only alternative), which
  re-introduces APK supply/extraction on every user's machine.
- What remains fixable — attribution, provenance and integrity — is now
  fixed and enforced by tests.

## Alternatives considered

- **Private image plus per-user grants**: removes anonymous redistribution,
  but every user needs `docker login` and a grant; the runbook already calls
  it a one-click-setup killer.
- **Source-only image with user-supplied libraries mounted at runtime**: no
  redistribution of those libraries by this fork, but requires user supply and
  extraction. It is now an accepted optional path, not a required setup burden.
- **Local image build per user**: an optional user-supplied path; the managed
  image remains available for users who choose it.

## Consequences

- The managed public artifact retains this fork's accepted residual risk. The
  user-supplied path and upstream product contracts do not inherit that posture.
- Every republish produces a new manifest digest, so the tag, `WRAPPER_V2_IMAGE`
  and `WRAPPER_V2_IMAGE_DIGEST` move together in `docs/wrapper-image.md`'s
  lockstep table. The publish summary prints the digest.
- Notices and labels ride the publish pipeline from 2026-09-15 on; the tag
  that carries them is recorded in `docs/wrapper-image.md`'s lockstep table,
  and the app-side digest check applies to whichever tag the pin names.
- Digest verification is a pull-time check: it catches a registry serving
  different bytes than the pin. A local image mutated after verification by
  someone with Docker access is outside its threat model.
- The prior bundled-client decision remains the baseline. New engine stacks
  require whole-stack review under ADR 0004; this image decision cannot clear
  their dependencies or establish runtime/media qualification.

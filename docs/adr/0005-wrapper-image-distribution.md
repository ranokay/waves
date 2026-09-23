# 0005: the wrapper image stays public, with notices, labels and digest checks

- Status: accepted
- Decided: 2026-09-15 (issue #203, audit item 24; the bundled clients are ADR 0004)
- Scope: distribution of the Waves-built wrapper image and its guest libraries

## Decision

Waves keeps publishing `ghcr.io/ranokay/waves-wrapper-v2` publicly and
knowingly accepts that the image contains Apple's proprietary libraries —
they are what makes ALAC decryption possible, and upstream's own vendor
README calls them non-redistributable. Everything that can be made compliant
is:

- the publish pipeline ships AOSP license texts and a NOTICE under `/licenses`
  (appended to the single upstream build; no retagging) and sets OCI
  source/revision/licenses labels;
- the app verifies the pulled image's digest against `WRAPPER_V2_IMAGE_DIGEST`
  at pull time and records it in the runtime receipt, refusing a mismatch.

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
  redistribution, but re-introduces APK supply and extraction (audit S13) and
  puts guest libraries on every user's disk.
- **Local image build per user**: maximum friction; rejected when the pinned
  public image was chosen.

## Consequences

- The Apple libraries stay in a public artifact by decision; changing posture
  means taking one of the alternatives above.
- Every republish produces a new manifest digest, so the tag, `WRAPPER_V2_IMAGE`
  and `WRAPPER_V2_IMAGE_DIGEST` move together in `docs/wrapper-image.md`'s
  lockstep table. The publish summary prints the digest.
- The published `0.2.3` predates the notices and labels; the `0.2.4` publish
  (2026-09-23) carries them, and the app-side digest check applies to
  whichever tag the pin names.
- Digest verification is a pull-time check: it catches a registry serving
  different bytes than the pin. A local image mutated after verification by
  someone with Docker access is outside its threat model.
- ADR 0004's license review for the bundled clients closes here with no
  change: gamdl/yt-dlp remain ordinary dependencies, and the published image
  carries only the Apple-derived risk accepted above.

# Wrapper image inspection evidence

Re-pulled the pinned image on 2026-09-21 and verified it resolves to the
record the review page describes. No image bytes are committed here; the
digest below is the checksum address.

- Pinned digest: `sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15`
- Pulled as: `ghcr.io/ranokay/waves-wrapper-v2@sha256:1aac…be15` (anonymous pull)
- Reported `RepoDigests`: `ghcr.io/ranokay/waves-wrapper-v2@sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15` — matches the pin in
  `waves/providers/apple/runtime.py` (`WRAPPER_V2_IMAGE_DIGEST`) and
  `docs/wrapper-image.md`
- Architecture / OS: arm64 / linux; size 327,650,304 bytes (≈328 MB);
  created 2026-09-10
- `/licenses` is absent from this tag, confirming the review's record that
  `0.2.3` predates the notices/labels (ADR 0005; the next publish carries them)

The full contents inventory and the accepted-risk record live in
`docs/wrapper-image-license-review.md` (decision: `docs/adr/0005-wrapper-image-distribution.md`).
Accepted by #203; the 2026-09-15 live transcript was never written to disk,
and this file is its reproducible replacement.

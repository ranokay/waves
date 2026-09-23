# Wrapper image inspection evidence

Re-pulled the pinned image on 2026-09-21 and verified it resolves to the
record the review page describes. No image bytes are committed here; the
digests below are the checksum addresses.

## 0.2.3 (the reviewed pull)

- Pinned digest: `sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15`
- Pulled as: `ghcr.io/ranokay/waves-wrapper-v2@sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15` (anonymous pull)
- Verified against repo revision `c20a2258772c84ba1ec464c3533e13e12d93a9e8`
  (`develop`): the pin it carries is the digest above
- Reported `RepoDigests`: `ghcr.io/ranokay/waves-wrapper-v2@sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15` — matches the pin in
  `waves/providers/apple/runtime.py` (`WRAPPER_V2_IMAGE_DIGEST`) and
  `docs/wrapper-image.md`
- Architecture / OS: arm64 / linux; size 327,650,304 bytes (≈328 MB);
  created 2026-09-10
- `/licenses` is absent from this tag, confirming the review's record that
  `0.2.3` predates the notices/labels (ADR 0005; `0.2.4` carries them)

## 0.2.4 (the notices/labels publish)

Pulled on 2026-09-23 from the publish run
`https://github.com/ranokay/waves/actions/runs/35852390691`, dispatched with
upstream SHA `100e0a864e883e03a3ac450a780dd9563fff5271` (the tracked pin).

- Digest: `sha256:79a36375a3555ca9e4aa6a9d1ccffbf0ac45a1604d19d307761c6d6ba29b428b`
  — matches `WRAPPER_V2_IMAGE_DIGEST` and `docs/wrapper-image.md`
- `docker run --rm --entrypoint ls ghcr.io/ranokay/waves-wrapper-v2:0.2.4 -1 /licenses`
  lists `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `NOTICE`
- Labels: `org.opencontainers.image.revision=100e0a864e883e03a3ac450a780dd9563fff5271`
  (the upstream SHA the run was dispatched with), plus `source`, `licenses`,
  `title` and `description`
- The `0.2.3` tag still resolves to `sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15`;
  it was never retagged.

The full contents inventory and the accepted-risk record live in
`docs/wrapper-image-license-review.md` (decision: `docs/adr/0005-wrapper-image-distribution.md`).
Accepted by #203; the 2026-09-15 live transcript was never written to disk,
and this file is its reproducible replacement.

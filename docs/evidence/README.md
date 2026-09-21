# Acceptance evidence index

R-05 (#229, finding HD-13): every acceptance claim that issues #126, #128,
#200, #203 and #205 cited from outside the repository now has an
in-repository artifact or a checksum plus a durable link. Each artifact
names the revision it was produced from. Nothing here carries secrets,
account data or signed URLs (pinned by
`tests/packaging/test_acceptance_evidence.py`).

| Cited by   | Claim                                                                            | Artifact or checksum + link                                                                                                                                                                                                                                                                                                       |
| ---------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #200       | Signed bundle contains no Apple-derived/proprietary material; signature verifies | [`bundle-inspection.md`](bundle-inspection.md) — fresh inspection at `c20a225` (exit 0); repeatable via `tools/inspect_bundle.py`                                                                                                                                                                                                 |
| #203       | Published wrapper image matches the reviewed inventory at the pinned digest      | [`wrapper-image-inspection.md`](wrapper-image-inspection.md) — digest `sha256:1aac…be15`, re-pulled 2026-09-21, RepoDigest matches the pin; full inventory in `docs/wrapper-image-license-review.md`                                                                                                                              |
| #205       | Linux builds verified; Windows legs genuinely fail                               | [`platform-builds.md`](platform-builds.md) — run ids, head SHAs and conclusions with durable Actions links                                                                                                                                                                                                                        |
| #126, #128 | Rationale citations to the Sept-11 audit report                                  | Checksum `f2fa3e4b479c654cd0dab88fbf7d56e803bf22236770ecfe486928cad4708030` of the maintainer's working copy (`docs/audits/apple-music-2026-09-11/REPORT.md`, untracked by policy like all audit workspaces). The _acceptance_ for both issues was the test suite, which is in-repo and green; the report is rationale, not proof |

Audit workspaces stay untracked: they hold live-session transcripts and
often account-adjacent material, so evidence that must be reproducible
lives here instead, scrubbed by construction.

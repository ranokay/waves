"""The R-05 acceptance evidence resolves and stays secret-free.

Issues #126/#128/#200/#203/#205 cited acceptance evidence from outside the
repository (HD-13). `docs/evidence/` is the durable answer: this guard pins
that the index links every artifact, that each artifact carries the
revision (or checksum) it was produced from, and that no committed file
carries secrets, account data or signed URLs. Removing an artifact, its
revision stamp, or its index row fails here instead of silently reopening
the finding.
"""

from __future__ import annotations

import re

from support.paths import REPO_ROOT

EVIDENCE = REPO_ROOT / "docs" / "evidence"
INDEX = EVIDENCE / "README.md"

ARTIFACTS = (
    "bundle-inspection.md",
    "wrapper-image-inspection.md",
    "platform-builds.md",
)

# CI runs are multi-hour logs; the durable record is the run id plus the
# head SHA, both linkable on the run pages forever.
PLATFORM_RUN_IDS = (
    "34928310777",
    "34929398611",
    "35019374456",
    "34928309207",
    "34766640853",
)

_SECRET_PATTERNS = (
    "ghp_",
    "github_pat_",
    "AKIA",
    "PRIVATE KEY",
    "X-Amz-Signature",
    "SharedAccessSignature",
    "sig=",
    "password=",
)


def test_the_index_links_every_artifact():
    text = INDEX.read_text(encoding="utf-8")
    for name in ARTIFACTS:
        assert name in text, f"the index no longer links {name}"
        assert (EVIDENCE / name).is_file(), f"linked artifact missing: {name}"


def test_each_artifact_carries_its_producing_revision():
    bundle = (EVIDENCE / "bundle-inspection.md").read_text(encoding="utf-8")
    assert re.search(r"\b[0-9a-f]{40}\b", bundle), "no producing revision in the bundle inspection"
    image = (EVIDENCE / "wrapper-image-inspection.md").read_text(encoding="utf-8")
    assert "sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15" in image
    builds = (EVIDENCE / "platform-builds.md").read_text(encoding="utf-8")
    for run_id in PLATFORM_RUN_IDS:
        assert run_id in builds, f"platform run {run_id} lost from the evidence"


def test_the_audit_report_checksum_is_recorded():
    assert re.search(r"\b[0-9a-f]{64}\b", INDEX.read_text(encoding="utf-8"))


def test_no_evidence_file_carries_secrets():
    for path in sorted(EVIDENCE.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in _SECRET_PATTERNS:
            assert pattern not in text, f"{path.name} carries {pattern!r}"

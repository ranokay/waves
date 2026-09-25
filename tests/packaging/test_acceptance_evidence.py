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
import shutil
import subprocess

import pytest
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
    "35575720429",
    "35579368870",
    "35583595525",
    "35588929771",
    "35836125855",
)

_SECRET_PATTERNS = (
    "ghp_",
    "github_pat_",
    "AKIA",
    "ASIA",
    "eyJ",
    "xoxb-",
    "PRIVATE KEY",
    "X-Amz-Signature",
    "SharedAccessSignature",
    "sig=",
    "password=",
)

_LABELED_REVISION = re.compile(r"(?i)\brevision\b[^:\n]*:[^\n]*?([0-9a-f]{40})")


def _labeled_revision(text: str) -> str:
    """The `revision: <40-hex>` stamp naming what produced the artifact.

    A bare 40-hex string anywhere in the file is not a stamp: any hex-shaped
    token (a fabricated sha, a checksum of something else) satisfies it.
    """
    match = _LABELED_REVISION.search(text)
    assert match, "no labeled producing revision (revision: <40-hex sha>) in the artifact"
    return match.group(1)


def _assert_revision_is_real(sha: str) -> None:
    """The stamped revision must be a commit in this repository's history.

    A fabricated `revision: 1111...` carries the label but names nothing that
    was ever committed, so the guard resolves it instead of trusting the text.
    """
    git = shutil.which("git")
    assert git, "git is not on PATH; the evidence guard resolves revisions through it"
    proc = subprocess.run(  # noqa: S603 (fixed argv: the resolved git, one cat-file existence check)
        [git, "cat-file", "-e", sha],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stamped revision {sha} is not a commit in this repository"


def test_the_index_links_every_artifact():
    text = INDEX.read_text(encoding="utf-8")
    for name in ARTIFACTS:
        assert name in text, f"the index no longer links {name}"
        assert (EVIDENCE / name).is_file(), f"linked artifact missing: {name}"


def test_each_artifact_carries_its_producing_revision():
    bundle = (EVIDENCE / "bundle-inspection.md").read_text(encoding="utf-8")
    _assert_revision_is_real(_labeled_revision(bundle))
    image = (EVIDENCE / "wrapper-image-inspection.md").read_text(encoding="utf-8")
    assert "sha256:1aac416aae06995095fac19a12d180d869a3bc615b83d31b0773281a9801be15" in image
    assert "sha256:79a36375a3555ca9e4aa6a9d1ccffbf0ac45a1604d19d307761c6d6ba29b428b" in image
    builds = (EVIDENCE / "platform-builds.md").read_text(encoding="utf-8")
    for run_id in PLATFORM_RUN_IDS:
        assert run_id in builds, f"platform run {run_id} lost from the evidence"
    for head_sha in (
        "b67bc72c0c2776fb15bae10cb055bf65a39a9d38",
        "d08e7a19ff2c2889707ad7150f78c64607394743",
        "709e18671a2a8decc70793514c9f57a2988fe7d4",
        "cbf4827315f5e6b8ac2bc5dffa5b75270b33d38e",
    ):
        assert head_sha in builds, f"head SHA {head_sha[:7]} lost from the evidence"


ACCEPTANCE_SUITES = (
    "tests/library/test_apple_quarantine_actions.py",
    "tests/providers/apple/test_apple_provider_disable.py",
    "tests/providers/apple/test_apple_supervision.py",
    "tests/settings/test_settings_migration_sidecar.py",
    "tests/downloads/test_apple_integrity_gate.py",
    "tests/downloads/test_apple_standalone_fallback.py",
)


def test_the_index_names_resolving_acceptance_suites():
    text = INDEX.read_text(encoding="utf-8")
    for suite in ACCEPTANCE_SUITES:
        assert suite in text, f"the index no longer cites {suite}"
        assert (REPO_ROOT / suite).is_file(), f"cited suite missing: {suite}"


def _secret_hits(paths) -> list[str]:
    """Every committed file under the evidence dir, whatever its depth or suffix.

    The old top-level `*.md` glob stayed green with a secret one directory down,
    in a `.json`/`.txt` artifact, or shaped like an unlisted pattern (a temporary
    `ASIA` key, a JWT `eyJ` header, a Slack `xoxb-` token).
    """
    hits: list[str] = []
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits.extend(f"{path.name} carries {pattern!r}" for pattern in _SECRET_PATTERNS if pattern in text)
    return hits


def _assert_no_secrets(root) -> None:
    """The guard itself, parameterized by directory so the negatives below run
    the same composition (recursive scan + full pattern set) as the real check.
    """
    files = [path for path in root.rglob("*") if path.is_file()]
    assert files, f"no evidence files found under {root}"
    hits = _secret_hits(files)
    assert not hits, "\n".join(hits)


def test_no_evidence_file_carries_secrets():
    _assert_no_secrets(EVIDENCE)


def test_a_fabricated_revision_fails_the_guard():
    """Negative: a labeled revision that names no commit must fail."""

    assert re.search(r"\b[0-9a-f]{40}\b", "revision: " + "1" * 40), "fixture must satisfy the old bare-hex check"
    with pytest.raises(AssertionError):
        _assert_revision_is_real(_labeled_revision("Revision built: `" + "1" * 40 + "`"))


def test_a_secret_in_a_subdirectory_fails_the_scan(tmp_path):
    """Negative: the scan reaches past the top level."""
    nested = tmp_path / "notes" / "session.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("token ghp_fabricatedsecretfornegative000\n", encoding="utf-8")
    assert list(tmp_path.glob("*.md")) == [], "fixture must escape the old top-level glob"
    with pytest.raises(AssertionError):
        _assert_no_secrets(tmp_path)


def test_a_secret_in_a_json_artifact_fails_the_scan(tmp_path):
    """Negative: the scan is not limited to Markdown."""
    artifact = tmp_path / "transcript.json"
    artifact.write_text('{"token": "eyJmYWJy.aWNhdGVk.fG9ybmVnYXRpdmU"}', encoding="utf-8")
    assert list(tmp_path.glob("*.md")) == [], "fixture must escape the old top-level glob"
    with pytest.raises(AssertionError):
        _assert_no_secrets(tmp_path)

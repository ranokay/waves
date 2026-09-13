"""The wrapper-image pipeline stays pinned to the app (issue #76).

The CI workflow publishes exactly the image the app pulls: its default tag
must equal WRAPPER_V2_IMAGE, it must build linux/arm64 from upstream source
with the APK arriving only via the private APK_URL secret, and it must
smoke-test before pushing. The maintainer runbook must name the current
APK and guest-lib pins, so a pin bump without a runbook update fails here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "wrapper-image.yml"
RUNBOOK = REPO / "docs" / "wrapper-image.md"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_workflow_defaults_publish_exactly_the_pinned_image():
    from waves.providers.apple.runtime import WRAPPER_V2_IMAGE

    wf = _workflow()
    inputs = wf[True]["workflow_dispatch"]["inputs"]  # YAML reads `on:` as boolean True
    tag = inputs["image_tag"]["default"]
    # The tag must equal the app pin; the registry path defaults to the
    # publishing owner's namespace (issue #86), so forks need no edits.
    assert WRAPPER_V2_IMAGE.rsplit(":", 1)[1] == tag
    assert "ghcr.io/${{ github.repository_owner }}/waves-wrapper-v2" in WORKFLOW.read_text()
    assert inputs["wrapper_ref"]["default"]


def test_workflow_builds_arm64_from_upstream_source_with_a_secret_apk():
    text = WORKFLOW.read_text()
    assert "arm64-v8a" in text and "linux/arm64" in text
    assert "glomatico/wrapper-v2" in text
    assert "secrets.APK_URL" in text
    # Private hosting authenticates through an optional masked header.
    assert "secrets.APK_AUTH_HEADER" in text
    assert "push: true" in text
    # Pins regenerate deterministically from the blessed APK (issue #82)
    # instead of trusting upstream's file to track it; the strict
    # extraction then proves the staged tree matches.
    assert "--ignore-hash" in text
    assert "LIBS_VERSION.json" in text
    # The APK arrives at build time only: never checked out, never committed.
    assert "extract-libs.sh" in text and "LIBS_VERSION" in text
    # Smoke test gates the push: /health plus the TCP decrypt port.
    assert "/health" in text and "11020" in text


def test_blessed_apk_inputs_match_the_app_pins():
    import yaml

    from waves.providers.apple.runtime import APK_PINNED_VERSION

    wf = yaml.safe_load(WORKFLOW.read_text())
    inputs = wf[True]["workflow_dispatch"]["inputs"]  # YAML reads `on:` as boolean True
    assert inputs["apk_version"]["default"] == APK_PINNED_VERSION
    assert inputs["apk_build"]["default"] == "1109"


def test_runbook_names_the_current_pins():
    from waves.providers.apple.runtime import APK_PINNED_VERSION, WRAPPER_LIBS_VERSION, WRAPPER_V2_IMAGE

    doc = RUNBOOK.read_text()
    tag = WRAPPER_V2_IMAGE.rsplit(":", 1)[1]
    assert tag in doc and APK_PINNED_VERSION in doc and WRAPPER_LIBS_VERSION in doc
    assert "APK_URL" in doc and "Public" in doc


def test_upstream_pin_file_is_a_valid_sha_and_the_watcher_uses_it():
    import re

    text = (REPO / ".github" / "wrapper-upstream.sha").read_text()
    sha = text.strip().splitlines()[-1].strip()
    assert re.fullmatch(r"[0-9a-f]{40}", sha), "pin file must end with one full commit SHA"
    watcher = (REPO / ".github" / "workflows" / "wrapper-upstream-check.yml").read_text()
    assert "wrapper-upstream.sha" in watcher
    assert "glomatico/wrapper-v2" in watcher
    assert "schedule" in watcher and "cron" in watcher
    assert "issues: write" in watcher
    # Human-gated: watches and files issues, never builds or publishes.
    assert "build-push-action" not in watcher and "docker push" not in watcher.lower()

"""The wrapper-image pipeline stays pinned to the app.

The CI workflow publishes exactly the image the app pulls: its default tag
must equal WRAPPER_V2_IMAGE, it must build linux/arm64 from upstream source
with the APK arriving only via the private APK_URL secret, and it must
smoke-test before pushing. The maintainer runbook must name the current
APK and guest-lib pins, so a pin bump without a runbook update fails here.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import yaml
from support.paths import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "wrapper-image.yml"
RUNBOOK = REPO_ROOT / "docs" / "wrapper-image.md"
# SPDX templates that must never ship as a notice.
TEMPLATE_MARKERS = ("<year>", "<owner>")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _tracked_wrapper_files() -> set[str]:
    """The paths under tools/wrapper-image that git actually carries."""
    git = shutil.which("git")
    assert git, "git is not on PATH; every release checkout needs it"
    result = subprocess.run(  # noqa: S603 (fixed argv: the resolved git, one ls-files call)
        [git, "ls-files", "-z", "tools/wrapper-image"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {path for path in result.stdout.split("\0") if path}


def test_workflow_defaults_publish_exactly_the_pinned_image():
    from waves.providers.apple.runtime import WRAPPER_V2_IMAGE

    wf = _workflow()
    inputs = wf[True]["workflow_dispatch"]["inputs"]  # YAML reads `on:` as boolean True
    tag = inputs["image_tag"]["default"]
    # The tag must equal the app pin; the registry path defaults to the
    # publishing owner's namespace, so forks need no edits.
    assert WRAPPER_V2_IMAGE.rsplit(":", 1)[1] == tag
    assert "ghcr.io/${{ github.repository_owner }}/waves-wrapper-v2" in WORKFLOW.read_text()


def test_workflow_requires_a_full_upstream_sha():
    wf = _workflow()
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    ref = inputs["wrapper_ref"]
    assert ref.get("required") is True
    assert "default" not in ref, "a default ref lets a one-click dispatch build a moving branch"
    step = next(
        (s for s in wf["jobs"]["build"]["steps"] if s.get("name") == "Require a full upstream commit SHA"),
        None,
    )
    assert step is not None, "the publish lost its ref guard"
    run = str(step["run"])
    assert "^[0-9a-f]{40}$" in run
    assert "exit 1" in run


def test_workflow_refuses_to_overwrite_a_published_tag():
    wf = _workflow()
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    override = inputs["allow_tag_overwrite"]
    assert override["type"] == "boolean"
    assert override["default"] is False
    steps = wf["jobs"]["build"]["steps"]
    guard = next((s for s in steps if s.get("name") == "Refuse to overwrite an existing tag"), None)
    assert guard is not None, "the publish lost its tag guard"
    run = str(guard["run"])
    assert "imagetools inspect" in run
    assert "exit 1" in run
    # The override arrives through the environment, never interpolated into
    # the script text.
    assert guard["env"]["ALLOW_TAG_OVERWRITE"] == "${{ inputs.allow_tag_overwrite }}"
    assert "${ALLOW_TAG_OVERWRITE}" in run
    names = [s.get("name") for s in steps]
    assert names.index("Refuse to overwrite an existing tag") < names.index("Build and push")


def test_workflow_builds_arm64_from_upstream_source_with_a_secret_apk():
    text = WORKFLOW.read_text()
    assert "arm64-v8a" in text and "linux/arm64" in text
    assert "glomatico/wrapper-v2" in text
    assert "secrets.APK_URL" in text
    # Private hosting authenticates through an optional masked header.
    assert "secrets.APK_AUTH_HEADER" in text
    # A private repo's /releases/download/ URL only serves a browser
    # session, so the step must resolve it through the asset API.
    assert "releases/assets" in text
    assert "push: true" in text
    # Pins regenerate deterministically from the blessed APK
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


def test_the_pinned_image_digest_matches_the_runbook():
    from waves.providers.apple.runtime import WRAPPER_V2_IMAGE_DIGEST

    assert WRAPPER_V2_IMAGE_DIGEST in RUNBOOK.read_text(), "the image digest pin and the runbook disagree"


def test_the_publish_checks_out_this_repo_for_the_notices_templates():
    steps = _workflow()["jobs"]["build"]["steps"]
    names = [s.get("name") for s in steps]
    own_checkouts = [
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout") and "repository" not in step.get("with", {})
    ]
    assert own_checkouts, "the notices stage reads tools/wrapper-image/, which needs this repo checked out"
    assert own_checkouts[0] < names.index("Prepare notices")


def test_the_publish_adds_notices_and_provenance_labels():
    steps = _workflow()["jobs"]["build"]["steps"]
    prepare = next((s for s in steps if s.get("name") == "Prepare notices"), None)
    assert prepare is not None, "the publish lost its notices stage"
    run = str(prepare.get("run", ""))
    notices = ("NOTICE", "Apache-2.0.txt", "BSD-3-Clause.txt", "BSD-2-Clause.txt")
    copied = set(re.findall(r"cp (\S+) wrapper-v2/notices/", run))
    assert copied, "the notices stage copies nothing"
    assert copied == {f"tools/wrapper-image/{name}" for name in notices}
    # Every source the stage copies must exist AND be tracked: a notice the
    # workflow names but git does not carry fails the publish in this step,
    # before the build, and an untracked file in one working tree
    # is exactly how that hid from the previous check.
    tracked = _tracked_wrapper_files()
    for src in copied:
        path = REPO_ROOT / src
        assert path.is_file(), f"the publish copies {src}, which is not on disk"
        assert src in tracked, f"the publish copies {src}, which git does not track"
        # The text must be a real license, not an SPDX template, which once
        # shipped `Copyright (c) <year> <owner>` because nothing read it.
        text = path.read_text()
        assert not any(marker in text for marker in TEMPLATE_MARKERS), f"{src} is still a license template"
    assert "COPY notices/NOTICE /licenses/NOTICE" in run

    build = next(s for s in steps if s.get("name") == "Build and push")
    labels = str(build.get("with", {}).get("labels", ""))
    assert "org.opencontainers.image.licenses" in labels
    assert "org.opencontainers.image.revision" in labels
    assert "org.opencontainers.image.source" in labels


def test_the_notice_names_every_bundled_component():
    notice = (REPO_ROOT / "tools" / "wrapper-image" / "NOTICE").read_text()
    assert "Unlicense" in notice and "wrapper-v2" in notice
    assert "Apache-2.0" in notice and "AOSP" in notice
    assert "com.apple.android.music" in notice and "remain" in notice


def test_upstream_pin_file_is_a_valid_sha_and_the_watcher_uses_it():
    import re

    text = (REPO_ROOT / ".github" / "wrapper-upstream.sha").read_text()
    sha = text.strip().splitlines()[-1].strip()
    assert re.fullmatch(r"[0-9a-f]{40}", sha), "pin file must end with one full commit SHA"
    watcher = (REPO_ROOT / ".github" / "workflows" / "wrapper-upstream-check.yml").read_text()
    assert "wrapper-upstream.sha" in watcher
    assert "glomatico/wrapper-v2" in watcher
    assert "schedule" in watcher and "cron" in watcher
    assert "issues: write" in watcher
    # Human-gated: watches and files issues, never builds or publishes.
    assert "build-push-action" not in watcher and "docker push" not in watcher.lower()

"""The Flatpak channel stays minimal and wired.

The sandbox permission set is a security surface, so it is pinned here: a
--filesystem=host or a socket added without thought fails this test until the
rationale (packaging/flatpak/README.md) is updated with it. The bundle itself
only builds on Linux; the manifest, the glue files and the CI wiring are the
testable half on every host. The updater's Flatpak deference is covered in
tests/ui/test_updater.py.
"""

from __future__ import annotations

import yaml
from support.paths import REPO_ROOT

FLATPAK_DIR = REPO_ROOT / "packaging" / "flatpak"
MANIFEST = FLATPAK_DIR / "org.getwaves.Waves.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "flatpak-build.yml"


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_the_sandbox_is_minimal_and_never_gets_host_filesystem():
    m = _manifest()
    assert m["app-id"] == "org.getwaves.Waves"
    assert m["command"] == "waves"
    assert set(m["finish-args"]) == {
        "--share=network",
        "--share=ipc",
        "--socket=wayland",
        "--socket=fallback-x11",
        "--socket=pulseaudio",
        "--device=dri",
        "--filesystem=home",
    }


def test_the_module_installs_the_glue_files_from_expected_sources():
    m = _manifest()
    module = m["modules"][0]
    commands = "\n".join(module["build-commands"])
    for installed in (
        "/app/bin/waves",
        "org.getwaves.Waves.desktop",
        "org.getwaves.Waves.metainfo.xml",
        "org.getwaves.Waves.png",
    ):
        assert installed in commands, installed
    paths = {source["path"] for source in module["sources"]}
    # The dist is the tree tools/build_waves.sh produces.
    assert paths == {"../../dist/waves.dist", ".", "../../waves/desktop/icons"}


def test_the_desktop_and_metainfo_agree_on_the_app_id():
    desktop = (FLATPAK_DIR / "org.getwaves.Waves.desktop").read_text(encoding="utf-8")
    assert "Exec=waves" in desktop
    assert "Icon=org.getwaves.Waves" in desktop

    # Literal checks, not an XML parser: the file is repo-controlled and
    # malformed XML fails flatpak-builder anyway; parsing it here would trip
    # the untrusted-XML lint (S314) for no benefit.
    metainfo = (FLATPAK_DIR / "org.getwaves.Waves.metainfo.xml").read_text(encoding="utf-8")
    assert "<id>org.getwaves.Waves</id>" in metainfo
    assert '<launchable type="desktop-id">org.getwaves.Waves.desktop</launchable>' in metainfo


def test_ci_builds_and_smoke_launches_the_bundle():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = wf["jobs"]["linux"]
    arches = {entry["OS_ARCH"] for entry in job["strategy"]["matrix"]["include"]}
    assert arches == {"linux-x64", "linux-arm64"}
    steps = job["steps"]
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert "flatpak-builder" in runs
    assert "flatpak build-bundle" in runs
    assert "flatpak run" in runs
    # The smoke-launch installs the built bundle itself, not just a runtime,
    # and stays x64-only (the ARM runners skip it, as in the release workflow).
    assert 'flatpak install --user -y --noninteractive "dist/waves_${{ matrix.OS_ARCH }}.flatpak"' in runs
    smoke = next(step for step in steps if step.get("name") == "Smoke-launch the installed bundle")
    assert "linux-x64" in str(smoke["if"])
    uses = [str(step.get("uses", "")) for step in steps]
    assert any(u.startswith("actions/upload-artifact") for u in uses)
    # Attach by upload only: creating the Release here would race the release
    # workflow's draft (the v0.1.2 duplicate-release incident).
    assert "gh release upload" in runs
    assert not any(u.startswith("softprops/action-gh-release") for u in uses)

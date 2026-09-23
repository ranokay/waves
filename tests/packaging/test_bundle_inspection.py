"""The bundle inspector that enforces spec §10.1.

The tool classifies a built bundle: Apple-derived engine material must never
be there, open-source clients ship (ADR 0004) and are reported, gamdl's
pywidevine and protobuf dependencies are reported present or absent
(`docs/dependency-updates.md`), and on macOS the code signature must verify.
These tests pin the classifier against a fake bundle tree and a fake
codesign/strings; the real signed bundle inspection is run per build and
recorded as evidence.
"""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest
from support.paths import REPO_ROOT


def _load():
    spec = importlib.util.spec_from_file_location("inspect_bundle", REPO_ROOT / "tools" / "inspect_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inspect_bundle_tool = _load()


def _fake(*, rc: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def _bundle(tmp_path, names: tuple[str, ...], *, with_natives: bool = True):
    root = tmp_path / "waves.app"
    (root / "Contents" / "MacOS").mkdir(parents=True)
    (root / "Contents" / "MacOS" / "waves").write_bytes(b"\x00")
    if with_natives:
        for module, _kind in inspect_bundle_tool._REQUIRED_NATIVE:
            path = root / "Contents" / "MacOS" / "Crypto" / "Cipher" / f"{module}.abi3.so"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00")
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00")
    return root


def test_apple_derived_engine_material_is_forbidden(tmp_path):
    bundle = _bundle(
        tmp_path,
        ("game.apkm", "bin/N_m3u8DL-RE_Beta_osx-arm64.tar.gz", "apple-runtime/wrapper-data/session.db"),
    )

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

    kinds = sorted({item["kind"] for item in report["forbidden"]})
    assert kinds == ["APK", "N_m3u8DL-RE binary", "managed runtime directory"]
    assert report["ok"] is False


def test_guest_library_names_are_forbidden(tmp_path):
    bundle = _bundle(tmp_path, ("libsession.so", "frida-gadget.dylib"))

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

    assert len(report["forbidden"]) == 2
    assert report["ok"] is False


def test_open_source_clients_ship_and_are_reported_not_failed(tmp_path):
    bundle = _bundle(tmp_path, ("site-packages/gamdl/__init__.py", "site-packages/yt_dlp/__init__.py"))

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

    assert report["forbidden"] == []
    assert any("gamdl" in item for item in report["clients"])
    assert any("yt-dlp" in item for item in report["clients"])
    assert report["ok"] is True


def test_strict_clients_fail_the_report(tmp_path):
    bundle = _bundle(tmp_path, ("site-packages/gamdl/__init__.py",))

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False, strict_clients=True)

    assert report["clients"]
    assert report["ok"] is False


def test_embedded_client_markers_are_found_in_the_executable(tmp_path):
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake(stdout="yt_dlp\nyt_dlp.YoutubeDL\ngamdl.api\n")
        return _fake()

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, verify_signature=False)

    assert any(item.startswith("gamdl: embedded") for item in report["clients"])
    assert any(item.startswith("yt-dlp: embedded") for item in report["clients"])
    assert report["ok"] is True


def test_expected_dependencies_are_reported_present_or_absent(tmp_path):
    """pywidevine and protobuf ride gamdl in by decision
    (docs/dependency-updates.md); the report names each present or absent and
    fails neither."""
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake(stdout="pywidevine\npywidevine.cdm\ngoogle.protobuf\n")
        return _fake()

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, verify_signature=False)

    assert any(item.startswith("pywidevine: embedded") for item in report["expected"])
    assert any(item.startswith("protobuf: embedded") for item in report["expected"])
    assert report["ok"] is True


def test_absent_expected_dependencies_are_reported_not_failed(tmp_path):
    bundle = _bundle(tmp_path, ())

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=lambda args: _fake(), verify_signature=False)

    assert report["expected"] == ["pywidevine: absent", "protobuf: absent"]
    assert report["ok"] is True


def test_expected_dependencies_shipped_as_packages_are_reported_by_path(tmp_path):
    """pywidevine ships as its own package; protobuf lives under `google/`."""
    bundle = _bundle(
        tmp_path,
        ("site-packages/pywidevine/__init__.py", "site-packages/google/protobuf/__init__.py"),
    )

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=lambda args: _fake(), verify_signature=False)

    assert "pywidevine: site-packages/pywidevine" in report["expected"]
    assert "protobuf: site-packages/google/protobuf" in report["expected"]
    assert report["ok"] is True


def test_signature_verification_and_kind(tmp_path):
    bundle = _bundle(tmp_path, ())
    calls: list[list[str]] = []

    def runner(args):
        calls.append(args)
        if "--verbose=2" in args:
            return _fake(stderr="Signature=adhoc\nTeamIdentifier=not set")
        return _fake()

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, platform="darwin")

    assert report["signature"]["checked"] is True
    assert report["signature"]["verified"] is True
    assert report["signature"]["kind"] == "ad-hoc"
    assert report["ok"] is True
    assert any(call[:2] == ["codesign", "--verify"] for call in calls), calls


def test_a_failed_signature_fails_the_inspection(tmp_path):
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake()
        if "--deep" in args:
            return _fake(rc=1, stderr="invalid signature")
        return _fake(stderr="Authority=Developer ID Application: Someone (TEAM)")

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, platform="darwin")

    assert report["signature"]["verified"] is False
    assert report["signature"]["kind"] == "Developer ID"
    assert report["ok"] is False


def test_require_developer_id_rejects_adhoc(tmp_path):
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake()
        if "--verbose=2" in args:
            return _fake(stderr="Signature=adhoc")
        return _fake()

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, platform="darwin", require_developer_id=True)

    assert report["signature"]["verified"] is True
    assert report["ok"] is False, "an ad-hoc bundle must not satisfy the release policy"


def test_require_developer_id_accepts_a_developer_id(tmp_path):
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake()
        if "--verbose=2" in args:
            return _fake(stderr="Authority=Developer ID Application: Waves (TEAM)")
        return _fake()

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, platform="darwin", require_developer_id=True)

    assert report["signature"]["kind"] == "Developer ID"
    assert report["ok"] is True


def test_a_missing_codesign_fails_closed(tmp_path):
    bundle = _bundle(tmp_path, ())

    def runner(args):
        if args[0] == "strings":
            return _fake()
        raise FileNotFoundError("codesign")

    report = inspect_bundle_tool.inspect_bundle(bundle, runner=runner, platform="darwin")

    assert report["signature"]["kind"] == "unavailable"
    assert report["signature"]["verified"] is False
    assert report["ok"] is False


def test_a_missing_pycryptodome_native_module_fails_the_inspection(tmp_path):
    """The runtime loads these by name through ctypes, so a build or a trim can
    drop them silently and the Apple download path then dies at the first
    native load."""
    bundle = _bundle(tmp_path, (), with_natives=False)

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

    assert report["missing"] == [kind for _name, kind in inspect_bundle_tool._REQUIRED_NATIVE]
    assert report["ok"] is False


def test_a_native_module_outside_crypto_does_not_satisfy_the_guard(tmp_path):
    """The guard looks inside the bundle's Crypto package; a same-named file
    anywhere else must not pass it."""
    bundle = _bundle(tmp_path, ("_raw_aes.so",), with_natives=False)

    report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

    assert report["missing"] == [kind for _name, kind in inspect_bundle_tool._REQUIRED_NATIVE]
    assert report["ok"] is False


def test_every_platform_spelling_of_the_native_modules_is_accepted(tmp_path):
    """The same module file is `_raw_aes.abi3.so`, `_raw_aes.cpython-…so` or
    `_raw_aes.pyd` depending on OS and packaging; all spellings satisfy the
    guard."""
    for index, suffix in enumerate((".abi3.so", ".cpython-313-darwin.so", ".pyd")):
        bundle = _bundle(tmp_path / str(index), (), with_natives=False)
        for module, _kind in inspect_bundle_tool._REQUIRED_NATIVE:
            path = bundle / "Contents" / "MacOS" / "Crypto" / "Cipher" / f"{module}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00")

        report = inspect_bundle_tool.inspect_bundle(bundle, verify_signature=False)

        assert report["missing"] == [], suffix
        assert report["ok"] is True


def test_a_missing_bundle_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_bundle_tool.inspect_bundle(tmp_path / "nope.app", verify_signature=False)


def test_cli_exit_codes(tmp_path):
    clean = _bundle(tmp_path / "clean", ())
    dirty = _bundle(tmp_path / "dirty", ("game.apkm",))

    assert inspect_bundle_tool.main([str(clean), "--no-signature", "--json"]) == 0
    assert inspect_bundle_tool.main([str(dirty), "--no-signature"]) == 1

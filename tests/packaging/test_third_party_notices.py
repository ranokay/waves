"""The third-party notices generator ships DEP-09's bundle artifact."""

from __future__ import annotations

import importlib.util

from support.paths import REPO_ROOT


def _load():
    spec = importlib.util.spec_from_file_location(
        "generate_third_party_notices", REPO_ROOT / "tools" / "generate_third_party_notices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notices_tool = _load()


def test_notices_list_the_bundle_closure_with_texts(tmp_path):
    bundle = tmp_path / "waves.dist"

    notice = notices_tool.generate(bundle)

    text = notice.read_text()
    for name in ("PySide6", "tidalapi", "mutagen", "pywidevine", "protobuf", "gamdl"):
        assert name in text, name
    licenses = list((bundle / "licenses").iterdir())
    assert licenses, "license texts must ship beside the notices"
    assert (bundle / "THIRD_PARTY_NOTICES").is_file()


def test_cli_writes_beside_the_app(tmp_path, capsys):
    bundle = tmp_path / "waves.app"
    bundle.mkdir()

    assert notices_tool.main([str(bundle)]) == 0

    assert (bundle / "THIRD_PARTY_NOTICES").is_file()
    assert any((bundle / "licenses").iterdir())
    assert "wrote" in capsys.readouterr().out


def test_generator_script_ships(tmp_path):
    # The build calls it as `python tools/generate_third_party_notices.py <bundle>`.
    assert (REPO_ROOT / "tools" / "generate_third_party_notices.py").is_file()

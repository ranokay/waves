"""Hand-edited boolean words in settings.json load as their boolean.

A string such as ``"false"`` used to reach the model decode untouched, where a
non-empty value read as true: ``false``, ``0`` and ``no`` all switched their
toggle back on. The pre-decode pass now rewrites the canonical six words and
drops any other word, which resets only that field to its model default and
leaves the rest of the file alone.
"""

from __future__ import annotations

import json

import pytest

from waves.config import BaseConfig
from waves.model.cfg import Settings as ModelSettings


def _cfg(tmp_path) -> BaseConfig:
    cfg = BaseConfig()
    cfg.cls_model = ModelSettings
    cfg.file_path = str(tmp_path / "settings.json")
    cfg.path_base = str(tmp_path)
    return cfg


def _read(tmp_path, raw: dict) -> BaseConfig:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    cfg = _cfg(tmp_path)
    assert cfg.read(str(path)) is True
    return cfg


def test_hand_edited_boolean_words_load_as_their_boolean(tmp_path):
    raw = json.loads(ModelSettings().to_json())
    raw["skip_existing"] = "false"
    raw["lyrics_embed"] = "Yes"
    raw["lyrics_file"] = "maybe"
    raw["download_delay_sec_min"] = 7

    data = _read(tmp_path, raw).data

    assert data.skip_existing is False
    assert data.lyrics_embed is True
    assert data.lyrics_file is ModelSettings().lyrics_file
    assert data.download_delay_sec_min == 7, "every other setting in the file survives"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" True ", True),
        ("false", False),
        ("FALSE", False),
        ("\tfalse\n", False),
        ("1", True),
        (" 1 ", True),
        ("0", False),
        (" 0 ", False),
        ("yes", True),
        ("YES", True),
        (" yes ", True),
        ("no", False),
        ("NO", False),
        (" no ", False),
    ],
)
def test_each_canonical_word_loads_as_its_boolean(tmp_path, word, expected):
    assert _read(tmp_path, {"skip_existing": word}).data.skip_existing is expected


def test_boolean_words_load_into_an_optional_boolean_field(tmp_path):
    assert _read(tmp_path, {"download_dolby_atmos": "no"}).data.download_dolby_atmos is False
    assert _read(tmp_path, {"download_dolby_atmos": "Yes"}).data.download_dolby_atmos is True


def test_an_unknown_boolean_word_resets_only_that_field(tmp_path):
    raw = json.loads(ModelSettings().to_json())
    # The default is False, so a truthy read of "maybe" is visible here.
    raw["lyrics_embed"] = "maybe"
    raw["download_delay_sec_min"] = 7

    cfg = _read(tmp_path, raw)

    assert cfg.data.lyrics_embed is False, "an unrecognized word resets the field to its default"
    assert cfg.data.download_delay_sec_min == 7, "the rest of the file survives"
    assert list(tmp_path.glob("settings.json*.bak")) == [], "the file is not set aside"


def test_real_booleans_and_other_field_shapes_load_as_before(tmp_path):
    raw = json.loads(ModelSettings().to_json())
    raw["skip_existing"] = False
    raw["lyrics_embed"] = True
    raw["quality_video"] = ModelSettings().quality_video
    raw["api_rate_limit_batch_size"] = 25
    raw["format_album"] = "custom {track_title}"

    data = _read(tmp_path, raw).data

    assert data.skip_existing is False
    assert data.lyrics_embed is True
    assert data.quality_video == ModelSettings().quality_video
    assert data.api_rate_limit_batch_size == 25
    assert data.format_album == "custom {track_title}"


def test_a_file_without_boolean_strings_comes_back_unchanged(tmp_path):
    path = tmp_path / "settings.json"
    text = ModelSettings().to_json()
    path.write_text(text, encoding="utf-8")

    assert _cfg(tmp_path).read(str(path)) is True

    assert path.read_text(encoding="utf-8") == text, "read's write-back left the file alone"

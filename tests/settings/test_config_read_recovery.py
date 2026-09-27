"""The corrupt-config repair can itself fail, and must not abort startup.

``BaseConfig.read`` moves a broken settings/token file aside and carries on,
but the move used to run unguarded: a config folder that cannot be written, or
a ``.bak`` that cannot be removed, raised ``OSError`` out of the constructor.
``Settings.__init__`` runs in the bridge constructor before QML loads, so that
exception meant the app never opened its window -- in exactly the locked-file
environment the atomic write already accounts for. The repair is now
best-effort: on failure the file is not moved aside, a warning is logged, and
the defaults stand.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from collections.abc import Iterator

from waves.config import BaseConfig
from waves.model.cfg import Settings as ModelSettings


def _cfg(tmp_path) -> BaseConfig:
    cfg = BaseConfig()
    cfg.cls_model = ModelSettings
    cfg.file_path = str(tmp_path / "settings.json")
    cfg.path_base = str(tmp_path)
    return cfg


@contextlib.contextmanager
def _config_log_records() -> Iterator[list[logging.LogRecord]]:
    """Attach to waves.config itself: diagnostics.install can stop the waves
    tree propagating, so caplog would see nothing when it has run."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("waves.config")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def test_a_backup_move_that_raises_warns_and_still_reads_as_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    cfg = _cfg(tmp_path)

    def refuse(src, dst):
        raise PermissionError("the config folder is not writable")

    monkeypatch.setattr(shutil, "move", refuse)

    with _config_log_records() as records:
        assert cfg.read(str(path)) is False

    assert [record.levelno for record in records] == [logging.WARNING]
    assert cfg.data == ModelSettings(), "a failed repair must leave the app on defaults"


def test_a_bak_that_cannot_be_removed_still_reads_as_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    # A directory in the .bak slot: the old code removed it; the ported
    # set-aside never deletes an older backup and timestamps instead.
    bak = tmp_path / "settings.json.bak"
    bak.mkdir()
    cfg = _cfg(tmp_path)

    with _config_log_records() as records:
        assert cfg.read(str(path)) is False

    assert [record.levelno for record in records] == [logging.WARNING]
    assert list(bak.iterdir()) == [], "the older backup is never deleted or filled"
    assert cfg.data == ModelSettings()
    assert cfg._keep_file_untouched is False, "the corrupt file was set aside, so defaults may persist"
    stamped = list(tmp_path.glob("settings.json.*.bak"))
    assert len(stamped) == 1, "the unusable file is kept under a timestamped backup"


def test_a_set_aside_that_fails_leaves_the_file_alone(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    cfg = _cfg(tmp_path)

    def refuse(src, dst):
        raise PermissionError("the config folder is not writable")

    monkeypatch.setattr(shutil, "move", refuse)

    with _config_log_records():
        assert cfg.read(str(path)) is False

    assert cfg._keep_file_untouched is True
    assert path.read_text(encoding="utf-8") == "[]", "the only copy must not be overwritten"
    cfg.write_serialized(cfg.data.to_json())
    assert path.read_text(encoding="utf-8") == "[]", "later saves must not overwrite it either"


def test_an_unreadable_file_runs_on_defaults_without_touching_it(tmp_path):
    path = tmp_path / "settings.json"
    path.mkdir()  # a folder under that name: open() raises OSError
    cfg = _cfg(tmp_path)

    with _config_log_records():
        assert cfg.read(str(path)) is False

    assert cfg._keep_file_untouched is True
    assert cfg.data == ModelSettings()
    assert path.is_dir(), "nothing is written over a file that may be fine"


def test_unusable_fields_are_dropped_and_the_rest_survives(tmp_path):
    from waves.config import _drop_unusable_fields

    good = ModelSettings().to_json()
    import json as _json

    raw = _json.loads(good)
    raw["skip_existing"] = None  # a null from a hand edit or half-merged sync
    raw["quality_video"] = "NO_SUCH_TIER"  # a rollback past a newer enum member
    witness = raw.get("download_delay_sec_min")
    dropped = _drop_unusable_fields(_json.dumps(raw), ModelSettings)
    kept = _json.loads(dropped)
    assert "skip_existing" not in kept
    assert "quality_video" not in kept
    assert kept["download_delay_sec_min"] == witness, "every usable field survives"

    path = tmp_path / "settings.json"
    path.write_text(_json.dumps(raw), encoding="utf-8")
    cfg = _cfg(tmp_path)
    assert cfg.read(str(path)) is True
    assert cfg.data.download_delay_sec_min == witness


def test_nulls_a_field_allows_survive(tmp_path):
    import json as _json

    from waves.config import _drop_unusable_fields
    from waves.model.cfg import Token as ModelToken

    # A logged-out token.json: nulls the model itself declares. Dropping them
    # would rewrite the file and warn on every launch over a healthy sign-out.
    raw = {"token_type": None, "access_token": None, "refresh_token": None, "expiry_time": 0.0}
    assert _drop_unusable_fields(_json.dumps(raw), ModelToken) == _json.dumps(raw)

    path = tmp_path / "settings.json"
    path.write_text(_json.dumps(raw), encoding="utf-8")
    cfg = _cfg(tmp_path)
    cfg.cls_model = ModelToken
    with _config_log_records() as records:
        assert cfg.read(str(path)) is True
    assert [r for r in records if "unusable field" in r.getMessage()] == []

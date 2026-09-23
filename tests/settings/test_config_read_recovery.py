"""The corrupt-config repair can itself fail, and must not abort startup.

``BaseConfig.read`` moves a broken settings/token file aside and carries on,
but the move used to run unguarded: a config folder that cannot be written, or
a ``.bak`` that cannot be removed, raised ``OSError`` out of the constructor.
``Settings.__init__`` runs in the bridge constructor before QML loads, so that
exception meant the app never opened its window -- in exactly the locked-file
environment the atomic write already accounts for. The repair is now
best-effort: on failure the file stays where it is, a warning is logged, and
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
    # A directory in the .bak slot: os.remove raises OSError on every platform.
    (tmp_path / "settings.json.bak").mkdir()
    cfg = _cfg(tmp_path)

    assert cfg.read(str(path)) is False
    assert cfg.data == ModelSettings()

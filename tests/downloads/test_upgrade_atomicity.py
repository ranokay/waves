"""An upgrade verifies first and commits atomically.

Any fetch/verification/placement/ownership failure leaves the origin file and
its row untouched; the backup falls back from a hard link to a same-folder copy.
"""

from __future__ import annotations

import pathlib

from waves.constants import QualityTier
from waves.library.upgrade import UpgradePlan, commit_upgrade, upgrade_eligible
from waves.metadata.digest import audio_digest
from waves.providers.catalog_offers import DeliveryFacts


def _plan(path: pathlib.Path, *, audio_type: str = "stereo") -> UpgradePlan:
    return UpgradePlan(
        origin_id="tidal:1",
        origin_path=str(path),
        audio_type=audio_type,
        recorded=DeliveryFacts(
            tier=QualityTier.LOSSLESS, audio_type=audio_type, codec="flac", bit_depth=16, sample_rate=44100
        ),
        delivered_provider="apple",
        delivered_media_id="apple:42",
        origin_digest=audio_digest(path),
    )


def _delivered(**changes) -> DeliveryFacts:
    values = {
        "tier": QualityTier.HI_RES_LOSSLESS,
        "audio_type": "stereo",
        "codec": "alac",
        "bit_depth": 24,
        "sample_rate": 96000,
    }
    values.update(changes)
    return DeliveryFacts(**values)


def test_eligibility_requires_a_demonstrated_same_type_improvement():
    plan = _plan(pathlib.Path("/music/Song.ogg"))

    assert upgrade_eligible(plan, _delivered()) is True
    assert upgrade_eligible(plan, _delivered(bit_depth=16, sample_rate=44100)) is False
    assert upgrade_eligible(plan, _delivered(audio_type="atmos")) is False
    assert upgrade_eligible(plan, _delivered(bit_depth=None, sample_rate=None)) is False


def test_same_container_commit_replaces_and_records(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new bytes")
    recorded: list = []

    result = commit_upgrade(
        staged,
        _plan(origin),
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=lambda final: recorded.append(pathlib.Path(final)),
    )

    assert result.ok and result.path == origin
    assert origin.read_bytes() == b"new bytes"
    assert recorded == [origin]
    assert not list(tmp_path.glob(".*waves-upgrade*"))


def test_a_record_failure_restores_the_origin_file(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new bytes")

    def fail(_final):
        raise RuntimeError("store unavailable")

    result = commit_upgrade(
        staged,
        _plan(origin),
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=fail,
    )

    assert not result.ok
    assert origin.read_bytes() == b"old bytes"


def test_a_hard_link_refusal_falls_back_to_a_same_folder_copy(tmp_path, monkeypatch):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new bytes")

    def no_link(*_args, **_kwargs):
        raise OSError("network mount")

    monkeypatch.setattr("waves.library.upgrade.os.link", no_link)

    result = commit_upgrade(
        staged,
        _plan(origin),
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=lambda final: None,
    )

    assert result.ok and origin.read_bytes() == b"new bytes"


def test_when_no_backup_can_be_made_the_upgrade_aborts(tmp_path, monkeypatch):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new bytes")

    monkeypatch.setattr("waves.library.upgrade.os.link", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr("waves.library.upgrade.shutil.copy2", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))

    result = commit_upgrade(
        staged,
        _plan(origin),
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=lambda final: None,
    )

    assert not result.ok
    assert origin.read_bytes() == b"old bytes"


def test_a_cross_container_commit_lands_the_new_extension_and_removes_the_old(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"new bytes")

    result = commit_upgrade(
        staged,
        _plan(origin),
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=lambda final: None,
    )

    assert result.ok
    assert result.path == tmp_path / "Song.m4a"
    assert result.path.read_bytes() == b"new bytes"
    assert not origin.exists()


def test_a_changed_origin_refuses_the_commit(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new bytes")
    plan = _plan(origin)
    origin.write_bytes(b"the user edited the audio")

    result = commit_upgrade(
        staged,
        plan,
        _delivered(),
        place=lambda source, final: pathlib.Path(source).replace(final) or True,
        record=lambda final: None,
    )

    assert not result.ok
    assert origin.read_bytes() == b"the user edited the audio"

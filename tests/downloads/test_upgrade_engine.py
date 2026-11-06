"""The TIDAL engine commits a verified upgrade only, and restores on failure."""

from __future__ import annotations

import pathlib
import shutil
from collections import defaultdict
from threading import Lock, local
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tidalapi import Track

from waves.constants import QualityTier
from waves.desktop import backend
from waves.download import StreamInfo
from waves.library.upgrade import UpgradePlan
from waves.metadata.digest import audio_digest
from waves.providers.catalog_offers import DeliveryFacts


def _tracked(tmp_path, *, plan, record_replacement):
    td = backend._TrackedDownload.__new__(backend._TrackedDownload)
    td._track_signals = MagicMock()
    td._tls = local()
    td._skip_existing_base = True
    td._duplicate_policy = "keep_existing"
    td._quality_strategy = "best_available"
    td._target_rank = 2
    td._upgrade_plan = plan
    td._record_replacement = record_replacement
    td._ownership_of = lambda *_a, **_k: None
    td.fn_logger = MagicMock()
    td._names_reserved = {}
    td._names_written = {}
    td._names_reserved_lock = Lock()
    td._delivered = {}
    td._delivered_lock = Lock()
    td._dirs_filled = set()
    td._dirs_filled_lock = Lock()
    td.settings = SimpleNamespace(
        data=SimpleNamespace(
            video_convert_mp4=False,
            extract_flac=False,
            downsample_enabled=False,
            path_binary_ffmpeg="",
        )
    )
    media = Track.__new__(Track)
    media.id = "1"
    media.waves_identity_id = None
    return td, media


def _plan(origin: pathlib.Path) -> UpgradePlan:
    return UpgradePlan(
        origin_id="tidal:1",
        origin_path=str(origin),
        audio_type="stereo",
        recorded=DeliveryFacts(
            tier=QualityTier.LOSSLESS, audio_type="stereo", codec="flac", bit_depth=16, sample_rate=44100
        ),
        delivered_provider="apple",
        delivered_media_id="1",
        origin_digest=audio_digest(origin),
    )


def _run(td, media, origin, *, delivered):
    stream_info = StreamInfo(
        delivered=delivered,
        codecs=str(delivered.get("codecs") or ""),
        file_extension=".ogg",
    )
    staged = pathlib.Path(str(origin)).with_name("staged")
    staged.write_bytes(b"new bytes")

    def place(source, final, **_kwargs):
        staged_final = final.with_name(final.name + ".part")
        shutil.copyfile(source, staged_final)
        staged_final.replace(final)
        return True

    with (
        patch.object(backend._TrackedDownload, "_download", return_value=(True, staged)),
        patch.object(backend._TrackedDownload, "_finalize_plan", lambda *a, **k: defaultdict(float)),
        patch.object(backend._TrackedDownload, "_note_stage", lambda *a, **k: None),
        patch.object(backend._TrackedDownload, "_claim_destination", return_value=(origin, "reserved")),
        patch.object(backend._TrackedDownload, "_handle_metadata_and_extras", return_value=None),
        patch.object(backend._TrackedDownload, "_move_file", side_effect=place),
        patch.object(backend._TrackedDownload, "_record_name_written"),
        patch.object(backend._TrackedDownload, "_note_dir_filled"),
        patch("waves.download.name_builder_item", return_value="x"),
    ):
        return td._perform_actual_download(media, origin, stream_info, False, None)


def _delivered() -> dict:
    return {
        "tier": "HI_RES_LOSSLESS",
        "audio_type": "stereo",
        "bit_depth": 24,
        "sample_rate": 96000,
        "codecs": "alac",
    }


def test_a_verified_upgrade_commits_and_reports_the_replacement(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    recorded: list = []
    td, media = _tracked(tmp_path, plan=_plan(origin), record_replacement=lambda *a, **k: recorded.append((a, k)))

    ok, landed = _run(td, media, origin, delivered=_delivered())

    assert ok and landed == origin
    assert origin.read_bytes() == b"new bytes"
    assert recorded
    assert td._tls.replaced == ("tidal:1", str(origin))


def test_a_delivery_that_does_not_improve_keeps_the_origin(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    td, media = _tracked(tmp_path, plan=_plan(origin), record_replacement=lambda *a, **k: None)

    ok, landed = _run(
        td,
        media,
        origin,
        delivered={"tier": "LOSSLESS", "audio_type": "stereo", "bit_depth": 16, "sample_rate": 44100},
    )

    assert ok and landed == origin
    assert origin.read_bytes() == b"old bytes"
    assert td._tls.outcome[0] == "retained"


def test_an_ownership_failure_restores_the_origin(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    td, media = _tracked(tmp_path, plan=_plan(origin), record_replacement=lambda *a, **k: None)

    def fail(*_a, **_k):
        raise RuntimeError("store unavailable")

    td._record_replacement = fail
    ok, landed = _run(td, media, origin, delivered=_delivered())

    assert ok and landed == origin
    assert origin.read_bytes() == b"old bytes"
    assert td._tls.outcome[0] == "retained"


def test_an_upgrade_without_an_ownership_callback_refuses_to_commit(tmp_path):
    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    td, _media = _tracked(tmp_path, plan=_plan(origin), record_replacement=None)
    td._record_replacement = None

    try:
        td._record_upgraded(_media, origin, None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("an upgrade without an ownership callback must not report success")


def test_a_forced_keep_existing_replacement_carries_tags(tmp_path, monkeypatch):
    import waves.download as download_module

    origin = tmp_path / "Song.ogg"
    origin.write_bytes(b"old bytes")
    td, media = _tracked(tmp_path, plan=None, record_replacement=None)
    td._duplicate_policy = "keep_existing"
    td._force_redownload = True
    td._ownership_of = lambda *_a, **_k: {
        "path": str(origin),
        "quality_rank": 2,
        "audio_digest": audio_digest(origin),
        "audio_type": "stereo",
    }
    called: list = []
    monkeypatch.setattr(
        download_module,
        "carry_over_tags",
        lambda *args, **kwargs: called.append((args, kwargs)) or 0,
    )

    ok, landed = _run(td, media, origin, delivered=_delivered())

    assert ok and landed == origin
    assert called and called[0][1]["strict"] is True

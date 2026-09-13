"""Dual-download: Atmos alongside stereo (issue #29).

One click queues both Versions where a real choice exists; each lands as its
own file (stereo beside the Atmos subfolder), with per-version ownership,
gates and button coverage. Toggle off stays byte-identical single rows.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from tidalapi.media import AudioMode, Quality, Track

from waves.constants import quality_rank
from waves.ownership import OwnershipStore, normalize_audio_type
from waves.waves_ui import backend
from waves.waves_ui.backend import (
    _copy_is_current,
    atmos_file_template,
)

ATMOS = AudioMode.dolby_atmos.value


def _track(tid="101", modes=None):
    t = Track.__new__(Track)
    t.id = tid
    t.name = "Song"
    t.artist = SimpleNamespace(name="Artist")
    t.audio_modes = list(modes) if modes is not None else [ATMOS]
    return t


def _file(tmp_path, name="song.m4a"):
    p = tmp_path / name
    p.write_text("audio")
    return str(p)


# Ownership per-version ----------------------------------------------------


def test_audio_type_normalizes_from_mode_and_explicit(tmp_path):
    assert normalize_audio_type("atmos", None) == "atmos"
    assert normalize_audio_type("STEREO", None) == "stereo"
    assert normalize_audio_type(None, "DOLBY_ATMOS") == "atmos"
    assert normalize_audio_type(None, "STEREO") == "stereo"
    assert normalize_audio_type(None, None) is None


def test_owning_stereo_leaves_the_atmos_half_fetching(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    store.record("tidal:101", _file(tmp_path, "stereo.m4a"), "LOSSLESS", audio_mode="STEREO")
    assert store.ownership_of("tidal:101", audio_type="stereo") is not None
    assert store.ownership_of("tidal:101", audio_type="atmos") is None
    # Whole-track still answers (best surviving, stereo) for legacy callers.
    assert store.ownership_of("tidal:101") is not None


def test_owning_both_versions_answers_each(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    store.record("tidal:101", _file(tmp_path, "stereo.flac"), "LOSSLESS", audio_mode="STEREO")
    store.record("tidal:101", _file(tmp_path, "atmos.m4a"), "HIGH", audio_mode="DOLBY_ATMOS")
    st = store.ownership_of("tidal:101", audio_type="stereo")
    at = store.ownership_of("tidal:101", audio_type="atmos")
    assert st is not None and at is not None
    assert st["path"].endswith("stereo.flac")
    assert at["path"].endswith("atmos.m4a")
    assert st["audio_type"] == "stereo"
    assert at["audio_type"] == "atmos"


def test_legacy_rows_backfill_from_mode(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    # A row written with only a mode gains its type on open (backfill).
    store.record("tidal:101", _file(tmp_path, "a.m4a"), "HIGH", audio_mode="DOLBY_ATMOS")
    assert store.ownership_of("tidal:101", audio_type="atmos") is not None
    assert store.ownership_of("tidal:101", audio_type="stereo") is None


def test_per_version_gates_close_the_second_path_gap(tmp_path):
    """Below-target stereo plus an Atmos-wanting job settles per version:
    the stereo half upgrades (force), the Atmos half fetches (None, not
    owned), and an owned Atmos half skips — instead of forcing forever."""
    from waves.waves_ui.backend import _TrackedDownload

    store = OwnershipStore(str(tmp_path / "own.db"))
    store.record("101", _file(tmp_path, "stereo.m4a"), "HIGH", audio_mode="STEREO")

    def gate(audio_type, target="LOSSLESS"):
        dl = _TrackedDownload.__new__(_TrackedDownload)
        dl._ownership_of = store.ownership_of
        dl._target_rank = quality_rank(target)
        dl._audio_type = audio_type
        dl.settings = SimpleNamespace(data=SimpleNamespace(default_audio_type="both"))
        return dl

    # Stereo half below target upgrades.
    verdict, _ = gate("stereo")._ownership_decision(_track("101", modes=[ATMOS, "STEREO"]))
    assert verdict == "force"
    # Atmos half missing fetches (no record, no gate).
    verdict, _ = gate("atmos")._ownership_decision(_track("101", modes=[ATMOS, "STEREO"]))
    assert verdict is None
    # Owned Atmos half skips.
    store.record("101", _file(tmp_path, "atmos.m4a"), "HIGH", audio_mode="DOLBY_ATMOS")
    verdict, _ = gate("atmos")._ownership_decision(_track("101", modes=[ATMOS, "STEREO"]))
    assert verdict == "skip"


# Placement -----------------------------------------------------------------


def test_atmos_template_inserts_a_subfolder_blank_means_alongside():
    base = "{artist_name}/[{album_year}] {album_title}/{album_track_num}. {artist_name} - {track_title}"
    assert atmos_file_template(base, "Dolby Atmos").endswith(
        "/Dolby Atmos/{album_track_num}. {artist_name} - {track_title}"
    )
    assert atmos_file_template(base, "") == base
    assert atmos_file_template(base, "   ") == base
    assert atmos_file_template("Song", "Dolby Atmos") == "Dolby Atmos/Song"


# Queue rows ---------------------------------------------------------------


class _InlinePool:
    def start(self, worker):
        worker.run()


def _bridge_for_button(store, *, atmos_on, tracks):
    b = backend.WavesBridge.__new__(backend.WavesBridge)
    b._ownership = store
    b._own_cache = {}
    b._own_lock = Lock()
    b._own_pending = set()
    b._own_pool = _InlinePool()
    b._own_announce = []
    b._own_announce_armed = False
    b._announce_ownership = lambda tid: None
    b._downloads_running = lambda: False
    b.settings = SimpleNamespace(
        data=SimpleNamespace(
            tidal_quality_audio=Quality.high_lossless.value,
            default_audio_type="both" if atmos_on else "stereo",
        )
    )
    b._objs = {"track": dict(tracks)}
    for name in (
        "ownershipOf",
        "_dual_button_need",
        "_override_target_rank",
        "_target_quality_rank",
        "_own_refresh",
        "_evict_own_cache_locked",
        "_would_refetch_atmos",
    ):
        setattr(b, name, getattr(backend.WavesBridge, name).__get__(b, backend.WavesBridge))
    return b


def test_button_settles_only_when_every_enabled_version_is_owned(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    dual = _track("101", modes=[ATMOS, "STEREO"])
    b = _bridge_for_button(store, atmos_on=True, tracks={"101": dual})
    # Nothing owned: DOWNLOAD.
    assert b.ownershipOf("101")["owned"] is False
    # Stereo only: still DOWNLOAD (Atmos half missing).
    store.record("101", _file(tmp_path, "stereo.flac"), "LOSSLESS", audio_mode="STEREO")
    b._own_cache.clear()
    b._own_refresh("101")
    info = b.ownershipOf("101")
    assert info["owned"] is True
    assert info["up_to_date"] is False
    # Both: DOWNLOADED.
    store.record("101", _file(tmp_path, "atmos.m4a"), "HIGH", audio_mode="DOLBY_ATMOS")
    b._own_cache.clear()
    b._own_refresh("101")
    assert b.ownershipOf("101")["up_to_date"] is True


def test_button_stays_single_when_default_is_stereo(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    dual = _track("101", modes=[ATMOS, "STEREO"])
    b = _bridge_for_button(store, atmos_on=False, tracks={"101": dual})
    store.record("101", _file(tmp_path, "stereo.flac"), "LOSSLESS", audio_mode="STEREO")
    b._own_refresh("101")
    assert b.ownershipOf("101")["up_to_date"] is True


def test_dual_button_need_is_cache_only_and_default_gated():
    b = backend.WavesBridge.__new__(backend.WavesBridge)
    b.settings = SimpleNamespace(data=SimpleNamespace(default_audio_type="both"))
    b._objs = {"track": {"1": _track("1", modes=[ATMOS, "STEREO"])}}
    b.providers = {}
    assert b._dual_button_need("1") == "both"
    b.settings.data.default_audio_type = "stereo"
    assert b._dual_button_need("1") is None
    # Direct helper (no bridge needed for the pure question).
    assert backend._offers_both(_track("1", modes=[ATMOS, "STEREO"])) is True
    assert backend._offers_both(_track("1", modes=[ATMOS])) is False
    assert backend._offers_both(_track("1", modes=["STEREO"])) is False


def test_copy_is_current_atmos_clause_generalized(tmp_path):
    # An owned Atmos copy is current for an Atmos-wanting job (existing
    # clause, generalized per version).
    rec = {"quality_tier": "HIGH", "quality_rank": quality_rank("HIGH"), "audio_mode": ATMOS, "audio_type": "atmos"}
    assert _copy_is_current(rec, quality_rank("HI_RES_LOSSLESS"), True) is True
    # ... but a stereo copy below target still upgrades.
    rec_st = {
        "quality_tier": "HIGH",
        "quality_rank": quality_rank("HIGH"),
        "audio_mode": "STEREO",
        "audio_type": "stereo",
    }
    assert _copy_is_current(rec_st, quality_rank("LOSSLESS"), False) is False


# Tags ----------------------------------------------------------------------


def test_untagged_files_read_no_audio_type(tmp_path):
    from waves.metadata import read_audio_type

    p = tmp_path / "plain.txt"
    p.write_text("not audio")
    assert read_audio_type(p) is None


def test_file_mode_reader_prefers_the_tag_over_the_codec(tmp_path, monkeypatch):
    """WAVES_AUDIO_TYPE answers first; the codec sniff is legacy fallback."""
    import shutil
    import subprocess

    import waves.download as download_mod
    from waves.constants import METADATA_LOOKUP_UPC, MetadataTargetUPC
    from waves.download import _file_audio_mode_is_atmos
    from waves.metadata import Metadata

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        import pytest

        pytest.skip("needs ffmpeg")
    target = tmp_path / "song.m4a"
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(target)],
        check=True,
    )
    meta = Metadata(
        path_file=target,
        target_upc=METADATA_LOOKUP_UPC[MetadataTargetUPC.UPC],
        title="Song",
        artists=["Artist"],
        albumartist=["Artist"],
        item_id="tidal:101",
        artist_ids=["1"],
        album_artist_ids=["1"],
        audio_type="atmos",
    )
    assert meta.save()

    class _Info:
        codec = "mp4a.40.2"  # stereo codec, contradicting the tag

    class _MP4:
        def __init__(self, _path):
            self.info = _Info()

    monkeypatch.setattr(download_mod, "MP4", _MP4)
    assert _file_audio_mode_is_atmos(target) is True

    # And an untagged file still falls back to the codec.
    plain = tmp_path / "plain.m4a"
    plain.write_bytes(b"stand-in")

    class _Info2:
        codec = "ec-3"

    class _MP42:
        def __init__(self, _path):
            self.info = _Info2()

    monkeypatch.setattr(download_mod, "MP4", _MP42)
    assert _file_audio_mode_is_atmos(plain) is True

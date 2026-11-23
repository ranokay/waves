"""Version-aware skip and ownership.

WHAT THIS FENCES OFF
--------------------
A dual download keeps one file per Version, and a blank ``format_atmos``
aims both rows at one name (spec §5.4: collisions fall to the numbered-copy
machinery). An id-only pre-stream skip lets the second row see the first
row's file, judge it "already downloaded", fetch nothing and record no
ownership: the Atmos half silently vanishes.

Every occupant gate must ask the same Version-aware on-disk question the
replace gate asks: the pre-stream and post-stream skips
(``_existing_same_item_at(..., version=...)``), the "has this fetch already
landed here" checks (``_already_landed_here``, whose id-only disk arm
discards the fetched Atmos bytes), the symlink-target and playlist-move
gates, and the Apple runner's own two skips. An untagged/unreadable occupant
and an unpinned job keep the skip -- neither is evidence of a DIFFERENT
Version.

Coverage: this module drives the gates and one full
``_perform_actual_download`` run (the blank template's numbered copy);
tests/downloads/test_apple_job_runner.py drives the Apple runner end to
end; tests/downloads/test_dual_download.py covers the per-Version
ownership gates that decide the two rows in the first place.
"""

from __future__ import annotations

import pathlib
import threading
from unittest.mock import MagicMock, patch

from tidalapi.media import Track

from waves.download import Download


def _make_download(*, pinned_audio_type: str | None = None) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=True,
        path_base="./tmp",
        fn_logger=MagicMock(),
        progress=MagicMock(),
        pinned_audio_type=pinned_audio_type,
    )
    dl.settings = MagicMock()
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()
    return dl


def _track(track_id: int = 101) -> Track:
    t = Track.__new__(Track)
    t.id = track_id
    t.audio_modes = ["DOLBY_ATMOS"]
    t.artists = []
    t.name = "Song"
    t.version = None
    return t


def _occupant(tmp_path: pathlib.Path, name: str = "Song.m4a") -> pathlib.Path:
    path = tmp_path / name
    path.write_bytes(b"audio")
    return path


def _modes(monkeypatch, mapping: dict):
    """Answer the Version question from a path -> "stereo"/"atmos"/None map.

    The shared rule (waves.metadata.tags.occupant_is_version) stays under test; its
    reader is the seam (its own rules live in tests/metadata and
    tests/library/test_atmos_never_overwritten).
    """

    def probe(path_file):
        return mapping.get(pathlib.Path(path_file))

    monkeypatch.setattr("waves.metadata.tags.read_file_audio_type", probe)


def test_a_stereo_occupant_does_not_answer_for_the_atmos_row(tmp_path, monkeypatch):
    """The acceptance's case: one blank-aimed name, the stereo file on disk.
    The Atmos row must fetch its own Version instead of skipping."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "stereo"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), "atmos") is None


def test_a_stereo_occupant_skips_the_stereo_row(tmp_path, monkeypatch):
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "stereo"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), "stereo") == occupant


def test_an_atmos_occupant_does_not_answer_for_the_stereo_row(tmp_path, monkeypatch):
    """The acceptance's reverse too: an Atmos copy on disk with stereo
    missing fetches stereo, it does not settle as done."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "atmos"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), "stereo") is None


def test_an_atmos_occupant_skips_the_atmos_row(tmp_path, monkeypatch):
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "atmos"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), "atmos") == occupant


def test_the_two_rows_of_a_dual_download_decide_against_one_blank_template(tmp_path, monkeypatch):
    """One file, two rows: the stereo row skips it, the Atmos row does not.
    This is the whole of blank-format_atmos + skip-existing, at the gate both
    rows consult before fetching."""
    occupant = _occupant(tmp_path, "Xtal.m4a")
    _modes(monkeypatch, {occupant: "stereo"})
    with patch("waves.download.read_item_id", return_value="101"):
        stereo = _make_download()._existing_same_item_at(occupant, _track(), "stereo")
        atmos = _make_download()._existing_same_item_at(occupant, _track(), "atmos")
    assert stereo == occupant  # the stereo half is already here
    assert atmos is None  # the Atmos half still has to fetch


def test_an_unreadable_occupant_keeps_the_historical_skip(tmp_path, monkeypatch):
    """A mode that cannot be read is not evidence of a different Version: the
    skip stands, or an existing pre-tag library would be duplicated wholesale."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: None})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), "atmos") == occupant


def test_an_unpinned_job_keeps_the_historical_skip(tmp_path, monkeypatch):
    """A legacy single row has no Version to compare against; the engine
    decides the stream's mode after this gate."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "atmos"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), None) == occupant


def test_a_numbered_variant_in_the_other_version_does_not_answer_either(tmp_path, monkeypatch):
    """The variant scan is Version-aware too, per candidate: a base occupant
    that is NOT this item (a colliding stranger) must not stop the scan, and
    the item's own copy at the numbered name only answers for its Version."""
    base = _occupant(tmp_path, "Song.m4a")  # a colliding stranger's file
    variant = _occupant(tmp_path, "Song_01.m4a")  # this item's stereo copy
    # Both occupants read as stereo on disk.
    _modes(monkeypatch, {base: "stereo", variant: "stereo"})

    def ids(path):
        return "999" if pathlib.Path(path) == base else "101"

    dl = _make_download()
    with patch("waves.download.read_item_id", side_effect=ids):
        # The stereo row: the variant is this Version's copy, so it skips there.
        assert dl._existing_same_item_at(base, _track(), "stereo") == variant
        # The Atmos row: a stereo copy is not this Version's, wherever it sits.
        assert dl._existing_same_item_at(base, _track(), "atmos") is None


def test_the_atmos_row_lands_beside_the_stereo_file_end_to_end(tmp_path, monkeypatch):
    """The acceptance, through the real pipeline: the Atmos row of a dual
    download must not stop at the stereo file the pre-stream gates let it
    through. With the blank template's one destination, the real
    _perform_actual_download must skip nothing, claim the numbered copy and
    leave the stereo file alone. A failure here means _already_landed_here's
    id-only disk arm discarded the fetched Atmos bytes."""
    from types import SimpleNamespace

    from waves.download import StreamInfo

    occupant = tmp_path / "Song.m4a"
    occupant.write_bytes(b"stereo bytes")
    monkeypatch.setattr(
        "waves.metadata.tags.read_file_audio_type",
        lambda path_file: "stereo" if pathlib.Path(path_file) == occupant else None,
    )
    monkeypatch.setattr(
        "waves.download.read_item_id", lambda path_file: "101" if pathlib.Path(path_file) == occupant else ""
    )
    dl = _make_download(pinned_audio_type="atmos")
    dl.settings = SimpleNamespace(
        data=SimpleNamespace(
            path_binary_ffmpeg="",
            extract_flac=False,
            downsample_enabled=False,
            video_convert_mp4=False,
        )
    )
    stream_info = StreamInfo(file_extension=".m4a", single_file=True, delivered={"audio_type": "atmos"})
    cls = Download
    with (
        patch.object(cls, "_download", return_value=(True, tmp_path / "raw")),
        patch.object(cls, "_extract_flac", side_effect=lambda p, transcode=False: p),
        patch.object(cls, "_downsample_audio", side_effect=lambda p: p),
        patch.object(cls, "_faststart_remux", side_effect=lambda p, s: p),
        patch.object(cls, "_handle_metadata_and_extras", return_value=None),
        patch.object(cls, "_move_file", return_value=True),
        patch.object(cls, "_record_name_written"),
        patch("waves.download.name_builder_item", return_value="Song"),
    ):
        ok, landed = dl._perform_actual_download(_track(), occupant, stream_info, False, None)

    assert ok is True
    assert landed != occupant  # the stereo file is not this fetch's landing
    assert landed == tmp_path / "Song_01.m4a"  # the blank template's numbered copy
    assert landed is not None


def test_the_engine_call_site_passes_the_jobs_pin(tmp_path, monkeypatch):
    """The gate is only Version-aware because the real pre-stream call site
    hands it the job's pin: both rows of a dual download consult one blank
    destination and answer differently."""
    from types import SimpleNamespace

    occupant = _occupant(tmp_path, "Xtal.m4a")
    _modes(monkeypatch, {occupant: "stereo"})

    def prepare(pinned):
        dl = _make_download(pinned_audio_type=pinned)
        dl.settings = SimpleNamespace(data=SimpleNamespace(symlink_to_track=False))
        dl._destination_path = lambda *a, **k: (occupant, ".m4a")
        with patch("waves.download.read_item_id", return_value="101"):
            _dst, _ext, skip_file, skip_download = dl._prepare_file_paths_and_skip_logic(
                _track(), "{track_title}", None, 0, 0
            )
        return skip_file, skip_download

    assert prepare("stereo") == (True, False)  # the stereo half is here
    assert prepare("atmos") == (False, False)  # the Atmos half still fetches


def test_the_crossing_pin_reaches_the_engine_from_the_bridge():
    """The bridge hands the engine the row's Version and rung (the Version is
    what makes the pre-stream gate Version-aware; the rung is the fetch's
    request, carried through the seam)."""
    from waves.constants import QualityTier
    from waves.desktop.backend import _TrackedDownload

    dl = _TrackedDownload(
        tidal_obj=MagicMock(),
        path_base="./tmp",
        fn_logger=MagicMock(),
        skip_existing=True,
        progress=MagicMock(),
        audio_type="atmos",
        pinned_quality=QualityTier.HI_RES_LOSSLESS,
    )
    assert dl._pinned_audio_type == "atmos"
    assert dl._audio_type == "atmos"
    assert dl._pinned_tier == QualityTier.HI_RES_LOSSLESS
    dl = _TrackedDownload(
        tidal_obj=MagicMock(),
        path_base="./tmp",
        fn_logger=MagicMock(),
        skip_existing=True,
        progress=MagicMock(),
        audio_type="nonsense",
    )
    assert dl._pinned_audio_type is None and dl._audio_type is None
    assert dl._pinned_tier is None


def test_the_delivered_word_outranks_the_pin_after_the_stream():
    """Post-stream the stream's own answer decides (the pin was the ask); a
    stream that does not say falls back to the pin."""
    from types import SimpleNamespace

    from waves.download import Download

    assert Download._delivered_version(SimpleNamespace(delivered={"audio_type": "atmos"})) == "atmos"
    assert Download._delivered_version(SimpleNamespace(delivered={"audio_type": "STEREO"})) == "stereo"
    assert Download._delivered_version(SimpleNamespace(delivered={})) is None
    assert Download._delivered_version(SimpleNamespace()) is None

    # _fetch_version prefers the delivered word and falls back to the pin.
    dl = _make_download(pinned_audio_type="atmos")
    assert dl._fetch_version(SimpleNamespace(delivered={"audio_type": "stereo"})) == "stereo"
    assert dl._fetch_version(SimpleNamespace(delivered={})) == "atmos"
    assert dl._fetch_version() == "atmos"
    assert _make_download()._fetch_version() is None

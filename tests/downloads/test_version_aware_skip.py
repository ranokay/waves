"""Version-aware skip and ownership (issue #231, audit R-12 / TS-02, AP-04).

WHAT THIS FENCES OFF
--------------------
A dual download keeps one file per Version, and a blank ``format_atmos``
aims both rows at one name (spec §5.4: collisions fall to the numbered-copy
machinery). The pre-stream skip was id-only, so the second row saw the first
row's file, judged it "already downloaded", fetched nothing and recorded no
ownership: the Atmos half silently vanished.

The fix makes the occupant gate Version-aware before the fetch (the same
on-disk mode question the replace gate already asked after it):
``_existing_same_item_at(..., fetch_is_atmos=...)`` refuses an occupant in
the other Version, and the Apple runner's own skip asks the same question.
An untagged/unreadable occupant and an unpinned job keep the historical
skip -- neither is evidence of a DIFFERENT Version.

The real end-to-end shape (both rows fetching through the engine) is also
driven in tests/downloads/test_apple_job_runner.py for the Apple runner and
tests/downloads/test_dual_download.py for the per-Version ownership gates.
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

    The shared rule (waves.metadata.occupant_is_version) stays under test; its
    reader is the seam (its own rules live in tests/metadata and
    tests/library/test_atmos_never_overwritten).
    """

    def probe(path_file):
        return mapping.get(pathlib.Path(path_file))

    monkeypatch.setattr("waves.metadata.read_audio_mode", probe)


def test_a_stereo_occupant_does_not_answer_for_the_atmos_row(tmp_path, monkeypatch):
    """The acceptance's case: one blank-aimed name, the stereo file on disk.
    The Atmos row must fetch its own Version instead of skipping."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "stereo"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), True) is None


def test_a_stereo_occupant_skips_the_stereo_row(tmp_path, monkeypatch):
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "stereo"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), False) == occupant


def test_an_atmos_occupant_does_not_answer_for_the_stereo_row(tmp_path, monkeypatch):
    """The acceptance's reverse too: an Atmos copy on disk with stereo
    missing fetches stereo, it does not settle as done."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "atmos"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), False) is None


def test_an_atmos_occupant_skips_the_atmos_row(tmp_path, monkeypatch):
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: "atmos"})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), True) == occupant


def test_the_two_rows_of_a_dual_download_decide_against_one_blank_template(tmp_path, monkeypatch):
    """One file, two rows: the stereo row skips it, the Atmos row does not.
    This is the whole of blank-format_atmos + skip-existing, at the gate both
    rows consult before fetching."""
    occupant = _occupant(tmp_path, "Xtal.m4a")
    _modes(monkeypatch, {occupant: "stereo"})
    with patch("waves.download.read_item_id", return_value="101"):
        stereo = _make_download()._existing_same_item_at(occupant, _track(), False)
        atmos = _make_download()._existing_same_item_at(occupant, _track(), True)
    assert stereo == occupant  # the stereo half is already here
    assert atmos is None  # the Atmos half still has to fetch


def test_an_unreadable_occupant_keeps_the_historical_skip(tmp_path, monkeypatch):
    """A mode that cannot be read is not evidence of a different Version: the
    skip stands, or an existing pre-tag library would be duplicated wholesale."""
    occupant = _occupant(tmp_path)
    _modes(monkeypatch, {occupant: None})
    dl = _make_download()
    with patch("waves.download.read_item_id", return_value="101"):
        assert dl._existing_same_item_at(occupant, _track(), True) == occupant


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
        assert dl._existing_same_item_at(base, _track(), False) == variant
        # The Atmos row: a stereo copy is not this Version's, wherever it sits.
        assert dl._existing_same_item_at(base, _track(), True) is None


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
    """The bridge hands the engine the row's pin (that is what makes the
    pre-stream gate Version-aware at all)."""
    from waves.waves_ui.backend import _TrackedDownload

    dl = _TrackedDownload.__new__(_TrackedDownload)
    dl._pinned_audio_type = "atmos"
    assert dl._pinned_is_atmos() is True
    dl._pinned_audio_type = "stereo"
    assert dl._pinned_is_atmos() is False
    dl._pinned_audio_type = None
    assert dl._pinned_is_atmos() is None


def test_the_delivered_word_outranks_the_pin_after_the_stream():
    """Post-stream the stream's own answer decides (the pin was the ask); a
    stream that does not say falls back to the pin."""
    from types import SimpleNamespace

    from waves.download import Download

    assert Download._delivered_is_atmos(SimpleNamespace(delivered={"audio_type": "atmos"})) is True
    assert Download._delivered_is_atmos(SimpleNamespace(delivered={"audio_type": "stereo"})) is False
    assert Download._delivered_is_atmos(SimpleNamespace(delivered={})) is None
    assert Download._delivered_is_atmos(SimpleNamespace()) is None

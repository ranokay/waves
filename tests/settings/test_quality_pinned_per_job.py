"""A download finishes at the quality it was queued at.

WHAT THIS FENCES OFF
--------------------
Streams are asked for at the SHARED tidal session's audio quality, and saving
a new audio quality writes it to that session at once (issue #9, so the choice
takes effect without a restart). That also silently retargeted work the user
had already started: a queue full of albums lined up at HI-RES began arriving
at HIGH the moment the setting changed, mid-run, and the drawer re-stated
every queued row to match.

Now each row records the quality it was queued at (``askQuality``) and its job
carries that quality as the seam resolve's own argument (R-13: the job's
request travels, shared state does not). ``Download._get_track_stream_info``
-- the engine resolver the provider calls back -- writes the rung onto the
session inside ``tidal.stream_lock``, the lock that already serialises every
stream fetch in the process, and puts back what it found. A change in Settings
therefore applies to what is queued NEXT; what is queued or running keeps its
quality, and the drawer keeps stating it (test_queue_expected_tier.py).

HOW THIS STAYS FIXED
--------------------
Method-bound stubs, no display and no session, driving the REAL engine
resolver with the job's request as the resolver's own arguments: the row
records the setting at enqueue; the runner hands that quality to the download
it builds; the engine asks at the job's rung and leaves the session as found;
an Atmos fetch keeps the Atmos request quality; a failed session restore is
answered the way the engine answers it (no stream, a retry later).

The Atmos case is fenced with the switch REALLY performed inside the fetch
(``_SwitchingTidal``), because a recorder-only session hides a put-back over
the Atmos request: the switch writes the Atmos quality only when it has to
BUILD the session, so the damage would show on the NEXT track, not this one.
"""

from __future__ import annotations

import inspect
from threading import Lock
from types import SimpleNamespace

import pytest
from tidalapi.media import AudioMode, Quality

from waves.config import ATMOS_REQUEST_QUALITY, tidal_quality_for_tier
from waves.constants import QualityTier
from waves.download import Download
from waves.waves_ui import backend

_ATMOS = AudioMode.dolby_atmos.value
_DUAL = (_ATMOS, "STEREO")


class _Session:
    """A session that records the quality each fetch is asked at.

    Both fetch arms land here: a stereo fetch asks the catalog object
    (``media.get_stream()``), an Atmos fetch the session's own track handle
    (``session.track(id).get_stream()``), and both record through ``asked``.
    """

    def __init__(self, quality=Quality.high_lossless):
        self.audio_quality = quality
        self.asked: list = []

    def track(self, _id):
        return SimpleNamespace(get_stream=self.record_stream)

    def record_stream(self):
        self.asked.append(self.audio_quality)
        return _stream()


def _stream():
    return SimpleNamespace(get_stream_manifest=lambda: SimpleNamespace(file_extension=".flac", codecs="FLAC"))


def _media(session, media_id="s", modes=()):
    """A stand-in track whose stereo fetch records the asked quality."""

    def get_stream():
        session.asked.append(session.audio_quality)
        return _stream()

    return SimpleNamespace(id=media_id, audio_modes=list(modes), get_stream=get_stream)


class _RecordingTidal:
    """The session switch and normalisation as recorders: which arm the fetch
    took, and how often it was asked to normalise."""

    def __init__(self):
        self.switches = 0
        self.restores = 0

    def switch_to_atmos_session(self) -> bool:
        self.switches += 1
        return True

    def restore_normal_session(self, force: bool = False) -> bool:
        self.restores += 1
        return True


class _Data:
    """Settings data whose audio-type default records every write, so a fetch
    that touched the user's choice cannot pass silently (R-13)."""

    def __init__(self, default_audio_type="stereo"):
        self._default = default_audio_type
        self.writes: list = []
        self.extract_flac = False
        self.tidal_quality_audio = "HI_RES_LOSSLESS"

    @property
    def default_audio_type(self):
        return self._default

    @default_audio_type.setter
    def default_audio_type(self, value):
        self.writes.append(value)
        self._default = value


def _engine(tidal, session, *, data=None, setting="stereo"):
    """The REAL engine resolver with only a session and settings beside it.
    The job's request arrives as the resolver's arguments (R-13), so no
    ``_pinned_tier`` / ``_pinned_audio_type`` instance state is involved."""
    dl = Download.__new__(Download)
    dl.tidal = tidal
    dl.session = session
    dl.settings = SimpleNamespace(data=data if data is not None else _Data(setting))
    dl.fn_logger = SimpleNamespace(error=lambda *a, **k: None, info=lambda *a, **k: None)
    return dl


def _fetch(session, *, tier, audio_type=None, modes=(), setting="stereo", tidal=None, data=None):
    dl = _engine(tidal or _RecordingTidal(), session, data=data, setting=setting)
    return dl, dl._get_track_stream_info(_media(session, modes=modes), tier, audio_type)


def test_the_fetch_uses_the_jobs_quality_and_the_session_is_left_as_found():
    session = _Session(Quality.low_320k)
    tidal = _RecordingTidal()
    _dl, info = _fetch(session, tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", tidal=tidal)
    assert session.asked == [Quality.hi_res_lossless], "the stream was not asked for at the job's quality"
    assert session.audio_quality == Quality.low_320k, "the shared session kept the job's quality"
    assert info.media_stream is not None
    # The rung is applied on top of the engine's own normalisation, which
    # re-reads the setting when it has to rebuild a normal session.
    assert tidal.restores == 1


def test_a_job_without_a_pin_is_left_entirely_alone():
    session = _Session(Quality.high_lossless)
    tidal = _RecordingTidal()
    _fetch(session, tier=None, tidal=tidal)
    assert session.asked == [Quality.high_lossless]
    assert session.audio_quality == Quality.high_lossless
    assert tidal.restores == 1  # the engine's own normalisation, and no pin


def test_an_atmos_pinned_row_fetches_atmos_whatever_the_default_says():
    """The R-13 acceptance's first leg, and TS-01's exact trigger: the stored
    default is stereo (the shipped default) and the queued ask is Atmos. The
    fetch used to read the setting, so the Atmos row fetched a stereo stream
    into the Atmos template; the pinned request decides now."""
    session = _Session(Quality.high_lossless)
    tidal = _RecordingTidal()
    _dl, info = _fetch(session, tier=QualityTier.HI_RES_LOSSLESS, audio_type="atmos", modes=_DUAL, tidal=tidal)
    assert tidal.switches == 1 and tidal.restores == 0, "the Atmos request did not take the Atmos session"
    assert info.media_stream is not None


def test_a_stereo_pinned_row_fetches_stereo_whatever_the_default_says():
    """The mirror: a "both" default must not drag a stereo row into the Atmos
    session (the row's Version is the user's answer to the choice)."""
    session = _Session(Quality.high_lossless)
    tidal = _RecordingTidal()
    _dl, info = _fetch(
        session, tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", modes=_DUAL, setting="both", tidal=tidal
    )
    assert (tidal.switches, tidal.restores) == (0, 1)
    assert session.asked == [Quality.hi_res_lossless], "the job's rung, not the setting, must be asked for"
    assert info.media_stream is not None


def test_a_fetch_never_writes_the_saved_default():
    """TS-03's fix: the transient stereo hold is gone. Nothing on the fetch
    path writes the audio-type default, so no save can persist a job's
    transient choice and no crash can leave one on disk."""
    session = _Session(Quality.high_lossless)
    data = _Data("both")
    _fetch(session, tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", modes=_DUAL, data=data)
    assert data.writes == [], "a fetch mutated the user's audio-type default"
    assert data.default_audio_type == "both"


def test_a_settings_save_during_the_fetch_persists_the_users_default():
    """The acceptance's save-during-a-fetch leg: a stereo-pinned row is in
    flight under a "both" default and a save lands inside the fetch (before
    the stream comes back), serialising the settings the way _save_settings
    does. It must serialize "both", never the row's stereo."""
    session = _Session(Quality.high_lossless)
    data = _Data("both")
    saved: list = []

    def get_stream():
        session.asked.append(session.audio_quality)
        saved.append(data.default_audio_type)  # what a save would write out
        return _stream()

    media = SimpleNamespace(id="s", audio_modes=list(_DUAL), get_stream=get_stream)
    dl = _engine(_RecordingTidal(), session, data=data)
    dl._get_track_stream_info(media, QualityTier.HI_RES_LOSSLESS, "stereo")
    assert saved == ["both"]
    assert data.writes == []


# --------------------------------------------------------------------------- #
# Atmos fetches and the session's own request quality.
# --------------------------------------------------------------------------- #
class _SwitchingTidal:
    """The session switch as waves/config.py really performs it.

    The two facts that matter, and that a recorder-only stub hides: the Atmos
    request quality is written only when the session has to be BUILT, and the
    flag is sticky, so a second switch on an already-Atmos session writes
    nothing at all. Restoring a normal session re-reads the setting.
    """

    def __init__(self, session, setting_quality):
        self.session = session
        self.is_atmos_session = False
        self.restores = 0
        self.settings = SimpleNamespace(data=SimpleNamespace(tidal_quality_audio=setting_quality))

    def switch_to_atmos_session(self) -> bool:
        if self.is_atmos_session:
            return True
        self.session.audio_quality = ATMOS_REQUEST_QUALITY
        self.is_atmos_session = True
        return True

    def restore_normal_session(self, force: bool = False) -> bool:
        self.restores += 1
        if not self.is_atmos_session and not force:
            return True
        self.session.audio_quality = tidal_quality_for_tier(QualityTier(self.settings.data.tidal_quality_audio))
        self.is_atmos_session = False
        return True


def _run(pinned_versions, session, *, tier=QualityTier.HI_RES_LOSSLESS):
    """Drive the real resolver over a RUN of tracks, reporting the quality each
    fetch was actually asked at. The Atmos switch runs for real, so a put-back
    over it would show on the following track."""
    tidal = _SwitchingTidal(session, "HI_RES_LOSSLESS")
    dl = _engine(tidal, session, setting="both")
    asked: list = []
    for audio_type, modes in pinned_versions:
        dl._get_track_stream_info(_media(session, modes=modes), tier, audio_type)
        asked.append(session.asked[-1])
    return asked, tidal


def test_an_atmos_fetch_keeps_the_atmos_request_quality():
    session = _Session(Quality.hi_res_lossless)
    asked, tidal = _run([("atmos", [_ATMOS])], session)
    assert asked == [ATMOS_REQUEST_QUALITY], "the job's rung overrode the Atmos request quality"
    assert session.audio_quality == ATMOS_REQUEST_QUALITY, "the rung was put back over the Atmos session"
    assert tidal.restores == 0, "an Atmos fetch is the engine's business; the rung restores nothing"


def test_every_atmos_track_in_a_run_is_asked_for_at_the_atmos_quality():
    """Not just the first one: a put-back over the Atmos request would leave
    the Atmos session asking for stereo for the rest of the job."""
    session = _Session(Quality.hi_res_lossless)
    asked, _tidal = _run([("atmos", [_ATMOS])] * 3, session)
    assert asked == [ATMOS_REQUEST_QUALITY] * 3, asked


def test_a_run_that_mixes_atmos_and_stereo_asks_each_at_its_own_quality():
    """And each stereo fetch's restore decides what it puts back, so the Atmos
    quality never leaks onto a rebuilt normal session."""
    session = _Session(Quality.hi_res_lossless)
    asked, _tidal = _run([("atmos", [_ATMOS]), ("stereo", []), ("atmos", [_ATMOS])], session)
    assert asked == [ATMOS_REQUEST_QUALITY, Quality.hi_res_lossless, ATMOS_REQUEST_QUALITY], asked


# --------------------------------------------------------------------------- #
# The queue row pins its ask.
# --------------------------------------------------------------------------- #
def test_the_row_records_the_setting_it_was_queued_at():
    stub = SimpleNamespace()
    stub._queue_seq = 0
    stub._queue = []
    stub._queue_index = {}
    stub._queue_lock = Lock()
    stub._qdirty_added = []  # _enqueue marks the new row for the delta flush
    stub._emit_queue = lambda: None
    stub._target_tier = lambda: "HI-RES"
    stub.settings = SimpleNamespace(data=SimpleNamespace(tidal_quality_audio="HI_RES_LOSSLESS"))
    stub._queued_quality_value = backend.WavesBridge._queued_quality_value.__get__(stub, type(stub))
    # The other value a row pins at birth, tested on its own in
    # tests/ui/test_queue_row_pins_the_library_skip.py.
    stub._library_bulk_skip_on = lambda: True
    qid = backend.WavesBridge._enqueue.__get__(stub, type(stub))("Album", "album")
    assert stub._queue[0]["askQuality"] == "HI_RES_LOSSLESS"
    assert stub._queue[0]["qid"] == qid


def test_an_unreadable_setting_pins_nothing_rather_than_failing_to_queue():
    stub = SimpleNamespace()  # no settings at all
    assert backend.WavesBridge._queued_quality_value.__get__(stub, type(stub))() == ""


@pytest.mark.parametrize(
    ("raw", "want"),
    [(Quality.low_320k.value, Quality.low_320k), ("", None), ("NOT_A_TIER", None)],
)
def test_job_quality_reads_the_row(raw, want):
    stub = SimpleNamespace()
    stub._queue_item = lambda qid: {"qid": qid, "askQuality": raw}
    assert backend.WavesBridge._job_quality.__get__(stub, type(stub))(1) == want


def test_a_missing_row_pins_nothing():
    stub = SimpleNamespace(_queue_item=lambda qid: None)
    assert backend.WavesBridge._job_quality.__get__(stub, type(stub))(1) is None


def test_the_runner_hands_its_rows_quality_to_the_download():
    src = inspect.getsource(backend.WavesBridge)
    call = src[src.index("dl = self._build_download(") :]
    call = call[: call.index("\n        )")]
    assert "pinned_quality=self._job_quality(qid)" in call, call


def test_the_skip_rank_follows_the_jobs_quality_not_the_setting():
    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace(tidal_quality_audio="HIGH")))
    rank = backend.WavesBridge._target_quality_rank.__get__(stub, type(stub))
    assert rank() == rank("HIGH")
    assert rank("HI_RES_LOSSLESS") > rank(), "a job queued higher must still count as an upgrade"


# --------------------------------------------------------------------------- #
# A failed restore is not pinned over.
# --------------------------------------------------------------------------- #
class _FlakyRestoreTidal:
    """config.py's restore_normal_session, transcribed with the facts the
    switching stand-in above leaves out: it writes the LIVE setting onto the
    session, lowers the Atmos flag BEFORE re-authenticating, and when the
    re-login fails it returns False with the flag already down. So the next
    normalise early-returns without re-authenticating and the next fetch
    proceeds. The script says which re-logins succeed, in order."""

    def __init__(self, session, setting_quality, relogin_script):
        self.session = session
        self.is_atmos_session = True  # an Atmos track just went through
        self.settings = SimpleNamespace(data=SimpleNamespace(tidal_quality_audio=setting_quality))
        self._script = list(relogin_script)
        self.restores = 0

    def switch_to_atmos_session(self) -> bool:
        return True

    def restore_normal_session(self, force: bool = False) -> bool:
        self.restores += 1
        if not self.is_atmos_session and not force:
            return True
        self.session.audio_quality = tidal_quality_for_tier(QualityTier(self.settings.data.tidal_quality_audio))
        self.is_atmos_session = False
        return bool(self._script.pop(0) if self._script else True)


def _stereo_after_atmos(setting, relogin_script):
    """A job fetching a stereo track whose session is in Atmos mode (an Atmos
    track just went through), driven through the REAL engine resolver, so the
    engine's own restore really runs. Settings has moved past the job's rung:
    the job is queued at HI-RES while the setting now says HIGH."""
    session = _Session(ATMOS_REQUEST_QUALITY)
    tidal = _FlakyRestoreTidal(session, setting, relogin_script)
    dl = _engine(tidal, session, data=_Data("both"))
    return dl, _media(session), tidal


def _fetch_stereo(dl, media):
    return dl._get_track_stream_info(media, QualityTier.HI_RES_LOSSLESS, "stereo")


def test_a_stereo_track_after_atmos_is_fetched_at_the_pin_when_the_restore_works():
    dl, media, _tidal = _stereo_after_atmos("HIGH", [True])
    info = _fetch_stereo(dl, media)
    assert info.media_stream is not None
    assert dl.session.asked == [Quality.hi_res_lossless]


def test_a_failed_restore_never_fetches_at_the_live_setting_over_the_pin():
    """The job was queued at HI-RES; Settings has since moved to HIGH. The
    engine's restore fails on a network flap. The rung is only applied AFTER a
    successful restore, so nothing is fetched at today's setting: the track is
    answered the way the engine answers the same failure, no stream, which
    item() counts as a failed track that a retry picks up. One track retried
    beats one track written at the wrong quality with nothing to say so."""
    dl, media, _tidal = _stereo_after_atmos("HIGH", [False, True])
    info = _fetch_stereo(dl, media)
    assert dl.session.asked == [], "a stream was fetched at all after a failed restore"
    assert info.media_stream is None and info.stream_manifest is None, "the engine's own answer to this failure"


def test_a_failed_restore_leaves_the_session_for_the_next_track_to_recover():
    """The next stereo track's restore is a fresh attempt: nothing here holds
    the session in a state that makes recovery impossible."""
    dl, media, _tidal = _stereo_after_atmos("HIGH", [False, True])
    first = _fetch_stereo(dl, media)
    second = _fetch_stereo(dl, media)
    assert first.media_stream is None
    assert second.media_stream is not None
    assert dl.session.asked == [Quality.hi_res_lossless]

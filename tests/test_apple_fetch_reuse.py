"""E11 reuse: one verified probe, one gamdl stack and one event loop per job.

The engine's fetch session keeps a job's cookies/wrapper stack and event
loop alive; the provider opens that session through ``fetch_job_session``
and carries the engine's verified probe on the delivery so the runner does
not verify or probe the same bytes again. These tests count the
constructions and subprocess calls rather than assert on source spelling.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from waves.constants import QualityTier
from waves.providers.apple import AppleProvider, engine, runner
from waves.providers.base import AudioType


def _song_resource(song_id="song-1", traits=("lossless",)):
    return {
        "id": song_id,
        "type": "songs",
        "attributes": {
            "name": "Xtal",
            "artistName": "Aphex Twin",
            "albumName": "Selected Ambient Works 85-92",
            "url": "https://music.apple.com/us/album/x/album-1?i=song-1",
            "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
            "durationInMillis": 293000,
            "trackNumber": 1,
            "discNumber": 1,
            "audioTraits": list(traits),
            "isrc": "GBAAA9200001",
        },
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def _client():
    class _Client:
        def __init__(self):
            self.closed = 0

        async def aclose(self):
            self.closed += 1

    return _Client()


def _fakes(monkeypatch):
    """Deterministic binary/verification seams: no PATH, no subprocess."""
    monkeypatch.setattr(engine, "_require_binary", lambda name, override="": f"/fake/{name}")
    monkeypatch.setattr(engine, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(engine, "ffprobe_for", lambda ffmpeg_path="": "/fake/ffprobe")


def test_engine_session_reuses_one_cookies_stack_and_loop(tmp_path, monkeypatch):
    """One stack and loop for many tracks; one probe + decode per track."""
    fixture = tmp_path / "staged.m4a"
    fixture.write_bytes(b"tone")
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    _fakes(monkeypatch)

    client = _client()
    stacks, fetches, probes, decodes = [], [], [], []

    async def fake_cookies_stack(cookies_path):
        stacks.append(cookies_path)
        return SimpleNamespace(client=client), SimpleNamespace()

    async def fake_fetch(*, interface, song_downloader, song_id):
        fetches.append(song_id)
        return fixture, "aac"

    monkeypatch.setattr(engine, "_create_cookies_stack", fake_cookies_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fake_fetch)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": probes.append(str(path)) or {"codec": "aac", "sample_rate": "44100"},
    )
    monkeypatch.setattr(engine, "decode_check", lambda staged, ffmpeg_path="": decodes.append(str(staged)))

    session = engine.AppleFetchSession(cookies_path=str(cookies), ffmpeg_path="/fake/ffmpeg")
    loop = session._loop
    try:
        first = session.download_song(song_id="song-1", atmos=False)
        second = session.download_song(song_id="song-2", atmos=False)
        assert not loop.is_closed(), "the loop stays open across the job"
    finally:
        session.close()

    assert stacks == [str(cookies)], "one cookie API parse per session"
    assert fetches == ["song-1", "song-2"]
    assert session._loop is loop and loop.is_closed(), "close retires the one loop"
    assert first.verified is True and second.verified is True
    assert first.probe["codec"] == "aac" and second.probe["sample_rate"] == "44100"
    assert probes == [str(fixture), str(fixture)], "one verification probe per track"
    assert decodes == [str(fixture), str(fixture)], "one decode per track"
    assert first.workdir != second.workdir, "workdirs stay per track"
    assert client.closed == 1, "the shared client closes once, at session end"
    engine.cleanup_delivery(first)
    engine.cleanup_delivery(second)


def test_engine_session_reuses_one_wrapper_client_across_alac_tracks(tmp_path, monkeypatch):
    """The wrapper guest session and its API client are built once per job."""
    fixture = tmp_path / "staged-alac.m4a"
    fixture.write_bytes(b"alac")
    _fakes(monkeypatch)

    wrapper_client = _client()
    alpha_client = _client()
    builds, fetches, probes = [], [], []

    async def fake_wrapper_stack(*, base_url, decrypt_host, decrypt_port):
        builds.append(base_url)
        return (
            SimpleNamespace(client=wrapper_client),
            SimpleNamespace(client=alpha_client),
            SimpleNamespace(),
        )

    async def fake_fetch(*, interface, song_downloader, song_id):
        fetches.append(song_id)
        return fixture, "alac"

    monkeypatch.setattr(engine, "_create_wrapper_stack", fake_wrapper_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fake_fetch)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": probes.append(str(path))
        or {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )
    monkeypatch.setattr(engine, "decode_check", lambda staged, ffmpeg_path="": None)

    session = engine.AppleFetchSession(wrapper_url="http://127.0.0.1:51234/", ffmpeg_path="/fake/ffmpeg")
    loop = session._loop
    try:
        first = session.download_alac(song_id="song-1", max_tier=QualityTier.HI_RES_LOSSLESS.value)
        second = session.download_alac(song_id="song-2", max_tier=QualityTier.LOSSLESS.value)
    finally:
        session.close()

    assert builds == ["http://127.0.0.1:51234"], "one guest session per job"
    assert fetches == ["song-1", "song-2"]
    assert session._loop is loop and loop.is_closed()
    assert first.verified is True and second.verified is True
    assert probes == [str(fixture), str(fixture)]
    assert wrapper_client.closed == 1 and alpha_client.closed == 1
    for delivery in (first, second):
        engine.cleanup_delivery(delivery)


def test_provider_scope_reuses_one_stack_and_carries_the_probe(tmp_path, monkeypatch):
    """Three tracks through one scope: one session, one probe read each."""
    provider = AppleProvider(catalog=None)
    provider.cookies_path = str(tmp_path / "cookies.txt")
    (tmp_path / "cookies.txt").write_text("# Netscape\n")
    instances = []

    class _Session:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.downloads = []
            self.closed = 0
            instances.append(self)

        def download_song(self, *, song_id, atmos):
            self.downloads.append(song_id)
            return SimpleNamespace(
                staged_path=Path("/nonexistent") / f"{song_id}.m4a",
                workdir=Path("/nonexistent"),
                is_atmos=False,
                codec="mp4a.40.2",
                probe={"codec": "aac", "sample_rate": "44100", "bit_depth": None},
                verified=True,
            )

        def download_alac(self, *, song_id, max_tier=""):
            raise AssertionError("wrapper path not used for an AAC ask")

        def close(self):
            self.closed += 1

    monkeypatch.setattr(engine, "AppleFetchSession", _Session)
    monkeypatch.setattr(
        provider,
        "_probe_sample_rate",
        lambda staged_path: pytest.fail("the provider must reuse the carried probe"),
    )

    with provider.fetch_job_session():
        infos = [
            provider.resolve_stream(_song_resource(f"song-{n}"), QualityTier.HIGH, AudioType.STEREO) for n in (1, 2, 3)
        ]

    assert len(instances) == 1, "one stack for the whole job"
    session = instances[0]
    assert session.downloads == ["song-1", "song-2", "song-3"]
    assert session.closed == 1, "the scope closes the stack"
    assert session.kwargs["cookies_path"] == provider.cookies_path
    assert all(info.delivered["probe"]["codec"] == "aac" for info in infos)
    assert [info.delivered["sample_rate"] for info in infos] == [44100, 44100, 44100]


def test_provider_rebuilds_the_stack_after_a_credential_failure(tmp_path, monkeypatch):
    """A stale export drops the stack; the retry builds a fresh one."""
    provider = AppleProvider(catalog=None)
    provider.cookies_path = str(tmp_path / "cookies.txt")
    (tmp_path / "cookies.txt").write_text("# Netscape\n")
    instances = []

    class _FlakySession:
        def __init__(self, **kwargs):
            self.closed = 0
            self.calls = 0
            instances.append(self)

        def download_song(self, *, song_id, atmos):
            self.calls += 1
            if len(instances) == 1:
                raise engine.AppleCredentialsError("The cookies export is not signed in")
            return SimpleNamespace(
                staged_path=Path("/nonexistent") / f"{song_id}.m4a",
                workdir=Path("/nonexistent"),
                is_atmos=False,
                codec="mp4a.40.2",
                probe={},
                verified=False,
            )

        def download_alac(self, *, song_id, max_tier=""):
            raise AssertionError("wrapper path not used")

        def close(self):
            self.closed += 1

    monkeypatch.setattr(engine, "AppleFetchSession", _FlakySession)
    monkeypatch.setattr(provider, "_probe_sample_rate", lambda staged_path: None)

    with provider.fetch_job_session():
        with pytest.raises(engine.AppleCredentialsError):
            provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.STEREO)
        info = provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.STEREO)

    assert len(instances) == 2, "the retry rebuilds the stack"
    assert instances[0].closed == 1, "the stale stack is retired at the failure"
    assert instances[1].closed == 1, "and the fresh one closes at job end"
    assert info.delivered["tier"] == QualityTier.HIGH.value


def test_provider_rebuilds_the_stack_after_a_wrapper_outage(tmp_path, monkeypatch):
    """A dead guest drops the stack; the retry opens a fresh guest session."""
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    instances = []

    class _DeadSession:
        def __init__(self, **kwargs):
            self.closed = 0
            instances.append(self)

        def download_song(self, *, song_id, atmos):
            raise AssertionError("cookies path not used")

        def download_alac(self, *, song_id, max_tier=""):
            if len(instances) == 1:
                raise engine.AppleWrapperDown("Apple wrapper is unreachable at http://127.0.0.1:51234")
            return SimpleNamespace(
                staged_path=Path("/nonexistent") / f"{song_id}.m4a",
                workdir=Path("/nonexistent"),
                is_atmos=False,
                codec="alac",
                probe={},
                verified=False,
            )

        def close(self):
            self.closed += 1

    monkeypatch.setattr(engine, "AppleFetchSession", _DeadSession)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )

    with provider.fetch_job_session():
        with pytest.raises(engine.AppleWrapperDown):
            provider.resolve_stream(_song_resource(), QualityTier.LOSSLESS, AudioType.STEREO)
        info = provider.resolve_stream(_song_resource(), QualityTier.LOSSLESS, AudioType.STEREO)

    assert len(instances) == 2, "the retry opens a fresh guest session"
    assert instances[0].closed == 1, "the dead session is retired"
    assert instances[1].closed == 1
    assert info.delivered["tier"] == QualityTier.LOSSLESS.value


def test_provider_fetches_one_shot_outside_a_job_scope(tmp_path, monkeypatch):
    """No scope: the provider keeps the per-fetch engine entry, unchanged."""
    provider = AppleProvider(catalog=None)
    provider.cookies_path = str(tmp_path / "cookies.txt")
    (tmp_path / "cookies.txt").write_text("# Netscape\n")
    calls = []

    monkeypatch.setattr(
        engine,
        "download_song_file",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(
            staged_path=tmp_path / "staged.m4a",
            workdir=tmp_path,
            is_atmos=False,
            codec="",
            probe={},
            verified=False,
        ),
    )
    monkeypatch.setattr(
        engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )

    provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.STEREO)

    assert len(calls) == 1 and calls[0]["song_id"] == "song-1"
    assert provider._fetch_stack is None


def test_carried_probe_still_rejects_the_wrong_codec_family(tmp_path):
    """The carried probe skips the subprocesses, never the family check."""
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"tone-bytes")
    hooks = runner.AppleJobHooks()

    with pytest.raises(engine.AppleIntegrityError):
        runner.verify_staged(
            hooks,
            staged,
            expect_atmos=True,
            verified_probe={"codec": "aac", "sample_rate": "44100"},
        )
    with pytest.raises(engine.AppleIntegrityError):
        runner.verify_staged(
            hooks,
            staged,
            expect_atmos=False,
            verified_probe={"codec": "eac3", "sample_rate": "48000"},
        )
    # The matching families pass, normalization included.
    runner.verify_staged(hooks, staged, expect_atmos=False, verified_probe={"codec": "ALAC"})
    runner.verify_staged(hooks, staged, expect_atmos=True, verified_probe={"codec": "e-ac-3"})


def test_wrapper_connection_death_mid_session_is_held_not_failed(tmp_path, monkeypatch):
    """A guest client that outlived its sidecar holds the row, never fails it."""
    fixture = tmp_path / "staged-alac.m4a"
    fixture.write_bytes(b"alac")
    _fakes(monkeypatch)
    calls = []

    async def fake_wrapper_stack(*, base_url, decrypt_host, decrypt_port):
        return SimpleNamespace(client=_client()), SimpleNamespace(client=_client()), SimpleNamespace()

    async def fake_fetch(*, interface, song_downloader, song_id):
        calls.append(song_id)
        if len(calls) > 1:
            raise RuntimeError("All connection attempts failed")
        return fixture, "alac"

    monkeypatch.setattr(engine, "_create_wrapper_stack", fake_wrapper_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fake_fetch)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )
    monkeypatch.setattr(engine, "decode_check", lambda staged, ffmpeg_path="": None)

    session = engine.AppleFetchSession(wrapper_url="http://127.0.0.1:51234", ffmpeg_path="/fake/ffmpeg")
    try:
        first = session.download_alac(song_id="song-1", max_tier="")
        with pytest.raises(engine.AppleWrapperDown):
            session.download_alac(song_id="song-2", max_tier="")
    finally:
        session.close()
    engine.cleanup_delivery(first)


def test_wrapper_delivery_reuses_the_carried_verified_probe(tmp_path, monkeypatch):
    """A verified ALAC delivery answers the honest tier without a re-probe."""
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"alac")

    monkeypatch.setattr(
        engine,
        "download_song_alac_file",
        lambda **kwargs: SimpleNamespace(
            staged_path=staged,
            workdir=tmp_path,
            is_atmos=False,
            codec="alac",
            probe={"codec": "alac", "sample_rate": "96000", "bit_depth": 24},
            verified=True,
        ),
    )
    monkeypatch.setattr(engine, "probe_audio_file", lambda path, ffprobe_path="": pytest.fail("re-probed"))

    info = provider.resolve_stream(
        _song_resource(traits=("hi-res-lossless",)), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO
    )

    assert info.delivered["tier"] == QualityTier.HI_RES_LOSSLESS.value
    assert info.delivered["bit_depth"] == 24
    assert info.delivered["sample_rate"] == 96000
    assert info.delivered["probe"]["codec"] == "alac"
    provider.discard_delivery(str(staged))


# ---------------------------------------------------------------------------
# End-to-end counts through the real runner, provider and session
# ---------------------------------------------------------------------------


class _CountingSession(engine.AppleFetchSession):
    """The real session with a construction counter."""

    built = 0

    def __init__(self, **kwargs):
        type(self).built += 1
        super().__init__(**kwargs)


def _album_song(song_id: str) -> dict:
    raw = _song_resource(song_id)
    raw["attributes"]["name"] = f"Track {song_id[-1]}"
    raw["attributes"]["trackNumber"] = int(song_id[-1])
    return raw


def _album_row(song_id: str) -> dict:
    return {
        "id": f"apple:{song_id}",
        "title": f"Track {song_id[-1]}",
        "artist": "Aphex Twin",
        "artist_id": "apple:artist-1",
        "artists": [],
        "album": "Selected Ambient Works 85-92",
        "album_id": "apple:album-1",
        "num": int(song_id[-1]),
        "vol": 1,
        "art": "",
        "year": "1992",
        "date": "1992-02-12",
        "duration": "4:53",
        "duration_sec": 293,
        "quality": "HIGH",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }


class _AlbumProvider(AppleProvider):
    """The real provider with three stubbed catalog reads."""

    def row_for(self, kind, item):
        if kind == "track":
            return _album_row(str(item.get("id")).removeprefix("apple:"))
        return {
            "id": "apple:album-1",
            "title": "Selected Ambient Works 85-92",
            "artist": "Aphex Twin",
            "artist_id": "apple:artist-1",
            "artists": [],
            "art": "",
            "year": "1992",
            "date": "1992-02-12",
            "tracks": 3,
            "duration_sec": 293,
            "quality": "HIGH",
            "popularity": -1,
            "explicit": False,
            "added": "",
        }

    def collection_items(self, obj, include_videos=True):
        return [_album_row(f"song-{n}") for n in (1, 2, 3)]

    def get_object(self, kind, raw_id):
        return _album_song(str(raw_id).removeprefix("apple:"))


def _album_hooks(provider, base: Path, *, pinned=QualityTier.HIGH, extract_flac=False):
    data = SimpleNamespace(
        download_base_path=str(base),
        skip_existing=True,
        extract_flac=extract_flac,
        extract_flac_all=False,
        playlist_create=False,
        apple_quality_audio=pinned.value,
        default_audio_type="stereo",
        mark_explicit=False,
        metadata_target_upc="UPC",
        path_binary_ffmpeg="/fake/ffmpeg",
        format_album="{artist_name}/{album_title}/{track_title}",
        album_track_num_pad_min=1,
        filename_delimiter_artist=", ",
        filename_delimiter_album_artist=", ",
        filename_illegal_replacement="",
        filename_illegal_map=None,
    )
    cover_off = {"metadata_cover_embed": False, "cover_album_file": False, "cover_single_track_file": False}
    return runner.AppleJobHooks(
        provider=lambda: provider,
        settings=lambda: SimpleNamespace(data=data),
        psetting=lambda provider_id, key, default=None: cover_off.get(key, default),
        ownership=lambda: None,
        job_quality=lambda qid: pinned,
        status=lambda text: None,
    )


def _run_album(provider, base: Path, *, pinned=QualityTier.HIGH, extract_flac=False):
    spec = SimpleNamespace(
        kind="album",
        collection=True,
        media_id="apple:album-1",
        is_retry=False,
        file_template="{artist_name}/{album_title}/{track_title}",
    )
    runner.run_job_body(
        _album_hooks(provider, base, pinned=pinned, extract_flac=extract_flac),
        1,
        spec,
        _album_song("song-1"),
        signals=SimpleNamespace(
            track_event=SimpleNamespace(emit=lambda *a: None),
            item=SimpleNamespace(emit=lambda *a: None),
            list_item=SimpleNamespace(emit=lambda *a: None),
        ),
        job_abort=Event(),
        row_ask=None,
        name="Selected Ambient Works 85-92",
    )


def test_cookies_album_end_to_end_one_stack_one_probe_per_track(tmp_path, monkeypatch):
    """The app's worker path: three tracks, one gamdl stack, one probe each."""
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    fixtures = {}
    for n in (1, 2, 3):
        fixture = tmp_path / f"song-{n}.m4a"
        fixture.write_bytes(b"tone")
        fixtures[f"song-{n}"] = fixture
    _fakes(monkeypatch)

    stack_builds, fetched, probes, decodes = [], [], [], []

    async def fake_cookies_stack(cookies_path):
        stack_builds.append(cookies_path)
        return SimpleNamespace(client=_client()), SimpleNamespace()

    async def fake_fetch(*, interface, song_downloader, song_id):
        fetched.append(song_id)
        return fixtures[song_id], "aac"

    monkeypatch.setattr(engine, "_create_cookies_stack", fake_cookies_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fake_fetch)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": probes.append(str(path)) or {"codec": "aac", "sample_rate": "44100"},
    )
    monkeypatch.setattr(engine, "decode_check", lambda staged, ffmpeg_path="": decodes.append(str(staged)))
    _CountingSession.built = 0
    monkeypatch.setattr(engine, "AppleFetchSession", _CountingSession)
    provider = _AlbumProvider(catalog=None)
    provider.cookies_path = str(cookies)

    _run_album(provider, tmp_path / "lib")

    assert _CountingSession.built == 1, "one engine session for the whole album"
    assert stack_builds == [str(cookies)], "one cookie API parse per album"
    assert fetched == ["song-1", "song-2", "song-3"]
    assert probes == [str(fixtures[f"song-{n}"]) for n in (1, 2, 3)]
    assert decodes == [str(fixtures[f"song-{n}"]) for n in (1, 2, 3)]
    landed = sorted(path.name for path in (tmp_path / "lib").rglob("*.m4a"))
    assert landed == ["Track 1.m4a", "Track 2.m4a", "Track 3.m4a"]


def test_wrapper_album_end_to_end_one_stack_one_probe_per_track(tmp_path, monkeypatch):
    """The wrapper tier through the same path: one guest session, one probe each."""
    fixtures = {}
    for n in (1, 2, 3):
        fixture = tmp_path / f"song-{n}-alac.m4a"
        fixture.write_bytes(b"alac")
        fixtures[f"song-{n}"] = fixture
    _fakes(monkeypatch)
    monkeypatch.setattr(runner, "ensure_sidecar", lambda hooks, qid, job_abort, *, need_wrapper: True)

    stack_builds, fetched, probes, decodes = [], [], [], []

    async def fake_wrapper_stack(*, base_url, decrypt_host, decrypt_port):
        stack_builds.append(base_url)
        return SimpleNamespace(client=_client()), SimpleNamespace(client=_client()), SimpleNamespace()

    async def fake_fetch(*, interface, song_downloader, song_id):
        fetched.append(song_id)
        return fixtures[song_id], "alac"

    monkeypatch.setattr(engine, "_create_wrapper_stack", fake_wrapper_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fake_fetch)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": probes.append(str(path))
        or {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )
    monkeypatch.setattr(engine, "decode_check", lambda staged, ffmpeg_path="": decodes.append(str(staged)))
    _CountingSession.built = 0
    monkeypatch.setattr(engine, "AppleFetchSession", _CountingSession)
    provider = _AlbumProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"

    _run_album(provider, tmp_path / "lib", pinned=QualityTier.HI_RES_LOSSLESS)

    assert _CountingSession.built == 1, "one engine session for the whole album"
    assert stack_builds == ["http://127.0.0.1:51234"], "one guest session per album"
    assert fetched == ["song-1", "song-2", "song-3"]
    assert probes == [str(fixtures[f"song-{n}"]) for n in (1, 2, 3)]
    assert decodes == [str(fixtures[f"song-{n}"]) for n in (1, 2, 3)]
    landed = sorted(path.name for path in (tmp_path / "lib").rglob("*.m4a"))
    assert landed == ["Track 1.m4a", "Track 2.m4a", "Track 3.m4a"]

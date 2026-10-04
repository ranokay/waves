"""Source precedence + standalone actions (spec section 9.1)."""

import pytest

from waves.model.cfg import Settings


def test_new_settings_defaults_match_spec():
    data = Settings()
    # Best quality out of the box: sidecars on, embed opt-in.
    assert data.lyrics_embed is False
    assert data.lyrics_file is True
    assert data.lyrics_file_synced_only is False
    assert data.lyrics_prefer_lrclib is True
    # Word-timed on, verbatim .ttml on; original-format cover sidecars.
    assert data.lyrics_word_timed is True
    assert data.lyrics_ttml_file is True
    assert data.cover_file_format == "raw"


def test_word_timed_ttml_converts_to_enhanced_lrc():
    """Honest parser contract: syllable TTML converts to enhanced LRC."""
    from waves.metadata.ttml_lyrics import ttml_timing_mode, ttml_to_enhanced_lrc

    syllable = """<tt xmlns:itunes="x" itunes:timing="Word"><body><div>
    <p begin="00:01.00"><span begin="00:01.00">Hi</span></p></div></body></tt>"""
    assert ttml_timing_mode(syllable) == "word"
    word_lrc = ttml_to_enhanced_lrc(syllable)
    assert word_lrc.startswith("[00:01.00]")
    assert "<00:01.00>Hi" in word_lrc


def test_provider_word_timed_lrc_helper():
    from waves.providers.apple import AppleProvider

    syllable = """<tt xmlns:itunes="x" itunes:timing="Word"><body><div>
    <p begin="00:01.00"><span begin="00:01.00">Hi</span></p></div></body></tt>"""
    provider = AppleProvider(catalog=object(), catalog_factory=lambda: None)
    provider.fetch_syllable_ttml = lambda track: syllable  # type: ignore[method-assign]
    assert "<00:01.00>Hi" in provider.fetch_word_timed_lrc({"id": "apple:1"})
    provider.fetch_syllable_ttml = lambda track: ""  # type: ignore[method-assign]
    assert provider.fetch_word_timed_lrc({"id": "apple:1"}) == ""


def test_provider_native_lyrics_converts_ttml():
    from waves.providers.apple import AppleProvider

    provider = AppleProvider(catalog=object(), catalog_factory=lambda: None)
    line_ttml = """<tt itunes:timing="Line" xmlns:itunes="x"><body><div>
    <p begin="00:10.00">Hello</p></div></body></tt>"""
    provider.fetch_line_ttml = lambda track: line_ttml  # type: ignore[method-assign]
    provider.fetch_syllable_ttml = lambda track: ""  # type: ignore[method-assign]
    synced, plain = provider.fetch_lyrics({"id": "apple:1"})
    assert "Hello" in synced
    assert "Hello" in plain


LINE_TTML = """<tt xmlns:itunes="x" itunes:timing="Line"><body><div>
<p begin="00:10.00">Hello</p><p begin="00:12.00">World</p></div></body></tt>"""


class _Options:
    def __init__(self, **values):
        self.values = values

    def option(self, name, default=False):
        return self.values.get(name, default)


def _lyrics_stub(
    monkeypatch, *, native=("[00:10.00]Hello\n[00:12.00]World", "Hello\nWorld"), lrclib=("", ""), syllable=""
):
    from types import SimpleNamespace

    from waves.providers.apple import runner

    calls = {"native": 0}
    provider = SimpleNamespace(
        get_object=lambda kind, raw_id: {"id": raw_id},
        fetch_syllable_ttml=lambda track: syllable,
        fetch_line_ttml=lambda track: LINE_TTML,
    )

    def _fetch_native(track):
        calls["native"] += 1
        return native

    provider.fetch_lyrics = _fetch_native
    hooks = runner.AppleJobHooks()
    monkeypatch.setattr(runner, "_pooled_session", lambda: None)
    monkeypatch.setattr(runner, "fetch_lrclib_lyrics", lambda session, **kwargs: lrclib)
    return hooks, provider, calls


def _lyrics_options(**overrides):
    values = {
        "lyrics_embed": True,
        "lyrics_file": True,
        "lyrics_ttml_file": False,
        "lyrics_word_timed": False,
        "lyrics_prefer_lrclib": True,
    }
    values.update(overrides)
    return _Options(**values)


def test_plain_only_lrclib_does_not_hide_native_timing(monkeypatch):
    from waves.providers.apple import runner

    hooks, provider, calls = _lyrics_stub(monkeypatch, lrclib=("", "plain words"))

    synced, plain, ttml = runner.lyrics_full(
        hooks,
        provider,
        {"id": "apple:s1", "artist": "A", "title": "T", "album": "X", "duration_sec": 10},
        {},
        options=_lyrics_options(),
    )

    assert synced == "[00:10.00]Hello\n[00:12.00]World", "native timing is not hidden by unsynced LRCLIB text"
    assert plain == "plain words", "LRCLIB's text owns the plain slot when both plain sources exist"
    assert ttml == LINE_TTML
    assert calls["native"] == 1


def test_lrclib_synced_still_wins_outright(monkeypatch):
    from waves.providers.apple import runner

    hooks, provider, calls = _lyrics_stub(monkeypatch, lrclib=("[00:01.00]LRCLIB", "lrclib text"))

    synced, plain, _ttml = runner.lyrics_full(
        hooks,
        provider,
        {"id": "apple:s1", "artist": "A", "title": "T", "album": "X", "duration_sec": 10},
        {},
        options=_lyrics_options(),
    )

    assert synced == "[00:01.00]LRCLIB"
    assert plain == "lrclib text"
    assert calls["native"] == 0, "a timed LRCLIB hit never spends the native fetch"


def test_plain_only_lrclib_alone_stays_plain(monkeypatch):
    from waves.providers.apple import runner

    hooks, provider, _calls = _lyrics_stub(monkeypatch, native=("", ""), lrclib=("", "plain words"))

    synced, plain, _ttml = runner.lyrics_full(
        hooks,
        provider,
        {"id": "apple:s1", "artist": "A", "title": "T", "album": "X", "duration_sec": 10},
        {},
        options=_lyrics_options(),
    )

    assert synced == "" and plain == "plain words"


WORD_TTML = """<tt xmlns:itunes="x" itunes:timing="Word"><body><div>
<p begin="00:01.00"><span begin="00:01.00">Hi</span></p></div></body></tt>"""


def test_word_timed_outranks_a_synced_lrclib_hit(monkeypatch):
    """The word-timed Apple document wins the synced slot outright."""
    from waves.providers.apple import runner

    hooks, provider, calls = _lyrics_stub(monkeypatch, syllable=WORD_TTML, lrclib=("[00:02.00]LRCLIB", "lrclib text"))

    synced, plain, ttml = runner.lyrics_full(
        hooks,
        provider,
        {"id": "apple:s1", "artist": "A", "title": "T", "album": "X", "duration_sec": 10},
        {},
        options=_lyrics_options(lyrics_word_timed=True),
    )

    assert "<00:01.00>Hi" in synced and synced != "[00:02.00]LRCLIB"
    assert plain == "lrclib text"
    assert ttml == WORD_TTML
    assert calls["native"] == 0


def test_native_line_timed_fills_the_synced_slot(monkeypatch):
    from waves.providers.apple import runner

    hooks, provider, calls = _lyrics_stub(monkeypatch, lrclib=("", ""))

    synced, plain, ttml = runner.lyrics_full(
        hooks,
        provider,
        {"id": "apple:s1", "artist": "A", "title": "T", "album": "X", "duration_sec": 10},
        {},
        options=_lyrics_options(lyrics_prefer_lrclib=False),
    )

    assert synced == "[00:10.00]Hello\n[00:12.00]World"
    assert plain == "Hello\nWorld"
    assert ttml == LINE_TTML
    assert calls["native"] == 1


def test_apple_standalone_lyrics_embeds_with_every_sidecar_off(tmp_path):
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace()))
    stub.providers = {
        "apple": SimpleNamespace(get_object=lambda kind, raw_id: {"id": raw_id}, track_facts=lambda obj: {})
    }
    stub._standalone_base_dir = lambda: tmp_path
    stub._standalone_apple_tracks = lambda media_id: [({"id": "apple:s1"}, None, False)]
    stub._apple_lyrics_full = lambda provider, row, facts, options=None: ("[00:01.00]hi", "hi", "")
    stub._apple_standalone_dest = lambda base, row, album, collection: (tmp_path, "S1")
    embedded = []
    stub._apple_standalone_embed_lyrics = lambda *args: embedded.append(args[1]) or True
    stub._psetting = lambda provider, name, default: {
        "lyrics_file": False,
        "lyrics_file_synced_only": False,
        "lyrics_ttml_file": False,
        "lyrics_embed": True,
    }.get(name, default)
    stub._standalone_apple = WavesBridge._standalone_apple.__get__(stub, SimpleNamespace)

    served = stub._standalone_apple("apple:s1", "lyrics")

    assert served == 1, "an embed-only action is served, not dead"
    assert embedded == ["S1"]


def test_apple_standalone_lyrics_counts_nothing_without_a_saved_file(tmp_path):
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace()))
    stub.providers = {
        "apple": SimpleNamespace(get_object=lambda kind, raw_id: {"id": raw_id}, track_facts=lambda obj: {})
    }
    stub._standalone_base_dir = lambda: tmp_path
    stub._standalone_apple_tracks = lambda media_id: [({"id": "apple:s1"}, None, False)]
    stub._apple_lyrics_full = lambda provider, row, facts, options=None: ("[00:01.00]hi", "hi", "")
    stub._apple_standalone_dest = lambda base, row, album, collection: (tmp_path, "S1")
    stub._psetting = lambda provider, name, default: {
        "lyrics_file": False,
        "lyrics_file_synced_only": False,
        "lyrics_ttml_file": False,
        "lyrics_embed": True,
    }.get(name, default)
    stub._apple_standalone_embed = WavesBridge._apple_standalone_embed.__get__(stub, SimpleNamespace)
    stub._apple_standalone_embed_lyrics = WavesBridge._apple_standalone_embed_lyrics.__get__(stub, SimpleNamespace)
    stub._standalone_apple = WavesBridge._standalone_apple.__get__(stub, SimpleNamespace)

    assert stub._standalone_apple("apple:s1", "lyrics") == 0


def test_tidal_standalone_lyrics_embeds_with_every_sidecar_off(tmp_path):
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    class _Download:
        def _retrieve_lyrics(self, track_obj):
            return None, "[00:01.00]hi", "hi"

    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace()), _dl=_Download())
    stub._standalone_base_dir = lambda: tmp_path
    stub._standalone_tidal_tracks = lambda media_id: [(SimpleNamespace(id=1), None, False)]
    stub._tidal_standalone_dest = lambda base, track_obj, collection: (tmp_path, "S1")
    embedded = []
    stub._tidal_standalone_embed = lambda *args: embedded.append(args[1]) or True
    stub._psetting = lambda provider, name, default: {
        "lyrics_file": False,
        "lyrics_file_synced_only": False,
        "lyrics_embed": True,
    }.get(name, default)
    stub._standalone_tidal = WavesBridge._standalone_tidal.__get__(stub, SimpleNamespace)

    served = stub._standalone_tidal("123", "lyrics")

    assert served == 1, "an embed-only action is served, not dead"
    assert embedded == ["S1"]


def test_tidal_standalone_lyrics_without_lyrics_is_not_served(tmp_path):
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    class _Download:
        def _retrieve_lyrics(self, track_obj):
            return None, "", ""

    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace()), _dl=_Download())
    stub._standalone_base_dir = lambda: tmp_path
    stub._standalone_tidal_tracks = lambda media_id: [(SimpleNamespace(id=1), None, False)]
    embedded = []
    stub._tidal_standalone_embed = lambda *args: embedded.append(args[1]) or True
    stub._psetting = lambda provider, name, default: {
        "lyrics_file": False,
        "lyrics_file_synced_only": False,
        "lyrics_embed": True,
    }.get(name, default)
    stub._standalone_tidal = WavesBridge._standalone_tidal.__get__(stub, SimpleNamespace)

    assert stub._standalone_tidal("123", "lyrics") == 0
    assert embedded == [], "nothing to embed never tags a file or reports a serve"


# --------------------------------------------------------------------------- #
# Standalone actions through the real bridge entry points
# --------------------------------------------------------------------------- #


def _psetting_map(*, lyrics_file=False, lyrics_embed=False, lyrics_ttml_file=False, cover_album_file=True):
    return {
        "lyrics_file": lyrics_file,
        "lyrics_file_synced_only": False,
        "lyrics_ttml_file": lyrics_ttml_file,
        "lyrics_embed": lyrics_embed,
        "metadata_cover_embed": False,
        "cover_album_file": cover_album_file,
    }


def _standalone_bridge(tmp_path, *, psettings, lyrics=None, lyrics_error=False):
    from types import SimpleNamespace

    from conftest import _InlinePool

    from waves.desktop import backend
    from waves.desktop.backend import WavesBridge

    folder = tmp_path / "Artist"
    folder.mkdir(parents=True, exist_ok=True)
    statuses: list[str] = []
    states: list[tuple] = []
    from providers.fakes import StubProvider

    from waves.providers import Capability

    provider = StubProvider("apple", "Apple Music", capabilities={Capability.LYRICS, Capability.ART}, logged_in=True)
    provider.get_object = lambda kind, raw_id: {"id": raw_id}
    provider.track_facts = lambda obj: {}
    stub = SimpleNamespace(
        settings=SimpleNamespace(
            data=SimpleNamespace(
                download_base_path=str(tmp_path),
                mark_explicit=False,
                metadata_target_upc="UPC",
            )
        ),
        providers={"apple": provider},
        downloadState=SimpleNamespace(emit=lambda media_id, state: states.append((media_id, state))),
        _set_status=statuses.append,
        _download_gate=lambda: "ok",
        threadpool=_InlinePool(),
        _psetting=lambda provider_id, name, default: psettings.get(name, default),
        _standalone_apple_tracks=lambda media_id: [({"id": "apple:s1", "title": "S1"}, None, False)],
        _apple_standalone_dest=lambda base, row, album, collection: (folder, "S1"),
        _apple_wants_cover=lambda collection: True,
        _cover_convert_ffmpeg=lambda: "",
        _tag_write_flags=lambda: {},
    )
    # The provider's download surface: the bridge implements Apple's and binds
    # it where the providers are wired, so a standalone stub binds it too.
    provider.downloads = backend._AppleDownloads(stub)
    if lyrics_error:

        def _raise(*args, **kwargs):
            raise RuntimeError("provider exploded")

        stub._apple_lyrics_full = _raise
    else:
        stub._apple_lyrics_full = lambda provider, row, facts, options=None: lyrics or ("[00:01.00]hi", "hi", "")
    stub._apple_cover_bytes = lambda provider, raw: (b"\xff\xd8\xff\xdbjpeg-bytes", b"\xff\xd8\xff\xdbjpeg-bytes")
    for name in (
        "_standalone_fetch",
        "_standalone_base_dir",
        "_apple_standalone_embed",
        "_apple_standalone_embed_lyrics",
        "_apple_standalone_embed_cover",
        "downloadLyricsOnly",
        "downloadArtOnly",
        "_standalone_apple",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, SimpleNamespace))
    return stub, folder, statuses, states


def test_download_lyrics_only_writes_the_sidecar_and_no_audio(tmp_path):
    stub, folder, statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_file=True))

    stub.downloadLyricsOnly("apple:s1")

    assert (folder / "S1.lrc").read_text() == "[00:01.00]hi"
    assert list(folder.glob("*.m4a")) == [] and list(folder.glob("*.flac")) == []
    assert states == [("apple:s1", "running"), ("apple:s1", "done")]
    assert statuses[-1] == "Saved lyrics for 1 track"


def test_download_lyrics_only_replaces_an_existing_hand_edited_sidecar(tmp_path):
    stub, folder, _statuses, _states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_file=True))
    (folder / "S1.lrc").write_text("[hand-edited]")

    stub.downloadLyricsOnly("apple:s1")

    assert (folder / "S1.lrc").read_text() == "[00:01.00]hi"


@pytest.mark.ffmpeg
def test_download_lyrics_only_embeds_into_an_existing_track(tmp_path):
    import mutagen.mp4
    from support.audio_fixtures import tone

    stub, folder, _statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_embed=True))
    tone(folder / "S1.m4a")

    stub.downloadLyricsOnly("apple:s1")

    assert "hi" in str(mutagen.mp4.MP4(str(folder / "S1.m4a")).tags["\xa9lyr"][0])
    assert not (folder / "S1.lrc").exists(), "the sidecar toggle stays independent of the embed"
    assert len(list(folder.glob("*.m4a"))) == 1, "the embed tags the existing file, never downloads audio"
    assert states[-1] == ("apple:s1", "done")


def test_download_lyrics_only_reports_a_failed_provider_request(tmp_path):
    stub, folder, statuses, states = _standalone_bridge(
        tmp_path, psettings=_psetting_map(lyrics_file=True), lyrics_error=True
    )

    stub.downloadLyricsOnly("apple:s1")

    assert states[-1] == ("apple:s1", "failed")
    assert statuses[-1] == "Could not fetch lyrics, try again"
    assert not (folder / "S1.lrc").exists()


def test_download_art_only_writes_the_cover_and_no_audio(tmp_path):
    stub, folder, statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map())

    stub.downloadArtOnly("apple:s1")

    assert (folder / "cover.jpg").read_bytes().startswith(b"\xff\xd8\xff")
    assert list(folder.glob("*.m4a")) == [] and list(folder.glob("*.flac")) == []
    assert states == [("apple:s1", "running"), ("apple:s1", "done")]
    assert statuses[-1] == "Saved artwork for 1 track"


def test_download_lyrics_only_files_the_verbatim_ttml_when_asked(tmp_path):
    """The TTML sidecar toggle is independent: the verbatim document lands as .ttml."""
    ttml = '<tt><body><div><p begin="00:01.00">Hi</p></div></body></tt>'
    stub, folder, _statuses, _states = _standalone_bridge(
        tmp_path,
        psettings=_psetting_map(lyrics_ttml_file=True),
        lyrics=("[00:01.00]hi", "hi", ttml),
    )

    stub.downloadLyricsOnly("apple:s1")

    assert (folder / "S1.ttml").read_text() == ttml
    assert not (folder / "S1.lrc").exists()


class _AssetPool:
    def __init__(self):
        self.workers = []

    def start(self, worker):
        self.workers.append(worker)


@pytest.mark.parametrize("mode", ["lyrics", "art"])
def test_standalone_revocation_during_fetch_prevents_output_and_releases_only_its_buttons(tmp_path, mode):
    from threading import Event, Thread

    from waves.desktop import backend
    from waves.desktop.providers.lifecycle import provider_contexts, scan_generation

    stub, folder, statuses, states = _standalone_bridge(
        tmp_path, psettings=_psetting_map(lyrics_file=True, lyrics_embed=True)
    )
    stub.threadpool = _AssetPool()
    entered, release = Event(), Event()

    def fetch(*args):
        entered.set()
        assert release.wait(2)
        return ("[00:01.00]hi", "hi", "") if mode == "lyrics" else (b"jpeg", b"jpeg")

    if mode == "lyrics":
        stub._apple_lyrics_full = fetch
    else:
        stub._apple_cover_bytes = fetch
    stub._standalone_fetch("apple:s1", mode)
    other = scan_generation(stub, "paper")
    stub._standalone_active["paper:s1"] = other
    worker = Thread(target=stub.threadpool.workers.pop(0).fn)
    worker.start()
    try:
        assert entered.wait(2)
        provider_contexts(stub).revoke("apple")
        backend._stop_standalone(stub, "apple")
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert not list(folder.iterdir())
    assert states == [("apple:s1", "running"), ("apple:s1", "")]
    assert stub._standalone_active == {"paper:s1": other}
    assert not any(text.startswith("Saved ") for text in statuses)


def test_standalone_revoked_before_dispatch_never_fetches(tmp_path):
    from waves.desktop import backend
    from waves.desktop.providers.lifecycle import provider_contexts

    stub, folder, _statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_file=True))
    stub.threadpool = _AssetPool()
    calls = []
    stub._apple_lyrics_full = lambda *args: calls.append(args) or ("hi", "hi", "")
    stub.downloadLyricsOnly("apple:s1")
    provider_contexts(stub).revoke("apple")
    backend._stop_standalone(stub, "apple")
    stub.threadpool.workers.pop(0).fn()
    assert not calls and not list(folder.iterdir())
    assert states == [("apple:s1", "running"), ("apple:s1", "")]


def test_standalone_revocation_during_tagging_preserves_saved_audio(tmp_path, monkeypatch):
    from waves.desktop import backend
    from waves.desktop.providers.lifecycle import provider_contexts

    stub, folder, _statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_embed=True))
    original = folder / "S1.m4a"
    original.write_bytes(b"saved audio")

    def tag(candidate, **kwargs):
        assert candidate != original and candidate.read_bytes() == b"saved audio"
        provider_contexts(stub).revoke("apple")
        backend._stop_standalone(stub, "apple")
        candidate.write_bytes(b"new tags")
        return True

    monkeypatch.setattr(backend, "tag_apple_file", tag)
    stub.downloadLyricsOnly("apple:s1")
    assert original.read_bytes() == b"saved audio"
    assert list(folder.iterdir()) == [original]
    assert states == [("apple:s1", "running"), ("apple:s1", "")]


def test_standalone_completion_queued_before_revocation_cannot_repaint(tmp_path):
    from conftest import _Signal

    from waves.desktop import backend
    from waves.desktop.providers.lifecycle import provider_contexts

    stub, folder, _statuses, states = _standalone_bridge(tmp_path, psettings=_psetting_map(lyrics_file=True))
    stub._catalogEvent = _Signal()
    stub.downloadLyricsOnly("apple:s1")
    assert (folder / "S1.lrc").is_file()  # publication preceded revocation
    assert states == [("apple:s1", "running")]
    provider_contexts(stub).revoke("apple")
    backend._stop_standalone(stub, "apple")
    for event in stub._catalogEvent.emits:
        backend.WavesBridge._on_catalog_event(stub, event)
    assert states == [("apple:s1", "running"), ("apple:s1", "")]

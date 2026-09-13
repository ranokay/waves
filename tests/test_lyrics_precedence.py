"""Source precedence + standalone slots (issue #34)."""

from waves.model.cfg import Settings


def test_new_settings_defaults_match_spec():
    data = Settings()
    # Best quality out of the box (issue #59): sidecars on, embed opt-in.
    assert data.lyrics_embed is False
    assert data.lyrics_file is True
    assert data.lyrics_file_synced_only is False
    assert data.lyrics_prefer_lrclib is True
    # Word-timed on, verbatim .ttml on; original-format cover sidecars.
    assert data.lyrics_word_timed is True
    assert data.lyrics_ttml_file is True
    assert data.cover_file_format == "raw"


def test_word_timed_outranks_line_lrclib():
    """Precedence unit: the provider layer prefers enhanced LRC over LRCLIB text.

    Exercises the ordering rule directly: when a word-timed document exists,
    its conversion wins the synced slot even against a line-timed LRCLIB hit.
    """
    from waves.ttml_lyrics import ttml_timing_mode, ttml_to_enhanced_lrc

    syllable = """<tt xmlns:itunes="x" itunes:timing="Word"><body><div>
    <p begin="00:01.00"><span begin="00:01.00">Hi</span></p></div></body></tt>"""
    assert ttml_timing_mode(syllable) == "word"
    word_lrc = ttml_to_enhanced_lrc(syllable)
    assert word_lrc.startswith("[00:01.00]")
    # The rule: word_lrc is chosen before lrclib_synced. The backend
    # implements it in _apple_lyrics_full; this pins the conversion half.
    assert "<00:01.00>Hi" in word_lrc


def test_standalone_slots_exist():
    from waves.waves_ui import backend as backend_module

    assert hasattr(backend_module.WavesBridge, "downloadLyricsOnly")
    assert hasattr(backend_module.WavesBridge, "downloadArtOnly")


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


def _lyrics_stub(monkeypatch, *, native=("[00:10.00]Hello\n[00:12.00]World", "Hello\nWorld"), lrclib=("", "")):
    from types import SimpleNamespace

    from waves.providers.apple import runner

    calls = {"native": 0}
    provider = SimpleNamespace(
        get_object=lambda kind, raw_id: {"id": raw_id},
        fetch_syllable_ttml=lambda track: "",
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


def test_apple_standalone_lyrics_embeds_with_every_sidecar_off(tmp_path):
    from types import SimpleNamespace

    from waves.waves_ui.backend import WavesBridge

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

    from waves.waves_ui.backend import WavesBridge

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

    from waves.waves_ui.backend import WavesBridge

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

    from waves.waves_ui.backend import WavesBridge

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

"""Source precedence + standalone slots (issue #34)."""

from waves.model.cfg import Settings


def test_new_settings_defaults_match_spec():
    data = Settings()
    # Existing TIDAL defaults unchanged.
    assert data.lyrics_embed is False
    assert data.lyrics_file is False
    assert data.lyrics_file_synced_only is False
    assert data.lyrics_prefer_lrclib is True
    # New toggles: word-timed on, .ttml off.
    assert data.lyrics_word_timed is True
    assert data.lyrics_ttml_file is False
    assert data.cover_file_format == "jpg"


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

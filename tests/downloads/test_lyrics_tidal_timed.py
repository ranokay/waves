"""TIDAL timed lyrics outrank a plain-only LRCLIB hit (issue #722).

LRCLIB's unsynced text is better than nothing, not a substitute for timing:
a plain-only LRCLIB hit must still ask TIDAL for timed subtitles, keep the
LRCLIB text as the untimed form, and retain it when TIDAL has nothing timed or
its request fails. A timed LRCLIB hit must never spend the TIDAL request.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import waves.download as download_mod
from waves.download import Download


def _lyrics_download(
    monkeypatch, lrclib, lyrics_source, *, prefer_lrclib: bool = True
) -> tuple[Download, SimpleNamespace]:
    """A download engine and the tidalapi Track surface it reads.

    ``lrclib`` is a (synced, plain) pair, or a callable when a case needs to
    assert whether LRCLIB was asked at all.
    """
    download = Download.__new__(Download)
    download.fn_logger = MagicMock()
    download.settings = SimpleNamespace(data=SimpleNamespace(lyrics_prefer_lrclib=prefer_lrclib))
    download._shared_http = lambda: None
    monkeypatch.setattr(
        download_mod,
        "fetch_lrclib_lyrics",
        lrclib if callable(lrclib) else lambda *_a, **_kw: lrclib,
    )
    return download, SimpleNamespace(
        artist=None,
        album=None,
        duration=0,
        name="Song",
        full_name="Song",
        artists=[],
        lyrics=lyrics_source,
    )


def test_a_plain_only_lrclib_hit_still_takes_tidals_timed_lyrics(monkeypatch):
    download, track = _lyrics_download(
        monkeypatch,
        ("", "plain from lrclib"),
        lambda: SimpleNamespace(text="tidal text", subtitles="[00:01.00] timed"),
    )

    assert download._retrieve_lyrics(track) == ("[00:01.00] timed", "[00:01.00] timed", "plain from lrclib")


def test_a_plain_only_lrclib_hit_stands_when_tidal_has_nothing_timed(monkeypatch):
    download, track = _lyrics_download(
        monkeypatch, ("", "plain from lrclib"), lambda: SimpleNamespace(text="t", subtitles="")
    )

    assert download._retrieve_lyrics(track) == ("plain from lrclib", "", "plain from lrclib")


def test_a_plain_only_lrclib_hit_stands_when_tidal_fails(monkeypatch):
    def boom():
        raise RuntimeError("404")

    download, track = _lyrics_download(monkeypatch, ("", "plain from lrclib"), boom)

    assert download._retrieve_lyrics(track) == ("plain from lrclib", "", "plain from lrclib")


def test_timed_lrclib_lyrics_never_ask_tidal(monkeypatch):
    def never():
        raise AssertionError("TIDAL was asked")

    download, track = _lyrics_download(monkeypatch, ("[00:01.00] lrclib", "plain"), never)

    assert download._retrieve_lyrics(track) == ("[00:01.00] lrclib", "[00:01.00] lrclib", "plain")


def test_preference_off_asks_tidal_directly(monkeypatch):
    def never(*_a, **_kw):
        raise AssertionError("LRCLIB was asked with the preference off")

    download, track = _lyrics_download(
        monkeypatch,
        never,
        lambda: SimpleNamespace(text="tidal text", subtitles="[00:01.00] timed"),
        prefer_lrclib=False,
    )

    assert download._retrieve_lyrics(track) == ("[00:01.00] timed", "[00:01.00] timed", "tidal text")

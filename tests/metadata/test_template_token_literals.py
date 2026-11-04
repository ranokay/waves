"""A literal {token} inside a media name stays literal.

WHAT THIS FENCES OFF
--------------------
``format_path_media`` walks the matches of the template and turns each one into
a global ``result.replace``. A substituted value that itself contains a known
token was therefore re-read by the later replacements: a track named "Ode to
{artist_name}" rendered "Ode to Willie Nelson - Willie Nelson", and a playlist
named "Best of {artist_name}" scattered one folder per artist on the second
pass a collection's baked-in template goes through. The folder-path sanitizer
already rewrote braces in a folder name; ordinary media values did not.

HOW IT HOLDS
------------
Every substituted value is sanitized, then any known ``{token}`` left in it is
written as ``(token)``, the spelling folder names already use, before the next
replacement runs. Neutralizing AFTER sanitization also catches a token that only
forms once an illegal character is stripped (``{artist:_name}`` reads
``{artist_name}`` after the colon goes). Braces that are not a known token --
``{Live}``, ``{ Live }``, ``{not_a_token}`` -- are left byte-for-byte, so a
library that never held one keeps the spelling it has on disk.

The known-token set is every name ``format_str_media`` resolves for some media
type, so the guard at the bottom compares it against the formatter's own
vocabulary: a token added to a ``_format_*`` function without the set fails.

The formatter's lookups are isinstance-gated, so the fixtures are real
``tidalapi`` objects (``__new__`` plus the attributes the lookups read), never
SimpleNamespace stand-ins that would resolve nothing and pass on their own.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from tidalapi import Album, Mix, Playlist, Track, Video

import waves.download as download_module
import waves.paths as paths
from waves.constants import MediaType
from waves.download import Download
from waves.paths import format_path_media, format_str_media

_EXPECTED_PLAYLIST_TEMPLATE = "Playlists/{playlist_name}/{artist_name} - {track_title}"


def _artist() -> SimpleNamespace:
    return SimpleNamespace(name="Willie Nelson", id=99, roles=None)


def _album(artist: SimpleNamespace) -> Album:
    album = Album.__new__(Album)
    album.id = 10
    album.name = "Red Headed Stranger"
    album.artists = [artist]
    album.artist = artist
    album.num_tracks = 1
    album.num_volumes = 1
    album.explicit = False
    album.release_date = datetime(1975, 5, 1)
    album.type = "ALBUM"
    album.duration = 2550
    return album


def _track(title: str = "On the Road Again", artist: SimpleNamespace | None = None) -> Track:
    artist = artist or _artist()
    track = Track.__new__(Track)
    track.id = 1
    track.name = title
    track.full_name = title
    track.version = None
    track.explicit = False
    track.track_num = 1
    track.volume_num = 1
    track.duration = 150
    track.isrc = "USSM1000001"
    track.media_metadata_tags = []
    track.artists = [artist]
    track.artist = artist
    track.album = _album(artist)
    return track


def _playlist(name: str) -> Playlist:
    playlist = Playlist.__new__(Playlist)
    playlist.id = "p1"
    playlist.name = name
    playlist.duration = 3720
    return playlist


def test_a_playlist_named_like_a_token_keeps_one_folder():
    """Upstream regression: the baked folder is formatted again per track, so
    a literal token in the playlist name must already be neutralized by then."""
    playlist = _playlist("Best of {artist_name}")

    baked = format_path_media(_EXPECTED_PLAYLIST_TEMPLATE, playlist)

    assert baked.startswith("Playlists/Best of (artist_name)/")
    assert "Willie Nelson" not in baked

    out = format_path_media(baked, _track())

    assert out == "Playlists/Best of (artist_name)/Willie Nelson - On the Road Again"


def test_a_track_title_holding_a_token_is_not_expanded_by_a_later_one():
    """Upstream regression: the title's token is seen by the artist replacement
    later in the same pass."""
    track = _track("Ode to {artist_name}")

    assert format_path_media("{track_title} - {artist_name}", track) == "Ode to (artist_name) - Willie Nelson"


def test_a_value_naming_the_current_token_is_not_expanded_by_a_later_pass():
    """Neutralized output holds no braces, so a second pass over the rendered
    path cannot expand it either."""
    first = format_path_media("{track_title}", _track("{track_title}"))
    assert first == "(track_title)"

    assert format_path_media(first, _track("Something Else")) == "(track_title)"


def test_a_token_formed_by_illegal_character_removal_is_neutralized():
    """A colon is stripped from a file name, welding "{artist:_name}" into a
    known "{artist_name}": neutralization runs after sanitization to catch it."""
    out = format_path_media("{track_title}", _track("{artist:_name}"))

    assert out == "(artist_name)"
    assert "{" not in out


def test_an_unknown_brace_word_is_kept_byte_for_byte():
    assert format_path_media("{track_title}", _track("Song {Live}")) == "Song {Live}"
    assert format_path_media("{track_title}", _track("Song { Live }")) == "Song { Live }"
    assert format_path_media("{track_title}", _track("Song {not_a_token}")) == "Song {not_a_token}"
    assert format_path_media("{track_title}", _track("Song {Live} (Live)")) == "Song {Live} (Live)"


def test_a_value_that_never_held_a_token_is_byte_for_byte_unchanged():
    for title in ("Song", "Song (Live)", "Song (Live) [Remix]", "A (B) - C"):
        assert format_path_media("{track_title}", _track(title)) == title


def test_user_written_template_tokens_still_expand():
    assert format_path_media("{artist_name} - {track_title}", _track("Song {Live}")) == "Willie Nelson - Song {Live}"


def _make_download(base: pathlib.Path) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        path_base=str(base),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    dl.settings = MagicMock()
    dl.settings.data.filename_illegal_replacement = ""
    dl.settings.data.filename_illegal_map = None
    dl.settings.data.filename_delimiter_artist = ", "
    dl.settings.data.filename_delimiter_album_artist = ", "
    dl.settings.data.use_primary_album_artist = False
    dl.settings.data.album_track_num_pad_min = 0
    dl.provider = SimpleNamespace(media_kind=lambda _item: MediaType.TRACK)
    dl.extension_guess = lambda *_args, **_kwargs: ".flac"
    return dl


def test_the_playlist_download_renders_the_literal_name_once(tmp_path, monkeypatch):
    """The real engine composition: bake the playlist's folder, then format the
    item template per track, exactly as ``_setup_collection_download_context``
    and ``_destination_path`` do for a download."""
    track = _track()
    monkeypatch.setattr(download_module, "items_results_all", lambda *_a, **_k: [track])
    dl = _make_download(tmp_path)

    relative, _name, _short, items, _stdout = dl._setup_collection_download_context(
        _playlist("Best of {artist_name}"), _EXPECTED_PLAYLIST_TEMPLATE, False
    )
    destination, _extension = dl._destination_path(items[0], relative, None, 1, len(items))

    assert destination.relative_to(tmp_path) == pathlib.Path(
        "Playlists/Best of (artist_name)/Willie Nelson - On the Road Again.flac"
    )


def _formatter_token_literals() -> set[str]:
    """Every token name the ``_format_*`` functions compare ``name`` against."""
    tree = ast.parse(pathlib.Path(paths.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_format"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Compare)
                and isinstance(sub.left, ast.Name)
                and sub.left.id == "name"
                and len(sub.ops) == 1
                and isinstance(sub.ops[0], ast.Eq)
                and isinstance(sub.comparators[0], ast.Constant)
                and isinstance(sub.comparators[0].value, str)
            ):
                found.add(sub.comparators[0].value)
    return found


def test_wiring_every_resolved_token_is_a_known_token():
    """The neutralizer's set must equal the formatter's vocabulary.

    Proven behaviorally above (a known token in a value is neutralized); this
    pin compares the set against every name the ``_format_*`` functions can
    answer, which no runtime seam exposes. A token added to the formatter
    without the set therefore fails here instead of silently surviving in a
    download path.
    """
    assert _formatter_token_literals() == paths._TEMPLATE_TOKENS


def test_every_known_token_resolves_for_some_supported_media_type():
    """The other direction: the set holds no name the formatter cannot answer.

    Real objects, because every lookup is isinstance-gated; the empty-value
    tokens read as resolved too, since a formatter returned their value."""
    artist = _artist()
    track = _track()
    album = _album(artist)
    playlist = _playlist("Example Playlist")

    mix = Mix.__new__(Mix)
    mix.id = "m1"
    mix.title = "Example Mix"

    video = Video.__new__(Video)
    video.id = 2
    video.name = "Example Video"
    video.full_name = "Example Video"
    video.release_date = datetime(2026, 1, 2)
    video.explicit = True
    video.video_quality = "HIGH"
    video.duration = 300
    video.track_num = 1
    video.volume_num = 1
    video.media_metadata_tags = []
    video.artists = [artist]
    video.artist = artist
    video.album = album

    probes = ((track, 4, 23), (album, 0, 0), (playlist, 0, 0), (mix, 0, 0), (video, 0, 0))
    unresolved = sorted(
        token
        for token in paths._TEMPLATE_TOKENS
        if all(
            format_str_media(token, media, 1, pos, total, provider_name="Tidal") == token
            for media, pos, total in probes
        )
    )

    assert unresolved == []

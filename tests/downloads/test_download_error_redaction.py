"""The text a failed download's OSError puts on screen.

A failed move must not print the track title in the clear, a rename error wraps
both of its filenames, and the retry helper actually uses the redacting formatter.
"""

from __future__ import annotations

import inspect

import pytest

from waves import download as download_mod
from waves import redaction
from waves.download import _os_error_text


def test_a_failed_move_does_not_print_the_track_title_in_the_clear():
    """The retry helper's DESCRIPTION wraps the diagnosis, but the error
    interpolated one field later carries
    "<library>/<Artist>/<Album>/.<track title>.<uuid>.tmp" as its filename, so
    the same line that anonymised its paths puts the title straight back into
    the bundle, past the "also hide titles and searches" switch."""
    name = "/Music/Some Artist/Some Album/.Song.m4a.abc.tmp"
    error = PermissionError(13, "Permission denied", name)

    text = _os_error_text(error)

    assert redaction.content(name) in text, "the filename is not marked as content"
    assert "[Errno 13] Permission denied" in text, "the diagnosis itself must survive"
    # And the marking is what the export's content pass acts on, which is the
    # whole point: with "also hide titles and searches" on, nothing readable
    # about the artist, the album or the song is left.
    hidden = redaction._Redactor.scrub_content(text)
    assert "Some Artist" not in hidden and "Song.m4a" not in hidden, hidden
    assert "[Errno 13] Permission denied" in hidden


def test_a_rename_error_wraps_both_of_its_filenames():
    """os.replace failures carry filename AND filename2, and a move inside a
    download names two user paths."""
    error = OSError(18, "Invalid cross-device link", "/Music/A/B/.x.tmp", None, "/Music/A/B/x.flac")

    text = _os_error_text(error)

    assert text.count(redaction._C_OPEN) == 2, text
    assert "/Music/A/B" not in redaction._Redactor.scrub_content(text)


@pytest.mark.parametrize(
    "error",
    [OSError("something went wrong"), ValueError("not an OSError at all")],
)
def test_an_error_with_nothing_to_take_apart_reads_as_it_always_did(error):
    assert _os_error_text(error) == str(error)


def test_the_retry_helper_actually_uses_it():
    """The helper is only worth anything if the retry call sites use it."""
    source = inspect.getsource(download_mod.Download._retry_file_operation)

    assert "{error}" not in source and "{error_last}" not in source
    assert source.count("_os_error_text(") == 2

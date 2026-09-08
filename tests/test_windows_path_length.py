"""The platform's path cap is checked on the whole path, not just the folder.

path_file_sanitize validated the DIRECTORY for length and shortened it when it
did not fit, then joined the file name on without looking again. A folder that
was comfortably valid plus a long track name therefore came back over the cap,
and the download failed at the move after it had already finished.

The numbers differ per platform (259 on Windows, 1023 elsewhere) but
the code is one path, so the repro is built against the engine's own cap
(waves.helper.path.PATH_LENGTH_MAX) rather than by probing pathvalidate:
pathvalidate's posix ceiling (4096) is far above the engine's, so a folder
probed "just inside" pathvalidate's limit already exceeds the engine's and
correctly loses a folder component instead of just a file name, which says
nothing about the rule under test.
"""

import pathlib

import pytest
from pathvalidate import sanitize_filepath
from pathvalidate.error import ValidationError

from waves.helper.path import PATH_LENGTH_MAX, _exceeds_path_cap, path_file_sanitize


def _is_valid(path_file: pathlib.Path) -> bool:
    try:
        sanitize_filepath(path_file, validate_after_sanitize=True, platform="auto")
    except ValidationError:
        return False

    return True


# The cap the download engine actually enforces (259 on Windows from
# MAX_PATH, 1023 elsewhere so the terminating NUL is never the difference).
# pathvalidate's own posix ceiling sits far above it, so probing pathvalidate
# would build a folder the engine already shortens at the directory stage.
PATH_CAP = PATH_LENGTH_MAX
LONG_NAME = "a" * 200 + ".flac"


def _folder_just_inside_the_cap() -> pathlib.Path:
    """A deep folder that is valid on its own, but not once a long name joins it.

    Built from components of an ordinary size (a single 900-character directory
    would be truncated per component and would prove nothing about the join).
    """
    folder = pathlib.Path("/Music")

    while len(str(folder)) + 51 < PATH_CAP - len(LONG_NAME) + 100:
        folder = folder / ("x" * 50)

    return folder


# A folder well inside the cap, and a name well inside the 255 name cap, whose
# join is over it: the exact shape the old check waved through.
FOLDER = _folder_just_inside_the_cap()


class TestTheWholePathIsRevalidated:
    def test_a_valid_folder_plus_a_long_name_still_fits(self):
        candidate = FOLDER / LONG_NAME

        assert _is_valid(FOLDER), "the folder alone has to be valid, or the old check would have caught it"
        assert not _exceeds_path_cap(FOLDER), "the folder alone has to fit the engine cap too"
        assert _exceeds_path_cap(candidate), "the case under test has to be over the engine cap to begin with"

        result = path_file_sanitize(candidate, adapt=True)

        assert _is_valid(result)
        assert not _exceeds_path_cap(result)

    def test_the_file_keeps_its_extension_and_its_folder(self):
        result = path_file_sanitize(FOLDER / LONG_NAME, adapt=True)

        assert result.suffix == ".flac"
        assert result.parent == FOLDER, "trimming the name is enough; the album folder is shared and stays put"

    def test_a_short_path_is_left_exactly_as_it_is(self):
        candidate = pathlib.Path("/Music/Artist/Album/01 Song.flac")

        assert path_file_sanitize(candidate, adapt=True) == candidate

    def test_an_over_long_folder_still_shortens(self):
        # The behavior that was already there: when the folder itself cannot
        # fit, it is shrunk deepest-first and the file stays under the base.
        candidate = pathlib.Path("/Music") / ("d" * (PATH_CAP + 200)) / "Song.flac"

        result = path_file_sanitize(candidate, adapt=True)

        assert _is_valid(result)
        assert result.parts[:2] == ("/", "Music")

    def test_without_adapt_the_over_long_path_still_raises(self):
        with pytest.raises(ValidationError):
            path_file_sanitize(FOLDER / LONG_NAME, adapt=False)

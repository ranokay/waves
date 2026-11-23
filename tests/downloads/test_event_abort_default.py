"""DL-05: a Download built without event_abort must not crash on it.

The constructor advertises event_abort as optional, so omitting it has to
read as "no abort in force" on every hot path. A one-item run with nothing
to download fails on the missing media, never on AttributeError.
"""

import threading
from unittest.mock import MagicMock

from waves.download import Download


def test_item_without_event_abort_fails_on_missing_media(tmp_path):
    dl = Download(
        tidal_obj=MagicMock(),
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    assert isinstance(dl.event_abort, threading.Event)
    assert not dl.event_abort.is_set()

    ok, path = dl.item(file_template="{track_title}")

    assert (ok, path) == (False, "")


def test_event_abort_default_is_per_instance(tmp_path):
    first = Download(
        tidal_obj=MagicMock(),
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    second = Download(
        tidal_obj=MagicMock(),
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    first.event_abort.set()

    assert not second.event_abort.is_set()

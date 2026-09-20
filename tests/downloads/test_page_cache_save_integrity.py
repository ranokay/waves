"""Page-cache saves that race a library cache mutating mid-save.

A torn snapshot never reaches the disk, a normal save writes valid JSON, and
the save serializes in one shot so a concurrent mutation cannot tear it.
"""

from __future__ import annotations

import json
import pathlib
import threading
from unittest.mock import patch

from waves.desktop.backend import WavesBridge

# ---- a racing page-cache save skips the save, never crashes its caller -----


class _RacingDict(dict):
    """A library cache whose iteration blows up like a dict mutated mid-scan."""

    def items(self):
        raise RuntimeError("dictionary changed size during iteration")


class _SaveStub:
    _save_page_cache = WavesBridge._save_page_cache

    def __init__(self, path: pathlib.Path, lib=None):
        self._logged_in = True
        self._factory_reset = False
        self._lib_cache = {("tidal", "albums"): {"items": [{"id": "a1"}], "more": False}} if lib is None else lib
        self._lib_sort = {}
        self._browse_root_cache = {}
        self._browse_pages = {}
        self._artist_cache = {}
        self._home_cache = {}
        self._search_cache = {}
        self._page_cache_lock = threading.Lock()
        self._page_cache_path = str(path)

    def _cache_user_id(self):
        return "u"


def test_a_cache_mutating_mid_save_never_escapes_the_worker(tmp_path: pathlib.Path) -> None:
    stub = _SaveStub(tmp_path / "page_cache.json", lib=_RacingDict())
    stub._save_page_cache()  # must not raise: an escape latches the busy spinner on
    assert not (tmp_path / "page_cache.json").exists(), "a torn snapshot is never written"


def test_a_normal_save_still_writes_valid_json(tmp_path: pathlib.Path) -> None:
    stub = _SaveStub(tmp_path / "page_cache.json")
    stub._save_page_cache()
    data = json.loads((tmp_path / "page_cache.json").read_text(encoding="utf-8"))
    assert data["library"]["tidal:albums"]["items"] == [{"id": "a1"}]


def test_the_save_serializes_one_shot_never_incrementally(tmp_path: pathlib.Path) -> None:
    """json.dump's pure-Python encoder yields between dict items and can watch
    a cache change size mid-encode; json.dumps' one-shot C encoder cannot. The
    save must use dumps."""
    stub = _SaveStub(tmp_path / "page_cache.json")
    with patch("waves.desktop.backend.json.dump", side_effect=AssertionError("dump() must not be used")):
        stub._save_page_cache()
    assert (tmp_path / "page_cache.json").exists()

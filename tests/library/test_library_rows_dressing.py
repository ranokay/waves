"""A My Tidal shelf row carries its library verdict, the way a browse card does."""

from __future__ import annotations

from waves.desktop.backend import WavesBridge


class _Stub:
    _LIBRARY_DRESSED = WavesBridge._LIBRARY_DRESSED
    _dress_library_row = WavesBridge._dress_library_row
    _dress_library_rows = WavesBridge._dress_library_rows
    _dress_panel_rows = WavesBridge._dress_panel_rows

    def __init__(self, stamp=3, fail=False):
        self._library_stamp = stamp
        self._fail = fail
        self.calls: list = []

    def libraryAlbumPresence(self, *args):
        if self._fail:
            raise RuntimeError("no index")
        self.calls.append(("album", args))
        return {"present": True, "local_class": "hires"}

    def libraryTrackPresence(self, *args):
        self.calls.append(("track", args))
        return {"present": False}

    def artistLibraryPresence(self, name):
        self.calls.append(("artist", (name,)))
        return {"present": True, "albums": 2, "tracks": 9}


def _album(**over):
    row = {"id": "a1", "title": "Blue", "artist": "Joni", "year": "1971", "tracks": 10, "duration_sec": 2160}
    row.update(over)
    return row


def test_an_album_row_bakes_the_pill_verdict_and_its_publish():
    s = _Stub(stamp=3)
    (out,) = s._dress_library_rows("albums", [_album()])
    assert out["lib"] == {"present": True, "local_class": "hires"}
    assert out["libStamp"] == 3
    assert s.calls == [("album", ("Joni", "Blue", "1971", 10, 2160, -1))]


def test_a_track_row_asks_the_track_index_with_its_album():
    s = _Stub()
    row = {"id": "t1", "title": "River", "artist": "Joni", "album": "Blue", "year": "1971", "duration_sec": 241}
    (out,) = s._dress_library_rows("tracks", [row])
    assert out["lib"] == {"present": False} and out["libStamp"] == 3
    assert s.calls == [("track", ("Joni", "River", "Blue", "1971", 241, -1))]


def test_an_artist_row_bakes_the_strip_rollup():
    s = _Stub()
    (out,) = s._dress_library_rows("artists", [{"id": "ar1", "name": "Joni"}])
    assert out["lib"] == {"present": True, "albums": 2, "tracks": 9}
    assert s.calls == [("artist", ("Joni",))]


def test_the_cached_page_is_left_undressed():
    s = _Stub()
    cached = [_album()]
    out = s._dress_library_rows("albums", cached)
    assert out is not cached and out[0] is not cached[0]
    assert "lib" not in cached[0] and "libStamp" not in cached[0]


def test_other_categories_come_back_as_they_are():
    s = _Stub()
    rows = [{"id": "p1", "kind": "playlist", "title": "Mix"}]
    assert s._dress_library_rows("playlists", rows) is rows
    assert s._dress_library_rows("videos", rows) is rows
    assert s.calls == []


def test_a_publish_landing_mid_verdict_leaves_the_old_stamp_on_the_row():
    s = _Stub(stamp=0)
    verdict = s.libraryAlbumPresence

    def presence_then_publish(*args):
        s._library_stamp = 1
        return verdict(*args)

    s.libraryAlbumPresence = presence_then_publish
    (out,) = s._dress_library_rows("albums", [_album()])
    assert out["libStamp"] == 0


def test_a_failing_lookup_leaves_the_row_asking_live():
    s = _Stub(fail=True)
    (out,) = s._dress_library_rows("albums", [_album()])
    assert "lib" not in out and "libStamp" not in out


def test_panel_track_rows_are_dressed_but_video_rows_are_not():
    s = _Stub(stamp=5)
    rows = [
        {"id": "t1", "title": "River", "artist": "Joni", "album": "Blue", "year": "1971", "duration_sec": 241},
        {"id": "v1", "kind": "video", "title": "Clip"},
    ]
    out = s._dress_panel_rows(rows)
    assert out[0]["libStamp"] == 5 and out[0]["lib"] == {"present": False}
    assert "lib" not in out[1]
    assert "lib" not in rows[0]

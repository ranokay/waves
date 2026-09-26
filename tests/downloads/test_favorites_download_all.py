"""My Music shelves' DOWNLOAD ALL queues every favourite through the seam.

``downloadFavoriteTracks/Albums/Artists/Playlists/Mixes/Videos`` are the
shelf headers' bulk downloads (issue #485, ported from upstream's My Tidal
DOWNLOAD ALL onto the provider seam: every read goes through the source's
own ``favorites_page`` / ``favorites_count`` / ``user_collections``, never a
direct session call). Each pages the whole shelf (a short window must never
truncate it), registers a folder-style rollup under its fixed ``fav:<kind>``
id so the header button and its badge follow the queued / running / done /
failed lifecycle, and hands the keys to the GUI thread in ONE batch emit.
The partial-scan rule holds throughout: a failed page, a missing count or a
STOP queues nothing rather than reporting clean success over a set it never
saw. ``resolveFavoriteX`` is the count behind the confirm.

The artists rollup counts whole artists (members keyed ``artist:<id>`` so an
artist id is never mistaken for an album or track id), settling each as its
discography does, including a discography scan that queued nothing or
failed. The stranded-group reaper must not eat that rollup while its
artists' groups are alive, since a discography holds no queue row of its
own.
"""

from __future__ import annotations

import contextlib
import re
from threading import Lock
from types import SimpleNamespace

import pytest
from support.paths import QML_DIR, QML_MAIN

from waves.desktop.backend import (
    _ARTIST_ROLLUP_MEMBER,
    _LIBRARY_PAGE,
    WavesBridge,
    _fav_group_id,
    _ScanStopped,
)

QML_GROUP = (QML_DIR / "LibSourceGroup.qml").read_text(encoding="utf-8")
QML_MAIN_TEXT = QML_MAIN.read_text(encoding="utf-8")

SOURCE = "tidal"
_FAV_TRACKS_GROUP_ID = _fav_group_id(SOURCE, "tracks")
_FAV_ALBUMS_GROUP_ID = _fav_group_id(SOURCE, "albums")
_FAV_ARTISTS_GROUP_ID = _fav_group_id(SOURCE, "artists")
_FAV_PLAYLISTS_GROUP_ID = _fav_group_id(SOURCE, "playlists")
_FAV_MIXES_GROUP_ID = _fav_group_id(SOURCE, "mixes")
_FAV_VIDEOS_GROUP_ID = _fav_group_id(SOURCE, "videos")


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args if len(args) != 1 else args[0])


class _OrderedSignal(_Signal):
    def __init__(self, tag: str, log: list):
        super().__init__()
        self._tag = tag
        self._log = log

    def emit(self, *args):
        super().emit(*args)
        self._log.append(self._tag)


class _InlinePool:
    @staticmethod
    def start(worker):
        worker.fn()


class _FavProvider:
    """One source's favourites shelf through the seam: windows, count,
    collections and folder tree, the way the endpoint answers."""

    def __init__(
        self,
        tracks=(),
        albums=(),
        artists=(),
        videos=(),
        mixes=(),
        lists=None,
        tree=None,
        fail_page: int | None = None,
        count_fails: bool = False,
    ):
        self._rows = {
            "tracks": list(tracks),
            "albums": list(albums),
            "artists": list(artists),
            "videos": list(videos),
        }
        self._mixes = list(mixes)
        self._lists = lists
        self._tree = tree
        self._fail_page = fail_page
        self._count_fails = count_fails
        self.calls = 0

    def favorites_count(self, kind):
        if self._count_fails:
            raise RuntimeError("503")
        if kind == "mixes":
            return len(self._mixes)
        return len(self._rows[kind])

    def favorites_page(self, kind, offset, limit, order=None):
        self.calls += 1
        if self._fail_page is not None and offset // _LIBRARY_PAGE == self._fail_page:
            raise RuntimeError("429")
        rows = self._rows[kind]
        window = limit if limit is not None else len(rows)
        return list(rows[offset : offset + window]), offset + window < len(rows)

    def user_collections(self):
        return self._lists or {"playlists": [], "mixes": self._mixes}

    def folder_tree(self, root_folders=None):
        return self._tree


class _Node:
    def __init__(self, nid, parent, name, playlists):
        self.id, self.parent_id, self.name, self.playlists = nid, parent, name, playlists


class _Tree:
    def __init__(self, nodes, partial=False):
        self.nodes = nodes
        self.partial = partial

    def playlists_under(self, fid):
        out = []
        for node in self.nodes:
            if node.id == fid:
                out.extend(node.playlists)
                for child in self.nodes:
                    if child.parent_id == fid:
                        out.extend(self.playlists_under(child.id))
        return out


class _Stub:
    downloadFavoriteTracks = WavesBridge.downloadFavoriteTracks
    downloadFavoriteAlbums = WavesBridge.downloadFavoriteAlbums
    downloadFavoriteArtists = WavesBridge.downloadFavoriteArtists
    downloadFavoritePlaylists = WavesBridge.downloadFavoritePlaylists
    downloadFavoriteMixes = WavesBridge.downloadFavoriteMixes
    downloadFavoriteVideos = WavesBridge.downloadFavoriteVideos
    resolveFavoriteTracks = WavesBridge.resolveFavoriteTracks
    resolveFavoriteAlbums = WavesBridge.resolveFavoriteAlbums
    resolveFavoriteArtists = WavesBridge.resolveFavoriteArtists
    resolveFavoritePlaylists = WavesBridge.resolveFavoritePlaylists
    resolveFavoriteMixes = WavesBridge.resolveFavoriteMixes
    resolveFavoriteVideos = WavesBridge.resolveFavoriteVideos
    _all_favorites = WavesBridge._all_favorites
    _resolve_favorite_count = WavesBridge._resolve_favorite_count
    _fav_gates = WavesBridge._fav_gates
    _fav_refuse = WavesBridge._fav_refuse
    _register_fav_group = WavesBridge._register_fav_group
    _fav_scan_work = WavesBridge._fav_scan_work
    _download_favorite_collections = WavesBridge._download_favorite_collections
    _favorite_playlist_keys = WavesBridge._favorite_playlist_keys
    _favorite_mix_keys = WavesBridge._favorite_mix_keys
    _enqueue_artists = WavesBridge._enqueue_artists
    _enqueue_collections = WavesBridge._enqueue_collections
    _bump_folder_group = WavesBridge._bump_folder_group
    _bump_artist_group = WavesBridge._bump_artist_group
    _reap_stranded_groups = WavesBridge._reap_stranded_groups

    def __init__(self, provider, gate: str = "ok", claim_on: bool = False, claimed: set | None = None):
        self._dl = object()
        self._logged_in = True
        self.providers = {SOURCE: provider}
        self.settings = SimpleNamespace(data=SimpleNamespace(download_dolby_atmos=True))
        self._folder_groups: dict = {}
        self._folder_lock = Lock()
        self._artist_groups: dict = {}
        self._artist_lock = Lock()
        self._scan_pool = _InlinePool()
        self.threadpool = _InlinePool()
        self._scan_gen = 0
        self._browse_gen = 0
        self._scans_in_flight = 0
        self._scan_count_lock = Lock()
        self._browse_loading: set = set()
        self._merge_plans: dict = {}
        self._merge_scanned: set = set()
        self._queue: list = []
        self._queue_lock = Lock()
        self._pending_downloads: list = []
        self._pending_lock = Lock()
        self._stranded_once: set = set()
        self.scanningChanged = _Signal()
        self.order: list = []
        self.downloadProgress = _Signal()
        self.downloadState = _OrderedSignal("state", self.order)
        self.folderRemaining = _OrderedSignal("badge", self.order)
        self._tracksQueued = _Signal()
        self._albumsQueued = _Signal()
        self._artistsQueued = _Signal()
        self._collectionsQueued = _Signal()
        self._videosQueued = _Signal()
        self.favoriteTracksResolved = _Signal()
        self.favoriteAlbumsResolved = _Signal()
        self.favoriteArtistsResolved = _Signal()
        self.favoritePlaylistsResolved = _Signal()
        self.favoriteMixesResolved = _Signal()
        self.favoriteVideosResolved = _Signal()
        self.statuses: list = []
        self.remembered: list = []
        self.stashed: list = []
        self.started: list = []
        self.artist_clicks: list = []
        self._gate = gate
        self._claim_on = claim_on
        self._claimed = claimed or set()

    def _download_gate(self):
        return self._gate

    def _stash_pending_download(self, media_id, retry):
        self.stashed.append(media_id)

    def _ffmpeg_gate_holds(self, media_id, retry):
        return False

    def _gate_reachability(self, retry, media_id):
        return True

    def _set_status(self, text):
        self.statuses.append(text)

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_videos(self, videos):
        return list(videos)

    def _waves_pref_bool(self, key):
        return False

    def _library_bulk_skip_on(self):
        return self._claim_on

    def _library_claim_media(self, media, album=None):
        return str(media.id) in self._claimed

    def _library_claims_album(self, album):
        return str(album.id) in self._claimed

    def _remember(self, bucket, key, obj):
        self.remembered.append((bucket, key))

    def downloadArtist(self, artist_id):
        self.artist_clicks.append(artist_id)

    def downloadPlaylist(self, key):
        self.started.append(("playlist", key))

    def downloadMix(self, key):
        self.started.append(("mix", key))

    def _media_lists(self, source, refresh, walk=True):
        provider = self.providers[source]
        lists = provider.user_collections() or {"playlists": [], "mixes": []}
        return lists, (provider.folder_tree() if walk else None)

    def _queue_batch(self):
        return contextlib.nullcontext()


def _tracks(n):
    return [SimpleNamespace(id=f"t{i}", album=None) for i in range(n)]


def _albums(n):
    return [SimpleNamespace(id=f"a{i}") for i in range(n)]


def _artists(n):
    return [SimpleNamespace(id=f"r{i}") for i in range(n)]


def test_tracks_page_the_whole_shelf_into_one_batch():
    count = _LIBRARY_PAGE * 2 + 20
    stub = _Stub(_FavProvider(tracks=_tracks(count)))
    stub.downloadFavoriteTracks(SOURCE)
    assert len(stub._tracksQueued.emits) == 1, "one batched delivery, not one per track"
    gen, queued = stub._tracksQueued.emits[0]
    assert gen == 0
    assert len(queued) == count, "the scan stopped at the first window"
    assert queued[0] == "t0" and queued[-1] == f"t{count - 1}"
    assert stub.remembered[0] == ("track", "t0")
    assert any(f"{count} tracks" in s for s in stub.statuses)


def test_tracks_rollup_is_registered_and_published_badge_first():
    stub = _Stub(_FavProvider(tracks=_tracks(3)))
    stub.downloadFavoriteTracks(SOURCE)
    grp = stub._folder_groups[_FAV_TRACKS_GROUP_ID]
    assert grp["keys"] == {"t0", "t1", "t2"} and grp["total"] == 3
    assert grp["weights"] == {"t0": 1, "t1": 1, "t2": 1}
    assert (_FAV_TRACKS_GROUP_ID, 3, 3) in stub.folderRemaining.emits
    assert (_FAV_TRACKS_GROUP_ID, "queued") in stub.downloadState.emits
    # The badge reads the remaining map as soon as the state flips, so the
    # count must land before QUEUED.
    assert stub.order == ["state", "badge", "state"], "running, then the count, then QUEUED"


def test_tracks_a_failed_page_queues_nothing():
    stub = _Stub(_FavProvider(tracks=_tracks(_LIBRARY_PAGE + 5), fail_page=1))
    stub.downloadFavoriteTracks(SOURCE)
    assert stub._tracksQueued.emits == []
    assert _FAV_TRACKS_GROUP_ID not in stub._folder_groups
    assert stub.downloadState.emits[-1] == (_FAV_TRACKS_GROUP_ID, "")
    assert any("try again" in s for s in stub.statuses)


def test_tracks_a_stop_mid_scan_queues_nothing(monkeypatch):
    stub = _Stub(_FavProvider(tracks=_tracks(_LIBRARY_PAGE * 3)))
    ticks = {"n": 0}

    def stop_check_for(bridge):
        def check():
            ticks["n"] += 1
            if ticks["n"] >= 3:  # after page 0 has landed, so a partial list exists to leak
                raise _ScanStopped()

        return check

    monkeypatch.setattr("waves.desktop.backend._stop_check_for", stop_check_for)
    stub.downloadFavoriteTracks(SOURCE)
    assert stub.providers[SOURCE].calls >= 1, "the stop must land mid-scan, not before it"
    assert stub._tracksQueued.emits == []
    assert _FAV_TRACKS_GROUP_ID not in stub._folder_groups
    assert stub.downloadState.emits[-1] == (_FAV_TRACKS_GROUP_ID, "")


def test_tracks_a_bulk_scan_without_a_count_refuses_rather_than_guessing():
    """A short window is not the end of the list (unavailable items drop
    inside it). Without a count the shelf pages may stop there; the bulk
    download must not, or the rest of the favourites are quietly left out."""
    stub = _Stub(_FavProvider(tracks=_tracks(_LIBRARY_PAGE * 2), count_fails=True))
    stub.downloadFavoriteTracks(SOURCE)
    assert stub._tracksQueued.emits == []
    assert _FAV_TRACKS_GROUP_ID not in stub._folder_groups
    assert any("try again" in s for s in stub.statuses)


def test_tracks_a_folder_nudge_stashes_the_retry_and_publishes_no_group():
    stub = _Stub(_FavProvider(tracks=_tracks(2)), gate="nudge")
    stub.downloadFavoriteTracks(SOURCE)
    assert stub.stashed == [_FAV_TRACKS_GROUP_ID]
    assert stub._tracksQueued.emits == [] and stub._folder_groups == {}


def test_tracks_an_empty_list_and_a_fully_claimed_list_say_so():
    stub = _Stub(_FavProvider(tracks=[]))
    stub.downloadFavoriteTracks(SOURCE)
    assert stub._tracksQueued.emits == []
    assert stub.statuses[-1] == "No tracks to download"
    assert stub.downloadState.emits[-1] == (_FAV_TRACKS_GROUP_ID, "")

    stub = _Stub(_FavProvider(tracks=_tracks(2)), claim_on=True, claimed={"t0", "t1"})
    stub.downloadFavoriteTracks(SOURCE)
    assert stub._tracksQueued.emits == []
    assert "already in your library" in stub.statuses[-1]


def test_tracks_the_library_claim_skips_only_what_it_owns():
    stub = _Stub(_FavProvider(tracks=_tracks(3)), claim_on=True, claimed={"t1"})
    stub.downloadFavoriteTracks(SOURCE)
    assert stub._tracksQueued.emits[0][1] == ["t0", "t2"]
    assert stub._folder_groups[_FAV_TRACKS_GROUP_ID]["total"] == 2
    assert "1 already in your library" in stub.statuses[-1]


def test_albums_page_the_whole_list_into_one_batch_under_the_rollup():
    count = _LIBRARY_PAGE + 7
    stub = _Stub(_FavProvider(albums=_albums(count)))
    stub.downloadFavoriteAlbums(SOURCE)
    assert len(stub._albumsQueued.emits) == 1
    gen, keys = stub._albumsQueued.emits[0]
    assert gen == 0 and len(keys) == count
    grp = stub._folder_groups[_FAV_ALBUMS_GROUP_ID]
    assert grp["total"] == count and grp["keys"] == set(keys)
    assert stub.downloadState.emits[-1] == (_FAV_ALBUMS_GROUP_ID, "queued")
    # Edition handling already ran in the sweep; downloadAlbum must not
    # divert these into its own scan, which never bumps the rollup.
    assert stub._merge_scanned == set(keys)


def test_albums_the_library_owns_are_left_out():
    stub = _Stub(_FavProvider(albums=_albums(3)), claim_on=True, claimed={"a1"})
    stub.downloadFavoriteAlbums(SOURCE)
    assert stub._albumsQueued.emits[0][1] == ["a0", "a2"]
    assert "1 already in your library" in stub.statuses[-1]


def test_albums_a_failed_page_queues_nothing():
    stub = _Stub(_FavProvider(albums=_albums(3), fail_page=0))
    stub.downloadFavoriteAlbums(SOURCE)
    assert stub._albumsQueued.emits == [] and stub._folder_groups == {}
    assert stub.downloadState.emits[-1] == (_FAV_ALBUMS_GROUP_ID, "")


def test_artists_start_one_discography_each_under_a_namespaced_rollup():
    stub = _Stub(_FavProvider(artists=[*_artists(3), SimpleNamespace(id="r1")]))
    stub.downloadFavoriteArtists(SOURCE)
    gen, ids = stub._artistsQueued.emits[0]
    assert ids == ["r0", "r1", "r2"], "one discography per artist, duplicates dropped"
    grp = stub._folder_groups[_FAV_ARTISTS_GROUP_ID]
    assert grp["keys"] == {_ARTIST_ROLLUP_MEMBER + i for i in ids}
    assert (_FAV_ARTISTS_GROUP_ID, 3, 3) in stub.folderRemaining.emits
    stub._enqueue_artists(gen, ids)
    assert stub.artist_clicks == ids


def test_artists_a_batch_stop_overtook_starts_no_discography():
    stub = _Stub(_FavProvider(artists=_artists(2)))
    stub._enqueue_artists(stub._scan_gen - 1, ["r0", "r1"])
    assert stub.artist_clicks == []


def test_artists_a_stop_mid_scan_registers_nothing(monkeypatch):
    def stop_check_for(bridge):
        def check():
            raise _ScanStopped()

        return check

    monkeypatch.setattr("waves.desktop.backend._stop_check_for", stop_check_for)
    stub = _Stub(_FavProvider(artists=_artists(2)))
    stub.downloadFavoriteArtists(SOURCE)
    assert stub._artistsQueued.emits == [] and stub._folder_groups == {}
    assert stub.downloadState.emits[-1] == (_FAV_ARTISTS_GROUP_ID, "")


def _fav_artists_group(stub, ids):
    keys = [_ARTIST_ROLLUP_MEMBER + i for i in ids]
    stub._folder_groups[_FAV_ARTISTS_GROUP_ID] = {
        "keys": set(keys),
        "done": set(),
        "failed": set(),
        "prog": {},
        "weights": dict.fromkeys(keys, 1),
        "total": len(keys),
    }


def test_a_finished_discography_settles_its_artist_in_the_rollup():
    stub = _Stub(_FavProvider())
    _fav_artists_group(stub, ["r0", "r1"])
    for aid, album in (("r0", "x0"), ("r1", "x1")):
        stub._artist_groups[aid] = {"keys": {album}, "done": set(), "failed": set(), "prog": {}}
    # The album numbered like an artist must not credit that artist.
    stub._bump_folder_group("r1", None, "done")
    assert stub._folder_groups[_FAV_ARTISTS_GROUP_ID]["done"] == set()
    stub._bump_artist_group("x0", 50.0, None)
    assert stub._folder_groups[_FAV_ARTISTS_GROUP_ID]["prog"][_ARTIST_ROLLUP_MEMBER + "r0"] == 50.0
    stub._bump_artist_group("x0", None, "done")
    assert (_FAV_ARTISTS_GROUP_ID, 1, 2) in stub.folderRemaining.emits
    stub._bump_artist_group("x1", None, "failed")
    assert _FAV_ARTISTS_GROUP_ID not in stub._folder_groups
    assert stub.downloadState.emits[-1] == (_FAV_ARTISTS_GROUP_ID, "failed")


def test_the_reaper_keeps_the_rollup_while_a_discography_is_alive():
    stub = _Stub(_FavProvider())
    _fav_artists_group(stub, ["r0"])
    stub._artist_groups["r0"] = {"keys": {"x0"}, "done": set(), "failed": set(), "prog": {}}
    stub._queue = [{"media_id": "x0", "status": "queued"}]
    stub._reap_stranded_groups()
    stub._reap_stranded_groups()
    assert _FAV_ARTISTS_GROUP_ID in stub._folder_groups
    # With the discography gone, the net still catches a stranded rollup.
    stub._artist_groups.clear()
    stub._queue = []
    stub._reap_stranded_groups()
    stub._reap_stranded_groups()
    assert _FAV_ARTISTS_GROUP_ID not in stub._folder_groups


class _ArtistScanStub:
    """Just enough bridge for downloadArtist to end without queueing."""

    downloadArtist = WavesBridge.downloadArtist
    _bump_folder_group = WavesBridge._bump_folder_group

    def __init__(self, artist):
        self._dl = object()
        self._logged_in = True
        self.providers = {}
        self._artist = artist
        self.settings = SimpleNamespace(data=SimpleNamespace(download_dolby_atmos=True, video_download=False))
        self._scan_pool = _InlinePool()
        self._scan_gen = 0
        self._scans_in_flight = 0
        self._scan_count_lock = Lock()
        self.scanningChanged = _Signal()
        self.downloadProgress = _Signal()
        self.downloadState = _Signal()
        self.folderRemaining = _Signal()
        self._folder_groups: dict = {}
        self._folder_lock = Lock()
        self._artist_groups: dict = {}
        self._artist_lock = Lock()
        self._merge_scanned: set = set()
        self._merge_plans: dict = {}
        self.statuses: list = []

    def _download_gate(self):
        return "ok"

    def _ffmpeg_gate_holds(self, media_id, retry):
        return False

    def _gate_reachability(self, retry, media_id):
        return True

    def _set_status(self, text):
        self.statuses.append(text)

    def _get_artist(self, artist_id):
        return self._artist

    def _artist_releases(self, artist):
        return [], [], True

    def _dedup_albums(self, albums):
        return list(albums)

    def _waves_pref_bool(self, key):
        return False

    def _library_bulk_skip_on(self):
        return False

    def artistDownloadSupported(self, artist_id):
        return True

    def _remember(self, bucket, key, obj):
        pass


@pytest.mark.parametrize(("artist", "verdict"), [(SimpleNamespace(id="r0"), "done"), (None, "failed")])
def test_a_discography_that_queues_nothing_still_settles_its_artist(artist, verdict):
    stub = _ArtistScanStub(artist)
    _fav_artists_group(stub, ["r0"])
    stub.downloadArtist("r0")
    assert _FAV_ARTISTS_GROUP_ID not in stub._folder_groups, "the rollup waited on an artist forever"
    assert stub.downloadState.emits[-1] == (_FAV_ARTISTS_GROUP_ID, verdict)


def _root_lists():
    folder = SimpleNamespace(id="f1")  # a root folder row carries no track count
    return {
        "playlists": [folder, SimpleNamespace(id="p1", num_tracks=9)],
        "mixes": [SimpleNamespace(id="m1"), SimpleNamespace(id="m2")],
    }


def _tree(partial=False):
    return _Tree(
        nodes=[
            _Node("f1", "root", "F1", [SimpleNamespace(id="p2", num_tracks=5)]),
            _Node("f2", "f1", "F2", [SimpleNamespace(id="p3", num_tracks=1), SimpleNamespace(id="p1", num_tracks=9)]),
        ],
        partial=partial,
    )


def _playlist_stub(partial=False):
    return _Stub(_FavProvider(lists=_root_lists(), tree=_tree(partial)))


def test_playlists_take_every_folder_at_any_depth_once():
    stub = _playlist_stub()
    stub.downloadFavoritePlaylists(SOURCE)
    gen, kind, keys = stub._collectionsQueued.emits[0]
    assert kind == "playlist" and keys == ["p1", "p2", "p3"]
    grp = stub._folder_groups[_FAV_PLAYLISTS_GROUP_ID]
    assert grp["weights"] == {"p1": 9, "p2": 5, "p3": 1}, "the bar is track-weighted, like a folder's"
    stub._enqueue_collections(gen, kind, keys)
    assert stub.started == [("playlist", "p1"), ("playlist", "p2"), ("playlist", "p3")]
    stub.resolveFavoritePlaylists(SOURCE)
    assert stub.favoritePlaylistsResolved.emits == [(SOURCE, 3)]


def test_playlists_refuse_a_folder_walk_cut_short():
    stub = _playlist_stub(partial=True)
    stub.downloadFavoritePlaylists(SOURCE)
    assert stub._collectionsQueued.emits == [] and stub._folder_groups == {}
    assert stub.downloadState.emits[-1] == (_FAV_PLAYLISTS_GROUP_ID, "")
    assert "try again" in stub.statuses[-1]


def test_mixes_queue_each_mix_and_a_stale_batch_starts_nothing():
    stub = _Stub(_FavProvider(mixes=[SimpleNamespace(id="m1"), SimpleNamespace(id="m2")]))
    stub.downloadFavoriteMixes(SOURCE)
    gen, kind, keys = stub._collectionsQueued.emits[0]
    assert kind == "mix" and keys == ["m1", "m2"]
    assert _FAV_MIXES_GROUP_ID in stub._folder_groups
    stub._enqueue_collections(gen - 1, kind, keys)
    assert stub.started == []


def test_videos_page_every_favourite_video():
    count = _LIBRARY_PAGE + 3
    stub = _Stub(_FavProvider(videos=[SimpleNamespace(id=f"v{i}") for i in range(count)]))
    stub.downloadFavoriteVideos(SOURCE)
    _gen, keys = stub._videosQueued.emits[0]
    assert len(keys) == count
    assert stub._folder_groups[_FAV_VIDEOS_GROUP_ID]["total"] == count


def test_an_empty_tab_says_so_and_publishes_no_group():
    stub = _Stub(_FavProvider())
    stub.downloadFavoriteMixes(SOURCE)
    assert stub._folder_groups == {} and stub.statuses[-1] == "No mixes to download"


def test_resolve_counts_each_shelf_and_minus_one_on_failure():
    stub = _Stub(
        _FavProvider(
            tracks=_tracks(7),
            albums=_albums(4),
            artists=_artists(2),
            videos=[SimpleNamespace(id="v0")],
            lists=_root_lists(),
            tree=_tree(),
        )
    )
    stub.resolveFavoriteTracks(SOURCE)
    stub.resolveFavoriteAlbums(SOURCE)
    stub.resolveFavoriteArtists(SOURCE)
    stub.resolveFavoriteVideos(SOURCE)
    stub.resolveFavoriteMixes(SOURCE)
    assert stub.favoriteTracksResolved.emits == [(SOURCE, 7)]
    assert stub.favoriteAlbumsResolved.emits == [(SOURCE, 4)]
    assert stub.favoriteArtistsResolved.emits == [(SOURCE, 2)]
    assert stub.favoriteVideosResolved.emits == [(SOURCE, 1)]
    assert stub.favoriteMixesResolved.emits == [(SOURCE, 2)]
    assert stub._browse_loading == set(), "the in-flight keys must clear"

    stub = _Stub(_FavProvider(count_fails=True))
    stub.resolveFavoriteTracks(SOURCE)
    assert stub.favoriteTracksResolved.emits == [(SOURCE, -1)]
    assert any("try again" in s for s in stub.statuses)


def test_resolve_drops_a_count_from_a_previous_account():
    stub = _Stub(_FavProvider(tracks=_tracks(7)))

    class _BumpPool:
        @staticmethod
        def start(worker):
            stub._browse_gen += 1  # logout landed while the count was in flight
            worker.fn()

    stub.threadpool = _BumpPool()
    stub.resolveFavoriteTracks(SOURCE)
    assert stub.favoriteTracksResolved.emits == []
    assert stub._browse_loading == set(), "a dropped count must still release the key"


def test_zero_favourites_says_so():
    stub = _Stub(_FavProvider())
    stub.resolveFavoriteTracks(SOURCE)
    assert stub.favoriteTracksResolved.emits == [(SOURCE, 0)]
    assert stub.statuses[-1] == "No favourite tracks yet"


def test_resolve_needs_a_login():
    stub = _Stub(_FavProvider(tracks=_tracks(7)))
    stub._logged_in = False
    stub.resolveFavoriteTracks(SOURCE)
    assert stub.favoriteTracksResolved.emits == []


@pytest.mark.parametrize(
    ("cat", "btn", "suffix", "resolve", "slot", "kind"),
    [
        (
            "tracks",
            "favTracksBtn",
            "tracks",
            "resolveFavoriteTracks",
            "downloadFavoriteTracks",
            "favTracks",
        ),
        (
            "albums",
            "favAlbumsBtn",
            "albums",
            "resolveFavoriteAlbums",
            "downloadFavoriteAlbums",
            "favAlbums",
        ),
        (
            "artists",
            "favArtistsBtn",
            "artists",
            "resolveFavoriteArtists",
            "downloadFavoriteArtists",
            "favArtists",
        ),
        (
            "playlists",
            "favPlaylistsBtn",
            "playlists",
            "resolveFavoritePlaylists",
            "downloadFavoritePlaylists",
            "favPlaylists",
        ),
        ("mixes", "favMixesBtn", "mixes", "resolveFavoriteMixes", "downloadFavoriteMixes", "favMixes"),
        (
            "videos",
            "favVideosBtn",
            "videos",
            "resolveFavoriteVideos",
            "downloadFavoriteVideos",
            "favVideos",
        ),
    ],
)
def test_wiring_shelf_buttons(cat, btn, suffix, resolve, slot, kind):
    # Wiring pin (DEVELOPER.md): the per-tab button objectName, the shared
    # per-source group id on the button and its badge, the tap path, and the
    # confirm-gate dispatch have no behavioral seam (a real tap needs an
    # offscreen render). The behavior is proved by
    # tests/ui/test_my_music_download_all_qml.py.
    gid = _fav_group_id(SOURCE, suffix)
    assert f'objectName: "{btn}"' in QML_GROUP, f"the {cat} DOWNLOAD ALL button is missing"
    assert f'mediaId: "fav:" + group.sourceId + ":{suffix}"' in QML_GROUP, (
        "the button and the backend must share one per-source group id"
    )
    assert f'folderId: "fav:" + group.sourceId + ":{suffix}"' in QML_GROUP, "the badge must count down the same rollup"
    assert gid == f"fav:{SOURCE}:{suffix}", "the backend group id names the same source and kind"
    assert f'group.favTap("{cat}")' in QML_GROUP, "the button must drive the shared tap path"
    assert f"waves.{resolve}(group.sourceId)" in QML_GROUP
    assert f"waves.{slot}(group.sourceId)" in QML_GROUP, "the muted-confirm path must call the slot"
    assert f"{kind}Pending" in QML_GROUP
    gate = re.search(r"id: catDlGate.*?label: \"Cancel\"", QML_MAIN_TEXT, re.DOTALL)
    assert gate and f'p.kind === "{kind}"' in gate.group(0) and f"waves.{slot}(p.source)" in gate.group(0)


def test_wiring_logout_disarms_counts():
    # Wiring pin (DEVELOPER.md): clearPanes disarming every pending count on
    # an account flip has no behavioral seam short of a full sign-out
    # render; the armed-count lifecycle itself is proved by
    # tests/ui/test_my_music_download_all_qml.py.
    for flag in (
        "favTracksPending",
        "favAlbumsPending",
        "favArtistsPending",
        "favPlaylistsPending",
        "favMixesPending",
        "favVideosPending",
    ):
        assert f"group.{flag} = false" in QML_GROUP, f"clearPanes must disarm {flag}"

"""The Provider seam is the only road (ticket #22, the contract half).

With both migration batches routed, the old roads are deleted: the bridge no
longer reaches the TIDAL session, helper, or download bodies directly. Login
and logout, the account id, the credential facts the redactor registers, the
session rebuild, the folder walk, the Browse/editorial reads, the id lookups,
the small track search, and the preview stream resolution all cross
``self.providers``; the engine keeps its own fenced session machinery.

HOW THIS STAYS FIXED
--------------------
Two mechanisms. A static test parses backend.py and fails on any
``self.tidal.<...>`` reach outside the engine subclass (whose session work is
the Atmos fence the spec pins to the engine), and on any helper catalog body
the bridge has no business calling. The behavioral tests bind the real,
unbound ``WavesBridge`` methods onto minimal stand-ins whose provider is a
recording fake and whose ``tidal`` object fails the test on any touch.
"""

from __future__ import annotations

import ast
import pathlib
import threading
from types import SimpleNamespace

import pytest

import waves.waves_ui.backend as backend
from waves.waves_ui.backend import WavesBridge

# --------------------------------------------------------------------------- #
# the static contract: backend.py's reach inventory
# --------------------------------------------------------------------------- #
BACKEND_PATH = pathlib.Path(backend.__file__)


def _class_span(tree: ast.Module, name: str) -> tuple[int, int]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node.lineno, node.end_lineno
    raise AssertionError(f"class {name} not found in backend.py")


def _self_tidal_reaches(source: str) -> list[tuple[int, str]]:
    """Every ``self.tidal.<attr>`` reach, as (line, attr), except the bare
    ``self.tidal`` references (construction and the engine hand-off)."""
    tree = ast.parse(source)
    reaches: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr != "tidal"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "tidal"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            reaches.append((node.lineno, node.attr))
    return reaches


def _helper_tidal_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "waves.helper.tidal":
            return {alias.name for alias in node.names}
    return set()


class TestTheStaticContract:
    def test_the_bridge_never_reaches_the_tidal_object_outside_the_engine(self):
        # The engine subclass (_TrackedDownload) keeps its fenced session work
        # (the Atmos swap machinery the spec pins to the engine). The bridge
        # proper keeps exactly two touches, pinned in the next test: handing
        # the engine its tidal object, and wiring the config layer's
        # credential event. Everything else rides the provider.
        source = BACKEND_PATH.read_text(encoding="utf-8")
        start, end = _class_span(ast.parse(source), "_TrackedDownload")
        allowed = {"on_session_credentials"}

        offenders = [
            (line, attr)
            for line, attr in _self_tidal_reaches(source)
            if not (start <= line <= end) and attr not in allowed
        ]
        assert offenders == [], (
            "the bridge reached the TIDAL object directly (route through "
            f"self.providers instead): {offenders}"
        )

    def test_no_getattr_reach_either(self):
        # getattr(self.tidal, "session", None) is the same reach spelled
        # sideways, invisible to the attribute walk.
        source = BACKEND_PATH.read_text(encoding="utf-8")
        assert 'getattr(self.tidal' not in source

    def test_the_two_allowed_touches_are_exactly_these(self):
        source = BACKEND_PATH.read_text(encoding="utf-8")
        assert source.count("tidal_obj=self.tidal") == 2, "the engine hand-off"
        assert "self.tidal.on_session_credentials = self._register_session_secrets" in source

    def test_the_bridge_imports_no_catalog_helper_bodies(self):
        # The dict builders are the documented rendering carve-out (the naming
        # normalizers stay until the dict builders move with the second
        # provider); quality_audio_highest stays for the merge/dedup rank's own
        # fallback semantics until the quality-enum ticket retires it. Every
        # CATALOG body -- search, collections, media instantiation, the url
        # grammar, the folder walk -- rides the seam.
        source = BACKEND_PATH.read_text(encoding="utf-8")
        assert _helper_tidal_imports(source) == {
            "name_builder_album_artist",
            "name_builder_artist",
            "name_builder_title",
            "quality_audio_highest",
        }


# --------------------------------------------------------------------------- #
# the behavioral contract
# --------------------------------------------------------------------------- #


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args[0] if len(args) == 1 else args)


class _GuardTidal:
    """Any attribute touch fails: the provider is the only road."""

    def __getattr__(self, name):
        raise AssertionError(f"the bridge reached the TIDAL object directly: .{name}")


class _FakeProvider:
    """Records the seam calls the bridge makes; answers with canned values."""

    def __init__(self, **answers):
        self.calls: list[tuple] = []
        self._answers = answers

    def _answer(self, key, *call):
        self.calls.append(call)
        answer = self._answers.get(key)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def login_begin(self):
        return self._answer("login_begin", "login_begin")

    def login_complete(self, payload):
        return self._answer("login_complete", "login_complete", payload)

    def login_resume(self):
        return self._answer("login_resume", "login_resume")

    def logout(self):
        return self._answer("logout", "logout")

    def reset_session(self):
        return self._answer("reset_session", "reset_session")

    def account_id(self):
        return self._answer("account_id", "account_id")

    def credential_facts(self):
        return self._answer("credential_facts", "credential_facts")

    def apply_quality(self, tier, audio_type):
        return self._answer("apply_quality", "apply_quality", tier, audio_type)

    def get_object(self, kind, raw_id):
        return self._answer("get_object", "get_object", kind, raw_id)

    def search_tracks(self, needle, limit=10):
        return self._answer("search_tracks", "search_tracks", needle, limit)

    def folder_tree(self, root_folders=None):
        return self._answer("folder_tree", "folder_tree", root_folders)

    def browse_page(self, title, api_path):
        return self._answer("browse_page", "browse_page", title, api_path)

    def browse_home(self):
        return self._answer("browse_home", "browse_home")

    def browse_window(self, title, data_path, mod_type, offset, limit=50):
        return self._answer("browse_window", "browse_window", title, data_path, mod_type, offset, limit)

    def resolve_preview(self, track):
        return self._answer("resolve_preview", "resolve_preview", track)

    def collection_items(self, obj, include_videos=True):
        return self._answer("collection_items", "collection_items", obj, include_videos)

    def user_collections(self):
        return self._answer("user_collections", "user_collections")


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.run()


class _AuthStub:
    """Base stand-in for the auth slots: the guard tidal, the fake provider,
    the inline pool and the signals they touch."""

    def __init__(self, provider):
        self.providers = {"tidal": provider}
        self.tidal = _GuardTidal()
        self.threadpool = _InlinePool()
        self.statuses: list[str] = []
        self.busy: list[bool] = []
        self.loginUrlReady = _Signal()

    @staticmethod
    def start(worker, priority: int = 0):  # matches self.threadpool.start(worker)
        worker.run()

    def _set_status(self, msg: str) -> None:
        self.statuses.append(msg)

    def _set_busy(self, value: bool) -> None:
        self.busy.append(value)

    def _set_logged_in(self, value: bool) -> None:
        self.logged_in_calls.append(value)

    def _load_page_cache(self) -> None:
        self.page_cache_loaded = True

    def _init_download(self) -> None:
        self.init_download_called = True

    def _prefetch_tile_art(self) -> None:
        self.prefetch_called = True


class TestTheSessionLifecycle:
    def _stub(self, **answers) -> _AuthStub:
        provider = _FakeProvider(**answers)
        stub = _AuthStub(provider)
        stub.logged_in_calls = []
        stub.page_cache_loaded = False
        stub.init_download_called = False
        stub.prefetch_called = False
        stub._provider = provider
        return stub

    def _run(self, stub, name, *args):
        method = getattr(WavesBridge, name)
        method.__get__(stub, type(stub))(*args)

    def test_begin_login_asks_the_provider_for_the_flow_entry(self):
        stub = self._stub(login_begin="https://login.tidal.com/authorize?x=1")

        self._run(stub, "beginLogin")

        assert stub._provider.calls == [("login_begin",)]
        assert stub.loginUrlReady.emits == ["https://login.tidal.com/authorize?x=1"]
        assert stub.statuses[-1] == "Finish signing in, then paste the URL back"

    def test_a_failed_login_begin_reports_instead_of_raising(self):
        stub = self._stub(login_begin=RuntimeError("network died"))

        self._run(stub, "beginLogin")

        assert stub.statuses[-1] == "Could not start login"
        assert stub.loginUrlReady.emits == []

    def test_complete_login_exchanges_through_the_provider(self):
        stub = self._stub(login_complete=True)

        self._run(stub, "completeLogin", "https://tidal.com/login?code=q")

        assert stub._provider.calls == [("login_complete", "https://tidal.com/login?code=q")]
        assert stub.statuses[-1] == "Signed in"
        assert stub.logged_in_calls == [True]
        assert stub.busy == [True, False]
        assert stub.page_cache_loaded and stub.init_download_called and stub.prefetch_called

    def test_complete_login_reports_a_failed_finalize(self):
        stub = self._stub(login_complete=False)

        self._run(stub, "completeLogin", "https://tidal.com/login?code=q")

        assert stub.statuses[-1] == "Sign-in failed. Try again."
        assert stub.logged_in_calls == []
        assert stub.busy == [True, False]

    def test_a_paste_without_https_is_refused_before_the_provider(self):
        stub = self._stub(login_complete=True)

        self._run(stub, "completeLogin", "not a url")

        assert stub._provider.calls == []
        assert stub.statuses[-1] == "That isn't the sign-in link. Copy the full URL from the browser."
        assert stub.busy == []

    def test_token_login_resumes_through_the_provider(self):
        stub = self._stub(login_resume=True)
        stub._session_resolved = False
        stub.sessionResolvedChanged = _Signal()

        self._run(stub, "_try_token_login")

        assert stub._provider.calls == [("login_resume",)]
        assert stub.statuses[-1] == "Signed in"
        assert stub.logged_in_calls == [True]
        assert stub._session_resolved is True
        assert stub.sessionResolvedChanged.emits == [()]

    def test_a_failed_resume_answers_not_signed_in_and_resolves_the_overlay(self):
        stub = self._stub(login_resume=False)
        stub._session_resolved = False
        stub.sessionResolvedChanged = _Signal()

        self._run(stub, "_try_token_login")

        assert stub.statuses[-1] == "Not signed in"
        assert stub.logged_in_calls == []
        assert stub._session_resolved is True

    def test_logout_signs_out_through_the_provider_and_rebuilds(self):
        stub = self._stub(logout=None, reset_session=None)
        stub.stopAll = lambda: None
        # The cache-clearing half is logout's own policy; give it the state.
        for name, value in {
            "_logged_in": True,
            "_lib_cache": {},
            "_lib_loading": {},
            "_lib_sort": {},
            "_fav_ids": {},
            "_pending_lock": threading.Lock(),
            "_pending_downloads": [],
            "_lib_gen": 0,
            "_browse_root_cache": None,
            "_browse_pages": {},
            "_browse_loading": set(),
            "_category_pl": {},
            "_browse_gen": 0,
            "_browse_reval_ts": 1.0,
            "_prefetch_lock": threading.Lock(),
            "_prefetch_key": None,
            "_prefetch_claimed": False,
            "_prefetch_unrecorded": set(),
            "_album_tracks_inflight": {},
            "_album_tracks_unrecorded": set(),
            "_item_fetch_ts": {},
            "_artist_cache": {},
            "_artist_loading": {},
            "_album_tracks_cache": {},
            "_home_cache": None,
            "_home_loading": False,
            "_home_reval_ts": 1.0,
            "_lib_reval_ts": {},
            "_media_lists_cache": None,
            "_folder_tree": None,
            "_tree_warm_waiting": [],
            "_search_cache": {},
            "_search_gen": 0,
            "_artist_pop_cache": {},
            "_objs_lock": threading.Lock(),
            "_objs": {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}},
            "_page_cache_path": "/nonexistent/page_cache.json",
        }.items():
            setattr(stub, name, value)

        self._run(stub, "logout")

        assert stub._provider.calls == [("logout",), ("reset_session",)]
        assert stub.logged_in_calls == [False]
        assert stub.statuses[-1] == "Signed out"

    def test_the_page_cache_user_id_reads_the_provider(self):
        stub = self._stub(account_id="4242")

        assert WavesBridge._cache_user_id.__get__(stub, type(stub))() == "4242"

    def test_a_failed_account_read_answers_empty(self):
        stub = self._stub(account_id=RuntimeError("gone"))

        assert WavesBridge._cache_user_id.__get__(stub, type(stub))() == ""


class TestTheRedactorRegistration:
    def _stub(self, **answers):
        provider = _FakeProvider(**answers)
        stub = _AuthStub(provider)
        return stub, provider

    def test_session_secrets_come_from_the_provider(self, monkeypatch):
        registered: list[tuple[str, str]] = []
        monkeypatch.setattr(backend.diagnostics, "register_secret", lambda val, tag: registered.append((val, tag)))
        stub, _ = self._stub(
            credential_facts={
                "access_token": "tok",
                "refresh_token": "ref",
                "session_id": "sid",
                "account_id": "7",
                "username": "me@example.com",
            }
        )

        WavesBridge._register_session_secrets.__get__(stub, type(stub))()

        assert ("tok", "‹token›") in registered
        assert ("ref", "‹token›") in registered
        assert ("sid", "‹session›") in registered
        assert ("7", "‹account›") in registered
        assert ("me@example.com", "‹email›") in registered

    def test_a_failed_credential_read_never_breaks_the_caller(self, monkeypatch):
        # The config layer calls this on every credential mint; a failing read
        # must never take a login or a quality switch down with it.
        monkeypatch.setattr(backend.diagnostics, "register_secret", lambda val, tag: None)
        stub, _ = self._stub(credential_facts=RuntimeError("no session"))

        WavesBridge._register_session_secrets.__get__(stub, type(stub))()  # must not raise


class TestTheQualityReapply:
    def test_a_quality_change_reapplies_through_the_provider(self):
        from tidalapi.media import Quality

        from waves.providers import AudioType, QualityTier

        provider = _FakeProvider(apply_quality=None)
        stub = _AuthStub(provider)

        WavesBridge._reapply_quality.__get__(stub, type(stub))(Quality.hi_res_lossless)

        assert provider.calls == [("apply_quality", QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)]


class TestTheEngineHandoff:
    def test_the_download_init_composes_the_shared_provider(self):
        # The seam's composition rule: one provider instance -- the engine
        # registers its stream resolver on THE provider the bridge dispatches
        # through, never a private second one.
        source = BACKEND_PATH.read_text(encoding="utf-8")
        assert "provider=self.providers[CTX_TIDAL]" in source


# --------------------------------------------------------------------------- #
# the catalog roads: folder walk, browse windows, id lookups, previews
# --------------------------------------------------------------------------- #


class TestTheCatalogRoads:
    def _stub(self, **answers):
        provider = _FakeProvider(**answers)
        stub = _AuthStub(provider)
        stub._provider = provider
        return stub

    def test_the_folder_walk_reads_the_provider(self):
        from types import SimpleNamespace as NS

        stub = self._stub(
            user_collections={"playlists": [NS(id="f1"), NS(num_tracks=3, id="p1")], "mixes": []},
            folder_tree=NS(nodes=[NS()], playlist_paths={"p1": "F"}, partial=False),
        )
        stub._media_lists_lock = threading.Lock()
        stub._media_lists_cache = None
        stub._MEDIA_LISTS_TTL = 60.0
        stub._folder_tree = None

        fresh, tree = WavesBridge._media_lists.__get__(stub, type(stub))(refresh=True, walk=True)

        assert stub._provider.calls == [
            ("user_collections",),
            ("folder_tree", [fresh["playlists"][0]]),  # the root folders, reused
        ]
        assert tree.playlist_paths == {"p1": "F"}
        assert stub._folder_tree is tree

    def test_browse_fetch_reads_the_provider(self):
        page = object()
        stub = self._stub(browse_page=page)

        result = WavesBridge._browse_fetch.__get__(stub, type(stub))("Explore", "pages/explore")

        assert result is page
        assert stub._provider.calls == [("browse_page", "Explore", "pages/explore")]

    def test_the_home_rows_read_the_provider_and_drop_the_handles(self):
        stub = self._stub(browse_home=object())
        stub._page_rows = lambda page: [
            {"title": "Shelf", "more": "pages/data/x", "data": "d", "total": 5, "offset": 2, "modType": "m", "items": []}
        ]

        rows = WavesBridge._home_v2_rows.__get__(stub, type(stub))()

        assert stub._provider.calls == [("browse_home",)]
        assert rows == [{"title": "Shelf", "more": "", "items": []}]

    def test_a_browse_more_window_reads_the_provider(self):
        from waves.providers import BrowseWindow

        cat = SimpleNamespace(items=[object(), None])
        stub = self._stub(browse_window=BrowseWindow(category=cat, n=2, total=200))
        stub._logged_in = True
        stub._browse_loading = set()
        stub._browse_gen = 3
        stub._browse_card = lambda obj: {"id": "c1"}
        grown: list = []
        stub._browse_grow_cached = lambda *args: grown.append(args)
        stub.browseSectionMore = _Signal()

        WavesBridge.loadBrowseSectionMore.__get__(stub, type(stub))("key", "pages/data/x", 50, "pagedList", "Genre")

        assert stub._provider.calls == [("browse_window", "Genre", "pages/data/x", "pagedList", 50, 50)]
        (payload,) = stub.browseSectionMore.emits
        assert payload["items"] == [{"id": "c1"}]
        assert payload["more"] is True and payload["offset"] == 52
        assert grown  # the cached copies grew too

    def test_the_category_rest_loop_advances_by_the_raw_page_length(self):
        from tidalapi.playlist import Playlist

        from waves.providers import BrowseWindow

        pl1, pl2, other = Playlist.__new__(Playlist), Playlist.__new__(Playlist), object()
        windows = iter(
            [
                BrowseWindow(SimpleNamespace(items=[pl1, other]), 2, 9),
                BrowseWindow(SimpleNamespace(items=[pl2]), 1, 9),
                BrowseWindow(SimpleNamespace(items=[]), 0, 9),
            ]
        )
        stub = self._stub()
        stub._browse_gen = 1

        def window(*args):
            stub._provider.calls.append(("browse_window", *args))
            return next(windows)

        stub._provider.browse_window = window

        out = WavesBridge._category_page_rest.__get__(stub, type(stub))(
            {"n": 0, "total": 9, "data": "pages/data/x", "modType": "pagedList"}, gen=1
        )

        assert out == [pl1, pl2]  # the non-Playlist row is skipped, not counted short
        assert stub._provider.calls == [
            ("browse_window", "", "pages/data/x", "pagedList", 0),
            ("browse_window", "", "pages/data/x", "pagedList", 2),
            ("browse_window", "", "pages/data/x", "pagedList", 3),
        ]

    def test_a_refetch_resolves_through_get_object(self):
        obj = object()
        stub = self._stub(get_object=obj)
        stub._browse_gen = 2
        stub._refetch_inflight = set()
        stub._logged_in = True
        stub.downloadState = _Signal()
        stub._mediaRefetched = _Signal()
        stub._bump_download_groups = lambda *args: None
        remembered: list = []
        stub._remember = lambda kind, mid, o: remembered.append((kind, mid, o))
        stub._set_status = lambda text: stub.statuses.append(text)

        WavesBridge._refetch_for_download.__get__(stub, type(stub))("album", "42")

        assert stub._provider.calls == [("get_object", "album", "42")]
        assert remembered == [("album", "42", obj)]
        ((bucket, mid),) = stub._mediaRefetched.emits
        assert (bucket, mid) == ("album", "42")

    def test_a_failed_refetch_reports_the_row_failed(self):
        stub = self._stub(get_object=RuntimeError("gone"))
        stub._browse_gen = 2
        stub._refetch_inflight = set()
        stub._logged_in = True
        stub.downloadState = _Signal()
        stub._mediaRefetched = _Signal()
        bumps: list = []
        stub._bump_download_groups = lambda *args: bumps.append(args)
        stub._remember = lambda *args: None
        stub._set_status = lambda text: stub.statuses.append(text)

        WavesBridge._refetch_for_download.__get__(stub, type(stub))("album", "42")

        assert stub.downloadState.emits == [("42", "preparing"), ("42", "failed")]
        assert bumps == [("42", None, "failed")]

    def test_the_video_album_fallback_searches_tracks_through_the_provider(self):
        tr = SimpleNamespace(name="Selected Works", id="9", album=SimpleNamespace(id=5), artists=[SimpleNamespace(name="Artist")])
        stub = self._stub(search_tracks=[tr])
        remembered: list = []
        stub._remember = lambda kind, mid, o: remembered.append((kind, mid))

        album_id, track_id = WavesBridge._video_album_fallback.__get__(stub, type(stub))(
            "Selected Works (Official Video)", "Artist, Second Artist"
        )

        assert stub._provider.calls == [("search_tracks", "Selected Works artist", 10)]
        assert (album_id, track_id) == ("5", "9")
        assert remembered == [("track", "9")]

    def test_the_video_album_fallback_answers_empty_when_nothing_matches(self):
        stub = self._stub(search_tracks=[])

        assert WavesBridge._video_album_fallback.__get__(stub, type(stub))("Song", "Artist") == ("", "")


class _PreviewStub(_AuthStub):
    """The preview source's collaborators: the clip cache, the ffmpeg binary,
    the remux recorder."""

    def __init__(self, provider):
        super().__init__(provider)
        self._provider = provider
        self._preview_clips = {}
        self._remuxes: list[tuple] = []

    def _preview_ffmpeg_bin(self):
        return "/usr/bin/ffmpeg"

    def _remux_preview(self, ffmpeg, src, hls, whole):
        self._remuxes.append((src, hls, whole))
        return "/tmp/waves-test/out.m4a"

    def _remember_preview_clip(self, key, path):
        self.clip_key = key


class TestThePreviewRoad:
    def _run(self, stub, track, whole=True):
        return WavesBridge._preview_source.__get__(stub, type(stub))(track, whole)

    def test_a_bts_preview_hands_ffmpeg_the_single_file(self):
        from waves.providers import StreamInfo

        track = object()
        stub = _PreviewStub(_FakeProvider(resolve_preview=StreamInfo(urls=["file-src"], single_file=True)))

        url = self._run(stub, track)

        assert stub._provider.calls == [("resolve_preview", track)]
        assert stub._remuxes == [("file-src", None, True)]
        assert url == pathlib.Path("/tmp/waves-test/out.m4a").as_uri()

    def test_an_hls_preview_hands_ffmpeg_the_master_url(self):
        from waves.providers import StreamInfo

        stub = _PreviewStub(_FakeProvider(resolve_preview=StreamInfo(hls_url="hls-master")))

        self._run(stub, object())

        assert stub._remuxes == [(None, "hls-master", True)]

    def test_an_encrypted_stream_never_reaches_the_remux(self):
        from waves.providers import StreamInfo

        stub = _PreviewStub(_FakeProvider(resolve_preview=StreamInfo(encrypted=True)))

        with pytest.raises(RuntimeError, match="encrypted"):
            self._run(stub, object())
        assert stub._remuxes == []

    def test_an_unresolvable_stream_reports_the_preview_failed(self):
        from waves.providers import StreamInfo

        stub = _PreviewStub(_FakeProvider(resolve_preview=StreamInfo()))  # the all-default answer

        with pytest.raises(RuntimeError):
            self._run(stub, object())
        assert stub._remuxes == []

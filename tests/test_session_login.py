"""Regression tests for the cached-token launch login (``_try_token_login``).

Hermetic and Qt-free in the ``test_audit_backend.py`` style: the real, unbound
``WavesBridge`` method is bound onto a minimal stand-in whose collaborators are
fakes. ``_try_token_login`` dispatches a ``Worker`` to ``self.threadpool``; the
conftest ``_InlinePool`` runs it synchronously on the calling thread, and the
real ``Worker.run`` (which deliberately swallows and logs any exception so a
background crash cannot abort Qt) is exercised as shipped, so a raise inside the
worker behaves here exactly as it would in the app.

Covered bug: a corrupt ``page_cache.json`` made ``_load_page_cache`` raise
*before* the session-resolved latch was set, so ``sessionResolved`` never
flipped and the launch overlay latched on "Signing in…" forever. The latch now
lives in a ``finally`` and the page-cache warmup is guarded.

And the same bug once more on the OTHER login path. ``completeLogin`` ran its
whole post-success block outside any ``finally``: the identical corrupt cache
raised there too, so the busy spinner never cleared and the app went on showing
signed out over credentials the exchange had already saved. Restarting signed in
cleanly (the boot path above guards the same call), which made the hang look
random.

Since the Provider seam contract (ticket #22) both slots ask the provider for
the login work; the stand-ins answer through a recording fake and carry no
TIDAL object at all.
"""

from __future__ import annotations

from conftest import _InlinePool, _Signal

from waves.waves_ui.backend import WavesBridge


class _FakeLoginProvider:
    """The login surface of the provider, canned."""

    def __init__(self, *, resume_ok: bool = True, resume_raises: bool = False):
        self.resume_calls = 0
        self._resume_ok = resume_ok
        self._resume_raises = resume_raises

    def login_resume(self) -> bool:
        self.resume_calls += 1
        if self._resume_raises:
            raise ConnectionError("black-holed network")
        return self._resume_ok


class _LoginStub:
    """Stand-in carrying exactly what ``_try_token_login`` reads and writes."""

    def __init__(self, *, login_ok: bool, page_cache_raises: bool = False, login_raises: bool = False):
        self._page_cache_raises = page_cache_raises
        self._session_resolved = False
        self._logged_in_calls: list[bool] = []
        self._statuses: list[str] = []
        self._page_cache_loaded = False
        self._init_download_called = False
        self._prefetch_called = False
        self.sessionResolvedChanged = _Signal()
        self.threadpool = _InlinePool()
        self.providers = {
            "tidal": _FakeLoginProvider(resume_ok=login_ok, resume_raises=login_raises)
        }

    def _set_status(self, msg: str) -> None:
        self._statuses.append(msg)

    def _set_logged_in(self, value: bool) -> None:
        self._logged_in_calls.append(value)

    def _load_page_cache(self) -> None:
        if self._page_cache_raises:
            raise RuntimeError("corrupt page_cache.json")
        self._page_cache_loaded = True

    def _init_download(self) -> None:
        self._init_download_called = True

    def _prefetch_tile_art(self) -> None:
        self._prefetch_called = True


def _run(stub: _LoginStub) -> None:
    WavesBridge._try_token_login.__get__(stub, _LoginStub)()


def test_corrupt_page_cache_still_resolves_and_logs_in():
    # The bug: _load_page_cache raising stranded the login overlay forever.
    stub = _LoginStub(login_ok=True, page_cache_raises=True)

    _run(stub)

    assert stub._session_resolved is True, "the session latch must resolve even if the warmup raised"
    assert stub.sessionResolvedChanged.emits == [()], "sessionResolvedChanged must fire exactly once"
    assert stub._logged_in_calls == [True], "a successful login must still flip loggedIn despite a bad cache"
    assert "Signed in" in stub._statuses
    # A guarded warmup failure must not abort the post-login setup.
    assert stub._init_download_called is True
    assert stub._prefetch_called is True


def test_happy_path_resolves_logs_in_and_inits_download():
    stub = _LoginStub(login_ok=True)

    _run(stub)

    assert stub._page_cache_loaded is True
    assert stub._session_resolved is True
    assert stub.sessionResolvedChanged.emits == [()]
    assert stub._logged_in_calls == [True]
    assert stub._init_download_called is True
    assert stub._prefetch_called is True
    assert stub._statuses[-1] == "Signed in"


def test_login_failure_resolves_as_not_signed_in():
    stub = _LoginStub(login_ok=False)

    _run(stub)

    assert stub._session_resolved is True, "a failed login must still resolve the latch"
    assert stub.sessionResolvedChanged.emits == [()]
    assert stub._logged_in_calls == [], "loggedIn must not flip on a failed login"
    assert stub._init_download_called is False
    assert "Not signed in" in stub._statuses


def test_login_exception_resolves_as_not_signed_in():
    # login_resume raising (e.g. a transient network error) must not strand
    # the overlay either: it resolves as not-signed-in.
    stub = _LoginStub(login_ok=False, login_raises=True)

    _run(stub)

    assert stub._session_resolved is True
    assert stub.sessionResolvedChanged.emits == [()]
    assert stub._logged_in_calls == []
    assert "Not signed in" in stub._statuses


# --------------------------------------------------------------------------- #
# completeLogin: the pasted-URL path, which had no guard of its own.
# --------------------------------------------------------------------------- #
class _FakePkceProvider:
    """The PKCE half of the provider, canned."""

    def __init__(self, *, finalize_ok: bool = True, exchange_raises: bool = False):
        self.exchange_calls: list[str] = []
        self._finalize_ok = finalize_ok
        self._exchange_raises = exchange_raises

    def login_complete(self, redirect_url: str) -> bool:
        self.exchange_calls.append(redirect_url)
        if self._exchange_raises:
            raise ConnectionError("black-holed network")
        return self._finalize_ok


class _PkceStub:
    """Stand-in carrying exactly what ``completeLogin`` reads and writes."""

    def __init__(self, *, finalize_ok: bool = True, page_cache_raises: bool = False, exchange_raises: bool = False):
        self._page_cache_raises = page_cache_raises
        self._busy: list[bool] = []
        self._logged_in_calls: list[bool] = []
        self._statuses: list[str] = []
        self._page_cache_loaded = False
        self._init_download_called = False
        self._prefetch_called = False
        self.threadpool = _InlinePool()
        self.providers = {
            "tidal": _FakePkceProvider(finalize_ok=finalize_ok, exchange_raises=exchange_raises)
        }

    def _set_busy(self, value: bool) -> None:
        self._busy.append(value)

    def _set_status(self, msg: str) -> None:
        self._statuses.append(msg)

    def _set_logged_in(self, value: bool) -> None:
        self._logged_in_calls.append(value)

    def _load_page_cache(self) -> None:
        if self._page_cache_raises:
            raise RuntimeError("corrupt page_cache.json")
        self._page_cache_loaded = True

    def _init_download(self) -> None:
        self._init_download_called = True

    def _prefetch_tile_art(self) -> None:
        self._prefetch_called = True


def _complete(stub: _PkceStub, url: str = "https://tidal.com/cb?code=x") -> None:
    WavesBridge.completeLogin.__get__(stub, _PkceStub)(url)


def test_a_corrupt_page_cache_never_strands_the_pasted_url_sign_in():
    stub = _PkceStub(page_cache_raises=True)

    _complete(stub)

    assert stub._busy[-1] is False, "the spinner turned forever over a sign-in that had succeeded"
    assert stub._logged_in_calls == [True], "the credentials were saved; the app must show it"
    assert "Signed in" in stub._statuses
    assert stub._init_download_called is True
    assert stub._prefetch_called is True


def test_the_happy_path_signs_in_and_clears_the_spinner():
    stub = _PkceStub()

    _complete(stub)

    assert stub._page_cache_loaded is True
    assert stub._busy == [True, False]
    assert stub._logged_in_calls == [True]
    assert stub._statuses[-1] == "Signed in"


def test_a_refused_exchange_clears_the_spinner_and_says_so():
    stub = _PkceStub(finalize_ok=False)

    _complete(stub)

    assert stub._busy[-1] is False
    assert stub._logged_in_calls == []
    assert "Sign-in failed. Try again." in stub._statuses


def test_a_raising_exchange_clears_the_spinner_too():
    stub = _PkceStub(exchange_raises=True)

    _complete(stub)

    assert stub._busy[-1] is False
    assert stub._logged_in_calls == []
    assert "Sign-in failed. Try again." in stub._statuses


def test_a_raising_post_login_step_still_clears_the_spinner():
    """Anything in there: the engine build, the art prefetch, the cache."""
    stub = _PkceStub()
    stub._init_download = lambda: (_ for _ in ()).throw(RuntimeError("no ffmpeg"))

    _complete(stub)

    assert stub._busy[-1] is False
    assert stub._logged_in_calls == [True]


def test_an_empty_url_does_not_even_start():
    stub = _PkceStub()

    _complete(stub, "   ")

    assert stub._busy == [], "no spinner for a paste of nothing"
    assert stub._logged_in_calls == []

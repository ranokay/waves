"""Auth workers stay detached; GUI events follow account and attempt authority."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from threading import Event, Thread

import pytest
from providers.fakes import BareProvider

from waves.desktop import backend
from waves.desktop.providers import auth
from waves.desktop.providers.lifecycle import ProviderContexts, ProviderToken
from waves.providers.base import ProviderDescriptor


class _Signal:
    def __init__(self) -> None:
        self.emits: list[tuple] = []

    def emit(self, *values) -> None:
        self.emits.append(values)


class _Worker:
    def __init__(self, work: Callable[[], None]) -> None:
        self.work = work

    def run(self) -> None:
        self.work()


class _Pool:
    def __init__(self) -> None:
        self.pending: deque[_Worker] = deque()

    def start(self, worker: _Worker) -> None:
        self.pending.append(worker)

    def run_next(self) -> None:
        self.pending.popleft().run()


class _Candidate:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider
        self.begin_hook: Callable[[], None] | None = None
        self.validate_hook: Callable[[], None] | None = None
        self.validate_results = deque([True])
        self.persist_results = deque([True])
        self.payloads: list[str] = []
        self.validated = False
        self.persisted = 0
        self.rejected = 0
        self.discarded = False

    def begin(self) -> str:
        if self.begin_hook is not None:
            self.begin_hook()
        return f"https://{self.provider.id}.test/authorize"

    def validate(self, payload: str) -> bool:
        # Match the staged TIDAL helper: successful validation consumes its
        # code and cannot be repeated, even if publishing later fails.
        if self.validated:
            return False
        self.payloads.append(payload)
        if self.validate_hook is not None:
            self.validate_hook()
        self.validated = self.validate_results.popleft() if self.validate_results else True
        return self.validated

    def persist(self, commit_if_current: Callable[[Callable[[], None]], bool]) -> bool:
        if self.persist_results and not self.persist_results.popleft():
            return False

        def commit() -> None:
            self.persisted += 1
            self.provider.signed_in = True

        return commit_if_current(commit)

    def reject(self, commit_if_current: Callable[[Callable[[], None]], bool]) -> bool:
        return commit_if_current(lambda: setattr(self, "rejected", self.rejected + 1))

    def discard(self) -> None:
        self.discarded = True


class _Provider(BareProvider):
    def __init__(self, provider_id: str = "tidal") -> None:
        self.id = provider_id
        self.signed_in = False
        self.flow = "browser"
        self.created: list[_Candidate] = []
        self.creation_hook: Callable[[], None] | None = None
        self.candidate = _Candidate(self)

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(id=self.id, name=self.id, login_flow=self.flow)

    def create_login_attempt(self, *, resume=False, register_secrets=None) -> _Candidate:
        candidate = self.candidate
        if self.creation_hook is not None:
            self.creation_hook()
        self.created.append(candidate)
        return candidate


class _Bridge:
    def __init__(self, *providers: _Provider) -> None:
        self.providers = {provider.id: provider for provider in providers}
        self._provider_contexts = ProviderContexts()
        self._provider_login_attempts: dict[str, auth.ActiveLogin] = {}
        self._provider_cleanup_events: dict[str, Event] = {}
        self._providerLoginEvent = _Signal()
        self.threadpool = _Pool()
        self.providerLoginUrlReady = _Signal()
        self.loginUrlReady = _Signal()
        self.providerLoginFinished = _Signal()
        self.providerStateChanged = _Signal()
        self.sessionResolvedChanged = _Signal()
        self._tracked_sessions = frozenset({"tidal"})
        self._session_resolved = False
        self.busy: set[str] = set()
        self.statuses: list[str] = []
        self.logged_in: list[bool] = []
        self.initialized = 0
        self.prefetched = 0
        self.warmed: list[ProviderToken] = []
        self.warm_hook: Callable[[ProviderToken], None] | None = None

    def _set_login_busy(self, provider_id: str, value: bool) -> None:
        if value:
            self.busy.add(provider_id)
        else:
            self.busy.discard(provider_id)

    def _set_status(self, message: str) -> None:
        self.statuses.append(message)

    def _set_logged_in(self, value: bool) -> None:
        self.logged_in.append(value)

    def _init_download(self) -> None:
        self.initialized += 1

    def _prefetch_tile_art(self) -> None:
        self.prefetched += 1

    def _warm_provider_login_cache(self, token: ProviderToken) -> None:
        self.warmed.append(token)
        if self.warm_hook is not None:
            self.warm_hook(token)

    def deliver(self) -> auth.LoginEvent:
        event = self._providerLoginEvent.emits.pop(0)[0]
        auth.apply_login_event(self, event)
        return event


@pytest.fixture(autouse=True)
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "Worker", _Worker)


def _begin(bridge: _Bridge, provider_id: str = "tidal") -> None:
    auth.start_login(bridge, provider_id)
    bridge.threadpool.run_next()
    assert bridge.deliver().phase == "url"


def _blocked(started: Event, release: Event) -> None:
    started.set()
    assert release.wait(5), "test must release the fake account service"


@pytest.mark.parametrize("resume", [False, True])
def test_cancel_before_candidate_is_created_drops_work_and_resolves_pending_resume(resume):
    provider = _Provider()
    bridge = _Bridge(provider)
    auth.start_login(bridge, provider.id, resume=resume)
    auth.cancel_login(bridge, provider.id)
    bridge.threadpool.run_next()
    assert provider.created == []
    assert bridge._providerLoginEvent.emits == []
    assert bridge._provider_login_attempts == {}
    assert bridge.busy == set()
    assert bridge._session_resolved is resume


@pytest.mark.parametrize("phase", ["create", "begin", "validate"])
def test_cancellation_while_provider_blocks_never_waits_or_commits_late_candidate(phase):
    provider = _Provider()
    bridge = _Bridge(provider)
    started, release = Event(), Event()
    block = lambda: _blocked(started, release)
    if phase == "create":
        provider.creation_hook = block
        auth.start_login(bridge, provider.id)
    elif phase == "begin":
        provider.candidate.begin_hook = block
        auth.start_login(bridge, provider.id)
    else:
        _begin(bridge)
        provider.candidate.validate_hook = block
        auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    worker = Thread(target=bridge.threadpool.run_next)
    worker.start()
    cancelled = Event()
    canceller = Thread(target=lambda: (auth.cancel_login(bridge, provider.id), cancelled.set()))
    try:
        assert started.wait(5)
        canceller.start()
        assert cancelled.wait(2), "GUI cancellation must not wait for provider work"
        assert not provider.signed_in
        assert bridge.busy == set()
    finally:
        release.set()
        worker.join(5)
        if canceller.ident is not None:
            canceller.join(5)
    assert not worker.is_alive() and not canceller.is_alive()
    for _ in list(bridge._providerLoginEvent.emits):
        bridge.deliver()
    assert provider.candidate.persisted == 0
    assert provider.candidate.discarded
    assert bridge.providerLoginFinished.emits == []
    assert bridge.logged_in == []


def test_duplicate_submit_commits_once_and_warms_before_completion_event():
    provider = _Provider()
    bridge = _Bridge(provider)
    _begin(bridge)
    bridge.warm_hook = lambda _token: (
        pytest.fail("completion emitted before warmup") if bridge._providerLoginEvent.emits else None
    )
    auth.complete_login(bridge, provider.id, "  https://tidal.test/callback  ")
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    assert len(bridge.threadpool.pending) == 1
    bridge.threadpool.run_next()
    assert provider.candidate.payloads == ["https://tidal.test/callback"]
    assert provider.candidate.persisted == 1
    assert bridge.warmed == [ProviderToken("tidal", 0)]
    assert bridge.busy == {"tidal"}
    assert bridge.deliver().ok
    assert bridge.busy == set()
    assert bridge.providerLoginFinished.emits == [("tidal", True)]
    assert bridge.initialized == bridge.prefetched == 1


def test_late_candidate_cannot_replace_a_new_attempt_or_clear_its_busy_state():
    provider = _Provider()
    bridge = _Bridge(provider)
    old = provider.candidate
    started, release = Event(), Event()
    provider.creation_hook = lambda: _blocked(started, release)
    auth.start_login(bridge, provider.id)
    worker = Thread(target=bridge.threadpool.run_next)
    worker.start()
    try:
        assert started.wait(5)
        provider.creation_hook = None
        replacement = _Candidate(provider)
        provider.candidate = replacement
        _begin(bridge)
        current = bridge._provider_login_attempts[provider.id]
        auth.complete_login(bridge, provider.id, "https://tidal.test/replacement")
        assert bridge.busy == {provider.id}
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert old.discarded
    assert not replacement.discarded
    assert bridge._provider_login_attempts[provider.id] is current
    assert bridge._providerLoginEvent.emits == []
    assert bridge.busy == {provider.id}
    bridge.threadpool.run_next()
    assert bridge.deliver().ok
    assert old.persisted == 0
    assert replacement.persisted == 1


@pytest.mark.parametrize("failure", ["validation", "persistence"])
def test_retry_is_available_after_gui_failure_and_reuses_successful_validation(failure):
    provider = _Provider()
    bridge = _Bridge(provider)
    if failure == "validation":
        provider.candidate.validate_results = deque([False, True])
    else:
        provider.candidate.persist_results = deque([False, True])
    _begin(bridge)
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    bridge.threadpool.run_next()
    assert not provider.signed_in
    assert not auth.committed_account_current(bridge, provider.id)
    # Until the failure event is consumed, a delayed duplicate paste cannot
    # launch a retry whose busy state that old event would then clear.
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    assert len(bridge.threadpool.pending) == 0
    assert not bridge.deliver().ok
    assert bridge.busy == set()
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    bridge.threadpool.run_next()
    assert bridge.deliver().ok
    assert provider.candidate.persisted == 1
    assert len(provider.candidate.payloads) == (2 if failure == "validation" else 1)
    assert bridge.providerLoginFinished.emits == [("tidal", False), ("tidal", True)]


def test_provider_busy_and_completion_are_independent():
    tidal, paper = _Provider(), _Provider("paper")
    bridge = _Bridge(tidal, paper)
    _begin(bridge, "tidal")
    _begin(bridge, "paper")
    auth.complete_login(bridge, "tidal", "https://tidal.test/callback")
    auth.complete_login(bridge, "paper", "https://paper.test/callback")
    assert bridge.busy == {"tidal", "paper"}
    bridge.threadpool.run_next()
    bridge.deliver()
    assert bridge.busy == {"paper"}
    bridge.threadpool.run_next()
    bridge.deliver()
    assert bridge.busy == set()
    assert bridge.providerLoginFinished.emits == [("tidal", True), ("paper", True)]


@pytest.mark.parametrize("revoke", [False, True])
def test_cancel_after_credential_commit_preserves_account_truth_until_signout_revoke(revoke):
    provider = _Provider()
    bridge = _Bridge(provider)
    _begin(bridge)
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    bridge.threadpool.run_next()
    assert provider.signed_in
    auth.cancel_login(bridge, provider.id)
    if revoke:
        bridge._provider_contexts.revoke(provider.id)
    assert auth.committed_account_current(bridge, provider.id) is not revoke
    bridge.deliver()
    assert bridge.logged_in == ([] if revoke else [True])
    assert bridge.initialized == bridge.prefetched == (0 if revoke else 1)
    assert bridge.providerLoginFinished.emits == []


def test_cancel_during_warmup_preserves_commit_and_warmup_uses_captured_account_epoch():
    provider = _Provider()
    bridge = _Bridge(provider)
    _begin(bridge)
    started, release = Event(), Event()
    bridge.warm_hook = lambda _token: _blocked(started, release)
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    worker = Thread(target=bridge.threadpool.run_next)
    worker.start()
    cancelled = Event()
    canceller = Thread(target=lambda: (auth.cancel_login(bridge, provider.id), cancelled.set()))
    try:
        assert started.wait(5)
        assert provider.signed_in
        canceller.start()
        assert cancelled.wait(2), "warmup must not hold the provider authority lock"
    finally:
        release.set()
        worker.join(5)
        if canceller.ident is not None:
            canceller.join(5)
    assert not worker.is_alive() and not canceller.is_alive()
    assert bridge.warmed == [ProviderToken("tidal", 0)]
    bridge.deliver()
    assert bridge.logged_in == [True]
    assert bridge.providerLoginFinished.emits == []


def test_replacement_before_completion_revokes_committed_account_and_old_catalog_epoch():
    provider = _Provider()
    bridge = _Bridge(provider)
    bridge._end_provider_context = lambda provider_id, _reason: bridge._provider_contexts.revoke(provider_id)
    _begin(bridge)
    started, release = Event(), Event()
    bridge.warm_hook = lambda _token: _blocked(started, release)
    auth.complete_login(bridge, provider.id, "https://tidal.test/old-callback")
    worker = Thread(target=bridge.threadpool.run_next)
    worker.start()
    try:
        assert started.wait(5)
        old_catalog_token = bridge.warmed[0]
        assert provider.signed_in
        assert bridge.logged_in == [], "the committed account has not reached the GUI yet"
        assert auth.committed_account_current(bridge, provider.id)
        auth.cancel_login(bridge, provider.id)
        provider.candidate = _Candidate(provider)
        backend.WavesBridge.beginProviderLogin(bridge, provider.id)
        assert not bridge._provider_contexts.current(old_catalog_token)
        assert not auth.committed_account_current(bridge, provider.id)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert bridge.deliver().ok
    assert bridge.logged_in == [], "the revoked old account must not be published"
    assert bridge.providerLoginFinished.emits == []
    bridge.warm_hook = None
    bridge.threadpool.run_next()
    assert bridge.deliver().phase == "url"
    auth.complete_login(bridge, provider.id, "https://tidal.test/new-callback")
    bridge.threadpool.run_next()
    assert bridge.deliver().ok
    assert auth.committed_account_current(bridge, provider.id)
    assert bridge.logged_in == [True]


def test_replacement_cancels_pending_commit_before_account_truth_lookup(monkeypatch):
    provider = _Provider()
    bridge = _Bridge(provider)
    _begin(bridge)
    old = provider.candidate
    auth.complete_login(bridge, provider.id, "https://tidal.test/old-callback")

    def interleaved_account_read(bridge, provider_id: str) -> bool:
        current = auth.committed_account_current(bridge, provider_id)
        # Advance a pending worker after the GUI has read account truth but
        # before it registers the replacement attempt.
        bridge.threadpool.run_next()
        return current

    monkeypatch.setattr(backend, "committed_account_current", interleaved_account_read)
    provider.candidate = _Candidate(provider)
    backend.WavesBridge.beginProviderLogin(bridge, provider.id)
    assert old.persisted == 0
    assert not auth.committed_account_current(bridge, provider.id)
    assert not bridge.deliver().ok
    assert bridge.logged_in == []
    assert bridge.providerLoginFinished.emits == []
    bridge.threadpool.run_next()
    assert bridge.deliver().phase == "url"


def test_failed_cache_warmup_does_not_roll_back_committed_account_or_log_exception(caplog):
    provider = _Provider()
    bridge = _Bridge(provider)
    _begin(bridge)

    def corrupt_cache(_token: ProviderToken) -> None:
        raise ValueError("fixture private cache detail")

    bridge.warm_hook = corrupt_cache
    auth.complete_login(bridge, provider.id, "https://tidal.test/callback")
    bridge.threadpool.run_next()
    assert bridge.deliver().ok
    assert provider.signed_in
    assert "fixture private cache detail" not in caplog.text
    assert "Provider page cache could not warm" in caplog.text


def test_resume_rejection_resolves_once_and_does_not_offer_browser_retry():
    provider = _Provider()
    provider.candidate.validate_results = deque([False])
    bridge = _Bridge(provider)
    auth.start_login(bridge, provider.id, resume=True)
    bridge.threadpool.run_next()
    assert bridge.deliver().resume
    assert provider.candidate.rejected == 1
    assert provider.candidate.discarded
    assert not auth.committed_account_current(bridge, provider.id)
    assert bridge._provider_login_attempts == {}
    assert bridge._session_resolved
    assert bridge.statuses[-1] == "Not signed in"

"""Detached auth uses fake SDK requests and real private, atomic file writes."""

from __future__ import annotations

import datetime
import json
import os
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
import requests
import tidalapi

from waves import config as config_module
from waves.config import Settings
from waves.desktop.session import WavesTidal
from waves.model.cfg import Settings as SettingsModel
from waves.model.cfg import Token
from waves.providers import tidal_auth
from waves.providers.tidal_auth import TidalLoginAttempt

_SDKSession = tidalapi.Session
_REDIRECT = "https://login.example.test/callback?code=fixture-code"
_EXPIRY = datetime.datetime(2030, 1, 2, tzinfo=datetime.UTC)


class _FakeSession(_SDKSession):
    def __init__(self, config: tidalapi.Config) -> None:
        super().__init__(config)
        self.error: Exception | None = None
        self.valid = True
        self.processing: Callable[[], None] | None = None
        self.checked: Callable[[], None] | None = None
        self.load_calls: list[tuple[str, str, str | None, datetime.datetime | float | None, bool | None]] = []
        self.payloads: list[str] = []

    def pkce_login_url(self) -> str:
        return "https://login.example.test/authorize"

    def pkce_get_auth_token(self, url_redirect: str) -> dict[str, str | int]:
        self.payloads.append(url_redirect)
        if self.error is not None:
            raise self.error
        return {
            "token_type": "Bearer",
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    def process_auth_token(self, json: dict[str, str | int], is_pkce_token: bool = True) -> bool:
        if self.processing is not None:
            self.processing()
        self.token_type = str(json["token_type"])
        self.access_token = str(json["access_token"])
        self.refresh_token = str(json["refresh_token"])
        self.expiry_time = _EXPIRY
        self.session_id = "new-session"
        self.is_pkce = is_pkce_token
        return True

    def load_oauth_session(
        self,
        token_type: str,
        access_token: str,
        refresh_token: str | None = None,
        expiry_time: datetime.datetime | None = None,
        is_pkce: bool | None = False,
    ) -> bool:
        self.load_calls.append((token_type, access_token, refresh_token, expiry_time, is_pkce))
        if self.error is not None:
            raise self.error
        self.token_type = token_type
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expiry_time = expiry_time
        self.session_id = "resumed-session"
        self.is_pkce = bool(is_pkce)
        return self.valid

    def check_login(self) -> bool:
        if self.checked is not None:
            self.checked()
        if self.error is not None:
            raise self.error
        return self.valid


@pytest.fixture
def sessions(monkeypatch: pytest.MonkeyPatch) -> list[_FakeSession]:
    made: list[_FakeSession] = []

    def factory(config: tidalapi.Config) -> _FakeSession:
        session = _FakeSession(config)
        made.append(session)
        return session

    def no_request(*_args, **_kwargs) -> None:
        pytest.fail("staged-auth tests must never make a live request")

    monkeypatch.setattr(tidal_auth.tidalapi, "Session", factory)
    monkeypatch.setattr(requests.Session, "send", no_request)
    return made


def _owner(tmp_path: Path) -> WavesTidal:
    owner = WavesTidal.__new__(WavesTidal)
    owner.data = Token(token_type="Bearer", access_token="old-access", refresh_token="old-refresh", expiry_time=1000.0)  # noqa: S106
    owner.file_path = str(tmp_path / "token.json")
    owner.path_base = str(tmp_path)
    owner._keep_file_untouched = False
    owner.persistence_frozen = False
    owner.token_from_storage = True
    owner.is_pkce = True
    owner.is_atmos_session = True
    owner.stream_lock = Lock()
    owner.original_client_id = "normal-client"
    owner.original_client_secret = "normal-client-secret"  # noqa: S105
    owner.original_client_id_pkce = "normal-pkce-client"
    owner.original_client_secret_pkce = "normal-pkce-secret"  # noqa: S105
    owner.session = _FakeSession(tidalapi.Config())
    owner.session.access_token = "old-access"  # noqa: S105
    owner.session.config.client_id = "atmos-client"
    owner.session.audio_quality = tidalapi.Quality.low_320k
    settings = Settings.__new__(Settings)
    settings.data = SettingsModel(tidal_quality_audio="LOSSLESS")
    owner.settings = settings
    Path(owner.file_path).write_text(owner.data.to_json(), encoding="utf-8")
    return owner


def _commit(write: Callable[[], None]) -> bool:
    write()
    return True


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError("fixture response", response=response)


def test_attempt_constructs_only_detached_sdk_and_preserves_normal_pairs_and_quality(tmp_path, sessions, monkeypatch):
    owner = _owner(tmp_path)
    live = owner.session
    saved = owner.data.to_json()

    def no_singleton(*_args, **_kwargs):
        pytest.fail("a login attempt must not construct a singleton owner")

    monkeypatch.setattr(config_module.SingletonMeta, "__call__", no_singleton)
    attempt = TidalLoginAttempt(owner)
    candidate = sessions[-1]
    assert attempt.begin() == "https://login.example.test/authorize"
    assert candidate is not live
    assert candidate.config.item_limit == 10000
    assert candidate.config.client_id == "normal-client"
    assert candidate.config.client_secret == "normal-client-secret"  # noqa: S105
    assert candidate.config.client_id_pkce == "normal-pkce-client"
    assert candidate.config.client_secret_pkce == "normal-pkce-secret"  # noqa: S105
    assert candidate.audio_quality == tidalapi.Quality.high_lossless
    assert candidate.video_quality == tidalapi.VideoQuality.high
    assert candidate.request_session.adapters["https://"].max_retries.allowed_methods == frozenset({"GET", "HEAD"})
    assert owner.session is live
    assert owner.data.to_json() == saved


@pytest.mark.parametrize(
    "payload", ["", " ", "http://login.example.test/?code=x", "a pasted secret", "https:///missing-host"]
)
def test_blank_or_non_https_paste_never_reaches_sdk(tmp_path, sessions, payload, caplog):
    owner = _owner(tmp_path)
    attempt = TidalLoginAttempt(owner)
    assert attempt.validate(payload) is False
    assert sessions[-1].payloads == []
    assert caplog.text == ""


def test_candidate_secrets_registered_before_process_and_check_and_listener_after_commit(tmp_path, sessions):
    owner = _owner(tmp_path)
    facts: list[dict[str, str]] = []
    attempt = TidalLoginAttempt(owner, register_secrets=facts.append)
    candidate = sessions[-1]
    events: list[str] = []

    def processing() -> None:
        assert facts[0]["access_token"] == "new-access"  # noqa: S105
        assert facts[0]["refresh_token"] == "new-refresh"  # noqa: S105
        events.append("process")

    def checked() -> None:
        assert facts[-1]["session_id"] == "new-session"
        events.append("check")

    candidate.processing = processing
    candidate.checked = checked
    guard_lock = Lock()

    def listener() -> None:
        assert guard_lock.acquire(blocking=False), "the listener must run outside the provider guard"
        guard_lock.release()
        assert owner.stream_lock.acquire(blocking=False), "the listener must run outside the engine lock"
        owner.stream_lock.release()
        assert owner.session is candidate
        events.append("listener")

    owner.on_session_credentials = listener

    def guarded(write: Callable[[], None]) -> bool:
        with guard_lock:
            events.append("commit")
            write()
        return True

    assert attempt.validate(_REDIRECT) is True
    assert owner.session is not candidate
    assert attempt.persist(guarded) is True
    assert events == ["process", "check", "commit", "listener"]
    assert owner.token_from_storage is True
    assert owner.is_atmos_session is False
    assert owner.is_pkce is True
    assert owner.original_client_id == candidate.config.client_id
    assert owner.original_client_secret == candidate.config.client_secret
    assert owner.original_client_id_pkce == candidate.config.client_id_pkce
    assert owner.original_client_secret_pkce == candidate.config.client_secret_pkce
    assert json.loads(Path(owner.file_path).read_text())["expiry_time"] == _EXPIRY.timestamp()
    attempt.discard()
    assert owner.session is candidate


def test_private_staging_preserves_json_format_and_rejected_commit_leaves_old_owner(tmp_path, sessions):
    owner = _owner(tmp_path)
    live, old = owner.session, Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)
    assert attempt.validate(_REDIRECT)

    def refuse(_write: Callable[[], None]) -> bool:
        staged = list(tmp_path.glob("token.json.*.tmp"))
        assert len(staged) == 1
        if os.name != "nt":
            assert stat.S_IMODE(staged[0].stat().st_mode) == 0o600
        assert '\n    "access_token": "new-access"' in staged[0].read_text()
        assert Path(owner.file_path).read_bytes() == old
        return False

    assert attempt.persist(refuse) is False
    assert owner.session is live
    assert Path(owner.file_path).read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []


def test_validation_can_be_cancelled_while_network_is_blocked(tmp_path, sessions):
    owner = _owner(tmp_path)
    live, old = owner.session, Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)
    started, release = Event(), Event()

    def checked() -> None:
        started.set()
        assert release.wait(5), "test must release the simulated request"

    sessions[-1].checked = checked
    results: list[bool] = []
    worker = Thread(target=lambda: results.append(attempt.validate(_REDIRECT)))
    worker.start()
    try:
        assert started.wait(5)
        attempt.discard()
        assert owner.session is live
        assert Path(owner.file_path).read_bytes() == old
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results == [False]
    assert attempt.persist(_commit) is False
    assert owner.session is live
    assert Path(owner.file_path).read_bytes() == old


def test_fsync_is_outside_guard_and_cancellation_during_flush_cleans_staging(tmp_path, sessions, monkeypatch):
    owner = _owner(tmp_path)
    live, old = owner.session, Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)
    assert attempt.validate(_REDIRECT)
    started, release = Event(), Event()
    guard_lock = Lock()
    commits: list[str] = []
    fsync = os.fsync

    def blocked_fsync(fd: int) -> None:
        started.set()
        assert release.wait(5), "test must release the simulated fsync"
        fsync(fd)

    def guarded(write: Callable[[], None]) -> bool:
        with guard_lock:
            commits.append("commit")
            write()
        return True

    monkeypatch.setattr(config_module.os, "fsync", blocked_fsync)
    results: list[bool] = []
    worker = Thread(target=lambda: results.append(attempt.persist(guarded)))
    worker.start()
    try:
        assert started.wait(5)
        assert guard_lock.acquire(blocking=False)
        guard_lock.release()
        attempt.discard()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results == [False]
    assert commits == []
    assert owner.session is live
    assert Path(owner.file_path).read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_restore_finishes_before_commit_without_holding_authority(tmp_path, sessions, monkeypatch, cancel):
    owner = _owner(tmp_path)
    live, old = owner.session, Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)
    assert attempt.validate(_REDIRECT)
    staged = Event()
    active = Event()
    active.set()
    authority = Lock()
    fsync = os.fsync

    def note_fsync(fd: int) -> None:
        fsync(fd)
        staged.set()

    def guarded(write: Callable[[], None]) -> bool:
        with authority:
            if not active.is_set():
                return False
            write()
        return True

    monkeypatch.setattr(config_module.os, "fsync", note_fsync)
    results: list[bool] = []
    owner.stream_lock.acquire()
    worker = Thread(target=lambda: results.append(attempt.persist(guarded)))
    worker.start()
    try:
        assert staged.wait(5), "staging must finish before waiting for the engine lock"
        assert authority.acquire(blocking=False), "the GUI authority must stay free while the engine drains"
        authority.release()
        assert owner.session is live
        if cancel:
            active.clear()
            attempt.discard()
        # An old Atmos job's finally block restores only its old live session.
        owner.session.config.client_id = "restored-old-client"
        owner.original_client_id = "restored-old-client"
    finally:
        owner.stream_lock.release()
        worker.join(5)
    assert not worker.is_alive()
    assert results == [not cancel]
    assert list(tmp_path.glob("*.tmp")) == []
    if cancel:
        assert owner.session is live
        assert Path(owner.file_path).read_bytes() == old
    else:
        assert owner.session is sessions[-1]
        assert owner.session.config.client_id == "normal-client"
        assert owner.original_client_id == "normal-client"


@pytest.mark.parametrize("failure", ["validate", "fsync", "replace"])
def test_failure_preserves_live_session_and_saved_credentials(tmp_path, sessions, monkeypatch, failure):
    owner = _owner(tmp_path)
    live, saved = owner.session, replace(owner.data)
    old = Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)

    def failed_io(*_args) -> None:
        raise OSError("fixture I/O failure")

    if failure == "validate":
        sessions[-1].valid = False
        assert attempt.validate(_REDIRECT) is False
    else:
        assert attempt.validate(_REDIRECT)
        monkeypatch.setattr(config_module.os, failure, failed_io)
    assert attempt.persist(_commit) is False
    assert owner.session is live
    assert owner.data == saved
    assert Path(owner.file_path).read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("protected", ["persistence_frozen", "_keep_file_untouched"])
def test_protected_store_blocks_adoption_and_save_even_when_guard_allows(tmp_path, sessions, protected):
    owner = _owner(tmp_path)
    live, old = owner.session, Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner)
    assert attempt.validate(_REDIRECT)

    def guarded(write: Callable[[], None]) -> bool:
        setattr(owner, protected, True)
        write()
        return True

    assert attempt.persist(guarded) is False
    assert owner.session is live
    assert Path(owner.file_path).read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []


def test_resume_uses_captured_token_and_ignores_payload(tmp_path, sessions):
    owner = _owner(tmp_path)
    owner.is_pkce = False
    attempt = TidalLoginAttempt(owner, resume=True)
    candidate = sessions[-1]
    assert attempt.begin() == ""
    owner.data.access_token = "changed-access"  # noqa: S105
    assert attempt.validate("ignored redirect") is True
    assert candidate.payloads == []
    assert candidate.load_calls == [("Bearer", "old-access", "old-refresh", 1000.0, False)]
    assert attempt.persist(_commit) is False, "a replaced saved snapshot must not be republished"
    assert owner.data.access_token == "changed-access"  # noqa: S105


@pytest.mark.parametrize("status", [401, 403])
def test_refused_resume_deletes_only_in_current_commit(tmp_path, sessions, status):
    owner = _owner(tmp_path)
    live = owner.session
    attempt = TidalLoginAttempt(owner, resume=True)
    sessions[-1].error = _http_error(status)
    assert attempt.validate("ignored") is False
    assert Path(owner.file_path).exists()
    assert attempt.reject(lambda _write: False) is False
    assert Path(owner.file_path).exists()
    assert attempt.reject(_commit) is True
    assert not Path(owner.file_path).exists()
    assert owner.token_from_storage is False
    assert owner.session is live


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_unanswered_resume_keeps_prior_credentials(tmp_path, sessions, status):
    owner = _owner(tmp_path)
    old = Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner, resume=True)
    sessions[-1].error = _http_error(status)
    assert attempt.validate("ignored") is False
    assert attempt.reject(_commit) is False
    assert Path(owner.file_path).read_bytes() == old
    assert owner.token_from_storage is True


@pytest.mark.parametrize("error", [requests.exceptions.Timeout("fixture timeout"), KeyError("sessionId")])
def test_network_or_malformed_resume_keeps_prior_credentials(tmp_path, sessions, error):
    owner = _owner(tmp_path)
    old = Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner, resume=True)
    sessions[-1].error = error
    assert attempt.validate("ignored") is False
    assert attempt.reject(_commit) is False
    assert Path(owner.file_path).read_bytes() == old


@pytest.mark.parametrize("cause", ["cancelled", "changed", "probe", "frozen", "protected"])
def test_refusal_cannot_delete_a_cancelled_replaced_or_protected_sign_in(tmp_path, sessions, cause):
    owner = _owner(tmp_path)
    old = Path(owner.file_path).read_bytes()
    attempt = TidalLoginAttempt(owner, resume=True)
    sessions[-1].error = _http_error(401)
    assert attempt.validate("ignored") is False
    if cause == "cancelled":
        attempt.discard()
    elif cause == "changed":
        owner.data.refresh_token = "replacement-refresh"  # noqa: S105
    elif cause == "probe":
        owner._sign_in_at_stake = False
    elif cause == "frozen":
        owner.persistence_frozen = True
    else:
        owner._keep_file_untouched = True
    assert attempt.reject(_commit) is False
    assert Path(owner.file_path).read_bytes() == old


def test_positive_refusal_in_exception_chain_and_secret_sink_failures_are_handled(tmp_path, sessions):
    owner = _owner(tmp_path)

    def broken_sink(_facts: dict[str, str]) -> None:
        raise RuntimeError("fixture listener failure")

    attempt = TidalLoginAttempt(owner, resume=True, register_secrets=broken_sink)
    outer = requests.exceptions.JSONDecodeError("fixture malformed response", "fixture", 0)
    outer.__context__ = _http_error(403)
    sessions[-1].error = outer
    assert attempt.validate("ignored") is False
    assert attempt.reject(_commit) is True


def test_saved_success_and_legacy_listener_failure_still_publish(tmp_path, sessions):
    owner = _owner(tmp_path)
    attempt = TidalLoginAttempt(owner, resume=True)

    def broken_listener() -> None:
        raise RuntimeError("fixture listener failure")

    owner.on_session_credentials = broken_listener
    assert attempt.validate("ignored") is True
    assert attempt.persist(_commit) is True
    assert owner.session is sessions[-1]
    assert owner.token_from_storage is True
    assert json.loads(Path(owner.file_path).read_text())["access_token"] == "old-access"  # noqa: S105

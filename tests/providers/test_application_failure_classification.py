"""Owner classification keeps recovery boundaries and diagnostic copy apart."""

from collections.abc import Callable
from threading import Event
from types import SimpleNamespace

import pytest
from providers.fakes import BareProvider
from requests import HTTPError, Response
from tidalapi.exceptions import AuthenticationError, ObjectNotFound, TooManyRequests, UnknownManifestFormat

from waves.desktop.providers import auth
from waves.desktop.providers.lifecycle import ProviderContexts
from waves.events import ApplicationEvent, EventAction, EventCode, EventDomain, Failure, FailureScope, Lifecycle
from waves.providers.apple import runner
from waves.providers.apple.engine import (
    AppleCredential,
    AppleCredentialsError,
    AppleIntegrityError,
    AppleTrackUnavailable,
    AppleVariantUnavailable,
    AppleWrapperDown,
)
from waves.providers.apple.engines import EngineFailure, EngineRouteUnavailable
from waves.providers.apple.engines import FailureScope as EngineFailureScope
from waves.providers.apple.provider import AppleCatalogUnavailable, AppleCollectionIncomplete, AppleProvider
from waves.providers.base import Provider
from waves.providers.tidal import TidalProvider

_PRIVATE = "token=account-secret-value /Users/private-account/cookies.txt"


@pytest.mark.parametrize("provider", [BareProvider(), TidalProvider.__new__(TidalProvider), AppleProvider()])
@pytest.mark.parametrize("text", [_PRIVATE, "rate limited 429", "Apple runtime unavailable", "AuthenticationError 401"])
def test_unclassified_text_never_establishes_an_independent_failure_boundary(provider: Provider, text: str) -> None:
    failure = provider.classify_failure(RuntimeError(text))
    assert failure.scope == FailureScope.UNKNOWN
    assert failure.code == EventCode.FAILED
    assert not failure.retryable
    assert text not in failure.summary


@pytest.mark.parametrize(
    ("error", "scope", "code"),
    [
        (AuthenticationError(_PRIVATE), FailureScope.ACCOUNT, EventCode.ACCOUNT_REQUIRED),
        (TooManyRequests(_PRIVATE), FailureScope.UNKNOWN, EventCode.RATE_LIMITED),
        (ObjectNotFound(_PRIVATE), FailureScope.ITEM, EventCode.UNAVAILABLE),
        (UnknownManifestFormat(_PRIVATE), FailureScope.ENGINE, EventCode.PROTOCOL_INCOMPATIBLE),
    ],
)
def test_tidal_owns_concrete_failure_types(error: BaseException, scope: FailureScope, code: EventCode) -> None:
    failure = TidalProvider.__new__(TidalProvider).classify_failure(error)
    assert (failure.scope, failure.code) == (scope, code)
    assert _PRIVATE not in failure.summary


@pytest.mark.parametrize(
    ("status", "body", "scope", "code"),
    [
        (
            401,
            b'{"subStatus":11001,"userMessage":"token=account-secret-value"}',
            FailureScope.ACCOUNT,
            EventCode.ACCOUNT_REQUIRED,
        ),
        (
            403,
            b'{"subStatus":4005,"userMessage":"token=account-secret-value"}',
            FailureScope.ITEM,
            EventCode.UNAVAILABLE,
        ),
        (429, b"", FailureScope.UNKNOWN, EventCode.RATE_LIMITED),
        (503, b"", FailureScope.PROVIDER, EventCode.FAILED),
    ],
)
def test_tidal_response_facts_distinguish_account_and_item_refusals(
    status: int, body: bytes, scope: FailureScope, code: EventCode
) -> None:
    response = Response()
    response.status_code = status
    response._content = body
    failure = TidalProvider.__new__(TidalProvider).classify_failure(HTTPError(_PRIVATE, response=response))
    assert (failure.scope, failure.code) == (scope, code)
    assert "account-secret-value" not in failure.summary


@pytest.mark.parametrize(
    ("error", "scope", "code"),
    [
        (AppleCredentialsError(_PRIVATE), FailureScope.ACCOUNT, EventCode.ACCOUNT_REQUIRED),
        (AppleWrapperDown(_PRIVATE), FailureScope.RUNTIME, EventCode.FAILED),
        (AppleIntegrityError(_PRIVATE), FailureScope.ENGINE, EventCode.INTEGRITY_FAILED),
        (AppleVariantUnavailable(_PRIVATE), FailureScope.ENGINE, EventCode.UNAVAILABLE),
        (AppleTrackUnavailable(_PRIVATE), FailureScope.ITEM, EventCode.UNAVAILABLE),
        (AppleCatalogUnavailable(), FailureScope.PROVIDER, EventCode.PROTOCOL_INCOMPATIBLE),
        (AppleCollectionIncomplete(_PRIVATE), FailureScope.PROVIDER, EventCode.FAILED),
        (EngineRouteUnavailable(_PRIVATE), FailureScope.CONFIGURATION, EventCode.INVALID_CONFIGURATION),
    ],
)
def test_apple_owns_concrete_failure_types(error: BaseException, scope: FailureScope, code: EventCode) -> None:
    failure = AppleProvider().classify_failure(error)
    assert (failure.scope, failure.code) == (scope, code)
    assert "account-secret-value" not in failure.summary


def test_account_failure_identifies_the_required_apple_credential() -> None:
    provider = AppleProvider()
    cookies = provider.classify_failure(AppleCredentialsError(_PRIVATE))
    wrapper = provider.classify_failure(AppleCredentialsError(_PRIVATE, credential=AppleCredential.WRAPPER))
    assert cookies.runtime_id == "apple:cookies-client"
    assert wrapper.runtime_id == "apple:wrapper-v2"
    assert "cookies" in cookies.summary and "wrapper" in wrapper.summary


def test_engine_failure_contract_keeps_its_compatibility_identity_and_safe_verdict() -> None:
    assert EngineFailureScope is FailureScope
    failure = AppleProvider().classify_failure(
        EngineRouteUnavailable(
            _PRIVATE, failure=EngineFailure("incompatible_client", FailureScope.ENGINE, "gamdl", "apple:wrapper-v2")
        )
    )
    assert failure.code == EventCode.PROTOCOL_INCOMPATIBLE
    assert (failure.engine_id, failure.runtime_id) == ("gamdl", "apple:wrapper-v2")
    assert _PRIVATE not in failure.summary


def test_repeated_apple_holds_and_recovery_use_one_job_lifecycle() -> None:
    events: list[ApplicationEvent] = []
    hooks = runner.AppleJobHooks(provider=AppleProvider, event=events.append)
    for _ in range(3):
        runner.set_held(hooks, 12)
    account = AppleProvider().classify_failure(AppleCredentialsError(_PRIVATE))
    runner.set_held(hooks, 12, _PRIVATE)
    runner._publish_job_failure(hooks, 12, account)
    runner._resolve_job_event(hooks, 12)
    assert len({event.id for event in events}) == 1
    assert all(event.references.job_id == 12 for event in events)
    assert events[-2].scope == FailureScope.ACCOUNT
    assert EventAction.OPEN_SETTINGS in events[-2].actions
    assert EventAction.RETRY_JOB not in events[-2].actions
    assert events[-1].lifecycle == Lifecycle.RESOLVED and events[-1].actions == ()
    assert "account-secret-value" not in str([event.payload() for event in events])


def test_apple_final_classification_survives_explicit_setup_wrapping() -> None:
    hooks = runner.AppleJobHooks(provider=AppleProvider)
    account = AppleProvider().classify_failure(AppleCredentialsError(_PRIVATE))
    original = runner._AppleSetupRequired(_PRIVATE, failure=account)
    from waves.errors import DownloadIncomplete

    wrapped = DownloadIncomplete(_PRIVATE)
    wrapped.__cause__ = original
    failure = runner._classified_failure(hooks, wrapped)
    assert failure.scope == FailureScope.ACCOUNT and failure.retryable
    assert failure.runtime_id == "apple:cookies-client"


def test_apple_event_failure_does_not_interrupt_existing_held_state() -> None:
    statuses: list[tuple[int, str, str]] = []

    def broken_event(_event: ApplicationEvent) -> None:
        raise RuntimeError("event relay gone")

    hooks = runner.AppleJobHooks(
        event=broken_event, queue_status=lambda qid, state, reason: statuses.append((qid, state, reason))
    )
    runner.set_held(hooks, 8)
    assert statuses[0][:2] == (8, "queued")


def test_apple_job_failure_is_classified_after_queue_settlement(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[ApplicationEvent] = []
    statuses: list[tuple] = []
    finished: list[int] = []
    failure = Failure(FailureScope.ENGINE, EventCode.INTEGRITY_FAILED, "Verification failed.", retryable=True)

    def failed_download(*_args, **_kwargs) -> str:
        raise runner._AppleJobIncomplete("token=account-secret-value", failure)

    monkeypatch.setattr(runner, "run_apple_job", failed_download)
    hooks = runner.AppleJobHooks(
        provider=lambda: None,
        event=events.append,
        queue_status=lambda *args: statuses.append(args),
        finish_job=finished.append,
    )
    spec = SimpleNamespace(kind="track", file_template="", collection=False, media_id="apple:1")
    runner.run_job_body(hooks, 11, spec, None, signals=None, job_abort=Event(), row_ask=None, name="Example")
    assert statuses[-1][1] == "failed" and finished == [11]
    assert len(events) == 1
    assert events[0].scope == FailureScope.ENGINE and events[0].code == EventCode.INTEGRITY_FAILED
    assert events[0].references.job_id == 11
    assert EventAction.RETRY_JOB in events[0].actions
    assert "account-secret-value" not in events[0].copy_text()


def test_login_event_publishes_only_current_failure_and_resolves_committed_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[ApplicationEvent] = []
    guards: list[Callable[[], bool] | None] = []
    resolved: list[tuple[EventDomain, str]] = []

    def publish(_bridge, event: ApplicationEvent, valid: Callable[[], bool] | None = None) -> None:
        emitted.append(event)
        guards.append(valid)

    def resolve(_bridge, domain: EventDomain, *, provider_id: str, valid: Callable[[], bool]) -> None:
        if valid():
            resolved.append((domain, provider_id))

    from waves.desktop.diagnostics import events as delivery

    monkeypatch.setattr(delivery, "publish_event", publish)
    monkeypatch.setattr(delivery, "resolve_events", resolve)
    contexts = ProviderContexts()
    token = contexts.start_login("paper")
    signal = SimpleNamespace(emit=lambda *_args: None)
    bridge = SimpleNamespace(
        _provider_contexts=contexts,
        _provider_login_attempts={"paper": auth.ActiveLogin(token)},
        _set_login_busy=lambda *_args: None,
        _set_status=lambda *_args: None,
        providerLoginFinished=signal,
        providerStateChanged=signal,
    )
    auth.apply_login_event(bridge, auth.LoginEvent(token, "complete"))
    assert len(emitted) == 1 and emitted[0].scope == FailureScope.ACCOUNT
    assert emitted[0].actions == (EventAction.RECONNECT, EventAction.OPEN_SETTINGS)
    assert guards[0] is not None and guards[0]()
    contexts.revoke("paper")
    assert not guards[0]()
    auth.apply_login_event(bridge, auth.LoginEvent(token, "failed_start"))
    assert len(emitted) == 1
    current = contexts.start_login("paper")
    auth.apply_login_event(bridge, auth.LoginEvent(current, "complete", ok=True))
    assert resolved == [(EventDomain.ACCOUNT, "paper")]

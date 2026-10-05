"""Provider-scoped desktop auth; candidates and credentials stay provider-owned."""

from __future__ import annotations

import contextlib
import dataclasses
import logging
from collections.abc import Callable

from waves import redaction
from waves.constants import CTX_TIDAL
from waves.desktop.providers.lifecycle import ProviderToken, provider_contexts
from waves.desktop.worker import Worker
from waves.events import EventAction, EventCode, EventDomain, EventReferences, FailureScope, application_event
from waves.providers.base import LoginAttempt, Provider

logger = logging.getLogger("waves.providers.auth")


@dataclasses.dataclass
class ActiveLogin:
    token: ProviderToken
    candidate: LoginAttempt | None = None
    resume: bool = False
    submitted: bool = False
    validated: bool = False


@dataclasses.dataclass(frozen=True)
class LoginEvent:
    token: ProviderToken
    phase: str
    url: str = ""
    ok: bool = False
    resume: bool = False


def _register_secrets(facts: dict[str, str]) -> None:
    for key, value in facts.items():
        if value:
            redaction.register_secret(
                value, {"account_id": "‹account›", "username": "‹email›", "session_id": "‹session›"}.get(key, "‹token›")
            )


def committed_account_current(bridge, provider_id: str) -> bool:
    """Read committed account truth before its queued GUI event arrives."""
    token = getattr(bridge, "_provider_committed_accounts", {}).get(provider_id)
    return token is not None and provider_contexts(bridge).current(token)


def _commit_account(bridge, token: ProviderToken, callback: Callable[[], None]) -> bool:
    published = False

    def commit() -> None:
        nonlocal published
        if getattr(bridge, "_factory_reset", False):
            return
        callback()
        published = True
        if not hasattr(bridge, "_provider_committed_accounts"):
            bridge._provider_committed_accounts = {}
        bridge._provider_committed_accounts[token.provider_id] = dataclasses.replace(token, attempt=None)

    return provider_contexts(bridge).commit(token, commit) and published


def start_login(bridge, provider_id: str, *, resume: bool = False) -> None:
    if getattr(bridge, "_factory_reset", False):
        return
    provider = bridge.providers.get(provider_id)
    if provider is None or (not resume and provider.descriptor().login_flow != "browser"):
        return
    contexts = provider_contexts(bridge)
    token = contexts.start_login(provider_id)
    if not hasattr(bridge, "_provider_login_attempts"):
        bridge._provider_login_attempts = {}
    previous = bridge._provider_login_attempts.pop(provider_id, None)
    if previous is not None and not previous.submitted:
        _discard(previous.candidate)
    # Register the request before scheduling: cancel can resolve a pending
    # resume even while its candidate constructor or cleanup barrier waits.
    active = ActiveLogin(token, resume=resume, submitted=resume)
    if not contexts.commit(token, lambda: bridge._provider_login_attempts.__setitem__(provider_id, active)):
        return
    bridge._set_login_busy(provider_id, resume)
    bridge.threadpool.start(Worker(lambda: _begin_login_work(bridge, provider, active)))


def _discard(candidate: LoginAttempt | None) -> None:
    if candidate is not None:
        with contextlib.suppress(Exception):
            candidate.discard()


def _begin_login_work(bridge, provider: Provider, active: ActiveLogin) -> None:
    contexts = provider_contexts(bridge)
    token = active.token
    candidate = None
    try:
        cleanup = getattr(bridge, "_provider_cleanup_events", {}).get(token.provider_id)
        while cleanup is not None and not cleanup.wait(0.05):
            if not contexts.current(token):
                return
        if not contexts.current(token):
            return
        candidate = provider.create_login_attempt(resume=active.resume, register_secrets=_register_secrets)
        if not contexts.commit(token, lambda: setattr(active, "candidate", candidate)):
            _discard(candidate)
            return
        if active.resume:
            _validate(bridge, active, "")
        else:
            url = candidate.begin()
            if contexts.current(token):
                bridge._providerLoginEvent.emit(LoginEvent(token, "url", url=url))
            else:
                _discard(candidate)
    except Exception:
        # Provider exceptions may contain pasted payloads or minted tokens.
        logger.warning("Provider sign-in could not start")
        _discard(candidate)
        bridge._providerLoginEvent.emit(LoginEvent(token, "failed_start", resume=active.resume))


def complete_login(bridge, provider_id: str, payload: str) -> None:
    active = getattr(bridge, "_provider_login_attempts", {}).get(provider_id)
    if active is None or active.candidate is None or active.submitted or not payload.strip():
        return
    contexts = provider_contexts(bridge)
    if not contexts.commit(active.token, lambda: setattr(active, "submitted", True)):
        return
    bridge._set_login_busy(provider_id, True)
    bridge.threadpool.start(Worker(lambda: _validate(bridge, active, payload.strip())))


def _validate(bridge, active: ActiveLogin, payload: str) -> None:
    contexts = provider_contexts(bridge)
    ok = False
    candidate = active.candidate
    if candidate is None:
        return
    try:
        if not contexts.current(active.token):
            return
        accepted = active.validated or candidate.validate(payload)
        if accepted:
            # A one-time code already exchanged successfully must not be
            # exchanged again just because publishing its token file failed.
            active.validated = True
            ok = candidate.persist(lambda callback: _commit_account(bridge, active.token, callback))
            if ok:
                warm = getattr(bridge, "_warm_provider_login_cache", None)
                if warm is not None:
                    try:
                        warm(dataclasses.replace(active.token, attempt=None))
                    except Exception:
                        logger.warning("Provider page cache could not warm")
        elif active.resume:
            candidate.reject(lambda callback: contexts.commit(active.token, callback))
    except Exception:
        logger.warning("Provider sign-in failed")
    finally:
        if ok or not contexts.current(active.token) or active.resume or getattr(bridge, "_factory_reset", False):
            _discard(candidate)
        # Failed submissions remain latched until the GUI consumes this
        # event, so its queued failure cannot clear a newer retry's busy flag.
        bridge._providerLoginEvent.emit(LoginEvent(active.token, "complete", ok=ok, resume=active.resume))


def cancel_login(bridge, provider_id: str) -> None:
    """Invalidate immediately; a network worker never holds the GUI's lock."""
    provider_contexts(bridge).cancel_login(provider_id)
    active = getattr(bridge, "_provider_login_attempts", {}).pop(provider_id, None)
    if active is not None and not active.submitted:
        _discard(active.candidate)
    bridge._set_login_busy(provider_id, False)
    if active is not None and active.resume:
        bridge._session_resolved = True
        bridge.sessionResolvedChanged.emit()


def _publish_account(bridge, event: LoginEvent) -> None:
    """Account truth follows the credential commit's epoch, beyond form cancel."""
    account_token = dataclasses.replace(event.token, attempt=None)
    if not event.ok or not provider_contexts(bridge).current(account_token):
        return
    from waves.desktop.diagnostics.events import resolve_events

    resolve_events(
        bridge,
        EventDomain.ACCOUNT,
        provider_id=event.token.provider_id,
        valid=lambda: provider_contexts(bridge).current(account_token),
    )
    if event.token.provider_id in getattr(bridge, "_tracked_sessions", ()):
        bridge._set_logged_in(True)
    bridge.providerStateChanged.emit(event.token.provider_id)
    if event.token.provider_id == CTX_TIDAL:
        for setup in (bridge._init_download, bridge._prefetch_tile_art):
            try:
                setup()
            except Exception:
                logger.warning("Provider post-login setup could not finish")


def apply_login_event(bridge, event: LoginEvent) -> None:
    """GUI thread: commit only the result still owned by this request."""
    if getattr(bridge, "_factory_reset", False):
        return
    contexts = provider_contexts(bridge)
    current = contexts.current(event.token)
    if event.phase == "url":
        if current:
            bridge.providerLoginUrlReady.emit(event.token.provider_id, event.url)
            if event.token.provider_id == CTX_TIDAL:
                bridge.loginUrlReady.emit(event.url)
            bridge._set_status("Finish signing in, then paste the URL back")
        return
    # A cancellation after the credential commit cannot undo a completed
    # account. Account publication follows its epoch; optional form effects
    # still follow the auth attempt. Sign-out revokes both.
    _publish_account(bridge, event)
    active = getattr(bridge, "_provider_login_attempts", {}).get(event.token.provider_id)
    if not current or active is None or active.token != event.token:
        return
    if event.ok or event.resume or event.phase == "failed_start":
        getattr(bridge, "_provider_login_attempts", {}).pop(event.token.provider_id, None)
    else:
        active.submitted = False
    bridge._set_login_busy(event.token.provider_id, False)
    if event.resume:
        bridge._session_resolved = True
        bridge.sessionResolvedChanged.emit()
    bridge._set_status("Signed in" if event.ok else "Not signed in" if event.resume else "Sign-in failed. Try again.")
    if not event.ok:
        from waves.desktop.diagnostics.events import publish_event

        publish_event(
            bridge,
            application_event(
                EventDomain.ACCOUNT,
                "Sign-in could not finish. Reconnect your account in Settings.",
                key=event.token.provider_id,
                code=EventCode.ACCOUNT_REQUIRED,
                scope=FailureScope.ACCOUNT,
                references=EventReferences(provider_id=event.token.provider_id),
                actions=(EventAction.RECONNECT, EventAction.OPEN_SETTINGS),
            ),
            valid=lambda: contexts.current(event.token),
        )
    bridge.providerLoginFinished.emit(event.token.provider_id, event.ok)

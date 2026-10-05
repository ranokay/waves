"""Bridge-owned queued event delivery and applicability checks, without disk I/O."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot

from waves.desktop.providers.lifecycle import ProviderToken
from waves.events import (
    ApplicationEvent,
    EventAction,
    EventCode,
    EventDomain,
    EventReferences,
    Failure,
    FailureScope,
    Lifecycle,
    application_event,
)
from waves.redaction import scrub_event_text


@dataclass(frozen=True)
class _Delivery:
    event: ApplicationEvent
    valid: Callable[[], bool] | None = None


@dataclass(frozen=True)
class _Resolution:
    domain: EventDomain
    provider_id: str
    job_id: int | None
    valid: Callable[[], bool] | None = None
    identity: str = ""


class ApplicationEvents(QObject):
    """One GUI-thread action index; persistent notification history has its own owner.

    Publishing always queues. No worker mutates the index or invokes an action.
    Owners supply a generation/account/job guard checked at delivery and again
    when an action is requested. Only active events retain actionable context.
    """

    changed = Signal(dict)
    submitted = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: dict[str, _Delivery] = {}
        self._occurrences: dict[str, int] = {}
        self._closed = False
        self.submitted.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    def publish(self, event: ApplicationEvent, valid: Callable[[], bool] | None = None) -> None:
        if not self._closed:
            with contextlib.suppress(RuntimeError):  # QObject may be gone after a bounded quit drain.
                self.submitted.emit(_Delivery(event, valid))

    def resolve(
        self,
        domain: EventDomain,
        provider_id: str = "",
        job_id: int | None = None,
        valid: Callable[[], bool] | None = None,
        *,
        identity: str = "",
    ) -> None:
        if not self._closed:
            with contextlib.suppress(RuntimeError):
                self.submitted.emit(_Resolution(domain, provider_id, job_id, valid, identity))

    @Slot(object)
    def _receive(self, delivery: _Delivery | _Resolution) -> None:
        if self._closed or (delivery.valid is not None and not delivery.valid()):
            return
        if isinstance(delivery, _Resolution):
            for identity, active in tuple(self._active.items()):
                refs = active.event.references
                if (
                    active.event.domain == delivery.domain
                    and (not delivery.identity or identity == delivery.identity)
                    and (not delivery.provider_id or refs.provider_id == delivery.provider_id)
                    and (delivery.job_id is None or refs.job_id == delivery.job_id)
                ):
                    self.finish(identity)
            return
        event = delivery.event
        self._occurrences[event.id] = self._occurrences.get(event.id, 0) + 1
        if event.lifecycle == Lifecycle.ACTIVE:
            self._active[event.id] = delivery
        else:
            self._active.pop(event.id, None)
        self._emit(event)
        if event.lifecycle != Lifecycle.ACTIVE:
            self._occurrences.pop(event.id, None)

    def _emit(self, event: ApplicationEvent) -> None:
        self.changed.emit({**event.payload(), "occurrences": self._occurrences.get(event.id, 1)})

    def action(self, identity: str, action: str) -> ApplicationEvent | None:
        delivery = self._active.get(identity)
        try:
            command = EventAction(action)
        except ValueError:
            return None
        if delivery is None or command not in delivery.event.actions:
            return None
        if delivery.valid is not None and not delivery.valid():
            self.finish(identity, Lifecycle.RESOLVED)
            return None
        return delivery.event

    def finish(self, identity: str, lifecycle: Lifecycle = Lifecycle.RESOLVED) -> None:
        delivery = self._active.pop(identity, None)
        if delivery is not None:
            self._emit(delivery.event.finish(lifecycle))
            self._occurrences.pop(identity, None)

    def close(self) -> None:
        self._closed = True
        self._active.clear()
        self._occurrences.clear()


class EventHost(Protocol):
    _events: ApplicationEvents

    def _set_status(self, message: str) -> None: ...


def _owner_guard(bridge: EventHost, valid: Callable[[], bool] | None) -> Callable[[], bool] | None:
    token = getattr(getattr(bridge, "_catalog_thread", None), "token", None)
    contexts = getattr(bridge, "_provider_contexts", None)
    if isinstance(token, ProviderToken) and contexts is not None:
        return lambda: contexts.current(token) and (valid is None or valid())
    return valid


def publish_event(bridge: EventHost, event: ApplicationEvent, valid: Callable[[], bool] | None = None) -> None:
    relay = getattr(bridge, "_events", None)
    if relay is not None:
        relay.publish(event, _owner_guard(bridge, valid))


def resolve_events(
    bridge: EventHost,
    domain: EventDomain,
    *,
    provider_id: str = "",
    job_id: int | None = None,
    valid: Callable[[], bool] | None = None,
    key: str = "",
) -> None:
    relay = getattr(bridge, "_events", None)
    if relay is not None:
        valid = _owner_guard(bridge, valid)
        if key:
            relay.resolve(domain, provider_id, job_id, valid, identity=application_event(domain, "", key=key).id)
        else:
            relay.resolve(domain, provider_id, job_id, valid)


def catalog_succeeded(bridge: EventHost, *, key: str = "") -> None:
    """Owners mark a successful result; unrelated or merely started work cannot recover it."""
    if key:
        resolve_events(bridge, EventDomain.PROVIDER, key=key)
    else:
        context = getattr(bridge, "_catalog_thread", None)
        if isinstance(getattr(context, "event_key", None), str):
            context.event_success = True


def report_failure(
    bridge: EventHost,
    domain: EventDomain,
    summary: str,
    *,
    scope: FailureScope = FailureScope.UNKNOWN,
    code: EventCode = EventCode.FAILED,
    exception: BaseException | None = None,
    references: EventReferences | None = None,
    key: str = "",
    retryable: bool = False,
    valid: Callable[[], bool] | None = None,
    actions: tuple[EventAction, ...] = (EventAction.OPEN_LOGS, EventAction.COPY_DIAGNOSTICS),
) -> ApplicationEvent:
    context = getattr(bridge, "_catalog_thread", None)
    operation_key = getattr(context, "event_key", "")
    if domain == EventDomain.PROVIDER and isinstance(operation_key, str) and operation_key:
        context.event_failed = True
        key = key or operation_key
    if references is None:
        token = getattr(getattr(bridge, "_catalog_thread", None), "token", None)
        references = (
            EventReferences(provider_id=token.provider_id) if isinstance(token, ProviderToken) else EventReferences()
        )
    event = application_event(
        domain,
        summary,
        scope=scope,
        code=code,
        exception=exception,
        references=references,
        key=key,
        retryable=retryable,
        actions=actions,
    )
    publish_event(bridge, event, valid)
    return event


def provider_failure_event(
    provider,
    domain: EventDomain,
    exception: BaseException,
    *,
    key: str = "",
    job_id: int | None = None,
    media_id: str = "",
    provider_id: str = "",
) -> ApplicationEvent:
    """Use only the provider owner's classification, never a shared text heuristic."""
    classify = getattr(provider, "classify_failure", None)
    failure = classify(exception) if classify is not None else Failure()
    if not isinstance(failure, Failure):
        failure = Failure()
    provider_id = provider_id or getattr(provider, "id", "")
    actions = (EventAction.OPEN_LOGS, EventAction.COPY_DIAGNOSTICS)
    if failure.scope == FailureScope.ACCOUNT:
        actions = (EventAction.RECONNECT, EventAction.COPY_DIAGNOSTICS)
    elif failure.scope == FailureScope.CONFIGURATION:
        actions = (EventAction.OPEN_SETTINGS, EventAction.COPY_DIAGNOSTICS)
    elif failure.retryable and job_id is not None:
        actions = (EventAction.RETRY_JOB, *actions)
    return application_event(
        domain,
        failure.summary,
        key=key or provider_id,
        code=failure.code,
        scope=failure.scope,
        exception=exception,
        retryable=failure.retryable,
        references=EventReferences(
            provider_id=provider_id,
            engine_id=failure.engine_id,
            runtime_id=failure.runtime_id,
            job_id=job_id,
            media_id=media_id,
        ),
        actions=actions,
    )


def status_failure(bridge: EventHost, domain: EventDomain, summary: str, **kwargs) -> None:
    """Retain the existing status consumer while publishing the owner's error event."""
    event = report_failure(bridge, domain, summary, **kwargs)
    bridge._set_status(event.summary)


def operation_state(
    bridge: EventHost,
    domain: EventDomain,
    signal_name: str,
    state: str,
    message: str,
    *,
    exception: BaseException | None = None,
) -> None:
    """Install/update owners share safe delivery while retaining their existing signals."""
    message = scrub_event_text(message)
    if state in {"failed", "remove_failed"}:
        report_failure(
            bridge,
            domain,
            message,
            key=signal_name,
            exception=exception,
            scope=FailureScope.CONFIGURATION if isinstance(exception, OSError) else FailureScope.UNKNOWN,
            actions=(EventAction.OPEN_SETTINGS, EventAction.COPY_DIAGNOSTICS),
        )
    elif state in {"done", "cancelled"}:
        resolve_events(bridge, domain, key=signal_name)
    getattr(bridge, signal_name).emit(state, message)

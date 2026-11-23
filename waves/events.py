"""Small, Qt-free application events. Only redacted values leave this owner."""

from __future__ import annotations

import hashlib
import re
import traceback
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TypedDict

from waves.redaction import scrub_event_text


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class EventDomain(StrEnum):
    PROVIDER = "provider"
    ACCOUNT = "account"
    SEARCH = "search"
    DOWNLOAD = "download"
    LIBRARY = "library"
    UPDATE = "update"
    DEPENDENCY = "dependency"
    RUNTIME = "runtime"
    CONFIGURATION = "configuration"
    DIAGNOSTICS = "diagnostics"


class FailureScope(StrEnum):
    PROVIDER = "provider"
    ACCOUNT = "account"
    RUNTIME = "runtime"
    ENGINE = "engine"
    ITEM = "item"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class EventCode(StrEnum):
    FAILED = "operation_failed"
    ACCOUNT_REQUIRED = "account_required"
    UNAVAILABLE = "item_unavailable"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_MISSING = "dependency_missing"
    PATH_UNREACHABLE = "path_unreachable"
    INVALID_CONFIGURATION = "invalid_configuration"
    INTEGRITY_FAILED = "integrity_failed"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    COMPLETED = "completed"


class Lifecycle(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EventAction(StrEnum):
    OPEN_SETTINGS = "open_settings"
    RECONNECT = "reconnect"
    RETRY_JOB = "retry_job"
    COPY_DIAGNOSTICS = "copy_diagnostics"
    OPEN_LOGS = "open_logs"


@dataclass(frozen=True)
class EventReferences:
    provider_id: str = ""
    engine_id: str = ""
    runtime_id: str = ""
    job_id: int | None = None
    media_id: str = ""

    def __post_init__(self) -> None:
        for key in ("provider_id", "engine_id", "runtime_id", "media_id"):
            object.__setattr__(self, key, scrub_event_text(getattr(self, key)))
        if self.job_id is not None and (type(self.job_id) is not int or self.job_id < 0):
            raise ValueError("Event job identity must be a nonnegative integer")  # noqa: TRY003


@dataclass(frozen=True)
class Failure:
    """An owner's verdict. Unknown scope grants no independent-engine recovery."""

    scope: FailureScope = FailureScope.UNKNOWN
    code: EventCode = EventCode.FAILED
    summary: str = "The operation could not finish. Try again or open the logs."
    retryable: bool = False
    engine_id: str = ""
    runtime_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", FailureScope(self.scope))
        object.__setattr__(self, "code", EventCode(self.code))
        for key in ("summary", "engine_id", "runtime_id"):
            object.__setattr__(self, key, scrub_event_text(getattr(self, key)))


class ReferencePayload(TypedDict):
    provider_id: str
    engine_id: str
    runtime_id: str
    job_id: int | None
    media_id: str


class EventPayload(TypedDict):
    id: str
    code: str
    severity: str
    domain: str
    scope: str
    title: str
    summary: str
    details: list[str]
    diagnostics: str
    references: ReferencePayload
    retryable: bool
    lifecycle: str
    actions: list[str]


@dataclass(frozen=True)
class ApplicationEvent:
    """Safe to present, serialize or copy immediately after construction.

    Identity is opaque: a deduplication key may name a private path/account,
    but that input is never retained. Actions contain commands, never URLs,
    arbitrary callbacks or shell text.
    """

    id: str
    domain: EventDomain
    code: EventCode
    title: str
    summary: str
    severity: Severity = Severity.ERROR
    scope: FailureScope = FailureScope.UNKNOWN
    references: EventReferences = field(default_factory=EventReferences)
    retryable: bool = False
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    details: tuple[str, ...] = ()
    diagnostics: str = ""
    actions: tuple[EventAction, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-f0-9]{32}", self.id) is None:
            raise ValueError("Event identity must be an opaque digest")  # noqa: TRY003
        for key, enum in (
            ("domain", EventDomain),
            ("code", EventCode),
            ("severity", Severity),
            ("scope", FailureScope),
            ("lifecycle", Lifecycle),
        ):
            object.__setattr__(self, key, enum(getattr(self, key)))
        for key in ("title", "summary", "diagnostics"):
            object.__setattr__(self, key, scrub_event_text(getattr(self, key)))
        object.__setattr__(self, "details", tuple(scrub_event_text(value) for value in self.details))
        actions = tuple(dict.fromkeys(EventAction(value) for value in self.actions))
        object.__setattr__(self, "actions", actions if self.lifecycle == Lifecycle.ACTIVE else ())

    def finish(self, lifecycle: Lifecycle = Lifecycle.RESOLVED) -> ApplicationEvent:
        if lifecycle == Lifecycle.ACTIVE:
            raise ValueError("Finishing an event requires a terminal lifecycle")  # noqa: TRY003
        return replace(self, lifecycle=lifecycle, actions=())

    def payload(self) -> EventPayload:
        """Re-scrub at export as credentials may have been learned since creation."""
        refs = self.references
        return EventPayload(
            id=self.id,
            code=self.code.value,
            severity=self.severity.value,
            domain=self.domain.value,
            scope=self.scope.value,
            title=scrub_event_text(self.title),
            summary=scrub_event_text(self.summary),
            details=[scrub_event_text(value) for value in self.details],
            diagnostics=scrub_event_text(self.diagnostics),
            references=ReferencePayload(
                provider_id=scrub_event_text(refs.provider_id),
                engine_id=scrub_event_text(refs.engine_id),
                runtime_id=scrub_event_text(refs.runtime_id),
                job_id=refs.job_id,
                media_id=scrub_event_text(refs.media_id),
            ),
            retryable=self.retryable,
            lifecycle=self.lifecycle.value,
            actions=[value.value for value in self.actions],
        )

    def copy_text(self) -> str:
        payload = self.payload()
        return "\n".join((payload["title"], payload["summary"], *payload["details"], payload["diagnostics"])).strip()


def application_event(
    domain: EventDomain,
    summary: str,
    *,
    key: str = "",
    code: EventCode = EventCode.FAILED,
    title: str = "",
    severity: Severity = Severity.ERROR,
    scope: FailureScope = FailureScope.UNKNOWN,
    references: EventReferences | None = None,
    retryable: bool = False,
    details: tuple[str, ...] = (),
    exception: BaseException | None = None,
    actions: tuple[EventAction, ...] = (),
    lifecycle: Lifecycle = Lifecycle.ACTIVE,
) -> ApplicationEvent:
    refs = references or EventReferences()
    owner_key = key or f"{code.value}:{refs.provider_id}:{refs.runtime_id}:{refs.job_id}:{refs.media_id}"
    identity = hashlib.sha256(f"{domain.value}:{owner_key}".encode()).hexdigest()[:32]
    diagnostics = "".join(traceback.format_exception(exception)) if exception is not None else ""
    return ApplicationEvent(
        identity,
        domain,
        code,
        title or domain.value.title(),
        summary,
        severity,
        scope,
        refs,
        retryable,
        lifecycle,
        details,
        diagnostics,
        actions,
    )

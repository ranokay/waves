"""Subordinate Apple execution contracts and deterministic route selection.

Catalog and account identity remain on AppleProvider. This seam selects one
attempt; bounded recovery and persistent request policies have separate owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event
from typing import Protocol

from waves.constants import QualityTier
from waves.providers.base import AudioType, ReadinessState, StreamInfo


class EngineOperation(StrEnum):
    AUDIO = "audio"
    LYRICS = "lyrics"
    ARTWORK = "artwork"


class FailureScope(StrEnum):
    ENGINE = "engine"
    RUNTIME = "runtime"
    ACCOUNT = "account"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EnginePolicy:
    """Order is a preference; a pin admits only that engine."""

    preferences: tuple[str, ...] = ("gamdl",)
    pin: str = ""

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(value.strip().lower() for value in self.preferences if value.strip()))
        pin = self.pin.strip().lower()
        object.__setattr__(self, "preferences", normalized)
        object.__setattr__(self, "pin", "" if pin == "auto" else pin)


@dataclass(frozen=True)
class EngineRequest:
    operation: EngineOperation
    media: dict
    tier: QualityTier = QualityTier.HIGH
    audio_type: AudioType = AudioType.STEREO
    abort: Event = field(default_factory=Event, compare=False)
    required_codec: str = ""
    artwork_dimension: int = 1280
    artwork_original: bool = False
    lyrics_format: str = "converted"


@dataclass(frozen=True)
class EngineFacts:
    """Cached setup facts, never an instruction to probe protected media."""

    enabled: bool | None = None
    cookies_ready: bool | None = None
    wrapper_ready: bool | None = None
    fetch_ready: bool | None = None
    protocol_compatible: bool | None = None
    wrapper_runtime_ready: bool | None = None


@dataclass(frozen=True)
class EngineRequirement:
    operation: EngineOperation
    codecs: tuple[str, ...]
    audio_types: tuple[AudioType, ...]
    tiers: tuple[QualityTier, ...]
    runtime: str
    runtime_kind: str
    account_boundary: str
    protocol: str = ""
    formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineDescriptor:
    id: str
    name: str
    requirements: tuple[EngineRequirement, ...]
    client: str
    compatible_versions: str
    # An operation is Recommended only with a published qualification record.
    recommendations: tuple[tuple[EngineOperation, str], ...] = ()

    @property
    def operations(self) -> frozenset[EngineOperation]:
        return frozenset(requirement.operation for requirement in self.requirements)


@dataclass(frozen=True)
class EngineReadiness:
    state: ReadinessState
    runtime: str = ""
    account_boundary: str = ""
    action: str = ""


@dataclass(frozen=True)
class EngineFailure:
    code: str
    scope: FailureScope
    engine: str
    runtime: str = ""
    account_boundary: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class EngineResult:
    value: StreamInfo | tuple[str, str] | str | None = None
    failure: EngineFailure | None = None
    # Preserve the concrete error for the existing runner's holds/quarantine.
    # Exceptions never cross the desktop presentation boundary.
    error: Exception | None = None


class AppleEngine(Protocol):
    descriptor: EngineDescriptor

    def supports(self, request: EngineRequest) -> bool: ...
    def readiness(self, request: EngineRequest, facts: EngineFacts) -> EngineReadiness: ...
    def execute(self, request: EngineRequest) -> EngineResult: ...
    def cancel(self, request: EngineRequest) -> None: ...


class EngineRouteUnavailable(RuntimeError):
    """The pin or request has no eligible route; selection never relaxes it."""


class EngineRouter:
    """An Apple-owned, statically supplied set of engines. No plugin discovery."""

    def __init__(self, engines: tuple[AppleEngine, ...]) -> None:
        self.engines = {engine.descriptor.id: engine for engine in engines}
        if len(self.engines) != len(engines):
            raise ValueError("Apple engine identities must be unique")  # noqa: TRY003

    def select(self, request: EngineRequest, policy: EnginePolicy, facts: EngineFacts | None = None) -> AppleEngine:
        if policy.pin:
            order = (policy.pin,)
        else:
            recommended = tuple(
                engine.descriptor.id
                for engine in self.engines.values()
                if any(
                    operation == request.operation and evidence
                    for operation, evidence in engine.descriptor.recommendations
                )
            )
            order = tuple(dict.fromkeys((*policy.preferences, *recommended, *self.engines)))
        for identity in order:
            engine = self.engines.get(identity)
            if engine is None or not engine.supports(request):
                continue
            state = engine.readiness(request, facts or EngineFacts()).state
            # Direct callers without setup evidence retain concrete engine
            # validation. Known failures still exclude an engine; desktop
            # dispatch supplies facts and admits only a ready route.
            if state != ReadinessState.READY and not (facts is None and state == ReadinessState.UNKNOWN):
                continue
            return engine
        raise EngineRouteUnavailable("The selected Apple engine cannot serve this request. Review Apple Music setup.")  # noqa: TRY003

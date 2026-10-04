"""Wrap the eligible gamdl route, including its cookies and wrapper-v2 paths."""

from __future__ import annotations

from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from waves.constants import QualityTier
from waves.providers.apple.engines import (
    EngineDescriptor,
    EngineFacts,
    EngineFailure,
    EngineOperation,
    EngineReadiness,
    EngineRequest,
    EngineRequirement,
    EngineResult,
    FailureScope,
)
from waves.providers.base import AudioType, ReadinessState, RefusalKind, StreamInfo

if TYPE_CHECKING:
    from waves.providers.apple.provider import AppleProvider


@cache
def gamdl_version() -> str:
    try:
        return version("gamdl")
    except PackageNotFoundError:
        return ""


def compatible_gamdl(value: str) -> bool:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError:
        return False
    return len(parts) == 3 and (3, 8, 5) <= parts < (3, 9, 0)


class GamdlEngine:
    descriptor = EngineDescriptor(
        "gamdl",
        "gamdl",
        (
            EngineRequirement(
                EngineOperation.AUDIO,
                ("aac", "eac3"),
                (AudioType.STEREO, AudioType.ATMOS),
                (QualityTier.HIGH,),
                "apple:cookies-client",
                "built_in",
                "apple:cookies",
            ),
            EngineRequirement(
                EngineOperation.AUDIO,
                ("alac",),
                (AudioType.STEREO,),
                (QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS),
                "apple:wrapper-v2",
                "external",
                "apple:wrapper-session",
                "wrapper-v2",
            ),
            EngineRequirement(
                EngineOperation.LYRICS, (), (), (), "apple:catalog-client", "built_in", "apple:catalog-account"
            ),
            EngineRequirement(EngineOperation.ARTWORK, (), (), (), "apple:catalog-client", "built_in", ""),
        ),
        "gamdl",
        ">=3.8.5,<3.9",
    )

    def __init__(self, provider: AppleProvider) -> None:
        self.provider = provider

    def supports(self, request: EngineRequest) -> bool:
        if request.operation not in self.descriptor.operations:
            return False
        if request.operation != EngineOperation.AUDIO:
            return not request.required_codec
        if request.audio_type not in (AudioType.STEREO, AudioType.ATMOS):
            return False
        if not request.required_codec:
            return True
        codec = request.required_codec.lower()
        return codec in (("eac3",) if request.audio_type == AudioType.ATMOS else ("aac", "alac")) and (
            codec != "alac" or request.tier in (QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS)
        )

    def requirement(self, request: EngineRequest) -> EngineRequirement:
        if request.operation == EngineOperation.AUDIO:
            codec = request.required_codec.lower()
            wrapper = codec == "alac" or (
                codec != "aac"
                and request.audio_type == AudioType.STEREO
                and request.tier in (QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS)
                and self.provider.wrapper_available
            )
            return self.descriptor.requirements[1 if wrapper else 0]
        return next(item for item in self.descriptor.requirements if item.operation == request.operation)

    def readiness(self, request: EngineRequest, facts: EngineFacts) -> EngineReadiness:
        if not self.supports(request):
            return EngineReadiness(ReadinessState.UNSUPPORTED)
        requirement = self.requirement(request)
        state, action = ReadinessState.READY, ""
        if facts.enabled is False:
            state, action = ReadinessState.DISABLED, "setup"
        elif facts.enabled is None:
            state = ReadinessState.UNKNOWN
        elif request.operation != EngineOperation.ARTWORK and not compatible_gamdl(gamdl_version()):
            state, action = ReadinessState.SETUP_REQUIRED, "update"
        elif request.operation == EngineOperation.ARTWORK:
            pass
        elif request.operation == EngineOperation.LYRICS:
            account = (
                True
                if True in (facts.cookies_ready, facts.wrapper_ready)
                else False
                if facts.cookies_ready is False and facts.wrapper_ready is False
                else None
            )
            state = (
                ReadinessState.READY
                if account
                else ReadinessState.SIGN_IN_REQUIRED
                if account is False
                else ReadinessState.UNKNOWN
            )
            action = "signin" if state == ReadinessState.SIGN_IN_REQUIRED else ""
        else:
            account = facts.wrapper_ready if requirement.protocol else facts.cookies_ready
            if account is not True:
                state = ReadinessState.SIGN_IN_REQUIRED if account is False else ReadinessState.UNKNOWN
                action = "signin" if account is False else ""
            elif requirement.protocol and facts.protocol_compatible is not True:
                state = ReadinessState.SETUP_REQUIRED if facts.protocol_compatible is False else ReadinessState.UNKNOWN
                action = "update" if facts.protocol_compatible is False else ""
            elif facts.fetch_ready is not True:
                state = ReadinessState.SETUP_REQUIRED if facts.fetch_ready is False else ReadinessState.UNKNOWN
                action = "setup" if facts.fetch_ready is False else ""
        return EngineReadiness(state, requirement.runtime, requirement.account_boundary, action)

    def cancel(self, request: EngineRequest) -> None:
        request.abort.set()

    def execute(self, request: EngineRequest) -> EngineResult:
        if not self.supports(request):
            return EngineResult(failure=EngineFailure("unsupported_request", FailureScope.ENGINE, self.descriptor.id))
        requirement = self.requirement(request)
        try:
            self._check_cancelled(request)
            if request.operation != EngineOperation.ARTWORK and not compatible_gamdl(gamdl_version()):
                return EngineResult(
                    failure=EngineFailure("incompatible_client", FailureScope.ENGINE, self.descriptor.id)
                )
            if request.operation == EngineOperation.AUDIO:
                value = self.provider._resolve_gamdl_stream(
                    request.media, request.tier, request.audio_type, required_codec=request.required_codec.lower()
                )
            elif request.operation == EngineOperation.LYRICS:
                value = self.provider.fetch_lyrics(request.media)
            else:
                value = self.provider.cover_url(request.media, request.artwork_dimension)
            self._check_cancelled(request, value)
            return EngineResult(value=value)
        except Exception as exc:
            return self._failure_result(request, requirement, exc)

    def _check_cancelled(self, request: EngineRequest, value: StreamInfo | tuple[str, str] | str | None = None) -> None:
        from waves.providers.apple.engine import _AppleAborted

        if request.abort.is_set():
            if isinstance(value, StreamInfo) and value.local_file:
                self.provider.discard_delivery(value.local_file)
            raise _AppleAborted()

    def _failure_result(self, request: EngineRequest, requirement: EngineRequirement, exc: Exception) -> EngineResult:
        from waves.providers.apple.engine import (
            AppleCredentialsError,
            AppleIntegrityError,
            AppleVariantUnavailable,
            AppleWrapperDown,
            _AppleAborted,
        )

        scope, code, retryable = FailureScope.UNKNOWN, "execution_failed", False
        if isinstance(exc, _AppleAborted) or request.abort.is_set():
            scope, code = FailureScope.ENGINE, "cancelled"
        elif isinstance(exc, AppleCredentialsError):
            scope, code = FailureScope.ACCOUNT, "authentication_required"
            boundary = "apple:wrapper-session" if str(exc.credential) == "wrapper" else "apple:cookies"
            return EngineResult(
                failure=EngineFailure(
                    code,
                    scope,
                    self.descriptor.id,
                    "apple:wrapper-v2" if str(exc.credential) == "wrapper" else "apple:cookies-client",
                    boundary,
                ),
                error=exc,
            )
        elif isinstance(exc, AppleWrapperDown):
            scope, code, retryable = FailureScope.RUNTIME, "runtime_unavailable", True
        elif isinstance(exc, AppleIntegrityError):
            scope, code, retryable = FailureScope.ENGINE, "integrity_failed", True
        elif isinstance(exc, AppleVariantUnavailable):
            scope, code = FailureScope.ENGINE, "delivery_unavailable"
        elif self.provider.classify_refusal(exc).kind == RefusalKind.THROTTLED:
            code = "rate_limited"
        elif self.provider.classify_refusal(exc).kind == RefusalKind.UNAVAILABLE:
            scope, code = FailureScope.PROVIDER, "item_unavailable"
        return EngineResult(
            failure=EngineFailure(
                code, scope, self.descriptor.id, requirement.runtime, requirement.account_boundary, retryable
            ),
            error=exc,
        )

"""Apple engines preserve operation constraints, pins, cancellation and failure scope."""

from dataclasses import replace
from threading import Event

import pytest

from waves.constants import QualityTier
from waves.providers.apple.engines import (
    EngineDescriptor,
    EngineFacts,
    EngineOperation,
    EnginePolicy,
    EngineReadiness,
    EngineRequest,
    EngineRequirement,
    EngineResult,
    EngineRouter,
    EngineRouteUnavailable,
    FailureScope,
)
from waves.providers.apple.gamdl_engine import GamdlEngine
from waves.providers.apple.provider import AppleProvider
from waves.providers.base import AudioType, ReadinessState, StreamInfo


class FakeEngine:
    def __init__(
        self,
        identity,
        *,
        ready=True,
        operations=(EngineOperation.AUDIO,),
        codecs=("aac",),
        runtime="shared-runtime",
        recommendations=(),
    ):
        self.descriptor = EngineDescriptor(
            identity,
            identity,
            tuple(
                EngineRequirement(
                    operation, codecs, (AudioType.STEREO,), (QualityTier.HIGH,), runtime, "external", "shared-account"
                )
                for operation in operations
            ),
            "test-client",
            "test-version",
            recommendations,
        )
        self.ready = ready
        self.calls = []

    def supports(self, request):
        return request.operation in self.descriptor.operations and (
            not request.required_codec
            or any(request.required_codec in item.codecs for item in self.descriptor.requirements)
        )

    def readiness(self, request, facts):
        return EngineReadiness(
            ReadinessState.READY if self.ready else ReadinessState.SETUP_REQUIRED, "shared-runtime", "shared-account"
        )

    def execute(self, request):
        self.calls.append(request)
        return EngineResult(StreamInfo([], ".m4a", "aac", False, {"codecs": "aac"}))

    def cancel(self, request):
        request.abort.set()


def audio(**kwargs):
    return EngineRequest(EngineOperation.AUDIO, {"id": "song-1"}, **kwargs)


def test_auto_selects_a_ready_engine_in_preference_order_for_the_operation():
    first = FakeEngine("first", ready=False)
    second = FakeEngine("second")
    lyrics = FakeEngine("lyrics", operations=(EngineOperation.LYRICS,))
    router = EngineRouter((first, second, lyrics))
    policy = EnginePolicy(("first", "second", "lyrics"))
    assert router.select(audio(), policy, EngineFacts()) is second
    assert router.select(EngineRequest(EngineOperation.LYRICS, {}), policy, EngineFacts()) is lyrics
    assert first.calls == second.calls == lyrics.calls == []


@pytest.mark.parametrize("pin", ["first", "missing"])
def test_an_unready_or_unknown_pin_never_substitutes_a_ready_engine(pin):
    first, second = FakeEngine("first", ready=False), FakeEngine("second")
    router = EngineRouter((first, second))
    with pytest.raises(EngineRouteUnavailable):
        router.select(audio(), EnginePolicy(("second",), pin), EngineFacts())
    assert first.calls == second.calls == []


def test_delivery_constraints_filter_preferences_and_pins():
    aac, alac = FakeEngine("aac"), FakeEngine("alac", codecs=("alac",))
    router = EngineRouter((aac, alac))
    request = audio(required_codec="alac", tier=QualityTier.LOSSLESS)
    assert router.select(request, EnginePolicy(("aac", "alac")), EngineFacts()) is alac
    with pytest.raises(EngineRouteUnavailable):
        router.select(request, EnginePolicy(("alac",), "aac"), EngineFacts())


def test_recommendations_require_operation_specific_qualification_evidence():
    baseline = FakeEngine("baseline")
    candidate = FakeEngine("candidate", recommendations=((EngineOperation.AUDIO, ""),))
    router = EngineRouter((baseline, candidate))
    assert router.select(audio(), EnginePolicy(()), EngineFacts()) is baseline
    candidate.descriptor = replace(
        candidate.descriptor, recommendations=((EngineOperation.AUDIO, "test-qualification-record"),)
    )
    assert router.select(audio(), EnginePolicy(()), EngineFacts()) is candidate
    assert GamdlEngine.descriptor.recommendations == ()


def test_duplicate_engine_identities_are_refused():
    with pytest.raises(ValueError, match="unique"):
        EngineRouter((FakeEngine("same"), FakeEngine("same")))


def test_engine_choice_is_captured_for_a_job_and_provider_identity_stays_apple():
    first, second = FakeEngine("first"), FakeEngine("second")
    provider = AppleProvider(engines=(first, second))
    provider.engine_selection = "first"
    policy = provider.engine_policy()
    provider.engine_selection = "second"
    with provider.engine_job_context(policy, Event()):
        result = provider.resolve_stream({"id": "song-1"}, QualityTier.HIGH, AudioType.STEREO)
    assert len(first.calls) == 1 and second.calls == []
    assert result.delivered["engine_id"] == "first"
    assert provider.id == "apple"
    provider.resolve_stream({"id": "song-2"}, QualityTier.HIGH, AudioType.STEREO)
    assert len(second.calls) == 1


@pytest.mark.parametrize(
    ("engine_request", "facts", "state"),
    [
        (audio(), EngineFacts(True, True, False, True, False), ReadinessState.READY),
        (audio(audio_type=AudioType.ATMOS), EngineFacts(True, True, False, True, False), ReadinessState.READY),
        (
            audio(required_codec="alac", tier=QualityTier.LOSSLESS),
            EngineFacts(True, False, True, True, True),
            ReadinessState.READY,
        ),
        (
            audio(required_codec="alac", tier=QualityTier.LOSSLESS),
            EngineFacts(True, True, False, True, True),
            ReadinessState.SIGN_IN_REQUIRED,
        ),
        (
            audio(required_codec="alac", tier=QualityTier.LOSSLESS),
            EngineFacts(True, True, True, True, False),
            ReadinessState.SETUP_REQUIRED,
        ),
        (audio(), EngineFacts(True, True, False, False), ReadinessState.SETUP_REQUIRED),
        (audio(), EngineFacts(False, True, True, True, True), ReadinessState.DISABLED),
        (audio(), EngineFacts(), ReadinessState.UNKNOWN),
        (EngineRequest(EngineOperation.LYRICS, {}), EngineFacts(True, True, False, False), ReadinessState.READY),
        (EngineRequest(EngineOperation.ARTWORK, {}), EngineFacts(True, False, False, False), ReadinessState.READY),
    ],
)
def test_gamdl_readiness_separates_cookies_wrapper_assets_and_fetch_tools(engine_request, facts, state):
    engine = GamdlEngine(AppleProvider())
    assert engine.readiness(engine_request, facts).state == state


@pytest.mark.parametrize("version", ["", "3.8.4", "3.9.1", "3.8.5rc1"])
def test_incompatible_client_versions_do_not_dispatch(version, monkeypatch):
    import waves.providers.apple.gamdl_engine as adapter

    monkeypatch.setattr(adapter, "gamdl_version", lambda: version)
    provider = AppleProvider()
    monkeypatch.setattr(provider, "_resolve_gamdl_stream", lambda *_a, **_kw: pytest.fail("incompatible dispatch"))
    result = GamdlEngine(provider).execute(audio())
    assert result.failure.code == "incompatible_client"
    assert result.failure.scope == FailureScope.ENGINE


def test_cancellation_before_dispatch_and_after_a_late_delivery_cleans_staging(monkeypatch):
    from waves.providers.apple.engine import _AppleAborted

    provider, request = AppleProvider(), audio()
    engine = GamdlEngine(provider)
    dispatched, discarded = [], []

    def deliver(*args, **kwargs):
        dispatched.append(True)
        engine.cancel(request)
        return StreamInfo([], ".m4a", "aac", False, {"codecs": "aac"}, local_file="staged.m4a")

    monkeypatch.setattr(provider, "_resolve_gamdl_stream", deliver)
    monkeypatch.setattr(provider, "discard_delivery", discarded.append)
    result = engine.execute(request)
    assert result.failure.code == "cancelled" and isinstance(result.error, _AppleAborted)
    assert discarded == ["staged.m4a"]
    dispatched.clear()
    assert engine.execute(request).failure.code == "cancelled"
    assert dispatched == []


def test_classified_results_distinguish_shared_runtime_and_account_failures(monkeypatch):
    from waves.providers.apple.engine import AppleCredential, AppleCredentialsError, AppleWrapperDown

    provider = AppleProvider()
    provider.wrapper_url = "http://private-endpoint.invalid"
    request = audio(tier=QualityTier.LOSSLESS)
    engine = GamdlEngine(provider)

    def fail(error):
        def execute(*args, **kwargs):
            raise error

        return execute

    monkeypatch.setattr(provider, "_resolve_gamdl_stream", fail(AppleWrapperDown("private endpoint detail")))
    result = engine.execute(request)
    assert result.failure.scope == FailureScope.RUNTIME
    assert result.failure.runtime == "apple:wrapper-v2"
    assert result.failure.retryable is True
    monkeypatch.setattr(
        provider,
        "_resolve_gamdl_stream",
        fail(AppleCredentialsError("private account detail", credential=AppleCredential.WRAPPER)),
    )
    result = engine.execute(request)
    assert result.failure.scope == FailureScope.ACCOUNT
    assert result.failure.account_boundary == "apple:wrapper-session"
    assert result.failure.retryable is False
    assert "private" not in repr(result.failure)


def test_safe_engine_details_keep_assets_independent_of_audio_setup():
    provider = AppleProvider()
    details = provider.engine_details(EngineFacts(True, True, False, False, False))
    assert details[0]["id"] == "gamdl" and details[0]["recommended_operations"] == []
    requirements = details[0]["requirements"]
    assert next(item for item in requirements if item["operation"] == "lyrics")["state"] == "ready"
    assert next(item for item in requirements if item["operation"] == "artwork")["state"] == "ready"
    assert all(item["state"] != "ready" for item in requirements if item["operation"] == "audio")


def test_bridge_engine_details_use_verified_account_facts_without_audio_binary_coupling():
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    provider = AppleProvider()
    bridge = SimpleNamespace(
        providers={"apple": provider},
        _apple_live_flags=lambda: {"enabled": True, "cookies_account_ready": True, "wrapper_ready": False},
        _apple_fetch_binary_ready=lambda: False,
        _apple_container_serves=lambda: False,
    )
    details = WavesBridge._apple_engine_details(bridge)
    bridge._provider_engine_probes = {"apple": lambda: details}
    assert WavesBridge.providerEngines(bridge, "apple") == details
    assert WavesBridge.providerEngines(bridge, "unknown") == []
    states = {item["operation"]: item["state"] for item in details[0]["requirements"]}
    assert states["lyrics"] == states["artwork"] == "ready"
    assert states["audio"] != "ready"


def test_unknown_asset_account_is_not_presented_as_signed_out():
    engine = GamdlEngine(AppleProvider())
    state = engine.readiness(EngineRequest(EngineOperation.LYRICS, {}), EngineFacts(enabled=True, wrapper_ready=False))
    assert state.state == ReadinessState.UNKNOWN and state.action == ""

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
        if request.operation == EngineOperation.LYRICS:
            return EngineResult(("synced", "plain") if request.lyrics_format == "converted" else "<tt>lyrics</tt>")
        if request.operation == EngineOperation.ARTWORK:
            return EngineResult("https://public.invalid/cover.jpg")
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
            EngineFacts(True, False, True, True, True, True),
            ReadinessState.READY,
        ),
        (
            audio(required_codec="alac", tier=QualityTier.LOSSLESS),
            EngineFacts(True, True, False, True, True, False),
            ReadinessState.SIGN_IN_REQUIRED,
        ),
        (
            audio(required_codec="alac", tier=QualityTier.LOSSLESS),
            EngineFacts(True, True, True, True, False, True),
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
        _apple_wrapper_auth_cache={"result": {"reachable": False}},
        _get_apple_enabled=lambda: True,
    )
    WavesBridge._apple_engine_facts(bridge)
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


def test_provider_routing_skips_unready_preferences_and_refuses_an_unready_pin():
    first, second = FakeEngine("first", ready=False), FakeEngine("second")
    provider = AppleProvider(engines=(first, second))
    provider.engine_preferences = ("first", "second")
    provider.engine_facts_probe = lambda: EngineFacts(enabled=True)
    result = provider.resolve_stream({"id": "song-1"}, QualityTier.HIGH, AudioType.STEREO)
    assert result.delivered["engine_id"] == "second"
    assert first.calls == []
    provider.engine_selection = "first"
    with pytest.raises(EngineRouteUnavailable):
        provider.resolve_stream({"id": "song-1"}, QualityTier.HIGH, AudioType.STEREO)
    # A direct caller without desktop facts also excludes a known bad route.
    provider.engine_facts_probe = None
    provider.engine_selection = "auto"
    provider.resolve_stream({"id": "song-2"}, QualityTier.HIGH, AudioType.STEREO)
    assert first.calls == [] and len(second.calls) == 2


def test_asset_operations_use_the_captured_pin_and_never_substitute_unknown_pins():
    first = FakeEngine("first", operations=(EngineOperation.LYRICS, EngineOperation.ARTWORK))
    second = FakeEngine("second", operations=(EngineOperation.LYRICS, EngineOperation.ARTWORK))
    provider = AppleProvider(engines=(first, second))
    provider.engine_selection = "first"
    policy = provider.engine_policy()
    provider.engine_selection = "second"
    with provider.engine_job_context(policy, Event()):
        assert provider.fetch_lyrics({"id": "song"}) == ("synced", "plain")
        assert provider.fetch_line_ttml({"id": "song"}) == "<tt>lyrics</tt>"
        assert provider.fetch_syllable_ttml({"id": "song"}) == "<tt>lyrics</tt>"
        assert provider.cover_url({"id": "song"}, 2048) == "https://public.invalid/cover.jpg"
    assert len(first.calls) == 4 and second.calls == []
    assert first.calls[-1].artwork_dimension == 2048
    provider.engine_selection = "unknown"
    assert provider.fetch_lyrics({"id": "song"}) == ("", "")
    assert provider.fetch_line_ttml({"id": "song"}) == ""
    assert provider.cover_url({"id": "song"}, 1280) == ""
    assert len(first.calls) == 4 and second.calls == []


def test_wrapper_runtime_and_unverified_protocol_never_masquerade_as_account_failure():
    engine = GamdlEngine(AppleProvider())
    request = audio(required_codec="alac", tier=QualityTier.LOSSLESS)
    offline = EngineFacts(True, False, True, True, True, False)
    state = engine.readiness(request, offline)
    assert state.state == ReadinessState.SETUP_REQUIRED and state.action == "setup"
    unknown_protocol = replace(offline, wrapper_runtime_ready=True, protocol_compatible=None)
    state = engine.readiness(request, unknown_protocol)
    assert state.state == ReadinessState.UNKNOWN and state.action == ""


def test_stereo_delivery_from_an_atmos_ask_classifies_the_actual_wrapper_boundary(monkeypatch):
    from waves.providers.apple.engine import AppleWrapperDown

    provider = AppleProvider()
    provider.wrapper_url = "http://private.invalid"

    def fail(*args, **kwargs):
        raise AppleWrapperDown("private detail")

    monkeypatch.setattr(provider, "_resolve_gamdl_stream", fail)
    result = GamdlEngine(provider).execute(audio(tier=QualityTier.LOSSLESS, audio_type=AudioType.ATMOS))
    assert result.failure.scope == FailureScope.RUNTIME
    assert result.failure.runtime == "apple:wrapper-v2"
    assert result.failure.account_boundary == "apple:wrapper-session"


def test_engine_policy_normalizes_pins_and_orders_at_every_intake():
    assert EnginePolicy((" GAMDL ", "gamdl"), " GAMDL ") == EnginePolicy(("gamdl",), "gamdl")
    assert EnginePolicy((" Gamdl ",), " Auto ") == EnginePolicy()


def test_engine_detail_slot_queues_setup_reads_and_serves_cached_facts():
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    queued, reads, signals = [], [], []
    bridge = SimpleNamespace(
        providers={"apple": AppleProvider()},
        threadpool=SimpleNamespace(start=queued.append),
        _get_apple_enabled=lambda: True,
        _apple_live_flags=lambda: (
            reads.append("facts") or {"enabled": True, "cookies_account_ready": True, "wrapper_ready": False}
        ),
        _apple_wrapper_auth_cache={"result": {"reachable": False}},
        _apple_fetch_binary_ready=lambda: False,
        _apple_container_serves=lambda: False,
        appleStatusChanged=SimpleNamespace(emit=lambda: signals.append(True)),
    )
    bridge._apple_engine_facts = lambda token=None: WavesBridge._apple_engine_facts(bridge, token)
    details = WavesBridge._apple_engine_details(bridge)
    assert reads == [] and len(queued) == 1
    assert all(row["state"] == "unknown" for row in details[0]["requirements"] if row["operation"] != "artwork")
    WavesBridge._apple_engine_details(bridge)
    assert len(queued) == 1
    queued[0].run()
    refreshed = WavesBridge._apple_engine_details(bridge)
    assert reads == ["facts"] and signals == [True]
    assert next(row for row in refreshed[0]["requirements"] if row["operation"] == "lyrics")["state"] == "ready"
    assert len(queued) == 1


def test_revoked_engine_detail_refresh_cannot_restore_account_readiness():
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge
    from waves.desktop.providers.lifecycle import provider_contexts

    bridge = SimpleNamespace(
        _apple_live_flags=lambda: {"enabled": True, "cookies_account_ready": True, "wrapper_ready": True},
        _apple_wrapper_auth_cache={"result": {"reachable": True, "state": "authenticated"}},
        _apple_fetch_binary_ready=lambda: True,
        _apple_container_serves=lambda: True,
    )
    token = provider_contexts(bridge).capture("apple")
    provider_contexts(bridge).revoke("apple")
    assert WavesBridge._apple_engine_facts(bridge, token).enabled is False
    assert getattr(bridge, "_apple_engine_facts_cache", None) is None

"""Account changes and Stop revoke admission before dispatch and publication."""

from contextlib import contextmanager

import pytest

from waves.constants import QualityTier
from waves.providers.apple.engine import AppleWrapperDown, _AppleAborted
from waves.providers.apple.engines import (
    EngineDescriptor,
    EngineFacts,
    EngineOperation,
    EngineReadiness,
    EngineRequirement,
    EngineResult,
)
from waves.providers.apple.provider import AppleProvider
from waves.providers.apple.runtime_sessions import (
    AccountContext,
    AppleRuntimeSessions,
    RuntimeKind,
    RuntimeProfile,
    SessionEvidence,
)
from waves.providers.base import AudioType, ReadinessState, StreamInfo


class ContextEngine:
    """An external engine whose boundary callbacks order a context change."""

    def __init__(self, runtime="apple:wrapper-v2"):
        self.runtime = runtime
        self.descriptor = EngineDescriptor(
            "context-engine",
            "Context engine",
            (
                EngineRequirement(
                    EngineOperation.AUDIO,
                    ("alac",),
                    (AudioType.STEREO,),
                    (QualityTier.LOSSLESS,),
                    runtime,
                    "user_managed",
                    "apple:wrapper-session",
                ),
            ),
            "synthetic-client",
            "1",
        )
        self.on_readiness = lambda: None
        self.on_execute = lambda: None
        self.dispatched = False

    def supports(self, request):
        return request.operation == EngineOperation.AUDIO

    def readiness(self, request, facts):
        state = ReadinessState.READY if facts.enabled else ReadinessState.UNKNOWN
        self.on_readiness()
        return EngineReadiness(state, self.runtime, "apple:wrapper-session")

    def execute(self, request):
        self.dispatched = True
        self.on_execute()
        return EngineResult(StreamInfo([], ".m4a", "alac", False, {"codecs": "alac"}, local_file="staged.m4a"))

    def cancel(self, request):
        request.abort.set()


@pytest.fixture
def execution(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.configure(RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2"))
    sessions.set_account(AccountContext("account-one", "us", "cookies-one"))
    sessions.observe("apple:wrapper-v2", SessionEvidence(True, True, True, True, "account-one", "us", "session-one"))
    engine = ContextEngine()
    provider = AppleProvider(engines=(engine,))
    provider.engine_facts_probe = lambda: EngineFacts(enabled=True)
    provider.runtime_context_revision = sessions.revision
    provider.runtime_stopped = sessions.is_stopped
    return provider, sessions, engine


@pytest.mark.parametrize("boundary", ["probe", "readiness", "usage"])
@pytest.mark.parametrize("change", ["stop", "account"])
def test_account_change_or_stop_before_dispatch_never_executes(execution, boundary, change):
    provider, sessions, engine = execution

    def change_context():
        if change == "stop":
            sessions.stop("apple:wrapper-v2")
        else:
            sessions.set_account(AccountContext("account-two", "us", "cookies-two"))

    if boundary == "probe":

        def probe():
            facts = EngineFacts(enabled=True)
            change_context()
            return facts

        provider.engine_facts_probe = probe
    elif boundary == "readiness":
        engine.on_readiness = change_context
    else:

        @contextmanager
        def usage():
            change_context()
            yield

        provider.runtime_usage = usage
    error = AppleWrapperDown if change == "stop" else _AppleAborted
    with pytest.raises(error):
        provider.resolve_stream({"id": "song"}, QualityTier.LOSSLESS, AudioType.STEREO)
    assert engine.dispatched is False


@pytest.mark.parametrize("change", ["stop", "account"])
def test_account_change_or_stop_during_execution_discards_delivery(execution, change, monkeypatch):
    provider, sessions, engine = execution
    discarded = []
    monkeypatch.setattr(provider, "discard_delivery", discarded.append)
    if change == "stop":
        engine.on_execute = lambda: sessions.stop("apple:wrapper-v2")
    else:
        engine.on_execute = lambda: sessions.set_account(AccountContext("account-two", "us", "cookies-two"))
    error = AppleWrapperDown if change == "stop" else _AppleAborted
    with pytest.raises(error):
        provider.resolve_stream({"id": "song"}, QualityTier.LOSSLESS, AudioType.STEREO)
    assert discarded == ["staged.m4a"]


def test_stopping_wrapper_allows_an_independent_runtime_to_deliver(execution):
    provider, sessions, _engine = execution
    engine = ContextEngine("apple:cookies-client")
    provider = AppleProvider(engines=(engine,))
    provider.engine_facts_probe = lambda: EngineFacts(enabled=True)
    provider.runtime_context_revision = sessions.revision
    provider.runtime_stopped = sessions.is_stopped
    engine.on_readiness = lambda: sessions.stop("apple:wrapper-v2")
    result = provider.resolve_stream({"id": "song"}, QualityTier.LOSSLESS, AudioType.STEREO)
    assert result.local_file == "staged.m4a"
    assert result.delivered["runtime_id"] == "apple:cookies-client"


def test_unchanged_runtime_context_delivers(execution):
    provider, _sessions, _engine = execution
    result = provider.resolve_stream({"id": "song"}, QualityTier.LOSSLESS, AudioType.STEREO)
    assert result.local_file == "staged.m4a"
    assert result.delivered["runtime_id"] == "apple:wrapper-v2"


def test_first_cookies_context_observation_does_not_abort_its_own_delivery(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    engine = ContextEngine("apple:cookies-client")
    provider = AppleProvider(engines=(engine,))

    def probe():
        sessions.set_account(AccountContext("", "us", "first-observed-cookies"))
        return EngineFacts(enabled=True)

    provider.engine_facts_probe = probe
    provider.runtime_context_revision = sessions.revision
    provider.runtime_stopped = sessions.is_stopped
    result = provider.resolve_stream({"id": "song"}, QualityTier.LOSSLESS, AudioType.STEREO)
    assert result.local_file == "staged.m4a"
    assert engine.dispatched

"""Operation eligibility is provider policy, independent of card presentation."""

from types import SimpleNamespace

import pytest
from conftest import _Signal
from providers.fakes import StubProvider, stub_bridge

from waves.desktop.backend import WavesBridge, _search_provider_on
from waves.desktop.bridge_surfaces import (
    _my_music_empty,
    _provider_light,
    _provider_readiness,
    _saved_shelf_sources,
    _source_provider,
)
from waves.providers import AccountState, Capability, ReadinessState, StatusKind
from waves.providers.apple.provider import AppleProvider


def test_public_catalog_can_be_enabled_and_signed_out():
    provider = AppleProvider()
    state = provider.readiness(enabled=True, signed_in=False)
    assert state.account == AccountState.SIGNED_OUT
    assert state.for_operation(Capability.SEARCH).state == ReadinessState.READY
    assert state.for_operation(Capability.OPEN_URL).state == ReadinessState.READY
    assert state.for_operation(Capability.DOWNLOAD).state == ReadinessState.SIGN_IN_REQUIRED
    assert state.for_operation(Capability.FAVORITES).state == ReadinessState.UNSUPPORTED


def test_disabled_setup_and_unknown_probe_are_distinct():
    provider = StubProvider("third", "Third", capabilities={Capability.SEARCH}, status_kind=StatusKind.SETUP)
    unknown = stub_bridge({"third": provider})
    assert _provider_readiness(unknown, provider).for_operation(Capability.SEARCH).state == ReadinessState.UNKNOWN
    assert _provider_light(unknown, provider)["state"] == "unknown"
    disabled = stub_bridge({"third": provider}, probes={"third": lambda: {"enabled": False}})
    assert _provider_readiness(disabled, provider).for_operation(Capability.SEARCH).state == ReadinessState.DISABLED
    assert not _search_provider_on(disabled, "third")
    opportunity = WavesBridge.searchOpportunities(disabled)[0]
    assert (opportunity["provider"], opportunity["action"]) == ("third", "setup")


def test_failed_live_probe_never_grants_an_operation():
    provider = StubProvider("third", "Third", capabilities={Capability.SEARCH}, logged_in=True)
    bridge = stub_bridge({"third": provider})

    def failed():
        raise RuntimeError

    bridge._provider_readiness_probes = {"third": failed}
    assert not _search_provider_on(bridge, "third")
    assert _provider_readiness(bridge, provider).account == AccountState.UNKNOWN


def test_setup_card_shape_does_not_prevent_account_shelves():
    provider = StubProvider(
        "third", "Third", capabilities={Capability.FAVORITES}, status_kind=StatusKind.SETUP, logged_in=True
    )
    bridge = stub_bridge({"third": provider}, probes={"third": lambda: {"enabled": True}})
    assert _saved_shelf_sources(bridge) == [{"id": "third", "name": "Third", "label": ""}]
    assert not _my_music_empty(bridge)
    provider._logged_in = False
    assert _my_music_empty(bridge)["action"] == "signin"


def test_unknown_account_remains_unknown():
    class UnreadableProvider(StubProvider):
        @property
        def is_logged_in(self):
            raise RuntimeError

    provider = UnreadableProvider("third", "Third", capabilities={Capability.SEARCH})
    state = _provider_readiness(stub_bridge({"third": provider}), provider)
    assert state.account == AccountState.UNKNOWN
    assert state.for_operation(Capability.SEARCH).state == ReadinessState.UNKNOWN


class _PrivateShelfProvider(StubProvider):
    public_operations = frozenset({Capability.CATALOG})

    def __init__(self, provider_id="paper", account=True):
        super().__init__(
            provider_id,
            provider_id.title(),
            capabilities={Capability.CATALOG, Capability.FAVORITES},
            status_kind=StatusKind.SETUP,
            logged_in=account,
        )
        self.calls = []

    def favorites_page(self, kind, offset, limit, order=None):
        self.calls.append((kind, offset, limit))
        return [{"id": f"{self.id}:album-1"}], False

    def row_for(self, kind, item):
        return item


@pytest.mark.parametrize(
    ("enabled", "account", "expected"),
    [
        (True, False, ReadinessState.SIGN_IN_REQUIRED),
        (False, True, ReadinessState.DISABLED),
        (True, None, ReadinessState.UNKNOWN),
    ],
)
def test_direct_private_shelf_calls_require_the_owning_operation_ready(enabled, account, expected):
    provider = _PrivateShelfProvider(account=account)
    tidal = _PrivateShelfProvider("tidal")
    bridge = stub_bridge(
        {"tidal": tidal, "paper": provider},
        probes={"paper": lambda: {"enabled": enabled}, "tidal": lambda: {"enabled": True}},
    )
    scheduled = []
    bridge.threadpool = SimpleNamespace(start=scheduled.append)
    bridge.libraryLoaded = _Signal()
    bridge._lib_cache = {("paper", "albums"): {"items": [{"id": "paper:old-account"}], "more": False}}
    readiness = _provider_readiness(bridge, provider)
    assert readiness.for_operation(Capability.FAVORITES).state == expected
    if account is None:
        assert readiness.account == AccountState.UNKNOWN
    if enabled:
        assert readiness.for_operation(Capability.CATALOG).state == ReadinessState.READY

    assert _source_provider(bridge, "paper") is None
    assert WavesBridge._library_page(bridge, "paper", "albums", 0, 40) == ([], False)
    WavesBridge.loadLibrary(bridge, "paper", "albums")

    assert not scheduled and not bridge.libraryLoaded.emits
    assert provider.calls == [] and tidal.calls == [], "a closed source never falls back into another account"


def test_direct_private_shelf_calls_use_a_ready_third_provider():
    provider = _PrivateShelfProvider()
    bridge = stub_bridge({"paper": provider}, probes={"paper": lambda: {"enabled": True}})
    bridge._lib_sort = {}

    assert _source_provider(bridge, "paper") is provider
    assert WavesBridge._library_page(bridge, "paper", "albums", 0, 40) == ([{"id": "paper:album-1"}], False)
    assert provider.calls == [("albums", 0, 40)]


@pytest.mark.parametrize("audio_ready", [False, True])
def test_apple_asset_readiness_is_independent_of_audio_fetch_setup(audio_ready):
    provider = AppleProvider()
    bridge = SimpleNamespace(
        providers={"apple": provider},
        _apple_live_flags=lambda: {"enabled": True, "account_signed_in": True, "signed_in": audio_ready},
    )
    snapshot = WavesBridge._apple_readiness(bridge)
    assert snapshot.account == AccountState.SIGNED_IN
    assert snapshot.for_operation(Capability.LYRICS).state == ReadinessState.READY
    assert snapshot.for_operation(Capability.ART).state == ReadinessState.READY
    assert snapshot.for_operation(Capability.DOWNLOAD).state == (
        ReadinessState.READY if audio_ready else ReadinessState.SETUP_REQUIRED
    )

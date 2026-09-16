"""The header's per-provider lights and Browse's availability (issue #223).

WHAT THIS FENCES OFF
--------------------
1. The TIDAL-only "OFFLINE" pill. The header reports one light per provider
   that has a status to report, composed from the provider's descriptor and
   the live state its status_kind names: no surface says OFFLINE while
   another provider is usable, and a third provider contributes a light from
   its descriptor alone (the paper test, extended to the header).

2. Browse availability as a provider-identity branch. A configured provider
   that declares Capability.BROWSE makes Browse exist; none does, and the
   destination is hidden (never a permanently blank page). A signed-out
   browse provider keeps the destination with its sign-in call to action.

The data half is module-level, so these tests drive it with stub bridges and
no Qt session, in the same shape as the saved-shelf tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from support.provider_fakes import BareProvider

from waves.providers import Capability, ProviderDescriptor, StatusKind
from waves.waves_ui import backend


class _Provider(BareProvider):
    """A provider whose identity and status live on the instance."""

    def __init__(self, provider_id, name, *, capabilities=frozenset(), status_kind=StatusKind.SESSION, logged_in=False):
        self.id = provider_id
        self.name = name
        self.capabilities = frozenset(capabilities)
        self._status_kind = status_kind
        self._logged_in = logged_in

    @property
    def is_logged_in(self):
        return self._logged_in

    def descriptor(self):
        return ProviderDescriptor(id=self.id, name=self.name, status_kind=self._status_kind)


def _stub(providers, *, logged_in=False, tracked=frozenset(), probes=None) -> SimpleNamespace:
    return SimpleNamespace(
        providers=dict(providers),
        _logged_in=logged_in,
        _tracked_sessions=tracked,
        _provider_status_probes=dict(probes or {}),
    )


def test_a_session_provider_reports_its_session_state():
    tidal = _Provider("tidal", "TIDAL", capabilities={Capability.BROWSE})

    out = backend._provider_lights(_stub({"tidal": tidal}))
    assert out == [
        {"id": "tidal", "name": "TIDAL", "state": "signed_out", "word": "Signed out"},
    ]

    signed = backend._provider_lights(_stub({"tidal": tidal}, logged_in=True, tracked=frozenset({"tidal"})))
    assert signed[0]["state"] == "signed_in"
    assert signed[0]["word"] == "Connected"


def test_a_setup_provider_reports_its_setup_light_and_off_contributes_none():
    apple = _Provider("apple", "Apple Music", status_kind=StatusKind.SETUP)
    probes = {"apple": lambda: {"enabled": True, "runtime_ready": True}}

    out = backend._provider_lights(_stub({"apple": apple}, probes=probes))
    assert out == [{"id": "apple", "name": "Apple Music", "state": "runtime_ready", "word": "Runtime ready"}]

    # A disabled provider is not availability to report: no light at all.
    off = backend._provider_lights(_stub({"apple": apple}, probes={"apple": lambda: {"enabled": False}}))
    assert off == []


def test_a_provider_with_no_status_contributes_no_light():
    nameless = _Provider("noneco", "NoneCo", status_kind=StatusKind.NONE)

    assert backend._provider_lights(_stub({"noneco": nameless})) == []


def test_a_third_provider_adds_a_light_with_no_surface_edit():
    # The paper test: a provider that is neither TIDAL nor Apple appears in
    # the header from its descriptor and its live session alone.
    tidal = _Provider("tidal", "TIDAL", logged_in=True)
    fake = _Provider("fake", "Fake Music", logged_in=True)

    out = backend._provider_lights(_stub({"tidal": tidal, "fake": fake}))

    assert [light["id"] for light in out] == ["tidal", "fake"]
    assert [light["word"] for light in out] == ["Connected", "Connected"]


def test_browse_requires_a_browse_capable_provider():
    # TIDAL declares BROWSE: the destination exists, and its account state
    # decides between the page and the sign-in call to action.
    tidal = _Provider("tidal", "TIDAL", capabilities={Capability.BROWSE})
    assert backend._browse_nav(_stub({"tidal": tidal})) == {"available": True, "signed_in": False}
    assert backend._browse_nav(_stub({"tidal": tidal}, logged_in=True, tracked=frozenset({"tidal"}))) == {
        "available": True,
        "signed_in": True,
    }

    # Apple declares no BROWSE today: an Apple-only registry has no Browse.
    apple = _Provider("apple", "Apple Music", capabilities={Capability.SEARCH}, status_kind=StatusKind.SETUP)
    assert backend._browse_nav(_stub({"apple": apple})) == {"available": False, "signed_in": False}
    assert backend._browse_nav(_stub({})) == {"available": False, "signed_in": False}


def test_a_third_provider_with_browse_restores_the_destination():
    fake = _Provider("fake", "Fake Music", capabilities={Capability.BROWSE}, logged_in=True)

    assert backend._browse_nav(_stub({"fake": fake})) == {"available": True, "signed_in": True}


def test_the_header_carries_no_offline_pill_and_the_card_owns_sign_out():
    # The QML half of the acceptance: the TIDAL-only pill and the header
    # sign-out are gone, and the header renders the bridge's lights.
    from pathlib import Path

    qml = (Path(backend.__file__).resolve().parent / "qml" / "Main.qml").read_text(encoding="utf-8")

    assert '"OFFLINE"' not in qml
    assert 'text: "SIGN OUT"' not in qml
    assert "waves.providerLights()" in qml
    assert "waves.browseNav()" in qml

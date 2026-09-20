"""The welcome surface's provider cards carry copy and live status (#219).

WHAT THIS FENCES OFF
--------------------
1. Hardcoded card copy. The action under a provider's mark is the provider's
   own words from its descriptor ("Set up Apple Music", never "Sign in"): a
   first-time user reads what the click does, and a third provider's card
   needs no QML edit.

2. A card that cannot state where its provider stands. Each card carries the
   provider's live status on the same shape the header's marks read (a
   session state, a setup light; a disabled setup provider reports nothing),
   so the welcome surface can show status wherever the account is shown.

The data half is module-level, so these tests drive it with stub bridges and
no Qt session, in the same shape as the header-light and saved-shelf tests.
"""

from __future__ import annotations

from pathlib import Path

from support.provider_fakes import StubProvider, stub_bridge

from waves.providers import Capability, StatusKind
from waves.providers.apple.provider import AppleProvider
from waves.providers.tidal import TidalProvider
from waves.waves_ui import backend


def test_both_providers_state_their_welcome_action():
    # The onboarding spec (#213), Apple card: it says what it does (a one-time
    # setup, no Apple account needed for search), never "Sign in".
    tidal = TidalProvider.descriptor()
    apple = AppleProvider.descriptor()

    assert tidal.welcome_action == "Continue with TIDAL"
    assert apple.welcome_action == "Set up Apple Music"


def test_a_card_carries_its_live_status():
    tidal = StubProvider("tidal", "TIDAL", capabilities={Capability.BROWSE})
    apple = StubProvider("apple", "Apple Music", status_kind=StatusKind.SETUP)
    probes = {"apple": lambda: {"enabled": True, "runtime_ready": True}}

    cards = backend.WavesBridge.providerCards(stub_bridge({"tidal": tidal, "apple": apple}, probes=probes))
    by_id = {card["id"]: card for card in cards}

    assert by_id["tidal"]["state"] == "signed_out"
    assert by_id["tidal"]["word"] == "Signed out"
    assert by_id["apple"]["state"] == "runtime_ready"
    assert by_id["apple"]["word"] == "Runtime ready"

    # A disabled setup provider reports no status: nothing to say about it.
    off = backend.WavesBridge.providerCards(stub_bridge({"apple": apple}, probes={"apple": lambda: {"enabled": False}}))
    assert off[0]["state"] == "" and off[0]["word"] == ""


def test_a_third_provider_contributes_its_action_and_status():
    fake = StubProvider("fake", "Fake Music", logged_in=True)

    card = backend.WavesBridge.providerCards(stub_bridge({"fake": fake}))[0]

    assert card["id"] == "fake"
    assert card["action"] == ""
    assert (card["state"], card["word"]) == ("signed_in", "Signed in")


def test_the_welcome_action_is_descriptor_data_not_qml_copy():
    # The welcome renders the bridge's card fields; the copy lives in the
    # descriptors, so a provider's own words reach the surface unedited. The
    # welcome surface is WelcomePicker.qml since #315 slice 8, so read it
    # beside Main.qml: neither may grow a hardcoded provider action.
    qml_dir = Path(backend.__file__).resolve().parent / "qml"
    qml = (qml_dir / "Main.qml").read_text(encoding="utf-8") + (qml_dir / "WelcomePicker.qml").read_text(
        encoding="utf-8"
    )

    assert "Set up Apple Music" not in qml
    assert "modelData.action" in qml
    assert "modelData.word" in qml

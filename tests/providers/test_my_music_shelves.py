"""My Music's saved-shelf sources: labels come from provider descriptors.

Issue #221's source-label rule: the shelves a provider contributes are
labelled by their source only when more than one provider contributes them.
TIDAL is the only saved-shelf source today, so the pane renders exactly as it
did before -- no label; a second provider makes every section's label
source-qualified ("Saved from TIDAL").

The data half of the third-provider paper test lives here: a provider that is
not TIDAL contributes a saved section from its descriptor and its live
session alone, and the label text is bridge data, never QML copy, so the
pane's Text binds a property rather than a literal.
"""

from __future__ import annotations

from pathlib import Path

from support.provider_fakes import StubProvider, stub_bridge

from waves.providers import Capability
from waves.waves_ui import backend
from waves.waves_ui.backend import WavesBridge

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_QML = REPO_ROOT / "waves" / "waves_ui" / "qml" / "Main.qml"


def _shelf_provider(provider_id, name, *, logged_in=True, capabilities=None):
    """A provider whose saved shelves My Music can render.

    The neutral descriptor is a session-kind one, so the readiness read is
    the provider's own ``is_logged_in`` unless the bridge tracks it.
    """
    return StubProvider(
        provider_id,
        name,
        capabilities=frozenset({Capability.FAVORITES}) if capabilities is None else capabilities,
        logged_in=logged_in,
    )


def test_a_lone_saved_shelf_source_carries_no_label():
    # One provider contributes: the pane's rows are that provider, so the
    # label stays "" and the pane renders exactly as it did (issue #221).
    sources = backend._saved_shelf_sources(stub_bridge({"tidal": _shelf_provider("tidal", "TIDAL")}))

    assert sources == [{"id": "tidal", "name": "TIDAL", "label": ""}]


def test_a_second_saved_shelf_source_qualifies_every_label():
    # The paper test: a provider that is not TIDAL contributes a second saved
    # section from its descriptor and its session alone -- the labels become
    # source-qualified together, with no QML edit.
    sources = backend._saved_shelf_sources(
        stub_bridge(
            {
                "tidal": _shelf_provider("tidal", "TIDAL"),
                "fake": _shelf_provider("fake", "Fake Music"),
            }
        )
    )

    assert [s["id"] for s in sources] == ["tidal", "fake"]
    assert [s["label"] for s in sources] == ["Saved from TIDAL", "Saved from Fake Music"]


def test_a_provider_that_cannot_fill_shelves_is_not_a_source():
    # A provider with no favourites capability and a signed-out provider
    # cannot fill saved shelves, so neither contributes a section.
    no_capability = _shelf_provider("apple", "Apple Music", capabilities=frozenset({Capability.SEARCH}))
    signed_out = _shelf_provider("tidal", "TIDAL", logged_in=False)
    assert backend._saved_shelf_sources(stub_bridge({"tidal": signed_out, "apple": no_capability})) == []

    # A tracked session answers from the bridge's flag (the one the login
    # flow and every catalog read move together), not the provider's.
    tracked = _shelf_provider("tidal", "TIDAL", logged_in=True)
    assert backend._saved_shelf_sources(stub_bridge({"tidal": tracked}, tracked=frozenset({"tidal"}))) == []
    sourced = backend._saved_shelf_sources(
        stub_bridge({"tidal": tracked}, logged_in=True, tracked=frozenset({"tidal"}))
    )
    assert [s["id"] for s in sourced] == ["tidal"]


def test_the_pane_label_is_empty_until_a_second_source_contributes():
    tidal = _shelf_provider("tidal", "TIDAL")

    assert WavesBridge._get_my_music_source_label(stub_bridge({"tidal": tidal})) == ""

    paired = stub_bridge({"tidal": tidal, "fake": _shelf_provider("fake", "Fake Music")})
    assert WavesBridge._get_my_music_source_label(paired) == "Saved from TIDAL"

    # TIDAL's shelves are the pane's rows: while TIDAL is signed out the pane
    # shows its sign-in state, and no label stands over absent sections.
    signed_out = stub_bridge(
        {
            "tidal": _shelf_provider("tidal", "TIDAL", logged_in=False),
            "fake": _shelf_provider("fake", "Fake Music"),
            "x": _shelf_provider("x", "X"),
        }
    )
    assert WavesBridge._get_my_music_source_label(signed_out) == ""


def test_the_source_label_is_bridge_data_not_qml_copy():
    # The pane binds the bridge property and carries no label literal, so a
    # provider's own name (or a third provider's) reaches the UI without a
    # QML edit.
    qml = MAIN_QML.read_text(encoding="utf-8")

    assert "Saved from" not in qml
    assert "text: waves.myMusicSourceLabel" in qml

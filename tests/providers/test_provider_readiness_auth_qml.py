"""A third provider's readiness, actions and cancellable auth use shared QML."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event

import pytest
from providers.fakes import BareProvider
from providers.qml_auth import CallbackLoginAttempt
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until
from support.qml_probe import scene_js

from waves.providers import Capability, ProviderDescriptor


class _PaperProvider(BareProvider):
    id = "paper"
    name = "Paper Music"
    capabilities = frozenset({Capability.SEARCH, Capability.CATALOG, Capability.OPEN_URL, Capability.FAVORITES})
    public_operations = frozenset({Capability.SEARCH, Capability.CATALOG, Capability.OPEN_URL})

    def __init__(self) -> None:
        self.enabled = False
        self.signed_in = False
        self.entry_started = Event()
        self.release_entry = Event()
        self.entry_returned = Event()
        self.hold_entry = True
        self.submitted: list[str] = []
        self.persisted = 0

    @classmethod
    def descriptor(cls) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=cls.id,
            name=cls.name,
            welcome_action="Continue with Paper Music",
            link_hosts=("paper.test",),
        )

    @property
    def is_logged_in(self) -> bool:
        return self.signed_in

    def credential_facts(self) -> dict[str, str]:
        return {}

    def open_url(self, url: str) -> dict:
        return {"kind": "album", "item": _album(self.id)}

    def row_for(self, kind: str, item: dict) -> dict:
        return item

    def create_login_attempt(self, *, resume=False, register_secrets=None):
        def begin() -> str:
            if self.hold_entry:
                self.entry_started.set()
                if not self.release_entry.wait(5):
                    raise RuntimeError("the scenario did not release the held auth entry")
                self.entry_returned.set()
            return "https://paper.test/authorize"

        def validate(payload: str) -> bool:
            self.submitted.append(payload)
            return payload == "https://paper.test/redirect"

        def persist() -> None:
            self.persisted += 1
            self.signed_in = True

        return CallbackLoginAttempt(begin, validate, persist)


def _click(q, scope: str, name: str) -> None:
    q(
        scene_js(
            f"var action = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)} && o.visible; }});\n"
            "if (!action) throw new Error('missing visible provider action');\n"
            "action.clicked();\n"
        )
    )


def _album(provider_id: str) -> dict:
    return {
        "id": f"{provider_id}:album-1",
        "title": f"{provider_id} album",
        "artist": "Artist",
        "artist_id": "",
        "artists": [],
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "tracks": 1,
        "duration_sec": 180,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }


def _run_scenario() -> int:
    from PySide6.QtCore import QObject, QUrl, Slot
    from PySide6.QtGui import QDesktopServices

    class Browser(QObject):
        def __init__(self):
            super().__init__()
            self.urls: list[str] = []

        @Slot(QUrl)
        def opened(self, url: QUrl) -> None:
            self.urls.append(url.toString())

    browser = Browser()
    QDesktopServices.setUrlHandler("https", browser, "opened")
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    provider = _PaperProvider()
    bridge.providers[provider.id] = provider
    bridge._provider_readiness_probes[provider.id] = lambda: provider.readiness(
        enabled=provider.enabled, signed_in=provider.signed_in
    )

    def enable() -> None:
        provider.enabled = True
        bridge.providerStateChanged.emit(provider.id)

    bridge._provider_verb_flows[provider.id] = {"setup": enable}
    q("setupSettings.firstRunAnswered = true; root.openSearch()")
    bridge.providerStateChanged.emit(provider.id)
    wait_until(lambda: q("root.searchOpportunities.some(function(o) { return o.provider === 'paper' })"))
    assert not q("root.searchAvailable")
    assert q("waves.providerReadiness('paper').catalog") == "disabled"
    _click(q, "results", "emptyProviderCta_paper")
    wait_until(lambda: q("root.searchAvailable"))
    assert q("waves.providerReadiness('paper').account") == "signed_out"
    assert q("waves.providerReadiness('paper').catalog") == "ready"
    assert not q("root.searchOpportunities.some(function(o) { return o.provider === 'paper' })")
    assert q("waves.isProviderLink('paper.test/album/1')")
    assert not q("waves.isProviderLink('paper.test.evil/album/1')")
    q("searchDecoder.run('https://paper.test/album/1')")
    wait_until(lambda: q("(root.searchSources || []).some(function (s) { return s.provider === 'paper' })"))
    assert q("searchResultsView.modelFor('albums').get(0).title") == "paper album"

    # Begin waits at the provider boundary: cancel before its URL returns.
    bridge.providerAction(provider.id, "signin")
    wait_until(lambda: q("root.setupMode") == provider.id)
    assert q("root.setupProviderName") == provider.name
    _click(q, "setupPane", "welcomeSignInOpen")
    wait_until(provider.entry_started.is_set)
    _click(q, "setupPane", "welcomeSignInCancel")
    assert q("root.setupMode") == "cards"
    provider.release_entry.set()
    wait_until(provider.entry_returned.is_set)
    assert bridge.threadpool.waitForDone(2000)
    settle(100)
    assert browser.urls == []
    assert not q("root.setupUrlOpened")
    assert provider.persisted == 0

    # Cancelling the shared steps stops a decoder before it can submit.
    provider.hold_entry = False
    bridge.providerAction(provider.id, "signin")
    wait_until(lambda: q("root.setupMode") == provider.id)
    _click(q, "setupPane", "welcomeSignInOpen")
    wait_until(lambda: q("root.setupUrlOpened"))
    q(
        scene_js(
            "var box = findFirst(setupPane, function(o) { return o.objectName === 'signInPaste'; });\n"
            "box.pasteDecoder.run('https://paper.test/redirect');\n"
        )
    )
    _click(q, "setupPane", "welcomeSignInCancel")
    settle(800)
    assert provider.submitted == []
    assert provider.persisted == 0

    # A new attempt commits once through the public slot and completes its page.
    bridge.providerAction(provider.id, "signin")
    wait_until(lambda: q("root.setupMode") == provider.id)
    _click(q, "setupPane", "welcomeSignInOpen")
    wait_until(lambda: q("root.setupUrlOpened"))
    bridge.completeProviderLogin(provider.id, "https://paper.test/redirect")
    wait_until(lambda: q("waves.providerReadiness('paper').account") == "signed_in")
    wait_until(lambda: q("root.setupMode") == "cards")
    assert provider.persisted == 1
    assert not q("root.setupOpen")

    # Both sources hold actual rows; disabling Paper must retain TIDAL's
    # delegate and models rather than reconstructing the whole source list.
    bridge._logged_in = True
    bridge.providers["tidal"].favorites_page = lambda *args, **kwargs: ([], False)
    bridge.providers["tidal"].user_collections = lambda: {"playlists": [], "mixes": []}
    bridge.loggedInChanged.emit()
    wait_until(lambda: q("root.libGroupFor('tidal') !== null && root.libGroupFor('paper') !== null"))
    bridge.libraryLoaded.emit("tidal", "albums", [_album("tidal")], False)
    bridge.libraryLoaded.emit("paper", "albums", [_album("paper")], False)
    wait_until(lambda: q("root.libGroupFor('tidal').modelFor('albums').count") == 1)
    q("root.libGroupFor('tidal').category = 'albums'")

    # The two-source page is a REAL search through the bridge's fan-out (the
    # providers are faked at their boundary), so disabling Paper refolds the
    # displayed page and only its own rows leave.
    class _TidalAlbum:
        id = "tidal:album-1"
        name = "tidal album"

    bridge.providers["tidal"].search = lambda needle: {"albums": [_TidalAlbum()], "top_hit": None}
    bridge._album_dict = lambda album: _album("tidal")
    provider.search = lambda needle: {"albums": [_album("paper")]}
    q("root.submitSearch('probe')")
    wait_until(
        lambda: q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')") == "tidal,paper",
        timeout_ms=5000,
        message="both providers' search rows did not land",
    )

    # The changed provider's history leaves; unrelated account pages survive.
    q("root.navHistory = [{v:'artist',id:'paper:1'}, {v:'artist',id:'apple:2'}, {v:'artist',id:'123'}, {v:'settings'}]")
    q("root.navForwardHistory = [{v:'artist',id:'paper:1'}, {v:'artist',id:'apple:2'}]")
    q("root.searchSaved = {artistData:{id:'apple:2'}}")
    q("root.previewKind = 'track'; root.previewId = 'paper:track-1'; root.previewLoading = true")
    provider.enabled = False
    # An old status notification still observes every registered provider's
    # readiness transition; its signal name must not make the clear Apple-only.
    bridge.appleStatusChanged.emit()
    wait_until(lambda: q("root.navHistory.length") == 3)
    assert q("root.navHistory[0].id") == "apple:2"
    assert q("root.navHistory[1].id") == "123"
    assert q("root.navForwardHistory.length") == 1
    assert q("root.searchSaved.artistData.id") == "apple:2"
    assert q("root.previewId") == ""
    assert not q("root.previewLoading")
    assert q("root.searchAvailable")
    assert q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')") == "tidal"
    assert q("root.libGroupFor('paper') === null")
    assert q("root.libGroupFor('tidal').category") == "albums"
    assert q("root.libGroupFor('tidal').modelFor('albums').count") == 1
    # Another Paper change must preserve the unrelated legacy TIDAL preview.
    q("root.previewKind = 'track'; root.previewId = '123'; root.previewLoading = true")
    bridge.providerStateChanged.emit(provider.id)
    settle(50)
    assert q("root.previewId") == "123"
    assert q("root.previewLoading")
    QDesktopServices.unsetUrlHandler("https")
    return EXIT_OK


@pytest.mark.qml
def test_a_third_provider_has_catalog_readiness_and_cancellable_inline_auth():
    run_scenario(Path(__file__), "--run-scenario", timeout=45, sandbox_prefix="waves-provider-readiness-")


if __name__ == "__main__":
    if "--run-scenario" in sys.argv:
        raise SystemExit(_run_scenario())

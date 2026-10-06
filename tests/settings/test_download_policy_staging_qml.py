"""Rendered settings and Chooser controls preserve their staged policies."""

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    ROLLING_ALBUM_ROW,
    boot_main_qml,
    checkpoint,
    run_scenario,
    seed_tidal_search,
)

pytestmark = pytest.mark.qml


_FIND = """(function () {
    var seen = [];
    function walk(o) {
        if (!o || seen.indexOf(o) >= 0) return null;
        seen.push(o);
        if (o.visible === true && (%s)) return o;
        var children = o.children || [];
        for (var i = 0; i < children.length; i++) {
            var hit = walk(children[i]);
            if (hit) return hit;
        }
        var content = walk(o.contentItem);
        return content || walk(o.item);
    }
    return walk(root);
})()"""


def test_policy_edits_only_persist_after_save():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-policy-staging-", timeout=90)


def test_chooser_fallback_consents_reach_the_provider_independently_and_reset_on_reopen():
    run_scenario(Path(__file__), "--run-chooser", sandbox_prefix="waves-policy-chooser-", timeout=90)


def _boot():
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, _settle, _bridge = booted
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false; setupSettings.providerPickerDone = false"
    )
    q("providerPicker.visible = false; scrollDressing.visible = false")
    return booted


def _run_scenario():
    booted = _boot()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    q("settingsOpen = true")
    settle(400)
    q("settingsPage.setSectionOpen('downloads', true)")
    settle(150)
    combo = "(" + (_FIND % 'o.objectName === "settingsEnum_download_policies.shared.matching"') + ")"
    cancel = "(" + (_FIND % 'o.objectName === "cancelEditsBtn"') + ")"
    save = "(" + (_FIND % 'o.objectName === "saveChangesBtn"') + ")"
    checkpoint("visible policy selector")
    if not q(combo + " !== null"):
        return EXIT_REGRESSED
    original = bridge.settings.data.download_policies.shared.matching
    q(combo + ".incrementCurrentIndex(); " + combo + ".activated(1)")
    if bridge.settings.data.download_policies.shared.matching != original:
        return EXIT_REGRESSED
    q(cancel + ".triggered()")
    settle(100)
    checkpoint("cancel restores displayed policy")
    if bridge.settings.data.download_policies.shared.matching != original or q(combo + ".currentIndex") != 0:
        return EXIT_REGRESSED
    q(combo + ".incrementCurrentIndex(); " + combo + ".activated(1)")
    q(save + ".triggered()")
    settle(200)
    checkpoint("save persists displayed policy")
    if bridge.settings.data.download_policies.shared.matching != "release":
        return EXIT_REGRESSED
    q(combo + ".decrementCurrentIndex(); " + combo + ".activated(0)")
    q(cancel + ".triggered()")
    settle(100)
    return EXIT_OK if q(combo + ".currentIndex") == 1 else EXIT_REGRESSED


def _run_chooser():
    from waves.desktop.providers.catalog_identity import CatalogSelection
    from waves.desktop.providers.catalog_offers import OfferSnapshot
    from waves.metadata.catalog_identity import CatalogResolution, MatchState
    from waves.providers.base import DownloadAdapter
    from waves.providers.catalog_offers import CatalogOffer, OfferConstraints

    booted = _boot()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    requests = []

    class ProviderDownloads(DownloadAdapter):
        def serve_entry(self, kind, media_id, **kwargs):
            requests.append(kwargs)
            return True

    bridge.providers["tidal"].downloads = ProviderDownloads()
    q("openSearch()")
    seed_tidal_search(q, bridge, albums=[ROLLING_ALBUM_ROW])
    settle(500)
    button = "(" + (_FIND % 'o.mediaId === "al-roll" && typeof o.openChooser === "function"') + ")"
    assert q(button + " !== null"), "seeded album has no Chooser"
    provider_check = "(" + (_FIND % 'o.objectName === "chooserAllowProviderFallback"') + ")"
    engine_check = "(" + (_FIND % 'o.objectName === "chooserAllowEngineFallback"') + ")"
    for provider_allowed, engine_allowed in ((True, False), (False, True), (False, False)):
        q(button + ".openChooser()")
        settle(200)
        assert q(provider_check + " !== null") and q(engine_check + " !== null")
        assert not q(provider_check + ".picked") and not q(engine_check + ".picked"), "reopen retained consent"
        if provider_allowed:
            q(provider_check + ".clicked()")
        if engine_allowed:
            q(engine_check + ".clicked()")
        # The seeded search has no catalog lookup. Admit its origin through
        # the current guarded snapshot so this scenario owns consent dispatch.
        bridge.threadpool.waitForDone()
        settle(50)
        snapshot = OfferSnapshot(
            CatalogSelection("album", "al-roll"),
            (
                CatalogOffer(
                    "tidal",
                    "tidal:al-roll",
                    "album",
                    CatalogResolution("tidal:al-roll", MatchState.HIGH_CONFIDENCE),
                    OfferConstraints(),
                    readiness="ready",
                ),
            ),
            (lambda: True,),
        )
        bridge._catalog_offer_snapshot = (bridge._catalog_offer_generation, snapshot)
        previous_count = len(requests)
        q(button + ".confirmChooser()")
        assert len(requests) == previous_count + 1, "guarded confirmation did not reach the provider"
        toggles = requests[-1]["chooser_toggles"]
        assert toggles["allow_provider_fallback"] is provider_allowed
        assert toggles["allow_engine_fallback"] is engine_allowed
        assert "allow_fallback" not in toggles
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(_run_chooser() if "--run-chooser" in sys.argv else _run_scenario())

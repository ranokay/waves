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


def test_chooser_fallback_toggle_reaches_the_provider_and_resets_on_reopen():
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
    from waves.providers.base import DownloadAdapter

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
    if not q(button + " !== null"):
        return EXIT_REGRESSED
    q(button + ".openChooser()")
    settle(200)
    check = "(" + (_FIND % 'o.objectName === "chooserAllowFallback"') + ")"
    if not q(check + " !== null") or q(check + ".checked"):
        return EXIT_REGRESSED
    q(check + ".toggled()")
    q(button + ".confirmChooser()")
    if not requests or not requests[-1]["chooser_toggles"]["allow_fallback"]:
        return EXIT_REGRESSED
    q(button + ".openChooser()")
    settle(200)
    if q(check + ".checked"):
        return EXIT_REGRESSED
    q(button + ".confirmChooser()")
    return EXIT_OK if not requests[-1]["chooser_toggles"]["allow_fallback"] else EXIT_REGRESSED


if __name__ == "__main__":
    sys.exit(_run_chooser() if "--run-chooser" in sys.argv else _run_scenario())

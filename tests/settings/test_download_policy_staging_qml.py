"""The Settings page stages, discards and applies the single policy store."""

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario

pytestmark = pytest.mark.qml


def test_policy_edits_only_persist_after_apply():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-policy-staging-", timeout=90)


def _run_scenario():
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    q("settingsOpen = true")
    settle(400)
    original = bridge.settings.data.download_policies.shared.matching
    q('settingsPage.editMap = {"download_policies.shared.matching": "release"}; settingsPage.dirty = true')
    if bridge.settings.data.download_policies.shared.matching != original:
        return EXIT_REGRESSED
    q("settingsPage.discardEdits()")
    settle(100)
    if bridge.settings.data.download_policies.shared.matching != original or q("settingsPage.dirty"):
        return EXIT_REGRESSED
    q(
        'settingsPage.editMap = {"download_policies.shared.matching": "release", "download_policies.providers.apple.required_codec": "alac"}; settingsPage.dirty = true'
    )
    q("waves.applySettings(settingsPage.editMap)")
    settle(200)
    policies = bridge.settings.data.download_policies
    if policies.shared.matching != "release" or policies.effective("apple").required_codec != "alac":
        return EXIT_REGRESSED
    q("settingsPage.discardEdits()")
    settle(100)
    return EXIT_OK if bridge.settings.data.download_policies == policies else EXIT_REGRESSED


if __name__ == "__main__":
    sys.exit(_run_scenario())

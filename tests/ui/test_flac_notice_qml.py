"""The one-time FLAC signature notice, driven offscreen.

The real QML and the real bridge, with the session forced signed in (the app
needs a live account to reach Browse). What is pinned: it shows once on
Browse for an existing install; GOT IT persists the flag and it never returns;
it never stacks with a first-run prompt and appears once that prompt clears;
a fresh install marks it seen at the first terms acceptance and never sees it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    checkpoint,
    run_scenario,
    wait_until_true,
)
from support.qml_probe import scene_js

pytestmark = pytest.mark.qml


def test_the_flac_notice_shows_once_and_fresh_installs_never_see_it():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-flac-notice-",
        failure_message="the FLAC notice lost its once-per-install or fresh-install behaviour.",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, four checks)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    def visible() -> bool:
        return bool(q("flacNoticeGate.visible"))

    def seen() -> bool:
        return bool(q("setupSettings.flacNoticeSeen"))

    def click(name: str) -> bool:
        return bool(q(scene_js(f'var o = findObject(flacNoticeGate, "{name}"); if (o) o.clicked(); return !!o;')))

    problems: list[str] = []
    checkpoint("existing install shows once on Browse")
    bridge._set_logged_in(True)
    q("setupSettings.ffmpegSetupDone = true")
    q("setupSettings.flacNoticeSeen = false")
    q("setupSettings.updatePromptAnswered = true")
    q("legalSettings.termsAccepted = true")
    q("legalSettings.termsAcceptedVersion = termsVersion")
    q("bootOverlay.done = true")
    q("browseOpen = true")
    q("settingsOpen = false")
    q("artistOpen = false")
    q("libraryOpen = false")
    settle(200)
    if not wait_until_true(q, "flacNoticeGate.visible", "notice shown", 8000):
        problems.append("the notice never showed on Browse for an existing install")
    if seen():
        problems.append("the notice was already marked seen before it was answered")
    click("flacNoticeGotIt")
    if not wait_until_true(q, "!flacNoticeGate.visible", "notice answered", 8000):
        problems.append("the notice stayed up after GOT IT")
    if not seen():
        problems.append("GOT IT did not persist flacNoticeSeen")

    from PySide6.QtCore import QSettings

    # QML Settings flushes to QSettings on the event loop, so give the write
    # a beat instead of reading the old value in the same tick.
    stored = None
    for _ in range(40):
        stored = QSettings().value("setup/flacNoticeSeen")
        if stored in (True, "true", 1, "1"):
            break
        settle(50)
    if stored not in (True, "true", 1, "1"):
        problems.append(f"flacNoticeSeen did not reach QSettings: {stored!r}")

    q("browseOpen = false")
    settle(100)
    q("browseOpen = true")
    settle(700)
    if visible():
        problems.append("the notice came back after the user answered it")

    checkpoint("never stacks with a first-run prompt")
    q("setupSettings.flacNoticeSeen = false")
    q("setupSettings.updatePromptAnswered = false")
    settle(200)
    if bool(q("updateOptInGate.shouldShow")) is False:
        problems.append("the update prompt was not due, so the stacking case was not exercised")
    if visible():
        problems.append("the notice stacked over the update prompt")
    q("setupSettings.updatePromptAnswered = true")
    settle(200)
    if not wait_until_true(q, "flacNoticeGate.visible", "notice after the prompt cleared", 8000):
        problems.append("the notice did not appear once the update prompt cleared")

    checkpoint("a fresh install marks it seen at the terms gate")
    q("flacNoticeGate.shown = false")
    q("setupSettings.flacNoticeSeen = false")
    q("legalSettings.termsAccepted = false")
    q("legalSettings.termsAcceptedVersion = ''")
    q("setupSettings.updatePromptAnswered = true")
    q("browseOpen = true")
    settle(700)
    if visible():
        problems.append("the notice showed on a fresh install before the terms gate")
    q("ackChk.checked = true")
    q(scene_js('var o = findObject(termsGate, "termsAckAction"); if (o) o.clicked(); return !!o;'))
    settle(700)
    if not seen():
        problems.append("the first terms acceptance did not mark the notice seen")
    if visible():
        problems.append("the notice showed after a fresh install accepted the terms")

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return EXIT_REGRESSED
    print(f"ok stored={stored!r}")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())

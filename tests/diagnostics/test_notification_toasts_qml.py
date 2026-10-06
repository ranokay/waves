"""Toasts: severity timing, in-place updates, completion grouping, overflow,
hover/focus pause, expansion and the copy/report affordances."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from support.qml import EXIT_OK, boot_main_qml, checkpoint, run_scenario, wait_until

COMPLETION_KEY = "completions"


@pytest.mark.qml
def test_notification_toasts_hold_their_timing_focus_and_overflow_contract():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        sandbox_prefix="waves-notification-toasts-",
        drop=("WARN", "waves.qt"),
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    root, q, settle, bridge = boot
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from support.qml_probe import scene_js

    import waves.desktop.backend as bk
    from waves.events import EventAction, EventCode, EventDomain, Lifecycle, Severity, application_event
    from waves.redaction import register_secret

    def keys() -> list:
        return list(q("notificationToasts.visibleKeys()").toVariant())

    def entry(index: int) -> dict:
        value = q(f"notificationToasts.toastJson({index})")
        return json.loads(value) if value else {}

    def publish(event) -> None:
        bridge._events.publish(event)

    # The boot scenario's parked sign-in fails on purpose and publishes a real
    # account error; every assertion below starts from its own clean stack.
    for key in keys():
        bridge.dismissEvent(key)
    wait_until(lambda: keys() == [], timeout_ms=15000, message="quiet baseline")

    def click(name: str) -> None:
        q(
            scene_js(
                f"var o = findObject(root, '{name}'); if (!o) throw new Error('missing {name}');"
                " if (o.triggered) o.triggered(); else o.clicked(); return 1;"
            )
        )

    def dismiss(identity: str) -> None:
        bridge.dismissEvent(identity)
        wait_until(lambda: identity not in keys(), timeout_ms=15000, message=f"dismissed {identity[:8]}")

    checkpoint("error toast is sticky and never steals focus")
    focus_before = str(q(scene_js("return root.activeFocusItem ? ('' + root.activeFocusItem) : '';")))
    error = application_event(
        EventDomain.DOWNLOAD,
        "Download failed. Open the logs for details.",
        key="toast-error",
        title="Download",
        details=("Retried the same engine once",),
        exception=RuntimeError('password="toast-private-value"'),
        actions=(EventAction.OPEN_SETTINGS, EventAction.RETRY_JOB),
    )
    register_secret("toast-private-value")
    publish(error)
    wait_until(lambda: keys() == [error.id], timeout_ms=15000, message="error toast appears")
    focus_after = str(q(scene_js("return root.activeFocusItem ? ('' + root.activeFocusItem) : '';")))
    assert focus_after == focus_before, "a toast must not steal focus"
    assert entry(0)["title"] == "Download"
    card_name = q(scene_js("return findObject(notificationToasts, 'notificationCard').Accessible.name;"))
    assert "Download failed" in str(card_name)

    settle(4500)
    assert error.id in keys(), "an actionable error stays until dismissed or resolved"

    checkpoint("expand, advanced trace and the copy/report affordances")
    click("notificationExpand")
    assert bool(q(scene_js("return findObject(notificationToasts, 'notificationCard').expanded;")))
    click("notificationAdvanced")
    assert bool(q(scene_js("return findObject(notificationToasts, 'notificationCard').advanced;")))
    assert bool(
        q(
            scene_js(
                "var b = findFirst(notificationToasts, function (o) { return o.objectName === 'notificationCopyDiagnostics'; });"
                " return b !== null && b.visible === true;"
            )
        )
    ), "a retained entry offers copy-diagnostics"
    q(scene_js("findObject(root, 'notificationCopyDiagnostics').clicked(); return 1;"))
    copied = QGuiApplication.clipboard().text()
    assert "Download failed" in copied
    assert "toast-private-value" not in copied, "copy is redacted"
    opened: list[str] = []
    bk.QtGui.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(str(url)))
    q(scene_js("findObject(root, 'notificationReportIssue').clicked(); return 1;"))
    assert opened and "/issues/new" in opened[0]
    assert "toast-private-value" not in opened[0], "the draft is redacted"
    draft = {key: value[0] for key, value in parse_qs(opened[0].split("?", 1)[1]).items()}
    assert "Download failed" in draft["body"]

    checkpoint("dismiss removes the notice")
    click("notificationDismiss")
    wait_until(lambda: keys() == [], message="dismissed toast leaves")

    checkpoint("success expires while a warning outlives it")
    success = application_event(EventDomain.DOWNLOAD, "Saved Track A", key="toast-ok", severity=Severity.SUCCESS)
    publish(success)
    wait_until(lambda: keys() == [success.id], timeout_ms=15000, message="success toast appears")
    wait_until(lambda: keys() == [], timeout_ms=15000, message="success toast expires")

    checkpoint("a repeated issue updates one notice and keeps the peak count")
    warning = application_event(
        EventDomain.RUNTIME, "Runtime unavailable", key="toast-warning", severity=Severity.WARNING
    )
    publish(warning)
    publish(warning)
    wait_until(lambda: keys() == [warning.id], timeout_ms=15000, message="one notice for one identity")
    wait_until(
        lambda: int(entry(0).get("occurrences", 0)) == 2, timeout_ms=15000, message="occurrences update in place"
    )
    settle(5000)
    assert warning.id in keys(), "a warning outlives the success window"
    dismiss(warning.id)

    checkpoint("nearby completions group into one notice and can be disabled")
    completions = [
        application_event(
            EventDomain.DOWNLOAD,
            f"Finished Track {name}",
            key=f"toast-job-{name}",
            code=EventCode.COMPLETED,
            severity=Severity.SUCCESS,
            lifecycle=Lifecycle.RESOLVED,
        )
        for name in ("A", "B", "C")
    ]
    for event in completions:
        publish(event)
    wait_until(
        lambda: keys() == [COMPLETION_KEY] and entry(0).get("title") == "Finished 3 downloads",
        timeout_ms=15000,
        message="one completion notice",
    )
    assert entry(0)["title"] == "Finished 3 downloads"
    assert len(entry(0)["details"]) == 3
    q(
        scene_js(
            "findFirst(notificationToasts, function (o) { return o.objectName === 'notificationExpand'; }).triggered();"
            " return 1;"
        )
    )
    settle(100)
    assert bool(
        q(
            scene_js(
                "var b = findFirst(notificationToasts, function (o) { return o.objectName === 'notificationCopyDiagnostics'; });"
                " return b !== null && b.visible === false;"
            )
        )
    ), "the completion aggregate hides the copy/report affordances that need a retained entry"
    bridge.setWavesPref("notify_completion_toasts", False)
    quiet = application_event(
        EventDomain.DOWNLOAD,
        "Finished Track D",
        key="toast-job-D",
        code=EventCode.COMPLETED,
        severity=Severity.SUCCESS,
        lifecycle=Lifecycle.RESOLVED,
    )
    publish(quiet)
    settle(300)
    assert keys() == [COMPLETION_KEY], "completion toasts can be disabled"
    wait_until(lambda: keys() == [], timeout_ms=15000, message="completion notice expires")

    checkpoint("the motion pref reaches the live stack")
    bridge.setWavesPref("notification_motion", False)
    wait_until(lambda: q("notificationToasts.motion") is False, timeout_ms=10000, message="motion pref re-read")
    bridge.setWavesPref("notification_motion", True)
    wait_until(lambda: q("notificationToasts.motion") is True, timeout_ms=10000, message="motion pref restored")

    checkpoint("at most three visible; overflow waits in the center")
    infos = [
        application_event(
            EventDomain.LIBRARY, f"Library note {index}", key=f"toast-info-{index}", severity=Severity.INFO
        )
        for index in range(4)
    ]
    for event in infos:
        publish(event)
    wait_until(lambda: len(keys()) == 3, timeout_ms=15000, message="three visible")
    assert infos[3].id not in keys(), "the fourth waits in the center"
    wait_until(lambda: int(q("notificationToasts.overflow")) == 1, timeout_ms=15000, message="overflow counted")
    assert bool(q(scene_js("return findObject(root, 'notificationOverflow').visible;")))
    q(scene_js("findObject(root, 'notificationOverflowTap').triggered(); return 1;"))
    wait_until(lambda: bool(q("notificationCenter.opened")), timeout_ms=10000, message="overflow opens the center")
    assert int(q("notificationToasts.overflow")) == 0, "opening the center clears the overflow badge"
    q("notificationCenter.close()")
    for event in infos[:3]:
        dismiss(event.id)

    checkpoint("hover freezes the dismissal timer")
    hovered = application_event(EventDomain.SEARCH, "Search finished", key="toast-hover", severity=Severity.WARNING)
    publish(hovered)
    wait_until(lambda: keys() == [hovered.id], timeout_ms=15000, message="hover toast appears")
    card = q(scene_js("return findObject(notificationToasts, 'notificationCard');"))
    centre = card.mapToScene(QPointF(card.width() / 2, card.height() / 2))
    root.requestActivate()
    settle(100)

    def paused_state() -> dict:
        value = q(
            scene_js(
                "var c = findObject(notificationToasts, 'notificationCard');"
                " if (!c) return '';"
                " var t = c.parent;"
                " return JSON.stringify({paused: t.paused, msLeft: t.msLeft, leaving: t.leaving});"
            )
        )
        return json.loads(value) if value else {}

    # Hover delivery on the offscreen platform can swallow moves under load;
    # nudge the pointer until the card reports the pause.
    import time as _time

    deadline = _time.monotonic() + 8.0
    moved = 0
    state = paused_state()
    while not (state.get("paused") and state.get("msLeft", 0) > 0) and _time.monotonic() < deadline:
        QTest.mouseMove(root, QPoint(int(centre.x()) + (moved % 3), int(centre.y()) + (moved % 2)))
        settle(120)
        moved += 1
        state = paused_state()
    assert state.get("paused") and state["msLeft"] > 0 and not state["leaving"], state
    first = state["msLeft"]
    settle(1500)
    state = paused_state()
    assert state.get("paused") and state["msLeft"] == first, f"hover freezes the countdown: {first} -> {state}"
    QTest.mouseMove(root, QPoint(5, 5))
    settle(150)
    wait_until(lambda: keys() == [], timeout_ms=15000, message="unhovered notice resumes and leaves")

    checkpoint("keyboard focus freezes the dismissal timer")
    focused = application_event(
        EventDomain.SEARCH, "Search finished again", key="toast-focus", severity=Severity.SUCCESS
    )
    publish(focused)
    wait_until(lambda: keys() == [focused.id], timeout_ms=15000, message="focus toast appears")
    button = q(scene_js("return findObject(root, 'notificationDismiss');"))
    button.forceActiveFocus()
    wait_until(
        lambda: bool(
            q(
                scene_js(
                    "var c = findObject(notificationToasts, 'notificationCard');"
                    " return c && c.parent && c.parent.paused === true;"
                )
            )
        ),
        timeout_ms=5000,
        message="focus registers as pause",
    )
    state = json.loads(
        q(
            scene_js(
                "var t = findObject(notificationToasts, 'notificationCard').parent;"
                " return JSON.stringify({paused: t.paused, msLeft: t.msLeft, leaving: t.leaving});"
            )
        )
    )
    assert state["paused"] and state["msLeft"] > 0 and not state["leaving"], state
    first = state["msLeft"]
    settle(1500)
    state = json.loads(
        q(
            scene_js(
                "var t = findObject(notificationToasts, 'notificationCard').parent;"
                " return JSON.stringify({paused: t.paused, msLeft: t.msLeft});"
            )
        )
    )
    assert state["paused"] and state["msLeft"] == first, f"focus freezes the countdown: {first} -> {state}"
    q("searchField.forceActiveFocus()")
    wait_until(lambda: keys() == [], timeout_ms=15000, message="unfocused notice resumes and leaves")

    bridge.shutdown()
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())

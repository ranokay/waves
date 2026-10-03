"""Incubation remains live and yields between boot and page frames."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from support.qml import EXIT_OK, checkpoint, run_scenario, sandbox_app_config, sandbox_qml_settings, wait_until

from waves.desktop import app as desktop_app
from waves.desktop.app import _BootPacedIncubation, _content_item


class _Timer:
    def __init__(self) -> None:
        self.active = True
        self._interval = _BootPacedIncubation._TICK_MS

    def interval(self) -> int:
        return self._interval

    def setInterval(self, ms: int) -> None:
        self._interval = ms

    def stop(self) -> None:
        self.active = False


class _Screen:
    def __init__(self, rate: float) -> None:
        self.rate = rate

    def refreshRate(self) -> float:
        return self.rate


class _ScreenChanged:
    def __init__(self) -> None:
        self.listeners: list[Callable[[_Screen], None]] = []

    def connect(self, listener: Callable[[_Screen], None]) -> None:
        self.listeners.append(listener)

    def emit(self, screen: _Screen) -> None:
        for listener in self.listeners:
            listener(screen)


class _Window:
    def __init__(self, rate: float = 60.0) -> None:
        self.current_screen = _Screen(rate)
        self.screenChanged = _ScreenChanged()

    def screen(self) -> _Screen:
        return self.current_screen

    def move_to(self, rate: float) -> None:
        self.current_screen = _Screen(rate)
        self.screenChanged.emit(self.current_screen)


class _Stub:
    """State consumed by real pacer methods, without a Qt controller."""

    _BOOT_SLICE_MS = _BootPacedIncubation._BOOT_SLICE_MS
    _TICK_MS = _BootPacedIncubation._TICK_MS
    _IDLE_TICK_MS = _BootPacedIncubation._IDLE_TICK_MS
    _FRAME_FRESH_S = _BootPacedIncubation._FRAME_FRESH_S
    _slices_for = staticmethod(_BootPacedIncubation._slices_for)
    _read_screen = _BootPacedIncubation._read_screen
    _set_tick = _BootPacedIncubation._set_tick
    _tick = _BootPacedIncubation._tick
    _frame = _BootPacedIncubation._frame
    attach_window = _BootPacedIncubation.attach_window
    release_throttle = _BootPacedIncubation.release_throttle
    count_reader = _BootPacedIncubation.count_reader
    set_count_notifier = _BootPacedIncubation.set_count_notifier

    def __init__(self, *, count: int = 7, hook: bool | RuntimeError | TypeError = False) -> None:
        self._boot = True
        self._released = False
        self._notify: Callable[[int], None] | None = None
        self._last_frame = 0.0
        self._win: _Window | None = None
        self._timer = _Timer()
        self._frame_slice_ms, self._open_slice_ms, self._frame_period_s = self._slices_for(60.0)
        self.count = count
        self.hook = hook
        self.hooks = 0
        self.slices: list[int] = []

    def incubatingObjectCount(self) -> int:
        return self.count

    def incubateFor(self, ms: int) -> None:
        self.slices.append(ms)

    def _hook_frames(self) -> bool:
        self.hooks += 1
        if isinstance(self.hook, (RuntimeError, TypeError)):
            raise self.hook
        return self.hook


def test_the_count_virtual_is_not_overridden():
    assert "incubatingObjectCountChanged" not in _BootPacedIncubation.__dict__


def test_the_count_reader_answers_the_live_count():
    pacer = _Stub()
    read = pacer.count_reader()
    assert read() == 7
    pacer.count = 2
    assert read() == 2


def test_boot_ticks_always_incubate_and_frames_do_not():
    pacer = _Stub(count=0)
    pacer._tick()
    pacer._frame()
    assert pacer.slices == [_BootPacedIncubation._BOOT_SLICE_MS]
    assert pacer._timer.active


@pytest.mark.parametrize("hook", [True, False, RuntimeError("no window"), TypeError("no signal")])
def test_release_keeps_timer_fallback_and_notifies_once(hook, monkeypatch):
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: 100.0)
    pacer = _Stub(hook=hook)
    seen: list[int] = []
    pacer.set_count_notifier(seen.append)

    pacer.release_throttle()
    pacer.release_throttle()
    pacer._tick()

    assert not pacer._boot
    assert pacer.hooks == 1
    assert seen == [0]
    assert pacer._timer.active
    assert pacer.slices == [10]


def test_timer_yields_to_recent_frames_and_resumes_after_the_gap(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: now[0])
    pacer = _Stub()
    pacer.release_throttle()
    pacer._frame()
    now[0] += 0.02
    pacer._tick()
    assert pacer.slices == [5]

    now[0] += pacer._FRAME_FRESH_S
    pacer._tick()
    assert pacer.slices == [5, 10]


def test_idle_pacer_relaxes_and_a_new_build_wakes_the_timer(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: now[0])
    pacer = _Stub(count=0)
    pacer.release_throttle()
    pacer._tick()
    pacer._frame()
    assert pacer.slices == []
    assert pacer._timer.interval() == pacer._IDLE_TICK_MS
    assert pacer._timer.active

    pacer.count = 3
    now[0] += 0.1
    pacer._tick()
    assert pacer.slices == [10]
    assert pacer._timer.interval() == pacer._TICK_MS

    pacer.count = 0
    pacer._tick()
    assert pacer.slices == [10]
    assert pacer._timer.interval() == pacer._IDLE_TICK_MS


@pytest.mark.parametrize(
    ("rate", "frame_ms", "timer_ms", "period"),
    [
        (60.0, 5, 10, 1 / 60),
        (120.0, 2, 4, 1 / 120),
        (144.0, 2, 4, 1 / 144),
        (0.0, 5, 10, 1 / 60),
        (-1.0, 5, 10, 1 / 60),
        (float("nan"), 5, 10, 1 / 60),
        (float("inf"), 5, 10, 1 / 60),
    ],
)
def test_slices_follow_valid_display_rates_and_default_unknown_rates(rate, frame_ms, timer_ms, period):
    frame, timer, actual_period = _BootPacedIncubation._slices_for(rate)
    assert (frame, timer) == (frame_ms, timer_ms)
    assert actual_period == pytest.approx(period)


def test_queued_frame_backlog_incubates_once_and_the_next_frame_incubates_again(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: now[0])
    pacer = _Stub()
    pacer.attach_window(_Window(120.0))
    pacer.release_throttle()
    pacer._frame()
    for _ in range(4):
        now[0] += 0.0002
        pacer._frame()
    now[0] += 1 / 120
    pacer._frame()
    assert pacer.slices == [2, 2]


def test_screen_change_resizes_the_next_frame_and_timer_slices(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: now[0])
    window = _Window()
    pacer = _Stub()
    pacer.attach_window(window)
    assert pacer.hooks == 0
    pacer.release_throttle()
    pacer._frame()

    window.move_to(120.0)
    now[0] += 1 / 120
    pacer._frame()
    now[0] += 0.1
    pacer._tick()
    assert pacer.slices == [5, 2, 4]
    assert pacer._frame_period_s == pytest.approx(1 / 120)


def test_unreadable_screen_uses_default_slices():
    class BrokenWindow(_Window):
        def screen(self) -> _Screen:
            raise RuntimeError("window destroyed")

    pacer = _Stub()
    pacer.attach_window(BrokenWindow(120.0))
    assert (pacer._frame_slice_ms, pacer._open_slice_ms) == (5, 10)
    assert pacer._frame_period_s == pytest.approx(1 / 60)


@pytest.mark.parametrize("wake", ["timer", "frame"])
def test_waking_rechecks_a_screen_rate_changed_while_idle(monkeypatch, wake):
    now = [100.0]
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: now[0])
    window = _Window()
    pacer = _Stub(count=0)
    pacer.attach_window(window)
    pacer.release_throttle()
    pacer._tick()
    assert pacer._timer.interval() == pacer._IDLE_TICK_MS

    # The same QScreen changes rate, so QWindow.screenChanged does not fire.
    window.current_screen.rate = 120.0
    pacer.count = 3
    now[0] += 0.1
    (pacer._tick if wake == "timer" else pacer._frame)()
    assert pacer.slices == [4 if wake == "timer" else 2]
    assert pacer._timer.interval() == pacer._TICK_MS
    assert pacer._frame_period_s == pytest.approx(1 / 120)


_WINDOW_QML = b"""
import QtQuick
import QtQuick.Controls.Basic
ApplicationWindow {
    id: window
    visible: true
    width: 300
    height: 200
    property int first: 0
    property int second: 0
    property int built: 0
    property bool animating: false
    Component {
        id: row
        Rectangle {
            width: 100
            height: 1
            Repeater { model: 40; Text { text: "row" } }
            Component.onCompleted: window.built++
        }
    }
    Column {
        Repeater {
            model: window.first
            delegate: Loader {
                asynchronous: true
                width: 100
                height: 1
                sourceComponent: row
            }
        }
    }
    Column {
        x: 120
        Repeater {
            model: window.second
            delegate: Loader {
                asynchronous: true
                width: 100
                height: 1
                sourceComponent: row
            }
        }
    }
    Rectangle {
        width: 10
        height: 10
        color: "blue"
        NumberAnimation on x {
            from: 0
            to: 200
            duration: 1000
            loops: Animation.Infinite
            running: window.animating
        }
    }
}
"""


@pytest.mark.qml
def test_binding_free_window_paces_frames_and_completes_a_build_started_while_idle():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=45,
        sandbox_prefix="waves-incubation-test-",
        failure_message="binding-free incubation pacing regressed",
    )


def _counting_pacer(app):
    from PySide6.QtCore import QThread

    class Counting(_BootPacedIncubation):
        def __init__(self) -> None:
            self.frame_slices = 0
            self.timer_slices = 0
            self.wakes = 0
            self._source = "timer"
            super().__init__(app)

        def _set_tick(self, ms: int) -> None:
            if ms == self._TICK_MS and self._timer.interval() == self._IDLE_TICK_MS:
                self.wakes += 1
            super()._set_tick(ms)

        def incubateFor(self, ms: int) -> None:
            assert QThread.currentThread() == app.thread(), "incubation left the GUI thread"
            if not self._boot:
                if self._source == "frame":
                    self.frame_slices += 1
                else:
                    self.timer_slices += 1
            super().incubateFor(ms)

        def _frame(self) -> None:
            self._source = "frame"
            try:
                super()._frame()
            finally:
                self._source = "timer"

    return Counting()


def _run_scenario() -> int:
    sandbox_app_config()
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
    from PySide6.QtGui import QGuiApplication, QWindow
    from PySide6.QtQml import QQmlApplicationEngine

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    assert "PySide6.QtQuick" not in sys.modules

    engine = QQmlApplicationEngine()
    pacer = _counting_pacer(app)
    assert pacer._timer.isActive(), "boot must start the timer without a count callback"
    engine.setIncubationController(pacer)
    engine.loadData(_WINDOW_QML, QUrl("incubation-window.qml"))
    roots = engine.rootObjects()
    assert len(roots) == 1, "ApplicationWindow did not load"
    window = roots[0]
    assert type(window) is QWindow, "the scenario must use the packaged app's plain window wrapper"

    content = _content_item(window)
    assert content is not None and content != window
    assert content.metaObject().className() == "QQuickRootItem"
    assert content.parent() == window

    class TargetFilter(QObject):
        def __init__(self) -> None:
            super().__init__(app)
            self.targets: list[QObject] = []

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.User:
                self.targets.append(watched)
            return False

    target_filter = TargetFilter()
    content.installEventFilter(target_filter)
    QCoreApplication.sendEvent(content, QEvent(QEvent.Type.User))
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.User))
    assert target_filter.targets == [content], "the filter must target the content root, not the window"

    pacer.attach_window(window)
    assert pacer._relay is None, "boot must not connect a crossing per frame"
    pacer.release_throttle()
    assert pacer._relay is not None, "the named frame signal did not connect"
    assert pacer._relay.thread() == app.thread()
    assert pacer._timer.isActive()

    try:
        checkpoint("first animated build")
        window.setProperty("animating", True)
        window.setProperty("first", 200)
        wait_until(
            lambda: window.property("built") == 200 and pacer.incubatingObjectCount() == 0,
            timeout_ms=8000,
            message="first 200 rows complete",
        )
        assert pacer.frame_slices > 0, "frames never carried an incubation slice"

        checkpoint("idle beat")
        window.setProperty("animating", False)
        wait_until(
            lambda: pacer._timer.interval() == pacer._IDLE_TICK_MS,
            timeout_ms=1500,
            message="pacer idle after first build",
        )
        before_slices = pacer.frame_slices + pacer.timer_slices
        before_wakes = pacer.wakes

        checkpoint("build started while idle")
        window.setProperty("second", 100)
        wait_until(
            lambda: window.property("built") == 300 and pacer.incubatingObjectCount() == 0,
            timeout_ms=5000,
            message="all 300 rows complete after idle",
        )
        assert pacer.wakes > before_wakes, "new incubation did not wake the busy beat"
        assert pacer.frame_slices + pacer.timer_slices > before_slices
        wait_until(
            lambda: pacer._timer.interval() == pacer._IDLE_TICK_MS,
            timeout_ms=1500,
            message="pacer idle after second build",
        )
        assert pacer._timer.isActive()
        assert "PySide6.QtQuick" not in sys.modules
        checkpoint("binding-free builds complete")
        return EXIT_OK
    finally:
        pacer._timer.stop()
        window.close()


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())

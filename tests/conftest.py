"""Shared test doubles for the WavesBridge unit tests.

The bridge tests are Qt-free: they bind the real, unbound ``WavesBridge`` methods
onto a minimal stand-in and drive them with fakes instead of a live QObject, a
QThreadPool, or an event loop. ``_Signal`` (``support.signals.RecordingSignal``)
and ``_InlinePool`` are the shared doubles; import them with
``from conftest import _Signal, _InlinePool``.

Deliberately NOT centralized:
  * ``_Stub`` stays per-file. It is not one fake but many: each test's stand-in
    carries exactly the state that test's bound methods read and write, so a
    shared version would be a grab-bag, not a contract. Each inherits
    ``support.bridge_stub.BridgeStub``, which only answers the bridge's public
    signals.
  * A couple of purpose-built variants keep their own copy where the extra
    behavior is the point (e.g. an _InlinePool that counts ``start()`` calls, or
    a signal double that records single values under a different name).
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

import pytest
from support.signals import RecordingSignal

# Every test in this suite runs against a throwaway config directory.
#
# A test that builds a real WavesBridge otherwise reads and WRITES the config
# of the machine it runs on: __init__ alone stamps waves.json (see
# _migrate_video_flag), so one suite run could overwrite a real install's
# library switch, folder and MusicBrainz choice, its window geometry and its
# explicit-version setting with whatever the test happened to hold. Nothing in
# a test may touch a person's own settings, whether or not the test remembers
# to sandbox itself.
#
# path_config_base honors XDG_CONFIG_HOME on every platform, and this runs at
# conftest import, before any test module is imported and before any path is
# resolved from it. The subprocess scenarios copy this environment, so they
# land in the same throwaway home unless they name one of their own.
#
# Nothing here ever un-sandboxes the session. The live account suite is the
# exception that proves it: its module switches the variable back around its
# own fixture only (see tests/account/test_live_account.py), so an ordinary
# test can never touch the real profile, whatever the gate says.
_TEST_CONFIG_HOME = tempfile.mkdtemp(prefix="waves-test-config-")
ORIGINAL_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME")
os.environ["XDG_CONFIG_HOME"] = _TEST_CONFIG_HOME
atexit.register(shutil.rmtree, _TEST_CONFIG_HOME, True)


# The recording signal double lives in support.signals (QML scenario children
# import it without this conftest); `_Signal` stays its name here.
_Signal = RecordingSignal


class _InlinePool:
    """Stand-in for a ``QThreadPool`` that runs a dispatched ``Worker``
    synchronously on the calling thread, so worker dispatch is exercised without
    a real thread or event loop and the slot completes before ``start`` returns.
    """

    def start(self, worker, priority: int = 0) -> None:
        # Priority is accepted and ignored: QThreadPool takes one (the library
        # seed is dispatched raised, to jump a queue busy with downloads), and
        # running inline there is no queue for it to jump.
        worker.run()


class _InlineWriter:
    """Stand-in for the bridge's ``SingleFlightWriter`` that performs each
    submitted config write synchronously, so a test that borrows the real
    ``_save_settings`` / ``_save_waves_prefs`` can assert what landed on disk
    right after the call, exactly as before those saves went off-thread. The
    writer's own async behavior is covered by its dedicated tests."""

    def submit(self, key: str, fn) -> None:
        fn()

    def flush(self, timeout: float = 0.0) -> None:
        pass


@pytest.fixture(autouse=True)
def _bridge_stand_ins_are_bridge_stubs():
    """Every object a test runs bridge methods on is a support.bridge_stub
    BridgeStub (or a real bridge or a mock), so a new bridge signal reaches it
    without an edit. Tests that never load the bridge skip the check."""
    if "waves.desktop.backend" not in sys.modules:
        yield
        return
    from support import bridge_stub

    bridge_stub.watch_stand_ins()
    bridge_stub.take_offenders()
    yield
    offenders = bridge_stub.take_offenders()
    if offenders:
        pytest.fail(
            "bridge methods ran on stand-ins that are not support.bridge_stub.BridgeStub:\n" + "\n".join(offenders),
            pytrace=False,
        )


@pytest.fixture
def isolated_settings_migrations(tmp_path, monkeypatch):
    """Keep one test's migration sidecar out of the shared config home.

    The sidecar beside settings.json is what keeps a one-time migration from
    replaying after a downgrade, so a test that drives ``_migrate_settings``
    directly must not read a sidecar another test left behind (and must not
    leave one for the next). Tests that need the sidecar write it themselves.
    """
    from waves import config

    monkeypatch.setattr(config, "_migrations_state_path", lambda: tmp_path / "settings-migrations.json")


# ---------------------------------------------------------------------------
# Markers and the GUI-required run
# ---------------------------------------------------------------------------


def pytest_addoption(parser) -> None:
    """The GUI-required run's switch: skips become failures."""
    parser.addoption(
        "--require-qml",
        action="store_true",
        default=False,
        help="fail instead of skipping when QML scenarios cannot run (GUI-required)",
    )


def pytest_configure(config) -> None:
    """Record --require-qml and refuse to run it without PySide6."""
    from support import qml as qml_support

    qml_support.set_require_qml(config.getoption("require_qml"))
    if qml_support.require_qml() and qml_support.missing_qt():
        raise pytest.UsageError("--require-qml was given but PySide6 is not importable")


def _skip_marked(items, marker: str, reason: str) -> None:
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker(marker):
            item.add_marker(skip)


def pytest_collection_modifyitems(config, items) -> None:
    """Auto-skip marked tests only for a positively missing dependency."""
    from support import qml as qml_support

    if os.environ.get("WAVES_ACCOUNT_TESTS") != "1":
        _skip_marked(items, "account", "live account tests; set WAVES_ACCOUNT_TESTS=1 to run")
    if shutil.which("ffmpeg") is None:
        _skip_marked(items, "ffmpeg", "ffmpeg is not on PATH")
    if qml_support.missing_qt() and not qml_support.require_qml():
        _skip_marked(items, "qml", "PySide6 is not importable")

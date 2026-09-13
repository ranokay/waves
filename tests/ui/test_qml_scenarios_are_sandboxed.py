"""An offscreen scenario must never run against the real config directory.

WHAT THIS FENCES OFF
--------------------
A scenario that builds a real ``WavesBridge`` inherits whatever config
directory the environment points at, and on a developer's machine that is
the packaged app's own: ``~/Library/Application Support/Waves`` (or the
platform equivalent). The bridge then adopts the user's settings, writes
its startup lines and tracebacks into the user's ``waves_dev.log``, and,
if a library root is configured, starts a REAL scan of the user's music
library from its constructor.

Three scenarios were missing the sandbox, and it showed: a verbose log
kept for a livetest was interleaved with test sessions, each one starting
a library scan that bailed seconds later, and a test's own "live TIDAL API
disabled in this test" traceback was written into it as an app ERROR.

HOW THIS STAYS FIXED
--------------------
Every test module that constructs a bridge behind a QML engine either runs
its child through ``support.qml.run_scenario`` (which hands it a private
``XDG_CONFIG_HOME``) or sets that variable on its own subprocess env.
``path_config_base()`` honours the variable first on every platform, so a
scenario given one can only ever touch a temporary directory.
"""

from __future__ import annotations

from support.paths import TESTS_ROOT


def test_every_offscreen_bridge_scenario_sandboxes_its_config_dir():
    unsandboxed = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        src = path.read_text()
        builds_bridge = "WavesBridge(" in src and "QQmlApplicationEngine" in src
        if not builds_bridge:
            continue
        runs_shared = "from support.qml import" in src and "run_scenario(" in src
        if "XDG_CONFIG_HOME" not in src and not runs_shared:
            unsandboxed.append(str(path.relative_to(TESTS_ROOT)))

    assert not unsandboxed, (
        "these scenarios build a real WavesBridge without an XDG_CONFIG_HOME of "
        "their own, so they run against the packaged app's config dir: they adopt "
        "the user's settings, write into the user's log, and start a real scan of "
        "the user's library. Run them through support.qml.run_scenario (or set "
        'env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-<name>-test-")): ' + ", ".join(unsandboxed)
    )

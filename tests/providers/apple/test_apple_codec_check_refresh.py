"""The Apple wizard's codec-check step follows the FFmpeg install.

The step reads the ffprobe beside the Apple provider's ffmpeg, and an FFmpeg
install, update or remove is what moves it. Proved on the real Settings page:
the rendered step says the format check is skipped while no ffprobe exists,
and flips to done once one lands beside ffmpeg and ffmpegStatusChanged fires,
with no Apple signal in between.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_PRECONDITION, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

# Every text the Settings page shows, Loader items included. A hidden
# subtree is skipped: the schema renders control variants per row, and only
# the visible one is on screen.
_TEXTS_BODY = """
    var texts = [];
    function collect(o) {
        if (!o || o.visible === false) return;
        if (o.text !== undefined && ("" + o.text).length > 0) texts.push("" + o.text);
        if (o.item) collect(o.item);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) collect(kids[i]);
    }
    collect(settingsPage);
    return JSON.stringify(texts);
"""

_SKIPPED = "skip the format check"
_CHECKED = "checked for the format it asked for"


@pytest.mark.qml
def test_the_codec_check_step_follows_an_ffmpeg_install():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-apple-codec-check-",
        failure_message="the codec-check step no longer follows the FFmpeg install",
    )


def _tool(folder: Path, name: str) -> Path:
    tool = folder / (name + (".exe" if os.name == "nt" else ""))
    tool.write_bytes(b"#!/bin/sh\n")
    tool.chmod(0o755)
    return tool


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    q("waves.applySettings({'apple_enabled': true})")
    q("root.refreshAppleEnabled()")
    settle(300)

    q("settingsOpen = true")
    settle(300)
    q("settingsPage.jumpToCard('providers_apple')")
    settle(500)

    # A managed-looking ffmpeg with nothing beside it, and no ffprobe on
    # PATH. The page computed its mirror off the host's own binaries, so an
    # Apple signal re-reads it once: the baseline must not come from the
    # FFmpeg signal the flip below is about.
    tools = Path(tempfile.mkdtemp(prefix="waves-codec-check-tools-"))
    ffmpeg = _tool(tools, "ffmpeg")
    os.environ["PATH"] = str(tools / "nothing-here")
    bridge.providers["apple"].ffmpeg_path = str(ffmpeg)
    bridge.appleStatusChanged.emit()
    settle(300)

    def texts() -> list[str]:
        rendered = str(q(scene_js(_TEXTS_BODY)) or "")
        return json.loads(rendered) if rendered else []

    before = texts()
    if "Codec check (ffprobe)" not in before:
        print("the Apple wizard column renders no codec-check step", file=sys.stderr)
        return EXIT_PRECONDITION

    failures = []
    if not any(_SKIPPED in text for text in before):
        failures.append("with no ffprobe anywhere, the step does not say the format check is skipped")

    _tool(tools, "ffprobe")
    bridge.ffmpegStatusChanged.emit()
    settle(300)

    after = texts()
    if any(_SKIPPED in text for text in after):
        failures.append("the step still says the check is skipped after ffprobe landed beside ffmpeg")
    if not any(_CHECKED in text for text in after):
        failures.append("the step never reads done after ffprobe landed beside ffmpeg")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())

"""Apple's console programs start without a console window on Windows.

The packaged Windows app has no console, so a console program it starts
without CREATE_NO_WINDOW opens a window of its own over the UI: once per
verified track for ffprobe and the ffmpeg decode check. Every Apple spawn
takes its options from ``child_guard.NO_WINDOW``; each case sets them to
Windows' value and drives one spawn through its public entry point.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from waves.providers.apple import child_guard, engine, files, integrity, runtime
from waves.providers.apple.supervision import SidecarSupervisor

# subprocess.CREATE_NO_WINDOW, which exists only on Windows.
CREATE_NO_WINDOW = 0x08000000


def test_spawn_options_hide_the_console_on_windows_only():
    expected = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    assert expected == child_guard.NO_WINDOW


def _tool(tmp_path: Path) -> str:
    tool = tmp_path / "tool"
    tool.write_bytes(b"")
    return str(tool)


def _song(tmp_path: Path) -> Path:
    song = tmp_path / "song.m4a"
    song.write_bytes(b"m4a")
    return song


def _install_download_tool(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        member = tarfile.TarInfo("N_m3u8DL-RE")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"tool"))
    blob = archive.getvalue()
    release = runtime.Nm3u8dlreRelease(
        version="test", url="https://example.invalid/N.tar.gz", sha256=hashlib.sha256(blob).hexdigest()
    )
    response = SimpleNamespace(raise_for_status=lambda: None, headers={}, iter_content=lambda chunk_size: [blob])
    session = SimpleNamespace(get=lambda url, **_k: contextlib.nullcontext(response))
    runtime.AppleRuntimeManager(tmp_path).install(release=release, session=session)


# Each spawn's fake output, enough for its entry point to finish.
SPAWNS = [
    pytest.param(
        '{"streams": [{"codec_name": "alac"}]}',
        lambda tmp: engine.probe_audio_file(_song(tmp), _tool(tmp)),
        id="codec probe",
    ),
    pytest.param("", lambda tmp: engine.decode_check(_song(tmp), _tool(tmp)), id="decode check"),
    pytest.param(
        '{"format": {"tags": {"creation_time": "2025-06-01T00:00:00Z"}}}',
        lambda tmp: integrity.encoded_date_of(_song(tmp), _tool(tmp)),
        id="encoded date",
    ),
    pytest.param(b"png", lambda tmp: files.convert_image(b"jpeg", "png", _tool(tmp)), id="cover conversion"),
    pytest.param("", lambda tmp: runtime.detect_container_runtime(), id="container runtime detection"),
    pytest.param("[]", lambda tmp: runtime.AppleRuntimeManager(tmp).ensure_image(), id="wrapper image pull"),
    pytest.param("N_m3u8DL-RE 0.3.0", _install_download_tool, id="download tool install"),
    pytest.param("", lambda tmp: SidecarSupervisor().stop(), id="wrapper sidecar stop"),
]


@pytest.mark.parametrize(("stdout", "spawn"), SPAWNS)
def test_apple_spawn_opens_no_console_window_on_windows(tmp_path, monkeypatch, stdout, spawn):
    monkeypatch.setattr(child_guard, "NO_WINDOW", {"creationflags": CREATE_NO_WINDOW})
    calls = []

    def fake_run(args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    spawn(tmp_path)
    assert calls, "the entry point started no program"
    assert [kwargs.get("creationflags") for kwargs in calls] == [CREATE_NO_WINDOW] * len(calls)

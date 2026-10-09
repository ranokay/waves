"""The Apple downloader ends with its job, and with Waves.

gamdl starts N_m3u8DL-RE with nothing tying it to the fetch or the app, so a
stopped job and a killed Waves both left it downloading (issue #660). These
tests run a stand-in downloader through the real launch path: a script that
takes a file lock and sleeps. The OS frees the lock when the process dies,
however it dies, so a lock that frees is a downloader that is gone.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves.constants import QualityTier
from waves.providers.apple import AppleProvider, child_guard, engine, workdirs
from waves.providers.base import AudioType

REPO_ROOT = Path(__file__).resolve().parents[3]

_STANDIN = """\
import os, time
fd = os.open({lock!r}, os.O_RDWR | os.O_CREAT, 0o600)
if os.name == "nt":
    import msvcrt
    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
else:
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)
open({ready!r}, "w").close()
time.sleep(120)
"""


@dataclass
class _Standin:
    script: Path
    lock: Path
    ready: Path

    def alive(self) -> bool:
        """Whether the stand-in still holds its lock."""
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        finally:
            os.close(fd)
        return False


def _standin(tmp_path: Path) -> _Standin:
    lock, ready = tmp_path / "standin.lock", tmp_path / "standin.ready"
    script = tmp_path / "standin.py"
    script.write_text(_STANDIN.format(lock=str(lock), ready=str(ready)))
    return _Standin(script, lock, ready)


def _wait(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _fetch(tier: str, session: engine.AppleFetchSession, abort: Event):
    if tier == "cookies":
        return session.download_song(song_id="song-1", atmos=False, abort=abort)
    return session.download_alac(song_id="song-1", abort=abort)


@pytest.mark.parametrize("guarded", [True, False], ids=["guarded", "unguarded"])
@pytest.mark.parametrize("tier", ["cookies", "wrapper"])
def test_stopping_a_job_ends_its_downloader_and_removes_its_workdir(tmp_path, monkeypatch, tier, guarded):
    """STOP mid-song: the downloader dies and the fetch's workdir goes with it."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    standin = _standin(tmp_path)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    # The interpreter stands in for N_m3u8DL-RE: gamdl's argv puts the stream
    # URL first, so the "URL" is the stand-in script.
    monkeypatch.setattr(engine, "_require_binary", lambda name, override="": sys.executable)
    monkeypatch.setattr(engine, "_require_yt_dlp", lambda: None)

    async def cookies_stack(cookies_path):
        return SimpleNamespace(client=None), SimpleNamespace()

    async def wrapper_stack(*, base_url, decrypt_host, decrypt_port):
        return SimpleNamespace(client=None), SimpleNamespace(client=None), SimpleNamespace()

    async def fetch_through_the_downloader(*, interface, song_downloader, song_id):
        base = song_downloader.base
        await base._download_nm3u8dlre(str(standin.script), str(Path(base.temp_path) / "song.m4a"))
        raise AssertionError("the stand-in never finishes on its own")

    monkeypatch.setattr(engine, "_create_cookies_stack", cookies_stack)
    monkeypatch.setattr(engine, "_create_wrapper_stack", wrapper_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fetch_through_the_downloader)

    abort = Event()
    session = engine.AppleFetchSession(
        cookies_path=str(cookies),
        wrapper_url="http://127.0.0.1:1",
        child_guard=child_guard.launcher(None) if guarded else (),
    )
    raised: list[BaseException] = []

    def fetch() -> None:
        try:
            _fetch(tier, session, abort)
        except BaseException as exc:
            raised.append(exc)

    worker = threading.Thread(target=fetch)
    worker.start()
    try:
        assert _wait(standin.ready.exists), "the stand-in downloader never started"
        abort.set()
        worker.join(child_guard.GUARD_STOP_SEC + 5)
        assert not worker.is_alive(), "the fetch did not stop with its job"
    finally:
        abort.set()
        worker.join(30)
        session.close()

    assert len(raised) == 1 and isinstance(raised[0], engine._AppleAborted)
    assert _wait(lambda: not standin.alive()), "the downloader outlived its job"
    run = workdirs.run_folder()
    assert run is not None and [path.name for path in run.iterdir()] == [workdirs.LEASE_NAME]


_PARENT = """\
import asyncio, sys
from waves.providers.apple import child_guard
asyncio.run(child_guard.run_guarded([sys.executable, sys.argv[1]], guard=child_guard.launcher(None)))
"""


@pytest.mark.integration
def test_killing_waves_ends_its_guarded_downloader(tmp_path):
    """The issue's reproduction: Waves dies mid-download, the downloader with it."""
    standin = _standin(tmp_path)
    waves = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the parent script above)
        [sys.executable, "-c", _PARENT, str(standin.script)]
    )
    try:
        assert _wait(standin.ready.exists), "the stand-in downloader never started"
        assert standin.alive()
    finally:
        waves.kill()  # SIGKILL off Windows: nothing in Waves runs after this
        waves.wait(10)
    assert _wait(lambda: not standin.alive()), "the downloader outlived Waves"


def test_the_guard_ends_its_tool_when_the_parent_pipe_closes(tmp_path):
    standin = _standin(tmp_path)
    parent_end, waves_end = os.pipe()
    codes: list[int] = []
    guard = threading.Thread(
        target=lambda: codes.append(child_guard.guard([sys.executable, str(standin.script)], parent_end))
    )
    guard.start()
    try:
        assert _wait(standin.ready.exists), "the stand-in downloader never started"
    finally:
        os.close(waves_end)
        guard.join(10)
        os.close(parent_end)
    assert not guard.is_alive() and codes and codes[0] != 0
    assert _wait(lambda: not standin.alive())


def test_the_guard_passes_its_tool_s_exit_code_through():
    parent_end, waves_end = os.pipe()
    try:
        assert child_guard.guard([sys.executable, "-c", "raise SystemExit(7)"], parent_end) == 7
    finally:
        os.close(waves_end)
        os.close(parent_end)


def test_the_guard_says_why_a_tool_cannot_start(tmp_path, capsys):
    parent_end, waves_end = os.pipe()
    try:
        assert child_guard.guard([str(tmp_path / "missing-tool")], parent_end) == 127
    finally:
        os.close(waves_end)
        os.close(parent_end)
    assert "could not start" in capsys.readouterr().err
    assert child_guard.main(["--apple-child-guard"]) == 2


@pytest.mark.parametrize("guarded", [True, False], ids=["guarded", "unguarded"])
def test_a_failing_tool_raises_with_its_exit_code_and_output(guarded):
    failing = [sys.executable, "-c", "import sys; sys.stderr.write('segment 3 failed'); sys.exit(3)"]
    with pytest.raises(child_guard.ToolFailed) as excinfo:
        asyncio.run(child_guard.run_guarded(failing, guard=child_guard.launcher(None) if guarded else (), silent=True))
    assert str(excinfo.value).startswith("Exited with code 3: ")
    assert "segment 3 failed" in str(excinfo.value)


@pytest.mark.integration
def test_the_packaged_entry_point_runs_the_guard_role():
    """``waves.py`` is the frozen binary's entry: the flag must reach the guard."""
    guard = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the entry file, a fixed tool)
        [
            sys.executable,
            str(REPO_ROOT / "waves.py"),
            child_guard.GUARD_FLAG,
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(7)",
        ],
        stdin=subprocess.PIPE,
    )
    try:
        assert guard.wait(60) == 7
    finally:
        guard.stdin.close()


def test_the_provider_hands_its_fetch_the_job_s_abort_and_guard(tmp_path, monkeypatch):
    """A job's fetches run under its abort, so STOP reaches a song in flight."""
    provider = AppleProvider(catalog=None)
    provider.cookies_path = str(tmp_path / "cookies.txt")
    provider.child_guard = ("/Applications/Waves.app/Contents/MacOS/Waves", child_guard.GUARD_FLAG)
    sessions: list[dict] = []
    aborts: list[Event | None] = []

    class _Session:
        def __init__(self, **kwargs):
            sessions.append(kwargs)

        def download_song(self, *, song_id, atmos, abort=None):
            aborts.append(abort)
            return SimpleNamespace(
                staged_path=tmp_path / "staged.m4a",
                workdir=tmp_path,
                is_atmos=False,
                codec="mp4a.40.2",
                probe={"codec": "aac", "sample_rate": "44100", "bit_depth": None},
                verified=True,
            )

        def close(self):
            pass

    monkeypatch.setattr(engine, "AppleFetchSession", _Session)
    abort = Event()
    song = {"id": "song-1", "type": "songs", "attributes": {"name": "Xtal", "audioTraits": ["lossless"]}}

    with provider.engine_job_context(provider.engine_policy(), abort), provider.fetch_job_session():
        provider.resolve_stream(song, QualityTier.HIGH, AudioType.STEREO)

    assert [kwargs["child_guard"] for kwargs in sessions] == [provider.child_guard]
    assert aborts == [abort]


@pytest.mark.parametrize("frozen", [False, True], ids=["source", "packaged"])
def test_the_bridge_hands_the_provider_its_guard_launcher(monkeypatch, frozen):
    from waves.desktop import runtime_paths
    from waves.desktop.backend import WavesBridge

    app_binary = Path("/Applications/Waves.app/Contents/MacOS/Waves")
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: frozen)
    monkeypatch.setattr(runtime_paths, "executable_path", lambda: app_binary)
    provider = AppleProvider()
    bridge = BridgeStub(
        providers={"apple": provider},
        settings=SimpleNamespace(data=SimpleNamespace()),
        _settings_save_lock=Lock(),
    )

    WavesBridge._configure_apple_provider(bridge)

    if frozen:
        assert provider.child_guard == (str(app_binary), child_guard.GUARD_FLAG)
    else:
        assert provider.child_guard == (sys.executable, "-I", os.path.abspath(child_guard.__file__))

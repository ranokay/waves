"""The Apple engine's download tool stops with its job, and with Waves.

N_m3u8DL-RE runs as its own process, and nothing in it watches the fetch or
the app. These tests run a stand-in tool through the real launch path: a
script that takes a file lock and sleeps. The OS frees the lock when the
process dies, however it dies, so a lock that frees is a tool that is gone.
"""

from __future__ import annotations

import asyncio
import contextlib
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

from waves import file_locks
from waves.constants import QualityTier
from waves.providers.apple import AppleProvider, child_guard, engine, runner, workdirs

REPO_ROOT = Path(__file__).resolve().parents[3]

_STANDIN = """\
import os, time
from waves import file_locks
assert file_locks.try_lock({lock!r}) is not None
with open({ready!r}, "w") as ready:
    ready.write(str(os.getppid()))
time.sleep(120)
"""


@dataclass
class _Standin:
    script: Path
    lock: Path
    ready: Path

    def alive(self) -> bool:
        """Whether the stand-in still holds its lock."""
        fd = file_locks.try_lock(self.lock)
        if fd is None:
            return True
        file_locks.release(fd)
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


def _no_workdir_left() -> bool:
    run = workdirs.run_folder()
    return run is not None and not [path for path in run.iterdir() if path.is_dir()]


def _engine_fetching(monkeypatch, fetch) -> None:
    """Fake the Apple stacks and binaries; every song fetch runs ``fetch``.

    The interpreter stands in for N_m3u8DL-RE and ffmpeg.
    """
    monkeypatch.setattr(engine, "_require_binary", lambda name, override="": sys.executable)
    monkeypatch.setattr(engine, "_require_yt_dlp", lambda: None)

    async def cookies_stack(cookies_path):
        return SimpleNamespace(client=None), SimpleNamespace()

    async def wrapper_stack(*, base_url, decrypt_host, decrypt_port):
        return SimpleNamespace(client=None), SimpleNamespace(client=None), SimpleNamespace()

    monkeypatch.setattr(engine, "_create_cookies_stack", cookies_stack)
    monkeypatch.setattr(engine, "_create_wrapper_stack", wrapper_stack)
    monkeypatch.setattr(engine, "_fetch_song_staged", fetch)


def _engine_through_the_standin(monkeypatch, standin: _Standin) -> None:
    """Fetch by running the stand-in as N_m3u8DL-RE: gamdl's argv puts the
    stream URL first, so the "URL" is the stand-in script."""

    async def fetch_through_the_tool(*, interface, song_downloader, song_id):
        base = song_downloader.base
        await base._download_nm3u8dlre(str(standin.script), str(Path(base.temp_path) / "song.m4a"))
        raise AssertionError("the stand-in never finishes on its own")

    _engine_fetching(monkeypatch, fetch_through_the_tool)


def _stop_once_running(standin: _Standin, abort: Event, work) -> list[BaseException]:
    """Run ``work`` on a worker, set ``abort`` once the stand-in runs; what it raised."""
    raised: list[BaseException] = []

    def run() -> None:
        try:
            work()
        except BaseException as exc:
            raised.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert _wait(standin.ready.exists), "the stand-in tool never started"
        abort.set()
        worker.join(child_guard.GUARD_STOP_SEC + 5)
        assert not worker.is_alive(), "the work did not stop with its job"
    finally:
        abort.set()
        worker.join(30)
    return raised


@pytest.mark.integration
@pytest.mark.parametrize("guarded", [True, False], ids=["guarded", "unguarded"])
@pytest.mark.parametrize("tier", ["cookies", "wrapper"])
def test_stopping_a_job_stops_its_download_tool_and_removes_its_workdir(tmp_path, monkeypatch, tier, guarded):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    standin = _standin(tmp_path)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    _engine_through_the_standin(monkeypatch, standin)
    abort = Event()
    session = engine.AppleFetchSession(
        cookies_path=str(cookies),
        wrapper_url="http://127.0.0.1:1",
        guard_launcher=child_guard.launcher(None) if guarded else (),
    )

    def fetch() -> None:
        if tier == "cookies":
            session.download_song(song_id="song-1", atmos=False, abort=abort)
        else:
            session.download_alac(song_id="song-1", abort=abort)

    try:
        raised = _stop_once_running(standin, abort, fetch)
    finally:
        session.close()

    assert len(raised) == 1 and isinstance(raised[0], engine._AppleAborted)
    assert _wait(lambda: not standin.alive()), "the tool outlived its job"
    assert _no_workdir_left()


_SONG = {
    "id": "song-1",
    "type": "songs",
    "attributes": {
        "name": "Xtal",
        "artistName": "Aphex Twin",
        "albumName": "Selected Ambient Works 85-92",
        "url": "https://music.apple.com/us/album/x/album-1?i=song-1",
        "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
        "releaseDate": "1992-02-12",
        "durationInMillis": 293000,
        "trackNumber": 1,
        "discNumber": 1,
        "audioTraits": ["lossless"],
        "isrc": "GBAAA9200001",
    },
    "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
}


class _SongProvider(AppleProvider):
    """The real provider, serving one song without a catalog."""

    def row_for(self, kind, item):
        return {
            "id": "apple:song-1",
            "title": "Xtal",
            "artist": "Aphex Twin",
            "artist_id": "apple:artist-1",
            "artists": [],
            "album": "Selected Ambient Works 85-92",
            "album_id": "apple:album-1",
            "num": 1,
            "vol": 1,
            "art": "",
            "year": "1992",
            "date": "1992-02-12",
            "duration": "4:53",
            "duration_sec": 293,
            "quality": "HIGH",
            "popularity": -1,
            "explicit": False,
            "added": "",
        }

    def get_object(self, kind, raw_id):
        return _SONG


@pytest.mark.integration
def test_stop_reaches_the_song_a_job_is_fetching(tmp_path, monkeypatch):
    """STOP through the job body the queue runs: the row settles cancelled."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    standin = _standin(tmp_path)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    _engine_through_the_standin(monkeypatch, standin)
    provider = _SongProvider(catalog=None)
    provider.cookies_path = str(cookies)
    provider.guard_launcher = child_guard.launcher(None)
    data = SimpleNamespace(
        download_base_path=str(tmp_path / "lib"),
        skip_existing=True,
        extract_flac=False,
        extract_flac_all=False,
        playlist_create=False,
        apple_quality_audio=QualityTier.HIGH.value,
        default_audio_type="stereo",
        mark_explicit=False,
        metadata_target_upc="UPC",
        path_binary_ffmpeg="",
        album_track_num_pad_min=1,
        filename_delimiter_artist=", ",
        filename_delimiter_album_artist=", ",
        filename_illegal_replacement="",
        filename_illegal_map=None,
    )
    statuses: list[str] = []
    hooks = runner.AppleJobHooks(
        provider=lambda: provider,
        settings=lambda: SimpleNamespace(data=data),
        job_quality=lambda qid: QualityTier.HIGH,
        queue_status=lambda qid, status, *reason: statuses.append(status),
    )
    spec = SimpleNamespace(
        kind="track", collection=False, media_id="apple:song-1", is_retry=False, file_template="{track_title}"
    )
    signals = SimpleNamespace(
        track_event=SimpleNamespace(emit=lambda *a: None),
        item=SimpleNamespace(emit=lambda *a: None),
        list_item=SimpleNamespace(emit=lambda *a: None),
    )
    abort = Event()

    raised = _stop_once_running(
        standin,
        abort,
        lambda: runner.run_job_body(hooks, 1, spec, _SONG, signals=signals, job_abort=abort, row_ask=None, name="Xtal"),
    )

    assert raised == []
    assert statuses[-1] == "cancelled"
    assert _wait(lambda: not standin.alive()), "the tool outlived its job"
    assert _no_workdir_left()
    assert not list((tmp_path / "lib").rglob("*.m4a"))


_PARENT = """\
import asyncio, sys
from waves.providers.apple import child_guard
asyncio.run(child_guard.run_guarded([sys.executable, sys.argv[1]], guard_launcher=child_guard.launcher(None)))
"""


@pytest.mark.integration
def test_killing_waves_kills_its_guarded_download_tool(tmp_path):
    """Waves dies mid-download, and the tool goes with it."""
    standin = _standin(tmp_path)
    waves = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the parent script above)
        [sys.executable, "-c", _PARENT, str(standin.script)]
    )
    try:
        assert _wait(standin.ready.exists), "the stand-in tool never started"
        assert standin.alive()
    finally:
        waves.kill()  # SIGKILL off Windows: nothing in Waves runs after this
        waves.wait(10)
    assert _wait(lambda: not standin.alive()), "the tool outlived Waves"


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="Windows cannot reach a tool whose guard has died")
@pytest.mark.parametrize("guard_state", ["frozen", "dead"])
def test_a_stop_kills_the_tool_whatever_became_of_its_guard(tmp_path, monkeypatch, guard_state):
    """A guard that cannot act on the stop, or has died, still leaves no tool."""
    import signal

    monkeypatch.setattr(child_guard, "GUARD_STOP_SEC", 0.5)
    standin = _standin(tmp_path)
    guards: list[int] = []

    async def fetch() -> None:
        task = asyncio.ensure_future(
            child_guard.run_guarded(
                [sys.executable, str(standin.script)], guard_launcher=child_guard.launcher(None), silent=True
            )
        )
        while not standin.ready.exists() or not standin.ready.read_text():
            await asyncio.sleep(0.02)
        guards.append(int(standin.ready.read_text()))  # the tool's parent
        os.kill(guards[0], signal.SIGSTOP if guard_state == "frozen" else signal.SIGKILL)
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(asyncio.wait_for(fetch(), 20))
        assert _wait(lambda: not standin.alive()), "the tool outlived the stop"
    finally:
        # A regression must not leave a stopped guard and its tool behind.
        for guard in guards:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(guard, signal.SIGKILL)


def _cookies_session(tmp_path, monkeypatch, fetch) -> engine.AppleFetchSession:
    """A cookies-tier session whose song fetch is ``fetch``; no process runs."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    _engine_fetching(monkeypatch, fetch)
    return engine.AppleFetchSession(cookies_path=str(cookies))


def test_stop_lands_while_a_fetch_waits_on_the_network(tmp_path, monkeypatch):
    """A request that would run for minutes does not hold the stop."""
    reached = Event()

    async def stalled(*, interface, song_downloader, song_id):
        reached.set()
        await asyncio.sleep(600)

    session = _cookies_session(tmp_path, monkeypatch, stalled)
    abort = Event()
    threading.Thread(target=lambda: reached.wait(10) and abort.set()).start()
    started = time.monotonic()
    try:
        with pytest.raises(engine._AppleAborted):
            session.download_song(song_id="song-1", atmos=False, abort=abort)
    finally:
        session.close()
    assert time.monotonic() - started < 5
    assert _no_workdir_left()


def test_stop_waits_for_a_decrypt_still_writing_before_removing_its_workdir(tmp_path, monkeypatch):
    """The decrypt writes on a thread that cancelling the fetch does not stop."""
    decrypting, decrypted = Event(), Event()

    def decrypt(workdir: Path) -> None:
        decrypting.set()
        time.sleep(0.5)
        (workdir / "song-1_decrypted.m4a").write_bytes(b"\0")
        decrypted.set()

    async def fetch(*, interface, song_downloader, song_id):
        await asyncio.to_thread(decrypt, Path(song_downloader.base.temp_path))
        raise AssertionError("the decrypt finished and the stop never landed")

    session = _cookies_session(tmp_path, monkeypatch, fetch)
    abort = Event()
    threading.Thread(target=lambda: decrypting.wait(10) and abort.set()).start()
    try:
        with pytest.raises(engine._AppleAborted):
            session.download_song(song_id="song-1", atmos=False, abort=abort)
        assert decrypted.is_set(), "the workdir went while the decrypt was still writing"
        assert _no_workdir_left()
        # The session's next song decrypts as before.
        abort.clear()
        decrypted.clear()
        with pytest.raises(engine.AppleDownloadError, match="the stop never landed"):
            session.download_song(song_id="song-2", atmos=False, abort=abort)
        assert decrypted.is_set()
    finally:
        session.close()


def test_a_stuck_thread_step_holds_a_stop_only_for_its_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "THREAD_STEP_WAIT_SEC", 0.3)
    stuck, release = Event(), Event()
    stuck_at: list[float] = []

    def lookup() -> None:
        stuck_at.append(time.monotonic())
        stuck.set()
        release.wait(10)

    async def fetch(*, interface, song_downloader, song_id):
        await asyncio.to_thread(lookup)

    session = _cookies_session(tmp_path, monkeypatch, fetch)
    abort = Event()
    threading.Thread(target=lambda: stuck.wait(10) and abort.set()).start()
    try:
        with pytest.raises(engine._AppleAborted):
            session.download_song(song_id="song-1", atmos=False, abort=abort)
        stopped = time.monotonic()
        assert stopped - stuck_at[0] >= engine.THREAD_STEP_WAIT_SEC, "the stop did not wait for the step"
        assert stopped - stuck_at[0] < 3
        assert _no_workdir_left()
    finally:
        release.set()
        session.close()


def _run_guard(*command: str) -> subprocess.CompletedProcess:
    """The guard role as Waves starts it, its stdin pipe held open until it exits."""
    guard = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the guard module, a fixed tool)
        [*child_guard.launcher(None), "--", *command],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stderr = guard.stderr.read()
        returncode = guard.wait(30)
    finally:
        guard.stdin.close()
        guard.stderr.close()
    return subprocess.CompletedProcess(guard.args, returncode, "", stderr)


@pytest.mark.integration
def test_the_guard_passes_its_tool_s_exit_code_through():
    assert _run_guard(sys.executable, "-c", "raise SystemExit(7)").returncode == 7


@pytest.mark.integration
def test_the_guard_says_why_a_tool_cannot_start(tmp_path):
    result = _run_guard(str(tmp_path / "missing-tool"))
    assert result.returncode == 127
    assert "could not start" in result.stderr


def test_the_guard_refuses_to_run_without_a_command(capsys):
    assert child_guard.main([child_guard.GUARD_FLAG]) == 2
    assert "no command" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.parametrize("guarded", [True, False], ids=["guarded", "unguarded"])
def test_a_failing_tool_raises_with_its_exit_code_and_output(guarded):
    failing = [sys.executable, "-c", "import sys; sys.stderr.write('segment 3 failed'); sys.exit(3)"]
    with pytest.raises(child_guard.ToolFailed) as excinfo:
        asyncio.run(
            child_guard.run_guarded(failing, guard_launcher=child_guard.launcher(None) if guarded else (), silent=True)
        )
    assert str(excinfo.value).startswith("Exited with code 3: ")
    assert "segment 3 failed" in str(excinfo.value)


@pytest.mark.integration
def test_the_packaged_entry_point_runs_the_guard_role():
    """``waves.py`` is the packaged binary's entry: the flag must reach the guard."""
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


@pytest.mark.parametrize("frozen", [False, True], ids=["source", "packaged"])
def test_the_packaged_app_guards_the_tool_with_its_own_binary(monkeypatch, frozen):
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
        assert provider.guard_launcher == (str(app_binary), child_guard.GUARD_FLAG)
    else:
        assert provider.guard_launcher == (sys.executable, "-I", os.path.abspath(child_guard.__file__))

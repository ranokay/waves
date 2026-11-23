"""Keep the Apple engine's download tool from outliving its job or Waves.

gamdl starts N_m3u8DL-RE with ``asyncio.create_subprocess_exec`` and nothing
else: cancelling the awaiting task leaves the tool running, and so does Waves
dying, since nothing ties the tool to the app. ``run_guarded`` starts the tool
instead and kills it when the awaiting task is cancelled.

Killing the tool when Waves dies needs a process that outlives Waves, so the
tool runs under a guard: this module in its guard role (``main``), started
with its stdin on a pipe Waves holds and never writes. The pipe closes when
Waves closes it or exits, however it exits (a crash and SIGKILL included), and
the guard then kills the tool. Stopping a job closes the pipe the same way, so
a job stop and Waves' exit take one path.

The guard imports only the standard library: a source run starts this file
on the venv's interpreter in isolated mode, and the packaged app re-executes
its own binary with ``GUARD_FLAG`` (``waves.py`` dispatches it before any Qt
import). A guard whose stdin is not that pipe kills its tool at once.

Platforms: on macOS and Linux the guard leads a process group that the tool
and anything the tool starts join, and a stop kills whatever of that group is
left, even after the guard itself has died. On Windows the guard kills only
the tool process, and when a stop has to kill the guard, Waves kills the
guard's process tree; a tool whose guard died before the stop keeps running.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import BinaryIO, TypedDict

GUARD_FLAG = "--apple-child-guard"

# How long a stopped tool's guard has to kill it and leave before Waves kills
# the guard's process group itself, and the drain limit after tool exit.
GUARD_STOP_SEC = 5.0


class _SpawnOptions(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class _ToolOutput(TypedDict, total=False):
    stdout: int
    stderr: int


@dataclass
class _TerminalRelay:
    source: BinaryIO
    reader: threading.Thread
    writing: threading.Event


# Windows: no console window flashes up for a console process started from
# the windowless app. Every Apple provider spawn passes these; they live in
# this module because the guard role may import only the standard library.
NO_WINDOW: _SpawnOptions = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
# How Waves starts the guard, or the tool when it has no guard: off Windows,
# in a session of its own, which keeps terminal signals off it and makes it
# the leader of the group a stop kills.
_SPAWN: _SpawnOptions = NO_WINDOW if os.name == "nt" else {"start_new_session": True}


class ToolFailed(RuntimeError):
    """The tool exited nonzero; the words match gamdl's own failure message."""


def launcher(app_binary: str | None) -> tuple[str, ...]:
    """The guard's launch prefix, before ``--`` and the tool's argv.

    ``app_binary`` is the packaged app's own binary, or None for a source
    run, which starts this file on the current interpreter in isolated mode.
    """
    if app_binary:
        return (app_binary, GUARD_FLAG)
    return (sys.executable, "-I", os.path.abspath(__file__))


async def run_guarded(
    args: Sequence[str | os.PathLike], *, guard_launcher: Sequence[str] = (), silent: bool = False
) -> None:
    """Run one tool to completion, killing it if the awaiting task is cancelled.

    ``guard_launcher`` is the ``launcher`` prefix; without one the tool still
    dies with a cancelled fetch, but not with Waves. ``silent`` captures the
    tool's output for the failure message, as gamdl's runner does. A nonzero
    exit raises ToolFailed.
    """
    guarded = bool(guard_launcher)
    command = [*guard_launcher, "--", *args] if guarded else list(args)
    pipe = asyncio.subprocess.PIPE if silent else None
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if guarded else asyncio.subprocess.DEVNULL,
        stdout=pipe,
        stderr=pipe,
        **_SPAWN,
    )
    try:
        stdout, stderr = await _finish(process, silent=silent)
    except BaseException:
        await _stop(process, guarded=guarded)
        raise
    finally:
        if process.stdin is not None:
            process.stdin.close()
    if guarded or process.returncode != 0:
        # Tool completion, including success, may leave helpers behind. The
        # guard must exit before Waves can kill its group without losing the
        # original tool result.
        await _kill_remains(process)
    if process.returncode != 0:
        message = f"Exited with code {process.returncode}: {' '.join(str(arg) for arg in args)}"
        if stdout:
            message += f"\nstdout:\n{stdout.decode(errors='replace')}"
        if stderr:
            message += f"\nstderr:\n{stderr.decode(errors='replace')}"
        raise ToolFailed(message)


async def _finish(process: asyncio.subprocess.Process, *, silent: bool) -> tuple[bytes, bytes]:
    """The tool's captured output once it exits (empty when not ``silent``)."""
    if not silent:
        await process.wait()
        return b"", b""
    stdout, stderr, _ = await asyncio.gather(_read(process.stdout), _read(process.stderr), process.wait())
    return stdout, stderr


async def _read(stream: asyncio.StreamReader | None) -> bytes:
    return await stream.read() if stream is not None else b""


async def _stop(process: asyncio.subprocess.Process, *, guarded: bool) -> None:
    """End a tool whose fetch was cancelled, and wait for it.

    A live guard is asked through its pipe first. Then whatever is left of
    the group dies: a guard that missed GUARD_STOP_SEC, or a tool whose guard
    had already died.
    """
    if guarded and process.returncode is None and process.stdin is not None:
        process.stdin.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), GUARD_STOP_SEC)
    await _kill_remains(process)
    await process.wait()


async def _kill_remains(process: asyncio.subprocess.Process) -> None:
    """Kill what is left of a process Waves started with ``_SPAWN``: its
    process group off Windows, a live guard's process tree on Windows.

    Off Windows the group's id stays reserved while any member lives, and an
    empty group answers ESRCH.
    """
    if os.name != "nt":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        return
    if process.returncode is not None:
        return
    taskkill = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe")
    with contextlib.suppress(OSError):
        killer = await asyncio.create_subprocess_exec(
            taskkill,
            "/F",
            "/T",
            "/PID",
            str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **_SPAWN,
        )
        await killer.wait()
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        process.kill()


def main(argv: Sequence[str]) -> int:
    """The guard role: run the command after ``--`` while stdin stays open.

    Returns the command's exit code, 127 when it cannot start (the reason
    goes to stderr), or 2 without a command. A failed output relay keeps a
    tool's nonzero exit code, or turns its success into exit 1.
    """
    args = list(argv)
    command = args[args.index("--") + 1 :] if "--" in args else []
    if not command:
        print("Apple child guard: no command after --", file=sys.stderr)
        return 2
    if os.name != "nt":
        # Lead a process group of its own, which the tool joins (Waves starts
        # the guard as a session leader, which already leads one).
        with contextlib.suppress(OSError):
            os.setpgid(0, 0)
    result = None
    try:
        if sys.platform == "darwin":
            _watch_guard_exit()
        with _tool_output() as output:
            # The tool joins the guard's own group off Windows. Its stdin is
            # separate from the pipe that tells the guard Waves has left.
            tool = subprocess.Popen(command, stdin=subprocess.DEVNULL, **output, **NO_WINDOW)  # noqa: S603 (Waves' own tool argv)
            threading.Thread(target=_kill_when_waves_leaves, args=(sys.stdin.fileno(), tool), daemon=True).start()
            result = tool.wait()
            return result
    except OSError as exc:
        action = "start" if result is None else "relay output from"
        # A closed stderr must not replace the tool's exit code, including
        # through an interpreter-shutdown flush of a buffered diagnostic.
        reporter = threading.Thread(
            target=_write_guard_error,
            args=(f"Apple child guard could not {action} {command[0]}: {exc}\n".encode(errors="replace"),),
            daemon=True,
        )
        reporter.start()
        reporter.join(0.2)
        return 127 if result is None else result or 1


def _write_guard_error(message: bytes) -> None:
    # A full destination pipe must not hold up the failure result either.
    with contextlib.suppress(OSError):
        os.write(sys.stderr.fileno(), message)


def _watch_guard_exit() -> None:
    """Keep group cleanup owned even if Waves cannot run after guard exit."""
    guard = os.getpid()
    if os.getpgrp() != guard:
        raise OSError(errno.EPERM, "Apple child guard does not own its process group")
    # Fork before the guard starts any threads. This child does no buffered
    # I/O and never runs interpreter shutdown. Keeping the inherited output
    # pipes open also keeps captured completion behind group cleanup.
    if os.fork():
        return
    while os.getppid() == guard:
        time.sleep(0.02)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(guard, signal.SIGKILL)
    os._exit(0)


@contextlib.contextmanager
def _tool_output() -> Generator[_ToolOutput]:
    if sys.platform != "darwin" or (sys.stdout.isatty() and sys.stderr.isatty()):
        yield {}
        return

    import termios
    import tty

    # The pinned N_m3u8DL-RE forces Spectre.Console's live renderer on pipes,
    # whose missing terminal height can abort a download. Give it sized PTYs
    # while relaying each stream to its original destination. Raw mode keeps
    # diagnostics byte-for-byte; the guard's control pipe stays untouched.
    with contextlib.ExitStack() as resources:
        slaves: list[BinaryIO] = []
        relays: list[_TerminalRelay] = []
        failures: list[OSError] = []
        stop_reading = threading.Event()
        try:
            for destination in (sys.stdout, sys.stderr):
                master, slave = os.openpty()
                source = resources.enter_context(os.fdopen(master, "rb", buffering=0))
                sink = resources.enter_context(os.fdopen(slave, "wb", buffering=0))
                # Closing a PTY master can wait for its blocking read. The
                # drain deadline must also bound descriptor cleanup.
                os.set_blocking(master, False)
                slaves.append(sink)
                tty.setraw(slave)
                termios.tcsetwinsize(slave, (40, 120))
                writing = threading.Event()
                reader = threading.Thread(
                    target=_relay_terminal,
                    args=(source, destination.fileno(), failures, stop_reading, writing),
                    daemon=True,
                )
                reader.start()
                relays.append(_TerminalRelay(source, reader, writing))
            yield {"stdout": slaves[0].fileno(), "stderr": slaves[1].fileno()}
        finally:
            # Helpers can retain the slave descriptors after tool exit. Give
            # both readers one bounded drain period, then let Waves receive
            # the tool result and kill what remains of the group.
            deadline = time.monotonic() + GUARD_STOP_SEC
            # macOS can discard unread bytes when the last slave closes.
            # Keep our handles until queued tool output drains, or fails.
            while any(relay.writing.is_set() or _terminal_is_readable(relay.source) for relay in relays):
                if time.monotonic() >= deadline:
                    failures.append(OSError(errno.ETIMEDOUT, "Apple child guard output drain timed out"))
                    break
                time.sleep(0.01)
            for sink in slaves:
                sink.close()
            for relay in relays:
                relay.reader.join(max(0.0, deadline - time.monotonic()))
            stop_reading.set()
            for relay in relays:
                relay.reader.join(0.2)
            # An idle helper holding its terminal open is safe to stop. Bytes
            # queued at either end of a relay must not be discarded as success.
            if any(relay.writing.is_set() or _terminal_has_output(relay.source) for relay in relays):
                failures.append(OSError(errno.ETIMEDOUT, "Apple child guard output drain timed out"))
        if failures:
            raise failures[0]


def _terminal_is_readable(source: BinaryIO) -> bool:
    # Called while our slave is open, so readability means queued bytes.
    try:
        return bool(select.select((source,), (), (), 0)[0])
    except ValueError:  # A failed relay closed its master.
        return False
    except OSError as exc:
        if exc.errno == errno.EBADF:
            return False
        raise


def _terminal_has_output(source: BinaryIO) -> bool:
    # Readers have been stopped. A nonblocking probe distinguishes queued
    # bytes from readable EOF; a byte consumed here makes the result fail.
    try:
        return bool(os.read(source.fileno(), 1))
    except (BlockingIOError, ValueError):  # Idle terminal, or a failed relay closed it.
        return False
    except OSError as exc:
        if exc.errno in (errno.EIO, errno.EBADF):  # Slave closed, or relay closed the master.
            return False
        raise


def _relay_terminal(
    source: BinaryIO,
    destination: int,
    failures: list[OSError],
    stop_reading: threading.Event,
    writing: threading.Event,
) -> None:
    try:
        descriptor = source.fileno()
        while not stop_reading.is_set():
            if not select.select((descriptor,), (), (), 0.1)[0]:
                continue
            if stop_reading.is_set():
                return
            writing.set()
            try:
                try:
                    data = os.read(descriptor, 65536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno == errno.EIO:  # PTY slave closed after tool exit.
                        return
                    raise
                if not data:
                    return
                while data:
                    data = data[os.write(destination, data) :]
            finally:
                writing.clear()
    except OSError as exc:
        failures.append(exc)
        # A failed destination leaves nobody draining this terminal. Close
        # its master now so a still-running tool cannot block filling it.
        with contextlib.suppress(OSError):
            source.close()


def _kill_when_waves_leaves(parent: int, tool: subprocess.Popen) -> None:
    # A raw read, not sys.stdin's buffered one: the interpreter's exit flushes
    # that reader and would wait forever on the lock this blocked thread holds.
    with contextlib.suppress(OSError):
        while os.read(parent, 65536):
            # Waves never writes: a read that ends, or fails, means it is gone
            # or has stopped the job.
            pass
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.name != "nt" and os.getpgrp() == os.getpid():
            # The guard's own group: the tool, whatever it started, and the
            # guard itself, which has nothing left to do.
            os.killpg(os.getpid(), signal.SIGKILL)
        elif tool.poll() is None:
            tool.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

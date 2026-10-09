"""Keep the Apple engine's download tool from outliving its job or Waves.

gamdl starts N_m3u8DL-RE with ``asyncio.create_subprocess_exec`` and nothing
else: cancelling the awaiting task leaves the tool running, and so does Waves
dying, since nothing ties the tool to the app. ``run_guarded`` starts the tool
instead and stops it when its job's abort is set or the awaiting task is
cancelled.

Stopping the tool when Waves dies needs a process that outlives Waves, so the
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
and anything the tool starts join, and every kill reaches the whole group. On
Windows the guard kills the tool process alone, so a process the tool started
itself survives it, and a guard that does not leave within ``GUARD_STOP_SEC``
of a stop is killed without its tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from threading import Event

GUARD_FLAG = "--apple-child-guard"

# How long a stopped tool's guard has to kill it and leave before Waves kills
# the guard's process group itself.
GUARD_STOP_SEC = 5.0

# How often a running tool reads its job's abort.
ABORT_POLL_SEC = 0.2

# How Waves starts the guard, or the tool when it has no guard. POSIX: a
# session of its own keeps terminal signals off it and makes it the leader of
# the group every kill reaches. Windows: no console window flashes up for a
# console process started from the windowless app.
_SPAWN: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}


class ToolFailed(RuntimeError):
    """The tool exited nonzero; the words match gamdl's own failure message."""


class ToolStopped(RuntimeError):
    """The job's abort stopped the tool before it finished."""

    def __init__(self) -> None:
        super().__init__("The download tool stopped with its job")


def launcher(app_binary: str | None) -> tuple[str, ...]:
    """The guard's launch prefix, before ``--`` and the tool's argv.

    ``app_binary`` is the packaged app's own binary, or None for a source
    run, which starts this file on the current interpreter in isolated mode.
    """
    if app_binary:
        return (app_binary, GUARD_FLAG)
    return (sys.executable, "-I", os.path.abspath(__file__))


async def run_guarded(
    args: Sequence[str | os.PathLike],
    *,
    guard_launcher: Sequence[str] = (),
    abort: Event | None = None,
    silent: bool = False,
) -> None:
    """Run one tool to completion unless its job stops first.

    ``guard_launcher`` is the ``launcher`` prefix; without one the tool still
    stops with its job, but not with Waves. ``abort`` set, read every
    ABORT_POLL_SEC, stops the tool and raises ToolStopped; a cancelled
    awaiting task stops it too. ``silent`` captures the tool's output for the
    failure message, as gamdl's runner does. A nonzero exit raises ToolFailed.
    """
    if abort is not None and abort.is_set():
        raise ToolStopped()
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
    finished = asyncio.ensure_future(_finish(process, silent=silent))
    try:
        stdout, stderr = await _unless_stopped(finished, abort)
    except BaseException:
        finished.cancel()
        await _stop(process, guarded=guarded)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await finished
        raise
    finally:
        if process.stdin is not None:
            process.stdin.close()
    if process.returncode != 0:
        message = f"Exited with code {process.returncode}: {' '.join(str(arg) for arg in args)}"
        if stdout:
            message += f"\nstdout:\n{stdout.decode(errors='replace')}"
        if stderr:
            message += f"\nstderr:\n{stderr.decode(errors='replace')}"
        raise ToolFailed(message)


async def _unless_stopped(finished: asyncio.Future, abort: Event | None) -> tuple[bytes, bytes]:
    """``finished``'s output, or ToolStopped once ``abort`` is set first."""
    while not finished.done():
        if abort is not None and abort.is_set():
            raise ToolStopped()
        await asyncio.wait({finished}, timeout=ABORT_POLL_SEC)
    return finished.result()


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
    """End a tool whose job stopped, and wait for it.

    A guard is asked through its pipe; only one that does not leave in time
    is killed, together with its process group off Windows.
    """
    if process.returncode is not None:
        return
    if guarded and process.stdin is not None:
        process.stdin.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), GUARD_STOP_SEC)
            return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


def main(argv: Sequence[str]) -> int:
    """The guard role: run the command after ``--`` while stdin stays open.

    Returns the command's exit code, 127 when it cannot start (the reason
    goes to stderr), or 2 without a command.
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
    try:
        tool = subprocess.Popen(  # noqa: S603 (Waves' own tool argv)
            command,
            stdin=subprocess.DEVNULL,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
    except OSError as exc:
        print(f"Apple child guard could not start {command[0]}: {exc}", file=sys.stderr)
        return 127
    threading.Thread(target=_kill_when_waves_leaves, args=(sys.stdin.fileno(), tool), daemon=True).start()
    return tool.wait()


def _kill_when_waves_leaves(parent: int, tool: subprocess.Popen) -> None:
    # Waves never writes: a read that ends, or fails, means it is gone or has
    # stopped the job. A raw read, not sys.stdin's buffered one: the
    # interpreter's exit flushes that reader and would wait forever on the
    # lock this blocked thread holds.
    with contextlib.suppress(OSError):
        while os.read(parent, 65536):
            pass
    if tool.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.name != "nt" and os.getpgrp() == os.getpid():
            # The guard's own group: the tool, whatever it started, and the
            # guard itself, which has nothing left to do.
            os.killpg(os.getpid(), signal.SIGKILL)
        else:
            tool.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

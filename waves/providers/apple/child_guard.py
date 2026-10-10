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
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from typing import TypedDict

GUARD_FLAG = "--apple-child-guard"

# How long a stopped tool's guard has to kill it and leave before Waves kills
# the guard's process group itself.
GUARD_STOP_SEC = 5.0


class _SpawnOptions(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


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
    if process.returncode != 0:
        # A guard that died leaves its tool behind; a failed tool may leave
        # what it started.
        await _kill_remains(process)
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
        # The tool joins the guard's own group off Windows.
        tool = subprocess.Popen(command, stdin=subprocess.DEVNULL, **NO_WINDOW)  # noqa: S603 (Waves' own tool argv)
    except OSError as exc:
        print(f"Apple child guard could not start {command[0]}: {exc}", file=sys.stderr)
        return 127
    threading.Thread(target=_kill_when_waves_leaves, args=(sys.stdin.fileno(), tool), daemon=True).start()
    return tool.wait()


def _kill_when_waves_leaves(parent: int, tool: subprocess.Popen) -> None:
    # A raw read, not sys.stdin's buffered one: the interpreter's exit flushes
    # that reader and would wait forever on the lock this blocked thread holds.
    with contextlib.suppress(OSError):
        while os.read(parent, 65536):
            # Waves never writes: a read that ends, or fails, means it is gone
            # or has stopped the job.
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

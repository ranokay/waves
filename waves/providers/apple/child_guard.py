"""Keep the Apple engine's downloader child from outliving its job or Waves.

gamdl starts N_m3u8DL-RE with ``asyncio.create_subprocess_exec`` and nothing
else: cancelling the awaiting task leaves the child running, and so does
Waves dying, since nothing ties the child to the app. ``run_guarded`` starts
the tool instead, and ends it when the fetch is cancelled.

Ending it when Waves dies needs a process that survives Waves, so the tool
runs under a guard: this module in its guard role (``main``), started with
its stdin on a pipe Waves holds and never writes. The pipe closes when Waves
closes it or exits, however it exits (a crash and SIGKILL included), and the
guard then kills the tool and leaves. Cancelling a fetch closes the pipe the
same way, so job stop and Waves' exit take one path.

The guard imports only the standard library: a source run starts this file
on the venv's interpreter in isolated mode, and the packaged app re-executes
its own binary with ``GUARD_FLAG`` (``waves.py`` dispatches it before any Qt
import). A guard whose stdin is not that pipe ends its tool at once.

Platforms: on macOS and Linux the tool leads its own process group, and the
guard kills the whole group, so anything the tool started dies with it. On
Windows the guard kills the tool process alone, so a process the tool
started itself would survive it.
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

GUARD_FLAG = "--apple-child-guard"

# How long a cancelled fetch waits for the guard to end its tool and exit
# before killing the guard itself.
GUARD_STOP_SEC = 5.0

# POSIX: a session of its own keeps terminal signals off the child and makes
# it the leader of the group the kill reaches. Windows: no console window
# flashes up for a console tool started from the windowless app.
_SPAWN: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}


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


async def run_guarded(args: Sequence[str | os.PathLike], *, guard: Sequence[str] = (), silent: bool = False) -> None:
    """Run one tool to completion, ending it if the awaiting task is cancelled.

    ``guard`` is the ``launcher`` prefix; without one the tool still ends
    with a cancelled fetch, but not with Waves. ``silent`` captures the
    tool's output for the failure message, as gamdl's runner does. A nonzero
    exit raises ToolFailed.
    """
    command = [*guard, "--", *args] if guard else list(args)
    pipe = asyncio.subprocess.PIPE if silent else None
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if guard else asyncio.subprocess.DEVNULL,
        stdout=pipe,
        stderr=pipe,
        **_SPAWN,
    )
    stdout = stderr = b""
    try:
        if silent:
            stdout, stderr, _ = await asyncio.gather(_read(process.stdout), _read(process.stderr), process.wait())
        else:
            await process.wait()
    except BaseException:
        await _stop(process, guarded=bool(guard))
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


async def _read(stream: asyncio.StreamReader | None) -> bytes:
    return await stream.read() if stream is not None else b""


async def _stop(process: asyncio.subprocess.Process, *, guarded: bool) -> None:
    """End a tool whose fetch was cancelled, and wait for it.

    A guard is asked through its pipe so it can kill the tool; only a guard
    that does not leave in time is killed itself.
    """
    if process.returncode is not None:
        return
    if guarded and process.stdin is not None:
        process.stdin.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), GUARD_STOP_SEC)
            return
    _kill(process)
    await process.wait()


def _kill(process: asyncio.subprocess.Process | subprocess.Popen) -> None:
    """Kill a process started with ``_SPAWN``: its whole group off Windows."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)


def guard(command: Sequence[str], parent: int) -> int:
    """Run ``command`` until it exits or the ``parent`` descriptor reaches EOF.

    Returns the command's exit code, or 127 when it cannot start, with the
    reason on stderr.
    """
    try:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, **_SPAWN)  # noqa: S603 (Waves' own tool argv)
    except OSError as exc:
        print(f"Apple child guard could not start {command[0]}: {exc}", file=sys.stderr)
        return 127
    threading.Thread(target=_end_when_parent_leaves, args=(parent, child), daemon=True).start()
    return child.wait()


def _end_when_parent_leaves(parent: int, child: subprocess.Popen) -> None:
    # Waves never writes: a read that ends, or fails, means it is gone or has
    # asked the tool to stop. A raw read, not sys.stdin's buffered one: the
    # interpreter's exit flushes that reader and would wait forever on the
    # lock this blocked thread holds.
    with contextlib.suppress(OSError):
        while os.read(parent, 65536):
            pass
    if child.poll() is None:
        _kill(child)


def main(argv: Sequence[str]) -> int:
    """The guard role: run the command after ``--`` while stdin stays open."""
    args = list(argv)
    command = args[args.index("--") + 1 :] if "--" in args else []
    if not command:
        print("Apple child guard: no command after --", file=sys.stderr)
        return 2
    return guard(command, sys.stdin.fileno())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

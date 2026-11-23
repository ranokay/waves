"""Source and packaged entrypoint for local provider-session controls."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from waves.desktop.providers.session_ipc import request
from waves.desktop.runtime_paths import executable_path, is_frozen

_START_TIMEOUT = 20.0


def profile_path() -> Path:
    from waves.paths import path_config_base

    return Path(path_config_base())


def _send_until(profile: Path, message: dict, deadline: float) -> dict:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"version": 1, "error": "unavailable"}
        response = request(profile, message, timeout=min(remaining, 0.5))
        if response.get("error") != "unavailable":
            return response
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def activate_existing(profile: Path, *, timeout: float = _START_TIMEOUT) -> bool:
    return (
        _send_until(profile, {"version": 1, "op": "activate"}, time.monotonic() + timeout).get("result") == "activated"
    )


def _start_gui() -> None:
    command = (
        [str(executable_path())]
        if is_frozen()
        else [sys.executable, str(Path(__file__).resolve().parents[3] / "waves.py")]
    )
    subprocess.Popen(  # noqa: S603 - executable is this app or its Python interpreter
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )


def main(args: list[str]) -> int:
    """Print one fixed-schema result: 0 success, 2 invalid, 3 unavailable, 4 action required."""
    if sys.platform != "darwin":
        response = {"version": 1, "error": "unsupported_platform"}
        code = 3
    elif len(args) != 2 or args[0] not in {"status", "ensure"} or args[1] not in {"tidal", "apple"}:
        response = {"version": 1, "error": "invalid_request"}
        code = 2
    else:
        try:
            profile = profile_path()
            message = {"version": 1, "op": args[0], "provider": args[1]}
            response = request(profile, message, timeout=0.5)
            if response.get("error") == "unavailable" and args[0] == "ensure":
                _start_gui()
                response = _send_until(profile, message, time.monotonic() + _START_TIMEOUT)
            code = 3 if "error" in response else 4 if response.get("result") == "action_required" else 0
        except (OSError, RuntimeError, ValueError):
            response = {"version": 1, "error": "unavailable"}
            code = 3
    print(json.dumps(response, separators=(",", ":")))
    return code

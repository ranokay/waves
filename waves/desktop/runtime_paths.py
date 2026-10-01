"""Packaged/source runtime identity for update installation and child launches."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger("waves.runtime")


def is_frozen() -> bool:
    """True when running as a packaged/compiled build (PyInstaller or Nuitka).

    Deliberately NOT ``waves.is_dev_env()``: an editable/pip install is
    importlib-discoverable, so that helper would report a from-source run as
    non-dev. Only a genuine frozen build may self-install.
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def executable_path() -> Path:
    """Path of the running app binary.

    Nuitka 2.x standalone points ``sys.executable`` at a phantom ``python.exe``
    next to the binary (it emulates a venv layout for child interpreters); the
    real launcher path is ``sys.argv[0]``. Prefer argv[0] when it names a real
    file, falling back to ``sys.executable``. Confirmed in the field: the
    Windows helper relaunched ``C:\\Waves\\python.exe``, which does not exist.
    """
    try:
        cand = Path(sys.argv[0]).resolve()
        if cand.is_file():
            return cand
    except Exception:
        logger.debug("argv[0] did not resolve to a file", exc_info=True)
    return Path(sys.executable).resolve()

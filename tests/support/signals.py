"""The suite's recording double for a Qt signal.

Dependency-free on purpose: QML scenario child processes import the fakes
that use it, and importing tests/conftest.py there would replace the config
sandbox the scenario runner hands them.
"""

from __future__ import annotations


class RecordingSignal:
    """Stand-in for a Qt signal that records what was emitted.

    ``emit`` stores a single argument as itself and multiple arguments as a
    tuple, so a test can assert on ``sig.emits`` exactly what QML (or a connected
    slot) would have received. It has no ``connect``: the bound code paths under
    test only ever ``emit`` these, never connect to them.
    """

    def __init__(self) -> None:
        self.emits: list = []

    def emit(self, *args) -> None:
        self.emits.append(args[0] if len(args) == 1 else args)

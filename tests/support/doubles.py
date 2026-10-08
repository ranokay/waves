"""The suite's shared Qt doubles: a recording signal and an inline pool.

Dependency-free on purpose. QML scenario child processes import the fakes
modules that use these, and a fake that imported tests/conftest.py would run
it there and replace the config sandbox the scenario runner hands the child.
Test modules may keep importing the conftest names (`_Signal`, `_InlinePool`);
fakes modules import from here.
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


class InlinePool:
    """Stand-in for a ``QThreadPool`` that runs a dispatched ``Worker``
    synchronously on the calling thread, so worker dispatch is exercised without
    a real thread or event loop and the slot completes before ``start`` returns.
    """

    def start(self, worker, priority: int = 0) -> None:
        # Priority is accepted and ignored: QThreadPool takes one (the library
        # seed is dispatched raised, to jump a queue busy with downloads), and
        # running inline there is no queue for it to jump.
        worker.run()

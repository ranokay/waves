"""One breadcrumb trail per dump window across both logger trees.

A single dump handler shared by the waves tree and the root tree is what stops
a third-party error from writing the trail again inside the same window.
"""

from __future__ import annotations

import logging

from waves.desktop import diagnostics


class _Sink(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.NOTSET)
        self.records: list[str] = []

    def handle(self, record):
        self.records.append(record.getMessage())

    def emit(self, record):  # pragma: no cover - handle() is what the dumper calls
        self.records.append(record.getMessage())


def test_two_logger_trees_share_one_dump_limiter():
    crumbs = diagnostics._BreadcrumbHandler(capacity=5)
    crumbs.setFormatter(logging.Formatter("%(message)s"))
    for i in range(3):
        crumbs.emit(logging.LogRecord("waves.x", logging.INFO, "", 0, f"crumb {i}", None, None))
    sink = _Sink()
    dumper = diagnostics._CrumbDumpHandler(crumbs, sink)

    # The waves tree's error, then the root tree's a moment later. One handler
    # instance on both trees is what makes the second one hit the limiter.
    dumper.emit(logging.LogRecord("waves.download", logging.ERROR, "", 0, "boom", None, None))
    first = len(sink.records)
    dumper.emit(logging.LogRecord("urllib3", logging.ERROR, "", 0, "also boom", None, None))

    assert first > 0, "the first error must write the trail"
    assert len(sink.records) == first, "the trail was written twice inside one window"


def test_install_builds_a_single_dump_handler():
    """Structural: the handler is built once and added to both trees."""
    import inspect

    source = inspect.getsource(diagnostics.install)

    assert source.count("_CrumbDumpHandler(") == 1, "a dump handler per tree gives a limiter per tree"

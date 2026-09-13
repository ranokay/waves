"""Shared test machinery: repository paths, process runners and fake seams.

Anything two test domains need lives here. New shared machinery lands here
as its domain batch moves; the existing cross-module helpers migrate with
those batches. The package stays importable from any test depth (pytest
puts the tests root on ``sys.path``) and from scenario subprocesses (the QML
runner extends the child's ``PYTHONPATH``).
"""

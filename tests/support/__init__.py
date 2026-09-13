"""Shared test machinery: repository paths, process runners and fake seams.

Test modules never import another test module; anything two domains need
lives here. The package stays importable from any test depth (pytest puts
the tests root on ``sys.path``) and from scenario subprocesses (the QML
runner extends the child's ``PYTHONPATH``).
"""

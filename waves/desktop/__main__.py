import sys

if "--library-worker" in sys.argv[1:]:
    # The library scanner process (see waves.library.worker), decided before
    # the app's own imports: the scanner must never load Qt.
    from waves.library.worker import main as worker_main

    raise SystemExit(worker_main(sys.argv[1:]))

if sys.argv[1:2] == ["session"]:
    from waves.desktop.providers.session_control import main as session_main

    raise SystemExit(session_main(sys.argv[2:]))

from .app import waves_activate

raise SystemExit(waves_activate())
